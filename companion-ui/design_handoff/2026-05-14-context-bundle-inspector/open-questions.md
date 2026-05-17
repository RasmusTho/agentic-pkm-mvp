# Open questions — Context Bundle Inspector

The canonical list lives in **`prototype.html` §09 (Open questions)** of this package. This
document is the structured version intended for issue creation at crossings C/D.

## Status

All open questions are tracked in the prototype. Owner-doc owners are proposed in the
prototype; they are not assigned yet — assignment happens at crossing B during the
maturity-checklist review.

## Crossing-B blockers

If any open question would, if answered, change the state machine declared in the
implementation contract, that question is a crossing-B blocker per the governance pack §03.
The reviewer at crossing B must triage each open question into one of:

- **resolve before promotion** (blocker),
- **resolve in normalized spec** (non-blocker, but cite),
- **defer to implementation issue** (non-blocker, but acknowledge).

## How to read

Each open question in the prototype carries:

- a short title (used as the issue title if escalated),
- the rationale for the question,
- a proposed default (the package's recommendation),
- an implicit owner (the doc the question would amend if accepted).

Detailed answers are deliberately not pre-decided here — the question list is the package's
honest "we don't know yet, and we made a choice anyway" record.

## Crossing B review — 2026-05-17

**Reviewer:** Codex agent (issue #956)
**Date:** 2026-05-17

### Maturity checklist

| Item | Pass? | Notes |
|---|---|---|
| README names surface and declares authority status | ✅ | "Context Bundle Inspector"; "Visual guidance only — bundle schema not owned here" |
| `authority-boundaries.md` present and distinguishes design guidance / normalized spec / architecture contract / runtime truth | ✅ | All four layers distinguished; explicitly states it does not own the bundle schema |
| `implementation-contracts.md` present with state enum, allowed transitions, data attributes | ✅ | State enum and transitions delegated to `prototype.html §03+§05`; data attributes to `§07` |
| `open-questions.md` present; questions triaged | ✅ | Triage applied in this review |
| No crossing-B-blocking open questions remain unresolved | ✅ | See triage table below — no blockers |
| State gallery covers every declared state | ✅ | `state-gallery.md` + `prototype.html §05` together cover all 9 declared states |
| Package does not assert current runtime behavior without citing a shipped owner-doc | ✅ | `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and `docs/INTERACTION_SURFACES_AND_AUTHORITY/` are shipped; all bundle schema references are explicitly flagged as owner-doc authority |

**Owner-doc status note:** `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and `docs/INTERACTION_SURFACES_AND_AUTHORITY/` both exist and are shipped. Implementation dependency #894 is blocked, but that is an implementation concern; the design package is mature for normalized-spec authoring regardless.

### Open-question triage

| # | Title | Triage | Rationale |
|---|---|---|---|
| 1 | Default exclusion visibility threshold | `resolve-in-normalized-spec` | The normalized spec must make the "affects interpretation" threshold normative; current heuristic is sufficient for design review but not for implementation |
| 2 | Bundle-receipt shape | `resolve-in-normalized-spec` | Receipt taxonomy is a schema concern for `CONTEXT_BUNDLE_CONTRACT.md`; normalized spec should cite or propose a receipt taxonomy |
| 3 | "Why now" field location in bundle schema | `resolve-in-normalized-spec` | Field placement is a schema question for the owner-doc; does not change the 9-state state machine |
| 4 | Cross-bundle navigation | `defer-to-implementation-issue` | One-click link between bundles is a UI enhancement; does not affect state machine or authority model |
| 5 | Conditional `may_propose` semantics | `resolve-in-normalized-spec` | Whether "conditional" is a valid flag value for any authority flag touches the authority model; normalized spec should cite `CONTEXT_BUNDLE_CONTRACT.md` |
| 6 | Memory-class `may_write` constraint | `resolve-in-normalized-spec` | Architectural rule ("candidate memory is not semantic authority" — `authority-boundaries.md`); normalized spec should make this constraint explicit |

### Verdict

**PROMOTE**

All checklist items pass. No open question changes the 9-state state machine. Questions 1, 2, 3, 5, 6 are schema/authority normalization work that belongs in the normalized spec, not in this design review. Note: implementation issue #894 is blocked on an upstream dependency; this does not gate design-package promotion.
