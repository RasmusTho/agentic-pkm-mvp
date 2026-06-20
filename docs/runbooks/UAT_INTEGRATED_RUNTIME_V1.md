# Integrated Runtime v1 Golden-Path UAT Runbook

State: Active UAT runbook and scripted skeleton for the Integrated Runtime v1 release gate.
Doc role: Operator runbook / test-channel UAT
Authority: Defines the no-mock test-channel golden path for Start -> Orient -> Work -> Review -> Confirm -> Receipt -> Resume. Current runtime truth remains in `docs/STATUS.md`; environment boundaries remain in `docs/ENVIRONMENTS.md`.
Owner: Runtime / Companion UI / UAT
Temporal class: operational
Review cadence: event-driven
Last reviewed: 2026-06-12
Last verified against: docs/LOCAL_TEST_BOOTSTRAP/RUN_SCRIPTED_UAT.md, docs/ENVIRONMENTS.md, docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md, docs/STATUS.md, tests/uat/test_golden_path_integrated_runtime.py

---

## Purpose

This runbook defines the Companion-inclusive no-mock UAT path for Integrated Runtime v1. It uses the local `test` channel only: `PKM_ENVIRONMENT=test`, `app_test`, `vault-test/`, and `tmp-test/`. It must never point at the operator vault.

The scripted receipt is:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/uat -m uat_integrated_runtime
```

## Scope and Non-Goals

Core path:
- Start: health, readiness, API health, API status, and vault binding.
- Orient: Companion orientation returns a truthful read-only entry state.
- Work: governed capture appends to the test-vault inbox; Vault Browser pick re-anchors through workspace; direct human note save round-trips.
- Review: Vault Browser inspect plus `queue-review` stages a pending governed proposal with `loop_stage: queued_pending_confirmation` and no durable receipt.
- Confirm: same-origin Companion server proxy to `POST /api/panel/confirm` once route parity lands.
- Receipt: durable receipt visibility and event/receipt distinctness once Confirm is reachable.
- Resume: restart-survival of staged/confirmed state once Panel proposal/idempotency persistence lands.

Out of scope:
- Canvas/TTS/memory-review optional paths.
- Browser automation.
- Negative safety suite ownership. See [Negative Safety](#negative-safety).

## Prerequisites

Use a clean repo checkout and the **one** idempotent test-channel bootstrap —
it runs `vault init`, derives the canonical channel env (absolute paths,
host-reachable DSN, `tmp-test/` artifacts, single watcher), and fails loud on
any inconsistency, so no manual env exports are needed (issue #1997):

```bash
make bootstrap-test-channel          # config + Docker stack
# or, for the config layer only (no Docker engine):
make bootstrap-test-channel-config
```

The bootstrap is the source of truth. The explicit equivalent it replaces — kept
only for reference — is:

```bash
make test-vault-init
export PKM_ENVIRONMENT=test
export VAULT_ROOT_TEST="$(pwd)/vault-test"
export VAULT_ROOT="$(pwd)/vault-test"
export INDEX_OUTBOX_PATH="$(pwd)/tmp-test/index-outbox.jsonl"
export COMPANION_UI_URL="http://127.0.0.1:18002"
```

`make bootstrap-test-channel` self-seeds the full bring-up (it passes `VAULT_ROOT`
explicitly into `make test-start-full`), so the all-in-one path needs no shell exports.
The **standalone** steps below, however, read the caller's process env — `channel-preflight`,
`make test-start-full` run on their own, and Leg-1 `settings explain` all require the channel
env to be exported in the shell before those child processes start.

<!-- standalone host env seed -->
To seed a clean shell for those standalone host commands, either keep the reference exports
above, or export the canonical env that the bootstrap derives:

```bash
while IFS= read -r line; do
  [ -n "$line" ] || continue
  export "$line"
done < <(python -m app.cli ops bootstrap-test-channel --print-env)
```

To validate the live env at any point, run the fail-loud channel preflight (run it in a
seeded shell, per the note above):

```bash
python -m app.cli ops channel-preflight --channel test --context host
```

For a full local stack proof, start the test stack first (either via the self-seeding
`make bootstrap-test-channel`, or in a shell seeded as above):

```bash
make test-start-full
```

The scripted skeleton can also run in-process with an isolated temporary test vault:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/uat -m uat_integrated_runtime
```

## Leg 1: Start

Commands:

```bash
curl -fsS http://127.0.0.1:18002/healthz
curl -fsS http://127.0.0.1:18002/readyz
curl -fsS http://127.0.0.1:18002/api/health
curl -fsS http://127.0.0.1:18002/api/status
python -m app.cli settings-explain --json
```

Expected evidence:
- `/healthz` returns `{"ok": true}`.
- `/readyz` is running, catch-up, or degraded with explicit reason.
- `/api/health` and `/api/status` return structured runtime payloads.
- settings show `environment=test` and the vault root resolves to `vault-test/`.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_start_orient_work_review_legs`.

## Leg 2: Orient

Command:

```bash
curl -fsS http://127.0.0.1:18002/api/companion/orientation | python3 -m json.tool
```

Expected evidence:
- `scope.kind == "workspace"`.
- `scope.channel == "test"`.
- `guards.read_only == true`.
- `meta.contract_version == "workspace_orientation.v1"`.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_start_orient_work_review_legs`.

## Leg 3: Work

Commands:

```bash
curl -fsS -X POST http://127.0.0.1:18002/api/companion/capture \
  -H 'Content-Type: application/json' \
  -d '{"text":"Integrated Runtime v1 golden-path capture"}'

curl -fsS 'http://127.0.0.1:18002/api/companion/vault-browser?note_path=notes/golden-path.md'

curl -fsS 'http://127.0.0.1:18002/api/companion/workspace?note_path=notes/golden-path.md'

curl -fsS -X POST http://127.0.0.1:18002/api/companion/note/save \
  -H 'Content-Type: application/json' \
  -d '{"note_path":"notes/golden-path.md","new_body":"# Golden Path Note\n\nHuman test-channel save.\n"}'
```

Expected evidence:
- Capture writes to `Inbox/inbox.md` in the test vault and emits `capture.inbox.appended`.
- Workspace returns the picked artifact with vault identity and content hash.
- Human save preserves frontmatter and writes only the requested body change.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_start_orient_work_review_legs`.

## Leg 4: Review

Commands:

```bash
curl -fsS http://127.0.0.1:18002/api/companion/vault-browser | python3 -m json.tool

curl -fsS -X POST http://127.0.0.1:18002/api/companion/vault-browser/actions/queue-review \
  -H 'Content-Type: application/json' \
  -d '{"note_path":"notes/golden-path.md"}'
```

Expected evidence:
- Vault Browser inspect returns the test note and server-derived metadata.
- Queue review returns `state: pending_intent`, `loop_stage: queued_pending_confirmation`, `receipt_state: pending_intent_not_durable_receipt`, and `execution_path: /api/panel/confirm`.
- No durable receipt is asserted at this stage.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_start_orient_work_review_legs`.

## Leg 5: Confirm

Command, once route parity lands:

```bash
curl -fsS -X POST "$COMPANION_UI_URL/api/panel/confirm" \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id":"<from queue-review>","artifact_id":"<from queue-review>","action":"confirm","idempotency_key":"uat-confirm-1"}'
```

Expected evidence:
- The call is accepted through the Companion same-origin proxy, not by requiring the browser to call the runtime API port directly.
- Response status is `executed` or `logged`.
- `receipt_visibility == "durable_vault_visible"` and a receipt object is present.

Current gate:
- If `/api/panel/confirm` is not proxied same-origin, the scripted leg skips only while #1851 or #1875 is open.
- If those blockers are closed and the proxy remains missing, the test fails.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_confirm_and_receipt_leg`.

## Leg 6: Receipt

Commands:

```bash
curl -fsS http://127.0.0.1:18002/api/companion/vault-browser | python3 -m json.tool
```

Expected evidence:
- Receipts history/projection shows the durable receipt row for the confirmed artifact.
- `ConfirmResponse.receipt` is an accountability object.
- `ConfirmResponse.events_emitted` is a list of event trace names.
- Receipts and events are asserted distinct and not conflated.

Current gate:
- Same as Confirm: this leg skips only while #1851 or #1875 is open and the same-origin confirm path is unavailable.

Scripted coverage:
- `tests/uat/test_golden_path_integrated_runtime.py::test_confirm_and_receipt_leg`
- `tests/uat/test_golden_path_integrated_runtime.py::test_receipts_and_events_distinct`

## Leg 7: Resume

Commands:

```bash
make test-down
make test-start-full
curl -fsS 'http://127.0.0.1:18002/api/companion/workspace?note_path=notes/golden-path.md'
curl -fsS http://127.0.0.1:18002/api/companion/orientation
```

Expected evidence:
- After restart, the workspace renders the artifact truthfully.
- Pending or confirmed governance state is either still available from durable storage or explicitly absent/degraded with a truthful reason.
- Re-entry orientation renders a cold or orienting state without inventing durable authority.

Current gate:
- Panel proposal/idempotency staging is durable SQLite-backed staging.
- If durable staging is unavailable while #1877 is closed, the test fails instead of skipping.

Scripted coverage: `tests/uat/test_golden_path_integrated_runtime.py::test_resume_leg_after_restart`.

<!-- negative-safety -->
## Negative Safety

Run the governed mutation-boundary negative suite with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/uat -m uat_integrated_runtime
```

The suite proves the release gate fails safe and honestly across blocked writes,
stale source hashes, provider unavailability, missing receipt sources, wrong vault
startup, and replay/foreign intent confirmation. It must not be used to weaken
WriteGuard, receipt-source honesty, or vault isolation boundaries.

Scripted coverage: `tests/uat/test_negative_safety_integrated_runtime.py`.

Covered boundaries:
- WriteGuard blocked mutation.
- Content-hash mismatch on human save and Panel checkbox projection.
- Provider-unavailable coauthoring while capture/review/confirm remain honest.
- Missing receipt source.
- Wrong vault or wrong environment binding.
- Replay and foreign intent confirmation rejection.

## Validation

Focused UAT:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/uat -m uat_integrated_runtime
```

Repo lint for PRs that add tests:

```bash
ruff check app tests
```

Interpretation:
- Without `RUN_INTEGRATED_RUNTIME_UAT=1`, the suite is intentionally skipped.
- With `RUN_INTEGRATED_RUNTIME_UAT=1`, all golden-path legs must pass.
- Confirm/receipt legs fail if same-origin confirm route parity is missing after #1851/#1875 close.
- Resume fails if durable proposal/idempotency staging is unavailable after #1877 close.
- Negative safety must pass when opted in and must remain fail-closed around governance writes, source hashes, provider availability, receipt honesty, vault isolation, and replay/foreign intent handling.
