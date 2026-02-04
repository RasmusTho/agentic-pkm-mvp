State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Reality-MVP: note → ingest → index → ASK

Single-note Reality-MVP flow that already fits the existing SoT (vault plane, memory backend for tests).
- Input note: `tests/fixtures/reality_mvp/demo_note.md` (hot/semi-active vault note).
- Flow: note file → ingest/normalize/classify → store/outbox/index → hybrid search warm-load → `/api/ask`.
- Question to hit this flow: “Which store backend do the Reality-MVP tests rely on?”
- Expected answer: mentions the memory store backend and cites the ingested note.
- Source expectations: origin `vault`, path points to the ingested note; zone/trust are inherited from current pipeline defaults.
- Purpose: canonical, deterministic end-to-end check without changing runtime prompts or agent behavior.