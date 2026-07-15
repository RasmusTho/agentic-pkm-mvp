State: Delivered capability execution source for the provisional/low-trust direct-write memory boundary. Issues #3718–#3721 implement the record, governed producer, bounded consumer, and deterministic security/eval gate; epic #2314 remains the broader validation hub.
Doc role: Capability specification and execution index
Authority: Breaks down ADR-0025 and the Agent Memory / MemoryItem contracts into bounded implementation tasks. Semantic authority remains in those owner contracts.

# Provisional Memory

## Capability Boundary

This capability delivers the narrow direct-write tier authorized by ADR-0025:

- a provisional memory record and receipt-bearing lifecycle;
- a human-readable, provenance-bound Markdown note as the primary provisional artifact;
- a governed API that can create that artifact without promoting it;
- read and cited-proposal admission only; and
- deterministic proof that provisional memory can never authorize APPLY, tool use, promotion, or a durable authority transition.

The capability extends the shipped `docs/AGENT_MEMORY/` and
`docs/DURABLE_MEMORY_AND_RECALL/` runtimes. It does not replace their candidate, review,
promotion, materialization, or guarded-recall paths. Vault Markdown remains canonical for
meaning-bearing artifacts; receipts are authoritative only for lifecycle state, never claim truth.

## Product / Runtime Classification

- Primary subsystem: MEM — Machine Memory & Learning.
- Secondary subsystems: GOV (transition receipts and authority guard), HKA (human-readable
  provisional artifact), PDM (content-free receipt persistence), RCA (bounded read/cited-proposal
  admission), OEF (deterministic eval).
- Boundary risk: critical. A missed call site can turn unreviewed material into hidden authority.

## Non-Goals

- making provisional memory canonical, accepted, or action-authorizing;
- writing through the promoted semantic-memory materialization path;
- persisting activation state as authority;
- treating iCloud or another sync substrate as an execution bus;
- auto-promotion, auto-deprecation, auto-supersession, or auto-deletion;
- changing the embedding identity, retrieval ranking defaults, or production channel state.

## Implementation Tasks

1. [DEFINE_PROVISIONAL_MEMORY_RECORD.md](DEFINE_PROVISIONAL_MEMORY_RECORD.md)
2. [WRITE_PROVISIONAL_MEMORY_THROUGH_GOVERNED_API.md](WRITE_PROVISIONAL_MEMORY_THROUGH_GOVERNED_API.md)
3. [ADMIT_PROVISIONAL_MEMORY_AS_LOW_TRUST_CONTEXT.md](ADMIT_PROVISIONAL_MEMORY_AS_LOW_TRUST_CONTEXT.md)
4. [PROVE_PROVISIONAL_MEMORY_SECURITY_BOUNDARY.md](PROVE_PROVISIONAL_MEMORY_SECURITY_BOUNDARY.md)

## Execution Order

The order is flat and serial: record/lifecycle foundation → governed producer → bounded consumer →
security/eval closure. The last task validates the composed capability, not only its helper functions.

## Cross-Task Invariants / Interaction Safety

1. **No artifact without a lifecycle receipt.** If Markdown creation fails, the transition remains
   non-terminal and retryable; no success receipt may exist without the artifact. If receipt
   persistence fails after a staged write, the artifact must not become readable as admitted
   memory; the operation fails closed and reconciliation reports the orphan.
2. **No producer before the trust ceiling is executable.** The API must call the trust-tier guard
   on its production path. A typed record or unit-tested helper alone is insufficient.
3. **No reader bypass.** Every production consumer admits provisional memory only as read or
   explicitly cited proposal support, with provenance and review state visible. It never supplies
   an action-authorizing input or sets `may_write=true`.
4. **Promotion is a separate governed transition.** Creating or editing a provisional note never
   calls `materialize_promoted_memory`, never marks a review decision terminal, and never treats
   filesystem sync as a trigger.
5. **Lifecycle truth is not claim truth.** Receipts can prove that a candidate was created,
   revised, rejected, or promoted; they cannot prove that its content is correct.
6. **Partial order is fail-closed.** If producer delivery lands before reader delivery, provisional
   records remain reviewable but are not recalled. If the reader lands without a valid record or
   provenance receipt, it excludes the item and emits a content-free diagnostic.
7. **Markdown is the sole meaning-bearing record.** The typed provisional record is a read model
   reconstructed from the Markdown artifact plus content-free lifecycle receipts; it is not a
   second durable content store. A Markdown edit is reflected on the next read. A missing/deleted
   artifact is excluded and reconciled as missing without resurrecting content from a receipt or
   runtime cache. Receipt persistence may retain ids, hashes, transitions, actor/time, and artifact
   references, but never the claim payload needed to reconstruct the note.

## Capability-Level Acceptance Criteria

- [x] Direct writes create a provisional, noncanonical memory artifact with provenance and a
  receipt-bearing lifecycle; no silent promotion occurs.
  Verify: `tests/agent_memory/test_provisional_memory_api.py::test_direct_write_creates_provisional_artifact_and_receipt`
- [x] The production write and recall paths enforce the read/cited-proposal ceiling and can never
  authorize mutation.
  Verify: `tests/agent_memory/test_provisional_memory_call_sites.py::test_provisional_memory_cannot_reach_action_authority`
- [x] Failure between artifact and receipt persistence is recoverable and never produces an
  admitted orphan.
  Verify: `tests/agent_memory/test_provisional_memory_failures.py::test_partial_write_fails_closed_and_reconciles`
- [x] The bilingual deterministic eval and poisoning suite remain green for provisional-memory
  scenarios.
  Verify: `tests/eval/test_provisional_memory_boundary.py::test_bilingual_provisional_memory_boundary`

## Verification Path

Each task runs its named focused tests. Producer and consumer tasks also run the existing agent-memory,
context-admissibility, and write-guard suites. The final task runs `python -m app.eval.run`, the
provisional-memory security suite, and the full non-pg suite. Behavioral enforcement claims require
tests at real API/recall call sites.

## Validation / Acceptance Path

Epic #2314 remains the validation hub and is never an implementation pickup. After each child merge,
post the PR, merge SHA, focused/full validation, owner-doc impact, and remaining blocker there.
Promote current-state owner docs only after all four tasks are merged and the composed capability
passes the bilingual eval/security gate. Operator runtime observation may supplement but cannot
replace deterministic call-site proof.

## Evidence Surface

- This directory: stable implementation contract.
- Child GitHub Issues: executable task contracts.
- Child PRs: verification receipts.
- Epic #2314: cross-slice validation ledger and closure decision.
- Owner docs: promoted only after capability acceptance.

## Relationship to GitHub Issues

Parent validation hub: #2314. Strictly validated task Issues:

1. #3718 — PROVISIONAL-MEMORY-01 (delivered)
2. #3719 — PROVISIONAL-MEMORY-02 (delivered)
3. #3720 — PROVISIONAL-MEMORY-03 (delivered by PR #3743)
4. #3721 — PROVISIONAL-MEMORY-04 (delivered security/eval closure)

No task may claim #2314 itself. After each merge, the coordinator updates the validation ledger on
#2314 and recalculates which single dependent Issue can truthfully become ready.
