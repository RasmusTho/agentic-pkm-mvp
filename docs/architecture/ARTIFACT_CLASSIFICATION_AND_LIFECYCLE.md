State: Accepted cross-system design baseline (owner accepted 2026-08-17). Normative for classification and lifecycle routing; it makes no runtime or migration claim.
Doc role: Architecture / governance design record
Authority: Owns the shared classification axes and Capture → Explore → Synthesize → Propose → Promote → Implement → Verify → Supersede/Retire lifecycle across Builder working artifacts and Product/Runtime knowledge derivatives. Domain contracts remain authoritative for their concrete classes and enforcement.
Owner: Builder System / CES boundary, reconciled with Product/Runtime semantic owners
Temporal class: strategic target-state
Source of truth: This document owns the cross-plane classification/lifecycle overlay; local owner docs win for class-specific fields, state axes, and shipped behavior.
Last reviewed: 2026-08-17

# Artifact Classification and Lifecycle

## Purpose

This document gives Builder and PKM work one small, shared vocabulary for answering two different
questions:

1. What kind of standing does this artifact have now?
2. Which governed stage is it in on its way to a durable result?

The axes must remain separate. A file can be durable but non-normative, derived but useful, or
ephemeral but provenance-bearing. A lifecycle stage does not grant authority.

The detailed Mimer artifact classes remain owned by
`docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md`,
`docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`, and
`docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`. The detailed BuilderOps object classes
remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`.

## Classification axes

| Axis | Values used by this overlay | Question answered |
| --- | --- | --- |
| Authority standing | `Normative`, `Non-normative` | May this artifact define current requirements or truth for a named scope? |
| Derivation | `Source`, `Derived`, `Projection` | Is the artifact original, transformed, or a bounded read representation? |
| Durability | `Durable`, `Ephemeral`, `Rebuildable` | What should survive ordinary use, and may the representation be recreated? |
| Promotion posture | `Not-promoted`, `Proposed`, `Promoted`, `Superseded`, `Retired` | Has an explicit authority transition happened, and is it still current? |
| Lifecycle stage | The eight stages in §4 | Where is the artifact in the working-to-verified flow? |
| Location/surface | Source, Builder Vault, BuilderOps, repo, GitHub, projection | Where is it stored or observed? This is routing context, not authority. |

The classification is a tuple, not one overloaded status string. Existing contracts may serialize a
different field set; adapters must preserve the same distinctions rather than inventing an implicit
priority order.

## Canonical classifications by example

| Example | Classification overlay | Governing local owner |
| --- | --- | --- |
| External source or retained original | `Source + Non-normative/Source-owned + Durable` | Source-specific Product/Runtime contract |
| Builder research note | `Derived or Source + Non-normative + Ephemeral` | Builder Vault working surface |
| Agent draft, comparison, or design exploration | `Derived + Non-normative + Ephemeral` | Builder Vault; raw/analytical BuilderOps semantics where applicable |
| BuilderOps worklog or proposal | `Derived + Non-normative + Durable/operational` | ADR-0010 and BuilderOps object model |
| Accepted ADR, contract, or owner doc | `Derived or Source + Normative + Durable` | Named repo owner document / ADR |
| GitHub Issue or PR | `Derived + Builder-governed + Durable` | GitHub task/review lifecycle; not Product/Runtime semantic authority by default |
| CI, review, merge, or BuilderOps receipt | `Derived + Evidence + Durable` | The workflow that emitted the receipt, within its recorded scope |
| Search/index/graph/DevUI view | `Projection + Non-normative + Rebuildable` | Its source owner; projection must self-identify |
| Promoted PKM knowledge | `Derived + Normative/accepted + Durable` | Existing HKA/MEM/GOV authority path and receipt |
| Superseded artifact | Prior tuple plus `Superseded` | Successor and supersession receipt define current standing |

“Builder-governed” and “Evidence” above describe bounded roles; they do not create new global
authority classes. The existing BuilderOps `authority_class` vocabulary (`raw`, `operational`,
`analytical`, `staged`, `decision`, `projection`, `receipt`) remains the serialized BuilderOps
vocabulary where that object model applies.

## Term definitions

- **Normative:** accepted and owner-governed for a named scope. It can define a requirement or
  current truth only within that scope.
- **Non-normative:** working or reference material that may inform a proposal but cannot establish
  requirements, authorize work, or override an owner document.
- **Ephemeral:** disposable or short-lived by design. Ephemeral does not mean untraceable while in
  use; source references and relevant receipts still apply.
- **Derived:** produced from named source(s) by transformation, synthesis, extraction, comparison,
  or aggregation. It preserves lineage and inherits no stronger authority automatically.
- **Promoted:** moved across an explicit governed boundary into a target surface or stronger
  standing. Promotion creates or updates a target artifact; it is not a location or display flag.
- **Superseded:** no longer current because an explicit successor owns the same scoped claim. The
  old artifact remains historical unless a separate erasure rule applies.
- **Authority:** the right to define or authorize a bounded claim or transition. It is scoped and
  owned; it is never inferred from recency, popularity, Git storage, or UI exposure.
- **Projection:** a bounded representation used for discovery, retrieval, reporting, or navigation.
  It is rebuildable where its owner says so and never promotes its inputs.
- **Provenance:** source, derivation, actor/tool/time, review, promotion, supersession, and receipt
  links sufficient for a human or reconciler to reconstruct why the artifact exists and what it may
  claim.

## Lifecycle: Capture → Explore → Synthesize → Propose → Promote → Implement → Verify → Supersede/Retire

The lifecycle is a cross-plane flow, not a universal runtime state machine. Some artifact classes
stop earlier or use a domain-specific lifecycle. The stage names give the shared handoff vocabulary.

| Stage | Meaning | Allowed authority effect | Required evidence before leaving |
| --- | --- | --- | --- |
| **Capture** | Preserve the source, observation, question, or working input with identity and initial provenance. | No authority upgrade. | Source/location, capture time, scope, and limitations where known. |
| **Explore** | Inspect, compare, research, or test possibilities without treating working material as settled. | Remains non-normative. | Source refs, open questions, and explicit uncertainty. |
| **Synthesize** | Produce a derivative, summary, comparison, map, or draft from named inputs. | Derived output inherits no stronger authority. | Input refs, transformation/method, omissions, and disagreement handling. |
| **Propose** | Package a candidate claim, decision, Issue, ADR, owner-doc change, or implementation plan for review. | Proposal is not acceptance. | Target surface, requested authority, impact, acceptance/verification path, and provenance. |
| **Promote** | A human or governed process accepts, rejects, revises, discards, or explicitly stages the cross-boundary result. | This is the only stage that can change authority standing. | Decision-maker/process, outcome, timestamp, target ref, and receipt/PR/Issue evidence. |
| **Implement** | Build the promoted contract or bounded task in the authorized target surface. | Does not widen the promoted scope. | Governing Issue/contract and changed artifact refs. |
| **Verify** | Check the implemented result against the exact contract, source, tests, review, and delivery evidence. | Verification proves only its named scope. | Exact head/version, `Verify:` targets, CI/review/receipt evidence, and limitations. |
| **Supersede / Retire** | Replace a current artifact or end an obsolete line while preserving the historical relation. | Removes active standing only through explicit relation/decision. | Successor or retirement reason, effective scope/time, and receipt. |

Promotion may end in a new artifact, a GitHub Issue, an ADR/owner-doc PR, a generated projection,
or a discard receipt. It does not always produce normative knowledge. A projection may be generated
after promotion or verification, but its projection status remains independent.

## Transition rules

1. No stage transition may infer authority from file location, Git history, merge status, DevUI
   visibility, or a model/provider identity.
2. `Capture → Explore → Synthesize` may be automated when the source and transformation are
   inspectable; the result remains non-normative or derived.
3. `Propose → Promote` requires an explicit target authority and review outcome. If the target
   owner is missing or conflicting, remain proposed/unknown and fail closed.
4. `Promote → Implement` requires a bounded Issue, direct-repair contract, or docs-authoring path
   that names `Verify:` targets. A proposal alone is not pickup authority.
5. `Implement → Verify` uses exact-head evidence. Earlier evidence is discarded when the relevant
   source, contract, or head changes unless a governing workflow explicitly permits reuse.
6. `Supersede / Retire` never silently deletes the source lineage. Retention/erasure is a separate
   policy decision.
7. A failed or ambiguous transition is recorded as failed/unknown/blocked evidence, not rewritten
   as success by a projection.

## Minimum provenance envelope

Every non-trivial derived, proposed, promoted, projected, superseded, or retired artifact must be
able to answer:

```yaml
provenance:
  source_refs: []
  derived_from: []
  transformation: "human-readable method or governed operation"
  actor_or_process: "human, agent, or workflow identity"
  observed_at: "RFC3339"
  source_versions_or_watermarks: []
  review_or_decision_ref: null
  promotion_ref: null
  supersedes_refs: []
  receipt_refs: []
  limitations: []
```

This is a conceptual minimum, not a new schema. Existing contracts own the concrete field names and
serialization. Missing values are explicit unknowns; they must not be synthesized from timestamps,
paths, filenames, branch names, or semantic similarity.

## Cross-system example

```text
Builder Vault research note (ephemeral, non-normative)
  → comparison/synthesis with source refs
  → proposal naming Information Authority + DevUI contracts
  → docs-authoring PR / Issue / ADR decision with receipt
  → accepted owner docs
  → separate DevUI implementation Issue
  → exact-head CI/review/merge and owner-doc writeback
  → DevUI projection links back to the accepted sources
```

The equivalent PKM path is:

```text
source note or retained source
  → derivative summary/claim/synthesis with lineage
  → review-required proposal
  → existing HKA/MEM/GOV promotion and receipt
  → durable knowledge artifact
  → rebuildable indexes/projections
  → explicit supersession or retirement when the source/claim changes
```

The two paths share the authority/provenance/promotion rule; they do not share a storage schema,
runtime lifecycle, or owner.

## Non-goals and implementation gate

This document does not create a new artifact registry, storage migration, schema, graph, retention
engine, or runtime validator. It does not make any existing DevUI or BuilderOps surface delivered.

Before further DevUI implementation that depends on this boundary, the Information Authority Model,
this lifecycle document, and the DevUI Discovery Architecture must remain the accepted design
baseline and be reconciled with the live implementation Issue. Existing read-only recovery or validation work remains governed by its
own live Issue and source contract; no new implementation may use this proposal as an unapproved
authority shortcut.

## Related documents

- [`INFORMATION_AUTHORITY_MODEL.md`](./INFORMATION_AUTHORITY_MODEL.md)
- [`DEVUI_DISCOVERY_ARCHITECTURE.md`](./DEVUI_DISCOVERY_ARCHITECTURE.md)
- [`docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`](../CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md)
- [`docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`](../CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md)
- [`docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`](../builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md)
- [`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`](../CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md)
- [`docs/AGENT-FLOWS.md`](../AGENT-FLOWS.md)
- [`docs/audits/INFORMATION_AUTHORITY_ARTIFACT_LIFECYCLE_REVIEW_2026-08-17.md`](../audits/INFORMATION_AUTHORITY_ARTIFACT_LIFECYCLE_REVIEW_2026-08-17.md)
