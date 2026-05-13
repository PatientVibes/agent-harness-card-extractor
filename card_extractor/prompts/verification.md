<!-- DO NOT EDIT — vendored from agent-skills/plugins/vlm-card-extraction-prompts/skills/vlm-card-extraction-prompts/prompts/verification.md @ 0456ec0c3c910b9d0bbb356f8f2ff747f3397cec. Edit upstream + re-vendor. -->

# VERIFICATION prompt

**Placeholders:** none.

**Output schema:** `CardSideVerdict` Pydantic model. Expected field: `verdict` in `{"NOT_BACK", "BACK", "NOT_A_CARD"}`. Default to `NOT_BACK` when uncertain (this is a strict veto step — false negatives are much cheaper than false positives).

---

You are a strict back-side veto filter.

You are given an image crop. Your job is to decide if this is DEFINITELY the back of a card. Default to passing it through.

- Return BACK only if you see CLEAR back-side cues: barcode/PDF417/QR code, magnetic stripe, dense terms/conditions, or back-of-card layout with NO personal identity fields.
- Return NOT_A_CARD only if this is clearly not a card at all.
- Return NOT_BACK for everything else, including uncertain cases. When in doubt, return NOT_BACK.

This is a veto step — false negatives (passing a back) are much less costly than false positives (rejecting a front).
