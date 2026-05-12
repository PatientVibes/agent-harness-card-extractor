# Wiki Maintenance Rules

This file defines how the card knowledge wiki is structured and maintained.
It is immutable — changes are version-controlled, not LLM-generated.

## Page format: YAML frontmatter + markdown body

Each issuer page (`issuers/<slug>.md`) begins with a YAML frontmatter block
delimited by `---` fences, followed by a human-readable markdown body.

```
---
issuer: UnitedHealthcare
card_type: INSURANCE
patterns:
  member_id: '^\d{9}$'
  group_number: '^\d{2}-\d{6}$'
required_fields:
  - subscriber_name
  - member_id
version: 1
last_human_correction: ''
---

# UnitedHealthcare

## Card Types
- INSURANCE

## Layout Observations

## Observation Log
```

### Frontmatter is the rules source of truth

- The YAML frontmatter is the **machine-readable source of truth** for
  validation rules. Python parses it deterministically via `yaml.safe_load`
  into a Pydantic `IssuerRules` model. The markdown body is never parsed as
  a rules engine.
- Every regex in `patterns:` is compiled at write time via
  `IssuerRules.validate_patterns()`. If any pattern fails to compile, the
  write is rejected — no broken rules ever land in the wiki.
- Invalid frontmatter (malformed YAML, fields that fail Pydantic
  validation) is logged at ERROR and treated as "no rules" rather than
  silently degrading to partial validation.

### Markdown body is for humans and LLM context

- The body holds layout observations, sample value patterns with PII
  masked, and an append-only observation log.
- Bodies may be injected as LLM context for display/lookup. For extraction
  calls prefer injecting only the compact rules summary (see
  `prompts.format_rules_for_injection`), not the full markdown — saves
  tokens and removes noise.

## Frontmatter schema (`IssuerRules`)

| Field | Type | Notes |
|-------|------|-------|
| `issuer` | str | Display name of the issuer. |
| `card_type` | Literal["INSURANCE", "GOVERNMENT"] | Primary card category. |
| `patterns` | dict[str, str] | `field_name -> regex`. Every value must compile. |
| `required_fields` | list[str] | Fields an extraction of this issuer must populate. |
| `version` | int | Bumped on each human correction. |
| `last_human_correction` | str | ISO-8601 timestamp of the last correction, or `""`. |

## When to create a new issuer page

- After extracting data from a card type not yet in the index.
- Use `issuers/_template.md` as the starting point — it already contains
  an empty frontmatter block with the required keys.

## When to update an issuer page

- After a successful extraction with new layout observations — append to
  the markdown body only, never touch frontmatter.
- After a human correction is compiled — frontmatter is updated (patterns /
  required_fields / version / last_human_correction) AND the correction is
  recorded in the body log.
- Never delete existing observations; append with timestamp.

## Observation format

Each observation block in the body must include:
- Date, source PDF, confidence score.
- Field patterns observed (PII-masked).
- Layout notes (e.g. "group number appears below member ID on right side").

## Human corrections

Human corrections are the highest-priority input and are the ONLY path by
which `patterns` / `required_fields` in the frontmatter are modified.
`compile_correction()` validates every regex compiles before writing and
bumps `version`.

## Index maintenance

`index.md` is auto-maintained. Each issuer gets one row with card types
and last-updated date. Do not edit manually.

## Log

`log.md` is append-only. Every observation and correction is logged
chronologically.
