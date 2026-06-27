State: Canonical Yggdrasil ContextEnvelope contract. Docs-only architecture/schema contract for the foundation backlog (#2533–#2552); defines the bounded operating context handed to an agent. Pairs with `schemas/context-envelope.schema.json`. Does not claim shipped runtime behavior.
Doc role: Architecture / contract
Authority: Owns the `ContextEnvelope` contract — the boundary between RCA/GOV/WSP/MEM and CAO/agents. The machine-readable form is `schemas/context-envelope.schema.json`; this doc is its prose mirror. `ContextEnvelope` is a **new** contract; it composes, and does not replace, the existing RCA `ContextBundle` (`docs/contracts/CONTEXT_BUNDLE.md`). Subordinate to `docs/foundation/00-yggdrasil-doctrine.md` and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (ContextEnvelope contract); subordinate to doctrine and SBS
Last reviewed: 2026-06-27
Last verified against: docs/architecture/metadata-bundle.md, docs/architecture/semantic-dimensions.md, docs/architecture/cross-scope-flow.md, docs/contracts/CONTEXT_BUNDLE.md, docs/boundaries/RCA.md, docs/boundaries/CAO.md, schemas/context-envelope.schema.json

# Yggdrasil ContextEnvelope

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Contract issue: [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545) ·
Schema: [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json)

A `ContextEnvelope` is the **bounded operating context** the system assembles and hands to an agent.
Agents consume ContextEnvelopes. They do **not** receive raw vault access, raw index access, or
ambient authority. The envelope carries active scope, allowed capabilities, denied scopes, retrieved
items (each with a [metadata bundle](metadata-bundle.md)), composed context bundles, citation/memory/
mutation/execution policies, cross-scope flows in effect, and escalation conditions.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md), the
[semantic dimensions](semantic-dimensions.md), the [metadata bundle](metadata-bundle.md), and
[cross-scope-flow](cross-scope-flow.md).

## 1. ContextEnvelope vs ContextBundle (do not collapse)

These are two different contracts:

- **`ContextBundle`** ([`docs/contracts/CONTEXT_BUNDLE.md`](../contracts/CONTEXT_BUNDLE.md)) is the
  **RCA evidence/context package**: scoped *candidate* evidence with provenance, ranking, relevance
  explanation, and an explicit non-authority posture.
- **`ContextEnvelope`** (this contract) is the **broader bounded operating-context contract** consumed
  by CAO/agents. A ContextEnvelope **composes or references one or more ContextBundles**, and adds
  active scope, allowed capabilities, denied scopes, policies (citation, memory, mutation, execution),
  cross-scope flows, and escalation conditions.

> A ContextEnvelope **does not replace or erase** the ContextBundle concept. When the need is evidence
> packaging, extend `ContextBundle`. Define/extend `ContextEnvelope` only for the bounded operating
> context. The envelope references bundles by id (`context_bundles[].context_bundle_id`); it never
> redefines them. (Confirmed by the [RCA charter](../boundaries/RCA.md) naming note and context packet §8.)

## 2. Envelope fields

| Field | Meaning |
| --- | --- |
| `envelope_id` | Stable id for this envelope. |
| `access_mode` | Const `bounded_context_only` — asserts there is no raw vault/index access. |
| `active_workspace_id`, `active_scope_id`, `active_sphere` | The active situated context (WSP). |
| `principal_id`, `user_intent` | Who it is for, and the task it was assembled to serve. |
| `allowed_capabilities` | Capability grants the agent may exercise; empty = read/reason only. |
| `denied_scopes` | Scopes explicitly **not** available — recorded as denials with reasons, never as hidden context. |
| `cross_scope_flows` | Typed [`CrossScopeFlow`](cross-scope-flow.md) grants in effect. |
| `retrieved_items` | Individual context items, each carrying an embedded or referenced [metadata bundle](metadata-bundle.md). |
| `context_bundles` | References to the RCA [`ContextBundle`](../contracts/CONTEXT_BUNDLE.md)s this envelope composes. |
| `citation_policy`, `memory_policy`, `mutation_policy`, `execution_policy` | What the agent may cite, remember, propose to mutate, and request to execute. |
| `escalation_conditions` | When the agent must escalate instead of acting or silently dropping context. |
| `trace_id`, `provenance_event_ids`, `created_at` | Trace and provenance references. |

## 3. Required rules

1. **No raw vault access.** The envelope's `access_mode` is `bounded_context_only`; there is no field
   that grants raw vault or index access. Agents reason/propose within envelope boundaries
   ([CAO charter](../boundaries/CAO.md): `agent_no_raw_vault_access`, `agent_receives_bounded_context`).
2. **No denied scopes as hidden context — not even their identifiers.** `denied_scopes` records the
   required non-identifying routing fields (`reason`, `denial_class`, `escalation_recommended`), never
   the denied content and never the denied `scope_id`/`object_id`/provenance (revealing that a specific
   scope exists is itself cross-boundary disclosure). Identifiers needed for accountability live only
   in an audit-only record via `audit_ref`. Cross-scope flows in `cross_scope_flows` carry their full
   canonical guardrails (`source_roles_allowed`, `authority_states_allowed`, `evidence_roles_allowed`),
   so an operation grant cannot apply to the wrong source role, authority state, or evidence role.
3. **Retrieval ≠ citation.** Inclusion in `retrieved_items` does not grant citation; `citation_policy`
   decides, and cross-scope citation requires a flow that allows `cite`.
4. **Citation ≠ mutation.** `mutation_policy.requires_authority_transition` is always true; durable
   mutation routes through a governed [authority transition](authority-transition-flow.md).
5. **Execution cannot self-authorize.** `execution_policy.requires_authorization` is always true.
6. **Envelopes are projections, not primary evidence.** Composed bundles are marked non-authority; the
   envelope is a derived representation.
7. **Useful denied material becomes escalation, not hidden inclusion.** It surfaces in
   `escalation_conditions`, not in `retrieved_items` — and even there it carries no denied
   `scope_id`/`object_id` (only a non-identifying `reason`/`denial_class`, with identifiers behind
   `audit_ref`), so the escalation path itself cannot leak the existence of a denied scope.

## 4. Schema requirements

[`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json):

- requires active context (`active_workspace_id`, `active_scope_id`, `principal_id`, `user_intent`);
- requires `allowed_capabilities` and an explicit `denied_scopes` array (may be empty);
- requires policy blocks for citation, memory, mutation, and execution, each pinning its core
  invariant (`requires_authority_transition`, `requires_authorization`,
  `remembered_authority_state: noncanonical`, `cross_scope_citation_requires_flow`);
- requires each `retrieved_items` entry to carry an embedded `metadata_bundle` **or** a
  `metadata_bundle_ref` (no naked content);
- supports `cross_scope_flows` grants in effect and `escalation_conditions`;
- pins `access_mode` to `bounded_context_only`;
- closes the object (`additionalProperties: false`) with an explicit `extensions` point.

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — §8 envelope/bundle distinction
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — owning control boundaries
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — projections are not evidence
- [Functional ontology](functional-ontology.md) · [Semantic dimensions](semantic-dimensions.md) · [CrossScopeFlow](cross-scope-flow.md)
- [Metadata bundle](metadata-bundle.md) — what each retrieved item carries
- [Existing RCA `ContextBundle`](../contracts/CONTEXT_BUNDLE.md) — composed, not replaced
- [Traceability matrix](traceability-matrix.md)
- [Boundary charters](../boundaries/README.md) — [WSP](../boundaries/WSP.md), [RCA](../boundaries/RCA.md), [GOV](../boundaries/GOV.md), [CAO](../boundaries/CAO.md), [MEM](../boundaries/MEM.md), [OEF](../boundaries/OEF.md)
- Schema: [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json) · shared defs [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
