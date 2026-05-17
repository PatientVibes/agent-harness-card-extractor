# `agent-app-card-extractor` — Design

**Date:** 2026-05-17
**Status:** Draft, awaiting user review
**Author:** Chris Moore (with Claude)

## Goal

Create a new sibling repo, `agent-app-card-extractor`, that packages an installable desktop-style program around the existing `agent-harness-card-extractor` library. The app provides a file-drop intake, a dual JSON/XML previewer for extraction results, and an interactive chat session in which the agent can modify the extraction in response to user instructions.

The split is deliberate: the **app stays static** (UI, packaging, serializers, session glue) while the **agent harness evolves** independently as a versioned dependency.

## Non-goals

- Multi-user, multi-tenant, or hosted operation. Single user, single machine, offline-capable.
- Authentication, role separation, audit trails beyond local SQLite history.
- A new extraction pipeline, new VLM prompts, or new card-type support — those changes belong in the harness repo.
- A specific external XML schema (HL7, ACORD, etc.). XML is a generic serialization of the harness's Pydantic model; if a named external schema is needed later, that is a separate effort.
- Replacing the harness's batch CLI. `run_batch.py` and the file-based `review_queue/` workflow continue to work standalone.

## Repo shape

```
agent-app-card-extractor/
  app/                    # FastAPI backend
    main.py               # ASGI entry, mounts routes + static
    routes/
      uploads.py          # POST /uploads — file drop, returns job_id
      jobs.py             # GET /jobs/:id, GET /jobs/:id/xml
      chat.py             # WS /chat/:job_id — interactive session
    services/
      pipeline.py         # wraps card_extractor pipeline as async job
      serializers.py      # JSON ↔ XML conversion of Pydantic models
      chat_agent.py       # LangChain agent + extraction-edit tools
    state/
      jobs.db             # SQLite — job state, chat history, edit log
      uploads/            # incoming PDFs
      outputs/            # per-job extraction JSON
  web/                    # React + Vite frontend
    src/
      App.tsx
      panes/FileDrop.tsx
      panes/Previewer.tsx # tabs: JSON | XML, syntax-highlighted
      panes/Chat.tsx      # streaming messages, tool-call display, diff accept/reject
    # built output is copied into app/static/ at package time
  packaging/
    pyinstaller.spec      # single-file installer build
  pyproject.toml          # depends on agent-harness-card-extractor>=0.2.1
  README.md
```

## Architecture

Three logical layers, each independently testable:

1. **Pipeline service** — thin async wrapper around the harness's existing batch entry points. Owns job lifecycle (`pending` → `running` → `complete` | `failed`) and writes the canonical JSON output to `state/outputs/<job_id>.json`.
2. **Presentation layer** — read-only views over the canonical JSON. The JSON endpoint returns the file as-is; the XML endpoint returns a server-side transform of the same Pydantic model. The frontend tabs between them.
3. **Chat session** — a stateful WebSocket-backed agent loop scoped to a single job. The agent has tools to read the current extraction, propose field-level edits, and re-run focused VLM calls on individual cards. User accepts or rejects each proposed edit; accepted edits update the canonical JSON and feed back into `knowledge/` via the existing wiki-write path in the harness.

## Data flow

1. **Upload** — user drops a PDF into the file-drop pane. Frontend `POST`s to `/uploads`; backend stores the file in `state/uploads/`, creates a job row in SQLite with `status=pending`, returns `job_id`.
2. **Pipeline** — a background task picks up the pending job, invokes the harness pipeline (render → detect → verify → extract → validate → evaluator), and persists the resulting `CardExtraction` collection to `state/outputs/<job_id>.json`. Status moves to `complete` (or `failed` with a captured error).
3. **Preview** — frontend polls `/jobs/:id` until `complete`, then fetches `/jobs/:id` for JSON and `/jobs/:id/xml` for XML. The previewer pane renders whichever tab is active. Both views derive from the same on-disk JSON.
4. **Chat** — user opens the chat pane on a completed job. Frontend connects to `WS /chat/:job_id`. The backend instantiates a chat agent seeded with the current extraction, the original card images, and a description of the available tools. User and agent exchange messages; tool calls and proposed edits stream to the UI.
5. **Edit application** — when the agent calls `set_field`, the proposed change is sent to the UI as a diff. User clicks accept → backend mutates the JSON on disk, appends an entry to the edit log, and the previewer refreshes. Rejected edits are recorded but not applied. Accepted edits also flow into `knowledge/` through the same wiki-write API the harness uses for review-queue corrections.

## Chat agent tools

The chat agent is the same LLM family as the harness's VLM (configurable via env). It is given three tools:

- **`read_field(path: str) -> value`** — read a value from the current extraction by JSON path (e.g. `cards[0].member_id`). Used for grounding before suggesting edits.
- **`set_field(path: str, value, reason: str) -> proposal_id`** — propose a change. Does not apply immediately; surfaces a diff to the user. The `reason` field is captured in the edit log.
- **`re_examine(card_id: str, focus: str) -> observation`** — re-run a focused VLM call on the cropped card image with an instruction (e.g. "read the group number in the lower-right corner"). Returns the observation; the agent then decides whether to propose a `set_field` based on it.

The agent does not have a "commit" tool — only the user's accept action mutates state.

## Boundary: harness vs. app

| Lives in `agent-harness-card-extractor` (evolving) | Lives in `agent-app-card-extractor` (static) |
|---|---|
| Render / Detect / Verify / Extract / Validate stages | File-drop HTTP endpoint, job queue, SQLite state |
| Pydantic models — the schema contract | JSON ↔ XML serializers (presentation concern) |
| `knowledge/` wiki reader/writer API | Chat agent loop + edit-proposal tools |
| Prompt templates | UI for diffing, accepting, and rejecting edits |
| `run_batch.py` CLI | PyInstaller packaging / installer |
| Pipeline-level metrics / evaluator | Per-session chat history and edit audit log |

The app depends on the harness as a normal pip package (`agent-harness-card-extractor>=0.2.1`). Harness upgrades are a one-line bump in `pyproject.toml`.

## Local state

- **SQLite (`state/jobs.db`)** — `jobs` table (id, status, created_at, source_filename, output_path, error), `chat_messages` table (job_id, role, content, tool_calls, ts), `edit_log` table (job_id, path, old_value, new_value, reason, accepted, ts).
- **Filesystem** — `state/uploads/` for raw PDFs, `state/outputs/` for canonical JSON. Both are addressed by `job_id`.

No daemon, no external services. The app runs entirely offline once installed.

## Packaging and distribution

A single PyInstaller spec produces a one-file executable:

1. The Vite frontend is built into static assets and copied into `app/static/` before bundling.
2. PyInstaller bundles the FastAPI app, the harness package, the static assets, and a Python runtime.
3. Launching the binary starts uvicorn on a random localhost port, then opens the user's default browser to that URL.

This is the only sanctioned distribution mechanism for v1. No pip install path, no Docker image. The same spec produces Windows `.exe` and macOS `.app`; Linux is best-effort.

## XML serialization

The XML form is a literal, element-per-field serialization of the Pydantic model: tag names mirror field names, lists become repeated elements, optional/null fields are omitted. This is generated server-side from the same in-memory model used for the JSON output, so the two views are guaranteed consistent.

If a named external schema (HL7, ACORD, etc.) is needed later, it is added as an additional serializer alongside this generic one — not a replacement.

## Testing strategy

- **Pipeline service** — integration test against a fixture PDF, asserting the canonical JSON output exists and matches the harness's direct output.
- **Serializers** — unit tests for round-trip JSON↔XML on representative fixtures.
- **Chat tools** — unit tests for each tool (`read_field`, `set_field`, `re_examine`) against a fixed extraction, with the agent loop stubbed.
- **Edit application** — test that accepted edits mutate the on-disk JSON and append to the edit log; rejected edits append only.
- **Packaging** — smoke test that the PyInstaller binary launches, serves the UI, and processes a fixture PDF end-to-end.

The harness's existing tests are not duplicated.

## Open questions resolved during brainstorming

- **New repo vs. monorepo?** New sibling repo. Harness stays reusable and free of UI dependencies; app evolves on its own release cadence.
- **Runtime model?** Python-only web app, packaged installer (Option A). Rejected Tauri+sidecar and Electron+sidecar because the user wants the app to stay static while the agent evolves — a single-language pip-dependency model serves that goal best.
- **XML schema target?** Generic serialization of the Pydantic model. Not HL7 or ACORD.
- **Chat agent identity?** Same LLM family as the harness's VLM, reading the same `knowledge/` wiki. Not a separate review agent.
- **Multi-user?** No. Single-user, single-machine, offline.

## Out of scope / explicit deferrals

- Hosted / multi-user mode.
- Authentication.
- Mobile UI.
- Real-time collaborative editing of a single extraction.
- A separate REST API for third-party clients (the HTTP surface is an implementation detail of the installed app).
- Auto-update mechanism for the installer.
