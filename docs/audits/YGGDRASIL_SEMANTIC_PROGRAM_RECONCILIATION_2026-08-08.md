State: Advisory semantic-program reconciliation snapshot, 2026-08-08. Repository evidence baseline: `origin/main` at `141db6ec61e69f3635a95eff34b20321840fca66`. Reconciliation is enacted only by the owner-document changes shipped with this review; this audit remains subordinate to those owners. No schema, migration, runtime rename, filesystem migration, or AI-memory change is authorized.
Doc role: Reference (semantic-review targets 2-14 and global reconciliation)
Authority: Evidence-based target-review synthesis. Current owner docs, accepted ADRs, and current runtime evidence win on disagreement.
Owner: Architecture spine / CES stewardship
Temporal class: advisory snapshot
Review cadence: superseded by a later accepted semantic baseline or a material change to the reviewed owners
Source of truth: cited owner docs, contracts, schemas, code, tests, and accepted ADRs at the baseline SHA
Last reviewed: 2026-08-08

# Yggdrasil Semantic Program Reconciliation

## 1. Outcome

This audit completes review targets 2-14 from the
[`Yggdrasil Ontological, Semantic, and Nomenclature Baseline`](YGGDRASIL_ONTOLOGICAL_SEMANTIC_BASELINE_2026-08-08.md),
after target 1 established the ontology-overlap rule. One persistent semantic-owner context retained
decision authority; bounded read-only workers extracted evidence for independent target clusters.

The global verdict is **conforms with four bounded documentation corrections and tracked transition
debt**. The ecosystem decision, current/target split, SBS allocations, functional-object boundaries,
authority chain, representation posture, and Builder/Product separation form a coherent semantic
model. The review found no reason to add an ontology, semantic database, subsystem, control boundary,
or global rename.

The owner changes shipped with this snapshot:

1. separate MEM `memory_state` from `promotion_state`;
2. normalize Companion UI's current Hugin/Munin routing to the accepted reserved-name lifecycle;
3. make the Heimdal entry point state current Mimer/Heimdal nomenclature rather than repeat the
   superseded split; and
4. align the derivative human-flow allocation map with all eight canonical loops.

Runtime and compatibility migrations remain Issue-backed work. Repository AI memory is not changed:
the requested sequence requires repo owner truth first and a separately authorized memory update.

### TCD plan

```yaml
tcd_plan:
  task_summary: complete semantic review targets 2-14 and enact the minimum coherent reconciliation
  assumptions: accepted ADRs and scoped owner docs remain authoritative; target contracts do not imply shipped enforcement
  complexity: very_high
  risk: high
  verification_difficulty: hard
  human_review_burden: low
  defect_blast_radius: high
  budget_pressure: low
  recommended_capability:
    workflow_or_skill: architecture-research -> docs-governance -> docs-authoring
    model_family: Sol semantic owner with bounded evidence workers
    reasoning_effort: xhigh synthesis; low bounded extraction
    tools: repository search, source-line verification, REST GitHub reconciliation, docs validation
    github_context_required: true
  cheapest_acceptable_path: one consolidated indexed audit plus minimal owner edits and non-duplicate Issue routing
  escalation_triggers: accepted-ADR conflict, SBS reshape, schema/runtime invariant change, or compatibility migration
  deescalation_triggers: source-anchored representation cleanup under an accepted owner rule
  review_gate: source verification, current-target classification, docs checks, current-head CI, and independent PR verification
```

## 2. Docs Governance Decision

```text
Docs Governance Decision:
- Artifact role: one advisory program-reconciliation snapshot plus corrections in existing owners
- Owner: Architecture spine / CES for the audit; existing semantic owners for enacted rules
- Action: create one indexed audit; update MEM, Heimdal routing, Companion UI normalization, and the derivative human-flow map
- Traceability: baseline targets 2-14 -> evidence reviews -> global reconciliation -> owner changes and bounded residual Issues
- DOCS_INDEX impact: add the audit row and refresh the four affected routing rows
- SBS/interface ownership: conforms; no subsystem, control-boundary, interface-owner, or runtime allocation change
- Next skill or no-change receipt: docs-authoring, then publish-pr and verification-and-closure
- Human Exception: none
```

## 3. Target-review ledger

| # | Target | Evidence-backed resolution | Disposition |
|---:|---|---|---|
| 2 | Ecosystem identity and nomenclature | ADR-0044 owns Yggdrasil apex, Mimer undivided knowledge/cognition, Heimdal sensor, Hugin/Munin reserved (`docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md:38-70`; `docs/GLOSSARY.md:26-29`). Active term-map/scaffold/history surfaces lag. | Correct current doc routing; route runtime/filesystem cleanup separately. |
| 3 | Current spine, target SBS, shipped runtime | The eight current subsystems bridge to fourteen target control boundaries; WSP/SFC/MEM/EXE are target refinements, not missing current modules (`docs/MODULAR_ARCHITECTURE.md:24-30,70-128`; `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md:39-65`). | Accept coexistence; preserve boundary-register maturity. |
| 4 | HKA-SIP-PDM | HKA owns durable human artifacts/anchors, SIP semantic identity/provenance, PDM physical persistence; DRI remains derived (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:542-646,758-810`). Current code proves identity continuity and storage isolation, not full target metadata-envelope adoption. | No owner contradiction; retain transition posture. |
| 5 | GOV-CAO-EXE | Target chain is proposal -> GOV decision token -> EXE request/effect -> state-owner mutation -> receipt. The orchestrator still permits `decision_token=None` (`app/execution/execution_request.py:1-45`; `app/orchestrator/executor.py:330-380`), explicitly non-conformant in the target effect-spine contract. | Semantic contract accepted; runtime adoption remains D6 transition debt. |
| 6 | DRI-RCA | DRI representations are rebuildable; RCA filters before ranking and assembles candidate evidence, never truth (`docs/boundaries/DRI.md:14-35`; `docs/boundaries/RCA.md:18-78`). Live scope prefiltering and bounded context envelopes implement a compatible subset. | No semantic change; retain schema/runtime maturity distinction. |
| 7 | MEM | The canonical model separates existence/recall, visibility, and promotion (`docs/architecture/memory-model.md:31-70,99-132`). MEM charter collapsed promotion into `memory_state`. | Owner correction enacted. Current review/WriteGuard/materialization path remains transitional. |
| 8 | WSP-SFC | Workspace/scope/principal/device/replica are distinct; bindings and sync state confer neither identity nor authority (`docs/contracts/ACTIVE_CONTEXT_SET.md:18-40,58-102`; `docs/contracts/REPLICATION_ENVELOPE.md:63-105`). | No semantic change; typed cross-scope and broader replication remain partial. |
| 9 | HIX/UI/design | HIX owns interaction semantics; Panel, Chat, and Automation are the three surfaces. UI is presentation, never domain authority (`docs/boundaries/HIX.md:14-53`; interaction-surface owner). Current Hugin/Munin normalization contradicted ADR-0044. | Current term-map correction enacted; dated design history remains historical. |
| 10 | EBF/Heimdal/events | EBF normalizes external mechanisms and observations without granting authority; current `OutboxEvent` is operational, while `SourceObservationEvent` plus `ReplicationEnvelope` adds delivery semantics to one watcher seam (`docs/boundaries/EBF.md:13-50`; `docs/EVENTS.md:22-59,783-811`). Heimdal publishes append-only candidate evidence. | Correct Heimdal index routing; no event-contract change. |
| 11 | OEF/CES | OEF observes/evaluates but cannot decide; CES stewards architecture evolution but is neither runtime nor Builder System (`docs/boundaries/OEF.md:1-79`; `docs/boundaries/CES.md:1-91`). Enforcement is deliberately mixed CI/manual. | Accept; no general lifecycle registry needed. |
| 12 | Capability/function allocation | HUMAN-FLOWS owns human functions; the runtime map is derivative and explicitly not an FBS. CKM's capability tree is a BuilderOps projection, not a runtime registry. | Update loop inventory and missing allocation rows; keep synthetic IDs rejected. |
| 13 | Builder System and projections | GitHub/CI/merge prove delivery; BuilderOps coordinates; CKM/Cockpit/devUI/Project/Signboard render non-authoritative views (`docs/architecture/SBS_OPERATING_MODEL.md:70-161`; ADR-0010; `docs/DEVUI.md:39-53,242-260`). | Accept layered vocabulary; preserve Product/Builder separation. |
| 14 | Global reconciliation | Scoped owners agree once current, target, historical, operational, derived, and Builder representations are kept distinct. | Minimum owner changes above; no global ontology reshape. |

## 4. Accepted compact semantic state

```yaml
accepted_reconciliation:
  repository_baseline: 141db6ec61e69f3635a95eff34b20321840fca66
  ecosystem: Yggdrasil apex; Mimer knowledge-and-cognition; Heimdal sensor; Hugin/Munin reserved
  structure: current runtime spine and target SBS coexist through the explicit crosswalk
  meaning: scoped owner graph; Cognitive Ontology general human meaning; Functional Ontology Mimer system consequences
  representation: artifacts and accepted knowledge are distinct from semantic graph, storage, projections, retrieval, memory, events, and UI views
  authority: intent/proposal is not authorization; DecisionToken precedes governed effects; receipt records accountability afterward
  memory: memory_state, suppression_state, and promotion_state are orthogonal
  context: workspace, scope, principal, device, node, replica, and source binding do not collapse
  delivery: BuilderOps and UI projections do not become Product/Runtime or GitHub delivery authority
```

## 5. Cross-cutting invariants retained

- Current shipped truth, target architecture, and historical provenance always carry explicit status.
- External observation, retrieval, memory, event transport, Builder evidence, and UI presentation do
  not become accepted knowledge or authority by being represented.
- Identity, meaning, provenance, storage, derived representation, and topology remain separately owned.
- Human intent, agent proposal, policy decision, execution effect, durable mutation, and receipt remain
  distinct artifacts in the governed chain.
- Source/scope/workspace/device/replica fields describe different axes; none silently grants access.
- A capability is surface-independent behavior, not an agent, UI component, tool, service, or CKM row.
- Semantic evolution is explicit through owner-doc change, accepted ADR precedence, compatibility
  marking, and verification; it is never inferred from occurrence count.

## 6. Residuals and Issue routing

The following are implementation or compatibility work, not unresolved semantic decisions:

| Residual | Existing authority / route | Program disposition |
|---|---|---|
| Broad DecisionToken-bearing ExecutionRequest adoption | SBS debt D6 and fitness rail; prior containment slice #2361 is closed | Reconcile live backlog before creating a follow-up; do not misreport the current optional-token path as target-conformant. |
| Active scaffold directories `Hugin`, `Munin`, and `Heimdall` | `app/settings/mimer_scaffolder.py`; compatibility-sensitive filesystem output | [Issue #4674](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4674) owns the non-destructive new-root cleanup and focused tests. |
| Visible Hugin labels in checked-in Companion UI prototype/runtime assets | Accepted ADR-0044 plus corrected term map | [Issue #4675](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4675) owns active-copy normalization; dated handoff history remains historical. |
| Retrieval/context, cross-scope, memory-promotion, replication, and derived-envelope partial adoption | SBS debts D1/D4/D5/D6/D7/D9/D10 and current boundary register | Reuse existing debt and active feature Issues; no duplicate semantic-program Issue. |
| BuilderOps local/target control-plane layering | ADR-0062 and BuilderOps owner docs | No Product semantic change; keep projection watermarks and separate delivery authority. |
| Persistent AI memory | External to repository owner truth | No mutation in this program. A later explicit request may replace volatile names with a current-owner-doc pointer. |

## 7. Verification and next baseline

The candidate reconciliation must pass:

1. docs index and link/reference guards;
2. focused architecture and documentation tests selected by the repository validation workflow;
3. grep/readback proving no current owner surface introduced Hugin/Munin as active modules;
4. live Issue duplicate reconciliation for executable residuals;
5. current-head CI and the proportional verification gate; and
6. post-merge owner-doc review.

A later dated baseline may supersede this snapshot after material ecosystem/SBS/ontology change or
after the compatibility cleanup ships. It should read the reconciled owner surfaces rather than
copying this audit as authority.
