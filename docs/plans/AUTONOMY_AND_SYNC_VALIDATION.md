State: Delivered
Doc role: Plan
Authority: Docs-first capability plan for low-risk autonomy posture and automated multi-device sync/latency validation.
Owner: Runtime / interaction automation
Temporal class: strategic
Review cadence: on delivery or regression
Source of truth: mixed
Last reviewed: 2026-04-19
Last verified against: docs/HUMAN-FLOWS.md, docs/PANEL_AGENT.md, docs/STATUS.md, docs/ENVIRONMENTS.md, docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md, current repo state on 2026-04-19
# Low-Risk Autonomy And Sync Validation

## Purpose

Define a bounded forward path for two related needs:

- increase cognitive offloading by letting the runtime make and surface low-risk autonomous proposals by default
- prove the end-to-end multi-device sync chain automatically, including iCloud propagation and watcher/runtime reaction latency

This plan exists so the repo can move from wording cleanup to bounded implementation issues without
re-arguing the intended direction each time.

## Scope

This plan covers:

- the autonomy posture for low-risk proposal generation versus higher-risk artifact mutations
- the AI-panel proposal surface as the first concrete interaction path for autonomous suggestions
- the test/verification posture for measuring sync latency across a real multi-device chain
- the capability breakdown from docs to feature issue and child slices

## Out of Scope

This plan does not:

- claim that the current runtime already performs general autonomous execution across the system
- relax current write-safety, provenance, or idempotency requirements for risky mutations
- define a universal risk taxonomy for every future tool/action surface
- replace the existing local test bootstrap plan or the real-vault acceptance work for PanelAgent

## Delivery receipt

Delivered and closed 2026-04-13 to 2026-04-18.

- **#355** — parent feature closed COMPLETED 2026-04-13; policy/contract, panel proposal, sync trace, and multi-device harness slices delivered.
- **#380** — real-device sync validation run executed and acceptance receipt attached 2026-04-18; end-to-end iCloud propagation and watcher/runtime reaction latency verified against the acceptance criteria.

The capability anchors below describe the architecture as shipped. Forward-looking language in this document refers to the design intent that was implemented, not to pending work.

## Working interpretation

Low-risk autonomy in this repo means:

- the runtime may generate useful proposals, suggestions, or bounded trivial actions without forcing a human approval step every time
- stronger guardrails remain required when a write or transition could damage artifact value, continuity, provenance, or user trust
- the policy boundary should be explained in terms of artifact risk, not in terms of whether a machine acted at all

This keeps the human-flow contract honest: cognitive offloading requires autonomous help, but
governed mutation still matters where the downside is materially higher.

## Capability anchors

### AUTO-LOW-RISK-AUTONOMY

The runtime should treat low-risk cognitive offloading as a first-class goal rather than as an
exception to a human-in-the-loop default. The intended posture is:

- autonomous proposals are normal where artifact-risk is low
- visible receipts and provenance remain required
- stronger confirmation, policy checks, or blocked execution remain reserved for higher-risk writes

### AUTO-PANEL-PROPOSAL-SURFACE

The first concrete interaction surface for this posture is the AI panel:

- the system may add proposed unchecked checkbox actions when note context suggests a plausible next step
- proposal writeback should be cheap enough to reduce cognitive overhead in everyday inbox and note-hygiene flows
- proposal generation should not be artificially constrained to only the explicit instruction/no-checkbox case if the action remains low-risk and traceable

### AUTO-RISK-BASED-GUARDRAILS

Guardrails should scale with artifact risk:

- low-risk proposals and comparable trivial assistance should optimize for speed and offloading
- mutations that alter standing, identity, provenance-bearing metadata, or other durable artifact semantics should continue to use tighter policy and write-safety controls
- the runtime should make the effective policy legible through status, receipts, or diagnostics rather than through opaque silent skips

### AUTO-SYNC-LATENCY-HARNESS

Multi-device sync verification should become an automated harness, not a manual stopwatch exercise.
The harness should capture at least these timestamps:

- source edit time on device A
- file-visible arrival time on device B
- watcher detection time on device B
- downstream runtime completion time on device B

Primary measurements:

- sync transport latency
- watcher detection latency
- runtime action latency
- end-to-end latency

### AUTO-SYNC-EVIDENCE

The first acceptance target is not a benchmark vanity dashboard. It is a repeatable verification path
that can answer:

- did the change propagate
- did the watcher detect it
- did the intended panel/ingest path execute
- how long did each stage take

The initial evidence surface may be CLI or machine-readable logs; a richer dashboard is optional
follow-up work.

## Feature breakdown (as executed)

Delivered as one parent feature issue (#355) plus child slices:

1. policy/contract slice — low-risk versus artifact-risk guardrail boundary encoded in owning docs and status surfaces
2. panel proposal slice — AI-panel proposal writeback hardened for low-risk suggestion flows
3. sync trace slice — machine-readable timestamps captured across watcher/runtime stages for changed notes
4. multi-device harness slice — automated test/harness for real sync-chain latency runs
5. acceptance/evidence slice — repeated multi-device trials run; latency evidence attached to #355 via #380

## Verification path

Slice-level verification should stay bounded:

- policy/contract slice: docs consistency + targeted contract tests where policy is surfaced in code
- panel proposal slice: focused e2e coverage around suggested checkbox writeback and policy routing
- sync trace slice: regression coverage for emitted timestamps / structured summaries
- multi-device harness slice: scripted run that emits machine-readable latency results without manual timing

## Validation / acceptance path (met)

Parent feature #355 accepted and closed 2026-04-13. Acceptance criteria met:

- documented low-risk autonomy posture matches owner docs and current runtime claims
- runnable automated sync/latency harness delivered against the supported test path
- repeated end-to-end evidence from a real multi-device chain attached via #380 (iCloud-backed propagation included)
- owner-doc promotion completed with this update

## Relationship to existing docs

- `docs/HUMAN-FLOWS.md` owns the human-facing autonomy intent and cognitive offloading rationale
- `docs/PANEL_AGENT.md` owns the AI-panel interaction contract
- `docs/STATUS.md` owns current runtime truth and should not claim broader autonomy before acceptance
- `docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md` owns the canonical local test bootstrap path that this harness should build on

