"""Shared test fixtures."""

from __future__ import annotations

import pytest

from card_extractor.models import (
    BoundingBox,
    CardExtraction,
    CardRegion,
    GovernmentData,
    InsuranceData,
)


@pytest.fixture
def sample_insurance_extraction() -> CardExtraction:
    return CardExtraction(
        card_type="INSURANCE",
        insurance=InsuranceData(
            subscriber_name="JOHN SMITH",
            member_id="302307904",
            group_number="78-800132",
            rx_group_number="USHG",
            plan_type="PPO",
        ),
        government=GovernmentData(),
        confidence=0.92,
        issuer_hint="UnitedHealthcare",
    )


@pytest.fixture
def sample_government_extraction() -> CardExtraction:
    return CardExtraction(
        card_type="GOVERNMENT",
        insurance=InsuranceData(),
        government=GovernmentData(
            name="JANE DOE",
            id_number="D123-456-78-901",
            expiration_date="08/15/2028",
        ),
        confidence=0.88,
        issuer_hint="Florida DMV",
    )


@pytest.fixture
def sample_boxes() -> list[BoundingBox]:
    return [
        BoundingBox(card_type="Front", x1=0.05, y1=0.1, x2=0.95, y2=0.5),
        BoundingBox(card_type="Back", x1=0.05, y1=0.55, x2=0.95, y2=0.95),
    ]


@pytest.fixture
def sample_card_region(sample_boxes: list[BoundingBox]) -> CardRegion:
    return CardRegion(card_found=True, count=2, boxes=sample_boxes)
