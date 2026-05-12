"""Human review queue — flag, grade, and compile corrections back into the wiki."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from card_extractor.models import CardExtraction, ReviewItem, ValidationResult
from card_extractor.wiki import CardKnowledgeWiki

logger = logging.getLogger(__name__)


class ReviewQueue:
    """File-based review queue for low-confidence extractions."""

    def __init__(self, queue_dir: Path):
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def _item_path(self, item_id: str) -> Path:
        try:
            uuid.UUID(item_id)
        except ValueError:
            raise ValueError(f"Invalid review item ID: {item_id}")
        return self.queue_dir / f"{item_id}.json"

    def flag_for_review(
        self,
        source_pdf: str,
        page: int,
        crop_path: str,
        extraction: CardExtraction,
        validation: ValidationResult,
        wiki_context: str = "",
        box_index: int = 0,
    ) -> ReviewItem:
        """Create a review item and write it to the queue."""
        item = ReviewItem(
            id=str(uuid.uuid4()),
            source_pdf=source_pdf,
            page=page,
            box_index=box_index,
            crop_path=crop_path,
            extraction=extraction,
            validation=validation,
            wiki_context=wiki_context,
            created_at=datetime.now(timezone.utc),
        )
        self._item_path(item.id).write_text(
            item.model_dump_json(indent=2), encoding="utf-8",
        )
        return item

    def list_pending(self) -> list[ReviewItem]:
        """List all pending review items."""
        items: list[ReviewItem] = []
        for path in self.queue_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                item = ReviewItem(**data)
                if item.status == "pending":
                    items.append(item)
            except Exception as e:
                logger.warning("Skipping corrupt review item %s: %s", path.name, e)
                continue
        return sorted(items, key=lambda i: i.created_at)

    def list_all(self) -> list[ReviewItem]:
        """List all review items regardless of status."""
        items: list[ReviewItem] = []
        for path in self.queue_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(ReviewItem(**data))
            except Exception as e:
                logger.warning("Skipping corrupt review item %s: %s", path.name, e)
                continue
        return sorted(items, key=lambda i: i.created_at)

    def get(self, item_id: str) -> Optional[ReviewItem]:
        """Get a specific review item by ID."""
        path = self._item_path(item_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReviewItem(**data)

    def submit_review(
        self,
        item_id: str,
        status: str,
        correction: Optional[CardExtraction] = None,
    ) -> Optional[ReviewItem]:
        """Submit a human review decision."""
        item = self.get(item_id)
        if item is None:
            return None

        item.status = status  # type: ignore[assignment]
        item.human_correction = correction

        self._item_path(item_id).write_text(
            item.model_dump_json(indent=2), encoding="utf-8",
        )
        return item

    async def compile_reviewed_to_wiki(self, wiki: CardKnowledgeWiki) -> int:
        """Compile all corrected reviews into wiki pages. Returns count compiled."""
        compiled = 0
        for path in self.queue_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                item = ReviewItem(**data)
            except Exception:
                continue

            if item.status != "corrected" or item.human_correction is None:
                continue

            issuer = item.extraction.issuer_hint or "unknown"
            card_type = item.extraction.card_type

            # Build diff text
            orig = item.extraction
            corr = item.human_correction
            diffs: list[str] = []

            if card_type == "INSURANCE":
                for field in ("subscriber_name", "member_id", "group_number", "rx_group_number", "plan_type"):
                    ov = getattr(orig.insurance, field)
                    cv = getattr(corr.insurance, field)
                    if ov != cv:
                        diffs.append(f"  {field}: '{ov}' → '{cv}'")
            else:
                for field in ("name", "id_number", "expiration_date"):
                    ov = getattr(orig.government, field)
                    cv = getattr(corr.government, field)
                    if ov != cv:
                        diffs.append(f"  {field}: '{ov}' → '{cv}'")

            if diffs:
                await wiki.compile_correction(
                    issuer=issuer,
                    card_type=card_type,
                    original_text="\n".join(diffs),
                    correction_text="See field-level diffs above",
                    source_pdf=item.source_pdf,
                )
                compiled += 1

                # Mark as compiled so we don't re-process
                item.status = "approved"  # type: ignore[assignment]
                path.write_text(item.model_dump_json(indent=2), encoding="utf-8")

        return compiled
