State: Proposed target-state specification from issue #4698; BSC-01's pure governing-document
inventory composer, BSC-02's pure workflow-adapter and capability-binding composer, and BSC-03's
pure coverage/deviation and governed-route composer are delivered as nonvisual partial inputs.
BSC-04 design, BSC-05 previews, route/UI, commands, and the whole lens remain undelivered.
Delivered inputs and target contracts are separated below.
Doc role: Capability specification and hard authority boundary for the separate devUI Builder
System Control lens.
Authority: `docs/DEVUI.md` owns the owner experience. This document owns the target information,
source-state, coverage, deviation, and sequencing contracts for the lens. Every governing document,
workflow, GitHub surface, repository artifact, BuilderOps record, and receipt retains its existing
authority.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit delivered-input ledger
Review cadence: Event-driven
Source of truth: Owner documents own policy and intended behavior; workflow contracts own their
admission and receipts; live sources own observations; GitHub and repository evidence own delivery
truth. This lens owns none of them.
Last reviewed: 2026-08-10

# devUI Builder System Control

## Outcome

Builder System Control gives the owner one separate place to ask whether the Builder System is
governed and operating as intended. It orients across governing documents, workflow adapters,
bounded tool capabilities, policy/source coverage, freshness, exceptions, unknowns, and explicitly
correlated delivery-route deviations.

It is a read-time/rebuildable orientation projection and governed-command boundary. It does not
decide policy, advance a workflow, create work, reconcile sources, or become the source of truth for
anything it displays. No runtime, route, or visual implementation is delivered by this
specification.

## Current-to-target truth

| Surface | Status | Truth retained by the target lens |
| --- | --- | --- |
| `docs/DOCS_INDEX.md` and owner documents | Current delivered input | Document role and authority routing; the lens links and summarizes but does not copy their truth into a registry. |
| `docs/architecture/SBS_OPERATING_MODEL.md` | Current delivered input | Builder System boundary, artifact ownership, allowed write paths, and receipts. |
| `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` | Current delivered input | Descriptive system/process observations and target automation map, not new workflow authority. |
| Repo-local skill contracts | Current delivered input | Versioned workflow instructions and refusal/receipt behavior at their exact source refs. |
| MCP, connector, script, and CLI declarations | Current delivered input where explicitly declared | Bounded operations and admission surfaces; absence or unread declarations remain honest gaps. |
| BuilderOps, dispatcher, GitHub, Git, CI, review, and receipt evidence | Current delivered input where available | Live or durable observations under each source's own authority and watermark. |
| `devui.composition.v1`, Focus, and Conversation Port contracts | Current delivered inputs or accepted target contracts as named by their own docs | Shared presentation primitives and evidence axes only; they do not make this lens delivered. |
| BSC-01 governing-document inventory composer | Delivered partial input; no route, UI, or effect is delivered | Composes only explicit governing-document declarations per read, preserves source-owned authority/lifecycle/state evidence, and never discovers, copies, or decides document truth. |
| BSC-02 workflow-adapter and capability-binding composer | Delivered partial input; no source discovery, route, UI, command, or effect is delivered | Composes only explicit skill/MCP/connector/script/CLI declarations per read, preserves their exact refs, operations, ownership, admission boundary, source axes, and limitations, and withdraws unsupported ownership or authority claims rather than inferring them. |
| BSC-03 coverage/deviation and governed-route composer | Delivered partial input by issue #4725; no source discovery, UI, command, or effect is delivered | Composes only explicit bounded coverage, exception, unknown, intended/observed correlation, and governed-route declarations per read; incomplete completeness/exception evidence is withdrawn locally and a route remains navigation only. |
| `BuilderSystemControlView.v1` | Target contract; partially delivered | BSC-01..03 compose only explicit governing-document, workflow-adapter, capability-binding, coverage, deviation, and governed-route records per read; BSC-04 design, BSC-05 previews, route/UI, commands, and the whole lens remain undelivered. |
| Builder System Control route and UI | Target contract; not delivered | Separate system-governance context, pending implementation and governed design handoff. |
| Command proposals | Target contract; not delivered | Later proposals may route only to existing governed workflows. |

The status of an input is not inherited by the composed view. A delivered source may be stale,
unavailable, unread, unsupported, unlinked, missing, or measured empty at a particular read. A
target contract does not become delivered merely because this specification names it.

### Governing and supporting baseline

- `docs/DEVUI.md` and the accepted Focus boundary from PR #4699 govern the owner journey and hard
  sibling separation.
- The accepted cross-plane authority, artifact-lifecycle, and discovery vocabulary is in
  `docs/architecture/INFORMATION_AUTHORITY_MODEL.md`,
  `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`, and
  `docs/architecture/DEVUI_DISCOVERY_ARCHITECTURE.md`; those records remain subordinate to this
  lens's accepted local contract and do not alter its local semantics.
- `docs/architecture/SBS_OPERATING_MODEL.md` governs Builder System classification, artifact
  ownership, allowed write paths, and receipts.
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, refreshed by the process clarification in PR
  #4692, is a descriptive inventory and routing composition; each workflow it links retains its
  own authority.
- `docs/DOCS_INDEX.md` is the role/routing map for document reads. It is not a copied source
  registry.
- `docs/audits/BUILDER_SYSTEM_DEVUI_EXECUTION_ARCHITECTURE_2026-08-09.md` from PR #4689 is advisory
  source/design evidence. It can motivate or test this contract but cannot make target behavior
  delivered or authoritative by itself.
- `docs/audits/BUILDER_SYSTEM_INTENT_EVIDENCE_GOVERNANCE_2026-08-10.md` is advisory comparison and
  document-class evidence. This specification imports only its iterative intent–evidence,
  late-change visibility, and verification-versus-validation boundaries; the audit remains
  non-authoritative.

## Information architecture and hard boundary

```text
devUI shell
├── Overview / Cockpit — cross-subject orientation
├── Focus — one stable Issue or capability
│   └── Conversation Port — subject-bound external reasoning and governed proposal
└── Builder System Control — one explicit Builder System governance scope
    ├── Governance map — documents, roles, authority, ownership, lifecycle
    ├── Workflow map — versioned skill adapters and their owning workflows
    ├── Capability map — MCPs, connectors, scripts, and CLIs
    ├── Assurance map — coverage, freshness, drift, exceptions, unknowns
    └── Route map — intended and explicitly correlated observed delivery routes
```

Builder System Control is not a tab, panel, or evidence group inside Focus. Entering it replaces the
subject identity with `builder_system`, changes the header and evidence scope, and does not carry a
Focus claim into the system lens. Returning to Focus restores the prior stable subject. Cross-links
are navigation, never a data join.

The lens may link to a stable Issue/capability Focus or to an existing governed workflow. It may not
surface a global provider-session view, infer that a session is work, or treat provider provenance
as delivery authority. Cockpit -> Detail -> governed Command/Receipt remains the journey for any
later consequence. The lens is the Detail/orientation boundary, not a parallel backlog or autonomous
decision-maker.

### Lens-owned presentation

- the selected Builder System scope and governance baseline;
- source-owned document roles, authority scopes, owners, lifecycle, and freshness;
- skill adapters and bounded capabilities with exact source/version references;
- coverage claims, exceptions, unknowns, measured-empty reads, and limitations;
- intended/observed route differences only when an owning source provides explicit correlation; and
- links to source evidence and already governed repair or inquiry routes.

### Explicit non-authority

The lens owns no policy, workflow transition, task, queue, claim, session, source registry, delivery
graph, correlation, severity, approval, mutation, or durable disposition. It never writes GitHub,
the repository, BuilderOps, a provider, or an external system directly. It never promotes a
descriptive process-map observation into intended governance.

### Intent–evidence continuity

The target lens orients across the existing intent-to-evidence chain only when each relationship is
declared by its owning source. Progressive detail should answer which intent, need, outcome,
decision, or constraint governs the route; which capability/specification and Issue received it;
which PR/SHA evidence verifies it; whether a later change superseded a source or invalidated proof;
and whether the result is verified, **Ready to try**, tried, or accepted.

An absent relationship uses the existing source-state axes as unlinked, unread, missing, stale,
unavailable, or not assessed; composition never repairs it by inference. Discovery and delivery may
loop in either direction. A late change is not a deviation by itself: a deviation needs a
source-owned intended route, explicit observed correlation, and the source or receipt recording the
changed decision and affected evidence.

## Minimal data and state contract

`BuilderSystemControlView.v1` is composed per read and is safe to discard and rebuild:

```yaml
contract_version: builder-system-control-view.v1
authority: projection_only
primary_identity: builder_system
scope:
  kind: builder_system
  repository_ref: string
  governance_baseline_ref: SourceRef.v1
composed_at: RFC3339
governing_documents: [GoverningDocumentView.v1]
workflow_adapters: [WorkflowAdapterView.v1]
capability_bindings: [CapabilityBindingView.v1]
coverage: [CoverageView.v1]
deviations: [RouteDeviationView.v1]
governed_routes: [GovernedRouteRef.v1]
limitations: [Limitation.v1]
```

The view is invalid if its primary identity is a Focus subject, if any material claim lacks an
owning source/authority class, or if a child record silently becomes authoritative through
composition.

### Shared source state axes

Every material record carries independent source axes rather than one overloaded status:

| Axis | Allowed values | Requirement |
| --- | --- | --- |
| `availability` | `available`, `unavailable`, `refused`, `unsupported` | Anything except `available` withdraws dependent claims; it never means empty. |
| `freshness` | `fresh`, `stale`, `unknown` | Evaluated against the owning source's named policy, observation time, and watermark. |
| `coverage` | `complete`, `partial`, `unread`, `missing`, `not_applicable` | `unread` is not `missing`; neither permits a negative governance claim. |
| `cardinality` | `nonempty`, `measured_empty`, `not_measured`, `not_countable` | `measured_empty` requires a successful bounded read, exact scope, and watermark. |
| `linkage` | `linked`, `unlinked`, `not_assessed`, `not_applicable` | Only an explicit source-owned link supports a joined or deviation claim. |

Each state envelope also carries `captured_at`, source-specific `fresh_until` or freshness rule,
`read_scope`, `read_watermark`, and `limitations`. The view says **fresh**, **stale**,
**unavailable**, **unread**, **unsupported**, **unlinked**, **missing**, and **measured empty**
without collapsing them into blank, healthy, zero, or a confidence score. Composition time is not a
claim that all sources form one atomic snapshot.

### GoverningDocumentView.v1

```yaml
source_ref: SourceRef.v1
role: string
authority_class: normative | operational | reference | projection | receipt
authority_scope: string
owner_ref: SourceRef.v1 | null
lifecycle:
  phase: draft | proposed | accepted | superseded | retired | unknown
  temporal_class: strategic | operational | snapshot | historical | unknown
  review_cadence: string | unknown
  supersedes_refs: [SourceRef.v1]
  superseded_by_refs: [SourceRef.v1]
source_state: SourceState.v1
limitations: [Limitation.v1]
```

The record reports the document's declared role and authority. When no owner is declared,
`owner_ref` is null and the source state is `missing`; the lens does not invent one. It does not
decide conflicts or silently infer lifecycle from file age. Conflicts link to the owning
docs-governance path.

### WorkflowAdapterView.v1

```yaml
source_ref: SourceRef.v1
adapter_kind: skill
adapter_id: string
version_or_digest: string | unknown
owning_workflow_refs: [SourceRef.v1]
owning_policy_refs: [SourceRef.v1]
trigger: string
input_contract_refs: [SourceRef.v1]
output_and_receipt_refs: [SourceRef.v1]
refusal_and_authority_limits: [string]
source_state: SourceState.v1
limitations: [Limitation.v1]
```

A skill is a versioned workflow adapter: it makes an owning workflow usable by an agent or operator
at a specific source version. A skill is never the policy owner. A missing version/digest is rendered
as `unknown` with `missing` or `unlinked` source state; a missing owning workflow is likewise
`missing` or `unlinked`. The lens does not fabricate either.

### CapabilityBindingView.v1

```yaml
source_ref: SourceRef.v1
capability_kind: mcp | connector | script | cli
capability_id: string
version_or_digest: string | unknown
owning_workflow_refs: [SourceRef.v1]
available_operations: [string]
side_effect_class: read_only | governed_write | external_effect | mixed | unknown
admission_boundary_ref: SourceRef.v1 | null
explicit_non_authority: [string]
source_state: SourceState.v1
limitations: [Limitation.v1]
```

An MCP, connector, script, or CLI is a bounded capability exposed to an owning workflow. A
capability is never the policy or workflow owner. Availability does not grant admission, approval,
or mutation authority; those stay with the cited workflow and authentication boundary.

### CoverageView.v1

```yaml
claim_id: string
source_ref: SourceRef.v1
authority_scope: string
governing_source_refs: [SourceRef.v1]
completeness_definition_ref: SourceRef.v1 | null
assessed_scope: string
source_state: SourceState.v1
drift_observations: [DriftObservation.v1]
exception_refs: [SourceRef.v1]
exceptions: [CoverageException.v1]
unknowns: [string]
limitations: [Limitation.v1]
```

Coverage is an evidenced statement about one bounded scope, never a score for the Builder System as
a whole. `complete` requires an owning definition of completeness and a fresh successful read.
Drift is a descriptive difference between source versions or between an intended source and an
explicitly correlated observation. An exception must name the authority that permits it and its
lifecycle/expiry; otherwise it is an unknown or deviation, not an exception.

`CoverageException.v1` preserves `source_ref`, `permitting_authority_ref`, `lifecycle_ref`,
`expires_at`, and limitations. A missing, expired, or malformed authority/lifecycle declaration is
not admitted into `exceptions` or `exception_refs`; the supplied exception remains an explicit
unknown marker. An unavailable, stale, unlinked, or otherwise incomplete coverage record withdraws
only its own `complete` claim and never changes an unrelated record.

### RouteDeviationView.v1

```yaml
deviation_id: string
source_ref: SourceRef.v1
authority_scope: string
intended_route_refs: [SourceRef.v1]
observed_route_refs: [SourceRef.v1]
correlation_ref: SourceRef.v1
observed_at: RFC3339
difference: string
source_state: SourceState.v1
existing_repair_route_ref: GovernedRouteRef.v1 | null
repair_route_linkage: linked | unlinked | not_assessed
repair_route_correlation_ref: SourceRef.v1 | null
limitations: [Limitation.v1]
```

A deviation requires an intended route owned by a governing source, an observed route owned by live
evidence, and a positive source-owned correlation between them. Textual similarity, shared provider
metadata, and temporal proximity are not correlation. The projection describes the difference and
does not invent a severity, policy breach, or repair state. `source_state.linkage` remains `linked`
for every admitted deviation because it describes the intended-to-observed correlation. A null
`existing_repair_route_ref` requires `repair_route_linkage: unlinked` or `not_assessed` and no
offered action. In that state, `repair_route_correlation_ref` is also null. A non-null route requires
`repair_route_linkage: linked` and a non-null, source-owned `repair_route_correlation_ref` proving
that the route applies to this exact deviation. When an existing governed repair, inquiry,
docs-governance, issue-maintenance, or owner-decision route is available, both exact refs are
required; the lens never substitutes or invents either.

### GovernedRouteRef.v1 and limitations

A route reference names the existing workflow source, exact entrypoint, required authority or
approval, accepted inputs, expected side effects/non-effects, expected receipt, and availability.
It is navigation until a separately delivered typed proposal adapter binds exact fresh inputs.
Limitations are first-class records with affected claims, source refs, observed time, and whether
the dependent claim is withdrawn.

```yaml
route_id: string
source_ref: SourceRef.v1
entrypoint: string
authority_or_admission_ref: SourceRef.v1
accepted_inputs: [string]
expected_side_effects: [string]
expected_non_effects: [string]
receipt_ref: SourceRef.v1
source_state: SourceState.v1
limitations: [Limitation.v1]
```

## Interaction flows

### Orient and inspect

1. Open Builder System Control from the devUI shell with an explicit repository and governance
   baseline.
2. Read the trust frame: composition time, independent source watermarks, withdrawn claims, and
   material limitations.
3. Scan the five maps: governance, workflow, capability, assurance, and route.
4. Select one record to inspect its exact source, declared role/owner, lifecycle, freshness,
   correlation, and evidence.
5. Follow a source link, navigate to a stable Focus subject, route to an existing governed
   workflow, or take no action.

This remains Cockpit -> Detail -> governed Command/Receipt. Unresolved owner questions appear as a
detail-bound question with the governing source, why agent authority is insufficient, options and
consequences, freshness, and the existing owner-decision route. They do not become lens-owned tasks,
parallel backlog entries, or automatic decisions.

### Future governed command preview

The first BSC specification delivers no command. A later slice may render a typed command proposal
only when an existing destination workflow already owns admission, exact inputs, side effects,
approval, freshness invalidation, idempotency/readback, and receipts. The preview must show:

- proposal type and exact canonical inputs;
- source refs, versions/digests, correlations, and absolute expiry;
- destination workflow and entrypoint;
- expected side effects and explicit non-effects;
- approval rule and authenticated principal requirement;
- expected receipt and ambiguous-outcome behavior; and
- **Start/Hold** for workflow initiation or **Apply/Hold** for an already governed change.

Changed input, source, correlation, authority rule, destination contract, or freshness withdraws the
action. **Hold** has no durable effect. Conversation or explanatory prose is never executable. The
destination workflow executes and receipts the effect; Builder System Control does not.

## Source, correlation, freshness, and limitation requirements

1. Every claim links to the exact source ref and authority class that owns it. A projection or
   descriptive audit never overrides an owner document, GitHub, Git, CI, review, merge, or receipt.
2. Reads are source-specific. Each source exposes its own captured time, watermark, freshness rule,
   read scope, availability, coverage, cardinality, linkage, and limitations.
3. `measured_empty` is legal only after a successful bounded read whose exact scope and watermark
   are visible. Failed, refused, unsupported, stale, unread, or unlinked reads cannot prove zero.
4. Cross-source joins and intended/observed comparisons require an explicit stable correlation
   emitted by an owning source. The composer does not infer links from names, prose, sessions, or
   timestamps.
5. Provider transcripts and sessions are provenance only. The lens neither discovers nor stores a
   global session inventory and never treats a session as work or delivery authority.
6. A source failure withdraws only dependent claims. The remainder of the lens stays usable and
   names the limitation; absence is never silently rendered as health.
7. The lens does not persist copied source truth. Optional caches, if later introduced, are
   disposable transport aids with source versions and cannot become a registry or recovery
   authority.

## Process-health model

Process health is a multidimensional, evidence-bound orientation model for a **named Builder System
process step** from `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`. It asks whether that one step
is supported and continuing as its existing intended-process authority describes; it is not a
productivity score for the Builder System, a universal lifecycle, or a claim about a person, agent,
team, or repository as a whole.

Each process-health record names its step, the intended outcome cited from the process map or
owning workflow, the source owner for each input, independent evidence state, and a limitation. A
step is only in scope when its identity and intended outcome are explicitly declared. A read that
cannot establish either yields a typed `unknown` or withdrawal, not a synthesized health result.
The model is composed per read, rebuildable, and advisory: it has no policy, workflow, task,
session, release, prioritization, evaluation, ranking, or action authority.

The six dimensions are intentionally separate. A healthy-looking value on one dimension neither
fills a missing dimension nor implies that the step is delivered, correct, accepted, or suitable for
continuation. The lens presents the step, inputs, state envelope, denominator/window where present,
and limitations before any compact summary.

## Process-health dimensions

| Dimension | Per-step question and bounded evidence inputs | Can claim | Cannot claim |
| --- | --- | --- | --- |
| Coverage / maturity | For the named step, which explicitly declared required process elements, source declarations, or admitted capabilities have source-owned evidence? Inputs are the step's owner-defined requirement set and its linked source-state/coverage records. | Observed coverage of the declared set, or a bounded maturity observation when the owning source defines stages. | Universal completeness, delivery, quality, or maturity when the requirement set, denominator, or stage owner is absent. |
| Flow / continuation | Does source-owned route or receipt evidence show the declared step continuing through its next intended legal transition? Inputs are explicit intended-route refs, observed-route refs, and transition/receipt facts. | That an explicitly correlated route continued, paused, or is not evidenced in the stated window. | Causality, throughput, success, or a lifecycle transition inferred from time, prose, branch, session, or name similarity. |
| Late stop / rework | Did a source-owned stop, invalidation, supersession, or repair receipt identify work that reached this step before the stop? Inputs are explicit late-stop/rework facts and their stable correlation to the step. | Count or presence of explicitly evidenced late stops/rework in the bounded cohort/window. | Defect rate, blame, avoidability, cost, or causal attribution; ordinary iteration is not rework without an owning source's fact. |
| Escalation quality | When the step produces an escalation, did its owning workflow provide the declared authority, options/consequences, evidence, and receipt/readback? Inputs are explicitly linked escalation and owner-decision/workflow records. | Whether declared escalation-quality fields are evidenced or missing for that step. | Whether the decision was substantively right, whether the owner should decide, or an evaluation of the owner, worker, or agent. |
| Autonomous continuation | Where the owning workflow permits agent continuation, did source-owned evidence show a lawful continuation, a stop, or a required handoff? Inputs are workflow admission/authority rules plus explicit continuation, refusal, and receipt facts. | That a permitted continuation is evidenced, withdrawn, or unknown under the declared rule. | That autonomy is desirable, safe generally, equivalent to acceptance, or permission to bypass a named authority boundary. |
| Understanding / trust | Does the step's owner-facing evidence frame expose situation, meaning, next step, source freshness, disagreement, and material limitations? Inputs are source-owned state envelopes and the devUI cognitive-load/decision-support contract. | Whether the declared evidence needed to inspect and interpret this step is present, degraded, or unread. | A person's understanding, confidence, satisfaction, or trustworthiness; it is a presentation-evidence condition, not a psychometric measure. |

No dimension is populated from an unsupported substitute. In particular, GitHub provides only the
Issue/PR facts it owns; Git and CI/review/merge readback provide their own delivery facts;
BuilderOps and receipts provide only their recorded facts; and owner documents/workflow contracts
provide intended process semantics. A source's availability alone does not prove the dimension.

## Measurement contract

Every populated process-health dimension carries this measurement envelope; field absence is not
permission to estimate it:

```yaml
process_step_ref: SourceRef.v1                 # explicit process-map/workflow step identity
intended_outcome_ref: SourceRef.v1             # owner-defined intended outcome
dimension: coverage_maturity | flow_continuation | late_stop_rework |
  escalation_quality | autonomous_continuation | understanding_trust
source_inputs: [SourceRef.v1]                  # each input with its owning authority
population_or_cohort: string | unknown         # exact admitted step instances
evaluation_window:
  event_from: RFC3339 | unknown
  event_until: RFC3339 | unknown
denominator: integer | not_countable | unknown
numerator: integer | not_countable | unknown
minimum_evidence: string                       # owner-defined admission rule for this dimension
event_time: RFC3339 | unknown
observation_time: RFC3339
source_watermark: string | unknown
fresh_until: RFC3339 | unknown
state: evidenced | measured_empty | partial_window | disagreement | stale | unread |
  unavailable | refused | missing | unlinked | unsupported | unknown | withdrawn
limitations: [Limitation.v1]
```

Numerator and denominator are meaningful only for an owner-defined, countable population and one
compatible evaluation window. `measured_empty` requires a successful bounded read with a visible
population, event window, and watermark. A partial window is not a zero-filled full window.
Incompatible denominators, insufficient minimum evidence, unknown step membership, unlinked inputs,
or incomparable windows yield typed `unknown` or `withdrawn`; the composer never calculates a rate
or carries a prior value forward. Event time records when the source says something happened;
observation time records when it was read. Neither composition time nor freshness substitutes for
the other.

Freshness and expiry remain source-specific. A dimension displays its oldest material input
watermark and each input's freshness state; it may be `stale` while a different dimension for the
same step is fresh. A snapshot is a named read boundary, never evidence of an atomic cross-source
state.

## Authority and correlation boundaries

Owner documents and the Builder System process map define only intended process-step semantics,
outcomes, requirement sets, and authority boundaries. The process-health composer may cite those
declarations but cannot amend, normalize, or infer them. Live GitHub, Git, CI/review/merge
readback, BuilderOps, and receipts contribute only facts each source owns, with their own source
state, timestamp, watermark, and limitations.

Every cross-source input to a dimension requires an explicit stable correlation owned by a source
that may assert that relation. The composer never joins process events, cohorts, completions,
denominators, causes, or rework from names, prose, branch/session similarity, provider metadata, or
time proximity. When a correlation, input, or source authority is missing, the affected dimension is
`unlinked`, `unknown`, or `withdrawn` locally; unaffected dimensions remain visible with their own
limitations. devUI is a read-only composition and never becomes a process-health source of truth,
source registry, or repair authority.

## Anti-misleading-score safeguards

- Do not render or derive a generic Builder System productivity, efficiency, maturity, confidence,
  or health score. The six dimensions stay visible and independently stateful.
- Do not rank, compare, reward, penalize, or evaluate people, agents, workers, teams, repositories,
  or providers. This model describes evidence for a process step only.
- Do not hide weights, thresholds, imputations, denominator changes, stale carry-forward, or
  withdrawn inputs behind a summary. Any later optional aggregate is advisory only and must show
  every component, source, denominator/window, state, watermark, and limitation.
- Do not use a dimension or optional aggregate as a machine gate, release gate, policy rule,
  prioritizer, automation trigger, workflow transition, or sole input to an owner decision. It may
  orient the owner to source evidence and existing governed routes only.
- Refuse cross-process, cross-cohort, or cross-window comparisons unless an owning authority
  explicitly evidences compatible step semantics, population, denominator, window, and limitations.
  Similar labels or percentages do not establish comparability.
- Never render missing, unavailable, unread, refused, stale, partial, or incompatible evidence as
  healthy, zero, empty, neutral, or high trust.

## Process-health verification matrix

This is a specification verification matrix, not a claim that any collector, storage, API, route,
or visual surface exists.

| Case | Required process-health result | Prohibited rendering/inference |
| --- | --- | --- |
| Fresh | Show the bounded dimension value/state, source, cohort/window, watermark, and limitation. | Treat one fresh source as an atomic fresh step summary. |
| Stale | Retain the explicit stale state and affected claim; withdraw an expired claim where its source rule requires it. | Re-label stale evidence as current or silently carry it forward. |
| Missing | State `missing` or `unknown` for the affected input/dimension. | Healthy zero, empty, or assumed complete coverage. |
| Unread | State `unread` with the unperformed/unsupported read scope. | Equate unread with absent evidence or no events. |
| Unavailable | State `unavailable`, source identity, and limitation; preserve unrelated dimensions. | Suppress the failure or infer a negative/positive value. |
| Refused | State `refused` and the refusal reason/admission boundary. | Retry through an ungoverned path or treat refusal as measured empty. |
| Unknown | Preserve typed `unknown` where membership, denominator, authority, or minimum evidence is insufficient. | Estimate, impute, or score the unknown. |
| Measured-empty | Show the successful bounded read, exact cohort/window, and watermark. | Use a failed, stale, unread, or unlinked read to prove zero. |
| Partial-window | State `partial_window`, covered interval, missing interval, and limitation. | Divide as though the full window were observed. |
| Disagreement | Show the disagreeing source-owned facts and their scopes; withdraw any unsupported combined conclusion. | Select a preferred source or fabricate consensus. |
| Late-stop/rework | Show only the explicitly correlated stop/rework fact, step, cohort/window, and limitation. | Infer blame, defect rate, cause, cost, or a person/agent ranking. |

The matrix composes with the existing BSC source-state axes: coverage, freshness, exception,
unknown, measured-empty, and route-deviation remain their own source-owned facts. In the devUI
cognitive-load and decision-support frame, a process-health item must answer what is happening,
what it means, and what happens next while keeping source freshness, disagreement, and limitations
reachable at the same evidence depth. It may link to an existing governed route; it does not create
an action or decision authority.

## Existing governed routes

The target lens may navigate to, but does not reimplement, routes such as:

| Need | Existing route owner | Lens behavior |
| --- | --- | --- |
| Clarify or change a governing document | `docs-governance` and the narrower owning docs workflow | Link the conflict/source context; the PR path owns any change. |
| Convert accepted docs/spec into work | `docs-to-issue` or `feature-breakdown` | Supply exact source refs only after the source is authoritative. |
| Research an unresolved development question | `start-model-inquiry` | Link or later propose the existing artifact-first route; provider sessions remain provenance. |
| Repair Issue/PR/label/Project drift | `issue-maintenance-change-control` | Link explicit live evidence; the workflow owns mutations and readback. |
| Route a confirmed delivery divergence | `capture-learning`, then retrospective/`learning-to-issue` where applicable | Do not create a lens-local defect, task, or severity. |
| Escalate a genuine authority choice | `owner-decision-brief` | Present one bounded question only after technical routes are exhausted. |
| Verify and close delivered work | `verification-and-closure` and `post-merge-owner-doc` | Display resulting receipts; never synthesize closure. |

Route availability is itself source state. An unavailable route remains visible as unavailable; the
lens does not substitute an ungoverned action.

## Open implementation dependencies

- a source-discovery/composition contract that follows `DOCS_INDEX` and existing artifact maps
  without creating a copied source registry;
- stable, source-owned version/digest and ownership declarations for workflow adapters and bounded
  capabilities where current sources do not expose them;
- explicit correlations between intended workflows and observed GitHub/BuilderOps/delivery-route
  evidence;
- source-specific freshness/read-watermark adapters and safe withdrawal of dependent claims;
- a separate later implementation slice for explicit process-step input adapters and bounded
  fixtures; any collector, observation, storage, API, route, or UI remains outside this
  specification change;
- stable nonvisual fixtures for fresh, stale, unavailable, unread, unsupported, unlinked, missing,
  measured-empty, exception, and deviation cases;
- an authenticated action boundary plus destination-owned idempotency/readback before any typed
  proposal can become confirmable; and
- a governed visual design handoff after the nonvisual contracts and fixtures stabilize.

Technical gaps above route through their owning docs, workflow, source-adapter, or delivery path.
They are not owner decisions and do not justify a parallel engine.

## Open authority questions

No owner decision blocks this docs-only specification. Before runtime work admits stronger claims or
commands, the following questions must be answered by the authority that owns each source/workflow:

1. Which existing document declares completeness for each governance area, and where no such owner
   exists should the lens show `unknown` rather than propose one?
2. Which source is allowed to assert the stable intended-to-observed route correlation for each
   delivery family?
3. Which existing workflow owns disposition of a deviation when no repair route is currently
   declared?
4. Which document owns lifecycle/expiry rules for exceptions that today exist only as operational
   evidence?
5. Which authenticated destination workflows are eligible for later BSC typed proposals, and what
   replay/readback contract does each already provide?
6. Which existing owner may define countable cohorts, compatible denominators, minimum evidence,
   expiry, and comparison compatibility for each process-health dimension before a later data, UI,
   or implementation slice reads it?

Each answer must be recorded in the owning authority surface through its normal governed path. This
document does not answer by convention or implementation convenience. The later data, collector,
storage, API, visual/UI, or implementation work is separate follow-up scope and cannot be admitted
by treating this target-state specification as delivered behavior.

## Separate interaction and visual requirements

The future design handoff must preserve:

- a visibly different Builder System identity/header from any Issue or capability Focus;
- progressive disclosure from five calm orientation maps to exact evidence and limitations;
- source role, authority, freshness, and uncertainty before any health-like summary;
- equal first-class treatments for fresh, stale, unavailable, unread, unsupported, unlinked,
  missing, and measured-empty states;
- explicit visual separation of evidence/navigation from a future authority-bearing preview;
- unresolved owner questions inside their evidence detail and existing decision route, never in a
  new backlog; and
- reversible navigation back to the prior Focus without carrying or inferring correlations.

Claude Design availability affects BSC-04 only. It does not block the nonvisual contracts, source
inventory, composition, or fixtures that precede that handoff.

## Sequenced follow-up issue breakdown

These are bounded candidates for later governed issue creation. They must not be filed as children
of Focus parent #4693; Builder System Control remains a separate delivery line.

1. **BSC-01 — compose the source inventory (delivered by #4721).** Defines and implements a pure,
   per-read inventory of explicitly supplied governing documents with exact refs, declared
   role/authority/owner/lifecycle, source states, and hostile validation. No route or UI is
   delivered.
2. **BSC-02 — compose adapters and capabilities.** **Delivered partial input by issue #4723 / PR
   #4724.** Adds pure workflow-adapter and capability-binding projections over explicit
   skill/MCP/connector/script/CLI declarations. Missing ownership or admission boundaries withdraw
   dependent claims; the composer never infers policy.
3. **BSC-03 — compose coverage and route deviations (delivered by #4725).** Adds bounded explicit
   coverage/exception/unknown records, source-owned intended-versus-observed correlations, and
   governed repair-route references. It adds no severity, policy decision, UI, command, or effect.
4. **BSC-04 — governed visual design handoff.** Use stable fixtures from BSC-01..03 to validate the
   separate lens, degraded states, unresolved owner questions, accessibility, responsive behavior,
   and Command/Receipt boundary when the external design capability is available.
5. **BSC-05 — route previews over existing workflows.** After authenticated action admission and
   destination-owned replay/readback exist, add typed previews for a deliberately selected subset
   of existing governed workflows. No generic command language.

BSC-01 through BSC-03 are nonvisual and may proceed before BSC-04. BSC-05 depends on the accepted
design and each destination's authority contract. No follow-up creates a policy engine, workflow
engine, task system, or source registry.

## Cross-slice invariants

- Focus remains subject-centred; Builder System Control remains system-governance-centred.
- Cockpit, CKM, BuilderOps, Signboard, provider sessions, and this lens are projections or
  provenance according to their owning contracts, never replacement authority.
- Every durable consequence crosses an existing authenticated workflow and returns its existing
  receipt.
- Intent, decision, supersession, verification, and owner-validation relationships remain
  source-owned and independently evidenced; no delivery fact implies owner acceptance.
- No inferred links, copied work state, direct GitHub/repository mutation, global session view, or
  claimed system-wide atomic freshness is introduced.
- Current delivered capability and target-state design remain visibly separate in docs, tests, and
  future UI.
