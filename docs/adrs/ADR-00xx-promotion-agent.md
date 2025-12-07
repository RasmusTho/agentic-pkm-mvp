State: Partially outdated relative to SoT v4.10; promotion is stubbed in Reality-MVP.
# ADR-00xx: Promotion Agent – Event-Driven Human-First Lifecycle

## Status
Accepted historically (SoT v4.4). In v4.10 Reality-MVP, promotion/projector is limited to audit/membership stubs; no automated filesystem/frontmatter moves.

## Context
Proposed event-driven promotion to act on human intents (frontmatter/checkbox) and emit `promote.done` or `promote.pending_move`.

## Reality in SoT v4.10
- Promotion/Projector exists as stubs (`app/agents/promotion`, `app/agents/projector`), emitting audit/membership but **no** file moves or frontmatter updates.
- Events exist in `app/events/types.py`, but there is no worker consuming `promote.intent.created` in the current pipeline.
- Human flows in `docs/HUMAN-FLOWS.md` treat promotion/panel actions as planned/experimental.

## Decision (historical intent)
- Event-driven, async promotion agent consuming promotion intents and producing `promote.done|pending_move|error`, with cooldown/idempotence and local file operations.

## Current implementation
- Queue/worker runs best-effort (`app/promotion/queue.py`), but is not wired into ingest/panel flows.
- No frontmatter or filesystem mutation in Reality-MVP; promotion is effectively “record intent and audit”.

## Guidance
- Treat this ADR as future-facing. For current behaviour see `docs/AGENTS.md`, `docs/PANEL_AGENT.md`, and `docs/PROJECTOR.md`. Any revival should add worker wiring, tests, and clear UX contracts before claiming production readiness.
