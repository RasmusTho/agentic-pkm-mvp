State: Concept contract (forward line; not yet shipped) — defines the adaptive relevance evaluator for the Contextual Relevance Engine (CRE-02, part 1 of 2).
Doc role: Core SoT (relevance evaluator)
Authority: Canonical definition of the relevance evaluator — the *adaptive cognition* half of the engine that, given the context model, **produces** candidate moments (it does not enumerate them). Subordinate to the human-need brief `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` and to the moment, salience, capability-contract, and emergent-features contracts it composes; does not override current runtime truth in `docs/STATUS.md` / `docs/ARCHITECTURE.md`. The *whether/how to reach out* decision is a separate, deterministic contract — `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`.
Owner: Product / Contextual Relevance Engine capability authority
Temporal class: strategic
Review cadence: event-driven
Source of truth: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md
Last reviewed: 2026-06-13
Last verified against: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md, docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/EMERGENT_FEATURES_MODEL.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md

# Relevance Evaluator Contract

## Purpose

The relevance evaluator is the **adaptive cognition** half of the Contextual Relevance Engine. Given
the context model, it answers *what does the human need now?* and **produces** moments
(`docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`) — it does not pick from a fixed list. It is the seam
where intelligence lives; the discipline about *when to intrude* lives entirely in the separate,
deterministic reach-out/scarcity gate (`docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`).

This is the brief's core architectural stance — **adaptive cognition, deterministic gate**
(`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.1): "smart about what matters, disciplined about when
it intrudes — the adaptiveness never touches the authority or scarcity layer."

## What it produces

The evaluator emits **candidate moments**, each a moment artifact (CRE-01) with:

- a `need` whose `basis` is drawn from the salience vocabulary
  (`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`): **attentional salience** (what is
  mentally near / pulls attention), **attentional relevance** (what would be useful/timely to surface
  now), and **open-loop pressure** (what is still cognitively tugging because it is incomplete,
  unclear, blocked, or not safely parked) — the strongest driver of **surfacing need**;
- an `urgency` **assessment** as an ordinal band (`routine` < `timely` < `pressing` < `critical`),
  with its basis recorded;
- `surfaced_refs` with pointer-first, source-linked provenance.

These signals are **derived, situational, and revisable — never durable canonical artifact
properties** (the salience contract's representation posture). The evaluator returns a proposal; it
never asserts a fact or re-prioritizes the human's own work.

## Contract

Stated against the capability-contract field set (`docs/CAPABILITY_CONTRACT_MODEL.md`):

| Field | Value |
| --- | --- |
| **Name** | `relevance-evaluator` |
| **Purpose** | Given the context model (+ declared patterns + learned signal), produce candidate moments — the need served, surfaced references with provenance, and an urgency assessment. |
| **Inputs** | The **context model** (time, place, sphere/role, active work, imminence, neglect, and the interruptibility reading); **declared patterns** ("when *this* context, surface *that*") as soft guidance; **learned signal** (engagement vs. dismissal history) — read-only. Assembled as a context bundle (`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`). |
| **Outputs** | Zero or more **candidate moments** (CRE-01 artifacts), each non-authoritative, each carrying `need`, `surfaced_refs`, `urgency` band + basis, and `provenance`. Zero moments is a valid, common, healthy output. |
| **Allowed callers** | The proactive attention loop / now-surface composition (CRE-03/CRE-04). Not directly callable to cause an effect — it only proposes. |
| **Authority class** | `proposal` — returns structured proposals another layer may accept or reject; **no direct mutation**. Materializing a candidate moment is a separate governed write (write guard + receipt), per the moment contract. |
| **Side effects** | None intrinsic. Producing a candidate is pure cognition; the only durable effect downstream is materialization, which is governed elsewhere. No external execution, ever. |
| **Provenance requirements** | Every candidate records `produced_by` (this contract's id + version), `inputs_digest` (hash of the evaluator inputs), and `cognition mode` (`llm-cognition` \| `deterministic-fallback`). The `need.basis` and `trigger` make *why now* reconstructable without the runtime. |
| **Deterministic fallback** | When model cognition is unavailable, a **deterministic path** still produces moments from structured signals — time-based triggers (start-of-day), open-loop pressure from the commitment layer (`docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`), and imminence from dated commitments. The fallback is **degraded, not absent**: fewer, more conservative moments, marked `deterministic-fallback`. It must never produce something *worse than silence* (the default direction is silence when uncertain). |
| **Observability** | The evaluator's inputs, cognition mode, and produced candidates are inspectable; each candidate is a durable, source-linked artifact. |
| **Maturity** | Forward-line design; staged delivery — the deterministic-fallback path ships first (CRE-03), adaptive cognition layered after. |
| **Replacement strategy** | The contract (inputs → candidate moments) is stable; the cognition implementation behind it (heuristic → model → learned) may be swapped without changing callers, because callers depend on the moment artifact, not the evaluator internals. |

Capability metadata: `capability_class: proposal`, `authority_class: proposal`,
`mutation_risk: none`, `requires_human_gate: no`, `requires_policy_gate: yes` (the reach-out gate),
`receipt_required: yes` (materialization).

## LLM-cognition posture and the deterministic fallback

- **The relevance call is adaptive cognition**: model reasoning over the context model, declared
  patterns, and learned signal — *not* a hardcoded rule tree. It must handle situations nobody
  anticipated and adapt as it observes engagement vs. dismissal (the brief's §3.2 user-defined →
  emergent loop; the emergent loop itself is an explicit follow-on, not this contract).
- **The fallback is deterministic and always available**, so the engine degrades gracefully rather
  than going dark when a model is unreachable — consistent with local-first execution.
- **Adaptiveness never touches authority or scarcity.** The evaluator may be as smart as it likes
  about *what matters*; it has no power to *intrude*. All intrusion decisions are the deterministic
  gate's, and all durable effects are governed.

## How it composes (emergent-features pattern)

The evaluator occupies the first stages of the standard composition pattern in
`docs/EMERGENT_FEATURES_MODEL.md` — `trigger + context bundle + capability composition + policy
evaluation + proposal/action + receipt + feedback signal`:

- **trigger** — a context tick or a declared pattern firing;
- **context bundle** — the inspectable context assembled for the evaluation;
- **capability composition** — it reuses orientation/resurfacing (`docs/FINDING_AND_REORIENTING/`),
  the commitment layer, and context dimensions rather than re-implementing them;
- **proposal/action** — it emits candidate moments (proposals).

**policy evaluation** (the reach-out/scarcity gate), **receipt**, and **feedback signal** are owned by
the gate contract and the implementation slices. Because the evaluator rides this pattern, it cannot
bypass write guards, provenance, or authority by construction.

## Authority posture

Non-authoritative, derived, provenance-preserving. A candidate moment is a proposal with a recorded
basis; it is never silent truth, never a ranking authority over the human's work, and never a
substitute for the source. The evaluator performs no durable write and triggers no external
execution.

## Design choices for owner ratification

1. **`need.basis` enum** = {`open-loop-pressure`, `attentional-relevance`, `reorientation`,
   `commitment-risk`} (mirrors the moment schema; grounded in the salience contract). Open to
   extension.
2. **Declared-pattern weighting** — patterns are *soft guidance* that bias the evaluation, never hard
   rules that force or suppress a moment. Default: soft bias only.
3. **Staging** — deterministic-fallback path delivered first (CRE-03), adaptive cognition layered
   after, behind the same contract. Default: stage it.

## Out of scope

- The reach-out ladder, interruption threshold, and scarcity gate — `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`.
- The emergent/learned pattern loop (system proposes new patterns) — explicit follow-on after CRE-04.
- Any runtime implementation, UI, or test (CRE-03/CRE-04). External connectors (deferred slice).

## Related docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3, §3.1, §3.2.
- `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`, `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`.
- `docs/CAPABILITY_CONTRACT_MODEL.md`, `docs/EMERGENT_FEATURES_MODEL.md`.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`, `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`.
- `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md` — the deterministic gate it feeds.
