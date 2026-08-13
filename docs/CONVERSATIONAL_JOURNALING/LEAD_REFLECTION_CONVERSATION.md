---
name: Lead Reflection Conversation
description: Agent-led reflective conversation on the existing chat-session surface — opens informed by the day-context bundle, asks a small number of reflective questions, follows up, owner-controlled length and language, on-demand plus an optional settings-governed evening nudge
task_id: JRNL-02
source_anchor: docs/HUMAN-FLOWS.md :: 0
parent_capability: Conversational Journaling
prerequisites: [JRNL-01]
depends_on: [ASSEMBLE_DAY_CONTEXT.md]
can_parallelize_with: []
---

# Lead Reflection Conversation

## Purpose

JRNL-01 assembles what the day held; this task is where the agent actually becomes the ghost-writer's *interviewer* — leading a short, informed, owner-paced conversation rather than presenting a blank prompt. It runs on the chat-session surface that already exists, rather than inventing a new conversational transport.

## What This Task Does

1. **Opens informed.** The conversation's first agent turn is generated from JRNL-01's assembled day-context bundle (e.g. "Looks like you closed out the hiring commitment and made a call on the vendor question today — how did that feel?"), never a generic "how was your day?" that ignores substrate the system already has. If the bundle carries a `degraded_sources` marker, the opening turn is honest about the gap ("I don't have today's captures, but here's what I do have…") rather than pretending completeness.
2. **A small number of reflective questions, with follow-up.** The agent asks a bounded set of open reflective questions (not a fixed script — question selection and follow-up phrasing are LLM-driven, reasoning over the day-context bundle and the owner's prior answers in-session, per the repo's general preference for LLM cognition over keyword heuristics in intent/semantic work). The *count and stopping condition* are deterministic and owner-governed (see point 4), not left to the model to decide unilaterally.
3. **Runs on the existing chat-session surface.** The conversation is a chat session like any other (`app/chat/session_log.py`); no new conversational transport is built. ERE declares `chat.sessions` as `planned` until a normalizing adapter lands, so reflection conversations preserve the future episode-signal seam but are not consumed automatically today. The shipped `SessionLogWriter` guards open, append, and close with `CHAT_SESSION_PERSIST_ACTION` (PR #3486), so reflection sessions inherit the current WriteGuard-gated durability seam directly. Role messages use the versioned `role_message_format: blockquote-v1` framing: each content line is a Markdown blockquote beneath a standalone role marker. This keeps the log human-readable while preserving multiline owner text and marker-shaped literal content exactly for JRNL-03.
4. **Conversation length is owner-controlled.** The owner can stop the conversation at any turn (an explicit "I'm done" action, or simply going quiet past a bounded idle threshold) and still get a usable transcript for JRNL-03 to draft from — the conversation is never forced to a minimum number of exchanged turns before a draft becomes possible. A safety cap on maximum turns exists to bound runaway sessions, but the owner-initiated stop always takes precedence.
5. **Trigger: on-demand plus an optional settings-governed evening nudge.** The primary trigger is explicit owner action (start a reflection session from the companion surface or CLI). An optional evening nudge — a settings-governed time window, declared once per `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md`'s posture (provisional location until the Settings Spine lands, same posture `docs/DAILY_BRIEFING/SCHEDULE_AND_TRIGGER_GENERATION.md` used for its own tunables) — may **offer** to start the conversation, but never auto-starts it: an offer is a tap-to-begin affordance, matching the "offered, never auto-run" discipline `EXPANSION_CONNECT_AND_CREATE.md` §2.2 established for `create.digest`.
6. **Language follows the owner.** The conversation proceeds in whichever of Swedish or English the owner uses in-session (mixed sv/en is expected and already the norm elsewhere in this system); no language selection step is required.

## Concretely

```
$ python -m app.cli journaling reflect --start
Agent: "Looks like you closed the hiring commitment and made the vendor call today — how did that go?"
Owner: "Good, but I'm still unsure about the vendor pricing."
Agent: "What's the piece that's still unsure — the number itself, or whether they'll hold it?"
Owner: "I'm done for tonight."
$ # session closes; transcript persisted; JRNL-03 can now draft from it
```

Evening-nudge offer (never auto-starts):

```
Companion surface, configured evening window: shows a tap-to-begin "Reflect on today?" affordance.
No tap → no conversation starts. A tap starts exactly the same flow as the on-demand trigger.
```

## Why This Matters

An uninformed opening ("how was your day?") forces the owner to do the recall work the system already did for him — the entire value of "an agent that already knows what the day held" collapses if the agent asks as if it doesn't. Forcing a minimum conversation length before any draft is possible would punish the owner for having a short reflective moment, which is precisely the kind of low-cognitive-load, no-forced-interaction posture this whole ideation set is built around. Auto-starting the evening nudge (rather than merely offering it) would put this capability on the same "began deciding the human's day for him" path #1881's proportional-governance tiers exist to prevent.

## Acceptance Criteria

- [ ] AC1: the conversation's opening agent turn is generated from JRNL-01's assembled day-context bundle and references at least one concrete item from it (a commitment, receipt, or capture) rather than a generic prompt. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_conversation_opens_informed_by_day_context`
- [ ] AC2: when the day-context bundle carries a degraded-source marker, the opening turn names the gap honestly rather than presenting a falsely-complete picture. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_opening_names_degraded_context_honestly`
- [ ] AC3: the owner can stop the conversation at any turn (explicit stop action or idle timeout) and the session persists a usable transcript regardless of how many turns were exchanged. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_owner_can_stop_conversation_at_any_turn`
- [ ] AC4 (enforcement): the evening nudge, when its settings-governed window is reached, only ever renders a tap-to-begin offer — no code path on the nudge's own trigger starts a conversation without an explicit owner tap. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_evening_nudge_is_offer_only_never_auto_starts`
- [ ] AC5: the conversation runs on the existing chat-session surface (`app/chat/session_log.py`) with no new conversational transport introduced, and a completed reflection session is discoverable through the same `chat.sessions` read path the ERE stream registry already names. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_reflection_session_uses_existing_chat_surface`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/journaling/test_lead_reflection_conversation.py
pytest -q -m "not pg"
```

## Out of Scope

Assembling the day-context bundle (JRNL-01); drafting the journal entry (JRNL-03); the review surface (JRNL-04); voice input/output (`docs/MIMER_VOICE_LOOP/`'s seam — this task's conversation logic is transport-agnostic by construction so voice can be added later without redesign, but voice is not built here); changing the shipped chat-session WriteGuard contract (PR #3486); a full settings-UI surface for the nudge window or conversation-length tunables (code-level constants until the Settings Spine lands).

## Restart / Durability Posture

**Survives a restart:** every turn already exchanged in the conversation. `app/chat/session_log.py` appends each turn synchronously using the versioned blockquote framing, so a restart mid-conversation loses none of what was already said and a literal line that resembles a role marker cannot be reclassified — this is the load-bearing property behind the cross-task invariant "the owner's spoken reflection is never lost."

**Does NOT survive a restart, and must not be load-bearing:** any in-memory "which reflective question comes next" state, LLM context cache, or in-process conversation-turn counter. On restart, the owner experiences the conversation surface showing the persisted transcript so far; resuming means the agent re-derives its next question fresh from the persisted transcript plus the (re-assembled, JRNL-01) day-context bundle, not from a lost in-memory plan. If the owner does not resume at all, JRNL-03 can still draft from whatever was persisted before the restart — a restart mid-conversation is, at worst, a slightly re-oriented resumption, never a lost reflection.

**Trust consequence if this is not honored:** an owner who shared something meaningful, only to have a process restart erase it because it lived only in memory, would stop trusting the conversation with anything he was not willing to repeat — precisely the failure this posture prevents.

## Related Docs

- `docs/CONVERSATIONAL_JOURNALING/README.md` (capability spec, cross-task invariants, seams)
- `docs/CONVERSATIONAL_JOURNALING/ASSEMBLE_DAY_CONTEXT.md` (the bundle this task opens informed by)
- `app/chat/session_log.py` (existing chat-session surface this task reuses)
- `docs/CANVAS_CHAT_SURFACE/` and PR #3486 — the shipped WriteGuard-gated chat-session durability seam
- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` (declares `chat.sessions` planned — the future adapter seam)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2.2 (the "offered, never auto-run" precedent the evening nudge follows)
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md` (tunables posture for the nudge window / conversation-length default)
- `docs/HUMAN-FLOWS.md` §0 (audio-first / visual-pick posture; text-first day one for this task, voice arrives via `docs/MIMER_VOICE_LOOP/`)

## Related GitHub Issues

One issue: `[Conversational Journaling] lead-reflection-conversation: agent-led evening conversation on the chat-session surface`. `agent:blocked` until JRNL-01 merges.
