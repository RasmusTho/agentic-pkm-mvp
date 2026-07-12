State: Specification directory (parent feature issue #3543; first child #3544; no shipped behavior is claimed).
Doc role: Feature specification
Authority: Defines the future read-only contradiction-triage surface. Subordinate to `docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md` for the shipped contradiction-pass harness and to `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` for scope admission.
Owner: Product / architecture

# Contradiction Triage Bench

## Purpose

Contradiction Triage Bench makes a consequential tension from the existing curation harness inspectable in the established note/Panel proposal flow without making the system decide which statement is true. Its first release is a zero-durable-write adapter and diagnostic boundary: it proves that cited tensions can be consumed safely before any new lifecycle, dismissal, or supersession surface is considered.

## Current foundation and boundary

The contradiction-pass harness from G2-4 is delivered: it produces scope-aware findings with two resolvable citations and retains the semantic-curation propose-only guard. This capability does **not** replace that harness, its panel-proposal materialization, or its declined-proposal ledger.

The Bench is a supporting read path for the existing note/Panel confirmation model, not a parallel review UI. It must never infer a truth verdict, edit either source, create a receipt, or introduce a Bench-specific disposition. A later durable dismissal or superseding-decision flow requires its own authority, lifecycle, privacy, concurrency, and recovery contract.

## First delivery

| Task | Purpose | Status |
| --- | --- | --- |
| [DEFINE_ZERO_WRITE_FINDING_ADAPTER.md](DEFINE_ZERO_WRITE_FINDING_ADAPTER.md) | Establish the supported, scope-safe, zero-write interface from the delivered harness to the existing note/Panel proposal flow. | First executable slice |

After the adapter is proven, a follow-up may improve the existing proposal wording, evidence display, or confirmation path only through the owner-defined note/Panel surface. A separate contradiction review UI is explicitly out of scope unless the graduated-curation owner decision is reopened.

## Cross-task invariants / interaction safety

- Every visible finding has two currently resolvable citations in the caller's current admitted scope; failure to resolve either citation removes the finding rather than leaking partial context.
- The two claims receive equal evidentiary presentation. Model text may describe a tension but cannot resolve it.
- The Bench introduces no `not_a_conflict`, `needs_review`, or superseding-decision disposition. Existing Panel confirmation semantics remain the sole confirmation model.
- Scanning and adapter invocation produce no vault, outbox, receipt, lifecycle, or suppression write. The delivered harness's existing proposal/decline behavior remains governed by its owning curation contract.
- Any later correction is a new, human-confirmed artifact linked through `supersedes`; historical source text is never silently normalized.

## Capability acceptance path

The capability can be promoted only after the adapter proves: current-scope citations resolve; inaccessible evidence is not disclosed; all new adapter paths are zero-write; and a consumer can distinguish scan failure from no findings. Durable triage and supersession remain later work.

## Relationship to GitHub issues

Parent feature issue [#3543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3543) is the validation hub and remains `agent:blocked` while child [#3544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3544) delivers the first task. See [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

## Related docs

- `docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md :: §4, §6 (G2-4)`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
- `docs/CONCEPTS/RELATION_TAXONOMY.md :: supersedes`
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`
