State: Working cleanup matrix for docs refactor branch `codex/docs-refactor-structure`.
# Docs Second-Wave Cleanup Matrix

This matrix captures the next cleanup wave after:
- authority and entrypoint cleanup,
- historical root-file archival,
- documentation template and spec-writing guidance.

The goal of this wave is to reduce the remaining active document surface by merging overlapping reference docs and retiring deprecated or low-value files.

Decision labels:
- `keep` — keep as a distinct document
- `merge into` — fold useful content into a surviving document, then deprecate or archive
- `archive` — move out of the active surface; keep only for historical/reference value
- `delete` — remove once links and surviving content are handled

## Priority Summary

Recommended next execution order:
1. Ops / observability cluster
2. Quality / testing cluster
3. Settings / policy cluster
4. Deprecated aliases and stale compatibility docs
5. Legacy root docs that still remain in active root

## Matrix

| Path | Current role | Decision | Target / reason |
| --- | --- | --- | --- |
| `docs/STATUS.md` | Core SoT | keep | Active operational snapshot |
| `docs/ARCHITECTURE.md` | Core SoT | keep | Primary runtime architecture source |
| `docs/HUMAN-FLOWS.md` | Core SoT | keep | User-facing behavior contract |
| `docs/COMPONENTS.md` | Core SoT | keep | Component ownership and wiring catalog |
| `docs/EVENTS.md` | Core SoT | keep | Event contract |
| `docs/TESTING.md` | Core SoT | keep | Testing strategy owner |
| `docs/OPERATIONS.md` | Core SoT | keep | Top-level operational entrypoint |
| `docs/DOCS_INDEX.md` | Core SoT | keep | Document role map |
| `docs/PROJECT_KERNEL.md` | Core / concept anchor | keep | Stable project-intent contract |
| `docs/CORE_CONTRACT.md` | Core / domain contract | keep | Canonical Core-6 contract |
| `docs/NOTE_KIND_POLICIES.md` | Reference / domain contract | keep | Distinct policy surface |
| `docs/CONCURRENCY.md` | Reference / domain contract | keep | Distinct concurrency guardrail doc |
| `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md` | Reference / boundary contract | keep | Distinct boundary contract |
| `docs/EMBEDDINGS.md` | Reference / contract | keep | Normative embeddings spec |
| `docs/DIAGRAMS.md` | Reference | keep | Current visual companion |
| `docs/AGENTS.md` | Reference | keep | System-level agent architecture |
| `docs/PANEL_AGENT.md` | Reference | keep | PanelAgent-specific contract |
| `docs/ROADMAP.md` | Plan | keep | Strategic plan owner |
| `docs/plans/V56_FORWARD_LINE.md` | Plan | merge into | `docs/ROADMAP.md` once v5.6 planning stabilizes; currently still useful as a short-lived plan doc |
| `docs/CI.md` | Removed | completed | Content merged into `docs/TESTING.md`; redirect stub deleted on this branch |
| `docs/ISSUES_TESTING.md` | Removed | completed | Remaining active gap tracking merged into `docs/TESTING.md`; redirect stub deleted on this branch |
| `docs/QUALITY.md` | Removed | completed | Validation guidance merged into `docs/TESTING.md`; redirect stub deleted on this branch |
| `docs/eval.md` | Reference | keep | Distinct eval surface if kept narrow |
| `docs/guardrails.md` | Reference | keep | Distinct runtime safety policy surface |
| `docs/OBSERVABILITY.md` | Reference | keep | Runtime observability contract |
| `docs/OBSERVABILITY_STACK.md` | Removed | completed | Content merged into `docs/INFRASTRUCTURE.md`; redirect stub deleted on this branch |
| `docs/HEALTH.md` | Reference | keep | Distinct health contract/CLI surface |
| `docs/OPS_WATCHER.md` | Removed | completed | Content merged into `docs/OPERATIONS.md`; redirect stub deleted on this branch |
| `docs/INFRASTRUCTURE.md` | Reference | keep | Distinct local runtime / compose / topology doc |
| `docs/CLI.md` | Removed | completed | Stable operator CLI guidance merged into `docs/OPERATIONS.md`; redirect stub deleted on this branch |
| `docs/LLM.md` | Reference | keep | Operational LLM owner |
| `docs/LLM_ROUTING.md` | Reference / contract | keep | Distinct routing contract |
| `docs/RETRIEVAL.md` | Reference | keep | Distinct retrieval behavior surface |
| `docs/DATA_MODEL.md` | Reference | keep | Distinct data model doc |
| `docs/DATA_GOVERNANCE.md` | Removed | completed | Governance semantics merged into `docs/DATA_MODEL.md`; redirect stub deleted on this branch |
| `docs/DB_SCHEMA.md` | Reference | keep | Distinct DB snapshot/reference |
| `docs/FRONTMATTER.md` | Reference | keep | Distinct vault/frontmatter contract |
| `docs/SETTINGS.md` | Reference | keep | Main settings owner |
| `docs/SETTINGS_TIERING.md` | Removed | completed | Tiering guidance merged into `docs/SETTINGS.md`; redirect stub deleted on this branch |
| `docs/AUTH_RATE_LIMITING.md` | Removed | completed | Auth/rate-limiting posture merged into `docs/SECURITY.md`; redirect stub deleted on this branch |
| `docs/SECURITY.md` | Reference | keep | Distinct security posture doc |
| `docs/PRIVACY.md` | Reference | keep | Distinct privacy posture doc |
| `docs/DEPENDENCIES.md` | Reference | keep | Distinct external dependency inventory |
| `docs/PYTHON_VERSION_POLICY.md` | Removed | completed | Python floor/compatibility guidance merged into `docs/DEPENDENCIES.md`; redirect stub deleted on this branch |
| `docs/OBSIDIANSYNC.md` | Removed | completed | Active sync guidance merged into `docs/HUMAN-FLOWS.md`, `docs/OPERATIONS.md`, and `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`; redirect stub deleted on this branch |
| `docs/INVENTORY.md` | Reference | keep | Runtime inventory still useful as a separate lookup surface |
| `docs/GLOSSARY.md` | Reference | keep | Distinct terminology surface |
| `docs/DEV_WORKFLOW.md` | Reference | keep | Primary development workflow doc |
| `docs/CONTRIBUTING.md` | Removed | completed | Contributor setup and workflow merged into `docs/DEV_WORKFLOW.md`; redirect stub deleted on this branch |
| `docs/templates/DOC_TEMPLATE.md` | Reference / template | keep | Needed for governance |
| `docs/runbooks/UAT_PANEL_WATCHER.md` | Runbook | completed | Moved out of top-level `docs/` into `docs/runbooks/` |
| `docs/runbooks/RUNBOOK_RESET_TO_ZERO.md` | Runbook | completed | Moved out of top-level `docs/` into `docs/runbooks/` |
| `docs/runbooks/E2E_ALPHA.md` | Runbook | completed | Moved out of top-level `docs/` into `docs/runbooks/` |
| `docs/SCORECARDS.md` | Removed | completed | Scorecard-style aspirational targets merged into `docs/eval.md`; redirect stub deleted on this branch |
| `docs/plans/PROTOCOL_SATELLITE_SYNC.md` | Plan | keep | Distinct protocol/planning doc |
| `docs/work/DOCS_REFACTOR_PLAN.md` | Plan | keep | Active refactor work tracker until cleanup ends, then archive |
| `docs/work/HISTORICAL_EXTRACTION_REVIEW.md` | Working review | archive | Useful only during refactor execution |
| `docs/AI_DEVELOPMENT.md` | Removed | completed | Content already moved to `docs/DEV_WORKFLOW.md`; redirect stub deleted on this branch |
| `docs/LLM_BACKENDS.md` | Removed | completed | Content already moved to `docs/LLM.md`; redirect stub deleted on this branch |
| `docs/CORE6_CONTRACT.md` | Removed | completed | Canonical `docs/CORE_CONTRACT.md` already exists; compatibility alias deleted on this branch |
| `docs/legacy/PLANNER.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/PROJECTOR.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/ALIGNMENT.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/CHANGELOG.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/ingest.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/OVERVIEW_WS.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |
| `docs/legacy/MEMORY.md` | Legacy | completed | Moved out of top-level `docs/` into `docs/legacy/` |

## Recommended Next Slice

The highest-value next cleanup slice is:

### Ops / observability consolidation

Target docs:
- `docs/OPERATIONS.md`
- `docs/OBSERVABILITY.md`
- `docs/HEALTH.md`
- `docs/INFRASTRUCTURE.md`
Goal:
- Keep `OPERATIONS.md` as the operator entrypoint
- Keep `OBSERVABILITY.md` and `HEALTH.md` as distinct contracts
- `OPS_WATCHER.md` and `OBSERVABILITY_STACK.md` have been removed after their content was merged into surviving docs
- `CLI.md` has now been folded into operations guidance and removed

### Quality / testing consolidation

Target docs:
- `docs/TESTING.md`
- `docs/eval.md`

Goal:
- Make `TESTING.md` the clear owner
- Keep `eval.md` only if it stays distinct
- Fold gate/backlog/spec fragments into the surviving owners
- `CI.md`, `QUALITY.md`, `ISSUES_TESTING.md`, and `SCORECARDS.md` have now been removed after their content was merged into surviving docs

## Exit Criteria For Second Wave

- Fewer top-level docs in `docs/`
- Fewer deprecated stubs
- Fewer single-purpose operational docs in root
- Fewer low-signal legacy files still sitting in the active surface
- Each remaining top-level doc has a clear owner and non-overlapping responsibility
