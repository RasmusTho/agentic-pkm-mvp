---
name: Registry-Driven Adapter Dispatch
description: Generalize run_segmentation_tick from hardcoded per-stream blocks into a registry-driven adapter-dispatch table, so adding a source is a registry entry + adapter with no engine change
task_id: ERE-11
source_anchor: docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md :: "a new source is a registry entry + adapter, not an engine change"
parent_capability: Episode Resolution Engine
prerequisites: [ERE-01, ERE-04, ERE-09]
depends_on: [STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md, TWO_STREAM_SEGMENTATION_CORE.md, CALENDAR_STREAM_ADAPTER.md]
can_parallelize_with: []
---

# Registry-Driven Adapter Dispatch

## Purpose

ERE-01 frames the architecture as "adding a future stream is a registry entry + adapter, not an engine change," and ERE-09 (calendar) claims to prove it. But `app/episodes/segmenter.py::run_segmentation_tick` still pulls data through **hardcoded per-stream `if <STREAM_ID> in live_streams:` blocks** — one for heimdal, one for vault.activity, one for calendar. Enumeration is registry-driven (AC4/AC5, `enumerate_consumable_streams`); the data-pull loop is not. Calendar (ERE-09) *did* require editing the tick (the calendar block was added to `run_segmentation_tick`), so the ERE-01 claim is today aspirational, not literally true. This task makes it literally true: an adapter-dispatch table where each live registry entry resolves to a reader+normalizer, `run_segmentation_tick` iterates live streams and dispatches, and a future source (location/ERE-10) needs a registry entry + adapter with **zero** edit to `run_segmentation_tick`.

This is an owner-optional architectural/governance investment (`lane:governance`). It changes no segmentation *behavior* — it is a behavior-preserving refactor of the ingestion seam only. The pure five-dimension core (`fold_signals_into_segments`, `detect_shift`) and all ERE-04/ERE-09 behavior and tests are untouched.

## What This Task Does

1. **Adapter protocol.** Define a `StreamAdapter` protocol (name TBD in implementation) that models the *union* of the three existing streams' lifecycle shapes — the three are genuinely different, and a naive "extract the common case" would leak on all three:
   - `read(ctx) -> ReadResult` — pull this tick's raw rows for the stream; `ReadResult` carries the rows **and** a `degraded: list[str]` channel (only calendar populates it today; log streams return empty).
   - `normalize(row, ctx) -> SegmentationSignal | None` — map one raw row to a signal, or `None` to skip fail-loud (counted in `skipped_no_observation_time`).
   - `advance_cursor(rows, ctx) -> None` — durable cursor advance, defaulting to a **no-op** (calendar is cursorless: it re-polls a fixed window each tick and dedupes via `calendar_signal_id`; heimdal/vault advance an append-log cursor).
   - `ctx: TickContext` carries `consumer_id`, `vault_root`, `limit`, and lazily-provided shared resources (the calendar register snapshot; vault_root for vault-activity dimension resolution).
2. **Dispatch resolution.** Resolve each live `StreamRegistryEntry` to exactly one adapter. `module:` transports (heimdal, calendar) can expose their adapter from the named module; `outbox:` transports (vault.activity) name a topic, not a module, so a `stream_id → adapter` binding table (or an explicit `adapter:` resolution field) is the mechanism. **Design decision recorded in the PR:** whichever resolution shape is chosen, it must be declarative and keyed off the registry, never a second hardcoded list inside the segmenter.
3. **Migrate the three existing blocks.** Re-express the heimdal, vault.activity, and calendar blocks as `StreamAdapter` implementations with **byte-for-byte preserved behavior**: same reader calls (`read_observations_for_consumer`, `read_vault_activity_for_consumer`, `read_calendar_raw_items_for_tick`), same normalizers (`_signal_from_heimdal_row`, `_signal_from_vault_activity_row`, `_signal_from_calendar_row`), same skip-counting, same cursor advances, same degraded reporting.
4. **Generic tick loop.** Rewrite `run_segmentation_tick` so the data-pull is `for entry in enumerate_consumable_streams(registry): adapter = resolve(entry); ...` — read → normalize → hold rows; **then** (unchanged crash-safe ordering, INV-ERE-F) emit proposals → persist open state → advance each adapter's cursor → delete closed state LAST. The deferred cursor advance (currently `heimdal_rows`/`vault_rows` held to the end of the function) is preserved by holding per-adapter consumed rows and replaying `advance_cursor` after emission.
5. **Visible skip, not silent drop (bridge to ERE-12).** A live registry entry with no resolvable adapter must be **reported** in the tick summary (a new `no_adapter: [stream_id, ...]` key), not silently ignored as today. ERE-11 preserves current runtime behavior — those streams are still not consumed this slice — but makes the gap observable. ERE-12 turns the observable gap into a fail-loud correspondence guard once the registry is reconciled.

## Concretely

```
# Before: adding calendar (ERE-09) required editing run_segmentation_tick.
# After: the tick body names no stream_id. Behavior is identical.
$ python -m app.cli episodes tick --json
{"consumed": {"heimdal.observations": 4, "vault.activity": 2, "calendar": 3},
 "skipped_no_observation_time": {...}, "proposed": [...], "open_segments": 5,
 "degraded": [], "no_adapter": ["chat.sessions", "decision.receipts",
                                "kap.acquisitions", "heimdal.attention"]}

# The proof: grep the tick body for any stream_id literal — there are none.
$ grep -nE 'HEIMDAL_STREAM_ID|VAULT_ACTIVITY_STREAM_ID|CALENDAR_STREAM_ID' \
      app/episodes/segmenter.py
# (matches only in adapter definitions + constants, never inside run_segmentation_tick)
```

## Why This Matters

The ERE-01 claim is the whole architectural bet: sources are first-class registry entries, not engine edits. Today the claim is false at the tick's data-pull loop, and calendar (ERE-09) is the counter-example — it *did* edit the tick. When location (ERE-10) or any stream #8 lands, the current design forces another engine edit, and the fusion-source count is exactly where ERE-01 said the architecture must NOT require one. Making the dispatch registry-driven converts the claim from a docstring aspiration into an enforced property. It also removes the silent-drift hazard: the hardcoded blocks let the registry (which declares 7 live streams) and the engine (which ingests 3) diverge with nothing surfacing it — ERE-11 makes the divergence visible, ERE-12 makes it impossible.

## Acceptance Criteria

- [ ] AC1: A `StreamAdapter` protocol exists modelling read (with a degraded channel) + normalize + optional cursor-advance + a per-tick context, and the three existing streams (heimdal, vault.activity, calendar) are expressed as adapters. Verify: `tests/episodes/test_adapter_dispatch.py::test_three_live_streams_expose_adapters`
- [ ] AC2 (enforcement): `run_segmentation_tick`'s data-pull loop contains **no** stream_id literal and no per-stream `if` block — it iterates `enumerate_consumable_streams()` and dispatches to each entry's resolved adapter. The test asserts the property at the production entrypoint (drives a fixture registry whose live set differs from the seeded one and observes the tick consume exactly that set via adapters), not a static grep in isolation. Verify: `tests/episodes/test_adapter_dispatch.py::test_tick_dispatches_purely_via_registry`
- [ ] AC3 (behavior preservation): every existing ERE-04 and ERE-09 test passes unchanged, and a golden end-to-end tick over the two-stream + calendar fixture produces byte-identical `consumed` / `skipped_no_observation_time` / `proposed` / `open_segments` / `degraded` output to pre-refactor. Verify: `tests/episodes/test_segmentation_core.py` (whole file, unmodified) + `tests/episodes/test_calendar_adapter.py` (whole file, unmodified) + `tests/episodes/test_adapter_dispatch.py::test_tick_output_byte_identical_to_prerefactor_golden`
- [ ] AC4 (crash-safe ordering preserved): cursor advance still happens only after proposals + open-state persistence, and closed-segment state is deleted last; a simulated crash between the two cursor advances reconverges without a duplicate proposal (INV-ERE-F). Verify: `tests/episodes/test_adapter_dispatch.py::test_deferred_cursor_advance_preserves_crash_safety`
- [ ] AC5 (no-engine-change property): adding a brand-new live stream to a fixture registry with a test adapter causes the tick to consume it **with no edit to `run_segmentation_tick`** (the test registers the adapter + registry entry only). Verify: `tests/episodes/test_adapter_dispatch.py::test_new_stream_joins_via_registry_and_adapter_only`
- [ ] AC6: a live registry entry with no resolvable adapter is reported in the tick summary under a `no_adapter` key and is not silently consumed nor crashes the tick (bridge state for ERE-12). Verify: `tests/episodes/test_adapter_dispatch.py::test_unadapted_live_stream_reported_not_dropped`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_adapter_dispatch.py
pytest -q tests/episodes/test_segmentation_core.py tests/episodes/test_calendar_adapter.py tests/episodes/test_stream_registry.py
pytest -q -m "not pg"
```

The golden byte-identity check (AC3) captures the pre-refactor tick output as a fixture at the start of the slice, then asserts the post-refactor tick reproduces it exactly — the refactor's contract is "no behavior change," and this is its proof surface.

## Out of Scope

- Building adapters for the four currently-unconsumed live streams (`chat.sessions`, `decision.receipts`, `kap.acquisitions`, `heimdal.attention`) — ERE-11 makes their absence visible; ERE-12 reconciles the registry and either specs those adapters or downgrades the entries.
- Flipping the `no_adapter` report into a fail-loud error (ERE-12, after the registry is reconciled so `live` ⇒ has-adapter).
- Any change to shift detection, thresholds, scope partitioning, or the pure fold core.
- The location stream (ERE-10) — this task makes it addable without an engine edit; it does not add it.

## Restart / Durability Posture

Not applicable in the user-facing-surface sense: this task ships no new user-facing surface and no new durable state. It preserves the existing durable state exactly — the Heimdal observation-log cursor, the `episode_engine_state` vault-activity cursor and `open_segment:` rows — with identical advance timing (INV-ERE-F crash ordering). Cursorless calendar re-polling is preserved. A process restart mid-tick behaves exactly as it does pre-refactor: the next tick reprocesses uncommitted work and reconverges, deduped by the retained `signal_ids` ledgers and the deterministic episode id.

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` (ERE-01 — the registry + the architectural claim being made literally true)
- `docs/EPISODE_RESOLUTION_ENGINE/TWO_STREAM_SEGMENTATION_CORE.md` (ERE-04 — behavior preserved)
- `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md` (ERE-09 — the third existing adapter; the slice that first proved the tick still needed editing)
- `app/episodes/segmenter.py::run_segmentation_tick` (the refactor target); `app/episodes/stream_registry.py` (transport binding shapes `module:` / `outbox:`)

## Related GitHub Issues

Issue **#3523** — `[Episode Resolution Engine] adapter-dispatch: registry-driven ingestion so a new source needs no engine change`. Child of parent #3175, `lane:governance`, `agent:blocked`, `prio:low` (owner-optional investment, not on the critical ERE build path). Spec landed in PR #3522. Pairs with ERE-12 (#3524, fail-loud correspondence); ERE-11 must merge first.
