State: Initial target-boundary register; enforcement status is intentionally conservative.
Doc role: Boundary register
Authority: Owns whether each target SBS boundary has a charter, contract, enforcement, and physical module posture.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-24
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/contracts/*.md

# SBS Boundary Register

This register tracks boundary maturity. It is not a package map and does not require immediate physical module creation.

The "Current modules" column lists concrete, existing `app/*` paths that currently embody that subsystem's
responsibility. These anchors describe present-day code — they are NOT target ownership claims and do NOT
imply the module belongs exclusively to the named subsystem. "Physical module?" maturity ratings are unchanged.
CES is a stewardship practice with no `app/*` embodiment; its anchor column is intentionally empty.

| Boundary | Owner | Charter exists? | Contract exists? | Enforced? | Physical module? | Current modules | Notes |
|---|---|---:|---:|---|---:|---|---|
| HIX - Human Interaction & Intent | Human Experience | Yes | Partial | Manual review now | No | `app/chat/intent_classifier.py` | UI/interaction docs exist; target IntentEnvelope remains future contract work. |
| WSP - Workspace, Scope & Principal Context | Cognitive Context & Topology | Yes | Yes | Manual review now | Partial | `app/vault/active_context.py` | `ACTIVE_CONTEXT_SET.md` defines target seam; current runtime may still use active vault/path concepts. |
| HKA - Human Knowledge & Artifact Substrate | Human Authority Kernel | Yes | Yes | Manual review now | Partial | `app/knowledge/vault_identity.py` | `ARTIFACT_CONTRACT.md` defines target survivability seam over current vault/companion artifacts. |
| SIP - Semantic Identity & Provenance Projection | Human Authority Kernel | Yes | Partial | Manual review now | No | `app/index/embeddings.py` | Semantic docs exist; target projection contract needs deeper lifecycle enforcement later. |
| GOV - Governance, Policy, Authority & Receipts | Human Authority Kernel | Yes | Yes | Partial current guards | Partial | `app/governance/governed_write.py` | `GOVERNED_WRITE_PROTOCOL.md` defines target DecisionToken/AuthorityReceipt seam; current WriteGuard/receipt paths are transitional. |
| EBF - External Boundary Fabric | External Boundary | Yes | Partial | Manual review now | Partial | `app/watcher/watcher.py` | Existing integration/tool/provider docs exist; source-observation payload contract remains future work. Watcher/source-observation delivery semantics are not owned here today; they link to SFC `REPLICATION_ENVELOPE.md`. |
| PDM - Persistence & Data Management | Machine Substrate | Yes | Yes | Manual review now | Partial | `app/db/db.py` | `STORE_PORT.md` defines target seam; current direct storage use must be checked during implementation work. |
| DRI - Derived Representation & Indexing | Machine Substrate | Yes | Partial | Manual review now | Partial | `app/indexer/consumer.py` | Existing embedding/retrieval docs cover pieces; target derived-representation contract remains future work. |
| RCA - Retrieval & Context Assembly | Cognitive Augmentation | Yes | Yes | Partial current contracts | Partial | `app/retrieval/context_bundle_conformance.py` | `CONTEXT_BUNDLE.md` and existing ContextBundle docs define non-authoritative retrieval outputs. |
| MEM - Machine Memory & Learning | Cognitive Augmentation | Yes | Yes | Partial current contracts | Partial | `app/agent_memory/memory_record.py` | `MEMORY_RECORD.md` defines review/provenance/promotion seam over existing memory docs. |
| CAO - Cognitive Capability & Agent Orchestration | Cognitive Augmentation | Yes | Yes | Manual review now | Partial | `app/agents/classify.py` | `CAPABILITY_CONTRACT.md` and `WORKFLOW_CONTRACT.md` define target cognitive and workflow seams. |
| EXE - Capability Execution & Automation | Governed Execution | Yes | Yes | Manual review now | Partial | `app/execution/execution_request.py` | `EXECUTION_REQUEST.md` defines side-effect seam after GOV authorization. |
| SFC - Synchronization, Federation & Consensus | Cognitive Context & Topology | Yes | Yes | Manual review now | No | `app/sfc/replication_envelope.py` | `REPLICATION_ENVELOPE.md` is the current owner contract for watcher/source-observation delivery semantics: idempotency, replay/backfill, ordering/causal placeholders, failure visibility, no-op/single-node V1, and future central/satellite upgrade path. |
| OEF - Observability, Evaluation & Fitness | Trust, Fitness & Evolution | Yes | Yes | Partial current CI | Partial | `app/fitness/metrics.py` | `SBS_FITNESS_RULES.md` owns target SBS fitness rules. |
| CES practice - Contract & Evolution Stewardship | Trust, Fitness & Evolution | Yes | Partial | Manual review now | No | _(stewardship practice — no `app/*` anchor)_ | ADRs, indexes, contracts, registers, PR template, and dependency rules are the practice surface. CES is Product SBS stewardship, not the entire Builder System; `SBS_OPERATING_MODEL.md` owns the Builder System boundary and authority model. |

## Status Vocabulary

- `Yes` means the target boundary is represented in repo documentation.
- `Partial` means current docs or code cover some required behavior but do not fully implement the target contract.
- `Manual review now` means the boundary is named but not yet mechanically enforced.
- `No` under physical module is acceptable until volatility or enforcement justifies a split.
