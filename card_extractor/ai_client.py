"""AI Gateway client, retry logic, and token tracking.

Pattern adapted from a sibling Chorus CSD analyzer harness using the
same OpenAI-compatible gateway approach.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-32B-Instruct"
DEFAULT_TEXT_MODEL = "Qwen/Qwen3-30B-A3B"
DEFAULT_GATEWAY_URL = ""


@dataclass
class GatewayConfig:
    """AI Gateway configuration loaded from environment."""

    url: str = ""
    api_key: str = ""
    vlm_model: str = DEFAULT_VLM_MODEL
    text_model: str = DEFAULT_TEXT_MODEL
    vlm_temperature: float = 0.1
    extraction_temperature: float = 0.0
    max_tokens: int = 8192

    @classmethod
    def from_env(cls) -> GatewayConfig:
        return cls(
            url=os.environ.get("AI_GATEWAY_URL", DEFAULT_GATEWAY_URL),
            api_key=os.environ.get("AI_GATEWAY_KEY", ""),
            vlm_model=os.environ.get("VLM_MODEL", DEFAULT_VLM_MODEL),
            text_model=os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL),
            vlm_temperature=float(os.environ.get("VLM_TEMPERATURE", "0.1")),
            extraction_temperature=float(os.environ.get("EXTRACTION_TEMPERATURE", "0.0")),
        )

    @property
    def available(self) -> bool:
        return bool(self.url and self.api_key)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def create_vlm(config: GatewayConfig) -> ChatOpenAI:
    """Create a ChatOpenAI instance for vision-language tasks."""
    return ChatOpenAI(
        base_url=f"{config.url.rstrip('/')}/v1",
        api_key=config.api_key,
        model=config.vlm_model,
        temperature=config.vlm_temperature,
        max_tokens=config.max_tokens,
        default_headers={"X-API-Key": config.api_key},
    )


def create_extraction_llm(config: GatewayConfig) -> ChatOpenAI:
    """Create a ChatOpenAI instance for structured extraction (temperature=0)."""
    return ChatOpenAI(
        base_url=f"{config.url.rstrip('/')}/v1",
        api_key=config.api_key,
        model=config.vlm_model,
        temperature=config.extraction_temperature,
        max_tokens=config.max_tokens,
        default_headers={"X-API-Key": config.api_key},
    )


# ---------------------------------------------------------------------------
# Connection check (from chorus-agent ai_client.py)
# ---------------------------------------------------------------------------


async def check_gateway_connection(config: GatewayConfig) -> bool:
    """Verify the AI Gateway is reachable."""
    if not config.available:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{config.url.rstrip('/')}/v1/models",
                headers={"X-API-Key": config.api_key},
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning("AI Gateway connection check failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Retry logic (from chorus-agent agent.py:64-96)
# ---------------------------------------------------------------------------


def _is_transient(exc: Exception) -> bool:
    """Check if an exception is a transient error worth retrying."""
    msg = str(exc).lower()
    if any(code in msg for code in ["429", "500", "502", "503", "504"]):
        return True
    if any(kw in msg for kw in ["timeout", "connection", "temporarily", "rate limit"]):
        return True
    return False


def is_fatal(exc: Exception) -> bool:
    """Check if an exception is a fatal error that should stop processing."""
    msg = str(exc)
    return "403" in msg or "Forbidden" in msg or "413" in msg


async def retry_async(coro_factory, max_retries: int = 1, backoff: float = 2.0):
    """Retry an async callable on transient errors with exponential backoff.

    coro_factory: a zero-arg callable that returns a new coroutine each call.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if is_fatal(e):
                raise
            if attempt < max_retries and _is_transient(e):
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "Transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, wait, e,
                )
                await asyncio.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Token tracking (from chorus-agent pattern)
# ---------------------------------------------------------------------------


@dataclass
class TokenRecord:
    source: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: float = 0.0


@dataclass
class TokenTracker:
    """Track token usage across agent operations."""

    records: list[TokenRecord] = field(default_factory=list)

    def record(
        self,
        source: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.records.append(TokenRecord(
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=time.time(),
        ))

    @property
    def total_input(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output(self) -> int:
        return sum(r.output_tokens for r in self.records)

    def record_from_response(self, source: str, model: str, msg) -> None:
        """Extract token usage from a LangChain response message."""
        um = getattr(msg, "usage_metadata", None)
        if um:
            self.record(
                source=source,
                model=model,
                input_tokens=um.get("input_tokens", 0),
                output_tokens=um.get("output_tokens", 0),
            )

    def summary(self) -> dict:
        return {
            "total_input_tokens": self.total_input,
            "total_output_tokens": self.total_output,
            "total_calls": len(self.records),
            "by_source": self._by_source(),
        }

    def _by_source(self) -> dict[str, dict]:
        groups: dict[str, dict] = {}
        for r in self.records:
            if r.source not in groups:
                groups[r.source] = {"input": 0, "output": 0, "calls": 0}
            groups[r.source]["input"] += r.input_tokens
            groups[r.source]["output"] += r.output_tokens
            groups[r.source]["calls"] += 1
        return groups
