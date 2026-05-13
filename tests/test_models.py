"""Tests for Pydantic data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from card_extractor.models import (
    BatchProgress,
    BoundingBox,
    CardExtraction,
    CardRegion,
    GovernmentData,
    InsuranceData,
    RunManifest,
    ValidationIssue,
    ValidationResult,
)


class TestBoundingBox:
    def test_area_calculation(self):
        box = BoundingBox(card_type="Front", x1=0.0, y1=0.0, x2=0.5, y2=0.5)
        assert box.area == pytest.approx(0.25)

    def test_zero_area(self):
        box = BoundingBox(card_type="Front", x1=0.5, y1=0.5, x2=0.5, y2=0.5)
        assert box.area == 0.0

    def test_clamped_coordinates(self):
        """Out-of-range coords are clamped to [0, 1], not rejected."""
        box = BoundingBox(card_type="Front", x1=-0.1, y1=0.0, x2=0.5, y2=0.5)
        assert box.x1 == 0.0

        box2 = BoundingBox(card_type="Front", x1=0.0, y1=0.0, x2=1.1, y2=0.5)
        assert box2.x2 == 1.0

    def test_valid_card_types(self):
        for ct in ("Front", "Back", "Unknown"):
            box = BoundingBox(card_type=ct, x1=0.0, y1=0.0, x2=1.0, y2=1.0)
            assert box.card_type == ct


class TestCardRegion:
    def test_empty_region(self):
        region = CardRegion()
        assert region.card_found is False
        assert region.count == 0
        assert region.boxes == []

    def test_with_boxes(self, sample_card_region):
        assert sample_card_region.card_found is True
        assert sample_card_region.count == 2


class TestCardExtraction:
    def test_defaults(self):
        ext = CardExtraction(card_type="INSURANCE")
        assert ext.insurance.subscriber_name == "NONE"
        assert ext.government.name == "NONE"
        assert ext.confidence == 0.0
        assert ext.issuer_hint == ""

    def test_insurance(self, sample_insurance_extraction):
        ext = sample_insurance_extraction
        assert ext.card_type == "INSURANCE"
        assert ext.insurance.subscriber_name == "JOHN SMITH"
        assert ext.insurance.member_id == "302307904"

    def test_government(self, sample_government_extraction):
        ext = sample_government_extraction
        assert ext.card_type == "GOVERNMENT"
        assert ext.government.name == "JANE DOE"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            CardExtraction(card_type="INSURANCE", confidence=1.5)
        with pytest.raises(ValidationError):
            CardExtraction(card_type="INSURANCE", confidence=-0.1)

    def test_invalid_card_type(self):
        with pytest.raises(ValidationError):
            CardExtraction(card_type="OTHER")

    def test_serialization_roundtrip(self, sample_insurance_extraction):
        data = sample_insurance_extraction.model_dump()
        restored = CardExtraction(**data)
        assert restored == sample_insurance_extraction


class TestValidationResult:
    def test_valid_default(self):
        result = ValidationResult()
        assert result.valid is True
        assert result.issues == []

    def test_with_issues(self):
        result = ValidationResult(
            valid=False,
            issues=[ValidationIssue(field="member_id", issue="placeholder", severity="error")],
        )
        assert result.valid is False
        assert len(result.issues) == 1


class TestBatchProgress:
    def test_defaults(self):
        bp = BatchProgress()
        assert bp.total_pdfs == 0
        assert bp.completed_pdfs == {}
        assert bp.errors == {}


class TestRunManifest:
    def test_defaults(self):
        m = RunManifest()
        assert m.render_dpi == 300
        assert m.vlm_model == ""
        assert m.total_cards_detected == 0


