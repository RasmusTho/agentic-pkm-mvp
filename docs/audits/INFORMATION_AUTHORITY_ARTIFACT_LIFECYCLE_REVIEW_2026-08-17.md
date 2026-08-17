State: Advisory architecture/governance review snapshot (2026-08-17). The three companion design artifacts are proposed target-state inputs and remain subordinate to existing accepted owner docs and ADRs until owner acceptance.
Doc role: Reference (bounded architecture review and backlog handoff)
Authority: Evidence-based cross-plane analysis of information authority, artifact classification/lifecycle, provenance, promotion, and DevUI discovery. The review changes no runtime, schema, GitHub lifecycle, or authority by itself.
Owner: Builder System / CES boundary, with Product/Runtime semantic owners retaining local authority
Temporal class: snapshot
Review cadence: event-driven after owner disposition, acceptance of the companion artifacts, or material DevUI/BuilderOps/PKM authority change
Source of truth: `docs/DOCS_INDEX.md`, accepted ADRs, current owner docs, and live GitHub state; the companion artifacts are the proposed cross-plane writeback.
Repository baseline: `origin/main` at `d69028084` (2026-08-17)
Last reviewed: 2026-08-17

# Information Authority & Artifact Lifecycle Review — 2026-08-17

## 1. Charter and bounded scope

This review preserves and operationalizes the decision that:

1. DevUI is a discovery/control plane, not a separate docs portal.
2. Builder Vault is the working home for non-normative and ephemeral material such as research,
   agent drafts, design explorations, and intermediate products.
3. Authority, provenance, derivation, projection, promotion, supersession, and lifecycle must remain
   explicit and claim-scoped.
4. The same source → derivatives → provenance → promoted knowledge rule applies in PKM and Builder
   work.
5. No DevUI implementation should proceed across this boundary until the review and its three
   companion design artifacts are accepted through the docs-as-code review path.

The review is intentionally limited to information authority and artifact lifecycle. It does not
redesign the Product/Runtime ontology, add a metadata schema, implement Builder Vault storage, or
replace the existing DevUI/BSC/FCP/Stage-A contracts.

## 2. Docs Governance Decision

```text
Docs Governance Decision:
- Artifact role: advisory cross-plane architecture/governance review plus proposed target-state design artifacts
- Owner: Builder System / CES boundary for the cross-plane boundary; existing Product/Runtime and BuilderOps owners retain local authority
- Action: create one indexed audit and three indexed architecture design records; add routing cross-links to existing owner docs; do not change DevUI implementation
- Traceability: conversation decision -> live owner-doc reconciliation -> companion artifacts -> bounded implementation issues after acceptance
- DOCS_INDEX impact: add rows for the audit and all three architecture records
- SBS/interface ownership: conforms to the existing Builder System boundary and devUI owner contract; no SBS reshape; DevUI remains a projection/navigation boundary over existing sources
- Next skill or no-change receipt: docs-authoring now; docs-to-issue after owner acceptance for bounded implementation gaps; #4982 remains the unified UI/UX handoff owner
- Human Exception: owner acceptance is required before the proposed cross-plane artifacts become normative; until then existing owner docs win
```

## 3. Evidence read and current authority

| Question | Current evidence | Finding |
| --- | --- | --- |
| Is DevUI already defined as a new docs portal? | `docs/DEVUI.md :: One owner experience, internal capability providers`; `docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md :: Explicit non-authority`; `docs/audits/DEVUI_ARCHITECTURE_2026-08-06.md` | No. DevUI is already a target owner-facing umbrella and BSC is a read-time/rebuildable lens. The explicit “discovery, not docs portal” cross-plane rule was not yet a standalone owner artifact. |
| Is Builder working material protected from product truth? | `docs/adr/ADR-0010-builderops-vault-authority-boundary.md :: Decision`, `:: Raw worklog boundary`; `docs/architecture/SBS_OPERATING_MODEL.md :: Builder-Agent Authority Model` | Yes for BuilderOps authority, but “Builder Vault” as the ephemeral research/draft area and its relation to DevUI discovery was not named in one cross-plane model. |
| Does PKM already distinguish artifact, projection, source, and lifecycle? | `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`; `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`; `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` | Yes, with strong local contracts. They do not define the Builder ↔ PKM shared lifecycle overlay requested here. |
| Is promotion explicit? | `docs/SEMANTIC_AUTHORITY_MATRIX.md :: Reading rules`; `docs/adr/ADR-0018-provenance-split.md`; `docs/architecture/authority-transition-flow.md`; `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md` | Yes. The rule is distributed across Product/Runtime and BuilderOps owners; the new model makes the same rule discoverable without redefining it. |
| Is source → derivative → promoted knowledge already present? | `docs/AGENT-FLOWS.md :: 7. Zones` and `:: 8. Continuous knowledge compilation`; `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` | Yes in PKM flow language. The Builder flow and shared terms were not recorded alongside it. |
| Is a unified DevUI implementation already delivered? | `docs/DEVUI.md :: Current state and target`; live #4982 and #4741 | No. Current delivery is split across read-only providers/composers and incomplete target slices. This review must not be read as UI delivery. |

## 4. Research questions and resolutions

### RQ1 — What makes an artifact authoritative?

Authority is a scoped right assigned by an existing owner contract or an explicit governed
transition. Storage, Git, issue closure, indexing, display, model output, and recency do not create
authority. The proposed `INFORMATION_AUTHORITY_MODEL.md` makes this cross-plane rule explicit and
points to the existing local owners.

### RQ2 — How should Builder Vault relate to PKM artifacts?

Builder Vault is a non-normative working surface for research, drafts, explorations, and
intermediate products. It may preserve provenance and support proposals, but it does not become
Product/Runtime knowledge, a normative repo doc, or an executable task without explicit promotion.
PKM's HKA/MEM/GOV paths and BuilderOps' PromotionIntent/gateway remain separate target authorities.

### RQ3 — Which lifecycle is shared without inventing a universal state machine?

The shared handoff vocabulary is:

`Capture → Explore → Synthesize → Propose → Promote → Implement → Verify → Supersede/Retire`.

It is an overlay, not a replacement for Mimer memory states, Contextualization artifact states,
BuilderOps lifecycle states, or GitHub Issue/PR lifecycle. Each surface can stop at the stage it
owns, so a projection or draft cannot silently be treated as promoted knowledge.

### RQ4 — What may DevUI do?

DevUI may index, project, label, explain, and navigate to the source or an existing governed
workflow. It may not become a docs portal, alternate editor, source registry, task store, graph
authority, policy engine, or promotion executor. The discovery contract must preserve source refs,
authority class, lifecycle, freshness, provenance, and limitations.

### RQ5 — What is the gate before further DevUI implementation?

The review and three companion artifacts must be accepted via the normal docs-authoring PR path.
After acceptance, implementation is issued as bounded read-only discovery/projection and separate
Builder Vault classification/promotion slices, reconciled with live #4982. This review itself does
not modify DevUI code or unblock existing Issues.

## 5. Findings and invariant kernel

| ID | Invariant | Category | Existing posture |
| --- | --- | --- | --- |
| IAL-01 | A stored or displayed artifact does not gain authority from location or presentation. | MUST | Exists in ADR-0010, `SEMANTIC_AUTHORITY_MATRIX`, BSC; cross-plane wording is new. |
| IAL-02 | A projection/derivative self-identifies, preserves source lineage, and cannot exceed source authority. | MUST | Exists in ADR-0018, ADR-0033, metadata/projection contracts; DevUI composition already follows this in bounded paths. |
| IAL-03 | Promotion is an explicit, target-bound, receipt-bearing transition. | GATE | Exists in AuthorityTransition and BuilderOps promotion gateway; needs shared cross-plane acceptance language. |
| IAL-04 | Builder Vault research/drafts/explorations remain non-normative and ephemeral/rebuildable by default. | GATE | Partial: BuilderOps raw/analytical/staged classes exist; the requested Builder Vault working label and discovery treatment are new. |
| IAL-05 | Provenance distinguishes origin, derivation, decision/action, and supersession. | MUST | Exists through ADR-0018 and local contracts; needs one shared discovery envelope. |
| IAL-06 | DevUI navigation is typed source navigation, not a new docs, task, graph, or authority store. | GATE | Partial: `docs/DEVUI.md` and BSC forbid authority; standalone discovery architecture is new. |
| IAL-07 | Missing, stale, unavailable, unread, refused, or unlinked evidence withdraws only the dependent claim. | DOCTOR | Existing BSC/Overview source-state contracts; apply to the new cross-plane discovery envelope. |
| IAL-08 | Supersession/retirement is explicit and retains historical provenance unless a separate erasure rule applies. | DOCTOR | Existing in BuilderOps object lifecycle and PKM lifecycle; shared overlay is new. |

Minimal kernel: IAL-01 through IAL-04 carry the authority claim; IAL-05 through IAL-08 are the
traceability and fail-closed defense in depth required for an inspectable projection.

## 6. SBS reconciliation

This review **conforms to** the existing SBS rather than reshaping it:

- It classifies the work as Builder System / CES boundary work because it governs builder research,
  repo-authority crossings, and devUI discovery.
- It does not introduce a Product/Runtime SBS subsystem, a new CAO/MEM/HKA owner, or a second
  BuilderOps control plane.
- It keeps Product/Runtime semantics with Mimer owner docs and keeps Builder System governance with
  `docs/architecture/SBS_OPERATING_MODEL.md`, ADR-0010, and the BuilderOps object/gateway docs.
- DevUI remains an owner-facing projection/navigation shell; existing GitHub/CI/review/merge/closure
  authority is unchanged.
- Any future change to a Product/Runtime contract or to the SBS must route through its own owner
  doc/ADR and Issue; this review cannot enact it.

## 7. Backlog reconciliation and bounded gaps

| Candidate gap | Disposition | Existing owner/issue | Next bounded action |
| --- | --- | --- | --- |
| Cross-plane authority/lifecycle model | This review + three companion docs | Existing ADRs and owner docs remain local authority | Accept this docs-authoring PR; no duplicate parent issue. |
| Unified DevUI owner-facing architecture and UX handoff | Reuse, do not duplicate | #4982 owns the nine-layer process-to-UI map and governed handoff; #4980 owns process health | Add the new discovery boundary as a source input to #4982; keep #4980 separate. |
| PKM source lineage/evidence independence | Reuse, do not duplicate | #4906 owns source-lineage/evidence-independence validation | Cross-reference only; no new Product/Runtime issue here. |
| Builder Vault artifact capture/classification/provenance | New bounded Builder System implementation gap | Existing BuilderOps object model/boundary/gateway provide mechanics but no generic working-artifact admission contract | #4984 is filed `agent:blocked`; after owner acceptance, refine/readiness-check it for explicit non-normative working-artifact intake over existing BuilderOps surfaces. |
| DevUI authority-aware discovery projection/navigation | New bounded downstream gap | #4982 owns the unified UX handoff; existing Overview/BSC contracts own provider projections | #4985 is filed `agent:blocked`; after owner acceptance, refine/readiness-check it for a read-only projection consuming existing source contracts; no new source registry or docs store. |
| Governed promotion enforcement beyond proposal/receipt mechanics | Reconcile before filing | ADR-0010 and `BUILDEROPS_PROMOTION_GATEWAY.md` already own proposal-only mechanics; target surfaces own actual promotion | Do not file a duplicate gateway issue. File only a concrete missing target-surface adapter if live evidence identifies one. |

The two new implementation Issues are filed as explicitly blocked follow-ups (#4984 and #4985) now
that the docs-authoring PR exists. They must remain blocked until the proposed artifacts are accepted.
Their source anchors and `Verify:` targets must point to the accepted docs, not to this advisory audit
alone, before either Issue can become agent-ready.

## 8. Review acceptance gate

Before a DevUI implementation Issue may consume this model, the acceptance record must show:

- the exact merged docs-only PR head;
- owner review/acceptance of the three companion artifacts;
- `docs/DOCS_INDEX.md` rows for the artifacts and this audit;
- successful `docs_guard.py`, the relevant docs-index/spec tests, and `git diff --check` on that head;
- live reconciliation of #4982, #4980, #4906, and relevant DevUI issues; and
- no new claim that DevUI UI/runtime, Builder Vault discovery, or promotion execution is delivered.

## 9. Related documents

- [`../architecture/INFORMATION_AUTHORITY_MODEL.md`](../architecture/INFORMATION_AUTHORITY_MODEL.md)
- [`../architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`](../architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md)
- [`../architecture/DEVUI_DISCOVERY_ARCHITECTURE.md`](../architecture/DEVUI_DISCOVERY_ARCHITECTURE.md)
- [`../DEVUI.md`](../DEVUI.md)
- [`../DEVUI_BUILDER_SYSTEM_CONTROL/README.md`](../DEVUI_BUILDER_SYSTEM_CONTROL/README.md)
- [`../adr/ADR-0010-builderops-vault-authority-boundary.md`](../adr/ADR-0010-builderops-vault-authority-boundary.md)
- [`../adr/ADR-0018-provenance-split.md`](../adr/ADR-0018-provenance-split.md)
- [`../SEMANTIC_AUTHORITY_MATRIX.md`](../SEMANTIC_AUTHORITY_MATRIX.md)
- [`../AGENT-FLOWS.md`](../AGENT-FLOWS.md)
- Live downstream issues: #4982, #4980, #4906, #4915
