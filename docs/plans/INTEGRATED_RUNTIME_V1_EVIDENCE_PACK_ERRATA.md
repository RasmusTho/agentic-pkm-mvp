# Integrated Runtime v1 Evidence Pack Errata

Status: reconciliation addendum for
`docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md` against current `main`.
This does not rewrite the evidence pack, implement code, create issues, or
weaken any authority boundary.

Non-negotiable constraints remain unchanged:

- The vault remains the human/canonical surface.
- Runtime projections are not truth.
- No hidden writes.
- WriteGuard, receipts, source/projection separation, and event/receipt
  separation must not be weakened.
- Proportional governance remains a future design question.

## Errata Findings

### ERT-01 Capture is no longer library/test-only

- Evidence pack claim: Capture has "no UI route found", "no app route or CLI
  command found", and is "effectively library/test-only".
- Current main reality: `POST /api/companion/capture` is mounted through the API
  app and implements governed append to the vault inbox note. It validates
  plain text input, rejects task/due-date fields by schema, gates through
  WriteGuard, appends via `append_note_relative`, returns the writer receipt
  fields, and emits a metadata-only `capture.inbox.appended` event.
- Corrected interpretation: Capture is a shipped bounded intake path, not
  library-only. It is still narrow: it appends to the vault inbox as plain
  intake and is not a task system, reminder system, or hidden write path.
- Impact on Integrated Runtime v1 classification: move Capture from
  `experimental` toward `optional` or `core-candidate`, depending on whether
  v1 includes quick intake. It should not be treated as absent.
- Evidence anchors: `app/api/app.py:111`, `app/api/app.py:227`,
  `app/api/routes/capture.py:1`, `app/api/routes/capture.py:76`,
  `app/api/routes/capture.py:185`, `app/api/routes/capture.py:206`,
  `app/api/routes/capture.py:242`, `app/api/routes/capture.py:248`,
  `app/api/routes/capture.py:259`,
  `tests/api/test_capture_inbox_api.py:1`,
  `tests/companion_ui/test_capture_modal.py:1`.

### ERT-02 Capture has a Companion System Entry Point surface

- Evidence pack claim: Capture has no UI route found in inspected Companion
  entry points.
- Current main reality: `capture_modal.py` defines the `capture` overlay
  occupant opened by `Cmd/Ctrl+N` / `capture.open`; it posts to
  `/api/companion/capture`, preserves unsent draft text on dismiss, and labels
  offline captures as not yet written. The dev page imports the modal and emits
  its markup/script; the same-origin POST allowlist includes
  `/api/companion/capture`.
- Corrected interpretation: Capture has a shipped UI surface and same-origin
  proxy path. It is still session-honest rather than durable offline queueing,
  and the shipped topbar surface list does not include a capture icon; keyboard
  and overlay-host entry are the shipped path.
- Impact on Integrated Runtime v1 classification: Capture can be evaluated as
  an existing surfaced capability. Remaining v1 work is product-scope and
  operator-gating, not basic route discovery.
- Evidence anchors:
  `companion-ui/companion-app/companion_ui/workspace/capture_modal.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/capture_modal.py:46`,
  `companion-ui/companion-app/companion_ui/workspace/capture_modal.py:119`,
  `companion-ui/companion-app/companion_ui/workspace/capture_modal.py:154`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:37`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:60`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:72`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:117`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:65`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:9744`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10515`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:31`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:176`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:207`.

### ERT-03 Memory Review now has API endpoints and a review drawer

- Evidence pack claim: Memory Review has no first-class review API and no full
  review UI found.
- Current main reality: Companion API now exposes bounded read and governed
  decision endpoints at `/api/companion/memory/review-queue` and
  `/api/companion/memory/review-queue/{candidate_id}/decision`. The UI ships a
  `memory` overlay drawer that renders pending candidates, authority posture,
  provenance, governed accept/reject/revise actions, non-terminal defer, runtime
  outcomes, and receipts when the runtime produces them.
- Corrected interpretation: Memory Review is not merely posture projection.
  It has a shipped review surface. The useful warning that the queue machinery
  is bounded and based on the existing in-memory review queue still matters:
  v1 should verify persistence, activation/recall expectations, and restart
  behavior before classifying it as core memory.
- Impact on Integrated Runtime v1 classification: move from `experimental`
  toward `optional` or `core-candidate` for review workflow, with persistence
  and recall integration still gating core status.
- Evidence anchors: `app/api/routes/companion.py:2831`,
  `app/api/routes/companion.py:2847`,
  `app/api/routes/companion.py:2900`,
  `app/api/routes/companion.py:3046`,
  `app/api/routes/companion.py:3063`,
  `app/api/routes/companion.py:3076`,
  `app/api/routes/companion.py:3098`,
  `app/api/routes/companion.py:3133`,
  `app/api/routes/companion.py:3149`,
  `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py:53`,
  `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py:62`,
  `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py:267`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:80`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10388`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10533`,
  `tests/api/test_memory_review_queue_api.py:1`,
  `tests/companion_ui/test_memory_review_drawer.py:1`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:33`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:201`.

### ERT-04 System Entry Point child surfaces are more shipped than the pack says

- Evidence pack claim: The Companion UI is a dev/staging surface with route
  parity risk, and the integrated entry point needs to tie surfaces together.
- Current main reality: The System Entry Point spec now records shipped
  child surfaces for entry state, re-entry treatment, overlay host, Panel
  command palette, Capture, Memory Review, Receipts History, Settings, System
  Map, and guidance layer. The overlay host declares shipped occupants for
  `vault`, `capture`, `cmd`, `memory`, `receipts`, `settings`, and `map`.
- Corrected interpretation: The pack understated shipped shell composition.
  The remaining warning should be narrowed: the shell composition exists, but
  production/operator hardening and some legacy route parity gaps remain.
- Impact on Integrated Runtime v1 classification: System Entry Point remains
  `core`, with child-surface inventory upgraded from "missing composition" to
  "shipped composition requiring release gate verification".
- Evidence anchors:
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:23`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:29`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:31`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:33`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:35`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:37`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:39`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:41`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:190`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:51`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:60`,
  `companion-ui/companion-app/companion_ui/workspace/overlay_host.py:236`,
  `tests/companion_ui/test_entry_state_machine.py:1`,
  `tests/companion_ui/test_overlay_host.py:1`,
  `tests/companion_ui/test_system_map_overlay.py:1`,
  `tests/companion_ui/test_panel_command_palette.py:1`.

### ERT-05 Receipts history has a shipped read-only UI surface

- Evidence pack claim: There is no single unified operator receipt-history
  route found, and receipt visibility is fragmented.
- Current main reality: A receipts history modal is shipped as a read-only
  overlay over the existing vault-browser receipt projection. It renders a
  bounded recent list of runtime-produced receipt rows with outcome, id, target,
  timestamp, guard-held posture for blocked receipts, and honest empty/source
  unavailable states. It does not create, edit, aggregate, or invent receipts.
- Corrected interpretation: The warning should be narrowed from "missing
  visibility" to "visibility exists as a bounded UI projection over existing
  vault-browser receipts, not as a new authoritative receipt store or full
  retention/export system".
- Impact on Integrated Runtime v1 classification: Receipts visibility remains
  `core`; current main provides a shipped surface that can be part of the v1
  golden path, while durable receipt source coverage and retention/export
  remain release questions.
- Evidence anchors:
  `companion-ui/companion-app/companion_ui/workspace/receipts_history.py:1`,
  `companion-ui/companion-app/companion_ui/workspace/receipts_history.py:54`,
  `companion-ui/companion-app/companion_ui/workspace/receipts_history.py:66`,
  `companion-ui/companion-app/companion_ui/workspace/receipts_history.py:106`,
  `companion-ui/companion-app/companion_ui/workspace/receipts_history.py:189`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:102`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10406`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:35`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:178`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:208`,
  `tests/companion_ui/test_receipts_history_surface.py:1`.

### ERT-06 Route/proxy parity warning still applies, but not to the new SEP surfaces

- Evidence pack claim: Companion route parity is incomplete for visible
  controls including Vault related, Vault queue-review, Panel confirm, and
  several Canvas session/edit controls.
- Current main reality: Capture and Memory Review have same-origin proxy
  coverage. Receipts History uses a same-origin fragment route backed by the
  vault-browser projection. However, the current POST allowlist still does not
  include `/api/panel/confirm`, `/api/companion/vault-browser/actions/queue-review`,
  Canvas session open/edit/undo/close paths, or TTS status; the GET branches
  shown do not include `/api/companion/vault-related`. Older route-parity
  warnings therefore remain useful for those surfaces.
- Corrected interpretation: Do not carry a blanket "new child surfaces are
  dead affordances" warning. The precise warning is that route parity is fixed
  for capture, memory review decisions, and receipts-history fragments, while
  older Panel/Vault/Canvas/TTS gaps still need direct verification or hiding.
- Impact on Integrated Runtime v1 classification: Companion UI remains `core`,
  but route parity should be a release gate targeted at the remaining paths,
  not evidence that Capture/Memory/Receipts are absent.
- Evidence anchors:
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10351`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10372`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10385`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10388`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10406`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10515`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:10533`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:2905`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:2921`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:3770`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:3965`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:3995`,
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:4014`.

### ERT-07 Source Understanding remains mostly API-only in the checked surfaces

- Evidence pack claim: Source Understanding has no primary Companion route
  found and remains an optional read-only/proposal capability.
- Current main reality: The checked System Entry Point spec lists "Source peek"
  as shipped provenance presentation, but the Source Understanding P0 route
  itself remains an API route mounted from `app/api/app.py`. No Companion
  Source Understanding P0 apply surface was found in the checked files.
- Corrected interpretation: Keep the pack's Source Understanding warning, but
  avoid conflating it with the shipped source-peek/provenance presentation.
  Source peek is UI provenance; Source Understanding P0 remains a separate
  non-authoritative understanding projection without a governed apply path by
  default.
- Impact on Integrated Runtime v1 classification: `optional` remains accurate
  for Source Understanding P0.
- Evidence anchors: `app/api/app.py:106`, `app/api/app.py:225`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:160`,
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md:202`,
  `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md:244`.

## Reconciled Classification Deltas

| Capability | Evidence pack classification | Errata classification note |
| --- | --- | --- |
| Capture | experimental | Existing governed API + UI; optional or core-candidate, not absent. |
| Memory Review | experimental | Existing API + drawer; optional or core-candidate, with persistence/recall still gating core. |
| System Entry Point | core | Core remains; child-surface composition is now shipped and should be verified as release substrate. |
| Receipts history | core, missing unified surface | Core remains; bounded read-only history modal now exists over runtime projections. |
| Companion route parity | core release gate | Still a gate, but narrow it to remaining Panel/Vault/Canvas/TTS gaps. |
| Source Understanding P0 | optional | Still optional; source-peek UI does not equal governed Source Understanding apply. |

## Handoff Notes for Fable

- Do not remove the evidence pack's safety warnings. Instead, update the mental
  model: Capture, Memory Review, Receipts History, and several System Entry
  Point child surfaces are shipped but still need production/operator release
  gates.
- Do not treat receipts-history as a new authority store. It is a read-only
  bounded projection over runtime-produced receipt rows.
- Do not treat Memory Review accept/reject/revise as unconstrained memory
  authority. The drawer delegates to the runtime review boundary and receipts;
  defer is explicitly non-terminal and receipt-free.
- Do not treat Capture as tasks/reminders. It is governed vault inbox intake.
- Keep proportional governance open: this errata records shipped seams; it does
  not decide which flows should be fast-path versus governed in v1.
