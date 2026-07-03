# Boundary: HIX — Human Interaction & Intent

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md) ·
[Human flows](../HUMAN-FLOWS.md) · [User needs model](../CONCEPTS/USER_NEEDS_MODEL.md)

**Canonical separation rule:** HIX owns **human interaction semantics and intent expression**. UI
shells can be replaced; the need for human-facing intent, review, correction, approval, and
explanation cannot (`SYSTEM_BREAKDOWN_STRUCTURE.md:452-454`).

## Purpose

Own the surfaces through which a human reads, writes, decides, reviews, corrects, navigates,
approves, rejects, and controls the system — so that human action is always explicit and
attributable, and so the system can distinguish what it knows, what it suggests, what it did, and
why (`docs/CONCEPTS/USER_NEEDS_MODEL.md` §9 "Being able to trust system action").

## Owns

- Human-facing interaction semantics and intent capture (`IntentEnvelope`).
- Review, approval, rejection, and correction UX.
- Human-readable explanation views: presentation of authority posture, provenance, memory posture,
  proposal state, and receipts (`SYSTEM_BREAKDOWN_STRUCTURE.md:424-425`).
- Navigation across workspaces and scopes.
- UI shells themselves as replaceable implementations — Obsidian, Companion UI, CLI, mobile, web,
  voice, and future clients (`docs/HUMAN-FLOWS.md` §0 "cognitive prosthesis, second brain, and agent
  memory"; dyslexia-friendly and dual-user-model surfaces per `docs/HUMAN-FLOWS.md` §"Dyslexia-friendly
  surfaces and the dual user model").
- Attribution of human action: every capture, correction, approval, or rejection HIX originates is
  traceable to the human who performed it, not merged into an anonymous system action.

## Does not own

- Durable knowledge → **HKA**; memory lifecycle → **MEM**.
- Policy / admissibility / authority transitions → **GOV**.
- Retrieval ranking → **RCA**; agent runtime / planning → **CAO**.
- Storage → **PDM**; sync → **SFC**; tool execution → **EXE**.
- External adapter mechanics (the editor/transport implementation itself, as opposed to the
  interaction semantics) → **EBF** (HIX and EBF jointly cover "Replace Obsidian":
  `SYSTEM_BREAKDOWN_STRUCTURE.md:1570` — HIX owns the interaction contract, EBF owns the editor
  adapter).

> **Ownership-drift rule.** HIX may originate human intent but must not become authority or
> persistence. It must route durable mutation through GOV and the owning subsystem
> (`SYSTEM_BREAKDOWN_STRUCTURE.md:429-431`). HIX directly writing HKA/MEM/PDM is a forbidden
> dependency — "UI becomes domain authority" (`SYSTEM_BREAKDOWN_STRUCTURE.md:1456`).

## Inputs

- Human text, confirmations, corrections, review decisions, navigation actions
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1516`).
- Presentation data from **HKA** (artifact state), **SIP** (provenance), **GOV** (authority
  posture, receipts), **WSP** (situated context), **RCA** (context/evidence), **MEM** (memory
  posture), **CAO** (proposals), **EXE** (execution status), **OEF** (views)
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1436`).

## Outputs

- `IntentEnvelope` — carries human intent, review decisions, approvals, rejections, and corrections
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1492`).
- Review/approval/rejection/correction requests routed to GOV; explanation-view requests to the
  presenting subsystem.

## Calls allowed

- **HKA, SIP, GOV, WSP, RCA, MEM, CAO, EXE (status), OEF (views)**
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1436`) — HIX reads presentation state and submits intent through
  these; it does not call EXE to execute directly (routes through GOV/CAO).

## Calls forbidden

- **Direct writes to HKA/MEM/PDM** — UI becomes domain authority
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1456`).
- **Direct tool/execution invocation** — human-initiated actions that mutate or execute route through
  GOV authorization and EXE, never straight from the interaction layer.
- **Treating HIX-local state as domain truth** — HIX owns interaction state only; domain state
  belongs to the owner subsystems (`SYSTEM_BREAKDOWN_STRUCTURE.md:1802-1806`).

## Required metadata

HIX **originates the human-attribution facts** that feed `source_role` (human-authored vs.
agent-authored) but does not itself set `authority_state` or `evidence_role` — those are
GOV/SIP decisions downstream of a governed transition. HIX must preserve and surface
`authority_state`, `evidence_role`, `sensitivity`, and `suppression_state` in its presentation layer
without altering them; corrections a human makes are captured as new `IntentEnvelope` content, not
as a silent metadata edit.

## Policy obligations

- Every durable mutation a human requests through HIX routes through GOV policy + approval +
  authority receipt before HKA is updated (`SYSTEM_BREAKDOWN_STRUCTURE.md` canonical flow #4,
  "Authority transition / durable mutation").
- Semantic conflicts surfaced to a human for review (sync flow) are HIX presentation only; GOV/HKA
  hold the resolution authority (`SYSTEM_BREAKDOWN_STRUCTURE.md:1392`).

## Provenance obligations

- Every `IntentEnvelope` carries enough attribution that a later reviewer can determine which human
  action produced it and when — human action is explicit and attributable is HIX's primary
  invariant (`docs/boundaries/README.md`).
- HIX must not obscure who decided what: presentation of receipts and authority posture must not
  flatten agent-proposed and human-approved actions into an indistinguishable state
  (`docs/CONCEPTS/USER_NEEDS_MODEL.md` §8 "Preserving authorship and control").

## Invariants owned

- Human action is explicit and attributable (`docs/boundaries/README.md`; matrix row HIX,
  `SYSTEM_BREAKDOWN_STRUCTURE.md:1334`).
- HIX directly writing HKA/MEM/PDM is forbidden — UI does not become domain authority
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1456`).
- HIX-local interaction state is not domain truth (`SYSTEM_BREAKDOWN_STRUCTURE.md:1806`).

## Failure modes

- **UI-as-authority:** a human-facing surface writing durable state directly, bypassing GOV.
- **Attribution loss:** an action presented to the human (or recorded) without a clear human-vs-agent
  origin, undermining trust in system action (`docs/CONCEPTS/USER_NEEDS_MODEL.md` §9).
- **Silent metadata drift:** HIX altering `authority_state`/`evidence_role` in its presentation layer
  instead of surfacing them as owned by GOV/SIP.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `human_action_explicit_and_attributable`
- `hix_does_not_write_domain_state`
- `hix_state_not_domain_truth`

## Related ADRs

- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `IntentEnvelope` — highest-priority stable contract (SBS Part 5); review/approval/rejection/correction request shapes (future, [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)–[#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548)).

## Related issues

- Charter: [#2836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2836) (SBI-7) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
