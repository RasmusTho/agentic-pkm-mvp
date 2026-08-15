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

| Capability task | Existing Issue | Live role on 2026-08-15 | Dependency |
| --- | --- | --- | --- |
| External prerequisite — BCP-05 verification execution authority | [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603) | `agent:needs-human`; canonical BCP-05 API-backed installed-main Demerzel verifier/pilot | BuilderOps control-plane BCP-02 and BCP-04 acceptance |
| AVC-01 — post-merge closure and orphan recovery | [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604) | `agent:blocked`; exclusive closure dispatch/reconciliation owner | BCP-05 / #3603 |

## Validation handoff

After BCP-05 and AVC-01 each receive their existing PR/Issue closure receipts, record the pilot's
single-chain and replay-no-op evidence on #3224. Close neither #3224 nor an implementation Issue
from this document: closure authority remains with `verification-and-closure` and live GitHub
readback.
