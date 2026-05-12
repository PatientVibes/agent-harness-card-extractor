"""Tests for wiki and review queue modules."""

from __future__ import annotations

import asyncio
import re

import pytest

from card_extractor.models import CardExtraction, InsuranceData, IssuerRules, ValidationResult
from card_extractor.wiki import (
    CardKnowledgeWiki,
    _parse_frontmatter,
    _serialize_page,
    _slugify,
)
from card_extractor.review import ReviewQueue


class TestSlugify:
    def test_basic(self):
        assert _slugify("UnitedHealthcare") == "unitedhealthcare"

    def test_spaces_and_symbols(self):
        assert _slugify("Blue Cross / Blue Shield") == "blue_cross_blue_shield"

    def test_empty(self):
        assert _slugify("") == "unknown"

    def test_special_chars(self):
        assert _slugify("Aetna (PPO)") == "aetna_ppo"


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = (
            "---\n"
            "issuer: Aetna\n"
            "card_type: INSURANCE\n"
            "---\n"
            "\n# Aetna\n\nBody here.\n"
        )
        fm, body = _parse_frontmatter(content)
        assert fm == {"issuer": "Aetna", "card_type": "INSURANCE"}
        assert "# Aetna" in body
        assert "Body here" in body

    def test_no_frontmatter(self):
        content = "# Some page\n\nNo frontmatter here.\n"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_empty_frontmatter(self):
        content = "---\n---\n\n# Body\n"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert "# Body" in body

    def test_malformed_yaml(self):
        # Tabs in YAML + nesting mixed → YAMLError.
        content = "---\nissuer: : : bad\n  - [nested\n---\n\nbody\n"
        fm, body = _parse_frontmatter(content)
        # Malformed YAML → ({}, body) with warning log; must not crash.
        assert fm == {}
        assert "body" in body

    def test_unclosed_fence(self):
        content = "---\nissuer: Aetna\n\n# No closing fence\n"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_roundtrip(self):
        rules = IssuerRules(
            issuer="Aetna",
            card_type="INSURANCE",
            patterns={"member_id": r"^\d{9}$"},
            required_fields=["subscriber_name"],
            version=2,
            last_human_correction="2026-04-13T00:00:00+00:00",
        )
        body = "\n# Aetna\n\nObservations.\n"
        page = _serialize_page(rules, body)
        fm, parsed_body = _parse_frontmatter(page)
        assert fm["issuer"] == "Aetna"
        assert fm["patterns"]["member_id"] == r"^\d{9}$"
        assert fm["version"] == 2
        assert "# Aetna" in parsed_body


class TestCardKnowledgeWiki:
    def test_lookup_nonexistent(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        assert wiki.lookup("Nonexistent") is None

    async def test_write_and_lookup(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.write_observation(
            issuer="UnitedHealthcare",
            card_type="INSURANCE",
            observation="member_id is 9 digits",
            source_pdf="DOC-001.pdf",
            confidence=0.9,
        )
        content = wiki.lookup("UnitedHealthcare")
        assert content is not None
        assert "member_id is 9 digits" in content
        # New page has frontmatter.
        assert content.startswith("---\n")
        fm, _body = _parse_frontmatter(content)
        assert fm.get("issuer") == "UnitedHealthcare"

    async def test_write_observation_does_not_touch_frontmatter(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        # Seed the page with a pattern via compile_correction.
        await wiki.compile_correction(
            issuer="Aetna",
            card_type="INSURANCE",
            patterns={"member_id": r"^\d{9}$"},
        )
        before = wiki.lookup("Aetna")
        fm_before, _ = _parse_frontmatter(before)

        # Now append an observation.
        await wiki.write_observation("Aetna", "INSURANCE", "some obs")
        after = wiki.lookup("Aetna")
        fm_after, _ = _parse_frontmatter(after)

        # Frontmatter rules unchanged.
        assert fm_after["patterns"] == fm_before["patterns"]
        assert fm_after["version"] == fm_before["version"]
        assert "some obs" in after

    async def test_index_updated(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.write_observation("Aetna", "INSURANCE", "test obs")
        index = wiki.get_index()
        assert "aetna" in index
        assert "INSURANCE" in index["aetna"]

    async def test_index_no_duplicates(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.write_observation("Aetna", "INSURANCE", "obs 1")
        await wiki.write_observation("Aetna", "INSURANCE", "obs 2")
        index = wiki.get_index()
        assert index["aetna"].count("INSURANCE") == 1

    async def test_log_appended(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.write_observation("Aetna", "INSURANCE", "first obs")
        await wiki.write_observation("BCBS", "INSURANCE", "second obs")
        log = wiki.log_path.read_text(encoding="utf-8")
        assert "Aetna" in log
        assert "BCBS" in log

    def test_extraction_hints_empty(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        hints = wiki.get_extraction_hints("Nonexistent")
        assert hints == {}

    async def test_extraction_hints_from_frontmatter(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.compile_correction(
            issuer="Test Issuer",
            card_type="INSURANCE",
            patterns={"member_id": r"^\d{9}$"},
            required_fields=["subscriber_name", "member_id"],
        )
        hints = wiki.get_extraction_hints("Test Issuer")
        assert hints["patterns"]["member_id"] == r"^\d{9}$"
        assert "subscriber_name" in hints["required_fields"]
        assert "member_id" in hints["required_fields"]

    def test_extraction_hints_rejects_bad_frontmatter(self, tmp_path, caplog):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        # Hand-write a page with frontmatter that fails Pydantic validation.
        page = wiki.issuers_dir / "bad.md"
        page.write_text(
            "---\n"
            "issuer: Bad\n"
            "card_type: NOT_A_VALID_TYPE\n"
            "---\n\n# Bad\n",
            encoding="utf-8",
        )
        import logging
        with caplog.at_level(logging.ERROR):
            hints = wiki.get_extraction_hints("bad")
        assert hints == {}
        assert any("Invalid IssuerRules" in r.message for r in caplog.records)

    async def test_compile_correction_lands_in_frontmatter(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.compile_correction(
            issuer="Aetna",
            card_type="INSURANCE",
            patterns={"member_id": r"^\d{9}$"},
            required_fields=["subscriber_name"],
            source_pdf="DOC-002.pdf",
        )
        content = wiki.lookup("Aetna")
        fm, body = _parse_frontmatter(content)
        assert fm["patterns"]["member_id"] == r"^\d{9}$"
        assert "subscriber_name" in fm["required_fields"]
        assert fm["version"] == 2  # bumped from default 1
        assert fm["last_human_correction"]  # non-empty ISO timestamp
        assert "HUMAN CORRECTION" in body

    async def test_compile_correction_backcompat_text_only(self, tmp_path):
        """Callers that pass only original_text/correction_text still work."""
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        await wiki.compile_correction(
            issuer="Aetna",
            card_type="INSURANCE",
            original_text="member_id: 'ABC123'",
            correction_text="member_id: '987654321'",
            source_pdf="DOC-002.pdf",
        )
        content = wiki.lookup("Aetna")
        assert "HUMAN CORRECTION" in content
        assert "ABC123" in content
        assert "987654321" in content
        fm, _ = _parse_frontmatter(content)
        # No structured corrections → patterns stays empty, version still bumped.
        assert fm["patterns"] == {}
        assert fm["version"] == 2

    async def test_compile_correction_rejects_bad_regex(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        # First seed a valid page.
        await wiki.compile_correction(
            issuer="Aetna",
            card_type="INSURANCE",
            patterns={"member_id": r"^\d{9}$"},
        )
        before = wiki.lookup("Aetna")

        # Now attempt to write a malformed regex.
        with pytest.raises(re.error):
            await wiki.compile_correction(
                issuer="Aetna",
                card_type="INSURANCE",
                patterns={"group_number": r"[unclosed"},
            )

        # Page is unchanged.
        after = wiki.lookup("Aetna")
        assert after == before

    async def test_lock_serializes_concurrent_writes(self, tmp_path):
        """Sanity: concurrent write_observations don't corrupt the page."""
        wiki = CardKnowledgeWiki(tmp_path / "wiki")

        async def writer(i: int) -> None:
            await wiki.write_observation(
                "Aetna", "INSURANCE", f"obs {i}", source_pdf=f"doc-{i}.pdf",
            )

        await asyncio.gather(*(writer(i) for i in range(10)))

        content = wiki.lookup("Aetna")
        # All 10 observations landed.
        for i in range(10):
            assert f"obs {i}" in content
        # Frontmatter is still valid YAML (not corrupted by interleaved writes).
        fm, _ = _parse_frontmatter(content)
        assert fm.get("issuer") == "Aetna"


class TestReviewQueue:
    def _make_extraction(self) -> CardExtraction:
        return CardExtraction(
            card_type="INSURANCE",
            insurance=InsuranceData(subscriber_name="JOHN", member_id="123"),
            confidence=0.5,
            issuer_hint="TestIssuer",
        )

    def test_flag_and_list(self, tmp_path):
        queue = ReviewQueue(tmp_path / "queue")
        ext = self._make_extraction()
        item = queue.flag_for_review(
            source_pdf="DOC-001.pdf",
            page=1,
            crop_path="/tmp/crop.png",
            extraction=ext,
            validation=ValidationResult(),
        )
        assert item.status == "pending"

        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].id == item.id

    def test_submit_review(self, tmp_path):
        queue = ReviewQueue(tmp_path / "queue")
        ext = self._make_extraction()
        item = queue.flag_for_review("DOC.pdf", 1, "/tmp/c.png", ext, ValidationResult())

        corrected_ext = ext.model_copy(update={"insurance": InsuranceData(subscriber_name="JOHN", member_id="987654321")})
        updated = queue.submit_review(item.id, "corrected", correction=corrected_ext)

        assert updated is not None
        assert updated.status == "corrected"
        assert updated.human_correction.insurance.member_id == "987654321"

    def test_submit_nonexistent(self, tmp_path):
        queue = ReviewQueue(tmp_path / "queue")
        # Must use valid UUID format (path traversal protection)
        assert queue.submit_review("00000000-0000-0000-0000-000000000000", "approved") is None

    def test_submit_invalid_id(self, tmp_path):
        queue = ReviewQueue(tmp_path / "queue")
        with pytest.raises(ValueError, match="Invalid review item ID"):
            queue.submit_review("fake-id", "approved")

    async def test_compile_to_wiki(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        queue = ReviewQueue(tmp_path / "queue")

        ext = self._make_extraction()
        item = queue.flag_for_review("DOC.pdf", 1, "/tmp/c.png", ext, ValidationResult())

        corrected = ext.model_copy(update={"insurance": InsuranceData(subscriber_name="JOHN", member_id="987654321")})
        queue.submit_review(item.id, "corrected", correction=corrected)

        count = await queue.compile_reviewed_to_wiki(wiki)
        assert count == 1

        content = wiki.lookup("TestIssuer")
        assert content is not None
        assert "HUMAN CORRECTION" in content

    async def test_compile_skips_non_corrected(self, tmp_path):
        wiki = CardKnowledgeWiki(tmp_path / "wiki")
        queue = ReviewQueue(tmp_path / "queue")

        ext = self._make_extraction()
        item = queue.flag_for_review("DOC.pdf", 1, "/tmp/c.png", ext, ValidationResult())
        queue.submit_review(item.id, "approved")

        count = await queue.compile_reviewed_to_wiki(wiki)
        assert count == 0
