State: SETTINGS-08 owner-document consolidation is delivered; the GitHub parent feature issue
[#3156](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3156) remains open and is the
authoritative validation/closure receipt. This file is the local pointer/receipt, not the live body.
Doc role: Specification companion (parent-issue pointer)
Authority: The GitHub issue body wins for live backlog state; `README.md` wins for the task decomposition.

# Parent Feature Issue — Settings Spine

- Parent (validation hub): **#3156** — `feature: Settings Spine — two scopes, one spine, watcher-fed ingestion (Option B)`
- Filed: 2026-07-07, from `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md` §5-§6 (owner-ruled Option B; audit PR #3153)

## Child issues (execution order)

| Task | Issue | Initial state |
|---|---|---|
| SETTINGS-01 WIRE_SETTINGS_INGESTION | [#3159](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3159) | delivered / closed |
| SETTINGS-02 SINGLE_DEFAULT_REGISTRY | [#3160](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3160) | delivered / closed |
| SETTINGS-03 CANONICALIZE_SETTINGS_LOCATION | [#3161](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3161) | delivered / closed |
| SETTINGS-04 RECEIPT_EVERY_SETTINGS_WRITE | [#3162](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3162) | delivered / closed |
| SETTINGS-05 REBIND_ON_VAULT_SELECTION | [#3163](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3163) | delivered / closed; aggregate receipt recorded |
| SETTINGS-06 PROMPTS_AS_SETTINGS | [#3164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3164) | delivered / closed |
| SETTINGS-07 validation hub | [#3165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3165) | delivered / closed; 07A→07B→07C receipts verified |
| SETTINGS-07A LLM_AND_RETRIEVAL_SETTINGS | [#4948](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4948) | delivered / closed; replaces historical #4796 |
| SETTINGS-07B TTS_SETTINGS | [#4797](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4797) | delivered / closed |
| SETTINGS-07C WATCHER_AND_TUNING_SETTINGS | [#4798](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4798) | delivered / closed |
| SETTINGS-08 CONSOLIDATE_SETTINGS_OWNER_DOCS | [#3166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3166) | delivered owner-doc consolidation; parent closure remains with #3156 |

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
