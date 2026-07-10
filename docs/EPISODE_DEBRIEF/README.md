State: Specification directory — FILED, BLOCKED (parent #3331; children #3332–#3334 filed 2026-07-07,
all carrying `agent:blocked` pending Episode Resolution Engine core delivery — see
`README.md :: Blocked on Episode Resolution Engine core delivery`).
System-level source of truth for the Episode Debrief capability: when the Episode Resolution Engine
closes an episode, synthesize a provenance-cited debrief note — decisions made, commitments taken, open
loops, key captures — the retro the owner never has time to run. Grounded in
`docs/research/yggdrasil-closed-loops-ideation.md :: 4. Episode debrief`; subordinate to
`docs/EPISODE_RESOLUTION_ENGINE/` (closure is the trigger; scope/re-cut discipline is inherited, never
re-decided here), `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` (the Create engine
this capability's synthesis reuses), and `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (`review_state`
vocabulary this capability conforms to, not forks).
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (ERE prerequisite merges, task merges, parent-issue lifecycle)
Source of truth: this directory + the governing ERE/Create-engine docs; GitHub issues (#3331–#3334) are
execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Episode Debrief — Specification

Episodes (meetings, builds, trips) generate exhaust nobody distills. When the Episode Resolution Engine
closes an episode, this capability synthesizes a provenance-cited debrief — decisions made, commitments
taken, open loops, key captures, each item linked to its source artifact — as a candidate artifact linked
from the Episode note, surfaced in the companion UI for a lightweight accept/dismiss. ERE currently
specifies closure only as a decay trigger (`docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md`);
this capability wires closure to its second consumer.

Classification: **Product/Runtime System work**. Primary subsystem: **HKA** (the debrief is a new,
candidate-class Human Knowledge Artifact); secondary: **SIP** (episode closure/`episode_ref` consumption,
`debrief_ref` cross-reference), **CAO** (Create-engine synthesis orchestration, reused not rebuilt),
**GOV** (WriteGuard-gated writes, review-disposition receipts), **RCA** (retrieval-seam assembly of
decisions/commitments/captures as debrief inputs).

## THE WHOLE CAPABILITY IS BLOCKED ON ERE CORE DELIVERY

Every task below — and the parent feature issue — is blocked and carries (or will carry, once filed)
`agent:blocked`. See **Blocked on Episode Resolution Engine core delivery** below for the exact unblock
condition. Do not flip any issue in this capability to `agent:ready` before that condition is met.

## What this capability consumes from ERE (read-only; nothing here re-decides ERE's contracts)

- `episode.closed` outbox event (ERE-06, `EMIT_CLOSURE_AND_DERIVE_DECAY.md`) — the trigger.
- `episode_ref` bindings on artifacts (ERE-05, `ASSIGN_EPISODE_REF_TO_ARTIFACTS.md`) — what material
  belongs to the episode being debriefed.
- The Episode note schema/store (ERE-02, `EPISODE_NOTE_STORE_AND_PROJECTION.md`) — read for scope/bounds,
  appended to (`debrief_ref` only) by DEBRIEF-02.
- The split-per-scope / flow-gated-fusion discipline (ERE-08, `GATE_CROSS_SCOPE_FUSION.md`) — inherited
  unchanged; this capability never widens scope beyond what the episode itself resolved.
- The engine-never-overwrites-a-human-cut invariant (ERE-07, `RESPECT_HUMAN_RECUT.md`) — extended here to
  cover this capability's own write (the `debrief_ref` append), not just ERE's.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [TRIGGER_DEBRIEF_ON_CLOSURE](TRIGGER_DEBRIEF_ON_CLOSURE.md) | DEBRIEF-01 | ERE-02, ERE-04, ERE-06 (external, blocking) |
| 2 | [SYNTHESIZE_DEBRIEF_NOTE](SYNTHESIZE_DEBRIEF_NOTE.md) | DEBRIEF-02 | DEBRIEF-01 |
| 3 | [SURFACE_DEBRIEF_FOR_REVIEW](SURFACE_DEBRIEF_FOR_REVIEW.md) | DEBRIEF-03 | DEBRIEF-02 |

Flat order: DEBRIEF-01 → DEBRIEF-02 → DEBRIEF-03. Strict chain, no parallelization opportunity — each
task reads the previous task's durable output (trigger → draft → disposition), matching the
`COMMITMENT_SURFACING` precedent for a three-stage read-through pipeline.

## Provisional thresholds

- `EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT` (DEBRIEF-01): minimum in-bounds artifact count for an episode to
  be debrief-eligible. Provisional, named, single-sourced constant (proposed default: 3); documented
  provisional pending real-usage data, eventually governed by the Settings Spine
  (`docs/SETTINGS_SPINE/README.md`) rather than hardcoded permanently — mirrors ERE's own
  provisional-constant pattern (RQ-E1/RQ3). Skipping a debrief for a trivial episode is cheap (nothing
  lost); debriefing every two-artifact episode is noisy.

## Cross-Task Invariants / Interaction Safety

All three tasks read or write the shared episode/debrief substrate; these invariants hold *across* tasks,
with partial-failure walks:

- **INV-DEBRIEF-A — episode bounds and human-owned Episode note content are never mutated.** No task in
  this capability writes `time`, `title`, `goal`, `space`, `protagonists`, `segmentation`/cut, or body on
  an Episode note. The only permitted write to an Episode note anywhere in this capability is DEBRIEF-02's
  additive `debrief_ref` append — the same class of write ERE-05's binding append already is. Partial
  failure: an attempted mutation of a protected field is rejected + logged at the write seam; the note is
  otherwise untouched (extends ERE-07's engine-never-overwrites invariant to this capability's own write).
- **INV-DEBRIEF-B — exactly one debrief per closure, idempotent under at-least-once.** `debrief_id =
  hash(episode_id)` is the identity from DEBRIEF-01 through DEBRIEF-03; redelivery of the closure event,
  a re-run of synthesis, or a repeated review action never produces a duplicate trigger, draft, or
  receipt. Partial failure: DEBRIEF-01 consumes closure but DEBRIEF-02's synthesis crashes before
  completing — the "closed, eligible, undebriefed" condition (derived from the episode projection plus
  debrief-artifact existence, never held only in a queue) remains true, so the next reconciliation tick
  re-attempts cleanly. The trigger is never silently lost; it is recomputed, not remembered in a single
  fragile place.
- **INV-DEBRIEF-C — the scope gate holds through synthesis, unwidened.** A debrief must never fuse across
  scopes the episode itself did not fuse. DEBRIEF-01 passes the episode's own scope through unchanged;
  DEBRIEF-02's context assembly inherits the same `cross_scope_no_flow` denial class ERE-08 established,
  with no separate widening step anywhere in this capability. Partial failure: if DEBRIEF-02 is ever
  invoked with a stale/wrong scope (e.g. an episode re-cut after the trigger fired but before synthesis
  ran), the safe failure mode is to re-derive scope from the current episode note at synthesis time, not
  to trust the trigger's copy blindly — a re-cut episode is re-read, not assumed.
- **INV-DEBRIEF-D — candidate class never silently upgrades to authority.** The debrief note is
  `authority_state: proposal` at creation (DEBRIEF-02) and stays `proposal` through both possible
  dispositions (DEBRIEF-03's accept/dismiss flip only `review_state`, per `STATE_AXES_CONTRACT.md`'s
  core rule that the two axes are distinct). Partial failure: no code path in this capability mints a
  DecisionToken/AuthorityReceipt for a debrief at any stage; if one is ever observed, that is a contract
  violation any invariant probe must fail on, mirroring INV-ERE-B's posture on episode proposals.
- **INV-DEBRIEF-E — dismiss is a status flip, never a deletion.** Unlike EXP-4's `decline_draft` (which
  removes a pre-acceptance Create staging draft — appropriate there because an unaccepted draft has no
  independent durable value yet), a debrief is already a durable candidate artifact by the time DEBRIEF-03
  can act on it. Dismiss flips `review_state: archived`; the file, its content, and its `debrief_ref` link
  from the Episode note persist. Partial failure: if a dismiss receipt is lost (outbox at-least-once), the
  `review_state: archived` frontmatter flip is still the commit point (receipt-before-ack precedent from
  the Decision Receipt Log) — the disposition is never lost even if the receipt is.

If any of these seams could not be given an invariant, the slice boundaries would be wrong. They can; the
boundaries hold.

## Blocked on Episode Resolution Engine core delivery

This entire capability — the parent feature issue and all three children — is blocked. It must not be
filed as (or flipped to) `agent:ready` until the following ERE children merge to `main`:

- **#3177** (ERE-02, `EPISODE_NOTE_STORE_AND_PROJECTION`) — the Episode note schema/store DEBRIEF-01
  reads scope/existence from and DEBRIEF-02 appends `debrief_ref` to.
- **#3179** (ERE-04, `TWO_STREAM_SEGMENTATION_CORE`) — episodes must exist before they can close.
- **#3181** (ERE-06, `EMIT_CLOSURE_AND_DERIVE_DECAY`) — the `episode.closed` event DEBRIEF-01 subscribes
  to.

**Unblock condition**: all three of #3177/#3179/#3181 merged to `main`. Parent #3175 (the ERE capability
validation hub) remaining open is not itself a blocker for this capability — only these three named
children are read/write dependencies here; ERE-01/03/05/07/08/09 are not. Until the condition is met,
every issue filed from this spec (parent **#3331**; children **#3332–#3334**) carries `STATUS: blocked` /
`agent:blocked`; see `PARENT_FEATURE_ISSUE.md` for the live issue numbers.

## Capability acceptance criteria

- [ ] All three tasks compose end-to-end on a fixture: a closed, eligible episode produces exactly one
  trigger, one synthesized candidate debrief (four sourced sections) linked from the Episode note via
  `debrief_ref`, surfaced in the companion UI, and dispositioned (accept or dismiss) with a receipt and
  no deletion. Verify: `tests/episode_debrief/test_capability_end_to_end.py::test_fixture_closure_full_loop`
  (lands with DEBRIEF-03)
- [ ] Episode bounds and human-owned Episode note content are never mutated by any task in this
  capability. Verify: `tests/episode_debrief/test_synthesis.py::test_synthesis_never_mutates_episode_note_content`
- [ ] Exactly one debrief per closure, idempotent under at-least-once redelivery and repeated
  synthesis/review calls. Verify: `tests/episode_debrief/test_trigger.py::test_redelivered_closure_is_idempotent_at_consumer_entrypoint`
- [ ] The debrief never fuses across scopes the episode itself did not fuse. Verify: `tests/episode_debrief/test_synthesis.py::test_synthesis_never_crosses_episode_scope`
- [ ] Dismiss never deletes the artifact. Verify: `tests/episode_debrief/test_review.py::test_dismiss_does_not_delete_artifact`
- [ ] Live validation on the test channel deferred until unblocked — no test-channel receipt is owed
  before #3177/#3179/#3181 merge; once unblocked, one real closed episode's debrief is validated
  end-to-end on the mac mini test channel and the receipt is posted to the parent issue. Verify:
  parent-issue validation receipt (mac mini test channel, post-unblock)

## Relationship to GitHub issues

**Filed 2026-07-07.** Parent feature issue: **#3331** (Backlog, `agent:blocked` live validation hub; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). All three children were filed `agent:blocked`, consistent with the ERE precedent of pre-filing blocked children so the dependency chain is visible in the backlog: DEBRIEF-01 → **#3334** (blocked on ERE core delivery — #3177/#3179/#3181; parent #3175 tracks progress, not itself the blocker); DEBRIEF-02 → **#3333** (blocked on DEBRIEF-01/#3334); DEBRIEF-03 → **#3332** (blocked on DEBRIEF-02/#3333). None of this capability's issues flips to `agent:ready` on this spec PR's merge — the ERE-core unblock condition governs, not the spec-PR-merge convention used by the other closed-loop capabilities. The spec is the source of truth; issues track pickup state.

## Out of Scope (capability level)

Re-cutting or modifying episode bounds (ERE-owned, human-terminal — this capability only reads bounds,
never writes them); debriefs for still-open episodes (closure is the only entry condition); automatic
acceptance (no acceptance-by-silence for debriefs, unlike ERE-07's episode proposals); cross-episode
synthesis (rollups over weeks — future, unscoped); briefing delivery mechanics (the Daily Briefing
capability, `docs/DAILY_BRIEFING/`, is a named future consumer of the review receipts this capability
emits — not specified or built here).

## Open design notes carried (not blocking, not owner decisions requiring a pause)

- `create.episode_debrief` extends the Create engine's closed `OutputKind` enum (DEBRIEF-02) — the fourth
  entry after `overview`/`answer_note`/`digest`. This is a cross-capability contract touch: DEBRIEF-02's
  PR must update `EXPANSION_CONNECT_AND_CREATE.md` §2.1 in the same change, not as a follow-up.
  `synthesis_note_proposal`'s existing activation-gate record is reused unchanged — no new gate record.
- Debrief notes deliberately do not live under `_system/drafts/` (would be subject to EXP-3's expiry
  sweep, which conflicts with "dismissal does not delete"). They get a sibling staging-adjacent location
  (`_system/episode-debriefs/`) with the same ingest-exclusion treatment but no staleness sweep.
- `review_state: archived` is the canonical-vocabulary mapping used for "dismissed" (`STATE_AXES_CONTRACT.md`
  has no `dismissed` value; `archived`'s meaning — "no longer part of the active mutable working set" —
  fits without forking the contract). Flagged here so a reviewer does not mistake it for an invented value.

## Related Docs

- `docs/research/yggdrasil-closed-loops-ideation.md` (grounding capture, all five loops)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md` and its task files (governing spec, exemplar house style)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` (Create engine, reused)
- `docs/DECISION_RECEIPT_LOG/README.md`, `docs/COMMITMENT_SURFACING/README.md` (debrief inputs)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (`review_state` canonical vocabulary)
- `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`
