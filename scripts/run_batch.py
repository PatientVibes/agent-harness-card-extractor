"""CLI batch runner — process a directory of PDFs with experiment tracking."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from card_extractor.agent import AgentContext, process_batch
from card_extractor.models import RunManifest
from pipeline_trace import PipelineTrace


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main(args: argparse.Namespace) -> int:
    ctx = AgentContext.from_env()

    # Create trace after output_dir is set
    ctx.output_dir = Path(args.output)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    ctx.trace = PipelineTrace(ctx.output_dir / "_trace.jsonl")

    if not ctx.config.available:
        logger.error("AI_GATEWAY_KEY not set")
        return 1

    input_dir = Path(args.input)
    if not input_dir.exists():
        logger.error("Input directory not found: %s", input_dir)
        return 1

    ctx.output_dir = Path(args.output)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDFs found in %s", input_dir)
        return 0

    logger.info("Found %d PDFs in %s", len(pdfs), input_dir)

    # Create run manifest for experiment tracking
    manifest = RunManifest(
        run_id=str(uuid.uuid4())[:8],
        started_at=datetime.now(timezone.utc),
        vlm_model=ctx.config.vlm_model,
        text_model=ctx.config.text_model,
        render_dpi=ctx.render_dpi,
        crop_pad_px=ctx.crop_pad_px,
        vlm_temperature=ctx.config.vlm_temperature,
        extraction_temperature=ctx.config.extraction_temperature,
        detection_confidence=ctx.detection_confidence,
        review_confidence_threshold=ctx.review_threshold,
        max_retry_attempts=ctx.max_retry_attempts,
        total_pdfs=len(pdfs),
    )

    progress_path = ctx.output_dir / "_progress.json"
    progress = await process_batch(pdfs, ctx, progress_path=progress_path)

    # Update manifest with results
    manifest.total_extractions = sum(len(v) for v in progress.completed_pdfs.values())
    manifest.total_tokens_input = ctx.tracker.total_input
    manifest.total_tokens_output = ctx.tracker.total_output

    # Count flagged items
    pending_reviews = ctx.review_queue.list_pending()
    manifest.total_flagged_for_review = len(pending_reviews)

    # Save manifest
    manifest_path = ctx.output_dir / "run_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Run manifest saved to %s", manifest_path)

    # Summary
    logger.info("=" * 60)
    logger.info("Run %s complete", manifest.run_id)
    logger.info("PDFs processed: %d/%d", len(progress.completed_pdfs), manifest.total_pdfs)
    logger.info("Errors: %d", len(progress.errors))
    logger.info("Extractions: %d", manifest.total_extractions)
    logger.info("Flagged for review: %d", manifest.total_flagged_for_review)
    logger.info("Tokens: %d in / %d out", manifest.total_tokens_input, manifest.total_tokens_output)
    logger.info("Token summary: %s", json.dumps(ctx.tracker.summary(), indent=2))

    return 0


def cli():
    parser = argparse.ArgumentParser(description="Card Extractor — batch PDF processor")
    parser.add_argument("--input", required=True, help="Directory containing PDF files")
    parser.add_argument("--output", default="./output", help="Output directory (default: ./output)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))


if __name__ == "__main__":
    cli()
