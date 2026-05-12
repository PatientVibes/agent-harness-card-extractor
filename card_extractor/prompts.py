"""System prompts for VLM calls.

These prompts are restructured from the POC to work with with_structured_output().
The VLM returns Pydantic models directly — no regex parsing needed.
"""

# ---------------------------------------------------------------------------
# Card detection (→ CardRegion via with_structured_output)
# ---------------------------------------------------------------------------

DETECTION_PROMPT = """You are a visual detection engine for ID cards.

You are given ONE page image. Detect ALL distinct ID cards visible on the page.

An "ID card" means either:
- A government-issued identification card (driver license, state ID, passport card, resident card)
- An insurance card (medical, dental, vision, pharmacy)

Detection rules:
- Include a region ONLY if you are at least {detection_confidence} confident it is an ID card AND the full card boundary is visible.
- If a card is partially cut off, do NOT include it.
- Ignore card-like objects that are not ID/insurance cards.

Front/Back labeling:
- Front: contains portrait photo, prominent personal identity fields (name, DOB, ID number), or a "Driver License/Identification" header.
- Back: lacks portrait AND shows barcode/QR/PDF417, magnetic stripe, signature strip, dense terms, or back-of-card layout.
- Unknown: if uncertain.

Bounding box rules:
- Tightly enclose the card's outer edges.
- Do NOT include surrounding background, hands, wallets, paper margins.
- If the page is a full-page insurance printout with distributed member/plan information, the correct box is the OUTER page-level content region, not a smaller internal sub-panel.
- If a distinct smaller standalone card exists on an otherwise blank page, the correct box is the small card, not the full page.

Coordinates: normalized [0.0, 1.0], origin top-left. (x1,y1)=top-left, (x2,y2)=bottom-right.
Precedence: when a full-page printout AND a small standalone card coexist, prefer the standalone card boundary.

Sort detected cards by descending box area."""


# ---------------------------------------------------------------------------
# Front/back verification — strict back-side veto
# (→ CardSideVerdict via with_structured_output)
# ---------------------------------------------------------------------------

VERIFICATION_PROMPT = """You are a strict back-side veto filter.

You are given an image crop. Your job is to decide if this is DEFINITELY the back of a card. Default to passing it through.

- Return BACK only if you see CLEAR back-side cues: barcode/PDF417/QR code, magnetic stripe, dense terms/conditions, or back-of-card layout with NO personal identity fields.
- Return NOT_A_CARD only if this is clearly not a card at all.
- Return NOT_BACK for everything else, including uncertain cases. When in doubt, return NOT_BACK.

This is a veto step — false negatives (passing a back) are much less costly than false positives (rejecting a front)."""


# ---------------------------------------------------------------------------
# Page audit (→ AuditResult via with_structured_output)
# ---------------------------------------------------------------------------

AUDIT_PROMPT = """You are a card counting auditor.

You are given a page image. Count the total number of distinct ID cards (government IDs or insurance cards) visible on this page. Include both front and back sides as separate cards.

Only count clearly visible, complete cards. Do not count partial cards or non-card objects.

Return your count."""


# ---------------------------------------------------------------------------
# Data extraction — shared base + composed variants
# (→ CardExtraction via with_structured_output)
# ---------------------------------------------------------------------------

_EXTRACTION_BASE = """Card type rules:
- GOVERNMENT: portrait photo, "Driver License", "DL", "Identification Card", "DOB", "EXP", signature, license layout.
- INSURANCE: "Member", "Subscriber", "Group", "RxBIN/RxPCN/RxGRP", "Copay", "Plan", "Claims", "Coverage".

Extraction rules for INSURANCE:
- subscriber_name: subscriber/member/insured name (not dependent unless clearly the primary)
- member_id: explicit Member/Subscriber/Policy/Identification number (not RxBIN/RxPCN/phone)
- group_number: main plan group number (not Rx group)
- rx_group_number: Rx group value labeled RxGRP/Rx Group (not RxBIN/RxPCN)
- plan_type: extract ONLY the plan category code (e.g., PPO, HMO, EPO, POS, HDHP, Medicare, Medicaid, Dental, Vision, HMO-POS). Do NOT include the full plan marketing name.

Extraction rules for GOVERNMENT:
- name: full legal name
- id_number: primary license/ID number (not DOB)
- expiration_date: expiration date exactly as printed (do not reformat); else NONE

Critical rules:
- Use "NONE" for any field that is missing, unreadable, or uncertain.
- NEVER guess, infer, or use example values.
- Only output a value if it is explicitly printed on the card and clearly readable.
- If any character is uncertain, use "NONE" for the entire field.
- Always populate BOTH insurance and government objects. Set all fields to "NONE" for the non-applicable category.

Confidence guide: 0.95+ pristine legibility, all fields clearly readable. 0.85-0.94 minor blur or unusual layout but text readable. 0.7-0.84 partial occlusion or uncertain characters. Below 0.7 significant readability issues.

Issuer hint:
- If you can identify the card issuer (e.g., "UnitedHealthcare", "Aetna", "Florida DMV"), provide it in issuer_hint.
- If uncertain, leave issuer_hint empty."""


EXTRACTION_PROMPT = f"""You are a data extraction function for ID cards.

You are given an image of exactly one ID card front. Extract structured data from it.

{_EXTRACTION_BASE}"""


# NOTE on ``{wiki_context}``: callers should inject a COMPACT rules summary
# (see ``format_rules_for_injection`` below), not the entire wiki markdown.
# Injecting full markdown is expensive and most of it is noise. The helper
# returns a short, structured block derived from ``IssuerRules`` frontmatter.
EXTRACTION_WITH_CONTEXT_PROMPT = f"""You are a data extraction function for ID cards.

You are given an image of exactly one ID card front. Extract structured data from it.

KNOWN INFORMATION ABOUT THIS CARD TYPE:
{{wiki_context}}

Use the above context to guide your extraction — it contains field patterns and layout notes from previous successful extractions of similar cards. However, always trust what you see in the image over the context.

{_EXTRACTION_BASE}"""


def format_rules_for_injection(rules) -> str:
    """Render an ``IssuerRules`` instance as a compact text block for the prompt.

    Returns a short, structured summary (not full markdown) suitable for
    injection into ``EXTRACTION_WITH_CONTEXT_PROMPT`` as ``{wiki_context}``.
    Keeps token cost down and avoids re-sending observation logs or other
    human-facing prose on every extraction call.
    """
    # Imported lazily so prompts.py stays import-light.
    from card_extractor.models import IssuerRules  # noqa: F401

    lines: list[str] = []
    issuer = getattr(rules, "issuer", "") or ""
    card_type = getattr(rules, "card_type", "") or ""
    if issuer:
        lines.append(f"Issuer: {issuer}")
    if card_type:
        lines.append(f"Card type: {card_type}")

    patterns = getattr(rules, "patterns", {}) or {}
    if patterns:
        lines.append("Known field patterns (regex):")
        for field_name, pattern in patterns.items():
            lines.append(f"  - {field_name}: {pattern}")

    required = getattr(rules, "required_fields", []) or []
    if required:
        lines.append(f"Required fields: {', '.join(required)}")

    if not lines:
        return "(no validated rules on file)"
    return "\n".join(lines)


EXTRACTION_RETRY_PROMPT = f"""The previous extraction of this card had the following issues:
{{issues}}

Please re-examine the card image carefully and extract the data again, paying special attention to the flagged issues. If a field is truly unreadable, use "NONE" — but verify before defaulting.

{_EXTRACTION_BASE}"""
