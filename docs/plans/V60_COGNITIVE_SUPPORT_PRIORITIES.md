State: Proposed sequencing plan for v6.0 cognitive-support work; baseline-aware and not current runtime truth.
Doc role: Plan
Authority: Prioritization and sequencing plan for v6.0 cognitive-support capabilities; does not override the capability specs it anchors to, nor current runtime truth in `docs/ARCHITECTURE.md` or `docs/STATUS.md`.
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-04-18
Last verified against: docs/plans/V60_ARCHITECTURE_TARGET.md, docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/FINDING_AND_REORIENTING/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/CONCEPTS/USER_NEEDS_MODEL.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md, docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md, docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md

# v6.0 Cognitive-Support Priorities

## Purpose

This plan answers a single question: **what must change in the v6.0 line so the system actually delivers cognitive support, not just correct retrieval and safe writes?**

It is a prioritization and sequencing document. It does not replace the capability specs under
`docs/FINDING_AND_REORIENTING/`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`,
`docs/SEPARATING_PERSISTENCE_SURFACES/`, or `docs/COMMITMENT_AS_FIRST_CLASS/`. It reads those specs
against the current v5.5 runtime and states which moves unblock the others, which are
prerequisites for safe interaction-surface widening, and which are independent.

It is explicitly not:
- a target-state architecture document (that is `docs/plans/V60_ARCHITECTURE_TARGET.md`);
- a capability specification (those live under the capability directories above);
- current-state runtime truth (that is `docs/ARCHITECTURE.md` and `docs/STATUS.md`).

## Framing

`docs/CONCEPTS/USER_NEEDS_MODEL.md` names 14 primary human needs that the system is meant to serve.
The current runtime substantially supports a subset (not losing what matters; cross-device access;
artifact longevity through vault-first posture). It substantially under-supports the needs most
connected to *cognitive load and orientation*:

- Recovering orientation after interruption (Need #3)
- Managing commitments without overload (Need #4)
- Learning that compounds over time (Need #5)
- Trusting system action (Need #9)
- Contextual integrity across role identities (Need #13)

The gap is not bugs. It is **missing runtime surfaces that embody already-specified semantics**.
The capability specs describe the shape. This plan sequences the work so the shapes actually land
in a useful order.

## Diagnosis Anchored To Existing Docs

Five structural gaps between current runtime and the v6.0 capability specs:

1. **Salience and staleness are specified but not operationalized.**
   - `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` defines salience as relational and
     derived; `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` separates staleness from
     `maturity` and `review_state`.
   - Current runtime: `zone` is the only salience-adjacent signal, used as if it carries truth;
     no staleness signal exists; no resurfacing surface exists.
   - Consequence: Need #3 (orientation recovery) has no runtime path.

2. **`domain` carries more semantic load than the ontology allows.**
   - `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md` and
     `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md` split operational scope, sphere membership,
     situated role identity, and cross-scope allowance.
   - Current runtime: a single `domain` field plus path-derived fallback, flagged as a current-state
     bug in `docs/plans/V60_ARCHITECTURE_TARGET.md` (Finding 1).
   - Consequence: Need #13 (contextual integrity) cannot be enforced; every subsequent
     context-aware capability inherits the ambiguity.

3. **Trust verbs and receipts are specified but not runtime-enforced.**
   - `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` specifies ASSERT/SUGGEST/APPLY with receipt
     requirements; `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` separates receipts from
     traces; `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` names receipts as a distinct system
     sub-surface.
   - Current runtime: Panel proposals arrive as checklist items without receipt records; no
     verb-level gating at the retrieval or suggestion boundary; no executable audit trail for
     system-initiated changes.
   - Consequence: Need #9 (trusting system action) depends on artifacts that do not yet exist;
     Chat cannot safely gain mutation rights without them.

4. **Retrieval is still the architectural center; capability extraction is stated but not done.**
   - `docs/FINDING_AND_REORIENTING/README.md` separates retrieval, orientation, and resurfacing as
     three distinct cognitive moves and deprecates ASK as the center.
   - Current runtime: ASK is the de facto entrypoint; retrieval has no capability contract with
     explicit inputs/outputs/policy; orientation and resurfacing do not exist as runtime concepts.
   - Consequence: Panel/Chat separation
     (`docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`) cannot compose against retrieval as a
     capability, because retrieval is not yet capability-shaped.

5. **Commitments are first-class in the ontology but absent from the runtime.**
   - `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` and `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
     define commitments as a distinct semantic family with state transitions and receipt
     requirements.
   - Current runtime: no commitment queries, no next-action surfacing, no waiting-state resolution,
     no review-cycle triggers. `maturity` and `review_state` are orthogonal and do not substitute.
   - Consequence: Need #4 (commitment without overload) has no support surface.

## Sequencing Principles

- **Signal before surface.** Build the signals (salience, staleness, scope, receipt) before the
  surfaces that consume them (resurfacing, Chat mutation, commitment runtime). Surfaces built on
  absent signals become heuristics that silently become truth.
- **Disambiguate before enforce.** Split `domain` before any capability starts enforcing context
  boundaries; otherwise the wrong semantics harden.
- **Receipt before widen.** Ship receipt artifacts and SUGGEST/APPLY gating before Chat gains
  mutation rights or automation expands. Retrofitting audit is architecturally costly.
- **Capability before surface.** Extract retrieval as a capability before introducing a second
  interaction surface (Chat) that would otherwise re-entangle with it.
- **Single-user now, multi-user not foreclosed.** Every priority below is framed to hold under
  later multi-user expansion without forcing a rewrite (see
  `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`).

## Priorities

Priorities are ordered by unblock-value. Dependencies are explicit. Each priority names its
governing capability spec so `docs-to-issue` can decompose it into feature issues with stable
`Source Anchors`.

### Priority 1 — Operationalize salience and staleness as first-class signals

**Why first.** Without these, no cognitive-support surface (resurfacing, orientation recovery,
commitment review triggers, staleness-aware retrieval) can be built on anything but heuristics.
Also the highest-leverage gap against Need #3.

**Governing capability spec.** `docs/FINDING_AND_REORIENTING/README.md` (salience as derived;
orientation and resurfacing as distinct cognitive moves).

**Load-bearing source anchors.**
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/README.md`

**Scope shape.**
- Define salience derivation inputs (recency of interaction, open-loop pressure, commitment-state
  linkage, last-surface delta) without committing to a specific score.
- Define staleness signal shape distinct from `maturity`/`review_state` (time-window policies,
  drift indicators, external-dependency change).
- Stand up a minimal resurfacing surface that consumes both signals; the first surface may be
  a companion-note summary, not a UI.

**Out of scope for Priority 1.**
- Full Chat surface.
- Replacement of `zone` semantics (handled by the current-state bug fix track under v5.x).

**Dependencies.** None; unblocks Priorities 4 and 5.

### Priority 2 — Disambiguate context: path-fallback fix (v5.x) + scope/sphere/identity split (v6.0)

**Why second.** Priority 1 signals and every later capability need a context model that doesn't
silently collapse four concepts into one path-derived string. The question is not whether to fix,
but which parts are current-state bugs and which are enabling work. They do not share a release
line.

**Priority 2 splits into two tracks at `docs-to-issue` time.**

#### Priority 2a — Remove `domain` path-fallback (DELIVERED)

**Status: delivered.** Issue #435 closed 2026-04-16 by PR #453 (removed path inference from
`app/retrieval/hybrid.py::_extract_domain()` with regression coverage in
`tests/boundaries/test_domain_separation_defaults.py`). Owner-doc promotion followed in PR #490 on
2026-04-17 (ARCHITECTURE, ROADMAP, STATUS, DOCS_INDEX, HUMAN-FLOWS, OPERATIONS).

This line is retained in the plan for traceability only. No further issue creation is needed for
Priority 2a; the wider scope/sphere/identity split continues as Priority 2b below.

#### Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)

**Classification.** `enabling change` per `AGENTS.md`. Additive only; does not break current
behavior where no declaration exists.

**Governing capability spec.** `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` — README, 4 task files, and `PARENT_FEATURE_ISSUE.md` on disk. Underlying concept contracts: `CONTEXT_MODEL_DECISION_FRAME.md`, `CONTEXT_TERMINOLOGY_CONTRACT.md`, `COGNITIVE_AXES_AND_SPHERES.md`.

**Load-bearing source anchors.**
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md` (existing additive `sphere_membership` enablement)

**Scope shape.**
- Operational scope as an explicit artifact property distinct from sphere membership.
- Situated role identity as a first-class concept (not just a tag) with retrieval-policy
  implications.
- Additive only; builds on the existing sphere-membership enablement prep.

**Out of scope for 2b.**
- Sphere-membership enforcement in retrieval (follow-up after semantics stabilize).

**Dependencies.** 2a is independent and should ship first on v5.x. 2b should precede any
context-aware behavior in Priorities 3–5 on v6.0.

### Priority 3 — Receipts and SUGGEST/APPLY gating before Chat widens

**Why third.** Required before the interaction-surface split widens, before Chat gains mutation
rights, and before automation expands. Without receipts, every subsequent agent or surface adds
opaque system action.

**Governing capability specs.**
- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` (receipt as distinct system sub-surface).
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` (Chat authority model, governed mutation).

**Load-bearing source anchors.**
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`

**Posture: semantically distinct, physically may co-locate transitionally.**
`docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` is explicit that receipts are a distinct first-class
concept from mirror artifacts, and that "We are not requiring an immediate code-level split into
separate storage backends or tables. We are requiring new runtime and documentation work to model
mirror-targeted concerns and receipt-targeted concerns as different concerns." Priority 3 follows
that posture: receipt identity is its own from day one, even if its first physical container is a
bounded, addressable section within the companion note.

**Scope shape.**
- Define receipt artifact fields against `TRUST_SEMANTICS_CONTRACT.md` and
  `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`: verb (ASSERT/SUGGEST/APPLY), authority, basis,
  outcome, linked artifact, instance provenance.
- The receipt block must be addressable and relocatable without semantic change; a later physical
  split must be a layout move, not a re-modeling.
- Wire SUGGEST and APPLY gating at the Panel mutation boundary first, as the well-understood case.
- Establish that any future Chat mutation path passes the same gate.
- Ensure receipts are append-only and instance-scoped to stay safe under later multi-user.

**Out of scope for Priority 3.**
- Chat runtime itself.
- Full automation-authority expansion.
- A dedicated receipt storage backend; transitional co-location inside the companion note is
  acceptable if the four non-collapse rules from `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`
  are preserved.

**Hard non-collapse rules.**
- Receipt presence must not be expressed as companion-note metadata (and vice versa).
- `note_mirror` / `note_log` language must not return; the mirror/receipt decision explicitly
  deprecates it.
- Outbox events and audit rows may support receipt construction but must not be treated as the
  receipt model.

**Dependencies.** Independent of Priorities 1 and 2; a hard prerequisite for Chat mutation and for
any commitment-runtime writes (Priority 5).

### Priority 4 — Extract retrieval as a capability with an explicit contract

**Why fourth.** The Panel/Chat split is cosmetic until retrieval is capability-shaped. ASK as the
architectural center is the single largest obstacle to Chat, Deep Agents, and capability-based
composition more broadly.

**Governing capability spec.** `docs/FINDING_AND_REORIENTING/README.md`.

**Load-bearing source anchors.**
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/RETRIEVAL.md` (current-state retrieval; capability extraction is v6 direction)
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/DESIGN_PRINCIPLES.md` (capability-based composition)

**Scope shape.**
- Define a retrieval capability contract: inputs (query, scope, sphere membership, salience/staleness
  hints from Priority 1, trust boundary), outputs (results with provenance and temporal-validity
  flags), policy (ranking posture, rerank hooks).
- Keep ASK operational but no longer architecturally central; ASK becomes one of multiple consumers.
- Make retrieval consumable by a future Chat surface without further refactor.

**Out of scope for Priority 4.**
- Chat runtime.
- Retrieval replacement; this is extraction, not rewrite.

**Dependencies.** Benefits from Priorities 1 and 2 landing first (salience signals become
retrieval inputs; split scope becomes retrieval scope). Can start in parallel but should not ship
final without them.

### Priority 5 — Minimal commitment-runtime surface (absorbs V5.6 commitment slice)

**Why fifth.** Highest user value for Need #4, but built on top of Priorities 1–3. Commitment
tracking without salience signals, context separation, or receipts would re-create the exact
opacity the capability spec warns against.

**Absorption of the v5.6 commitment slice.** `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` was
authored as a bounded semantic-scaffold step and intentionally deferred storage/event shape. Its
follow-on sequencing maps directly onto Priority 5's dependency graph. Rather than maintaining two
parallel plans that will drift, Priority 5 absorbs the slice:
- The slice's **first-slice scope** (open loop, project, next action, waiting, review return as a
  distinct semantic family) becomes Priority 5's first bounded step.
- The slice's **ten non-collapse guardrails** become Priority 5's invariants, carried forward
  verbatim in the child-issue Constraints.
- `V56_COMMITMENT_RUNTIME_SLICE.md` is reclassified as a **historical precursor** once Priority 5's
  parent feature issue is created. It should not continue to read as a live planning surface.
- If the slice has already shipped in part, the absorption preserves those deliveries as "Priority 5
  foundation already in place"; the invariants still apply to future work.

**Governing capability spec.** `docs/COMMITMENT_AS_FIRST_CLASS/README.md`.

**Load-bearing source anchors.**
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
- `docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md` (§Guardrails And Non-Collapse Rules; §In-Scope First
  Slice) — carried forward as invariants, not as a separate track.

**Scope shape.**
- Commitment identity, state (open, waiting, resolved, cancelled, review-return), linked artifacts,
  review-cycle metadata.
- Commitment semantics remain distinct from `review_state`, `maturity`, and execution plan objects
  (per V5.6 slice guardrails 1–3).
- Minimal runtime queries for next-action surfacing and waiting-state resolution.
- Commitment writes flow through the Priority 3 receipt gate.
- Commitment queries consume Priority 1 salience/staleness signals.
- Unknown or partial commitment structure remains a legal state (V5.6 slice guardrail 10).

**Out of scope for Priority 5.**
- Full project/plan runtime.
- Automated commitment creation by agents.
- A new event family or API contract redesign (V5.6 slice out-of-scope, retained).

**Dependencies.** Priorities 1, 2, and 3 are prerequisites. Priority 4 is helpful but not required.

## What Is Explicitly Deferred

- **A2A SLAs and delivery contracts.** Amplify a cognitively-aware system; do not create one.
- **Deep Agents / DeepAgents harness.** Blocked behind Chat, which is blocked behind Priority 3.
- **Orchestrator V2 expansion.** Flagged baseline stays; no expansion until Priorities 1–4 land.
- **Multi-user expansion.** Not scheduled. Every priority above is multi-user-compatible; none
  introduces multi-user behavior.

## Multi-User Foreclosure Checks

Each priority carries an explicit check against the instance/device/replica contract:

- Priority 1: salience and staleness derivations must accept partial/lagged instance views.
- Priority 2: scope, sphere, and situated identity must be declarable per instance without requiring
  cross-instance agreement for single-user operation.
- Priority 3: receipts are append-only, instance-scoped, and safe to merge additively across
  replicas.
- Priority 4: retrieval contract inputs include instance provenance; outputs can flag staleness.
- Priority 5: commitment state transitions are additive and carry instance provenance.

## Relation To Existing Capability Specifications

This plan is a **sequencing layer** across already-authored capability specifications. It does not
replace them and, for most priorities, does not trigger new `feature-breakdown` work. The
feature-breakdown has already produced spec directories for four of the five priorities:

| Priority | Capability spec directory | Feature-breakdown state |
| --- | --- | --- |
| 1 — Salience and staleness signals | `docs/FINDING_AND_REORIENTING/` | Done: README + task files + `PARENT_FEATURE_ISSUE.md` on disk |
| 2a — Remove `domain` path-fallback | (none; single bounded v5.x fix) | Not applicable — direct `docs-to-issue` |
| 2b — Scope / sphere / situated-identity split | `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` | In progress: feature-breakdown done; parent feature issue #645 open; slice issues #651–654 created; SSI-01 (payload contract) delivered via PR #660 |
| 3 — Receipts and SUGGEST/APPLY gating | `docs/SEPARATING_PERSISTENCE_SURFACES/` (receipt side) and `docs/INTERACTION_SURFACES_AND_AUTHORITY/` (gating side) | Done on both; coordination across the two parent feature issues needed |
| 4 — Retrieval as capability | `docs/FINDING_AND_REORIENTING/` (shared with Priority 1) | Done: `DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md` + `DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md` authored |
| 5 — Minimal commitment-runtime surface | `docs/COMMITMENT_AS_FIRST_CLASS/` | Done, including `RECONCILE_WITH_V56_COMMITMENT_SLICE.md` aligned with the absorption decision in Priority 5 above |

What this means in practice: this plan's job is to **order parent feature issue creation** against
those directories, not to reinvent the task files those directories already contain.

## How This Plan Enters The Workflow

Per `.codex/skills/README.md`, route each priority as follows:

1. **This plan itself** is a docs-authoring artifact, not a backlog. No GitHub Issue governs its
   authoring.
2. **Priorities 1, 3, 4, 5** route through `feature-breakdown`'s parent-issue creation step,
   using the existing `PARENT_FEATURE_ISSUE.md` documents in each capability directory. Child
   issues are then created from the task files in dependency order. This plan contributes
   sequencing and dependency constraints across capabilities; it does not override the task shape
   inside any capability.
3. **Priority 2a** (DELIVERED) requires no further issue creation. It is documented here for traceability only.
4. **Priority 2b** capability directory exists at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` (feature-breakdown done). Parent feature issue #645 is open. Route slice issues through the `issue-to-code` skill; four slice issues (#651–654) are in progress; SSI-01 (payload contract, #651) delivered via PR #660.
5. **Cross-capability dependency enforcement** lives in the Issue `Context` field, not in this
   plan. When creating a Priority 3 parent feature issue, its `Context` must cite the Priority 1
   parent issue as a dependency so ordering is visible in GitHub state, not only here.
6. **Classification rules** from `AGENTS.md` apply to every Issue: current-state correction,
   enabling change, or target-state work. Priority 2a is the only current-state correction in this
   plan; every other priority is enabling change.

## Resolved Decisions

Three sequencing questions were resolved during authoring and are recorded here so later readers
understand the shape of the priorities above:

- **Priority 2 is split.** 2a (path-fallback removal) is a v5.x current-state correction per
  `V60_ARCHITECTURE_TARGET.md` Finding 1; 2b (scope/sphere/identity split) is a v6.0 enabling
  change. Combining them would force the correction to wait on the enabling work.
- **Priority 3 receipts are semantically distinct from day one, physically may co-locate
  transitionally** inside the companion note per the explicit posture in
  `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`. Full physical separation is a later layout move, not
  a re-modeling.
- **Priority 5 absorbs `V56_COMMITMENT_RUNTIME_SLICE.md`** rather than running parallel. The
  slice's ten non-collapse guardrails carry forward as Priority 5 invariants; the slice doc is
  reclassified as historical precursor once the Priority 5 parent feature issue is created.

## Non-Goals

- This plan does not redefine capability semantics. Capability specs own their semantics.
- This plan does not commit to a release sequencing beyond dependency order. ROADMAP owns release
  framing.
- This plan does not authorize any runtime change. Only Issue-governed implementation work does.
