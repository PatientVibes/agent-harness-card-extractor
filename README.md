# agent-harness-card-extractor

ID card and insurance card data extraction agent. Processes scanned PDFs containing government IDs and insurance cards through a LangChain agent harness with structured output, a Karpathy-style knowledge wiki, and a human review loop.

Reference implementation of the **12-component agent harness pattern** for VLM-driven document extraction.

## Architecture

Sequential pipeline with agent reasoning at decision points. Not a full ReAct loop — each stage runs a deterministic step or a single focused VLM call, keeping latency predictable and token usage low.

### Pipeline flow

```
+------------------+
|   Input PDFs     |
+--------+---------+
         |
1. RENDER (pypdfium2)
PDF pages -> PNG at configured DPI
         |
+--------v---------+
|  Page PNGs       |
+--------+---------+
         |
2. DETECT (VLM)
Locate card regions, return bounding boxes
with Front/Back labels + confidence scores
Output: CardRegion (Pydantic structured)
         |
+--------v---------+
|  Cropped Cards   |
+--------+---------+
         |
3. VERIFY (VLM)
Each crop -> FRONT / BACK / NOT_A_CARD
Filter out backs and non-cards
         |
+--------v---------+
|  Verified Fronts |
+--------+---------+
         |
4. EXTRACT (VLM + wiki context)
Wiki lookup by issuer_hint -> inject known
field patterns as system context
Output: CardExtraction (Pydantic structured)
         |
+--------v---------+
|  Raw Extractions |
+--------+---------+
         |
5. VALIDATE (deterministic)
Hallucination filters (placeholder IDs,
sequential digits, known bad dates)
+ wiki-derived regex checks
         |
     +---+---+
     |       |
  >threshold  <threshold
     |       |
+----v---+ +-v-------------+
| Output | | Review Queue  |
| JSON   | | review_queue/ |
+--------+ +-------+-------+
                   |
          Human corrects extraction
                   |
          +--------v--------+
          |  Wiki Update    |
          |  knowledge/     |
          +-----------------+
```

### Evaluator audit

After the main pipeline, an evaluator step re-examines the original page image against the list of detected cards. If the evaluator spots cards that were missed during detection, they are sent back through stages 3–5. This catches edge cases where the initial detection prompt fails on unusual card layouts.

## Setup

Requirements: Python 3.11+

```bash
git clone https://github.com/PatientVibes/agent-harness-card-extractor.git
cd agent-harness-card-extractor
uv pip install -e ".[dev]"
```

## Usage

```bash
# Web UI
uvicorn card_extractor.app:app --reload --port 8000

# Batch
python scripts/run_batch.py --input ./input/ --output ./output/
```

## Configuration (env vars)

| Variable | Default | Description |
|---|---|---|
| `AI_GATEWAY_URL` | — | OpenAI-compatible VLM gateway URL |
| `AI_GATEWAY_KEY` | — | API key |
| `VLM_MODEL` | — | Vision model ID |
| `TEXT_MODEL` | — | Text model ID (non-vision calls) |
| `RENDER_DPI` | `300` | PDF page render DPI |
| `CROP_PAD_PX` | `10` | Padding in pixels added around each cropped card region |
| `VLM_TEMPERATURE` | `0.1` | Temperature for detection and verification VLM calls |
| `EXTRACTION_TEMPERATURE` | `0.0` | Temperature for extraction VLM calls |
| `DETECTION_CONFIDENCE` | `0.85` | Min confidence for card detection |
| `REVIEW_CONFIDENCE_THRESHOLD` | `0.7` | Flag for human review below this |
| `MAX_RETRY_ATTEMPTS` | `1` | Number of extraction retries with issue feedback |
| `MAX_CONCURRENT` | `5` | Max number of PDFs processed concurrently |
| `WIKI_DIR` | `./knowledge` | Karpathy-style learning wiki location |
| `REVIEW_QUEUE_DIR` | `./review_queue` | Human-review queue location |
| `OUTPUT_DIR` | `./output` | Extracted-JSON output location |
| `ENABLE_AUDIT` | `1` | Enable the evaluator audit step (VLM card-count check). Set to `0` to disable. |
| `ENABLE_PREPROCESSING` | `1` | Enable image autocontrast preprocessing before VLM calls. Set to `0` to disable. |

## 12-component harness implementation

| Component | Implementation |
|---|---|
| Orchestration | Sequential per-page pipeline + orchestrator dispatching subagents for parallel PDFs |
| Tools | Composed from toolbox repos: `pdf_vlm_renderer` (PDF → PNG + crop + debug overlay) + `knowledge_wiki` (issuer wiki) + `review_queue` + `review_workflow.py` (flag → pending → reviewed lifecycle) + `pipeline_trace` (JSONL events) + vendored VLM prompts under `card_extractor/prompts/` |
| Memory | `knowledge_wiki.KnowledgeWiki` (Karpathy-style per-issuer page accumulation) |
| Context mgmt | Wiki lookup gates re-extraction with known patterns; otherwise no LLM-side context |
| Prompt construction | VLM prompts vendored from the `vlm-card-extraction-prompts` skill into `card_extractor/prompts/` as `.md` files (DETECTION, VERIFICATION, EXTRACTION, EXTRACTION_RETRY, EXTRACTION_WITH_CONTEXT, AUDIT) |
| Output parsing | Pydantic models (`CardRegion`, `CardSideVerdict`, `CardExtraction`, `AuditResult`, `ValidationResult`) |
| State | `llm_utils.save_checkpoint` / `load_checkpoint` with `BatchProgress` JSON wrap; wiki files versioned per issuer |
| Error handling | `llm_utils.retry_async` with `not is_transient(...)` as the fatal classifier; per-PDF subagent isolation |
| Guardrails | Validation filters (placeholder IDs, sequential digits); confidence-adjustment from validation |
| Verification | `_verify_extraction` + 1 retry with issue feedback; conditional page audit |
| Subagent orchestration | Semaphore-bounded `_subagent` per PDF; `_full_page_fallback` when detection finds no cards |
| Token tracking | `token_tracker.TokenTracker` records every VLM call; `pipeline_trace.PipelineTrace` writes JSONL trace per run via generic `trace.event(event_type=..., ...)` |

## Related projects

- [`agent-app-card-extractor`](https://github.com/PatientVibes/agent-app-card-extractor) — installable desktop-style sibling app built on this harness. Provides a file-drop UI, JSON/XML previewer, WebSocket chat for interactive field corrections, and a PyInstaller single-file installer. Consumes this harness as a versioned pip dependency. The spec and per-plan implementation docs for that project live in [`docs/superpowers/`](docs/superpowers/) in this repo.

## Related skills

- [`vlm-card-extraction-prompts`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/vlm-card-extraction-prompts) — the 6 VLM prompts under `card_extractor/prompts/` are vendored verbatim from this skill. Edit upstream + re-vendor; do not edit the .md files in this dir.
- [`verification-retry-loop`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/verification-retry-loop) — pattern reference for the harness's VLM detection → verification → extraction loop.
- [`human-review-loop`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/human-review-loop) — pattern reference for the flag → pending → reviewed lifecycle implemented by `review_workflow.py` on top of `agent-tool-review-queue`.

## License

MIT. See `LICENSE`.

## Origin

Reference implementation extracted from a discontinued client POC. Generalized and published as open source under personal copyright.
