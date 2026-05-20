Now I have a thorough understanding of the repository. Let me write the HANDOFF file.

# Handoff

## Current Status

**Version:** 0.2.1 (released 2026-05-13). The harness is stable and production-ready as a standalone service.

**What this repo is:** A Python 3.11+ LangChain VLM pipeline for extracting structured data from scanned PDFs of government IDs and insurance cards. Exposes a FastAPI service (`card_extractor/app.py`) and a batch CLI (`scripts/run_batch.py`). Consumes six toolbox packages pinned by git SHA via `[tool.uv.sources]` in `pyproject.toml`.

**Test suite:** 54 unit tests in `tests/`, no API key required. Integration tests marked `@pytest.mark.integration` require `AI_GATEWAY_KEY`.

**CI:** `.github/workflows/audit.yml` runs `repo-doc-gov audit --fail-on high` on every PR and push to `master` on a self-hosted runner (`gh-runner.mshome.net`). Audit artifacts retained 14 days.

**Sibling app repo:** `docs/superpowers/plans/` contains four detailed implementation plans for a sibling repo `agent-app-card-extractor` (at `D:\agent-app-card-extractor`) that wraps this harness as a library. Plans 1–4 cover backend, frontend, chat, and PyInstaller installer respectively. That repo is a separate project; its plans are stored here for reference.

## Recently Completed

**v0.2.1 (2026-05-13)**
- Fixed vendored prompt drift: `card_extractor/prompts/extraction_with_context.md` referenced deleted function `format_rules_for_injection(IssuerRules)`; re-vendored from upstream skill after fix.
- Removed `card_extractor.models.ReviewItem` (replaced by `review_queue` tool's `ReviewItem` in v0.2.0) and its corresponding test `tests/test_models.py::TestReviewItem::test_creation`.

**v0.2.0 (2026-05-13)**
- Replaced six inline implementations with toolbox packages: `agent-tool-pdf-vlm-renderer`, `agent-tool-knowledge-wiki`, `agent-tool-review-queue`, `agent-tool-pipeline-trace`, `agent-tool-token-tracker`, `agent-tool-llm-utils`.
- VLM prompts vendored from `vlm-card-extraction-prompts` skill into `card_extractor/prompts/` as `.md` files.
- Added `card_extractor/coords.py` to bridge normalized `BoundingBox` (VLM contract) to pixel `BoundingBox` (renderer boundary).
- Removed `card_extractor/rendering.py`, `wiki.py`, `review.py`, `trace.py` and their corresponding test files.
- Fixed `_durable()` unused parameter, dead code (`crop_front_boxes`, `format_rules_for_injection`), `knowledge/index.md` stub leak, `RENDER_DPI` documentation inconsistency, `scripts/run_batch.py` duplicate assignment.

## Known Issues

**JSONL trace key migration (breaking for downstream consumers):** The trace event key changed from `"event"` to `"event_type"` in v0.2.0 (inherent to the `pipeline_trace` tool API). Any downstream consumer grepping `"event":` in `_trace.jsonl` files must update to `"event_type":`.

**Review queue format is a breaking change from v0.1.0:** The `ReviewItem` shape changed. In-flight review queue items from v0.1.0 are NOT migrated. Drain the queue on v0.1.0 before upgrading a production deployment.

**Dark-background card detection gap:** Cards photographed on a dark surface fail detection because `autocontrast` cannot find edges. The fix (invert when >50% of pixels are below a threshold before the detection call) is documented in `docs/DESIGN.md §8` but not yet implemented. Parked until more dark-background samples are available.

**`compile_reviewed_to_wiki` reaches into `wiki._lock` (private attribute):** `card_extractor/review_workflow.py` acquires `wiki._lock` directly to serialize `promote_human_correction` against concurrent `write_observation` calls. This is fragile against upstream `knowledge_wiki` tool API changes. Documented in the module docstring.

**`RENDER_DPI` default is 300 (public reference) vs 200 (optimal for large pages):** Production deployments handling large-page PDFs should set `RENDER_DPI=200` to avoid 413 errors and reduce token cost (~45%). The public default matches the upstream `pdf_vlm_renderer` tool default. Documented in `docs/DESIGN.md §4`.

## Next Recommended Tasks

- [ ] Implement dark-background card inversion in `card_extractor/agent.py`: detect when >50% of pixels are below a threshold in `process_page()` and invert before the detection call. See `docs/DESIGN.md §8` for the design rationale. Requires dark-background sample fixtures in `fixtures/` to validate against.
- [ ] Replace the `wiki._lock` private-attribute access in `card_extractor/review_workflow.py::compile_reviewed_to_wiki`: track the upstream `agent-tool-knowledge-wiki` repo for a public API for sync-safe correction promotion, then remove the `async with wiki._lock:` workaround.
- [ ] Add auto-promotion of wiki observations to validation rules: after N consistent observations of the same masked pattern, promote to a regex rule in the frontmatter. Currently only human corrections write validation rules. See `docs/DESIGN.md §5` ("Future auto-promotion — planned, not implemented").
- [ ] Verify whether `tests/test_tools.py::TestWikiObservation` async tests are collected correctly: the class methods are `async def` but lack `@pytest.mark.asyncio` decorators — confirm `asyncio_mode = "auto"` in `pyproject.toml` covers class-level async methods under the installed `pytest-asyncio` version.
- [ ] Implement the `agent-app-card-extractor` sibling repo using the four plans in `docs/superpowers/plans/`. Plan 1 (backend) is the prerequisite for Plans 2–4.

## Verification Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Unit tests (no API key required)
pytest tests/ -k "not integration"

# Integration tests (requires AI_GATEWAY_KEY)
AI_GATEWAY_KEY=... pytest tests/ -m integration

# Batch CLI
AI_GATEWAY_KEY=... python scripts/run_batch.py --input ./input --output ./output

# Web service
AI_GATEWAY_KEY=... uvicorn card_extractor.app:app --reload
```

## Open Questions

- **Tool SHA pinning cadence:** The six toolbox tools in `[tool.uv.sources]` are pinned to specific git SHAs. There is no documented process for evaluating and updating these pins. Establish a review cadence or dependabot-equivalent for the PatientVibes tool repos.
- **`agent-tool-knowledge-wiki` lock API:** The `wiki._lock` workaround in `review_workflow.py` depends on the tool's internal implementation. If the tool adds a public sync-safe correction API, the workaround should be removed. Worth filing an issue upstream.
- **Integration test fixtures:** `tests/test_agent.py` looks for a sample PDF at `./fixtures/sample.pdf` or `./input/sample.pdf`. Neither path is committed. Confirm whether a fixture PDF should be added to the repo (with appropriate licensing) or whether integration tests are expected to be run only with user-supplied input.
