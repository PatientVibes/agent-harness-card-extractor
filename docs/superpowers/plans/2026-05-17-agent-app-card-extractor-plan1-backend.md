# agent-app-card-extractor — Plan 1 of 4: Backend Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a new sibling repo `agent-app-card-extractor` with a FastAPI backend that accepts PDF uploads, runs them through the existing harness as a library, and serves both JSON and XML views of the extraction result over HTTP.

**Architecture:** New repo at `D:\agent-app-card-extractor`, depends on `agent-harness-card-extractor` as a uv-managed path source for local dev. FastAPI app with a SQLite job table, a background job runner that calls `card_extractor.agent.process_pdf` directly (not the harness's HTTP layer), and read endpoints for status, JSON, and a server-side XML serialization of the same Pydantic models.

**Tech Stack:** Python 3.11+, uv, FastAPI, uvicorn, SQLite (stdlib), Pydantic v2, pytest + pytest-asyncio + httpx for tests, stdlib `xml.etree.ElementTree` for XML.

**Scope boundary:** No frontend (Plan 2), no chat WebSocket (Plan 3), no installer (Plan 4). This plan ends when `curl -F file=@sample.pdf http://localhost:8000/uploads` returns a job_id, status polling works, and JSON + XML can be fetched for a completed job.

---

## File Structure

```
D:\agent-app-card-extractor\
  pyproject.toml
  uv.lock                  # generated
  .python-version          # "3.11"
  .gitignore
  .env.example
  README.md
  app/
    __init__.py            # empty
    main.py                # FastAPI app, lifespan, route mounting
    config.py              # AppConfig dataclass loaded from env
    db.py                  # SQLite schema + helpers
    routes/
      __init__.py          # empty
      uploads.py           # POST /uploads
      jobs.py              # GET /jobs/:id, GET /jobs/:id/xml
      health.py            # GET /health
    services/
      __init__.py          # empty
      pipeline.py          # async wrapper around process_pdf
      serializers.py       # pydantic model → XML element tree
    state/
      .gitkeep             # uploads/ and outputs/ created at runtime
  tests/
    __init__.py            # empty
    conftest.py            # fixtures: tmp app, in-memory db, mocked pipeline
    test_config.py
    test_db.py
    test_health.py
    test_uploads.py
    test_jobs.py
    test_pipeline.py
    test_serializers.py
    test_smoke.py          # end-to-end with mocked process_pdf
```

Each file has one responsibility: routes only do HTTP-shape work and delegate to services; services hold the imperative logic; `db.py` is the only module that touches SQLite.

---

### Task 1: Scaffold the new repo

**Files:**
- Create: `D:\agent-app-card-extractor\pyproject.toml`
- Create: `D:\agent-app-card-extractor\.python-version`
- Create: `D:\agent-app-card-extractor\.gitignore`
- Create: `D:\agent-app-card-extractor\.env.example`
- Create: `D:\agent-app-card-extractor\README.md`
- Create: `D:\agent-app-card-extractor\app\__init__.py` (empty)
- Create: `D:\agent-app-card-extractor\app\routes\__init__.py` (empty)
- Create: `D:\agent-app-card-extractor\app\services\__init__.py` (empty)
- Create: `D:\agent-app-card-extractor\app\state\.gitkeep` (empty)
- Create: `D:\agent-app-card-extractor\tests\__init__.py` (empty)

- [ ] **Step 1: Create the directory and initialize git**

```bash
mkdir -p "D:\agent-app-card-extractor"
cd "D:\agent-app-card-extractor"
git init -b master
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "agent-app-card-extractor"
version = "0.1.0"
description = "Installable card-extraction app — wraps agent-harness-card-extractor with a web UI, dual JSON/XML previewer, and an interactive chat agent."
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Chris Moore" }]
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "python-multipart>=0.0.9",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
    "agent-harness-card-extractor",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
include = ["app*"]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
markers = [
    "integration: end-to-end tests that exercise the real harness (require AI_GATEWAY_KEY)",
]

[tool.uv.sources]
agent-harness-card-extractor = { path = "../agent-harness-card-extractor", editable = true }
```

- [ ] **Step 3: Write `.python-version`**

```
3.11
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
*.egg-info/
app/state/jobs.db
app/state/uploads/
app/state/outputs/
dist/
build/
```

- [ ] **Step 5: Write `.env.example`**

```
# Forwarded to the harness. See agent-harness-card-extractor/.env.example
# for the full list (AI_GATEWAY_KEY, VLM_MODEL, etc.).
AI_GATEWAY_KEY=

# App-specific
APP_STATE_DIR=./app/state
APP_HOST=127.0.0.1
APP_PORT=8000
```

- [ ] **Step 6: Write a minimal `README.md`**

```markdown
# agent-app-card-extractor

Installable card-extraction app. Wraps [agent-harness-card-extractor](../agent-harness-card-extractor) as a library.

## Status

Plan 1 of 4 in progress: backend foundation (file drop → JSON + XML).

## Dev

```bash
uv sync --extra dev
cp .env.example .env  # fill in AI_GATEWAY_KEY
uv run uvicorn app.main:app --reload
```
```

- [ ] **Step 7: Create empty package files**

Create each of these as a zero-byte file:
- `app/__init__.py`
- `app/routes/__init__.py`
- `app/services/__init__.py`
- `app/state/.gitkeep`
- `tests/__init__.py`

- [ ] **Step 8: Verify uv resolves the dependency tree**

Run: `uv sync --extra dev`
Expected: completes without error; `.venv/` is created; `agent-harness-card-extractor` is installed in editable mode from `../agent-harness-card-extractor`.

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "feat: scaffold agent-app-card-extractor repo

Empty FastAPI app skeleton, pyproject pointing at sibling harness as
an editable uv path source, uv.lock generated."
```

---

### Task 2: AppConfig module

**Files:**
- Create: `D:\agent-app-card-extractor\app\config.py`
- Test: `D:\agent-app-card-extractor\tests\test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
"""Tests for app.config — env-driven configuration."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig


def test_from_env_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_STATE_DIR", raising=False)
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.from_env()
    assert cfg.state_dir == Path("./app/state").resolve()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000


def test_from_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_STATE_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "9001")
    cfg = AppConfig.from_env()
    assert cfg.state_dir == (tmp_path / "custom").resolve()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9001


def test_paths_property_creates_subdirs(tmp_path):
    cfg = AppConfig(state_dir=tmp_path, host="127.0.0.1", port=8000)
    cfg.ensure_dirs()
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "outputs").is_dir()


def test_uploads_dir_and_outputs_dir(tmp_path):
    cfg = AppConfig(state_dir=tmp_path, host="127.0.0.1", port=8000)
    assert cfg.uploads_dir == tmp_path / "uploads"
    assert cfg.outputs_dir == tmp_path / "outputs"
    assert cfg.db_path == tmp_path / "jobs.db"
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: No module named 'app.config'`

- [ ] **Step 3: Implement `app/config.py`**

```python
"""App configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    state_dir: Path
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            state_dir=Path(os.environ.get("APP_STATE_DIR", "./app/state")).resolve(),
            host=os.environ.get("APP_HOST", "127.0.0.1"),
            port=int(os.environ.get("APP_PORT", "8000")),
        )

    @property
    def uploads_dir(self) -> Path:
        return self.state_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.state_dir / "outputs"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "jobs.db"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): AppConfig with env-driven state dir, host, port"
```

---

### Task 3: SQLite state module

**Files:**
- Create: `D:\agent-app-card-extractor\app\db.py`
- Test: `D:\agent-app-card-extractor\tests\test_db.py`

This module owns the only place we touch SQLite. Routes and services use these helpers, not raw cursors.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:

```python
"""Tests for app.db — SQLite schema and helpers."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from app.db import (
    create_job,
    get_job,
    init_db,
    set_job_failed,
    set_job_output,
    set_job_running,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "jobs.db"
    init_db(db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_init_creates_schema(tmp_path):
    init_db(tmp_path / "jobs.db")
    c = sqlite3.connect(tmp_path / "jobs.db")
    rows = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    assert "jobs" in names


def test_create_job_returns_row(conn):
    job_id = create_job(conn, source_filename="card.pdf", upload_path="/tmp/card.pdf")
    job = get_job(conn, job_id)
    assert job["id"] == job_id
    assert job["status"] == "pending"
    assert job["source_filename"] == "card.pdf"
    assert job["upload_path"] == "/tmp/card.pdf"
    assert job["output_path"] is None
    assert job["error"] is None
    assert job["created_at"] is not None


def test_get_job_returns_none_for_missing(conn):
    assert get_job(conn, "nonexistent") is None


def test_set_job_running(conn):
    job_id = create_job(conn, source_filename="x.pdf", upload_path="/tmp/x.pdf")
    set_job_running(conn, job_id)
    assert get_job(conn, job_id)["status"] == "running"


def test_set_job_output_marks_complete(conn):
    job_id = create_job(conn, source_filename="x.pdf", upload_path="/tmp/x.pdf")
    set_job_output(conn, job_id, output_path="/tmp/out.json")
    job = get_job(conn, job_id)
    assert job["status"] == "complete"
    assert job["output_path"] == "/tmp/out.json"


def test_set_job_failed(conn):
    job_id = create_job(conn, source_filename="x.pdf", upload_path="/tmp/x.pdf")
    set_job_failed(conn, job_id, error="boom")
    job = get_job(conn, job_id)
    assert job["status"] == "failed"
    assert job["error"] == "boom"
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: No module named 'app.db'`

- [ ] **Step 3: Implement `app/db.py`**

```python
"""SQLite state — the only module that touches the database."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK(status IN ('pending','running','complete','failed')),
    source_filename TEXT NOT NULL,
    upload_path     TEXT NOT NULL,
    output_path     TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL
);
"""


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        c.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(conn: sqlite3.Connection, *, source_filename: str, upload_path: str) -> str:
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs(id, status, source_filename, upload_path, created_at) "
        "VALUES (?, 'pending', ?, ?, ?)",
        (job_id, source_filename, upload_path, _now()),
    )
    conn.commit()
    return job_id


def get_job(conn: sqlite3.Connection, job_id: str) -> Optional[sqlite3.Row]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row


def set_job_running(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("UPDATE jobs SET status='running' WHERE id = ?", (job_id,))
    conn.commit()


def set_job_output(conn: sqlite3.Connection, job_id: str, *, output_path: str) -> None:
    conn.execute(
        "UPDATE jobs SET status='complete', output_path=? WHERE id = ?",
        (output_path, job_id),
    )
    conn.commit()


def set_job_failed(conn: sqlite3.Connection, job_id: str, *, error: str) -> None:
    conn.execute(
        "UPDATE jobs SET status='failed', error=? WHERE id = ?",
        (error, job_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat(db): SQLite jobs table with lifecycle helpers"
```

---

### Task 4: FastAPI app skeleton with health endpoint

**Files:**
- Create: `D:\agent-app-card-extractor\app\main.py`
- Create: `D:\agent-app-card-extractor\app\routes\health.py`
- Create: `D:\agent-app-card-extractor\tests\conftest.py`
- Test: `D:\agent-app-card-extractor\tests\test_health.py`

The lifespan builds an `AppConfig`, ensures dirs exist, runs `init_db`, and stashes a long-lived sqlite connection on `app.state`. Routes get the conn via a small dependency.

- [ ] **Step 1: Write `tests/conftest.py`** (shared fixtures)

```python
"""Shared test fixtures."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import AppConfig
from app.db import init_db


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(state_dir=tmp_path, host="127.0.0.1", port=8000)
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def db_conn(app_config: AppConfig) -> sqlite3.Connection:
    init_db(app_config.db_path)
    c = sqlite3.connect(app_config.db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
async def client(app_config: AppConfig, monkeypatch):
    """Boot the FastAPI app against a temp state dir."""
    monkeypatch.setenv("APP_STATE_DIR", str(app_config.state_dir))
    # Import inside the fixture so env is set before lifespan runs
    from app.main import build_app
    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
```

- [ ] **Step 2: Write `tests/test_health.py`**

```python
"""Tests for /health."""
import pytest


async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 3: Run the test to verify failure**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_app' from 'app.main'`

- [ ] **Step 4: Implement `app/routes/health.py`**

```python
"""Liveness endpoint — no dependency calls."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Implement `app/main.py`**

```python
"""FastAPI app entry — lifespan owns the durable state."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import AppConfig
from app.db import init_db
from app.routes import health


def build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = AppConfig.from_env()
        cfg.ensure_dirs()
        init_db(cfg.db_path)
        conn = sqlite3.connect(cfg.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        app.state.config = cfg
        app.state.db = conn
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(title="agent-app-card-extractor", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    return app


app = build_app()
```

- [ ] **Step 6: Run tests to verify pass**

Run: `uv run pytest tests/test_health.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/routes/health.py tests/conftest.py tests/test_health.py
git commit -m "feat(app): FastAPI skeleton with lifespan-managed config + db + /health"
```

---

### Task 5: Upload endpoint (no pipeline yet)

**Files:**
- Create: `D:\agent-app-card-extractor\app\routes\uploads.py`
- Modify: `D:\agent-app-card-extractor\app\main.py` (register the router)
- Test: `D:\agent-app-card-extractor\tests\test_uploads.py`

The endpoint stores the file under `state/uploads/<job_id>.pdf`, creates a job row, and returns `{job_id, status}`. The pipeline trigger comes in Task 7.

- [ ] **Step 1: Write `tests/test_uploads.py`**

```python
"""Tests for POST /uploads."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

PDF_MAGIC = b"%PDF-1.4\n%fake content\n"


async def test_upload_returns_job_id(client, app_config):
    files = {"file": ("card.pdf", io.BytesIO(PDF_MAGIC), "application/pdf")}
    r = await client.post("/uploads", files=files)
    assert r.status_code == 201
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "pending"


async def test_upload_persists_file(client, app_config):
    files = {"file": ("card.pdf", io.BytesIO(PDF_MAGIC), "application/pdf")}
    r = await client.post("/uploads", files=files)
    job_id = r.json()["job_id"]
    saved = app_config.uploads_dir / f"{job_id}.pdf"
    assert saved.exists()
    assert saved.read_bytes() == PDF_MAGIC


async def test_upload_rejects_non_pdf(client):
    files = {"file": ("card.png", io.BytesIO(b"PNG..."), "image/png")}
    r = await client.post("/uploads", files=files)
    assert r.status_code == 400


async def test_upload_creates_job_row(client, app_config, db_conn):
    files = {"file": ("card.pdf", io.BytesIO(PDF_MAGIC), "application/pdf")}
    r = await client.post("/uploads", files=files)
    job_id = r.json()["job_id"]
    # Re-open the db the app wrote to (fixture conn may not see commits from the app's conn)
    import sqlite3
    c = sqlite3.connect(app_config.db_path)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    c.close()
    assert row is not None
    assert row["source_filename"] == "card.pdf"
    assert row["status"] == "pending"
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_uploads.py -v`
Expected: FAIL — `404 Not Found` for `/uploads`.

- [ ] **Step 3: Implement `app/routes/uploads.py`**

```python
"""POST /uploads — accept a PDF and create a pending job."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from app.db import create_job

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload(request: Request, file: UploadFile = File(...)) -> dict:
    raw_name = Path(file.filename or "upload.pdf").name
    safe_name = re.sub(r"[^\w.\-]", "_", raw_name)
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a PDF")

    cfg = request.app.state.config
    conn = request.app.state.db

    # Reserve job_id by creating the row first with a placeholder path,
    # then move the bytes to <uploads>/<job_id>.pdf.
    placeholder = cfg.uploads_dir / "incoming.tmp"
    total = 0
    with placeholder.open("wb") as out:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                placeholder.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
            out.write(chunk)

    job_id = create_job(conn, source_filename=safe_name, upload_path="pending")
    final_path = cfg.uploads_dir / f"{job_id}.pdf"
    shutil.move(str(placeholder), str(final_path))
    conn.execute("UPDATE jobs SET upload_path=? WHERE id=?", (str(final_path), job_id))
    conn.commit()

    return {"job_id": job_id, "status": "pending"}
```

- [ ] **Step 4: Register the router in `app/main.py`**

Replace the body of `build_app` so the imports and `include_router` lines look like:

```python
from app.routes import health, uploads

# inside build_app(), after `app = FastAPI(...)`:
    app.include_router(health.router)
    app.include_router(uploads.router)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_uploads.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/routes/uploads.py app/main.py tests/test_uploads.py
git commit -m "feat(uploads): POST /uploads stores PDF and creates pending job"
```

---

### Task 6: Pipeline service

**Files:**
- Create: `D:\agent-app-card-extractor\app\services\pipeline.py`
- Test: `D:\agent-app-card-extractor\tests\test_pipeline.py`

This is the bridge to the harness. The service takes a `(job_id, upload_path)` pair, builds a per-request `AgentContext` against a shared `DurableContext`, calls `process_pdf`, writes the result to `state/outputs/<job_id>.json`, and updates the job row.

Tests mock `process_pdf` — real VLM calls happen only in the smoke test (Task 11), and only when `AI_GATEWAY_KEY` is set.

- [ ] **Step 1: Write `tests/test_pipeline.py`**

```python
"""Tests for the pipeline service — process_pdf is mocked."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.db import create_job, get_job, init_db
from app.services.pipeline import PipelineService


class FakeDurable:
    """Stand-in for DurableContext — pipeline only reads `.output_dir` via for_request."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir


class FakeAgentCtx:
    def __init__(self):
        self.tracker = type("T", (), {"summary": lambda self: {}})()


@pytest.fixture
def pipeline(app_config, monkeypatch):
    init_db(app_config.db_path)
    durable = FakeDurable(output_dir=app_config.state_dir / "harness_out")
    durable.output_dir.mkdir(parents=True, exist_ok=True)

    # Patch the harness symbols the service imports.
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: FakeAgentCtx())}),
    )
    fake_process = AsyncMock(return_value=[
        {"card_type": "INSURANCE", "insurance": {"member_id": "X123"}, "government": {}, "confidence": 0.9, "issuer_hint": "Aetna"}
    ])
    monkeypatch.setattr("app.services.pipeline.process_pdf", fake_process)

    return PipelineService(durable=durable, config=app_config)


async def test_run_writes_output_and_marks_complete(pipeline, app_config):
    conn = sqlite3.connect(app_config.db_path)
    conn.row_factory = sqlite3.Row
    pdf_path = app_config.uploads_dir / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    job_id = create_job(conn, source_filename="test.pdf", upload_path=str(pdf_path))

    await pipeline.run(conn, job_id=job_id, upload_path=pdf_path)

    row = get_job(conn, job_id)
    assert row["status"] == "complete"
    assert row["output_path"] is not None
    out = json.loads(Path(row["output_path"]).read_text())
    assert out["extractions"][0]["insurance"]["member_id"] == "X123"
    conn.close()


async def test_run_marks_failed_on_exception(pipeline, app_config, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.services.pipeline.process_pdf", AsyncMock(side_effect=RuntimeError("boom")))

    conn = sqlite3.connect(app_config.db_path)
    conn.row_factory = sqlite3.Row
    pdf_path = app_config.uploads_dir / "bad.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    job_id = create_job(conn, source_filename="bad.pdf", upload_path=str(pdf_path))

    await pipeline.run(conn, job_id=job_id, upload_path=pdf_path)

    row = get_job(conn, job_id)
    assert row["status"] == "failed"
    assert "boom" in row["error"]
    conn.close()
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `ImportError: No module named 'app.services.pipeline'`

- [ ] **Step 3: Implement `app/services/pipeline.py`**

```python
"""Pipeline service — wraps the harness's process_pdf for the app's job model."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

# Harness library imports — keep these at module level so monkeypatching in
# tests can target them without an extra indirection.
from card_extractor.agent import AgentContext, process_pdf  # type: ignore

from app.config import AppConfig
from app.db import set_job_failed, set_job_output, set_job_running

logger = logging.getLogger(__name__)


def _to_dict(obj: Any) -> Any:
    """Pydantic v2 model → dict; dict and list pass through."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


class PipelineService:
    def __init__(self, durable: Any, config: AppConfig):
        self.durable = durable
        self.config = config

    async def run(self, conn: sqlite3.Connection, *, job_id: str, upload_path: Path) -> None:
        set_job_running(conn, job_id)
        try:
            ctx = AgentContext.for_request(self.durable, job_id)
            extractions = await process_pdf(upload_path, ctx)
            payload = {
                "job_id": job_id,
                "extractions": [_to_dict(e) for e in extractions],
            }
            output_path = self.config.outputs_dir / f"{job_id}.json"
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            set_job_output(conn, job_id, output_path=str(output_path))
        except Exception as exc:
            logger.exception("Pipeline failed for job %s", job_id)
            set_job_failed(conn, job_id, error=f"{type(exc).__name__}: {exc}")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): PipelineService bridges uploads to harness.process_pdf"
```

---

### Task 7: Wire pipeline as background task on upload

**Files:**
- Modify: `D:\agent-app-card-extractor\app\main.py` (build DurableContext + PipelineService at lifespan, stash on `app.state`)
- Modify: `D:\agent-app-card-extractor\app\routes\uploads.py` (kick off background task)
- Test: `D:\agent-app-card-extractor\tests\test_uploads.py` (add post-trigger assertion)

The pipeline runs as `asyncio.create_task` so the response returns immediately. The harness's `DurableContext` is built once at lifespan startup, just like the harness's own `app.py` does.

- [ ] **Step 1: Add a test for the background trigger**

Append to `tests/test_uploads.py`:

```python
async def test_upload_kicks_off_pipeline(client, app_config, monkeypatch):
    """After upload, the pipeline task should mark the job complete."""
    import asyncio
    import io
    import sqlite3
    from unittest.mock import AsyncMock

    fake_process = AsyncMock(return_value=[
        {"card_type": "INSURANCE", "insurance": {}, "government": {}, "confidence": 0.5, "issuer_hint": ""},
    ])
    monkeypatch.setattr("app.services.pipeline.process_pdf", fake_process)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    r = await client.post("/uploads", files=files)
    job_id = r.json()["job_id"]

    # Yield control so the background task can run
    for _ in range(20):
        c = sqlite3.connect(app_config.db_path)
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        c.close()
        if row["status"] == "complete":
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"Job did not complete; final status: {row['status']}")
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_uploads.py::test_upload_kicks_off_pipeline -v`
Expected: FAIL — job stays in `pending`.

- [ ] **Step 3: Update `app/main.py` lifespan**

Replace the lifespan body to build the harness `DurableContext` and the pipeline service:

```python
"""FastAPI app entry — lifespan owns the durable state."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from card_extractor.agent import DurableContext  # type: ignore

from app.config import AppConfig
from app.db import init_db
from app.routes import health, uploads
from app.services.pipeline import PipelineService


def build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = AppConfig.from_env()
        cfg.ensure_dirs()
        init_db(cfg.db_path)
        conn = sqlite3.connect(cfg.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        durable = DurableContext.from_env()
        durable.output_dir = cfg.state_dir / "harness_out"
        durable.output_dir.mkdir(parents=True, exist_ok=True)

        app.state.config = cfg
        app.state.db = conn
        app.state.pipeline = PipelineService(durable=durable, config=cfg)
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(title="agent-app-card-extractor", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(uploads.router)
    return app


app = build_app()
```

- [ ] **Step 4: Update `app/routes/uploads.py` to schedule the job**

Replace the return block at the bottom of `upload()` (the lines that currently end with `return {"job_id": ..., "status": "pending"}`):

```python
    import asyncio
    asyncio.create_task(
        request.app.state.pipeline.run(conn, job_id=job_id, upload_path=final_path)
    )
    return {"job_id": job_id, "status": "pending"}
```

- [ ] **Step 5: Run all uploads tests to verify pass**

Run: `uv run pytest tests/test_uploads.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/routes/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): trigger pipeline as background task; lifespan owns DurableContext"
```

---

### Task 8: Jobs GET endpoint (status + JSON)

**Files:**
- Create: `D:\agent-app-card-extractor\app\routes\jobs.py`
- Modify: `D:\agent-app-card-extractor\app\main.py` (register router)
- Test: `D:\agent-app-card-extractor\tests\test_jobs.py`

`GET /jobs/:id` returns the job status. If `complete`, the response body includes the parsed JSON output. If `failed`, it includes the error string. No XML yet — that's the next task.

- [ ] **Step 1: Write `tests/test_jobs.py`**

```python
"""Tests for GET /jobs/:id."""
from __future__ import annotations

import io

import pytest


async def test_get_job_404_for_unknown(client):
    r = await client.get("/jobs/does-not-exist")
    assert r.status_code == 404


async def test_get_job_pending_no_extractions(client, monkeypatch):
    """Block the pipeline so the job stays pending while we read it."""
    import asyncio
    from unittest.mock import AsyncMock

    async def slow_process(*args, **kwargs):
        await asyncio.sleep(2)
        return []

    monkeypatch.setattr("app.services.pipeline.process_pdf", slow_process)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    job_id = (await client.post("/uploads", files=files)).json()["job_id"]
    r = await client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"pending", "running"}
    assert "extractions" not in body


async def test_get_job_complete_returns_extractions(client, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    fake = AsyncMock(return_value=[
        {"card_type": "INSURANCE", "insurance": {"member_id": "M1"}, "government": {}, "confidence": 0.8, "issuer_hint": "Aetna"},
    ])
    monkeypatch.setattr("app.services.pipeline.process_pdf", fake)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    job_id = (await client.post("/uploads", files=files)).json()["job_id"]

    for _ in range(20):
        r = await client.get(f"/jobs/{job_id}")
        if r.json()["status"] == "complete":
            break
        await asyncio.sleep(0.05)

    body = r.json()
    assert body["status"] == "complete"
    assert body["extractions"][0]["insurance"]["member_id"] == "M1"


async def test_get_job_failed_returns_error(client, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    monkeypatch.setattr("app.services.pipeline.process_pdf", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    job_id = (await client.post("/uploads", files=files)).json()["job_id"]

    for _ in range(20):
        r = await client.get(f"/jobs/{job_id}")
        if r.json()["status"] == "failed":
            break
        await asyncio.sleep(0.05)

    body = r.json()
    assert body["status"] == "failed"
    assert "boom" in body["error"]
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: FAIL — 404 on `/jobs/...` route.

- [ ] **Step 3: Implement `app/routes/jobs.py`**

```python
"""GET /jobs/:id — job status, plus extractions when complete."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.db import get_job

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, request: Request) -> dict:
    row = get_job(request.app.state.db, job_id)
    if row is None:
        raise HTTPException(404, f"Job {job_id} not found")

    body: dict = {
        "job_id": row["id"],
        "status": row["status"],
        "source_filename": row["source_filename"],
        "created_at": row["created_at"],
    }
    if row["status"] == "complete" and row["output_path"]:
        body["extractions"] = json.loads(Path(row["output_path"]).read_text())["extractions"]
    if row["status"] == "failed":
        body["error"] = row["error"]
    return body
```

- [ ] **Step 4: Register the router in `app/main.py`**

Add `jobs` to the imports and `include_router` calls in `build_app`:

```python
from app.routes import health, jobs, uploads
# ...
    app.include_router(health.router)
    app.include_router(uploads.router)
    app.include_router(jobs.router)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/routes/jobs.py app/main.py tests/test_jobs.py
git commit -m "feat(jobs): GET /jobs/:id returns status, extractions, or error"
```

---

### Task 9: XML serializer

**Files:**
- Create: `D:\agent-app-card-extractor\app\services\serializers.py`
- Test: `D:\agent-app-card-extractor\tests\test_serializers.py`

The serializer takes the same dict payload that lands in `state/outputs/<job_id>.json` and produces an XML string. Element names mirror field names. Lists become repeated elements. Null/empty optional fields are omitted.

- [ ] **Step 1: Write `tests/test_serializers.py`**

```python
"""Tests for app.services.serializers — JSON payload → XML string."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.services.serializers import extraction_payload_to_xml


def test_single_card_round_trip():
    payload = {
        "job_id": "abc",
        "extractions": [
            {
                "card_type": "INSURANCE",
                "insurance": {"member_id": "M1", "subscriber_name": "Jane Doe"},
                "government": {},
                "confidence": 0.9,
                "issuer_hint": "Aetna",
            }
        ],
    }
    xml = extraction_payload_to_xml(payload)
    root = ET.fromstring(xml)
    assert root.tag == "job"
    assert root.attrib["id"] == "abc"
    cards = root.findall("./extractions/card")
    assert len(cards) == 1
    assert cards[0].attrib["type"] == "INSURANCE"
    assert cards[0].find("./issuer_hint").text == "Aetna"
    assert cards[0].find("./confidence").text == "0.9"
    assert cards[0].find("./insurance/member_id").text == "M1"


def test_multiple_cards():
    payload = {
        "job_id": "j2",
        "extractions": [
            {"card_type": "INSURANCE", "insurance": {"member_id": "A"}, "government": {}, "confidence": 0.5, "issuer_hint": "X"},
            {"card_type": "GOVERNMENT", "insurance": {}, "government": {"id_number": "GA-1"}, "confidence": 0.7, "issuer_hint": "Y"},
        ],
    }
    xml = extraction_payload_to_xml(payload)
    root = ET.fromstring(xml)
    assert len(root.findall("./extractions/card")) == 2


def test_empty_strings_and_zero_values_preserved():
    """Falsy-but-present values are kept; only None is omitted."""
    payload = {
        "job_id": "j3",
        "extractions": [
            {"card_type": "INSURANCE", "insurance": {"member_id": ""}, "government": {}, "confidence": 0.0, "issuer_hint": ""},
        ],
    }
    xml = extraction_payload_to_xml(payload)
    root = ET.fromstring(xml)
    card = root.find("./extractions/card")
    assert card.find("./confidence").text == "0.0"
    # Empty string member_id is still emitted (presence matters)
    assert card.find("./insurance/member_id") is not None
    assert card.find("./insurance/member_id").text in ("", None)


def test_none_values_omitted():
    payload = {
        "job_id": "j4",
        "extractions": [
            {"card_type": "INSURANCE", "insurance": {"member_id": None}, "government": {}, "confidence": 0.5, "issuer_hint": "Z"},
        ],
    }
    xml = extraction_payload_to_xml(payload)
    root = ET.fromstring(xml)
    card = root.find("./extractions/card")
    assert card.find("./insurance/member_id") is None


def test_no_extractions():
    payload = {"job_id": "empty", "extractions": []}
    xml = extraction_payload_to_xml(payload)
    root = ET.fromstring(xml)
    assert root.find("./extractions") is not None
    assert root.findall("./extractions/card") == []
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/test_serializers.py -v`
Expected: FAIL — `ImportError: No module named 'app.services.serializers'`

- [ ] **Step 3: Implement `app/services/serializers.py`**

```python
"""JSON-payload → XML serialization for extraction results.

This is a presentation concern — the harness emits Pydantic/JSON. The XML
form here is a literal element-per-field rendering: tag names mirror field
names, lists become repeated elements, None values are omitted, falsy-but-
present values (empty strings, 0, 0.0) are emitted.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def _build_element(tag: str, value: Any, parent: ET.Element) -> None:
    """Append a child element representing `value` under `parent` with name `tag`."""
    if value is None:
        return
    if isinstance(value, dict):
        el = ET.SubElement(parent, tag)
        for k, v in value.items():
            _build_element(k, v, el)
    elif isinstance(value, list):
        for item in value:
            _build_element(tag, item, parent)
    else:
        el = ET.SubElement(parent, tag)
        el.text = str(value)


def extraction_payload_to_xml(payload: dict) -> str:
    """Serialize the on-disk extraction payload to an XML string.

    Input shape: {"job_id": str, "extractions": [<CardExtraction-as-dict>, ...]}
    """
    root = ET.Element("job", attrib={"id": str(payload.get("job_id", ""))})
    extractions_el = ET.SubElement(root, "extractions")
    for card in payload.get("extractions", []):
        card_attrib = {}
        if "card_type" in card:
            card_attrib["type"] = str(card["card_type"])
        card_el = ET.SubElement(extractions_el, "card", attrib=card_attrib)
        for k, v in card.items():
            if k == "card_type":
                continue
            _build_element(k, v, card_el)
    return ET.tostring(root, encoding="unicode")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_serializers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/serializers.py tests/test_serializers.py
git commit -m "feat(serializers): JSON-payload-to-XML element-per-field renderer"
```

---

### Task 10: Jobs XML endpoint

**Files:**
- Modify: `D:\agent-app-card-extractor\app\routes\jobs.py` (add `/jobs/:id/xml`)
- Modify: `D:\agent-app-card-extractor\tests\test_jobs.py` (add XML endpoint tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
async def test_get_job_xml_404_for_unknown(client):
    r = await client.get("/jobs/missing/xml")
    assert r.status_code == 404


async def test_get_job_xml_409_when_not_complete(client, monkeypatch):
    import asyncio
    import io
    from unittest.mock import AsyncMock

    async def slow(*args, **kwargs):
        await asyncio.sleep(2)
        return []

    monkeypatch.setattr("app.services.pipeline.process_pdf", slow)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )
    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    job_id = (await client.post("/uploads", files=files)).json()["job_id"]
    r = await client.get(f"/jobs/{job_id}/xml")
    assert r.status_code == 409


async def test_get_job_xml_returns_xml_for_complete(client, monkeypatch):
    import asyncio
    import io
    import xml.etree.ElementTree as ET
    from unittest.mock import AsyncMock

    fake = AsyncMock(return_value=[
        {"card_type": "INSURANCE", "insurance": {"member_id": "X9"}, "government": {}, "confidence": 0.7, "issuer_hint": "Aetna"},
    ])
    monkeypatch.setattr("app.services.pipeline.process_pdf", fake)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    job_id = (await client.post("/uploads", files=files)).json()["job_id"]

    for _ in range(20):
        r = await client.get(f"/jobs/{job_id}")
        if r.json()["status"] == "complete":
            break
        await asyncio.sleep(0.05)

    r = await client.get(f"/jobs/{job_id}/xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    assert root.find("./extractions/card/insurance/member_id").text == "X9"
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run pytest tests/test_jobs.py -v -k xml`
Expected: 3 FAIL — `/jobs/:id/xml` returns 404 for all routes.

- [ ] **Step 3: Add the XML endpoint to `app/routes/jobs.py`**

Append to the bottom of `jobs.py`:

```python
import json as _json
from fastapi.responses import Response

from app.services.serializers import extraction_payload_to_xml


@router.get("/jobs/{job_id}/xml")
async def get_job_xml(job_id: str, request: Request) -> Response:
    row = get_job(request.app.state.db, job_id)
    if row is None:
        raise HTTPException(404, f"Job {job_id} not found")
    if row["status"] != "complete":
        raise HTTPException(409, f"Job {job_id} is not complete (status: {row['status']})")
    payload = _json.loads(Path(row["output_path"]).read_text())
    return Response(content=extraction_payload_to_xml(payload), media_type="application/xml")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: 7 passed (4 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add app/routes/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): GET /jobs/:id/xml serves XML view of completed job"
```

---

### Task 11: End-to-end smoke test

**Files:**
- Create: `D:\agent-app-card-extractor\tests\test_smoke.py`

A single test that exercises upload → poll → fetch JSON → fetch XML, against a mocked harness. This is the integration-shape check: it doesn't need `AI_GATEWAY_KEY` because `process_pdf` is mocked, but it asserts every layer (HTTP, DB, pipeline, serializer) talks to its neighbors correctly.

- [ ] **Step 1: Write the test**

`tests/test_smoke.py`:

```python
"""End-to-end smoke: upload → poll → JSON → XML, with the harness mocked."""
from __future__ import annotations

import asyncio
import io
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock

import pytest


async def test_full_flow_mocked(client, monkeypatch):
    fake = AsyncMock(return_value=[
        {
            "card_type": "INSURANCE",
            "insurance": {"member_id": "MEM-001", "subscriber_name": "J. Doe"},
            "government": {},
            "confidence": 0.85,
            "issuer_hint": "Aetna",
        }
    ])
    monkeypatch.setattr("app.services.pipeline.process_pdf", fake)
    monkeypatch.setattr(
        "app.services.pipeline.AgentContext",
        type("AC", (), {"for_request": staticmethod(lambda d, rid: type("X", (), {"tracker": type("T", (), {"summary": lambda self: {}})()})())})
    )

    # 1. Upload
    files = {"file": ("card.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    r = await client.post("/uploads", files=files)
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    # 2. Poll until complete
    for _ in range(40):
        r = await client.get(f"/jobs/{job_id}")
        if r.json()["status"] == "complete":
            break
        await asyncio.sleep(0.05)
    assert r.json()["status"] == "complete"

    # 3. Fetch JSON
    body = r.json()
    assert body["extractions"][0]["insurance"]["member_id"] == "MEM-001"

    # 4. Fetch XML
    r = await client.get(f"/jobs/{job_id}/xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    assert root.find("./extractions/card/insurance/member_id").text == "MEM-001"
    assert root.find("./extractions/card/issuer_hint").text == "Aetna"
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (one new + everything from prior tasks).

- [ ] **Step 3: Manual sanity check**

Start the app:

```bash
cp .env.example .env
# fill in AI_GATEWAY_KEY (real value, since this isn't mocked)
uv run uvicorn app.main:app --reload
```

In another terminal:

```bash
curl -sf http://127.0.0.1:8000/health
# {"status":"ok"}
```

Document any rough edges in the README under a new "Known limitations" section if found.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py README.md
git commit -m "test: end-to-end smoke (upload → poll → JSON + XML), harness mocked"
```

---

## Plan 1 exit criteria

- [ ] All tests in `tests/` pass under `uv run pytest -v`.
- [ ] `uv run uvicorn app.main:app` starts cleanly with `AI_GATEWAY_KEY` set.
- [ ] `curl -F file=@<some>.pdf http://127.0.0.1:8000/uploads` returns a `job_id`.
- [ ] Polling `GET /jobs/:id` transitions `pending` → `running` → `complete` (or `failed` with a captured error).
- [ ] `GET /jobs/:id` on a complete job includes the extraction JSON.
- [ ] `GET /jobs/:id/xml` returns the same data as XML.
- [ ] No frontend, no chat, no installer — those are Plans 2-4.

When all boxes are checked, Plan 1 is done and we hand off to Plan 2 (frontend).
