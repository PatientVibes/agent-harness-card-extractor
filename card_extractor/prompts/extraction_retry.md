<!-- DO NOT EDIT — vendored from agent-skills/plugins/vlm-card-extraction-prompts/skills/vlm-card-extraction-prompts/prompts/extraction_retry.md @ 0456ec0c3c910b9d0bbb356f8f2ff747f3397cec. Edit upstream + re-vendor. -->

# EXTRACTION_RETRY prompt

**Placeholders:** `{issues}` — newline-joined bullet list of issue descriptions from the prior extraction's verification step (e.g., `"- subscriber_name is NONE but member_id is populated\n- member_id: pattern mismatch"`). Caller composes this from `_verify_extraction()` output.

**Output schema:** `CardExtraction` Pydantic model. Same shape as `EXTRACTION` (`card_type`, `insurance`, `government`, `confidence`, `issuer_hint`); missing/unreadable values must be the literal string `"NONE"`.

---

The previous extraction of this card had the following issues:
{issues}

Please re-examine the card image carefully and extract the data again, paying special attention to the flagged issues. If a field is truly unreadable, use "NONE" — but verify before defaulting.

Card type rules:
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
- If uncertain, leave issuer_hint empty.
