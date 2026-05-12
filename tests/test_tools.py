"""Unit tests for agent tools and helpers — no API calls needed."""

from __future__ import annotations

import pytest

from card_extractor.agent import (
    AgentContext,
    _verify_extraction,
    _load_checkpoint,
    _save_checkpoint,
    _update_wiki_observation,
)
from card_extractor.ai_client import GatewayConfig, TokenTracker
from card_extractor.models import (
    BatchProgress,
    CardExtraction,
    GovernmentData,
    InsuranceData,
)
from card_extractor.review import ReviewQueue
from card_extractor.wiki import CardKnowledgeWiki


@pytest.fixture
def mock_ctx(tmp_path):
    """Create an AgentContext with temp directories for testing."""
    return AgentContext(
        config=GatewayConfig(url="http://fake", api_key="fake"),
        wiki=CardKnowledgeWiki(tmp_path / "wiki"),
        review_queue=ReviewQueue(tmp_path / "queue"),
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


class TestCheckpoint:
    def test_load_nonexistent(self, tmp_path):
        progress = _load_checkpoint(tmp_path / "nope.json")
        assert progress.total_pdfs == 0
        assert progress.completed_pdfs == {}

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "progress.json"
        progress = BatchProgress(
            total_pdfs=5,
            completed_pdfs={"doc1.pdf": [1, 2]},
            errors={"doc2.pdf": "timeout"},
        )
        _save_checkpoint(path, progress)
        loaded = _load_checkpoint(path)
        assert loaded.total_pdfs == 5
        assert "doc1.pdf" in loaded.completed_pdfs
        assert "doc2.pdf" in loaded.errors

    def test_load_none_path(self):
        progress = _load_checkpoint(None)
        assert progress.total_pdfs == 0

    def test_save_none_path(self):
        # Should not raise
        _save_checkpoint(None, BatchProgress())


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
        assert content is not None
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
        assert content is not None
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


class TestTokenTracker:
    def test_record_and_summary(self):
        tracker = TokenTracker()
        tracker.record("detect", "model-a", input_tokens=100, output_tokens=50)
        tracker.record("extract", "model-a", input_tokens=200, output_tokens=100)
        assert tracker.total_input == 300
        assert tracker.total_output == 150
        summary = tracker.summary()
        assert summary["total_calls"] == 2
        assert "detect" in summary["by_source"]
