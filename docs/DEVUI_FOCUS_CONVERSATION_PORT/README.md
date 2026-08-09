State: Proposed target-state specification with blocked parent #4693, children #4694–#4697, and
separate Builder System Control specification issue #4698; no runtime or visual implementation
claimed. The delivered inputs are listed separately under Current-to-target truth.
Doc role: Capability specification and implementation boundary for the first subject-centred devUI
Focus slice, its external Conversation Port, the Start Model Inquiry command preview, and the
separate Builder System Control lens.
Authority: `docs/DEVUI.md` owns the owner experience. This directory owns the target data,
interaction, correlation, freshness, and sequencing contracts for this slice. Existing workflow,
source, repository, GitHub, and receipt contracts retain their authority.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit delivered-input ledger
Review cadence: Event-driven
Source of truth: Owner documents and accepted specifications own intended behavior; live source
artifacts and receipts own observations; GitHub and repository evidence own delivery truth.
Last reviewed: 2026-08-09

# devUI Focus + Conversation Port

## Outcome

This slice gives the owner one stable place to understand a single Issue or capability and to take
that subject into an external Codex or Claude conversation without pretending that a provider
session is work. It admits one governed command only: a fresh, exact **Start Model Inquiry** preview
with **Start/Hold**, executed through the existing artifact-first workflow and followed by its
existing terminal receipt.

Builder System Control is specified here only as a hard neighboring boundary and minimal read
contract. It is a separate system-governance lens and a separate follow-up, not part of the first
Focus flow.

## Current-to-target truth

| Surface or contract | Current delivered capability | Target added by this specification |
| --- | --- | --- |
| CKM | Non-authoritative capability queries/snapshots and static owner projection | Subject evidence in Focus, without changing CKM authority |
| BuilderOps Cockpit | Fresh read-time work register | Explicitly correlated subject observations, not a copied work store |
| `devui.composition.v1` | Local, read-only, per-request CKM/Cockpit composition with typed source degradation | Input to a subject composer; it does not already provide Focus |
| Builder System process map | Governs pre-Issue routes, `PromotionIntent`, delivery correlation, and session provenance | Source for next-legal-step and limitation rendering |
| Model Inquiry | Durable artifact-first launcher and terminal receipt contract | One devUI preview and confirmation adapter over that unchanged route |
| Codex/Claude conversations | External provider interactions with no global authoritative session source | Export/open of one hash-bound context pack; no session inventory |
| Focus UI | Not delivered | Subject-centred read view and external Conversation Port |
| Builder System Control | Not delivered | Separate future read-oriented governance lens |

The advisory Builder System devUI execution audit in PR #4689 supplies source and presentation
findings for this design. It does not make its proposed Stage A shell or any contract here delivered.

## Information architecture and hard boundary

```text
devUI shell
├── Overview
│   └── select one stable Issue or capability
├── Focus — subject context
│   ├── intent · governing source · evidence · receipts · risks
│   ├── next legal step · explicitly correlated observations
│   └── Conversation Port
│       └── external Codex/Claude → disposition or typed proposal
└── Builder System Control — system-governance context
    ├── documents · workflow adapters · bounded capabilities
    └── coverage · freshness · drift · exceptions · deviations
```

Focus and Builder System Control may link to each other, but a link is navigation, not a data join.
The active header must always say whether the primary identity is `subject` or `builder_system`.
The same record cannot appear as both merely because its text or provider metadata looks related.

### Focus owns

- one `SubjectRef.v1` for an Issue or capability;
- owner intent and governing source references;
- evidence, receipt, risk, limitation, and next-legal-step projections for that subject;
- observations only through explicit source-owned correlations; and
- a subject-bound external Conversation Port and its command preview.

### Builder System Control owns

- one `BuilderSystemScopeRef.v1` for a repository/governance baseline;
- governing-document roles, authority, ownership, lifecycle, and freshness;
- workflow-adapter declarations and bounded tool/capability declarations;
- policy/source coverage, drift, exceptions, unknowns, and route deviations; and
- links to existing governed workflows or stable Focus subjects.

### Neither owns

- Issue, PR, CI, review, merge, closure, claim, lease, or worktree truth;
- capability truth, policy, workflow advancement, tasks, queues, or durable dispositions;
- provider sessions, transcripts, credentials, or a global session inventory;
- inferred correlations, copied lifecycle state, or an authoritative graph; or
- direct GitHub/repository mutation.

## Shared evidence-state contract

Every material claim carries independent evidence axes. A single overloaded `status` is invalid.

| Axis | Allowed values | Rule |
| --- | --- | --- |
| `availability` | `available`, `unavailable`, `refused`, `unsupported` | Unavailable/refused/unsupported withdraw dependent claims; none means empty. |
| `freshness` | `fresh`, `stale`, `unknown` | Freshness is evaluated against the owning source policy and named watermark. |
| `coverage` | `complete`, `partial`, `unread`, `missing`, `not_applicable` | `unread` means accessible material was not assessed; `missing` means required material is absent. |
| `cardinality` | `nonempty`, `measured_empty`, `not_measured`, `not_countable` | `measured_empty` requires a successful bounded read, scope, and watermark. |
| `linkage` | `linked`, `unlinked`, `not_assessed`, `not_applicable` | Only `linked` evidence may support a subject-specific claim. |

The UI must use the honest terms **fresh**, **stale**, **unavailable**, **unread**, **unsupported**,
**unlinked**, **missing**, and **measured empty** where applicable. It must not collapse them into
blank, zero, healthy, unknown, or a confidence score. Each source retains its own snapshot identity
and `captured_at`; the composition is not presented as one atomic snapshot.

## Minimal Focus data contract

`FocusView.v1` is a per-read projection. It is not persisted by devUI.

```yaml
contract_version: focus-view.v1
authority: projection_only
composed_at: RFC3339
subject:
  kind: issue | capability
  stable_id: string
  authority_ref: SourceRef.v1
  title: string
owner_intent:
  summary: string
  source_ref: SourceRef.v1
governing_sources: [SourceClaim.v1]
evidence: [SourceClaim.v1]
receipts: [CorrelatedReceiptRef.v1]
risks: [RiskView.v1]
next_legal_step:
  workflow_ref: string
  actor_class: agent | owner | system
  legality: legal | blocked | unavailable | unknown
  reason: string
execution_observations: [ExecutionObservation.v1]
conversation_port: ConversationPortAvailability.v1
limitations: [Limitation.v1]
```

`SourceRef.v1` contains `source_type`, stable `source_id`, exact version/snapshot when the source
supports one, `content_hash` when content is material, and a resolvable locator. `SourceClaim.v1`
adds the five evidence axes, `captured_at`, limitation text, and the claim it supports.

`ExecutionObservation.v1` additionally requires `observation_ref`, `observed_at`, provider/carrier
provenance when applicable, and `correlation`:

```yaml
correlation:
  status: linked | unlinked | not_assessed
  method: governed_reference | explicit_receipt | none
  authority_ref: SourceRef.v1 | null
```

Only `linked` observations appear as subject evidence. `unlinked` and `not_assessed` may appear in
Inspect as limitations or diagnostic candidates, never as progress, ownership, or delivery state.
Filename, branch-text, transcript-text, temporal proximity, provider identity, and repository
similarity are not correlation methods.

### Focus read states

The browser holds only ephemeral selection and disclosure state. Owner-visible operational states
are derived each read:

- `focus_ready` — subject and governing source are readable;
- `focus_partial` — the subject is stable but one or more non-fatal claims are withdrawn;
- `focus_blocked` — the governing source or required correlation cannot support the view; and
- `focus_unsupported` — the supplied identity is not an Issue or governed capability reference.

These are presentation outcomes, not durable lifecycle states.

## Conversation Port contract

### Context pack

`ConversationContextPack.v1` is immutable once hashed:

```yaml
contract_version: conversation-context-pack.v1
pack_id: string
subject_ref: SubjectRef.v1
purpose: string
owner_intent_ref: SourceRef.v1
source_refs: [SourceRef.v1]
evidence_snapshot_refs: [SourceRef.v1]
scope:
  includes: [string]
  excludes: [string]
allowed_dialogue_outcomes:
  - disposition
  - decision_brief
  - plan
  - inquiry
  - workflow_route
  - no_action
allowed_effects: []
limitations: [Limitation.v1]
created_at: RFC3339
expires_at: RFC3339
hash_algorithm: sha256
content_hash: canonical_sha256
```

Canonical serialization, hash calculation, maximum age, and per-source freshness gates must be
specified and tested before implementation. The pack is context and provenance, never approval or
work authority. It excludes credentials, hidden system prompts, provider session material, broad
repository history, and sources not needed for the stated purpose.

### External-first interaction

1. The owner opens Conversation Port from a valid Focus subject.
2. devUI previews purpose, included/excluded scope, source states, expiry, and pack hash.
3. The owner chooses an available external adapter. `unavailable` or `unsupported` is terminal for
   that adapter and leaves Focus usable.
4. devUI exports/opens the immutable pack. It does not require or discover an existing provider
   session and does not ingest a global session list.
5. The provider may reason and return `ConversationDisposition.v1`: one allowed dialogue outcome,
   rationale, source references, limitations, and optionally a proposed command payload.
6. Without a typed command proposal, the conversation ends with no durable effect.
7. With a typed proposal, devUI validates it against the exact pack and renders a new preview. The
   provider transcript is only provenance for why it was proposed.

`ConversationDisposition.v1` itself is non-authoritative and need not be durably stored by devUI.
If a governed downstream workflow requires durable provenance, that workflow records the accepted
source reference or hash in its own existing artifact.

### Typed command preview

`TypedCommandProposal.v1` is the required boundary before any durable consequence:

```yaml
contract_version: typed-command-proposal.v1
proposal_id: string
command_type: start_model_inquiry
context_pack_ref:
  pack_id: string
  content_hash: sha256
exact_inputs: [CommandInput.v1]
source_refs: [SourceRef.v1]
destination:
  workflow_ref: .codex/skills/start-model-inquiry/SKILL.md
  contract_version: string
side_effects: [string]
explicit_non_effects: [string]
approval_rule:
  actor: owner
  mode: start_hold
  binds: [proposal_hash, context_pack_hash, input_hashes, source_versions, expires_at]
freshness:
  created_at: RFC3339
  expires_at: RFC3339
  invalidation_conditions: [string]
expected_receipt:
  schema_ref: model-inquiry terminal launcher response
  required_fields: [inquiry_id, final_state, terminal_receipt_id, human_readable_report]
refusal_conditions: [string]
proposal_hash: canonical_sha256
```

`Apply/Hold` is reserved for a future proposal whose owning workflow applies a governed change. No
such command is admitted by this slice. A button, provider response, pack, or proposal never
substitutes for the destination workflow's own admission checks.

## First command flow — Start Model Inquiry

### Preview

The preview shows:

- the exact question text or question-artifact reference and its SHA-256 hash;
- the bound Focus subject and context-pack hash;
- each governing source version, freshness, and limitation;
- destination `.codex/skills/start-model-inquiry/SKILL.md`;
- side effects: invoke the configured host launcher once and create its durable inquiry artifacts;
- transient operational effects: the workflow may stage the fixed question and acquire its
  exclusive lock under its existing contract;
- explicit non-effects: no GitHub Issue, Issue state, branch, worktree, repository file, PR,
  delivery run, CKM authority, or provider-session authority is created or changed;
- owner approval: **Start** binds the exact preview; **Hold** invokes nothing; and
- expected terminal receipt fields and ambiguous-outcome behavior.

### Confirmation and receipt

1. Re-read the proposal, pack, source versions, and expiry immediately before confirmation.
2. If anything changed or expired, withdraw **Start** and require a regenerated preview.
3. **Hold** closes the preview locally with no durable workflow effect.
4. **Start** invokes only the existing skill/launcher path exactly once; devUI does not reimplement
   its route selection, lock, staging, credential, subscription, or cleanup logic.
5. A valid terminal response renders the four existing receipt fields and links to the human report.
6. Any invalid, empty, nonzero, or malformed launcher result is rendered `ambiguous`; devUI neither
   releases protected recovery state nor retries the inquiry.
7. Inquiry promotion, Issue creation, docs change, or delivery remains a later separate governed
   route from the resulting artifact.

## Minimal Builder System Control data contract

`BuilderSystemControlView.v1` is a per-read/rebuildable orientation projection:

```yaml
contract_version: builder-system-control-view.v1
authority: projection_only
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

Minimum child fields:

- `GoverningDocumentView.v1`: source ref, role, authority class, owner, lifecycle, and evidence axes;
- `WorkflowAdapterView.v1`: skill ref, version/digest, trigger, inputs, outputs/receipts, owning policy
  refs, and authority limitations;
- `CapabilityBindingView.v1`: MCP/connector/script/CLI kind, stable ref, available operations,
  mutation class, owning workflow, admission boundary, and evidence axes;
- `CoverageView.v1`: policy/source area, governing ref, coverage state, freshness, exception refs,
  unknowns, and measured scope; and
- `RouteDeviationView.v1`: intended-route refs, explicitly correlated observed-route refs,
  difference, impact, and next safe governed workflow.

The projection may say that a workflow adapter or capability is unavailable, stale, unread,
unsupported, unlinked, missing, or measured empty. It may not repair or reinterpret the underlying
policy. A deviation is evidence for an existing repair route, not a new workflow state.

## Source, correlation, freshness, and limitation requirements

1. Every claim names its owning source and authority class; projection sources never silently
   replace owner documents, GitHub, Git, CI, dispatcher, or receipt authority.
2. Correlation is positive and source-owned. Absence of a link is `unlinked` or `not_assessed`, not
   a guessed join or proof that no work exists.
3. Provider transcripts and session identifiers may be retained only by their provider or an
   already governed provenance artifact. devUI must not build a transcript/session store.
4. Pack and command hashes bind canonical bytes. Displayed text and submitted bytes must be the same
   artifact; no browser reconstruction is accepted at confirmation.
5. Freshness is source-specific. Every preview carries an absolute expiry and invalidates on any
   changed required version, hash, correlation, admission rule, or destination contract.
6. `measured_empty` is legal only after a successful scoped read with timestamp/watermark. An
   unavailable, unread, unsupported, refused, missing, or unlinked source is never empty.
7. Cross-source skew and partial coverage remain visible. No `composed_at` timestamp implies a
   transactionally consistent global snapshot.
8. Limitations are first-class fields and remain visible through export, preview, confirmation, and
   receipt. A model may not summarize them away.
9. Unsupported provider handoff, source access, remote policy, or receipt readback fails closed and
   leaves the read-only subject view available when possible.
10. No provider, connector, MCP, script, or CLI becomes the policy owner merely because it can
    perform an operation.

## Open implementation dependencies

| Dependency | Why it is needed | Current posture / next safe path |
| --- | --- | --- |
| Subject composer over CKM/Cockpit sources | Builds `FocusView.v1` without copying authority | Extend the delivered read-only composition seam through FCP-01. |
| Canonical pack/proposal hashing and expiry policy | Makes preview and confirmation exact | Specify and test in FCP-01/FCP-03 before command activation. |
| Governed Yggdrasil visual handoff | Resolves layout, accessibility, external-port affordance, and command salience | FCP-02; use existing tokens/components. External design access remains a technical block, not an owner decision. |
| External Codex/Claude adapter boundary | Opens/exports a pack without session discovery or credentials in devUI | FCP-03; start with explicit availability/unsupported states. |
| Model Inquiry invocation adapter | Calls the existing skill exactly once and maps its receipt/failure states | FCP-04; do not duplicate launcher logic. |
| Local audience/auth policy | Current CKM/devUI read seam is single-operator local | Keep first slice local; route any audience expansion through the existing access-policy path. |
| Builder System source registry/coverage composition | Required for a truthful control lens | Separate BSC specification issue after this boundary lands. Reuse DOCS_INDEX, skill contracts, process map, BuilderOps records, and live evidence. |
| General devUI delivery command chain | Required for later GitHub/repository delivery commands | Remains governed and blocked through #3603, #4168–#4170, #3793, and related acceptance; not a dependency of Start Model Inquiry. |

## Authority questions

No owner decision is required to specify or implement the bounded first slice. The following are
future authority questions and must not be answered implicitly by implementation:

1. Which authenticated local owner identity may press **Start** when devUI moves beyond the current
   single-operator local audience?
2. Which durable provenance artifact, if any, should record an accepted external conversation
   disposition before a downstream workflow consumes it? The default for this slice is none.
3. Which owner document will define the canonical Builder System coverage taxonomy and deviation
   severity? Until accepted, the BSC lens may show source-specific facts but no synthesized policy
   verdict.
4. Which future command types, if any, may use **Apply/Hold**? Each needs separate workflow and
   authority approval; none is assumed here.

These questions do not block FCP-01 through FCP-04 under the stated local, Start-Model-Inquiry-only
scope. They block only the corresponding expansion.

## Sequenced follow-up breakdown

| Order | Task | Outcome | Dependency posture |
| --- | --- | --- | --- |
| 1 | [FCP-01 — Compose Subject-Centred Focus (#4694)](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4694) | Target contracts and read-only subject composition with explicit correlation | First implementation slice after this spec merges |
| 2 | [FCP-02 — Validate Focus and Conversation Design (#4695)](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4695) | Governed Yggdrasil handoff and accessibility/degraded-state receipt | Depends on FCP-01 fixtures; technically blocked while external handoff is unavailable |
| 3 | [FCP-03 — Open External Conversation Port (#4696)](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4696) | Hash-bound export/open flow and non-authoritative disposition | Depends on FCP-01 and accepted FCP-02 handoff |
| 4 | [FCP-04 — Start Model Inquiry from Exact Preview (#4697)](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4697) | Start/Hold, exactly-once existing workflow invocation, honest receipt/ambiguity | Depends on FCP-03 |
| Separate | [Builder System Control lens specification (#4698)](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4698) | Detailed source registry, coverage/deviation semantics, visual boundary, and later task split | Begins only after this boundary is accepted; not a Focus child |

All implementation children remain blocked until this specification is merged. The parent remains a
validation hub and never becomes ready work. Builder System Control is filed separately so its
meta-governance context cannot leak into the Focus capability flow.

## Cross-Task Invariants / Interaction Safety

- **FCP-INV-1 — stable primary identity.** Focus has one Issue/capability subject; Builder System
  Control has one governance scope. Neither accepts a provider session as identity.
- **FCP-INV-2 — authority remains external.** Every projection, conversation, disposition, preview,
  and tool capability is non-authoritative unless an existing destination workflow explicitly
  admits it and returns its own receipt.
- **FCP-INV-3 — correlation is never inferred.** Only exact governed references or explicit receipts
  establish a subject link.
- **FCP-INV-4 — fresh empty is measured.** Unavailable, unread, unsupported, unlinked, and missing
  are never rendered as zero or empty.
- **FCP-INV-5 — pack and command are immutable.** Changed bytes, sources, contract, correlation, or
  expiry require a new pack/proposal and confirmation.
- **FCP-INV-6 — external-first means provider-optional.** Focus remains useful without provider
  access, and devUI does not own provider sessions or transcripts.
- **FCP-INV-7 — first command is narrow.** Only Start Model Inquiry is admitted; no direct GitHub,
  repository, delivery, or CKM mutation exists.
- **FCP-INV-8 — no new engine.** Neither lens persists tasks, policy, workflow state, delivery state,
  source truth, or a global session graph.
- **FCP-INV-9 — current and target remain explicit.** Documentation and UI never present a target
  pack, command, lens, handoff, or adapter as delivered without code/test/receipt evidence.

Partial failures preserve these invariants: a composed Focus remains readable if the external port
fails; a generated context pack causes no effect if conversation launch fails; a provider
disposition causes no effect if proposal validation fails; a held, stale, or ambiguous command is
not silently completed by another task; and a valid inquiry receipt remains an inquiry artifact
until a separate governed promotion route acts on it.

## Capability acceptance

- [ ] The Focus fixtures cover Issue and capability subjects, all shared evidence states, explicit and
  absent correlations, partial sources, and cross-source skew.
- [ ] The Conversation Port exports the exact canonical pack bytes and hash without provider-session
  discovery, transcript persistence, or hidden effect.
- [ ] Every provider result is visibly provenance/non-authoritative and can end in no action.
- [ ] The command preview invalidates on source/hash/contract/expiry change and binds **Start/Hold** to
  the exact artifact.
- [ ] Start executes the unchanged Model Inquiry path once; Hold executes nothing; valid and ambiguous
  outcomes preserve the existing receipt/recovery contract.
- [ ] The visual handoff proves desktop, narrow, 200% zoom, keyboard, screen-reader naming, degraded,
  unsupported, stale, unread, unlinked, missing, and measured-empty states.
- [ ] Builder System Control remains a separate route/context and has no implementation hidden in the
  Focus slice.

## Relationship to GitHub issues

Parent [#4693](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4693) is the live validation hub.
Each task maps to one blocked
child Issue and carries the Issue number in `github_issue:` frontmatter. GitHub owns backlog state;
this specification owns the stable capability/task contract. No child becomes `agent:ready` until
this specification is merged and its live dependencies are reconciled.
Builder System Control is tracked separately by
[#4698](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4698).

## Governing and supporting sources

- `docs/DEVUI.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md`
- `.codex/skills/start-model-inquiry/SKILL.md`
- `app/builderops/devui_composition.py`
- `companion-ui/prompts/claude-design/README.md`
- `companion-ui/companion-app/colors_and_type.css`
- PR #4683 — delivered composition seam
- PR #4689 — advisory Builder System devUI execution audit
- PR #4692 — merged Builder System process clarification
