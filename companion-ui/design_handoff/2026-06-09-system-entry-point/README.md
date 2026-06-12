# Companion UI — System Entry Point

**Date:** 2026-06-09
**Status:** Design handoff · v1 · ready for review at Crossing B
**Authority:** **Visual / interaction guidance only.** Not architecture authority; not runtime truth.
**Crossing target:** B (handoff → normalized spec)
**Owner-docs this serves (external; referenced, not modified):**
`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`,
`companion-ui/docs/COMPANION_UI_STATE_MAP.md`,
`companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md`,
`companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`,
`companion-ui/docs/OVERLAY_GRAMMAR.md`,
`companion-ui/docs/POSTURE_TRANSITIONS.md`,
`companion-ui/docs/CONTINUITY_AND_DECAY.md`,
`companion-ui/docs/ATTENTION_MODEL.md`,
`companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`,
`companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`,
`docs/COMPANION_UI_PRODUCT_SPEC.md` (mode model, referenced by name only — not read in this package).

## What this is

The **front door**. Today the companion's design knowledge is spread across ~50 docs and a dozen handoff packages; there is no single place a newcomer can enter to understand the whole. This package defines, end to end, **how the companion is set up and entered** — and ties every existing fragmented surface into one coherent system.

It covers three things:

1. **Setup / first contact** — how a person enters the companion on first use and on every return: the runtime handshake, the cold-start states, and how a returning user is oriented back into their last *cognitive trajectory* rather than dropped onto a blank dashboard. This is the read-only re-entry substrate described by `WORKSPACE_ORIENTATION_CONTRACT.md` (`GET /api/companion/orientation`), composed through the latency ladder in `CONTINUITY_AND_DECAY.md`.

2. **The unified shell** — the one workspace frame everything else hangs from: the **document anchor** (primary), the **overlay layer**, **Chat** (margin rail / bottom sheet), the **Panel command surface**, and how attention, continuity, and temporal overlays compose into a single coherent screen instead of separate apps.

3. **The system map** — an index that absorbs the existing surfaces and shows how each one is reached from, and returns to, the entry point. This is the *total system entry point*: one place from which the whole companion is legible.

## Surfaces this package covers (the system-map nodes)

Every surface below is named in the prototype's system map, each tagged with its product mode (`docs/COMPANION_UI_PRODUCT_SPEC.md`: Find / Reorient / Resurface / Act) and its authority posture (`COMPANION_UI_STATE_MAP.md`). This package **unifies** these surfaces; it does not replace them.

| Surface | Mode | Reached from entry point as | Returns to | Source package / contract |
|---|---|---|---|---|
| Workspace orientation / re-entry | Reorient | the cold-load substrate itself | becomes the shell on resume | `WORKSPACE_ORIENTATION_CONTRACT.md` |
| Active note workspace (document anchor) | Find / Reorient / Act | the shell's primary column | — (it *is* the anchor) | `WORKSPACE_STATE_CONTRACT.md` |
| Converse / Chat | canvas | margin rail (bottom sheet when narrow) | document anchor | `2026-05-03-converse`, `converse_layout.html` |
| Canvas suggestion flow | Act · body-edit | staged block inside the document | stays on anchor | `2026-05-11-canvas-suggestion-flow`, `CANVAS_SUGGESTION_FLOW.md` |
| Panel / command surface | Act · governed | command palette overlay | document anchor | `2026-05-15-panel-interaction`, `PANEL_COMPANION_UI_CONTRACT.md` |
| Vault Browser | Find | left drawer overlay | document anchor (may re-anchor) | `2026-05-24-vault-browser-foundation` |
| Memory candidate review | Reorient seam | right drawer overlay | document anchor | `2026-05-14-memory-candidate-review`, ADR-0009 |
| Resurface | Resurface | in re-entry card + rail | source / anchor | `RESURFACING_HEURISTICS.md` |
| Temporal / provenance overlays | Reorient | re-entry mist, decay marginalia, source peek | ambient on anchor | `2026-05-08-cognitive-temporal`, `CONTINUITY_AND_DECAY.md` |
| Cognitive postures | all | emphasis switch overlay | anchor preserved | `POSTURE_TRANSITIONS.md` |
| Settings | Local UI | right drawer overlay | document anchor | `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`, `LOCAL_ACCESS_MODEL.md` |
| Read-back (local TTS) | Listening | per-surface plan popover | stays on anchor | `LOCAL_FIRST_TTS_CONTRACT.md` |
| Context lane (time + place) | Reorient | right drawer overlay | document anchor | **proposal/placeholder** — no calendar/location owner-doc yet |
| Capture | Capture | top modal (`⌘N`) | document anchor | `DESIGN_BRIEF.md` (Capture surface) |
| Receipts / history | Act / Reorient | top modal | document anchor | receipts are runtime-produced (`PANEL_COMPANION_UI_CONTRACT.md`) |

Staging prototypes accounted for: `companion-app/converse_layout.html`, `companion-app/canvas_suggestion_flow.html`, `companion-app/panel_visual_shell.html`. The entry point normalizes them onto the canonical `colors_and_type.css` tokens (the panel staging shell currently uses an off-palette ad-hoc theme; see `design-notes.md §Conflicts`).

## How to walk the prototype

Open `prototype.html`. It boots through the runtime handshake, then lands on whichever entry state the **prototype control deck** (bottom, clearly labelled scaffolding) selects:

1. **Cold start** → `First contact` or `Cold · 21d`: a calm, minimal way in. No manufactured activity, no re-entry overlay for cold trajectories.
2. **Setup / orientation** → `Returning · 2h` (full mist) and `Returning · 5d` (long mist + delta strip + whisper column): the four fixed re-entry questions, felt at the periphery.
3. **Shell with a live document** → press **Resume**. The document becomes the anchor; the residual ambient layer persists.
4. **Reaching each subordinate surface** → topbar icons and in-document affordances open Chat, the Panel command surface (`⌘K`), the Vault Browser, the memory review, source peek, posture switch, **Settings**, the **Context lane** (time + place), **Capture** (`⌘N`), read-back (the `Listen` control), and the **System map**.
5. **Returning** → every overlay dismisses back to the document anchor with no route reset.

Toggle `degraded` (partial orientation source) and `narrow` (portrait device) to see those cross-states. The `ⓘ` guidance toggle (off by default for the established user) reveals the explanatory help layer.

## Files

- `prototype.html` — self-contained interactive prototype: entry-point state machine + unified shell + all subordinate surfaces as overlays + system map. No network, no durable mutation; backend effects are `console.log` only.
- `design-notes.md` — system rationale: why the entry point is shaped this way and how it composes the existing surfaces into one whole.
- `state-gallery.md` — every state of the entry point and shell.
- `implementation-contracts.md` — state enum, allowed transitions, `data-*` attributes, and intents, framed as proposals.
- `authority-boundaries.md` — what this design is / is not.
- `open-questions.md` — each question triaged; no Crossing-B blocker left open.
- `edge-states.md` — degraded / empty / loading / blocked / narrow detail.
- `colors_and_type.css` — Yggdrasil token sheet, copied unchanged from the repo root.

## Authority & disclaimers

- **This design is visual/interaction guidance.** Architecture authority lives in `docs/**` owner-docs.
- **The owner-doc always wins.** Any passage here that appears to conflict with an owner-doc is a *proposal*, not a correction.
- **Runtime truth lives downstream** in shipped code, tests, `docs/STATUS.md`, and validation receipts — not asserted here.
- **Server declares; the UI renders.** This design introduces no surface that re-classifies runtime state.
- **The gated-execution invariant is honored throughout.** No surface mutates durable state outside the governed pipeline (policy → validation → event pipeline → deterministic writer).
- **Authority separation is preserved.** Chat is a canvas surface; Panel is the command surface; Automation is its own lane. They are never collapsed.
- This package does not assert current shipped behavior except where it cites an in-folder owner-doc by name. The architecture owner-docs under the repo's top-level `docs/**` are treated as authoritative-but-external; this package references them by name only.
