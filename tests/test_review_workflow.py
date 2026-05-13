"""Tests for the harness's review_workflow orchestration layer.

These cover the ReviewWorkflow-level orchestration only: id-prefix lookup,
status disposition recorded in extras, the corrected-payload diff promoted
to the wiki. The underlying file primitives (flag_for_review, list_pending,
mark_reviewed) are tested upstream in agent-tool-review-queue.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from card_extractor.models import (
    CardExtraction,
    GovernmentData,
    InsuranceData,
    IssuerRules,
    ValidationResult,
)
from card_extractor.review_workflow import ReviewWorkflow


def _insurance(member_id: str = "302307904", issuer: str = "Aetna") -> CardExtraction:
    return CardExtraction(
        card_type="INSURANCE",
        insurance=InsuranceData(
            subscriber_name="JANE DOE",
            member_id=member_id,
            group_number="78-800132",
            plan_type="PPO",
        ),
        confidence=0.6,
        issuer_hint=issuer,
    )


def _government(name: str = "JOHN") -> CardExtraction:
    return CardExtraction(
        card_type="GOVERNMENT",
        government=GovernmentData(name=name, id_number="D123456", expiration_date="08/15/2028"),
        confidence=0.6,
        issuer_hint="Florida DMV",
    )


@pytest.fixture
def workflow(tmp_path: Path) -> ReviewWorkflow:
    return ReviewWorkflow(tmp_path / "review")


class TestReviewWorkflow:
    def test_flag_creates_pending_item(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="doc-001.pdf",
            page=1,
            crop_path="/tmp/c1.png",
            extraction=_insurance(),
            validation=ValidationResult(),
        )
        assert path.exists()
        assert path.parent == workflow.pending_dir

    def test_list_pending_returns_flagged_items(self, workflow):
        workflow.flag_for_review(
            source_pdf="a.pdf", page=1, crop_path="/tmp/a.png",
            extraction=_insurance(issuer="A"), validation=ValidationResult(),
        )
        workflow.flag_for_review(
            source_pdf="b.pdf", page=1, crop_path="/tmp/b.png",
            extraction=_insurance(issuer="B"), validation=ValidationResult(),
        )
        pending = workflow.list_pending()
        assert len(pending) == 2

    def test_flag_preserves_legacy_metadata_in_extras(self, workflow):
        workflow.flag_for_review(
            source_pdf="doc-x.pdf",
            page=3,
            crop_path="/tmp/x_p3_b1.png",
            extraction=_insurance(),
            validation=ValidationResult(),
            wiki_context="ctx-blob",
            box_index=2,
        )
        pending = workflow.list_pending()
        assert len(pending) == 1
        item = pending[0]
        assert item.source_ref == "doc-x.pdf"
        assert item.context == "ctx-blob"
        assert item.extras["page"] == 3
        assert item.extras["box_index"] == 2
        assert item.extras["crop_path"] == "/tmp/x_p3_b1.png"
        assert item.extras["status"] == "pending"

    def test_get_finds_item_by_id_prefix(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="x.pdf", page=1, crop_path="/tmp/x.png",
            extraction=_insurance(issuer="X"), validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        result = workflow.get(item_id)
        assert result is not None
        assert result.source_ref == "x.pdf"

    def test_get_returns_none_for_unknown_id(self, workflow):
        assert workflow.get("0") is None

    def test_submit_review_approved_moves_to_reviewed(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="y.pdf", page=1, crop_path="/tmp/y.png",
            extraction=_insurance(issuer="Y"), validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        result = workflow.submit_review(item_id, status="approved")
        assert result is not None
        assert result.extras["status"] == "approved"
        assert len(workflow.list_pending()) == 0
        assert len(workflow.list_reviewed()) == 1

    def test_submit_review_corrected_persists_corrected_extraction(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="z.pdf", page=1, crop_path="/tmp/z.png",
            extraction=_insurance(issuer="Z", member_id="ORIGINAL"),
            validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        corrected = _insurance(issuer="Z", member_id="CORRECTED")
        result = workflow.submit_review(item_id, status="corrected", correction=corrected)
        assert result is not None
        # Tool replaces extraction with the corrected payload.
        assert result.extraction["insurance"]["member_id"] == "CORRECTED"
        # And we stashed the pre-correction snapshot so compile can diff.
        assert result.extras["status"] == "corrected"
        assert result.extras["original_extraction"]["insurance"]["member_id"] == "ORIGINAL"

    def test_submit_review_rejected_does_not_replace_extraction(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="r.pdf", page=1, crop_path="/tmp/r.png",
            extraction=_insurance(issuer="R", member_id="KEEP"),
            validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        # Even if a correction is passed, rejected must not overwrite.
        bogus = _insurance(issuer="R", member_id="SHOULD_NOT_APPEAR")
        result = workflow.submit_review(item_id, status="rejected", correction=bogus)
        assert result is not None
        assert result.extras["status"] == "rejected"
        assert result.extraction["insurance"]["member_id"] == "KEEP"

    def test_submit_review_returns_none_when_id_not_found(self, workflow):
        assert workflow.submit_review("nonexistent") is None

    def test_list_all_returns_pending_and_reviewed(self, workflow):
        p1 = workflow.flag_for_review(
            source_pdf="a.pdf", page=1, crop_path="/tmp/a.png",
            extraction=_insurance(issuer="A"), validation=ValidationResult(),
        )
        workflow.flag_for_review(
            source_pdf="b.pdf", page=1, crop_path="/tmp/b.png",
            extraction=_insurance(issuer="B"), validation=ValidationResult(),
        )
        workflow.submit_review(p1.stem.split("_")[0], status="approved")
        all_items = workflow.list_all()
        assert len(all_items) == 2

    def test_get_finds_reviewed_items_too(self, workflow):
        path = workflow.flag_for_review(
            source_pdf="g.pdf", page=1, crop_path="/tmp/g.png",
            extraction=_insurance(issuer="G"), validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        workflow.submit_review(item_id, status="approved")
        # After submission the pending file is gone, but get() looks in
        # reviewed/ too.
        result = workflow.get(item_id)
        assert result is not None
        assert result.source_ref == "g.pdf"

    @pytest.mark.asyncio
    async def test_compile_reviewed_to_wiki_promotes_corrected_items(self, workflow, tmp_path):
        from knowledge_wiki import KnowledgeWiki

        wiki = KnowledgeWiki(
            tmp_path / "wiki", entity_dir_name="issuers", rules_model=IssuerRules
        )

        path = workflow.flag_for_review(
            source_pdf="src.pdf", page=1, crop_path="/tmp/src.png",
            extraction=_insurance(issuer="Aetna", member_id="OLD"),
            validation=ValidationResult(),
        )
        item_id = path.stem.split("_")[0]
        workflow.submit_review(
            item_id,
            status="corrected",
            correction=_insurance(issuer="Aetna", member_id="NEW"),
        )

        count = await workflow.compile_reviewed_to_wiki(wiki)
        assert count == 1

        # Wiki page exists for the corrected issuer.
        content = wiki.lookup("Aetna", sub_kind="INSURANCE")
        assert content
        assert "HUMAN CORRECTION" in content

        # Second call should skip — the item was flipped to 'approved'.
        count2 = await workflow.compile_reviewed_to_wiki(wiki)
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_compile_skips_approved_and_rejected(self, workflow, tmp_path):
        from knowledge_wiki import KnowledgeWiki

        wiki = KnowledgeWiki(
            tmp_path / "wiki", entity_dir_name="issuers", rules_model=IssuerRules
        )

        p_approved = workflow.flag_for_review(
            source_pdf="a.pdf", page=1, crop_path="/tmp/a.png",
            extraction=_insurance(issuer="Approved"), validation=ValidationResult(),
        )
        p_rejected = workflow.flag_for_review(
            source_pdf="r.pdf", page=1, crop_path="/tmp/r.png",
            extraction=_insurance(issuer="Rejected"), validation=ValidationResult(),
        )
        workflow.submit_review(p_approved.stem.split("_")[0], status="approved")
        workflow.submit_review(p_rejected.stem.split("_")[0], status="rejected")

        count = await workflow.compile_reviewed_to_wiki(wiki)
        assert count == 0

    @pytest.mark.asyncio
    async def test_compile_diff_records_changed_fields(self, workflow, tmp_path):
        from knowledge_wiki import KnowledgeWiki

        wiki = KnowledgeWiki(
            tmp_path / "wiki", entity_dir_name="issuers", rules_model=IssuerRules
        )

        path = workflow.flag_for_review(
            source_pdf="src.pdf", page=1, crop_path="/tmp/src.png",
            extraction=_insurance(issuer="Cigna", member_id="111"),
            validation=ValidationResult(),
        )
        workflow.submit_review(
            path.stem.split("_")[0],
            status="corrected",
            correction=_insurance(issuer="Cigna", member_id="222"),
        )

        await workflow.compile_reviewed_to_wiki(wiki)
        # Read frontmatter directly to assert the diff landed.
        page_path = wiki.root_dir / "issuers" / "cigna.md"
        assert page_path.exists()
        text = page_path.read_text(encoding="utf-8")
        assert "member_id" in text
        assert "111" in text and "222" in text
        assert "last_correction_source: src.pdf" in text
