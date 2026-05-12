"""Integration tests for the agent pipeline — requires API key.

Run with: AI_GATEWAY_KEY=... pytest tests/test_agent.py -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from card_extractor.agent import AgentContext, process_pdf
from card_extractor.ai_client import GatewayConfig, check_gateway_connection


pytestmark = pytest.mark.integration


@pytest.fixture
def ctx(tmp_path):
    """Create a real AgentContext from environment."""
    config = GatewayConfig.from_env()
    if not config.available:
        pytest.skip("AI_GATEWAY_KEY not set")

    from card_extractor.wiki import CardKnowledgeWiki
    from card_extractor.review import ReviewQueue

    return AgentContext(
        config=config,
        wiki=CardKnowledgeWiki(tmp_path / "wiki"),
        review_queue=ReviewQueue(tmp_path / "queue"),
        output_dir=tmp_path / "output",
    )


@pytest.fixture
def sample_pdf() -> Path:
    """Find a sample PDF for testing."""
    candidates = [
        Path("./fixtures/sample.pdf"),
        Path("./input/sample.pdf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    pytest.skip("No sample PDF found")


@pytest.mark.asyncio
async def test_gateway_connection(ctx):
    """Verify we can reach the AI Gateway."""
    connected = await check_gateway_connection(ctx.config)
    assert connected, "Cannot reach AI Gateway"


@pytest.mark.asyncio
async def test_process_single_pdf(ctx, sample_pdf):
    """Process one PDF end-to-end and verify outputs."""
    extractions = await process_pdf(sample_pdf, ctx)

    # Should find at least one card in the sample PDF
    assert len(extractions) > 0

    for ext in extractions:
        assert ext.card_type in ("INSURANCE", "GOVERNMENT")
        assert ext.confidence > 0.0

        if ext.card_type == "INSURANCE":
            # Should have at least subscriber_name or member_id
            assert (
                ext.insurance.subscriber_name != "NONE"
                or ext.insurance.member_id != "NONE"
            )

    # Verify output files were created
    output_files = list(ctx.output_dir.glob("*.json"))
    assert len(output_files) > 0

    # Verify wiki was updated (if issuer_hint was found)
    issuer_pages = list((ctx.wiki.wiki_dir / "issuers").glob("*.md"))
    # Filter out template
    issuer_pages = [p for p in issuer_pages if p.name != "_template.md"]
    # May or may not have wiki entries depending on issuer_hint quality

    print(f"Extractions: {len(extractions)}")
    print(f"Output JSONs: {len(output_files)}")
    print(f"Wiki pages: {len(issuer_pages)}")
    print(f"Token usage: {ctx.tracker.summary()}")
