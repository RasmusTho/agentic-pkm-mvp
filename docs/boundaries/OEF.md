# Boundary: OEF — Observability, Evaluation & Fitness

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** OEF **observes and evaluates** — it can show *that something happened*.
**GOV** gives it normative meaning and decides *what it means*.

## Purpose

Own system legibility, diagnostics, evaluation, and architecture fitness — making behavior visible
and evaluable without ever becoming a control loop.

## Owns

- Traces (`TraceEvent`), health, metrics, evaluation harnesses, architecture fitness rules (`FitnessRule`).
- Drift/regression detection, boundary-violation detection, audit **visibility**, incident diagnostics.

## Does not own

- Policy / governance decisions → **GOV**.
- Memory → **MEM**; retrieval ranking → **RCA**; authority → **GOV**.
- Hidden control loops — observability must not silently steer behavior.

> **Ownership-drift rule.** OEF reveals and evaluates; it does not decide or mutate. When a metric or
> eval implies a behavior change, OEF surfaces it for a GOV decision — it never closes the loop itself.

## Inputs

- Events, traces, metrics, receipts, eval cases, drift signals from all subsystems.

## Outputs

- `TraceEvent`s, health/fitness reports, audit views, drift/incident reports — read models, not commands.

## Calls allowed

- Reads **events/traces from all subsystems**; surfaces evidence to **GOV** and views to **HIX**.

## Calls forbidden

- **Setting policy / authority** — must not mutate policy, memory, ranking, or `authority_state`.
- **Silent control** — eval/drift results must not auto-change runtime behavior.
- **Standing in for receipts** — an audit trace is not an `AuthorityReceipt`.

## Required metadata

OEF observability outputs are `Projection`s: `authority_state: derived`/`projection`,
`evidence_role: non_evidence` by default. It **reads** the full metadata bundle to evaluate
invariants and **preserves** provenance in reports; it sets no authority dimension.

## Policy obligations

- Evaluate against GOV-owned fitness/policy intent; never originate policy.
- Honor `sensitivity`/`suppression_state` when surfacing audit views.

## Provenance obligations

- Traces and audit views are observability records distinct from governance receipts.
- Reports carry provenance of what they observed; they do not become primary evidence by default.

## Invariants owned

- Observability is not policy (matrix #13).
- Evals reveal drift but do not silently control behavior (matrix #13).
- Audit visibility is not an authority receipt (matrix #13, distinct from #9).

## Failure modes

- **Observability-as-policy:** metrics silently updating policy/memory/retrieval.
- **Hidden control loop:** drift detection mutating behavior without GOV.
- **Trace-as-receipt:** treating an audit trace as the governance record.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `observability_not_policy`
- `audit_visibility_not_authority`
- `drift_detection_does_not_mutate`

## Related ADRs

- ADR-0022 (OEF first-class, non-authoritative).

## Related schemas/contracts

- existing `TraceEvent`/`FitnessRule` (SBS Part 5); anti-contamination eval corpus — [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551).

## Related issues

- Charter: [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
