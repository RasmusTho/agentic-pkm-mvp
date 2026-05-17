# Open questions — Vault Action Layer

The canonical list lives in **`prototype.html` §10**. This file is the structured version
intended for issue creation at crossings C/D.

## Open questions (summary)

1. **Tier 1 vs Tier 3 distinction.** Both produce queued artifacts for human review. Owner-doc
   should decide whether the split is durable.
2. **Idempotency window.** 24h is a placeholder; per-action default or single fixed value.
3. **Collision rule taxonomy.** `suffix` is the first rule. Future rules (`merge`,
   `refuse`, `timestamp`) should be declared per registry entry, never inferred.
4. **Cross-vault actions.** First action is single-vault. Suggest multi-vault always Tier 3.
5. **Registry-write authority.** Are registry changes themselves governance-bearing? Suggest yes.
6. **Classifier-confidence-to-tier coupling.** None proposed; render for transparency,
   never gate on it.
7. **Receipt retention.** Suggest: forever, in vault, as a subordinate artifact.

## Crossing-B blocker triage

The reviewer at crossing B must classify each question as:

- **resolve before promotion** — likely #1, #4 (would change the tier matrix).
- **resolve in normalized spec** — likely #2, #3, #5, #7.
- **defer to implementation issue** — likely #6.

## Crossing B review — 2026-05-17

**Reviewer:** Codex agent (issue #956)
**Date:** 2026-05-17

### Maturity checklist

| Item | Pass? | Notes |
|---|---|---|
| README names surface and declares authority status | ✅ | "Vault Action Layer / Agent Tool Authority"; "Visual + structural guidance — proposes a tool-authority taxonomy" |
| `authority-boundaries.md` present and distinguishes design guidance / normalized spec / architecture contract / runtime truth | ✅ | All four layers distinguished; explicitly states that `VAULT_ACTION_LAYER_CONTRACT.md` is the target authority doc "(to be authored)" |
| `implementation-contracts.md` present with state enum, allowed transitions, data attributes | ✅ | 9-step pipeline in `§02`, 5-tier taxonomy in `§03`, data attributes inline in `implementation-contracts.md`, intent table in `§08` — most complete contract of the four packages |
| `open-questions.md` present; questions triaged | ✅ | Triage applied in this review; package also pre-populated a provisional triage suggestion |
| No crossing-B-blocking open questions remain unresolved | ✅ | See triage table below; Q1 and Q4 do not block (rationale below) |
| State gallery covers every declared state | ✅ | `state-gallery.md` explicitly lists all 8 states with outcome tags; `prototype.html §06` is the visual authority |
| Package does not assert current runtime behavior without citing a shipped owner-doc | ✅ | `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` is shipped and cited. `VAULT_ACTION_LAYER_CONTRACT.md` is explicitly qualified as "(to be authored)" — not treated as shipped. |

**Owner-doc status note:** `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` exists and is shipped. The primary owner-doc `docs/CONCEPTS/VAULT_ACTION_LAYER_CONTRACT.md` is proposed and not yet authored — the package explicitly acknowledges this in `authority-boundaries.md` and `implementation-contracts.md`. Authoring that doc is the normalized-spec output of this promotion; its absence is expected and does not gate Crossing B.

### Open-question triage

| # | Title | Triage | Rationale |
|---|---|---|---|
| 1 | Tier 1 vs Tier 3 distinction | `resolve-in-normalized-spec` | **Does not block Crossing B.** The package takes a clear, well-motivated position: Tier 1 = "agent proposes X", Tier 3 = "known governance-bearing action". The two-tier distinction is coherent and the 8-state gallery is consistent with it. If the owner-doc later collapses them, the normalized spec absorbs that decision without retroactively invalidating the design package. |
| 2 | Idempotency window | `resolve-in-normalized-spec` | Per-action vs fixed is a registry-policy question; does not change the 9-step pipeline or 8 states |
| 3 | Collision rule taxonomy | `resolve-in-normalized-spec` | Declarative-per-action is the design's recommendation; owner-doc declares the registry shape |
| 4 | Cross-vault actions | `resolve-in-normalized-spec` | **Does not block Crossing B.** The first action is single-vault; multi-vault is deferred. The design's recommendation (multi-vault → always Tier 3) is normative guidance for the normalized spec. No state machine change is required now; the 8-state gallery remains complete for single-vault scope. |
| 5 | Registry-write authority | `resolve-in-normalized-spec` | Whether registry changes are governance-bearing is a policy question for `VAULT_ACTION_LAYER_CONTRACT.md` |
| 6 | Classifier-confidence-to-tier coupling | `defer-to-implementation-issue` | Transparency-only rendering; does not gate or re-tier; no state machine impact |
| 7 | Receipt retention | `resolve-in-normalized-spec` | Design recommends "forever, in vault"; owner-doc decides; does not affect 9-step pipeline |

### Verdict

**PROMOTE**

All checklist items pass. The package's provisional triage suggestion flagged Q1 and Q4 as likely blockers, but on review both can move to normalized spec: Q1 because the design takes a well-reasoned position that the normalized spec should confirm or refine, and Q4 because single-vault scope is complete and multi-vault guidance is captured as a normative recommendation. The primary owner-doc (`VAULT_ACTION_LAYER_CONTRACT.md`) does not exist yet — this is expected; authoring it is the direct output of Crossing B promotion. The 9-step pipeline and 5-tier taxonomy are internally consistent and ready for normalized-spec authoring.
