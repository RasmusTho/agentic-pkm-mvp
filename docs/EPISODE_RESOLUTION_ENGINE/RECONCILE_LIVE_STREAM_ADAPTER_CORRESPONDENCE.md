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

The registry declares **seven** live streams; `run_segmentation_tick` ingests **three** (heimdal, vault.activity, calendar). Four — `chat.sessions`, `decision.receipts`, `kap.acquisitions`, `heimdal.attention` — are declared `status: live` in `stream_registry.md` and listed **live** in the README's canonical Input-source inventory, but no adapter consumes them. The README's own capability acceptance criterion (README:79) reads *"All live streams in the inventory are registered and consumed only via the registry"* with `Verify: tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams` — but that test only asserts **enumeration parity** (`run_segmenter_stub` lists the registry's live entries), never **consumption**. So a currently-passing test with a consumption-claiming name masks a four-stream drift: the doc says these are consumed, the engine does not consume them, and nothing fails.

ERE-11 makes the drift *visible* (the `no_adapter` tick-summary key). ERE-12 makes it *impossible*: after this slice, `live` means "has a resolvable adapter and is consumed," the correspondence is machine-enforced fail-loud, and the capability-AC test actually asserts consumption. This directly repairs an unmet acceptance criterion of parent #3175.

## What This Task Does

1. **Resolve the true state of the four streams (owner-facing decision, pre-filled recommendation).** `chat.sessions` is carved out from the default downgrade path because downstream contracts already depend on it remaining live episode signal. Keep it `live` and land a follow-up adapter before ERE-12 closes. A product decision may downgrade it only if the same change reconciles every entry in the bounded authoritative inventory below. Repo-wide literal and semantic-alias searches remain useful discovery aids, but they are not allowed to stand in for that explicit contract boundary. For each of `decision.receipts`, `kap.acquisitions`, and `heimdal.attention`, decide exactly one:
   - **(a) genuinely adapter-pending** → the entry is mis-declared: downgrade `status: live → planned` in `stream_registry.md` (and the README inventory row) with a one-line reason, so `live` stops over-claiming. This is the conservative default and the recommended path for v1 — none of these three has a shipped normalizer today.
   - **(b) should be consumed now** → spec a follow-up adapter slice (ERE-13+) per stream and keep it `live` only once its adapter merges.
   The slice's deliverable is the reconciliation, not four new adapters: pick (a) for these three unless the owner directs otherwise, and treat the `chat.sessions` adapter as a prerequisite follow-up. Whichever is chosen, the invariant after this slice is total: every `live` entry resolves to exactly one adapter. Any change to stream liveness or the seeded inventory must update `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` in the same change; the ERE-01 contract may never retain a stale inventory.
2. **Flip the dispatch guard to fail-loud.** Once the registry is reconciled so every `live` entry has an adapter, change ERE-11's `no_adapter` *report* into a hard error: a `live` registry entry that resolves to no adapter raises at the tick entrypoint (fail-loud, mirroring the ERE-01 `UnknownTransportError` / "no silent default streams" discipline), never a silent skip. This closes the drift permanently — a future `live` entry added without an adapter breaks the tick immediately and loudly, at declaration time, not at stream #8.
3. **Strengthen the capability-AC test to assert consumption.** Replace/augment `test_engine_consumes_only_registered_streams` so it drives `run_segmentation_tick` (not just `run_segmenter_stub` enumeration) and asserts that the set of streams actually *read from* equals the registry's live set — so the test name stops over-claiming and the README:79 AC is honestly discharged.
4. **Update the canonical inventory to true state.** The README Input-source inventory table, `stream_registry.md`, and `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` reflect the reconciled statuses, with the 1:1 registry-match property (README:16) restored to actually true. If `chat.sessions` stays live as required by the current downstream contracts, those voice-loop and conversational-journaling specs remain consistent without edits; any downgrade requires their writeback in the same change.

## Authoritative `chat.sessions` Reconciliation Inventory

This table is the deterministic reconciliation boundary for a `chat.sessions` liveness change. A
future contract that asserts the stream is live or consumed must add itself here when authored; ERE-12
does not claim that a text search can prove semantic completeness.

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
# After reconciliation: chat.sessions remains live after its adapter lands;
# the other three take recommended path (a), so live ⇒ consumed and the
# registry matches the engine 1:1.
$ python -m app.cli episodes streams --json | jq '[.streams[] | select(.status=="live") | .stream_id]'
["heimdal.observations", "vault.activity", "chat.sessions", "calendar"]

# A live entry with no adapter is now a hard error, not a silent skip:
$ python -m app.cli episodes tick --json   # with a live entry lacking an adapter
RuntimeError: stream 'chat.sessions' is status=live but resolves to no adapter --
fail-loud, no silently-unconsumed live stream
```

## Why This Matters

The ERE README opens with the owner's requirement: *"every input source identified and part of the architecture ... A source absent here is an omission to fix, never an implicit input"* (README:16), and the registry must match the inventory **1:1**. A `live` stream the engine silently ignores is the exact failure that requirement exists to prevent — worse than an absent source, because the doc actively claims it is consumed. Left alone, the next reader trusts README:79, believes four more dimensions of evidence feed segmentation, and reasons about episode quality on a false premise. Making `live ⇒ consumed` fail-loud means the registry can never again claim a consumption that the engine does not perform.

## Acceptance Criteria

- [ ] AC1: every `live` entry in `stream_registry.md` resolves to exactly one adapter after reconciliation. `chat.sessions` remains live by default and therefore requires a merged adapter before ERE-12 closes; it may be downgraded only by a product decision that reconciles every row in `Authoritative chat.sessions Reconciliation Inventory` in the same change. The other three previously-unconsumed streams are either downgraded to `planned` with a documented reason or have a merged adapter. Verify: `tests/episodes/test_adapter_dispatch.py::test_every_live_entry_resolves_to_an_adapter`
- [ ] AC2 (enforcement): a `live` registry entry that resolves to no adapter raises at the `run_segmentation_tick` production entrypoint (fail-loud), never a silent skip nor a bare `no_adapter` report. The test drives the real tick with a fixture registry containing an adapterless live entry and asserts it raises. Verify: `tests/episodes/test_adapter_dispatch.py::test_live_without_adapter_fails_loud_at_tick`
- [ ] AC3 (capability-AC honesty): `test_engine_consumes_only_registered_streams` asserts the streams `run_segmentation_tick` actually reads equal the registry's live set — consumption, not just enumeration. Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams`
- [ ] AC4 (doc truth): the README Input-source inventory, `stream_registry.md`, and `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` reflect the reconciled statuses, and the 1:1 registry-match claim (README:16) holds against the live engine. Any stream-liveness or seeded-inventory change updates all three surfaces in the same change. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory (canonical)` + `docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md` + `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md :: What This Task Does`
- [ ] AC5 (`chat.sessions` downstream contract): every entry in `Authoritative chat.sessions Reconciliation Inventory` remains consistent with stream liveness. If the stream is downgraded, every inventory row is reconciled in the same change; otherwise the ERE-12 PR records that the inventoried live-stream claims remain valid. Literal `chat.sessions` and semantic-alias searches are discovery aids only and may reveal a contract that must first be added to the inventory; neither search is completeness proof. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/RECONCILE_LIVE_STREAM_ADAPTER_CORRESPONDENCE.md :: Authoritative chat.sessions Reconciliation Inventory` + PR body owner-doc / source-doc writeback receipt covering every inventory row
- [ ] AC6: the ERE-04/ERE-09 segmentation behavior and all existing tests remain green — reconciliation changes which streams are declared live, never how the consumed ones segment. Verify: `tests/episodes/test_segmentation_core.py` + `tests/episodes/test_calendar_adapter.py` (both whole-file, unmodified)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_adapter_dispatch.py tests/episodes/test_stream_registry.py
pytest -q tests/episodes/test_segmentation_core.py tests/episodes/test_calendar_adapter.py
pytest -q -m "not pg"
```

The `chat.sessions` adapter follows path (b) by default. If the owner chooses path (b) for another stream (build the adapter now rather than downgrade), that stream's adapter gets its own slice/issue and its own behavioral tests; ERE-12 still owns the fail-loud guard + the correspondence invariant + the strengthened capability-AC test.

## Out of Scope

- Building the actual normalizers for `chat.sessions` / `decision.receipts` / `kap.acquisitions` / `heimdal.attention` (each is a separate follow-up slice). `chat.sessions` follows path (b) by default; only the other three follow the recommended path (a) to `planned` unless the owner directs otherwise.
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

Issue **#3524** — `[Episode Resolution Engine] adapter-correspondence: make live mean consumed, fail-loud on an adapterless live stream`. Child of parent #3175, `lane:governance`, `agent:blocked`, `prio:low`. Blocked on ERE-11 (#3523). Spec landed in PR #3522. Note in `Context`: this slice repairs parent #3175's own capability AC (README:79), which is currently unmet because its named test asserts enumeration, not consumption.
