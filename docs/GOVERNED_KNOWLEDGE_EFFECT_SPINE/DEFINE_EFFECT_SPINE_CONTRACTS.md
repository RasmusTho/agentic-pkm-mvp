State: Target-state task contract. Defines logical responsibility and verification commitments; it does not claim runtime enforcement or prescribe module layout.
Doc role: Task specification / Product SBS contract boundary
Authority: Bounded effect-spine inventory subordinate to `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, the functional ontology, and the GOV/EXE/OEF boundary charters.
Owner: GOV with CES stewardship; state owners retain their mutation mechanics.
Temporal class: strategic
Review cadence: event-driven

# Define Governed Knowledge Effect Contracts

## What This Task Does

This task defines the common logical contract for authority-bearing knowledge and execution effects
before runtime migration. The chain, recovery states, and owner separation are normative in
`docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Invariants`; this file inventories every producer
family that must adopt that contract and pins the production-call-site verification commitments.

The inventory is by **producer responsibility**, not by package. One runtime path may implement more
than one row, and future code may move without changing the ownership contract.

| Producer family | Current production examples / seam | What it may produce | Required governed handoff | Prohibited responsibility |
| --- | --- | --- | --- | --- |
| Human/API interaction | `app/api/routes/capture.py`, panel confirmation and canvas/note mutation routes | Human-attributed capture, approval/rejection, or requested durable change | Evidence/intent plus actor, resource, action, and write class to GOV; state-owner mutation only after token validation | Must not treat HTTP success, a checkbox, `may_write`, or WriteGuard health alone as authorization or a receipt |
| CAO proposals and orchestrator plans | `app/orchestrator/executor.py::_run_vault_append`, planner/agent proposal paths | Proposal, plan step, or requested real-tool/vault effect | `ExecutionRequest` to EXE with a valid GOV DecisionToken before the real tool call | CAO/orchestrator must not mint its own authorization, call a side-effect adapter first, or treat an `ExecutionResult` as an AuthorityReceipt |
| EXE effect producers | `app/execution/execution_request.py` and real-tool adapters | Authorized external/tool effect and normalized execution result | Validate the bound token, execute once, return its factual effect receipt (state owners own their own mutation receipts), then let GOV record accountability | EXE must not decide policy, infer permission, mint tokens, own a state owner's mutation receipt, or write HKA/MEM state directly |
| HKA and other state owners | capture append, accepted-note materialization, commitment/episode/settings mutation seams | State-owner mutation plus source mutation receipt | Validate the token at the production write seam; return a stable operation/effect identity and result for AuthorityReceipt recording | Must not self-authorize, outsource mutation mechanics to GOV, or acknowledge before receipt durability |
| MEM promotion | memory review/materialization path | Promotion request; after approval, a separate HKA artifact | MEM proposes, GOV decides, HKA materializes and receipts | Must not flip a MemoryItem to canonical or use persistence as promotion |
| Evaluation capture and adjudication | `app/eval/failure_capture.py` dead-letter/UNKNOWN drafting and `promote_draft` / `reject_draft` | Non-authoritative eval candidate; explicit human disposition is an authority-bearing status transition | Candidate intake stays explicitly non-authoritative and preserves provenance; promote/reject requests enter the full governed chain with the human actor and a post-mutation AuthorityReceipt | OEF/eval code must not make its own draft golden, treat WriteGuard alone as authorization for disposition, or use a trace as a receipt |
| Heimdal and external evidence intake | Heimdal observation/candidate projectors and client capture adapters | Durable candidate/evidence input, never accepted knowledge by arrival alone | Persist candidate/recovery state before cursor advance; any later HKA effect enters GOV as a new requested transition | Must not let ingestion, projection, cursor movement, or external origin confer authority |
| SIP correction producers | source/provenance correction and identity reconciliation paths | Correction lineage and affected-source identity | Preserve the original receipt; notify DRI/state owners of repair scope using stable source/effect identities | SIP must not rewrite historical accountability or perform derived repair itself |
| DRI projection producers | indexing, embedding, graph/context projections | Rebuildable derived state | Consume only receipted/current durable sources; suppress or rebuild idempotently after source correction | Must not carry irreplaceable meaning, upgrade evidence standing, or become the only copy of an effect |
| OEF observations and evaluators | health, trace, invariant, and eval surfaces | Evidence, finding, trace, or repair-needed signal | Route authority-bearing follow-up as a proposal to GOV/state owner | Must not authorize, mutate, self-close recovery, or substitute observability for PolicyDecision/AuthorityReceipt |

### Effect-chain contract

All rows compose through one ordered chain:

`evidence/proposal -> PolicyDecision -> DecisionToken -> state-owner/EXE effect -> mutation/effect receipt -> AuthorityReceipt -> notification and derived repair`

- Candidate creation is not promotion.
- WriteGuard is a transitional health/admission input, not the whole PolicyDecision.
- A state-owner receipt proves what the mutation adapter did; an AuthorityReceipt proves the
  governed transition. Neither substitutes for the other.
- An outbox event or trace describes/propagates an outcome; it never grants authority.
- A source correction adds lineage and repairs current derived state; it never erases the historical
  decision/effect receipt.

### Recovery contract

Producers and consumers preserve the named partial-failure states in the governed-write contract.
The two ambiguous outcomes are fail-loud:

1. `applied_receipt_pending`: the mutation may have landed, so the caller reconciles by stable
   operation/effect identity and never blind-retries.
2. `receipted_notification_pending`: mutation and accountability are durable, so recovery replays
   only notification or derived repair.

No producer may turn either state into `completed` from an OEF trace, an HTTP response, a cursor, or
a derived row alone.

## Verification Commitments

Runtime-enforcement slices must test the **production call sites**, not only dataclasses, guard
helpers, fake adapters, or schemas:

- API/state-owner paths: a blocked or mismatched token reaches the actual write seam and leaves no
  mutation; a successful mutation cannot acknowledge before its durable AuthorityReceipt.
- Orchestrator/EXE: `_run_vault_append` (or its successor production real-tool seam) receives a valid
  token before calling the tool; missing authorization cannot remain a transitional `None`.
- Eval capture: production dead-letter/UNKNOWN drafting stays non-authoritative, while explicit
  promote/reject paths exercise the governed chain; an OEF-produced candidate cannot self-promote.
- Partial failure: fault injection after mutation but before AuthorityReceipt persistence proves
  `applied_receipt_pending` and reconciliation without duplicate mutation.
- Notification failure: fault injection after AuthorityReceipt persistence proves notification-only
  replay.
- Source correction: the production correction-to-index path suppresses or rebuilds all affected
  derived state idempotently while preserving the original receipt.

The canonical named probes and eventual test paths live in
`docs/testing/invariant-tests.md :: Governed knowledge effect spine invariants`.

## Non-Goals

- No module/package/service layout is prescribed.
- No runtime enforcement, migration, schema, or persistence store is added by this task.
- No current transitional path is declared fully conformant merely because it uses WriteGuard,
  `GovernedWriteAdapter`, an outbox event, or a receipt-shaped object.
