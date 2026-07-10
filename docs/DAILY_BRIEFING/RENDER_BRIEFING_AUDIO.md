---
name: Render Briefing Audio
description: Render the composed briefing to mixed sv/en per-segment audio via the existing SpeechPlan/TTS pipeline, one-tap listen, degrading to text-only when TTS is unavailable
task_id: BRIEF-03
source_anchor: companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md :: Provider Selection
parent_capability: Daily Briefing
prerequisites: [BRIEF-01]
depends_on: [COMPOSE_BRIEFING_ARTIFACT.md]
can_parallelize_with: [SCHEDULE_AND_TRIGGER_GENERATION, SURFACE_DAY_START_CARD]
---

# Render Briefing Audio

## Purpose

The owner is dyslexic and wants to *listen* to his day-start touchpoint, not read it. Mixed sv/en per-segment TTS already ships (`app/tts/planning.py::build_tts_plan`, per-sentence voice routing shipped in #2114, documented at `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md`) — this task wires the composed briefing note into that existing capability rather than building any new speech logic.

## What This Task Does

- Feeds the briefing note's normalized text through the existing `build_tts_plan` (`app/tts/planning.py`), which already: normalizes text, detects language per sentence segment, resolves each segment's own voice (`sv-SE` → Piper `sv_SE-lisa-medium`, `en-US`/`en-GB` → Kokoro `bf_isabella`), and returns a `SpeechPlan`-shaped plan with `segments[]`, `mixed_language`, `cache_key`, and provider-availability warnings. No new segmentation, voice-selection, or concatenation logic is added by this task — it is a consumer of the shipped capability.
- Adds a "listen" affordance to the briefing surface, backed by the existing `/api/companion/tts/plan` and `/api/companion/tts/synthesize` endpoints (`companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md`): one tap plans, synthesizes (or serves the cached artifact if already synthesized), and plays — no further user decision required.
- **Degrades to text-only** when TTS is unavailable: `TTS_ENABLED=false`, the resolved provider is unavailable (missing model/command), or `local_only` policy blocks a fallback. In every degraded case the full briefing text still renders; only the listen affordance itself becomes visibly disabled/absent, matching the existing Local-First TTS Contract's provider-unavailable posture (never a broken button, never a silent failure that looks like a working one).
- Respects the existing UI-boundary contract: no autoplay on render; audio plays only after the explicit tap.

## Concretely

```
POST /api/companion/tts/plan   {"text": "<briefing note body>"}
→ {"mixed_language": true, "segments": [
     {"language": "sv-SE", "voice_id": "sv_SE-lisa-medium", ...},
     {"language": "en-US", "voice_id": "bf_isabella", ...}
   ], "provider_available": true, ...}

# one tap:
POST /api/companion/tts/synthesize   {"cache_key": "..."}
→ {"audio_url": "/api/companion/tts/audio/<cache_key>.wav"}
→ playback starts
```

When TTS is disabled:

```
GET /api/companion/tts/status → {"environment": {"TTS_ENABLED": false}, ...}
→ day-start card renders full briefing text; listen button is disabled with a reason, no plan/synthesize call attempted
```

## Why This Matters

Audio is the entire reason this capability exists for this owner — a text-only briefing he still has to read defeats the "audio-first" requirement. But audio must never become a hard dependency: if TTS is down (model missing, engine not provisioned on the running host, `TTS_ENABLED=false` in dev), the briefing must still be fully useful as text, because the underlying information (commitments, relevance picks, decision receipts) is time-sensitive and cannot wait on TTS provisioning.

## Acceptance Criteria

- [ ] AC1: the briefing note's text produces a valid plan via the existing `build_tts_plan`, with mixed sv/en per-segment voice routing applied when the note mixes languages — no new segmentation logic introduced. Verify: `tests/briefing/test_briefing_audio.py::test_briefing_text_produces_valid_speech_plan`
- [ ] AC2: a single user tap triggers plan → synthesize → playback with no further user decision. Verify: `tests/companion_ui/test_briefing_listen_affordance.py::test_one_tap_listen_triggers_plan_and_synthesize`
- [ ] AC3: when TTS is disabled or the provider is unavailable, the day-start surface still presents the full briefing as text, with the listen affordance visibly disabled (not a broken/silently-failing button). Verify: `tests/companion_ui/test_briefing_listen_affordance.py::test_degrades_to_text_only_when_tts_unavailable`
- [ ] AC4: no autoplay — audio plays only following the explicit tap, matching the existing UI-boundary contract. Verify: `tests/companion_ui/test_briefing_listen_affordance.py::test_no_autoplay_on_render`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/briefing/test_briefing_audio.py tests/companion_ui/test_briefing_listen_affordance.py
pytest -q -m "not pg"
```

CI does not require real model files (existing TTS posture); provider-availability is reported false without failing the build. Live audio (real Piper/Kokoro output) is a mac-mini/operator receipt, folded into promote-to-test per house practice, matching `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`.

## Out of Scope

New TTS engines, voices, or languages; changing per-segment voice-selection or concatenation logic (owned by the existing `app/tts/*` capability, #2114); TTS provisioning itself (`docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`); OS-level push/notification delivery of audio; the composer (BRIEF-01) and the day-start card layout (BRIEF-04) beyond the listen affordance itself.

## Restart / Durability Posture

The synthesized audio artifact lives in the existing TTS cache (`TTS_CACHE_DIR`, LRU-evicted, already a derived/rebuildable store — see `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md :: Cache and Logs`). Losing the cache loses only re-synthesis time, never the briefing itself: the underlying text (BRIEF-01's durable note) is untouched, and a cache miss simply re-synthesizes on the next tap. No new non-durable state is introduced by this task beyond what the existing TTS cache already carries.

## Related Docs

- `docs/DAILY_BRIEFING/README.md` (capability spec)
- `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` (the note this task renders)
- `docs/DAILY_BRIEFING/SURFACE_DAY_START_CARD.md` (the card that hosts this listen affordance)
- `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md` (the shipped SpeechPlan/TTS contract this task consumes)
- `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md` (operator provisioning, unchanged by this task)
- `app/tts/planning.py`, `app/tts/service.py`, `app/tts/concat.py` (existing TTS implementation)

## Related GitHub Issues

One issue: `[Daily Briefing] render-briefing-audio: mixed sv/en one-tap listen via the existing SpeechPlan/TTS pipeline`. `agent:blocked` until BRIEF-01 merges.
