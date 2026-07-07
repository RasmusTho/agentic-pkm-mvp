State: FILED — the parent feature issue is live as #3175 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the local pointer + drafted body. Children: #3176 (ERE-01, ready), #3177 (ERE-02, ready, Tier 3 migration), #3178 (ERE-03, ready), #3179–#3183 (ERE-04..08, blocked on prerequisites), #3184 (ERE-09, blocked). ERE-10 has no issue by design.
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue once filed; this file is the draft + local pointer
Last reviewed: 2026-07-07

# [Episode Resolution Engine] parent: streams → episodes → episode_ref → closure-driven decay

Title on GitHub: `[Episode Resolution Engine] parent: segment registered streams into Episodes, assign episode_ref, emit closure-driven decay`

## Context

ADR-0051 enacted the `Episode` entity and `episode_ref` dimension; ADR-0054 placed the runtime organ in Mimer with Heimdal contributing single-stream boundary hints. The engine is fully specified in `docs/EPISODE_RESOLUTION_ENGINE/` (this spec directory is the source of truth; grounding: `docs/research/EPISODE_RESOLUTION_ENGINE.md`). The owner additionally requires every input source identified and architecturally classified — realized as the first-class stream registry (ERE-01) whose canonical inventory lives in the spec README.

This parent is the **live validation hub**: children post validation receipts here; it is `agent:blocked` (not a pickup issue) while children are outstanding.

## Scope

The capability outcome — not one PR: registered-stream consumption, five-dimension segmentation into proposed Episode notes, pending `episode_ref` assignment, human re-cut respected, closure emitting derived (never persisted) salience decay, split-per-scope with flow-gated fusion, calendar as the third stream. Location and further modalities are declared future posture (ERE-10).

## Source Anchors

- `docs/EPISODE_RESOLUTION_ENGINE/README.md` (spec: tasks, inventory, cross-task invariants, capability ACs)
- `docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md`; `docs/adr/ADR-0051-episode-as-ontological-primitive.md`
- `docs/architecture/semantic-dimensions.md :: episode_ref`; `docs/testing/invariant-tests.md :: observation_episode_binding_survives`

## SBS Impact

- Primary subsystem: SIP (owns `episode_ref`; situation identity/provenance)
- Secondary subsystem(s): HKA (Episode notes), RCA/MEM (closure decay honored), GOV (CrossScopeFlow), DRI (projection)
- Write class: mixed — mechanical durable via guarded seam (episode notes, proposal class); derived-rebuildable (projection); authority-bearing only at the flow-gated fuse (receipted)
- Authority impact: none beyond existing contracts — `pending` is not authority; closure never touches evidence_role/authority_state
- Persistence impact: new vault note class (episodes), new rebuildable PG projection, new outbox topic `episode.closed`
- Derived/rebuildable impact: projection rebuilds from vault; salience decay derived at retrieval, never persisted
- Human knowledge impact: Episode notes are human-legible Artifacts; re-cut is a note edit
- Memory impact: MEM honors episode_ref per doctrine; no memory-promotion change
- Retrieval/context impact: closure-derived salience drop + Moment suppression; ranking only
- Sync/deployment impact: one Alembic migration (ERE-02, Tier 3 child); tick integration
- External boundary impact: read-only CalDAV/ICS (ERE-09), credentials in private-bindings
- New or changed contract: signal contract + stream registry (ERE-01); episode-note schema (ERE-02); metadata-bundle `episode_ref` field (ERE-03)
- Owner-doc impact: on acceptance — invariant registry flip, semantic-dimensions TBD line, ADR-0054 consequences line
- Transition debt impact: reduces (fills the `future_runtime` invariant + the "engine has no issues" gap)
- Fitness rule impact: strengthens — `observation_episode_binding_survives` becomes enforced; cross-scope probes extended

## Constraints

Heimdal untouched (per-session `episode_id` consumed as-is; HEIM-2/4/5 preserved). Proposal class bypasses no health gate (WriteGuard asserted at every vault-write seam). Salience never persisted. No `session` primitive. "Event" stays reserved for plumbing. Cross-scope: deny-by-default.

## Acceptance Criteria

The capability-level ACs in `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Capability acceptance criteria`, each with its `Verify:` target there — including the end-to-end fixture-day loop, the enforced binding-survival invariant, the no-unflowed-cross-scope probe, machine-terminal re-cut, and a real-day live validation receipt from the test channel posted to this issue.

## Implementation Tasks

`docs/EPISODE_RESOLUTION_ENGINE/` — ERE-01..ERE-10 per the README execution order: 1‖2‖3 → 4 → 5 → 6‖7‖8 → 9 (10 = declared posture, no issue yet).

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`); hot-path children run the full `not pg` suite + opt-in integrated-runtime UAT; pg-marked probes run on the mac mini test channel.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, tick output). After ERE-06: run the fixture-day end-to-end. After ERE-09: the real-day live validation on the test channel. Acceptance → one owner-doc promotion PR (registry flip + ADR-0054 consequences + semantic-dimensions line) and parent closure; RQ-E1/RQ3 tuning spins off as follow-up issues informed by live data.

## Out of Scope

Decay-curve research (RQ3), threshold tuning (RQ-E1) beyond provisional constants; Heimdal v2 modalities (location/screen/biometric/ambient); Posture B; any bespoke re-cut UI; consent-revocation propagation; deletion of any kind.

## Suggested Validation

`pytest -q -m "not pg"` per child; `pytest -q -m pg tests/episodes/` on the test channel; `python -m app.cli episodes tick --json` against the Bifrost test vault; receipts to this issue.

## Source Docs

`docs/EPISODE_RESOLUTION_ENGINE/README.md`; `docs/research/EPISODE_RESOLUTION_ENGINE.md`; ADR-0051; ADR-0054.
