State: Working strategy for human-need-first acceptance and system-level TDD.
Doc role: Plan
Authority: Coordination guidance for translating human flows into executable UAT without collapsing baseline verification and target-state acceptance into one test gate.

# Human Need UAT Strategy

## Purpose

This document explains how the repo should validate the intended product behavior without confusing it with the currently locked runtime baseline.

It exists to prevent two opposite mistakes:
- shrinking human-need scenarios until they only test today's implementation seams
- turning future-facing human-need scenarios into immediate smoke failures before the system claims to support them

## Core rule

Human need is the primary acceptance source.

Use:
1. `docs/HUMAN-FLOWS.md` for the human problem and user-visible outcome
2. `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` for the scenario framing and acceptance signals
3. `docs/STATUS.md` for whether the current baseline actually claims the capability today
4. `docs/TESTING.md` for gate posture and CI classification

Do not start from current agents, queues, or event paths and work backward into a fake user story.

## Two-track validation model

### 1. Baseline verification

Purpose:
- prove the currently claimed runtime baseline still works

Typical examples:
- watcher -> panel -> promotion chain
- operator-safe enablement signals
- ingest -> index -> ASK sanity
- idempotence, write-guard, and provenance checks already claimed by the baseline

Gate posture:
- blocking in smoke, integration, or release UAT when the baseline requires it

Failure meaning:
- current supported behavior regressed

### 2. Human-need acceptance

Purpose:
- prove the system is becoming useful for the human situations it is meant to support

Typical examples:
- return after interruption and recover orientation
- use archive material without forcing note conversion
- keep commitments trustworthy over time
- move from notes and sources to a shippable output while preserving provenance

Gate posture:
- often non-blocking at first
- may run nightly or on-demand
- graduates into release/blocking posture only when `docs/STATUS.md` or equivalent SoT documents claim the capability as part of the active baseline

Failure meaning:
- target-state gap or partial implementation, not necessarily a regression in the active baseline

## Scenario posture vocabulary

Every major human-need scenario should carry two posture labels.

### Implementation posture

- `baseline`: the active runtime claims this scenario strongly enough that it should pass as part of the supported system behavior
- `partial`: the runtime supports part of the scenario, but the full human outcome is not yet assured
- `future`: the scenario is accepted as a product requirement, but the runtime does not yet claim it

### Test posture

- `smoke`: fast blocking verification for active baseline behavior
- `nightly`: broader recurring regression coverage, may still be non-blocking
- `non-blocking acceptance`: executable system-level TDD against human needs
- `release gate`: blocking UAT for capabilities the active baseline claims to support

## Promotion rule

A scenario should move toward stricter gates in this order:

1. human-first scenario exists in docs
2. scenario has observable pass criteria
3. scenario has an executable seeded/scripted flow
4. scenario is run as non-blocking acceptance
5. status/baseline docs claim the capability
6. scenario becomes release-gated or smoke-gated

Do not skip directly from "important human need" to "smoke blocker" unless the current baseline truly claims it.

## Guidance for agents and contributors

When proposing or editing tests:
- ask first which human need is being exercised
- define user-visible success before internal assertions
- record whether the scenario is `baseline`, `partial`, or `future`
- choose the gate posture explicitly instead of inheriting smoke by default

When proposing implementation work:
- use human-need acceptance scenarios as system-level TDD pressure
- do not rewrite the scenario to fit the current architecture
- do not treat failure in a `future` or `partial` scenario as proof that baseline behavior is broken

When updating status/baseline docs:
- promote scenarios into blocking gates only when the implementation and operator story are ready
- make that promotion explicit so other agents know the capability is now claimed

## Initial recommended scenarios

Good first candidates for non-blocking human-need acceptance:
- return after interruption and recover orientation
- work with archive material without forcing it into notes
- keep commitments trustworthy over time

These scenarios are broad enough to pressure architecture and product decisions without pretending they already belong in smoke.
