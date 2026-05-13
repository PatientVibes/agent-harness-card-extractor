"""FastAPI web service for card extraction.

Endpoints:
- POST /extract — upload PDF, get extractions (per-request run_id subdir)
- GET /review — list pending review items
- POST /review/{item_id} — submit human review
- GET /wiki/{issuer} — read wiki page
- GET /health/live — process-level liveness (no dependency calls)
- GET /health/ready — readiness (checks upstream gateway)
- GET /health — alias for /health/ready (backward compatibility)

Request isolation
-----------------
Durable state (GatewayConfig, wiki, review queue, base output dir, tunables)
is built once during the FastAPI ``lifespan`` startup and stored on
``app.state.durable``. Each ``/extract`` invocation generates a UUID4
``run_id`` and constructs a request-scoped ``AgentContext`` via
``AgentContext.for_request(...)`` — which gives it a fresh TokenTracker,
a fresh PipelineTrace, and a per-run output subdirectory. Token summaries
returned to the caller are therefore per-request, not cumulative.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from card_extractor.agent import AgentContext, DurableContext, process_pdf
from card_extractor.ai_client import check_gateway_connection
from card_extractor.models import CardExtraction

load_dotenv()
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB streaming chunk


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build durable state once at startup and attach to app.state.

    This replaces the previous module-level singleton and the token bleed
    it caused: TokenTracker and PipelineTrace are no longer shared across
    requests.
    """
    durable = DurableContext.from_env()
    durable.output_dir.mkdir(parents=True, exist_ok=True)
    app.state.durable = durable
    logger.info(
        "Lifespan startup: output_dir=%s gateway=%s",
        durable.output_dir,
        "configured" if durable.config.available else "missing",
    )
    try:
        yield
    finally:
        logger.info("Lifespan shutdown")


app = FastAPI(title="Card Extractor", version="0.1.0", lifespan=lifespan)


def _durable(request_app: FastAPI = None) -> DurableContext:
    """Accessor for the durable context stored on app.state."""
    return app.state.durable


async def verify_api_key(x_api_key: str = Header(...)):
    durable = _durable()
    if not durable.config.api_key or x_api_key != durable.config.api_key:
        raise HTTPException(401, "Invalid API key")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health/live")
async def health_live():
    """Process liveness — returns 200 immediately, no dependency calls."""
    return {"status": "alive"}


async def _health_ready_impl():
    durable = _durable()
    gateway_ok = await check_gateway_connection(durable.config)
    return {
        "status": "ok" if gateway_ok else "degraded",
        "gateway_connected": gateway_ok,
        "vlm_available": bool(durable.config.vlm_model),
        "text_available": bool(durable.config.text_model),
    }


@app.get("/health/ready")
async def health_ready():
    """Readiness — exercises the upstream gateway."""
    return await _health_ready_impl()


@app.get("/health")
async def health():
    """Backward-compatible alias for /health/ready."""
    return await _health_ready_impl()


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


class ExtractionResponse(BaseModel):
    pdf_name: str
    run_id: str
    extractions: list[CardExtraction]
    token_summary: dict


@app.post("/extract", response_model=ExtractionResponse, dependencies=[Depends(verify_api_key)])
async def extract(file: UploadFile = File(...)):
    """Upload a PDF and extract card data.

    Each request gets a UUID4 ``run_id`` and a fresh request-scoped
    AgentContext. Artifacts land under ``<output_dir>/<run_id>/``. The
    returned ``token_summary`` reflects only this request.
    """
    safe_name = re.sub(r'[^\w.\-]', '_', Path(file.filename or "upload.pdf").name)
    if not safe_name.lower().endswith('.pdf'):
        raise HTTPException(400, "File must be a PDF")

    durable = _durable()
    if not durable.config.available:
        raise HTTPException(503, "Service unavailable")

    run_id = str(uuid.uuid4())
    ctx = AgentContext.for_request(durable, run_id)

    # Save upload to temp file via chunked streaming so we never load the
    # entire PDF into memory. Abort as soon as MAX_UPLOAD_BYTES is crossed.
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        pdf_path = tmp_dir / safe_name
        total = 0
        with pdf_path.open("wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413,
                        f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    )
                f.write(chunk)

        extractions = await process_pdf(pdf_path, ctx)

        return ExtractionResponse(
            pdf_name=safe_name,
            run_id=run_id,
            extractions=extractions,
            token_summary=ctx.tracker.summary(),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------


@app.get("/review", dependencies=[Depends(verify_api_key)])
async def list_reviews():
    durable = _durable()
    pending = durable.review_queue.list_pending()
    return {"count": len(pending), "items": [item.model_dump() for item in pending]}


class ReviewSubmission(BaseModel):
    status: Literal["approved", "corrected", "rejected"]
    correction: Optional[CardExtraction] = None


@app.post("/review/{item_id}", dependencies=[Depends(verify_api_key)])
async def submit_review(item_id: str, body: ReviewSubmission):
    durable = _durable()
    item = durable.review_queue.submit_review(item_id, body.status, body.correction)
    if item is None:
        raise HTTPException(404, f"Review item {item_id} not found")

    # If corrected, compile to wiki
    if body.status == "corrected" and body.correction:
        count = await durable.review_queue.compile_reviewed_to_wiki(durable.wiki)
        return {"item": item.model_dump(), "wiki_updates": count}

    return {"item": item.model_dump()}


# ---------------------------------------------------------------------------
# Wiki
# ---------------------------------------------------------------------------


@app.get("/wiki/{issuer}", dependencies=[Depends(verify_api_key)])
async def get_wiki_page(issuer: str):
    durable = _durable()
    content = durable.wiki.lookup(issuer)
    if not content:
        raise HTTPException(404, f"No wiki page for '{issuer}'")
    return {"issuer": issuer, "content": content}


@app.get("/wiki", dependencies=[Depends(verify_api_key)])
async def list_wiki():
    durable = _durable()
    index = durable.wiki.get_index()
    return {"issuers": index}
