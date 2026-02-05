State: Historical (SoT v4.10). Projector behavior is not the current baseline; keep as reference only and prefer `docs/STATUS.md` + `docs/ARCHITECTURE.md` for current runtime.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# PROJECTOR

## Purpose
- Render-only mirror of selected `objects.payload` fields to the file system.
- Never mutates DB; one-way projection for human-readable artifacts.

## Whitelist
- Core-6: id, type, title, created, updated, origin
- Optional: summary, tags, links

## Layout
- content/<type>/<id>/index.md
- assets/<id>/*

## Idempotency
- Projection re-runs safely; only writes if content changes.

## Triggers
- On `curation.review.done` and manual requests.
