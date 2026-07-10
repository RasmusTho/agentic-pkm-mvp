State: Accepted (owner decision, 2026-07-10). Formalizes the Event Horizon decay model: relevance decay as the retrieval consequence of Episode closure. Downstream of ADR-0051 (Episode primitive) and ADR-0054 (Episode Resolution Engine); locks the model *shape* while leaving the decay curve parameters owner-open runtime tuning (RQ3). Implementation home: ERE-06 (#3181, `docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md`).
Doc role: Decision record (ADR)
Authority: Authoritative for what triggers decay, how decay acts on retrieval, and the invariants decay must never touch. It does NOT enact code, schema, or scoring changes — enactment lands via ERE-06 and annotates ADR-0024 at that point, since it adds a rank signal to the served scoring path.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (curve *parameters* are runtime tuning and never require an ADR revision; the model *shape* — closure-triggered, non-destructive, derived — does).
Source of truth: This ADR plus ADR-0051, ADR-0054, ADR-0039, `docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md`, `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`.

# ADR-0058: Event Horizon decay — relevance decay is a derived, reversible retrieval consequence of Episode closure

**Date:** 2026-07-10
**Status:** Accepted (owner decision, 2026-07-10)

---

## Context

ADR-0051 enacted the `Episode` entity and named its load-bearing property: **closure** (§3.6 — temporal structure is minimal, `start`/`end`/`closed`; "closure is the load-bearing property"). Its Consequences section promised the payoff without defining it: *"decay is the retrieval consequence of episode closure (Event Horizon Model), not a TTL."* ADR-0054 gave decay its runtime owner — the Mimer Episode Resolution Engine *"emits closure; retrieval consumes it"* — but explicitly left the decay model owner-open, as did the grounding research (RQ3: the decay curve; RQ2: identity under re-cut).

The intuition to formalize: **value is lost at a triggering event, not as a function of age.** The grocery list becomes worthless the moment the shopping is done — whether that takes an hour or a month. This is Radvansky's working-model flush: crossing an event boundary purges the situation model, and material bound to the flushed situation drops in accessibility while open situations stay hot (the Zeigarnik reinterpretation). A TTL cannot express this; it decays the wrong things (long-lived open concerns) and fails to decay the right ones (short-lived closed errands).

What was missing was the formal middle: *which* closure signals fire, *what* decay does to retrieval mechanically, *how* the artifact↔episode binding mediates it, and *proof* that the model cannot violate the doctrines it sits inside — retrieval-is-candidate (ADR-0039), markdown-canonical/index-disposable, and the low-trust posture. This ADR supplies that middle and records the owner's ruling on it.

## Decision (owner, 2026-07-10)

### 1. Exactly one trigger: the Episode's canonical `closed` state

Decay fires when — and only when — an Episode note's `time.closed` flips true. All other signals (goal completion, five-dimension shift, time-gap, calendar end, human close) are **inputs to the Episode Resolution Engine's closure resolution** (ADR-0054), never independent decay triggers. Retrieval reads exactly one bit per episode.

This keeps the seam clean: the engine owns *deciding* that a situation ended (cognition, multi-stream fusion, gated CrossScopeFlow where applicable); retrieval owns only the *consequence*. Time-gap may be one of the engine's shift detectors, so age can influence *closure*, but age never appears in the retrieval math (§Demarcation).

Closure propagates **downward through nesting, never upward**: closing a parent episode (`the workday`) closes its open children (`the standup within it`); a child closing says nothing about its parent. Re-opening a child re-opens nothing above it.

### 2. Decay acts as rank dampening — never exclusion, never tier demotion

On the served retrieval path, decay is a **multiplicative post-fusion factor** on the combined score:

```
final = combined × decay_factor(artifact)          # combined per ADR-0024 fusion, unchanged
decay_factor ∈ [η_min, 1.0],  η_min > 0 strictly
```

- **Open or unbound → 1.0.** No episode binding, or any open binding, means no dampening at all.
- **All bindings closed → drops to η** at the closure event (a step, not a slope), optionally declining along a tail toward the floor `η_min`, with **reinforcement resets**: post-closure re-access, re-citation, or re-linking restores the factor (the human touching it is evidence it still matters). The step-at-closure is the model; η, the tail shape, and per-scope variation (work vs. creative/RPG vs. private) are the owner-open curve (RQ3).
- **Explicitly rejected:** candidate *exclusion* (a rank heuristic acquiring destructive effect — in a retrieval-mediated system, invisible ≈ deleted) and `memory_state` *tier demotion* (that is MEM/GOV's durable lifecycle; decay is RCA's ephemeral rank signal — closure MAY later feed MEM consolidation, but that is a separate decision, §Owner-open Q4).
- **Direct reference is never dampened.** Lookup by identity (doc_id / uuid / explicit link) bypasses the factor entirely; the dampener applies only to similarity-ranked *discovery*. Asking for a thing by name always finds it at full strength.
- Hits carry their dampening in result metadata (`decay: {factor, closed_episode_refs}`) so every consumer can see *why* a candidate ranked where it did — same honesty posture as the existing provenance/temporal-validity metadata in the capability wrapper.

### 3. The artifact↔episode_ref mediation

`episode_ref` is zero-or-more episode ids, or `unbound` (semantic-dimensions.md). The mediation rule is **MAX over bindings** — an artifact is as hot as its hottest episode:

| Binding state | decay_factor |
| --- | --- |
| `unbound` (no episode_ref — evergreen) | 1.0, structurally immune |
| ≥ 1 referenced episode open | 1.0 |
| All referenced episodes closed | curve value (η → η_min) |
| Referenced episode id no longer resolves (post-recut orphan) | 1.0 + advisory flag — **fail open to visibility**, never fail closed to suppression |

- The grocery list bound to both `weekly-errands` (closed) and `party-planning` (open) stays fully hot until the party is over.
- `episode_ref` means **originated-in**, not about-ness: a retrospective *about* a closed episode originates in a new (writing) episode and does not cool with its subject. Aboutness is an ordinary link; only the origination binding mediates decay.
- **`pending` bindings count as bound** for decay purposes (decided by acceptance, §Owner-open Q2). ADR-0051 §5's opt-out posture (silence is acceptance) plus the non-destructive, reversible nature of a rank signal make this proportionate; a `pending` binding still confers no authority (semantic-dimensions.md). A softened dampener for `pending` remains a permissible future tuning knob, not a model requirement.

### 4. Reversibility: the factor is derived, never stored

The decay factor is **recomputed** — at query/cache-revalidation time — from exactly two canonical inputs: the artifact's `episode_ref` set and the referenced Episode notes' `closed` fields. No dampened score, no "decayed" stamp, no derived state is ever persisted on the artifact or in canonical metadata. Consequently:

- **Re-open** (`closed` flips back false — the trip resumed, the project un-ended): the factor returns to 1.0 on the next read. Nothing to undo, because nothing was written.
- **Re-cut** (split/merge/re-time — RQ2's identity question): the engine re-assigns `episode_ref` bindings; decay follows the *current* binding graph automatically. Under Kim fine-grained identity a re-cut mints new episode identities, so the engine must migrate bindings (or leave a supersession link); until it does, orphaned refs hit the fail-open row above. **Dampening never survives its justification** — if a closed episode is re-cut such that an artifact now belongs to an open one, it re-heats with no ceremony.
- The Episode's `closed` field itself is note-serialized, vault-canonical, human-legible, human-flippable (OD-2). The *entire* decay state of the system is thus visible and editable in markdown.

## Edge cases (model behavior stated)

1. **Evergreen notes without `episode_ref`:** factor 1.0 forever. Decay is *opt-in by binding* — nothing ever decays for merely lacking an episode, and nothing ever decays for being old. This is the anti-TTL property, load-bearing, restated as a rule: **absence of episodic origin is absence of decay.**
2. **Artifacts shared across episodes:** MAX rule (§3). One open binding keeps the artifact fully hot; partial closure is invisible. (A per-binding weighted blend was considered and rejected: it makes the factor depend on *how many* situations something touched, which measures promiscuity, not liveness.)
3. **Identity under re-cut after decay applied:** since nothing was applied *to the artifact* (§4), there is nothing stale to repair on the artifact side. The only failure mode is a dangling episode id, which fails open (visible, flagged, advisory) — mirroring the established posture that missing lineage is advisory, never a gate.
4. **Closed episode, still-open upward goal:** the artifact cools anyway — decided by acceptance (§Owner-open Q3). The model leans on ADR-0051 commitment 5 (episodic → semantic is *transformation/coexistence*): what remains project-relevant from a closed episode should live on in semantic derivatives (notes, decisions), which carry their own liveness; the episodic originals are exactly what *should* cool.
5. **Artifact bound to an episode that never closes** (an abandoned errand nobody ends): stays hot indefinitely — correctly, per the model; staleness of *episodes* is the engine's problem (a time-gap shift is grounds to propose closure), not retrieval's.

## Constraints honored

- **ADR-0039 — retrieval is candidate, not authority: holds.** Decay reorders candidates; it never touches admissibility, authority, scope, or cross-scope permission. Residual tension acknowledged: aggressive dampening has authority-*like* practical effect (what never surfaces effectively doesn't exist). Three guards close it: the strict floor `η_min > 0`, the direct-reference bypass, and per-hit decay metadata. With those, dampening is a visible, escapable suggestion — the definition of a candidate signal.
- **Markdown canonical / index disposable: holds.** The only canonical write in the whole model is the Episode note's own `closed` field — already ADR-0051/OD-2 territory. The factor is derived (§4); rebuilding the index from the vault reproduces identical decay behavior. Proposed fitness-invariant candidate for the registry (not assumed enacted): `closure_decay_is_derived_and_reversible` — no persisted dampened score anywhere; factor reproducible from vault state alone. Companions the already-registered `observation_episode_binding_survives`.
- **Low-trust / non-destructive: holds.** No deletion, no `suppression_state` change (that is GOV's), no `memory_state` mutation (MEM/GOV's), floor > 0, fail-open on ambiguity, reversible by construction. Decay is a proposal about ordering, which is the weakest thing the system can say.
- **Proportional governance:** closure→decay is below WriteGuard for the same reason segmentation is (ADR-0051 §5) — reversible, non-canonical in effect, opt-out. The one canonical act in the chain (writing `closed` into the Episode note) follows whatever posture Episode-note writes already have; this ADR adds no new write path.

## Demarcation

**Against TTL/age-GC:** no age term exists anywhere in the retrieval math. A three-year-old open episode scores 1.0; a one-hour-old closed one is dampened. Age participates only as one *input to the engine's closure proposal* (the time-gap shift detector), upstream of the single trigger bit. Nor is this garbage collection: decay changes ranking, GC changes existence. The event-triggered GC idea (value lost at a triggering event) gains its *trigger primitive* here — closure — but any archive/forget action is separate, future, and GOV-gated; this model performs none of it.

**Against `evidence_role`:** ADR-0051 §3.1 makes `episode_ref` orthogonal to `evidence_role`, and this model preserves it in both directions. The dampener never reads or writes `evidence_role`, `authority_state`, or `suppression_state`. An observation from a closed episode is *exactly* as admissible in reasoning as before closure — it is merely proposed less often. This extends the registered invariant `retrieval_cannot_upgrade_intrinsic_non_evidence` with its mirror: closure-decay cannot *downgrade* evidence either. Decay is about *when the system volunteers something*, never about *what it may prove*.

## Where it hooks in

- **Ontology:** no new entity, no new dimension. The model is a derived interpretation rule over two existing canonical facts (`episode_ref` × Episode `closed`). Documentation wiring: `semantic-dimensions.md` §`episode_ref` points here for the closure consequence, and `RETRIEVAL.md` names the multiplier as decided-not-current future work (both done with this acceptance); the full `RETRIEVAL.md` section and the salience-contract cross-reference land at enactment (ERE-06), when the behavior becomes current reality. Conceptually the model is a "situational, derived, revisable" salience signal — exactly the salience contract's own category.
- **Runtime path (when enacted, not now):** Episode Resolution Engine (Mimer, ADR-0054) resolves closure → Episode note updated (canonical) → served retrieval applies the post-fusion multiplier in `scoped_hybrid_search` at candidate scoring, with episode closure state riding the existing cache-through/generation-token revalidation (KERNEL-05 pattern) so a closure becomes rank-visible within the same bounded-freshness window as any other durable write. Surfaced through the typed capability wrapper as per-hit decay metadata. (The rerank hook was considered as the insertion point and rejected as primary: rerank is off by default; the model should hold on the default path.)
- **Scoring-change governance:** adding the multiplier is the first metadata signal to affect ordering, which ADR-0024/RETRIEVAL.md reserve for a new decision — *this ADR is that record* if accepted; ADR-0024 gets a status annotation, its fusion of the three base signals unchanged.
- **Resurfacing seam** (consequence, not obligation): closure is also a natural "why now" signal for the read-only resurfacing runtime — a *recently* closed episode is a consolidation/review candidate before it cools. Inverted use of the same bit; no new machinery.

## Consequences

- Event-triggered relevance decay stops being a slogan and becomes a checkable model: one trigger bit, one multiplicative rank factor, MAX-over-bindings, derived-never-stored, fail-open.
- The grocery-list behavior falls out: bound to the errand episode, hot while shopping is pending, dampened the moment the engine (or the human) closes the episode, resurrected instantly by re-opening or by direct reference.
- Evergreen knowledge is structurally untouchable by decay — a property the owner can state to himself as a guarantee, not a tuning outcome.
- The capture epic gains a concrete consumer contract for closure emission; the retrieval-quality lane (#2314) gains a specified, bounded rank signal instead of an open-ended "low-trust weights" idea.
- Two invariant candidates go to the registry when enacted: `closure_decay_is_derived_and_reversible` (new) and the downgrade mirror of `retrieval_cannot_upgrade_intrinsic_non_evidence`.

## Owner-open questions (posture after the 2026-07-10 acceptance)

The owner accepted the model **as drafted**, which resolves two of the five drafted defaults into decided posture (items 2 and 3 below); the rest stay genuinely open:

1. **The curve (RQ3) — open, runtime tuning:** η (initial post-closure factor), tail shape (flat step vs. decline to η_min), and per-scope variation (work vs. creative/RPG vs. private). The shape class (step-at-closure + floor + reinforcement resets) is accepted; parameters are named provisional constants tuned after live data (ERE-06 v1 = single step-down factor). Never requires revisiting this ADR.
2. **`pending` bindings — decided by acceptance:** full dampening (§3). A softened-factor variant remains a permissible future tuning knob, not a model change.
3. **Open upward goal — decided by acceptance:** no goal-level softening; episodic→semantic transformation carries live relevance (§Edge cases 4). Revisit only with evidence that consolidation lags hurt in practice — a tuning-level revisit.
4. **MEM coupling — open, separate decision:** whether closure also feeds `memory_state` consolidation transitions is deliberately outside this ADR (GOV/MEM owners).
5. **Re-cut supersession mechanics (RQ2) — open, engine-level:** eager binding migration vs. lazy supersession links; decided inside ERE-07's design space. Affects only how often the fail-open row fires; the retrieval model is indifferent.

## When to revisit

Supersede only if the owner reverses the shape class: makes decay time-based, exclusionary, persisted, or admissibility-touching. Curve tuning, engine thresholds, and the insertion-point detail (post-fusion vs. rerank) never require revisiting this ADR.

## References

- Upstream decisions: [ADR-0051](./ADR-0051-episode-as-ontological-primitive.md) (Episode entity; §3.6 closure; §Consequences decay promise), [ADR-0054](./ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) (engine emits closure; retrieval consumes), [ADR-0039](./ADR-0039-retrieval-result-is-candidate-context-not-authority.md), [ADR-0024](./ADR-0024-retrieval-topology.md) (fusion this model multiplies onto)
- Grounding: [EPISODE_AS_ONTOLOGICAL_PRIMITIVE](../research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md) (RQ1–RQ3; Radvansky Event Horizon Model; Zeigarnik reinterpretation)
- Contracts: [semantic-dimensions](../architecture/semantic-dimensions.md) §`episode_ref`, [SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT](../CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md), [RETRIEVAL](../RETRIEVAL.md), [invariant registry](../testing/invariant-tests.md)
- Implementation home: [EMIT_CLOSURE_AND_DERIVE_DECAY](../EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md) (ERE-06, #3181, blocked on ERE-04/05) — its derived-never-persisted / ranking-only commitments conform to this model; align its slice spec here rather than minting new issues
