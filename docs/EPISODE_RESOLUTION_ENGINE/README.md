State: Specification directory — ACTIVE (parent feature issue #3175 filed 2026-07-07; children #3176–#3184). System-level source of truth for building the Episode Resolution Engine, the Mimer organ decided by ADR-0054. Subordinate to ADR-0051 (Episode entity), ADR-0054 (placement + seam), the semantic-dimensions doctrine, the salience contract, and the CrossScopeFlow contract. Grounded in docs/research/EPISODE_RESOLUTION_ENGINE.md.
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory + the governing ADRs; GitHub issues are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Episode Resolution Engine — Specification

The runtime organ that (1) **segments** registered information streams into `Episode`s by five-dimension shift detection, (2) **assigns** `episode_ref` to artifacts that originated within them, and (3) **emits closure** so event-triggered relevance decay fires. Placement: **Mimer** (ADR-0054); Heimdal contributes single-stream boundary hints (its per-session `episode_id`) and is otherwise untouched.

Classification: **Product/Runtime System work** (new runtime subsystem). Primary subsystem: **SIP** (owns `episode_ref`); secondary: HKA (Episode notes are Artifacts), RCA/MEM (honor closure decay), GOV (cross-scope gating), DRI (projection).

## Input-source inventory (canonical)

The owner requires every input source identified and part of the architecture. This table is the canonical enumeration; the runtime stream registry (ERE-01, **delivered**: `docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md` is the markdown-first declaration surface, `app/episodes/stream_registry.py::load_registry()` the fail-loud code mirror) must match it 1:1. A source absent here is an omission to fix, never an implicit input.

| stream_id | Status | Transport | Dimensions fed | Consent/scope class | Owner |
| --- | --- | --- | --- | --- | --- |
| `heimdal.observations` | **live** | observation-log cursor (`heimdal.observation.published`) | time, protagonist, goal, causation | Heimdal consent-gated (grant_ref) | Heimdal |
| `vault.activity` | **live** | outbox `ingest.vault.changed` / `ingest.object.created` / `ingest.object.deleted` + frontmatter dimensions | time, goal, causation | vault-implicit, scope from frontmatter | Mimer |
| `chat.sessions` | **live** | session log (`.chats/`, `session_id`, per-turn timestamps) | time, goal | vault-implicit | Mimer |
| `decision.receipts` | **live** | receipt log + `decisions` projection / `decision.receipt` topic | time, goal, causation | vault-implicit | Mimer |
| `kap.acquisitions` | **live** | `knowledge_acquisition.stage.completed` | time, goal (content-origin; low situational weight) | vault-implicit | Mimer |
| `heimdal.attention` | **live** | attention log (daily `attention/YYYY-MM-DD.md`) | goal, protagonist | Heimdal-adjacent | Heimdal |
| `calendar` | **live** (ERE-09, #3184) | read-only CalDAV/ICS poll; credentials in private-bindings | time, protagonist, space (text), goal | per-calendar scope mapping | external via C3 |
| `bifrost.native_capture` | **planned** (Epic B) | governed capture API / direct FS per MIMER_CLIENT_CONTRACT | space, protagonist, causation enrichment | Heimdal consent-gated | Bifrost→Heimdal |
| `location` | **future** (ERE-10) | Heimdal v2 `modality: location` observations | space, time | Heimdal consent-gated (strict, opt-in per place/session) | Heimdal |
| `screen`, `biometric`, `ambient_audio` | **future** | Heimdal v2 modality vocabulary | varies | Heimdal consent-gated (Posture B) | Heimdal |

**Excluded (identified, deliberately out):** `builderops.records` — BuilderOps records / LearningSignals (dev-time builder telemetry, not lived situations); `orchestrator.internals` — orchestrator/planner/MCP/agent-internal events (machinery — the chat *session* is the lived-situation representative); `sync.transports` — sync transports (iCloud/Git — Integration Fabric class 5, never semantic); `egress.surfaces` — egress surfaces (notifications, TTS playback). Exclusions live in the registry with `status: excluded` so they are ruled out, not merely absent.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [STREAM_REGISTRY_AND_SIGNAL_CONTRACT](STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md) | ERE-01 | — |
| 2 | [EPISODE_NOTE_STORE_AND_PROJECTION](EPISODE_NOTE_STORE_AND_PROJECTION.md) | ERE-02 | — (∥ with 1, 3) |
| 3 | [THREAD_EPISODE_REF_INTO_METADATA_BUNDLE](THREAD_EPISODE_REF_INTO_METADATA_BUNDLE.md) | ERE-03 | — (∥ with 1, 2) |
| 4 | [TWO_STREAM_SEGMENTATION_CORE](TWO_STREAM_SEGMENTATION_CORE.md) | ERE-04 | 1, 2 |
| 5 | [ASSIGN_EPISODE_REF_TO_ARTIFACTS](ASSIGN_EPISODE_REF_TO_ARTIFACTS.md) | ERE-05 | 2, 3, 4 |
| 6 | [EMIT_CLOSURE_AND_DERIVE_DECAY](EMIT_CLOSURE_AND_DERIVE_DECAY.md) | ERE-06 | 4, 5 (∥ with 7, 8) |
| 7 | [RESPECT_HUMAN_RECUT](RESPECT_HUMAN_RECUT.md) | ERE-07 | 4, 5 (∥ with 6, 8) |
| 8 | [GATE_CROSS_SCOPE_FUSION](GATE_CROSS_SCOPE_FUSION.md) | ERE-08 | 4, 5 (∥ with 6, 7) |
| 9 | [CALENDAR_STREAM_ADAPTER](CALENDAR_STREAM_ADAPTER.md) | ERE-09 | 1, 4 |
| 10 | [LOCATION_STREAM_FUTURE_POSTURE](LOCATION_STREAM_FUTURE_POSTURE.md) | ERE-10 | spec-only posture; no issue until the Heimdal v2 trigger fires |
| 11 | [REGISTRY_DRIVEN_ADAPTER_DISPATCH](REGISTRY_DRIVEN_ADAPTER_DISPATCH.md) | ERE-11 | 4, 9 (owner-optional governance/refactor) |
| 12 | [RECONCILE_LIVE_STREAM_ADAPTER_CORRESPONDENCE](RECONCILE_LIVE_STREAM_ADAPTER_CORRESPONDENCE.md) | ERE-12 | 11 (owner-optional governance/refactor) |

Flat order: 1‖2‖3 → 4 → 5 → 6‖7‖8 → 9. ERE-10 is a declared posture, not a build step. ERE-11 → 12 is an owner-optional governance/refactor lane, off the critical build path: it generalizes the ingestion seam so the ERE-01 "registry entry + adapter, not an engine change" claim becomes literally true and the Input-source inventory's 1:1 registry-match property becomes fail-loud enforced. It changes no segmentation behavior.

## Cross-Task Invariants / Interaction Safety

Multiple tasks read/write the episode substrate; these invariants hold *across* tasks, with partial-failure walks:

- **INV-ERE-A — a binding always has a note.** `episode_ref: pending [ep-x]` may exist only if the Episode note `ep-x` was durably written first (ERE-04 emits note before ERE-05 binds). Partial failure: note write succeeds, assignment tick crashes → artifacts stay `unbound`, next tick assigns (idempotent). Assignment first is impossible by construction; a binding referencing a missing note is a projection-rebuild error, fail-loud.
- **INV-ERE-B — proposal and canonical write classes never blur.** Proposed episodes and pending bindings carry no DecisionToken/AuthorityReceipt; only the CrossScopeFlow fuse path (ERE-08) produces receipts. Partial failure: a receipt-bearing proposal is a contract violation any invariant probe must fail on, never quietly accept.
- **INV-ERE-C — closure truth lives on the note, decay is derived.** The `episode.closed` outbox event is plumbing; retrieval derives decay from the SoR/projection. Partial failure: event lost → decay still applies at next retrieval (derivation reads projection); note flip lost mid-write → episode stays open, no decay, no corruption. Never persist decay (salience contract).
- **INV-ERE-D — no unflowed cross-scope state, ever.** At every seam (segment partition ERE-04, binding ERE-05, fusion ERE-08, decay derivation ERE-06) absence of a flow means the per-scope default. Partial failure: a fuse allowed but receipt write fails → the fuse aborts (receipt-before-note ordering); a denied fuse is audit-logged and dropped.
- **INV-ERE-E — the engine never overwrites a human cut.** `accepted`/`re-cut` dimensions and cut are machine-terminal; new evidence becomes new proposals (ERE-07). Partial failure: re-cut detected but binding reconciliation crashes → stale bindings correct on next tick; the note (human truth) is already right, and bindings are corrections toward it.
- **INV-ERE-F — idempotent under at-least-once.** Cursor replay and outbox redelivery never duplicate episodes, bindings, or closure events (fold-by-key + idempotency keys per house pattern). Partial failure: crash between consume and cursor-advance → reprocessing next tick, deduped.
- **INV-ERE-G — live ⇒ has-adapter ⇒ consumed (ERE-11/12).** Every `status: live` registry entry resolves to exactly one dispatch adapter, and `run_segmentation_tick` consumes all and only the live-with-adapter streams via that dispatch — never a hardcoded per-stream block, never a silently-unconsumed live entry. The Input-source inventory's 1:1 registry-match property (above) is thereby machine-enforced, not aspirational. Partial-failure / transition walk: ERE-11 makes an adapterless live entry *visible* (`no_adapter` tick-summary key) while preserving current runtime behavior (it stays unconsumed, tick does not crash); ERE-12 then reconciles the registry (a live entry with no adapter is downgraded to `planned` or gets one) and flips the guard to fail-loud, so after ERE-12 an adapterless live entry raises at the tick entrypoint instead of being skipped. Until ERE-11/12 land this invariant is **known-violated**: four live entries (`chat.sessions`, `decision.receipts`, `kap.acquisitions`, `heimdal.attention`) are enumerated but unconsumed, and the capability AC below (`test_engine_consumes_only_registered_streams`) asserts only enumeration parity, not consumption.

## Provisional thresholds (RQ-E1)

Segmentation thresholds (time-gap, goal/protagonist shift sensitivity) and the closure decay step-down factor are **named, single-sourced constants documented as provisional**. RQ-E1 (multi-stream thresholds) and RQ3 (decay curve, per-scope variation) are open research resolved *after* live data accumulates — the tuning pass is parent-issue validation work, not a pre-code gate. Over-segmentation is preferred (merge is a cheap re-cut; wrong fusion is costly).

Delivered (ERE-04, #3179), all single-sourced in `app/episodes/segmenter.py` — no other module literal-copies these values:

| Constant | Value | Meaning |
| --- | --- | --- |
| `TIME_GAP_MINUTES` | `45` | No signal for this long closes the open segment window (with or without a new triggering signal). |
| `GOAL_SHIFT_DETECTION_ENABLED` | `True` | A signal's goal/project-binding set fully disjoint from the open segment's accumulated goal set is a shift. Conservative: fires only when both sides are non-empty. |
| `PROTAGONIST_SHIFT_DETECTION_ENABLED` | `True` | A signal's resolved-attribution protagonist set fully disjoint from the open segment's accumulated protagonist set is a shift. Same both-sides-non-empty bar. |
| `CAUSAL_BREAK_DETECTION_ENABLED` | `True` | v1 rule: an explicit Heimdal `supersedes` marker on the observation payload is a discontinuity. |
| `PLACE_SHIFT_DETECTION_ENABLED` | `False` | Place/space is unfed in v1 (no calendar/location stream yet, ERE-09/ERE-10) — never contributes a shift; a documented absence, not a silent omission. |

The Heimdal per-session `episode_id` boundary hint (ADR-0054 §3) is checked BEFORE all five dimensions: a signal continuing the open segment's own bound session always extends, overriding every other dimension (one session never spans two proposed episodes).

Delivered (ERE-06, #3181):

| Constant | Value | Single-sourced in | Meaning |
| --- | --- | --- | --- |
| `EPISODE_CLOSURE_QUIESCENCE_MINUTES` | `45` (= `TIME_GAP_MINUTES`, reused, never a second copy) | `app/episodes/closure.py` | Once an episode's own bounded `time.end` lies this far behind wall-clock `now`, the engine flips `time.closed: true` on the note (ADR-0058 §1 permits age as a *closure* input; it never appears in the retrieval decay math itself). |
| `CLOSURE_DECAY_STEP_DOWN_FACTOR` | `0.5` | `app/episodes/closure_decay.py` | v1 decay curve (RQ3 provisional): the single step-down factor a closed-episode binding's salience drops to at retrieval. Derived fresh on every read from `episode_ref` × the episode's `closed` state — never persisted (ADR-0058 §4). |

## Capability acceptance criteria

- [ ] All live streams in the inventory are registered and consumed only via the registry (ERE-01/04). Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams`
- [ ] End-to-end on a fixture day: signals → proposed episodes → pending bindings → quiesce → closure → derived salience drop, all idempotent. Verify: `tests/episodes/test_capability_end_to_end.py::test_fixture_day_full_loop` (lands with ERE-06)
- [ ] `observation_episode_binding_survives` enforced at `schema_enforced` + `runtime_test` (ERE-03/05). Verify: `tests/invariants/test_episode_binding.py::test_observation_episode_binding_survives`
- [ ] No unflowed cross-scope episode/binding/decay path exists (ERE-08). Verify: `tests/invariants/test_cross_scope_flow.py::test_episode_fusion_denied_without_flow`
- [ ] Human re-cut is machine-terminal (ERE-07). Verify: `tests/episodes/test_recut.py::test_engine_cannot_overwrite_human_cut`
- [ ] Live validation on the test channel: ≥1 real day of the operator's Bifrost/voice + vault activity segments into recognizable episodes, receipt posted to the parent issue. Verify: parent-issue validation receipt (mac mini test channel)
- [ ] Owner-doc promotion only after acceptance: `docs/architecture/semantic-dimensions.md` invariant TBD line, invariant registry, and the ADR-0054 "no implementation issues exist yet" consequence line updated to delivered truth. Verify: doc writeback at `docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md :: Consequences`

## Relationship to GitHub issues

Parent feature issue: **#3175** (live validation hub, `agent:blocked`; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). Children: ERE-01 → #3176, ERE-02 → #3177 (Tier 3: migration), ERE-03 → #3178 (all three `agent:ready`); ERE-04 → #3179, ERE-05 → #3180, ERE-06 → #3181, ERE-07 → #3182, ERE-08 → #3183, ERE-09 → #3184 (`agent:blocked` until prerequisites merge); ERE-10 gets no issue until its trigger. ERE-11 → #3523, ERE-12 → #3524 are an owner-optional governance/refactor lane (`lane:governance`, `agent:blocked`, `prio:low`), children of #3175; ERE-12 directly repairs #3175's own capability AC (the `test_engine_consumes_only_registered_streams` criterion currently asserts enumeration, not consumption — see INV-ERE-G). Spec landed in PR #3522. The spec is the source of truth; issues track pickup state.

## Open research carried (not blocking)

RQ-E1 thresholds (tuning pass, post-live-data); RQ-E2 fusion-confidence combination (v1: per-axis confidences carried, combination conservative — revisit with data); RQ-E3 late-signal re-cut (v1: late signals bind, never re-cut bounds); RQ2 identity-under-recut (v1: conservative operational rule in ERE-07); RQ3 decay curve (v1: step-down constant).
