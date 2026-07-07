---
name: Location Stream Future Posture
description: Location (space dimension) is a declared-future registry entry delivered through Heimdal's v2 modality vocabulary — posture fixed now so no other task designs around its absence wrongly
task_id: ERE-10
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: Suggested build order (step 3)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-01]
depends_on: [STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md]
can_parallelize_with: []
---

# Location Stream Future Posture

## Purpose

Space is the one Episode dimension no live or planned-near-term stream feeds (v1 voice lacks it; calendar gives only location *text*). This posture file fixes *how* location will arrive — so the registry carries it as identified-and-classified rather than absent, and so no other task invents a competing path. **This is a spec-only posture task: it ships no adapter and gets no implementation issue until its trigger fires.**

## What This Task Does (when triggered)

1. **Delivery path is Heimdal, not a Mimer adapter.** Location is a capture modality in the Heimdal v2 vocabulary (`modality ∈ speech, later screen, location, biometric, ambient_audio` — FABLE_COMPANION). Device geolocation is *sensing of reality* → it enters as consent-gated Heimdal observations over the existing observation-log transport, and the ERE consumes it through the already-live `heimdal.observations` registry entry (possibly as a modality-filtered sub-entry). No new Mimer-side transport.
2. **Consent class**: location is continuous-sensing-adjacent — it inherits Heimdal's consent posture (opt-in per place/session; OFF by default; D-CONSENT), stricter than calendar. The registry entry pins `consent_class: heimdal_gated` now.
3. **Registry now**: `location` sits in the registry as `status: future`, `owner_constituent: heimdal`, `dimensions_fed: {space: high, time: medium}` — identified, classified, unbuilt.
4. **Trigger to activate**: Heimdal v2 ships a location-modality capture (Posture B/Bifrost-native work, Epic B lineage) → this file converts to an implementation task (mostly: modality filter + space-dimension confidence wiring; the fusion core is unchanged by construction).

## Concretely

```
$ python -m app.cli episodes streams --json | jq '.streams[] | select(.stream_id=="location") | .status'
"future"
```

## Why This Matters

Leaving space unfed *implicitly* invites someone to bolt location onto the wrong seam (a Mimer poller against device APIs would bypass Heimdal's consent ledger entirely — a privacy-posture violation). Declaring the path now costs one registry entry and prevents that.

## Acceptance Criteria

- [ ] AC1: the registry carries `location` as `future` with the Heimdal delivery path and consent class declared (lands with ERE-01's seed; this file is the posture authority). Verify: `tests/episodes/test_stream_registry.py::test_registry_matches_readme_inventory` (covers the future entries)
- [ ] AC2: this posture file exists and names the activation trigger. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/LOCATION_STREAM_FUTURE_POSTURE.md :: Trigger to activate`

## How to Verify (Pre-Merge)

Covered by ERE-01's test run; no separate code.

## Out of Scope

Everything runtime. Building location capture (Heimdal v2 / Bifrost epic); screen/biometric/ambient_audio postures (same pattern, declared in the registry as future by ERE-01, activated the same way).

## Related Docs

- `docs/HEIMDAL/FABLE_COMPANION.md` (modality vocabulary); `docs/HEIMDAL/OWNER_DECISIONS.md` D-CONSENT
- `docs/BIFROST/CAPTURE_TRANSPORT_FEASIBILITY.md` ("Episode richness" — native capture as space/protagonist enrichment)

## Related GitHub Issues

**None now, by design.** An implementation issue is minted from this file when the Heimdal v2 location modality lands (trigger above). The capability does not block on it.
