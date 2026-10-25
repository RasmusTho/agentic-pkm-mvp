---
name: execute-promotion
description: "Execute an explicitly approved current-TEST promotion plan through a protected stable PR and the existing immutable-image deploy path; verify the result and preserve migration gates."
---

# Execute Promotion

> **Status: current source promotion policy (ADR-0068 D4, Issue #6228).**
> `stable` is the production promotion authority. Normal advancement requires the exact current
> `test` candidate C, trusted green TEST evidence, a durable functional PASS, and explicit approval
> of the concrete plan. Protected merge M records stable authority; it does not qualify a new
> source version or image. Production deploys the tested source C and immutable digest D.
> Repository support does not establish a running-prod observation or physical cutover. Current
> infrastructure observations belong to `RasmusTho/yggdrasil-infra/CURRENT_STATUS.md`.

Use this skill only with execution authority and a complete, explicitly human-approved plan from
`prepare-promotion`. Read `docs/RELEASE_CHANNELS/README.md :: Promotion contract`,
`DEFINE_PROMOTION_PLAN_CONTRACT.md`, and `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md` in that
same directory. This is Builder System boundary work: the plan and receipts govern effects on the
Product/Runtime channel. They do not constitute running-prod observations.

## Admission before any stable or host effect

Run the existing read-only admission entrypoint from the authoritative source checkout:

```bash
python -m app.release_channels.stable_promotion --plan <plan> --phase promotion
```

It checks the complete reviewed plan and human approval; exact current `test` C; trusted green DEV
and TEST artifacts; the build-once C/D image provenance; durable signed functional PASS and report;
the existing STARTUP trust registry, freshness, revocation, immutable source and migration checks;
stable protection; current baseline S; and S ancestry of C. A missing, stale or unavailable input is
a refusal. Do not turn a local flag, same-tree comparison, smoke verdict or check result into
human approval. Keep forward-only migration acknowledgments and vault/channel preflight mandatory.

Resolve the physical model from `ops/deployments/prod-latest.json`. An existing prod
`fleet_model_fitness.v1` PASS for `model=pinned-image` is required by this normal forward path. A checkout
would run GitHub's new merge SHA M rather than TEST source C; it is refused **before opening the
stable PR**. Do not deploy untested M, weaken stable protection, or infer that a physical model
transition occurred. Existing restart/recovery procedures are not new promotion authority.

If S is not an ancestor of C, stop before effects. A separately reviewed reconciliation must land
in `main` and pass the complete DEV/TEST route before that new current TEST candidate is eligible.
Never force stable, guess a baseline, or qualify an integration commit merely by matching trees.

## Protected stable advancement

Every normal stable advancement uses a governed PR targeting `stable`; pinned-image mode has the
same requirement. Read back protection: enforce admins, PR required, strict `smoke`, `smoke-docker`
and `pr-contract`, force pushes disabled, deletion disabled. Never write stable directly.

1. Preserve S and the previous-good C/D pin in the approved plan before effects.
2. Run the channel-isolation guard against the prod checkout's own full compose path:
   `python -m app.release_channels.channel_isolation_preflight <prod-checkout>/docker-compose.prod.yml prod`.
   Verify project `pkm-prod`, environment `prod`, DB `app`/15432, initialized real vault and the
   reviewed migration/config delta. Do not use a dev/test checkout or vault.
3. With the exact current C as PR head, open the governed PR to stable. Wait for all required checks
   per `_shared/CI_WAIT_CONTRACT.md`. Re-run promotion admission and verify exact PR head C after
   the wait, immediately before the operator-authorized expected-head merge. A changed TEST/S, stale
   receipt, changed plan or PR head requires refusal and fresh preparation. The operator merges
   under existing stable protection; plan preparation alone does not grant merge approval.
4. Read back the merged PR and current stable M. Require the same repository, base `stable`, head C,
   merge SHA M, M parents exactly `[S, C]`, and tree M equal to tree C. Record only the independently
   verified PR number and M in the existing plan's `execution` fields. Those output fields cannot
   change the approved C, D, S, migration narrative or model. Squash, rebase, additional merge edits,
   a changed current TEST, or a changed stable frontier fail closed.

M establishes protected stable authority only. C remains the source/runtime version and D remains
its TEST-qualified immutable image. Do not build, retag or silently qualify a new M artifact.

## Physical execution

Revalidate immediately before deployment:

```bash
python -m app.release_channels.stable_promotion --plan <plan> --phase deploy --candidate <C> --image-digest <D>
scripts/deploy_channel.sh deploy prod <C> --image-digest <D> --promotion-plan <absolute-plan-path>
```

Pass `--ack-forward-only` only for the explicitly acknowledged migrations in the plan. The deploy
script and native host adapter enforce admission before secret materialization or stack effects.
For the native host path, pass the same **target-host** absolute plan path through
`app.ops.postgres_deploy_host --promotion-plan`; a control-host path is not portable evidence.
The target must have the approved plan, retained P2 render/ChannelManifest, signed receipt/report/context
and existing trusted registry. The immutable S/C/M Git objects must be present in the authoritative
operations checkout for the existing sanitized reader; missing objects cause refusal. Any fetch
belongs to explicitly authorized preparation, never to this read-only admission guard.

The existing script owns migration classification, pin bump, service recreation, readiness, smoke
and `ops/deployments/prod-latest.json`. Do not replace it with checkout restart, apply unlisted
migrations, reverse a forward-only migration, or bypass its immutable-image gates. Its receipt must
retain the C/D, S/M, approval digest and functional receipt identity returned by admission.

STARTUP-04 keeps its signed v2 receipt and trust rules. Before the stable PR its migration baseline
is freshly read canonical S. After the PR, the same approved plan must independently prove the
current protected S→M transition for C/D before STARTUP may reuse S; no caller-selected baseline.

## Verification and recovery

Append observed execution/verification receipts after `<!-- promotion-outcomes -->` in the retained
plan. This output area grants no admission authority; modifying any reviewed inputs or narrative
still invalidates approval. Invoke `verify-promotion --plan <plan>` and retain ownership through its
acceptance receipt or governed recovery.

A refused plan, ancestry or PR check before effects requires diagnosis and repair. It does not
permit rollback. If effects are unknown, reconcile the actual stable, pin, migrations and process
state first. Only observed effects needing recovery and existing rollback authority permit
`rollback-promotion`; retain irreversible migration limits and verify the recovered channel.

## Routing

- Produced by: `prepare-promotion`
- On success → `verify-promotion`
- On failure before deployment effects → diagnose and repair the refused step; do not roll back.
- On failure after observed deployment effects → `rollback-promotion` within rollback authority.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. After successful execution, invoke
`verify-promotion` with the plan and retain ownership through its acceptance receipt or governed
recovery. A failed preflight, plan check, or stable-PR check does not authorize rollback: first read
back whether the deployed pin, stable ref, migrations, or running process state actually advanced.
If no deployment effect occurred, diagnose and repair the refused step without production mutation.
If the effect is unknown, reconcile observed state before choosing recovery; do not blindly retry or
roll back. Invoke `rollback-promotion` only after evidence establishes a deployment effect requiring
recovery and its existing rollback authority and migration gates hold. Never leave successful
execution unverified.

Missing concrete-plan approval, protected merge authorization, physical cutover evidence, or a
migration acknowledgment remains a genuine operator gate. Source implementation and local tests
do not satisfy any of those live gates.
