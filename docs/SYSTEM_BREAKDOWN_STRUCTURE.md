State: Target-state SBS V2 for 2030 resilience; docs-only strategic architecture; does not claim shipped runtime behavior.
Doc role: Core SoT / strategic architecture reference
Authority: Target System Breakdown Structure for Yggdrasil as a long-lived human-first cognitive platform. This document owns the enduring subsystem decomposition, two-level SBS, volatility boundaries, and change-impact model for long-horizon architecture. It is subordinate to `docs/PROJECT_KERNEL.md` and `docs/COGNITIVE_PROSTHESIS_CHARTER.md` on product intent, and subordinate to `docs/ARCHITECTURE.md` / `docs/STATUS.md` on current shipped behavior. It intentionally generalizes beyond current vault, Obsidian, retrieval, memory, storage, UI, sync, and agent-runtime choices.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21
Last verified against: docs/PROJECT_KERNEL.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md, docs/DESIGN_PRINCIPLES.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/CONCEPTS/PORTABILITY_CONTRACT.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md

# Yggdrasil System Breakdown Structure

This document defines the target System Breakdown Structure (SBS) for Yggdrasil as a long-lived human-first cognitive platform.

It is not a review of the current repository structure. It is not a service map, package map, deployment diagram, API inventory, or delivery plan. It defines enduring responsibilities that should still be recognizable in 2030 even if most implementation choices have been replaced.

The central design question is:

> If a major implementation choice changes in three years, how much of the system must be redesigned?

The preferred answer is:

> One control-boundary subsystem, plus stable interface adapters.

## Part 1 - Executive Summary

The recommended SBS V2 is a two-level architecture:

1. Eight macro-domains for human comprehension and documentation navigation.
2. Fourteen Level-2 control-boundary subsystems for change isolation, plus one cross-cutting contract-stewardship discipline.

This structure intentionally combines three useful perspectives:

- Authority-first architecture: Yggdrasil's long-term integrity depends on preventing hidden authority escalation.
- Change-isolation architecture: high-volatility seams must have named owners so replacement does not become a platform rewrite.
- Current-spine continuity: the existing system-of-systems document remains the bridge from the current runtime mental model to this target decomposition.

The target SBS V2 is not a compromise average. It is hierarchical: small enough at Level 1 for humans to navigate, precise enough at Level 2 for implementation replacement and AI-agent work routing.

The Level-2 boundaries are target control boundaries, not a command to instantiate fourteen teams, services, packages, owner docs, or runtime components on day one. Commit now to the eight macro-domains, dependency rules, and boundary litmus tests. Split a macro-domain into a distinct Level-2 implementation surface when a second independent volatility clock proves that the separation reduces TCD.

### Level 1 macro-domains

| L1 | Macro-domain | Purpose |
| --- | --- | --- |
| 1 | Human Authority Kernel | Durable human knowledge, semantic identity, provenance, authority, policy, and receipts. |
| 2 | Cognitive Context & Topology | Workspace, scope, active context, principal context, deployment posture, synchronization, and federation. |
| 3 | Human Experience | Human intent, review, correction, navigation, approval, rejection, and explanation surfaces. |
| 4 | External Boundary | Sources, adapters, providers, tools, egress, and external trust boundaries. |
| 5 | Machine Substrate | Persistence, derived representations, indexes, projections, and rebuildable machine artifacts. |
| 6 | Cognitive Augmentation | Retrieval, context assembly, memory, learning, capabilities, agents, and workflows. |
| 7 | Governed Execution | Authorized side effects, tool actuation, automation effects, preview, dry run, and rollback. |
| 8 | Trust, Fitness & Evolution | Observability, audit visibility, evaluations, architecture contracts, compatibility, and evolution discipline. |

### Level 2 control-boundary subsystems

| ID | Subsystem | Macro-domain | Enduring responsibility |
| --- | --- | --- | --- |
| HIX | Human Interaction & Intent | Human Experience | Human-facing surfaces, intent capture, review, approval, correction, explanation, and navigation. |
| WSP | Workspace, Scope & Principal Context | Cognitive Context & Topology | Active cognitive context as a governed set of bindings, not a scalar active vault. |
| HKA | Human Knowledge & Artifact Substrate | Human Authority Kernel | Durable human-authored and human-accepted knowledge artifacts that survive machine loss. |
| SIP | Semantic Identity & Provenance | Human Authority Kernel | Rebuildable semantic identity/provenance graph, ontology, relation vocabulary, lineage, attribution views, and semantic continuity. |
| GOV | Governance, Policy, Authority & Receipts | Human Authority Kernel | Admissibility, delegation, policy, authority, approval, accountability, and receipts. |
| EBF | External Boundary Fabric | External Boundary | Boundary adapters for sources, providers, tools, editors, parsers, models, embeddings, and egress. |
| PDM | Persistence & Data Management | Machine Substrate | Storage technology abstraction, migrations, backups, restore, data lifecycle, and store health. |
| DRI | Derived Representation & Indexing | Machine Substrate | Rebuildable embeddings, chunks, indexes, projections, mirrors, relation overlays, and invalidation. |
| RCA | Retrieval & Context Assembly | Cognitive Augmentation | Moment-specific search, ranking, evidence selection, citation basis, and context bundles. |
| MEM | Machine Memory & Learning | Cognitive Augmentation | Inspectable machine memory, review, promotion, recall, correction, decay, forgetting, and feedback. |
| CAO | Cognitive Capability & Agent Orchestration | Cognitive Augmentation | Reusable cognition, agent roles, planning, workflows, proposals, and non-side-effecting orchestration. |
| EXE | Capability Execution & Automation | Governed Execution | Side-effecting execution after authorization, tool actuation, automation effects, previews, and rollback. |
| SFC | Synchronization, Federation & Consensus | Cognitive Context & Topology | Node identity, replicas, sync state, causal ordering, conflict handling, convergence, and distributed receipts. |
| OEF | Observability, Evaluation & Fitness | Trust, Fitness & Evolution | Traces, health, metrics, evaluations, drift detection, audit visibility, and architecture fitness. |

Cross-cutting stewardship practice:

| ID | Practice | Macro-domain | Enduring responsibility |
| --- | --- | --- | --- |
| CES | Contract & Evolution Stewardship | Trust, Fitness & Evolution | Subsystem charters, interface versioning, compatibility, ADRs, dependency rules, and deprecation discipline. |

CES is not a runtime subsystem, peer implementation boundary, or the full continuous-development
Builder System. It is architecture, documentation, and CI discipline for Product SBS contracts. The
Builder System boundary and authority model live in `docs/architecture/SBS_OPERATING_MODEL.md`;
builder agents, repo-local skills, delivery workflows, BuilderOps records, and TCD routing use CES
practice surfaces when they change Product contracts, but they do not become CES-owned runtime
subsystems. Without explicit contract stewardship, the SBS will decay back into implementation
structure; with too much stewardship machinery, it becomes compliance overhead. Keep it lean.

### Major conclusions

- Authority is the primary invariant. Human authority, agent authority, automation authority, external-system authority, governance authority, memory, retrieval, execution, policy, and provenance must not collapse.
- Active context is a governed set of bindings, not `activeVault: VaultId`.
- Human knowledge survivability depends on minimal durable identity anchors and origin-provenance stamps living with the human artifact, not only in a separate semantic graph.
- Governance owns admissibility and accountability, not every write mechanism. Use a hard-enforced governed write protocol, not a Governance god-core.
- Synchronization, federation, and consensus need a first-class home now. Its first implementation can remain a single-node no-op until a second write-capable node is actually scheduled.
- Persistence and derived representation are separate. Storage technology and rebuildable machine structure change on different clocks.
- Retrieval, memory, capabilities, agent orchestration, and side-effecting execution must remain separate because they evolve differently and carry different authority risks.
- Vaults, folders, editors, model providers, embedding providers, storage engines, sync transports, and agent runtimes are replaceable mechanisms, not the architecture's identity.

The strongest final boundary set is:

`Human knowledge anchors != semantic graph != workspace/topology != governance/authority != memory != retrieval != derived representation != persistence != agent orchestration != execution != external integration != sync/federation != UI != observability`.

### Target-state posture and non-goals

This SBS is adopted as target-state architecture. It does not claim shipped runtime behavior, current module structure, or current enforcement. Current runtime behavior remains owned by `docs/ARCHITECTURE.md` and `docs/STATUS.md`; transition from current to target is owned by `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`.

Non-goals:

- Do not create fourteen new physical modules immediately.
- Do not rewrite the system to no-vault now.
- Do not remove Obsidian now.
- Do not build full distributed consensus now.
- Do not make GOV a general mechanism god-core.
- Do not let OEF become an automatic control loop.
- Do not claim target-state architecture as shipped behavior.
- Do not reorganize the repository solely to mirror the SBS.
- Do not treat this as an implementation refactor before docs, contracts, and issues are resident.

### Settled decisions

The durable decision records for this SBS are:

- `docs/adr/ADR-0015-authority-first-target-sbs.md` - adopts the authority-first, volatility-disciplined target SBS.
- `docs/adr/ADR-0016-contract-first-module-lazy-sbs.md` - adopts contract-first, module-lazy instantiation.
- `docs/adr/ADR-0017-human-knowledge-and-governance-survivability.md` - preserves one irreplaceable human knowledge set plus durable governance receipts.
- `docs/adr/ADR-0018-provenance-split.md` - splits provenance into artifact-origin, action/decision, and derived semantic lineage.
- `docs/adr/ADR-0019-governed-writes-decision-token-authority-receipt.md` - requires DecisionToken and AuthorityReceipt for authority-bearing durable writes.
- `docs/adr/ADR-0020-sfc-single-node-upgrade-path.md` - declares SFC now with a single-node/no-op V1 posture.
- `docs/adr/ADR-0021-ces-architecture-stewardship-practice.md` - keeps CES as architecture stewardship practice, not a runtime peer subsystem.
- `docs/adr/ADR-0022-oef-first-class-non-authoritative.md` - treats OEF as first-class but non-authoritative.

## Part 2 - Candidate Decomposition Strategies

### Strategy A - Authority-spine decomposition

Example decomposition:

1. Human Knowledge Substrate.
2. Context & Scope Authority.
3. Derived Representation Engine.
4. Cognitive Capability Runtime.
5. Agent Memory & Continuity.
6. Governance & Authority Core.
7. Interaction & Intent Surface.
8. Integration & Egress Fabric.

Strengths:

- Correctly treats authority as the deepest Yggdrasil boundary.
- Preserves the durable/rebuildable line.
- Names hidden authority escalation as the central architectural failure mode.
- Recognizes that scope must become richer than a scalar active vault.
- Introduces the principal axis early, which matters for family, shared, and enterprise-like futures.

Weaknesses:

- Too compressed for the 5 to 10 year TCD goal.
- Integration/Egress combines unrelated volatility vectors: source observation, providers, tools, sync, transport, topology, remote peers, and deployment placement.
- Derived Representation combines storage, projections, indexes, embeddings, rebuild pipelines, and relation graphs.
- Governance can be misread as the subsystem that physically performs every durable write.

Use in final SBS:

- Keep as the authority spine.
- Split overloaded boxes along volatility boundaries.
- Reframe "single durable write chokepoint" as "governed write protocol."

### Strategy B - Flat change-isolation decomposition

Example decomposition:

1. Human Interaction System.
2. Knowledge Artifact System.
3. Context and Ontology System.
4. Governance, Policy, and Authority System.
5. Workspace Topology and Configuration System.
6. Ingestion, Sync, and Replica System.
7. Projection, Storage, and Index System.
8. Retrieval and Context Assembly System.
9. Memory and Learning System.
10. Cognitive Capability System.
11. Agentic Execution and Automation System.
12. Integration Adapter Fabric.
13. Observability, Evaluation, and Fitness System.

Strengths:

- Identifies many seams that will hurt: UI replacement, active workspace changes, retrieval replacement, memory replacement, agent-runtime replacement, integration replacement, and observability.
- Separates retrieval and memory.
- Separates reusable capabilities from agents.
- Separates workspace topology from knowledge artifacts.
- Makes Observability/Evaluation/Fitness a first-class trust subsystem.

Weaknesses:

- Too flat for human comprehension and documentation navigation.
- Some ownership overlaps remain: Knowledge vs Ontology, Governance vs Observability, Workspace vs Context, Integration vs Ingestion/Sync, Projection vs Storage, Capabilities vs Execution.
- Central/satellite deployment is under-modeled; multi-write, offline-capable deployment has causal ordering, conflict, receipt, principal, and audit-reconstruction problems.

Use in final SBS:

- Keep the operational completeness.
- Add hierarchy.
- Split storage from derived representation.
- Split source/external boundary from synchronization/federation.
- Split agent orchestration from side-effecting execution.

### Strategy C - Current repository system-of-systems spine

Current repository decomposition:

1. Human Surface.
2. Knowledge & Artifact.
3. Runtime Projection.
4. Capability.
5. Agent / Orchestration.
6. Governance / Authority.
7. Integration Fabric.
8. Observability / Fitness.

Strengths:

- Best current adoption bridge.
- Reflects the present architecture language and documentation ecosystem.
- Kernel vs extension fabric is a strong mental model.
- Correctly distinguishes human surface, knowledge, runtime projection, capabilities, agents, governance, integration, and observability.

Weaknesses:

- Too current-runtime-shaped for the 2030 SBS.
- Vault-first language is too central for the target state.
- No explicit workspace/scope/topology subsystem.
- No explicit memory subsystem.
- Runtime Projection is too broad.
- Capability vs Agent vs Execution is under-specified.
- Distribution is not structurally represented.

Use in final SBS:

- Preserve as the bridge from current implementation to target decomposition.
- Treat this SBS as the long-horizon target above it.

### Selected synthesis

The selected SBS V2 is a hierarchical systems-of-systems decomposition:

- Use Level 1 macro-domains for comprehension.
- Use Level 2 control-boundary subsystems for change isolation.
- Use authority boundaries as the primary invariant.
- Use volatility to split compressed subsystems.
- Keep the repository's current eight-subsystem map as a bridge, not as the target 2030 decomposition.
- Treat CES as a cross-cutting stewardship practice, not a runtime subsystem.
- Avoid a 14-boundary big bang: instantiate a distinct Level-2 implementation surface only when a second independent volatility clock justifies the split.

## Part 3 - Proposed Yggdrasil SBS

### Level 1 macro-domains

#### 1. Human Authority Kernel

Purpose:

Preserve the human-first core: durable knowledge, semantic identity, provenance, authority, policy, and accountability.

Contains:

- HKA - Human Knowledge & Artifact Substrate.
- SIP - Semantic Identity & Provenance.
- GOV - Governance, Policy, Authority & Receipts.

Rationale:

If this macro-domain weakens, Yggdrasil stops being a human-first cognitive platform and becomes a collection of tools that can silently reinterpret or mutate human meaning.

#### 2. Cognitive Context & Topology

Purpose:

Represent where cognition is happening, for whom, under which scope, on which nodes or replicas, and under which deployment posture.

Contains:

- WSP - Workspace, Scope & Principal Context.
- SFC - Synchronization, Federation & Consensus.

Rationale:

Vaults, roots, workspaces, nodes, replicas, cloud spaces, and devices are not the identity of cognition. They are bindings in the active context and deployment topology.

#### 3. Human Experience

Purpose:

Provide the human-facing surfaces where intent, review, correction, approval, rejection, navigation, and explanation happen.

Contains:

- HIX - Human Interaction & Intent.

Rationale:

Yggdrasil remains human-first only if the human can understand, guide, correct, approve, and inspect the system.

#### 4. External Boundary

Purpose:

Attach replaceable outside mechanisms without allowing them to become semantic authority.

Contains:

- EBF - External Boundary Fabric.

Rationale:

Editors, providers, tools, parsers, cloud services, and external APIs will change. Their churn belongs at the boundary.

#### 5. Machine Substrate

Purpose:

Provide the storage and rebuildable machine structures that make the platform operational without becoming source of truth.

Contains:

- PDM - Persistence & Data Management.
- DRI - Derived Representation & Indexing.

Rationale:

Persistence mechanics and derived representations change for different reasons. They should not be one subsystem.

#### 6. Cognitive Augmentation

Purpose:

Provide retrieval, context assembly, memory, learning, reusable cognitive capabilities, and agentic workflow coordination.

Contains:

- RCA - Retrieval & Context Assembly.
- MEM - Machine Memory & Learning.
- CAO - Cognitive Capability & Agent Orchestration.

Rationale:

Retrieval assembles evidence for a moment. Memory preserves inspectable remembered support over time. Capabilities and agents reason, plan, and propose. These must not collapse.

#### 7. Governed Execution

Purpose:

Perform side-effecting work after authorization, with preview, dry run, rollback where possible, and execution reporting.

Contains:

- EXE - Capability Execution & Automation.

Rationale:

Agents may plan and propose. Governance authorizes. Execution acts. Tool side effects need a separate home.

#### 8. Trust, Fitness & Evolution

Purpose:

Make the system legible, evaluable, auditable, and capable of evolving without losing its architecture.

Contains:

- OEF - Observability, Evaluation & Fitness.
- CES - Contract & Evolution Stewardship practice.

Rationale:

A cognitive platform needs trust feedback and explicit contract stewardship. Without this, documentation and implementation drift will recreate the same coupling the SBS is meant to prevent.

### Level 2 control-boundary subsystems

#### HIX - Human Interaction & Intent

Purpose:

Own the surfaces through which humans read, write, decide, review, correct, navigate, approve, reject, and control the system.

Responsibilities:

- Human-facing interaction semantics.
- Human intent capture.
- Review, approval, rejection, and correction UX.
- Human-readable explanation views.
- Navigation across workspaces and scopes.
- UI shells such as Obsidian, Companion UI, CLI, mobile, web, voice, and future clients.

Ownership:

- Owns human interaction semantics and intent expression.
- Owns presentation of authority posture, provenance, memory posture, proposal state, and receipts.

Authority boundaries:

- May originate human intent.
- Must not become authority or persistence.
- Must route durable mutation through GOV and the owning subsystem.

Does not own:

- Durable knowledge.
- Memory lifecycle.
- Policy.
- Retrieval ranking.
- Agent runtime.
- Storage.
- Sync.
- Tool execution.

Expected rate of change:

- High.

Expected lifespan:

- Permanent while Yggdrasil remains human-first.

Rationale:

UI shells can be replaced. The need for human-facing intent, review, correction, approval, and explanation cannot.

#### WSP - Workspace, Scope & Principal Context

Purpose:

Own the active cognitive context: workspace, scope, sphere, situated identity, principal context, and topology posture.

Responsibilities:

- Active context as a set, not a scalar.
- Workspace identity.
- Scope and sphere binding.
- Situated identity context.
- Principal context for workspace/session posture.
- Multi-workspace, no-workspace, no-vault, and multi-root modes.
- Workspace membership.
- Topology configuration at the cognitive boundary.

Ownership:

- Owns the active cognitive context contract.
- Owns workspace/scope/principal binding semantics.

Authority boundaries:

- Provides context to GOV but does not decide permission.
- Provides bindings for HIX, RCA, MEM, CAO, EXE, and SFC.
- Must not turn vault, folder, root, repo, device, or cloud space into cognitive identity.

Does not own:

- Permission to act.
- Artifact meaning.
- Sync mechanics.
- Source observation.
- UI rendering.

Expected rate of change:

- Medium to high.

Expected lifespan:

- Permanent while Yggdrasil operates across contexts, workspaces, devices, principals, or deployment postures.

Rationale:

This subsystem replaces `activeVault` as an architectural primitive.

Key target rule:

```yaml
activeContext:
  bindings:
    - workspace
    - scope
    - sphere
    - situated_identity
    - principal
    - device_or_node_posture
    - authority_posture
```

The exact data model can evolve. The architecture rule must not: active cognitive context is a governed set of bindings, not a scalar pointer.

### Runtime lifecycle ownership

Decision (2026-06-24, issue #2473): **runtime-process-lifecycle authority — start, stop, idle, boot, and the binding of each long-lived runtime process to the active vault/context — is owned by WSP, extended, not by a new physical subsystem.** This resolves the keystone gap where process supervision fell between EBF (watcher *adapter*), EXE (execution *effects*), and OEF (*observation*) and lived only in ops scripts (`scripts/start_full_system.sh`) deliberately outside the SBS.

This is an **authority** assignment, not a mechanism relocation. The split is deliberate and must be preserved:

- **WSP owns the lifecycle-binding decision.** WSP already owns "the active cognitive context as a governed set of bindings" including `device_or_node_posture` and topology posture, and exists to "replace `activeVault` as an architectural primitive." Deciding *whether a runtime process should be running* and *which vault/context it is bound to* is a context-binding decision, so it is WSP's. WSP answers: *should the watcher/worker be running for the current context, and bound to which vault?* The authoritative input is WSP's `ActiveContextSet` (vault is one source binding within it), never a free-standing `activeVault` scalar.
- **WSP does not own the lifecycle mechanism.** WSP's charter explicitly does not own source observation or sync mechanics, and must not turn vault/root/device into cognitive identity. The *act* of starting, stopping, or re-pointing a process stays with the existing mechanism owners and is invoked under WSP's binding decision:
  - **EBF** — the watcher/source-observation adapter that physically attaches to or detaches from a vault path (watcher adapter; see EBF charter).
  - **EXE** — process start/stop and re-point as governed execution effects (`ExecutionRequest`), when those effects are authority-bearing.
  - **PDM** — per-environment store/runtime-state lifecycle bound to the selected environment (store ports, runtime artifact paths).
  - **OEF** — observes lifecycle state (running / idle / no-vault) and reports it; it does not drive the lifecycle (no OEF control loop).
  - **GOV** — authorizes any authority-bearing lifecycle effect (a process re-point that changes which durable vault is written carries a DecisionToken/receipt like any governed write).

**Non-goal honored:** no new physical module or process supervisor is instantiated to satisfy this boundary (per Part 1 non-goals — "Do not create fourteen new physical modules immediately" / "Do not instantiate physical modules to satisfy the boundary"). The change is a charter assignment plus a mapping row; current supervision continues to live in ops scripts as transition debt until a later, separately-gated slice routes it through these owners.

**Current vs target.** Current reality: lifecycle is operated by ops scripts and `PKM_ENVIRONMENT` resolution (`docs/ENVIRONMENTS.md :: Runtime Control Surface`); the no-vault idle/boot posture is owned by `docs/VAULT_OPTIONAL_RUNTIME/README.md` (the runtime boots with no vault bound and idles until one is opened, #2003/#2005). Target: that same start/stop/idle/boot + vault-binding behavior is classified under WSP authority with the mechanism distributed as above. This decision is a docs/charter assignment only — see `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md :: Runtime lifecycle` for the mapping row and `docs/architecture/SBS_TRANSITION_DEBT.md` (D13, plus the D1 active-vault relationship) for the open transition debt.

#### HKA - Human Knowledge & Artifact Substrate

Purpose:

Own durable human-authored and human-accepted knowledge artifacts.

Responsibilities:

- Human-authored artifacts.
- Human-accepted machine contributions.
- Durable retained source material.
- Minimal durable identity anchors carried inside the artifact representation.
- Origin-provenance stamps carried inside the artifact representation.
- Artifact lifecycle.
- Portable human-readable and exportable representations.
- Artifact survival, recovery, and representation migration at the artifact level.

Ownership:

- Owns durable human knowledge preservation.
- Owns whether a representation satisfies the human artifact contract.
- Owns the minimum identity/provenance data required for human knowledge to survive when machine artifacts disappear.

Authority boundaries:

- Human-authored and human-accepted artifacts carry human authority within their scope.
- System-originated changes require a GOV decision and receipt.
- HKA applies its own mutations through a governed write protocol.
- A human artifact must not depend on a separate SIP store, graph, index, or machine projection to retain its basic identity and origin provenance.

Does not own:

- Machine memory.
- Retrieval indexes.
- Embeddings.
- UI implementation.
- Vault implementation.
- Storage backend.
- Agent plans.
- Policy decisions.

Expected rate of change:

- Low for semantics; medium for representation migration.

Expected lifespan:

- Permanent while Yggdrasil preserves human knowledge.

Rationale:

If all derived machine artifacts disappear, HKA must still preserve usable human knowledge, including enough identity and origin provenance for the artifact to remain comprehensible and recoverable.

#### SIP - Semantic Identity & Provenance

Purpose:

Own the rebuildable semantic graph over identity/provenance anchors: ontology, relation vocabulary, concept identity, derived lineage, attribution views, context semantics, and semantic continuity.

Responsibilities:

- Semantic identity model derived from HKA identity anchors and declared sources.
- Concept identity.
- Provenance views and lineage graphs derived from HKA anchors, GOV receipts, MEM records, and declared sources.
- Attribution views.
- Claim/evidence relationships.
- Relation taxonomy.
- Artifact classes.
- Semantic migration rules.
- Scope and context semantics in coordination with WSP.

Ownership:

- Owns semantic identity and provenance semantics beyond the minimal durable HKA anchors.
- Owns ontology and relation vocabulary.
- Owns rebuildable semantic continuity across moves, representation changes, source changes, and migrations.

Authority boundaries:

- Provenance is not truth.
- Identity is not location.
- Ontology is not policy.
- SIP is not an irreplaceable origin store. If losing SIP would lose the minimum identity or origin provenance required for human knowledge survival, that data belongs in HKA.

Does not own:

- Human artifact content.
- Permission to mutate.
- UI rendering.
- Retrieval ranking.
- Memory lifecycle.
- Storage backend.
- Sync transport.

Expected rate of change:

- Low to medium.

Expected lifespan:

- Permanent while Yggdrasil needs stable meaning across changing representations and systems.

Rationale:

HKA owns durable content plus the minimum durable identity and origin-provenance anchors. SIP owns the richer semantic graph that can be rebuilt from HKA, GOV, MEM, and declared source records.

#### GOV - Governance, Policy, Authority & Receipts

Purpose:

Own policy, authority, admissibility, delegation, approval, and accountability.

Responsibilities:

- Human authority model.
- Agent authority model.
- Automation authority model.
- External system authority model.
- Delegation and revocation.
- Policy evaluation.
- Mutation admissibility.
- Review requirements.
- Authority receipts.
- Governance transitions.
- Promotion of machine output into human knowledge.
- Conflict-adjudication policy.

Ownership:

- Owns whether an action is allowed.
- Owns how authority-bearing decisions are accounted for.
- Owns receipt semantics.

Authority boundaries:

- Governance owns admissibility and accountability.
- State-owning subsystems perform their own writes through governed write protocols.
- GOV must not become a god-object for storage, formatting, routing, or implementation mechanism.
- The governed write protocol must be enforceable at the seam: a durable write without a valid decision/receipt token must be rejectable by the state owner's write guard.
- Receipts and policy decisions are accountability tokens; they authorize a bounded mutation class, not arbitrary subsystem behavior.

Does not own:

- UI layout.
- Storage mechanism.
- Agent implementation.
- Execution mechanism.
- Retrieval algorithm.
- Sync transport.
- Source adapter behavior.

Expected rate of change:

- Low for principles; medium for policy profiles and delegation rules.

Expected lifespan:

- Permanent while Yggdrasil has humans, agents, automation, memory, tools, or external systems.

Rationale:

Governance is the trust spine. It centralizes accountability, not all mechanism.

#### EBF - External Boundary Fabric

Purpose:

Own the boundary between Yggdrasil and things it does not fully control.

Responsibilities:

- Source adapters.
- Watcher adapters.
- Import adapters.
- Model provider adapters.
- Embedding provider adapters.
- Tool/MCP adapters.
- Parser/OCR adapters.
- External UI/editor adapters.
- Provider identity and versioning.
- Egress policy enforcement in coordination with GOV.
- External result normalization.
- External availability and fallback posture.

Ownership:

- Owns external attachment and adapter isolation.
- Owns provider identity, versioning, and fallback posture.

Authority boundaries:

- External systems provide mechanisms, observations, candidate evidence, inference, transport, or interface.
- External systems do not become authority without explicit governance.

Does not own:

- Semantic authority.
- Artifact identity.
- Policy decisions.
- Sync/federation semantics.
- Agent planning.
- Durable knowledge.
- Memory lifecycle.

Expected rate of change:

- Very high.

Expected lifespan:

- Permanent while Yggdrasil connects to external providers, tools, sources, editors, or APIs.

Rationale:

Provider churn belongs here. EBF translates and isolates external mechanisms; it must not become a dumping ground for core semantics.

#### PDM - Persistence & Data Management

Purpose:

Own storage technology abstraction and data-management mechanics.

Responsibilities:

- Storage backend selection.
- Store ports.
- Schema migrations.
- Backups.
- Snapshots.
- Restore.
- Data compaction.
- Encryption-at-rest mechanics.
- Store health.
- Data lifecycle mechanics.
- Durable vs rebuildable store classification.

Ownership:

- Owns persistence mechanics and store contracts.
- Owns storage replacement boundaries.
- Owns migration and recovery mechanics.

Authority boundaries:

- Storage is not meaning.
- Schemas do not define ontology.
- No subsystem should construct its own private persistence mechanism.

Does not own:

- Artifact meaning.
- Policy.
- Memory semantics.
- Retrieval semantics.
- Index semantics.
- Sync conflict semantics.
- UI state semantics.

Expected rate of change:

- Medium to high.

Expected lifespan:

- Permanent while Yggdrasil persists anything through replaceable storage technology.

Rationale:

Storage replacement is an explicit future change vector. It needs a clear subsystem owner.

#### DRI - Derived Representation & Indexing

Purpose:

Own rebuildable machine representations.

Responsibilities:

- Embeddings.
- Chunking.
- Lexical indexes.
- Vector indexes.
- Graph/relation projections.
- Derived overlays.
- Machine-readable mirrors.
- Rebuild pipelines.
- Staleness detection.
- Derived artifact invalidation.
- Embedding identity contracts.

Ownership:

- Owns rebuildable projections and indexes.
- Owns invalidation and rebuild semantics.
- Owns derived source-set declarations.

Authority boundaries:

- Everything DRI owns must be rebuildable from declared sources or reclassified into HKA, MEM, GOV, or SIP.
- DRI never becomes the source of truth.

Does not own:

- Storage backend.
- Human knowledge.
- Memory semantics.
- Retrieval answer composition.
- Policy.
- Agent runtime.
- UI.

Expected rate of change:

- High.

Expected lifespan:

- Permanent while Yggdrasil uses machine representations to operate over durable artifacts and memory.

Rationale:

Embeddings, indexes, chunks, and projections are high-churn and rebuildable. They must be separate from both durable knowledge and storage technology.

#### RCA - Retrieval & Context Assembly

Purpose:

Own moment-specific finding, ranking, evidence selection, and context-bundle assembly.

Responsibilities:

- Search.
- Ranking.
- Reranking.
- Retrieval strategy.
- Context bundles.
- Citation basis.
- Relevance explanation.
- Staleness signals.
- Evidence selection.
- Retrieval engine replacement boundary.

Ownership:

- Owns retrieval and context assembly semantics.
- Owns context-bundle contracts.
- Owns relevance explanation for selected evidence.

Authority boundaries:

- Retrieval produces candidate evidence and context.
- Retrieval does not produce truth, memory, or authority.

Does not own:

- Human knowledge.
- Memory lifecycle.
- Embedding provider.
- Storage technology.
- Policy.
- Agent runtime.
- UI rendering.

Expected rate of change:

- High.

Expected lifespan:

- Permanent while Yggdrasil helps find and assemble context.

Rationale:

Retrieval is central and volatile. Its replacement must not rewrite knowledge, memory, governance, or agents.

#### MEM - Machine Memory & Learning

Purpose:

Own inspectable machine memory and learning feedback across time.

Responsibilities:

- Memory classes: working, episodic, semantic, prospective, procedural, preference, interaction, project, and policy-adjacent memory.
- Memory candidate lifecycle.
- Review, promotion, rejection, and revision.
- Memory recall.
- Memory correction.
- Memory forgetting.
- Memory provenance.
- Contradiction handling.
- Learning feedback loops.
- Memory architecture replacement boundary.

Ownership:

- Owns machine memory semantics and lifecycle.
- Owns inspectability, correction, and forgetting.
- Owns memory recall contracts.

Authority boundaries:

- Memory is advisory unless explicitly promoted through governance.
- Unreviewed memory must never become hidden authority.

Does not own:

- Human-authored knowledge.
- Retrieval ranking.
- Agent runtime.
- Policy.
- UI.
- Storage backend.
- Embedding provider.

Expected rate of change:

- Medium to high.

Expected lifespan:

- Permanent while Yggdrasil learns or remembers machine-support material across time.

Rationale:

Memory is dangerous if hidden and weak if not inspectable. It must remain separate from human knowledge and retrieval.

#### CAO - Cognitive Capability & Agent Orchestration

Purpose:

Own reusable cognitive operations and agentic workflow coordination.

Responsibilities:

- Cognitive capabilities: summarize, synthesize, orient, clarify, compare, plan, review, critique, classify, and propose.
- Capability contracts.
- Agent roles.
- Agent workflow orchestration.
- Planning loops.
- Task state.
- Workflow state.
- Agent runtime replacement boundary.
- Proposal generation.
- Human-decision requests.
- Context requests to RCA.
- Memory requests to MEM.

Ownership:

- Owns non-side-effecting cognitive operations and workflow coordination.
- Owns agent orchestration and proposal generation.
- Owns agent-runtime replacement boundary.

Authority boundaries:

- Agents and cognitive capabilities may read, reason, plan, and propose.
- They must not directly mutate durable knowledge or perform unmanaged side effects.
- They request EXE for side effects and GOV for authorization.

Does not own:

- Permission to act.
- Durable writes.
- Tool side effects.
- Storage.
- Retrieval internals.
- Memory lifecycle.
- UI.

Expected rate of change:

- High.

Expected lifespan:

- Permanent while Yggdrasil offers cognitive augmentation beyond manual browsing.

Rationale:

Reusable cognition and agent orchestration are related but not the same as side-effecting execution.

#### EXE - Capability Execution & Automation

Purpose:

Own side-effecting execution after authorization.

Responsibilities:

- Capability execution when side effects are involved.
- Tool actuation.
- Automation effects.
- Dry runs.
- Previews.
- Rollback where possible.
- Execution status.
- External side-effect reporting.
- Execution-result normalization.
- Execution contracts.

Ownership:

- Owns how authorized effects are performed.
- Owns execution status and execution result semantics.

Authority boundaries:

- Execution knows how to do things.
- Governance decides whether they may be done.
- EXE must not decide policy internally.

Does not own:

- Policy.
- Agent planning.
- Human knowledge.
- Memory.
- Retrieval.
- Provider adapters.
- UI.
- Sync.

Expected rate of change:

- High.

Expected lifespan:

- Permanent while Yggdrasil performs side effects, automation, tool use, or delegated actions.

Rationale:

Agents plan and propose. Execution acts. Keeping them separate prevents agent frameworks from owning mutation mechanics.

#### SFC - Synchronization, Federation & Consensus

Purpose:

Own synchronization, replication, federation, node roles, causal ordering, conflict handling, and distributed deployment semantics.

Responsibilities:

- Node identity.
- Replica identity.
- Sync state.
- Replication.
- Federation.
- Causal ordering.
- Conflict detection.
- Conflict classification.
- Consensus or convergence strategy.
- Distributed receipt continuity.
- Offline/online transitions.
- Central/satellite behavior.
- Multi-device behavior.

Ownership:

- Owns distributed-system semantics.
- Owns synchronization and convergence contracts.
- Owns conflict staging semantics.

Authority boundaries:

- Sync may detect and stage conflicts.
- Sync must not silently resolve authority-bearing semantic conflicts unless GOV has explicitly authorized a policy for that conflict class.
- The SFC charter and ReplicationEnvelope contract should exist before central/satellite work begins; the implementation may remain a single-node no-op until a second write-capable node is scheduled.

Does not own:

- Artifact meaning.
- Policy.
- Human decision.
- Source observation.
- Storage backend.
- UI.
- Retrieval.
- Agent runtime.

Expected rate of change:

- Medium to high.

Expected lifespan:

- Permanent while Yggdrasil supports multi-device, central/satellite, offline/online, replicated, or federated operation.

Rationale:

Central + satellite deployment is not merely topology or integration. It needs causal ordering, conflict, receipt, partition, principal, and audit semantics.

#### OEF - Observability, Evaluation & Fitness

Purpose:

Own system legibility, diagnostics, evaluations, architectural fitness, and trust feedback.

Responsibilities:

- Traces.
- Health.
- Metrics.
- Evaluation harnesses.
- Architecture fitness checks.
- Regression detection.
- Drift detection.
- Audit visibility.
- Explanation support.
- Incident diagnostics.
- Boundary-violation detection.

Ownership:

- Owns visibility and verification.
- Owns evaluation and fitness rules.
- Owns diagnostic read models.

Authority boundaries:

- Observability can reveal and evaluate behavior.
- It must not silently become policy, memory, ranking, or authority.

Does not own:

- Policy.
- Knowledge.
- Memory.
- Retrieval ranking.
- Agent behavior.
- Execution.
- Storage.

Expected rate of change:

- Medium.

Expected lifespan:

- Permanent while Yggdrasil needs trust, diagnosis, evaluation, or regression protection.

Rationale:

In an agentic cognitive platform, observability is part of trust, not mere operations.

#### CES - Contract & Evolution Stewardship practice

Purpose:

Provide lean stewardship for long-term architectural contracts, subsystem charters, compatibility rules, versioning, and evolution discipline.

Responsibilities:

- Subsystem charters.
- Interface versioning.
- Compatibility matrices.
- Dependency rules.
- Boundary rules.
- Architecture decision records.
- Deprecation policy.
- Concept glossary governance.
- Change-impact playbooks.

Ownership:

- Stewardship practice for the architecture-control surface.
- Stewardship practice for compatibility and deprecation discipline.
- Stewardship practice for the boundary vocabulary that prevents implementation terms from becoming architecture terms.

Authority boundaries:

- CES is not a runtime subsystem, control plane, or user-facing governance authority.
- CES stewards architecture contracts; it does not approve user-level mutations or runtime business behavior.
- CES is not the Builder System; repo-local skills, issue pickup, release workflows, BuilderOps
  operational records, delivery receipts, and TCD routing remain Builder System concerns unless they
  also update Product SBS contracts through the normal repo authority path.
- CES must stay lean: ADRs, glossary hygiene, compatibility checks, and dependency-rule enforcement are enough until a concrete drift problem demands more.

Does not own:

- Runtime business behavior.
- Policy decisions.
- Storage.
- UI.
- Retrieval.
- Memory.
- Execution.

Expected rate of change:

- Low to medium.

Expected lifespan:

- Permanent while Yggdrasil expects to evolve over many years.

Rationale:

CES prevents implementation vocabulary from becoming architecture vocabulary without creating a new compliance machine.

## Part 4 - Dependency Model

### Core dependency rule

Dependencies should flow from volatile mechanisms toward stable contracts. The stable core should not depend on the volatile fabric.

### Macro-domain dependency posture

| Macro-domain | Subsystems |
| --- | --- |
| Human authority kernel | HKA, SIP, GOV |
| Context/topology | WSP, SFC |
| Human experience | HIX |
| External boundary | EBF |
| Machine substrate | PDM, DRI |
| Cognitive augmentation | RCA, MEM, CAO |
| Execution | EXE |
| Trust/evolution | OEF, plus CES practice |

### Allowed dependency pattern

| From | May depend on |
| --- | --- |
| HIX | HKA, SIP, GOV, WSP, RCA, MEM, CAO, EXE status, OEF views |
| WSP | SIP, GOV, SFC status, PDM configuration contracts |
| HKA | SIP semantic contracts, GOV-governed mutation decisions, PDM persistence ports |
| SIP | HKA identity/provenance anchors, WSP context definitions, GOV authority categories |
| GOV | SIP semantic identity/provenance views, HKA artifact references, WSP principal/scope context, SFC conflict classes, OEF evidence |
| EBF | Provider contracts from RCA, DRI, CAO, EXE, HIX, SFC, and PDM |
| PDM | Store contracts from state-owning subsystems |
| DRI | HKA, SIP, MEM declared source sets, PDM, EBF embedding/model providers |
| RCA | DRI, HKA, SIP, MEM, GOV filters, WSP scope |
| MEM | HKA/SIP provenance, GOV memory policy, RCA recall support, PDM, DRI memory representations |
| CAO | RCA, MEM, HKA read contracts, SIP, GOV, EXE request contracts, EBF model providers |
| EXE | GOV decisions, EBF tool/provider adapters, PDM execution state, OEF traces |
| SFC | WSP topology, PDM stores, GOV conflict policy, HKA/SIP identity references |
| OEF | Events/traces from all subsystems |
| CES practice | Contracts from all subsystems |

### Forbidden dependencies

| Forbidden dependency | Reason |
| --- | --- |
| HIX directly writes HKA/MEM/PDM | UI becomes domain authority. |
| RCA writes HKA | Retrieval becomes truth. |
| MEM writes HKA without GOV promotion | Memory becomes shadow knowledge. |
| CAO calls tools directly without EXE/GOV | Agents bypass execution governance. |
| EXE decides policy internally | Mechanism becomes authority. |
| EBF provider-specific concepts leak into HKA/SIP/GOV | Vendor/API choices become architecture. |
| SFC silently resolves semantic conflicts | Sync becomes authority. |
| PDM schema defines ontology | Storage becomes meaning. |
| DRI contains non-rebuildable meaning | Derived representation becomes hidden knowledge. |
| OEF metrics silently update policy, memory, or retrieval | Observability becomes an ungoverned control loop. |
| `vaultPath` or `activeVault` appears as a global contract | Vault becomes architecture identity. |

### Dependency inversion points

| Volatile implementation | Inverted behind |
| --- | --- |
| Obsidian or any editor | HIX interaction contracts and EBF editor adapters |
| Vault/folder/root representation | HKA ArtifactContract, WSP ActiveContextSet, and EBF source bindings |
| Watched folders and file watchers | EBF SourceObservationEvent / watcher adapter |
| Sync transport | SFC ReplicationEnvelope and EBF transport adapter |
| Storage backend | PDM StorePort |
| Embedding model | DRI DerivedRepresentationContract and EBF embedding adapter |
| Retrieval engine | RCA retrieval strategy contract |
| Memory architecture | MEM MemoryRecord and memory lifecycle contract |
| Agent runtime/framework | CAO WorkflowContract |
| Tool/MCP provider | EXE ExecutionRequest and EBF tool adapter |
| Telemetry backend | OEF TraceEvent and EBF telemetry adapter |

## Part 5 - Interface Contracts

These are conceptual contracts, not APIs.

### Highest-priority stable contracts

| Contract | Owner | Purpose |
| --- | --- | --- |
| IntentEnvelope | HIX | Carries human intent, review decisions, approvals, rejections, and corrections. |
| ActiveContextSet | WSP | Declares current workspace/scope/sphere/situated identity/principal/node/authority posture. |
| ArtifactContract | HKA | Defines durable human artifact identity, representation, lifecycle, and exportability. |
| SemanticIdentityContract | SIP | Defines rebuildable semantic identity, provenance views, relation, lineage, attribution, and ontology terms over HKA/GOV/MEM source anchors. |
| PolicyDecision | GOV | States whether an actor/action/resource/context is admissible. |
| AuthorityReceipt | GOV | Durable accountability record for governed decisions and mutations. |
| SourceObservationEvent | EBF | Records observed external/local source changes and source binding. Watcher/source-observation delivery semantics are currently owned by SFC `ReplicationEnvelope`. |
| StorePort | PDM | Abstracts persistence mechanics and migrations. |
| DerivedRepresentationContract | DRI | Defines rebuildable projections, embeddings, indexes, and source sets. |
| ContextBundle | RCA | Carries scoped candidate evidence with provenance and relevance explanation. |
| MemoryRecord | MEM | Carries remembered support material with review state, provenance, confidence, decay, and correction. |
| CapabilityContract | CAO | Defines reusable cognitive operation inputs, outputs, authority class, fallback, and side effects. |
| WorkflowContract | CAO | Defines agent/task state, plans, proposals, cancellation, and handoff. |
| ExecutionRequest | EXE | Requests side-effecting work under a GOV decision. |
| ReplicationEnvelope | SFC | Carries causal ordering, replica identity, conflict state, and delivery semantics. |
| TraceEvent / FitnessRule | OEF | Records behavior and evaluates architecture/system invariants. |
| SubsystemContract | CES practice | Defines versioned public contracts, ownership, dependencies, and deprecations. |

The first contracts to stabilize are ActiveContextSet, ArtifactContract, PolicyDecision, AuthorityReceipt, ContextBundle, MemoryRecord, StorePort, and ReplicationEnvelope.

### Conceptual subsystem interfaces

| Subsystem | Inputs | Outputs | Commands | Queries | Key contract rule |
| --- | --- | --- | --- | --- | --- |
| HIX | Human intent, text, confirmations, corrections, review decisions | IntentEnvelope, review decisions, correction requests | Capture intent, submit review, request action, request explanation | Show artifact, context, memory posture, proposal, receipt, status | UI may originate human intent but must not become authority or persistence. |
| WSP | Workspace definitions, scope/sphere/principal bindings, topology posture | ActiveContextSet, routing context, degraded-mode posture | Select context, add/remove root, change posture, validate context | What context is active? Which principal/scope applies? | Active context is a governed set, not `activeVault`. |
| HKA | Human artifacts, retained sources, governed mutations, representation migrations | ArtifactContract instances, artifact views, exports, lifecycle state | Create artifact, apply governed mutation, migrate representation, export | Resolve/read artifact, inspect lifecycle | Human knowledge survives loss of machine artifacts. |
| SIP | HKA identity anchors, origin provenance stamps, relation definitions, semantic migrations | SemanticIdentityContract, provenance views, lineage graph, relation rules | Define semantic identity, classify artifact/relation, migrate semantics | What is this entity? What is its lineage? | SIP graph is rebuildable; origin identity/provenance anchors live in HKA. |
| GOV | Intent, proposals, policy profiles, authority grants, conflict classes, evidence | PolicyDecision, AuthorityReceipt, approvals, denials, revocations | Evaluate action, approve/reject, record receipt, revoke delegation | Is this admissible? What authority applies? | GOV owns admissibility and accountability, not all mechanism. |
| EBF | External events, provider calls, source observations, tool/provider registrations | SourceObservationEvent, normalized external results, provider health | Attach adapter, call provider, normalize result, disconnect provider | Which integrations are available? What fallback applies? | External mechanisms do not become authority. |
| PDM | Store requests, schema changes, migration plans, backup/restore commands | StorePort bindings, migration results, backup/restore reports | Resolve store, migrate, backup, restore, compact, check health | Which store? What migration state? | Persistence is resolved once through PDM-owned contracts. |
| DRI | Source sets, embeddings, artifacts, memory records, invalidation requests | DerivedRepresentationContract, indexes, projections, staleness reports | Build projection, rebuild index, invalidate, refresh embedding | Is projection current? What source set built it? | Derived representations are rebuildable or reclassified. |
| RCA | Query/intent, ActiveContextSet, DRI projections, memory recall, GOV filters | ContextBundle, ranked evidence, citation basis, relevance explanation | Retrieve, rerank, assemble context, explain relevance | What evidence is relevant? Why selected? | Retrieval produces candidate evidence, not truth. |
| MEM | Observations, feedback, receipts, outcomes, source provenance, review decisions | MemoryRecord, recall results, contradiction reports, decay decisions | Create candidate, review, promote, reject, revise, recall, forget | Which memories apply? Are they reviewed? | Unreviewed memory must never become hidden authority. |
| CAO | Intent, context bundles, memory recall, policies, model outputs | Capability results, plans, proposals, workflow state | Invoke capability, plan, propose, hand off, request execution | Which capability? What plan? What proposal? | Agents reason, plan, and propose; they do not perform unmanaged effects. |
| EXE | GOV decisions, ExecutionRequest, tool adapters, automation triggers | Execution status, effect result, preview, rollback result | Execute, dry run, preview, rollback, report result | What ran? What failed? Which receipt applies? | Execution knows how; Governance decides whether. |
| SFC | Topology, replica state, sync deltas, node identity, conflict policy | ReplicationEnvelope, conflict candidates, convergence state | Sync, replicate, classify conflict, stage conflict, reconcile under policy | What is replica state? What conflict exists? | Sync stages authority-bearing conflicts; it does not silently decide them. |
| OEF | Events, traces, metrics, receipts, eval cases, drift signals | TraceEvent, health, fitness reports, audit views, incidents | Record trace, run eval, check health, detect drift, report incident | What happened? Which invariant failed? | Observability evaluates and explains; it is not policy. |
| CES practice | Subsystem contracts, ADRs, compatibility needs, deprecations | SubsystemContract, compatibility matrix, dependency rule, playbook | Version contract, deprecate, record ADR, validate boundary | Who owns this? Which contract changed? | CES prevents implementation vocabulary from becoming architecture vocabulary without becoming runtime governance. |

## Part 6 - Change Impact Matrix

Legend:

- `N` = No impact.
- `C` = Configuration impact.
- `I` = Interface impact.
- `R` = Subsystem redesign.

Columns: HIX, WSP, HKA, SIP, GOV, EBF, PDM, DRI, RCA, MEM, CAO, EXE, SFC, OEF.

| Change vector | HIX | WSP | HKA | SIP | GOV | EBF | PDM | DRI | RCA | MEM | CAO | EXE | SFC | OEF |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Change active vault | C | C | N | N | C | C | C | C | C | C | C | C | C | C |
| Add second vault | C | I | I | I | I | I | C | I | I | C | C | C | I | I |
| Remove vaults entirely | I | R | I | I | I | R | C | I | I | C | C | C | I | I |
| Change watcher implementation | N | N | N | N | N | R | N | C | C | N | N | N | N | C |
| Change synchronization model | C | I | I | I | I | I | I | C | C | C | C | C | R | I |
| Replace Obsidian | R | C | C | N | C | R | N | C | N | N | C | N | N | C |
| Replace Companion UI | R | C | N | N | C | I | N | N | N | C | C | C | N | C |
| Replace retrieval engine | N | C | N | N | C | I | C | I | R | C | C | C | N | I |
| Replace embedding model | N | C | N | N | N | I | C | R | I | I | C | N | N | I |
| Replace memory architecture | C | C | C | I | I | I | I | I | I | R | C | C | N | I |
| Replace agent runtime | C | C | N | N | I | I | C | C | C | C | R | I | N | I |
| Replace storage technology | N | C | I | C | I | I | R | I | C | I | C | C | I | I |
| Add central + satellite deployment | I | I | I | I | I | I | I | C | C | C | C | C | R | I |
| Add cloud-assisted deployment | C | I | C | C | I | R | I | C | C | C | C | I | I | I |
| Add offline-only deployment | C | I | C | N | C | I | I | C | C | C | C | C | I | C |

### Change-localization check

| Change vector | Primary subsystem(s) | Secondary impact | Desired result |
| --- | --- | --- | --- |
| Change active vault | WSP | EBF, DRI, RCA, HIX | Configuration/context change, not architecture change. |
| Add second vault | WSP, EBF | SIP, RCA, DRI, SFC | Scope/source expansion, not knowledge redesign. |
| Remove vaults entirely | HKA, WSP, EBF | SIP, HIX, DRI | Representation/source redesign, not cognitive-platform redesign. |
| Change watcher implementation | EBF | OEF, DRI refresh triggers | Localized adapter replacement. |
| Change synchronization model | SFC | PDM, GOV, WSP, OEF | Localized sync/federation redesign. |
| Replace Obsidian | HIX, EBF | HKA representation adapter | UI/source adapter change. |
| Replace Companion UI | HIX | EBF if external shell changes | UI-local redesign. |
| Replace retrieval engine | RCA | DRI, EBF, OEF evaluations | Retrieval-local redesign. |
| Replace embedding model | DRI, EBF | RCA, MEM indexes, OEF evaluations | Rebuild derived artifacts. |
| Replace memory architecture | MEM | PDM, RCA, GOV, HIX review | Memory-local redesign. |
| Replace agent runtime | CAO | OEF traces, EXE request compatibility | Agent-local redesign. |
| Replace storage technology | PDM | Migration interfaces for HKA/GOV/MEM/DRI/SFC | Storage-local redesign with controlled migrations. |
| Add central + satellite deployment | SFC | WSP, GOV, PDM, OEF, HIX conflict review | Major topology evolution, but not a new architecture. |
| Add cloud-assisted deployment | EBF, GOV | WSP, CAO, RCA, MEM, OEF | External capability mode, not cloud authority. |
| Add offline-only deployment | WSP, EBF, PDM | RCA/CAO/MEM fallback posture | Degraded but valid local mode. |

## Part 7 - Complexity Analysis

### Cognitive complexity

The two-level SBS reduces cognitive load by separating navigation from control boundaries:

- Level 1 gives humans eight macro-domains.
- Level 2 gives architects and agents precise subsystem owners.

The questions become simpler:

- "Where does human meaning live?" HKA.
- "What is this thing and where did it come from?" SIP.
- "What is allowed?" GOV.
- "Where and for whom are we operating?" WSP.
- "What external mechanism is involved?" EBF.
- "Where is data stored?" PDM.
- "What machine view was built?" DRI.
- "What evidence is relevant now?" RCA.
- "What is remembered over time?" MEM.
- "What agent or capability should reason?" CAO.
- "What side effect should run?" EXE.
- "How does this replicate or converge?" SFC.
- "What happened and did it violate an invariant?" OEF.
- "Which contract owns this boundary?" CES.

### Architectural complexity

The SBS reduces architectural complexity by preventing common collapses:

- active vault into cognitive context;
- storage schema into ontology;
- retrieval result into truth;
- memory into human knowledge;
- agent planning into execution;
- execution mechanism into authority;
- sync transport into conflict authority;
- UI state into accepted durable state;
- observability metrics into policy.

### Documentation complexity

CES gives the documentation ecosystem a control surface:

- Subsystem charters define owner boundaries.
- Interface contracts define stable handoffs.
- Compatibility matrices show what can change independently.
- ADRs record architecture-level decisions.
- Change-impact playbooks route future work to the right subsystem.

The existing system-of-systems doc remains the current-state bridge; this SBS owns the target-state decomposition.

### Agent context requirements

AI agents can load smaller context bundles:

- UI work: HIX, WSP, GOV presentation rules, relevant capability contract.
- Retrieval work: RCA, DRI, EBF provider adapter, GOV filters, OEF evaluations.
- Memory work: MEM, GOV policy, SIP provenance, HKA source references, PDM store contract.
- Storage work: PDM and affected StorePorts, not all knowledge/retrieval/memory docs.
- Sync work: SFC, WSP, GOV conflict policy, PDM store behavior, HKA/SIP identity.
- Agent-runtime work: CAO, EXE request compatibility, GOV authority rules, OEF tracing.

### Future migration costs

The target is controlled migration:

- Replace editor: HIX/EBF.
- Replace vault representation: HKA/WSP/EBF.
- Replace storage: PDM.
- Replace embeddings/indexing: DRI/EBF.
- Replace retrieval: RCA.
- Replace memory: MEM.
- Replace agent runtime: CAO.
- Replace tool execution: EXE/EBF.
- Add central/satellite: SFC/WSP/GOV/PDM.

The main migration principle is: migrate contracts first, mechanisms second, semantics only when necessary.

### Operational costs

OEF can attach incidents to subsystem owners:

- Stale projection: DRI.
- Store migration failure: PDM.
- Source adapter outage: EBF.
- Bad retrieval explanation: RCA.
- Hidden memory influence: MEM/GOV.
- Unauthorized write: GOV/EXE.
- Active-context confusion: WSP.
- Replica conflict: SFC.
- Documentation drift: CES.

## Part 8 - Failure Modes

### Governance god-core

Symptom:

Every subsystem calls GOV for mechanics, storage, formatting, routing, or implementation details.

Detection:

- GOV APIs start carrying storage, rendering, adapter, or execution-specific fields.
- Subsystems stop owning their own mutation contracts.

Mitigation:

GOV owns admissibility and receipts. State owners own their mutations under a governed protocol.

### Advisory governance

Symptom:

GOV emits suggestions, labels, or warnings, but authority-bearing durable writes can proceed without pre-mutation admissibility and post-mutation accountability.

Detection:

- Durable HKA/GOV/MEM mutation paths lack DecisionToken validation.
- Mutations complete without a durable AuthorityReceipt.

Mitigation:

Use the governed write protocol: state-owning subsystems perform their own mutations only after GOV issues a DecisionToken and emit an AuthorityReceipt after the mutation result is known.

### Integration dumping ground

Symptom:

EBF accumulates provider-specific business logic, source semantics, tool policies, and sync rules.

Detection:

- EBF decides artifact class, memory promotion, retrieval ranking, policy, or conflict meaning.

Mitigation:

EBF translates and isolates external mechanisms. Semantics stay with SIP/HKA/MEM/RCA/GOV/SFC.

### Storage leak

Symptom:

Multiple subsystems construct DSNs, manage migrations, or depend on storage tables directly.

Detection:

- Direct table references appear outside PDM-owned ports.
- Schema names appear in subsystem contracts as ontology.

Mitigation:

PDM owns store resolution and migration contracts. Other subsystems use StorePorts.

### Scope collapse into active vault

Symptom:

`activeVault`, `vaultPath`, or file root becomes a system-wide parameter.

Detection:

- New contracts pass vault path instead of ActiveContextSet.
- Scope, sphere, principal, and node posture are inferred from a file root.

Mitigation:

All operations consume WSP's ActiveContextSet. Vault is one possible source binding.

### Retrieval becomes truth

Symptom:

Context bundles or ranked results are treated as accepted knowledge.

Detection:

- RCA writes HKA.
- Ranked evidence appears as memory or fact without review.

Mitigation:

RCA outputs candidate evidence only. HKA/GOV own acceptance.

### Memory becomes hidden instruction

Symptom:

Unreviewed memory silently changes agent behavior.

Detection:

- MEM records lack review state, provenance, scope, confidence, or correction path.
- CAO consumes memory as instruction without authority posture.

Mitigation:

MEM records carry review state and provenance. GOV blocks hidden authority.

### Sync resolves meaning

Symptom:

Last-write-wins or transport rules decide semantically meaningful conflicts.

Detection:

- SFC applies conflict resolution to HKA/GOV/MEM records without a declared policy class.

Mitigation:

SFC stages conflicts. GOV/HIX resolve authority-bearing cases.

### UI state becomes authoritative

Symptom:

Companion UI, Obsidian plugin state, or client-local state becomes the only place where decisions, configuration, or accepted changes exist.

Detection:

- HIX state is read as domain truth by HKA/MEM/GOV.

Mitigation:

HIX owns interaction state only. Domain state belongs to owner subsystems.

### Event envelope lacks delivery semantics

Symptom:

A watcher or sync adapter emits well-shaped events but drops, reorders, or fails to backfill changes.

Detection:

- SourceObservationEvent lacks source binding, or ReplicationEnvelope lacks delivery guarantee,
  replay/backfill, ordering, idempotency, or failure visibility.

Mitigation:

EBF source-observation payloads preserve source binding. SFC ReplicationEnvelope specifies delivery semantics.

### OEF becomes control loop

Symptom:

Observability findings, metrics, or evaluations directly mutate policy, memory, retrieval ranking, knowledge, configuration, or execution behavior.

Detection:

- OEF code or configuration writes to GOV, MEM, RCA, HKA, CAO, EXE, or PDM state without a separate governed action path.
- Fitness results silently alter runtime behavior outside CI or explicit human-approved remediation.

Mitigation:

OEF observes, evaluates, reports, and may block CI when configured. Remediation is routed through GOV/HIX/CAO/EXE or normal development workflow.

### SIP becomes irreplaceable shadow store

Symptom:

SIP contains the only surviving copy of human meaning, artifact-origin facts, or accountability facts.

Detection:

- Losing SIP records would destroy human artifact identity, origin provenance, or governance accountability.
- HKA or GOV cannot rebuild required meaning or receipts without SIP.

Mitigation:

Keep SIP rebuildable. Store artifact-origin facts in HKA and decision/action receipts in GOV.

### Provider-specific concepts leak into core semantics

Symptom:

Provider model names, embedding-specific fields, tool payloads, or vendor taxonomies become public HKA/SIP/GOV contract fields.

Detection:

- Core contracts require provider-specific identifiers where a Yggdrasil-owned concept should exist.
- Replacing a model, embedding provider, parser, editor, or tool provider changes semantic authority rules.

Mitigation:

Route provider details through EBF/DRI/RCA/CAO/EXE adapters and translate them into stable Yggdrasil-owned contracts before crossing core boundaries.

### Agent runtime owns policy, retrieval, memory, or tool side effects

Symptom:

CAO or an agent framework decides policy, ranks evidence as truth, stores memory directly, or executes tools without GOV/EXE.

Detection:

- Agent runtime code carries policy decisions, unmanaged tool calls, durable memory promotion, or retrieval-specific output shapes as internal authority.
- Replacing the agent runtime would require redesigning GOV, RCA, MEM, or EXE.

Mitigation:

CAO owns cognition, planning, proposals, and workflow state. It consumes RCA/MEM/GOV contracts and requests side effects through EXE.

### Derived representations contain non-rebuildable meaning

Symptom:

Embeddings, indexes, chunks, projections, machine mirrors, or derived memory indexes contain the only copy of human meaning or accountability.

Detection:

- DRI loss would destroy accepted human knowledge, artifact-origin facts, or governance receipts.
- A derived record cannot be rebuilt from HKA/GOV/MEM source anchors and provider configuration.

Mitigation:

Reclassify non-rebuildable material into HKA, GOV, or MEM as appropriate. DRI remains disposable and rebuildable.

### Ontology abstraction tower

Symptom:

SIP becomes a conceptual dumping ground detached from implementation and tests.

Detection:

- A semantic concept has no lifecycle, query, validation, or fitness rule.

Mitigation:

Every SIP concept must attach to at least one owning lifecycle, query, validation, or OEF fitness rule.

## Part 9 - 2030 Future-State Stress Test

### Multiple vaults

Survives.

Primary impact:

- WSP and EBF for source/context expansion.
- SIP for identity and provenance.
- RCA/DRI for scoped retrieval and projections.
- SFC if replicas are involved.

Boundary test:

Adding vaults must not redefine artifact identity or human authority.

### No vaults

Survives if HKA's ArtifactContract is representation-independent.

Primary impact:

- HKA representation adapter.
- WSP context bindings.
- EBF source adapters.
- DRI rebuild.

Boundary test:

No-vault mode must not require redesigning memory, retrieval, governance, agents, or execution.

### Obsidian removed

Survives.

Primary impact:

- HIX and EBF.
- HKA only where Obsidian-specific representation assumptions leaked.

Boundary test:

Obsidian replacement should be a UI/editor/source adapter change, not a knowledge-architecture rewrite.

### New UI introduced

Survives.

Primary impact:

- HIX.
- EBF if it is an external shell.

Boundary test:

New UI state must not become authoritative.

### Retrieval engine replaced

Survives.

Primary impact:

- RCA.
- DRI/EBF for index/provider changes.
- OEF for evaluation recalibration.

Boundary test:

CAO and HIX consume ContextBundle contracts, not engine-specific result shapes.

### Memory system replaced

Survives.

Primary impact:

- MEM.
- PDM/DRI for storage and representation.
- GOV for review/promotion policy compatibility.
- RCA/CAO for recall integration.

Boundary test:

Memory replacement must preserve provenance, review state, correction, recall explanation, and forgetting semantics.

### Agent runtime replaced

Survives.

Primary impact:

- CAO.
- EXE request compatibility.
- OEF trace shape.

Boundary test:

Agent-runtime replacement must not alter GOV authority or HKA mutation semantics.

### Local-only deployment

Survives.

Primary impact:

- WSP, EBF, PDM.
- RCA/MEM/CAO fallback posture.

Boundary test:

Core flows remain valid with unavailable cloud providers and local persistence.

### Cloud-assisted deployment

Survives.

Primary impact:

- EBF and GOV.
- WSP, CAO, RCA, MEM, OEF.

Boundary test:

Cloud is an external capability mode, not cloud authority or the only copy of durable state.

### Central + satellite deployment

Survives, but this is a major topology evolution.

Primary impact:

- SFC.
- WSP, GOV, PDM, OEF, HIX conflict review.

Boundary test:

Central/satellite must not be implemented as "just another integration." It needs node identity, replica identity, causal ordering, partition behavior, distributed receipt continuity, and conflict staging.

### Multiple independent cognitive workspaces

Survives.

Primary impact:

- WSP.
- SIP context semantics.
- GOV cross-workspace policy.
- RCA/MEM scope filters.

Boundary test:

Cross-workspace retrieval, memory, and automation leakage must remain explicit and auditable.

### Shared family workspace

Partially survives; requires product and authority-model validation.

Primary impact:

- GOV principal model.
- WSP workspace membership.
- SIP actor/ownership/provenance.
- HIX review surfaces.
- OEF audit views.

Boundary test:

Family workspace introduces multi-principal authority and privacy boundaries, not merely multi-vault topology.

### Enterprise-style deployment

Partially survives; requires separate product decision.

Primary impact:

- GOV, WSP, SFC, OEF, EBF, PDM.

Boundary test:

Enterprise governance may conflict with personal human authority. Treat it as a different authority posture, not a scale-up of the personal system.

## Part 10 - Final Recommendation

Adopt SBS V2 as the target architecture:

> Authority-first, volatility-disciplined, systems-of-systems decomposition with a two-level structure.

Use the repository's current eight-subsystem architecture as the bridge. Use this SBS as the 2030 target decomposition.

### Recommended Level 1 macro-domains

1. Human Authority Kernel.
2. Cognitive Context & Topology.
3. Human Experience.
4. External Boundary.
5. Machine Substrate.
6. Cognitive Augmentation.
7. Governed Execution.
8. Trust, Fitness & Evolution.

### Recommended Level 2 control-boundary subsystems

1. HIX - Human Interaction & Intent.
2. WSP - Workspace, Scope & Principal Context.
3. HKA - Human Knowledge & Artifact Substrate.
4. SIP - Semantic Identity & Provenance.
5. GOV - Governance, Policy, Authority & Receipts.
6. EBF - External Boundary Fabric.
7. PDM - Persistence & Data Management.
8. DRI - Derived Representation & Indexing.
9. RCA - Retrieval & Context Assembly.
10. MEM - Machine Memory & Learning.
11. CAO - Cognitive Capability & Agent Orchestration.
12. EXE - Capability Execution & Automation.
13. SFC - Synchronization, Federation & Consensus.
14. OEF - Observability, Evaluation & Fitness.

### Required cross-cutting stewardship practice

- CES - Contract & Evolution Stewardship.

### Most important changes from SBS V1

1. Introduce SFC now, not later.
2. Split persistence from derived representation.
3. Treat active context as a set, not active vault.
4. Use a principal axis from the beginning.
5. Use governed write protocol rather than Governance-as-god-core.
6. Keep retrieval, memory, capabilities, agents, and execution separate.
7. Make CES explicit as a lean stewardship practice, not a runtime subsystem.

### Most durable decade-scale boundaries

1. Human Knowledge vs Machine Memory.
2. Human Knowledge vs Derived Representations.
3. Retrieval vs Memory.
4. Governance vs Execution.
5. Agent Orchestration vs Execution.
6. Workspace/Scope vs Vault/Source/Storage.
7. Semantic Identity/Provenance vs Storage Location.
8. External Boundary vs Core Semantics.
9. Persistence vs Derived Representation.
10. Synchronization/Federation vs Governance.
11. Human Interaction vs Domain Ownership.
12. Observability/Fitness vs Behavior.

### Open validation questions

- What minimum ArtifactContract supports no-vault operation while preserving human comprehensibility?
- What exact fields belong in ActiveContextSet V1?
- Which memory classes require explicit human review, agent review, or policy-only review?
- What ReplicationEnvelope semantics are required before central/satellite deployment can be safe?
- Which source-binding guarantees must SourceObservationEvent provide for watchers and external connectors, and when should those observations be wrapped in ReplicationEnvelope delivery semantics?
- Which StorePort abstractions are sufficient to prevent storage leakage without hiding necessary operational detail?
- Which OEF fitness checks can automatically detect hidden authority escalation?

The target architecture should optimize for this invariant:

> Yggdrasil may replace most implementation choices without losing human knowledge, semantic continuity, authority accountability, or local-first operability.
