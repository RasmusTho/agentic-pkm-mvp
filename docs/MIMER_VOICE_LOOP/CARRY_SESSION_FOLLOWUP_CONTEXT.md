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

```
ruff check app tests && mypy app
pytest -q tests/voice/test_session_followup.py tests/voice/test_session_transcript.py
pytest -q tests/chat/            # regression guard: session_log writer behavior unchanged for existing callers
pytest -q -m "not pg"
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # vault-write path (append-only) → opt-in UAT gate
```

## Restart / Durability Posture (required — in-memory state)

- **What survives a restart:** the **persisted transcript** in `vault/.chats/`; ERE consumption remains pending on the planned `chat.sessions` adapter.
- **What does not:** the **live in-session context binding** — the rolling prior-Q&A used to resolve follow-ups is **in-memory, keyed by `session_id`**. A process restart drops it.
- **What the user experiences:** after a restart mid-conversation, a follow-up ("and the second one?") can no longer resolve against the earlier turn — the assistant "loses the thread" and the user must restate context. Being in-memory is stated honestly here because the trust consequence is real: a follow-up that silently answers as if it still had context would be worse than an honest "I've lost the earlier part — which option do you mean?". v1 accepts the loss (turn-based voice, short sessions); it does not paper over it.

## Out of Scope

The durable, cross-session **"hot cache"** primitive (fable5-audit **G6** — a persistent working-context store that would survive restart and span sessions) is **explicitly out of scope and separately tracked**; this task is in-session only. Rebuilding live context from the persisted transcript after a restart (possible in principle, not built in v1); summarization/compaction of long sessions; any change to how ERE segments chat sessions (it consumes the stream as-is); cross-session memory promotion (MEM authority path, untouched).

## Related Docs

- `app/chat/session_log.py::SessionLogWriter` (`open_session`/`append_turn`/`close_session`); `app/chat/session_store.py::SessionStore` (session pointer index)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md` (input inventory — `chat.sessions` planned) + `STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` (the future adapter contract voice turns are shaped to feed)
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (append-only writer class — the transcript's write class); `project_fable5_audit` (G6 hot-cache, out of scope); VOICE-01 turn contract

## Related GitHub Issues

One issue: `[Mimer Voice Loop] session-followup: in-session voice context + transcript persisted as an ERE chat-session`. `agent:blocked` until VOICE-01 merges (consumes the turn contract; parallelizable with VOICE-03). TCD hint: **sonnet, high reasoning** — bounded surface, but the in-memory/durable split, the ERE stream-shape match, and the read-only append-only enforcement each carry correctness risk that rewards careful reasoning.
