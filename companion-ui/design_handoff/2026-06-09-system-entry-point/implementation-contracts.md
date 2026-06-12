# Implementation contract — System Entry Point

**Status:** Contract for UI integration · **target-state proposal**
**Mutates:** nothing on its own
**Depends on:** `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` (shipped), `companion-ui/docs/COMPANION_UI_STATE_MAP.md`, `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`, `companion-ui/docs/OVERLAY_GRAMMAR.md`, `companion-ui/docs/POSTURE_TRANSITIONS.md`, `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`, `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`, the gated-execution and authority-separation invariants.

## Position in the chain

This is the part of the package implementation reads. Everything else (README, design-notes, state-gallery, edge-states, authority-boundaries, open-questions) is guidance. The enums, attributes, and intents below are **proposals**: they reference fields the runtime exposes or could expose; they do not declare runtime schema. The server's declared class always wins; the UI renders and never re-classifies.

## Entry-point state enum (proposed)

The entry point is a small, explicit state machine. The implementation must enumerate exactly these states; adding or removing one without amending this document means the design no longer covers it.

| State | Meaning | Source signal |
|---|---|---|
| `boot` | Runtime handshake in progress. | request to `GET /api/companion/orientation` pending |
| `no_vault` | Runtime aggregate unreachable. | HTTP 503 `runtime_unavailable` |
| `cold_start` | First contact, or cold trajectory (> 14d): no admissible `leave_point`. | `leave_point.status: absent` (+ no warm/dormant signals) |
| `orienting` | Returning with a recoverable trajectory; re-entry surface shown. | `leave_point.status: present` |
| `shell_active` | Document anchor open; overlay layer available. | user resume / open action |

`orienting` carries a **re-entry shape** sub-attribute derived from the gap (latency ladder, `CONTINUITY_AND_DECAY.md`): `no_mist` (<90s) · `soft_mist` (15m–2h) · `full_mist` (2h–3d) · `long_mist` (3d–14d). The prototype demonstrates `full_mist` and `long_mist`; `cold_start` covers `>14d`.

Two **cross-flags** may decorate `orienting` and `shell_active` without being separate states:
- `degraded` — HTTP 200 partial snapshot; one or more `meta.degraded_reasons` present.
- `stale` — `leave_point.status: stale | artifact_missing | degraded` (re-entry still renders; resume is gated/qualified).

## Allowed transitions

```
boot ──▶ no_vault            (503)
boot ──▶ cold_start          (leave_point absent)
boot ──▶ orienting           (leave_point present)        [+degraded] [+stale]
no_vault ──▶ boot            (entry.retry)
cold_start ──▶ shell_active  (vault.open / vault.pick / map→surface)
orienting ──▶ shell_active   (entry.resume | entry.dismiss | vault.pick)
shell_active ──▶ boot         (deck: replay entry — prototype only)
```

Within `shell_active`, surface overlays open and close without leaving the state:

```
shell_active ⇄ rail(open|closed)           (Chat — canvas)
shell_active ⇄ overlay(cmd|vault|memory|peek|posture|map|settings|context|capture|receipts|tts)
shell_active: suggestion(staged ──▶ applied | discarded)   (body-edit lane)
shell_active: panel(proposal ──▶ confirming ──▶ executing ──▶ receipt)   (governed)
shell_active: panel(proposal ──▶ blocked)                  (WriteGuard deny)
```

Implementation must reject any transition not enumerated here. Every overlay transition returns to the document anchor; none performs a route-level reset (`OVERLAY_GRAMMAR.md`).

## Data attributes (stable selectors)

Required attributes the design relies on. Adding new attributes is permitted; renaming is not.

| Attribute | On | Purpose |
|---|---|---|
| `data-screen-label` | `#shell`, `#entry` | Names the high-level screen for comment/test context. |
| `data-region="reentry-card"` | re-entry card | The orientation re-entry surface. |
| `data-region="delta-strip"` | long-mist delta list | "What changed" strip. |
| `data-traj-state` | re-entry card | `warm \| dormant` (server-declared trajectory state; never UI-derived). |
| `data-region="document-anchor"` | topbar anchor pill | The current anchor identity. |
| `data-region="document-column"` | doc column | The primary cognitive anchor surface. |
| `data-region="chat-rail"` | rail | Chat (canvas) surface. |
| `data-region="suggestion-block"` | staged block | Canvas suggestion-flow body-edit object. |
| `data-suggestion-id` | staged block | Stable suggestion id. |
| `data-prop` | Panel proposal row | Stable proposal id. |
| `data-rail="open\|closed"` | `.shell-body` | Rail visibility. |
| `data-guidance="on\|''"` | `#stage` (root) | Opt-in explanatory guidance layer; absent/empty = off (established-user default). |
| `data-textsize="sm\|''\|lg"` | `#stage` (root) | Local display preference (byte-unchanged re-render). |
| `data-region="capture-input"` | capture textarea | Friction-free capture field. |
| `data-intent="…"` | any actionable | The intent vocabulary below. |

## Intent vocabulary

Each `data-intent` declares its surface, effect, and whether it routes through the governance pipeline. Implementation must not emit intents not declared here; adding one requires amending this document.

| Intent | Surface | Effect | Routes through pipeline? |
|---|---|---|---|
| `entry.retry` | no_vault | re-request orientation (read-only) | no |
| `entry.resume` | orienting | → `shell_active` at the leave-point | no (navigation) |
| `entry.dismiss` | orienting | → `shell_active`, fresh | no |
| `vault.open` | shell / entry | open Vault Browser overlay (read-only) | no |
| `vault.pick` | Vault Browser | re-anchor shell to a note (`GET /api/companion/workspace?note_path`) | no (read) |
| `vault.queue` | Vault Browser | `queue_review` | **yes — governed handoff** |
| `cmd.open` | shell (`⌘K`) | open Panel command surface | no |
| `panel.confirm` | Panel | confirm a governed proposal | **yes — `GovernanceRouter` → execute → receipt** |
| `panel.blocked` | Panel | attempt a guard-denied action | **yes — WriteGuard deny, returns blocked receipt** |
| `suggestion.apply` | document | body edit via `canvas_writer.apply_edit` | body-edit lane — **no governance receipt** |
| `suggestion.discard` | document | drop staged proposal (UI-local) | no |
| `source.peek` | document / rail | open provenance popover (read-only) | no |
| `memory.open` | shell / re-entry inspect | open memory candidate review | no (read + intent) |
| `memory.accept` | memory review | promote candidate | **yes — governed decision** |
| `memory.defer` / `memory.reject` | memory review | UI-local review-queue action | no |
| `posture.open` / `posture.set` | shell | shift cognitive emphasis | no (carry-forward preserved) |
| `map.open` | shell / entry | open system map | no |
| `rail.open` / `rail.close` | shell | toggle Chat rail | no |
| `rail.send` | Chat | propose into conversation | no (cannot commit to vault) |
| `overlay.dismiss` | any overlay | return to document anchor | no |
| `guidance.toggle` | shell / entry / any overlay head | toggle the opt-in explanatory guidance layer (UI-local; default off for the established user) | no |
| `settings.open` | shell / map | open Settings (Local UI) | no |
| `settings.set` | Settings | set a display/listening preference (Local UI; byte-unchanged) | no |
| `settings.reset` | Settings | reset display preferences to canonical | no |
| `tts.read` | document / map | open the read-back SpeechPlan (`POST /api/companion/tts/plan`) | no (read; after human action) |
| `tts.play` | read-back popover | synthesize + play (`POST /api/companion/tts/synthesize`) | no (read-only; never a mutation endpoint) |
| `context.open` | shell / map | open the Context lane (time + place salience) | no (read-only) |
| `location.enable` | Context lane | opt in to location focus (Local UI; local-first) | no |
| `capture.open` | shell (`⌘N`) / map | open Capture | no |
| `capture.save` | Capture | append the capture to the vault inbox | **yes — governed write** |
| `receipts.open` | shell / map | open the read-only receipts/history surface | no |

## Server contract surface (consumed, not declared)

- `GET /api/companion/orientation` → `WORKSPACE_ORIENTATION_CONTRACT.md`. The entry point renders `leave_point`, `open_loops`, `notable_changes`, `resurface.candidates`, `memory.pending_candidate_count`, `governance` summary, `guards`, and `mutation_intents` **as supplied**. It applies the cognitive-load display budget (a scarce displayed subset) on top of the server caps. It never widens collections, never classifies MemoryCandidate-worthiness locally, and never executes a `mutation_intent`.
- `GET /api/companion/workspace?note_path=…` → artifact-scoped re-anchor (`WORKSPACE_STATE_CONTRACT.md`).
- Panel confirm path → `POST /api/panel/confirm` (governed; `PANEL_COMPANION_UI_CONTRACT.md`).
- `queue_review` → `POST /api/companion/vault-browser/actions/queue-review` (governed handoff).
- Body edit → `canvas_writer.apply_edit` (body-edit lane; no receipt — `CANVAS_SUGGESTION_FLOW.md`).
- `/api/status` owns detailed runtime health; the entry point shows only a derived coarse posture in the vault-status dot.
- **Read-back (TTS):** `POST /api/companion/tts/plan` / `…/synthesize` / `GET …/tts/status` (`LOCAL_FIRST_TTS_CONTRACT.md`). Local-only; plan inspected before synthesis; runs only after a human action; never routed through a save/Panel/workspace endpoint; no autoplay.
- **Display / listening preferences:** Local UI state per `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`. Re-renders identical content; the canonical Markdown hash is byte-unchanged; a local-only indicator shows on any diverging render; preferences never reach a save/projection endpoint or the vault.
- **Capture:** `capture.save` appends to the vault inbox through the governed write path (policy → validation → deterministic writer). It is intake, not an app-owned task store; captures carry no due date and are surfaced later only by relevance.
- **Context lane (time + place):** read-only salience over existing material. No owner-doc grounds a calendar or location source yet — these are **proposals/placeholders** (see `open-questions.md` Q15–Q16). The lane never pushes, badges, or escalates to urgency.

## Authority-class rendering

The entry point renders server-declared authority via the `authority-tag` / `receipt-pill` components and the color mapping in `CORE_TERM_MAPPING.md` (`read` / `proposal` / `governed` / `receipt`). It must not infer governance, memory authority, urgency, salience, or actionability locally.

## Validation expectations

A passing validation receipt for this package would render the full state gallery against fixture orientation snapshots and verify:
- every declared entry-point transition, and rejection of undeclared ones;
- no UI-derived posture / class / authority anywhere;
- the cold (>14d) and `no_vault` states show **no** re-entry overlay;
- governed intents route through the pipeline and surface receipts; body edits do not;
- blocked/stale present as guard-held states, not generic errors;
- the cognitive-load display budget caps visible items below the server caps;
- reduced-motion is respected and all content is visible without animation;
- narrow/portrait preserves every critical affordance (rail → bottom sheet).

The exact fixture set is owned by the implementation issue, not this document.

## What this contract does not say

Free for implementation to choose: framework, styling technique, animation library (none required), client cache shape, network transport, and the exact pixel layout. This contract fixes the **state model, the surface composition, the authority postures, and the intent/attribute vocabulary** — not the rendering technology.
