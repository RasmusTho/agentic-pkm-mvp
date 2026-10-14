State: Development reference. Escalation-only PR workflow reference.
Doc role: Escalation reference
Authority: Conditional procedures for PR delivery. Do not read or execute these sections unless `PR_HOT_PATH.md` says a trigger applies.
Owner: Builder-agent governance
Temporal class: operational

# PR Escalation Paths

This document exists to keep the default PR hot path short.
Do not read or execute these sections unless a trigger in [`PR_HOT_PATH.md`](PR_HOT_PATH.md) applies.

## 1) CI Failure Investigation

Use when a required check fails, is missing on the current head SHA, or is stale.

- caused-by-PR -> fix the code, config, or test, then rerun the relevant checks before merge
- pre-existing-with-evidence -> link the follow-up, record the waiver or receipt, and do not claim the failure as resolved by this PR
- unresolved -> block merge

If a pytest failure mentions an unavailable plugin flag, treat that as a check-loading issue only when the PR actually touches the pytest invocation and the plugin is part of the expected environment.

## 2) Merge-Ref Validation

Use after a review-fix push when CI may differ on the GitHub merge ref.

- fetch `refs/pull/<PR>/merge`
- inspect the touched symbols in the merge ref, not only the branch head
- run at least one targeted smoke or regression test against a temporary worktree for the merge ref
- if the merge ref fails, do not declare `ready-for-verification`

## 3) Branch Drift Recovery

Use when local HEAD, the tracked remote branch, and the PR head SHA do not match, or when the active worktree is not the PR worktree.

- stop committing until branch truth is restored
- isolate unrelated local drift explicitly
- preserve any necessary backup state before re-pointing the PR branch
- re-check branch, worktree, and SHA truth before any new push

## 4) Dependency Issue Scan

Use after merge or after verification when the delivered work unblocks other issues.

- scan for issues that explicitly depend on the delivered issue
- remove `agent:blocked` and every `action:*` label, then add `agent:ready`, only when the dependency
  is truly satisfied and the prospective label set passes strict readiness validation; preserve the
  prior `blocker_action.v1` comment as immutable historical evidence
- do not unblock issues whose real dependency is still missing

## 5) Owner-Doc Check

Use after merge when shipped behavior, contracts, or architecture may have changed owner-doc truth.

- run the post-merge owner-doc check on the merged PR
- if the wording change is clear, open a docs-only PR
- if wording needs judgment, open one bounded follow-up issue
- if no owner-doc change is implied, leave the no-change receipt

## 6) Heavy Review / Comment Loop

Use when review feedback is blocking, repetitive, or clearly requires more than a quick hot-path reply.

- classify the feedback first
- P0/P1 correctness, contract, or safety defect -> block merge, fix, and independently re-review
- P2 real defect accepted for this PR -> leave the PR code unchanged for that finding, route it
  through `bug-to-issue`, reply on the finding/thread with the Issue reference, and merge without
  another review round once the durable disposition is live
- P3 informational advice or non-defect suggestion -> record when useful; do not block, repair, or
  open defect intake
- out-of-scope -> short response only
- incorrect or not applicable -> short response only
- apply the protected severity floors and dispatcher receipt compatibility rule from
  `.codex/skills/verification-and-closure/FULL_PATH.md :: Severity routing`; there is no valid
  `blocking P2`
- if the loop keeps expanding, stop and classify the PR as blocked rather than dragging the hot path into a governance cycle

## 7) GitHub Project / Board Cleanup

Use when lifecycle state is truthful in GitHub content but the board projection is stale.

- correct terminal work to `Done`
- correct open work to the state implied by its current labels and PR state
- do not treat board cleanup as a reason to block a delivered PR if the delivery itself is sound

## 8) Full Governance Receipt Repair

Use when the delivery trail is incomplete, stale, or contradictory.

- repair issue/PR traceability
- repair missing or stale receipts
- route terminal closure work through verification-and-closure or issue maintenance instead of padding the hot path

### Evaluated route disposition (#5858)

The finite #5857 inventory was refreshed against its merged main
`69e23e89ce5962c556af16cdf454026c2e1380fd`. The safe retirement is duplicated instruction text
and the stale review-only full-path selection claim. No executable route or generated proof
artifact is demonstrated unconsumed. Automatic native round-1 suppression already shipped in
#5836 and is retained, not attributed to this cleanup.

| Inventory surface | Disposition | Current consumer and concrete trigger |
| --- | --- | --- |
| `publish-pr/SKILL.md`, `scripts/publication.py`, `app/builderops/publication.py` | Retained | Native Tier 1/2 publication with review rounds 0/1, supported issue-free lanes, resumed/exact existing candidates and batches of at most ten; unsupported lanes, risk, base or history still refuse into `publish-pr/FULL_PATH.md` |
| `verification-and-closure/SKILL.md`, `scripts/closure.py` | Retained | Session-owned native merge and exact closing-Issue readback; the closure adapter remains the single-Issue rounds-0 subset. Independent review alone does not select executor ownership |
| `verification-and-closure/FULL_PATH.md` | Duplicate common validation, continuation and CI-wait instructions removed; review-only selection claim corrected | Common checks reference `SKILL.md :: Inputs` and `:: Validation`, README continuation and the shared CI wait contract. Dispatched contexts, authenticated merge attempts and release operations still consume the full path; unique supersession, severity, fencing, phase and recovery rules remain |
| Issue-free reviewed compatibility procedure within `FULL_PATH.md` | Retained with its actual executor/in-flight trigger | `scripts/prepare_verified_issue_set_merge.py` calls the issue-free reviewed-lane planner in `app/dispatcher/verified_merge.py`; `scripts/plan_issue_free_post_merge_reconciliation.py` consumes exact closure attribution. The existing full-path router must select this procedure first |
| `PR_ESCALATION_PATHS.md` | Retained; disposition recorded here | CI failure/missing checks, merge-ref review repairs, SHA/worktree drift, known dependent-Issue changes, owner-doc changes, blocking feedback and contradictory delivery receipts trigger their existing sections |
| `scripts/build_verification_dispatch_request.py` | Retained | Workflow/CLI automatic construction suppresses rounds 0/1; explicit `--executor-request` or provenance-bound canary input admits reviewed executor requests. Stale head, mismatched Issue or closing references still refuse |
| `.github/workflows/verification-dispatch-request.yml` | Retained | Successful current-head CI Smoke plus legacy rounds 2 reaches closing-reference lookup and artifact production. Native rounds 0/1 exit before those effects. An artifact does not transfer merge ownership |
| Dispatcher verification consumer/dispatch/contract/merge/store and CLI | Retained | Authenticated enqueue/consume requests and already-started fenced operations. Deployed capability, credentials and installation remain separate operational authority; unknown host adoption does not prove absence |
| Post-merge docs classifier and owner-doc watchdog workflows | Retained | Merged-PR classification imports `resolve_post_merge_issue_authority`; watchdog phase/history classification handles native and verified-merge trails. Native merges therefore still consume verified-merge helpers |
| Request/workflow/architecture/publication regression tests | Retained and extended at production callsites | The workflow snapshot step executes for native, malformed and legacy-round-2 inputs; real local Git publication and the request producer verify native/executor separation, stale-head and authority refusals |
| `BUILDER_SYSTEM_PROCESS_MAP.md`, `PR_HOT_PATH.md` | Retained | Existing owner/reference descriptions and their linked production consumers. This cleanup changes no executable routing or operational adoption claim |

No compatibility-code migration is inferred from the sampled deliveries. Retiring legacy automatic
rounds 2 would first require an identified host/request consumer migration and proof that no
authenticated attempt remains in flight; the current workflow is a concrete retained producer.
The two #5858 caller/routing `Verify:` tests cover this disposition without replacing current-head CI
or the protected full-path checks.
