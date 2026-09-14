State: Defined recovery boundary; no execution authorization.
Doc role: Builder System governance / recovery contract
Authority: Defines the only safe recovery route for a rejected prepared-history attempt. It does not authorize a merge, Issue closure, receipt rewrite, or retry by itself.
Owner: Builder System governance for the contract; the human owner for each recovery decision
Temporal class: operational
Source of truth: this contract plus the live authenticated GitHub evidence named below
Last reviewed: 2026-09-14

# Rejected Prepared-History Recovery Contract

This contract applies when a non-merged Pull Request has a `verified_issue_set_merge_phase.v1`
`prepared` marker that the current independent resolver rejects, and no merge request was accepted.
PR [#5539](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5539) and Issue
[#5531](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5531) are the motivating case. The
contract is a recovery boundary for the Builder System; it is not proof that the original delivery
was valid or that the target capability shipped.

## RPHR-01 — Decision and allowed route

The only supported v1 route is `supersede_and_restart`:

1. Freeze the rejected attempt as immutable audit history.
2. Verify the prevention repair tracked by [#5541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5541)
   (or an equivalent independently verified producer fix) is delivered before a new attempt starts.
3. Create a new PR from the current `main` with a new branch, new head, new `run_id`, fresh authority
   receipt, and fresh verification evidence.
4. After the new attempt has a valid fresh authority and current-head review/CI gate, close the old PR
   as superseded with an explicit link to the new PR. This does not close the governing Issue.
5. Deliver the new PR through the ordinary verified-merge and Issue-closure path. Only that new PR may
   close the governing Issue, and only if its authenticated closing set names it.

An in-place `resume` of a rejected prepared history is forbidden in v1. The current resolver fails
closed because an invalid current-schema phase cannot be treated as harmless history. Making it
ignorable would require a separately implemented and tested quarantine receipt, consumer rule, and
audit-continuity contract; prose or a new comment cannot supply that behavior.

## RPHR-02 — Evidence freeze before any recovery effect

The recovery decision must bind all of the following to the exact old repository and PR:

- old PR number, repository identity, base/head refs and SHAs, title, canonical body digest, and any
  neutralized-body digest;
- governing, closing, and supporting Issue sets; the immutable authority receipt digest and its
  `run_id`/repair-budget projection;
- the durable projection-convergence receipt digest, its embedded final-observation digest, and the
  rejected prepared-phase receipt/rejection reason;
- live evidence that the old PR is unmerged and that no accepted merge request was made; and
- the complete prior attempt and repair history, including all immutable comments and receipts.

If any identity, body, issue set, phase, convergence, merge, or attempt evidence is missing,
contradictory, stale, or ambiguous, recovery stops with no GitHub, branch, receipt, or lifecycle
mutation. The old PR and Issue remain blocked for human disposition.

The recovery packet must also name the new `main` base SHA, the exact prevention-fix evidence, the
new branch/PR/run identity, the selected route `supersede_and_restart`, and the permitted lifecycle
effect of superseding the old PR. A request to “retry” without these bindings is not recovery
authority.

## RPHR-03 — New-attempt rules

The new attempt must be independently derived from the current source and must:

- use a new branch, head SHA, `run_id`, authority receipt, body digest, and repair accounting;
- re-read the governing Issue and source documents, refusing changed or ambiguous scope rather than
  copying the old PR's untrusted phase output;
- pass the normal issue/PR contract, review, current-head CI, convergence, prepared-phase, merge,
  reconciliation, and owner-doc gates on its own exact head; and
- cite the old PR only as historical evidence of the rejected attempt, never as current merge or
  closure authority.

The old authority, convergence, and phase comments are retained verbatim. They cannot be deleted,
edited, replaced, re-digested into a new phase, or used to reuse the old `run_id`. The old PR is not
merged, and its closure as superseded must not close or relabel the governing Issue.

## RPHR-04 — Failure and refusal matrix

| Condition | Lawful action | Forbidden action |
| --- | --- | --- |
| Old authority, convergence, or phase history is incomplete or contradictory | Keep the attempt blocked; request a new owner decision | Guess, repair by comment, or select the newest observation |
| Old PR is merged, has an unknown merge outcome, or has an unauthorized closure | Stop and route to live merge/closure reconciliation | Supersede it as though no external effect occurred |
| Old PR body cannot be authenticated or safely restored | No write; preserve the existing history | Rewrite the body or reuse the old authority |
| Governing Issue, source scope, or parent relationship changed | Require a new bounded recovery decision and contract | Carry old approval into the changed scope |
| Prevention fix #5541 is not delivered and verified | Wait; no new attempt | Treat the prevention bug as recovery authority |
| New attempt loses head/body/review/CI/convergence truth | Stop that new attempt and retain both histories | Merge, close the Issue, or repair by bypass |
| Owner withdraws recovery authority | Stop with a blocker receipt | Continue because earlier receipts were green |

## RPHR-05 — Explicit non-effects

This contract does not:

- resume, neutralize, merge, close, relabel, or rewrite PR #5539;
- close, unblock, or mark Issue #5531 delivered;
- turn the prevention fix in #5541 into recovery authority;
- create synthetic delivery, CI, review, convergence, merge, or owner-acceptance evidence; or
- authorize runtime, deployment, credential, host, or Product/Runtime effects.

## Verification and acceptance boundary

This document is a governance contract. Its merge proves only that the recovery route is defined and
discoverable; it does not execute recovery or claim delivery. Any implementation of in-place phase
quarantine or a new recovery receipt requires a separate Issue with production callers, focused
tests, explicit mutation authority, and an independent review. Until then, `supersede_and_restart`
is the sole lawful route for the rejected prepared-history class.

The motivating state remains visible in the live records: [PR #5539](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5539)
is open and blocked, and [Issue #5531](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5531) retains
`agent:blocked` plus `action:repair-contract`.
