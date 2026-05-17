# Open questions — Memory Candidate Review Queue

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
| README names surface and declares authority status | ✅ | "Memory Candidate Review Queue"; "Review surface · state mutates through governed pipeline" |
| `authority-boundaries.md` present and distinguishes design guidance / normalized spec / architecture contract / runtime truth | ✅ | All four layers distinguished; "Memory candidacy" invariant explicitly stated |
| `implementation-contracts.md` present with state enum, allowed transitions, data attributes | ✅ | State enum and transitions delegated to `prototype.html §03+§05`; data attributes to `§07`; eight-action vocabulary declared |
| `open-questions.md` present; questions triaged | ✅ | Triage applied in this review |
| No crossing-B-blocking open questions remain unresolved | ✅ | See triage table below — no blockers |
| State gallery covers every declared state | ✅ | `state-gallery.md` + `prototype.html §05` together cover all 10 declared states |
| Package does not assert current runtime behavior without citing a shipped owner-doc | ✅ | `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` is shipped and cited as the authority for the memory class set and authority flags |

**Owner-doc status note:** `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` exists and is shipped. Implementation issue #900 is blocked on an upstream dependency; this does not gate design-package promotion.

### Open-question triage

| # | Title | Triage | Rationale |
|---|---|---|---|
| 1 | Notification surface (badge threshold) | `defer-to-implementation-issue` | UI preference / opt-in; does not affect 10-state state machine |
| 2 | Confidence presentation (numeric vs banded) | `resolve-in-normalized-spec` | The package takes a principled position (numeric, to avoid inferring authority from a band); normalized spec should cite `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and record this rationale |
| 3 | Conflict resolution ("keep both" as permitted state) | `resolve-in-normalized-spec` | Whether "keep both" is a valid memory state is a schema question for the owner-doc; impacts state coverage if answered negatively |
| 4 | Pacing (throttle on high rejection rate) | `defer-to-implementation-issue` | Runtime policy, not UI; no state machine impact |
| 5 | Promotion preview shape | `defer-to-implementation-issue` | Implementation detail for the normalize-to-note flow; does not affect the 10-state machine |
| 6 | Auto-archive interval default | `defer-to-implementation-issue` | Runtime policy owned by `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; design assumes a default; implementation issue resolves the number |
| 7 | Cross-link to context bundles | `defer-to-implementation-issue` | Enhancement; does not affect state machine or authority model |

### Verdict

**PROMOTE**

All checklist items pass. No open question changes the 10-state state machine. Question 3 could in theory reduce state coverage if "keep both" were disallowed, but the design package captures this contingency correctly — the normalized spec absorbs the decision. Note: implementation issue #900 is blocked on an upstream dependency; this does not gate design-package promotion.
