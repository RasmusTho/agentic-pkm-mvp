State: FILED — the GitHub parent feature issue exists and is the authoritative backlog/validation surface: [#3156](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3156) (Status=Backlog, `agent:blocked` — validation hub, not a pickup issue). This file is the local pointer/receipt, not the live body.
Doc role: Specification companion (parent-issue pointer)
Authority: The GitHub issue body wins for live backlog state; `README.md` wins for the task decomposition.

# Parent Feature Issue — Settings Spine

- Parent (validation hub): **#3156** — `feature: Settings Spine — two scopes, one spine, watcher-fed ingestion (Option B)`
- Filed: 2026-07-07, from `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md` §5-§6 (owner-ruled Option B; audit PR #3153)

## Child issues (execution order)

| Task | Issue | Initial state |
|---|---|---|
| SETTINGS-01 WIRE_SETTINGS_INGESTION | [#3159](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3159) | delivered / closed |
| SETTINGS-02 SINGLE_DEFAULT_REGISTRY | [#3160](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3160) | `agent:ready` (parallel with 01) |
| SETTINGS-03 CANONICALIZE_SETTINGS_LOCATION | [#3161](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3161) | `agent:ready` after #3159 |
| SETTINGS-04 RECEIPT_EVERY_SETTINGS_WRITE | [#3162](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3162) | `agent:ready` after #3159 |
| SETTINGS-05 REBIND_ON_VAULT_SELECTION | [#3163](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3163) | `agent:blocked` on #3161 and #3162; supersedes #2476/#3119's "do not converge" posture (both already closed — closes nothing) |
| SETTINGS-06 PROMPTS_AS_SETTINGS | [#3164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3164) | `agent:blocked` on #3161 |
| SETTINGS-07 DEHARDCODE_WAVE_ONE | [#3165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3165) | `agent:blocked` on #3160 + #3161 |
| SETTINGS-08 CONSOLIDATE_SETTINGS_OWNER_DOCS | [#3166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3166) | `agent:blocked` on ALL other children (#3159-#3165) — its parent-closure handoff verifies the full capability checklist, so it is last, not merely after #3161 |

## Lifecycle rules

- Each merged child posts a validation receipt on #3156 before a dependent child is picked up.
- When a blocking dependency merges, flip the dependent child to `agent:ready` (with a readiness
  receipt) — labels are mutated explicitly, never assumed.
- #3156 closes only via SETTINGS-08's parent-closure handoff (capability checklist verified,
  final receipt posted, this file and `README.md` reconciled to closed state).
