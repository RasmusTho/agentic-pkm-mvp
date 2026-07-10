State: FILED — the parent feature issue is live as #3314 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3315 (BRIEF-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3318 (BRIEF-02, blocked until BRIEF-01/#3315 merges), #3317 (BRIEF-03, blocked until BRIEF-01/#3315 merges), #3319 (BRIEF-04, blocked until BRIEF-01/#3315 merges), #3316 (BRIEF-05, blocked until BRIEF-01/#3315 merges and the external ERE-09/#3184 + ERE-02/#3177 prerequisites land).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3314; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Daily Briefing] parent: compose, schedule, speak, and surface one day-start briefing artifact

Title on GitHub: `[Daily Briefing] parent: one generated, provenance-cited, audio-first day-start briefing`

## Context

`docs/research/yggdrasil-closed-loops-ideation.md` (owner-ratified ideation, 2026-07-07) identified five uncaptured "closed loops" across already-live verticals; Daily Briefing is loop 1 and the owner-ratified **build-first** priority — highest value-to-effort on substrate that is already live (commitments surfacing, the Contextual Relevance Engine, the decision-receipt log, mixed sv/en TTS) and it becomes the distribution surface the other four loops deliver through as they land.

This capability also implements the **egress seam the Episode Resolution Engine deliberately excluded**: ADR-0054 and `docs/EPISODE_RESOLUTION_ENGINE/README.md` place notifications/TTS playback outside the ERE boundary on purpose. Daily Briefing is the other side of that seam — it is the first thing that actually reads and speaks derived signal to the human, not the engine that produces the signal.

The capability is fully specified in `docs/DAILY_BRIEFING/` (this spec directory is the source of truth; grounding: the ideation capture above).

This parent is the **live validation hub** once filed: children post validation receipts here; it starts `agent:blocked` (not a pickup issue) while children are outstanding, except that BRIEF-01 is immediately `agent:ready` (no prerequisites).

## Scope

The capability outcome — not one PR: a deterministic composer assembling commitments, CRE picks, and decision receipts into one provenance-cited briefing note written through the governed vault-write path (BRIEF-01); a once-per-day scheduled trigger with an on-first-contact-of-day fallback (BRIEF-02); mixed sv/en per-segment audio rendering via the existing SpeechPlan/TTS pipeline with one-tap listen (BRIEF-03); a companion-UI day-start card surfacing listen + read with zero typing (BRIEF-04); and, once the Episode Resolution Engine's calendar stream lands, a today's-calendar/episodes section (BRIEF-05, blocked on an external prerequisite: ERE-09 / GitHub #3184, and ERE-02).

## Source Anchors

- `docs/DAILY_BRIEFING/README.md` (spec: sources consumed, tasks, cross-task invariants, capability ACs)
- `docs/research/yggdrasil-closed-loops-ideation.md` (grounding ideation capture, loop 1)
- `docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md` (the egress exclusion this capability implements the other side of)
- `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md` (BRIEF-05's external blocking prerequisite)

## SBS Impact

- Primary subsystem: HIX (Human Interaction & Intent — the capability *is* the daily human-facing touchpoint/distribution channel)
- Secondary subsystem(s): RCA (composes context/evidence from multiple sources into one bundle), HKA (new vault-durable note class), GOV (decision receipts consumed as-is, no new authority), EBF (local TTS engine invocation), DRI (future: reads the ERE calendar/episode projection once BRIEF-05 unblocks)
- Write class: **derived** — the briefing note is generated/regenerable content; it never becomes authority-bearing and never overwrites a human-owned note
- Authority impact: none — the briefing carries no DecisionToken/AuthorityReceipt at any point; it is a read-only distribution surface end to end
- Persistence impact: new dated vault note class (`<system_dir>/briefings/YYYY-MM-DD.md`), one file per day, WriteGuard-gated; no new DB table, no projection
- Derived/rebuildable impact: fully derived — every fact traces back to an already-durable source; the briefing itself can be deleted or regenerated without losing any human-authored or human-accepted knowledge
- Human knowledge impact: none created; the briefing surfaces existing human-relevant state, it does not become a new human-knowledge authority
- Memory impact: none — no MEM promotion, no change to recall/decay semantics
- Retrieval/context impact: none beyond consuming CRE's existing read-only Moment projection
- Sync/deployment impact: none beyond a new note family riding existing vault sync (iCloud/git); no migration
- External boundary impact: local TTS engines only (already-provisioned Piper/Kokoro, `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`); BRIEF-05's calendar section inherits ERE-09's existing read-only CalDAV/ICS boundary, unchanged by this capability
- New or changed contract: one new vault note family (daily briefing note, companion-note-family pattern); no new domain contract
- Owner-doc impact: on acceptance — a writeback naming Daily Briefing delivered (target doc decided at promotion time) and a delivered-marker row in the ideation capture
- Transition debt impact: reduces (fills the "no distribution surface for Reflect-stage substrate" gap the ideation capture names)
- Fitness rule impact: no new fitness rule; reuses the existing WriteGuard-at-seam and read-only-projection precedents

## Constraints

The briefing is never a write-authority surface — no task in this capability may add a transition/mutation affordance for a commitment, decision receipt, or (future) episode from the briefing itself. WriteGuard is asserted at every vault-write seam this capability introduces (the briefing-note write in BRIEF-01). No OS push, no email, no wake-word/always-listening (out of scope, named explicitly in the spec). Salience/relevance semantics from CRE are consumed as-is, never recomputed here. Decision receipts are read via the existing `iter_decision_receipts` reader, never re-derived.

## Acceptance Criteria

The capability-level ACs in `docs/DAILY_BRIEFING/README.md :: Capability acceptance criteria`, each with its `Verify:` target there — including full-source composition with provenance, fail-legible partial generation, once-per-day idempotent triggering with a first-contact fallback, mixed-language one-tap audio with text-only degrade, a zero-typing day-start card that honestly distinguishes not-yet-generated from degraded from full, the blocked calendar/episodes section, and a real-day live validation receipt.

## Implementation Tasks

`docs/DAILY_BRIEFING/` — BRIEF-01..05 per the README execution order: 1 → {2, 3, 4 in parallel} → 5 (5 additionally blocked on the external ERE-09/ERE-02 prerequisite).

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`). BRIEF-01/02 touch the vault-write and watcher-tick hot paths and run the full `not pg` suite; BRIEF-03/04 are companion-UI/TTS-adjacent and run the companion-UI + TTS suites; BRIEF-05 runs the episode-adjacent test suite once unblocked.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, a sample generated briefing). After BRIEF-04: an operator UAT — a real day's briefing generated, heard via one tap, and seen as one card. After BRIEF-05 unblocks and merges: confirm the calendar/episodes section renders against a real CalDAV day. Acceptance → one owner-doc promotion PR (target doc decided at promotion time, per the capability README) and parent closure.

## Out of Scope

OS push notifications; email delivery; wake-word/always-listening; briefing as a write-authority surface; decision-revisit, standing-question, and episode-debrief *content* (named as future input seams only, not designed here); any change to the ERE calendar adapter or episode engine themselves (BRIEF-05 only reads their existing interfaces).

## Suggested Validation

`pytest -q -m "not pg" tests/briefing/` per child; `pytest -q tests/companion_ui/test_briefing_listen_affordance.py tests/companion_ui/test_day_start_card.py`; a manual one-day operator UAT (generate → listen → read) posted as a receipt to this issue.

## Source Docs

`docs/DAILY_BRIEFING/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`; `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md`.
