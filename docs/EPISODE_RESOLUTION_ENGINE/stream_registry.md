---
name: Stream Registry (markdown-first declaration)
description: The human-legible declaration surface app.episodes.stream_registry loads and validates fail-loud (ERE-01, #3176). Consistent with the `_heimdal/settings.md` markdown-first precedent (app.heimdal.settings_notes) -- this note is canonical, the code mirror never carries a parallel hardcoded copy.
---

# Stream Registry

Every Episode Resolution Engine input source is declared here as a registry
entry -- `status` (`live | planned | future | excluded`), `transport`,
`dimensions_fed`, `consent_class`, `cadence`, `owner_constituent`. This is
the **declaration surface**: `app.episodes.stream_registry.load_registry()`
parses the fenced block below and validates it fail-loud (missing file,
missing/empty fence, malformed entry, unknown `status`, or a `live` entry
missing `transport`/`consent_class`/`cadence`/`dimensions_fed` are all hard
errors -- never a silent default/empty registry).

This inventory must match `docs/EPISODE_RESOLUTION_ENGINE/README.md` §
Input-source inventory **1:1**, including the excluded list (Constraints,
binding). A source absent here is an omission to fix, never an implicit
input; an excluded source is present with `status: excluded`, never merely
absent.

`transport` encodes a machine-checkable binding for `live` entries
(AC3 -- rejected fail-loud if the binding does not resolve at load time):

- `outbox:<topic>` -- a topic constant registered in `app/events/types.py`.
- `module:<dotted.module.path>` -- an importable runtime consumer module
  (the generalized shape of "observation-log consumer path": every live,
  non-outbox stream below is read through a concrete runtime module exactly
  like `app.heimdal.observation_log`).

`planned` / `future` / `excluded` entries carry a descriptive `transport`
(or `null`) -- they name a source that is not yet, or will never be,
consumed, so no runtime binding is checked for them.

```yaml stream-registry
streams:
  # --- live -----------------------------------------------------------
  - stream_id: heimdal.observations
    status: live
    transport: "module:app.heimdal.observation_log"
    dimensions_fed: [time, protagonist, goal, causation]
    consent_class: heimdal_consent_gated
    cadence: bursty
    owner_constituent: Heimdal
    notes: "observation-log cursor; consent-gated via consent.grant_ref"

  - stream_id: vault.activity
    status: live
    transport: "outbox:ingest.vault.changed"
    dimensions_fed: [time, goal, causation]
    consent_class: vault_implicit
    cadence: bursty
    owner_constituent: Mimer
    notes: "also outbox ingest.object.created / ingest.object.deleted + extract_context_dimensions_for_note"

  - stream_id: chat.sessions
    status: live
    transport: "module:app.chat.session_log"
    dimensions_fed: [time, goal]
    consent_class: vault_implicit
    cadence: continuous
    owner_constituent: Mimer
    notes: "session log under .chats/, session_id, per-turn timestamps"

  - stream_id: decision.receipts
    status: live
    transport: "module:app.receipts.decision_receipt_log"
    dimensions_fed: [time, goal, causation]
    consent_class: vault_implicit
    cadence: sparse
    owner_constituent: Mimer
    notes: "WriteGuard-gated receipt log + decisions projection"

  - stream_id: kap.acquisitions
    status: live
    transport: "outbox:knowledge_acquisition.stage.completed"
    dimensions_fed: [time, goal]
    consent_class: vault_implicit
    cadence: sparse
    owner_constituent: Mimer
    notes: "content-origin, low situational weight"

  - stream_id: heimdal.attention
    status: live
    transport: "module:app.heimdal.attention_log"
    dimensions_fed: [goal, protagonist]
    consent_class: heimdal_adjacent
    cadence: continuous
    owner_constituent: Heimdal
    notes: "attention log, daily attention/YYYY-MM-DD.md"

  # --- planned ----------------------------------------------------------
  - stream_id: calendar
    status: planned
    transport: "caldav_ics_poll"
    dimensions_fed: [time, protagonist, space, goal]
    consent_class: per_calendar_scope_mapping
    cadence: sparse
    owner_constituent: "external via C3"
    notes: "ERE-09; read-only CalDAV/ICS poll, credentials in private-bindings"

  - stream_id: bifrost.native_capture
    status: planned
    transport: "governed_capture_api"
    dimensions_fed: [space, protagonist, causation]
    consent_class: heimdal_consent_gated
    cadence: bursty
    owner_constituent: "Bifrost->Heimdal"
    notes: "Epic B; governed capture API / direct FS per MIMER_CLIENT_CONTRACT"

  # --- future -------------------------------------------------------------
  - stream_id: location
    status: future
    transport: null
    dimensions_fed: [space, time]
    consent_class: heimdal_consent_gated_strict_optin
    cadence: null
    owner_constituent: Heimdal
    notes: "ERE-10; Heimdal v2 modality: location"

  - stream_id: screen
    status: future
    transport: null
    dimensions_fed: []
    consent_class: heimdal_consent_gated_posture_b
    cadence: null
    owner_constituent: Heimdal
    notes: "Heimdal v2 modality vocabulary"

  - stream_id: biometric
    status: future
    transport: null
    dimensions_fed: []
    consent_class: heimdal_consent_gated_posture_b
    cadence: null
    owner_constituent: Heimdal
    notes: "Heimdal v2 modality vocabulary"

  - stream_id: ambient_audio
    status: future
    transport: null
    dimensions_fed: []
    consent_class: heimdal_consent_gated_posture_b
    cadence: null
    owner_constituent: Heimdal
    notes: "Heimdal v2 modality vocabulary"

  # --- excluded (identified, deliberately out) -----------------------
  - stream_id: builderops.records
    status: excluded
    transport: null
    dimensions_fed: []
    consent_class: null
    cadence: null
    owner_constituent: BuilderOps
    notes: "BuilderOps records / LearningSignals -- dev-time builder telemetry, not lived situations"

  - stream_id: orchestrator.internals
    status: excluded
    transport: null
    dimensions_fed: []
    consent_class: null
    cadence: null
    owner_constituent: Orchestrator
    notes: "orchestrator/planner/MCP/agent-internal events -- machinery, not situations (the chat session is the lived-situation representative)"

  - stream_id: sync.transports
    status: excluded
    transport: null
    dimensions_fed: []
    consent_class: null
    cadence: null
    owner_constituent: Sync
    notes: "iCloud/Git sync transports -- Integration Fabric class 5, never semantic"

  - stream_id: egress.surfaces
    status: excluded
    transport: null
    dimensions_fed: []
    consent_class: null
    cadence: null
    owner_constituent: Companion
    notes: "notifications, TTS playback -- egress, not an input source"
```
