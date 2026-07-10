State: FILED — the parent feature issue is live as #3347 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3348 (JRNL-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3350 (JRNL-02, blocked until JRNL-01/#3348 merges), #3349 (JRNL-03, blocked until JRNL-01/#3348 and JRNL-02/#3350 merge), #3351 (JRNL-04, blocked until JRNL-03/#3349 merges).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3347; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Conversational Journaling] parent: evening reflection as a conversation, drafted in the owner's voice

Title on GitHub: `[Conversational Journaling] parent: agent-led evening reflection conversation drafts the day's journal entry`

## Context

`docs/research/yggdrasil-closed-loops-ideation.md` (owner-ratified ideation, 2026-07-07) identified seven uncaptured "closed loops" across already-live verticals; Conversational Journaling is loop 7, owner-stated: *"a bit of journaling and reflection on the day, in a conversational format with an agent as my ghost writer."* It is the **evening bookend** to `docs/DAILY_BRIEFING/` (loop 1, the morning push) — buildable early because its enabling substrate (chat sessions, the Create engine's draft-lifecycle machinery, commitments, decision receipts) is already live or already specified; voice and episode/screen-stream enrichment arrive later as named seams, not blockers.

The capability is fully specified in `docs/CONVERSATIONAL_JOURNALING/` (this spec directory is the source of truth; grounding: the ideation capture above).

This parent is the **live validation hub** once filed: children post validation receipts here; it starts `agent:blocked` (not a pickup issue) while children are outstanding, except that JRNL-01 is immediately `agent:ready` (no prerequisites).

## Scope

The capability outcome — not one PR: a deterministic day-context assembler carrying commitments touched/completed, decision receipts, and captures of the day into one provenance-cited bundle with fail-legible degrade (JRNL-01); an agent-led reflective conversation on the existing chat-session surface that opens informed, asks and follows up, and can be stopped by the owner at any turn (JRNL-02); a ghost-written, candidate-class, provenance-separated journal draft assembled from the conversation plus day context, one per day, idempotent under repeated sessions (JRNL-03); and a zero-typing visual review surface (accept / edit-then-accept / dismiss) that promotes an accepted draft to the canonical journal note and never overwrites it thereafter (JRNL-04).

## Source Anchors

- `docs/CONVERSATIONAL_JOURNALING/README.md` (spec: day-context inventory, tasks, cross-task invariants, capability ACs, seams)
- `docs/research/yggdrasil-closed-loops-ideation.md` (grounding ideation capture, loop 7)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2 (the Create engine draft-lifecycle this capability's governed-write tasks reuse)
- `docs/DAILY_BRIEFING/README.md` (the morning-bookend sibling this capability is symmetric with)

## SBS Impact

- Primary subsystem: HIX (Human Interaction & Intent — the capability *is* the evening reflective touchpoint, symmetric to Daily Briefing's morning one)
- Secondary subsystem(s): CAO (agent-led conversation logic + ghost-writer synthesis cognition), HKA (two new vault-durable artifact classes: conversation transcript, journal note), RCA (day-context assembly from multiple sources), GOV (candidate-class governed write + acceptance receipt)
- Write class: **mixed** — day-context assembly is read-only/derived (JRNL-01); the staged draft is mechanical durable via a guarded seam, candidate/proposal class (JRNL-03); acceptance materialization is a governed write that becomes human-owned but carries no DecisionToken/AuthorityReceipt of its own beyond the acceptance receipt (JRNL-04, same tier as Create's EXP-4 "additive new note, Git-reversible, human already disposed")
- Authority impact: none beyond existing contracts — a staged draft is never authority; acceptance makes the note human-owned, not machine-citable-as-settled-authority (mirrors EXPANSION_CONNECT_AND_CREATE §2.3's post-acceptance review-state posture)
- Persistence impact: new vault note class (journal entries, one per day) plus reuse of the existing chat-session artifact class for the conversation transcript; no new DB table
- Derived/rebuildable impact: the day-context bundle is fully derived (every fact traces to an already-durable source); the staged draft is regenerable pre-acceptance; the accepted journal note becomes human-owned and is no longer machine-regenerable without becoming a new addendum
- Human knowledge impact: the accepted journal entry is new human-authored-in-substance knowledge (the owner's own reflection, ghost-written) — the first capability in this ideation set whose accepted artifact is primarily the owner's voice, not a system-derived summary
- Memory impact: none — no MEM promotion, no change to recall/decay semantics
- Retrieval/context impact: none beyond the existing chat-session stream registration (`chat.sessions`, ERE-01); reflection conversations become episode signal for free once ERE lands, unchanged by this capability
- Sync/deployment impact: none beyond new note families riding existing vault sync (iCloud/git); no migration
- External boundary impact: none new; the chat-session surface this capability reuses is local
- New or changed contract: no new domain contract; reuses the existing candidate-draft frontmatter convention (`derived_by`/`authority_state`/`sources`, `docs/FRONTMATTER.md`) with a new `derived_by: conversation` value, and the existing Panel `AI-åtgärder` in-note checkbox acceptance convention
- Owner-doc impact: on acceptance — a writeback naming Conversational Journaling delivered (target doc decided at promotion time) and a delivered-marker row in the ideation capture
- Transition debt impact: reduces (fills the "no reflective conversation surface, no ghost-written journal artifact" gap the ideation capture names)
- Fitness rule impact: no new fitness rule; reuses the existing WriteGuard-at-seam, candidate-only, and never-overwrite-human-owned-note precedents from `EXPANSION_CONNECT_AND_CREATE`'s invariant registry candidates

## Constraints

The agent is a ghost writer, not a counselor — no task may add advice-giving or emotional interpretation. No task writes a drafted entry to the canonical journal location without explicit owner acceptance. WriteGuard is asserted at every vault-write seam this capability introduces (staging write JRNL-03, promotion write JRNL-04). The engine never mutates an already-accepted journal note — only a distinctly labeled addendum candidate may be proposed against it. No voice transport is built here (`docs/MIMER_VOICE_LOOP/`'s seam). Conversation length is owner-controlled; no task may force a minimum number of turns before a draft can be produced.

## Acceptance Criteria

The capability-level ACs in `docs/CONVERSATIONAL_JOURNALING/README.md :: Capability acceptance criteria`, each with its `Verify:` target there — including fail-legible day-context assembly, an owner-stoppable informed conversation, an idempotent provenance-separated draft, a zero-typing accept/edit/dismiss review surface with the never-overwrite invariant enforced, and a real-evening live validation receipt.

## Implementation Tasks

`docs/CONVERSATIONAL_JOURNALING/` — JRNL-01..04 per the README execution order: 1 → 2 → 3 → 4 (strict chain, no parallelization).

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`). JRNL-01/03 touch the vault-write hot path and run the full `not pg` suite; JRNL-02 is chat-surface/LLM-conversation-adjacent and runs the chat + journaling suites; JRNL-04 is companion-UI-adjacent and runs the companion-UI + journaling invariant suites.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, a sample assembled context / transcript / draft / accepted entry as applicable). After JRNL-04: an operator UAT — a real evening conversation produced, drafted, and accepted as a real journal note, with provenance intact and the never-overwrite invariant confirmed on a second same-day session. Acceptance → one owner-doc promotion PR (target doc decided at promotion time, per the capability README) and parent closure.

## Out of Scope

Voice transport (`docs/MIMER_VOICE_LOOP/`'s seam); auto-publishing without acceptance; mood/sentiment analytics over journal history; multi-day/weekly rollups; therapy-style guidance; episode-debrief and Heimdal screen-stream *content* (named as future day-context enrichment seams only, not designed here); any change to the Create engine's own closed output-kind enum (this capability reuses the shared draft-frontmatter convention directly rather than editing `EXPANSION_CONNECT_AND_CREATE.md`'s enum).

## Suggested Validation

`pytest -q -m "not pg" tests/journaling/` per child; `pytest -q tests/companion_ui -k journal`; a manual one-evening operator UAT (converse → draft → accept → confirm never-overwrite on a second session) posted as a receipt to this issue.

## Source Docs

`docs/CONVERSATIONAL_JOURNALING/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`; `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`; `docs/DAILY_BRIEFING/README.md`.
