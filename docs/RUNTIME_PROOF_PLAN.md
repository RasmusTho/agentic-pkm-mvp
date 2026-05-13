State: Draft runtime proof plan for establishing first stable operational baseline before legacy cleanup decisions.
Doc role: Reference
Authority: Operational verification plan for proving the current runtime baseline; does not authorize legacy deletion on its own.

# Runtime Proof Plan

## Purpose

This plan defines the minimum runtime proof required to establish operational confidence in the current system baseline. The goal is to prove core runtime paths behave correctly under normal local operation before any cleanup decisions are made.

## Relationship to legacy cleanup

Runtime proof must precede any legacy deletion discussion.

Passing this plan is evidence that current baseline behavior works; it is not proof-of-non-use for legacy code, and it does not by itself authorize deleting old pathways.

Legacy cleanup requires separate evidence about reachability, dependency impact, and migration safety.

## Minimal operational baseline

The baseline is considered proven when all checks below pass in a clean local run:

1. Startup and runtime bootstrap
- System starts via the supported startup path without manual patching.
- Runtime verification command exits successfully.
- Required core services report healthy status.

2. API health and status surfaces
- Health endpoints report expected liveness/readiness.
- Status surface returns expected runtime metadata for operator checks.
- No critical startup contract failures are present in status output.

3. Watcher detection path
- A vault change is detected by the watcher path in normal operation.
- Detection emits the expected ingest/event trigger signal.
- Detection does not require ad hoc or dev-only flow overrides.

4. Event and outbox creation
- A new ingest-relevant change results in a persisted event/outbox record.
- Persisted record contains enough metadata for worker handoff.
- Event creation is observable through supported runtime receipts/log surfaces.

5. Worker consumption and completion
- Worker consumes created outbox work item(s).
- Processing completes without poison/retry loops in baseline scenario.
- Post-consumption observable state indicates successful completion.

6. Settings source correctness
- Runtime reports effective settings source according to precedence rules.
- Effective values used by runtime align with expected startup environment.
- Settings explain/status surfaces are consistent with each other.

7. Write guard behavior
- Non-authorized write attempts are blocked with explicit guard response.
- Allowed write paths succeed and produce expected receipts.
- Guard outcomes are visible in operator-observable surfaces.

8. Minimal ASK / panel / canvas happy paths
- ASK request succeeds for a known test case and returns bounded result.
- Panel happy-path action executes under current action policy.
- Canvas happy path (when enabled) performs the minimal expected interaction without bypassing guardrails.

## Verification receipt expectations

For each baseline checkpoint, record:

- Command or action executed
- Timestamp
- PASS/FAIL result
- Primary evidence pointer (status output, log fragment, or receipt reference)

Capture evidence as operational receipts suitable for later comparison runs.

## Suggested execution sequence

1. Reset/prepare local runtime state using supported workflow.
2. Start full system using canonical startup path.
3. Run runtime verification command.
4. Execute the eight baseline checkpoints above in order.
5. Record a single consolidated proof run summary with explicit PASS/FAIL outcomes.

## Non-goals

- Creating new runtime-proof scripts in this slice.
- Performing dynamic proof-of-non-use analysis for legacy deletion.
- Refactoring or deleting runtime code paths.

## Runnable proof command

Run:

```bash
python3 scripts/runtime_proof_smoke.py
```

This command generates two receipts under `tmp/runtime-proof/`:

- `runtime-proof-receipt-<timestamp>.json` (machine-readable)
- `runtime-proof-receipt-<timestamp>.md` (human-readable)

The receipt always contains baseline coverage for all required checkpoints and one explicit gate line for #867:

- `UNBLOCK LEGACY CLEANUP AUDIT: #867`
- `KEEP LEGACY CLEANUP AUDIT BLOCKED: #867`

## How to run

1. Optional: start local runtime first for live endpoint checks:

```bash
scripts/start_full_system.sh
```

2. Execute the smoke proof command:

```bash
python3 scripts/runtime_proof_smoke.py
```

3. Open the generated markdown receipt and confirm:

- every baseline checkpoint is `pass`, `fail`, or `skip` with reason
- overall status is clearly `PASS` or `FAIL`
- the #867 gate line is present exactly once

By default, skipped checks are blocking and keep the overall receipt at `FAIL`. Use `--allow-skips-to-pass` only when you intentionally want a non-gating informational run.
