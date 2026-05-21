---
name: Companion UI MLP Capability Matrix
description: Current-state classification matrix for visible Companion UI MLP affordances and their backing runtime behavior.
doc_role: Foundation matrix
authority: Classifies visible Companion UI MLP affordances against current implementation evidence; subordinate to source-of-truth contracts and shipped behavior.
owner: Companion UI product + runtime integration
status: Current-state foundation for #1177 MLP implementation
last_reviewed: 2026-05-21
related_issues: "#1177, #1178, #1179, #1180"
---

# Companion UI MLP Capability Matrix

## Purpose and scope

This document classifies visible Companion UI MLP affordances by actual backing behavior. It exists to prevent the server-rendered Companion UI shell from implying authority, persistence, or execution that is not currently backed by runtime behavior.

Scope:

- Companion UI MLP path: `Open note -> Reorient -> Canvas body edit -> Panel Act -> Receipt`.
- Current server-rendered Companion UI shell and workspace API.
- Current Canvas and Panel runtime endpoints where they exist.
- Current read-side Reorient, Resurface, and Find presentation in the workspace shell.

Out of scope:

- New runtime behavior.
- New UI behavior.
- New event contracts.
- Production launch acceptance.
- Full #1177 closeout.

## Authority guardrails

- Companion UI is a shell/host, not a fourth authority surface.
- Vault / Markdown remains the human-readable canonical surface.
- Runtime owns policy, WriteGuard, idempotency, action handling, events, receipts, and durable projection.
- Companion UI does not write vault files directly.
- Companion UI does not reclassify server-declared proposals locally.
- Panel and Canvas remain separate.
- Canvas is body-edit/co-authoring only.
- Panel / Act is governed proposal confirmation.
- Reorient is read-side recovery, not execution.
- Resurface is low-pressure and must not imply urgency unless runtime provides urgency.
- Find must not imply full retrieval capability when no backend payload exists.

## Classification legend

| Classification | Meaning |
| --- | --- |
| `render_only` | UI can display the affordance/state from current page or payload state, but the UI action itself has no confirmed runtime write backing. |
| `runtime_read` | Current runtime/API provides read-side payload or state used by the UI. |
| `runtime_write` | Current UI/runtime path can call a runtime endpoint that mutates runtime or governed artifact state. |
| `durable_projected` | Current runtime path projects a result into a vault-visible artifact, session log, outbox, or other durable store. |
| `receipt_bearing` | Current path exposes a user-visible receipt, receipt pill, or block outcome. |
| `unavailable` | Capability is absent, blocked, placeholder-only, or intentionally non-actionable in the current MLP. |
| `experimental` | Capability exists only in dev/staging, behind a flag, with in-memory state, or without production launch acceptance. |
| `production_ready` | Capability has documented and tested production launch posture. Do not use this flag unless that proof exists. |

## Capability matrix

| Capability / affordance | Classification | Current backing | Current MLP note |
| --- | --- | --- | --- |
| Load real note | `runtime_read`, `experimental` | `GET /api/companion/workspace`; dev/staging shell calls runtime API. | Runtime-bound read. UI does not choose or read the vault directly. Not marked `production_ready`. |
| Display artifact identity | `runtime_read`, `render_only`, `experimental` | Workspace API returns `artifact.artifact_id`, `identity_source`, `identity_state`. | Display only; unresolved identity must remain visible. |
| Display note path | `runtime_read`, `render_only`, `experimental` | Workspace API returns runtime-relative `artifact.note_path`. | Display only; path is runtime-provided. |
| Display content hash | `runtime_read`, `render_only`, `experimental` | Workspace API returns `artifact.content_hash`; Canvas edit calls send hash. | Used for conflict visibility and Canvas hash guard. |
| Display runtime/channel label | `runtime_read`, `render_only`, `experimental` | Workspace API returns `runtime.environment_label` and `api_base_url_label`. | Current labels are minimal and may be `unknown` / `local-dev`. |
| Display vault/channel identity if available | `render_only`, `unavailable` | Workspace API does not expose a named vault/channel identity field beyond runtime/API labels. | UI should show unavailable/fallback until runtime exposes safe read-only identity. |
| Display WriteGuard status | `runtime_read`, `render_only`, `experimental` | Workspace API returns `guards.writeguard_status`. | Display only in shell; runtime still owns enforcement. |
| Display Canvas enabled/disabled state | `runtime_read`, `render_only`, `experimental` | Workspace API returns `guards.canvas_enabled`; Canvas endpoints enforce `CANVAS_ENABLED`. | Disabled state must block Canvas mutation affordances. |
| Open Canvas session | `runtime_write`, `durable_projected`, `experimental` | `POST /api/canvas/sessions`; session log writer opens session. | Session registry is in-memory; log path is runtime-owned. |
| Close Canvas session | `runtime_write`, `durable_projected`, `experimental` | `DELETE /api/canvas/sessions/{id}`; runtime closes session log. | In-memory session is removed; durable log remains. |
| Apply Canvas body edit | `runtime_write`, `durable_projected`, `experimental` | `POST /api/canvas/sessions/{id}/edits`; runtime CanvasWriter owns note write. | Body-only; guarded by active session and optional content hash. No direct UI vault write. |
| Undo Canvas body edit | `runtime_write`, `durable_projected`, `experimental` | `DELETE /api/canvas/sessions/{id}/edits/last`; runtime writes prior body through CanvasWriter. | Available only when runtime/UI state says the last edit is undoable. |
| Display Canvas recovery/conflict state | `runtime_read`, `render_only`, `experimental` | Workspace API returns recovery state; shell also detects local content-hash/session conflict. | Read/display state; conflict acknowledgement is local in current shell. |
| Acknowledge Canvas recovery/conflict | `render_only`, `experimental` | Local dev-page acknowledgement token. | Not durable and not runtime-write; must be treated as volatile UI state. |
| Render staged body suggestion | `runtime_read`, `render_only`, `experimental` | Workspace suggestions payload; UI renders only server-declared `body` classification. | UI must not reclassify. |
| Apply staged body suggestion | `runtime_write`, `durable_projected`, `experimental` | UI maps staged body suggestion to `POST /api/canvas/sessions/{id}/edits`. | Body edit only; no Panel receipt. |
| Render staged governance suggestion | `runtime_read`, `render_only`, `experimental` | Workspace suggestions payload; UI renders only server-declared `governance` classification. | No Apply button for governance-bearing suggestions. |
| Queue staged governance suggestion | `runtime_write`, `receipt_bearing`, `experimental` | `POST /api/canvas/sessions/{id}/governance`; runtime stages Panel proposal and UI shows receipt pill. | Queued/staged, not executed. Durable projection is not claimed here. |
| Display governance receipt pill | `render_only`, `receipt_bearing`, `experimental` | UI builds `ReceiptPill` from governance queue response. | User-visible receipt/status pill; not claimed as durable. |
| Render Panel state | `runtime_read`, `render_only`, `experimental` | Workspace API returns `panel.state`, counts, latest outcome/block reason. | Display only; Panel authority remains runtime-owned. |
| Render Panel proposal | `runtime_read`, `render_only`, `experimental` | Workspace payload can include server/runtime proposal rows. | UI renders proposals and affordances; no local classification. |
| Inspect Panel proposal evidence | `runtime_read`, `render_only`, `experimental` | Proposal evidence fields render from payload. | Evidence disclosure/display only. |
| Confirm Panel proposal | `runtime_write`, `durable_projected`, `receipt_bearing`, `experimental` | `POST /api/panel/confirm`; runtime owns policy, WriteGuard, idempotency, execution, receipts/events. | Same-turn and WriteGuard blocked paths are runtime-enforced. |
| Correct Panel proposal | `runtime_write`, `durable_projected`, `receipt_bearing`, `experimental` | UI submits correction in `POST /api/panel/confirm`; runtime applies correction semantics. | Explicit correction only; no silent local mutation. |
| Reject Panel proposal | `runtime_write`, `receipt_bearing`, `experimental` | `POST /api/panel/confirm` with `action=reject`; runtime returns rejected outcome. | Rejection is scoped to one proposal. Durable write may be skipped when WriteGuard blocks, so durable projection is not claimed generically. |
| Display Panel receipt | `runtime_read`, `render_only`, `receipt_bearing`, `experimental` | Workspace shell displays last Panel confirmation response and workspace panel latest outcome. | Receipt visibility is user-facing; runtime owns receipt production. |
| Display Panel block reason | `runtime_read`, `render_only`, `receipt_bearing`, `experimental` | Panel confirm response and workspace panel state expose block reason. | Blocked state must remain visible. |
| Render Reorient sections | `runtime_read`, `render_only`, `experimental` | Workspace API calls orientation runtime and maps facts/inferences/candidates/stale context. | Read-side recovery only. |
| Reorient Panel handoff | `render_only`, `unavailable`, `experimental` | Shell can render a Panel handoff button from payload marker. | No distinct durable handoff behavior is claimed in current MLP. |
| Render Resurface candidates | `runtime_read`, `render_only`, `experimental` | Workspace API calls read-only resurfacing runtime and shell renders candidates, empty state, or degraded state. | Low-pressure candidate display; no urgency unless payload says so. |
| Resurface dismiss | `render_only`, `unavailable` | Shell renders a disabled dismiss control; no persistence endpoint is present in current MLP. | Explicitly marked unavailable and not persistence-backed until persistence exists. |
| Resurface snooze | `render_only`, `unavailable` | Shell renders a disabled snooze control; no persistence endpoint is present in current MLP. | Explicitly marked unavailable and not persistence-backed until persistence exists. |
| Resurface pin | `render_only`, `unavailable` | Shell renders a disabled pin control; no persistence endpoint is present in current MLP. | Explicitly marked unavailable and not persistence-backed until persistence exists. |
| Render Find candidates | `render_only`, `unavailable`, `experimental` | Shell can render candidates if a payload exists, but workspace aggregate does not provide a full Find backend payload today. | Candidate display only; no full search product claim. |
| Find unavailable state | `render_only`, `unavailable` | Required MLP state for missing backend payload. | Should be explicit rather than silent absence. |
| Production launch profile | `unavailable`, `experimental` | Dev server documents port/bind defaults; production safety issue #1188 remains open. | Not `production_ready` until #1188 defines and verifies launch safety. |

## Current implementation notes

- The current Companion UI shell is explicitly dev/staging unless a later production launch pass promotes a supported profile.
- Workspace loading is runtime-bound through `GET /api/companion/workspace`; the UI does not read vault files and does not select a vault path.
- Canvas endpoints are real runtime endpoints, but `CANVAS_ENABLED` gates access and session registry state is in-memory.
- Canvas body edits and undo route through the runtime writer path and may durably change the active note body.
- Canvas governance suggestions queue/stage Panel proposals; they do not execute governance mutations from Canvas.
- Panel confirmation uses `POST /api/panel/confirm`; runtime owns policy, WriteGuard, idempotency, events, receipts, and durable projection.
- Reorient and Resurface are read-side in the current workspace shell.
- Find candidate rendering exists as a shell capability, but no full backend Find payload is claimed by this matrix.
- Resurface dismiss/snooze/pin controls are currently not backed by durable persistence and render as unavailable/not persistence-backed.

## Known MLP gaps

- No capability in this matrix is marked `production_ready`.
- Vault/channel identity is not yet exposed as a dedicated safe read-only workspace field.
- Find unavailable and empty states still need explicit UI treatment under #1187.
- Affordance status markers for all major rail cards/actionable sections are handled by #1179.
- Real-note shell metadata and runtime/channel identity polish are handled by #1182.
- Canvas recovery/conflict acknowledgement is currently local/volatile in the shell.
- Production launch command, bind-address safety, health checks, rollback/stop procedure, and limitations are handled by #1188.

## Rules for updating the matrix

- Any PR changing visible Companion UI affordances must update this matrix when a classification changes.
- Any PR adding a runtime write path must classify whether it is `runtime_write`, `durable_projected`, and/or `receipt_bearing`.
- Any PR adding or removing persistence for a visible control must update the row from `render_only` / `unavailable` to the accurate backed state, or vice versa.
- Do not add `production_ready` without a documented and tested production launch path.
- Do not add `durable_projected` unless the current runtime projects to a vault-visible artifact, session log, outbox, or other durable store.
- Do not add `receipt_bearing` unless the user can see a receipt, receipt pill, or block outcome.
- If backing behavior is unclear, mark the capability `experimental` or `unavailable` until the implementation issue proves otherwise.
