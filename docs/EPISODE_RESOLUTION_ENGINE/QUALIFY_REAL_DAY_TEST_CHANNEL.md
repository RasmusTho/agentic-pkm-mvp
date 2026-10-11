---
name: Source-authorized real-day test-channel profile
description: Define and implement the fixed ERE qualification profile for one real operator day, with registered-source admission and bounded effects.
task_id: ERE-13
github_issue: 6002
source_anchor: "docs/EPISODE_RESOLUTION_ENGINE/README.md :: Capability acceptance criteria"
parent_capability: Episode Resolution Engine
prerequisites: [ERE-09, "native qualification operation in #5969"]
depends_on: [CALENDAR_STREAM_ADAPTER.md]
can_parallelize_with: []
---

# Source-authorized real-day test-channel profile

## Purpose

The ERE parent requires live validation on a real day, while the native web qualification runner is being built around a fixed profile set. This task adds one explicit ERE profile to that runner after #5969 delivers the native qualification operation and its finite admission/effect/evidence path, without expanding general execution authority or treating fixture evidence as a real-day result.

## What This Task Does

Add a fixed, source-authorized ERE profile to the existing native qualification operation after #5969 delivers the native qualification operation and its finite admission/effect/evidence path. The profile describes and admits only the current registered live sources: `heimdal.observations`, `vault.activity`, and `calendar`. It does not activate the planned native-capture stream; voice-originated evidence enters only through the registered Heimdal observation path.

The profile binds one run to the admitted immutable candidate (source SHA and image digest), TEST channel, isolated test vault/binding, exact Heimdal consent/source binding, exact read-only iCloud CalDAV binding, bounded local calendar day (`Europe/Stockholm`), and one operation ID. The private-bindings owner supplies the configured `CALDAV_CALENDARS_JSON` entry (or the existing single-calendar `CALDAV_*` form) with calendar ID, endpoint, username, app-specific password, calendar path, and scope mapped to that same TEST vault; the test actor and receipts never receive the password. Record opaque binding IDs, source counts, time bounds, and content-free evidence references; never copy credentials, event descriptions, private notes, or raw observations into issue/PR/JUnit artifacts.

The automated test actor may invoke the existing ERE tick/qualification entrypoint and inspect its bounded outputs. Its effect inventory is limited to source reads and the already-guarded test-vault Episode proposal/closure writes, pending `episode_ref` changes, and rebuildable projection/outbox effects that the existing ERE contract requires. It cannot write calendar data, alter source observations, accept/promote knowledge, delete user data, mutate a human re-cut, or operate outside the admitted test binding. All durable writes must pass the production WriteGuard seam; refusal must occur before any effect when candidate, source binding, consent, scope, or channel admission is missing or mismatched.

The real-day profile must preserve per-binding isolation. No episode, binding, or derived decay may combine records from different vault/scope bindings without the existing explicit CrossScopeFlow path and receipt. Human re-cut remains terminal for machine mutation. Probes for missing admission, cross-scope refusal, WriteGuard invocation, and re-cut preservation use clearly labeled synthetic controls in the isolated test resources; they are separate evidence from the actual-day result and cannot satisfy the parent's real-day acceptance criterion.

This task delivers the profile and its deterministic refusal/guard tests. The operator's real-day execution and acceptance receipt remain a separate post-merge action on #3175, requiring the already-qualified TEST channel and currently authorized private bindings. This issue grants no access, secret, deployment, or real-day execution authority.

## Concretely

A qualifying profile execution is conceptually:

```text
native qualification operation <operation-id>
  profile = episode-resolution.real-day.v1
  candidate = <admitted source SHA + image digest>
  channel = test
  local_day = <one completed Europe/Stockholm day>
  bindings = <one TEST vault + authorized Heimdal source + read-only calendar>
  actor = bounded qualification test actor
```

The runner refuses before the first source read or write if any binding or admission field is absent or inconsistent. A passing profile receipt records the operation and candidate identities, opaque binding IDs, day/time bounds, per-source read counts, expected guarded write classes, outcome counts, and content-free provenance references. A fixture-only run may validate the profile machinery but is labeled `synthetic-control` and never counts as real-day acceptance. If no currently authorized read-only TEST calendar binding exists, the minimum operator action is to select one iCloud calendar and configure its app-specific password through the existing private-bindings owner path, mapping it to the TEST vault scope; do not create a new account, widen access, paste a secret into the repo, or run until admission is read back.

## Why This Matters

Without a fixed profile, the runner cannot prove the ERE's source and effect boundaries. If a fixture is allowed to stand in for a real day, or if a profile silently widens source admission, the parent could close without evidence for its actual acceptance claim or could read/write outside the intended vault scope.

## Acceptance Criteria

- [ ] AC1: The existing qualification runner admits only the fixed ERE profile and its three registered live sources; planned, future, excluded, unknown, or unbound sources are refused before effects. Verify: `tests/ops/test_native_web_acceptance.py::test_ere_profile_admits_only_registered_live_sources`
- [ ] AC2: The production qualification entrypoint binds a run to one exact admitted candidate, TEST channel, operation ID, `Europe/Stockholm` day, and the exact vault/Heimdal/calendar bindings; missing or mismatched admission refuses before source access or writes. Verify: `tests/ops/test_native_web_acceptance.py::test_ere_profile_refuses_incomplete_or_mismatched_source_binding`
- [ ] AC3: All permitted durable ERE effects flow through the production WriteGuard seam, and calendar/source records are read-only; the test actor cannot write, delete, accept, or promote source knowledge. Verify: `tests/ops/test_native_web_acceptance.py::test_ere_profile_effect_inventory_is_guarded_and_source_read_only`
- [ ] AC4: Cross-scope records remain separated absent the existing CrossScopeFlow receipt, and an existing human re-cut is not overwritten by the qualification tick; synthetic negative controls are labeled separately from real-day evidence. Verify: `tests/ops/test_native_web_acceptance.py::test_ere_profile_preserves_scope_and_human_recut_boundaries`
- [ ] AC5: The profile, source-to-binding map, test-actor limits, expected effects, and synthetic-versus-real evidence rule are documented in this task and reflected in the parent execution map. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Implementation tasks (execution order)`

## How to Verify (Pre-Merge)

Run the four named profile tests through the existing qualification runner's production call site after #5969 delivers the native qualification operation and its finite admission/effect/evidence path. Verify missing/mismatched admission has zero source reads and zero writes; permitted writes invoke WriteGuard; synthetic controls are explicitly marked and cannot emit the parent's real-day acceptance receipt. Run the applicable focused ERE test files and required CI for the diff. Do not run against a live TEST binding as part of PR verification.

The parent-level real-day operation is performed only after the channel and source bindings are currently qualified and admitted under their existing owners. It uses the exact merged candidate and one completed local day, posts only sanitized evidence to #3175, and remains independent from these deterministic tests.

## Out of Scope

- Changing the registered source inventory, enabling the planned native-capture stream, or adding another ERE source.
- Altering the #5969 runner's general admission, deployment, browser, model, or channel authority.
- Obtaining, creating, rotating, or reading a private credential outside the authorized service binding; writing calendar data; or executing against PROD.
- Using fixture data as a substitute for the actual-day receipt.
- Accepting/promoting Episode notes, changing owner-doc shipped claims, closing #3175, or running the real-day operation in a PR/test fixture.

## Related Docs

- [Episode Resolution Engine](README.md) — registered-source inventory, cross-task invariants, and parent acceptance.
- [Calendar Stream Adapter](CALENDAR_STREAM_ADAPTER.md) — read-only CalDAV/ICS and private-binding contract.
- [Human re-cut](RESPECT_HUMAN_RECUT.md) — machine-terminal human edits.
- `docs/TESTING.md :: CI Roles` — deterministic versus post-merge native evidence.
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Build-once / promote model` — immutable candidate identity.
- #3175 — live feature acceptance hub; #5969 — native qualification operation and finite admission/effect/evidence path.

## Related GitHub Issues

Child of #3175. Hard prerequisite: #5969 must merge the native qualification operation and its finite admission/effect/evidence path. A real-day receipt remains parent acceptance evidence, not this child issue's pre-merge test result.
