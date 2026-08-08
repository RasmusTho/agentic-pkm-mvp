State: Advisory ontological, semantic, and nomenclature audit snapshot, 2026-08-08. Repository baseline: `origin/main` at `6d5f23ab6b6445f7dfd6e26c6268e85132ea7941`. Subordinate to current owner docs, accepted ADRs, and current runtime evidence. No rename, ontology replacement, schema migration, memory mutation, or implementation work is authorized by this audit.
Doc role: Reference (architecture audit and semantic-review program baseline)
Authority: Evidence-based reconstruction and review protocol. Owner docs and accepted ADRs win on disagreement; findings remain observations until reconciled through their owning authority surface.
Owner: Architecture spine / CES stewardship
Temporal class: advisory snapshot
Review cadence: event-driven after an accepted semantic reconciliation, ecosystem/SBS reshape, or material target-review wave
Source of truth: `docs/DOCS_INDEX.md` for document routing; the cited owner docs, contracts, schemas, code, and accepted ADRs for individual claims
Last reviewed: 2026-08-08

# Yggdrasil Ontological, Semantic, and Nomenclature Baseline

## 1. Charter, classification, and method

This audit establishes the first baseline and the repeatable review program requested after a
superseded architectural name resurfaced from secondary AI memory. That symptom is evidence of a
general risk: architecture language can survive in implementation, design artifacts, generated
context, summaries, or memory after its normative meaning changes. The audit is not a review of one
name and does not assume that every old term is wrong.

The pass is **Builder System / CES boundary work producing an advisory Product/Runtime analysis
artifact**. It changes neither Product/Runtime semantics nor Builder workflow authority. It followed
`architecture-research` with one persistent synthesis context and three bounded read-only evidence
briefs: semantic authority, implementation/representation, and history/evolution. The coordinator
re-read every source used for a finding. GitHub was queried only to reconcile existing work; no Issue
or PR state was changed.

Research questions:

1. What architectural things does Yggdrasil currently recognize, and which documents own their
   meaning?
2. Is there one semantic system of record, or a governed set of owner surfaces?
3. How do current implementation, target decomposition, ontology, schemas, and projections relate?
4. Which obvious divergences warrant later target review?
5. How should repeated reviews preserve semantic continuity without creating a parallel ontology?

Requested-deliverable coverage:

| Deliverable | Section |
|---|---|
| A. Existing semantic governance map | §3 |
| B. System-wide semantic baseline | §4 |
| C. Initial semantic debt findings | §5 |
| D. Review protocol and worker contract | §7 |
| E. Ordered review-target inventory | §9 |
| F. Context and execution plan | §8 |
| G. Storage recommendation | §10 |
| H. Global reconciliation plan | §11 |
| I. Cleanup strategy, plan only | §12 |
| J. TCD assessment | §1 and §8 |

### TCD plan

```yaml
tcd_plan:
  task_summary: establish the semantic review program and first system-wide baseline
  assumptions: owner docs remain authoritative; this pass creates no runtime or normative semantic change
  complexity: very_high
  risk: high
  verification_difficulty: hard
  human_review_burden: medium
  defect_blast_radius: high
  budget_pressure: low
  recommended_capability:
    workflow_or_skill: architecture-research -> docs-governance -> docs-authoring
    model_family: Sol semantic owner; bounded evidence workers on the cheapest available verifiable tier
    reasoning_effort: xhigh for synthesis; low for evidence extraction
    tools: repository search, bounded git history, REST GitHub reads, file-line verification
    github_context_required: true
  cheapest_acceptable_path: one persistent Sol synthesis context plus bounded structured evidence briefs; one indexed audit artifact
  escalation_triggers: unresolved owner conflict, proposed SBS reshape, cross-cutting ambiguity, or protected authority/data invariant
  deescalation_triggers: accepted taxonomy and a target contract bounded enough for mechanical inventory or verification
  review_gate: evidence anchors, owner-doc precedence, SBS reconciliation, docs validation, and independent PR verification only if later promoted
```

Luna was requested for mechanical evidence work but was not available as a selectable worker model in
the execution environment. Terra/low was used under the same read-only bounded contracts. This avoided
transferring semantic ownership while retaining independently checkable evidence.

## 2. Executive verdict

Yggdrasil already has substantial semantic governance. It is deliberately **distributed by concern**,
not centralized in one ontology file or database:

- the Project Kernel and doctrine own intent and load-bearing commitments;
- accepted ADRs own durable decisions and supersession;
- the ecosystem naming decision distinguishes Yggdrasil, Mimer, Heimdal, and reserved names;
- the current runtime architecture owns shipped structural truth;
- the target SBS owns the long-horizon control-boundary decomposition;
- the semantic system map owns cross-layer semantic topology;
- cognitive and functional ontology documents own overlapping but differently scoped vocabularies;
- specialist contracts and schemas own narrower semantics and machine representation;
- the boundary register records implementation/enforcement maturity; and
- Git history and historical artifacts preserve provenance without outranking current owners.

The program should therefore **reconcile and make this authority graph legible**, not replace it.
The most important first findings are:

1. the relationship between the canonical Cognitive Ontology and canonical Functional Ontology is
   inferable but not stated in one authoritative routing rule;
2. the accepted Hugin/Munin supersession is explicit, but active operational and design-normalization
   surfaces still use those names as modules or agents without a compatibility/lifecycle annotation;
3. several mixed-status documents combine historical decisions with current routing, making valid
   history look like current terminology;
4. schemas strongly represent intended semantics, while several boundaries remain only partially
   enforced in the current runtime; and
5. no artifact named “System Design Model” exists. Its expected functions are distributed across the
   current architecture, target SBS, semantic map, boundary register, contracts, and the deliberately
   derivative human-flow allocation view.

This is enough to begin iterative reviews. It is not evidence that the whole repo should be renamed or
that a new semantic registry is needed.

## 3. Existing semantic governance map

| Concern | Current owner / authority | Role in the semantic system | Important boundary |
|---|---|---|---|
| Human intent and durable principles | `docs/PROJECT_KERNEL.md`; `docs/foundation/00-yggdrasil-doctrine.md` | North star and non-collapsible commitments | Not implementation taxonomy |
| Ecosystem apex and constituent names | ADR-0044 and `docs/GLOSSARY.md` | Yggdrasil = apex; Mimer = undivided knowledge-and-cognition constituent; Heimdal = sensor; Hugin/Munin reserved (`docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md:38-70`; `docs/GLOSSARY.md:26-29`) | Supersede only through a new accepted ADR |
| Current shipped architecture | `docs/ARCHITECTURE.md` and `docs/STATUS.md` | Current runtime components, boundaries, and current-vs-planned truth | Wins over target SBS for present-tense behavior (`docs/architecture/SBS_OPERATING_MODEL.md:28-33,46-57`) |
| Target structural decomposition | `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` | Eight macro-domains, fourteen Level-2 control boundaries, CES practice, dependencies and conceptual interfaces (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:56-113,1488-1530`) | Target state; control boundaries are not packages/services |
| SBS use and maturity | `docs/architecture/SBS_OPERATING_MODEL.md`; boundary/debt/fitness registers | Work classification, owner routing, current implementation maturity, transition debt, fitness | Registers do not make target ownership shipped (`docs/architecture/SBS_BOUNDARY_REGISTER.md:11-25`) |
| Cross-layer semantic topology | `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` | Seven layers, authority roles, meaning flow, runtime/durable map (`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:36-111,113-157`) | Integrating map; scoped owner contracts win (`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:28-34`) |
| General human/domain ontology | `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`; normalized vocabulary | Human-first actors, contexts, artifacts, commitments, operations and relations | General meanings yield to explicitly scoped specialist contracts (`docs/CONCEPTS/DEFINITION_OWNERSHIP.md:29-60`) |
| Architecture functional-object ontology | `docs/architecture/functional-ontology.md` | Canonical functional objects, non-collapse rules, and SBS semantic allocation (`docs/architecture/functional-ontology.md:1-8,35-64,83-125`) | Architecture contract; does not claim shipped runtime behavior |
| Orthogonal semantic dimensions | `docs/architecture/semantic-dimensions.md`; shared schema definitions | Source role, authority state, evidence role, sensitivity, scope, lifecycle/execution dimensions | Dimensions must not be collapsed (`docs/architecture/semantic-dimensions.md:29-52`) |
| Narrow concept meaning | `docs/CONCEPTS/**`, `docs/contracts/**`, owner ADRs | Specialist rules for memory, context, artifacts, relations, authority, execution, and interfaces | Narrow explicit scope wins over general definition |
| Machine representation | `schemas/**`, runtime typed contracts | Structural representation of identity, provenance, authority, lifecycle, and allowed transitions | Schema validity is not proof of end-to-end runtime enforcement |
| Functional allocation and verification | `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`; invariant/fitness registries | Derivative mapping from human flows to SBS owners, contracts, requirements, and checks | Explicitly not a new FBS or parallel source of truth (`docs/architecture/system-context-overlay.md:151-160`) |
| Historical evolution | ADR supersession, historical headers, git history, archive redirects | Preserves why semantics changed and which decision replaced which | Historical truth is evidence, not current authority |
| Builder semantics | root `AGENTS.md`, `.codex/skills/**`, Builder System owner docs | Development-time authority, delivery vocabulary, operational records | Must not become Product/Runtime memory or ontology (`docs/architecture/SBS_OPERATING_MODEL.md:102-110,150-161`) |
| Derived context and UI | CKM projections, devUI/cockpit, Companion UI projections, generated docs | Read, route, explain, or render authoritative sources | Never promote themselves to authority |

The semantic authority substrate is therefore the **governed owner-doc graph plus accepted decisions
and current implementation evidence**, routed by `DOCS_INDEX`; it is not a single file. Definition
ownership already requires downstream documents to reference rather than silently redefine terms and
requires semantic changes to be visible (`docs/CONCEPTS/DEFINITION_OWNERSHIP.md:29-76`).

## 4. System-wide semantic baseline

### 4.1 Ecosystem and system identity

The accepted ecosystem model is:

```text
Yggdrasil (acknowledged ecosystem apex)
├── Mimer (knowledge-and-cognition constituent; current system of interest)
│   ├── current runtime architecture
│   ├── target SBS control boundaries
│   └── capabilities, contracts, and semantic objects
├── Heimdal (sensor / event-capture constituent)
└── private-bindings (thin operator-bound constituent)
```

Hugin and Munin are reserved, not current constituents or active module names. ADR-0044 explicitly
supersedes ADR-0043's split and records the later code/glossary enactment
(`docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md:49-88`). “Yggdrasil” in older prose
often denotes what the current model calls Mimer; provenance should be retained and the temporal
reading made explicit, not mechanically erased (`docs/GLOSSARY.md:26-29`).

### 4.2 Structural taxonomy

Mimer has two structural readings that serve different time horizons:

- the current eight-subsystem architecture spine is a bridge for today's runtime; and
- the target SBS is an authority-first decomposition into eight macro-domains and fourteen control
  boundaries plus CES stewardship.

The current-to-target crosswalk is explicitly a translation between coexisting taxonomies, not an
arbitration mechanism. It records that Capability spans CAO + RCA, while WSP, SFC, MEM, and EXE have no
dedicated current-spine ancestor (`docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md:37-65`). The SBS
separates knowledge/meaning/storage, candidate evidence/admissibility/provenance,
proposal/authority/execution, memory/promotion/durable knowledge, and observability/normative meaning
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1242-1330`).

### 4.3 Semantic topology and representation

The semantic system map provides seven non-conflatable layers:

1. ontology;
2. artifact model;
3. representation;
4. governance/authority;
5. runtime;
6. machine mirror; and
7. UI projection.

Meaning and authority do not follow storage location or the component that happens to emit a value.
The canonical flow is human artifact → companion/system support → derived mirror → context bundle →
runtime/UI projection → proposal → receipt → governed durable mutation. Derived and runtime objects do
not acquire authority without an explicit transition (`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:90-133`).

Representations therefore classify as:

| Class | Examples | Semantic posture |
|---|---|---|
| Normative | owner docs, accepted ADRs, contracts, schemas within their declared scope | Defines meaning or allowed structure |
| Derived | DB/index/embedding rows, CKM projections, generated summaries, context bundles | Rebuildable or source-bound; cannot originate authority |
| Operational | code, runtime configuration, queues, receipts, current UI behavior | Evidence of current realization; may expose divergence from target contracts |
| Historical | superseded ADRs, concluded plans, archived docs, dated design handoffs | Provenance and intent at a point in time |
| Ephemeral | session state, model context, prompt cache, transient UI state | Working state only; not semantic SoT |

### 4.4 Ontological objects and dimensions

The Functional Ontology currently recognizes major object families rather than every implementation
symbol:

- topology/context: `VaultRoot`, `Workspace`, `Scope`, `Sphere`, `Principal`, `Device`, `Node`,
  `Replica`;
- knowledge/meaning: `Artifact`, `HumanArtifact`, `AcceptedArtifact`, `Segment`, `Claim`, `Concept`,
  `Relation`, `Source`, `Episode`;
- memory/cognition/capability: `MemoryItem`, `Proposal`, `Commitment`, `CapabilityGrant`,
  `CrossScopeFlow`;
- authority/provenance/effect: `AuthorityReceipt`, `ProvenanceEvent`, `Projection`,
  `ExecutionEffect`; and
- separately contracted candidate output: `RetrievalResult`.

Objects carry orthogonal dimensions including source role, authority state, evidence role,
sensitivity, scope binding, episode reference, suppression, memory, sync, and execution state. In
particular, source, authority, and evidence answer different questions and must not collapse
(`docs/architecture/semantic-dimensions.md:29-52,54-189`). The metadata schema makes identity,
scope, semantic roles, provenance, and lifecycle structurally visible, but the Boundary Register
still marks several seams as partial or manual-review-only.

### 4.5 Capabilities, interfaces, allocation, and verification

A capability is reusable behavior with an explicit contract; it is not automatically an agent, UI,
service, or tool. Current architecture explicitly calls retrieval a capability and keeps ASK as one
consumer (`docs/ARCHITECTURE.md:703-712`). The target SBS names conceptual interfaces for identity,
artifacts, policy/receipts, derived representations, context assembly, memory, capability, execution,
replication, and evaluation (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1488-1530`).

There is no normative artifact titled “System Design Model” and no full functional decomposition with
synthetic IDs. Equivalent concerns are intentionally distributed:

- system context and current realization: `ARCHITECTURE` and the context overlay;
- structure and allocation ownership: SBS and current-to-target mapping;
- semantic identity: semantic map plus ontology/contract owners;
- functional allocation: human-flow-to-runtime map; and
- verification: traceability, invariant, boundary, transition-debt, and fitness surfaces.

The human-flow allocation explicitly stays derivative and must not be used to infer that target SBS
ownership is implemented (`docs/HUMAN_FLOW_TO_RUNTIME_MAP.md:96-112`).

### 4.6 Identity, aliases, lifecycle, and provenance

Identity is scoped rather than globally flattened. Vault-note semantic identity resolves to a stable
frontmatter UUID; paths, hashes, sessions, proposals, and DB IDs are not substitutes
(`docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md:21-60`). The Functional Ontology gives concepts
labels and aliases, while schemas define stable object IDs and scoped references. ADRs carry durable
decision identity and explicit supersession.

The repository already has a useful semantic-evolution vocabulary:

- canonical/current;
- alias/compatibility language;
- historical;
- deprecated;
- superseded;
- candidate/proposal;
- target-state versus current-state; and
- derived versus authoritative.

These statuses are expressed through document headers, ADR status and supersession, glossary entries,
compatibility notes, and git history. They are not yet one uniform lifecycle field across all artifact
classes, and should not be forced into one without evidence that the different classes share a
contract.

## 5. Initial semantic debt findings

Findings are ranked by semantic-error blast radius and how silently a human or agent could adopt the
wrong meaning. They are review candidates, not cleanup authorization.

### F1 — Two canonical ontology entry points lack an explicit overlap contract

**Primary class:** semantic. **Confidence:** high observation, medium reconciliation.

The semantic map names `COGNITIVE_ONTOLOGY.md` as canonical Layer-1 ontology
(`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:40-45`). The newer Functional Ontology also claims canonical
names and system consequences (`docs/architecture/functional-ontology.md:1-8`), and `DOCS_INDEX`
labels it the canonical functional objects surface (`docs/DOCS_INDEX.md:190-192`). Definition
ownership provides a general-over-specialist precedence rule, but no cited owner surface states the
precise relationship between these two documents.

Likely reconciliation: human/domain ontology versus architecture-functional object vocabulary. That
reading must be verified and then stated by the owners; this audit does not enact it.

### F2 — Reserved Hugin/Munin names remain active in operational and normalization surfaces

**Primary class:** nomenclature with possible implementation and documentation debt. **Confidence:**
high observation; intent unresolved.

The accepted ADR and glossary reserve Hugin/Munin (`docs/GLOSSARY.md:26-29`), but:

- production scaffolding creates `Hugin` and `Munin` directories and its test pins them
  (`app/settings/mimer_scaffolder.py:21-50`; `tests/settings/test_mimer_scaffold_guard.py:29-32`);
- Companion UI's authoritative design term normalization calls Hugin a Panel agent and Munin a
  background agent (`companion-ui/docs/CORE_TERM_MAPPING.md:1-13,26-38`); and
- checked-in Companion UI prototype/runtime assets contain Hugin labels
  (`companion-ui/companion-app/canvas_suggestion_flow.html:70-115`;
  `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py:6049`).

The scaffolding may be a compatibility layout and the UI labels may be preserved design vocabulary,
but those classifications are not visible at the cited use sites. The target review must determine
whether to annotate, migrate, preserve as an alias, or remove; it must not assume a mass rename.

### F3 — Mixed-status artifacts make valid history look current

**Primary class:** historical/documentation. **Confidence:** high.

`docs/HEIMDAL/README.md` declares a mixed current/history role but still describes Munin and Hugin as
downstream constituents in its opening current-looking prose (`docs/HEIMDAL/README.md:1-20`). The
candidate Architectural Constitution says it adopts ADR-0043's split while also claiming later
ADR-0044–0047 reconciliation (`docs/foundation/ARCHITECTURAL_CONSTITUTION.md:20-42`). These sources
are subordinate or candidate material, so they do not overturn ADR-0044, but their internal temporal
posture makes incorrect retrieval or summarization likely.

### F4 — The declared authority route spans multiple owner surfaces

**Primary class:** semantic/documentation. **Confidence:** high.

The SBS source-of-truth matrix distributes current architecture, target decomposition, operating
model, mappings, registers, contracts, and ADRs across separate owners
(`docs/architecture/SBS_OPERATING_MODEL.md:42-68`). The semantic map separately delegates each
semantic layer to scoped owner contracts (`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:36-88,174-185`), and
definition ownership supplies the cross-document precedence rule
(`docs/CONCEPTS/DEFINITION_OWNERSHIP.md:29-60`). This is deliberate distribution, but the current
review route requires those surfaces to be composed before a reader can relate doctrine, current
runtime, target structure, ontology, representation, and implementation maturity. The bounded
finding is routing cost and flattening risk, not the absence of governance.

Issue [#3957](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3957) already owns a related but
narrower `ARCHITECTURE.md` authority-boundary trim. Do not create a duplicate cleanup Issue; reconcile
any owner-doc change with that contract.

### F5 — Strong schemas can be mistaken for shipped semantic enforcement

**Primary class:** implementation/semantic. **Confidence:** high.

Metadata, retrieval, memory, and authority-transition schemas encode strong invariants, while the
Functional Ontology explicitly disclaims shipped-runtime truth and the Boundary Register reports
partial/manual enforcement for several boundaries (`docs/architecture/functional-ontology.md:1-3`;
`docs/architecture/SBS_BOUNDARY_REGISTER.md:20-40`). A generated context or review must not infer
end-to-end enforcement from schema existence alone.

### F6 — Alias and supersession mechanisms are present but not uniform across representations

**Primary class:** nomenclature/historical. **Confidence:** medium-high.

ADRs have explicit supersession (`docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md:1-6,62-88`),
definition ownership requires visible dated semantic change
(`docs/CONCEPTS/DEFINITION_OWNERSHIP.md:62-76`), and the normalized vocabulary carries an explicit
drift map while allowing interpreted migration-era terms (`docs/CONCEPTS/ONTOLOGY_VOCABULARY.md:27-42,94-113`).
At the observed active use sites, scaffolding and Companion UI terminology preserve reserved names
without the same local lifecycle marker (`app/settings/mimer_scaffolder.py:31-40`;
`companion-ui/docs/CORE_TERM_MAPPING.md:26-38`). These representation classes therefore do not expose
one common lifecycle shape in the inspected evidence. This may be appropriate compatibility, but
target reviews need a common result format so “historical,” “compatibility alias,” and “current
canonical” are not inferred from occurrence alone.

### F7 — The machine-readable API surface is explicitly partial legacy coverage

**Primary class:** documentation/derived representation. **Confidence:** high.

`api/openapi.yaml` labels itself a partial legacy snapshot rather than complete published client
coverage (`api/openapi.yaml:1-16`). This is honest classification, not a runtime defect by itself, but
agents or tooling can still mistake the file's format for completeness. The API/interface target
review should verify discovery and routing rather than silently promoting it.

## 6. Semantic invariant kernel

These are candidate invariants for later reconciliation with the existing invariant/fitness surfaces;
this advisory audit does not add them to a registry or create an enforcement mechanism.

| Invariant | Category | Current posture | Evidence / gap |
|---|---|---|---|
| `SEM-01 Authority is explicit` — derived, runtime, UI, retrieval, or memory objects cannot originate durable authority | MUST | Exists partially; keep | Semantic authority flow and governed transition are explicit (`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:90-133`) |
| `SEM-02 Identity is representation-independent` — path, storage row, provider, or projection cannot silently redefine semantic identity | MUST | Exists partially; keep | Artifact lifecycle and SIP/PDM separation (`docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md:21-60`; `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1256-1277`) |
| `SEM-03 Current, target, and historical claims stay distinguishable` | GATE | Observed ambiguity; target review required | F3; mixed-status and candidate documents contain current-looking superseded names |
| `SEM-04 Accepted nomenclature supersession is visible at active use sites` | GATE | Unclassified at observed use sites; target review required | F2; active code and design normalization retain reserved names without local lifecycle posture |
| `SEM-05 Every canonical term has a resolvable owner and overlap rule` | DOCTOR | Violated for one high-level overlap | F1; cognitive versus functional ontology relationship is not explicit |
| `SEM-06 Representations disclose authority and completeness` | DOCTOR | Exists partially; keep | CKM/devUI classifications are strong; partial OpenAPI and schema/runtime maturity still need routing checks |
| `SEM-07 Provenance survives derivation and historical reconciliation` | MUST | Exists partially; keep | SIP, metadata bundle, ADR supersession, and definition ownership require traceability |

Minimal kernel for this program: `SEM-01`, `SEM-03`, `SEM-04`, and `SEM-05`. The remaining invariants
are necessary supporting boundaries but should not inflate the first reconciliation into a new
governance subsystem.

## 7. Repeatable target-review protocol

Each review is a bounded evidence test against this baseline.

1. **Charter the target.** Classify it as ecosystem/system, subsystem/control boundary, capability,
   cross-cutting concept, architectural domain, or interface boundary. State current/target scope and
   explicit non-goals.
2. **Resolve authority first.** Use `DOCS_INDEX`, accepted ADRs, definition ownership, current runtime
   owners, SBS owners, and specialist contracts. Record conflicts; do not average them.
3. **Collect evidence.** Inventory normative, derived, operational, historical, and ephemeral
   representations. Keep raw occurrence lists outside the semantic working prefix.
4. **Build the concept record.** Capture canonical identity/name, type, definition, responsibility,
   relationships, owner, implementation realization, lifecycle, aliases/history, confidence,
   ambiguity, and evidence.
5. **Test non-collapse rules.** Check identity versus representation, proposal versus authority,
   memory versus knowledge, retrieval versus truth, runtime versus durable, UI versus authority, and
   Product versus Builder System.
6. **Compare implementation and claims.** Distinguish contract existence, structural validation,
   production-path enforcement, current deployment, and target intent.
7. **Classify findings.** Use semantic, nomenclature, documentation, implementation, historical, or
   secondary-memory/context as the primary class; state confidence and protected invariant impact.
8. **Reconcile locally.** Determine whether evidence conforms to, extends, or proposes reshaping the
   SBS and whether it preserves existing owner boundaries.
9. **Return globally.** Submit accepted changes to the owner artifact; create bounded Issues only for
   executable cleanup or migration. Review artifacts never become canonical by accumulation.
10. **Verify and compact.** Re-read changed owners and dependent representations, update the compact
    review state, and retain raw evidence through anchors rather than prompt accumulation.

### Worker delegation contract

Delegate only contracts whose semantics are already bounded. Every worker returns:

```text
review_target
task
observation
interpretation
classification
representation_class
evidence (file:line or durable external object)
source_authority
confidence
ambiguity
unresolved_questions
```

Workers may inventory, extract, map, or check consistency. They do not silently promote an
interpretation to canonical truth. The semantic owner verifies every source used in synthesis.

## 8. Context, model-routing, and TCD execution plan

### Cost drivers

The dominant costs are semantic error and human reconstruction, not raw token price. Re-reading the
SBS, semantic map, ontologies, and authority rules for every target is expensive; transferring an
ambiguous subsystem to a new model loses more than it saves. High-volume occurrence inventories and
schema mapping are cheap and independently verifiable. Human review cost rises sharply when current,
target, and historical claims are mixed in one artifact.

### Stable semantic context

Keep a stable, versioned prefix containing:

- repository instructions and review protocol;
- Project Kernel, doctrine, accepted ecosystem decisions, and definition ownership;
- current-versus-target authority rules;
- SBS topology and crosswalk;
- semantic system map;
- accepted ontology overlap rule once reconciled;
- canonical nomenclature and supersession decisions;
- the invariant kernel; and
- compact accepted findings and unresolved conflicts.

### Target-specific context

Load only the target's owner docs, boundary charter, contracts/schemas, current code/tests, active
Issues/PRs where relevant, and necessary history. Remove raw inventories after synthesis while keeping
anchors and derived tables.

### Evidence that remains external

Occurrence lists, source excerpts, full git logs, screenshots, generated projections, CI logs, and
historical design packages remain in repository or authoritative external objects. The working context
keeps references, not copies.

### Model routing

| Work | Preferred route | Safe switching boundary |
|---|---|---|
| Global baseline, ontology overlap, ecosystem/SBS ambiguity, cross-cutting reconciliation | Sol semantic owner | Do not switch while the taxonomy or owner relation is itself under question |
| Bounded subsystem/capability interpretation, migration plan, semantic verification, independent critique | Terra | Safe after target owner, taxonomy, evidence contract, and non-goals are fixed |
| Search, occurrence inventory, extraction, tabulation, known-taxonomy classification, mechanical cleanup verification | Luna; Terra/low if Luna unavailable | Safe when output is structured, source-anchored, and contains no authority decision |

Avoid model switching for global synthesis, ontology reconstruction, contested boundaries, and final
canonical reconciliation. Use workers for evidence rather than independent “understand and decide”
prompts. Keep one semantic-owner thread/context for the program as far as the environment permits.

### Lowest-TCD sequence

1. reconcile the ontology entry points and naming-lifecycle ambiguity first;
2. freeze the compact accepted baseline in owner-linked repository form;
3. run bounded targets in dependency order with cheap evidence extraction;
4. conduct cross-cutting reviews only after their contributing targets have evidence;
5. reconcile globally in one semantic-owner pass;
6. update normative owners minimally; and
7. fan out mechanical cleanup and verification only after decisions are bounded.

## 9. Ordered review-target inventory

| Order | Target | Class | Why now / dependency | Likely route |
|---:|---|---|---|---|
| 1 | Semantic authority graph and Cognitive Ontology ↔ Functional Ontology overlap | Cross-cutting governance | Resolves F1 and fixes the routing prefix for every later review | Sol |
| 2 | Ecosystem identity and nomenclature lifecycle: Yggdrasil/Mimer/Heimdal/Hugin/Munin | Ecosystem/cross-cutting | Resolves F2/F3; prevents false constituent assumptions | Sol with Luna inventory |
| 3 | Current spine ↔ target SBS ↔ shipped runtime | System/structural | Establishes current/target allocation discipline | Sol/Terra |
| 4 | HKA–SIP–PDM identity, artifact, provenance, and storage boundary | Subsystem cluster | Core identity/representation invariant; prerequisite for derived surfaces | Sol/Terra |
| 5 | GOV–CAO–EXE proposal, authority, capability, and effect boundary | Subsystem cluster | Core mutation chain and capability meaning | Sol/Terra |
| 6 | DRI–RCA retrieval, projection, evidence, and context assembly | Subsystem/capability cluster | Tests retrieval ≠ truth and schema/runtime maturity | Terra |
| 7 | MEM memory lifecycle, review, promotion, and knowledge materialization | Subsystem/cross-cutting | Highest secondary-memory contamination risk | Sol/Terra |
| 8 | WSP–SFC scope, workspace, principal, device, replica, and cross-scope semantics | Subsystem cluster | Tests context/topology/policy non-collapse | Sol/Terra |
| 9 | HIX and UI/design projection terminology | Subsystem/interface | Resolves active Hugin labels and UI authority representation | Terra with Luna inventory |
| 10 | EBF/Heimdal/external interface and event semantics | Interface/constituent | Separates external mechanism, candidate evidence, and authority | Terra |
| 11 | OEF/CES observability, verification, evolution, and deprecation | Cross-cutting stewardship | Validates governance of semantic change itself | Sol/Terra |
| 12 | Capability inventory and functional allocation across human flows | Capability/system | Run after owner/taxonomy reconciliation; avoid synthetic FBS | Terra with Luna mapping |
| 13 | Builder System, CKM, devUI, skills, generated context, and delivery vocabulary | Cross-system boundary | Prevents builder projections from contaminating Product semantics | Sol/Terra |
| 14 | Global reconciliation across all accepted target findings | Global | Produces minimum coherent owner-doc update | Sol only |

## 10. Storage recommendation and compact review state

Do not create a semantic database or a new top-level ontology hierarchy.

| Material | Existing home | Rule |
|---|---|---|
| Canonical meanings | Existing ontology/concept/contract owner docs and accepted ADRs | Update the owner; never make this audit canonical |
| Structural ownership/current realization | SBS/current architecture/boundary registers | Keep target and shipped posture explicit |
| Review evidence and analysis | Dated `docs/audits/` snapshot | File-line anchors; advisory and immutable except explicit correction/supersession notes |
| Accepted semantic decision | Existing owner doc and ADR when owner-reserved | Link back to the audit finding and preserve supersession provenance |
| Executable cleanup/migration | Bounded GitHub Issue and PR | Issue is work, not semantic SoT |
| High-volume inventory | Regenerable script output, issue attachment, or generated projection | Do not keep in stable semantic context |
| Builder operational state | BuilderOps records/projections where their contracts apply | Never Product/runtime memory without promotion |
| AI-memory reconciliation | Post-reconciliation plan and bounded external-memory update | Repository owner truth first; never update memory from an unresolved audit |

### Review state snapshot — baseline 2026-08-08

```yaml
accepted_baseline:
  repository_sha: 6d5f23ab6b6445f7dfd6e26c6268e85132ea7941
  ecosystem: "Yggdrasil apex; Mimer undivided knowledge-and-cognition; Heimdal sensor; private-bindings; Hugin/Munin reserved"
  semantic_authority: "distributed owner-doc graph routed by DOCS_INDEX; scoped owner wins"
  structural_posture: "current runtime architecture distinct from target SBS"
canonical_concepts_discovered:
  - functional ontology object families
  - seven semantic layers and authority roles
  - SBS macro-domains and control boundaries
  - orthogonal semantic dimensions
  - governed authority transition and derived-representation posture
unresolved_ambiguities:
  - Cognitive Ontology versus Functional Ontology overlap and entry-point ownership
  - lifecycle intent of Hugin/Munin in scaffolding and Companion UI terminology
  - mixed-status Heimdal and candidate-constitution routing
  - schema presence versus production-path enforcement by target
active_review_target: none
completed_review_targets:
  - system-wide semantic governance discovery
  - first high-level baseline
  - initial nomenclature and representation scan
cross_cutting_findings:
  - current/target/historical posture must remain explicit
  - derived and Builder surfaces must not become Product semantic authority
decisions_pending_reconciliation:
  - explicit ontology overlap rule
  - compatibility/deprecation disposition for reserved names at active use sites
downstream_cleanup_candidates:
  - companion-ui term mapping and visible Hugin labels
  - Mimer scaffolder layout and guard test
  - Heimdal mixed-status entry prose
  - candidate constitution reconciliation
  - partial OpenAPI discovery posture
```

Future reviews update the accepted baseline only after owner reconciliation. Dated audit evidence stays
point-in-time; a later audit supersedes this snapshot rather than silently rewriting its observations.

## 11. Global reconciliation plan

1. Aggregate only evidence-backed target findings and separate observation from interpretation.
2. Resolve conflicts by owner scope and accepted decision precedence; if the owner relation itself is
   unclear, route one owner decision rather than inventing consensus.
3. Test every proposed conclusion against current runtime truth, target SBS posture, semantic
   topology, and protected invariants.
4. Produce the minimum coherent change set: owner-doc update first, dependent contract/schema changes
   second, representations third.
5. Record supersession, compatibility aliases, and historical provenance explicitly.
6. Re-run affected target reviews against the candidate reconciliation.
7. Promote executable residuals to existing Issues where possible; use `feature-breakdown` only when
   one accepted capability spans independently verifiable slices.
8. Rebuild derived context and update the compact review state from the accepted owner surfaces.

SBS reconciliation for this audit: **conforms**. The audit uses the existing Mimer/Yggdrasil ecosystem
decision, target SBS, crosswalk, and Builder System boundary. It proposes no new subsystem, control
boundary, interface owner, or restructure.

## 12. Downstream cleanup strategy — plan only

Cleanup follows accepted semantic decisions and is classified per representation:

| Surface | Eventual action options | Verification posture |
|---|---|---|
| Normative docs and glossary | update owner, add explicit overlap/supersession rule, or preserve with historical marker | owner-doc cross-reference and DOCS_INDEX routing review |
| Derived docs and generated context | regenerate or annotate from the reconciled owners | source watermark and no-hand-edit check |
| Schemas/metadata | migrate only if accepted semantics require a machine contract change | producer inventory, migration, preflight, and schema/runtime tests |
| Source code/config/filesystem names | preserve as compatibility alias, deprecate, migrate, or remove under a bounded Issue | caller/data inventory, backward-compatibility plan, focused tests |
| UI/design system/handoffs | update current term map and active UI copy; retain dated design history as history | design-system contract plus interaction/source provenance checks |
| Builder System/skills/workflows | update only when routing or execution semantics change | skill consistency and Product/Builder separation checks |
| Issues/roadmaps | link accepted findings to existing work; create only bounded non-duplicate tasks | live duplicate search and `Verify:` targets |
| Persistent AI memory | replace volatile architectural assertions with “consult current repo owner docs” pointers; preserve only stable governance rules | compare against reconciled canonical owners; no update during this audit |

No cleanup in this table is authorized by the baseline alone.

## 13. Research-question resolutions

1. **Recognized things and owners:** answered by the ecosystem model, SBS, semantic layers,
   functional/cognitive ontologies, specialist contracts, and representation classes above. The
   remaining high-level ambiguity is the ontology overlap rule.
2. **Semantic SoT:** a governed graph of scoped owner artifacts, accepted ADRs, and current runtime
   evidence; not one file or database.
3. **Current/target/representation relation:** current architecture owns shipped reality, SBS owns
   target control boundaries, semantic owners define meaning, schemas represent contracts, boundary
   registers state maturity, and derived/UI/Builder surfaces never self-promote.
4. **Obvious divergences:** F1–F7 are sufficient for the first target wave; the audit deliberately
   avoids turning every occurrence into a finding.
5. **Continuity:** one semantic-owner context, a stable owner-linked prefix, bounded evidence workers,
   this compact review state, dated audits, and owner-doc reconciliation preserve continuity without a
   new ontology subsystem.

## 14. Dependency-ordered program handoff

```text
Baseline accepted as advisory evidence
  -> ontology-entry-point review
  -> ecosystem/nomenclature lifecycle review
  -> current-spine/target-SBS review
  -> bounded subsystem and capability reviews
  -> cross-cutting authority/memory/context/verification reviews
  -> global reconciliation proposal
  -> owner/ADR decisions only where authority is reserved
  -> normative owner updates
  -> bounded downstream cleanup Issues/PRs
  -> derived-context and AI-memory reconciliation
  -> semantic verification and next dated baseline
```

Existing issue reconciliation:

- closed epic [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) and children
  #2534–#2552 established much of the foundation; this program reviews and evolves that work rather
  than reopening it;
- closed epic [#1363](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1363) established the
  seven-layer semantic map and its supporting contracts;
- open Issue [#3957](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3957) already owns the
  narrower current-architecture authority-boundary trim; and
- no new implementation or cleanup Issue is created by this first baseline. Findings must first pass
  their ordered target review and canonical reconciliation.
