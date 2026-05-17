# Open questions — Runtime Proof / Health Dashboard

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
| README names surface and declares authority status | ✅ | "Runtime Proof / Health Dashboard"; "Visual guidance only — mirror of runtime state" |
| `authority-boundaries.md` present and distinguishes design guidance / normalized spec / architecture contract / runtime truth | ✅ | All four layers distinguished; invariants listed |
| `implementation-contracts.md` present with state enum, allowed transitions, data attributes | ✅ | State enum and transitions delegated to `prototype.html §03+§05`; data attributes to `§07` |
| `open-questions.md` present; questions triaged | ✅ | Triage applied in this review |
| No crossing-B-blocking open questions remain unresolved | ✅ | See triage table below — no blockers |
| State gallery covers every declared state | ✅ | `state-gallery.md` + `prototype.html §05` together cover all 9 declared states |
| Package does not assert current runtime behavior without citing a shipped owner-doc | ✅ | `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` is shipped. "runtime-proof receipt contract (when normalized)" is explicitly qualified as not yet authored — package does not treat it as shipped. |

**Owner-doc status note:** `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` exists and is shipped. The "runtime-proof receipt contract" is proposed and not yet authored; the package correctly qualifies it with "(when normalized)" and does not assert it as current authority.

### Open-question triage

| # | Title | Triage | Rationale |
|---|---|---|---|
| 1 | Polling vs push | `defer-to-implementation-issue` | Field-name cosmetic change only (`polled_at` → `received_at`); does not alter state machine |
| 2 | Single vault scope | `defer-to-implementation-issue` | Multi-vault is out of product scope; design assumption is valid as stated |
| 3 | Proof-run confirmation | `defer-to-implementation-issue` | UI micro-interaction; design proposes a default; implementation issue decides |
| 4 | Agent card scope | `defer-to-implementation-issue` | Display policy; does not affect declared states or transitions |
| 5 | "blocked" naming distinction | `resolve-in-normalized-spec` | Two distinct blocked sub-states (policy vs failure) need normative copy in the normalized spec to ensure consistent labelling across surfaces |
| 6 | Proof history bar span | `defer-to-implementation-issue` | Configuration default; design proposes 14 d; implementation issue decides |

### Verdict

**PROMOTE**

All checklist items pass. No open question changes the state machine or blocks the design package's promotion to normalized-spec authoring. Implementation stabilization dependencies (watcher OOM repair, poison-message handling, etc.) are downstream implementation concerns and do not gate this design review.
