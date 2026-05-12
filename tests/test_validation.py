"""Tests for validation module — hallucination filters."""

from __future__ import annotations

import pytest

from card_extractor.models import CardExtraction, GovernmentData, InsuranceData
from card_extractor.validation import validate_extraction


class TestPlaceholderDetection:
    def test_placeholder_member_id(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="1234567890"),
        )
        result = validate_extraction(ext)
        assert not result.valid
        assert any("placeholder" in i.issue.lower() for i in result.issues)

    def test_sequential_member_id(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="123456789"),
        )
        result = validate_extraction(ext)
        assert not result.valid
        assert any("sequential" in i.issue.lower() for i in result.issues)

    def test_all_same_digit(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="999999"),
        )
        result = validate_extraction(ext)
        assert not result.valid
        assert any("same digit" in i.issue.lower() for i in result.issues)

    def test_valid_member_id_passes(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="302307904"),
        )
        result = validate_extraction(ext)
        assert result.valid

    def test_placeholder_government_id(self):
        ext = CardExtraction(
            card_type="GOVERNMENT",
            government=GovernmentData(name="JANE", id_number="0123456789"),
        )
        result = validate_extraction(ext)
        assert not result.valid

    def test_placeholder_date(self):
        ext = CardExtraction(
            card_type="GOVERNMENT",
            government=GovernmentData(name="JANE", id_number="D1234", expiration_date="01/01/2025"),
        )
        result = validate_extraction(ext)
        assert not result.valid
        assert any("placeholder date" in i.issue.lower() for i in result.issues)


class TestCrossFieldConsistency:
    def test_insurance_no_name_with_member_id(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="NONE", member_id="302307904"),
        )
        result = validate_extraction(ext)
        # This is a warning, not an error — so valid is still True
        assert result.valid
        assert any("subscriber name is none" in i.issue.lower() for i in result.issues)

    def test_government_no_name_with_id(self):
        ext = CardExtraction(
            card_type="GOVERNMENT",
            government=GovernmentData(name="NONE", id_number="D1234"),
        )
        result = validate_extraction(ext)
        assert not result.valid
        assert any("name is none" in i.issue.lower() for i in result.issues)


class TestWikiPatterns:
    def test_matching_pattern_passes(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="302307904"),
        )
        hints = {"patterns": {"member_id": r"\d{9}"}}
        result = validate_extraction(ext, wiki_hints=hints)
        assert result.valid
        assert not any("pattern" in i.issue.lower() for i in result.issues)

    def test_non_matching_pattern_warns(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="ABC123"),
        )
        hints = {"patterns": {"member_id": r"\d{9}"}}
        result = validate_extraction(ext, wiki_hints=hints)
        # Pattern mismatch is a warning, not an error
        assert result.valid
        assert any("pattern" in i.issue.lower() for i in result.issues)

    def test_none_value_skips_pattern_check(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="NONE"),
        )
        hints = {"patterns": {"member_id": r"\d{9}"}}
        result = validate_extraction(ext, wiki_hints=hints)
        assert result.valid

    def test_no_wiki_hints(self, sample_insurance_extraction):
        result = validate_extraction(sample_insurance_extraction)
        assert result.valid

    def test_bad_regex_logs_error_not_silent(self, caplog):
        """Fail-loud: a malformed wiki regex must ERROR-log, not silently skip."""
        import logging

        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="302307904"),
        )
        hints = {"patterns": {"member_id": r"[unclosed"}}
        with caplog.at_level(logging.ERROR, logger="card_extractor.validation"):
            result = validate_extraction(ext, wiki_hints=hints)

        # Bad regex did not crash validation.
        assert result.valid
        # Bad regex did not silently produce a false "doesn't match" warning.
        assert not any("pattern" in i.issue.lower() for i in result.issues)
        # An ERROR was logged identifying the offending field.
        assert any(
            "Invalid regex in wiki" in r.message and "member_id" in r.message
            for r in caplog.records
        )

    def test_good_and_bad_regex_mix(self, caplog):
        """Good patterns still run even when one sibling is malformed."""
        import logging

        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(
                subscriber_name="JOHN",
                member_id="ABC",  # would fail the good pattern
                group_number="12-345678",
            ),
        )
        hints = {"patterns": {
            "member_id": r"^\d{9}$",          # good
            "group_number": r"[unclosed",     # bad
        }}
        with caplog.at_level(logging.ERROR, logger="card_extractor.validation"):
            result = validate_extraction(ext, wiki_hints=hints)

        # Good pattern produced its warning.
        assert any(
            i.field == "member_id" and "pattern" in i.issue.lower()
            for i in result.issues
        )
        # Bad pattern logged and was skipped (no warning for group_number).
        assert any("group_number" in r.message for r in caplog.records)


class TestConfidenceAdjustment:
    def test_warnings_reduce_confidence(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="NONE", member_id="302307904"),
        )
        result = validate_extraction(ext)
        assert result.confidence_adjustment < 0

    def test_clean_extraction_no_adjustment(self, sample_insurance_extraction):
        result = validate_extraction(sample_insurance_extraction)
        assert result.confidence_adjustment == 0.0
