State: Canonical Yggdrasil RetrievalResult contract. Docs-only architecture/schema contract for the foundation backlog (#2533–#2552); defines candidate-evidence/context semantics for RCA retrieval. Pairs with `schemas/retrieval-result.schema.json`. Does not claim shipped runtime behavior.
Doc role: Architecture / contract
Authority: Owns the `RetrievalResult` contract — candidate context/evidence produced by RCA, with admissibility status, provenance/citation ranges, and cross-scope semantics. The machine-readable form is `schemas/retrieval-result.schema.json`; this doc is its prose mirror. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/cross-scope-flow.md`, and `docs/architecture/semantic-dimensions.md`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (RetrievalResult contract); subordinate to doctrine, cross-scope-flow, semantic dimensions
Last reviewed: 2026-06-27
Last verified against: docs/architecture/cross-scope-flow.md, docs/architecture/semantic-dimensions.md, docs/architecture/metadata-bundle.md, docs/contracts/CONTEXT_BUNDLE.md, docs/boundaries/RCA.md, docs/boundaries/GOV.md, schemas/retrieval-result.schema.json

# Yggdrasil Retrieval Contract (RetrievalResult)

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Contract issue: [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) ·
Schema: [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json)

A `RetrievalResult` represents **candidate context/evidence found by RCA** for a moment-specific
query. Retrieval finds and packages relevant material; it does **not** create truth, authority, or
cross-scope permission. This document defines the contract; the machine-checkable form is
[`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json).

> **Similarity is not permission.** Ranking surfaces candidates; admission is a GOV decision.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md), [cross-scope-flow](cross-scope-flow.md),
the [RCA charter](../boundaries/RCA.md), and the [metadata bundle](metadata-bundle.md). A
`RetrievalResult` is distinct from the RCA [`ContextBundle`](../contracts/CONTEXT_BUNDLE.md) (the
assembled candidate-evidence package) and from the [`ContextEnvelope`](context-envelope.md) (the
bounded agent operating context that composes bundles).

## 1. Fields

`retrieval_id`, `query_id`, `active_scope_id`, `active_workspace_id`, `principal_id`,
`scope_policy_prefiltered`, `candidate_items`, `applicable_cross_scope_flows`,
`denied_or_escalated_candidates`, `provenance_event_ids`, `trace_id`, `created_at`.

Each entry in `candidate_items` carries or references:

- `metadata_bundle` (embedded [metadata bundle](metadata-bundle.md)) — providing `object_id`,
  `object_type`, `source_role`, `authority_state`, `evidence_role`, `scope_id`, and
  `derived_from`/provenance;
- `object_id`;
- `admissibility_status`;
- `evidence_role_in_context` (may be downgraded from the intrinsic `evidence_role`, never upgraded);
- `ranking_signals` and `relevance_explanation` (signals inform order, not permission);
- `citation_ranges` (provenance/citation ranges);
- `admitting_cross_scope_flow` when the candidate crosses a scope boundary;
- a `confirmation_reason` when its admissibility status is `requires_confirmation`.

`candidate_items` carries only **surfaceable** candidates (`candidate`, `admitted`, `redacted`,
`requires_confirmation`). Denied and escalated cross-scope material is **never** a metadata-bearing
candidate — it is recorded only in the content-free `denied_or_escalated_candidates` list (see §3.6),
so object id/scope/provenance never leak into a usable result.

## 2. Admissibility states

`admissibility_status` ∈ `candidate`, `admitted`, `denied`, `redacted`, `requires_confirmation`,
`escalated`. This is what distinguishes **candidate** evidence from **admitted** evidence. Within a
metadata-bearing `candidate_items` entry the status is restricted to the **surfaceable** subset
(`candidate`, `admitted`, `redacted`, `requires_confirmation`); `denied` and `escalated` appear only
in the content-free `denied_or_escalated_candidates` list.

## 3. Required rules

1. **Scope/policy eligibility precedes ranking.** The `scope_policy_prefiltered` flag asserts this;
   out-of-scope and suppressed material is excluded before any vector/similarity step, and ranking
   never reintroduces it ([RCA charter](../boundaries/RCA.md): `retrieve_scope_prefilter`).
2. **Similarity is not permission.** `ranking_signals` (including similarity) inform ordering only.
3. **A retrieved item is not automatically citable.** Admission ≠ citation; citation is governed by
   the consuming [context envelope](context-envelope.md)'s citation policy and, across scopes, by a
   flow that allows `cite`.
4. **A citable item is not automatically mutable.** Durable change requires an
   [authority transition](authority-transition-flow.md).
5. **Projection/context bundle is not a primary source.** Candidates carry their real `source_role`
   and `evidence_role`; a projection candidate is not evidence by default.
6. **Denied cross-scope material must not be hidden context — not even its identifiers.** It is
   recorded in `denied_or_escalated_candidates` with the required non-identifying routing fields
   (`reason`, `denial_class`, `escalation_recommended`) and an optional `required_flow_class`,
   **without** content, a metadata bundle, or the denied `scope_id`/`object_id`/provenance. Any
   identifiers needed for accountability live only in an audit-only governance record referenced by
   `audit_ref`, outside the agent-facing result.
7. **Escalated material records why escalation is needed** — via the non-identifying `reason` /
   `denial_class` (and `escalation_recommended`) on its `denied_or_escalated_candidates` entry.
8. **Retrieval preserves citation/provenance ranges** (`citation_ranges`, `provenance_event_ids`).
9. **Applicable cross-scope flows carry their guardrails.** Each entry in
   `applicable_cross_scope_flows` must carry not only `flow_id`/`source_scope`/`target_scope`/
   `allowed_operations` but also the canonical `source_roles_allowed`, `authority_states_allowed`, and
   `evidence_roles_allowed` filters from [cross-scope-flow](cross-scope-flow.md) — so a consumer can
   never apply an operation grant to the wrong source role, authority state, or evidence role.

## 4. Schema requirements

[`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json):

- distinguishes candidate evidence from admitted evidence via `admissibility_status`;
- requires a `metadata_bundle` for every candidate;
- requires provenance/citation-range support (`citation_ranges`, `provenance_event_ids`);
- pins `scope_policy_prefiltered` to `true` so eligibility-before-ranking is asserted in data;
- supports denied/escalated cross-scope candidates via a content-free `denied_or_escalated_candidates`
  list (no leak);
- requires conditional reasons for `denied` / `escalated` / `requires_confirmation` candidates;
- includes a `trace_id`;
- closes the object (`additionalProperties: false`) with an explicit `extensions` point.

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md)
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md)
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — retrieval is candidate generation, not truth
- [Functional ontology](functional-ontology.md) (`RetrievalResult`, `Segment`, `Projection`) · [Semantic dimensions](semantic-dimensions.md) · [CrossScopeFlow](cross-scope-flow.md)
- [Metadata bundle](metadata-bundle.md) — what each candidate carries
- [Context envelope](context-envelope.md) — composes results/bundles into bounded agent context
- [Existing RCA `ContextBundle`](../contracts/CONTEXT_BUNDLE.md)
- [Traceability matrix](traceability-matrix.md)
- [Boundary charters](../boundaries/README.md) — [RCA](../boundaries/RCA.md), [GOV](../boundaries/GOV.md), [SIP](../boundaries/SIP.md), [WSP](../boundaries/WSP.md), [CAO](../boundaries/CAO.md), [OEF](../boundaries/OEF.md)
- Schema: [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) · shared defs [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
