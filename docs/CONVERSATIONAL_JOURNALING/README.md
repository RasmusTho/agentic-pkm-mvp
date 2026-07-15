State: Specification directory — FILED (parent #3347; children #3348–#3351 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). System-level source of truth for building the Conversational Journaling capability, loop 7 of the five-plus-two Yggdrasil closed loops identified in `docs/research/yggdrasil-closed-loops-ideation.md`. Grounded in that ideation capture; not itself a plan for the other loops. GitHub issues are execution artifacts; this spec remains the contract.
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory + the ideation capture it grounds; GitHub issues (#3347–#3351) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Conversational Journaling — Specification

The runtime capability that turns evening reflection into **a short conversation with an agent ghost-writer that already knows what the day held** — assembled from commitments, decision receipts, and captures — and that drafts the day's journal entry in the owner's own first-person voice for visual, zero-typing review. Owner phrase (2026-07-07): *"a bit of journaling and reflection on the day, in a conversational format with an agent as my ghost writer."*

Classification: **Product/Runtime System work** (new human-facing conversational surface + new durable journal-note artifact class). Primary subsystem: **HIX** (Human Interaction & Intent — this capability *is* the evening reflective touchpoint, symmetric to Daily Briefing's morning one); secondary: **CAO** (the agent-led conversation logic and ghost-writer synthesis cognition), **HKA** (two new vault-durable artifact classes: the conversation transcript and the journal note), **RCA** (day-context assembly from multiple sources, JRNL-01), **GOV** (candidate-class governed write + acceptance receipt, JRNL-03/04).

## Human need this serves

The owner is dyslexic and Swedish/English mixed; every read/type surface works against him, and the classic reflective practice — journaling — has historically meant staring at a blank page. This capability inverts that: the agent leads, the owner talks, the agent writes. It serves the same thin, acknowledged **Reflect** arc stage as its morning sibling (`docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2: "review → recalibrate; learn"), but on the *compounding-learning* half of that stage rather than the day-start orientation half: an evening record, in the owner's own words, of what the day meant to him — not merely what happened in it.

## Capability boundary

**The agent is a ghost writer, not a counselor.** This capability drafts a first-person account in the owner's voice from what he says and what the system already knows; it never offers therapy-style guidance, advice, or interpretation of the owner's emotional state. Stating this plainly is a product boundary, not an incidental scope note.

**The evening bookend to Daily Briefing.** `docs/DAILY_BRIEFING/` is the morning push — one generated, provenance-cited, audio-first touchpoint the owner receives. Conversational Journaling is the evening counterpart: instead of receiving a generated artifact, the owner *participates* in producing one, agent-led. Both serve the same Reflect arc stage; neither depends on the other shipping first. (See Seams below for how the two may compose later.)

**Text-first day one, voice-native by design.** Every surface in this system must work text-first for a dyslexic owner before voice arrives (`docs/HUMAN-FLOWS.md` §0). This capability's conversation is designed so that swapping its input/output transport for the `docs/MIMER_VOICE_LOOP/` voice medium, once that capability ships, requires no redesign of the conversation logic itself — only a transport change. This spec does not build voice.

**Candidate-only, never authority.** The journal note the ghost-writer drafts is a proposal until the owner accepts it (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2 — the Create engine's draft lifecycle is the reused precedent). Once accepted, the entry is human-owned; the engine may never overwrite it, only append a clearly marked addendum candidate for the owner's own later acceptance.

## Day-context inputs (canonical inventory)

| source | status | read path (existing unless noted) | provenance carried |
| --- | --- | --- | --- |
| commitments touched/completed today | **live** (new read shape) | `app/domain/commitments.py` state set via `app/services/commitment_persistence.py::load_commitments`, filtered to today's persisted-artifact change window — a broader read than Daily Briefing's forward-looking `query_next_and_waiting_commitments`, because reflection needs what *changed*, not only what is outstanding | `commitment_id`, `target_ref`, before/after state |
| decision receipts of the day | **live** | `app/receipts/decision_receipt_log.py::iter_decision_receipts`, filtered to today | receipt entry (`object_id`, `vault_uuid`, `key`, `created_at`) |
| captures/observations of the day | **live** (new read shape) | new-today candidate/inbox artifacts written to the vault, e.g. `app/knowledge_acquisition/candidate_writeback.py::write_candidate_note` output filtered to today's creation timestamp | candidate/source note ref |
| chat sessions (the reflection conversation itself) | **live artifact surface; ERE adapter planned** | existing chat-session surface (`app/chat/session_log.py`); ERE does not consume it until the `chat.sessions` adapter lands | `session_id`, transcript ref |
| episode debriefs | **future** (spec'd in `docs/EPISODE_DEBRIEF/`, same wave; delivery blocked on ERE core) | named as a future enrichment seam only — not a dependency | n/a |
| Heimdal screen-stream time-spans | **future** (spec'd in `docs/HEIMDAL_SCREEN_STREAM/`, same wave) | named as a future enrichment seam only — not a dependency | n/a |

A source absent from this table (mood/sentiment analytics, multi-day rollups, auto-publish) is excluded deliberately — see Out of Scope.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [ASSEMBLE_DAY_CONTEXT](ASSEMBLE_DAY_CONTEXT.md) | JRNL-01 | — |
| 2 | [LEAD_REFLECTION_CONVERSATION](LEAD_REFLECTION_CONVERSATION.md) | JRNL-02 | 1 |
| 3 | [DRAFT_JOURNAL_ENTRY](DRAFT_JOURNAL_ENTRY.md) | JRNL-03 | 1, 2 |
| 4 | [REVIEW_ACCEPT_JOURNAL](REVIEW_ACCEPT_JOURNAL.md) | JRNL-04 | 3 |

Flat order: 1 → 2 → 3 → 4. This is a strict dependency chain, not a fan-out: JRNL-02 needs JRNL-01's day-context bundle to open the conversation informed; JRNL-03 needs both JRNL-01's bundle and JRNL-02's transcript to draft; JRNL-04 needs JRNL-03's staged draft to review. No task in this capability can parallelize with another (each `can_parallelize_with: []`), the same posture `COMMITMENT_SURFACING` used for its strict persist → expose → render chain.

## Cross-Task Invariants / Interaction Safety

Multiple tasks read or write the same conversation/journal substrate; these invariants hold *across* tasks, including the partial-failure paths:

- **Journal candidates never overwrite accepted human-owned entries.** Once JRNL-04 promotes a draft to the day's canonical journal note, no later task may mutate that note's body. A second reflection session the same evening (JRNL-02 run again) can only ever produce a *new* draft candidate, never a rewrite of the accepted note; if the day already has an accepted entry, JRNL-03's output for that day is an **addendum candidate**, explicitly labeled as such, requiring its own acceptance to be appended.
- **One-candidate-per-day idempotency.** Before an entry is accepted, JRNL-03 re-running for the same day (a second conversation session, a retried draft after a prior failure) extends or redrafts the *same* staged candidate file — it never forks a second competing draft for one day. After acceptance, idempotency shifts meaning: a further session produces the addendum candidate described above, not a second primary entry.
- **Conversation transcript and journal entry are distinct artifacts with a link between them.** JRNL-02's transcript (the chat session) and JRNL-03's drafted note are never the same file and never collapsed into one. The drafted note carries a resolvable reference back to the session(s) that informed it; the transcript is never silently deleted once a draft or accepted entry exists.
- **Provenance separation survives into the accepted note.** Every accepted journal entry must let a reader (or a future consumer) distinguish the owner's own words (spoken/typed in the conversation) from system-derived context (a commitment summary, a receipt line, a capture title) that informed the draft but was never something the owner said. Flattening both into undifferentiated first-person prose with no way to tell them apart is exactly the failure this invariant exists to prevent — the "voice" is the owner's, but the *sourcing* of every fact folded into that voice must stay auditable.

### Partial-failure seams (walked)

- **Day-context assembly degrades (inside JRNL-01).** One source (commitments, receipts, or captures) fails to read. The bundle is still assembled, with the missing source **explicitly named**, never silently dropped — the same fail-legible discipline `docs/DAILY_BRIEFING/README.md` established for its own composer. JRNL-02 still opens the conversation informed by whatever context did assemble; it must not present a degraded bundle as if it were complete.
- **Conversation happens but draft generation fails (JRNL-02 ↔ JRNL-03).** The transcript is already durable the moment each turn is exchanged (JRNL-02 persists per-turn, independent of what happens downstream). If JRNL-03's draft generation then fails or crashes, nothing is lost: the transcript survives untouched, and the draft step is retried against the same persisted transcript. **The owner's spoken reflection is never lost merely because the ghost-writing step failed after the fact.**
- **Acceptance clicked while the write path is blocked (inside JRNL-04).** The owner checks the accept affordance in the staged draft note; WriteGuard is unhealthy/blocked at the moment of promotion. The checked box itself is durable (it lives in the already-written staging file, on disk, independent of whether promotion succeeds) — **the acceptance intent must not silently vanish**. The review surface must show an honest "accepted, pending materialization" state distinct from both "not yet reviewed" and "fully materialized," and promotion must retry rather than require the owner to re-click.
- **Second session the same evening (any pairing).** Before acceptance: JRNL-02 → JRNL-03 extends/redrafts the same day's staged candidate (never a duplicate). After acceptance: JRNL-02 → JRNL-03 produces a distinctly labeled addendum candidate, which JRNL-04 reviews and accepts (or dismisses) independently of the already-accepted primary entry.

If any of these seams could not be given an invariant, the slice boundaries would be wrong. They can; the boundaries hold.

## Capability acceptance criteria

- [ ] A day-context bundle assembles from commitments touched/completed, decision receipts, and captures of the day, each item carrying a resolvable provenance reference; a partial source failure names the missing source rather than silently thinning the bundle. Verify: `tests/journaling/test_assemble_day_context.py::test_assembles_full_context_with_provenance`, `tests/journaling/test_assemble_day_context.py::test_partial_source_failure_names_missing_source` (JRNL-01)
- [ ] The agent opens the conversation informed by the day-context bundle, asks a small number of reflective questions, follows up on answers, and can be stopped by the owner at any point while still producing a usable transcript. Verify: `tests/journaling/test_lead_reflection_conversation.py::test_conversation_opens_informed_by_day_context`, `tests/journaling/test_lead_reflection_conversation.py::test_owner_can_stop_conversation_at_any_turn` (JRNL-02)
- [ ] A ghost-written journal entry drafts from the conversation plus day context, staged as a candidate-class governed write, one per day, idempotent under a repeated same-day session; every fact folded into the first-person draft carries a distinguishable provenance (owner's words vs. system-derived context). Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_is_idempotent_same_day`, `tests/journaling/test_draft_journal_entry.py::test_draft_preserves_provenance_separation` (JRNL-03)
- [ ] The owner reviews the draft with zero typing required to accept; edit-then-accept and dismiss are both available; acceptance promotes the entry to the day's canonical journal note and produces a receipt; the engine never overwrites an already-accepted entry (a later same-day session only produces a reviewable addendum candidate). Verify: `tests/journaling/test_review_accept_journal.py::test_accept_requires_no_typing`, `tests/journaling/test_review_accept_journal.py::test_engine_cannot_overwrite_accepted_entry` (JRNL-04)
- [ ] Live validation: a real evening conversation produces a transcript, a drafted entry, and an owner-accepted journal note — receipt posted to the parent issue once filed. Verify: parent-issue validation receipt (operator channel)
- [ ] Owner-doc promotion only after acceptance: a writeback naming Conversational Journaling as a delivered capability (candidate target: `docs/HUMAN-FLOWS.md` or `docs/STATUS.md`, decided at promotion time) and a delivered-marker row in `docs/research/yggdrasil-closed-loops-ideation.md`. Verify: doc writeback at the target chosen at promotion time (not pre-decided here)

## Out of Scope (capability level)

- **Voice transport** — the conversation is text-first day one; voice input/output is `docs/MIMER_VOICE_LOOP/`'s seam, named but not built here (see Seams).
- **Auto-publishing without acceptance** — no path in this capability ever writes a drafted entry to the canonical journal location without an explicit owner acceptance action.
- **Mood/sentiment analytics over journal history** — a future capability, not designed, scheduled, or built here.
- **Multi-day/weekly rollups** — a future capability; this spec is strictly one conversation, one day, one entry.
- **Therapy-style guidance** — the agent is a ghost writer, not a counselor. No task in this capability may add advice-giving, emotional interpretation, or clinical framing to the conversation or the draft.
- Episode debrief and Heimdal screen-stream *content* — named as future day-context enrichment seams (see table above and Seams below) but not designed, scheduled, or built by any task in this directory.

## Seams

This capability composes with four sibling capabilities without depending on any of them shipping first:

- **`docs/DAILY_BRIEFING/`** — the morning bookend. Both capabilities serve the Reflect arc stage and share the same "derived-artifact, provenance-cited, candidate/read-only-until-accepted" discipline. Daily Briefing already names future briefing *sections* fed by loops that land later (`docs/DAILY_BRIEFING/README.md :: Capability boundary`); a future morning briefing could similarly surface "last night's accepted journal entry exists" as a new section once both capabilities are live — not designed or built here, named for symmetry only.
- **`docs/MIMER_VOICE_LOOP/`** (directory exists, currently empty — no spec yet) — the voice medium this capability's conversation is designed to accept without a redesign. JRNL-02's conversation logic is transport-agnostic by construction (chat-surface turns in, chat-surface turns out); voice becomes a new transport for the same turns, not a new conversation model. Not built here.
- **`docs/EPISODE_DEBRIEF/`** (does not exist yet, `docs/research/yggdrasil-closed-loops-ideation.md` loop 4) — a future richer "what happened" skeleton (decisions made, commitments taken, open loops, key captures per episode) that could become a day-context input to JRNL-01 once episodes and their debriefs exist, sequenced behind Episode Resolution Engine delivery. Named in the day-context inventory as `future`, not a dependency.
- **`docs/HEIMDAL_SCREEN_STREAM/`** (does not exist yet, ideation loop 6) — the richest future auto-journaling skeleton (screen activity, time-spend) that could pre-populate day context before the conversation even starts. Named as `future` in the day-context inventory, not a dependency; the owner ruling on the screen modality's always-on capture posture is recorded in the ideation capture but does not gate this capability.

**Shipped durability seam:** the chat-session surface JRNL-02 reuses (`app/chat/session_log.py`) routes `open_session`, append, and close through `DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION)` (PR #3486). Reflection-conversation sessions therefore inherit WriteGuard-gated durability without a separate journaling write path.

## Relationship to GitHub issues

**Filed 2026-07-07.** Parent feature issue: **#3347** (Backlog, `agent:blocked` live validation hub; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). All four children were filed `agent:blocked`: JRNL-01 → **#3348** (the dependency-free head — flips to `agent:ready` once this spec PR merges to `main`); JRNL-02 → **#3350** (stays `agent:blocked` until JRNL-01/#3348 merges); JRNL-03 → **#3349** (stays `agent:blocked` until JRNL-01/#3348 and JRNL-02/#3350 merge); JRNL-04 → **#3351** (stays `agent:blocked` until JRNL-03/#3349 merges). The spec is the source of truth; issues track pickup state.

## Related Docs

- `docs/research/yggdrasil-closed-loops-ideation.md` — the grounding capture (all seven loops, priority ranking, loop 7)
- `docs/DAILY_BRIEFING/README.md` — the morning-bookend sibling capability and its fail-legible/provenance precedents this capability reuses
- `docs/DECISION_RECEIPT_LOG/README.md` — decision-receipt log design and reader
- `docs/COMMITMENT_SURFACING/README.md` — commitment domain model, read-only/degrade-honestly precedent, and the strict-dependency-chain breakdown style this capability mirrors
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` — the Create engine draft-lifecycle (staging → acceptance) this capability's governed-write tasks reuse
- `docs/CANVAS_CHAT_SURFACE/` and PR #3486 — the shipped WriteGuard-gated chat-session durability seam JRNL-02 reuses
- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` — declares `chat.sessions` planned until its adapter lands; reflection transcripts preserve that future seam
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md` — the tunables posture the evening-nudge trigger and conversation-length default provisionally follow
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2 — the Reflect arc stage this capability serves
