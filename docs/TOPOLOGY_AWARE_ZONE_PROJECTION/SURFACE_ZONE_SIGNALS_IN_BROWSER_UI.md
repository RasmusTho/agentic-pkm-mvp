---
name: Surface Zone Signals In Browser UI
description: Surface the zone source/authority/provenance/degradation envelope in the Vault Browser UI, with any zone ordering/overlay surfacing its contributing signal.
task_id: TOPOZONE-02
source_anchor: docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md :: 4.3 VaultQuery
parent_capability: TOPOLOGY_AWARE_ZONE_PROJECTION
prerequisites: [TOPOZONE-01]
depends_on: [ZONE_PROJECTION_ENVELOPE.md]
can_parallelize_with: []
---

# Surface Zone Signals In Browser UI

## Purpose

Once the API describes where each `zone` came from (TOPOZONE-01), the Vault Browser UI must make that legible so the human can tell a durable, human-authored zone from a path-derived guess. This is the §2 "expose uncertainty" / "keep attention-state visible" obligation applied to zone.

## What This Task Does

In the Companion UI Vault Browser surface, render the zone envelope from the API:

- Show the `zone` value as today, but visibly mark when its `authority_role` is `runtime_projection` (path-derived) versus `durable_vault_metadata` (frontmatter).
- Make the `provenance` and `degradation` state inspectable (e.g. tooltip / detail line), so a `frontmatter_absent` / `frontmatter_invalid` zone is not presented as authoritative.
- If — and only if — this task introduces any zone-based ordering or overlay, the response/UI must surface the contributing signal, its deterministic rule, provenance, and degradation per §4.3. Opaque semantic ranking stays out of scope; deterministic filters remain the default.

The UI reads the server-declared envelope; it must not re-derive zone authority locally.

## Concretely

- A note with frontmatter `zone: active` renders its zone as a normal, durable signal.
- A note whose zone is path-derived renders with a clear "derived from path" affordance and, on inspect, shows `provenance: vault_path[0]=Projects`, `degradation: frontmatter_absent`.
- No new ordering is introduced by default; if a zone overlay is added, it shows "ordered by: shared zone (path-derived, frontmatter absent)" rather than an unexplained position.

## Why This Matters

If the UI flattens path-derived and frontmatter zones into the same chip, the envelope from TOPOZONE-01 is wasted and zone silently becomes hidden authority — the exact failure §4.1 and #1488 prohibit.

## Acceptance Criteria

- [ ] The Vault Browser UI visibly distinguishes a `durable_vault_metadata` zone from a `runtime_projection` (path-derived) zone. Verify: `companion-ui` test asserting the two render states differ (e.g. `companion-ui/tests/vault_browser_zone_signal.test.*`).
- [ ] The zone `provenance` and `degradation` are inspectable in the UI for a path-fallback note. Verify: same test asserts the provenance/degradation surface is present for a `frontmatter_absent` note.
- [ ] The UI reads the server envelope and does not locally re-derive zone authority. Verify: reviewer confirms no client-side zone source/authority computation; test fixture drives state purely from API payload.
- [ ] Any zone-based ordering/overlay introduced surfaces its contributing signal/provenance/degradation; if none is introduced, the task adds none. Verify: ordering test asserts surfaced signal, or reviewer confirms no ordering was added.

## How to Verify (Pre-Merge)

Local:
- Companion UI test suite for the Vault Browser zone signal passes.
- Render the Vault Browser against a fixture payload containing a frontmatter-zone note and a path-fallback note; confirm the two are visibly distinguishable and the path one exposes provenance/degradation on inspect. (Companion UI render is pure HTML; a static render + browser preview is acceptable when a live runtime is unreachable.)

CI:
- Standard companion-ui test job runs the zone-signal test.

## Out of Scope

- Backend envelope derivation (delivered by TOPOZONE-01).
- Any new topology source (registry/graph/semantic).
- Semantic/vector ranking or graph-primary browser UI.
- Changing the `zone` frontmatter schema.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- Prerequisite: [ZONE_PROJECTION_ENVELOPE.md](ZONE_PROJECTION_ENVELOPE.md)
- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` §2, §4.3
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` → "Runtime topology authority decision (#1488)"

## Related GitHub Issues

Implements `TOPOLOGY_AWARE_ZONE_PROJECTION/SURFACE_ZONE_SIGNALS_IN_BROWSER_UI`. One bounded Companion UI issue; `agent:blocked` until TOPOZONE-01 lands, then promote to `agent:ready`. The final child carries the #1473 parent-closure handoff.
