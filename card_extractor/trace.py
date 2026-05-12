"""Pipeline trace — structured log of every decision, VLM call, and outcome.

Produces a _trace.jsonl file (one JSON object per line) that records the full
pipeline execution path for debugging, auditing, and cost analysis.

Each trace event has: timestamp, event_type, source, and type-specific fields.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class PipelineTrace:
    """Append-only structured trace log for a pipeline run."""

    def __init__(self, trace_path: Path):
        self.trace_path = trace_path
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def _emit(self, event: dict) -> None:
        event["timestamp"] = time.time()
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def _read_events(self) -> list[dict]:
        """Read all events from the JSONL trace file."""
        events: list[dict] = []
        if not self.trace_path.exists():
            return events
        for line in self.trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events

    # ------------------------------------------------------------------
    # Pipeline lifecycle events
    # ------------------------------------------------------------------

    def pdf_start(self, pdf_name: str, page_count: int) -> None:
        self._emit({
            "event": "pdf_start",
            "pdf": pdf_name,
            "pages": page_count,
        })

    def pdf_end(self, pdf_name: str, extractions: int, time_s: float) -> None:
        self._emit({
            "event": "pdf_end",
            "pdf": pdf_name,
            "extractions": extractions,
            "time_s": round(time_s, 2),
        })

    def page_start(self, pdf_name: str, page_num: int) -> None:
        self._emit({
            "event": "page_start",
            "pdf": pdf_name,
            "page": page_num,
        })

    # ------------------------------------------------------------------
    # VLM call events
    # ------------------------------------------------------------------

    def vlm_call(
        self,
        source: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_s: float = 0.0,
        result_summary: str = "",
    ) -> None:
        self._emit({
            "event": "vlm_call",
            "source": source,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_s": round(latency_s, 2),
            "result": result_summary,
        })

    # ------------------------------------------------------------------
    # Pipeline decision events
    # ------------------------------------------------------------------

    def detection_result(
        self,
        page: str,
        card_found: bool,
        box_count: int,
        front_count: int,
        back_count: int,
        unknown_count: int,
    ) -> None:
        self._emit({
            "event": "detection",
            "page": page,
            "card_found": card_found,
            "boxes": box_count,
            "front": front_count,
            "back": back_count,
            "unknown": unknown_count,
        })

    def verification_decision(
        self,
        crop: str,
        box_label: str,
        action: str,
        verdict: str = "",
    ) -> None:
        """Record verification decisions.

        action: 'skipped' (Front label, no VLM call), 'verified', 'vetoed'
        """
        self._emit({
            "event": "verification",
            "crop": crop,
            "box_label": box_label,
            "action": action,
            "verdict": verdict,
        })

    def extraction_result(
        self,
        crop: str,
        card_type: str,
        confidence: float,
        issuer_hint: str,
        valid: bool,
        issues: list[str],
    ) -> None:
        self._emit({
            "event": "extraction",
            "crop": crop,
            "card_type": card_type,
            "confidence": confidence,
            "issuer_hint": issuer_hint,
            "valid": valid,
            "issues": issues,
        })

    def fallback_triggered(self, page: str, reason: str) -> None:
        self._emit({
            "event": "fallback",
            "page": page,
            "reason": reason,
        })

    def audit_result(
        self,
        page: str,
        vlm_count: int,
        extracted_count: int,
        back_count: int,
        mismatch: bool,
    ) -> None:
        self._emit({
            "event": "audit",
            "page": page,
            "vlm_sees": vlm_count,
            "extracted": extracted_count,
            "backs": back_count,
            "mismatch": mismatch,
        })

    def audit_skipped(self, page: str, reason: str) -> None:
        self._emit({
            "event": "audit_skipped",
            "page": page,
            "reason": reason,
        })

    def wiki_update(self, issuer: str, card_type: str, source_pdf: str) -> None:
        self._emit({
            "event": "wiki_update",
            "issuer": issuer,
            "card_type": card_type,
            "source_pdf": source_pdf,
        })

    def review_flagged(
        self,
        crop: str,
        reason: str,
        confidence: float,
    ) -> None:
        self._emit({
            "event": "review_flagged",
            "crop": crop,
            "reason": reason,
            "confidence": confidence,
        })

    def error(self, source: str, page: str, message: str) -> None:
        self._emit({
            "event": "error",
            "source": source,
            "page": page,
            "message": message,
        })

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Aggregate trace into a summary by reading the JSONL trace file."""
        events = self._read_events()
        vlm_calls = [e for e in events if e.get("event") == "vlm_call"]
        extractions = [e for e in events if e.get("event") == "extraction"]
        audits = [e for e in events if e.get("event") == "audit"]
        fallbacks = [e for e in events if e.get("event") == "fallback"]
        errors = [e for e in events if e.get("event") == "error"]
        verifications = [e for e in events if e.get("event") == "verification"]

        return {
            "total_events": len(events),
            "vlm_calls": len(vlm_calls),
            "total_input_tokens": sum(e.get("input_tokens", 0) for e in vlm_calls),
            "total_output_tokens": sum(e.get("output_tokens", 0) for e in vlm_calls),
            "total_vlm_latency_s": round(sum(e.get("latency_s", 0) for e in vlm_calls), 1),
            "extractions": len(extractions),
            "extractions_valid": sum(1 for e in extractions if e.get("valid")),
            "audits_run": len(audits),
            "audit_mismatches": sum(1 for e in audits if e.get("mismatch")),
            "fallbacks_triggered": len(fallbacks),
            "verifications_skipped": sum(1 for e in verifications if e.get("action") == "skipped"),
            "verifications_run": sum(1 for e in verifications if e.get("action") == "verified"),
            "errors": len(errors),
        }
