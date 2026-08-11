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
| SETTINGS-05 REBIND_ON_VAULT_SELECTION | [#3163](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3163) | blocked validation hub, not pickup; waits on #3161/#3162 plus MVR-01B #3854 and MVR-01C #3855; after this docs repair, extract three serial implementation children (05A dormant record → 05B dormant reconciler → 05C activation/aggregate proof) from `REBIND_ON_VAULT_SELECTION.md :: Bounded implementation issue decomposition` |
| SETTINGS-06 PROMPTS_AS_SETTINGS | [#3164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3164) | `agent:blocked` on #3161 |
| SETTINGS-07 validation hub | [#3165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3165) | `agent:blocked`; child ledger and stage receipt only |
| SETTINGS-07A LLM_AND_RETRIEVAL_SETTINGS | [#4796](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4796) | `agent:ready` after #3160 + #3161 |
| SETTINGS-07B TTS_SETTINGS | [#4797](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4797) | `agent:blocked` on #4796 merge + origin/main reconciliation |
| SETTINGS-07C WATCHER_AND_TUNING_SETTINGS | [#4798](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4798) | `agent:blocked` on #4797 merge + origin/main reconciliation |
| SETTINGS-08 CONSOLIDATE_SETTINGS_OWNER_DOCS | [#3166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3166) | `agent:blocked` on ALL other children (#3159-#3165) — its parent-closure handoff verifies the full capability checklist, so it is last, not merely after #3161 |

## Lifecycle rules

- Each merged child posts a validation receipt on #3156 before a dependent child is picked up.
- SETTINGS-05's implementation children also post slice receipts on #3163. Only 05C may close the
  SETTINGS-05 validation hub after all three mapped proof sets resolve; #3163 itself is never picked up.
- SETTINGS-07 children run 07A → 07B → 07C. Each posts a delivery receipt to #3165 and #3156; only
  07C can hand the stage to SETTINGS-08.
- When a blocking dependency merges, flip the dependent child to `agent:ready` (with a readiness
  receipt) — labels are mutated explicitly, never assumed.
- #3156 closes only via SETTINGS-08's parent-closure handoff (capability checklist verified,
  final receipt posted, this file and `README.md` reconciled to closed state).
