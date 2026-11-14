State: Development reference. Not an auto-loaded instruction file.
# Development Workflow

Use this document for the builder-agent working loop and validation expectations after reading `AGENTS.md`.

For normal PR delivery, read [`PR_HOT_PATH.md`](PR_HOT_PATH.md) first. It is the default short path for routine PR work. Read [`PR_ESCALATION_PATHS.md`](PR_ESCALATION_PATHS.md) only when the hot-path classification finds a risk trigger, stale SHA, blocking review feedback, CI failure, or another escalation condition.

This document applies to development-time contributors. It does not define runtime/system-agent behavior.

## Working loop

For non-trivial changes:

1. Identify the owning document via `docs/DOCS_INDEX.md`.
2. Read the owner doc before changing code or neighboring docs.
3. Confirm the planning chain for the work: human flow/scenario -> feature specification and capability contracts -> appropriately scoped parent or slice issue -> code/PR -> slice verification -> merge -> feature/capability/contract validation -> acceptance -> owner-doc promotion.
4. Add or update tests for the intended change when the work is not docs-only.
5. Implement the smallest change that fits the documented architecture.
6. Update owner docs in the same change when behavior, contracts, or architecture changed.
7. Run the relevant validation commands and record any gaps.

For larger `type:bug` issue sets, apply `AGENTS.md :: Transition-period bug-delivery policy`: a
minimal coordinator dispatches each bug to its own end-to-end Codex task/session and isolated
worktree, with serial implementation as the default. This is Builder System transition guidance,
not Product/Runtime behavior or evidence of a shipped deterministic orchestrator.

## OpenHands factory owner trial

The local OpenHands delivery entry point is an experimental, explicitly authorized single-Issue
path. It does not establish factory qualification or authorize merge or release. Install the pinned
components with `scripts/setup_openhands_factory.sh /absolute/install/root /absolute/worktree/root`;
the second argument is optional and defaults to `worktrees` under the install root. `uv`, Node and Codex must be
on `PATH`, with Codex CLI 0.167.0 and the existing ChatGPT subscription login. Start fetches
`origin/main` and verifies it against the remote's current default-branch SHA before preparing a
worktree. It fails if the network is unavailable, the default branch is not `main`, the SHAs
do not match, or updating the tracking ref would not be a fast-forward; it does not use the
factory checkout's `HEAD` as the base.

The installer also installs the Canvas launcher at the reviewed #6602 revision and checks its
SHA-256; if that Git object is absent locally it retrieves the same pinned file from GitHub. An
existing launcher with different contents is left in place and setup stops for inspection. The
OpenHands bootstrap builds its pinned `func-timeout` source in a separate filesystem sandbox without
the host home or Git metadata; the remaining bootstrap packages use wheels. Package tools use a
private setup home. The test lock below is independent of this bootstrap.

The installer creates a private state directory and a short owner entry point bound to this factory
checkout and the chosen roots. The experimental Canvas route uses a dedicated model-free owner
service, independent of a worker Issue or its conversation. Start or restore it with:

```sh
/absolute/install/root/bin/openhands owner --ui-action start --port 8766 --ui-port 3001
```

Open the returned Canvas URL. In **Builder control**, enter `start #456` to authorize that one
Issue and its draft PR, or `status #456`, `cancel #456`, `resume #456`, or `stop #456` for the
recorded run. This conversation is a command bridge and makes no model request; the task itself
still uses the guarded native Codex session. No backlog scanner is enabled. The control session
uses a model-free native ACP profile. A browser connecting to this Canvas origin for the first time
may ask for the local session key from `<install-root>/runs/owner/server/session-api-key`; retain it
privately. This is one-time browser setup, not a model or provider credential.
The control session
is a trial route, not an adopted default. Use `owner --ui-action status` and
`owner --ui-action stop` for that service; restarting it uses its recorded backend and Canvas ports and retained
conversation. The owner service refuses native Codex launches; tasks start on their own worker backend.
The older `control --issue <number>` command opens the same independent owner conversation once the
owner has been set up; it does not start that Issue. It uses the recorded owner UI port. If the owner
has not been set up, start it with `owner --ui-action start`; an explicit `--ui-port` can avoid a port
already used by a worker Canvas. Prior worker-hosted control records are preserved and are not reattached
or deleted.
A new start or resume is refused while an earlier worker backend is running or its delivery is
unresolved. After publication the watcher stops the finished worker backend; published worker sessions
cannot be restarted. Existing live older workers must be inspected and stopped before another admission.
These mechanisms do not yet establish delegated-process cancellation. Roll back to the existing CLI
if needed; retain recorded sessions and draft PRs.

The CLI remains available directly. Replace the example paths and explicitly authorized Issue:

```sh
/absolute/install/root/bin/openhands start --issue 123 --port 8765
```

Use the same entry point with `status`, `cancel`, `resume`, or `stop` in place of `start`. The `status`
command also reads current GitHub checks for a recorded draft when its PR and commit identity can be
verified. This is a point-in-time observation, not a merge decision; unavailable or changed readback
is reported as unknown. It does not restart the worker or watcher.
The owner control process uses the existing GitHub CLI login in its home directory; it does not
forward GitHub token or configuration environment variables. A login available only through those
variables can work in a direct CLI but remains unavailable in the owner view.
The entry point derives its pinned ACP and isolated service configuration; model selection stays on
`gpt-6.1-terra` with subscription authentication, with no provider or model fallback. `cancel`
interrupts the conversation; it does not establish that delegated processes have stopped. If the
run is still admitting input, cancellation can return without sending an interrupt: use `status`
and retry when admission finishes. For a
previously interrupted delivery, `resume` currently refuses continuation because native and
delegated execution cannot yet be proven stopped. `status` reports available task-scoped observations
of the recorded service, worktree and publication, with unknowns retained; a paused conversation is
not proof that the underlying work has ended. New worker backends refuse further delivery inputs
after interruption and prove possession of the recorded session key on the same connection before
the factory sends it. This is
a partial mitigation, not a verified recovery procedure, and does not retrofit a backend that is
already running. Event-history reads and new worker event connections are also refused after
interruption because OpenHands can reload an unloaded runtime while handling them. Preserve the
recorded state and inspect it rather than replaying the task.
For a legacy worker without the identity challenge, the factory will not send its session key to
an unverified listener. Inspect the exact recorded service with
`python3 -m app.builderops.openhands_service --state-dir <recorded-run>/server status`; an explicit
legacy shutdown can use the same command with `stop`. This stops only the identity-checked service
process. It does not prove native or delegated work has stopped, so retain the run as unresolved
and do not start conflicting work solely because the service stopped.
For a
new run, `start` also authorizes a draft PR and requests a detached, single-run host watcher. Test
targets use the separately prepared, hash-locked test environment on macOS arm64 with Python 3.12.
Setup downloads only hash-verified binary wheels, then installs and checks them without network access.
Before admission the factory checks the default branch's runtime project dependencies and the two
requirements files against that lock;
uncovered dependencies stop the task before claim. An interrupted preparation is retained for inspection,
not silently replaced. The lock is specific to this host platform and does not resolve new dependencies.
It does not install the optional `dev` or `browser` extras from `pyproject.toml`; tasks needing
packages outside the two locked requirements files need a separately prepared environment.
Older recorded runs retain their original test interpreter. The
worker is instructed to leave a private ignored `.codex-tmp/openhands-finish.json` with its proposed
title, body fields, risk classification and exact changed paths. After observing the finished
conversation and children, the watcher checks the claim, branch/worktree gate, handoff and actual
change set, commits the scoped changes locally with hooks and signing disabled, and invokes the
existing `finish` verification, independent review and draft publication path. The review assesses
the declared risk against the actual change. Worker claims are not test or review evidence.

For one actionable test failure or structured review finding, the watcher can send bounded actual
feedback to the same recorded conversation. The worker updates the private handoff with only the
repair paths, which must be a subset of the originally recorded paths. It must preserve the Issue's
exclusions and existing behavior outside the authorized fix, choose the smallest in-scope fix,
and leave a required contract expansion unresolved. Review and repair assess the Issue's acceptance
examples and regressions without making unchanged, out-of-scope improvements blockers by themselves.
After checking the message,
session and finished conversation, the watcher commits the additive repair through the same gates
and reruns verification and independent review. A second failure, an unavailable or non-actionable
review, unresolved test targets, or an out-of-scope repair stops for inspection. If message delivery
is ambiguous, the recorded `repair_sending` phase is pending and is never automatically resent.

For a canonical document-writeback Verify target, `finish` requires the target to be a changed
regular file in the exact candidate and an explicit semantic pass from the independent reviewer.
The file or heading alone is not a pass; unsupported targets and uncertain assessments remain
unresolved. Review evidence is stored in private host state outside the worker workspace. As with
the existing publication path, manually supplied host evidence is trusted and is not authenticated
against a malicious user on the same host. Automatic repair of document-bearing review findings is
not yet supported.

`status` includes the watcher's `running`, `finished`, `pending` or `failed` state; a launch request
alone is not proof it started. Status reads the atomically retained delivery state without waiting
for a long-running review; if that state changes during live readback it reports the new state and
asks for a retry. A healthy active task has no fixed delivery deadline. The watcher
retries an unavailable conversation readback at most three times. It independently checks the live
Issue and recorded claim and renews the same unexpired dispatcher lease and worktree registration
while watching, testing, reviewing and publishing. Renewal runs at most 30 minutes apart and sooner
when the observed remaining lease time requires it. Dispatcher-backed renewal uses the existing
holder heartbeat and checks its result against the recorded claim; a label-only fallback has no
dispatcher lease and keeps its existing weaker
coordination semantics. The heartbeat status and expiry are visible through `status`; a failed or
uncertain renewal stops subsequent guarded commands and leaves the run pending. An effect already
in flight requires the existing readback and reconciliation. A lost process or uncertain
publication is retained as pending. After inspection, `watch` with the same Issue and roots can
restart a stopped watcher; a kernel lock prevents concurrent watcher effects, and publication uses the existing
reconciliation. An interruption while staging or committing is always pending for manual index and
branch inspection and is not automatically repeated. Older runs without the recorded automatic
authorization remain manual. The watcher does not restart itself after a host reboot; an expired
dispatcher lease cannot be revived by its heartbeat. Preserve state and reconcile an interrupted or uncertain
start before retrying.

After publishing, the watcher waits for GitHub checks and independently re-reads the draft PR and
its current head. It reports a failure as failed, a genuinely incomplete or unavailable result as
pending, and success only when the recorded current head has passed the check wait. It does not
yet automatically diagnose or repair a CI-only failure. Enter `watch #456` in the control
conversation to recheck a pending or rerun CI result while the original delivery lease is active;
this reuses the same draft instead of publishing another one. After lease expiry, inspect current
checks directly on the draft PR. A recorded passing result includes the head it covered and is not
a live status for a subsequently changed head.

`stop` first checks that the recorded conversation is finished or has been interrupted through
`cancel`, then records the existing ACP session and service settings privately and stops the
recorded Canvas (if present) and backend while retaining session data. It does not verify
delegated-process cancellation. To restore that backend for conversation readback or publication,
use `start` again with the same Issue, installation, repository and roots. It reuses the recorded
workspace, port, key and session; it does not claim the Issue again or resume an agent turn.
`resume` currently refuses an interrupted turn: paused conversation status alone does not establish
that the earlier native command and delegated work have stopped or that their effects are reconciled.
Keep the recorded workspace and session for inspection; no continuation prompt or replay is sent.
For an interrupted run, `status` reports a point-in-time view of visible descendants, the worktree
and matching draft PRs where available. The process view can omit detached work and does not prove
termination; conversation status, an empty process snapshot and a clean worktree are not recovery
approval. GitHub or local readback failures remain unknown. The retained recovery settings contain
a sensitive ACP session identifier and must remain private.

For a finished conversation on a clean committed worktree, use `verify` with the same Issue and
roots. It rereads the recorded Issue contract and runs concrete `tests/...py` pytest targets in the
retained Codex sandbox profile, capturing output and exit status in a private verification
directory. The JSON result binds the evidence to `HEAD` and lists passing, failing and unresolved
targets. Canonical document-writeback targets remain pending independent review; other document
anchors, arbitrary commands and unmapped targets remain unresolved. Standalone `verify` exits
nonzero unless verification passes, including when document review is pending. This is test
evidence, not independent review or publication authority. Some tests need facilities excluded by the
sandbox, such as network access; their actual results remain visible in the private logs.

Use `review` with the same Issue and roots to run an independent native Codex review of the
finished, committed candidate. The separate reviewer uses the guarded ChatGPT/Terra preflight and
a read-only workspace profile; it records the structured verdict and actual response privately,
bound to the exact candidate SHA. Refusals, failures, changed candidates and ambiguous output are
unresolved. The separate `verify` and `review` commands remain available for diagnosis.

For an explicitly authorized publication, `finish` runs both steps for the finished, clean committed
candidate, assembles their exact-head evidence and invokes the existing `publish-full` draft workflow:

```sh
/absolute/install/root/bin/openhands finish --issue 123 --authorize-publication \
  --title 'Describe the change' --body-input-json /absolute/host/pr-body-inputs.json \
  --risk-surface auth
```

Provide the existing PR body generator's implementation-lane JSON inputs, including its SBS impact,
owner-doc and BuilderOps fields and `final_review_rounds: 1`. The recorded claim supplies the Issue
and pickup receipt. Supply every applicable `--risk-surface`; omit it when no listed surface applies.
The independent reviewer checks the risk assessment even when no surfaces are declared. This route
still uses the existing review and publication gates for the candidate's actual paths and risks.
When the existing review gate requires a workflow review receipt, pass its host-side path with
`--workflow-review-receipt`. Finish derives the candidate paths from committed history, preserves
its private assembled receipt, and delegates claim, risk, issue, draft, check readback and ambiguous
effect reconciliation to the existing publisher. A retry of an already recorded `publish-full`
publication uses its original private host-side evidence, including when it was created outside
`finish`; changed inputs or uncertain effects may require reconciliation. Failed or unresolved
tests or review refuse publication. This does not establish passing CI, qualification,
or completion of review-repair and mechanism-convergence obligations.

The separate manual `finish` route still requires the operator to supply title, body inputs and risk
classification. Automatic runs stop for malformed or missing handoffs, unsupported Verify targets,
missing special review evidence, repeated or non-actionable failures, and uncertain effects.
Finish does not assemble the stateful-fallback matrix; use the existing full publication
route when that exception is required. Host-reboot recovery remains manual, so this is not yet
unattended end to end.

The launcher reads the applicable host and planned-worktree Codex TOML configuration to disable
inherited MCP servers and plugins by name; it does not copy their configuration values. The service
uses the `HOME`-based Codex configuration, and its effective-configuration preflight still refuses
an enabled external tool or an unverified subscription/model before a worker turn. If configuration
cannot be inspected, start fails and the operator must resolve the local configuration first.

For a new run, the launcher also inspects the installed Python interpreter's `_sqlite3` and `_ssl`
extensions. It uses `otool` on macOS or `ldd` on Linux to identify linked SQLite, SSL and crypto
libraries, and grants their non-system library directories read-only access in the worker, verifier
and reviewer profiles. Both the linked directory and its resolved directory are included when they
differ; system libraries remain under the minimal profile. Missing inspection tools, unresolved
library paths or inaccessible dependencies fail start rather than broadening access. For a macOS
Python framework in a Homebrew `Cellar`, the profile also includes that Python version's package
directory and the same Homebrew prefix's `opt` directory when present, for interpreter and library
symlink traversal. Other Python layouts do not receive those Homebrew traversal roots. A stopped
run retains its original settings and does not silently gain new sandbox roots on restart.
The worker, test verifier and independent reviewer run Git with global and system configuration
disabled; repository-local Git configuration remains in effect.

For the owner interface, install the independently reviewed `scripts/openhands_canvas.py` from
the #6602 candidate as `/absolute/install/root/bin/openhands_canvas.py`, retaining its source and
commit receipt. #6602 is a draft and this launcher is not yet merged. Start the installed official
Agent Canvas against the recorded service using the same paths and Issue:

```sh
/absolute/install/root/bin/openhands ui --issue 123 --ui-port 3001 --open
```

`--open` is optional; omit it to use the returned loopback URL manually. The UI port defaults to
3001 and must differ from the backend port. Use `ui --ui-action status` or `ui --ui-action stop`
with the same Issue and roots to inspect or stop Canvas without stopping the backend. The command
passes the private session-key file path to the launcher; never print or copy its contents into
logs or PRs.

## OpenHands owner access on BOB-1

The bounded #6630 owner interface uses upstream Agent Canvas 1.37.0 at
<https://builder-system.tailcfb3a1.ts.net:9443/conversations/5f3b0e85-dbf6-4666-b650-95728a551601>.
Connect the iPad to the existing Tailscale network under the owner's personal account. On a new
browser, keep the prefilled backend URL, give it a name, leave API Key empty and select **Next**;
select **Skip for now** on agent setup. No provider key, OpenHands Cloud account or SSH is needed.
If the anonymous-analytics prompt appears, turn it off and confirm. Repeat that browser setup once
for the separate sandbox origin when first opening it.

In the existing owner conversation, send `status` (or `status #6615`). The model-free ACP bridge
reads the existing epic run-state, joins Issue, worker, branch and conversation identities, and
uses the pinned controller's exact endpoint guard for bounded live observations. Recorded next
actions can lag the active owner's latest comment; follow the linked Issue and PR #6628 for
current blockers, review, CI and delivery. Stopped/busy/unreachable observations remain unavailable;
monitoring never starts, loads or stops the existing epic workers. Native descendants are opaque.
An active or finished conversation is not accepted progress, a merged PR or completed delivery.
The ongoing #6618/#6619 owners retain their claims and workspaces.

Use `sandbox start` in the owner conversation for a separate owner scratch workspace, then follow
**Open sandbox Canvas** to <https://builder-system.tailcfb3a1.ts.net:9444>. Open the existing admitted
conversation and send the next bounded read-only/scratch task there. Browser **New Chat** creation
is refused: one controller-reserved conversation owns that checkout. The selected native engine
is Codex `gpt-6.1-terra` using the existing ChatGPT subscription, without paid API/provider fallback.
The native login directory is a single shared slot; start refuses while another worker mounts it.
Do not interrupt existing epic work to make room. Repository-wide automatic delivery, issue pickup,
review/repair/merge and control of the existing epic workers remain with their owning workflows;
this sandbox is not a second factory coordinator.

Within a live sandbox conversation, **Stop** interrupts it; a subsequent message can continue it.
That UI state does not prove native descendants stopped. For a verified contained stop, return to
the owner conversation and send `sandbox stop`. The existing controller checks actual container
absence and retains the workspace/history/checkpoint. `sandbox status` reads the sandbox state.
A later explicit `sandbox start` runs the existing takeover/preservation checks and creates a new
OpenHands conversation; it does not replay the last task. Uncertain creation is reconciled by its
reserved ID; unavailable or failed engine execution must not be presented as ready.

The new user units are `openhands-owner-backend` (model-free server 1.62.0, loopback 18812),
`openhands-owner-canvas` (static UI, loopback 18821), and `openhands-owner-primary-gateway` /
`openhands-owner-sandbox-gateway` (loopback 18820 / 18822). Their private configuration, pinned Node
24.22.2 executable and copied Canvas assets live under `~/epic-sandbox/owner-access/`. Tailscale
Serve adds only HTTPS 9443 and 9444; the previous 443/8443 routes remain intact. The gateway admits
only the configured owner identity from the loopback Serve hop, checks browser Origin, injects
session keys only upstream and exposes no generic host Bash/file/secret or settings-write API.
The sole settings mutation supported is disabling anonymous analytics. This follows
[Tailscale Serve identity-header guidance](https://tailscale.com/docs/features/tailscale-serve#identity-headers).
The owner backend has its own fixed custom ACP profile and conversation, separate from trusted
control 18811 and Automation 18810; neither existing service is proxied or restarted.

The sandbox is epic/workspace 6630, worker `owner-sandbox`, with ports 18840–18847, separate from
existing epic work. Owner commands call the frozen `9fa8001484e5` controller with the already
approved native image `epic-worker@sha256:3c3c2472b35ea3ccb0df57df7cc9d2303f582dcb2987b259124c9df946d56644`.
The frozen CLI's upstream 1.60.1 default image is insufficient for this native path; the wrapper
passes the reviewed image and the existing approved `epicws-6615-egress-20261114` network explicitly. The old default `epicws` bridge cannot reach the provider; a local CLI login-status result alone does not prove working provider access. The recovery `runner/current` remains `c68dd18db4dc`.
No active controller/image was hot-replaced. Runtime evidence and per-capability acceptance are
recorded on #6630; physical iPad use remains unverified until the owner opens the URL and sends
`status` from Safari with Tailscale connected.

## Persistent epic workspace on TARS (experimental)

Epic #6615 runs a persistent, per-epic workspace on BOB-1 (VM 102, guest `builder-system`). It is a
bootstrap baseline (#6616), not a qualified factory. The trusted controller is
`app/builderops/epic_workspace.py`, installed read-only as a pinned release under
`~ygg/epic-sandbox/runner/<sha>/` with `current` pointing at the active release. Its only entry
point is `~ygg/epic-sandbox/bin/epicws`, which fixes the workspace root to
`~ygg/epic-sandbox/workspaces` and the engine to the default Docker engine. Neither path is mounted
into a worker. The dedicated BuilderOps engine and its services are not used.

The new PR evidence adapter emits repository-specific requests; it is not yet wired to automatic
merge. Since 2026-11-13 (owner bootstrap receipt on #6618, comment 6840611036) the existing
upstream Automation definition `35aca793-3940-48be-8139-f8513d589b8c` and its same SQLite state run
under two enabled user units of the lingering `ygg` user: `epicws-6615-control.service` (upstream
agent-server, SDK and tools 1.62.0; trusted control API on loopback port 18811) and
`epicws-6615-automation.service` (Automation 1.30.1 with its required SDK 1.60.1 in a separate
environment, loopback port 18810; server 1.62 and SDK 1.60.1 cannot share one environment). The former
Docker automation container (image `sha256:b36bb669cf50846c3fa6c5157397dd47526721334a7a544b7df449d9b62f523d`)
is stopped and preserved with its original environment; its state was backed up to
`~/epic-sandbox/automation/state-pre-native-20261113T005031Z`. The definition's `*/5` cron runs the
already-merged `8fe1df054` read-only contract and review collector from its uploaded tarball
(`python3 collector.py`); a manual run and successive cron runs completed (comment 6841477071). The
current owner continuation (comment 6842687488) reports both units running, the `c68` recovery
controller unchanged and only these read-only scans active: completion, review, repair, merge and the
other delivery effects of the source candidate below are not activated. Status: `ssh bob-1-builder-system
'python3 ~/epic-sandbox/automation/status.py'`.

`python -m app.builderops.openhands_pr_observation` is the read-only, unauthenticated collector for that
adapter: it reads open PRs, reviews and the exactly-one `Governing-Issue` Issue through bounded public
REST calls to the pinned repository and prints a JSON report. It writes no run state and does not call
`intake`; a trusted caller decides separately whether to pass the observations on. Failures, closed
PRs, an incomplete inventory, oversize or too deeply nested responses and HTTP refusals (including the
unauthenticated limit of about 60 requests per hour, roughly 3 per open PR) are reported explicitly as
an incomplete scan with exit code 1. The transport timeout applies per socket operation and the
120-second deadline is only checked between requests, so a scan is not a hard wall-clock bound.
Owner, route, review, Verify, CI, closure and effect evidence have no trusted source there and stay
`unknown`, so every PR waits and nothing can be reserved from this report. The standalone CLI never
repeats a scan. The scheduled trusted wrapper is distinct: it calls the collector core through
authenticated host `gh` GET reads restricted to the same path allowlist, so the unauthenticated rate
limit above applies only to the standalone CLI.

The source candidate also has a one-shot host controller, `python -m
app.builderops.openhands_pr_cycle --once --root <workspace-root> --epic 6615 --config
<admission.json>`. Its controller-owned JSON contains an `admissions` array, initially empty;
one trial entry names `number`, exact `head_sha`, dedicated pre-existing `worker`, `engine`,
`model`, `native_session_owned: true`, `claimant`, `lease_id`, `session`, `owner_worktree`,
`lifecycle_repo`, and explicit pytest
`verify_targets`, and `test_venv`, an absolute host path to a secret-free test environment. The
controller configuration must be owned by the controller and protected from other writers. The
venv path and its contents must satisfy the ownership, mode, symlink and credential-shaped filename
preflight; that filename check cannot prove arbitrary file contents are secret-free. It must be a
controller-owned path outside the configured model workspace root (`--root`) and must not be that root
or one of its ancestors: a venv in a worker checkout or home could fake passing tests, and an
enclosing directory would mount the whole workspace. An agent-local test venv is never admissible as
the independent verifier environment. A venv's Python
symlink may point to the supported system Python path in the pinned container. The source reads the host GitHub identity, dispatcher claim and verification
history, and uses the existing OpenHands lifecycle and a separate credential-free test container.
That container mounts the configured host venv read-only at `/opt/pr-cycle-venv` and refuses to run tests
when its in-container interpreter and pytest preflight fails. The source includes guarded native
merge and PR-specific post-merge continuation. Review evidence binds the observed diff, exact closing
contracts and check configuration; every closing criterion needs a review assessment. The native
metadata reader connects the exact retained OpenHands conversation and live ACP session to that
session's bounded Codex or Claude log, retaining only model, effort, timestamps and session identities.
It requires the observed model to match the selected model; a Codex effort must be `high` or stronger
(`xhigh`, `max`, `ultra`) and equal the API-selected `current_effort`. A session keeps one effort; a
supported escalation starts a new conversation rather than changing effort mid-task. These are
native-provided observations, not tamper-proof attestation. Missing, mixed or mismatched observations
stop the review. Subscription authentication also requires the native login check; no model call is
needed for this metadata read.

`lifecycle_repo` is an absolute, controller-owned host checkout of the existing worktree lifecycle
registry, outside every model workspace; it must expose the candidate's actual registered worktree,
branch, session and generation. The controller reads that authority before binding it to the current
coordination record. It refuses missing, expired, contradictory or model-controlled registrations.
Admission fields alone are not current ownership proof. The default authority route requires a locally
verifiable dispatcher claim; a claim on another host is not proof in this controller. For a genuinely unavailable dispatcher, the existing pickup wrapper and
closure degraded-coordination reader provide the GitHub receipt route. To select it, the admission
supplies `coordination_mode: github-label-only-fallback`, `owner_worktree`, `claimant`, `session`,
`fallback_reason`, and `coordination_evidence` (`github-comment:<id>`). The receipt must match the
live PR branch and exact owner worktree as well as the other caller fields. Any existing remote lease
and worktree ownership must first be transferred and read back through their normal recovery procedure.
A fallback receipt must not be fabricated or used to bypass an available dispatcher. The native
controller binds the active registry owner to the unique current dispatcher claim event's Builder
`session`; an ACP engine session is execution evidence and does not own the claim. The pickup wrapper
passes that Builder session and a unique attempt identity into the claim transaction, then reads back
the task, lease and exact event. A lost reply is reconciled from that attempt without a second claim
or an unfenced release. Native claims without a bound session refuse. A rightful unchanged legacy
owner may establish a bound claim through a fresh normal pickup when the registry proves that owner
was continuously registered before the old release; a new claim cannot prove an earlier
unknown transfer. Use the existing owner or maintenance route to re-establish missing predecessor
authority and perform the normal handoff.

A changed Builder session requires the existing authenticated handoff. Dispatcher events identify
the latest session change and its predecessor, even when the current session subsequently reclaims
its own expired lease. An atomic `release --expected-lease-id <observed-id>` fences the predecessor
release and pickup cleanup; same-agent stale takeover is only a self-resume when the old claim event
and live registry establish the same Builder session. The registry retains the branch's last ended
owner (released, completed or merely expired) with its path, branch, generation, continuous-validity
window and transfer anchor across re-registration or a proven path move. Only a release records a
release time: an expired or completed owner, including one replaced when an earlier session
returns, is never a handoff predecessor and needs owner or maintenance reconciliation. Equally
recent ended registrations cannot establish their order, even for the same session, and require
reconciliation. A heartbeat after expiry begins a new window; it does not fill the gap. The receipt must be
written during both the predecessor's live claim window (including recorded heartbeats) and its
continuous registration window. Equal dispatcher timestamps do not establish order. GitHub comments
have second precision, so the entire receipt second must precede the release or successor pickup;
the acknowledgment must follow successor registration and the candidate readbacks while the
successor's pickup lease remains live. A later same-session reclaim preserves that handoff. The pending and
acknowledged comments must carry identical receipt fields apart from the acknowledgment and must not
show edits. Same-second edits cannot be distinguished by GitHub timestamps. The ordering relies on
trusted GitHub and controller clocks and authorized actors; predecessor stop and live readback remain
separate obligations.

A historical fallback origin must identify an actual authenticated Issue pickup comment with the
matching Issue, owner, session, path, branch and reason, without requiring the dispatcher still to be
unavailable. When a same-session predecessor has multiple matching pickups, both handoff comments
carry `predecessor_pickup_comment_id` naming its uniquely latest matching comment; tied or newer
conflicting pickups remain unresolved. From the original claim through the current owner, each
authenticated pickup must be the original receipt, the successor pickup bound to a valid handoff,
or match the agent, session, branch and worktree of the proven owner for a complete GitHub comment
second within that registration interval. Dispatcher claims
must match the proven owner or the handoff's successor claim. A later pickup, mode change, return to
an earlier session or subsequent handoff cannot resolve a competing claimant by itself. Review
preparation and native authority both check that history; missing or conflicting evidence requires
the existing owner or maintenance reconciliation. For dispatcher-to-fallback across hosts, the receiving host authenticates its actual
current fallback comment and the existing handoff's predecessor release/readback; it does not claim
to inspect a nonlocal dispatcher database. That remote readback is the immediate predecessor: the
receiving host's own last registry owner is older history only if it was released before the remote
claim, the transfer proof does not record it as the predecessor, and unreleased or overlapping local
history refuses. The coordinator must establish the remote predecessor's
stop, exact lease release and worktree release before acknowledging. For this cross-host case, both
handoff comments also carry the same `predecessor_registration` mapping (`path`, `owner`, `branch`,
`generation`, `status: active`, numeric `observed_at` and `expires_at`) and
`predecessor_dispatcher` mapping (`task_id`, `lease_id`, `holder`, Builder `session`, and RFC3339
`claimed_at`, `observed_at` and `expires_at`, plus `history_reconciled: true` only after the
coordinator has reconciled earlier transfers). These are the trusted coordinator's actual remote
readbacks before the receipt; the observations must remain live for the full receipt second. The
acknowledgment's `prior_coordination_release.released_at` is the RFC3339 release event time, and
`prior_worktree_release.released_at` is the numeric registry release time. The former must follow the
receipt and precede the TARS pickup; the latter must follow the pickup and precede the new
registration. The former session and the exact path, branch and generation must agree with the
predecessor readback. A legacy remote claim's session is the trusted coordinator's observation, not
a retroactive dispatcher event binding. The coordinator must reconcile any earlier session transfer
before recording that observation; a fresh claim cannot establish missing transfer history. An older
PR pickup is provenance and need not be rewritten when the coordinator's current readback names a
later same-session lease. If neither an initial pickup nor a local predecessor is known, the normal
authenticated handoff and remote readbacks are required; otherwise use maintenance to re-establish
authority. On 2026-11-13 the owner reported
that the approved TARS publication checkout had no dispatcher DB and that the existing #6618 Mac
lease `54616511`, holder `codex-6618-pr-completion`, session `codex-6618-20261112`, had not been
transferred. The coordinator must re-read those facts, release the exact old lease, establish readiness,
perform the real TARS fallback pickup, release/register the worktrees and compare the candidate before
the separate acknowledgment. No new dispatcher DB or invented TARS lease is needed. Ambiguous or
contradictory history stops the affected merge and routes to ordinary owner/maintenance reconciliation.

For the native controller, the existing handoff is two authenticated Issue or PR comments in the
canonical order, each a YAML or JSON mapping under `lifecycle_handoff_receipt.v1` (optionally in one
fenced code block). The current owner posts the receipt, without `successor_acknowledgment`, before its
coordination release. After its own claim, registration and readbacks, the successor posts the
acknowledgment as a new comment: the same receipt plus `successor_acknowledgment`. Editing the receipt
comment instead does not count. The existing fields in `BUILDER_SUBAGENT_ROLES.md :: Handoff receipt`
remain authoritative. Encode `current_lifecycle_owner` and `successor` as `{agent, session}`; use the
exact branch, base (`main` or its current SHA), worktree, candidate HEAD and sorted changed-file paths,
identical in the latest receipt and the acknowledgment. Include validation and review evidence,
blockers, residual risk and the next authorized action. The `successor_acknowledgment` has the
successor's `agent` and `session` and these readback mappings:

- `prior_coordination_release`: `status: released` and, for a dispatcher predecessor, its exact
  `task_id`, `lease_id` and `holder`, plus `readback` with `status: ready` or `blocked` and null
  `claimed_by` and `lease_id`.
- `successor_pickup`: `mode`, `agent`, `session`, and the current dispatcher `lease_id` or fallback
  `evidence` (`github-comment:<id>`).
- `prior_worktree_release`: `status: released`, `path`, former session as `owner`, `branch`, and
  `generation`.
- `successor_registration`: the `path`, `owner`, `branch`, `generation`, registration `epoch`, and
  numeric `observed_at` returned by the preparation command below.
- `candidate_readback`: the preparation command's `branch`, `base`, immutable `base_sha`, `head`,
  sorted `changed_files`, `clean: true`, and numeric `observed_at`.

Before posting the acknowledgment, the trusted coordinator reads the pending comment and the actual
clean registered checkout using the normal lifecycle registry. Supply the exact transfer-time base
SHA and the pending Issue or PR comment ID; include `--pr <number>` when either comment is on the
PR. The output supplies the two acknowledgment mappings above:

```bash
python3 scripts/agent_worktree.py --cwd <host-repo> prepare-transfer \
  --worktree <successor-worktree> --owner <successor-session> --workspace-root <model-workspace-root> --issue <number> \
  --pending-comment-id <id> --base-sha <sha> [--pr <number>]
```

After posting the separate acknowledgment, wait until its complete GitHub timestamp second has
elapsed and execute the following readback with the actual comment IDs. It pins the two comment
digests and observed interval in the same existing registry row only if the same epoch remained live
throughout that second. A release, expiry, path or generation change starts a new epoch; it cannot
make an earlier gap valid. Repeating an exact completed pin reads back the existing proof.

```bash
python3 scripts/agent_worktree.py --cwd <host-repo> pin-transfer \
  --worktree <successor-worktree> --owner <successor-session> --workspace-root <model-workspace-root> --issue <number> \
  --pending-comment-id <id> --ack-comment-id <id> [--pr <number>]
```

These are technical readbacks in the existing handoff, not a per-PR approval. The historical pin is
retained through same-session registration, reclaim and verified path moves. A new transfer retains
the predecessor's bounded proof and move snapshots within the same registry record. When a path is
reused and its row replaced, the consumer accepts the move only if the preserved snapshot proves
the earlier released pinned interval. Snapshot and transfer nesting is limited to 32 levels; exceeding the bound
or encountering incomplete older evidence refuses the affected continuation and requires the owner
or maintenance workflow to reconcile the preserved registry and authenticated handoffs. A later
pickup cannot manufacture past proof. The controller
independently checks current live ownership and the clean current PR head. The transfer head must be
an ancestor of the current head; the existing current-head scope review receives the intervening
diff to assess dropped obligations and reverts along with intended fixes and refactors. Tests and CI
remain bound to the current head. The controller never runs host Git against a model-owned checkout.
Only a comment from the existing authenticated GitHub identity with OWNER, MEMBER or COLLABORATOR
association is considered.

The reviewer uses the public final response for its exact finished conversation. One bounded JSON
report may be enclosed between `<BEGIN_PR_CYCLE_REPORT>` and `<END_PR_CYCLE_REPORT>` after plain
public closeout text. The controller binds the report to the native execution observation, persists
both before stopping the exact reviewer container, and reconciles an uncertain stop by checking that
container's absence. Findings return to the existing repair owner after reviewer capacity is released.
Exact closing Issue holds are checked again immediately before merge; a non-closing parent remains
open. Dispatcher recovery records each reclaim and completion intent and reads back the actual lease
and ordered events before proceeding. Older ambiguous effect records remain unknown.
It is not installed
or qualified by its tests. Do not schedule delivery until independent source review and actual host
qualification have passed.

Each epic directory holds a controller-owned bare mirror, one separate clone and home per worker,
an integration checkout and the existing `epic_run_state` record (worker, branch, container,
engine, model, budget and next action per Issue). Containers are replaceable; checkouts and
run-state are unique work and survive container removal. The mirror is seeded from a git bundle.
The trusted host has its existing GitHub CLI authentication; worker containers do not receive it.
Publication stays with the coordinator, which fetches the
worker branch and uses `publish-pr`.

OpenHands is the normal execution and session-control surface. The default image in this source is
the pinned upstream agent-server (`ghcr.io/openhands/agent-server:1.60.1-python`, by digest; it bundles
claude-agent-acp 0.63.0 and codex-acp 2.2.2). The installed controller and image require separate
runtime readback. The recorded #6618 exception is worker `w-6618`, stopped and replaced between runs
(not hot-swapped) with the pinned upstream 1.62.0 image (`bd35862a…`, bundling native Claude Code
2.1.312), per #6618 comments 6837205144 and 6842687488. Each worker gets a loopback-only
port in 18700–18799 and a per-worker session key in the controller-only `control/` directory.
Conversation history is kept in the worker's persistent home. `conversation-start --engine
claude-code|codex [--model M]` creates the conversation through upstream `agent_settings`
(`acp_server`, `acp_model`), tagged with epic, Issue and worker. The default is Claude Code with
`claude-sonnet-5-5`; Codex accepts only `gpt-6.1-terra`, and Astra is refused. The conversation id
is recorded before the request. A lost response is reconciled by reading that id and is never
retried as a create. In this source candidate, `conversation-status` reads the newest bounded
upstream event page (default 50) and classifies only the latest `ConversationErrorEvent` as
`quota_exhausted`, `authentication`, `context_exhausted`, `transient_network` or `task_failure`.
The classifier recognizes the observed native session and weekly quota phrases; tool and message
text cannot trigger a handoff. Upstream 1.60.1 already supports the newest-first event ordering.
Only quota exhaustion may trigger the engine handoff (#6618). The running pinned controller has
not been hot-upgraded with this correction, and automatic handoff remains unqualified.
`worker-start` runs a
plain container and is recorded as `native-exception`: it is for bootstrap, diagnostics and recovery
only and never counts as OpenHands-delivered work.

The boundary rules below apply to both. `worker-start` mounts only the worker's checkout (`/workspace`) and home (`/home/worker`). It
enforces CPU, memory and pids budgets, drops all capabilities, sets `no-new-privileges`, uses a
read-only root, runs as uid 1000 and joins the owned `epicws` bridge. It refuses before any engine
effect for: other mounts, Docker or host paths, host or container network modes, invalid budgets, a
credential env file inside the workspace root or readable by others, and an existing container for
the same worker. If the engine is unavailable, it refuses: there is no host fallback. `worker-stop`
removes the container. It records `stopped_verified` only after engine readback shows the container
is absent, together with the checkout's uncommitted, ignored and unpublished work.

Stop and recovery, from outside any worker:

```sh
ssh bob-1-builder-system '~/epic-sandbox/bin/epicws --epic <N> status'
ssh bob-1-builder-system '~/epic-sandbox/bin/epicws --epic <N> worker-stop --worker <W> --reason <why>'
ssh bob-1-builder-system 'docker rm -f $(docker ps -aq --filter label=epic-workspace.epic=<N>)'
ssh bob-1-builder-system 'ln -sfn <previous-sha> ~/epic-sandbox/runner/current'
```

The third command is the emergency stop for every container of one epic. The fourth restores the
previous controller release. Workers must not hot-replace the active release. A candidate controller
is installed as a new `<sha>` directory between reconciled runs.

Preservation, takeover and retirement are implemented in the #6617 source candidate. The running
pinned controller has not been upgraded or qualified by this source change. After the candidate is
independently reviewed, installed and verified, these commands run from outside any worker:

- `worker-stop` removes the container, reads absence back from the engine, then captures unique work
  in a controller-owned checkpoint repository under `control/checkpoints/<worker>.git`. The checkout
  is mounted read-only in a networkless inspection container; a separate index and configuration
  keep worker filters from running. Controller-owned Git attributes override worktree conversions, and
  a contained CRLF round-trip must pass before inspection or checkpointing. Paired checkpoint refs
  hold the worktree and the worker's staged index tree; retained refs hold objects from the worker's
  refs, both object IDs in every reflog entry, stash history and linked-worktree HEADs. The common
  Git directory and each registered linked worktree's reflogs are inspected; each raw record must
  have a complete committer identity and date, including the name, email delimiters, nonzero
  timestamp and timezone.
  Malformed, missing, unreadable or oversized reflog evidence keeps the checkout. A connectivity check without the checkout's object
  directory must pass before the checkpoint is recorded. An unmerged or unreadable index is kept as
  unreadable work.
- Unique work is: staged edits, uncommitted or untracked files, ignored files, commits reachable from any worker
  ref, reflog, stash history or linked-worktree HEAD that are not
  reachable from a controller-owned `source.git` ref or a coordinator-recorded published head, and
  unreadable evidence. Worker remote-tracking and checkpoint-looking refs never prove publication.
  Cache-looking names do not prove that their contents are disposable. A nested Git repository is
  treated as unreadable work and kept intact because a gitlink does not capture its worktree.
- `takeover --worker W --reason R [--readback-file F]` is the only way to continue a replaced worker.
  It removes any remaining container and proves absence by engine readback (a lease or timeout proves
  nothing), checkpoints the files, checks the post-checkpoint content and refs, validates the recorded
  mapping and reconciles publication attempts from coordinator-supplied readback. If the actual named
  branch differs, or HEAD is detached, takeover checkpoints even a clean checkout and records the
  actual execution identity under the existing worker and generation. Detached HEAD and its work are
  independently retained in the controller checkpoint. Takeover compares HEAD, branch, staged tree,
  raw index, worktree, refs and reflog identity after checkpointing and again before authorization; start checks that
  identity and checkpoint again. If the checkout changed, start refuses and a new takeover records
  the new work before continuation. A legacy authorization lacking that identity also requires a new
  takeover. The original publisher/claim branch remains separate; this reconciliation neither changes
  a claim nor authorizes publication. Unreadable evidence, unmerged indices and unsettled Git
  metadata lock files remain fenced and preserved.
  It reads engine absence again while recording exactly one continuation. Per-worker controller locks fence overlapping
  starts, stops, checkpoints and takeovers. The successor's `worker-start` or `openhands-start` consumes
  that authorization; a repeated takeover before a start returns the same continuation only while
  its checkout, checkpoint and engine checks still match. Worker
  launches create an unstarted container first and record its full ID before sending a start for
  that ID. A timed-out create can leave an unstarted container; `worker-stop` or `takeover` verifies
  the exact name and labels before removing it. A timed-out start is settled by removing the recorded
  ID and reading back its absence. A late start for that removed ID cannot start a replacement.
  Checkpoint writers use the same create, record, start and ID-bound removal sequence; their
  outstanding ID is recorded before the write starts. If cleanup or readback is unavailable, the
  checkpoint and continuation remain blocked. Retry `worker-stop`, `worker-checkpoint`, or `takeover`
  after the engine recovers; the checkpoint is then retried or an existing partial result adopted.
  Read-only inspection uses disposable scratch. Its timeout cleanup checks exact name and inspection
  scope; an already absent `--rm` container does not create a false cleanup failure. A late create
  can leave an unstarted container that occupies its name until a later scoped stop removes it.
  A legacy unresolved `docker run` without an ID or a legacy checkpoint-cleanup marker has no such
  proof and is refused; engine absence alone cannot prove that its old request will not run later.
  OpenHands port selection and credential-home admission are serialized within the workspace root;
  a conflicting bind from outside that root is settled through the same stop and takeover path.
- `continuation-brief` rebuilds the next authorized action, checkpoints, blocked operations and the
  engine-neutral successor prompt from run-state alone, so a Codex worker can continue a Claude
  worker's task (and back) without the predecessor writing a summary.
- Publication goes through `publication-begin` (intent recorded before the effect), then
  `publication-complete` or `publication-reconcile`. The coordinator supplies
  the independently established full intended commit as `--expect-sha` when beginning every new
  `branch_push`. Legacy pushes without a target remain quarantined on generic branch readback unless
  operation-specific positive completion settles the original request. The coordinator reads GitHub;
  completion supplies
  the observed `branch` and `sha`, plus a PR `number` for PR creation. Reconciliation supplies a complete
  branch readback with its `name`, `exists` and, when present, `sha`, or the queried `branch` with a
  complete `pull_requests` list whose sole match includes `number`, `branch` and `sha`. An unknown
  outcome is quarantined for that operation only and is never replayed. A missing branch or empty PR
  list does not establish that an old request has finished. Older `absent_confirmed` records from
  such readbacks remain unresolved. This controller has no authenticated no-effect settlement receipt;
  a later matching positive readback can confirm the original operation when no other create attempt
  could have produced that PR. A confirmed push keeps its
  evidence, and a different, explicitly specified head can use a new push intent after all prior pushes
  on that branch have settled. Normal parent publisher and branch gates still apply.
- `worker-retire` removes only the container carrying this epic/worker label pair, then the checkout
  only when nothing unique remains. It refuses while unique work, unreadable evidence, an unreleased
  checkpoint or an unresolved publication exists. Unlike takeover, retirement does not checkpoint a
  clean detached or drifted checkout only to retain its identity, because it authorizes no
  continuation. Such a checkout retires once its earlier checkpoints are released. This requires
  that its HEAD, refs, reflogs and stash are reachable from controller-held publication evidence, and that
  no uncommitted or ignored content remains. Worker refs never count as that evidence. An
  unpublished detached or reflog-only commit is unique work, so retirement checkpoints it and refuses.
  Registered linked checkouts share the common Git directory and cannot be inspected through this
  checkout's mount, so retirement retains the common checkout while any remain registered.
  `checkpoint-release` supersedes a checkpoint only
  when paths from both captured trees match a controller-proven published commit and its retained
  commits are reachable from controller-held publication evidence. Different staged and worktree
  bytes for the same path cannot both match one published commit, so the checkpoint remains preserved.
  Older checkpoint records without staged-index or reflog coverage evidence also remain preserved;
  a previously released record without that reflog proof likewise blocks checkout retirement.
- `worker-create` on an existing checkout reads the actual branch back and refuses a mismatch with the
  requested or reconciled execution branch instead of recording it. For an authorized detached checkout,
  the existing publisher branch is supplied as `--branch` and the bound detached identity is checked.
  It does not alter the publisher branch.

Claude Code authenticates with a subscription token from `claude setup-token`. The token is stored
as `CLAUDE_CODE_OAUTH_TOKEN` in `~ygg/.config/epic-workspace/claude.env` (mode 0600, outside the
workspace root) and passed with `--env-file` (`openhands-start --claude-env-file`). Upstream OpenHands
lets this token take precedence and strips `ANTHROPIC_API_KEY`. The Terra reserve uses one ChatGPT
subscription login in `~ygg/.config/epic-workspace/codex`, created once by the owner with
`ssh -t bob-1-builder-system '~/epic-sandbox/runner/current/config/builderops/epic-workspace/codex-device-login.sh'`.
`openhands-start --codex-home` mounts it at `/run/codex-home` for one worker at a time, because
refresh tokens rotate. No API key and no host credential store is used.

Known limits: on the 3915 MiB, no-swap trial VM, native workers hit OOM at both 1000 and 1200 MiB;
the current trial uses 1500 MiB and serial execution pending peak-memory and concurrency
qualification. Test runs use an owned disk-backed temporary directory for `TMPDIR` and a separate
pytest base directory per run to avoid accumulating temporary files in memory. These are trial
observations, not a global worker budget minimum. The default engine's `docker0` bridge is missing,
which is why the owned `epicws` bridge is used.
An agent-server worker uses about 0.5 GB at rest. A checkpoint containing ignored files or stash commits
can remain unreleasable when publication cannot prove their captured content or reachability.
The reflog inspection requires the main and registered linked worktree HEAD logs, accepts up to
32 MiB of reflog bytes and 5,000 distinct retained objects, and does not reconstruct expired or
deleted entries or arbitrary unreachable Git objects. A checkout with a `.git` file instead of the
supported plain common Git directory remains unreadable and retained.
A worker stopped inside a Git operation can leave a `*.lock` file under `.git`, such as `index.lock`
or a ref lock. The controller treats any such lock as an unsettled Git transaction and therefore as unreadable unique
work. Checkout and lock bytes are retained, no checkpoint is taken, takeover and retirement refuse,
and the next action remains `takeover`, so no successor starts. The controller never deletes,
clears or applies a lock and has no general Git or rebase recovery. An ordinary readable file-level
partial write outside a Git operation is checkpointed and continued normally. The next technical
action belongs to the owning workflow: reconcile the stopped Git transaction from the retained
checkout and lock, then rerun `takeover`, which inspects again from the start. Until then the
work is retained but not continued or reclaimed. Nothing
reclaims a workspace that may hold unique work until #6617 qualifies
preservation (KD-B5F8B2D2F2BB, KD-FE5EDF575D1E). The engine handoff and the disconnect-safe
coordinator are #6618; non-progress handling is #6619.

## Planning vocabulary and lightweight breakdown

Use these terms consistently across specifications, skills, and issues:

- **Use case / scenario** — an actor's goal in a real situation, with an intended outcome and
  failure modes. Anchor the human need in `docs/HUMAN-FLOWS.md` and scenario-level acceptance in
  `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`. A use case is not an implementation unit.
- **Feature** — a user-facing outcome that may compose multiple use cases, capabilities,
  integrations, surfaces, and subsystems. A feature specification owns target scope and flow; a
  parent feature issue, when needed, is the end-to-end validation hub.
- **Capability** — a reusable, surface-independent function with a typed contract. Its primary
  subsystem owner is the Capability subsystem; its contract and collaborating subsystem roles are
  defined by `docs/CAPABILITY_CONTRACT_MODEL.md`. A capability is not a feature, agent, integration,
  or UI. Do not create one for each step of a feature flow; reuse or extend the existing capability
  set first.
- **Contract** — a normative agreement about meaning, authority, inputs/outputs, or boundaries
  across artifacts or subsystems. A contract is not itself a user outcome or executable capability;
  it constrains the capabilities and subsystems that implement it. For example,
  `docs/CONCEPTS/ARTIFACT_RETENTION_POLICY_CONTRACT.md` defines shared retention policy, while the
  Capability subsystem assesses relative value and Governance / Authority admits deletion.
- **System Breakdown Structure (SBS)** — the target system and subsystem decomposition and
  change-impact model in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`. The current eight-subsystem
  system-of-systems spine and subsystem responsibilities are described in
  `docs/MODULAR_ARCHITECTURE.md`; use both at their appropriate horizons.
- **System Requirements Document (SRD)** — Yggdrasil does not currently have one formal,
  consolidated SRD. Feature specifications and subsystem/capability contracts are authoritative in
  their own scope, while the Scenario Acceptance Matrix provides human-scenario validation. Do not
  create a new global SRD by default; use these existing surfaces unless a human explicitly asks
  for a formal SRD and defines its intended authority.

Some older specification directories and issue references use *capability* as a broad historical
label for a target area. Do not infer that such a document defines a reusable function owned by the
Capability subsystem. Classify it by the outcome or contract it actually specifies, and use
`docs/CAPABILITY_CONTRACT_MODEL.md` to determine Capability-subsystem ownership.

The practical traceability chain is:

`Human flow -> scenario/use-case acceptance -> feature specification and cross-cutting owner contracts -> capability contracts and subsystem ownership -> parent or slice issue(s) -> code/PR -> slice verification -> feature/capability/contract validation -> acceptance -> owner-doc promotion`

Use different delivery hubs for different outcomes:

- A **feature issue** tracks an end-to-end user outcome and its validation path.
- A **capability issue**, when a reusable function needs multiple implementation slices, validates
  that function's typed contract and named subsystem ownership; it does not replace feature-level
  acceptance.
- A **cross-cutting contract issue**, when a shared policy or boundary needs multiple slices,
  validates that normative behavior and its subsystem-owner boundaries; it does not replace feature
  or capability acceptance.
- **Epic** is a tracker convention for grouping work, not a separate product or architecture
  concept. A parent issue may serve that tracking role, but its source classification remains
  feature, capability, or contract.
- A **slice issue** defines one bounded implementation step for agent pickup.
- A **PR** should usually map to one slice issue, not a vague roadmap heading.
- **Slice verification** proves the implementation at the intended layer. Feature or capability
  validation proves the larger outcome after its required slices merge.
- **Acceptance** is the explicit decision to promote supported truth into owner docs.

Example: `docs/LOCAL_TEST_BOOTSTRAP/` is a feature-level system specification for one target
outcome. It can span multiple implementation issues without becoming either a capability or a
formal SRD.

Interpretation rules:

- slices may be done at merge while the parent validation issue remains open;
- a capability may support several features, and a feature may compose capabilities from the same
  or different subsystem boundaries; and
- this is a lightweight delivery spine, not a heavyweight process rewrite.

## Evidence surfaces

Use different surfaces for stable intent versus live delivery evidence:

- Docs define the intended verification path and acceptance path up front.
- Feature / capability issues hold the live validation evidence and acceptance checklist, usually in the issue body and follow-up comments.
- Slice / child issues hold the bounded implementation contract.
- PRs hold the slice verification receipt.
- Owner docs change when accepted/shipped truth changes, not for every post-merge rerun.

Practical rule:
- do not open a new docs PR just because more post-merge evidence arrived
- do record that evidence on the parent feature issue so acceptance can be decided from one place
- do create a docs PR when owner-doc truth changes, for example from planned to accepted or supported

## Validation baseline

### Repository documentation language

Repository documentation uses English as its primary prose. The policy covers root contributor
documents, `docs/**`, repo-local skills and agent adapters, Companion UI documentation, and governed
design handoffs. It deliberately does not reclassify Product/vault Markdown or multilingual test
corpora as documentation; those surfaces contain Swedish and other languages by design.

`python3 scripts/docs_guard.py --language-only` scans the complete tracked documentation surface on
every PR, including implementation PRs. It removes fenced code, inline code, URLs, and comments
before applying a deterministic primary-language check. Explicit bilingual Markdown tables whose
headers name at least two languages are treated as localization data, while ordinary technical
tables remain part of the prose check. Bounded quotations, localization strings, and SV/EN examples
are permitted inside an otherwise-English document. A document whose primary prose is detected as
non-English fails with the path and marker evidence; there is no per-file bypass.

The dependency-free detector uses closed-class markers for common Latin-script languages and a
Unicode-script threshold for non-Latin prose. It is intentionally a CI fitness heuristic, not
universal language identification: very terse text with too little language evidence, an uncommon
Latin-script language outside the marker sets, or an unlabeled mixed-language table can remain
ambiguous. Review remains responsible for those cases.

- Docs-only changes:
  - run any repo docs validation command if one exists
  - when `.codex/skills/**` changed, run `python3 scripts/lint_skills_consistency.py` (exit 0, zero output = clean)
  - otherwise run lightweight repo checks that are still appropriate
- Exact CI-contract-only changes (`TEST_STRATEGY_HOT_PATH.md :: Exact CI contract scope`):
  - lint the changed tooling and run the selector's covering CI/helper/workflow contract tests
  - run documentation checks for the paired development owner docs
  - Product-wide type/model/ACL gates are unnecessary when the closed CI predicate admits no
    Product, dependency, runtime-configuration or shared-fixture change
- Isolated test-module-only changes (`TEST_STRATEGY_HOT_PATH.md :: Test-only scope`):
  - run the explicit representative targets and common CI integrity checks; exhaustive fault matrices
    run in the existing nightly/manual lane, and explicit full-matrix contracts still need full proof
  - retain the normal test environment and dependencies; unrelated
    Product type/model/ACL/smoke gates add no evidence for this exact no-consumer test-only scope
  - shared fixtures, helpers, configuration and mixed Product changes use their normal broader scope
- Product/runtime code-affecting changes:
  - `ruff check app tests companion-ui/companion-app`
  - `mypy app`
  - run the governing Issue's `Verify:` targets and the affected subsystem's focused tests
  - Functional tests that exercise Product model access through ingest, worker, retrieval, or
    evaluation callers must enroll the module-level `product_model_access_gateway` fixture
    explicitly. It supplies typed deterministic Product responses at the fabric router seam and
    does not require a host endpoint or certificate configuration. Keep executor transport and
    admission tests outside that enrollment so missing path configuration still fails before
    transport creation; never make the fixture autouse or provide fake host credentials.
- API tests that exercise model-backed request handlers should request the explicit
  `tests/api/conftest.py::mock_product_api_routes` fixture only on those test functions. It forces
  the deterministic mock provider because compiled model routing can override `LLM_PROVIDER=mock`;
  keep selected-route health and admission tests outside this fixture. Do not make it autouse.
- Operational caller or launcher changes must be checked as the final assembled invocation,
  including its interpreter, cwd, configuration and import/validation boundary. Keep core
  orchestration, public contract readers and validation real; substitute only external effect
  ports. Cover both DEV and TEST when the affected caller supports both non-production channels,
  including a credible refusal or partial-failure path. Apply the existing evidence-reuse and
  stop rule in `docs/development/GOVERNANCE_PROPORTIONALITY.md`; this does not require a broader suite.
- Settings/runtime contract changes:
  - `python -m app.cli settings-validate --json`

When the governing Issue requires the full non-PG suite, retain the exact selection
and run it through the host-global lease:

```bash
python3 scripts/run_with_host_lease.py --resource pytest-not-pg --execution-id <issue-or-pr>:<sha> -- pytest -q -m "not pg"
```

The root
`conftest.py` provisions and validates a unique `PYTEST_DEBUG_TEMPROOT` namespace
before collection for every invocation. An inherited debug root supplies the parent
directory; each process still receives a fresh direct child namespace. Without an
inherited root, the harness uses a stable UID-owned private directory beneath the
system temporary directory. Setup failure aborts before tests execute, with no
shared-root fallback. Each new namespace records its
owner and keeps a shared lifetime lock, including locks on marked parent namespaces
for nested pytest runs. On normal completion it records the end time; a nested run
also extends the retention of its marked ancestors. On a later invocation the harness
may remove only its marked direct-child namespaces at least seven days after completion,
when the owner is absent and the exclusive cleanup lock is available. Missing or
malformed markers, interrupted runs without a complete end record, uncertain child runs,
live or unknown owners, symlinks, and failed checks are preserved. Existing unmarked
namespaces are not migrated or removed; cleanup is best effort and leaves uncertain
evidence intact. Automatic cleanup is limited to UID-owned 0700 parents on qualified
ownership-enforcing mounts and uses a common parent lock shared by cooperating harnesses
around namespace changes. macOS `noowners` and unknown filesystem semantics are not
qualified; mount identity is rechecked before moving or deleting a candidate. A
candidate with another mount, special files, or uninspectable entries is preserved. The
parent listing and each candidate scan have a limit of 100,000 entries and share a
five-second pre-rename budget; an unfinished root requires separately qualified
maintenance. This does not interrupt a stalled filesystem call or
bound deletion after rename. An
unqualified default mount fails setup; an inherited unqualified parent remains available
for isolated tests without pruning. A same-UID
or root process deliberately bypassing that advisory lock is outside this boundary;
an inherited parent that cannot be qualified still supports isolated tests but is
never pruned. Markers on confirmed `noowners` enclosing mounts are left untouched;
qualified enclosing namespaces retain lifetime fences. If an enclosing marker exists
but its mount probe is inconclusive, setup fails rather than dropping its fence. On a qualified mount, a marked enclosing
namespace whose owner marker cannot be safely opened and pinned fails setup rather
than being treated as unmarked legacy.
A valid busy lock is waited on for at most 30 seconds, then setup fails
loudly; cleanup holds it only for final identity checks and the rename, not recursive
deletion. A malformed default-parent lock also fails setup before collection.

### Validation-readiness diagnostic

Before starting a costly validation lane, an operator may run the bounded, read-only diagnostic:

```bash
python3 scripts/validation_environment_readiness.py --target test
python3 scripts/validation_environment_readiness.py --target lint
```

The command resolves the repository interpreter through `scripts/lib/resolve_repo_python.sh`,
including an explicit `BUILDEROPS_PYTHON` override, and emits value-free JSON. `compatible` means
the required modules imported in that interpreter; `unavailable` and `import_incompatible` require
selecting an existing supported interpreter or fixing the invocation context. Helper status is
`visible`, `missing`, `restricted`, or `unknown`; a failed or timed-out helper invocation remains
`unknown` and does not imply a credential or ACL failure.

The PG classification is `absent`, `forbidden`, `ambiguous`, or `disposable_candidate`. `absent`
matches the existing no-DSN skip banner and is never a pass. A primary disposable DSN remains
`ambiguous` when runtime or ambient writers are also configured, so one value cannot hide another
target. Multiple primary DSNs are also unresolved unless they repeat the same value. URI or
keyword conninfo without an explicit host is a forbidden local-socket target, and a host without an
explicit port remains ambiguous. Only an explicit disposable candidate such as the documented
`app_test` target may proceed to the existing PG guard and host-lease workflow; the diagnostic never
connects, provisions, installs, or authorizes a lane. For
`unavailable` or `import_incompatible`, select an existing supported interpreter or set a valid
explicit override and rerun. For `missing` or `restricted`, use the existing helper path with the
current checkout/sandbox visibility; for `unknown`, inspect the helper's bounded invocation result
and rerun without changing credentials or ACLs. The terminal evidence for each recovery is the
value-free JSON status plus the ordinary validation command's own receipt. A zero exit status means
only that the diagnostic ran, so its statuses must be read before a validation command is started.
This is an operator aid and does not add a mandatory gate or replace the existing Make/lease
selection owned by #5805 or the temporary-isolation work tracked by #4009.

### Pointing the PG lane at a scratch database

The `pg` lane has **no default database** (#4573). It runs destructive DDL, `TRUNCATE`, and
`CREATE DATABASE` / `DROP DATABASE` against whatever `DATABASE_URL` / `DB_DSN` resolves to, so it
refuses to guess:

- Nothing configured → every `pg`-marked test **skips**, with a terminal banner naming what to set.
  A skipped PG lane is never silent, including under `pytest-xdist` (`make smoke`, `CI Smoke`).
- A DSN that `app/db/dsn.py :: looks_like_prod_dsn` flags → the run **aborts in `pytest_configure`,
  before the first test module is imported**, so nothing opens a connection. That classifier flags a
  DSN whose database name is exactly `app` or whose port is the prod-published `15432`.

The same classification runs again at all three psycopg connection entry points during pytest. That
side-effect-boundary guard classifies positional conninfo together with libpq keyword parameters, so
late overrides cannot hide a production target. It also refuses implicit or explicit local-socket
targets and service indirection, whose server cannot be proven safe. The AST census under
`tests/architecture/` deliberately checks only hard-coded defaults; it is not a Python dataflow analyzer.

The gate checks **four** ways this repo can name a database, not just the obvious one:

| Writer | Reached through | Checked |
|---|---|---|
| `DATABASE_URL` / `DB_DSN` | `app/db/dsn.py :: resolve_dsn` | always |
| `PKM_DB_HOST` / `PKM_DB_PORT` / `PKM_DB_NAME_*` / `POSTGRES_*` | `app/config/database.py :: resolve_runtime_database_url` → `app/db/db.py :: conn_rw` | always when explicitly configured |
| `PGHOST` / `PGHOSTADDR` / `PGPORT` / `PGDATABASE` / `PGUSER` | libpq's own defaults, whenever an empty conninfo is passed | always when any target field is explicitly configured |
| `PGSERVICE` / `PGSERVICEFILE` | libpq service indirection | fail closed whenever either is configured because its effective target cannot be inspected safely before imports |
| `BUILDEROPS_DATABASE_URL` | the control plane's own `CREATE SCHEMA` path | always |

Service indirection is fail-closed whether selected through `PGSERVICE` / `PGSERVICEFILE` or embedded
as a `service` option in an explicit conninfo/URI: the service file can supply a target the pre-import
guard cannot inspect safely.

The second and third are the reason `DATABASE_URL` alone is not sufficient: a run with
`PKM_DB_HOST=127.0.0.1 PKM_DB_PORT=15432` and no `DATABASE_URL` reaches production through
`conn_rw()` while the documented pair still looks unconfigured. Each writer is checked independently:
a safe primary DSN cannot hide a production runtime or ambient libpq target. The unconditional
compose-internal fallback is ignored only when no runtime writer was explicitly configured.

Collection authorization stays consumer-specific. `DATABASE_URL` / `DB_DSN` authorizes the ordinary
`pg` lane; `BUILDEROPS_DATABASE_URL` authorizes only the control-plane tests and BuilderOps recovery
test that consume it. Runtime and ambient libpq variables never globally unskip destructive tests
that consume the documented pair.

The refusal is deliberately placed before imports rather than after collection: several test modules
probe Postgres at import time (`tests/stores/test_capabilities_matrix.py` evaluates `pg_available()`
inside a `skipif`), and every import happens after collection begins. A collection-time check
refuses only *after* the suite has already dialled the server. The consequence is that the check
reads the environment, not the selected test set: a run whose marker expression happens to exclude
`pg` still aborts if a prod-looking DSN is exported, unless the expression contains the literal
`not pg`, which makes `tests/conftest.py` drop both variables up front. Unset the variable, or use
`-m "not pg"`, when you want that run to proceed.

Name a non-production target explicitly:

```bash
DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test python3 -m pytest -q -m pg
```

Per `docs/ENVIRONMENTS.md`, `dev` publishes `15433` / `app_dev` and `test` publishes `15434` /
`app_test`; `15432` / `app` is production and is exactly what the guard exists to refuse. The
scratch-database factories under `tests/migrations/**` derive their admin DSN from the same
resolution, so this one setting also decides where `CREATE DATABASE` lands. CI supplies its own
`app_test` service DSN and is unaffected.

Escalate to the repo-wide non-PG suite only when the governing Issue/owner document names it or the
change has cross-system blast radius that focused subsystem tests cannot cover:

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/run_with_host_lease.py --resource pytest-not-pg --execution-id <issue-or-pr>:<sha> -- pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -p xdist.plugin -q -m "not pg" -n auto --dist=loadfile`

### Resource-bounded local `not pg` fallback

Use the canonical command above first. When it cannot execute on the local host because its
single pytest process exhausts a host resource (for example file descriptors), run the following
sanctioned fallback instead. It retains the same `not pg` marker selection, runs every top-level
test directory and root-level `test_*.py` file, and holds the same host-global lease for the whole
run. It is a local execution fallback, not a way to narrow the required validation standard.

```bash
export PYTHONPATH="${PWD}:${PWD}/companion-ui/companion-app${PYTHONPATH:+:${PYTHONPATH}}"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/run_with_host_lease.py \
  --resource pytest-not-pg \
  --execution-id <issue-or-pr>:<sha> \
  -- zsh -o pipefail -c '
    shard_list="$(mktemp)" || exit $?
    trap "rm -f -- \"$shard_list\"" EXIT
    find tests -mindepth 1 -maxdepth 1 \
      \( -type d -name "__pycache__" -prune \) -o \
      \( -type d -o \( -type f -name "test_*.py" \) \) -print0 | \
      LC_ALL=C sort -z >"$shard_list"
    discovery_pipeline_status=$?
    (( discovery_pipeline_status == 0 )) || exit "$discovery_pipeline_status"
    selected_shards=()
    while IFS= read -r -d "" shard; do
      if [[ -d "$shard" ]]; then
        collectible="$(find "$shard" -type f -name "test_*.py" -print -quit)"
        discovery_status=$?
        (( discovery_status == 0 )) || exit "$discovery_status"
        [[ -n "$collectible" ]] || continue
      fi
      selected_shards+=("$shard")
    done <"$shard_list"
    (( ${#selected_shards[@]} > 0 )) || { print -u2 -- "no collectible not-pg shards discovered"; exit 1; }
    failed=0
    for shard in "${selected_shards[@]}"; do
      python3 -m pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -p xdist.plugin \
        -q -m "not pg" "$shard"
      shard_status=$?
      if (( shard_status != 0 )); then
        print -u2 -- "uncovered shard: $shard (pytest exit $shard_status)"
        failed=1
      fi
    done
    (( failed == 0 ))'
```

The explicit `PYTHONPATH` is part of this one sanctioned command because tests outside
`tests/companion_ui` import the nested `companion_ui` package during collection. Do not add
one-off path exports to Issue or PR handoffs. Record the canonical command's host-resource failure,
the fallback command, and every failed shard. The command selects a directory only after finding a
collectible `test_*.py` file beneath it, so helper-only directories are never passed to pytest. Its
`pipefail` discovery pipeline is checked before its output is used, and its per-directory collection
checks fail the leased command before a partial shard list can produce a receipt. A fallback run is complete only when every selected shard
passes; if a shard cannot run, the command reports it as an `uncovered shard` and exits nonzero, so
record the uncovered shard as a validation gap rather than claiming the full `not pg` selection
passed.

The full non-PG suite is host-global. The wrapper above holds an atomic repo-common kernel lock for
the entire child process and releases it automatically when the process exits. A chat handshake,
process census, or quiet-period check is useful diagnosis but is not mutual exclusion. If the lock
is already held, do not start another suite and do not kill the holder; retry only with bounded wait
or after the holder's receipt shows terminal state.

The closed canonical resource allowlist is declared once as `HOST_GLOBAL_RESOURCE_NAMES` in
`scripts/run_with_host_lease.py`. Callers must use a name from that allowlist; the wrapper rejects
ad-hoc aliases before creating a lock file, and the host-lease regression tests keep this documented
command aligned with the allowlist.

Enforcement note:
- The applicable command list above is a required pre-merge gate, not advisory; do not substitute a
  repo-wide suite for identifying and running the affected subsystem's verification targets.
- For code-affecting PRs, run the lint and type commands in the applicable baseline above before merge.
- Docs and governance PRs keep validation focused and do not run full smoke by default unless their touched surface requires it.
- Record the applicable baseline results or an explicit tooling limitation in the PR body.
- If CI is not currently blocking these checks, treat merge as blocked until either:
  - the checks pass locally and evidence is attached to the PR, or
  - blocking CI coverage is added for the missing check and enabled.
- For `ruff --fix` in `conftest.py` or known re-export modules, review F401 removals manually and preserve intentional re-exports with `# noqa: F401` where needed.

### CI / validation expectations

`CI Smoke` (`.github/workflows/ci-smoke.yaml`) runs the `Unit tests (not pg)` check
(`pr-unit-tests-not-pg`) automatically on `pull_request`. That check
uses `scripts/select_pr_tests.py` to execute affected-subsystem pytest targets without a Postgres
service, so relevant unit regressions are visible before merge without paying for the repo-wide
suite on every PR. [`TEST_STRATEGY_HOT_PATH.md`](TEST_STRATEGY_HOT_PATH.md) owns that selection
behavior and its paths filter.

`Unit tests (not pg)` is a **required** status check in `main` branch protection. A red run blocks
merge at the platform level: the REST merge API rejects the merge with HTTP 405 while the check is
failing. `main` protection requires this single check, requires no approving review, does not
require the branch to be up to date (`strict=false`), and applies to admins. Verified against
`gh api repos/RasmusTho/agentic-pkm-mvp/branches/main/protection` on 2026-07-29; the durable receipt
lives in [`GITHUB_GOVERNANCE_SETUP.md`](GITHUB_GOVERNANCE_SETUP.md).

Platform enforcement is a floor, not the process gate. [`PR_HOT_PATH.md`](PR_HOT_PATH.md) still
governs when a PR may merge, and the absence of a protection rule on any other surface never waives
it.

The shared `app/ops/pg_acceptance.py` profile retains the former PR PG acceptance surface and runs
inside native post-merge dev/test verification after the coverage handoff under #5675. Each stage
uses the same immutable candidate image with its own disposable pgvector database and scratch
vault, and requires every selected PG result to pass. Non-PG PR CI remains the merge check; its
success cannot replace the native PG receipt. The independently bounded PG and integration lanes
remain on `integration-nightly.yaml` (nightly schedule plus `workflow_dispatch`). See
[`TESTING.md`](../TESTING.md) and the [deployment owner](../deployment/DEPLOYMENT_AND_ENVIRONMENTS.md).

The nightly `k6-search` job provisions pgvector in its disposable `k6_search` database, applies
`alembic upgrade head`, and runs assert-only outbox bootstrap before seeding canonical object and
vector rows through `scripts.k6_search_fixture`. The finite fixture uses generated binding/object
identities and the deterministic embedding profile. Its manifest feeds both the real `/search`
compatibility-route readiness/warm-up probe and `scripts/k6_search.js`; each requires the seeded
UUID and title. k6 retains five VUs, ten seconds, and `p(95)<250` ms, with zero HTTP errors and all
status/result checks passing. An equivalent local run must use an explicitly admitted localhost
database named `k6_search_<12 hex characters>`, the same producer commands, and a real isolated API;
never enable schema autocreation or substitute a successful empty response for the fixture result.

## Documentation rules

- Update the owner doc first.
- Keep current-state docs descriptive of shipped reality.
- Put future-state intent in roadmap/plan docs instead of current-state owner docs.
- Replace duplicated policy with links or short boundary notes.
- When a capability is still being stabilized, make the intended verification path and acceptance path explicit instead of implying they will emerge later.

## Pre-implementation classification

Before starting implementation on a non-trivial task, apply `docs/development/AGENT_OPERATING_PROTOCOL.md` to classify the task class (Architecture / Implementation / Operations / Governance / Cost-control), confirm artifact class and environment/channel risk, identify the governing owner doc, and verify that every AC carries a resolvable `Verify:` target. This is a routing and orientation step, not a process gate — it keeps implementation bounded and stops misclassified work before it reaches code.

## Docs-authoring lane

Docs authoring is the docs-only path for evolving or clarifying authoritative repo docs before backlog extraction.

Use this lane only when:

- changed files stay inside approved docs-authoring surfaces:
  - `docs/**`
  - `README.md`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/AGENTS.md`
  - `.github/github-governance.yml`
  - `.github/ISSUE_TEMPLATE/*.yml`
  - `.github/pull_request_template.md`
  - `.github/workflows/issue-pr-governance.yml`
  - `companion-ui/docs/`
  - `companion-ui/design_handoff/`
- the PR does not change code, runtime behavior, contracts, or shipped reality

Docs-authoring rules:

- a governing GitHub Issue is not required
- the PR must be explicitly classified as docs authoring
- the skills consistency lint runs on every PR in the smoke gate (`python3 scripts/lint_skills_consistency.py`, stdlib-only); run it locally when touching `.codex/skills/**` — the pytest wrapper is `tests/governance/test_skills_consistency_lint.py`
- docs authoring does not automatically create backlog work or Project state
- use `docs-to-issue` later when the authored docs are ready to become bounded implementation tasks
- use `feature-breakdown` later when one docs-defined feature should become one parent feature issue plus child slices
- if the change starts affecting implementation or delivered behavior, switch back to the Issue-first implementation lane

## Governance lane

Governance lane is the separate PR path for bounded repository-governance changes that are not product/runtime implementation but are broader than docs-only authoring.

The executable authority for these surfaces is
`.github/workflows/issue-pr-governance.yml`'s
`governanceAllowedExact` and `governanceAllowedPrefixes`.  The list below is
the intentionally checked human-readable mirror; the governance regression
suite rejects drift between the two.  It is distinct from
`scripts/docs_guard_logic.py :: GOVERNANCE_TEMPORAL_ENFORCEMENT`, which is a
narrow temporal owner-doc pairing map rather than a governance-lane admission
allowlist.  `GITHUB_GOVERNANCE_SETUP.md` records this ownership decision
instead of maintaining a second partial list.

Use this lane only when:

- changed files stay inside approved governance surfaces:
  - `README.md`
  - `docs/**`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.codex/AGENTS.md`
  - `.codex/skills/**`
  - `.codex/agents/**`
  - `.codex/config.toml`
  - `.github/github-governance.yml`
  - `.github/ISSUE_TEMPLATE/**`
  - `.github/pull_request_template.md`
  - `.github/workflows/ci-smoke.yaml`
  - `.github/workflows/issue-pr-governance.yml`
  - `Makefile`
  - `tests/architecture/test_requirements_consistency.py`
  - `scripts/plan_full_suite_node_shards.py`
  - `tests/ops/test_ci_workflow.py`
  - `scripts/select_pr_tests.py`
  - `tests/scripts/test_select_pr_tests.py`
  - `tests/architecture/test_handoff_fencing_governance.py`
  - `tests/governance/test_autonomous_escalation_contract.py`
  - `tests/governance/test_late_change_supersession.py`
  - `tests/governance/test_verification_closure_contract.py`
  - `tests/governance/test_skill_model_selection_contract.py`
  - `scripts/docs_guard.py`
  - `scripts/docs_guard_logic.py`
  - `scripts/install_skills.sh`
  - `scripts/agent_workspace_preflight.sh`
  - `scripts/agent_workspace_cleanup.sh`
  - `scripts/agent_worktree.py`
  - `scripts/git_hygiene.py`
  - `scripts/git_archive_retirement.py`
  - `scripts/git_hygiene_preflight.py`
  - `scripts/git_hygiene_janitor.py`
  - `scripts/issue_pickup_claim.sh`
  - `scripts/reconcile_project_status.py`
  - `scripts/pr_body_generator.py`
  - `scripts/py312_smoke_test.sh`
  - `scripts/await_pr_checks.sh`
  - `scripts/review_before_ci_gate.py`
  - `scripts/workflow_review_risk.py`
  - `scripts/run_with_host_lease.py`
  - `scripts/verify_runtime_chain.sh`
  - `scripts/validate_source_anchors.py`
  - `tests/ops/test_agent_worktree.py`
  - `scripts/validate_issue_readiness.py`
  - `scripts/lint_skills_consistency.py`
  - `companion-ui/design_handoff/README.md`
  - `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
  - `companion-ui/prompts/claude-design/**`
  - `companion-ui/prompts/codex/deliver-epic-autonomous-runner.md`
  - `tests/ops/test_git_hygiene.py`
  - `tests/ops/test_git_archive_retirement.py`
  - `tests/architecture/test_agent_skill_entrypoints.py`
  - `tests/architecture/test_pr_hot_path_governance.py`
  - `tests/governance/test_codex_agents_contract.py`
  - `tests/governance/test_ci_smoke_docs_only_gate.py`
  - `tests/governance/test_issue_pr_governance.py`
  - `tests/governance/test_known_defects_registry.py`
  - `tests/governance/test_resume_work_contract.py`
  - `tests/governance/test_skills_consistency_lint.py`
  - `tests/ops/test_project_status_reconcile.py`
  - `tests/ops/test_review_before_ci_gate.py`
  - `tests/ops/test_review_before_ci_workflow_risk.py`
  - `tests/ops/test_host_global_lease.py`
  - `tests/scripts/test_validate_issue_readiness.py`
  - `tests/scripts/test_issue_pickup_claim.py`
  - `tests/scripts/test_validate_source_anchors.py`
  - `tests/scripts/test_docs_guard.py`
  - `tests/scripts/test_pr_body_generator.py`
  - `tests/fixtures/issue_readiness/**`
  - `tests/fixtures/pr_body_generator/**`
- the PR is limited to repo governance, agent workflow, or lightweight enforcement
- the PR does not change product/runtime implementation or shipped feature behavior

Governance-lane rules:

- a governing GitHub Issue is not required
- the PR must be explicitly classified as governance lane
- governance lane is for repository policy and workflow maintenance, not backlog delivery
- if the change starts affecting implementation or delivered behavior, switch back to the Issue-first implementation lane

Issues are the normal workflow contract. Direct repair PRs are allowed for bounded immediate fixes when the PR body is the contract, but they should stay narrow and avoid inventing backlog work after the fact.

## Runtime separation

- Builder-agent instruction lives in `AGENTS.md` and the development reference docs.
- Runtime/system-agent architecture lives in `docs/AGENTS.md` and related runtime/concept docs.
- Do not treat runtime semantics as builder-agent instructions, and do not write builder-agent workflow into runtime docs.

## GitHub issue-first execution loop

For implementation work, the delivery loop is:

1. Docs/owner docs define the intended contract.
2. Feature / capability Issue defines the target outcome plus verification and validation / acceptance path.
3. Slice / child Issue defines the bounded implementation task.
4. Builder agent implements the slice in a PR.
5. CI/test workflows verify the slice and its changed seams.
6. Merge closes the slice when its bounded contract is satisfied.
7. Feature validation continues on the parent issue until the operator/product path is proven.
8. Acceptance closes the feature and triggers owner-doc promotion when the support claim changes.

State model for lane-based delivery:

- Issue state supports claim and bounded execution truth: `Ready`, `In Progress`, `Blocked`, `Done`.
- PR/Project-item state supports review/integration projection: `Review`, `In Progress`, `Blocked`, `Done`.
- Keep issue and PR state separate in multi-slice lanes where several implementation issues can feed the same lane PR.
- `issue-to-code` owns fast issue claim (verified dispatcher lease when available; otherwise remove
  `agent:ready` only through the durable claimant-receipt fallback) to prevent double-pick.
  - Claim must run through
    `scripts/issue_pickup_claim.sh --issue <N> --agent <agent_id> --session <session_id>` so workspace
    preflight and actual claim evidence are verified before label mutation.
- Open PR is the default publication mode. Draft PR is opt-in and requires an explicit reason.
- `Review` is the agent-review gate before verification, not a generic waiting state.
- `pr-integration` is conditional and should be used when mergeability/CI attachment/reviewability needs repair; it is not required after every publication.
- Workspace isolation is mandatory for multi-agent work: one active Codex session per worktree/branch checkout.
- Prefer automation for PR/project-item projection (especially `Done` on terminal PR state) and use manual skill writes as fallback correction when drift is detected.

Execution rule:

- do not start non-trivial implementation without a governing Issue
- select Issues with a strictly validated `agent:ready` label; Project Status is not a pickup gate
- use the linked Issue as the bounded source of truth for scope and acceptance
- implementation PRs should usually link the governing slice / child issue
- do not implement directly from a feature / capability issue when the work is clearly multi-slice
- when a capability spans multiple PRs, keep verification and acceptance attached to the capability rather than scattering them across unrelated roadmap bullets

Docs-authoring and governance-lane PRs are separate lanes and do not replace this implementation contract.

Optional repo-local Codex skills may assist with either lane from `.codex/skills/`, but they do not replace the governing repo policy. Implementation-facing skills should route larger work through `feature-breakdown`, then execute slices through the same `Docs -> Feature -> Slice -> PR -> Slice verification -> Feature validation -> Acceptance` sequence and keep `AGENTS.md` as the canonical builder-agent policy surface.

Lifecycle truth rule:

- GitHub Issue state and linked PR/merge state are the harder lifecycle authority.
- Project `Status` is an optional legacy projection for board visibility.
- `agent:ready` qualifies an Issue for pickup after strict contract validation; dispatcher claim state prevents active collisions when available.
- `In Progress` covers active implementation, including draft PRs and open PRs before explicit review handoff.
- `Review` begins only when the PR becomes the explicit review handoff artifact, normally after review is requested.
- closed or delivered work must not retain `agent:*` labels.
- if Project state drifts because automation cannot update the board, correct it opportunistically without treating the drift itself as a delivery blocker

## Acceptance verifiability

`docs/TESTING.md :: Automated Technical Acceptance` owns deployed technical acceptance: automated
TEST journeys by default, short DEV smoke, qualified synthetic actors/data and actual same-candidate
SHA/digest evidence. Human-need outcomes do not imply manual execution. Missing environment or
automation is concrete Builder recovery/delivery work; a human acceptance exception needs an
observable choice, why it cannot be automated, owner and exact `unblocks_when`.

Every Acceptance Criterion on a backlog Issue must declare its verification inline with a `Verify:` marker. This is a contract-shape rule, not a test-methodology rule: it covers behavioral and non-behavioral ACs alike.

Form:

```
## Acceptance Criteria

- [ ] Ingest rejects entries whose domain fails boundary validation.
  Verify: `tests/ingest/test_domain_boundary.py::test_rejects_invalid_domain`
- [ ] `docs/CONCEPTS/DOMAIN.md` describes the ingest boundary as shipped.
  Verify: doc writeback at `docs/CONCEPTS/DOMAIN.md :: ingest-boundary`
- [ ] Roadmap no longer lists domain-at-ingest as pending.
  Verify: `docs/ROADMAP.md :: DOMAIN-INGEST` removed or rewritten as delivered.
```

Rules:

- Behavioral ACs point to a concrete test (existing or to-be-added) by file and test name.
- Ready-label validation permits a behavioral `tests/...py::test_name` target to name a new test
  file that the builder will add. Other file-based `Verify:` targets must resolve to existing
  repository files.
- Enforcement ACs — behavioral ACs asserting a guard, gate, or invariant holds on the live runtime path — must point to a test that exercises the production call site, not the guard function in isolation. "Module exists and is unit-tested" does not discharge an enforcement AC; "invoked on the runtime path and asserted there" does.
- Non-behavioral ACs point to a concrete observable target: doc writeback path plus anchor, roadmap diff, runtime receipt, a bare repo anchor (`` `<path> :: <anchor>` ``), a diff-of-file target (``diff of `<repo path>` <what the diff adds>``), or a marker-presence target (`` `<literal>` present in `<repo path>` ``). A durable repository path or anchor is what makes the target concrete.
- A backticked canonical target may carry a trailing prose annotation on the same marker line (as the roadmap example above shows); the target stays the backticked segment. The `Verify:` marker opens its own line per the template; an inline tail on the AC line declares a marker only when its target is grammar-resolvable — any other mid-line mention inside AC prose is not a marker.
- An AC that needs several targets declares one `Verify:` line per target, as sub-bullets of the same acceptance item — splitting the targets does not split the AC and does not change the AC count. Targets joined on one marker line (` + `, `and`, or a comma between two backticked targets) are read as a single target whose backticks no longer pair, so the line fails resolution and validation reports a missing file for a path that exists (#3857, #3859).
- If an AC cannot carry a resolvable `Verify:` target, refine or split it before marking the Issue `agent:ready`.
- `Suggested Validation` remains the section that lists the commands and procedures that execute the declared `Verify:` targets. ACs and Suggested Validation are coupled: commands exist to resolve the Verify targets, not to duplicate them.

Enforcement surfaces:

- Creation: `docs-to-issue`, `feature-breakdown`, and `bug-to-issue` must produce ACs with `Verify:` lines.
- Repair: `issue-maintenance-change-control` treats missing `Verify:` as malformed contract shape.
- Consumption: `issue-to-code` gates on `Verify:` presence and reuses meaningful behavioral coverage and performs non-behavioral writeback.

## Multi-Agent Workspace Guardrails

- Preflight before claim/integration:
  - `scripts/agent_workspace_preflight.sh --expected-branch "$(git branch --show-current)" --expected-worktree "$(git rev-parse --show-toplevel)"`
- Preflight at the publication boundary (pre-commit and pre-push, every lane):
  - `scripts/agent_workspace_preflight.sh --expected-branch "$EXPECTED_BRANCH" --expected-worktree "$EXPECTED_WORKTREE" --allow-dirty`
  - The branch-truth gate lives in `publish-pr` and applies to implementation, feature-breakdown, docs-authoring, and governance lanes — not only `issue-to-code`. `--allow-dirty` tolerates the intentionally dirty tree at publish time while still failing on branch or worktree drift, so a concurrent agent switching the shared root worktree's branch cannot land a commit on the wrong branch.
  - The base-branch check asserts what matters at the publication boundary: HEAD already contains `origin/main`. A local `main` ref that lags or diverges from `origin/main` is advisory when HEAD already contains `origin/main`, because `main` stays checked out in the shared root worktree and another task may advance or diverge it. A local base ref that does not prove `origin/main` reachability, or a HEAD without `origin/main`, still fails the gate.
- Safe cleanup report:
  - `scripts/agent_workspace_cleanup.sh --report`
- Safe cleanup apply (clean tree required):
  - `scripts/agent_workspace_cleanup.sh --apply --pr-state-file <path> --lease-file <path>`
  - To reclaim exactly one completed worktree, add both `--target-worktree <absolute-path>` and
    `--target-generation <32-hex-generation>`. Targeted apply limits mutations to that eligible
    worktree and its associated local branch; it never acts on unrelated worktrees, branches,
    remotes, stashes, or prune candidates. It also skips the global `git fetch --prune origin`
    step, which remains part of untargeted apply only. Missing, mismatched, or non-candidate
    selectors fail closed before removal.
- Register dedicated issue worktrees with `scripts/agent_worktree.py register`, renew them with
  `heartbeat`, and record `release` or `complete` when ownership ends. Cleanup is report-only by
  default. Apply may remove only a registered, expired, clean, unlocked worktree whose live
  path/branch/HEAD and generation marker still match, with no active lease and proven merge/closure
  eligibility; active, dirty, locked, mismatched, replaced-generation, orphaned, and unregistered
  worktrees are preserved. Apply requires explicit PR-state and active-lease files and a present,
  readable lifecycle registry; absence or corruption of any of those proofs is fail-closed. Fetch and planning use a locked lifecycle snapshot without retaining the
  registry lock; lease and lifecycle authority are revalidated at the targeted removal boundary,
  with the lifecycle lock held through that one command. Before Git removal it durably records a
  generation-bound `removal_pending` transition. Successful removal durably retires the exact
  generation before branch deletion; restart reconciliation completes only a pending transition
  and never infers removal from an ordinary missing lifecycle record. A separate explicit
  `preserve-missing` operation can mark one exact expired active generation `missing_preserved`
  when its checkout is absent; it retains the branch and path identity, blocks path reuse and
  branch retirement, and never authorizes cleanup. Branch deletion after a
  removal revalidates both the `worktree:<path>` and the `branch:<branch>` lease identity
  immediately before the irreversible delete and fails closed if either is claimed. That
  revalidation reads a foreign lease file it cannot lock, so it is a check-then-act guard, not
  mutual exclusion: a lease that first becomes active between that read and the delete is not seen.
  The removal tombstone keeps the path→branch association, so a later cleanup run still binds the
  branch to its former worktree path and preserves it while that path lease is active. The registry
  is keyed by path, so re-registering that path for a new branch carries the displaced binding
  forward on the new record (`prior_bindings`, deduplicated by branch and bounded to the 8 most
  recent) rather than dropping it. Broad `git worktree prune`
  remains report-only. The current checkout is always skipped.
  Registration, heartbeat, release, and completion resolve potentially slow live Git identity and
  generation-marker state without holding the shared lifecycle-registry lock. Each update first
  snapshots any existing target authority under a short lock, captures live path, branch, and
  generation outside it, and serializes first-time generation-marker creation with a checkout-local
  lock. It then re-reads the registry at the atomic write boundary and refuses the write if the
  target path, branch, owner, generation, or lifecycle state changed. Unrelated lifecycle writers
  therefore remain independent without weakening generation-bound, fail-closed cleanup authority.
- Stash cleanup within the same apply run only ever drops a stash it resolved as a
  `preserve-local-drift`-marked, age-eligible candidate; it never drops by a stale positional
  index. `stash@{N}` is a position in the stash reflog, not a stable name — worktree paths and
  branch names do not shift when a sibling is removed, but every drop of an earlier stash renumbers
  every later one, and (independently) capturing that selector from a `--date`-formatted listing
  can make it unresolvable to any real reflog position at all. Each candidate is instead identified
  by its stash commit hash, captured once at plan time; immediately before every drop, `janitor_apply`
  re-resolves that hash to whichever `stash@{N}` currently holds it and verifies the match. A
  candidate that cannot be re-resolved, or whose re-resolved entry no longer matches, aborts the
  remaining stash cleanup for that run with a recorded error rather than dropping a different,
  non-candidate stash.
- Resuming interrupted work: when a session breaks mid-task (quota, network, hung command, tool failure) and the tree is dirty or the branch has unmerged work, reconstruct state from git first, then continue — see `.codex/skills/resume-work/SKILL.md`.
- Closure: `verification-and-closure` resolves every AC's `Verify:` target and blocks merge if any behavioral test is missing, skipped, or xfailed.

Reuse existing passing coverage for behavior-preserving work. Add a reproducing regression test for bugs when practical and focused tests for uncovered new behavior. Several ACs may share a meaningful test; a fresh failing test is not a prerequisite for every AC.

## Source-anchor rule for backlog creation

For new backlog work, GitHub is the live tracking surface and docs provide the semantic source.

Use this split:

- owner docs, SoT docs, roadmap docs, and active plans define intent, constraints, sequencing, verification posture, validation posture, and acceptance posture
- GitHub Issues define backlog task truth; GitHub Project provides the shared board projection
- owner-doc updates are required when work is delivered and the shipped reality changes

When converting a doc item into a GitHub Issue:

1. Add a stable `Source Anchors` section to the Issue.
2. Reference the most local actionable doc item, not only a broad document path.
3. Prefer stable item IDs such as `PA2-FREEFORM` or `ORCHV2-TDD-PILOT` over prose fragments.
4. Keep the anchor stable even if the surrounding paragraph is reworded.

For an existing defect or implementation fact, an existing repository file with a descriptive
locator is also a valid source anchor: code, tests, Makefile targets, and workflow paths can locate
the evidence directly. `Source Docs` still names the normative owner authority; a factual file
reference neither becomes policy authority nor requires inventing a documentation item.

`scripts/validate_source_anchors.py` enforces existing file paths, rejects absolute paths,
traversal, directories, and symlinks escaping the repository, and resolves explicit stable IDs in
Markdown. Other locators are descriptive; path validation does not prove symbol semantics.
Changes to that validator require this owner document in the same diff.

Recommended anchor format:

- uppercase kebab-case or compact uppercase tokens
- short family prefix tied to the track or owning doc
- examples:
  - `docs/PANEL_AGENT.md :: PA2-FREEFORM`
  - `docs/ROADMAP.md :: ORCHV2-PILOT`
  - `docs/STATUS.md :: SETTINGS-PROVENANCE`

Do not rely on inline `Tracked by: #...` or `Backlog: #...` markers as the primary backlog receipt.
Those markers are now secondary convenience notes because they are not visible to other collaborators until merged.

## Delivery writeback rule

When an Issue is delivered:

1. Update the owner document to reflect the new shipped state.
2. Move the truth from the Issue into the owner doc (e.g., `STATUS.md`, roadmap sections, etc.).
3. Remove or rewrite roadmap/plan wording so it no longer reads as pending when work is delivered.
4. Keep GitHub Issue/PR history and labels as the authoritative backlog and delivery record;
   Project Status, when maintained, is a rebuildable projection.
5. If only a slice was delivered, update the parent feature issue with validation evidence and keep owner docs stable until acceptance.
6. If the work closed a larger capability, make sure the owner docs also record what verified it and what accepted it.

Owner docs are the source of shipped reality. Generated receipt pages (if adopted) may summarize Issue state from GitHub, but they do not replace the owner doc as the canonical truth for shipped behavior.
