"""Deterministic hallucination filters and extraction validation — no LLM calls."""

from __future__ import annotations

import logging
import re
from typing import Optional

from card_extractor.models import CardExtraction, ValidationIssue, ValidationResult


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known-bad placeholder values (migrated from POC)
# ---------------------------------------------------------------------------

PLACEHOLDER_DATES = {
    "01/01/2025", "12/31/2025",
    "01/01/2026", "12/31/2026",
    "01/01/2027", "12/31/2027",
}

PLACEHOLDER_IDS = {
    "1234567890", "0123456789",
    "1111111111", "0000000000",
}

SEQUENTIAL_DIGITS = {
    "123456", "1234567", "12345678", "123456789", "1234567890",
    "0123456", "01234567", "012345678", "0123456789",
}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_placeholder_id(value: str, field_name: str) -> Optional[ValidationIssue]:
    if value in PLACEHOLDER_IDS:
        return ValidationIssue(
            field=field_name,
            issue=f"Value '{value}' is a known placeholder ID",
            severity="error",
        )
    return None


def _check_sequential_digits(value: str, field_name: str) -> Optional[ValidationIssue]:
    stripped = re.sub(r"[^0-9]", "", value)
    if stripped in SEQUENTIAL_DIGITS:
        return ValidationIssue(
            field=field_name,
            issue=f"Value '{value}' looks like sequential/test digits",
            severity="error",
        )
    return None


def _check_placeholder_date(value: str, field_name: str) -> Optional[ValidationIssue]:
    if value in PLACEHOLDER_DATES:
        return ValidationIssue(
            field=field_name,
            issue=f"Value '{value}' is a known placeholder date",
            severity="error",
        )
    return None


def _check_all_same_digit(value: str, field_name: str) -> Optional[ValidationIssue]:
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) >= 6 and len(set(digits)) == 1:
        return ValidationIssue(
            field=field_name,
            issue=f"Value '{value}' is all the same digit — likely fabricated",
            severity="error",
        )
    return None


# ---------------------------------------------------------------------------
# Cross-field consistency checks
# ---------------------------------------------------------------------------


def _check_insurance_consistency(ext: CardExtraction) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ins = ext.insurance

    if ins.subscriber_name == "NONE" and ins.member_id != "NONE":
        issues.append(ValidationIssue(
            field="subscriber_name",
            issue="Member ID present but subscriber name is NONE — likely missed the name",
            severity="warning",
        ))

    if ins.member_id == "NONE" and ins.group_number != "NONE":
        issues.append(ValidationIssue(
            field="member_id",
            issue="Group number present but member ID is NONE — unusual for insurance cards",
            severity="warning",
        ))

    return issues


def _check_government_consistency(ext: CardExtraction) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    gov = ext.government

    if gov.name == "NONE" and (gov.id_number != "NONE" or gov.expiration_date != "NONE"):
        issues.append(ValidationIssue(
            field="name",
            issue="ID number or expiration present but name is NONE — likely missed the name",
            severity="error",
        ))

    return issues


# ---------------------------------------------------------------------------
# Wiki-informed checks
# ---------------------------------------------------------------------------


def _check_wiki_patterns(
    ext: CardExtraction, wiki_hints: dict,
) -> list[ValidationIssue]:
    """Validate extracted values against known patterns from the wiki.

    Pre-compiles every pattern up front. Any pattern that fails to compile
    is logged at ERROR level and skipped — never silently ignored, since a
    silently-broken regex disables validation and is a poisoning vector.
    Input values longer than 200 characters are skipped (ReDoS protection).
    """
    issues: list[ValidationIssue] = []
    patterns = wiki_hints.get("patterns", {})

    field_map = {
        "member_id": ext.insurance.member_id,
        "group_number": ext.insurance.group_number,
        "rx_group_number": ext.insurance.rx_group_number,
        "id_number": ext.government.id_number,
    }

    # Pre-compile all patterns once. Bad regex → ERROR log + skip.
    compiled_patterns: dict[str, re.Pattern[str]] = {}
    for field_name, pattern_str in patterns.items():
        try:
            compiled_patterns[field_name] = re.compile(pattern_str)
        except re.error as e:
            logger.error(
                "Invalid regex in wiki for field %s: %s (pattern=%r)",
                field_name, e, pattern_str,
            )
            continue

    for field_name, compiled in compiled_patterns.items():
        value = field_map.get(field_name, "NONE")
        if value == "NONE" or len(value) > 200:
            continue
        if not compiled.match(value):
            issues.append(ValidationIssue(
                field=field_name,
                issue=f"Value '{value}' doesn't match known pattern '{compiled.pattern}' from wiki",
                severity="warning",
            ))

    return issues


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def validate_extraction(
    extraction: CardExtraction,
    wiki_hints: Optional[dict] = None,
) -> ValidationResult:
    """Run all deterministic validation checks on an extraction."""
    issues: list[ValidationIssue] = []

    if extraction.card_type == "INSURANCE":
        ins = extraction.insurance
        for field, value in [
            ("member_id", ins.member_id),
            ("group_number", ins.group_number),
        ]:
            if value == "NONE":
                continue
            for checker in [_check_placeholder_id, _check_sequential_digits, _check_all_same_digit]:
                issue = checker(value, field)
                if issue:
                    issues.append(issue)

        issues.extend(_check_insurance_consistency(extraction))

    elif extraction.card_type == "GOVERNMENT":
        gov = extraction.government
        for field, value in [
            ("id_number", gov.id_number),
        ]:
            if value == "NONE":
                continue
            for checker in [_check_placeholder_id, _check_sequential_digits, _check_all_same_digit]:
                issue = checker(value, field)
                if issue:
                    issues.append(issue)

        if gov.expiration_date != "NONE":
            issue = _check_placeholder_date(gov.expiration_date, "expiration_date")
            if issue:
                issues.append(issue)

        issues.extend(_check_government_consistency(extraction))

    # Wiki-informed checks
    if wiki_hints:
        issues.extend(_check_wiki_patterns(extraction, wiki_hints))

    # Compute validity — any "error" severity issue makes it invalid
    has_errors = any(i.severity == "error" for i in issues)
    confidence_penalty = -0.1 * sum(1 for i in issues if i.severity == "warning")

    return ValidationResult(
        valid=not has_errors,
        issues=issues,
        confidence_adjustment=confidence_penalty,
    )
