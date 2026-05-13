"""Agent core — AgentContext, tools, pipeline orchestration, verification loop.

Architecture adapted from the chorus-csd-analyzer agent harness pattern.
See: https://github.com/PatientVibes/agent-harness-chorus-csd-analyzer
Sequential pipeline with orchestrator and evaluator audit step.

Enhancements over v1:
- Page audit step (evaluator) catches missed cards
- Smart verification: skip for Front-labeled boxes, only verify Unknown
- Full-page fallback when detection finds no cards
- Image preprocessing (autocontrast) for degraded scans
- Orchestrator dispatches subagents for parallel page processing
- Pipeline trace: structured JSONL log of every decision and VLM call
- Conditional audit: only runs when detection/extraction counts look suspicious
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage
from llm_utils import (
    is_transient,
    load_checkpoint,
    retry_async,
    save_checkpoint,
)
from token_tracker import TokenTracker

from card_extractor.ai_client import (
    GatewayConfig,
    create_extraction_llm,
    create_vlm,
)
from card_extractor.models import (
    AuditResult,
    BatchProgress,
    BoundingBox,
    CardExtraction,
    CardRegion,
    CardSideVerdict,
    ValidationResult,
)
from card_extractor.prompts import (
    AUDIT_PROMPT,
    DETECTION_PROMPT,
    EXTRACTION_PROMPT,
    EXTRACTION_RETRY_PROMPT,
    EXTRACTION_WITH_CONTEXT_PROMPT,
    VERIFICATION_PROMPT,
)
from card_extractor.rendering import (
    crop_region,
    draw_debug_boxes,
    encode_image_base64,
    pdf_to_page_pngs,
    preprocess_for_vlm,
)
from card_extractor.review import ReviewQueue
from pipeline_trace import PipelineTrace
from card_extractor.validation import validate_extraction
from card_extractor.wiki import CardKnowledgeWiki

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent context (from chorus-agent agent.py:176-182)
# ---------------------------------------------------------------------------


@dataclass
class DurableContext:
    """Long-lived, request-independent state built once at service startup.

    Holds references that are safe to share across concurrent requests: the
    gateway config, the wiki/review queue handles, the base output directory,
    and tunable parameters. Request-scoped state (TokenTracker, PipelineTrace,
    per-run output subdir) is built from this via
    ``AgentContext.for_request(durable, run_id)``.
    """

    config: GatewayConfig
    wiki: CardKnowledgeWiki
    review_queue: ReviewQueue
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    render_dpi: int = 300
    crop_pad_px: int = 10
    detection_confidence: float = 0.85
    review_threshold: float = 0.7
    max_retry_attempts: int = 1
    max_concurrent: int = 5
    enable_audit: bool = True
    enable_preprocessing: bool = True

    @classmethod
    def from_env(cls) -> DurableContext:
        config = GatewayConfig.from_env()
        wiki_dir = Path(os.environ.get("WIKI_DIR", "./knowledge"))
        queue_dir = Path(os.environ.get("REVIEW_QUEUE_DIR", "./review_queue"))
        output_dir = Path(os.environ.get("OUTPUT_DIR", "./output"))

        return cls(
            config=config,
            wiki=CardKnowledgeWiki(wiki_dir),
            review_queue=ReviewQueue(queue_dir),
            output_dir=output_dir,
            render_dpi=int(os.environ.get("RENDER_DPI", "300")),
            crop_pad_px=int(os.environ.get("CROP_PAD_PX", "10")),
            detection_confidence=float(os.environ.get("DETECTION_CONFIDENCE", "0.85")),
            review_threshold=float(os.environ.get("REVIEW_CONFIDENCE_THRESHOLD", "0.7")),
            max_retry_attempts=int(os.environ.get("MAX_RETRY_ATTEMPTS", "1")),
            max_concurrent=int(os.environ.get("MAX_CONCURRENT", "5")),
            enable_audit=os.environ.get("ENABLE_AUDIT", "1") == "1",
            enable_preprocessing=os.environ.get("ENABLE_PREPROCESSING", "1") == "1",
        )


@dataclass
class AgentContext:
    """Request-scoped context for a single pipeline run.

    Durable fields (config, wiki, review_queue, tunables) are shared across
    requests. Mutable per-run fields — TokenTracker, PipelineTrace, and a
    per-run output_dir subdirectory — are fresh on each instance so that
    concurrent requests do not contaminate each other's tallies or artifacts.
    """

    config: GatewayConfig
    wiki: CardKnowledgeWiki
    review_queue: ReviewQueue
    tracker: TokenTracker = field(default_factory=TokenTracker)
    trace: Optional[PipelineTrace] = None
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    render_dpi: int = 300
    crop_pad_px: int = 10
    detection_confidence: float = 0.85
    review_threshold: float = 0.7
    max_retry_attempts: int = 1
    max_concurrent: int = 5
    enable_audit: bool = True
    enable_preprocessing: bool = True

    @classmethod
    def from_env(cls) -> AgentContext:
        """Build a full AgentContext from environment.

        Retained for scripts (run_batch, run_pass2, experiment) that do not
        use the FastAPI lifespan pattern.
        """
        durable = DurableContext.from_env()
        return cls(
            config=durable.config,
            wiki=durable.wiki,
            review_queue=durable.review_queue,
            output_dir=durable.output_dir,
            render_dpi=durable.render_dpi,
            crop_pad_px=durable.crop_pad_px,
            detection_confidence=durable.detection_confidence,
            review_threshold=durable.review_threshold,
            max_retry_attempts=durable.max_retry_attempts,
            max_concurrent=durable.max_concurrent,
            enable_audit=durable.enable_audit,
            enable_preprocessing=durable.enable_preprocessing,
        )

    @classmethod
    def for_request(cls, durable: DurableContext, run_id: str) -> AgentContext:
        """Build a fresh request-scoped AgentContext from a DurableContext.

        Creates a new TokenTracker and a new PipelineTrace writing to
        ``<durable.output_dir>/<run_id>/_trace.jsonl``. The request's
        ``output_dir`` is the per-run subdir so artifacts from concurrent
        requests cannot collide.
        """
        run_output_dir = durable.output_dir / run_id
        run_output_dir.mkdir(parents=True, exist_ok=True)
        trace = PipelineTrace(run_output_dir / "_trace.jsonl")
        return cls(
            config=durable.config,
            wiki=durable.wiki,
            review_queue=durable.review_queue,
            tracker=TokenTracker(),
            trace=trace,
            output_dir=run_output_dir,
            render_dpi=durable.render_dpi,
            crop_pad_px=durable.crop_pad_px,
            detection_confidence=durable.detection_confidence,
            review_threshold=durable.review_threshold,
            max_retry_attempts=durable.max_retry_attempts,
            max_concurrent=durable.max_concurrent,
            enable_audit=durable.enable_audit,
            enable_preprocessing=durable.enable_preprocessing,
        )


# ---------------------------------------------------------------------------
# VLM calls with structured output
# ---------------------------------------------------------------------------


def _build_image_message(image_path: Path, text: str) -> HumanMessage:
    """Build a HumanMessage with text + base64 image."""
    b64 = encode_image_base64(image_path)
    suffix = image_path.suffix.lstrip(".").lower()
    return HumanMessage(content=[
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:image/{suffix};base64,{b64}"}},
    ])


def _parse_structured_result(
    result, model_cls,
    tracker: Optional[TokenTracker],
    trace: Optional[PipelineTrace],
    source: str, model_name: str,
    latency_s: float = 0.0,
    result_summary: str = "",
):
    """Parse result from with_structured_output(include_raw=True) and track tokens + trace."""
    parsed = None
    input_tokens = 0
    output_tokens = 0

    if isinstance(result, dict) and "parsed" in result:
        parsed = result["parsed"]
        raw_msg = result.get("raw")
        if raw_msg:
            um = getattr(raw_msg, "usage_metadata", None)
            if um:
                input_tokens = um.get("input_tokens", 0)
                output_tokens = um.get("output_tokens", 0)
            if tracker:
                tracker.record_from_response(source, model_name, raw_msg)
    elif isinstance(result, model_cls):
        parsed = result
    elif isinstance(result, dict):
        parsed = model_cls(**result)

    if parsed is None:
        raise ValueError(f"Could not parse {model_cls.__name__} from result: {type(result)}")

    if not isinstance(parsed, model_cls):
        parsed = model_cls(**parsed) if isinstance(parsed, dict) else parsed

    # Record in trace
    if trace:
        trace.event(
            "vlm_call",
            source=source, model=model_name,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_s=round(latency_s, 2), result=result_summary,
        )

    return parsed


async def detect_cards(
    page_image: Path, ctx: AgentContext,
) -> CardRegion:
    """Detect card regions in a page image using VLM -> CardRegion."""
    vlm = create_vlm(ctx.config)
    structured_vlm = vlm.with_structured_output(CardRegion, include_raw=True)

    prompt_text = DETECTION_PROMPT.format(detection_confidence=ctx.detection_confidence)
    msg = _build_image_message(page_image, prompt_text)

    t0 = time.time()
    result = await retry_async(
        lambda: structured_vlm.ainvoke([msg]),
        max_retries=ctx.max_retry_attempts,
    )
    latency = time.time() - t0

    return _parse_structured_result(
        result, CardRegion, ctx.tracker, ctx.trace,
        "detect_cards", ctx.config.vlm_model,
        latency_s=latency, result_summary=f"page={page_image.name}",
    )


async def verify_card_side(
    crop_path: Path, ctx: AgentContext,
) -> CardSideVerdict:
    """Verify whether a crop is front/back/not a card -> CardSideVerdict."""
    vlm = create_vlm(ctx.config)
    structured_vlm = vlm.with_structured_output(CardSideVerdict, include_raw=True)

    msg = _build_image_message(crop_path, VERIFICATION_PROMPT)

    t0 = time.time()
    result = await retry_async(
        lambda: structured_vlm.ainvoke([msg]),
        max_retries=ctx.max_retry_attempts,
    )
    latency = time.time() - t0

    return _parse_structured_result(
        result, CardSideVerdict, ctx.tracker, ctx.trace,
        "verify_card_side", ctx.config.vlm_model,
        latency_s=latency, result_summary=f"crop={crop_path.name}",
    )


async def extract_card_data(
    crop_path: Path,
    ctx: AgentContext,
    wiki_context: Optional[str] = None,
) -> CardExtraction:
    """Extract structured data from a card crop -> CardExtraction."""
    llm = create_extraction_llm(ctx.config)
    structured_llm = llm.with_structured_output(CardExtraction, include_raw=True)

    if wiki_context:
        prompt_text = EXTRACTION_WITH_CONTEXT_PROMPT.format(wiki_context=wiki_context)
    else:
        prompt_text = EXTRACTION_PROMPT

    msg = _build_image_message(crop_path, prompt_text)

    t0 = time.time()
    result = await retry_async(
        lambda: structured_llm.ainvoke([msg]),
        max_retries=ctx.max_retry_attempts,
    )
    latency = time.time() - t0

    return _parse_structured_result(
        result, CardExtraction, ctx.tracker, ctx.trace,
        "extract_card_data", ctx.config.vlm_model,
        latency_s=latency, result_summary=f"crop={crop_path.name}",
    )


async def audit_page(
    page_image: Path, ctx: AgentContext,
) -> AuditResult:
    """Audit a page to count how many cards the VLM sees (evaluator step)."""
    vlm = create_vlm(ctx.config)
    structured_vlm = vlm.with_structured_output(AuditResult, include_raw=True)

    msg = _build_image_message(page_image, AUDIT_PROMPT)

    t0 = time.time()
    result = await retry_async(
        lambda: structured_vlm.ainvoke([msg]),
        max_retries=1,
    )
    latency = time.time() - t0

    return _parse_structured_result(
        result, AuditResult, ctx.tracker, ctx.trace,
        "audit_page", ctx.config.vlm_model,
        latency_s=latency, result_summary=f"page={page_image.name}",
    )


# ---------------------------------------------------------------------------
# Verification loop (from chorus-agent agent.py:475-522, 651-687)
# ---------------------------------------------------------------------------


def _verify_extraction(
    extraction: CardExtraction,
    wiki_hints: Optional[dict] = None,
    validation: Optional[ValidationResult] = None,
) -> list[str]:
    """Returns list of issue descriptions. Empty = passed."""
    issues: list[str] = []

    if extraction.card_type == "INSURANCE":
        if extraction.insurance.subscriber_name == "NONE" and extraction.insurance.member_id != "NONE":
            issues.append("subscriber_name is NONE but member_id is populated")
    elif extraction.card_type == "GOVERNMENT":
        if extraction.government.name == "NONE":
            issues.append("Government card with no name extracted")

    if validation is None:
        validation = validate_extraction(extraction, wiki_hints)
    for vi in validation.issues:
        if vi.severity == "error":
            issues.append(f"{vi.field}: {vi.issue}")

    return issues


async def _retry_extraction(
    crop_path: Path,
    original: CardExtraction,
    issues: list[str],
    ctx: AgentContext,
    wiki_context: Optional[str] = None,
) -> CardExtraction:
    """Re-extract with issue feedback -- max 1 retry (chorus-agent pattern)."""
    llm = create_extraction_llm(ctx.config)
    structured_llm = llm.with_structured_output(CardExtraction, include_raw=True)

    issue_text = "\n".join(f"- {i}" for i in issues)
    retry_prompt = EXTRACTION_RETRY_PROMPT.format(issues=issue_text)

    msg = _build_image_message(crop_path, retry_prompt)

    try:
        t0 = time.time()
        result = await retry_async(
            lambda: structured_llm.ainvoke([msg]),
            max_retries=1,
        )
        latency = time.time() - t0
        return _parse_structured_result(
            result, CardExtraction, ctx.tracker, ctx.trace,
            "extract_retry", ctx.config.vlm_model,
            latency_s=latency, result_summary=f"crop={crop_path.name}",
        )
    except Exception as e:
        logger.warning("Retry extraction failed: %s -- keeping original", e)
        return original


# ---------------------------------------------------------------------------
# Checkpoint / resume — uses llm_utils.save_checkpoint / load_checkpoint.
# Helpers used to live inline; extracted to `llm_utils` per the agent-toolbox
# extraction (2026-05-12). load_checkpoint returns {} for missing/None paths,
# so BatchProgress(**load_checkpoint(...)) yields a default BatchProgress() in
# the absent-checkpoint case.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Single card extraction pipeline (used by both normal and fallback paths)
# ---------------------------------------------------------------------------


async def _extract_single_card(
    crop_path: Path,
    ctx: AgentContext,
    source_pdf: str,
    page_num: int,
    crop_idx: int,
) -> Optional[CardExtraction]:
    """Extract data from a single card crop through the full pipeline."""
    # Wiki lookup (we don't know issuer yet, extract first)
    wiki_context = None
    wiki_hints: Optional[dict] = None

    extraction = await extract_card_data(crop_path, ctx, wiki_context=wiki_context)

    # Now that we have issuer_hint, look up wiki for structured hints only.
    # We only re-extract with wiki context when the wiki has explicit
    # validation rules (patterns or required_fields) — either from human
    # corrections or auto-promoted patterns. Observation text alone is
    # noise that burns tokens without improving accuracy.
    if extraction.issuer_hint:
        wiki_hints = ctx.wiki.get_extraction_hints(extraction.issuer_hint, extraction.card_type)

        has_validation_rules = bool(
            wiki_hints.get("patterns") or wiki_hints.get("required_fields")
        )
        if has_validation_rules:
            wiki_context = ctx.wiki.lookup(extraction.issuer_hint, extraction.card_type)
            if wiki_context:
                logger.info(
                    "Re-extracting with wiki rules for %s", extraction.issuer_hint,
                )
                extraction = await extract_card_data(
                    crop_path, ctx, wiki_context=wiki_context,
                )

    # Validate
    validation = validate_extraction(extraction, wiki_hints)

    # Verification loop (pass existing validation to avoid double-validation)
    issues = _verify_extraction(extraction, wiki_hints, validation=validation)
    if issues and ctx.max_retry_attempts > 0:
        logger.info("Verification issues on %s: %s -- retrying", crop_path.name, issues)
        extraction = await _retry_extraction(
            crop_path, extraction, issues, ctx, wiki_context,
        )
        validation = validate_extraction(extraction, wiki_hints)

    # Apply confidence adjustment
    adjusted_confidence = max(0.0, min(1.0,
        extraction.confidence + validation.confidence_adjustment,
    ))

    # Trace extraction result
    if ctx.trace:
        ctx.trace.event(
            "extraction",
            crop=crop_path.name, card_type=extraction.card_type,
            confidence=extraction.confidence, issuer_hint=extraction.issuer_hint,
            valid=validation.valid, issues=[i.issue for i in validation.issues],
        )

    # Flag for review if low confidence or invalid
    if not validation.valid or adjusted_confidence < ctx.review_threshold:
        ctx.review_queue.flag_for_review(
            source_pdf=source_pdf,
            page=page_num,
            box_index=crop_idx,
            crop_path=str(crop_path),
            extraction=extraction,
            validation=validation,
            wiki_context=wiki_context or "",
        )
        if ctx.trace:
            reason = "invalid" if not validation.valid else f"low confidence ({adjusted_confidence:.2f})"
            ctx.trace.event("review_flagged", crop=crop_path.name, reason=reason, confidence=adjusted_confidence)
        if not validation.valid:
            logger.info("Suppressed invalid extraction for %s", crop_path.name)
            return None

    # Save extraction JSON
    out_json = ctx.output_dir / f"{crop_path.stem}.json"
    out_json.write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8",
    )
    logger.info("Extracted -> %s", out_json.name)

    # Update wiki
    if extraction.issuer_hint:
        await _update_wiki_observation(extraction, ctx, source_pdf)
        if ctx.trace:
            ctx.trace.event("wiki_update", issuer=extraction.issuer_hint, card_type=extraction.card_type, source_pdf=source_pdf)

    return extraction


# ---------------------------------------------------------------------------
# Full-page fallback: when detection finds no cards, try the whole page
# ---------------------------------------------------------------------------


async def _full_page_fallback(
    page_png: Path,
    ctx: AgentContext,
    source_pdf: str,
    page_num: int,
) -> list[CardExtraction]:
    """Try extracting from the full page when detection finds no card regions."""
    logger.info("Full-page fallback on %s", page_png.name)

    # Preprocess the full page
    if ctx.enable_preprocessing:
        processed = ctx.output_dir / f"{page_png.stem}_preprocessed.png"
        page_to_use = preprocess_for_vlm(page_png, processed)
    else:
        page_to_use = page_png

    try:
        extraction = await _extract_single_card(
            page_to_use, ctx, source_pdf, page_num, crop_idx=0,
        )
        if extraction:
            return [extraction]
    except Exception as e:
        logger.warning("Full-page fallback failed on %s: %s", page_png.name, e)

    return []


# ---------------------------------------------------------------------------
# Per-page pipeline with audit step
# ---------------------------------------------------------------------------


async def process_page(
    page_png: Path,
    ctx: AgentContext,
    source_pdf: str = "",
    page_num: int = 1,
) -> list[CardExtraction]:
    """Process a single page image through the full pipeline with audit."""
    base_name = page_png.stem
    results: list[CardExtraction] = []

    # Optional: preprocess page for better detection on degraded scans
    if ctx.enable_preprocessing:
        preprocessed_path = ctx.output_dir / f"{base_name}_enhanced.png"
        detection_image = preprocess_for_vlm(page_png, preprocessed_path)
    else:
        detection_image = page_png

    # Step 1: Detect cards
    try:
        region = await detect_cards(detection_image, ctx)
    except Exception as e:
        logger.error("Detection failed on %s: %s", page_png.name, e)
        if not is_transient(e):
            raise
        return results

    # Trace: detection result
    front_count = sum(1 for b in region.boxes if b.card_type == "Front") if region.boxes else 0
    back_count = sum(1 for b in region.boxes if b.card_type == "Back") if region.boxes else 0
    unknown_count = sum(1 for b in region.boxes if b.card_type == "Unknown") if region.boxes else 0
    if ctx.trace:
        ctx.trace.event(
            "detection",
            page=page_png.name, card_found=region.card_found,
            boxes=len(region.boxes) if region.boxes else 0,
            front=front_count, back=back_count, unknown=unknown_count,
        )

    # Step 1b: Full-page fallback if no cards detected
    if not region.card_found or not region.boxes:
        logger.info("No cards detected on %s -- trying full-page fallback", page_png.name)
        if ctx.trace:
            ctx.trace.event("fallback", page=page_png.name, reason="no cards detected")
        return await _full_page_fallback(page_png, ctx, source_pdf, page_num)

    # Save debug visualization
    try:
        outlined_path = ctx.output_dir / f"{base_name}_outlined.png"
        draw_debug_boxes(page_png, region.boxes, outlined_path)
    except Exception as e:
        logger.warning("Failed to draw debug boxes: %s", e)

    # Step 2: Smart crop -- include Front AND Unknown boxes (not just Front)
    candidate_boxes = [b for b in region.boxes if b.card_type in ("Front", "Unknown")]
    if not candidate_boxes:
        logger.info("No Front/Unknown boxes on %s -- trying full-page fallback", page_png.name)
        return await _full_page_fallback(page_png, ctx, source_pdf, page_num)

    crops: list[tuple[Path, BoundingBox]] = []
    for idx, box in enumerate(candidate_boxes, start=1):
        out_path = ctx.output_dir / f"{base_name}_boxed_{idx}.png"
        result = crop_region(page_png, box, out_path, pad_px=ctx.crop_pad_px)
        if result is not None:
            crops.append((result, box))

    logger.info("Cropped %d candidate boxes from %s", len(crops), page_png.name)

    # Step 3-6: Per-crop extraction pipeline
    for crop_idx, (crop_path, box) in enumerate(crops):
        try:
            # Step 3: Smart verification
            # Skip VLM verify for Front-labeled boxes (saves ~9% tokens)
            # Only verify Unknown-labeled boxes
            if box.card_type == "Unknown":
                verdict = await verify_card_side(crop_path, ctx)
                if verdict.verdict in ("BACK", "NOT_A_CARD"):
                    logger.info("Vetoed %s (verdict=%s)", crop_path.name, verdict.verdict)
                    if ctx.trace:
                        ctx.trace.event("verification", crop=crop_path.name, box_label=box.card_type, action="vetoed", verdict=verdict.verdict)
                    continue
                if ctx.trace:
                    ctx.trace.event("verification", crop=crop_path.name, box_label=box.card_type, action="verified", verdict=verdict.verdict)
            else:
                # Front-labeled: skip VLM call entirely
                if ctx.trace:
                    ctx.trace.event("verification", crop=crop_path.name, box_label=box.card_type, action="skipped", verdict="Front")

            # Steps 4-6: Extract, validate, wiki update
            extraction = await _extract_single_card(
                crop_path, ctx, source_pdf, page_num, crop_idx,
            )
            if extraction:
                results.append(extraction)

        except Exception as e:
            logger.error("Extraction failed on %s: %s", crop_path.name, e)
            if not is_transient(e):
                raise
            continue

    # Step 7: Conditional audit -- only when extraction count looks suspicious
    # Skip audit if all detected Front/Unknown boxes produced extractions (nothing to catch)
    expected_extractions = len(crops)
    actual_extractions = len(results)

    should_audit = (
        ctx.enable_audit
        and actual_extractions < expected_extractions  # some crops failed extraction
    )

    if should_audit:
        try:
            audit = await audit_page(page_png, ctx)
            cards_on_page = audit.card_count
            mismatch = cards_on_page > actual_extractions + back_count

            if ctx.trace:
                ctx.trace.event(
                    "audit",
                    page=page_png.name, vlm_sees=cards_on_page,
                    extracted=actual_extractions, backs=back_count,
                    mismatch=mismatch,
                )

            if mismatch:
                logger.warning(
                    "AUDIT MISMATCH on %s: VLM sees %d cards, extracted %d (+ %d backs). "
                    "Potential missed cards.",
                    page_png.name, cards_on_page, actual_extractions, back_count,
                )
                # Try full-page fallback for the missing cards
                fallback = await _full_page_fallback(page_png, ctx, source_pdf, page_num)
                results.extend(fallback)
        except Exception as e:
            logger.warning("Audit failed on %s: %s (non-fatal)", page_png.name, e)
    elif ctx.trace:
        ctx.trace.event(
            "audit_skipped",
            page=page_png.name,
            reason=f"all {expected_extractions} crops extracted successfully" if actual_extractions == expected_extractions
            else "audit disabled",
        )

    return results


def _mask_value(value: str) -> str:
    """Mask PII by showing only format pattern, not actual value.

    Replaces each character class independently to avoid order-of-replacement
    issues (e.g., digits→N then N→A).
    """
    result = []
    for ch in value:
        if ch.isdigit():
            result.append("#")
        elif ch.isupper():
            result.append("A")
        elif ch.islower():
            result.append("a")
        else:
            result.append(ch)  # keep separators, spaces, punctuation
    return "".join(result)


async def _update_wiki_observation(
    extraction: CardExtraction,
    ctx: AgentContext,
    source_pdf: str,
) -> None:
    """Write observations about this extraction to the wiki."""
    if extraction.card_type == "INSURANCE":
        ins = extraction.insurance
        parts = []
        if ins.member_id != "NONE":
            parts.append(f"- member_id pattern: {_mask_value(ins.member_id)}")
        if ins.group_number != "NONE":
            parts.append(f"- group_number pattern: {_mask_value(ins.group_number)}")
        if ins.rx_group_number != "NONE":
            parts.append(f"- rx_group_number pattern: {_mask_value(ins.rx_group_number)}")
        if ins.plan_type != "NONE":
            parts.append(f"- plan_type: {ins.plan_type}")
        observation = "\n".join(parts) if parts else "- Extraction completed, no notable patterns"
    else:
        gov = extraction.government
        parts = []
        if gov.id_number != "NONE":
            parts.append(f"- id_number pattern: {_mask_value(gov.id_number)}")
        if gov.expiration_date != "NONE":
            parts.append(f"- expiration_date pattern: {_mask_value(gov.expiration_date)}")
        observation = "\n".join(parts) if parts else "- Extraction completed, no notable patterns"

    try:
        await ctx.wiki.write_observation(
            issuer=extraction.issuer_hint,
            card_type=extraction.card_type,
            observation=observation,
            source_pdf=source_pdf,
            confidence=extraction.confidence,
        )
    except Exception as e:
        logger.warning("Failed to update wiki: %s", e)


# ---------------------------------------------------------------------------
# Per-PDF pipeline
# ---------------------------------------------------------------------------


async def process_pdf(
    pdf_path: Path,
    ctx: AgentContext,
) -> list[CardExtraction]:
    """Process all pages of a PDF through the pipeline."""
    logger.info("=== PDF: %s ===", pdf_path.name)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Render pages
    try:
        page_pngs = pdf_to_page_pngs(pdf_path, ctx.output_dir, dpi=ctx.render_dpi)
        logger.info("Rendered %d pages to PNG", len(page_pngs))
    except Exception as e:
        logger.error("PDF render failed on %s: %s", pdf_path.name, e)
        if ctx.trace:
            ctx.trace.event("error", source="render", page=pdf_path.name, message=str(e))
        return []

    if ctx.trace:
        ctx.trace.event("pdf_start", pdf=pdf_path.name, pages=len(page_pngs))

    all_extractions: list[CardExtraction] = []
    for page_num, page_png in enumerate(page_pngs, start=1):
        if ctx.trace:
            ctx.trace.event("page_start", pdf=pdf_path.name, page=page_num)
        extractions = await process_page(
            page_png, ctx, source_pdf=pdf_path.name, page_num=page_num,
        )
        all_extractions.extend(extractions)

    if ctx.trace:
        ctx.trace.event("pdf_end", pdf=pdf_path.name, extractions=len(all_extractions), time_s=round(time.time() - t0, 2))

    return all_extractions


# ---------------------------------------------------------------------------
# Orchestrator: parallel PDF processing with subagent pattern
# (from chorus-agent agent.py:948-976)
# ---------------------------------------------------------------------------


async def process_batch(
    pdf_paths: list[Path],
    ctx: AgentContext,
    progress_path: Optional[Path] = None,
) -> BatchProgress:
    """Orchestrator — process a batch of PDFs with concurrency control.

    Each PDF is a "subagent" task dispatched with semaphore-controlled
    concurrency. Failed PDFs are isolated and don't block the batch.
    Progress is checkpointed after each completion.
    """
    progress = BatchProgress(**load_checkpoint(progress_path))
    progress.total_pdfs = len(pdf_paths)

    pending = [p for p in pdf_paths if p.name not in progress.completed_pdfs]
    if not pending:
        logger.info("All PDFs already processed (checkpoint)")
        return progress

    logger.info(
        "Orchestrator dispatching %d PDFs (%d already done, concurrency=%d)",
        len(pending), len(pdf_paths) - len(pending), ctx.max_concurrent,
    )

    sem = asyncio.Semaphore(ctx.max_concurrent)

    async def _subagent(pdf_path: Path) -> tuple[str, list[CardExtraction]]:
        """Subagent: process one PDF with semaphore control and isolation."""
        async with sem:
            logger.info("[subagent] Starting %s", pdf_path.name)
            return pdf_path.name, await process_pdf(pdf_path, ctx)

    tasks = [_subagent(p) for p in pending]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(batch_results):
        pdf_name = pending[i].name
        if isinstance(result, Exception):
            logger.error("Subagent error on %s: %s", pdf_name, result)
            progress.errors[pdf_name] = str(result)
        else:
            name, extractions = result
            progress.completed_pdfs[name] = [
                idx for idx in range(len(extractions))
            ]

        progress.timestamp = time.time()
        save_checkpoint(progress_path, progress.model_dump())

    logger.info(
        "Orchestrator complete: %d/%d PDFs, %d errors",
        len(progress.completed_pdfs), progress.total_pdfs, len(progress.errors),
    )
    return progress
