State: Filed target-state Builder System capability specification. Existing parent #3224 remains
`agent:blocked`; producer #3602 is delivered, execution-authority prerequisite #3603 is
`agent:needs-human`, and post-merge closure #3604 is `agent:blocked` on #3603. No new parent or
child Issue was created because these live, authoritative Issues already cover the bounded chain.
Doc role: Builder System capability specification
Authority: This directory owns the capability boundary, decomposition, cross-task invariants,
verification path, and acceptance path. GitHub Issues own executable lifecycle truth; GitHub PR,
CI, review, merge, and owner-document evidence remain authoritative for individual deliveries.
Owner: Builder System governance
Temporal class: Target-state implementation contract
Source of truth: #3224, #3603, #3604, `verification-and-closure`, live GitHub delivery evidence,
and the BuilderOps API/outbox contract for durable execution state.
Last reviewed: 2026-08-15

# Autonomous PR verification and closure

## Capability boundary

This Builder System capability makes an eligible published PR a durable, self-recovering
verification-and-closure case. It reduces the operator's coordination and memory burden by having
the installed verifier select the next safe action from current evidence until the case is merged,
blocked with one concrete governed decision, or superseded.

It does not create a second PR policy, task store, merge authority, or Product/Runtime capability.
GitHub remains authoritative for PR, Issue, check, review-thread, merge, and closure facts;
`verification-and-closure` remains the policy authority. BuilderOps API/PostgreSQL/outbox state
holds only the execution claim, attempt, idempotency, and readback-recovery evidence required to
operate that policy safely.

## Existing work reused rather than duplicated

- [#3602](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3602) delivered the artifact-only,
  current-head verification dispatch producer. It never invokes a model or mutates GitHub.
- [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603) is the exclusive existing
  prerequisite for the API-backed, host-fenced `verification_closer` execution authority. Its
  installed-main Demerzel cycle is not yet proved, so it is currently `agent:needs-human`.
- [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604) is the exclusive existing
  owner for post-merge dispatch, `merged_closure_pending`, orphan recovery, and the owner-document
  terminal gate. It is dependency-blocked on #3603.
- [#3224](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3224) remains the live parent
  validation hub for autonomous review, repair, and closure gates. This directory does not turn it
  into a pickup Issue.

## Case model and safe action selection

### Durable queue, claim, and idempotency

- A pre-merge case is identified by `RepoRef`, PR number, exact head SHA, `verification` stage,
  and the authenticated request contract/version. A post-merge case is identified by repository,
  PR number, exact merge commit SHA, `closure` stage, and contract version.
- The authenticated artifact plus a fresh live observation may create or re-open only the same
  canonical case. BuilderOps API task/attempt/outbox records provide the single durable claim,
  fencing token, heartbeat, operation key, and terminal receipt; duplicate events/replays must
  return the same case rather than launch another closer.
- An exact-head change, governing-issue/closing-set drift, required-check drift, protected-base or
  delivery-manifest drift invalidates the affected attempt before a model or GitHub mutation. The
  case records a bounded backoff or supersession and must re-read live authority before it can run
  again.

### Verification actions and gates

- The consumer may routinely authenticate an artifact, claim a case, collect bounded current PR,
  Issue, check, review, comment, and receipt evidence, wait with the shared backoff contract, and
  invoke the registered closer only after the existing eligibility gates pass.
- The closer verifies every Issue acceptance criterion and `Verify:` target on the current head.
  Required CI is necessary but never sufficient. The selected delivery tier determines whether the
  independent review gate applies; fresh review/comment and review-thread evidence is evaluated on
  the current head, and a blocking P0/P1 finding invalidates prior review authority.
- Merge, Issue closure, label cleanup, optional Project projection, parent validation, and
  owner-document handling remain exactly the steps and permissions already authorized by
  `verification-and-closure`; the case function may not bypass or reinterpret them.
- The safe terminal states are `merged` only after exact readback and receipts, `blocked` only with
  a deduplicated technical or governed Human Exception reason, and `superseded` only when live
  authority proves a later exact-head/terminal chain replaces it.

### Post-merge reconciliation and orphan recovery

- Every merged PR emits one artifact-only closure request. A bounded scheduled/manual reconciler
  also derives `merged_closure_pending` from live terminal evidence, not from a stale local list.
- Recovery re-fetches merged PR, closing Issue set, labels, dispatcher/API task state, receipts,
  optional Project projection, parent state, and the required `post-merge owner-doc check:`
  receipt. It performs only a missing authorized terminal step; a completed replay performs zero
  GitHub mutations.
- A closed-unmerged PR, conflicting Issue links, missing proof, or ambiguous closure attribution
  is not guessed. It remains a deduplicated technical block or the canonical Human Exception
  packet, as classified by the existing escalation contract.

## Cross-task invariants / interaction safety

1. **One canonical case per authority identity.** Event delivery, reconciliation, restart, and
   takeover may converge on one fenced case, never create parallel verification or closure chains.
   A case is not terminal merely because an event was consumed.
2. **Live authority outranks queued evidence.** An artifact, stored request, cached check, review,
   or prior receipt may locate work but cannot authorize an effect after head, policy, issue, or
   merge-state drift. Revalidation happens before launch and before privileged effect.
3. **No effect before durable intent; no success before readback.** A fenced attempt/outbox intent
   commits before an external effect. A timeout is `unknown`; recovery reads GitHub before retry.
   A model return, merge response, or local completion never alone proves delivery.
4. **Closure is monotonic and stepwise.** A crash after merge but before Issue/receipt/owner-doc
   completion leaves `merged_closure_pending`; replay can finish only the missing steps and cannot
   repeat a closure comment, owner-doc decision, label mutation, Project write, or Issue closure.
5. **Policy and authority do not migrate into automation.** GitHub Actions stays artifact-only;
   BuilderOps durability does not make it PR or Product authority; the closer may not repair source
   code in closure-only mode; unresolved authority is routed once through the canonical classifier.
6. **Owner-document proof is a terminal gate.** Where `verification-and-closure` requires it, an
   exact, trusted owner-document receipt is necessary before the case releases its delivery lane.
   A watchdog nudge or a generic comment cannot substitute for it.

Partial failures therefore preserve a retryable pending case rather than a false successful closure:
if dispatch is written but the consumer dies, reconciliation rediscovers it; if a merge effect is
unknown, readback resolves it before retry; if merge succeeds but closure crashes, the closure case
remains pending; if a newer head arrives, the old head is superseded without erasing audit or
repair accounting.

## Implementation tasks and order

1. [Establish verification execution authority](ESTABLISH_VERIFICATION_EXECUTION_AUTHORITY.md)
   (AVC-01, existing #3603) makes the durable, API-backed host consumer eligible for an
   installed-main pilot. It is an external prerequisite for this capability's closure task.
2. [Dispatch and reconcile post-merge closure](DISPATCH_AND_RECONCILE_POST_MERGE_CLOSURE.md)
   (AVC-02, existing #3604) consumes that authority to make post-merge closure self-healing.

The first task must finish its host-authority and pilot proof before the second becomes ready. The
two tasks intentionally do not run in parallel because they share the same execution authority and
one-active-chain safety invariant.

## Verification and pilot / acceptance path

Each task runs its named focused contract tests, exact-head CI, and the tier-selected independent
review/comment handling in its governing Issue and PR. The live parent #3224 receives one compact
receipt after each child delivery; owner docs are promoted only when the capability's supported
truth changes.

The smallest acceptance pilot uses one low-risk, issue-backed PR and proves this full chain:

`published PR -> current-head CI artifact -> authenticated host claim -> verification gates ->
merge or governed block -> closure request -> terminal Issue/owner-doc receipt -> replay no-op`.

The receipt names the PR, exact head/merge SHA, dispatch id, BuilderOps run and terminal receipt,
all lifecycle mutations, the owner-document disposition, and a replay showing zero duplicate
mutation. It also compares the operator interventions needed for that case with the previous
manual handoff; a reduction is accepted only when every existing CI, review, issue, closure, and
owner-document gate still has current evidence.

## Relationship to GitHub Issues

No duplicate parent or child backlog was filed in this specification pass. #3224 is the existing
parent validation hub; #3603 and #3604 are the existing independently deliverable issue contracts
in dependency order. Their live GitHub labels and exact-head evidence, rather than this document's
status line, govern pickup and completion.
