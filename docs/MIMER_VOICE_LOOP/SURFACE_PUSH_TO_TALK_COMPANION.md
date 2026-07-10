---
name: Surface Push-to-Talk Companion
description: Companion UI push-to-talk surface — hold-or-tap to talk, spoken answer playback, text + citations visible, zero typing
task_id: VOICE-03
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 5. Mimer voice loop
parent_capability: Mimer Voice Loop
prerequisites: [VOICE-01]
depends_on: [DEFINE_VOICE_ASK_CONTRACT.md]
can_parallelize_with: [Carry Session Followup Context]
---

# Surface Push-to-Talk Companion

## Purpose

Voice is the interface where the owner's dyslexia inverts into an advantage — but only if the surface itself demands **zero typing**. This task gives the companion UI a push-to-talk control that captures a spoken question, calls the voice-ask turn (VOICE-01), plays the spoken answer, and shows the text answer + citations, with no keyboard step anywhere in the path.

## What This Task Does

1. **Push-to-talk control** — a hold-to-talk (press-and-hold, release to send) with a tap-to-toggle fallback for accessibility, captured via the browser `MediaRecorder` API into one of the containers VOICE-01 accepts (e.g. `webm`/`ogg`). The control is a visual pick, not a text field — consistent with the dyslexia-friendly, no-manual-paths posture (record → release → answer; no path typing, no search box).
2. **Turn call + rendering** — POSTs the recorded audio to `POST /api/ask/voice` and renders the response: the **transcript** (so the user confirms what was heard), the **text answer**, the **citations** (each source's title, linkable to the note), and an **audio player** for `audio_url` that plays the spoken answer. Reuses the existing SpeechPlan renderer (`renderSpeechPlan(plan)` in the companion UI) rather than inventing a second playback path.
3. **Legible degrade in the UI** — the three VOICE-01 degrade states each get a visible treatment: `stt_unavailable` → "I couldn't hear that clearly — try again" with the record control re-armed; ASK error → show the transcript + "I couldn't answer that right now" (never a blank); `tts_unavailable`/`degraded` → show the full text answer + citations with a small "voice unavailable" marker and no dead player. No silent empty state, ever.
4. **Zero-typing guarantee** — the entire ask→answer→listen loop is reachable by voice + one hold gesture; typing is never required to ask, to hear, or to follow a citation.

## Concretely

Local UAT (companion UI renders to static HTML for preview per `reference_companion_ui_local_uat` practice; live audio needs a runtime):

```
# render the push-to-talk surface with a fixture voice-ask response
python -m companion_ui.workspace.serve_dev_page --fixture voice_ask_turn --out /tmp/ptt.html
# browser-preview: record control present, transcript+answer+citations+audio player render; no text input required
```

## Why This Matters

If the surface still needs a keyboard to ask, or shows a blank box when STT/TTS is down, the one interface built for the owner's strength quietly reverts to his weakness. The zero-typing guarantee and the legible degrade states are the whole point — this task is where "voice is where the disadvantage inverts" either holds or doesn't.

## Acceptance Criteria

- [ ] AC1: the push-to-talk control records audio and calls `POST /api/ask/voice` with no text-input step in the path. Verify: `tests/companion_ui/test_push_to_talk_surface.py::test_ask_loop_requires_no_typing`
- [ ] AC2: a successful turn renders transcript, text answer, citations (linkable), and an audio player bound to `audio_url`. Verify: `tests/companion_ui/test_push_to_talk_surface.py::test_push_to_talk_renders_answer_citations_and_audio`
- [ ] AC3: each degrade state renders its legible treatment and never a blank/dead surface — STT error re-arms the control; ASK error shows the transcript; TTS-degraded shows full text + citations + marker with no dead player. Verify: `tests/companion_ui/test_push_to_talk_surface.py::test_degrade_states_render_legibly`
- [ ] AC4 (out-of-scope guard): the surface offers no wake-word / always-on toggle — it is strictly hold-or-tap, single-turn. Verify: `tests/companion_ui/test_push_to_talk_surface.py::test_no_always_on_affordance` + local UAT receipt on the parent issue

## How to Verify (Pre-Merge)

```
ruff check app companion-ui tests && mypy app
pytest -q tests/companion_ui/test_push_to_talk_surface.py
pytest -q -m "not pg"
# local UAT: render fixture turn → browser preview → receipt on parent issue; live audible loop on the mac mini test channel
```

## Out of Scope — explicit owner-decision references

- **Wake word / always-on listening** — this is the **Heimdal capture-posture fork** (Posture A discrete-capture v1 vs Posture B always-on), an **open owner decision** (`docs/HEIMDAL/OWNER_DECISIONS.md`; Bifrost B3 #3026). This task **references it as out of scope and does not open it** — the surface is push-to-talk only; no always-on affordance is designed, prototyped, or toggled here.
- Mobile/Watch surfaces (Bifrost B3 #3026 consumes the VOICE-01 contract later); changing ASK or TTS behavior; the voice-ask endpoint (VOICE-01); in-session follow-up context (VOICE-04 — this UI displays turns; VOICE-04 owns the context that links them).

## Restart / Durability Posture

The surface is client-side and stateless across reloads: a page reload starts a fresh turn. It reflects — but does not own — the in-memory in-session context (VOICE-04); after a runtime restart the surface still works for a fresh question, but a follow-up may no longer resolve (see VOICE-04 and the capability README).

## Related Docs

- `companion-ui/companion_ui/workspace/serve_dev_page.py::renderSpeechPlan` (playback reuse); `reference_companion_ui_local_uat` (render-to-static UAT practice)
- VOICE-01 turn contract (`DEFINE_VOICE_ASK_CONTRACT.md`); `feedback_dyslexia_friendly_no_manual_paths` (visual-pick, zero-typing posture); `project_companion_ui_audit_2026` (companion UI surface conventions)
- `docs/HEIMDAL/OWNER_DECISIONS.md` + `docs/HEIMDAL/CAPABILITY_CHARTER.md` (capture-posture fork — referenced, not opened)

## Related GitHub Issues

One issue: `[Mimer Voice Loop] push-to-talk: companion UI hold-to-talk with spoken answer + citations, zero typing`. `agent:blocked` until VOICE-01 merges (consumes the turn contract; parallelizable with VOICE-04). TCD hint: **sonnet, medium reasoning** — a companion-UI surface following existing render/UAT patterns; the risk is degrade-state legibility and the zero-typing guarantee, both bounded.
