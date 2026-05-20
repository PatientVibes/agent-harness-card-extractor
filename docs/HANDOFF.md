# Handoff

## Current Status

**Version:** 0.2.1 (tagged `v0.2.1`). The project is stable and in active use as a reference implementation of the 12-component agent harness pattern.

**Branch:** `master`. A `ci/audit-gate` branch exists for the doc-governance CI workflow.

**What it is:** A FastAPI + LangChain VLM pipeline that extracts structured data from scanned PDFs of government IDs and insurance cards. Detect → verify → extract → validate → audit, with a Karpathy-style knowledge wiki and human review queue. Python 3.11+, MIT-licensed, all dependencies permissively licensed (no AGPL).

**Runtime dependencies** (pinned by git SHA in `[tool.uv.sources]`):
- `agent-tool-pdf-vlm-renderer` — PDF → PNG + crop + debug overlay
- `agent-tool-knowledge-wiki` — per-issuer YAML-frontmatter wiki
- `agent-tool-review-queue` — review item lifecycle
- `agent-tool-pipeline-trace` — JSONL trace writer
- `agent-tool-token-tracker` — per-request VLM token accounting
- `agent-tool-llm-utils` — retry, checkpoint, transient-error classifier

**CI:** `.github/workflows/audit.yml` runs `repo-doc-gov audit --fail-on high` on every PR and push to `master` on a self-hosted `repo-doc-gov` runner.

## Recently Completed

- **v0.2.1 (2026-05-13):** Fixed vendored prompt drift in `card_extractor/prompts/extraction_with_context.md` (stale `format_rules_for_injection` reference). Removed the now-redundant `card_extractor.models.ReviewItem` Pydantic class and its test.
- **v0.2.0 (2026-05-13):** Replaced all inline tool implementations with the six `agent-tool-*` toolbox packages. Removed `rendering.py`, `wiki.py`, `review.py`, `trace.py` and their tests. Added `card_extractor/coords.py` to bridge normalized VLM bounding boxes to pixel coordinates. Vendored 6 VLM prompts from the `vlm-card-extraction-prompts` skill into `card_extractor/prompts/*.md`.
- **v0.1.0 (2026-05-12):** Initial public release from a discontinued private POC.

## Known Issues

- **Dark-background card detection gap.** Cards photographed on a black surface fail detection because `ImageOps.autocontrast` cannot find edges against a dark background. The fix (detect when >50% of pixels are below a threshold and invert before the detection call) is documented in `docs/DESIGN.md §8` but not implemented. Parked until more dark-background samples are available.
- **Review queue format is a breaking change from v0.1.0.** The `ReviewItem` shape changed in v0.2.0 (now from `agent-tool-review-queue`). Existing pending items from v0.1.0 are not migrated. Any deployment upgrading from v0.1.0 with in-flight review items must drain the queue on v0.1.0 before upgrading.
- **JSONL trace key changed.** The event-type key in `_trace.jsonl` changed from `"event"` to `"event_type"` in v0.2.0. Downstream consumers that grep `"event":` must update to `"event_type":`.
- **Wiki injection token tax on known issuers.** Wiki context is only injected when explicit validation rules exist (patterns or required fields), not on raw observations. This is intentional and documented in `docs/DESIGN.md §5`, but worth noting for anyone tuning token costs.
- **`AGENTS.md` test count may drift.** `AGENTS.md` states 54 unit tests; the actual count should be verified against `pytest tests/ -k "not integration" --collect-only` after any test additions.

## Next Recommended Tasks

- [ ] Implement dark-background inversion in `card_extractor/agent.py`: detect when >50% of pixels are below a threshold in `preprocess_for_vlm` and invert before the detection call. See `docs/DESIGN.md §8` for the full description.
- [ ] Add auto-promotion of wiki observations to validation rules in `card_extractor/agent.py` / `knowledge_wiki`: after N consistent observations of the same masked pattern, promote to a regex rule. Described as "planned, not implemented" in `docs/DESIGN.md §5`.
- [ ] Verify `AGENTS.md` test count (currently states 54) matches actual unit test count after any test changes: run `pytest tests/ -k "not integration" --collect-only`.
- [ ] Confirm the six `[tool.uv.sources]` git SHAs in `pyproject.toml` are still the intended pinned revisions for each `agent-tool-*` dependency before any release.

## Open Questions

- **`crop_pad_px` default discrepancy.** `DurableContext.from_env()` defaults `crop_pad_px` to `10` (via `CROP_PAD_PX` env var), but `docs/DESIGN.md §4` states the optimal padding found in experiments was 5 px. Verify whether the production default should be 5 or 10 and reconcile `DESIGN.md` or the code default accordingly.
- **`agent-app-card-extractor` sibling status.** `README.md` references a sibling desktop app at `github.com/PatientVibes/agent-app-card-extractor` with plans in `docs/superpowers/`. It is unclear whether that project is actively maintained or whether the plans in `docs/superpowers/plans/` represent completed, in-progress, or abandoned work.
