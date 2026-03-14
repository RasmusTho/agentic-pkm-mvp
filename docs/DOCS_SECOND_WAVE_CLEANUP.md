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
| `docs/V56_FORWARD_LINE.md` | Plan | merge into | `docs/ROADMAP.md` once v5.6 planning stabilizes; currently still useful as a short-lived plan doc |
| `docs/CI.md` | Reference | merge into | `docs/TESTING.md` or a surviving quality doc; overlaps strongly with testing/quality gates |
| `docs/ISSUES_TESTING.md` | Reference / backlog | merge into | `docs/TESTING.md` as “known gaps” or move into issue tracker; not a strong standalone doc |
| `docs/QUALITY.md` | Reference | merge into | `docs/TESTING.md` or `docs/eval.md`; quality gates overlap heavily with CI/testing |
| `docs/eval.md` | Reference | keep | Distinct eval surface if kept narrow |
| `docs/guardrails.md` | Reference | keep | Distinct runtime safety policy surface |
| `docs/OBSERVABILITY.md` | Reference | keep | Runtime observability contract |
| `docs/OBSERVABILITY_STACK.md` | Reference | merge into | `docs/INFRASTRUCTURE.md` or `docs/OPERATIONS.md`; local stack/how-to only |
| `docs/HEALTH.md` | Reference | keep | Distinct health contract/CLI surface |
| `docs/OPS_WATCHER.md` | Reference | merge into | `docs/OPERATIONS.md`; watcher-specific operational guidance likely better as a section unless it keeps growing |
| `docs/INFRASTRUCTURE.md` | Reference | keep | Distinct local runtime / compose / topology doc |
| `docs/CLI.md` | Reference | merge into | `docs/OPERATIONS.md` or `docs/DEV_WORKFLOW.md`; partial CLI reference is weak as standalone unless expanded |
| `docs/LLM.md` | Reference | keep | Operational LLM owner |
| `docs/LLM_ROUTING.md` | Reference / contract | keep | Distinct routing contract |
| `docs/RETRIEVAL.md` | Reference | keep | Distinct retrieval behavior surface |
| `docs/DATA_MODEL.md` | Reference | keep | Distinct data model doc |
| `docs/DATA_GOVERNANCE.md` | Reference | merge into | `docs/DATA_MODEL.md` or `docs/CORE_CONTRACT.md`; strong overlap in canonical-vs-derived semantics |
| `docs/DB_SCHEMA.md` | Reference | keep | Distinct DB snapshot/reference |
| `docs/FRONTMATTER.md` | Reference | keep | Distinct vault/frontmatter contract |
| `docs/SETTINGS.md` | Reference | keep | Main settings owner |
| `docs/SETTINGS_TIERING.md` | Reference | merge into | `docs/SETTINGS.md`; likely better as a major section than standalone doc |
| `docs/AUTH_RATE_LIMITING.md` | Reference | merge into | `docs/SECURITY.md` unless it is expected to grow materially |
| `docs/SECURITY.md` | Reference | keep | Distinct security posture doc |
| `docs/PRIVACY.md` | Reference | keep | Distinct privacy posture doc |
| `docs/DEPENDENCIES.md` | Reference | keep | Distinct external dependency inventory |
| `docs/PYTHON_VERSION_POLICY.md` | Reference | merge into | `docs/DEPENDENCIES.md` or `docs/CONTRIBUTING.md`; too narrow for long-term standalone status |
| `docs/OBSIDIANSYNC.md` | Reference | merge into | `docs/OPERATIONS.md` or `docs/HUMAN-FLOWS.md`; likely too narrow and partly historical |
| `docs/INVENTORY.md` | Reference | keep | Runtime inventory still useful as a separate lookup surface |
| `docs/GLOSSARY.md` | Reference | keep | Distinct terminology surface |
| `docs/DEV_WORKFLOW.md` | Reference | keep | Primary development workflow doc |
| `docs/CONTRIBUTING.md` | Reference | merge into | `docs/DEV_WORKFLOW.md`; currently a lightweight subset/entrypoint |
| `docs/templates/DOC_TEMPLATE.md` | Reference / template | keep | Needed for governance |
| `docs/UAT_PANEL_WATCHER.md` | Reference / runbook | merge into | `docs/runbooks/` or `docs/OPERATIONS.md`; better as runbook material than top-level doc |
| `docs/RUNBOOK_RESET_TO_ZERO.md` | Runbook | move into | `docs/runbooks/` for consistency with other runbooks |
| `docs/E2E_ALPHA.md` | Reference / runbook | move into | `docs/runbooks/` or keep if treated as a test contract; needs explicit ownership decision |
| `docs/SCORECARDS.md` | Plan | merge into | `docs/eval.md` or `docs/QUALITY.md` successor; not strong enough alone while unimplemented |
| `docs/PROTOCOL_SATELLITE_SYNC.md` | Plan | keep | Distinct protocol/planning doc |
| `docs/DOCS_REFACTOR_PLAN.md` | Plan | keep | Active refactor work tracker until cleanup ends, then archive |
| `docs/HISTORICAL_EXTRACTION_REVIEW.md` | Working review | archive | Useful only during refactor execution |
| `docs/AI_DEVELOPMENT.md` | Deprecated | delete | Remove once links are fully gone; content already moved to `DEV_WORKFLOW` |
| `docs/LLM_BACKENDS.md` | Deprecated | delete | Remove once links are fully gone; content already moved to `LLM.md` |
| `docs/CORE6_CONTRACT.md` | Deprecated alias | delete | Remove once compatibility links are gone; canonical doc already exists |
| `docs/PLANNER.md` | Legacy | archive | Historical only |
| `docs/PROJECTOR.md` | Legacy | archive | Historical only |
| `docs/ALIGNMENT.md` | Legacy | archive | Historical only |
| `docs/CHANGELOG.md` | Legacy | archive | Historical only |
| `docs/ingest.md` | Legacy | archive | Historical only |
| `docs/OVERVIEW_WS.md` | Legacy | archive | Historical only |
| `docs/MEMORY.md` | Legacy | archive | Historical only |

## Recommended Next Slice

The highest-value next cleanup slice is:

### Ops / observability consolidation

Target docs:
- `docs/OPERATIONS.md`
- `docs/OPS_WATCHER.md`
- `docs/OBSERVABILITY.md`
- `docs/OBSERVABILITY_STACK.md`
- `docs/HEALTH.md`
- `docs/INFRASTRUCTURE.md`
- `docs/CLI.md`

Goal:
- Keep `OPERATIONS.md` as the operator entrypoint
- Keep `OBSERVABILITY.md` and `HEALTH.md` as distinct contracts
- Merge `OPS_WATCHER.md` and `OBSERVABILITY_STACK.md` into surviving docs unless a strong standalone need remains
- Decide whether `CLI.md` survives or is folded into operations/dev workflow

### Quality / testing consolidation

Target docs:
- `docs/TESTING.md`
- `docs/CI.md`
- `docs/QUALITY.md`
- `docs/eval.md`
- `docs/ISSUES_TESTING.md`
- `docs/SCORECARDS.md`

Goal:
- Make `TESTING.md` the clear owner
- Keep `eval.md` only if it stays distinct
- Fold gate/backlog/spec fragments into the surviving owners

## Exit Criteria For Second Wave

- Fewer top-level docs in `docs/`
- Fewer deprecated stubs
- Fewer single-purpose operational docs in root
- Fewer low-signal legacy files still sitting in the active surface
- Each remaining top-level doc has a clear owner and non-overlapping responsibility
