---
name: Zone Projection Envelope
description: Wrap the existing frontmatter-preferred/path-derived Vault Browser zone in the #1488 source/authority_role/provenance/degradation envelope.
task_id: TOPOZONE-01
state: delivered — #1554 / PR #1558
source_anchor: docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Runtime topology authority decision (#1488)
parent_capability: TOPOLOGY_AWARE_ZONE_PROJECTION
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Zone Projection Envelope

## Purpose

The #1488 decision requires any topology-derived Vault Browser field to describe its `source`, `authority_role`, `provenance`, and `degradation`. This task made the existing projection self-describing without inventing a new source.

## What This Task Does

In the Vault Browser API metadata projection (`app/api/routes/companion.py::_parse_note_artifact_metadata`, which already takes `path_derived_zone` from `::_zone_for_path`), add an additive envelope alongside the existing `zone` value:

- `source` — the source used to derive the zone for this artifact: `frontmatter.zone` when present, else `vault_path_segment`.
- `authority_role` — `durable_vault_metadata` when `zone` came from frontmatter; `runtime_projection` when it came from the path fallback; `unavailable` when neither yields a value.
- `provenance` — the concrete derivation: the frontmatter key (`frontmatter.zone`) or the vault-relative first path segment used.
- `degradation` — `none` when frontmatter `zone` was present and valid; `frontmatter_absent` when falling back to path; `frontmatter_invalid` when frontmatter failed to parse and the path fallback was used.

The existing `zone` string value and existing zone filter behavior (`_FILTER_FIELDS`, `_note_matches_filters`) stay unchanged. The envelope is purely additive metadata on the artifact projection. No frontmatter is rewritten; no schema changes.

## Concretely

For a note with frontmatter `zone: active`:

```json
{ "zone": "active",
  "zone_source": "frontmatter.zone",
  "zone_authority_role": "durable_vault_metadata",
  "zone_provenance": "frontmatter.zone",
  "zone_degradation": "none" }
```

For a note at `Projects/Foo/note.md` with no frontmatter `zone`:

```json
{ "zone": "Projects",
  "zone_source": "vault_path_segment",
  "zone_authority_role": "runtime_projection",
  "zone_provenance": "vault_path[0]=Projects",
  "zone_degradation": "frontmatter_absent" }
```

(Exact field naming/nesting is an implementation choice; flat `zone_*` or a nested `zone_projection` object are both acceptable as long as all four envelope dimensions are present and reconstructible.)

## Why This Matters

Without the envelope, a path-derived guess looks identical to a durable human-authored zone — exactly the "hidden semantic authority" the #1488 decision and §4.1 forbid. The envelope is the contract precondition for any later UI ordering/overlay and for any future real topology source.

## Acceptance Criteria

- [ ] The Vault Browser artifact metadata projection includes `source`, `authority_role`, `provenance`, and `degradation` for `zone`, additive to the existing `zone` value. Verify: `tests/api/test_companion_vault_browser.py::test_zone_projection_envelope_frontmatter` asserts the envelope on a frontmatter-`zone` note.
- [ ] Path-fallback notes report `authority_role=runtime_projection`, `source=vault_path_segment`, and `degradation=frontmatter_absent`. Verify: `tests/api/test_companion_vault_browser.py::test_zone_projection_envelope_path_fallback`.
- [ ] Malformed-frontmatter notes that fall back to path report `degradation=frontmatter_invalid` and still degrade to the path posture (no fabricated zone). Verify: `tests/api/test_companion_vault_browser.py::test_zone_projection_envelope_malformed_frontmatter`.
- [ ] The existing `zone` value and zone filter behavior are unchanged. Verify: existing Vault Browser zone-filter tests still pass with no assertion changes.

## How to Verify (Pre-Merge)

Local:
- `pytest tests/api/test_companion_vault_browser.py -k "zone_projection_envelope or zone_filter"` passes.
- Manual: hit the browser list/detail endpoint against a fixture vault containing one frontmatter-`zone` note, one path-fallback note, and one malformed-frontmatter note; confirm the envelope values match the table above.

CI:
- Standard backend test job runs the above test module.

## Out of Scope

- Any new topology source (registry/graph/semantic). The only sources here are existing frontmatter and path.
- UI changes (that is `SURFACE_ZONE_SIGNALS_IN_BROWSER_UI`).
- Changing the `zone` frontmatter schema or the zone filter contract.
- Zone-based ordering/ranking.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` → "Runtime topology authority decision (#1488)"
- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` §4.1
- Code: `app/api/routes/companion.py::_parse_note_artifact_metadata`, `::_zone_for_path`

## Related GitHub Issues

Delivered by #1554 / PR #1558.
