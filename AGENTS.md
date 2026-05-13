# AGENTS.md

Cross-tool agent configuration for the Card Extractor agent.
Compatible with Claude Code, OpenAI Codex, Cursor, and other AAIF-compliant tools.

## Project

ID card and insurance card data extraction pipeline using a LangChain agent harness with VLM (Vision Language Model) calls, a Karpathy-style knowledge wiki, and human-in-the-loop review.

**License: MIT.** See [LICENSE](./LICENSE). Third-party dependencies must remain permissively licensed (MIT, Apache-2.0, BSD-3-Clause, HPND); never add AGPL/GPL — this keeps the project freely redistributable.

## Build and test

```bash
pip install -e ".[dev]"
pytest tests/ -k "not integration"                       # unit tests (no API key)
AI_GATEWAY_KEY=... pytest tests/ -m integration           # integration tests
AI_GATEWAY_KEY=... python scripts/run_batch.py --input ./input --output ./output
AI_GATEWAY_KEY=... uvicorn card_extractor.app:app --reload   # web service
```

## Code style

- Python 3.11+, `from __future__ import annotations` in every module
- Type hints throughout, Pydantic v2 models for all data shapes
- `card_extractor/models.py` is the single source of truth for data structures — no model definitions elsewhere
- Prompts composed from shared bases in `card_extractor/prompts.py` — no copy-paste duplication
- Async pipeline with `asyncio` — all VLM calls are async
- Logging via `logging` module, not print statements

## Architecture constraints

- **Licensing**: All dependencies must be MIT, Apache-2.0, BSD, or similarly permissive. No AGPL/GPL.
- **No PyMuPDF**: Use `pypdfium2` for PDF rendering (Apache-2.0 replaces AGPL).
- **Structured output**: All VLM calls use `with_structured_output(PydanticModel, include_raw=True)` — no regex parsing of free-text JSON.
- **API keys**: Never stored in code. Always via `AI_GATEWAY_KEY` environment variable.
- **Token tracking**: Every VLM call must be tracked via `TokenTracker` and recorded in the trace.
- **Wiki rules schema**: Wiki rules live in YAML frontmatter (parsed via `yaml.safe_load` + `IssuerRules` Pydantic model). The markdown body is never parsed as rules. Every regex is compiled and validated before a write is accepted.
- **Request isolation**: Request-scoped state (`TokenTracker`, `PipelineTrace`, output subdir) must be built per-request via `AgentContext.for_request(durable, run_id)`, not shared across requests. Shared long-lived state belongs in `DurableContext`.
- **Dependencies**: Top-level runtime deps are `fastapi`, `uvicorn`, `httpx`, `langchain-core`, `langchain-openai`, `pydantic`, `python-dotenv`, plus the 6 toolbox tools (`agent-tool-pdf-vlm-renderer`, `agent-tool-knowledge-wiki`, `agent-tool-review-queue`, `agent-tool-pipeline-trace`, `agent-tool-token-tracker`, `agent-tool-llm-utils`) pinned by git SHA via `[tool.uv.sources]`. `pypdfium2`, `Pillow`, `PyYAML` are transitive via the tools, not top-level. No AGPL.

## Pipeline flow

```
PDF -> render (pypdfium2) -> preprocess (autocontrast)
    -> detect cards (VLM) -> [if none: full-page fallback]
    -> crop -> smart verify (only Unknown labels, skip Front)
    -> wiki lookup -> extract (VLM + structured output)
    -> validate -> verify loop -> conditional audit
    -> wiki update -> trace log -> output JSON
```

## Key patterns

- Tools as closures over `AgentContext`
- Evaluator audit step: VLM counts cards on page, compares to extraction count
- Full-page fallback when detection finds no card boundaries
- Smart verification: skip VLM verify for Front-labeled boxes, only verify Unknown
- Karpathy wiki: observations + human corrections compiled into markdown knowledge base
- `DurableContext` (shared, built in FastAPI `lifespan`) vs `AgentContext` (request-scoped, built via `AgentContext.for_request(durable, run_id)`) — long-lived state separated from per-request state
- YAML frontmatter as machine-readable rules; markdown body as human/LLM context — single file, deterministic parsing, no string scraping
- `knowledge_wiki.KnowledgeWiki` holds its own `asyncio.Lock` for `write_observation` + `update_index` (both async). `promote_human_correction` is sync and does NOT acquire that lock; the harness's `ReviewWorkflow.compile_reviewed_to_wiki` wraps each call in `async with wiki._lock:` per-item to serialize against concurrent agent-loop observation writes.

## Testing

- 55 unit tests in `tests/`, no API key needed
- Integration tests marked `@pytest.mark.integration` require `AI_GATEWAY_KEY`
- Experiment runner at `scripts/experiment.py` for parameter sweeps

## Files agents should not modify

- `knowledge/schema.md` — immutable wiki rules (version controlled)
- `fixtures/` — input test fixtures
- Any `.env` file — contains secrets

## Output artifacts

Each pipeline run produces:
- `{stem}_boxed_N.json` — extraction results (the product)
- `_trace.jsonl` — structured pipeline trace (every decision, call, timing)
- `run_manifest.json` — experiment config + aggregate metrics
- `_progress.json` — checkpoint for resume
- `knowledge/issuers/*.md` — wiki pages (persistent across runs)
- `review_queue/*.json` — items flagged for human review
