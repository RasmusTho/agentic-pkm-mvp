State: Target-state delivery plan; no post-merge dev/test automation is claimed as shipped.
Doc role: Plan.
Authority: Proposes the post-merge Product Runtime `dev` → `test` automation boundary. `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` remains the deployment-mechanics owner; `docs/TESTING.md` remains the testing-gate owner; `docs/RELEASE_CHANNELS/README.md` remains the promotion-authority owner.
Temporal class: operational
Review cadence: before implementation and after the first ten-candidate pilot
Source of truth: repository workflows/scripts plus fresh, redaction-safe runtime receipts
Last reviewed: 2026-09-25
Last verified against: `.github/workflows/ci-smoke.yaml`, `.github/workflows/integration-nightly.yaml`, `.github/workflows/app-image-build.yml`, `scripts/deploy_channel.sh`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, issue #2698 final receipt

# Fast PR-to-merge with automatic dev/test delivery

## Intent and boundary

Reduce PR-to-merge time by keeping broad, slow, or live-host evidence out of the required PR merge path, while using isolated `dev` and `test` channels for fast post-merge feedback. This document is a delivery plan, not evidence that the automation or runtime qualification is complete.

The intended flow is:

`PR required smoke → merge → build one immutable image for the exact main SHA → deploy to dev → short health/version smoke → promote that same image to test`

Production remains on the separately governed promotion path. Neither a green dev/test deployment nor this plan grants production authority.

## Verified starting point

- `.github/workflows/ci-smoke.yaml` is the PR fast path. Docs-only changes have a lighter selected path; source/integration changes retain their required smoke checks.
- `.github/workflows/integration-nightly.yaml` runs the broad scheduled/on-demand suite, including its bounded PostgreSQL lane. It is not the PR merge gate and does not deploy or roll back a channel.
- `.github/workflows/app-image-build.yml` builds and publishes an image identified by source SHA and verifies image/runtime identity on its current main path.
- `scripts/deploy_channel.sh` provides channel-scoped deployment mechanics, but no workflow in the verified repository state invokes it.
- Issue #2698 is closed. Its final public receipt records a successful pinned-image production deployment at SHA `311631b08efdf08809a5677d20e3612f80a0022c`; that receipt does not establish fresh equivalent `dev` and `test` acceptance here. Do not infer their current deployment state from the production receipt.
- Issue #5676 remains an owner decision about whether the bounded PG nightly is standalone or also candidate-bound pre-promotion evidence. This plan does not decide it.

## Target policy

### PR merge

- Require the existing CI Smoke and normal review/governance checks for the exact PR head.
- Do not wait for nightly, live host acceptance, or a dev/test deployment to merge.
- Keep PR workflows isolated from deployment credentials and trusted deployment executors. A PR must not gain deploy authority by changing workflow code.

### Post-merge dev/test

1. Build once from a specific `main` commit and record both the source SHA and immutable image digest.
2. Deploy that exact image to `dev` using a trusted, narrowly scoped executor and a channel-specific deployment lock.
3. Require a short post-deploy health and `/version` check that proves the running source SHA and image identity. On success, make that exact image eligible for `test`.
4. Deploy the same digest—not a rebuild—to `test`, with its own lock and health/version check.
5. Record per-channel attempt, candidate SHA/digest, result, and failure reference. Keep deployment secrets and host-local credentials outside Git and outside PR jobs.

Serialize deployments independently per channel. Do not allow overlapping mutations of one channel. A newer main commit may supersede an older queued candidate before its deployment starts; once a deployment mutation starts, let it reach a recorded terminal result. A candidate may enter `test` only after its own `dev` check passes.

GitHub Actions environments can scope deployment approvals/secrets by branch, and workflow concurrency can serialize work. Apply those controls if supported by repository policy, but first select and qualify the actual private executor. Do not assume a long-lived self-hosted runner is safe: keep untrusted PR jobs away from it and review its isolation and persistence before use. See [GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments), [deployment concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments), and [self-hosted runner security](https://docs.github.com/en/actions/reference/security/secure-use).

### Failure and recovery policy

| Failure | Immediate response | Candidate eligibility |
| --- | --- | --- |
| Image build/publish or digest verification fails | Stop before deployment; attach failure to the exact SHA and create/update actionable CI follow-up. | Not eligible for dev/test. |
| Dev preflight, deploy, health, or version check fails | Stop before test; preserve the full receipt and create/update an actionable issue. Do not silently retry against a different SHA. | That SHA cannot advance to test or production. A later SHA may proceed independently after its own dev check. |
| Test deploy, health, or version check fails | Record the exact failed candidate and stop its promotion path; create/update an actionable issue. | Not eligible for production until resolved and re-verified. A later candidate can proceed independently through dev/test. |
| Nightly fails | Bind the failure to the tested SHA and channel, publish actionable test/run evidence, and create/update an issue. Do not block an already-merged PR or newer candidates from entering dev/test. | The failing SHA is not eligible for production promotion until the failure is resolved and required evidence is green. |

No automated database rollback is part of this plan. A failed health check must not imply that restoring an older image restores database state. Keep the channel failure visible and use the existing operator-governed recovery/rollback procedure; any future automatic recovery needs its own migration-aware contract and acceptance evidence.

## Preconditions and delivery sequence

1. **Refresh deployment evidence.** Obtain fresh, redaction-safe `dev` and `test` channel topology, executor, image-pin, health/version, and recovery receipts from the authorized runtime owner. The dated Builder Vault summaries and #2698 production receipt do not substitute for this evidence.
2. **Select one trusted executor.** Confirm its identity, private reachability, least privilege, branch/environment restrictions, channel locking, audit output, and separation from untrusted PR code. Do not add personal or long-lived workstation credentials to GitHub.
3. **Add the post-merge workflow.** Trigger only from trusted main/image-build evidence, bind the immutable digest, and deploy `dev` then `test` with separate environment/concurrency controls. Preserve one deployment authority per channel; reconcile any existing operator path before enabling the workflow.
4. **Add failure-path verification.** Prove image mismatch refusal, dev failure stopping test, test failure stopping production eligibility, nightly SHA attribution, lock contention, newer-candidate supersession before mutation, and secret-free receipts.
5. **Pilot and measure.** Enable the path for a bounded candidate set, keep production manual, and review elapsed PR-open-to-merge time plus post-merge failure/repair time after ten merged candidates. Adjust only with observed evidence.

## Acceptance

- Required PR merge checks do not depend on nightly or dev/test live-host execution.
- Each post-merge deployment names one exact source SHA and image digest; `test` uses the digest that passed `dev`.
- Concurrent runs cannot mutate the same channel at once, and every started attempt ends with an attributable receipt.
- A failing SHA cannot silently proceed to the next channel or production; newer SHAs are not globally blocked by an older candidate's failure.
- Nightly failure yields a durable actionable issue linked to its exact run/SHA without reopening or blocking the merged PR.
- No credentials, private endpoints, or personal host paths enter repository files or public receipts.
- Production promotion, #5676's PG policy decision, Model Access Router gates, and owner/live acceptance remain independently governed.

## Non-goals

- Changing required PR correctness checks or weakening branch protection by inference.
- Automatically rolling back databases or promoting to production.
- Claiming TARS/Mac mini executor qualification, live `dev`/`test` residency, or deployment success without fresh receipts.
- Deciding #5676 or bypassing unrelated MARR, BuilderOps, or human-authorization gates.
