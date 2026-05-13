"""Prompt constants loaded from vendored .md files.

The actual prompt text lives in card_extractor/prompts/*.md, vendored from
the vlm-card-extraction-prompts skill. Edit upstream in the skill repo and
re-vendor (see README.md) — do NOT edit the .md files in this dir.
"""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


DETECTION_PROMPT = _load("detection")
VERIFICATION_PROMPT = _load("verification")
EXTRACTION_PROMPT = _load("extraction")
EXTRACTION_RETRY_PROMPT = _load("extraction_retry")
EXTRACTION_WITH_CONTEXT_PROMPT = _load("extraction_with_context")
AUDIT_PROMPT = _load("audit")
