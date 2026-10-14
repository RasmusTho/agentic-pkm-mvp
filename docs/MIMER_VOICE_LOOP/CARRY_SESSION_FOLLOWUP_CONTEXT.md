---
name: Carry Session Followup Context
description: Session-scoped conversational context — follow-ups resolve against the current voice session's prior Q&A only; the session transcript persists through the existing chat-session path (ERE chat.sessions stream)
task_id: VOICE-04
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 5. Mimer voice loop
parent_capability: Mimer Voice Loop
prerequisites: [VOICE-01]
depends_on: [DEFINE_VOICE_ASK_CONTRACT.md]
can_parallelize_with: [Surface Push-to-Talk Companion]
---

# Carry Session Followup Context

## Repository implementation

VOICE-04 is implemented in `app/api/routes/ask.py::ask_voice` and
`app/chat/voice_session.py::VoiceSessions`. A successful question turn on an initialized,
selected vault returns a server-minted `session_id`; callers pass it on later turns.
`end_session=true` appends the existing writer's close marker and retires the live
context. Unknown, closed, restarted, or differently scoped/selected sessions return
`409 voice_session_context_lost`; the caller starts a new session and restates context.
Session context is process-local, so a different API worker also refuses an unknown id.

Within one API process, the shared `VaultManager.selection_window()` holds the
selection stable from context lookup through ASK retrieval and transcript
create/append/close. Concurrent selection and lazy selection loading wait until
those effects finish. Derived TTS runs after the window is released. This is an
ephemeral mutex, not durable session state or a cross-process recovery promise.

Standalone voice logs use `SessionLogWriter.open_session(None, "voice")` under
`.chats/voice/`, without creating an anchor note or healing a human note's UUID.
Each voice `append_turn` supplies one UTC timestamp for both the question and answer
line and quotes their Markdown bodies. The existing note-linked canvas call shape is
unchanged. Citations are retained in both the live Q&A and the transcript.
`SessionStore(durable=False)` holds only in-process pointers: voice turns never write
or restore `.canvas-sessions` pointers and never reconstruct live context from disk.

The transcript is best effort per `README.md :: Cross-Task Invariants / Interaction
Safety`: a write refusal, unselected/uninitialized vault, or failed append leaves the
grounded answer available and reports `session_error: session_transcript_unavailable`.
That marker is separate from `reason: tts_unavailable`, so simultaneous degradation
does not conceal a missing log. Capture-intent suggestions create no transcript.
The scoped mutation seal remains active on this compatibility route.

The five task tests below exercise the shipped route and writer. Repository delivery
does not establish qualified TEST audio acceptance or current ERE consumption;
`chat.sessions` remains a planned adapter and parent #3335 retains those gates.

## Purpose

Spoken conversation is inherently follow-up-shaped: "what did I decide about the project?" → "and the second option?". A single-turn endpoint answers each question in a vacuum. This task adds **session-scoped** context so a follow-up resolves against the current voice session's prior Q&A — and persists the conversation through the **existing chat-session path**, preserving the shape the planned ERE adapter will later consume.

## What This Task Does

1. **In-session context** — the voice-ask turn accepts an optional `session_id`. Within a session, the prior turns' questions and answers (and their citations) form a small rolling context appended to the ASK question so a pronoun/ellipsis follow-up ("the second one", "why?") resolves against **this session's** prior Q&A **only**. First turn opens a session and returns its `session_id`; subsequent turns pass it back.
2. **Persistence through the existing seam** — the session transcript is written via the shipped `app/chat/session_log.py::SessionLogWriter` (`open_session` on turn 1, `append_turn` per Q&A, `close_session` on end) to `vault/.chats/…`, frontmatter `type: chat-session`, `session_id`. **No new persistence primitive.** `chat.sessions` is declared **planned** in ERE until a normalizing adapter lands, so this task preserves the future adapter shape but does not claim the transcript is consumed today.
3. **Per-turn timestamp** — record a per-turn timestamp on each `append_turn` (Q and A). The shipped writer stamps only a session-level `date`; the ERE `chat.sessions` contract expects **per-turn timestamps** for time-dimension segmentation. Close that small gap here so voice turns segment correctly as episode signal. (This is an append-only chat-log write — ADR-0055 append-only class, last-write-wins accepted — not a human-note content write; the read-only invariant is intact.)
4. **Bounded scope** — context is the session's prior turns, nothing else. It reaches into no durable cross-session memory; a new session starts empty.

## Concretely

```
$ POST /api/ask/voice  (audio="what did I decide about Projekt X?")            → {session_id:"s-1", answer:"…", …}
$ POST /api/ask/voice  (audio="and the second option?", session_id:"s-1")      → resolves "second option" against turn 1's answer
# transcript on disk:
vault/.chats/projekt-x/2026-07-07T…-voice.md   # type: chat-session, session_id: s-1, per-turn timestamps
```

## Why This Matters

Without in-session context, every spoken follow-up must be a fully-restated question — punishing for a voice-first, dyslexic user, and unnatural for speech. Persisting through the chat-session path (rather than a bespoke store) preserves the single future Episode Resolution Engine adapter seam; it does not flow into ERE until that planned adapter lands. The per-turn timestamp keeps the artifact ready for that later segmentation path.

## Acceptance Criteria

- [ ] AC1: within a session, a follow-up resolves against the current session's prior Q&A (a pronoun/ellipsis follow-up gets a correct answer that a first-turn cold ask could not). Verify: `tests/voice/test_session_followup.py::test_followup_resolves_against_in_session_context`
- [ ] AC2 (scoping): a follow-up in a **new** session does **not** see the prior session's context; context is session-bounded and reaches no durable cross-session store. Verify: `tests/voice/test_session_followup.py::test_context_does_not_leak_across_sessions`
- [ ] AC3: the transcript persists via `SessionLogWriter` to `vault/.chats/…` with `type: chat-session` + `session_id`, matching the planned ERE `chat.sessions` adapter shape without claiming current consumption. Verify: `tests/voice/test_session_transcript.py::test_voice_transcript_written_as_chat_session`
- [ ] AC4: each turn carries a per-turn timestamp on both the question and the answer line. Verify: `tests/voice/test_session_transcript.py::test_each_turn_has_a_timestamp`
- [ ] AC5 (enforcement, read-only): the only vault write on the turn path is the append-only chat-session transcript; no human-note content write occurs — asserted at the turn's production write call site. Verify: `tests/voice/test_session_transcript.py::test_only_write_is_appendonly_transcript`

## How to Verify (Pre-Merge)

```bash
ruff check app tests companion-ui/companion-app
mypy app
python3 scripts/docs_guard.py --language-only
python3 -m pytest -q tests/voice/ tests/chat/
python3 scripts/select_pr_tests.py --base-ref <immutable-main-sha> --head-ref <candidate-sha>
```

Run the selector's emitted `pytest_args` through the canonical host lease:
`python3 scripts/run_with_host_lease.py --resource pytest-not-pg --execution-id issue3336:<candidate-sha> -- python3 -m pytest <emitted-args>`.
Retain the complete selection and its marker expression from
`docs/development/TEST_STRATEGY_HOT_PATH.md`; record the base, candidate, command
and actual terminal result. Every task `Verify:` target and the selected tests
must pass, with an independent review of the current contract and implementation
and current-head CI before merge. The full voice and chat suites protect existing
turn callers and note-linked session-log behavior.

The append-only integration proof is
`tests/voice/test_session_transcript.py::test_only_write_is_appendonly_transcript`:
HTTP requests use the real selected-vault resolver, `SessionLogWriter` and guarded
create/append/close operations on an isolated initialized vault. It checks existing
human/config bytes, the `.chats/voice/` write boundary and absence of
`.canvas-sessions` writes. The voice suites also check scope/vault isolation,
restart and close refusal, concurrent HTTP selection/ASK/transcript ordering,
capture-intent zero writes, write refusal/append failure
and quoted timestamped Markdown framing. ASR, ASK synthesis and TTS doubles in
these tests prove session wiring and failure boundaries, not live model/audio quality.

The generic `tests/uat` Canvas/Panel journeys do not exercise voice sessions or
this transcript seam, so they are not VOICE-04 pre-merge proof. Parent #3335 still
owns composed UI and qualified TARS TEST sv/en audio acceptance through the actual
configured routes. Its acceptance remains pending until that proof passes;
repository slice verification does not replace it or any required real-model
qualification. Broader E2E/live/eval/UAT lanes retain their dedicated owners under
the repository test strategy.

## Restart / Durability Posture (required — in-memory state)

- **What survives a restart:** the **persisted transcript** in `vault/.chats/`; ERE consumption remains pending on the planned `chat.sessions` adapter.
- **What does not:** the **live in-session context binding** — the rolling prior-Q&A used to resolve follow-ups is **in-memory, keyed by `session_id`**. A process restart drops it.
- **What the user experiences:** after a restart mid-conversation, a follow-up ("and the second one?") can no longer resolve against the earlier turn — the assistant "loses the thread" and the user must restate context. Being in-memory is stated honestly here because the trust consequence is real: a follow-up that silently answers as if it still had context would be worse than an honest "I've lost the earlier part — which option do you mean?". v1 accepts the loss (turn-based voice, short sessions); it does not paper over it.

## Out of Scope

The durable, cross-session **"hot cache"** primitive (fable5-audit **G6** — a persistent working-context store that would survive restart and span sessions) is **explicitly out of scope and separately tracked**; this task is in-session only. Rebuilding live context from the persisted transcript after a restart (possible in principle, not built in v1); summarization/compaction of long sessions; building or changing the planned ERE `chat.sessions` adapter; cross-session memory promotion (MEM authority path, untouched).

## Related Docs

- `app/chat/session_log.py::SessionLogWriter` (`open_session`/`append_turn`/`close_session`); `app/chat/session_store.py::SessionStore` (session pointer index)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md` (input inventory — `chat.sessions` planned) + `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` (the future adapter contract voice turns are shaped to feed)
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (append-only writer class — the transcript's write class); `project_fable5_audit` (G6 hot-cache, out of scope); VOICE-01 turn contract

## Related GitHub Issues

Child #3336 owns this repository implementation; VOICE-01 was delivered by PR #3490.
Parent #3335 owns capability validation and qualified TEST acceptance. TCD capability
selection follows the configured resolver: the in-memory/durable split, future ERE
shape, and append-only enforcement justify an independent review of the bounded change.
