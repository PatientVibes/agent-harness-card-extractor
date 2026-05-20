# AGENTS.md

ID card and insurance card data extraction pipeline. A LangChain agent harness accepts PDF uploads, renders pages via `pypdfium2`, detects card regions with a VLM, crops and extracts structured data using `with_structured_output`, validates against a Karpathy-style knowledge wiki, flags low-confidence results for human review, and writes a structured JSONL trace of every decision. The project is MIT-licensed; all dependencies must remain permissively licensed.

## Build and test

```bash
pip install -e ".[dev]"
pytest tests/ -k "not integration"                        # unit tests (no API key needed)
AI_GATEWAY_KEY=... pytest tests/ -m integration            # integration tests
AI_GATEWAY_KEY=... python scripts/run_batch.py --input ./input --output ./output
AI_GATEWAY_KEY=... uvicorn card_extractor.app:app --reload  # web service
```

## Working rules

- **License**: All dependencies must be MIT, Apache-2.0, BSD-3-Clause, or HPND. Never add AGPL/GPL — this keeps the project freely redistributable.
- **No PyMuPDF**: Use `pypdfium2` for PDF rendering (Apache-2.0; PyMuPDF is AGPL).
- **Structured output only**: All VLM calls use `with_structured_output(PydanticModel, include_raw=True)`. No regex parsing of free-text JSON.
- **API keys**: Never stored in code. Always via the `AI_GATEWAY_KEY` environment variable.
- **Token tracking**: Every VLM call must be tracked via `TokenTracker` and recorded in the trace.
- **Request isolation**: Request-scoped state (`TokenTracker`, `PipelineTrace`, output subdir) must be built per-request via `AgentContext.for_request(durable, run_id)`. Never share these across requests. Shared long-lived state belongs in `DurableContext`.
- **Logging**: Use the `logging` module. No `print` statements in library code.
- **`from __future__ import annotations`** in every module.

## Scope discipline

- Do not refactor working pipeline code unless a bug or test failure requires it.
- Do not add dependencies without checking license compatibility first.
- Do not move model definitions out of `card_extractor/models.py` or prompt definitions out of `card_extractor/prompts/`.
- Do not edit vendored prompt `.md` files in `card_extractor/prompts/` — edit upstream in the skill repo and re-vendor.

## Architecture notes

**Context split**: `DurableContext` (shared, built once in FastAPI `lifespan`) holds `GatewayConfig`, `KnowledgeWiki`, `ReviewWorkflow`, output dir, and tunables. `AgentContext` (request-scoped, built via `AgentContext.for_request(durable, run_id)`) adds a fresh `TokenTracker`, a fresh `PipelineTrace`, and a per-run output subdirectory. Scripts (`run_batch.py`, `run_pass2.py`, `experiment.py`) use `AgentContext.from_env()` directly.

**Pipeline flow**:
```
PDF -> render (pypdfium2) -> preprocess (autocontrast)
    -> detect cards (VLM) -> [if none: full-page fallback]
    -> crop -> smart verify (only Unknown labels, skip Front)
    -> wiki lookup -> extract (VLM + structured output)
    -> validate -> verify loop -> conditional audit
    -> wiki update -> trace log -> output JSON
```

**Key patterns**:
- Smart verification: skip VLM verify for Front-labeled boxes; only verify Unknown-labeled boxes (~9% token saving).
- Conditional audit: evaluator VLM counts cards on page and compares to extraction count; only fires when some crops failed extraction.
- Full-page fallback: when detection finds no card boundaries, or when audit detects a mismatch.
- Wiki re-extraction: only re-extracts with wiki context when the issuer's wiki page has explicit `patterns` or `required_fields` rules — observation text alone is skipped to avoid burning tokens without accuracy gain.
- `KnowledgeWiki` holds its own `asyncio.Lock` for `write_observation` and `update_index` (both async). `promote_human_correction` is sync and does NOT acquire that lock. `ReviewWorkflow.compile_reviewed_to_wiki` wraps each `promote_human_correction` call in `async with wiki._lock:` to serialize against concurrent agent-loop observation writes.

**Toolbox dependencies** (pinned by git SHA in `[tool.uv.sources]`):
`agent-tool-pdf-vlm-renderer`, `agent-tool-knowledge-wiki`, `agent-tool-review-queue`, `agent-tool-pipeline-trace`, `agent-tool-token-tracker`, `agent-tool-llm-utils`. `pypdfium2`, `Pillow`, and `PyYAML` are transitive via the tools — do not add them as top-level deps.

**Wiki schema**: Rules live in YAML frontmatter (parsed via `yaml.safe_load` + `IssuerRules` Pydantic model). The markdown body is never parsed as rules. Every regex is compiled and validated before a write is accepted (`IssuerRules.validate_patterns()`). `card_extractor/models.py` is the single source of truth for `IssuerRules`.

**Prompts**: Loaded from `card_extractor/prompts/*.md` at import time via `card_extractor/prompts.py`. Composed from shared bases — no copy-paste duplication.

## Code style

- Python 3.11+, `from __future__ import annotations` in every module.
- Type hints throughout; Pydantic v2 models for all data shapes.
- `card_extractor/models.py` is the single source of truth for all data structures — no model definitions elsewhere.
- Async pipeline with `asyncio`; all VLM calls are async.

## Files agents must not modify

- `knowledge/schema.md` — immutable wiki rules schema (version controlled)
- `card_extractor/prompts/*.md` — vendored prompt files; edit upstream in the skill repo
- Any `.env` file — contains secrets

## Output artifacts

Each pipeline run produces:
- `{stem}_boxed_N.json` — extraction results
- `_trace.jsonl` — structured pipeline trace (every decision, call, timing)
- `run_manifest.json` — experiment config and aggregate metrics
- `_progress.json` — checkpoint for resume
- `knowledge/issuers/*.md` — wiki pages (persistent across runs)
- `review_queue/*.json` — items flagged for human review

## Testing

- Unit tests in `tests/` require no API key: `pytest tests/ -k "not integration"`
- Integration tests marked `@pytest.mark.integration` require `AI_GATEWAY_KEY`
- `scripts/experiment.py` — parameter sweep runner
- `scripts/run_pass2.py` — measures wiki learning effect (pass 1 wiki → pass 2 accuracy)

## Handoff expectations

After making changes, report:
1. Which files were modified and why.
2. Whether `pytest tests/ -k "not integration"` passes.
3. Any new dependencies added and their licenses.
4. Whether any `DurableContext`/`AgentContext` isolation boundaries were touched (flag explicitly — token bleed across requests is a known failure mode).
5. Whether any wiki write paths were changed (flag `wiki._lock` usage if altered).

## Known pitfalls

- **Token bleed**: Module-level or class-level `TokenTracker`/`PipelineTrace` singletons will accumulate counts across requests. Always use `AgentContext.for_request(durable, run_id)` in the FastAPI path.
- **Wiki lock**: `promote_human_correction` is sync and lock-free. Any caller that runs it concurrently with `write_observation` must hold `wiki._lock` explicitly (see `ReviewWorkflow.compile_reviewed_to_wiki`).
- **Coordinate systems**: `card_extractor.models.BoundingBox` uses normalized 0–1 coords. `pdf_vlm_renderer.BoundingBox` uses pixel coords with confidence. Convert at the rendering boundary only via `card_extractor.coords.norm_to_px` / `norm_to_px_for_image`.
- **Wiki re-extraction gate**: Only re-extract with wiki context when `patterns` or `required_fields` are present. Skipping this gate burns tokens on observation-only pages with no accuracy benefit.
- **Prompt files are vendored**: Do not edit `card_extractor/prompts/*.md` directly. Changes will be overwritten on the next re-vendor.
- **`fixtures/` directory**: Currently empty in the repo; integration tests look for `./fixtures/sample.pdf` or `./input/sample.pdf` and skip if absent.
