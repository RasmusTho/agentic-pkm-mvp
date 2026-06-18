# Companion UI — Cold-start entry threshold

**Date:** 2026-06-19
**Status:** Design handoff · v1 · ready for review at Crossing B
**Authority:** **Visual / interaction guidance only.** Not architecture authority; not runtime truth.
**Crossing target:** B (handoff → normalized-spec amendment)
**Amends (not replaces):** `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — the `cold_start` / `no_vault` surface only. The five-state machine, the re-entry shape ladder, the cross-flag rules, the transition set, and the data-attribute vocabulary are **unchanged**.
**Owner-docs this serves (external; referenced, not modified):**
`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`,
`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`,
`companion-ui/docs/COGNITIVE_PRINCIPLES.md` ("No AI-dashboard posture"),
`companion-ui/docs/CONTINUITY_AND_DECAY.md`,
`companion-ui/docs/ATTENTION_MODEL.md`,
`companion-ui/docs/OVERLAY_GRAMMAR.md`,
`docs/COMPANION_UI_PRODUCT_SPEC.md` (Find / Reorient / Resurface / Act mode model, referenced by name only).

## Why this exists

A live operator session (2026-06-18) found the entry surface rendering, on a true first contact, a **"Re-entry snapshot"** heading over a telemetry meta row and a two-column grid of zero-filled collections (leave-point, governance counts, open loops, notable changes, resurface). That is "a home screen of cards, counts, and feeds filled with manufactured activity" — exactly what `SYSTEM_ENTRY_POINT_SPEC.md` declares **normatively forbidden** ("the entry point must never become a home screen of cards, counts, and feeds"; "the front door is a door into continuity of thought, **not a dashboard**").

Verified root cause: the body of `_render_orientation_index_html` (`companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:6377-6408`) assembles the header + telemetry meta row + orientation grid **unconditionally** — there is no branch on `entry_resolution.state`. The state machine already resolves `cold_start` correctly (`resolve_entry_state()` returns `cold_start` when `leave_point.status == "absent"`); the renderer simply ignores it. So this is a **divergence from the existing normative spec**, not a gap in the spec and not a styling problem.

## What this package proposes

Recompose the `cold_start` (and `no_vault`) surface into a calm **intent-declaration threshold** — a door *into* thinking, not a status report. Concretely, `cold_start` renders:

1. a quiet **vault chip** (status dot + `scope.vault_id`) — which of the operator's vaults this is;
2. an honest **headline** — "Nothing is open yet." (first contact) / "Re-entry is through the vault." (> 14 d cold) — with no mist, card, count, or tint;
3. a single inline **verb-line** rendered as a sentence (never a button/card grid): *Find a note · Jot something down · See the map*, mapping 1:1 onto the already-declared intents `vault.open` / `capture.open` / `map.open` (zero new intents);
4. an inline **governed capture field** ("Leave a note for future-you…") that mounts the shipped capture occupant — the one *generative* affordance on an empty door;
5. one mono **provenance line** — `leave_point: absent · read-only · server-declared`.

All telemetry (leave-point, governance counts, open loops, notable changes, resurface) **relocates behind the pull-only System map** (and the topbar runtime-status disclosure), rendered as read-only projection — never as live tiles.

Deliberately **no "Reorient" verb** on `cold_start`: there is no trajectory to reorient into, so offering it would be the forbidden false-continuity claim. The full re-entry mist ladder for `orienting` is **untouched**.

## Provenance

This package is the normalized output of a four-direction design round (document-as-door · quiet-threshold · resurface-invitation · intent-led-modes), each adversarially critiqued across four lenses (spec-compliance · cognitive-soundness · implementability · human-meaning). Quiet-threshold (8.5) and intent-led-modes (8.3) were the only two with zero lens-fails; the recommended design is quiet-threshold as the base with the intent-led verb-line and an honest recents-anchor grafted in. See `design-notes.md` for the full round, scores, and rejected directions.

## Files

- `design-notes.md` — the design round, scores, recommended design, grafts, and what-moves-to-map.
- `implementation-contracts.md` — the concrete `cold_start` / `no_vault` render contract: state-gating, regions, intents, the proposed `capture.open` surface widening, and the proposed recents-anchor contract field.
- `open-questions.md` — the three operator decisions (resolved) and the deferred items.
- `authority-boundaries.md` — design guidance vs normalized spec vs owner-doc vs runtime; the spec amendments are **proposals**, applied through reviewed PRs.
- `prototype.html` — a static render of the proposed `cold_start` threshold and `no_vault` surface.
