# Changelog

## 0.2.1 — 2026-05-13

### Fixed
- **Vendored prompt drift.** `card_extractor/prompts/extraction_with_context.md:3` referenced `format_rules_for_injection(IssuerRules)` — a function that was deleted in v0.2.0's prompts.py rewrite. Fixed upstream in the `vlm-card-extraction-prompts` skill (commit `0869e14`) to point at `wiki.get_rules(entity_key, sub_kind)` from the `knowledge_wiki` tool, then re-vendored into the harness. No runtime effect (the placeholder doc is informational; the actual `{wiki_context}` substitution happens at prompt-assembly time in `agent.py`).

### Removed
- **`card_extractor.models.ReviewItem`** Pydantic class. Replaced by the `review_queue` tool's `ReviewItem` in v0.2.0, but the harness model lingered because `tests/test_models.py::TestReviewItem::test_creation` referenced it. Removed both the class and the test — the new tool's `ReviewItem` is used everywhere `review_workflow.py` cares about review-item shape.

## 0.2.0 — 2026-05-13

### Changed
- Consumes the six toolbox tools shipped 2026-05-12 instead of inline implementations:
  - `agent-tool-pdf-vlm-renderer` (replaces `card_extractor/rendering.py`)
  - `agent-tool-knowledge-wiki` (replaces `card_extractor/wiki.py`)
  - `agent-tool-review-queue` + new `card_extractor/review_workflow.py` orchestration (replaces `card_extractor/review.py`)
  - `agent-tool-pipeline-trace` (replaces `card_extractor/trace.py`; all 13 typed methods → generic `trace.event(...)`)
  - `agent-tool-token-tracker` (replaces inline `TokenTracker` in `card_extractor/ai_client.py`)
  - `agent-tool-llm-utils` (replaces inline `retry_async`, `is_transient`, `is_fatal`, `save_checkpoint`, `load_checkpoint`)
- VLM prompts vendored from the `vlm-card-extraction-prompts` skill into `card_extractor/prompts/` as `.md` files.
- New `card_extractor/coords.py` bridges the harness's normalized `BoundingBox` (VLM-prompt contract) to the renderer's pixel `BoundingBox` (rendering boundary).

### Fixed (v0.1.x retro fold-in)
- `_durable()` no longer declares an unused `request_app: FastAPI = None` parameter (`app.py:75`).
- `crop_front_boxes` dead code removed (was in `rendering.py`).
- `format_rules_for_injection` dead code removed (was in `prompts.py`).
- `knowledge/index.md` shipped with an empty stub instead of leaked fixture-issuer rows.
- `RENDER_DPI` reconciled — both README and DESIGN.md now say 300 (the tool default).
- `AGENTS.md` test count refreshed to 55 (current).
- `scripts/run_batch.py` duplicate `ctx.output_dir` assignment removed.

### Removed
- `card_extractor/rendering.py`, `wiki.py`, `review.py`, `trace.py` (replaced by tool consumption).
- `tests/test_rendering.py`, `test_wiki.py`, `test_trace.py` (tested upstream in the tool repos).
- Five tests in `tests/test_tools.py` (TestCheckpoint, TestTokenTracker classes — symbols now live upstream in `llm_utils` and `token_tracker`).

### Compatibility notes
- On-disk checkpoint format: byte-identical (BatchProgress JSON wrap preserved).
- Wiki page format: byte-identical (YAML frontmatter + markdown body).
- Review queue file format: NEW shape (ReviewItem Pydantic model from review_queue tool — distinct from the v0.1.0 harness shape). Existing pending items from v0.1.0 are NOT migrated; treat as a breaking change for in-flight review queues. If you have unfinished reviews in production, drain them on v0.1.0 before upgrading.
- JSONL trace format: event-type VALUE strings preserved (`pdf_start`, `page_start`, `vlm_call`, `detection`, `verification`, `extraction`, `fallback`, `audit`, `audit_skipped`, `wiki_update`, `review_flagged`, `pdf_end`). However, the JSONL KEY for the event type changed from `"event"` to `"event_type"` (inherent to the pipeline_trace tool's API). Downstream consumers that grep `"event":` must update to `"event_type":`.
- FastAPI surface (`/review/*` routes): request/response shapes preserved; "approved | corrected | rejected" status semantics preserved via `extras["status"]` workaround on the new ReviewItem model.
- Two-decimal rounding on `latency_s` and `time_s` preserved at the trace call sites.

## 0.1.0 — 2026-05-12

Initial public release. Generalized and MIT-licensed under Chris Moore personal copyright from a discontinued private client POC (`gene-card-agent`).

- LangChain VLM pipeline (detect → verify → extract → validate) for ID cards and insurance cards.
- Karpathy-style learning wiki (`knowledge/issuers/`) accumulates per-issuer patterns across runs.
- Human review queue for low-confidence extractions.
- pypdfium2 (Apache-2.0) for PDF rendering — replaced PyMuPDF (AGPL) during the POC.
- 12-component agent harness implementation.
