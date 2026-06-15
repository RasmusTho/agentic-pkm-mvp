State: Concept contract (forward line; not yet shipped) — defines the deterministic reach-out ladder + scarcity gate for the Contextual Relevance Engine (CRE-02, part 2 of 2).
Doc role: Core SoT (reach-out / scarcity gate)
Authority: Canonical definition of the *deterministic gate* half of the engine — the graduated reach-out ladder, the context-dependent interruption threshold, the non-negotiable zero-tolerance floor, defer-not-drop suppression, and the mapping of effects onto the #1881 governance tiers. Subordinate to the human-need brief `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` and to the moment, receipt, and cognitive-load contracts it composes; does not override current runtime truth in `docs/STATUS.md` / `docs/ARCHITECTURE.md`. The *what to surface* decision is the separate, adaptive `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`.
Owner: Product / Contextual Relevance Engine capability authority
Temporal class: strategic
Review cadence: event-driven
Source of truth: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md
Last reviewed: 2026-06-13
Last verified against: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md, docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md, docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md, docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md, docs/CAPABILITY_CONTRACT_MODEL.md

# Reach-out and Scarcity Gate Contract

## Purpose

This is the **deterministic discipline** half of the Contextual Relevance Engine. The relevance
evaluator (`docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`) decides *what* a moment is; this gate
decides *whether and how* to reach out about it. **Scarcity is the core feature, not a setting**
(`docs/HUMAN-FLOWS.md` §0): a persistent stream the human must monitor is a new burden, not a
prosthesis. The gate is where that discipline is enforced, deterministically.

## The reach-out ladder

The engine reaches out on a **graduated ladder of intrusiveness**; a moment climbs only as high as it
earns (`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.3):

- **Glance surface** — a companion-UI "now" view; always available, zero interruption (**pull**).
  Materialized moments always appear here. This rung is never an interruption, so it is never gated by
  the threshold — it is the floor of the ladder, not a reach-out.
- **In-app nudge** — a badge/banner when the app is already open. A reach-out; gated.
- **OS push notification** — the real interrupt; top rung, highest bar. Reserved for time-critical /
  commitment-risk moments. A reach-out; gated, and additionally barred by the zero-tolerance floor.

A moment that does not earn a reach-out is **not** a failure — it sits quietly at the glance surface
for when the human pulls. The default direction is silence.

## Interruption threshold

Scarcity is **not a fixed per-day cap**. It is a **context-dependent interruption threshold driven by
the human's current cognitive load / interruptibility** — the same context model that drives relevance
also tells the gate how interruptible the human is right now
(`docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md :: Interruptibility`,
`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`):

- low load (at home, not in a meeting) → higher tolerance → **lower bar** to surface;
- high load (in a 1-1, deep focus) → lower tolerance → **higher bar**;
- **sleep / declared do-not-disturb → zero tolerance → never push** (see §Zero-tolerance floor).

**Mechanics.** The threshold is expressed as the **minimum urgency band a moment must clear to occupy
each gated rung**, as a function of the current interruptibility reading:

```
threshold(context) = {
  in_app_min:  <min urgency band to show an in-app nudge>,
  push_min:    <min urgency band to fire an OS push>,
}
```

A moment occupies a rung only when its `urgency` band (from the evaluator: `routine` < `timely` <
`pressing` < `critical`) is **≥ that rung's minimum for the current context**. Higher load raises the
minimums; lower load lowers them. The bands the curve keys on (home / meeting / focus / sleep) are
**seeded by the human** and then **learned** from engagement vs. dismissal, always within the
deterministic floor. When interruptibility is **uncertain, the gate holds to the higher threshold**
(silence) — the brief's default direction.

### Zero-tolerance floor

**Sleep** and **declared do-not-disturb** are a hard, deterministic, **non-negotiable floor**: in a
zero-tolerance state `in_app_min` and `push_min` are unreachable, so **no reach-out is emitted
regardless of urgency** — even `critical`. The glance surface (pull) remains available; the human is
simply never pushed. This floor is not a learned preference and cannot be relaxed by the adaptive
layer.

### Defer-not-drop

A push fires only when a moment's urgency clears the *current* threshold. Below it, the moment
**degrades down the ladder and defers** — it is never dropped; it waits at the glance surface and
re-attempts when interruptibility rises. **Suppression is timing, not deletion** (the moment's
`lifecycle` becomes `deferred`, a recorded state, not a removal). This is the `defer-not-drop`
guarantee.

## Determinism boundary

This section is binding. The split between adaptive cognition and the deterministic gate is the whole
discipline (`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.1):

- **Adaptive (in the relevance call):** *what is relevant / what the human needs* — model reasoning,
  declared patterns, learned signal. Owned by the relevance-evaluator contract.
- **Deterministic (in this gate):** *whether the engine may interrupt* — the threshold comparison,
  the zero-tolerance floor, defer-not-drop, and the receipts. **No model reasoning runs inside the
  interruption decision or the floor.** The tolerance *curve* may be learned (which band → which
  minimums), but the **comparison and the floor are deterministic** and inspectable.
- **Even a fast path emits a receipt and never triggers external execution without the trail.** Every
  gate decision — surface at glance, nudge in-app, push, defer, or suppress at the floor — produces a
  human-legible receipt linked to the moment
  (`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`); the existence of traces alone does not
  satisfy this. No gate decision causes an external side-effect.

The adaptiveness never touches the authority or scarcity layer; the determinism never tries to be
smart about relevance.

## Governance tier mapping (#1881)

The gate maps reach-out effects onto the settled tiers (`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md`
§4; #1881):

| Tier | Reach-out effect | Human interrupted? |
| --- | --- | --- |
| **Act** | Surface at the glance surface; show an in-app nudge; materialize a moment; log a receipt — reversible, vault-internal, clear authority. | no |
| **Agent review** | A high-urgency push candidate that is genuinely ambiguous — route to a more capable agent to decide push-worthiness rather than interrupt the human. | no |
| **Ask you** | An external side-effect (send, book, hit an external API). **Out of scope for the engine's core chain** — no reach-out ever does this. | yes |

The safety net is the log + Git/GitHub history (every durable change is recorded and revertible), so
the default is *act, don't ask*. Reach-out (glance / in-app / push) is **Act / agent-review**;
*sending* or *booking* is **Ask you** and is not part of this gate.

## Contract

Stated against the capability-contract field set (`docs/CAPABILITY_CONTRACT_MODEL.md`):

| Field | Value |
| --- | --- |
| **Name** | `reachout-scarcity-gate` |
| **Purpose** | Decide, deterministically, whether and how far up the intrusiveness ladder a candidate moment may climb, given its urgency and the current interruptibility threshold; defer or suppress otherwise; emit a receipt for every decision. |
| **Inputs** | A candidate moment (with `urgency` band) and the current interruptibility reading from the context model. |
| **Outputs** | A reach-out decision (`glance` \| `in-app` \| `push` \| `defer`) + a receipt; on the zero-tolerance floor, always `defer` for the gated rungs. |
| **Allowed callers** | The proactive attention loop (CRE-04) and the now-surface composition (CRE-03, glance only). |
| **Authority class** | `governed effect` — it causes a governed effect (a reach-out + receipt) through the authority/event envelope; never bypasses it. |
| **Side effects** | A reach-out signal (glance render / in-app nudge / OS push) and a receipt. **No external side-effects.** |
| **Provenance requirements** | Each decision records the moment ref, the urgency band, the interruptibility reading, the threshold applied, and the outcome (climbed / deferred / floor-suppressed). |
| **Deterministic fallback** | The gate is already deterministic; its safe default is **silence** (hold to the higher threshold) whenever interruptibility is uncertain or unavailable. |
| **Observability** | Every decision is a receipt; the threshold and floor are inspectable. |
| **Maturity** | Forward-line design with shipped runtime slices: the glance path shipped in CRE-03 (pull-only); #1964 runs the reach-out decision loop on governed context ticks and projects in-app nudges; OS-push delivery remains deferred. |
| **Replacement strategy** | The decision contract is stable; the learned tolerance curve may evolve behind it without changing the deterministic comparison or the floor. |

Capability metadata: `capability_class: governed_execution`, `authority_class: governed_effect`,
`mutation_risk: additive`, `requires_human_gate: no` (reach-out is Act/agent-review),
`requires_policy_gate: yes` (it *is* the policy gate), `receipt_required: yes`.

## Design choices for owner ratification

1. **Threshold representation** — per-rung minimum urgency band as a function of the interruptibility
   reading (vs a single scalar threshold). Default: per-rung minimum band (maps cleanly onto the
   ladder).
2. **Agent-review trigger** — high-urgency *push* candidates that are genuinely ambiguous route to
   `agent-review` rather than interrupt; glance/in-app stay `Act`. Default: yes, route ambiguous push
   candidates to agent-review.
3. **Default-to-silence on uncertainty** — mandated by the brief, not optional; stated here for
   completeness.

## Out of scope

- The relevance evaluator that produces moments — `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`.
- Any runtime implementation, UI, or test (CRE-03/CRE-04).
- External connectors and any external side-effect (the #1881 `ask-you` tier).
- The emergent/learned pattern loop (explicit follow-on after CRE-04).

## Related docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.1, §3.3, §4.
- `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`, `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`.
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md` (Interruptibility), `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`,
  `docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md`.
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`.
- GitHub #1881 — governance tiers.
