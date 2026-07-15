State: FILED — the parent feature issue is live as #3335 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3337 (VOICE-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3338 (VOICE-02, dependency-free head — flips to agent:ready when this spec PR merges to main), #3339 (VOICE-03, blocked until VOICE-01/#3337 merges), #3336 (VOICE-04, blocked until VOICE-01/#3337 merges).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3335; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Mimer Voice Loop] parent: microphone → grounded ASK → spoken answer, read-only and client-agnostic

Title on GitHub: `[Mimer Voice Loop] parent: close the voice loop — audio question → grounded ASK with citations → spoken answer, read-only and client-agnostic`

## Context

The owner is dyslexic and Swedish-native; every current query surface is read-or-type. Voice is the one interface where that disadvantage inverts (`docs/research/yggdrasil-closed-loops-ideation.md`, loop 5). All three legs ship **separately** — Heimdal STT on the capture path (`app/media/transcribe.py::run_asr`), grounded ASK with citations (`POST /api/ask`), mixed sv/en per-segment TTS (`app/tts/planning.py::build_tts_plan`) — but nothing connects microphone → ASK → spoken answer. The capability is fully specified in `docs/MIMER_VOICE_LOOP/` (this spec directory is the source of truth). The one new surface is a single orchestrating turn endpoint, `POST /api/ask/voice`, added to `docs/contracts/MIMER_CLIENT_CONTRACT.md` so Bifrost native clients (B1 #3023, B3 #3026) consume it later without change.

This parent is the **live validation hub**: children post validation receipts here; it is `agent:blocked` (not a pickup issue) while children are outstanding.

## Scope

The capability outcome — not one PR: a client-agnostic voice-ask turn (STT → grounded ASK → SpeechPlan/audio), one shared transcription engine across the capture and voice paths (no fork), a companion-UI push-to-talk surface with zero typing, and in-session follow-up context whose transcript persists through the existing chat-session path. ERE keeps `chat.sessions` declared as `planned` until its adapter lands, so episode consumption is a named future seam rather than a free current behavior. Turn-based and read-only end to end. Mobile/Watch surfaces, wake word, and the durable cross-session hot cache are explicitly out of scope.

## Source Anchors

- `docs/MIMER_VOICE_LOOP/README.md` (spec: legs, the new surface, cross-task invariants, capability ACs, Bifrost consumption)
- `docs/research/yggdrasil-closed-loops-ideation.md :: 5. Mimer voice loop`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md :: 4. Callable HTTP surface` (addition target); `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` (transports); `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md` (Heimdal = sensor); `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (append-only transcript class)

## SBS Impact

- Primary subsystem: HIX (human interaction & intent — a new interface surface over shipped cognition)
- Secondary subsystem(s): RCA/CAO (the ASK synthesis it wraps), EXE (local STT/TTS capabilities), HKA (append-only chat-session transcript — the only vault write), SIP (future `chat.sessions` adapter boundary; not consumed while planned)
- Write class: read-only end-to-end **except** the append-only chat-session transcript (mechanical, append-only class per ADR-0055; not authority-bearing, not a human-note content write)
- Authority impact: none — voice-ask never promotes or mutates human knowledge; capture intent is surfaced, not written
- Persistence impact: no new persistence primitive — transcript uses the shipped `SessionLogWriter` (`vault/.chats/`); in-session context is in-memory (lost on restart, stated)
- Derived/rebuildable impact: SpeechPlan + synthesized audio are derived/cache-key-addressed (rebuildable); transcript is durable
- Human knowledge impact: none written; answers are read-only synthesis with citations
- Memory impact: none — in-session context is not MEM; no memory promotion
- Retrieval/context impact: reuses ASK retrieval unchanged; in-session context is a per-session rolling append to the ASK question only
- Sync/deployment impact: TTS provisioning per `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md` (local-only, `TTS_ENABLED` gated); new API route
- External boundary impact: none new — STT/TTS are existing local capabilities; no cloud egress added (STT/TTS local-only)
- New or changed contract: `POST /api/ask/voice` added to `MIMER_CLIENT_CONTRACT.md §4` (VOICE-01); a transcription-sharing seam note (VOICE-02)
- Owner-doc impact: will-update-in-PR on acceptance — client-contract callable-surface row
- Transition debt impact: reduces (fills the "microphone → ASK → spoken answer is unwired" gap the ideation capture names); adds a bounded, stated debt (in-session context is in-memory, no restart durability)
- Fitness rule impact: strengthens — adds a no-fork ASR-engine invariant (VOICE-02) and a read-only voice-turn probe

## Constraints

Read-only end-to-end (only the append-only transcript writes; capture stays Heimdal's job; capture-intent utterances are surfaced, never written). One transcription engine — no second whisper instance (VOICE-02). Citation fidelity survives text→speech (no raw uuid/path spoken). Every leg degrades legibly (STT→explicit error; ASK→propagated error + transcript; TTS→text answer + degrade marker). No ASK-prompt or TTS-voice change. Client-agnostic (companion UI and Bifrost consume one contract). STT/TTS stay local-only (no cloud egress); ASK synthesis routing follows the shipped model posture (human-invoked, paid-eligible under `capability-first`).

## Acceptance Criteria

The capability-level ACs in `docs/MIMER_VOICE_LOOP/README.md :: Capability acceptance criteria`, each with its `Verify:` target there — including the end-to-end grounded-spoken-answer turn, the read-only + capture-intent-surfaced enforcement, the one-engine no-fork invariant, citation text↔speech fidelity, both degrade partials (STT ok + ASK down; ASK ok + TTS down), in-session follow-up scoping, the zero-typing push-to-talk surface, and a live sv+en audible-answer validation receipt from the mac mini test channel posted to this issue.

## Implementation Tasks

`docs/MIMER_VOICE_LOOP/` — VOICE-01..VOICE-04 per the README execution order: **1 ‖ 2 → 3 ‖ 4**.

- VOICE-01 [DEFINE_VOICE_ASK_CONTRACT](DEFINE_VOICE_ASK_CONTRACT.md) — the turn contract + endpoint skeleton (prereq: none)
- VOICE-02 [SHARE_TRANSCRIPTION_CAPABILITY](SHARE_TRANSCRIPTION_CAPABILITY.md) — one ASR engine, verified no-fork; boundary work (prereq: none)
- VOICE-03 [SURFACE_PUSH_TO_TALK_COMPANION](SURFACE_PUSH_TO_TALK_COMPANION.md) — companion UI push-to-talk, zero typing (prereq: VOICE-01)
- VOICE-04 [CARRY_SESSION_FOLLOWUP_CONTEXT](CARRY_SESSION_FOLLOWUP_CONTEXT.md) — in-session context + transcript as ERE chat-session (prereq: VOICE-01)

## Verification Path

Per-task `Verify:` targets (each task couples ACs to `How to Verify (Pre-Merge)`); VOICE-01/03/04 touch a new user-facing surface / vault-write path → full `not pg` suite + opt-in `RUN_INTEGRATED_RUNTIME_UAT=1`; VOICE-02 runs the no-fork test + the Heimdal `asr_stage` regression guard; TTS-audible and sv/en checks are mac-mini test-channel receipts (laptop is not the runtime env).

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, degrade-path outputs). After VOICE-01: the end-to-end fixture turn. After VOICE-03/04: the companion-UI local UAT render receipt. Acceptance → a real spoken sv + en question answered audibly end-to-end on the mac mini test channel (receipt here), then one owner-doc promotion PR (the client-contract callable-surface row) and parent closure. In-memory-context durability and any hedgy-answer quality observations spin off as follow-up issues / a `LearningSignal`, not blockers.

## Out of Scope

Wake word / always-on listening (the Heimdal capture-posture fork — an open owner decision, referenced not opened); mobile/Watch surfaces (Bifrost B3 #3026 consumes the contract later); voice capture (Heimdal's job); any vault content write; speaker identification; streaming/interruptible TTS (v1 turn-based); the durable cross-session hot cache (fable5-audit G6, separately tracked); any change to ASK synthesis or TTS voices.

## Suggested Validation

`pytest -q tests/voice/` and `pytest -q -m "not pg"` per child; `pytest -q tests/heimdal/test_asr_stage.py` (VOICE-02 regression guard); `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat` for surface/write children; `curl -F audio=@q.m4a .../api/ask/voice` + audible playback on the mac mini test channel; receipts to this issue.

## Source Docs

`docs/MIMER_VOICE_LOOP/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`; `docs/contracts/MIMER_CLIENT_CONTRACT.md`; ADR-0056; ADR-0043; ADR-0055.
