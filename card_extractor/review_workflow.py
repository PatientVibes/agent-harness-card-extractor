"""Harness orchestration on top of the review_queue tool's primitives.

``review_queue.ReviewQueue`` exposes the file-backed primitives (flag, list,
read, mark-reviewed). This module composes them into the harness-shaped
surface that the FastAPI app expects: id-prefix lookup, list-pending +
list-reviewed, and the compile-reviewed-to-wiki bridge that promotes human
corrections to the knowledge wiki.

This is harness code, NOT a thin adapter shim — ``compile_reviewed_to_wiki``
couples ``ReviewQueue`` + ``KnowledgeWiki`` in a domain-specific way
(per-issuer iteration, diffing the original vs corrected ``CardExtraction``
and constructing the frontmatter patch from the diff).

Status model
------------
The previous harness used a four-state field on each item:
``pending`` / ``approved`` / ``corrected`` / ``rejected``. The new tool only
distinguishes ``pending/`` from ``reviewed/`` (directory placement) plus
optional ``corrected`` extraction. To preserve the semantics the FastAPI
``/review/{item_id}`` route exposed, the disposition (``approved`` |
``corrected`` | ``rejected``) is recorded in the ``extras`` dict at
submit-review time and used by ``compile_reviewed_to_wiki`` to filter.

Concurrent-write safety
-----------------------
``KnowledgeWiki.promote_human_correction`` is synchronous and does NOT
acquire the wiki's internal asyncio lock. If a concurrent agent loop is
running ``write_observation``, we could interleave a frontmatter
read/modify/write cycle and lose updates. ``compile_reviewed_to_wiki``
holds ``wiki._lock`` around each promote call to serialize against the
wiki's async writers. Reaching into ``_lock`` is fragile (it is a private
attribute) but it is the cleanest fix available given the tool's API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from knowledge_wiki import KnowledgeWiki
from review_queue import ReviewItem, ReviewQueue

from card_extractor.models import CardExtraction


class ReviewWorkflow:
    """Harness-side wrapper over the review_queue tool's ReviewQueue.

    Exposes the surface the FastAPI app needs: id-prefix lookup, list pending
    + reviewed, submit-review, and compile-reviewed-to-wiki. Each instance
    owns one ``ReviewQueue`` rooted at ``root_dir``.
    """

    def __init__(self, root_dir: Path) -> None:
        self._queue = ReviewQueue(root_dir)
        self.root_dir = root_dir
        self.pending_dir = self._queue.pending_dir
        self.reviewed_dir = self._queue.reviewed_dir

    # ------------------------------------------------------------------
    # Flagging
    # ------------------------------------------------------------------

    def flag_for_review(
        self,
        source_pdf: str,
        page: int,
        crop_path: str,
        extraction: CardExtraction,
        validation,  # ValidationResult (Pydantic) or dict
        wiki_context: str = "",
        box_index: int = 0,
    ) -> Path:
        """Flag a low-confidence extraction. Returns the pending file path.

        Matches the old harness signature so the agent's flag-call site
        keeps working unchanged. Page/crop_path/box_index/wiki_context flow
        into the tool's ``extras`` dict so the FastAPI route handler can
        surface them to reviewers.
        """
        validation_dict = (
            validation.model_dump() if hasattr(validation, "model_dump") else (validation or {})
        )
        return self._queue.flag_for_review(
            source_ref=source_pdf,
            extraction=extraction,
            validation=validation_dict,
            context=wiki_context,
            page=page,
            box_index=box_index,
            crop_path=crop_path,
            status="pending",
        )

    # ------------------------------------------------------------------
    # Listing / lookup
    # ------------------------------------------------------------------

    def list_pending(self) -> list[ReviewItem]:
        """Return all pending items as ReviewItem objects (oldest first)."""
        return [self._queue.read_pending(p) for p in self._queue.list_pending()]

    def list_reviewed(self) -> list[ReviewItem]:
        """Return all reviewed items as ReviewItem objects (oldest first)."""
        if not self.reviewed_dir.exists():
            return []
        return [
            ReviewItem.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self.reviewed_dir.glob("*.json"))
        ]

    def list_all(self) -> list[ReviewItem]:
        """Return pending + reviewed items (pending first, both oldest-first)."""
        return self.list_pending() + self.list_reviewed()

    @staticmethod
    def _id_prefix(path: Path) -> str:
        """Extract the timestamp-prefix id from a queue filename."""
        return path.stem.split("_")[0]

    def _find_by_id(self, item_id: str) -> Optional[Path]:
        for candidate_dir in (self.pending_dir, self.reviewed_dir):
            if not candidate_dir.exists():
                continue
            matches = list(candidate_dir.glob(f"{item_id}_*.json"))
            if matches:
                return matches[0]
        return None

    def get(self, item_id: str) -> Optional[ReviewItem]:
        """Look up a single item by id-prefix across pending and reviewed."""
        path = self._find_by_id(item_id)
        if path is None:
            return None
        return ReviewItem.model_validate_json(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Review submission
    # ------------------------------------------------------------------

    def submit_review(
        self,
        item_id: str,
        status: str = "approved",
        correction: Optional[CardExtraction] = None,
    ) -> Optional[ReviewItem]:
        """Mark a pending item reviewed, recording the disposition in extras.

        ``status`` must be one of ``approved`` / ``corrected`` / ``rejected``
        (the legacy harness vocabulary, preserved for the existing FastAPI
        contract). Only ``corrected`` items have their stored extraction
        replaced with ``correction``; only ``corrected`` items are picked up
        by ``compile_reviewed_to_wiki``.

        Returns the persisted ``ReviewItem`` or ``None`` if no pending item
        matches ``item_id``.
        """
        matches = list(self.pending_dir.glob(f"{item_id}_*.json"))
        if not matches:
            return None
        pending_path = matches[0]

        # Read the pending item so we can update extras with the disposition
        # before mark_reviewed moves the file. For ``corrected`` submissions,
        # stash the pre-correction extraction in extras so the compile step
        # can diff it against the corrected payload.
        item = self._queue.read_pending(pending_path)
        new_extras = {**item.extras, "status": status}
        if status == "corrected" and correction is not None:
            new_extras["original_extraction"] = item.extraction
        item.extras = new_extras
        pending_path.write_text(item.model_dump_json(indent=2), encoding="utf-8")

        corrected_arg = correction if status == "corrected" else None
        return self._queue.mark_reviewed(pending_path, corrected=corrected_arg)

    # ------------------------------------------------------------------
    # Compile reviewed corrections into the wiki
    # ------------------------------------------------------------------

    async def compile_reviewed_to_wiki(self, wiki: KnowledgeWiki) -> int:
        """Promote ``corrected`` reviewed items to the wiki. Returns count promoted.

        For each reviewed item with ``extras["status"] == "corrected"``, diff
        the original extraction against the stored (corrected) extraction
        and write the changed fields into the issuer's wiki frontmatter via
        ``wiki.promote_human_correction``. Items are marked compiled (status
        flipped to ``approved`` in extras) so they are not re-processed.

        See module docstring for the rationale behind holding ``wiki._lock``.
        """
        compiled = 0
        for path in sorted(self.reviewed_dir.glob("*.json")):
            try:
                item = ReviewItem.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if item.extras.get("status") != "corrected":
                continue

            # ``item.extraction`` here is the post-correction snapshot (the
            # tool replaced it at mark_reviewed time). The pre-correction
            # snapshot is recorded in ``extras["original_extraction"]`` if
            # the caller stashed it; otherwise we cannot build a diff and
            # treat the whole corrected payload as the patch.
            try:
                corrected = CardExtraction.model_validate(item.extraction)
            except Exception:
                continue

            original_dict = item.extras.get("original_extraction")
            original = (
                CardExtraction.model_validate(original_dict) if original_dict else None
            )

            diffs = _diff_extraction_fields(original, corrected)

            issuer = corrected.issuer_hint or "unknown"
            sub_kind = corrected.card_type
            patch = {
                "last_correction_diff": "\n".join(diffs) if diffs else "(full replacement)",
                "last_correction_source": item.source_ref,
            }

            # The wiki's promote_human_correction is sync and does not hold
            # its own lock — serialize against concurrent write_observation
            # callers by holding the wiki's private async lock here.
            async with wiki._lock:  # noqa: SLF001 — see module docstring
                wiki.promote_human_correction(
                    entity_key=issuer,
                    sub_kind=sub_kind,
                    frontmatter_patch=patch,
                )
            compiled += 1

            # Mark compiled so we don't re-process on the next call.
            item.extras = {**item.extras, "status": "approved"}
            path.write_text(item.model_dump_json(indent=2), encoding="utf-8")

        return compiled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _diff_extraction_fields(
    original: Optional[CardExtraction],
    corrected: CardExtraction,
) -> list[str]:
    """Build a per-field diff string list from original vs corrected.

    Returns ``[]`` when ``original`` is None (caller treats this as a full
    replacement) or when no fields changed.
    """
    if original is None:
        return []

    diffs: list[str] = []
    if corrected.card_type == "INSURANCE":
        fields = ("subscriber_name", "member_id", "group_number", "rx_group_number", "plan_type")
        section_orig = original.insurance
        section_corr = corrected.insurance
    else:
        fields = ("name", "id_number", "expiration_date")
        section_orig = original.government
        section_corr = corrected.government

    for field in fields:
        ov = getattr(section_orig, field)
        cv = getattr(section_corr, field)
        if ov != cv:
            diffs.append(f"  {field}: '{ov}' -> '{cv}'")
    return diffs
