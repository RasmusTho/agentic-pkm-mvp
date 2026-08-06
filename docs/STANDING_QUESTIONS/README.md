State: Specification directory — FILED (parent #3325; children #3326–#3330 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). System-level source of truth for building Standing Questions, the third of the seven uncaptured closed loops named in `docs/research/yggdrasil-closed-loops-ideation.md`. Grounded in that ideation capture; not itself the grounding research. GitHub issues are execution artifacts; this spec remains the contract.
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory; GitHub issues (#3325–#3330) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Standing Questions — Specification

A durable open-question entity: the owner registers a question once (an architect carrying open
questions for months has nowhere durable to put them today), and the system matches new evidence
against it over time — captures, Knowledge Acquisition Platform (KAP) candidates, new/edited notes —
re-drafting a provenance-cited candidate answer when the evidence changes, and explicitly surfacing
contradictions with the current standing answer rather than silently rewriting it. ASK
(`docs/adr/*` synthesis path) answers only from what exists *now*; this capability adds the temporal
dimension the owner's own workflow already needs.

Classification: **Product/Runtime System work** (new runtime subsystem, composed entirely from
existing machinery — no new architecture). Primary subsystem: **HKA** (owns the Question note and
candidate-answer artifacts as durable-but-provisional Human Knowledge Artifacts). Secondary: **CAO**
(capture-intent classification, evidence association, answer drafting — all LLM cognition behind
deterministic gates), **SIP** (evidence provenance/identity), **GOV** (human-terminal lifecycle,
acceptance authority, candidate/authority discipline), **DRI** (rebuildable projection), **HIX**
(companion UI review surface), **RCA** (evidence assembly through the existing retrieval seam).

## What this capability deliberately does not invent

Every mechanism below is a **reuse**, not new architecture — this spec composes existing contracts
the same way `docs/EPISODE_RESOLUTION_ENGINE/` composes the vault-write seam and outbox, and the
same way `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` composes the retrieval
seam and `CompilationDraft`:

| Existing machinery | Role here |
| --- | --- |
| Guarded knowledge-write seam (`app/knowledge/write_ops.py::guard.assert_writes_allowed`), `WriteReceipt` | every Question-note and evidence-log write (SQ-01/03/04) |
| Note-store + rebuildable-projection pattern (`docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md`, `app/jobs/decisions_projection.py` precedent) | SQ-01's persistence substrate, copied structurally |
| Schema-constrained LLM completion with explicit `UNKNOWN` (`app/components/llm/constrained.py::constrained_completion`, `docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md`) | SQ-02's capture-intent classification and SQ-03's evidence-association judgment — the repo's standing pattern for "LLM cognition, deterministic gate" |
| Create engine (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2, `create.answer_note` kind, `CompilationDraft`, staging, citation validation, in-draft `AI-åtgärder` acceptance checkbox) | SQ-04's candidate-answer drafting, given a new trigger (evidence-delta) instead of explicit-ask |
| Declined-proposal ledger (`EXPANSION_CONNECT_AND_CREATE.md` §3) | SQ-05's dismiss path — a dismissed candidate answer is a decline, not a deletion |
| Panel `AI-åtgärder` checkbox + Companion UI read-mode checkbox-projection acceleration (`docs/PANEL_AGENT.md`) | SQ-05's visual accept/dismiss — a UI click projects the same governed checkbox semantics, never a parallel authority store |
| FRONTMATTER.md human-owned vs. system-owned (bounded) field ownership model | the Question note's write discipline (SQ-01): human owns `text`; system appends bounded fields only |

**External, cross-capability dependency (named once, load-bearing):** SQ-04 needs the Create engine
(EXP-3, `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`) delivered. That spec is
"Advisory until child issues are delivered" as of this writing — **EXP-3 has not merged**. SQ-04 is
fully specifiable now (the trigger, contradiction-surfacing, and partial-failure discipline are this
capability's own contribution), but it cannot be *implemented* before EXP-3 lands. See SQ-04's
Context for how its GitHub issue should actually be labeled despite the uniform drafting convention
used below.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [STORE_QUESTION_NOTES_AND_PROJECTION](STORE_QUESTION_NOTES_AND_PROJECTION.md) | SQ-01 | — |
| 2 | [REGISTER_QUESTIONS_FRICTION_FREE](REGISTER_QUESTIONS_FRICTION_FREE.md) | SQ-02 | SQ-01 (∥ with 3) |
| 3 | [MATCH_EVIDENCE_TO_OPEN_QUESTIONS](MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md) | SQ-03 | SQ-01 (∥ with 2) |
| 4 | [REFRESH_ANSWER_ON_EVIDENCE_DELTA](REFRESH_ANSWER_ON_EVIDENCE_DELTA.md) | SQ-04 | SQ-01, SQ-03 + **external**: EXP-3 (Create engine) merged |
| 5 | [SURFACE_QUESTION_LIST_AND_REVIEW](SURFACE_QUESTION_LIST_AND_REVIEW.md) | SQ-05 | SQ-01, SQ-02, SQ-03, SQ-04 |

Flat order: 1 → 2‖3 → 4 → 5. No task here needs a plan beyond this list; if a future revision cannot
still say it in one flat line, the boundary has grown too large and needs re-cutting.

## Cross-Task Invariants / Interaction Safety

Multiple tasks read or write the same Question-note/evidence/candidate-answer substrate. These
invariants hold *across* tasks, each with its partial-failure walk:

- **INV-SQ-A — Question notes are human-terminal.** The human owns `text` (the question itself) and
  `status`; the engine may only (a) create a note via a governed propose→accept path (SQ-02) or
  (b) append to system-owned bounded fields — the evidence log (SQ-03), the candidate-answer pointer
  (SQ-04). It must never overwrite a human-owned field once written. Partial failure: an engine write
  that would touch a human-owned field is rejected at the guarded seam, logged, and the note is left
  untouched — never a partial overwrite.
- **INV-SQ-B — Evidence links never mutate the evidence artifact.** SQ-03 writes only to the
  question side (the Question note's evidence log + its projection mirror); the source capture, KAP
  candidate, or note is never touched, consistent with SQ-03's own "no writes to the evidence
  artifacts themselves" boundary. Partial failure: the vault-side evidence-log append succeeds but
  the projection update fails (or vice versa) — the vault note is SoR; the next projection rebuild
  reconciles from it. A link recorded on only one side is a detectable drift, never a silent
  duplicate or a lost link.
- **INV-SQ-C — Answers are candidate-class until explicit acceptance; acceptance is the only path to
  `status: answered`.** Partial failure: acceptance is one governed transaction at the seam
  (materialize the accepted answer content **and** flip `status` together); if either half fails the
  whole acceptance is retried, never split — a note must never end up `answered` without a
  materialized answer, nor carry an accepted answer while still `open`.
- **INV-SQ-D — A pending review is never clobbered by a new refresh.** If a candidate-answer draft is
  un-actioned (not yet accepted, dismissed, or expired) when a new evidence delta crosses the refresh
  threshold, the refresh **defers** — evidence keeps accumulating in the log, but no second draft
  is generated until the pending one resolves. Partial failure: the refresh tick crashes after
  detecting "pending exists, defer" but before recording anything — the next tick re-derives pending
  state fresh from the vault (it is never a stored decision), so no evidence is lost and no draft is
  silently replaced. This is the seam SQ-04 exists to walk explicitly.
- **INV-SQ-E — Contradiction is surfaced, never silently resolved.** When a refreshed candidate
  disagrees with the current standing answer, the draft is labeled (`contradicts_standing_answer:
  true` + a quoted basis) before it ever reaches the human; no path may drop the flag or let a
  contradicting draft quietly supersede the standing answer without the explicit accept act. Partial
  failure: the contradiction judgment itself degrades to `UNKNOWN` (schema-validation failure,
  degraded LLM backend) — the refresh never asserts non-contradiction it could not verify; it lands
  on a legible "comparison inconclusive, human should compare" state instead.
- **INV-SQ-F — Matching and refresh act only on `open` questions.** `answered`/`closed` are terminal
  for the engine; a human re-opening a question (editing `status` back to `open`) is the only way to
  resume matching — mirrors the Episode Resolution Engine's human re-cut precedent
  (`docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md`). Partial failure: a match/refresh tick
  reads `open` but the human closes the question mid-tick — the write path re-checks status
  immediately before writing at the guarded seam and drops the write if the question closed in the
  interim; a closed question can never be resurrected by a race.
- **INV-SQ-G — Projection is rebuildable from vault alone.** Question notes plus their system-owned
  evidence/candidate-answer fields are the SoR; the PG projection (open-question list, evidence
  trail, pending-review lookups) rebuilds row-for-row from the vault. Losing the projection loses
  only query speed, never a question, an evidence link, or an answer.

## Provisional thresholds (RQ-SQ1, RQ-SQ2)

Two thresholds are **named, single-sourced constants documented as provisional**, following the
Episode Resolution Engine's own provisional-threshold discipline
(`docs/EPISODE_RESOLUTION_ENGINE/README.md :: Provisional thresholds`):

- **RQ-SQ1 — evidence-delta refresh threshold** (SQ-04): how much new evidence (count and/or
  confidence-weighted) triggers a re-draft. Starting posture: over-triggering is preferred to
  under-triggering — a redundant candidate draft costs one dismiss; a missed contradiction costs
  silently stale knowledge.
- **RQ-SQ2 — evidence-attach confidence threshold** (SQ-03): the deterministic floor the LLM
  association's confidence class must clear to attach a link at all. Starting posture: conservative
  (under-attaching is preferred — a missed link can still be found by a later, stronger-evidence
  pass; a wrongly attached link pollutes the evidence trail a human must then mentally discount).
  **Shipped as** `EVIDENCE_ATTACH_CONFIDENCE_FLOOR` in `app/standing_questions/evidence_matching.py`
  — the single source for this threshold, currently `ConfidenceClass.HIGH`. It is **provisional**:
  nothing else may hard-code an attach cutoff, and retuning it is a one-constant edit.

Both are tuning research resolved after live data accumulates, exactly like RQ-E1/RQ3 in the Episode
Resolution Engine — not a pre-code gate.

## Capability acceptance criteria

- [ ] A registered question survives as a vault-canonical note and appears in the rebuildable
      projection. Verify: `tests/standing_questions/test_question_store.py::test_registered_question_appears_in_projection`
- [ ] End-to-end on a fixture: capture-intent text → classified proposal → accepted → open question →
      matching evidence attaches with provenance → evidence delta crosses threshold → candidate answer
      drafted → human accepts → `status: answered`, all idempotent. Verify:
      `tests/standing_questions/test_capability_end_to_end.py::test_fixture_question_full_loop`
      (lands with SQ-05)
- [ ] Question notes are human-terminal (INV-SQ-A) enforced at the production write seam. Verify:
      `tests/standing_questions/test_question_store.py::test_engine_cannot_overwrite_human_owned_fields`
- [ ] Evidence links never mutate the evidence artifact (INV-SQ-B). Verify:
      `tests/standing_questions/test_evidence_matching.py::test_matching_never_writes_to_source_artifact`
- [ ] Answers are candidate-class until acceptance; acceptance is the only path to `answered`
      (INV-SQ-C). Verify: `tests/standing_questions/test_answer_refresh.py::test_answered_status_requires_acceptance`
- [ ] A pending candidate-answer review is never clobbered by a later refresh (INV-SQ-D). Verify:
      `tests/standing_questions/test_answer_refresh.py::test_pending_review_not_clobbered_by_new_delta`
- [ ] A contradicting refresh is explicitly flagged, never silently applied (INV-SQ-E). Verify:
      `tests/standing_questions/test_answer_refresh.py::test_contradiction_surfaced_not_silently_rewritten`
- [ ] Live validation on the test channel: ≥1 real standing question the operator registers
      accumulates real evidence and produces a legible candidate answer, receipt posted to the parent
      issue. Verify: parent-issue validation receipt (mac mini test channel)
- [ ] Owner-doc promotion only after acceptance: no owner doc currently claims this capability as
      shipped; none needs a "not yet built" line removed until the first task merges (unlike ERE, no
      ADR consequence line references this capability yet). Verify: doc writeback at this README's
      `State:` line, updated from DRAFT to the live parent-issue state once filed

## Out of Scope (capability level)

- **Autonomous web research to answer questions.** The Knowledge Acquisition Platform stays the sole
  acquisition path (`docs/KNOWLEDGE_ACQUISITION/README.md`); Standing Questions matches against
  whatever KAP (and other streams) already produced, it never triggers new external fetches.
- **Auto-accepting answers.** No confidence level, delta size, or elapsed time ever flips
  `status: answered` without the explicit human accept act (INV-SQ-C).
- **Briefing delivery.** A daily/periodic surface that *pushes* open questions, evidence deltas, or
  fresh candidate answers to the owner is a future seam this capability enables but does not build —
  named as the eventual consumer in `docs/DAILY_BRIEFING/` (loop 1 in the ideation capture). Standing
  Questions only builds the pull-based companion UI surface (SQ-05).
- **Question sharing/federation.** Standing Questions are single-scope, single-owner artifacts;
  cross-scope or cross-instance question sharing is out of scope entirely (not merely deferred) and
  would need its own ADR if ever raised, per the repo's standing cross-scope discipline
  (`docs/architecture/cross-scope-flow.md`).

## Relationship to GitHub issues

**Filed 2026-07-07.** Parent feature issue: **#3325** (Backlog, `agent:blocked` live validation hub; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). All five children were filed `agent:blocked`: SQ-01 → **#3329** (the dependency-free head — flips to `agent:ready` once this spec PR merges to `main`); SQ-02 → **#3328** and SQ-03 → **#3326** (both stay `agent:blocked` until SQ-01/#3329 merges); SQ-04 → **#3327** (stays `agent:blocked` until SQ-01/#3329 and SQ-03/#3326 merge, **and** the external Create-engine prerequisite EXP-3 lands); SQ-05 → **#3330** (stays `agent:blocked` until SQ-01/#3329, SQ-02/#3328, SQ-03/#3326, and SQ-04/#3327 all merge). The spec is the source of truth; issues track pickup state.

## Open research carried (not blocking)

RQ-SQ1 (evidence-delta refresh threshold, tuning pass after live data); RQ-SQ2 (evidence-attach
confidence floor, tuning pass after live data); whether `create.answer_note` needs a Standing
Questions-specific sub-kind or can carry the evidence-delta trigger as a bare parameter (SQ-04
implementation choice, not a spec-blocking question).
