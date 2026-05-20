Now I have a thorough understanding of the repo. The manifests declare no runnable commands directly, but the `pyproject.toml` confirms the build system, test framework, and dependency structure. The commands in the current AGENTS.md use `pip install` while the repo uses `uv` (the audit workflow installs via `uv tool install` and the `[tool.uv.sources]` section is present). I'll note this as a `Needs verification` item per the hard rules, since the manifests themselves declare no explicit install/run commands.

# Agent Instructions

Cross-tool agent configuration for the Card Extractor agent.
Compatible with Claude Code, OpenAI Codex, Cursor, and other AAIF-compliant tools.

## Repository purpose

ID card and insurance card data extraction pipeline using a LangChain agent harness with VLM (Vision Language Model) calls, a Karpathy-style knowledge wiki, and human-in-the-loop review. The service exposes a FastAPI web interface (`card_extractor/app.py`) and a batch script runner (`scripts/run_batch.py`). It is part of the PatientVibes agent-toolbox ecosystem and depends on six toolbox libraries pinned by git SHA.

**License: MIT.** See [LICENSE](./LICENSE). Third-party dependencies must remain permissively licensed (MIT, Apache-2.0, BSD-3-Clause, HPND); never add AGPL/GPL — this keeps the project freely redistributable.

## Build and test commands

> **Needs verification:** The repo's `pyproject.toml` uses `[tool.uv.sources]` and the CI workflow installs via `uv tool install`. The commands below use `pip install`; if the project is managed with `uv`, substitute `uv pip install` or `uv sync` as appropriate for the local environment. The manifests declare no explicit install/run commands.

```bash
pip install -e ".[dev]"
pytest tests/ -k "not integration"                        # unit tests (no API key needed)
AI_GATEWAY_KEY=... pytest tests/ -m integration            # integration tests
AI_GATEWAY_KEY=... python scripts/run_batch.py --input ./input --output ./output
AI_GATEWAY_KEY=... uvicorn card_extractor.app:app --reload  # web service
```

- 54 unit tests in `tests/`, no API key needed for unit tests.
- Integration tests are marked `@pytest.mark.integration` and require `AI_GATEWAY_KEY`.
- `pytest` is configured via `[tool.pytest.ini_options]` in `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`.
- Experiment parameter sweeps: `scripts/experiment.py`.

## Working rules

- `from __future__ import annotations` in every module.
- Type hints throughout; Pydantic v2 models for all data shapes.
- `card_extractor/models.py` is the single source of truth for data structures — no model definitions elsewhere.
- Prompts composed from shared bases in `card_extractor/prompts.py` — no copy-paste duplication.
- Async pipeline with `asyncio` — all VLM calls are async.
- Logging via the `logging` module, not `print` statements.
- API keys are never stored in code; always via the `AI_GATEWAY_KEY` environment variable.
- Every VLM call must be tracked via `TokenTracker` and recorded in the pipeline trace.

## Scope discipline

- Do not refactor working pipeline stages without a clear bug or requirement driving the change.
- Do not move model definitions out of `card_extractor/models.py` or prompt definitions out of `card_extractor/prompts.py`.
- Do not add new top-level runtime dependencies without verifying their license is MIT, Apache-2.0, BSD, or similarly permissive.
- Do not touch files listed under [Files agents must not modify](#files-agents-must-not-modify).

## Architecture notes

**Context split — DurableContext vs AgentContext:**
- `DurableContext` (shared, built once in FastAPI `lifespan`): holds `GatewayConfig`, `KnowledgeWiki`, `ReviewWorkflow`, base output dir, and tunables.
- `AgentContext` (request-scoped): built per-request via `AgentContext.for_request(durable, run_id)`, giving each request a fresh `TokenTracker`, a fresh `PipelineTrace`, and a per-run output subdirectory. Never share `AgentContext` across requests.
- Scripts (`run_batch.py`, `run_pass2.py`, `experiment.py`) use `AgentContext.from_env()` directly (no FastAPI lifespan).

**Structured output:** All VLM calls use `with_structured_output(PydanticModel, include_raw=True)` — no regex parsing of free-text JSON.

**No PyMuPDF:** Use `pypdfium2` for PDF rendering (Apache-2.0; replaces AGPL PyMuPDF). `pypdfium2`, `Pillow`, and `PyYAML` are transitive via the toolbox tools, not top-level dependencies.

**Wiki rules schema:** Wiki rules live in YAML frontmatter (parsed via `yaml.safe_load` + `IssuerRules` Pydantic model). The markdown body is never parsed as rules. Every regex is compiled and validated before a write is accepted.

**Wiki locking:** `KnowledgeWiki` holds its own `asyncio.Lock` for `write_observation` and `update_index` (both async). `promote_human_correction` is sync and does NOT acquire that lock; `ReviewWorkflow.compile_reviewed_to_wiki` wraps each call in `async with wiki._lock:` per-item to serialize against concurrent agent-loop observation writes.

**Toolbox dependencies** (pinned by git SHA in `[tool.uv.sources]`):
- `agent-tool-pdf-vlm-renderer`
- `agent-tool-knowledge-wiki`
- `agent-tool-review-queue`
- `agent-tool-pipeline-trace`
- `agent-tool-token-tracker`
- `agent-tool-llm-utils`

**Pipeline flow:**
```
PDF -> render (pypdfium2) -> preprocess (autocontrast)
    -> detect cards (VLM) -> [if none: full-page fallback]
    -> crop -> smart verify (only Unknown labels, skip Front)
    -> wiki lookup -> extract (VLM + structured output)
    -> validate -> verify loop -> conditional audit
    -> wiki update -> trace log -> output JSON
```

**Key patterns:**
- Tools as closures over `AgentContext`.
- Evaluator audit step: VLM counts cards on page, compares to extraction count; only fires when some crops failed extraction.
- Full-page fallback when detection finds no card boundaries.
- Smart verification: skip VLM verify for Front-labeled boxes, only verify Unknown-labeled boxes (~9% token saving).
- Karpathy wiki: observations + human corrections compiled into per-issuer markdown knowledge base under `knowledge/issuers/`.
- YAML frontmatter as machine-readable rules; markdown body as human/LLM context — single file, deterministic parsing, no string scraping.
- Wiki re-extraction only fires when the wiki page has explicit `patterns` or `required_fields` rules; observation text alone is not sufficient.

## Output artifacts

Each pipeline run produces artifacts under `<output_dir>/<run_id>/`:
- `{stem}_boxed_N.json` — extraction results (the product)
- `_trace.jsonl` — structured pipeline trace (every decision, call, timing)
- `run_manifest.json` — experiment config + aggregate metrics
- `_progress.json` — checkpoint for resume
- `knowledge/issuers/*.md` — wiki pages (persistent across runs)
- `review_queue/*.json` — items flagged for human review

## Files agents must not modify

- `knowledge/schema.md` — immutable wiki rules schema (version controlled)
- `knowledge/index.md` — wiki index managed by `KnowledgeWiki`; do not edit directly
- Any `.env` file — contains secrets

## Known pitfalls

- **Token bleed:** Never reuse an `AgentContext` across requests. The `TokenTracker` and `PipelineTrace` on `AgentContext` are per-request; sharing them causes cumulative token counts and trace corruption.
- **Wiki lock contention:** `promote_human_correction` is sync and does not acquire `wiki._lock`. Always wrap it in `async with wiki._lock:` when calling from async code that may race with `write_observation`.
- **Regex validation:** All regexes in wiki YAML frontmatter are compiled and validated at write time. A malformed regex will raise at `IssuerRules` construction, not at query time.
- **Audit is conditional:** The audit step only runs when `actual_extractions < expected_extractions`. Do not assume it always fires.
- **Full-page fallback:** When detection finds no cards, the pipeline falls back to treating the entire page as a single card crop. This can produce low-confidence extractions that land in the review queue.
- **Checkpoint resume:** `load_checkpoint` returns `{}` for a missing or `None` path, so `BatchProgress(**load_checkpoint(...))` safely yields a default `BatchProgress()` when no checkpoint exists.
- **License gate:** The CI audit workflow (`audit.yml`) runs `repo-doc-gov audit --fail-on high` on every PR and push to `master`. High or Blocker drift findings block merge.

## Handoff expectations

After making changes, report:
1. Which files were modified and why.
2. Whether `pytest tests/ -k "not integration"` passes (all 54 unit tests green).
3. Whether any new dependencies were added and their licenses.
4. Whether any `card_extractor/models.py` or `card_extractor/prompts.py` interfaces changed (downstream tools may be affected).
5. Any wiki schema or `IssuerRules` model changes (affects all existing wiki pages).
