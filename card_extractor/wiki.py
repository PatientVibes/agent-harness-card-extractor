"""CardKnowledgeWiki — Karpathy-style markdown knowledge base for card extraction.

Three layers:
- Raw sources: immutable card images (never modified by LLM)
- Wiki: LLM-maintained markdown pages per card issuer/type
- Schema: rules for wiki maintenance (knowledge/schema.md)

Wiki page format
----------------
Each issuer page is markdown with a YAML frontmatter block delimited by ``---``
at the top. The frontmatter is the machine-readable source of truth for
validation rules and is parsed deterministically via ``yaml.safe_load``. The
markdown body below is for human reading and LLM context injection and is
NEVER parsed as a rules engine.

Example:

    ---
    issuer: UnitedHealthcare
    card_type: INSURANCE
    patterns:
      member_id: '^\\d{9}$'
    required_fields:
      - subscriber_name
      - member_id
    version: 1
    last_human_correction: ''
    ---

    # UnitedHealthcare

    ## Card Types
    - INSURANCE
    ...
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from card_extractor.models import IssuerRules


logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert issuer name to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unknown"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split a page into (frontmatter_dict, body_str).

    If the file does not begin with a ``---`` fence, returns ``({}, content)``.
    If the YAML is malformed, logs a warning and returns ``({}, content)`` —
    callers should treat missing frontmatter as "no rules" rather than crashing.
    """
    if not content.startswith("---"):
        return {}, content

    # Find the closing fence. Walk line-by-line so we're robust to CRLF.
    lines = content.splitlines(keepends=True)
    # Skip the opening fence line (lines[0]).
    end_idx = None
    for i in range(1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "---":
            end_idx = i
            break

    if end_idx is None:
        # No closing fence — treat as body only.
        return {}, content

    yaml_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1:])

    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        logger.warning("Malformed YAML frontmatter: %s", e)
        return {}, body

    if not isinstance(data, dict):
        logger.warning("YAML frontmatter is not a mapping; ignoring.")
        return {}, body

    return data, body


def _serialize_page(rules: IssuerRules, body: str) -> str:
    """Render a wiki page as frontmatter + markdown body."""
    yaml_text = yaml.safe_dump(
        rules.model_dump(),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    # Ensure body starts with a newline for readability.
    if body and not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{yaml_text}---{body}"


class CardKnowledgeWiki:
    """File-based knowledge wiki for card extraction patterns."""

    def __init__(self, wiki_dir: Path):
        self.wiki_dir = wiki_dir
        self.issuers_dir = wiki_dir / "issuers"
        self.index_path = wiki_dir / "index.md"
        self.log_path = wiki_dir / "log.md"
        self.template_path = self.issuers_dir / "_template.md"

        self.issuers_dir.mkdir(parents=True, exist_ok=True)

        # Serializes concurrent mutating operations across asyncio tasks.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def lookup(self, issuer_hint: str, card_type: str = "") -> Optional[str]:
        """Read wiki page content for an issuer. Returns None if not found.

        Returns the full page text (frontmatter + body) for LLM context /
        display. Callers that want only rules must call ``get_extraction_hints``.
        """
        slug = _slugify(issuer_hint)
        page_path = self.issuers_dir / f"{slug}.md"
        if page_path.exists():
            return page_path.read_text(encoding="utf-8")
        return None

    def get_index(self) -> dict[str, list[str]]:
        """Parse index.md into {issuer_slug: [card_types]} mapping."""
        if not self.index_path.exists():
            return {}

        result: dict[str, list[str]] = {}
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            # Parse table rows: | issuer | card_types | ... |
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1] and parts[1] != "Issuer" and not parts[1].startswith("-"):
                slug = _slugify(parts[1])
                card_types = [t.strip() for t in parts[2].split(",") if t.strip()]
                result[slug] = card_types

        return result

    def get_extraction_hints(self, issuer_hint: str, card_type: str = "") -> dict:
        """Return validated rules from YAML frontmatter as a typed dict.

        Returns dict with optional keys:
        - patterns: {field_name: regex_pattern}
        - required_fields: [field_names]

        If frontmatter is missing, empty, or fails Pydantic validation, logs
        and returns ``{}`` — the caller then operates without wiki rules
        rather than silently accepting broken rules.
        """
        content = self.lookup(issuer_hint, card_type)
        if not content:
            return {}

        frontmatter, _body = _parse_frontmatter(content)
        if not frontmatter:
            return {}

        try:
            rules = IssuerRules(**frontmatter)
        except Exception as e:
            logger.error(
                "Invalid IssuerRules frontmatter for issuer %r: %s",
                issuer_hint,
                e,
            )
            return {}

        hints: dict = {}
        if rules.patterns:
            hints["patterns"] = dict(rules.patterns)
        if rules.required_fields:
            hints["required_fields"] = list(rules.required_fields)
        return hints

    # ------------------------------------------------------------------
    # Page construction helpers
    # ------------------------------------------------------------------

    def _render_template_body(self, issuer: str, card_type: str) -> str:
        """Return the default markdown body for a new issuer page (no frontmatter)."""
        if self.template_path.exists():
            template = self.template_path.read_text(encoding="utf-8")
            # The template may itself include a frontmatter block — strip it;
            # we only want the body here.
            _fm, body = _parse_frontmatter(template)
            body = body.replace("{{issuer}}", issuer)
            body = body.replace("{{card_type}}", card_type)
            return body

        return (
            f"\n# {issuer}\n\n"
            f"## Card Types\n- {card_type}\n\n"
            f"## Layout Observations\n\n"
            f"## Observation Log\n"
        )

    def _load_page(
        self, slug: str, issuer: str, card_type: str,
    ) -> tuple[IssuerRules, str, Path]:
        """Load existing page (or seed defaults). Returns (rules, body, path)."""
        page_path = self.issuers_dir / f"{slug}.md"
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(content)
            try:
                rules = IssuerRules(**frontmatter) if frontmatter else IssuerRules(
                    issuer=issuer, card_type=card_type or "INSURANCE",  # type: ignore[arg-type]
                )
            except Exception as e:
                logger.error(
                    "Invalid existing frontmatter for %s; rebuilding: %s", slug, e,
                )
                rules = IssuerRules(
                    issuer=issuer,
                    card_type=card_type or "INSURANCE",  # type: ignore[arg-type]
                )
        else:
            rules = IssuerRules(
                issuer=issuer,
                card_type=card_type or "INSURANCE",  # type: ignore[arg-type]
            )
            body = self._render_template_body(issuer, card_type)
        return rules, body, page_path

    # ------------------------------------------------------------------
    # Write operations (all async; hold self._lock)
    # ------------------------------------------------------------------

    async def update_index(self, issuer: str, card_type: str) -> None:
        """Add entry to index.md if not present."""
        async with self._lock:
            self._update_index_locked(issuer, card_type)

    def _update_index_locked(self, issuer: str, card_type: str) -> None:
        slug = _slugify(issuer)
        index = self.get_index()

        if slug in index and card_type in index[slug]:
            return  # already present

        if slug in index:
            index[slug].append(card_type)
        else:
            index[slug] = [card_type]

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [
            "# Card Type Index\n",
            "| Issuer | Card Types | Last Updated |",
            "|--------|-----------|--------------|",
        ]
        for s, types in sorted(index.items()):
            types_str = ", ".join(types)
            lines.append(f"| {s} | {types_str} | {now} |")

        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def write_observation(
        self,
        issuer: str,
        card_type: str,
        observation: str,
        source_pdf: str = "",
        confidence: float = 0.0,
    ) -> Path:
        """Append observation to issuer page body. Never touches frontmatter.

        If the page does not exist, creates it from the template (which
        includes empty frontmatter).
        """
        async with self._lock:
            slug = _slugify(issuer)
            rules, body, page_path = self._load_page(slug, issuer, card_type)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            # Append observation to body only.
            entry = (
                f"\n### {now} | {source_pdf} | confidence={confidence:.2f}\n"
                f"{observation}\n"
            )
            body = body + entry

            page_path.write_text(_serialize_page(rules, body), encoding="utf-8")

            # Append to log.md
            log_entry = f"## [{now}] observe | {issuer} | {source_pdf}\n{observation}\n\n"
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(log_entry)

            # Update index inline (we already hold the lock).
            self._update_index_locked(issuer, card_type)

            return page_path

    async def compile_correction(
        self,
        issuer: str,
        card_type: str,
        original_text: str = "",
        correction_text: str = "",
        source_pdf: str = "",
        patterns: Optional[dict[str, str]] = None,
        required_fields: Optional[list[str]] = None,
    ) -> Path:
        """Compile a human correction into the wiki.

        Updates the YAML frontmatter (the machine-readable rules) with any
        ``patterns`` / ``required_fields`` provided, validates every regex
        compiles before writing, bumps ``version``, and stamps
        ``last_human_correction``. Also appends a human-readable note to the
        body log. If an invalid regex is supplied, raises ``re.error`` and
        writes nothing.

        The ``original_text`` / ``correction_text`` args are kept for
        backward compatibility with callers that pass free-form diff text —
        they are recorded in the body log but do not mutate the frontmatter.
        """
        async with self._lock:
            slug = _slugify(issuer)
            rules, body, page_path = self._load_page(slug, issuer, card_type)

            # Merge structured corrections into rules.
            if patterns:
                merged = dict(rules.patterns)
                merged.update(patterns)
                rules.patterns = merged
            if required_fields:
                existing = list(rules.required_fields)
                for f in required_fields:
                    if f not in existing:
                        existing.append(f)
                rules.required_fields = existing

            rules.version = int(rules.version) + 1
            rules.last_human_correction = datetime.now(timezone.utc).isoformat()
            if not rules.issuer:
                rules.issuer = issuer
            # Only override card_type if it's a recognized value.
            if card_type in ("INSURANCE", "GOVERNMENT"):
                rules.card_type = card_type  # type: ignore[assignment]

            # Validate — raises re.error before any write.
            try:
                rules.validate_patterns()
            except re.error as e:
                raise re.error(
                    f"Refusing to write wiki rules for {issuer!r}: bad regex "
                    f"({e}). Frontmatter unchanged."
                ) from e

            # Append a human-readable audit note to the body log.
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            summary_parts: list[str] = []
            if original_text:
                summary_parts.append(f"- Original: {original_text}")
            if correction_text:
                summary_parts.append(f"- Corrected: {correction_text}")
            if patterns:
                summary_parts.append(f"- Patterns updated: {list(patterns.keys())}")
            if required_fields:
                summary_parts.append(f"- Required fields added: {required_fields}")
            summary = "\n".join(summary_parts) or "- (no diff text provided)"

            entry = (
                f"\n### {now} HUMAN CORRECTION | {source_pdf}\n"
                f"{summary}\n"
            )
            body = body + entry

            page_path.write_text(_serialize_page(rules, body), encoding="utf-8")

            # Also append to log.md.
            log_entry = (
                f"## [{now}] correction | {issuer} | {source_pdf}\n{summary}\n\n"
            )
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(log_entry)

            self._update_index_locked(issuer, card_type)

            return page_path
