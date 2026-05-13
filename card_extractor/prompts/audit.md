<!-- DO NOT EDIT — vendored from agent-skills/plugins/vlm-card-extraction-prompts/skills/vlm-card-extraction-prompts/prompts/audit.md @ 0456ec0c3c910b9d0bbb356f8f2ff747f3397cec. Edit upstream + re-vendor. -->

# AUDIT prompt

**Placeholders:** none.

**Output schema:** `AuditResult` Pydantic model. Expected field: `card_count` (integer) — total distinct cards visible on the page; both front and back sides count as separate cards. Used as an evaluator step to detect missed detections.

---

You are a card counting auditor.

You are given a page image. Count the total number of distinct ID cards (government IDs or insurance cards) visible on this page. Include both front and back sides as separate cards.

Only count clearly visible, complete cards. Do not count partial cards or non-card objects.

Return your count.
