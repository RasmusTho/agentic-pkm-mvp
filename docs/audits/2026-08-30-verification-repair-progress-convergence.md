# Verification repair-progress mechanism convergence packet

State: Advisory mechanism-review evidence for Issue #4862 / PR #4927; not runtime authority.

Mechanism key: `review_code_correctness:verification-repair-progress-admission`

This packet records the mechanism-level review required after multiple P1 findings in the same
verification repair/convergence mechanism. `docs/AGENT_ISSUE_DISPATCHER.md`, the verification
dispatcher request/receipt schemas, and BuilderOps control-plane contracts remain authoritative.

## Protected invariants

- A previously blocked finding/domain/mechanism key cannot start another workspace-writing closer
  until the consumer has committed and re-read one server-derived `repair_progress_intent.v1` under
  the current run lease.
- The intent binds the exact prior repair attempt, blocking review, reviewed head H1, stable finding,
  failure domain, mechanism id, the blocking review's typed mechanism-path projection authenticated
  as a non-empty subset of the prior GitHub repair transition, the corresponding server-reported
  blob states, and authenticated check-run/workflow-run execution frontier.
- Direct and atomic-batch writes on both durable adapters require the canonical non-empty projection
  and cannot replace it while reusing one blocking-review session or by inserting clean/fresh review
  rows against the same repair anchor before another repair. Clean receipts reject both failure
  binding and mechanism paths at the shared adapter validation boundary, in parity with the consumer.
- Direct writes cannot inject producer-reserved atomic-batch identity/index/size fields. SQLite and
  BuilderOps require each planned row's deterministic batch attempt id before persistence, then
  accept replay only for a complete index set whose ids and size match the exact batch, preventing
  false or permanently unreplayable writes from suppressing a blocking review.
- A verification attempt becomes closure-eligible only when the receipt consumer has minted the
  validated-receipt capability through the private run/producer admission boundary; public
  schema/sanitizer validation returns an inert mapping. The ledger-local registry binds the exact
  object to run/repository/PR/pre-launch-head/session/holder/lease plus receipt digest, and rejects
  direct construction, subclassing, mutation, or copied seals before persisting its durable content
  digest. Reviews bind
  the actual latest eligible anchor and current head. Only successful verified/delivered verdicts
  receive this authority, closing synthetic and failed-verdict verification/review paths.
- A repeated repair is admissible only after GitHub reports a distinct repaired head H2, an
  untruncated linear H1...H2 comparison that changes a path selected by the independent blocking
  review for this specific mechanism, and a new
  authenticated check execution frontier. Merely substituting H2 for H1 in a digest, touching an
  unrelated path, or returning the same mechanism blob/check execution is non-progress. The ledger,
  not coordinator prose, builds and validates the durable `repair_progress_evidence.v1` receipt.
- H1 and H2 remain distinct across rebind, restart, replay, and takeover. Reused or unchanged
  mechanism/validation digests fail closed.
- Receipt/schema/sanitizer projection preserves only the canonical intent id. Review events cannot
  carry one, and a malformed id is rejected before event application.
- SQLite is compatibility-only; the production BuilderOps API ledger provides the same fenced
  direct-write, atomic-batch, restart, replay, rebind, and takeover semantics.

## States and transitions

- `unreviewed`: a repair exists without a fresh blocking review; no next intent is produced.
- `reviewed/H1`: a blocking review binds the latest repair and current exact head H1.
- `intent-admitted`: the consumer commits and re-reads the typed intent under the active task lease.
- `effect-claimed`: the BuilderOps model-effect outbox carries the admitted intent ids before the
  closer starts; the local compatibility path retains the task-lease fence.
- `repair-returned/H2`: fresh GitHub PR, compare, check-run, and workflow-run reads prove a distinct
  repaired head H2, a relevant mechanism transition, and the exact-H2 execution frontier before
  event application.
- `progress-committed`: the repair batch contains server-derived evidence binding H1, H2, the intent,
  and before/after validation digests.
- `reviewed/H2`: a fresh independent blocking or clean review determines the next transition.
- `blocked/backoff`: missing, stale, ambiguous, unchanged, reused, or unverifiable progress stops the
  next launch or event application without manufacturing a Human Exception.

## Writers, consumers, and crash order

1. `VerificationConsumer` reads live PR/check authority and plans intents from durable ledger rows.
2. `VerificationDispatchLedger` or `BuilderOpsVerificationLedger` validates, lease-fences, commits,
   and replays the exact intent idempotently.
3. The consumer re-reads the intent and, for BuilderOps, binds its ids into the model-effect outbox
   payload before launch.
4. The closer receives full admitted intents but may return only a canonical intent id on a repair
   event; schema validation and sanitization preserve that id without accepting free-form progress.
5. After launch, the consumer re-reads PR/check truth and the bounded GitHub H1...H2 comparison,
   verifies a linear transition that overlaps the blocking review's authenticated mechanism-path
   projection, rebinds the run from H1
   to H2 under the same lease, and supplies the path-blinded transition plus authenticated execution
   digest to the event consumer.
6. `VerificationAgentLoop` builds the progress receipt and each ledger independently rebuilds it
   before committing the atomic event batch. Exact replay is a no-op.

A crash before step 2 leaves no launch authority. A crash after step 2 reuses the same durable intent.
After the closer returns, its durable verification receipt, coordinator session, stored pre-launch
context, admitted intent ids, and BuilderOps model-effect reconciliation bind the post-launch
continuation. Recovery may therefore re-read H2/compare/check truth and replay the deterministic
event batch without launching the closer again, whether the crash occurred after receipt persistence,
effect completion, H2 observation, head rebind, or immediately before batch commit. Lease loss at
any mutation rejects the stale writer; a later holder must claim a new fence and re-read the same
durable history.

## Races and recovery

- Concurrent consumers cannot both authorize progress because intent and batch mutations require the
  current task fence; stale holders fail at the ledger boundary.
- A head move between intent admission and return is not silently folded into H1. Only the post-launch
  exact GitHub read can establish H2, and the rebind requires the expected H1 plus live PR identity.
- A malformed historical second repair without progress makes intent planning fail before the next
  closer launch. This is the safe recovery default for pre-fix or corrupted rows.
- Restart and takeover reconstruct admission from durable attempts, not in-memory coordinator state.
  The intent id and batch id remain deterministic, so exact retries do not create duplicate evidence.

## Prior findings and convergence disposition

| Finding | Mechanism-level disposition |
| --- | --- |
| Progress evidence was impossible to produce through the closer schema/sanitizer. | The schema carries a canonical `progress_intent_id`; sanitizer round-trip and semantic rejection tests bind it to the consumer. |
| The prior reviewed head H1 was compared to the repaired head H2. | Intent binds H1; post-launch live truth and lease-fenced rebind establish distinct H2. |
| Arbitrary reusable strings could claim mechanism/validation progress. | A bounded GitHub compare supplies path/blob state and authenticated check/workflow execution ids supply validation state; head relabels, unrelated paths, identical blobs/executions, reused digests, and altered receipts are rejected. |
| A path shared with the prior full repair diff could be unrelated to the stable mechanism. | The blocking review schema/sanitizer carries a sorted path-hash projection; intent planning authenticates it as a non-empty subset of the prior GitHub transition and H1→H2 must modify that selected subset. |
| The convergence guard ran only after workspace mutation. | Durable intent planning/commit/readback is now a pre-launch gate; non-converging history never calls the closer. |

## Focused proof map

| Obligation | Probe |
| --- | --- |
| Non-converging history is stopped before closer launch | `tests/dispatcher/test_verification_consumer.py::test_repeated_nonconverging_repair_is_rejected_before_closer_launch` |
| Schema and sanitizer preserve canonical intent authority | `tests/dispatcher/test_verification_review_repairs_attempt7.py::test_progress_intent_round_trips_schema_and_consumer_without_authority_loss` |
| SQLite fence, direct/batch replay, restart, H1/H2 rebind, takeover | `tests/dispatcher/test_verification_review_repairs_attempt7.py::test_sqlite_progress_intent_is_fenced_monotonic_and_replay_safe` |
| BuilderOps API parity for the same transitions | `tests/dispatcher/test_verification_review_repairs_attempt7.py::test_builderops_progress_intent_is_fenced_monotonic_and_replay_safe` |
| Same validation execution, unrelated paths, and unchanged mechanism blobs are non-progress | `tests/dispatcher/test_verification_review_repairs_attempt7.py::test_repeated_repair_rejects_non_progressing_server_evidence` and `tests/dispatcher/test_verification_consumer.py::test_progress_validation_requires_new_authenticated_check_execution` |
| Receipt/effect/H2/rebind/pre-batch crashes recover without closer relaunch on both ledgers | `tests/dispatcher/test_verification_recovery.py::test_repair_postlaunch_crash_windows_resume_without_relaunch` and `tests/dispatcher/test_verification_recovery.py::test_builderops_repair_recovery_accepts_completed_effect_binding` |
| Pending delivered repair replay rebuilds authenticated transition/check evidence on both ledgers and fails closed without its persisted launch head | `tests/dispatcher/test_verification_review_repairs_attempt5.py::test_pending_delivered_repair_replay_rebuilds_authenticated_evidence` and `tests/dispatcher/test_verification_review_repairs_attempt5.py::test_pending_delivered_repair_replay_fails_without_launch_base_head` |
| Legitimate repeated progress has no numeric stop and always re-reviews | `tests/dispatcher/test_verification_agent_loop.py::test_progressing_repair_rounds_have_no_numeric_stop_and_require_rereview` |

Focused local proof receipts are intentionally not frozen in this packet. Exact-head CI and a fresh
independent mechanism review must both pass on the published head before merge or Issue closure.
