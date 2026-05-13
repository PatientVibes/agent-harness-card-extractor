"""Unit tests for agent tools and helpers — no API calls needed."""

from __future__ import annotations

import pytest

from card_extractor.agent import (
    AgentContext,
    _verify_extraction,
    _update_wiki_observation,
)
from card_extractor.ai_client import GatewayConfig
from card_extractor.models import (
    CardExtraction,
    GovernmentData,
    InsuranceData,
)
from card_extractor.models import IssuerRules
from card_extractor.review_workflow import ReviewWorkflow
from knowledge_wiki import KnowledgeWiki


@pytest.fixture
def mock_ctx(tmp_path):
    """Create an AgentContext with temp directories for testing."""
    return AgentContext(
        config=GatewayConfig(url="http://fake", api_key="fake"),
        wiki=KnowledgeWiki(tmp_path / "wiki", entity_dir_name="issuers", rules_model=IssuerRules),
        review_queue=ReviewWorkflow(tmp_path / "queue"),
        output_dir=tmp_path / "output",
    )


class TestVerifyExtraction:
    def test_valid_insurance(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="302307904"),
            confidence=0.9,
        )
        issues = _verify_extraction(ext)
        assert issues == []

    def test_insurance_missing_name(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="NONE", member_id="302307904"),
        )
        issues = _verify_extraction(ext)
        assert any("subscriber_name" in i for i in issues)

    def test_government_missing_name(self):
        ext = CardExtraction(
            card_type="GOVERNMENT",
            government=GovernmentData(name="NONE", id_number="D1234"),
        )
        issues = _verify_extraction(ext)
        assert len(issues) > 0

    def test_placeholder_detected(self):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="1234567890"),
        )
        issues = _verify_extraction(ext)
        assert any("placeholder" in i.lower() for i in issues)

    def test_with_wiki_hints(self):
        """Wiki pattern mismatches are warnings, not errors — they don't appear
        in _verify_extraction issues (which only collects errors), but they do
        appear in validate_extraction results."""
        from card_extractor.validation import validate_extraction as ve

        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="ABC"),
        )
        hints = {"patterns": {"member_id": r"\d{9}"}}
        # validate_extraction captures the warning
        result = ve(ext, wiki_hints=hints)
        assert any("pattern" in i.issue.lower() for i in result.issues)


class TestWikiObservation:
    async def test_insurance_observation(self, mock_ctx):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(
                subscriber_name="JOHN",
                member_id="302307904",
                group_number="78-800132",
                plan_type="PPO",
            ),
            confidence=0.9,
            issuer_hint="UnitedHealthcare",
        )
        await _update_wiki_observation(ext, mock_ctx, "DOC-001.pdf")
        content = mock_ctx.wiki.lookup("UnitedHealthcare")
        assert content
        # PII is masked: 302307904 -> #########
        assert "#########" in content
        assert "302307904" not in content  # raw PII must NOT appear

    async def test_government_observation(self, mock_ctx):
        ext = CardExtraction(
            card_type="GOVERNMENT",
            government=GovernmentData(
                name="JANE",
                id_number="D123456",
                expiration_date="08/15/2028",
            ),
            confidence=0.85,
            issuer_hint="Florida DMV",
        )
        await _update_wiki_observation(ext, mock_ctx, "DOC-002.pdf")
        content = mock_ctx.wiki.lookup("Florida DMV")
        assert content
        # PII is masked: D123456 -> A######
        assert "A######" in content or "id_number pattern" in content
        assert "D123456" not in content  # raw PII must NOT appear

    async def test_no_issuer_hint(self, mock_ctx):
        ext = CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="123"),
            issuer_hint="",
        )
        # Should not crash even with empty issuer
        await _update_wiki_observation(ext, mock_ctx, "DOC.pdf")


