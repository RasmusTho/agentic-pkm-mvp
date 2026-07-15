---
name: Stream Registry and Signal Contract
description: First-class registry of every input source the Episode Resolution Engine may consume — each stream a declared contract; the engine reads the registry, never hardcoded sources
task_id: ERE-01
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: The new part — multi-stream fusion
parent_capability: Episode Resolution Engine
prerequisites: []
depends_on: []
can_parallelize_with: [Episode Note Store and Projection, Thread episode_ref into Metadata Bundle]
---

# Stream Registry and Signal Contract

## Purpose

The engine fuses *multiple* information streams, and the owner requires that **every input source is identified and part of the architecture** — not an implicit list inside the segmenter. This task makes streams first-class: a declared registry where each source is a contract entry, and the engine consumes the registry, never hardcoded sources. Adding a future stream (calendar, location, ambient audio) becomes a registry entry + adapter, not an engine change.

## What This Task Does

1. Defines the **signal contract** — the normalized shape every stream must deliver to the segmenter:
   - `stream_id` (registry key), `signal_id` (idempotency), `observed_at` (bitemporal start; `emitted_at` separate, mirroring `heimdal.observation.published.v1` bitemporality)
   - `dimensions_fed`: which of the five Episode dimensions (time / space / protagonist / goal / causation) this signal can evidence, with per-dimension confidence (per-axis, never scalar — mirrors the Heimdal confidence block)
   - `scope_binding` / sphere context when known (SSI-01 shape from `app/context_dimensions.py`)
   - `provenance_ref` back to the source record (observation id, outbox event id, note path+hash)
2. Defines the **registry entry contract** per stream: `stream_id`, `status` (`live | planned | future | excluded`), `transport` (observation-log cursor / outbox topic / file event), `consent_class` (Heimdal consent-gated vs. vault-implicit), `cadence` (bursty/continuous/sparse), `owner_constituent` (Heimdal / Mimer / external via private-bindings).
3. Ships the registry as **markdown-first settings + code mirror**, consistent with the `_heimdal/settings.md` precedent: the human-legible registry doc is the declaration surface; `app/episodes/stream_registry.py` loads and validates it fail-loud.
4. Seeds the registry with the **complete inventory** (canonical enumeration lives in the capability [README](README.md), which this registry must match 1:1):
   - **live:** `heimdal.observations` (observation-log cursor; feeds time/protagonist/goal; consent-gated), `vault.activity` (`ingest.vault.changed`/`ingest.object.created`/`ingest.object.deleted` outbox topics + `extract_context_dimensions_for_note`; feeds time/goal/causation), `calendar` (ERE-09 read-only CalDAV/ICS adapter; feeds time/protagonist/space/goal)
   - **planned:** `chat.sessions` (session log exists; ERE normalizer pending), `decision.receipts` (receipt log/projection exists; ERE normalizer pending), `kap.acquisitions` (stage-completed events exist; ERE normalizer pending), `heimdal.attention` (attention log exists; ERE normalizer pending), `bifrost.native_capture` (space/protagonist/causation enrichment per `CAPTURE_TRANSPORT_FEASIBILITY.md` "Episode richness")
   - **future:** `location`, `screen`, `biometric`, `ambient_audio` (the Heimdal v2 `modality` vocabulary — ERE-10)
   - **excluded (identified, deliberately out):** BuilderOps/LearningSignals (dev-time, not lived situations), orchestrator/planner/MCP/agent internals (machinery, not situations — the chat *session* is the lived-situation representative), sync transports (iCloud/Git — never semantic per Integration Fabric class 5), egress surfaces (notifications, TTS)

## Concretely

```
$ python -m app.cli episodes streams --json
{"streams": [{"stream_id": "heimdal.observations", "status": "live", "transport": "observation_log", ...}]}
$ python -m app.cli episodes streams --validate   # fail-loud on malformed registry doc
```

## Why This Matters

Without a registry, every new source silently reshapes the segmenter, streams escape consent/scope classification, and "which inputs does the engine watch?" has no authoritative answer. The registry is also where the excluded list lives — sources are *identified and ruled out*, never merely absent.

## Acceptance Criteria

- [ ] AC1: A signal-contract schema exists and validates the normalized signal shape (bitemporal, per-dimension confidence, provenance ref). Verify: `tests/episodes/test_stream_registry.py::test_signal_contract_validates_required_shape`
- [ ] AC2: The registry loads from the markdown-first declaration, fail-loud on missing/malformed entries (no silent default streams). Verify: `tests/episodes/test_stream_registry.py::test_registry_fails_loud_on_malformed_declaration`
- [ ] AC3: Every seeded `live` entry names a transport that exists in the runtime (observation-log consumer path or a registered outbox topic in `app/events/types.py`); registry validation rejects a live entry with an unknown transport. Verify: `tests/episodes/test_stream_registry.py::test_live_streams_bind_to_existing_transports`
- [ ] AC4: The registry carries the four status classes and the seeded inventory matches the capability README's inventory table 1:1 (including the excluded list). Verify: `tests/episodes/test_stream_registry.py::test_registry_matches_readme_inventory`
- [ ] AC5 (enforcement): the engine's stream-consumption entrypoint enumerates sources **only** via the registry — asserted at the production call site, not just unit-tested on the registry module. Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams` (asserts the segmenter entrypoint resolves its consumers through `stream_registry`, with an unregistered-source attempt rejected)
- [ ] AC6: Registry doc + contract doc written (`docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory` is the canonical human surface; the runtime declaration mirrors it). Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_stream_registry.py
pytest -q -m "not pg"
```

AC5's call-site assertion lands with a stub segmenter entrypoint if ERE-04 has not merged yet (the entrypoint contract is this task's deliverable; ERE-04 fills the body).

## Out of Scope

Segmentation logic (ERE-04); building the calendar/location adapters (ERE-09/ERE-10); any Heimdal-side change (Heimdal's per-session `episode_id` is consumed as-is).

## Related Docs

- [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) — placement + seam
- [Research grounding](../research/EPISODE_RESOLUTION_ENGINE.md) §The new part: multi-stream fusion
- `docs/EVENTS.md` §Outbox envelope + consumer contract; `schemas/events/heimdal.observation.published.v1.schema.json`
- `docs/INTEGRATION_FABRIC_CONTRACT.md` (class taxonomy the excluded list leans on)

## Related GitHub Issues

One issue: `[Episode Resolution Engine] stream-registry: every input source declared, classified, and consumed via contract`. Ready immediately (no prerequisites).
