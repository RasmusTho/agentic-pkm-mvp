---
name: Emit Closure and Derive Decay
description: Flip time.closed on quiesced episodes, emit episode.closed, and derive (never persist) the retrieval-salience drop + Moment suppression — event-triggered relevance decay goes live
task_id: ERE-06
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: The three jobs (job 3)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-04, ERE-05]
depends_on: [TWO_STREAM_SEGMENTATION_CORE.md, ASSIGN_EPISODE_REF_TO_ARTIFACTS.md]
can_parallelize_with: [Respect Human Re-cut, Gate Cross-Scope Fusion]
---

# Emit Closure and Derive Decay

## Purpose

Closure is the load-bearing property (ADR-0051 commitment 6): when an episode closes, its bound observations drop in retrieval salience — the Event Horizon working-model flush, and the runtime realization of the owner's event-triggered relevance decay model (HEIM-7's declared-but-unbuilt half, on the Mimer side per ADR-0054).

## What This Task Does

1. **Closure detection**: an open episode whose segment window has quiesced (no new in-bounds signals for the time-gap threshold) flips `time.closed: true` on the Episode note (guarded seam, proposal-class edit on a proposed note; on an accepted note it is a low-trust state flip, still no confirm gate — closure is reversible by re-cut). A human re-cut always wins (ERE-07).
2. **Closure event**: emits outbox topic `episode.closed` (payload: `episode_id`, `closed_at`, `scope`, bound-artifact count; `context_dimensions` per SSI-01; idempotency-keyed per house producer rule). The note flip is SoR; the event is plumbing — consumers that miss it self-heal from the projection.
3. **Decay derivation — derived, never persisted** (the salience contract's hard rule):
   - Retrieval: closure-based salience drop computed at retrieval time into `RetrievalSignalPayload.salience` (`app/retrieval/capability.py`) for items whose `episode_ref` points at closed episodes **and whose note-class is episode-near/dampenable per ADR-0058 §2 (amended 2026-07-11) and the ADR-0055/T2 classification (#3131) — exempt classes (accepted decisions, evergreen knowledge notes, project status) always stay at full salience, even when episode-bound**. **v1 decay curve: a single step-down factor** (named constant, provisional pending RQ3/ADR-0051 — curve shape and per-scope variation are research, the plumbing is not). Open episodes stay hot (Zeigarnik): no decay applied.
   - CRE: `Moment` proposals whose basis artifacts bind only to closed episodes are suppressed in the deterministic evaluator (open-loop-pressure drop).
4. **No authority/scope effect**: decay influences ranking only — never trust, scope, evidence_role, or visibility gates ("use salience to influence ranking, not to silently override trust or scope boundaries").

## Concretely

```
$ python -m app.cli episodes tick --json
{"closed": ["ep-..."], "events_emitted": 1}
# retrieval of an artifact bound to the closed episode now carries salience {"episode_closure": {"closed": true, "factor": 0.5}}
# the same artifact re-opened by human re-cut returns to full salience next retrieval — nothing was persisted
```

## Why This Matters

This is the moat mechanic: the grocery list stops surfacing after the shopping is done — by *event*, not TTL. Persisting decay would violate the salience contract and make re-cut irreversible; skipping the projection-derivation path would make decay depend on event delivery instead of SoR.

## Acceptance Criteria

- [ ] AC1: a quiesced open episode flips `closed: true` and emits exactly one idempotent `episode.closed` event; a still-active episode does not close. Verify: `tests/episodes/test_closure.py::test_quiesced_episode_closes_once`
- [ ] AC2 (enforcement): retrieval of an episode-near artifact bound to a closed episode carries the closure-derived salience drop **on the production retrieval path** (`retrieve()` call site); an open-episode artifact carries none, and an artifact of an exempt note-class (ADR-0058 §2 class gate) carries none even when its episodes are closed. Verify: `tests/episodes/test_closure_decay.py::test_closed_episode_binding_derives_salience_drop_at_retrieval`, `tests/episodes/test_closure_decay.py::test_exempt_class_binding_carries_no_salience_drop`
- [ ] AC3: decay is derived-only — no persisted artifact field, bundle field, or index column changes on closure (extends the existing probe posture). Verify: `tests/retrieval/test_salience_signals.py::test_salience_signals_are_derived_not_persisted` (extended with the closure case)
- [ ] AC4: closure never alters `evidence_role`, `authority_state`, scope visibility, or cross-scope decisions. Verify: `tests/episodes/test_closure_decay.py::test_closure_affects_ranking_only`
- [ ] AC5: Moments based solely on closed-episode artifacts are suppressed in the deterministic evaluator; mixed-basis Moments survive. Verify: `tests/relevance/test_episode_closure_suppression.py::test_closed_episode_moments_suppressed`
- [ ] AC6: re-opening (re-cut) restores full salience with no residue — proving nothing was persisted. Verify: `tests/episodes/test_closure_decay.py::test_reopen_restores_salience_no_residue`
- [ ] AC7: the v1 step-down factor is a named, single-sourced constant documented as provisional (RQ3). Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Provisional thresholds (RQ-E1)`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/ tests/retrieval/test_salience_signals.py tests/relevance/
pytest -q -m "not pg"          # full suite: retrieval hot path
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat
```

## Out of Scope

The decay *curve* shape and per-scope variation (RQ3 — research, revisited after live data); Heimdal raw-layer hard retention (delivered, HEIM-7 half untouched); consent-revocation deletion propagation; any deletion at all — decay is ranking, never erasure.

## Restart / Durability Posture

Closure state is vault-durable on the Episode note; the outbox event is at-least-once plumbing. Salience is recomputed per retrieval — restarts lose nothing user-facing.

## Related Docs

- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` (derived-not-persisted; ranking-not-authority)
- `app/retrieval/capability.py::RetrievalSignalPayload`; `app/relevance/evaluator.py` + `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`
- [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md) §Relevance decay = episode closure; `docs/HEIMDAL/CAPABILITY_CHARTER.md` HEIM-7
- [ADR-0058](../adr/ADR-0058-event-horizon-closure-decay.md) (Accepted 2026-07-10) — the normative decay model this slice implements: single closure trigger, post-fusion rank multiplier with floor > 0, MAX over `episode_ref` bindings, direct-reference bypass, fail-open on dangling refs, derived-never-persisted. Where this spec is looser, ADR-0058 wins.

## Related GitHub Issues

One issue: `[Episode Resolution Engine] closure-decay: episode closure emits the event-triggered salience drop`. Blocked until ERE-04/05 merge.
