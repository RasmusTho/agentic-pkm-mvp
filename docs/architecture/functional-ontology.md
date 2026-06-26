State: Canonical Yggdrasil functional ontology. Docs-only architecture contract for the foundation backlog (#2533–#2552); names the objects the system reasons about. Does not claim shipped runtime behavior.
Doc role: Architecture / functional ontology
Authority: Owns the canonical names and system consequences of Yggdrasil's functional objects (scope, artifact, claim, memory, provenance, proposal, capability, authority, projection, execution). Future schemas, contracts, and code reference these terms instead of inventing parallel ones. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md` (doctrine) and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (boundaries); each term names its owning Level 2 control boundary defined there.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (ontology terms); subordinate to doctrine and SBS
Last reviewed: 2026-06-26
Last verified against: docs/foundation/00-yggdrasil-doctrine.md, docs/foundation/yggdrasil-architecture-context-packet.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/architecture/SBS_BOUNDARY_REGISTER.md

# Yggdrasil Functional Ontology

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)

This document names the objects Yggdrasil can reason about and fixes their meaning so future code
does not invent parallel terms for scope, memory, artifact, claim, provenance, proposal, capability,
and authority. It is **not a glossary-only cleanup**: every term carries system consequences —
an owning control boundary, key metadata, the semantic dimensions it must preserve, and a
forbidden conflation.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md) and the
[context packet](../foundation/yggdrasil-architecture-context-packet.md). The owning boundaries
(HKA, SIP, GOV, WSP, …) are defined in the [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md)
and the [boundary register](SBS_BOUNDARY_REGISTER.md). The orthogonal metadata fields referenced in
the "Semantic dimensions" column are defined in [semantic dimensions](semantic-dimensions.md). The
field bundle that physically carries this metadata is the metadata bundle schema
([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)); per-term tests/evals are pinned
by the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) and the
anti-contamination eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)).

> Convention: "Owning boundary" is the Level 2 control boundary that owns the term's semantics.
> Some terms have a primary owner plus a co-owning boundary for a distinct facet (for example a
> policy facet owned by GOV or a provenance facet owned by SIP); these are named in the row.

## 1. Ontology rules (read before the terms)

These rules govern how the terms below relate. They are load-bearing.

- **Scope is not merely vault/folder/device.** Scope is simultaneously a cognitive frame, an
  audience boundary, a policy boundary, and a provenance context. A folder or device may *carry* a
  scope binding but does not *define* the scope.
- **VaultRoot is physical/storage topology; Scope is cognitive/policy/provenance context.** Two
  artifacts in the same VaultRoot may be in different scopes; one scope may span VaultRoots.
- **Workspace is an active working surface/context, not durable identity by itself.** A workspace
  binds *which* scopes/principal/device are active now; it is not the artifact's identity and does
  not confer authority.
- **Sphere is human-facing life-domain meaning, not sufficient policy by itself.** "Work", "RPG",
  "private" are spheres a human recognizes; policy decisions still require GOV, not the sphere label
  alone.
- **`Artifact`, `Segment`, `Source`, `Projection`, and `RetrievalResult` are distinct.** They are
  not interchangeable: an artifact is durable content, a segment is a delimited span of it, a source
  is an origin, a projection is a rebuildable derivation, and a retrieval result is moment-specific
  candidate output.
- **`MemoryItem` is not canonical knowledge by default.** It is advisory and noncanonical until
  promoted into HKA through governance.
- **`Projection` is not evidence by default.** It is a derived representation; it gains evidence
  standing only through provenance-backed promotion.
- **`CrossScopeFlow` is not a boolean.** It is a typed, directional, operation-specific grant — see
  [cross-scope-flow](cross-scope-flow.md).
- **`AuthorityReceipt` records governance, not observability alone.** It is the accountable record
  of a governed transition; an observability trace ([OEF](../SYSTEM_BREAKDOWN_STRUCTURE.md)) can show
  that something happened but is not itself the authority record.
- **Standards are adapters, not the ontology.** PROV-O/SKOS/ABAC/ReBAC/MCP may implement these
  terms; they do not redefine them.

## 2. Topology and context terms

These describe *where* and *in what frame* material lives. Owning boundaries: **PDM** (physical
storage), **WSP** (workspace, scope & principal context), **SFC** (synchronization, federation &
consensus).

| Term | Meaning | What it is NOT | Owning boundary | Key metadata | Semantic dimensions | Tests/evals |
| --- | --- | --- | --- | --- | --- | --- |
| `VaultRoot` | A physical/storage root: a topological container of artifact files on a device or backing store. | A scope, a policy boundary, or a unit of meaning. Two scopes can share a VaultRoot; one scope can span VaultRoots. | PDM (storage topology); HKA owns the knowledge-survivability of artifacts within it | `vault_root_id`, storage location, device binding | `scope_binding` (carried, not defined here), `sync_state` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Workspace` | An active working surface/context: the set of bindings (scopes, principal, device) that are active for a session of work. | Durable identity, authority, or a scope by itself. Closing a workspace does not change any artifact's identity. | WSP | `workspace_id`, active `ActiveContextSet` bindings | `scope_binding` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Scope` | A cognitive frame **and** audience boundary **and** policy boundary **and** provenance context that material belongs to. | Merely a vault/folder/device; merely a human-facing label; a permission grant by itself. | WSP (binding); GOV (policy facet); SIP (provenance facet) | `scope_id`, frame, audience, policy ref, provenance context | `scope_binding`, `sensitivity` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Sphere` | A human-facing life-domain (e.g. work, private, RPG/worldbuilding) used to organize scopes for a person. | A sufficient policy boundary on its own; a scope's full meaning. Policy still requires GOV. | WSP (topology); HIX surfaces it to the human | `sphere_id`, label, member scopes | `scope_binding`, `sensitivity` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Principal` | An identified actor (the human, or a delegated agent role) on whose behalf context and actions are attributed. | A device; a credential; authority itself. A principal *holds* delegated capability; it is not the capability. | WSP (principal context); GOV (delegation/authority) | `principal_id`, kind (human/agent-role), delegation ref | `authority_state` (of its grants) | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Device` | A physical/logical machine with a role (e.g. primary, satellite) that hosts replicas and participates in a principal's situated context. | A principal; a replica; a scope. A device *hosts* replicas; it is not the artifact identity. | WSP (device/principal context); SFC (replica-host facet) | `device_id`, role, hosted replicas | `sync_state` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Node` | A participant identity in the synchronization/federation topology. | A device's hardware; a scope; an authority. | SFC | `node_id`, topology role | `sync_state` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Replica` | A materialized copy of artifacts/state on a node, subject to sync/convergence. | The canonical artifact; a separate identity; a source of new authority. Sync preserves boundaries; it does not promote. | SFC | `replica_id`, node ref, convergence/causal markers | `sync_state` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |

## 3. Knowledge and meaning terms

These describe *what is durable knowledge* and *how it means*. Owning boundaries: **HKA** (human
knowledge & artifact substrate), **SIP** (semantic identity & provenance), **DRI** (derived
representation & indexing).

| Term | Meaning | What it is NOT | Owning boundary | Key metadata | Semantic dimensions | Tests/evals |
| --- | --- | --- | --- | --- | --- | --- |
| `Artifact` | A durable unit of content under HKA care (note, document, record). | A projection, a segment, a retrieval result, or a storage row. Being stored is not being an artifact. | HKA | `artifact_id`, `scope_binding`, `source_role`, `authority_state` | `source_role`, `authority_state`, `scope_binding`, `sensitivity` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `HumanArtifact` | An artifact authored or captured by a human. | Automatically canonical. Authorship sets `source_role`, not `authority_state`. | HKA | `artifact_id`, `source_role: human_*`, `authority_state` | `source_role`, `authority_state` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `AcceptedArtifact` | An artifact that has reached an accepted/canonical `authority_state` through a governed transition. | The same as being human-authored or stored. Acceptance is a GOV transition with a receipt, not a default. | HKA (state); GOV (transition) | `artifact_id`, `authority_state: accepted`, `authority_receipt_ref` | `authority_state`, `evidence_role` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Segment` | A delimited, citable span of an artifact used for indexing, retrieval, and citation. | A separate artifact; the whole source; evidence by itself. It is rebuildable from its artifact and must preserve provenance. | DRI (rebuildable chunk); SIP (span identity); HKA source anchor | `segment_id`, `artifact_id`, span, `provenance_ref` | `source_role`, `authority_state` (inherited), `evidence_role` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Claim` | A semantic assertion stated or extracted, carrying its provenance and standing. | True by virtue of existing; canonical because it was extracted. A claim's standing is its `authority_state`/`evidence_role`. | SIP (semantic identity); GOV (standing) | `claim_id`, statement, `provenance_ref`, subject refs | `authority_state`, `evidence_role`, `source_role` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Concept` | A named semantic entity in the identity/ontology graph that artifacts and claims refer to. | A storage key; a folder; an authority. | SIP | `concept_id`, label, aliases | `scope_binding` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Relation` | A typed semantic edge between concepts, artifacts, or claims. | A retrieval similarity score; a permission; a flow. Similarity is not a relation, and a relation is not permission. | SIP | `relation_id`, type, endpoints, `provenance_ref` | `scope_binding`, `evidence_role` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Source` | The origin an artifact/claim derives from (internal artifact, external document, provider feed). | The segment or projection derived from it; evidence standing by itself. External-source adapters are EBF; provenance is SIP. | SIP (provenance/attribution); EBF (external adapter facet) | `source_id`, kind, locator, `provenance_ref` | `source_role`, `sensitivity` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |

## 4. Memory, cognition, and capability terms

These describe *recall*, *proposal*, and *delegated capability*. Owning boundaries: **MEM** (machine
memory & learning), **CAO** (cognitive capability & agent orchestration), **GOV** (governance,
policy, authority & receipts), **HKA** (for accepted commitments).

| Term | Meaning | What it is NOT | Owning boundary | Key metadata | Semantic dimensions | Tests/evals |
| --- | --- | --- | --- | --- | --- | --- |
| `MemoryItem` | An inspectable, revisable machine-memory record that aids recall and reasoning. | Canonical human knowledge; evidence by default. It is noncanonical until promoted into HKA via governance. | MEM (lifecycle); GOV (promotion); HKA (target of promotion) | `memory_id`, `source_role: agent_memory`, `memory_state`, `provenance_ref` | `source_role`, `authority_state`, `evidence_role`, `memory_state` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Proposal` | A non-side-effecting suggestion produced by cognition/agents for the human to accept, reject, or revise. | A commitment; an authorized change; durable knowledge. A proposal mutates nothing until governed acceptance. | CAO (production); GOV (disposition) | `proposal_id`, content, target ref, rationale | `authority_state: proposed`, `evidence_role` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `Commitment` | A durable obligation/decision the human has accepted (a decision record, promise, or deadline). | A proposal; an agent memory. A commitment is the accepted form, reached through governance. | HKA (durable state); GOV (acceptance) | `commitment_id`, statement, `authority_receipt_ref`, due/lifecycle | `authority_state: accepted`, `evidence_role: evidence` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `CapabilityGrant` | A scoped, revocable grant permitting a principal/agent role to perform classes of operations. | An execution; an authority transition; a universal bypass. A grant is bounded and auditable. | GOV | `grant_id`, principal ref, allowed operations, scope, `expiry` | `authority_state`, `scope_binding` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `CrossScopeFlow` | A typed, directional, operation-specific grant permitting movement/use of material across a scope boundary. | A boolean; a default; a consequence of similarity. See [cross-scope-flow](cross-scope-flow.md). | GOV | `flow_id`, `source_scope`, `target_scope`, `allowed_operations`, `provenance_requirements`, `expiry` | `scope_binding`, `source_role`, `authority_state`, `evidence_role` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |

## 5. Authority, provenance, and effect terms

These describe *accountability*, *lineage*, *derivation*, and *side effects*. Owning boundaries:
**GOV** (authority & receipts), **SIP** (provenance), **DRI** (projections), **EXE** (execution).

| Term | Meaning | What it is NOT | Owning boundary | Key metadata | Semantic dimensions | Tests/evals |
| --- | --- | --- | --- | --- | --- | --- |
| `AuthorityReceipt` | The accountable record that a governed authority transition occurred (who/what/why/when, under which grant). | An observability trace; a log line; the transition itself. It records governance, not behavior. | GOV | `receipt_id`, actor, transition, grant ref, timestamp, justification | `authority_state` (resulting) | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |
| `ProvenanceEvent` | A recorded lineage event capturing how an artifact/claim/derivation came to be and why it has the standing it has. | An authority decision; an OEF metric. Provenance carries justification and survives derived use. | SIP | `event_id`, subject ref, derivation, `source_role`, justification | `source_role`, `evidence_role` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `Projection` | A rebuildable derived representation: dashboard, summary, context bundle, embedding, graph overlay, or agent answer. | A primary source; evidence by default. It must preserve metadata/provenance and is regenerable from durable sources. | DRI (most projections); OEF (observability projections) | `projection_id`, derivation, source refs, `rebuildable: true` | `evidence_role: non_evidence` (default), `source_role`, `scope_binding` | TBD ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) |
| `ExecutionEffect` | An authorized side effect actually performed (a tool action, automation, external write) and its status. | A proposal; an authorization; a projection. Execution cannot authorize itself; it requires a prior governed grant/transition. | EXE (effect); GOV (authorization) | `effect_id`, operation, `authority_receipt_ref`, status, rollback ref | `execution_state`, `authority_state` | TBD ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) |

> `RetrievalResult` is named in the ontology rules as distinct from `Artifact`/`Segment`/`Projection`
> but is contracted separately as candidate-evidence output by
> [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) (RCA). It is moment-specific
> candidate evidence/context, never truth or authority; see
> [semantic dimensions](semantic-dimensions.md) and [cross-scope-flow](cross-scope-flow.md).

## Related documents

- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — the commitments these terms protect
- [Semantic dimensions](semantic-dimensions.md) — the orthogonal metadata each term must carry
- [CrossScopeFlow](cross-scope-flow.md) — governed cross-scope use of these objects
- [Traceability matrix](traceability-matrix.md) — principle → ontology → boundary → contract → test → issue
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — the owning control boundaries
- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — full synthesis
- Pending schema: metadata bundle ([#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)); `MemoryItem` ([#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546)); `AuthorityTransition` ([#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547)); `RetrievalResult` ([#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548))
