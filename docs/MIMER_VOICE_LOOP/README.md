State: Specification directory — FILED (parent #3335; children #3336–#3339 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). One of the seven Yggdrasil closed-loop capabilities grounded in `docs/research/yggdrasil-closed-loops-ideation.md` (loop 5). Subordinate to `docs/contracts/MIMER_CLIENT_CONTRACT.md` (client-agnostic transports), ADR-0056 (client contract + transport set), ADR-0043 (Heimdal = sensor constituent), ADR-0055 (multi-writer posture — only touched by the append-only transcript log), and `docs/architecture/SBS_OPERATING_MODEL.md` (classification + boundary-work rules).
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory + the governing contracts/ADRs; GitHub issues (#3335–#3339) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Mimer Voice Loop — Specification ("Talk to Mimer")

A **closed voice conversation with the vault**: audio question in → transcript → grounded ASK answer with per-source citations → text answer **and** spoken answer out. Turn-based, read-only, client-agnostic.

Owner context (`docs/research/yggdrasil-closed-loops-ideation.md`, loop 5): the owner is dyslexic and Swedish-native; every current query surface is read-or-type. Voice is the one interface where that disadvantage inverts. All three legs already ship **separately** — Heimdal speech-to-text on the capture path, ASK synthesis with citations, mixed sv/en per-segment TTS read-back — but **nothing connects microphone → ASK → spoken answer**. This capability is the wiring, plus the one new contract that lets Bifrost native clients (Epic B) consume it later without change.

Classification: **Product/Runtime System work** (a new human interface surface over shipped cognition), with **one boundary task** (VOICE-02) that crosses the Heimdal capture path ↔ Mimer voice-ask path seam. Primary subsystem: **HIX** (human interaction & intent). Secondary: **RCA/CAO** (the ASK synthesis it wraps), **EXE** (the local STT/TTS capabilities), **HKA** (the append-only chat-session transcript, the only vault write in the loop).

## What already ships (the three legs, verified)

| Leg | Where it lives today | Consumed by voice loop as |
| --- | --- | --- |
| **STT (audio→transcript)** | `app/media/transcribe.py::run_asr` — faster-whisper, local-only, `int8`, module-level `_MODEL_CACHE`; language **auto-detected** (`model.transcribe(...)` with no `language=` arg → `info.language`), never asserted as ground truth. Heimdal's capture-path glue `app/heimdal/asr_stage.py::run_asr_stage` already reuses it via lazy import ("no two whisper instances", `docs/HEIMDAL/FABLE_COMPANION.md` §5.2/§9-j). | the transcription leg (VOICE-02 names + verifies the sharing) |
| **Grounded ASK + citations** | `POST /api/ask` → `app/api/routes/ask.py::ask` → `app/agents/ask/graph.py::run_ask_graph`; `AskResponse{answer, sources[AskSource{uuid,title,origin,plane,zone,path}], synthesis_receipt_id, …}`; system prompt `app/settings/models.py::DEFAULT_ASK_SYSTEM_PROMPT` (answer only from provided sources; say "unsure" when unsupported). Answer language implicitly follows the question language (LLM behavior; bilingual eval battery `docs/eval/ask_cases_bilingual.yaml`). | the answer leg (reused as-is) |
| **Mixed sv/en TTS** | `app/tts/planning.py::build_tts_plan` → SpeechPlan (`segments[]` each `{index,text,language,voice_id,provider,provider_available}`, `mixed_language`, `cache_key`, `audio_url`); per-sentence `app/tts/language.py::segment_by_language`; voices sv-SE→Piper `sv_SE-lisa-medium`, en→Kokoro `bf_isabella`; endpoints under `/api/companion/tts/*`; local-only, `TTS_ENABLED` default false, `/tts/synthesize` returns 503 when unavailable (never browser/cloud fallback). | the spoken-answer leg (reused as-is) |
| **Chat-session transcript** | `app/chat/session_log.py::SessionLogWriter` (`open_session`/`append_turn`/`close_session`) → `vault/.chats/<slug>/<ts>-<label>.md` (frontmatter `type: chat-session`, `session_id`, `date`). **This is already an ERE-registered stream** — `chat.sessions` is `live` in `docs/EPISODE_RESOLUTION_ENGINE/README.md` — so a voice conversation logged here becomes episode signal for free. | the durability + episode-signal seam (VOICE-04) |

## The one new surface

`POST /api/ask/voice` — a single orchestrating turn endpoint: multipart audio in; returns `{transcript, answer, sources, speech_plan, audio_url?, degraded?}`. One endpoint, so every client (companion UI now, Bifrost B3 later) gets the whole turn without re-implementing STT→ASK→TTS orchestration. This is the contract VOICE-01 adds to `docs/contracts/MIMER_CLIENT_CONTRACT.md §4` and Bifrost B1/B3 (#3023/#3026) consume unchanged.

## Hard invariants (capability-level; do not weaken)

1. **Read-only, end-to-end.** Voice-ask never writes the vault. Capture stays Heimdal's job. If the utterance is a *capture intent* ("remember that…", "add to my inbox…"), the correct behavior is to **say so** — surface it as a suggestion to use the capture path — **not to write**. The single exception is the append-only chat-session transcript (VOICE-04), which is ADR-0055's append-only writer class (last-write-wins accepted), not a content write to a human note.
2. **One transcription implementation — no fork.** The voice path and the Heimdal capture path resolve to the same `app/media/transcribe.py::run_asr` (one model cache). A second STT implementation on the voice path is a defect.
3. **Citation fidelity survives into speech.** Every source the text answer cites must be representable **speakably** in the SpeechPlan; the spoken answer never drops a citation the text shows and never speaks a raw uuid or filesystem path.
4. **Degrade legibly at every leg.** STT unavailable → explicit `stt_unavailable` error, never a silent empty or hallucinated answer. ASK unavailable → propagate its error, never answer from model memory while claiming vault grounding (`MIMER_CLIENT_CONTRACT.md` §6). TTS unavailable → text answer + citations still returned with a degrade marker (SpeechPlan `provider_available:false`), never a failed turn.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [DEFINE_VOICE_ASK_CONTRACT](DEFINE_VOICE_ASK_CONTRACT.md) | VOICE-01 | — (∥ with 2) |
| 2 | [SHARE_TRANSCRIPTION_CAPABILITY](SHARE_TRANSCRIPTION_CAPABILITY.md) | VOICE-02 | — (∥ with 1) |
| 3 | [SURFACE_PUSH_TO_TALK_COMPANION](SURFACE_PUSH_TO_TALK_COMPANION.md) | VOICE-03 | VOICE-01 (∥ with 4) |
| 4 | [CARRY_SESSION_FOLLOWUP_CONTEXT](CARRY_SESSION_FOLLOWUP_CONTEXT.md) | VOICE-04 | VOICE-01 (∥ with 3) |

Flat order: **1 ‖ 2 → 3 ‖ 4.**

## Cross-Task Invariants / Interaction Safety

The four tasks share the voice-turn path and the transcript seam; these invariants hold *across* tasks, with the partial-failure walks that the seams demand:

- **INV-VOICE-A — the loop writes nothing but the append-only transcript.** VOICE-01's turn endpoint, VOICE-02's STT leg, and VOICE-03's UI produce no vault write; only VOICE-04's transcript append touches the vault, through the existing `SessionLogWriter` (ADR-0055 append-only class). *Partial failure — ASK succeeds, transcript-log append fails:* the answer is still returned to the user; the log is best-effort episode signal, never a precondition for answering. A failed or absent log degrades episode richness, never the turn. *Partial failure — capture-intent utterance:* it is surfaced as a suggestion and produces zero writes; a voice-ask that ever writes a human note is a contract violation an invariant probe must fail on.
- **INV-VOICE-B — one transcription engine across both paths.** The Heimdal capture path (`asr_stage.run_asr_stage`) and the voice-ask path (VOICE-01) both resolve to `app/media/transcribe.py::run_asr`; the model cache is shared, not duplicated. *Partial failure — engine import fails on the voice path:* the turn returns `stt_unavailable` (INV-VOICE-D), it never silently spins up a second, divergent transcriber. A second STT module on the voice path is a fitness violation VOICE-02's no-fork test fails on.
- **INV-VOICE-C — citation set is identical text↔speech.** The sources rendered in `answer`/`sources` and the speakable citations in the SpeechPlan derive from **one** `AskResponse.sources` list; the speech-rendering step may *reformat* a citation (uuid/path → "your note '<title>'") but may never *drop* or *add* one. *Partial failure — TTS down:* the text answer carries the full citation set; the audio leg is simply absent, so the citation set the user can see is unchanged, only unspoken.
- **INV-VOICE-D — every leg degrades to a legible, named state.** Each leg has exactly one honest failure surface: STT→`stt_unavailable` (explicit error), ASK→propagated ASK error (never model-memory answer), TTS→text-only + `degraded` marker. *Walk STT ok + ASK down:* the turn fails at ASK but **returns the transcript** so the user sees what was heard and can retry. *Walk ASK ok + TTS down:* the turn returns `answer + sources` as text with `degraded:true, reason:"tts_unavailable"`, `audio_url` absent — a successful (if silent) turn, not a 5xx.

If these four cannot be stated as holding across the tasks, the slice boundaries are wrong. They are the reason VOICE-01 owns the turn contract (A/C/D live in the endpoint), VOICE-02 owns the engine seam (B), and VOICE-04 owns the transcript seam (A's write half).

## Restart / Durability Posture (capability-level)

The **persisted** chat-session transcript survives a restart (it is a file in `vault/.chats/`). The **live in-session conversational context** that VOICE-04 uses to resolve follow-ups ("and the second one?") is **in-memory, keyed by voice session id, and lost on process restart**. Trust consequence, stated plainly: after a runtime restart mid-conversation, a follow-up question can no longer resolve against the earlier turn — the user experiences the assistant "losing the thread," and must restate context. This is acceptable for v1 turn-based voice; the durable cross-session "hot cache" (fable5-audit G6) is explicitly **out of scope** and separately tracked (see VOICE-04).

## Capability acceptance criteria

- [ ] End-to-end on a fixture: audio question → transcript → grounded `AskResponse` with ≥1 citation → SpeechPlan whose spoken text carries a speakable citation, all in one `POST /api/ask/voice` turn. Verify: `tests/voice/test_voice_ask_end_to_end.py::test_audio_question_returns_grounded_spoken_answer` (lands with VOICE-01)
- [ ] Read-only enforcement: a voice turn (including a capture-intent utterance) performs zero vault content writes; capture intent is surfaced, not written. Verify: `tests/voice/test_voice_ask_readonly.py::test_capture_intent_is_surfaced_not_written` and `tests/voice/test_voice_ask_readonly.py::test_voice_turn_writes_no_vault_note`
- [ ] One-engine invariant: the voice path and Heimdal capture path resolve to the same `run_asr`; no second STT implementation exists on the voice path. Verify: `tests/voice/test_transcription_sharing.py::test_voice_and_capture_share_one_asr_engine` (VOICE-02)
- [ ] Citation fidelity: every `AskResponse.sources` entry is represented speakably in the SpeechPlan; no raw uuid/path is spoken. Verify: `tests/voice/test_citation_speech_fidelity.py::test_every_citation_is_speakable_and_none_dropped`
- [ ] Degrade legibility across both partials (STT ok + ASK down; ASK ok + TTS down). Verify: `tests/voice/test_voice_degrade_paths.py::test_ask_down_returns_transcript_and_error` and `::test_tts_down_returns_text_answer_with_degrade_marker`
- [ ] In-session follow-up resolves against the current session's prior Q&A only, and the transcript persists via the existing chat-session path (ERE `chat.sessions` stream). Verify: `tests/voice/test_session_followup.py::test_followup_resolves_against_in_session_context_only`
- [ ] Companion UI push-to-talk: hold-or-tap to talk, spoken answer plays, text + citations visible, zero typing. Verify: companion_ui render/interaction test `tests/companion_ui/test_push_to_talk_surface.py::test_push_to_talk_renders_answer_citations_and_audio` + local UAT receipt on the parent issue
- [ ] Live validation on the mac mini test channel: ≥1 real spoken question (sv and en) answered end-to-end with audible answer, receipt posted to the parent issue. Verify: parent-issue validation receipt (mac mini test channel; laptop is not the runtime env)
- [ ] Owner-doc promotion only after acceptance: `docs/contracts/MIMER_CLIENT_CONTRACT.md §4` callable-surface table gains the voice-ask row as delivered truth. Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: 4. Callable HTTP surface`

## Relationship to GitHub issues

**Filed 2026-07-07.**

- **Parent feature issue** — **#3335** (Backlog, `agent:blocked`, live validation hub while children are outstanding); see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).
- **VOICE-01** → **#3337** and **VOICE-02** → **#3338** — filed `agent:blocked`; both are dependency-free heads and flip to `agent:ready` once this spec PR merges to `main`.
- **VOICE-03** → **#3339** and **VOICE-04** → **#3336** — filed `agent:blocked`, staying blocked until VOICE-01/#3337 merges (they consume the turn contract).

The spec is the source of truth; issues track pickup state. One task specification may map to more than one issue if the implementation is large (e.g. VOICE-01's contract-doc and endpoint-skeleton halves), but each remains independently mergeable.

## Bifrost consumption (client-agnostic by design)

The whole point of the single `POST /api/ask/voice` turn contract is that native clients consume it **without change**:

- **B1 — #3023 (`bifrost#1`)** establishes Bifrost's adherence to `docs/contracts/MIMER_CLIENT_CONTRACT.md`. VOICE-01 adds the voice-ask row to that contract's callable surface, so B1's contract-conformance work automatically covers the voice endpoint — no Bifrost-specific server work.
- **B3 — #3026** is where the mobile/Watch capture-and-now-query context arrives. The ideation capture notes Bifrost B3 is *capture-only* today; the voice-ask contract is exactly what lets a B3 surface add spoken query later by calling the same endpoint. Mobile/Watch surfaces are **out of scope here** (this capability delivers the server contract + the companion UI surface); B3 consumes the contract when its transport work lands.

Neither Bifrost issue is a prerequisite for this capability, and this capability files no Bifrost work.

## Out of scope (capability level)

Wake word / always-on listening (that is the **Heimdal capture-posture fork** — Posture A discrete vs Posture B always-on, an owner decision; `docs/HEIMDAL/OWNER_DECISIONS.md`; referenced, not opened here); mobile/Watch surfaces (Bifrost B3 #3026 consumes the contract later); voice *capture* (already Heimdal's job); any vault content write; speaker identification / diarization-for-identity; streaming or interruptible TTS (v1 is turn-based); the durable cross-session "hot cache" primitive (fable5-audit G6, separately tracked).
