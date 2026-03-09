State: Spec (not enforced by runtime; keep this doc honest by stating what is measured vs aspirational).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Scorecards (Spec)

This file defines the *shape* of evaluation/fitness targets we want to track over time. It is **not** currently a hard gate in CI unless a test suite explicitly reads these targets.

## Current Reality (v5.5)
- Fitness/CI gates are described in `docs/TESTING.md` and `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`.
- Some eval tests exist under `tests/eval/` but are opt-in.

## Example Targets (Aspirational)

```yaml
ingestion_quality:
  frontmatter_core6_complete: true
  chunk_semantics_ok: true
retrieval_answering:
  faithfulness: \">= 0.8\"
  provenance: \">= 0.8\"
```

## Delta (Spec vs Code)
- No runtime component consumes this scorecard file today.
- If we want CI to enforce scorecards, we should add a parser + a gate that fails when metrics fall below targets.
