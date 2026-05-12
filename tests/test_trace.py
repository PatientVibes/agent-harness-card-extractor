"""Tests for PipelineTrace — verifies summary() reads aggregates from the
JSONL file (no in-memory buffer)."""

from __future__ import annotations

import json

from card_extractor.trace import PipelineTrace


def test_summary_reads_from_file(tmp_path):
    """summary() should read and aggregate events from the trace file, not
    from an in-memory list (which no longer exists)."""
    trace_path = tmp_path / "_trace.jsonl"
    trace = PipelineTrace(trace_path)

    trace.pdf_start("doc.pdf", page_count=2)
    trace.vlm_call("detect_cards", "vlm", input_tokens=100, output_tokens=20, latency_s=1.2)
    trace.vlm_call("extract_card_data", "vlm", input_tokens=200, output_tokens=50, latency_s=2.0)
    trace.extraction_result("crop1.png", "INSURANCE", 0.9, "Acme", valid=True, issues=[])
    trace.extraction_result("crop2.png", "INSURANCE", 0.6, "Acme", valid=False, issues=["bad"])
    trace.verification_decision("crop1.png", "Front", "skipped")
    trace.verification_decision("crop2.png", "Unknown", "verified", verdict="FRONT")
    trace.fallback_triggered("page1.png", "no cards detected")
    trace.error("render", "doc.pdf", "boom")

    assert trace_path.exists()
    summary = trace.summary()

    assert summary["vlm_calls"] == 2
    assert summary["total_input_tokens"] == 300
    assert summary["total_output_tokens"] == 70
    assert summary["extractions"] == 2
    assert summary["extractions_valid"] == 1
    assert summary["fallbacks_triggered"] == 1
    assert summary["verifications_skipped"] == 1
    assert summary["verifications_run"] == 1
    assert summary["errors"] == 1


def test_summary_empty_when_no_events(tmp_path):
    trace = PipelineTrace(tmp_path / "_trace.jsonl")
    summary = trace.summary()
    assert summary["vlm_calls"] == 0
    assert summary["total_input_tokens"] == 0
    assert summary["extractions"] == 0


def test_summary_tolerates_garbage_lines(tmp_path):
    """Malformed lines in the trace file should be skipped, not crash."""
    trace_path = tmp_path / "_trace.jsonl"
    trace = PipelineTrace(trace_path)
    trace.vlm_call("detect_cards", "vlm", input_tokens=10, output_tokens=5, latency_s=0.1)

    # Append a garbage line
    with trace_path.open("a", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write("\n")
        f.write(json.dumps({"event": "vlm_call", "input_tokens": 7, "output_tokens": 3}) + "\n")

    summary = trace.summary()
    assert summary["vlm_calls"] == 2
    assert summary["total_input_tokens"] == 17
    assert summary["total_output_tokens"] == 8


def test_events_not_buffered_in_memory(tmp_path):
    """Regression guard: PipelineTrace must not keep an in-memory _events list."""
    trace = PipelineTrace(tmp_path / "_trace.jsonl")
    trace.pdf_start("doc.pdf", 1)
    assert not hasattr(trace, "_events")
