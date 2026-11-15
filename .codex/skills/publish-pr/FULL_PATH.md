State: Canonical full-path publication procedure for `.codex/skills/publish-pr/SKILL.md`.

# Full-Path PR Publication

Use this file only after the publish-pr router rejects the normal plan/apply path. It owns the
publication boundary through exact PR readback; it does not own implementation, merge, Issue
closure, release, deployment, or claim release.

## Scope

| Trigger | Required route inside this procedure |
| --- | --- |
| Existing PR or review repair outside the exact native binding | Refresh exact PR scope, then use `pr-integration` before publication effects. |
| Unbounded/merge history, non-`main` base, unexplained remote head, or closed/merged/duplicate/mismatched head-branch history | Preserve the state and run the authority/collision checks below; never coerce it into native plan/apply. |
| Issue batches outside the explicit native contract | Apply `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`. Never waive its ten-Issue limit. |
| Direct Repair or issue-free work outside docs/governance | Apply the matching lane contract in `docs/development/PR_HOT_PATH.md`. |
| Tier 3 or auth/security/data/migration/concurrency/external-API/credential-durability/state-machine risk | Complete `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate` on the local publishable SHA before expensive proof or an external effect. |
| Ambiguous transport/readback | Stop with the observed state and use `pr-integration`; no blind retry or alternate transport. |

Verified merge body fencing, merge, Issue closure, post-merge owner-doc writeback, release, and
promotion remain with their named skills.

## Procedure

1. Refresh the full governing Issue, active claim/lease, worktree registry row, branch, local `HEAD`,
   effective fetch and push repository identities, live target-base SHA, remote head, all-state PR
   history for the exact head branch, and—when present—the PR head/base/body/check/review state.
   Treat URL userinfo, multiple effective URLs, fetch/push repository mismatch, stale base, duplicate
   history, or a worktree/lease collision as a hard stop. Never retain or report raw remote URLs.
2. Bind the intended file set, lane, Issue set, target base, commit intent, PR title/body, TCD risk
   classification, BuilderOps routing, and owner-doc resolution. Re-run
   `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: PR-Level Scope Revalidation Gate`
   for an existing PR. Complete Mechanism Convergence when its trigger applies.
3. Generate and inspect the complete PR body through `scripts/pr_body_generator.py`. Run the
   affected focused checks and `scripts/review_before_ci_gate.py`; a high-risk mechanism receipt must
   name the current local publishable SHA. A failed or stale gate blocks publication.
4. Run `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` immediately before commit and again
   immediately before push. Stage only the bound paths and make an additive commit when content
   changes. A clean unchanged-head metadata-only update under the scope gate skips commit; the
   existing adapter retains its ordinary non-force same-SHA push and exact readback.
   Do not rebase, amend, reset, delete a ref, force-push, or rewrite unrelated history unless a separate explicit
   authority contract requires that exact action.
5. Immediately before a new PR effect, refresh the target base, effective fetch/push identities,
   remote head, and all-state PR history again. New-PR creation requires no conflicting history and
   one explainable remote branch state. Existing-PR publication requires one exact open PR whose
   repository, head ref/SHA, base ref/SHA, Issue scope, title, and body match the refreshed intent.
6. Use an ordinary non-force push only when branch truth proves it is a fast-forward of the observed
   remote state. Create at most one new PR, or update only the uniquely matched existing PR. A
   nonzero/timeout is not success: perform one immediate complete readback and continue only when it
   proves the exact intended effect; otherwise stop `unknown`.
7. Read back local `HEAD`, remote head, live base, all-state PR history, and the exact PR identity.
   Report commit SHA, PR number, base SHA, checks run, plan/gate receipts, and the next workflow.
   Never fabricate a receipt or treat publication as merge, closure, release, or delivery success.

### #6561 existing PR observation

For interactive native continuation of the separately reconciled #6561 / #6562, immediately before
each push or PR update re-read the pinned successor, current claim, local candidate and unique PR
under the ordinary procedure above. Also run the bounded read-only source observation below with
the exact original pending operator comment ID and actual current session; compare its
`operator_digest` with the pinned registration's pending digest. A missing or mismatched source,
observation or pin is UNKNOWN. Coordinate no new manual starts throughout the observation and
effect. The observation is not publication authority or a lock, and does not replace the normal
PR, scope, review, branch or effect-readback gates.

```sh
python3 -c 'import json,sys; from pathlib import Path; from app.builderops.legacy_codex_6561_guard import check_runtime; print(json.dumps(check_runtime(cwd=Path.cwd(), issue=6561, pr=6562, worktree=Path(sys.argv[1]), session=sys.argv[2], comment_id=int(sys.argv[3]))))' \
  <absolute-6561-worktree> <current-session> <pending-operator-comment-id>
```

The current head and body are checked by the ordinary full-path PR readback: the original
publication's terminal commands and source-bound old body remain historical evidence. Read back
each exact push or update; a timeout, contradictory result, or unavailable readback remains UNKNOWN
and cannot justify a blind retry. Do not use this route to replace an observed dispatched or in-flight
executor's authority or phase gates.

### #6560 existing PR proof

For recovery of #6560 into its existing PR #6565, run the read-only proof below immediately before
each effect, with `--effect push` or `--effect patch`, the actual successor agent/session, the exact
local commit, and the freshly read remote PR head. Before the first PATCH, pass
`--just-pushed-from <original-pr-head>` only after exact readback of that specific push.

Before each PATCH, generate and inspect the exact new body, including exactly one invisible marker
`<!-- operator-publication-attempt:<32 lowercase hexadecimal characters> -->` with a fresh attempt
ID. Preserve that body as an absolute file outside the worktree. After the file exists and is
reviewed, the authenticated operator uses the existing Issue or PR comment channel to record a JSON
object with the sole root `operator_publication_intent.v1`. Its fields are `issue`, `pr`,
`repository`, `branch`, `session`, `agent`, `lease_id`, `head`, `before_body_sha256`,
`body_sha256`, `body`, `attempt_id`, and `reviewed: true`. The body field contains the entire
reviewed body, not merely its hash. Read back the unedited owner-account comment and pass its ID and
the body file as `--next-intent-comment-id` and `--next-body-file`. For any later push or PATCH
after a successor body is live, also pass that body's original file and comment ID with
`--prior-body-file` and `--prior-intent-comment-id`. A later PATCH needs both the prior live-body
intent and the new attempt's intent. A missing, foreign, edited, duplicate, mismatched or late
intent stops the effect.

The comment authenticates the account and binds the bytes attested by the operator; it does not
authenticate a human signature or establish that a PATCH actually ran. The coordinating operator
must preserve and inspect the active session's actual ordered command records: the completed proof
with that comment ID, the specific subsequent PATCH invocation and its exact body input, and its
response/readback. Bind these records to the same issue, PR, head, session and attempt ID. If the
records do not establish that the comment and proof preceded the specific attempt, its exact input,
or the outcome, retain UNKNOWN and do not issue another PATCH. Generic PR `updated_at`, an arbitrary
caller hash, a source label, or a body copied from a later GitHub response is not that evidence.
After an ambiguous response, exact authenticated live body/head may reconcile only that earlier
reviewed, source-established attempt. The single-coordinator and no-new-manual-starts conditions
remain necessary. This proof is not a distributed lock and does not replace review, scope, CI or
branch gates.

```bash
python3 -m scripts.legacy_6560_publication_gate \
  --worktree <original-6560-worktree> --agent <successor-agent> --session <successor-session> \
  --effect push --head <local-candidate-sha> --expected-remote-head <observed-pr-head-sha>
```

The first candidate commit must contain exactly the two acknowledged dirty files and their preserved
bytes; use an isolated temporary index for that commit so unrelated existing staging is preserved.
After the commit, reconcile only those two selected entries in the ordinary index to the new HEAD,
then verify the previously staged unrelated entries still have their exact prior blob IDs. Do not
reset or otherwise rewrite the unrelated index entries.
The normal `publication.py` and OpenHands draft adapters refuse this scoped recovery. This procedure
cannot prevent a raw, ungoverned Git push or a manually initiated Codex session.

## Recovery outcomes

- Exact unchanged pre-effect state: rerun the owning gate, then retry the single failed command.
- Exact intended commit and no PR: revalidate authority and create only the missing PR.
- One exact open PR: reconcile and hand off without another create.
- Exact closed/merged history, duplicate/mismatched history, unexpected remote movement, base drift,
  unavailable readback, or uncertain command outcome: stop and preserve evidence for
  `pr-integration`; no further publication effect is authorized.

## Handoff

Execute `pr-integration` for concrete repair/readiness or ambiguity. Otherwise immediately execute
`verification-and-closure` under `.codex/skills/README.md :: Workflow continuation`; reporting the
next workflow is not a terminal handoff. The active claim and worktree lifecycle stay with `issue-to-code` until
that workflow performs governed closure.
