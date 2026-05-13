"""Pydantic data models — single source of truth for all data shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Bounding box / detection
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """VLM-prompt contract: normalized 0–1 coords with a card_type label.

    Distinct from ``pdf_vlm_renderer.BoundingBox`` (pixel coords + confidence) —
    that type is used at the rendering boundary only. Convert via
    :func:`card_extractor.coords.norm_to_px`.

    Coordinates are clamped to ``[0, 1]`` since VLMs occasionally return
    values slightly out of range (e.g., 1.01, -0.005).
    """

    card_type: Literal["Front", "Back", "Unknown"] = "Unknown"
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 1.0
    y2: float = 1.0

    @field_validator("x1", "y1", "x2", "y2", mode="before")
    @classmethod
    def clamp_coordinate(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


class CardRegion(BaseModel):
    """Output of the detect_cards tool."""

    card_found: bool = False
    count: int = 0
    boxes: list[BoundingBox] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Card extraction
# ---------------------------------------------------------------------------


class InsuranceData(BaseModel):
    subscriber_name: str = "NONE"
    member_id: str = "NONE"
    group_number: str = "NONE"
    rx_group_number: str = "NONE"
    plan_type: str = "NONE"


class GovernmentData(BaseModel):
    name: str = "NONE"
    id_number: str = "NONE"
    expiration_date: str = "NONE"


class CardExtraction(BaseModel):
    """Structured output from extract_card_data — used with with_structured_output()."""

    card_type: Literal["INSURANCE", "GOVERNMENT"]
    insurance: InsuranceData = Field(default_factory=InsuranceData)
    government: GovernmentData = Field(default_factory=GovernmentData)
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Model self-assessed confidence in the extraction",
    )
    issuer_hint: str = Field(
        default="",
        description="Best guess at issuer name, e.g. 'UnitedHealthcare', 'Florida DMV'",
    )


class CardSideVerdict(BaseModel):
    """Output of the front/back verification step."""

    verdict: Literal["FRONT", "BACK", "NOT_BACK", "NOT_A_CARD"]


class AuditResult(BaseModel):
    """Output of the page audit step — how many cards does the VLM see?"""

    card_count: int = Field(ge=0, description="Number of distinct ID cards visible on the page")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    field: str
    issue: str
    severity: Literal["error", "warning"] = "error"


class ValidationResult(BaseModel):
    valid: bool = True
    issues: list[ValidationIssue] = Field(default_factory=list)
    confidence_adjustment: float = Field(
        default=0.0,
        description="Delta to apply to extraction confidence (negative = reduce)",
    )


# ---------------------------------------------------------------------------
# Human review queue
# ---------------------------------------------------------------------------


class ReviewItem(BaseModel):
    """An extraction flagged for human review."""

    id: str
    source_pdf: str
    page: int
    box_index: int = 0
    crop_path: str
    extraction: CardExtraction
    validation: ValidationResult = Field(default_factory=ValidationResult)
    wiki_context: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["pending", "approved", "corrected", "rejected"] = "pending"
    human_correction: Optional[CardExtraction] = None


# ---------------------------------------------------------------------------
# Wiki rules (YAML frontmatter schema)
# ---------------------------------------------------------------------------


class IssuerRules(BaseModel):
    """Machine-readable validation rules for an issuer wiki page.

    Lives in YAML frontmatter at the top of each issuer's markdown file.
    Separates human-readable observations (markdown body) from machine-critical
    rules (frontmatter). LLMs update both; Python only parses frontmatter.
    """

    issuer: str = ""
    card_type: Literal["INSURANCE", "GOVERNMENT"] = "INSURANCE"
    patterns: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    version: int = 1
    last_human_correction: str = ""

    def validate_patterns(self) -> None:
        """Compile each regex — raise re.error if any pattern is malformed.

        Called at write time to prevent silently-broken rules from landing in the wiki.
        """
        import re
        for field_name, pattern in self.patterns.items():
            re.compile(pattern)


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


class BatchProgress(BaseModel):
    """Checkpoint/resume state for batch processing."""

    total_pdfs: int = 0
    completed_pdfs: dict[str, list[int]] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    timestamp: float = 0.0


class RunManifest(BaseModel):
    """Experiment tracking — logged per batch run."""

    run_id: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    vlm_model: str = ""
    text_model: str = ""
    render_dpi: int = 300
    crop_pad_px: int = 10
    vlm_temperature: float = 0.1
    extraction_temperature: float = 0.0
    detection_confidence: float = 0.85
    review_confidence_threshold: float = 0.7
    max_retry_attempts: int = 1
    total_pdfs: int = 0
    total_cards_detected: int = 0
    total_extractions: int = 0
    total_flagged_for_review: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
