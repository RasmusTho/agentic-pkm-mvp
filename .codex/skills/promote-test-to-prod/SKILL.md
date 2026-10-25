---
name: promote-test-to-prod
description: "Promote the exact current green TEST candidate with durable functional PASS and explicit plan approval through protected stable authority, then deploy its tested immutable image and verify."
---

# Promote Test to Prod

> **Status: current source promotion policy (ADR-0068 D4, Issue #6228).**
> `stable` is the production promotion authority. Normal advancement requires the exact current
> `test` candidate C, trusted green TEST evidence, a durable functional PASS, and explicit approval
> of the concrete plan. Protected merge M records stable authority; it does not qualify a new
> source version or image. Production deploys the tested source C and immutable digest D.
> Repository support does not establish a running-prod observation or physical cutover. Current
> infrastructure observations belong to `RasmusTho/yggdrasil-infra/CURRENT_STATUS.md`.

Use this skill for the normal production stage of `main` → `dev` → `test` → `stable`. Read
`docs/RELEASE_CHANNELS/README.md :: Promotion model`, `:: Promotion contract`,
`docs/ENVIRONMENTS.md :: Code vs Environment Separation` and the existing plan contract. This is
Builder System boundary work; release receipts do not constitute runtime/user memory.

## Required evidence

All of these are required together:

- C is the **exact current** `test` ref, with trusted green DEV and TEST verdict artifacts from the
  delivered controller, and published build-once image provenance for immutable digest D.
- `promote-to-test` produced a durable functional PASS for C/D on isolated `test` bindings. Its signed
  STARTUP-04 v2 receipt, report, context and existing trust registry are available and fresh,
  non-revoked and mutually consistent. A green deploy, PG smoke or Markdown PASS alone is insufficient.
- The plan enumerates S→C code, config, migration and rollback deltas. S is the freshly read protected
  stable baseline and ancestor of C. A human approves this **concrete** plan, including every
  forward-only migration acknowledgment. An approved different plan cannot be replayed.
- Existing production model, isolation, vault, immutable-image and migration gates pass.

An older PASS candidate is ineligible once `test` changes. No implicit emergency bypass is provided
by this normal path or its source guard. A genuine emergency requires separately established
operator authority and an explicit recovery contract; a written risk note alone does not waive
these eligibility or migration checks.

## Procedure

1. Read current channel evidence and resolve C/D. Invoke `promote-to-test` when functional evidence
   is missing; do not replace it with fixtures or a deploy verdict.
2. Invoke `prepare-promotion` for this exact C. Preserve the signed functional evidence and trust
   inputs in the existing plan's `Test evidence` section; keep the seven required narrative sections.
3. Obtain the human's exact-plan approval and acknowledgments. Preparation never auto-approves.
4. Run `python -m app.release_channels.stable_promotion --plan <plan> --phase promotion` before
   effects. Refuse divergent S, unqualified checkout M, missing cutover evidence or changed TEST.
5. Invoke `execute-promotion --plan <plan>`. Both physical models retain the protected stable PR
   requirement. The implemented normal path uses an established pinned-image model and verifies
   M's `[S, C]` parents and unchanged tree, then deploys **C/D**, never an untested M image/version.
6. Invoke `verify-promotion --plan <plan>`. Require live C/D and the retained S/M admission receipt,
   plus all health, isolation, watcher, outbox and functional checks. Append observed receipts to
   the plan's output area and return the acceptance evidence.
7. On a pre-effect refusal, diagnose/repair. Reconcile unknown effects. Only an observed deployment
   effect needing recovery permits authorized `rollback-promotion` → `verify-promotion`; do not
   reverse forward-only migrations or start an automatic recovery loop.

## Binding and effect limits

Use `docker-compose.yaml:docker-compose.prod.yml`, project `pkm-prod`, `PKM_ENVIRONMENT=prod`, the
operator-configured real vault, DB `app` on 15432 and prod artifact paths. Never use test resources
for production. In pinned-image mode only `scripts/deploy_channel.sh deploy prod <C> --image-digest
<D> --promotion-plan <path>` performs the physical forward deployment. Recovery uses the existing
`rollback` command with the recorded previous-good pin under its separate authority.

The vault is never rewound; forward-only migrations and external effects cannot be undone by this
workflow. A source-policy merge establishes repository support, not a completed physical cutover
or running-prod observation. Current host facts belong to `RasmusTho/yggdrasil-infra/CURRENT_STATUS.md`.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. Continue prepare → execute → verify when
execution authority and exact-plan approvals already exist; do not ask twice for recorded approval.
On failure, use `execute-promotion`'s observed-effect recovery classification: failures before
deployment effects require diagnosis/repair without rollback; unknown effects require state
reconciliation. Only an observed deployment effect requiring recovery permits the authorized
rollback → verification route.
Missing approval, protected PR merge authorization, cutover evidence and migration acknowledgments
remain gates. Return preparation evidence when the authorized scope ends at planning.
