State: FILED — the parent feature issue is live as #3325 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3329 (SQ-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3328 (SQ-02, blocked until SQ-01/#3329 merges), #3326 (SQ-03, blocked until SQ-01/#3329 merges), #3327 (SQ-04, blocked until SQ-01/#3329 and SQ-03/#3326 merge, plus the external Create-engine EXP-3 prerequisite), #3330 (SQ-05, blocked until SQ-01/#3329, SQ-02/#3328, SQ-03/#3326, and SQ-04/#3327 all merge).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3325; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Standing Questions] parent: register once → match evidence over time → candidate answer → human acceptance

Title on GitHub: `[Standing Questions] parent: durable open-question entity with temporal evidence matching and candidate re-answering`

## Context

`docs/research/yggdrasil-closed-loops-ideation.md` (owner-ratified ideation, 2026-07-07) names Standing
Questions as loop 3 of five uncaptured closed loops: an architect carries open questions for months;
ASK only answers from what exists *now*; the Knowledge Acquisition Platform deliberately ends at
`candidate` (`docs/KNOWLEDGE_ACQUISITION/README.md`) with no durable open-question entity to match its
output against over time. This capability is fully specified in `docs/STANDING_QUESTIONS/` (this spec
directory is the source of truth); it composes entirely existing machinery — the guarded vault-write
seam, the note-store+projection pattern proven by the Episode Resolution Engine
(`docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md`), schema-constrained LLM
classification with explicit `UNKNOWN`
(`docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md`), and the Create engine's
candidate-answer drafting (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`).

This parent is the **live validation hub** once children start merging: each child posts a validation
receipt here; it stays `agent:blocked` (not a pickup issue) while children are outstanding.

**Named external dependency:** SQ-04 (candidate-answer refresh) needs the Create engine (EXP-3) merged.
EXP-3 is advisory/undelivered as of this writing. SQ-01/02/03/05 do not depend on it.

## Scope

The capability outcome — not one PR: vault-canonical Question notes with a rebuildable projection
(SQ-01); friction-free registration via capture-intent classification and explicit companion-UI
registration (SQ-02); LLM-associated, provenance-cited evidence matching against open questions with a
deterministic attach threshold (SQ-03); threshold-triggered candidate-answer re-drafting that
explicitly surfaces contradictions with the standing answer and never clobbers a pending review
(SQ-04); a companion UI surface for the open-question list, per-question evidence trail, and
visual accept/dismiss review (SQ-05).

## Source Anchors

- `docs/STANDING_QUESTIONS/README.md` (spec: tasks, cross-task invariants, capability ACs)
- `docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions`
- `docs/KNOWLEDGE_ACQUISITION/README.md` (the acquisition path this capability matches against, ends
  at candidate, never re-triggered by Standing Questions)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` (the Create engine SQ-04 reuses)

## SBS Impact

- Primary subsystem: HKA (Question notes + candidate-answer artifacts, durable-but-provisional)
- Secondary subsystem(s): CAO (capture-intent classification, evidence association, answer drafting
  — all LLM cognition behind deterministic gates), SIP (evidence provenance/identity), GOV
  (human-terminal lifecycle, acceptance authority), DRI (projection), HIX (companion UI review
  surface), RCA (evidence assembly through the existing retrieval seam)
- Write class: mixed — proposal class at the propose seams (question-registration proposal, evidence
  links, candidate-answer drafts); authority-bearing only at explicit human acceptance (governed
  materialization + status flip)
- Authority impact: none beyond existing contracts — a `pending`/candidate artifact carries no
  authority; only the accept act does
- Persistence impact: new vault note class (Question notes + staged candidate-answer drafts, the
  latter reusing Create's existing staging area), new rebuildable PG projection
- Derived/rebuildable impact: projection rebuilds from vault; nothing here is the only copy of meaning
- Human knowledge impact: Question notes and accepted answers are human-legible Artifacts the human
  can read/edit directly in Obsidian; registering, closing, and accepting are all note-level or
  one-click acts
- Memory impact: none — this capability does not touch MEM promotion semantics
- Retrieval/context impact: evidence assembly for drafting reuses the existing retrieval capability
  seam (scope prefilter + evidence-role clamp intact); no new retrieval mechanism
- Sync/deployment impact: at least one Alembic migration (SQ-01, Tier 3 child)
- External boundary impact: none — no new external egress; matches only against already-acquired
  streams
- New or changed contract: Question-note schema (SQ-01); capture-intent classification schema (SQ-02);
  evidence-association schema (SQ-03); contradiction-flag extension to the candidate-answer draft
  frontmatter (SQ-04)
- Owner-doc impact: none until first task merges — no current owner doc claims this capability exists
- Transition debt impact: reduces (fills the "ASK has no temporal/standing-question dimension" gap
  named in the ideation capture)
- Fitness rule impact: strengthens — candidates for new invariant-registry entries: human-terminal
  Question-note ownership, candidate-answer-requires-acceptance, pending-review-not-clobbered

## Constraints

Question notes are human-owned by default (registration is the human's or a confirmed proposal's
act); the engine only appends to system-owned bounded fields thereafter, never rewrites `text` or
`status`. No auto-acceptance under any threshold, ever. No new authority path, no new promotion
ladder, no new memory-promotion rule. KAP stays the only acquisition path — this capability never
initiates external fetches. Cross-scope: Standing Questions are single-scope by construction (no
cross-scope sharing/federation — out of scope entirely, not deferred).

## Acceptance Criteria

The capability-level ACs in `docs/STANDING_QUESTIONS/README.md :: Capability acceptance criteria`,
each with its `Verify:` target there — including the end-to-end fixture loop, the human-terminal
Question-note invariant, the no-writes-to-evidence-artifacts invariant, the
acceptance-is-the-only-path-to-answered invariant, the pending-review-not-clobbered invariant, the
contradiction-surfaced invariant, and a real-question live validation receipt from the test channel
posted to this issue.

## Implementation Tasks

`docs/STANDING_QUESTIONS/` — SQ-01..SQ-05 per the README execution order: 1 → 2‖3 → 4 → 5. SQ-04
additionally blocks on the external Create engine (EXP-3) dependency named in Context/Scope.

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`); the capture-
intent and evidence-association classifiers run through the schema-constrained-completion gate
(`app/components/llm/constrained.py`) so their `UNKNOWN`/degrade paths are fuzz-tested the same way
`docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md` requires; pg-marked probes
(projection rebuild, migration) run on the mac mini test channel.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, tick output). After SQ-03:
run a fixture evidence-matching pass against a seeded open question. After SQ-04/SQ-05: run the
fixture-question end-to-end (register → match → refresh → accept). Then: the real-day live
validation — the operator registers ≥1 real standing question on the test channel and lets it
accumulate real evidence — receipt posted here. Acceptance → parent closure; RQ-SQ1/RQ-SQ2 tuning
spins off as follow-up issues informed by live data. No owner-doc promotion PR is needed at capability
acceptance unless a currently-shipped-truth doc would otherwise misstate this capability as absent
(none identified at spec time).

## Out of Scope

Autonomous web research to answer questions (KAP stays the acquisition path); auto-accepting answers
under any threshold; briefing delivery (future seam, named for `docs/DAILY_BRIEFING/`); question
sharing/federation (out of scope entirely, would need its own ADR).

## Suggested Validation

`pytest -q -m "not pg"` per child; `pytest -q -m pg tests/standing_questions/` on the test channel;
`python -m app.cli questions tick --json` against the Bifrost test vault; receipts to this issue.

## Source Docs

`docs/STANDING_QUESTIONS/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`;
`docs/KNOWLEDGE_ACQUISITION/README.md`; `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`.
