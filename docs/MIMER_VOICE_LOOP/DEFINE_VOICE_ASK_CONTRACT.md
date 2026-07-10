---
name: Define Voice-Ask Contract
description: The client-agnostic voice-ask turn — audio in, transcript + grounded ASK answer with citations + SpeechPlan/audio out; one orchestrating endpoint honoring the read-only and degrade invariants
task_id: VOICE-01
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 5. Mimer voice loop
parent_capability: Mimer Voice Loop
prerequisites: []
depends_on: []
can_parallelize_with: [Share Transcription Capability]
---

# Define Voice-Ask Contract

## Purpose

Nothing connects microphone → ASK → spoken answer. This task defines the **one** contract that does, as a single orchestrating turn so every client (companion UI now, Bifrost later) consumes the whole loop without re-implementing STT→ASK→TTS orchestration. Contract-first: the deliverable is the `docs/contracts/MIMER_CLIENT_CONTRACT.md` addition **plus** the endpoint skeleton honoring it.

## What This Task Does

1. **Contracts the turn shape** — `POST /api/ask/voice` (added to `docs/contracts/MIMER_CLIENT_CONTRACT.md §4` callable-surface table, marked `Read-only`):
   - **In:** multipart audio (`audio` part) + optional `session_id` (VOICE-04) + optional `zone_strategy` (passthrough to ASK). Format/limits stated in the contract: accept a small set of common containers the runtime can decode to WAV (wav/m4a/webm/ogg), a hard max duration and byte ceiling (named constants, e.g. 60 s / a few MB — a query utterance, not a recording), reject oversize with an explicit `audio_too_large` 413, reject undecodable with `audio_undecodable` 415. No streaming (v1 turn-based).
   - **Out:** `{transcript, detected_language, answer, sources[AskSource], speech_plan, audio_url?, degraded?, reason?, session_id, trace_id}`. `answer`/`sources` are the verbatim `AskResponse` shape (no re-typing); `speech_plan` is the `build_tts_plan` SpeechPlan; `audio_url` is the existing cache-key URL (`/api/companion/tts/audio/{cache_key}.wav`) when TTS synthesized, absent when degraded.
2. **Skeleton orchestration** — a `POST /api/ask/voice` route (`app/api/routes/ask.py` sibling or a new `app/api/routes/voice_ask.py`, registered under `/api`) that wires the three shipped legs in order: (a) STT via the shared engine (`app/media/transcribe.py::run_asr`, formalized by VOICE-02) on the decoded utterance — **ephemeral temp WAV, deleted after; NOT the Heimdal raw-read gate** (this audio is a transient query, not a governed Heimdal capture, so it produces no raw record); (b) grounded answer via `run_ask_graph` reusing `POST /api/ask` internals with `question = transcript`; (c) `build_tts_plan` over the answer, then `synthesize_tts` when `TTS_ENABLED` and provider available.
3. **Language handling** — transcription language is **detected** (faster-whisper `info.language`, sv/en auto), surfaced as `detected_language`; the ASK answer language **follows the question language** (current implicit LLM behavior, pinned by an AC and the bilingual eval battery); the SpeechPlan is built with `language=detected_language` so the spoken answer uses the sv or en voice matching the question, and mixed-language answers segment per-sentence (`segment_by_language`).
4. **Read-only enforcement + capture-intent handling** — the endpoint performs no vault content write. A lightweight capture-intent classifier on the transcript ("remember…", "add to my inbox…", "spara det…") sets `answer` to a **suggestion** ("That sounds like something to capture — say it to the capture surface to save it") and writes nothing; the turn stays read-only. (LLM-classification over keyword heuristics is preferred for the intent decision; the read-only *gate* stays deterministic — the endpoint has no write path to reach.)
5. **Degrade paths** — STT fails/unavailable → `stt_unavailable` (explicit error, no empty answer); ASK fails → propagate ASK's error but still return `transcript` so the user sees what was heard; TTS unavailable/`TTS_ENABLED` false → return `answer + sources` as text with `degraded:true, reason:"tts_unavailable"` and no `audio_url` (never a 5xx for a missing voice).

## Concretely

```
$ curl -sS -X POST http://127.0.0.1:8000/api/ask/voice \
    -H 'x-trace-id: t-123' -F audio=@question.m4a | jq '{transcript, detected_language, answer, n:( .sources|length), degraded}'
{"transcript":"vad bestämde jag om projektet i förra veckan?","detected_language":"sv","answer":"Enligt din anteckning 'Projekt X – planering' bestämde du …","n":2,"degraded":false}
# TTS disabled → same answer, text-only:
{"transcript":"…","answer":"…","n":2,"degraded":true}   # reason:"tts_unavailable", no audio_url
```

## Why This Matters

This is the seam the whole capability is named for. If the turn shape is not client-agnostic, Bifrost B3 must re-implement orchestration and the "consume without change" promise (#3023/#3026) fails. If a degrade path is silent — an empty answer on STT failure, a model-memory answer on ASK failure, a 5xx on missing TTS — the dyslexic owner who cannot fall back to reading gets a dead-end instead of a legible next step. If read-only leaks, a spoken question mutates the vault and voice stops being safe to talk to.

## Acceptance Criteria

- [ ] AC1: `POST /api/ask/voice` returns a well-formed turn for a decodable audio question — transcript, `detected_language`, verbatim `AskResponse` answer+sources, and a SpeechPlan. Verify: `tests/voice/test_voice_ask_end_to_end.py::test_audio_question_returns_grounded_spoken_answer`
- [ ] AC2 (enforcement): the endpoint performs **no vault content write** on any turn, and a capture-intent utterance is surfaced as a suggestion, not written — asserted at the route's production call path (no write adapter is reachable from it). Verify: `tests/voice/test_voice_ask_readonly.py::test_voice_turn_writes_no_vault_note` (asserts the route invokes no `write_ops`/governed-write call site) and `::test_capture_intent_is_surfaced_not_written`
- [ ] AC3: audio limits enforced — oversize → 413 `audio_too_large`, undecodable → 415 `audio_undecodable`, both before any STT work. Verify: `tests/voice/test_voice_ask_contract.py::test_audio_limits_rejected_legibly`
- [ ] AC4: detected sv vs en drives both the answer language and the SpeechPlan voice selection (sv→Piper lisa, en→Kokoro isabella); a mixed answer segments per-sentence. Verify: `tests/voice/test_voice_ask_language.py::test_detected_language_drives_answer_and_speechplan_voice`
- [ ] AC5 (degrade): STT unavailable → `stt_unavailable` error, never an empty/hallucinated answer. Verify: `tests/voice/test_voice_degrade_paths.py::test_stt_unavailable_is_explicit_error`
- [ ] AC6 (degrade): ASK down → error propagated **with** the transcript returned; TTS unavailable → `answer+sources` text with `degraded:true, reason:"tts_unavailable"`, no `audio_url`, HTTP 200. Verify: `tests/voice/test_voice_degrade_paths.py::test_ask_down_returns_transcript_and_error` and `::test_tts_down_returns_text_answer_with_degrade_marker`
- [ ] AC7 (contract doc): the voice-ask row exists in the client contract's callable surface with in/out shape, read-only marking, and the three degrade states. Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: 4. Callable HTTP surface`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/voice/
pytest -q -m "not pg"                                   # hot-path: new API route + reuses ASK graph
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # new user-facing surface → opt-in UAT gate
```

Live audible-answer verification (sv + en) is a mac-mini test-channel receipt on the parent issue (laptop is not the runtime env; TTS is provisioned there per `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`).

## Out of Scope

The push-to-talk UI (VOICE-03); in-session follow-up context and transcript persistence (VOICE-04); the shared-engine no-fork contract/test (VOICE-02 — this task consumes `run_asr`, VOICE-02 formalizes the sharing); any change to ASK synthesis, the ASK system prompt, or the TTS voices; streaming TTS; mobile/Watch transport; wake word.

## Restart / Durability Posture

The turn endpoint is stateless per request — a restart loses nothing it owns (each turn re-decodes, re-transcribes, re-asks). The only cross-turn state (in-session context) is VOICE-04's and is in-memory; see that task and the capability README for the restart trust consequence.

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4 (callable surface — the addition target), §3 (read-only + no-hidden-truth invariants), §6 (never answer from client/model memory claiming grounding); ADR-0056 (transport set = HTTP API + FS; this rides the HTTP API leg)
- `app/api/routes/ask.py` (`AskRequest`/`AskResponse`/`AskSource`, `run_ask_graph`); `app/settings/models.py::DEFAULT_ASK_SYSTEM_PROMPT`
- `app/tts/planning.py::build_tts_plan`, `app/tts/service.py::synthesize_tts`, `app/api/routes/companion.py` (`/tts/*`); `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`
- `app/media/transcribe.py::run_asr` (STT leg, formalized by VOICE-02); `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` (ASK synthesis is human-invoked → paid-eligible; STT/TTS are local-only)

## Related GitHub Issues

Likely one issue; may split into a contract-doc issue and an endpoint-skeleton issue if the implementation is large. Both `agent:ready` immediately (no prerequisites). TCD hint: **sonnet, high reasoning** — it composes shipped legs, but degrade-path completeness, read-only enforcement, and client-contract precision are the risk; opus is reserved for the boundary reshape in VOICE-02.
