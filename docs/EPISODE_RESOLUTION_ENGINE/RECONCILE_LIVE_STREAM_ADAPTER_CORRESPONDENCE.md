---
name: Reconcile Live-Stream / Adapter Correspondence
description: Make "live" mean "has an adapter and is consumed" — reconcile the four registry-live-but-unconsumed streams, flip the dispatch guard to fail-loud, and strengthen the capability-AC test to assert consumption not just enumeration
task_id: ERE-12
source_anchor: docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory (canonical)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-11]
depends_on: [REGISTRY_DRIVEN_ADAPTER_DISPATCH.md]
can_parallelize_with: []
---

# Reconcile Live-Stream / Adapter Correspondence

## Purpose

Before ERE-12, the registry declared **seven** live streams while `run_segmentation_tick` ingested **three** (heimdal, vault.activity, calendar). Four — `chat.sessions`, `decision.receipts`, `kap.acquisitions`, `heimdal.attention` — were declared `status: live` without an adapter. ERE-12 takes the conservative path for all four: each is `planned` with an explicit adapter-pending reason, so the live set is once again exactly the set the engine consumes.

ERE-11 makes the drift *visible* (the `no_adapter` tick-summary key). ERE-12 makes it *impossible*: after this slice, `live` means "has a resolvable adapter and is consumed," the correspondence is machine-enforced fail-loud, and the capability-AC test actually asserts consumption. This directly repairs an unmet acceptance criterion of parent #3175.

## What This Task Does

1. **Resolve the true state of the four streams.** ERE-12 applies the conservative path to `chat.sessions`, `decision.receipts`, `kap.acquisitions`, and `heimdal.attention`:
   - **(a) genuinely adapter-pending** → the entry is mis-declared: downgrade `status: live → planned` in `stream_registry.md` (and the README inventory row) with a one-line reason, so `live` stops over-claiming. This is the conservative default and the chosen path for v1 — none of these four has a shipped normalizer today.
   - **(b) should be consumed now** → spec a follow-up adapter slice (ERE-13+) per stream and keep it `live` only once its adapter merges.
   The slice's deliverable is the reconciliation, not four new adapters. All four take path (a), and the downstream surfaces below now describe episode consumption as adapter-pending rather than live. The invariant after this slice is total: every `live` entry resolves to exactly one adapter. The README, declaration, and ERE-01 contract update atomically.
2. **Flip the dispatch guard to fail-loud.** Once the registry is reconciled so every `live` entry has an adapter, change ERE-11's `no_adapter` *report* into a hard error: a `live` registry entry that resolves to no adapter raises at the tick entrypoint (fail-loud, mirroring the ERE-01 `UnknownTransportError` / "no silent default streams" discipline), never a silent skip. This closes the drift permanently — a future `live` entry added without an adapter breaks the tick immediately and loudly, at declaration time, not at stream #8.
3. **Strengthen the capability-AC test to assert consumption.** Replace/augment `test_engine_consumes_only_registered_streams` so it drives `run_segmentation_tick` (not just `run_segmenter_stub` enumeration) and asserts that the set of streams actually *read from* equals the registry's live set — so the test name stops over-claiming and the README:79 AC is honestly discharged.
4. **Update the canonical inventory to true state.** The README Input-source inventory table, `stream_registry.md`, and `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` reflect the reconciled statuses, with the 1:1 registry-match property (README:16) restored to actually true. Because `chat.sessions` is downgraded, the voice-loop, conversational-journaling, Heimdal example, and DOCS_INDEX surfaces in the authoritative reconciliation inventory update in the same change.

## Authoritative `chat.sessions` Reconciliation Inventory

This table is the deterministic reconciliation boundary used for the ERE-12 downgrade. Every listed
surface is updated to say that the chat-session artifact exists but its ERE adapter is pending. A
future adapter slice must flip these surfaces back together when it promotes the stream to `live`.

| Role | Required reconciliation surfaces |
| --- | --- |
| ERE liveness and seeded inventory authority | `docs/EPISODE_RESOLUTION_ENGINE/README.md`; `docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md`; `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md`; `docs/EPISODE_RESOLUTION_ENGINE/REGISTRY_DRIVEN_ADAPTER_DISPATCH.md` |
| Mimer Voice Loop downstream contract | `docs/MIMER_VOICE_LOOP/README.md`; `docs/MIMER_VOICE_LOOP/PARENT_FEATURE_ISSUE.md`; `docs/MIMER_VOICE_LOOP/CARRY_SESSION_FOLLOWUP_CONTEXT.md` |
| Conversational Journaling downstream contract | `docs/CONVERSATIONAL_JOURNALING/README.md`; `docs/CONVERSATIONAL_JOURNALING/PARENT_FEATURE_ISSUE.md`; `docs/CONVERSATIONAL_JOURNALING/LEAD_REFLECTION_CONVERSATION.md` |
| Heimdal Screen Stream downstream contract | `docs/HEIMDAL_SCREEN_STREAM/REGISTER_SCREEN_STREAM_WITH_ERE.md` |
| Registered owner/spec summaries | the rows for the three capability directories in `docs/DOCS_INDEX.md` |

Advisory, research, audit, and archived captures are evidence, not stream-liveness contracts. For
example, `docs/research/yggdrasil-closed-loops-ideation.md` records the discovery-time live posture but
does not authorize or block a later reconciliation. A liveness-change PR may update such evidence for
reader clarity, but it must not count those files as substitutes for any inventory row above.

## Concretely

```
# After reconciliation: all four adapterless declarations are planned, so
# live implies consumed and the registry matches the engine 1:1.
$ python -m app.cli episodes streams --json | jq '[.streams[] | select(.status=="live") | .stream_id]'
["heimdal.observations", "vault.activity", "calendar"]

# A live entry with no adapter is now a hard error, not a silent skip:
$ python -m app.cli episodes tick --json   # with a live entry lacking an adapter
RuntimeError: stream 'fixture.unadapted' is status=live but resolves to no adapter --
fail-loud, no silently-unconsumed live stream
```

## Why This Matters

The ERE README opens with the owner's requirement: *"every input source identified and part of the architecture ... A source absent here is an omission to fix, never an implicit input"* (README:16), and the registry must match the inventory **1:1**. A `live` stream the engine silently ignores is the exact failure that requirement exists to prevent — worse than an absent source, because the doc actively claims it is consumed. Left alone, the next reader trusts README:79, believes four more dimensions of evidence feed segmentation, and reasons about episode quality on a false premise. Making `live ⇒ consumed` fail-loud means the registry can never again claim a consumption that the engine does not perform.

## Acceptance Criteria

- [ ] AC1: every `live` entry in `stream_registry.md` resolves to exactly one adapter after reconciliation. The four previously-unconsumed streams are downgraded to `planned` with a documented adapter-pending reason. Verify: `tests/episodes/test_adapter_dispatch.py::test_every_live_entry_resolves_to_an_adapter`
- [ ] AC2 (enforcement): a `live` registry entry that resolves to no adapter raises at the `run_segmentation_tick` production entrypoint (fail-loud), never a silent skip nor a bare `no_adapter` report. The test drives the real tick with a fixture registry containing an adapterless live entry and asserts it raises. Verify: `tests/episodes/test_adapter_dispatch.py::test_live_without_adapter_fails_loud_at_tick`
- [ ] AC3 (capability-AC honesty): `test_engine_consumes_only_registered_streams` asserts the streams `run_segmentation_tick` actually reads equal the registry's live set — consumption, not just enumeration. Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams`
- [ ] AC4 (doc truth): the README Input-source inventory, `stream_registry.md`, and `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` reflect the reconciled statuses, and the 1:1 registry-match claim (README:16) holds against the live engine. Any stream-liveness or seeded-inventory change updates all three surfaces in the same change. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory (canonical)` + `docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md` + `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md :: What This Task Does`
- [ ] AC5 (`chat.sessions` downstream contract): every entry in `Authoritative chat.sessions Reconciliation Inventory` says the artifact path exists while ERE consumption remains adapter-pending. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/RECONCILE_LIVE_STREAM_ADAPTER_CORRESPONDENCE.md :: Authoritative chat.sessions Reconciliation Inventory` + PR body owner-doc / source-doc writeback receipt covering every inventory row
- [ ] AC6: the ERE-04/ERE-09 segmentation behavior and all existing tests remain green — reconciliation changes which streams are declared live, never how the consumed ones segment. Verify: `tests/episodes/test_segmentation_core.py` + `tests/episodes/test_calendar_adapter.py` (both whole-file, unmodified)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_adapter_dispatch.py tests/episodes/test_stream_registry.py
pytest -q tests/episodes/test_segmentation_core.py tests/episodes/test_calendar_adapter.py
pytest -q -m "not pg"
```

All four adapterless entries follow path (a) in ERE-12. A future path-(b) promotion gets its own slice and behavioral tests, and may flip an entry to `live` only when its adapter lands.

## Out of Scope

- Building the actual normalizers for `chat.sessions` / `decision.receipts` / `kap.acquisitions` / `heimdal.attention` (each is a separate follow-up slice before that stream can become `live`).
- The dispatch mechanism itself (delivered by ERE-11 — this slice only tightens its guard).
- Shift-detection, threshold, or scope-partitioning changes.

## Restart / Durability Posture

Not applicable: no new user-facing surface, no new durable state. Reconciliation changes registry declarations (markdown + the code mirror) and a guard; it does not alter cursors, `open_segment:` state, or emission. Restart behavior is identical to ERE-11.

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory (canonical)` (the 1:1 claim being restored) and `:: Capability acceptance criteria` (README:79, the AC being honestly discharged)
- `docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md` (the markdown-first declaration reconciled to true state)
- `docs/EPISODE_RESOLUTION_ENGINE/REGISTRY_DRIVEN_ADAPTER_DISPATCH.md` (ERE-11 — the dispatch this slice makes strict)
- `docs/MIMER_VOICE_LOOP/CARRY_SESSION_FOLLOWUP_CONTEXT.md` and the other downstream contract surfaces in AC5's authoritative inventory (the live/consumed-stream claims any downgrade must reconcile)

## Related GitHub Issues

Issue **#3524** — `[Episode Resolution Engine] adapter-correspondence: make live mean consumed, fail-loud on an adapterless live stream`. Child of parent #3175 in the Product/Runtime core lane. ERE-11 (#3523 / PR #3727) satisfied its prerequisite; this slice repairs parent #3175's live-stream capability AC by making the named test exercise production consumption rather than enumeration.
