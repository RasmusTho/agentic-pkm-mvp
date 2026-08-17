State: Accepted cross-system design baseline (owner accepted 2026-08-17). Normative for the cross-plane vocabulary and boundaries; it makes no shipped-runtime claim.
Doc role: Architecture / governance design record
Authority: Owns the cross-plane information-authority model for the Product/Runtime knowledge surfaces and the Builder System working surfaces. Existing domain owner docs remain authoritative for their local semantics, schemas, runtime behavior, and delivery lifecycle.
Owner: Builder System / CES boundary, with Product/Runtime semantic owners retaining their existing authority
Temporal class: strategic target-state
Source of truth: This document owns the cross-plane map; the linked owner documents win for local contract detail and current-state truth.
Last reviewed: 2026-08-17

# Information Authority Model

## Purpose and scope

Yggdrasil has two related information flows that must remain legible as one system without being
collapsed into one authority:

- the Product/Runtime knowledge flow from source material to derived representations and governed
  knowledge; and
- the Builder System flow from research and working material to a reviewed repository, Issue, PR,
  owner document, or other governed delivery surface.

This is the cross-plane routing model for those flows. It does not replace the Mimer semantic
authority matrix, the Contextualization Layer contracts, ADR-0010, or the devUI owner contract.
Those documents remain the local owners named in the reconciliation table below.

## Decision baseline

1. **Authority is scoped to a claim and a surface.** A document, record, or view is authoritative
   only for the bounded claim its owner contract assigns to it.
2. **Storage is not authority.** A file does not become normative merely because it is in Git, a
   Builder Vault, a database, or a generated export.
3. **Presentation is not authority.** An item does not become normative merely because DevUI
   indexes, projects, ranks, or displays it.
4. **Derived representations inherit; they do not originate.** A derivative, mirror, index,
   search result, or DevUI view must preserve a resolvable link to its source and cannot gain more
   authority than that source.
5. **Promotion is explicit and governed.** Crossing from working, derived, or proposed material
   into a normative or otherwise stronger authority class requires an explicit review/decision,
   a target surface, and a durable receipt or equivalent repo evidence.
6. **Supersession is explicit.** A new artifact may replace an earlier artifact only when the
   relation, scope, reason, and effective authority are recorded. The older artifact remains
   inspectable unless a separate retention/erasure rule applies.
7. **Provenance survives every transformation.** Origin, transformation lineage, and decision/
   action accountability remain distinguishable, following ADR-0018.

## Authority domains and boundaries

| Domain or surface | What it may own | What it may not silently become |
| --- | --- | --- |
| Source / original artifact | What the external or human source says, within its scope | A universal interpretation of the source |
| Product/Runtime owner docs, ADRs, contracts, code, and tests | Accepted product meaning, architecture decisions, contracts, and shipped behavior according to each owner | A Builder working note or a DevUI-generated copy |
| Builder Vault working artifacts | Non-normative research, agent drafts, design explorations, comparisons, and intermediate products | Product/runtime truth, accepted architecture, or an executable task without promotion |
| BuilderOps operating plane | Builder worklogs, signals, proposals, operational state, and receipts under ADR-0010 | Product/runtime semantic truth or direct repo/GitHub mutation |
| GitHub Issues and PRs | The executable Builder task contract and delivery/review lifecycle for their bounded scope | Product/runtime semantic truth merely by being open, merged, or displayed |
| Generated projection / mirror | A rebuildable view over named sources, with freshness and limitations | A new source of truth or an authority upgrade |
| DevUI discovery/control plane | Read-time indexing, projection, navigation, source-state presentation, and links to governed actions | A docs portal, source registry, policy engine, task store, or promotion authority |
| Receipt / verification evidence | What a bounded transition, review, or verification observed and recorded | A replacement for the owner contract or proof of unrelated claims |

“Builder Vault” in this document means the working-artifact area for ephemeral or non-normative
Builder material. It is not a new authority above the existing BuilderOps Vault boundary. Where a
record is a BuilderOps operational object, ADR-0010 and
`docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md` remain authoritative for its object semantics.

## Canonical terms

These terms are cross-plane terms. A local owner may add narrower fields or states, but must not
reverse the meaning below without an accepted owner decision.

| Term | Cross-plane meaning | Authority consequence |
| --- | --- | --- |
| **Normative** | Accepted and owner-governed for a named scope; it can define requirements, architecture, policy, or current truth as its owner contract allows. | It is a source of authority only within that scope. |
| **Non-normative** | Useful, inspectable, and explicitly not a source of requirements or current truth. | It may inform a proposal but cannot authorize implementation or action by itself. |
| **Ephemeral** | Intended to be short-lived, disposable, or retained only for a bounded working episode. | Durability is low; it still needs provenance while it is used and must not gain authority from persistence. |
| **Derived** | Produced from one or more named sources by a transformation, synthesis, aggregation, or projection. | It must preserve lineage and cannot exceed source authority. |
| **Promoted** | Explicitly accepted at a governed boundary into a target surface or stronger authority class. | Promotion is a recorded transition, not a copy or a status inferred from location. |
| **Superseded** | Retained artifact whose active claim has been replaced for a named scope by an explicit successor. | It is historical/audit context, not current authority. |
| **Authority** | The bounded right to define, establish, or authorize a claim or transition for a named scope. | Authority is claim-, scope-, and owner-specific; it is not a storage or UI property. |
| **Projection** | A bounded, usually rebuildable representation for discovery, retrieval, reporting, or operation. | It must self-identify and link to source authority; rendering is not promotion. |
| **Provenance** | The inspectable record of origin, derivation, actor/tool/time, review, promotion, supersession, and relevant receipts. | Missing or ambiguous provenance withdraws the stronger claim; it never gets filled by inference. |

The terms are orthogonal. For example, an artifact can be `Derived + Non-normative + Ephemeral`,
or `Derived + Normative` when an accepted owner document deliberately owns the resulting claim.
`Promoted` describes a transition outcome; it is not a permanent synonym for `Normative`.

## Shared source → derivative → knowledge model

The same boundary applies to PKM and Builder work:

```text
source / capture
      │ identity + origin provenance
      ▼
derived representation or working artifact
      │ transformation + limitations + lineage
      ▼
reviewable synthesis / proposal
      │ explicit decision + target surface + receipt
      ▼
promoted knowledge, owner doc, Issue, PR, ADR, or governed projection
      │ implementation / verification evidence where applicable
      ▼
current accepted result ──explicit successor──> superseded / retired history
```

In PKM, a source note, transcript, or external source can produce summaries, claims, or synthesis
artifacts; only the existing human/memory authority paths can admit a stronger knowledge posture.
In Builder work, research and drafts can produce a proposal, Issue, ADR, owner-doc change, or PR;
the normal GitHub/repository authority path owns the resulting Builder or Product/Runtime truth.

The transformation is not allowed to erase the source, hide disagreement, or make a derivative
look independent when it is not. ADR-0018's split remains binding:

- artifact-origin provenance belongs to the relevant source/knowledge owner;
- action and decision provenance belongs to governed receipts; and
- derived semantic lineage belongs to the semantic/projection owner.

## Promotion boundary

Promotion must state, at minimum:

- the source artifact(s) and their versions or observation watermarks;
- the proposed target surface and authority class;
- what was transformed, omitted, or newly asserted;
- reviewer/decision-maker or governed process identity and time;
- acceptance, rejection, revision, or discard outcome;
- the receipt, PR, Issue, ADR, or owner-doc reference that records the transition; and
- any supersession or rollback relationship.

BuilderOps `PromotionIntent` and the promotion gateway may prepare and receipt the crossing, but
the target surface still performs its own normal authority action. DevUI may present or navigate to
that route; it does not execute or infer promotion.

## Reconciliation with existing owners

| Concern | Existing owner | This model's relationship |
| --- | --- | --- |
| Per-entity Product/Runtime authority flags | `docs/SEMANTIC_AUTHORITY_MATRIX.md` | Local semantic detail; this model adds the Builder/PKM cross-plane boundary. |
| Artifact, projection, and source-role meaning | `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` | Existing ontology wins; `Projection` and `Source` are reused, not redefined. |
| Human, agentic-memory, bridge, mirror, and companion lifecycles | `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` | Existing per-class lifecycle wins; this model supplies the shared cross-plane overlay. |
| Artifact metadata and derivation fields | `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` | Existing metadata contract wins; provenance must remain source-linked. |
| BuilderOps authority and promotion boundary | `docs/adr/ADR-0010-builderops-vault-authority-boundary.md` | Existing BuilderOps boundary wins; Builder Vault working material does not bypass it. |
| Provenance ownership split | `docs/adr/ADR-0018-provenance-split.md` | Binding split between origin, decision/action, and derived lineage. |
| Durable knowledge authority transition | `docs/architecture/authority-transition-flow.md` | Existing governed mutation path wins for Product/Runtime knowledge. |
| Owner-facing discovery and Builder System Control | `docs/DEVUI.md`, `docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md` | This model supplies the authority vocabulary that DevUI must display and navigate, not a second UI contract. |

## Adoption and non-goals

This is an accepted target-state baseline through the docs-authoring lane. Existing owner docs and ADRs
remain authoritative for local contract detail and current-state truth. This document
does not:

- create a new database, metadata schema, source registry, graph authority, or lifecycle engine;
- convert Builder Vault material into product/runtime memory or knowledge;
- claim that DevUI, Builder Vault, or any promotion path is fully implemented;
- replace existing Mimer, BuilderOps, GitHub, CI, review, merge, or receipt authority; or
- authorize further DevUI implementation by itself; implementation remains governed by the merged
  docs head and the bounded Issues' live readiness contracts.

Implementation gaps are recorded in the companion review audit and must become bounded Issues with
`Verify:` targets before execution.

## Related documents

- [`ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`](./ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md)
- [`DEVUI_DISCOVERY_ARCHITECTURE.md`](./DEVUI_DISCOVERY_ARCHITECTURE.md)
- [`SBS_OPERATING_MODEL.md`](./SBS_OPERATING_MODEL.md)
- [`docs/adr/ADR-0010-builderops-vault-authority-boundary.md`](../adr/ADR-0010-builderops-vault-authority-boundary.md)
- [`docs/adr/ADR-0018-provenance-split.md`](../adr/ADR-0018-provenance-split.md)
- [`docs/DEVUI.md`](../DEVUI.md)
- [`docs/audits/INFORMATION_AUTHORITY_ARTIFACT_LIFECYCLE_REVIEW_2026-08-17.md`](../audits/INFORMATION_AUTHORITY_ARTIFACT_LIFECYCLE_REVIEW_2026-08-17.md)
