State: FILED — the parent feature issue is live as #3340 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3343 (SCREEN-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3341 (SCREEN-03, dependency-free head per this spec's own design — flips to agent:ready when this spec PR merges to main; Bifrost-transfer candidate), #3344 (SCREEN-02, blocked until SCREEN-01/#3343 merges), #3345 (SCREEN-05, blocked until SCREEN-02/#3344 merges), #3342 (SCREEN-06, blocked until SCREEN-01/#3343 and SCREEN-03/#3341 merge), #3346 (SCREEN-04, blocked until SCREEN-02/#3344 merges and externally blocked on ERE stream registry #3176).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3340; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Heimdal Screen Stream] parent: always-on desktop observer → screen-modality observations → event motor / journaling / time-spend

Title on GitHub: `[Heimdal Screen Stream] parent: always-on desktop observer → screen-modality observations feeding the event motor, journaling, and time-spend`

## Context

The owner ruled (2026-07-07, `docs/research/yggdrasil-closed-loops-ideation.md` loop 6): always-on
desktop screen observation is **approved** on their single-operator machines, with pause + app/scope
exclusion controls and a derive-and-discard raw posture as spec defaults; the wearable/audio side of
the capture-posture fork stays an open owner decision. This capability extends **Heimdal** with a
`screen` capture modality (Heimdal v1 shipped the voice modality: encrypted raw store, gated read,
hard-retention, governed publish, candidate projector — all reused here) and feeds three tracks at
once: the ERE event motor, the sibling Conversational Journaling capability, and time-spend analysis.
Fully specified in `docs/HEIMDAL_SCREEN_STREAM/` (this spec directory is the source of truth;
grounding: the ideation capture + the Heimdal charter/companion).

This parent is the **live validation hub**: children post validation receipts here; it is
`agent:blocked` (not a pickup issue) while children are outstanding.

## Scope

The capability outcome — not one PR: a native macOS observer client (Bifrost-homed) captures screen
state and ships raw bundles to the host; the host derives privacy-conscious textual activity
observations in-seam with a local vision model and publishes them through the governed Heimdal path;
`screen` is registered as a live ERE stream; a rebuildable time-spend projection lands in the vault; and
an operator control surface (visible pause, app/scope exclusions, retention tunables) governs it with a
receipt per change. On-device derivation and wearable/audio capture are declared future/reserved, not
built.

## Source Anchors

- `docs/HEIMDAL_SCREEN_STREAM/README.md` (spec: tasks, topology, cross-task invariants, capability ACs)
- `docs/research/yggdrasil-closed-loops-ideation.md :: 6. Heimdal screen stream` (the owner ruling)
- `docs/HEIMDAL/CAPABILITY_CHARTER.md` (FIXED constraints, HEIM invariants); `docs/HEIMDAL/OWNER_DECISIONS.md` (D-CONSENT / D-PRIVACY / D-RETENTION; R-CONSENT reserved)
- `docs/HEIMDAL/FABLE_COMPANION.md` (observation payload §1.3, in-seam derivation §5.2/§7.3, HEIM-12)
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` (always-on-local floor); `docs/adr/ADR-0050-cross-repo-governance-and-bifrost-client-repo.md` (client home)
- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` + `.../README.md :: Input-source inventory` (the screen future→live flip)

## SBS Impact

- Primary subsystem: EBF (Heimdal is the external-boundary/ingress fabric; the observer is the sensor and the capture endpoint is the seam)
- Secondary subsystem(s): SIP (observation schema/provenance/confidence + the `screen` stream identity), HKA (observation-candidate notes + markdown time-spend projection), DRI (rebuildable time-spend projection), GOV (raw-frame read gating, consent grant, control-change receipts)
- Write class: mixed — mechanical durable via the governed capture/publish seam (raw records, published observations); derived-rebuildable (time-spend projection, candidate notes); governance/receipts (consent grant, control receipts)
- Authority impact: none — screen observations are `requires_review` noncanonical evidence-candidates (HEIM-8); never canonical knowledge without a governed transition
- Persistence impact: reuses `heimdal_raw_record` (frames) + `heimdal_observation_log` (observations); new derived time-spend projection note class; new `screen_always_on` consent grant + screen-control receipts
- Derived/rebuildable impact: time-spend projection rebuilds from observations; frames are derive-and-discard (bounded buffer)
- Human knowledge impact: observation-candidate notes + time-spend notes are human-legible derived Artifacts; overwrite no human note
- Memory impact: none directly (feeds ERE/journaling/time-spend downstream)
- Retrieval/context impact: via the ERE event motor once `screen` is registered (SCREEN-04)
- Sync/deployment impact: reuses the Heimdal capture runtime; new local vision model dependency on the host (Ollama-servable); the client is a separate native app (Bifrost) reaching the host over loopback/Tailscale-local
- External boundary impact: **yes** — a new native macOS client (SCREEN-03) at the LAN/Tailscale boundary posting to the governed capture endpoint; raw pixels transit the trusted LAN (mitigated: capture-time exclusion, encrypted-at-rest, derive-and-discard)
- New or changed contract: `docs/contracts/HEIMDAL_SCREEN_CLIENT_CONTRACT.md` (host-side, SCREEN-01); `modality: screen` extension of `heimdal.observation.published.v1`; the ERE `screen` registry entry (SCREEN-04)
- Owner-doc impact: on acceptance — Heimdal STATUS/modality note + the ERE inventory `screen` row (future→live)
- Transition debt impact: reduces (fills the ERE `screen: future` placeholder and the Heimdal v2 `screen` modality gap with buildable work)
- Fitness rule impact: strengthens — extends HEIM-12 (declared egress) to the screen stage; adds the INV-SCREEN-A..F seam invariants
- External boundary / consent: single-party by construction (own machine); the always-on approval is scoped to the desktop screen modality only; the wearable/audio fork stays reserved (R-CONSENT)

## Constraints

Heimdal machinery reused, not forked (raw store, gated read, retention, publish, projector). Raw frames
never persist beyond the named retention buffer (INV-SCREEN-A). No keylogging/input/clipboard/video —
still frames + app metadata only. Derivation is structurally local (always-on-local floor) — no cloud
egress of raw pixels. Pause means PAUSED and is durable (INV-SCREEN-C). Exclusion honored at capture,
never host-side redaction (INV-SCREEN-D). Every control change receipted. Single-operator: no multi-user
consent machinery.

## Acceptance Criteria

The capability-level ACs in `docs/HEIMDAL_SCREEN_STREAM/README.md :: Capability acceptance criteria`,
each with its `Verify:` target there — including schema-validated governed publish, derive-and-discard
frame retention with legible aged-out loss, capture-time exclusion, durable total pause, `screen`
registered live in the ERE registry with span boundaries surviving into the signal shape, a rebuildable
time-spend projection, a receipt per control change, and a real at-computer-session live validation
receipt from the test channel posted to this issue.

## Implementation Tasks

`docs/HEIMDAL_SCREEN_STREAM/` — SCREEN-01..SCREEN-06 per the README execution order:
**01 → 02‖03 → 05‖06 → 04**. SCREEN-03 (the client) is Bifrost-homed and may transfer to the `bifrost`
repo; SCREEN-04 is externally blocked on the ERE stream registry (#3176) and is the parent-closure child.

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`); capture/publish
hot-path children (SCREEN-01/02/06) run the full `not pg` suite + integrated-runtime UAT where they
touch the vault/watcher hot path; SCREEN-03 verifies in Bifrost CI (Swift build+test+lint per ADR-0050)
if transferred, with the same AC names.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, tick output). After
SCREEN-02: a real at-computer session on the test channel produces recognizable activity spans + a
time-spend rollup (SCREEN-05). After #3176 lands and SCREEN-04 merges: a day of screen spans segments
into recognizable episodes (the event-motor validation). Acceptance → one owner-doc promotion PR
(Heimdal modality/STATUS + the ERE inventory screen-row flip) and parent closure; threshold/coalescing
tuning spins off as follow-up issues informed by live data.

## Out of Scope

Wearable/ambient-audio always-on capture (reserved owner decision, R-CONSENT); keylogging/input/video;
the Conversational Journaling reflection layer (`docs/CONVERSATIONAL_JOURNALING/` — this capability only
names the seam and feeds it); the ERE segmentation/closure core (ERE's own capability); on-device
derivation runtime (declared future; the contract holds the shape); cloud vision derivation of raw
frames (structurally rejected by the always-on-local floor).

## Suggested Validation

`pytest -q -m "not pg"` per child; `RUN_INTEGRATED_RUNTIME_UAT=1` for the capture/settings hot-path
children; a real at-computer session on the mac mini test channel producing spans + a time-spend note;
`python -m app.cli episodes tick --json` showing `screen` consumed once #3176 + SCREEN-04 land; receipts
to this issue.

## Source Docs

`docs/HEIMDAL_SCREEN_STREAM/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`;
`docs/HEIMDAL/CAPABILITY_CHARTER.md`; `docs/HEIMDAL/FABLE_COMPANION.md`;
`docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md`;
`docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md`; ADR-0050; ADR-0054.
