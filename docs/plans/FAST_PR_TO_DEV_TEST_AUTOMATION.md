State: Delivery plan with verified native PostgreSQL coverage handoff; permanent controller activation and measurement are tracked separately.
Doc role: Plan.
Authority: Proposes the post-merge Product Runtime `dev` → `test` automation boundary. `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` remains the deployment-mechanics owner; `docs/TESTING.md` remains the testing-gate owner; `docs/RELEASE_CHANNELS/README.md` remains the promotion-authority owner.
Temporal class: operational
Review cadence: before implementation and after the first ten merged candidates
Source of truth: repository workflows/scripts plus fresh, redaction-safe runtime receipts
Last reviewed: 2026-10-11
Last verified against: #5922, #5932 and #5950; `.github/workflows/postmerge-dev-test.yml`, `scripts/postmerge_dev_test.py`, `scripts/install_postmerge_controller.py`, native DeployPlan/RPC and digest-pin tests; [actual same-candidate native DEV/TEST receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5675#issuecomment-6105991683) under #5675

# Fast PR-to-merge with automatic dev/test delivery

## Intent and boundary

Reduce PR-to-merge time by keeping broad, slow, or live-host evidence out of the required PR merge path, while using isolated `dev` and `test` channels for fast post-merge feedback. Actual both-stage native coverage is recorded on #5675; permanent controller activation and the ten-candidate measurement are recorded separately.

The intended flow is:

`PR required smoke → merge → build one immutable image for the exact main SHA → deploy to dev → health/version and isolated PG verification → deploy that same image to test → equivalent verification`

Production remains on the separately governed promotion path. Neither a green dev/test deployment nor this plan grants production authority.

## Verified starting point

- `.github/workflows/ci-smoke.yaml` is the PR fast path. Docs-only changes have a lighter selected path; source/integration changes retain their required smoke checks.
- `.github/workflows/integration-nightly.yaml` runs the broad scheduled/on-demand suite, including its bounded PostgreSQL lane. It is not the PR merge gate and does not deploy or roll back a channel.
- `.github/workflows/app-image-build.yml` builds and publishes an image identified by source SHA and verifies image/runtime identity on its current main path.
- #5922 adds credential-free source-build admission in Actions and private-host polling of the same authoritative image proof. The poller uses the existing native deployment boundary; Actions does not execute deployments or acquire their credentials.
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
3. Require post-deploy health and `/version` checks that prove the running source SHA and image identity, plus the isolated shared PG acceptance profile. On success, make that exact image eligible for `test`.
4. Deploy the same digest to `test`, with its own lock and equivalent health/version and isolated PG verification.
5. Record per-channel attempt, candidate SHA/digest, result, and failure reference. Keep deployment secrets and host-local credentials outside Git and outside PR jobs.

Serialize deployments independently per channel. Do not allow overlapping mutations of one channel. A newer main commit may supersede an older queued candidate before its deployment starts; once a deployment mutation starts, let it reach a recorded terminal result. A candidate may enter `test` only after its own `dev` check passes.

The selected executor is the existing private host secret controller, supervised by a host-local
LaunchAgent. It polls successful `main` builds every 60 seconds and revalidates their exact proof;
the Actions workflow is a credential-free admission signal. This avoids installing a new trusted
GitHub runner alongside public PR execution. Native locks remain channel mutation authority.
Ordinary dev/test candidates need no additional manual approval. Installation and recovery mechanics
belong to `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: CI deployment automation posture`.

### Failure and recovery policy

| Failure | Immediate response | Candidate eligibility |
| --- | --- | --- |
| Image build/publish or digest verification fails | Stop before deployment; attach failure to the exact SHA and create/update actionable CI follow-up. | Not eligible for dev/test. |
| Dev preflight, deploy, health, or version check fails | Stop before test; preserve the full receipt and create/update an actionable issue. Do not silently retry against a different SHA. | That SHA cannot advance to test or production. A later SHA may proceed independently after its own dev check. |
| Test deploy, health, or version check fails | Record the exact failed candidate and stop its promotion path; create/update an actionable issue. | Not eligible for production until resolved and re-verified. A later candidate can proceed independently through dev/test. |
| Forward-only migration is found for dev or test | Classify and record the exact source-to-target migration work, then follow the ordinary non-production deployment path without a manual acknowledgement. On failure retain the compatible target under the existing recovery rules. | Classification alone does not block the automatic candidate. Automation never supplies `--ack-forward-only` or `DEPLOY_ACK_FORWARD_ONLY`; production keeps its separate target-bound acknowledgement and promotion contract. |
| Nightly fails | Bind the failure to the tested SHA and channel, publish actionable test/run evidence, and create/update an issue. Do not block an already-merged PR or newer candidates from entering dev/test. | This plan adds no production eligibility rule from a nightly result. Production remains governed by `docs/RELEASE_CHANNELS/README.md` and its required receipts. The bounded PostgreSQL nightly's role remains for the owner decision in #5676. |

No automated database rollback is part of this plan. A failed health check must not imply that restoring an older image restores database state. Keep the channel failure visible and use the existing operator-governed recovery/rollback procedure; any future automatic recovery needs its own migration-aware contract and acceptance evidence.

## Preconditions and delivery sequence

1. **Refresh deployment evidence.** Obtain fresh, redaction-safe `dev` and `test` channel topology, executor, image-pin, health/version, and recovery receipts from the authorized runtime owner. The dated Builder Vault summaries and #2698 production receipt do not substitute for this evidence.
2. **Install the existing private host executor.** #5922 delivers the host-local LaunchAgent installer, exact build/artifact admission and native dev → test driver. Retain a clean reviewed-main tooling checkout and its working dependencies, and install the updated native VM runtime once through the existing installer. Later automatic candidates fetch their missing exact-SHA Git objects under the native VM lock without moving the retained checkout or supplying credentials. Reuse existing private reachability and credentials; GitHub receives none of the deployment credentials. Coordinate the live owner of a frozen acceptance run before loading the unit; this is writer coordination, not a new approval gate.
3. **Qualify migration and deployment behavior.** Automatic dev/test deployment follows the ordinary non-production migration policy: classify forward-only work without adding a manual acknowledgement, preserve exact pending-request validation and retain the compatible target on migration failure. SHA plus digest remain bound in the existing request journal, pin, Compose reference and fleet verification. Run the live same-digest dev/test path after current channel acceptance permits a new candidate. Production keeps its existing target-bound token and separate promotion authority.
4. **Verify failure paths and coverage handoff.** #5922 covers artifact mismatch, dev failure preventing test, supersession before mutation, checkpoint/lock behavior, native recovery and immutable image IDs deterministically. Live functional tests and failure repair remain on #5675. Child #5932 is merged in PR #5939 and supplies the isolated scratch-PG profile inside the existing native verification phase. Its repository implementation preserves the retained selectors and watchdog; the accepted full controller flow has now committed equivalent DEV/TEST profiles at one admitted immutable image, each 547/547 selected tests with exact owned cleanup. The dated #5675 receipt establishes PostgreSQL PR coverage retirement; non-PG PR and bounded nightly checks remain. An interrupted native operation must produce matching terminal evidence before continuation; a normal failed candidate does not add a global veto on later candidates.
5. **Enable and measure.** Enable the path for ordinary merged main candidates, keep production manual, and review elapsed PR-open-to-merge time plus post-merge failure/repair time after ten merged candidates. Measurement is follow-up and does not gate activation or candidate delivery. Adjust only with observed evidence.

## Acceptance

- Required PR merge checks do not depend on nightly or dev/test live-host execution.
- Each post-merge deployment names one exact source SHA and image digest; `test` uses the digest that passed `dev`.
- Concurrent runs cannot mutate the same channel at once, and every started attempt ends with an attributable receipt.
- A failed build, deployment, or channel health/version gate cannot silently advance its candidate; newer SHAs are not globally blocked by an older candidate's failure.
- Automatic dev/test forward-only migrations follow the ordinary non-production policy without operator acknowledgement; classification, exact pending-request validation and failure target retention remain enforced. Production keeps its existing target-bound acknowledgement.
- Nightly failure yields a durable actionable issue linked to its exact run/SHA without reopening or blocking the merged PR, and does not create a production eligibility rule in this plan.
- No credentials, private endpoints, or personal host paths enter repository files or public receipts.
- Production promotion, #5676's PG policy decision, Model Access Router gates, and owner/live acceptance remain independently governed.

## Non-goals

- Changing required PR correctness checks or weakening branch protection by inference.
- Automatically rolling back databases or promoting to production.
- Claiming private executor qualification, live `dev`/`test` residency, or deployment success without fresh receipts.
- Deciding #5676 or bypassing unrelated MARR, BuilderOps, or human-authorization gates.
