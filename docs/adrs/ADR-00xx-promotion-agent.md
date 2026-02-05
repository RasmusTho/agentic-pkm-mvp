State: ADR (historical).
# ADR-00xx: Promotion Agent – Event-Driven Human-First Lifecycle

## Status
Accepted — SoT v4.4 baseline

## Delta vs SoT v5.5 baseline (current)
- The DB outbox is the canonical queue; JSONL is audit/diagnostic only.
- Promotion is driven by `promote.intent.created` events consumed from the DB outbox and guarded by idempotency/dedup stores; file moves remain policy-gated and may be disabled by default.

## Context
The previous workflow exposed “processed” and “promoted” states to users, requiring manual actions or plugins to move notes through the lifecycle. This caused unnecessary cognitive load and UI noise in Obsidian, while promotion itself was a purely mechanical transition. The system already implements event-driven agents, a canonical DB outbox (plus JSONL audit logging), and a PER (Plan-Execute-Reflect) loop shared across many agents.

## Decision
Introduce a Promotion Agent that executes human intent to promote files, expressed as lightweight frontmatter or checkbox intents inside the vault. The agent runs as a worker in the existing PER-loop ecosystem, consuming `promote.intent.created` events and producing `promote.done` or `promote.pending_move` outcomes.

- Execution model: event-driven, asynchronous
- Inputs: JSONL events (`promote.intent.created`)
- Outputs: `promote.done`, `promote.pending_move`, `promote.error`
- Behavior: cooldown plus idle enforcement, idempotence by UUID
- Policy: file move configuration (`promotion.move_policy`) in `system-settings.yaml`
- UX principle: no explicit “processed/promoted” UI; the checkbox disappears after promotion
- File operations: local file-tools only — no Obsidian plugin dependency
- Observability: events traced with `trace_id`; logs stored under `_system/events/`

## Consequences
- Human-first UX: users interact through intent only; agents handle execution quietly.
- Simplified states: “processed” becomes implicit; “promoted” is internal.
- Consistency: reuses the same outbox/event model as other agents.
- Extensibility: future option to swap file-tools with an Obsidian-API backend without breaking contracts.
- Risk: minor delay (cooldown plus batch window) before files are physically moved.
- Mitigation: immediate index refresh upon frontmatter update ensures promotion appears instant to users.

## References
- `docs/ARCHITECTURE.md` — Agents and PER-loop section
- `docs/ROADMAP.md` — SoT v4.4.B Promotion Agent
- `schemas/system-settings.schema.json` — promotion block
- Events: `promote.intent.created`, `promote.done`, `promote.pending_move`, `promote.error`
