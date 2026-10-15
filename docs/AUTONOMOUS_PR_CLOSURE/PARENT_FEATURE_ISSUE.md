State: Existing parent validation hub #3224 is open and `agent:blocked`; no duplicate parent Issue
was created.
Doc role: Parent validation-hub linkage
Authority: #3224 owns live autonomous review/repair/closure validation state. This document records
the narrower PR closure capability's relationship to that existing hub.

# Parent feature issue — autonomous PR verification and closure

## Existing parent and child ledger

The existing parent is [#3224](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3224),
`builder: add autonomous review and repair gates`. It remains a validation hub, never a pickup
Issue. It already names the prerequisite guardrails and requires autonomous closure to preserve
them.

| Capability task | Existing Issue | Role reconciled on 2026-10-15 | Dependency |
| --- | --- | --- | --- |
| BCP-05 topology reconciliation | [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603) | Closed; `REWRITE_FOR_VM` receipt, not executor qualification | Preserves VM102 target and explicit evidence gaps |
| AVC-01 — post-merge closure and orphan recovery | [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604) | Open; full producer/consumer/pilot acceptance remains | Producer can proceed independently; VM102 consumer and pilot require their qualification/authority evidence |
| Existing recovery authority | [#4897](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4897) | Post-effect recovery/v2 phase/watchdog owner | Reuse exact deployed authority; do not duplicate the mechanism |
| Native single-closer integration | [#4893](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4893) | Separate integration owner | No claim of completion from this specification |
| Complete VM102 admission | [#5181](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5181) / [#3793](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3793) | Qualification/operator gates / canonical-writer cutover | #5056 bounded component activation does not replace either gate |

A producer child may satisfy only the artifact-only subset of #3604. Its closure must leave the
consumer, active-chain, owner-doc terminal and live pilot criteria visibly incomplete on #3604.

## Validation handoff

After AVC-01 receives its complete consumer and pilot evidence, record the pilot's
single-chain and replay-no-op evidence on #3224. Close neither #3224 nor an implementation Issue
from this document: closure authority remains with `verification-and-closure` and live GitHub
readback.
