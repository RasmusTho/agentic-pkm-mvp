State: Advisory architecture audit snapshot, 2026-08-10. Repository baseline: `origin/main` at
`07d060f1e24f93ed9e0e0834256e053fa5781d30`. Subordinate to current owner docs, accepted ADRs,
and live GitHub contracts. This audit does not claim implementation or create a new authority.
Doc role: Reference (architecture audit)
Authority: Evidence-led document-class and governance synthesis for Builder System and devUI.
Owner docs win on disagreement; only bounded owner-doc changes that cite this audit promote selected
principles into target-state governance.
Owner: Builder System governance
Temporal class: advisory snapshot
Review cadence: event-driven after a material owner-intent, Builder System, or devUI authority change
Source of truth: `docs/DOCS_INDEX.md` for routing; cited owner docs, ADRs, contracts, GitHub objects,
and receipts for the claims they own
Last reviewed: 2026-08-10

# Builder System intent–evidence governance

## 1. Executive finding

Yggdrasil does not need a systems-engineering bureaucracy or another master development method. It
already has most required document classes, authority boundaries, executable work contracts,
verification evidence, and learning records. The useful addition is a small **Intent–Evidence
Loop** that makes crossings between those existing authorities visible:

```text
owner intent / need / outcome
  → bounded discovery and assumption tests
  → explicit disposition
  → normative owner doc / ADR / specification
  → Issue / agent work / PR / exact-SHA evidence
  → verification
  → optional owner validation
  → divergence, learning, or supersession back to the affected intent or decision
```

These are short, nested loops, not sequential phases. Late changes remain allowed. A late change is
governable when it names the intent or decision that changed, preserves the superseded state and
consequence, and reruns only the evidence invalidated by the change.

Two material gaps remain:

1. the top of the graph lacks a consistently visible join from owner intent or need through
   capability/specification to the executable Issue; and
2. the bottom lacks a general owner-usage validation receipt, so verified delivery,
   **Ready to try**, tried by owner, and owner accepted must remain distinct.

The remedy is read-time traceability over current authorities plus bounded contract work where an
edge is truly absent. It is not a requirements database, persistent delivery graph, phase-gate
process, change-control board, or mandatory canvas for every change.

## 2. Current document-class map

| Class | Representative surfaces | Role and authority | Temporal posture | Link to the next level |
| --- | --- | --- | --- | --- |
| Human intent and stable purpose | `docs/COGNITIVE_PROSTHESIS_CHARTER.md`, `docs/PROJECT_KERNEL.md` | Highest-level human purpose, flows, trust and stability constraints | strategic, durable | constrains doctrine, architecture and outcomes |
| Design doctrine | `docs/DESIGN_PRINCIPLES.md`, `docs/foundation/00-yggdrasil-doctrine.md` | Stable design commitments and boundary rules | strategic, durable | constrains ADRs, SBS, contracts and implementation |
| Current runtime truth | `docs/ARCHITECTURE.md`, `docs/STATUS.md` | Shipped architecture and current verified operating snapshot | current state; `STATUS` is high-churn | changes only with delivered, verified reality |
| Strategic target and sequencing | `docs/ROADMAP.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/architecture/SBS_*.md` | Target direction, subsystem boundaries and transition posture | target state / planning | decomposes into capability specs and work |
| Capability and boundary specifications | specification directories, SBS boundary charters, `docs/DEVUI*.md` | Normative target behavior, ownership, invariants and acceptance intent | proposed, accepted, delivered ledger, or superseded | source anchors for Issues and design handoffs |
| Accepted decisions | `docs/adr/ADR-*.md`, design-decision ledgers | Why one consequential architecture or owner option was selected | accepted or superseded | constrains specs, contracts and later changes |
| Interface and behavior contracts | `docs/contracts/**`, schemas and owning tests | Narrow semantic and interface authority | current or target, explicitly labelled | implementation and verification bind to exact contract |
| Traceability and routing indexes | `docs/DOCS_INDEX.md`, `docs/REQUIREMENTS_INDEX.md`, `docs/architecture/traceability-matrix.md` | Routing and coverage views, not replacement authorities | current index or dated analysis | points to owners and explicit gaps |
| Builder-agent operating policy | `AGENTS.md`, `.codex/skills/**`, `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` | Agent entry, workflow adapters and process composition | operational governance | routes normative intent into governed work |
| Executable delivery contract | live GitHub Issue body, labels and comments | Scope, constraints, acceptance criteria and resolvable `Verify:` targets | active operational state | binds claim, branch, PR and closure |
| Delivery proposal and review | branch, PR body/diff, review threads | Proposed repo mutation and review state | operational record | binds Issue to exact SHA and CI/review evidence |
| Verification and closure evidence | CI, review readback, merge, closure and promotion/health receipts | What was proved, integrated or promoted | immutable or append-only evidence | feeds owner readiness, CKM and retrospectives |
| Builder operational learning | BuilderOps `LearningSignal`, `PromotionIntent`, `BuilderOpsReceipt`, worklog and roadmap records | Builder-plane divergence, promotion provenance and outcomes | operational / append-only | crosses authority only through explicit gates |
| Projections | devUI, Builder System Control, CKM, Cockpit, Signboard, generated BuilderOps views | Read-time or rebuildable orientation over source-owned facts | current-at-read, freshness-bound | links authorities but owns no lifecycle truth |
| Advisory and historical evidence | `docs/audits/**`, research, `docs/learning-log.md`, old plans and receipts | Analysis, prior observations and compatibility history | snapshot or historical | needs disposition and promotion before normative use |

The classes are intentionally distributed. “One source of truth” means one authority for each
semantic or lifecycle category, not one database or document for the whole delivery graph.

## 3. Existing strength, actual gap, and excess to avoid

| Mechanism | Already present | Actual gap | Enterprise complexity to reject |
| --- | --- | --- | --- |
| Stakeholder intent | Charter/kernel, owner docs, devUI owner loop, owner-decision method | intent/need/outcome → capability/spec/Issue joins are inconsistent | stakeholder registers, committees, universal `OwnerIntent` objects |
| Discovery | architecture research, Model Inquiry, Yggdrasil handoff, disposition and `PromotionIntent` | assumption evidence is not always connected to the decision it changed | compulsory discovery phase or canvas for routine work |
| Requirements/traceability | capability specs, Issue contracts, `Verify:` targets, indexes, PR→Issue CI gate | top-level need joins and owner-acceptance edge remain incomplete | monolithic SRS, requirements database, full matrices for every field |
| Decisions/changes | ADRs, ledgers, Git/PR review, BuilderOps receipts and supersession | compact late-change durability rule was missing | CCB approval for reversible decisions; heavy baselining |
| Verification/validation | exact-SHA CI, review, merge/closure and promotion receipts; **Ready to try** | general tried-by-owner / accepted receipt is absent | treating merge, release, or test pass as validation |
| Configuration control | Git, protected PR path, exact refs, channel receipts | affected-evidence invalidation needs visible linkage | configuration-item bureaucracy for every document/branch |
| Feedback/learning | small slices, CI/review repair, `LearningSignal`, retrospective, CKM | learning appears only when a trigger is captured and promoted | mandatory retrospectives or learning records for normal PRs |
| Deviation handling | honest missing/stale/unlinked states, bounded route deviations | comparison requires source-owned intended and observed correlation | inferred deviations, scalar health scores, central exception queues |

## 4. Mechanism comparison — adapt, do not copy

### Systems engineering

INCOSE's [Systems Engineering Handbook](https://www.incose.org/resources-publications/technical-publications/se-handbook/)
and NASA guidance provide useful mechanisms: stakeholder expectations, requirements traceability,
architecture boundaries, decision analysis, verification, validation, configuration/change
visibility, and lifecycle feedback. NASA treats requirements as changeable and traceable and system
design as iterative and recursive: [requirements management](https://www.nasa.gov/reference/6-2-requirements-management/)
and [system design](https://www.nasa.gov/reference/4-0-system-design-processes/).

Reuse the mechanisms, not a document lifecycle. Translate them into source references, explicit
constraints, resolvable verification, owner validation, and visible change consequences. Reject
sequential gates, exhaustive baselines, change boards, large requirements hierarchies, and documents
whose main purpose is coordinating departments that do not exist here.

### Double Diamond

The Design Council's [Double Diamond](https://www.designcouncil.org.uk/resources/the-double-diamond/)
separates understanding the problem from choosing a definition, then exploring alternatives from
testing and improving a solution. Its divergent/convergent rhythm prevents the first owner statement
or agent proposal from silently becoming scope.

Use Discover/Define and Develop/Deliver as repeatable thinking moves inside a capability or slice,
not project phases. Evidence may send delivery back to discovery. The durable output is the changed
disposition, decision, normative target, and affected proof—not phase-completion documents.

### Lean and Lean UX

Lean starts with customer value and seeks better value with fewer wasted activities
([Lean Enterprise Institute](https://www.lean.org/explore-lean/what-is-lean/)). Lean UX makes problem
statements, assumptions, hypotheses and experiments explicit
([Lean UX Canvas](https://jeffgothelf.com/blog/the-lean-ux-canvas/)). Apply these when uncertainty is
real: state the outcome, find the riskiest assumption, run the smallest informative test, and change
the decision from evidence.

Do not require an experiment for a deterministic repair with clear intent and verification. Keep
unvalidated hypotheses advisory until disposition and promotion.

### Agile and continuous delivery

The [Agile principles](https://agilemanifesto.org/principles.html) welcome late requirement changes,
frequent increments and regular adaptation. DORA's
[small batches](https://dora.dev/capabilities/working-in-small-batches/) make the feedback mechanism
explicit: small changes test assumptions sooner and lower course-correction cost.

Retain bounded Issues, short slices, exact-SHA evidence, automated checks and rapid correction.
Reject sprint ceremony, coordination roles and velocity proxies that add no decision or evidence
value for one owner and replaceable agents.

## 5. The Intent–Evidence Loop

### Minimum crossing receipt

Do not create one mandatory new schema. At an authority crossing, existing artifacts should make
these answerable through native fields or references:

- `source_ref`: owner intent, need, evidence, decision or prior contract that motivated the move;
- `disposition`: accepted, rejected, deferred, superseded, or requires owner decision;
- `decision`: what changed and why when a normative constraint or outcome changes;
- `target_ref`: owner doc, ADR, specification, Issue, PR or receipt that owns the next claim;
- `verification_ref`: what proves the target, or what remains explicitly unverified; and
- `limitations`: uncertainty, missing linkage, freshness or consequence not to infer away.

Routine reversible implementation choices stay in Issue, Git and PR evidence. A separate durable
decision is warranted when a choice changes owner intent, a governing constraint, acceptance
criteria, authority ownership, privacy/retention, or a costly-to-reverse boundary.

### Late-change rule

Late changes are allowed everywhere. They must:

1. identify the intent, assumption, requirement, decision or acceptance criterion that changed;
2. preserve a supersession link and consequence for active work or prior evidence;
3. update the owning authority rather than a projection or chat; and
4. invalidate and rerun only affected verification or validation evidence.

This is change visibility without heavy baselining. An unchanged check remains valid only when its
inputs, governing contract and relevant delivery blob are unchanged.

### Verification and validation remain separate

- **Verification:** did the artifact satisfy its governing contract on the exact evidence identity?
- **Ready to try:** is it available with enough evidence and instructions for owner use?
- **Owner validation:** did it solve the intended need in use?
- **Acceptance:** did the owner explicitly accept it under a defined authority?

No earlier fact implies a later one. Until an owner-validation authority exists, devUI displays the
absence rather than inferring acceptance from merge, deployment, activity or chat.

## 6. Builder System and devUI consequences

Builder System preserves research/design disposition and `PromotionIntent`, Issue-first execution,
exact-SHA proof, and triggered learning. It adds no stage gate. Discovery and delivery may alternate
within a slice or change the normative source before replacement work is admitted.

devUI and Builder System Control should show, only from owning sources: intent/need/outcome and
normative decision; capability/spec and Issue; PR/SHA proof and limitations; supersession and
affected proof; separate delivered, **Ready to try**, tried and accepted evidence; and `unlinked`,
`not_assessed`, `stale`, `unavailable` or `absent` when a join is missing.

The projection must not infer correlation, determine intent, copy lifecycle state, or persist a new
graph. A route deviation needs an owning source for both the intended route and observed correlation.
Owner decisions continue to use Decision Quality: one decision, options, consequences, a
recommendation and consequence of waiting.

## 7. Explicit non-actions

This synthesis does **not** authorize a persistent delivery graph or intent/requirements store; a
universal intent, requirement, experiment, deviation or acceptance entity; sequential Double Diamond
phase gates; a mandatory SRS, matrix, Lean UX canvas or ADR for each change; a change-control board;
a learning/validation record for every PR; or a scalar score hiding missing evidence.

## 8. Three proportionate follow-ups

1. Walk three representative capabilities from owner intent to Issue, PR evidence and any owner-use
   evidence; record joins as present, absent or stale. Do not build from this audit alone.
2. If a repeated gap is confirmed, author one bounded specification and Issue for the smallest
   relationship/supersession view or owner-validation receipt. Reuse existing identifiers and axes.
3. Deliver that slice through the existing Builder System Control/devUI sequence and validate it
   with one owner task. Do not create a new hub, workflow engine or governance layer.

