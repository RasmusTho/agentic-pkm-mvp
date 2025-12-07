State: SoT v4.10 Reality-MVP (current).
# Reality-MVP: note → ingest → index → ASK

Single-note Reality-MVP flow that already fits the existing SoT (vault plane, memory backend for tests).
- Input note: `tests/fixtures/reality_mvp/demo_note.md` (hot/semi-active vault note).
- Flow: note file → ingest/normalize/classify → store/outbox/index → hybrid search warm-load → `/api/ask`.
- Question to hit this flow: “Which store backend do the Reality-MVP tests rely on?”
- Expected answer: mentions the memory store backend and cites the ingested note.
- Source expectations: origin `vault`, path points to the ingested note; zone/trust are inherited from current pipeline defaults.
- Purpose: canonical, deterministic end-to-end check without changing runtime prompts or agent behavior.

## References
- Enforced by `tests/e2e/test_reality_mvp_pipeline.py` (memory store, mock LLM).
- CLI ingest in the test uses `ingest_vault_root` (non-recursive) to populate HybridStore before `/api/ask`.
