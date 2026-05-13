"""AI Gateway client, retry logic, and token tracking.

Pattern adapted from a sibling Chorus CSD analyzer harness using the
same OpenAI-compatible gateway approach.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx
from langchain_openai import ChatOpenAI
from llm_utils import is_transient, retry_async  # noqa: F401  (re-exported for callers)
from token_tracker import TokenTracker  # noqa: F401  (re-exported for callers)

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
# Retry logic and token tracking are imported from sibling tools
# (`llm_utils` and `token_tracker`). They used to live inline in this file;
# see commit history pre-2026-05-13. They were extracted as reusable tools
# per the agent-toolbox extraction (`D:/ai-agents/docs/superpowers/specs/
# 2026-05-12-agent-toolbox-extraction-design.md`).
# ---------------------------------------------------------------------------
