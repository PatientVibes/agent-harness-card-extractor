# Changelog

## 0.1.0 — 2026-05-12

Initial public release. Migrated from a private SS&C-owned POC (`gene-card-agent`), generalized and MIT-licensed under Chris Moore personal copyright (see `D:/ai-agents/docs/superpowers/specs/2026-05-12-reference-agents-migration-design.md`).

- LangChain VLM pipeline (detect → verify → extract → validate) for ID cards and insurance cards.
- Karpathy-style learning wiki (`knowledge/issuers/`) accumulates per-issuer patterns across runs.
- Human review queue for low-confidence extractions.
- pypdfium2 (Apache-2.0) for PDF rendering — replaced PyMuPDF (AGPL) during the POC.
- 12-component agent harness implementation.
