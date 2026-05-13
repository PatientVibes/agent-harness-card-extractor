# Design Document: Card Extractor Agent

**Audience:** Engineers inheriting or evaluating this codebase.
**Purpose:** Explain *why* each decision was made. The code shows what we built; this document explains why we built it that way and what we rejected.

**License:** MIT. See [../LICENSE](../LICENSE). The original implementation was built under a redistributable-commercial constraint, which drives several design decisions below (notably the PyMuPDF → pypdfium2 swap and the exclusion of AGPL/GPL dependencies throughout). Those constraints still serve the open-source posture: the project stays freely redistributable.

---

## 1. The Problem

The original POC works: it extracts structured data from scanned PDFs of government IDs and insurance cards using three sequential VLM API calls. But it has properties that make it unsuitable for a production service:

- **AGPL-licensed dependency** (PyMuPDF / `fitz`). The AGPL forces source disclosure of any application that links against it, including over a network. That's incompatible with freely redistributable code.
- **Regex JSON parsing** of VLM output. The VLM is instructed to emit a specific text format, which is then parsed with regex. One formatting drift and the whole pipeline fails silently.
- **No learning loop.** Every PDF is processed from scratch. Corrections from human reviewers have nowhere to go.
- **No structured output contract.** Fields come back as strings in a dict. No confidence scores, no issuer identification, no type safety.
- **No batch isolation.** A single bad PDF can halt processing on 500 PDFs.
- **No observability.** Print statements only. Can't answer "why did this extraction fail?" after the fact.
- **Three VLM calls per card** (detect → verify front/back → extract). The verification step exists because the indexing step's Front/Back labeling isn't trusted — paying for a second call to compensate for weak output.

Fixing each of these in isolation would produce a slightly better POC. We instead rebuilt the pipeline as an **agent harness** — the patterns that come from Anthropic's "Building Effective Agents," LangChain's Deep Agents, and the production harness literature. This document explains each decision.

---

## 2. The Framing: Agent Harness, Not Agent Framework

### What we rejected: a full ReAct agent

The instinct on hearing "agent" is to reach for `create_react_agent()` and let an LLM plan the whole pipeline. We rejected that. Card extraction has a **fixed, well-understood flow**: render the PDF, find the cards, extract the fields, validate. The order doesn't vary by input. Having an LLM "decide" to crop before detecting is wasted reasoning — it's always going to be detect-then-crop.

Anthropic's guidance from "Building Effective Agents": *"find the simplest solution possible, and only increase complexity when needed."* For this problem, that means deterministic orchestration with LLM calls at the points that require judgment (what's on the card, what field is what).

### What we built: a sequential pipeline with agent reasoning at decision points

```
PDF → render (code) → preprocess (code) → detect (VLM)
    → [fallback if empty: full-page extraction (VLM)]
    → crop (code) → smart verify (VLM, conditional)
    → extract (VLM, structured output)
    → validate (code) → retry (VLM, on failure)
    → audit (VLM, conditional) → wiki update (code)
```

This is what the literature calls an **agentic workflow** (pre-defined orchestration, LLM nodes) rather than an **agentic system** (LLM decides the whole flow). Workflows are more predictable, debuggable, and cheaper. We reserve LLM autonomy for the decision points that truly need it.

### Pattern reference

The overall structure implements the 12-component agent harness pattern catalogued in Akshay Pachaar's "Anatomy of an Agent Harness" article: orchestration loop, tools with schemas, memory, context management, prompt construction, output parsing, state management, error handling, guardrails, verification loops, subagent orchestration, token tracking. We map to all twelve.

---

## 3. Stack Choices and Why

### Framework: LangChain (MIT), not LangGraph Platform

We use `langchain-core` and `langchain-openai` for the VLM calls and structured output binding. Both are MIT-licensed. We considered `langgraph` (also MIT, the library form) but removed it from dependencies when it became clear we weren't using its graph primitives — a sequential pipeline with plain `async` functions is simpler and doesn't need a graph runtime.

We explicitly avoided **LangGraph Platform / LangSmith Cloud** — those are proprietary SaaS. Staying with the open-source libraries means the commercial licensing story is clean and there's no vendor lock-in for observability.

### PDF rendering: pypdfium2 (Apache-2.0), not PyMuPDF

The POC used `fitz` (PyMuPDF), which is dual-licensed AGPL-3.0 / commercial. AGPL-3.0 propagates through network distribution, so any application that imports PyMuPDF must adopt AGPL terms. That's incompatible with the MIT posture here.

`pypdfium2` wraps PDFium (Google's Chrome PDF engine) and is dual-licensed Apache-2.0 / BSD-3-Clause. It produces equivalent PDF-to-image rendering at comparable speed. The swap was mechanical.

### Image processing: Pillow (HPND, permissive)

Standard choice. The HPND (Historical Permission Notice and Disclaimer) license is effectively equivalent to MIT.

### VLM: Qwen/Qwen2.5-VL-32B via an OpenAI-compatible gateway

The original deployment used an enterprise OpenAI-compatible VLM gateway with `X-API-Key` authentication. Any OpenAI-compatible endpoint (vLLM, llama.cpp server, hosted gateways) works the same way. We tested the larger `qwen.qwen3-vl-235b-a22b` (via AWS Bedrock) and found it doesn't support tool calling, which breaks `with_structured_output()`. Qwen2.5-VL-32B is the pragmatic choice: structured output works, Vision is strong enough, cost is low ($0.0003/1K tokens).

### Structured output: Pydantic + `with_structured_output(include_raw=True)`

This is the single most important architectural choice and the one that most distinguishes the harness from the POC.

The POC prompts the VLM to produce JSON as free text, then parses with regex. Every prompt has to re-explain the exact output format. Every VLM formatting drift breaks parsing.

The harness defines a Pydantic model (`CardExtraction`) and binds it to the LLM. LangChain translates the schema into a tool definition, and the VLM invokes the tool. The return value is a validated Pydantic instance — not a string to parse. This means:

- Schema is version-controlled in code, not in prompts
- Field types (Literals, floats with bounds) are enforced
- Prompt tokens shrink because we no longer need to describe format
- Parsing never fails on formatting drift

We use `include_raw=True` so we can still access `usage_metadata` for token tracking. Without it, the raw response is discarded and we'd have no cost visibility.

Wiki rules are also structured output: they live as YAML frontmatter on each issuer page and are parsed into a Pydantic `IssuerRules` model (`card_extractor/models.py`). The markdown body is never parsed for rules. See §5.

### YAML frontmatter: PyYAML 6.0 (MIT)

Used only in `card_extractor/wiki.py` to parse the machine-readable rules block at the top of each issuer page. `yaml.safe_load` only — no arbitrary-tag deserialization. Single dependency addition.

### Web framework: FastAPI (MIT)

Thin REST layer. We picked FastAPI over Flask because: first-class async (matches our pipeline), automatic OpenAPI docs, Pydantic-native validation, and it's the de facto default for new Python services in 2025. No strong reason it had to be FastAPI over Starlette or similar — this is a low-stakes choice.

### Testing: pytest + pytest-asyncio

Standard choice. Integration tests are marked `@pytest.mark.integration` so the main suite runs without an API key (71 unit tests, 4s). Integration tests (which make real VLM calls) gate behind `AI_GATEWAY_KEY`.

---

## 4. The Pipeline, Step by Step (and Why)

### Step 1: Render (pypdfium2)

PDF → PNG at 300 DPI (the `pdf_vlm_renderer` tool default; tunable via the `RENDER_DPI` env var). Earlier POC experiments lowered this to 200 DPI to:
- Eliminate 413 Payload Too Large failures for large pages
- Reduce tokens per VLM call by ~45%
- Without hurting extraction accuracy (card text is large enough at 200 DPI)

The public reference defaults to 300 to match the upstream `pdf_vlm_renderer` default; production deployments dealing with large pages should set `RENDER_DPI=200`.

This is a **deterministic, code-only** step. No LLM involved.

### Step 2: Preprocess (Pillow autocontrast)

We apply `ImageOps.autocontrast(cutoff=1)` before VLM calls. This normalizes the histogram, which helps with faded/washed-out scans that would otherwise look flat to the VLM.

Visual inspection found ~30% of our sample PDFs had faded or darkened photocopies. The autocontrast pass catches those. It's cheap (milliseconds) and has no false-positive risk — if the image is already good, the transform is near-identity.

We do **not** yet handle dark-background scans (e.g., cards photographed on a black table). That requires inversion detection, which is a known gap.

### Step 3: Detect (VLM + structured output)

One VLM call per page. Returns a `CardRegion` Pydantic model with a list of bounding boxes, each tagged `Front`, `Back`, or `Unknown`. Coordinates are normalized [0, 1] with a Pydantic field validator that clamps to handle the VLM occasionally returning 1.01 or -0.005.

The detection prompt is intentionally shorter than the POC's (which was 60+ lines of formatting rules). Since structured output handles the serialization, we only describe the task and the decision criteria.

### Step 3b: Full-page fallback

If detection returns zero boxes, we don't give up. Many cards in the sample set **fill the entire page** — there's no card border visible because the card *is* the page. Detection can't find a boundary that doesn't exist.

The fallback simply treats the whole page as a candidate crop and runs it through extraction. This recovered ~10 cards in our test set that the POC and early versions of the agent both missed.

### Step 4: Crop (Pillow)

Deterministic. We crop Front-labeled and Unknown-labeled boxes (skipping Back). Padding is 5 pixels after experiments found pad=0 caused catastrophic retry loops (card edges cut off) and pad=20 added noise without helping.

### Step 5: Smart verification (VLM, conditional)

Here's a nuance worth explaining carefully.

**Pre-enhancement behavior**: every crop went through a "backside veto" VLM call regardless of how detection labeled it. The POC did the same. We measured 0 vetoes out of 12 calls on our first run — the verification step was running purely on Front-labeled crops and never rejecting anything. Pure waste.

**Current behavior**: we **only** run the veto on Unknown-labeled crops. Front-labeled crops skip the VLM call entirely (detection was already pretty sure). This saves ~9% of total tokens.

We also rewrote the veto prompt to be a **true veto** (default to "pass", only reject on clear back-side evidence) rather than a classifier (pick Front or Back). The POC's framing was accidentally rejecting faded but valid fronts.

### Step 6: Extract (VLM + Pydantic structured output)

The core of the pipeline. Takes a card crop, returns a `CardExtraction` with `card_type`, nested `insurance` or `government` fields, `confidence`, and `issuer_hint`.

The prompt is composed from a shared `_EXTRACTION_BASE` constant. We factored this out after noticing the base extraction prompt and the wiki-context variant were 90% identical. One source of truth avoids drift when we update extraction rules.

Temperature is 0.0 for extraction (deterministic output is strictly better here — we want the same card to produce the same extraction on repeat runs).

### Step 7: Validate (deterministic)

Hallucination filters run in Python:
- Known placeholder IDs (`1234567890`, `0000000000`)
- Sequential digits (`123456789`)
- All-same-digit strings (`999999999`)
- Placeholder dates (`01/01/2025`)
- Cross-field consistency (member_id without subscriber_name on insurance cards is suspicious)

We also run optional **wiki-informed** validation: regex patterns from the wiki's Validation Rules section (e.g., "Florida DLs match `[A-Z]\d{12}`"). These are classified as warnings, not errors — a pattern mismatch reduces confidence but never suppresses the extraction. This prevents false negatives when a carrier changes their format.

A 200-character input cap protects against ReDoS via pathological wiki regex (defense in depth — wiki writes are authenticated, but we shouldn't trust our own future selves).

### Step 8: Verify loop (conditional re-extraction)

If validation surfaced errors, we re-extract with the issues listed in the prompt. Maximum one retry. Mirrors the chorus-agent's `_verify_analysis` pattern. On the enhanced config we set `max_retry_attempts=0` since the experiments showed retries rarely helped on this dataset — worth the knob though.

We pass the already-computed `ValidationResult` into `_verify_extraction` to avoid running validation twice on the same extraction. (Small fix from the code review.)

### Step 9: Audit (VLM, conditional evaluator)

This was the biggest insight from reviewing the first results. I had used an agent subagent to visually inspect the PDFs and compare to the extraction results — it found 11 missed cards by counting what it saw vs what came out. The technique that found the gap should *be the pipeline.*

So we added an **evaluator-optimizer** step: one more VLM call that asks "how many cards do you see on this page?" and compares to our actual extraction count. If the VLM sees more cards than we extracted (accounting for Back-labeled boxes that we deliberately skipped), we trigger the full-page fallback to catch the missing cards.

The audit is **conditional**: we only run it when `actual_extractions < expected_extractions` (some crops failed extraction). On clean pages where every detected crop extracted successfully, audit is skipped. This saved ~14% of total tokens vs running audit unconditionally.

Anthropic's "Building Effective Agents" names this pattern explicitly: evaluator-optimizer. It's cheap insurance against silent recall failures.

### Step 10: Wiki + Review (the learning loop)

This is where the Karpathy "LLM Knowledge Base" pattern comes in. See section 5.

---

## 5. The Wiki and Human Review: Why They Exist

### The dual-role problem (and how we fixed it)

An earlier iteration of the wiki parsed markdown with string scraping to pull out validation rules. The same file served two audiences: humans reading prose observations, and the rules engine extracting regex patterns by searching for section headers and bullet markers. This is the classic dual-role trap. A stray asterisk, a reformatted heading, or a malformed regex inside a prose paragraph would silently disable validation for that issuer. The wiki looked fine to a human skimming it; the rules engine quietly returned nothing.

**The fix**: YAML frontmatter. Each issuer page now starts with a fenced YAML block holding the machine-readable rules (regex patterns, required fields, version, timestamps). That block parses into a Pydantic `IssuerRules` model via `yaml.safe_load`. The markdown body below the frontmatter is reserved for human observations and optional LLM context, and is **never** parsed as rules. One file, one source of truth, deterministic parsing.

**Write-time validation**: `compile_correction()` accepts structured `patterns` and `required_fields` kwargs. Before writing, every regex is compiled via `re.compile`. If any pattern is invalid, `compile_correction` raises `re.error` and the write is aborted. Broken rules never land in the wiki.

**Read-time validation**: `get_extraction_hints()` runs `yaml.safe_load` then validates the result into `IssuerRules`. Malformed YAML or Pydantic validation failure logs ERROR and returns an empty dict. `validation.py::_check_wiki_patterns` pre-compiles each regex and logs ERROR on failure (skipping the one bad pattern rather than killing the whole validation pass). In both cases the system fails **loud**, not silent — see §12.

**Karpathy preservation**: The "wiki as compounding artifact" pattern is intact. Humans and LLMs still read the markdown body. Only the rules engine reads the frontmatter. The frontmatter's schema is documented in `knowledge/schema.md`; new issuer pages are bootstrapped from `knowledge/issuers/_template.md` which starts with an empty frontmatter block.

**Concurrency**: `CardKnowledgeWiki` now holds an `asyncio.Lock`. `write_observation()`, `update_index()`, and `compile_correction()` are async and acquire the lock before mutating a page. This prevents the interleaved-write race that would corrupt the YAML block under concurrent requests. `review.py::compile_reviewed_to_wiki()` is async accordingly.

### The problem: models don't learn from individual runs

Every VLM call is stateless. The 500th Aetna card looks just as unfamiliar as the first one. Layout quirks that a human would notice once and remember forever have to be re-discovered every time.

Traditional fixes are fine-tuning (expensive, infrastructure-heavy, model-dependent) or RAG with embeddings (useful but overkill here). Karpathy's April 2026 essay on "LLM Knowledge Bases" suggests a simpler third option: **have the LLM maintain a structured markdown wiki about what it's seen**.

### How we use it

Three layers:
- **Raw sources** — the card images themselves, immutable, never touched by the LLM
- **Schema** (`knowledge/schema.md`) — hand-written rules for what goes in the wiki and how
- **Wiki pages** (`knowledge/issuers/*.md`) — LLM-maintained markdown, one per issuer

Each extraction writes an observation to the relevant issuer's page: field patterns (masked), plan types, layout notes. Over time the wiki accumulates everything the system has seen for that issuer.

### The PII problem (and the mask)

An obvious risk: if the wiki stores observations like "member_id format: 302307904" and serves them via API, it's PII leakage. The security review flagged this as critical.

We solved it with **shape masking**. `_mask_value()` replaces digits with `#`, uppercase letters with `A`, lowercase with `a`, preserving separators. So `302307904` becomes `#########` and `78-800132` becomes `##-######`. The wiki captures the structural information without the payload.

### The learning experiment and the outcome

We ran the 20-PDF set twice: once with a fresh wiki, once with the wiki populated from the first run. Same 38 extractions both times. But the second pass used **17% more tokens** because every extraction for a known issuer injected the wiki context.

The observation text alone (masked patterns) added no extractable signal beyond what the VLM already inferred from the image. We were paying for context the model didn't use.

### The fix: conditional wiki injection

We now only inject wiki context when `wiki_hints` contains **explicit validation rules** (regex patterns or required fields). These come from two sources:

1. **Human corrections** via the review queue. When a reviewer corrects an extraction and submits via `POST /review/{item_id}`, `compile_reviewed_to_wiki` writes to the Validation Rules section.
2. **Future auto-promotion** (planned, not implemented). After N consistent observations of the same masked pattern, promote to a regex rule.

On a fresh install, no rules exist, so no wiki injection happens, so no token tax. As human corrections accumulate, rules populate, and extraction quality improves on the next run for that issuer. The wiki is a **dormant learning surface** — it costs nothing until signal exists.

### The review queue

Any extraction with `confidence < 0.7` or that fails validation lands in `review_queue/*.json`. A human can `POST /review/{item_id}` with a correction. Corrections compile into the wiki's Validation Rules section and take effect on the next run for that issuer.

This is the **hill-climbing loop**. Each human correction is a gradient step. The wiki is the weight storage. The hill we're climbing is extraction accuracy for this deployment's actual card mix, whatever it happens to be.

---

## 6. Observability: Tracing Every Decision

The trace artifact (`_trace.jsonl`) is one JSON event per line covering every decision the pipeline made:

- PDF/page lifecycle (`pdf_start`, `pdf_end`, `page_start`)
- Every VLM call with source, model, tokens, latency, and result summary
- Detection results (box counts by label)
- Verification decisions (skipped, verified, vetoed)
- Extraction results (confidence, validity, issues)
- Fallback triggers (reason)
- Audit results (VLM count, extracted count, mismatch flag)
- Audit skips (reason)
- Wiki updates
- Review flags (reason, confidence)
- Errors (source, page, message)

Why JSONL: append-only, streamable, one-line-per-event trivial to grep/jq. Playable through any log analyzer. No schema migration problems.

`PipelineTrace.summary()` reads back from the JSONL file rather than from an in-memory event list. The earlier `_events` list was removed — the file is the durable artifact, duplicating it in memory was a memory leak on long runs and a second source of truth. One trace, one file.

The trace is the answer to "why did this extraction fail?" two weeks after the batch. Without it you have no way to investigate, and a commercial service that can't explain its own outputs is a liability.

---

## 7. Security Posture

The code review surfaced 3 critical and 7 high findings. All are fixed. Summary of what we did:

- **Path traversal on PDF upload**: filenames sanitized via regex strip of path components
- **Path traversal on review item_id**: validated as UUID before file path construction
- **PII in wiki**: all extracted values mask-transformed before storage
- **No auth on API**: added `X-API-Key` dependency on every endpoint except `/health`
- **DoS via upload size**: 50MB hard limit before the read completes
- **ReDoS via wiki regex**: 200-character input cap on pattern matching
- **Stack trace leakage**: global exception handler returns generic 500
- **Info disclosure on /health**: model names replaced with boolean availability flags

Security is not an after-thought here — it's a requirement gate for shipping to a client who handles PII (member IDs, gov IDs, names).

### Second-round findings (request isolation and rule integrity)

- **Cross-request state bleed**: the module-level `_ctx` singleton in `card_extractor/app.py` was replaced. A FastAPI `lifespan` now builds a shared `DurableContext` (config, wiki, review queue, tunables) at startup. Every `/extract` call builds a fresh request-scoped `AgentContext` via `AgentContext.for_request(durable, run_id)` with its own `TokenTracker` and `PipelineTrace`. Concurrent requests no longer see each other's token counts or trace events.
- **Filename collisions on concurrent uploads**: each request generates `run_id = uuid.uuid4()` and writes artifacts to `output_dir/run_id/`. Two clients uploading identically-named PDFs at the same time no longer clobber each other's output.
- **Upload DoS via RAM pressure**: PDF uploads are streamed in 1 MB chunks with on-the-fly size enforcement, rather than read entirely into memory before the size check. The 50 MB cap still applies.
- **Invalid review statuses**: `ReviewSubmission.status` is now `Literal["approved", "corrected", "rejected"]`. FastAPI rejects unknown statuses at the API boundary with a 422 before any handler runs.
- **Race on concurrent wiki writes**: `asyncio.Lock` on `CardKnowledgeWiki` serializes all mutations. See §5.
- **Rule poisoning via silent regex failures**: `_check_wiki_patterns` previously swallowed `re.error` silently. It now logs ERROR and skips only the bad pattern. A wiki that accumulated a broken rule no longer silently ceased to validate that issuer.
- **Rule poisoning at write time**: `compile_correction()` validates every regex compiles before writing. Invalid patterns raise `re.error` and the wiki is unchanged.
- **Cheap liveness check**: `/health/live` returns 200 immediately with no dependency probe — suitable for container orchestrator liveness checks that shouldn't cascade failures on gateway blips. `/health/ready` retains the gateway dependency check for readiness. `/health` aliases `/health/ready` for backward compatibility.

---

## 8. What We Deliberately Did NOT Build

To show discipline: here's what we rejected and why.

### Full ReAct agent

Overkill. Pipeline is fixed. Would cost tokens on planning that produces the same answer every time.

### LangGraph Platform / LangSmith Cloud

Proprietary SaaS, contradicts the commercial licensing story, introduces vendor lock-in.

### LangGraph (the library, even though it's MIT)

Never used its graph primitives. Plain `async def` functions are simpler for our sequential flow.

### Fine-tuning

Infrastructure-heavy. Model-coupled. The wiki + review loop achieves the same learning goal without touching model weights.

### Vector DB / RAG on wiki content

The wiki at current scale (~20 issuer pages) doesn't need a vector DB. Direct file lookup by issuer slug is O(1). When/if we grow to thousands of issuers, revisit.

### MCP servers for the tools

MCP is valuable when tools need to be portable across agent runtimes. Our tools are pipeline-internal closures over `AgentContext`. No portability need. We could wrap them as MCP servers later via `langchain-mcp-adapters` if a use case appears.

### Image inversion for dark-background cards

Known gap. One sample card photographed on a black surface fails detection because autocontrast can't find edges against a dark background. The fix is to detect when >50% of pixels are below a threshold and invert before the detection call. Parked until we have more dark-background samples to validate against.

---

## 9. Testing Strategy

- **Unit tests** (71, no API key): every model, every validation rule, every wiki operation, every tool path with mock context
- **Integration tests** (marked): end-to-end pipeline run against one sample PDF, requires `AI_GATEWAY_KEY`
- **Experiment runner**: parameter sweeps across DPI, temperature, confidence thresholds, padding — generates comparable metrics, used to find the optimal config (DPI=200 for large-page workloads, temp=0.0, pad=5; public reference defaults to DPI=300 to match the upstream tool)

Tests check *behavior*, not implementation. Most validations check "this input produces this output" rather than "this function is called with these arguments." Refactor-friendly.

---

## 10. Metrics and What They Mean

Final enhanced run, 20 PDFs:

| Metric | Value | Notes |
|---|---|---|
| Extractions | 38 | +73% vs POC (22) |
| Wall-clock time | 265s | 13s per PDF average |
| API calls | 83 | ~4 per extracted card |
| Input tokens | 372K | 98% of total tokens |
| Output tokens | 7.4K | 2% — almost all tokens are image bytes |
| Cost per card | $0.003 | at Qwen gateway rates |
| Cost per 1,000 PDFs | $5.60 | linearly scales |
| Review queue | 0 | all extractions passed confidence threshold |
| Trace events | ~450 | one JSONL line per decision |

**Interpretation:**
- Token cost is dominated by images, not prompts. Lowering DPI was the single biggest cost reduction.
- 4 API calls per card is: 1 detection (amortized per page), 1 optional verify (only for Unknown), 1 extraction, 1 occasional audit.
- The pipeline is not bottlenecked on anything we control — it's bottlenecked on gateway latency.

---

## 11. Deployment Shape

A FastAPI service in a container. Endpoints:

- `POST /extract` — upload PDF, get `{run_id, extractions, token_summary}` (per-request token summary, not cumulative)
- `GET /review` — list items awaiting human grading
- `POST /review/{item_id}` — submit a correction (status: approved / corrected / rejected)
- `GET /wiki/{issuer}` — read a wiki page
- `GET /health/live` — cheap liveness (200 immediately, no dep check)
- `GET /health/ready` — readiness (checks gateway availability)
- `GET /health` — alias for `/health/ready` (backward compat)

Volume mounts:
- `knowledge/` — wiki persistence (YAML frontmatter + markdown)
- `review_queue/` — queue state
- `output_dir/` — per-request `run_id` subdirectories accumulate here; rotate/clean on a schedule appropriate to the deployment

Single API key via `AI_GATEWAY_KEY` env var.

The natural deployment is a standalone container alongside whatever orchestration consumes the API. It's a stateful service with its own persistence (wiki, review queue) and calls an external VLM gateway.

---

## 12. Design Principles That Kept Showing Up

If you're editing this codebase, these are the principles to preserve:

1. **Code handles facts; agent handles interpretation.** PDF rendering, coordinate math, validation rules, file I/O — all deterministic code. Card type classification, field extraction, layout observation — VLM calls.
2. **Structured output everywhere.** Every VLM call returns a Pydantic model. No regex JSON parsing. Ever.
3. **Observability is a product feature.** The trace exists because "why did extraction X fail?" is a question customers will ask.
4. **Conditional expense.** Every VLM call has a gate. Verification skips Front labels. Audit skips clean pages. Wiki injection waits for validation rules. Nothing is paid for unless it might add value.
5. **Human signal trumps automated observation.** Wiki observations from extractions are masked patterns (low-confidence). Human corrections write validation rules (high-confidence). The system trusts humans more than itself.
6. **Failure isolation.** Per-PDF errors don't halt the batch. Per-crop errors don't halt the PDF. Per-step errors don't halt the crop. The pipeline degrades gracefully.
7. **Licensing is non-negotiable.** Every dependency checked against permissive-license criteria before it's added. No AGPL anywhere, no vendor lock-in.
8. **Machine-critical data uses typed schemas, not string parsing.** Wiki rules live in YAML frontmatter parsed into `IssuerRules`. Review submission status is a `Literal`. Pipeline I/O is Pydantic end-to-end. If a machine reads it, it has a schema; if a human reads it, prose is fine.
9. **Fail loudly on rule parsing errors.** Silent degradation of validation is a rule-poisoning vector — a wiki that quietly stops enforcing its regexes looks identical to one that's working. Bad regex, bad YAML, bad frontmatter, invalid `IssuerRules`: all log ERROR. Writes with invalid patterns are rejected at `compile_correction()`. The system prefers a visible failure over a silent one.

---

## 13. References

- **Anthropic: Building Effective Agents** — https://www.anthropic.com/research/building-effective-agents
- **LangChain: Anatomy of an Agent Harness** — https://blog.langchain.com/the-anatomy-of-an-agent-harness/
- **LangChain: Deep Agents** — https://blog.langchain.com/deep-agents/
- **Karpathy: LLM Knowledge Bases** — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **AGENTS.md specification** — https://agents.md/
- **Pachaar: Anatomy of an Agent Harness** — the 12-component catalog used as the alignment benchmark
- **agent-harness-chorus-csd-analyzer** — sibling reference harness using the same 12-component pattern, available at https://github.com/PatientVibes/agent-harness-chorus-csd-analyzer
