State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Runbook – Ingest incidenter
- Symptom: dubbletter / saknade poster i `index-outbox.jsonl`
- Checklista:
  1) Verifiera fingerprint/hashing
  2) Kolla PII-redaktion inte nollar content
  3) Läs senaste rader i outbox, validera JSON
- Åtgärd: kör om `normalize/pipe` med `--trace-id`