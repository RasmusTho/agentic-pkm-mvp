State: Normalized spec (Crossing B output for the 2026-06-09 system-entry-point handoff package). Defines target-state entry/shell composition over shipped surfaces; shipped-vs-new status is declared per surface and nothing unshipped is claimed as current behavior.
Doc role: Normalized spec / entry-point and shell composition contract
Authority: Normalized-spec authority for the entry-point state model, re-entry treatment, and unified-shell/overlay composition. Per-surface behavior remains owned by the per-surface owner contracts named in the composition table; where this spec appears to disagree with an owner contract, the owner contract wins and the passage here is corrected.
Owner: Companion UI / interaction model
Temporal class: stable
Review cadence: event-driven
Source of truth: authoritative for entry/shell composition; per-surface authority remains with owner contracts; runtime truth remains with shipped code, tests, and docs/STATUS.md
Last reviewed: 2026-06-20
Last verified against: tests/companion_ui/test_entry_state_gallery.py (state-gallery validation harness, #1795), companion-ui/design_handoff/2026-06-09-system-entry-point/, companion-ui/design_handoff/2026-06-19-cold-start-threshold/implementation-contracts.md, companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md (§recents_anchor, #2176), companion-ui/docs/WORKSPACE_STATE_CONTRACT.md, companion-ui/docs/COMPANION_UI_STATE_MAP.md, companion-ui/docs/OVERLAY_GRAMMAR.md, companion-ui/docs/POSTURE_TRANSITIONS.md, companion-ui/docs/CONTINUITY_AND_DECAY.md, companion-ui/docs/ATTENTION_MODEL.md, companion-ui/docs/CANVAS_SUGGESTION_FLOW.md, companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md, companion-ui/docs/DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md, companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md, companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md, companion-ui/docs/CORE_TERM_MAPPING.md, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/CANVAS_CHAT_SURFACE/README.md, companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py

# System Entry Point — Normalized Spec

## Purpose and position in the chain

This is the normalized spec for the `2026-06-09-system-entry-point` design handoff package, authored at Crossing B of the chain defined in `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` (exploration → handoff package → **normalized spec** → GitHub issue → PR → validation receipt).

The entry point is the companion's front door: **a door into continuity of thought, not a dashboard.** Today the companion's surfaces (orientation, active-note workspace, Vault Browser, Panel, canvas co-authoring, TTS read-back, receipts) each shipped as their own slice; there is no single declared composition that says how a person enters, how the shell hangs together, and how every overlay returns to the document. This spec declares that composition.

Anti-dashboard posture is normative: the entry point must never become a home screen of cards, counts, and feeds filled with manufactured activity (`COGNITIVE_PRINCIPLES.md`: "No AI-dashboard posture"; `SYSTEM_OVERVIEW.md`). The document is the front door, and orientation is how you walk through it.

## Shipped-reality baseline (what this spec composes)

This spec composes — it does not replace — the shipped Companion UI:

- The Companion UI is a server-rendered page: `render_index_html()` in `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` (dev/test) with `serve_production_page.py` importing the same renderer. Vanilla JS, inline CSS on Yggdrasil tokens, `data-testid`/`data-region` test attributes; tests in `tests/companion_ui/`.
- The renderer today hard-branches between an **orientation page** (when no note is active) and the **adaptive 3-column workspace page** (vault-browser left pane | note body | agent rail) shipped via #1395. That 3-column workspace is a settled production decision. The handoff prototype's drawer-based layout is **mapped onto** the shipped layout, not adopted as a replacement: the design's "Vault Browser as left drawer overlay" maps to the existing left pane and its narrow-mode modal behavior; the design's "Panel command palette" is a new presentation over the existing Panel rail, not a relocation of Panel authority.
- Already shipped and consumed as-is: the orientation surface (`GET /api/companion/orientation`), the document anchor, the vault browser (browse/find/outline + governed `queue_review`), Panel rail proposals (`POST /api/panel/confirm`, checkbox projection), canvas co-authoring (server-gated, `CANVAS_ENABLED`), TTS read-back (plan/synthesize/status), receipts read-only projection, the help guide page (`/help`, #1755), the diagnostics popover (`?diagnostics=1`, #1758), display preferences (#1675), and responsive collapse.

Every surface this spec defined as new has now shipped (the final two — the user-facing system map overlay, #1787, and the opt-in guidance layer, #1788 — are described below); only the §Surface composition rows still marked **new** (source-peek popover presentation, posture emphasis switch) and the §Parked items remain undelivered. The entry-point state machine as a declared wrapper over the existing orientation/workspace branch is **shipped** (#1783): `resolve_entry_state()` in `companion-ui/companion-app/companion_ui/workspace/entry_state.py` resolves the five-state enum server-side and declares it on the shell root (`data-entry-state`, plus `data-reentry-shape` when orienting and the `data-degraded` / `data-stale` cross-flags); tests in `tests/companion_ui/test_entry_state_machine.py`. The re-entry mist latency-ladder treatment is **shipped** (#1784): the orientation surface renders the per-shape `orienting` treatments server-side — the four-fixed-questions card (`data-region="reentry-card"`, `data-traj-state`) for full/long mist, the long-mist delta strip (`data-region="delta-strip"`) and narrow-suppressed whisper column, the soft-mist peripheral cue, the thread-fade fractional rail fade, the amber degraded banner, the guard-held stale resume, the §Resolved Q5 display budget, and the residual ambient layer in `shell_active`; tests in `tests/companion_ui/test_reentry_orientation_treatment.py`.

The unified-topbar consolidation, the shared overlay host, and the keyboard map are **shipped as substrate** (#1785, SEP-03): the workspace header (`data-region="workspace-header"`) carries the anchor pill (`data-region="document-anchor"`), the rendering-only posture pill (`data-posture-emphasis`, prototype default `recovery`; the switch overlay has not shipped), surface icons for shipped surfaces only (vault, map, memory, receipts, settings, help — no dead affordances), and the coarse vault-status dot (`data-coarse-posture`; detailed health stays with `/api/status`). The overlay host (`data-region="overlay-host"`, pure model in `companion-ui/companion-app/companion_ui/workspace/overlay_host.py`) enforces the overlay-grammar rule in one place — declared-id registry, `Esc`/scrim dismiss-to-anchor with no route reset and no data loss — with the narrow-mode vault-browser modal as its first occupant; `⌘K`/`⌘N` are reserved and wired to `cmd.open`/`capture.open`. The ⌘K Panel command palette is **shipped** (#1786, SEP-04): `companion-ui/companion-app/companion_ui/workspace/panel_palette.py` registers the host's `cmd` occupant and presents the **same** server-declared Panel proposals as the rail (identical `data-proposal-id`s, status, and actions), declares the rail's `POST /api/panel/confirm` transport with no palette-local execution or receipt invention, renders WriteGuard denials as the calm guard-held state, and states Panel ≠ Chat with a filter-only input (grammar deferred, package Q12); tests in `tests/companion_ui/test_panel_command_palette.py`. The ⌘N capture modal is **shipped** (SEP-08b, #1791): `companion-ui/companion-app/companion_ui/workspace/capture_modal.py` registers the host's `capture` occupant — a top modal opened via `⌘N` / `capture.open` — with a `data-region="capture-input"` textarea and a "Capture to inbox" action (`capture.save`) that posts to the shipped governed endpoint (`POST /api/companion/capture`, #1790); session captures accumulate in the session list with written/not-yet-written state bound to the runtime acknowledgement; offline captures are plainly labeled not yet written and no text is silently dropped; dismissal routes through the host back to the anchor with unsent text preserved and no route reset; no due-date field and no task states (spec §Resolved Q17); tests in `tests/companion_ui/test_capture_modal.py`. The remaining overlay **surfaces** (source peek, posture switch) remain new per their own tasks; tests in `tests/companion_ui/test_overlay_host.py`.

The memory candidate review drawer is **shipped** (SEP-09: #1792 endpoints + #1793 drawer): the runtime serves the bounded review-queue read (`GET /api/companion/memory/review-queue`) and the governed decision path (`POST /api/companion/memory/review-queue/{candidate_id}/decision`) over the existing `agent_memory.review_queue` machinery (accept promotes only through `app.agent_memory.promotion` per ADR-0009; reject/revise are durable, receipt-bearing review outcomes; defer is non-terminal and receipt-free); tests in `tests/api/test_memory_review_queue_api.py`. The drawer (`companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py`) mounts on the overlay host as the `memory` occupant — reached from the topbar surface icon and from the re-entry card's unresolved-inspect affordance (`memory.open`), dismissing to the anchor — and renders the "Unreviewed memory is not semantic authority" callout, the pending candidates with why-now/provenance/authority posture, and the four actions; outcomes and receipts come from the runtime and a governed refusal (409) renders calm with the candidate still pending; tests in `tests/companion_ui/test_memory_review_drawer.py`.

The receipts history modal is **shipped** (#1794, SEP-10): `companion-ui/companion-app/companion_ui/workspace/receipts_history.py` registers the host's `receipts` occupant — a top modal opened from the topbar surface icon (`receipts.open`), dismissing through the host back to the anchor — and renders a bounded recent list of the existing runtime-produced receipt projections (the vault-browser `notes[].receipts` rows over governed outbox records, `app/receipts/artifact_receipts.py`) with outcome, id, target, and timestamp verbatim. The surface is strictly read-only: reads only, no receipt creation, no mutation affordance, and no receipt invented, edited, or re-derived; blocked receipts render with calm guard posture per `BLOCKED_AND_STALE_STATE_SPEC.md`, visually distinct from generic errors, and an empty history renders honestly with no manufactured rows; tests in `tests/companion_ui/test_receipts_history_surface.py`.

The Settings drawer is **shipped** (SEP-07, #1789): `companion-ui/companion-app/companion_ui/workspace/settings_drawer.py` registers the host's `settings` occupant — a right drawer reached from the topbar surface icon (`settings.open`), dismissing to the anchor — with Display / Listening / Behaviour / Connection sections. Display consolidates the shipped #1675 controls in presentation only (the form moved into the drawer; its `companion.displayPreferences.v1` storage and apply mechanism are unchanged and stay the single owner of display state). Listening (modality/speed) is render-only pacing over the shipped read-back; Behaviour holds the stored guidance-layer default (`data-guidance="on"`) and quiet hours, which dampen ambient salience presentation only per §Resolved Q18 (opacity on ambient cues; no timers, no notification machinery); Connection is a read-only posture display that never offers vault selection. Per §Resolved Q19 the storage home is browser-local state, the canonical content hash is byte-unchanged across any preference change, a `local-only render` badge appears on divergence, and reset-to-canonical is always available; tests in `tests/companion_ui/test_settings_drawer.py`.

The system map overlay is **shipped** (#1787, SEP-05): `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py` registers the host's `map` occupant — a renderer/router index (Projection) per §Resolved Q4 — rendering the entry-point center node plus one node per §Surface composition table surface with its product mode (Find/Reorient/Resurface/Act per `docs/COMPANION_UI_PRODUCT_SPEC.md`, or a truthful `local-ui` chip), how it is reached, how it returns, and its truthful shipped/partial/new status mirrored from the table (the map re-classifies nothing). Shipped surface nodes route through existing affordances only (host mounts, `vaultBrowser.focus()`, pane focus) after dismissing back to the anchor; unshipped/partial nodes are present but visibly inert; parked surfaces (context lane / place band, §Parked Q15–Q16) render only as a non-interactive parked note. It is pull-based and never shown unbidden: opened only by explicit `map.open` affordances — the topbar surface icon on the shell, and a calm affordance on the orientation surface (`cold_start` / `no_vault`) and the no_vault error page; tests in `tests/companion_ui/test_system_map_overlay.py`.

The opt-in guidance layer is **shipped** (SEP-06, #1788): `companion-ui/companion-app/companion_ui/workspace/guidance_layer.py` is a cross-cutting layer (not a host occupant) splitting "help" into its two kinds — evidence (provenance lines, authority tags, receipt pills: always present, terse, untouched by the layer) and explanation (opt-in callouts, off by default in every entry state). The `ⓘ` affordance (`guidance.toggle`) renders in the topbar, in each shipped overlay-host occupant head (vault, cmd, capture, memory, receipts, settings, map), and on the re-entry card; it flips the shell-root `data-guidance="on"` attribute (absent = off) and the stylesheet reveals the server-rendered `.callout.guidance` blocks describing each surface and the re-entry model. The toggle is UI-local: nothing persisted (reload → off again), no save/projection endpoint reached, no content semantics changed; the stored guidance-layer *default* remains owned by the Settings drawer's Behaviour section (#1789), which applies the same root attribute at load — the toggle is the session-local override on top of it. Callouts deep-link into the shipped `/help` guide (#1755), which remains the long-form document; tests in `tests/companion_ui/test_guidance_layer.py`.

## Term mapping

Design language in the handoff package maps to architecture language per `companion-ui/docs/CORE_TERM_MAPPING.md`. Additional mappings introduced by this spec:

| Design language (package) | Architecture language (this spec) | Authority source |
|---|---|---|
| "front door" / "entry point" | entry-point state model over the orientation/workspace branch | this spec (normative below) |
| "unified shell" | the shipped adaptive workspace page plus the overlay host declared here | this spec; `WORKSPACE_STATE_CONTRACT.md` |
| "re-entry mist" | re-entry shape per the latency ladder | `CONTINUITY_AND_DECAY.md` |
| "system map" | system map overlay (pull-based projection) | this spec §Resolved Q4 |
| "posture" (user-switchable) | **local posture emphasis** (Local UI) | this spec §Resolved Q6; `POSTURE_TRANSITIONS.md` |
| "cognitive mode" (runtime-declared) | **server-declared cognitive mode** | this spec §Resolved Q6; `COGNITIVE_MODES.md` |
| "capture" | governed append to the vault inbox | this spec §Resolved Q17 |
| "context lane" / "place band" | parked placeholders (Q15–Q16) | this spec §Parked |
| "Hugin chat margin rail" | chat rail slot; implementation owned by the canvas-chat lane | `docs/CANVAS_CHAT_SURFACE/README.md` |

## Entry-point state model (NORMATIVE)

### State enum

The entry point is a small explicit state machine wrapping the existing renderer branch. Implementations must enumerate exactly these states; adding or removing one is a change to this spec.

| State | Meaning | Source signal |
|---|---|---|
| `boot` | Runtime handshake in progress. | request to `GET /api/companion/orientation` pending |
| `no_vault` | Runtime aggregate unreachable. | HTTP 503 `runtime_unavailable` (`WORKSPACE_ORIENTATION_CONTRACT.md §Runtime Unavailable`) |
| `cold_start` | First contact, or cold trajectory (> 14 days): no admissible `leave_point`. Renders the **intent-declaration threshold** (vault chip + honest headline + verb-line Find/Jot/Map + inline governed capture + provenance line). Does **NOT** render the orientation grid or any re-entry overlay; those are gated to `state in ('orienting', 'shell_active')`. | `leave_point.status: absent` (and no warm/dormant signals) |
| `orienting` | Returning with a recoverable trajectory; re-entry surface shown. | `leave_point.status: present` (or `stale`/`artifact_missing`/`degraded` with the stale cross-flag, see below) |
| `shell_active` | Document anchor open; overlay layer available. | user resume / open action |

`orienting` carries a **re-entry shape** sub-attribute derived from the gap, per the latency ladder in `CONTINUITY_AND_DECAY.md`:

| Shape | Gap | Treatment (see §Resolved Q5) |
|---|---|---|
| `no_mist` | < 90s | active state; no overlay |
| `thread_fade` | 90s – 15m | conversation/rail pane fades a fraction; no card; trajectory implicit |
| `soft_mist` | 15m – 2h | residual ambient cues only; no re-entry card |
| `full_mist` | 2h – 3d | the four fixed re-entry questions; canonical re-entry |
| `long_mist` | 3d – 14d | full mist + delta strip + whisper column |
| (cold) | > 14d | **not an `orienting` shape** — resolves to `cold_start`; no re-entry overlay |

Two **cross-flags** may decorate `orienting` and `shell_active` without being separate states:

- `degraded` — HTTP 200 partial snapshot; one or more `meta.degraded_reasons` present. Render an amber banner naming the missing source; the rest of the surface stays calm. Never alarm or substitute a local default.
- `stale` — `leave_point.status: stale | artifact_missing | degraded`. The re-entry surface still renders; the resume affordance is qualified per §Resolved Q9.

### Allowed transitions

```
boot ──▶ no_vault            (503)
boot ──▶ cold_start          (leave_point absent)
boot ──▶ orienting           (leave_point present)        [+degraded] [+stale]
no_vault ──▶ boot            (entry.retry)
cold_start ──▶ shell_active  (vault.open / vault.pick / recents.open / map→surface)
orienting ──▶ shell_active   (entry.resume | entry.dismiss | vault.pick)
```

Within `shell_active`, surface overlays open and close without leaving the state:

```
shell_active ⇄ rail(open|closed)            (chat rail slot — canvas lane)
shell_active ⇄ overlay(cmd|vault|memory|peek|posture|map|settings|capture|receipts|tts|help)
shell_active: suggestion(staged ──▶ applied | discarded)   (body-edit lane)
shell_active: panel(proposal ──▶ confirming ──▶ executing ──▶ receipt)   (governed)
shell_active: panel(proposal ──▶ blocked)                  (WriteGuard deny, guard-held)
```

Implementations must **reject any transition not enumerated here**. Entry-state resolution is server-side: the server renders the page with the resolved state declared; the UI never re-derives entry state from payload contents it was not declared.

### Overlay-grammar rule (NORMATIVE)

Every overlay dismisses back to the **document anchor** with **no route reset**. Overlays augment the current document context; they never replace it; dismissal must not lose data, erase unresolved cognitive tension (staged suggestions and open-loop counts survive), or reset navigation (`OVERLAY_GRAMMAR.md §Structural rules`, `§Continuity rules`). There are no separate apps and no full-screen context replacement.

## Data-attribute vocabulary (NORMATIVE)

Attributes follow the shipped renderer conventions (`data-testid` for test hooks, `data-region` for structural regions). The package's prototype attributes are normalized as follows. Adding new attributes is permitted; renaming a normalized attribute is a change to this spec.

| Normalized attribute | On | Purpose | Prototype attribute (renamed from) |
|---|---|---|---|
| `data-entry-state="boot\|no_vault\|cold_start\|orienting\|shell_active"` | shell root | The resolved entry-point state. Server-declared. | (new; prototype used `data-screen-label`) |
| `data-reentry-shape="no_mist\|thread_fade\|soft_mist\|full_mist\|long_mist"` | shell root, when `orienting` | Re-entry shape per the latency ladder. | (implicit in prototype scenarios) |
| `data-degraded="true"` | shell root | Degraded cross-flag (partial snapshot). | (prototype `degraded` toggle) |
| `data-stale="true"` | shell root | Stale cross-flag (leave-point not current). | (prototype scenario) |
| `data-region="reentry-card"` | re-entry card | The orientation re-entry surface. | same |
| `data-region="delta-strip"` | long-mist delta list | "What changed" strip. | same |
| `data-traj-state="warm\|dormant"` | re-entry card | Server-declared trajectory state; never UI-derived. | same |
| `data-region="document-anchor"` | topbar anchor pill | Current anchor identity. | same |
| `data-region="document-column"` | note column | Primary cognitive anchor surface (existing `data-region="note-body"` region remains). | same |
| `data-region="chat-rail"` | rail slot | Chat (canvas) surface slot; occupant owned by the canvas-chat lane. | same |
| `data-region="suggestion-block"` + `data-suggestion-id` | staged block | Canvas suggestion-flow body-edit object. | same |
| `data-proposal-id` | Panel proposal row (rail and palette) | Stable proposal id; never inferred from position. | `data-prop` |
| `data-rail="open\|closed"` | shell body | Rail visibility; survives re-anchor per §Resolved Q8. | same |
| `data-guidance="on"` (absent = off) | shell root | Opt-in explanatory guidance layer; off is the established-user default. | same |
| `data-region="capture-input"` | capture textarea | Friction-free capture field. | same |
| `data-region="cold-start-threshold"` | `cold_start` container | Non-overlay structural region for the intent-declaration threshold. NOT registered with `overlay_host`; carries no continuity claim; suppressed under reduced-content/print. | (new; #2171) |
| `data-region="cold-start-verbs"` | `cold_start` verb-line | Non-overlay structural region for the inline Find/Jot/Map verb sentence. NOT registered with `overlay_host`; carries no continuity claim. | (new; #2171) |
| `data-cognitive-mode` | shell root | Server-declared cognitive mode, rendered as supplied (§Resolved Q6). | (disambiguated) |
| `data-posture-emphasis` | shell root | Local posture emphasis (Local UI) (§Resolved Q6). | (disambiguated) |
| `data-intent="…"` | any actionable | The intent vocabulary below. | same |

Display preferences keep the shipped `data-testid="display-pref-*"` conventions (#1675); the prototype's `data-textsize` root attribute is **not** adopted — text-size rendering stays inside the shipped display-preference mechanism.

## Intent vocabulary (NORMATIVE)

Each `data-intent` declares its surface, effect, and whether it routes through the governed pipeline. This table governs the **entry/shell-composition vocabulary** — the intents the entry point and the surfaces this spec introduces emit. Shipped per-surface intents owned by their own contracts (for example `find.panelHandoff`, `resurface.dismiss`, `governance.queue`, `blocked.acknowledge` in the shipped workspace) remain governed by those owner contracts and are unaffected by this table. Implementations must not emit **new entry/shell-composition intents** not declared here; adding one requires amending this spec. Per-surface vocabularies evolve under their own owner contracts.

| Intent | Surface | Effect | Routes through pipeline? |
|---|---|---|---|
| `entry.retry` | no_vault | re-request orientation (read-only) | no |
| `entry.resume` | orienting | → `shell_active` at the leave point | no (navigation) |
| `entry.dismiss` | orienting | → `shell_active`, fresh | no |
| `vault.open` | shell / entry | open/focus the Vault Browser pane (narrow: modal) | no |
| `vault.pick` | Vault Browser | re-anchor shell to a note via `GET /api/companion/workspace?note_path` (§Resolved Q8) | no (read) |
| `recents.open` | cold_start | re-anchor shell to the server-declared `recents_anchor` via `GET /api/companion/workspace?note_path` (§Q1) | no (read) |
| `vault.queue` | Vault Browser | `queue_review` via `POST /api/companion/vault-browser/actions/queue-review` | **yes — governed handoff** |
| `cmd.open` | shell (`⌘K`) | open Panel command palette | no |
| `panel.confirm` | Panel (rail or palette) | confirm a governed proposal via `POST /api/panel/confirm` | **yes — governed; receipt** |
| `panel.blocked` | Panel | attempt a guard-denied action | **yes — WriteGuard deny; guard-held blocked state** |
| `suggestion.apply` | document | body edit via `canvas_writer.apply_edit` | body-edit lane — **no governance receipt** |
| `suggestion.discard` | document | drop staged proposal (UI-local) | no |
| `source.peek` | document / rail | open provenance popover (read-only) | no |
| `memory.open` | shell / re-entry inspect | open memory candidate review drawer | no (read + intent) |
| `memory.accept` | memory review | promote candidate | **yes — governed decision (ADR-0009 boundary); receipt** |
| `memory.reject` | memory review | reject candidate with accountable review semantics — a durable review outcome, never a promotion | **yes — governed review boundary (ADR-0009); receipt** |
| `memory.revise` | memory review | send candidate back for revision (review outcome per `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`) | **yes — governed review boundary; receipt** |
| `memory.defer` | memory review | non-terminal queue bookkeeping; candidate stays pending; no semantic transition | no (no receipt — nothing durable decided) |
| `posture.open` / `posture.set` | shell | shift local posture emphasis (carry-forward preserved) | no |
| `map.open` | shell / entry | open system map overlay | no |
| `rail.open` / `rail.close` | shell | toggle chat rail slot | no |
| `overlay.dismiss` | any overlay | return to document anchor | no |
| `guidance.toggle` | shell / entry / overlay head | toggle the guidance layer (UI-local; default off) | no |
| `settings.open` | shell / map | open Settings drawer (Local UI) | no |
| `settings.set` | Settings | set a display/listening preference (byte-unchanged) | no |
| `settings.reset` | Settings | reset display preferences to canonical | no |
| `tts.read` | document / map | open the read-back SpeechPlan (`POST /api/companion/tts/plan`) | no (read; only after human action) |
| `tts.play` | read-back popover | synthesize + play (`POST /api/companion/tts/synthesize`) | no (read-only; never a mutation endpoint) |
| `capture.open` | shell (`⌘N`) / entry / map | open Capture modal | no |
| `capture.save` | Capture | append the capture to the vault inbox | **yes — governed write (§Resolved Q17)** |
| `receipts.open` | shell / map | open the read-only receipts/history surface | no |
| `operator.open` | map | open the Operator diagnostics drawer (the operator layer; runtime/diagnostic telemetry lives here, off the front edge — CUIDR-04 #2447) | no (read-only diagnostics; never a mutation endpoint) |

Reserved, **not implementable** until Q15–Q16 resolve (see §Parked): `context.open`, `location.enable`.

Chat-rail composer intents (`rail.send` in the prototype) are owned by the canvas-chat lane (`docs/CANVAS_CHAT_SURFACE/README.md`), not this spec.

### Keyboard map

`⌘K` opens the Panel command palette (`cmd.open`). `⌘N` opens Capture (`capture.open`). `Esc` dismisses the topmost overlay back to the anchor (`overlay.dismiss`). A fuller keyboard model is deferred to implementation (package Q14). The map substrate is shipped with the overlay host (#1785); `⌘K` mounts the shipped Panel command palette (#1786); `⌘N` mounts the shipped capture modal (#1791).

## Surface composition (NORMATIVE table)

The unified shell is the shipped adaptive workspace plus the overlay host. Each surface keeps its owner contract; this table declares only the composition.

| Surface | Authority class | Reached as | Returns | Status | Governing owner doc |
|---|---|---|---|---|---|
| Orientation re-entry | Projection (read-only; emits intents, never applies) | the entry substrate (`orienting`) | becomes the shell on resume | shipped (re-entry surface; state-machine wrapper #1783; mist-shape treatments #1784) | `WORKSPACE_ORIENTATION_CONTRACT.md` |
| Document anchor (active note) | Canonical (note body) over Projection (chrome) | the shell's primary column | — (it *is* the anchor) | shipped | `WORKSPACE_STATE_CONTRACT.md`, `VAULT_MARKDOWN_RENDERER_CONTRACT.md` |
| Vault Browser | Projection (read-only); `queue_review` is the one governed handoff | left pane; modal in narrow mode (maps the design's "left drawer") | re-anchors the shell (§Resolved Q8) | shipped | `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`, `VAULT_BROWSER_UI_REQUIREMENTS.md` |
| Panel rail | Proposal → Confirmation → Receipt (governed) | right rail (shipped agent rail) | stays on anchor | shipped | `PANEL_COMPANION_UI_CONTRACT.md` |
| ⌘K Panel command palette | same authority as Panel rail — a **presentation**, not new authority | command overlay (`cmd.open`) | dismisses to anchor | shipped (#1786, SEP-04) | `PANEL_COMPANION_UI_CONTRACT.md` + this spec |
| Chat rail slot | canvas (proposes; cannot commit to vault) | margin rail slot (bottom sheet when narrow) | dismisses to anchor | slot defined here; occupant owned by the canvas-chat lane (#1716+); canvas co-authoring shipped | `docs/CANVAS_CHAT_SURFACE/README.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md` |
| Canvas suggestion blocks | Proposal → body-edit lane (no receipt) | staged block inside the document | stays on anchor | shipped | `CANVAS_SUGGESTION_FLOW.md` |
| Memory candidate review drawer | Proposal (candidate); accept/reject/revise are governed, receipt-bearing review outcomes (§Design-vs-owner-doc correction) | right drawer overlay (`memory.open`: topbar icon + re-entry unresolved-inspect) | dismisses to anchor | shipped (seam: count + intents; endpoints #1792; drawer UI #1793) | ADR-0009, `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` |
| Source peek | Projection (read-only provenance) | anchored popover (`source.peek`) | dismisses to anchor | shipped (provenance lines); popover presentation normalized here | `TEMPORAL_PROVENANCE.md`, `OVERLAY_GRAMMAR.md` |
| Posture emphasis switch | Local UI (never overrides server-declared cognitive mode) | centered overlay (`posture.open`) | anchor preserved with carry-forward set | **new** | `POSTURE_TRANSITIONS.md` + §Resolved Q6 |
| System map overlay | Projection (index; renderer/router only) | topbar + cold-start affordance (`map.open`) | dismisses to anchor; nodes route to surfaces | **shipped** (#1787, SEP-05); `system_map_overlay.py`, `tests/companion_ui/test_system_map_overlay.py` | this spec §Resolved Q4 |
| Settings drawer | Local UI | right drawer overlay (`settings.open`: topbar icon) | dismisses to anchor | shipped (#1675 display prefs; drawer consolidation + listening prefs #1789, SEP-07) | `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` + §Resolved Q19 |
| TTS read-back | Local read-only (plan inspected before audio) | per-surface `Listen` control → plan popover | stays on anchor | shipped | `LOCAL_FIRST_TTS_CONTRACT.md` |
| Capture | Proposal → governed write | top modal (`⌘N`) | dismisses to anchor | **shipped** (#1791, SEP-08b); endpoint `POST /api/companion/capture` (#1790) | this spec §Resolved Q17 (invariants); `capture_modal.py`, `tests/companion_ui/test_capture_modal.py` |
| Receipts / history | Receipt (read-only; never invented by the UI) | top modal (`receipts.open`) | dismisses to anchor | **shipped** (#1794, SEP-10) over the shipped receipts projection; `receipts_history.py`, `tests/companion_ui/test_receipts_history_surface.py` | `PANEL_COMPANION_UI_CONTRACT.md`, `COMPANION_UI_STATE_MAP.md` |
| Guidance layer | Local UI (persists nothing; carries no authority) | `ⓘ` toggle on topbar, overlay heads, re-entry card | cross-cutting | **shipped** (#1788, SEP-06); integrates with the shipped `/help` guide (#1755); `guidance_layer.py`, `tests/companion_ui/test_guidance_layer.py` | this spec; help guide |
| Context lane (time) / place band | — | — | — | **parked** (Q15–Q16) | §Parked |

## Resolved questions

Each resolution below settles a `resolve-in-normalized-spec` question from the package's `open-questions.md`. The owner doc cited wins over any conflicting package prose.

### Q4 — System map placement
The system map is an **always-available overlay**, reachable from the topbar in every state and offered as a calm affordance in `cold_start` and `no_vault`. It is **pull-based and never shown unbidden** — no first-run auto-display, no periodic surfacing. It is a renderer/router index (Projection): each node shows the surface's mode (`docs/COMPANION_UI_PRODUCT_SPEC.md` Find/Reorient/Resurface/Act), how it is reached, and how it returns; clicking routes to the surface. It re-classifies nothing.

### Q5 — Re-entry shapes and display budget
Re-entry shapes follow the `CONTINUITY_AND_DECAY.md` latency ladder exactly (table above), including the **thread-fade interval (90s–15m)**: the conversation/rail pane fades a fraction, no card is shown, and the trajectory stays implicit. Within any orienting moment the UI shows a **scarce displayed subset — counts, not enumerations** ("3 open loops · 1 staged", with a deliberate inspect/expand affordance), per `ATTENTION_MODEL.md` and the orientation contract's cognitive-load display budget.

- **Default `items_per_orientation_moment` = 3 visible items per collection** (`open_loops`, `notable_changes`, `resurface.candidates`), matching the shipped resurfacing-card default (#1680). Deliberate expansion may reveal more, **never above the server caps** (8/8/5 per `WORKSPACE_ORIENTATION_CONTRACT.md §Bounded Collections`); the UI must not widen collections or enforce larger local caps.
- **Soft mist (15m–2h) is minimal: residual ambient cues only — no re-entry card.** The latency ladder's one-line "where you stopped" sentence is normalized to a **peripheral one-line cue** (caret echo at the stop point plus the single sentence at the margin), consistent with the ladder's "no metadata" rule and the invariant that **no card ever centers on the document**. No four-questions card, no delta strip, no whisper column at this gap.
- Cold (>14d) and first contact show **no re-entry overlay** of any kind — a continuity claim the system cannot back is forbidden.

### Q6 — Two concepts that shared the name "posture"
This spec names them distinctly and they must not be conflated:

1. **Server-declared cognitive mode** (`data-cognitive-mode`): declared by the runtime, rendered as supplied, never overridden or re-derived by the UI (`COGNITIVE_MODES.md`; "server declares; UI renders").
2. **Local posture emphasis** (`data-posture-emphasis`): a Local UI emphasis control over the five canonical postures (Orientation / Exploration / Synthesis / Review / Recovery). Switching it preserves the carry-forward set — anchor document, provenance context, unresolved tension — per `POSTURE_TRANSITIONS.md §Minimal transition contract`. It persists nothing durable and carries no authority. The shell opens in **Recovery** emphasis after a re-entry.

### Q7 — Token source
`colors_and_type.css` (the Yggdrasil token sheet, as inlined by the shipped renderer) is the **binding token source**. The design-guide prose (warm/parchment/gold palette) is aspirational language only; where prose and the CSS disagree, the CSS wins. Normalizing the off-palette Panel staging shell onto these tokens is mechanical implementation work (package Q13, deferred to an implementation issue).

### Q8 — Re-anchoring scope on `vault.pick`
Opening a note from the Vault Browser re-anchors via **`GET /api/companion/workspace?note_path=…` only**; orientation is **not** re-issued (`WORKSPACE_STATE_CONTRACT.md` owns the artifact-scoped aggregate; orientation is the no-artifact substrate). Across the re-anchor, per `OVERLAY_GRAMMAR.md` continuity rules: the rail open/closed state survives, and staged suggestions survive **bound to their source note** — a suggestion staged on note A remains associated with A and does not transfer to or render inside note B's body. Dismissal/re-anchor must not erase the staged object.

### Q9 — Stale leave point
When `leave_point.status` is `stale`, `artifact_missing`, or `degraded`, the re-entry card still renders, with a **qualified resume affordance presented as a guard-held state, not an error**, per `BLOCKED_AND_STALE_STATE_SPEC.md`: the state names the cause ("source changed since this was captured" / "artifact is missing"), states that nothing was mutated, and offers a path forward (open the current artifact state, or re-enter through the Vault Browser when the artifact is missing). The UI never silently resumes into a moved or missing artifact and never renders this as a generic error toast.

### Q17 — Capture
Capture is a **governed append to the vault inbox**: policy → validation → deterministic writer. Normative invariants (the exact endpoint is an implementation-issue decision):

- A capture is vault intake — a commitment to future-self — **never an app-owned task**: no due dates, no app-managed task states, no nagging, no reminders. Captured material resurfaces later only by relevance, like any vault material.
- Capture must **never be silently dropped offline**: when the runtime is unreachable the composer stays usable and the UI states plainly that the capture is **not yet written**; it never claims a write it cannot back.
- Capture writes route through the governed pipeline only; no direct vault I/O from the UI.

### Q18 — Quiet hours
Quiet hours (a Settings control) **dampen ambient salience presentation only** — reduced intensity of ambient cues during the configured window. Quiet hours can never become a notification scheduler: there are no notifications to schedule, suppress, or batch (`WORKSPACE_ORIENTATION_CONTRACT.md` forbids notification/urgency transport; resurfacing is salience, not urgency).

### Q19 — Settings storage home
Settings preferences are Local UI state stored in the **`WORKSPACE_STATE_CONTRACT.md` local-state home** as pinned by `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` — never vault Markdown/frontmatter, never a save/projection endpoint. The canonical Markdown hash is **byte-unchanged** across any preference change; a **`local-only render` badge** appears whenever a preference diverges from the canonical render; **reset-to-canonical is always available**. Per-surface overrides may layer on global defaults.

### Q15 / Q16 — Context lane and place band: parked
The context lane (time) and the place band are **out-of-scope placeholders**. No owner doc grounds a calendar or location source, and the package marks them resolve-before-promotion *for those surfaces only*. They are **explicitly parked**: this spec defines nothing about them beyond this parking note, and the reserved intents (`context.open`, `location.enable`) must not be implemented. A gated backlog issue (`agent:needs-human`) will track the open decisions; see `docs/SYSTEM_ENTRY_POINT/README.md §Parked`.

### Design-vs-owner-doc correction — memory review outcomes
The package's implementation contract proposed `memory.defer` / `memory.reject` as UI-local review-queue actions. The owner docs win: `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md` requires **promote, reject, and revise as separate review outcomes**, and ADR-0009 requires a receipt for "rejecting memory with accountable review semantics". This spec therefore treats `memory.reject` and `memory.revise` as durable, receipt-bearing review decisions through the governed review boundary; only `memory.defer` (non-terminal "decide later" bookkeeping, no semantic transition) stays receipt-free. Raised by Codex review on PR #1776; resolved in the owner docs' favor.

### Q1 — Recents-anchor (server-declared Find/recency projection)

Operator decision: adopt (Q1 in `companion-ui/design_handoff/2026-06-19-cold-start-threshold/open-questions.md`). Governing issue: #2176.

The runtime MAY emit a `recents_anchor` field on the `cold_start` orientation payload — a server-declared **Find/recency projection** identifying the most recently edited vault note at snapshot time. It is explicitly **NOT** a `leave_point` and carries **NO** continuity semantics. Full field definition and render rules are owned by `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md §recents_anchor`.

Summary of render rules (normative detail in the owner doc):

- The UI renders `recents_anchor` as a labeled "Open your most recent note" sub-affordance on the `cold_start` threshold's Find verb, routing via the existing `/workspace?note_path=…` path.
- The UI must **never** auto-open this path on mount; it is an affordance only.
- The UI must **omit the sub-affordance entirely** when the field is absent.
- The UI must **not** derive this field locally via a filesystem `mtime` probe — that would violate the "no direct vault I/O from the UI" invariant (ADR-0014, #2141).

### Deferred to implementation issues (unchanged from the package)
Q10 (ambient foreground refresh opt-in, gated on `COMPANION_ORIENTATION_AMBIENT_REFRESH` per ADR-0011), Q11 (bottom-sheet snap points), Q12 (command-palette input grammar), Q13 (off-palette Panel staging-shell migration), Q14 (fuller keyboard map), Q20 (read-back eligibility scope).

## Validation expectations

The validating implementation is **shipped** (#1795, SEP-11): `tests/companion_ui/test_entry_state_gallery.py` renders the package's state gallery against fixture orientation snapshots and asserts every item below across the fixture matrix (entry states A1–A7 including the degraded/stale cross-flags, shell states for every shipped occupant, responsive C1, guidance E, and the shipped settings/read-back/capture/receipts F-states). A validating implementation verifies:

- every declared entry-point transition, and rejection of undeclared transitions;
- no UI-derived posture / class / authority anywhere — all classification server-declared;
- `cold_start` (first contact and >14d) and `no_vault` show **no** re-entry overlay;
- governed intents (`vault.queue`, `panel.confirm`, `memory.accept`, `memory.reject`, `memory.revise`, `capture.save`) route through the pipeline and surface receipts; body edits (`suggestion.apply`) and non-terminal `memory.defer` produce **no** governance receipt — the governed-vs-body-edit receipt asymmetry is asserted, not assumed;
- blocked and stale present as guard-held states per `BLOCKED_AND_STALE_STATE_SPEC.md`, never generic errors;
- the display budget caps visible items at or below the server caps, with the default scarce subset of §Resolved Q5;
- `prefers-reduced-motion` is respected and every end-state is fully visible without animation;
- narrow/portrait preserves every critical affordance (rail → bottom sheet; whisper column suppressed).

The fixture set itself is owned by the validation harness (`docs/SYSTEM_ENTRY_POINT/STATE_GALLERY_VALIDATION.md` → `tests/companion_ui/test_entry_state_gallery.py`), not this document.

Shipped-vs-new audit at capability closure (#1795): every surface in §Surface composition carries its delivering issue number; the only rows still **new** are the source-peek popover presentation and the posture emphasis switch (truthfully undelivered — declared overlay ids that do not mount), and the context lane / place band stay **parked** under the gated decision issue #1796.

## Authority boundaries

- This spec is the **normalized-spec authority for entry/shell composition** only. It declares no runtime schema, no new endpoints, and no authority surface.
- **Server declares; the UI renders.** Entry state, trajectory state, cognitive mode, authority class, governance counts, receipt outcomes, and degraded posture are rendered as supplied. The UI never re-classifies.
- **Gated execution is preserved.** Durable mutations route only through the governed pipeline (policy → validation → event pipeline → deterministic writer). The body-edit lane (`canvas_writer`) remains the deliberate exception defined by `CANVAS_SUGGESTION_FLOW.md` and produces no governance receipt.
- **Chat ≠ Panel.** Chat is a canvas surface; Panel is the command surface; Automation is its own lane. The ⌘K palette is a Panel presentation and must stay visually and behaviorally distinct from chat. This spec does **not** define a second chat implementation: it defines the rail **slot** so the canvas-chat lane (`docs/CANVAS_CHAT_SURFACE/README.md`) can occupy it.
- **Receipts are never invented by the UI.** The receipts surface is read-only projection of runtime-produced receipts.
- The owner doc always wins. Any passage here that appears to contradict a per-surface owner contract is in error and must be corrected here.

## Related docs

- Design source: `companion-ui/design_handoff/2026-06-09-system-entry-point/` (guidance only)
- Chain governance: `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- Term mapping: `companion-ui/docs/CORE_TERM_MAPPING.md`
- Feature breakdown: `docs/SYSTEM_ENTRY_POINT/README.md`
- Per-surface owner contracts: as named in the composition table above
