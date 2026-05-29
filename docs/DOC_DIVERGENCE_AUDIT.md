State: Documentation reality audit, point-in-time, non-canonical.
Doc role: Audit report
Authority: Advisory only. `docs/DOCS_INDEX.md` remains the canonical documentation role map.
Owner: Documentation governance / architecture review
Temporal class: snapshot
Review cadence: ad hoc
Source of truth: mixed
Last reviewed: 2026-05-28

# Documentation Divergence Audit

## Purpose and framing

This is a point-in-time audit of documentation reality. It is advisory only and does not change any
authority boundary. `docs/DOCS_INDEX.md` remains the canonical documentation role map; this report
is subordinate to it and must not be read as a competing source of truth.

The audit exists to make one thing explicit:

- The repo does **not** lack documentation governance. `docs/DOCS_INDEX.md` already acts as the
  canonical documentation role map, with role, review status, temporal class, and owner mapping for
  the active doc set.
- The consolidation risk is **not** "too many docs" in itself. A large, well-mapped doc set is not a
  defect.
- The real risk is **role drift** between six kinds of documentation surface that overlap in
  subject but differ in authority:
  1. current-runtime truth (what is shipped now),
  2. target-state design (capability specs, target architecture),
  3. implementation writebacks (owner-doc updates after delivery),
  4. roadmap / spec docs (forward-looking intent),
  5. operations docs (runbooks, release channels, environments),
  6. historical / snapshot docs (point-in-time records).
- The correct response is **authority-preserving normalization** — repair contradictions and make
  authority boundaries legible — **not** a broad rewrite that would itself create drift.

## How to read the findings

Each finding names a risk, why it matters, the owner doc(s) that hold authority for the area, and a
recommended follow-up. Findings are advisory. Where evidence is ambiguous the finding says so and
names the follow-up rather than guessing.

## Findings

### 1. `DOCS_INDEX.md` must remain canonical

- **Risk:** A second "map of docs" (including this audit) could be mistaken for the authoritative
  role map, splitting documentation authority.
- **Why it matters:** Authority splitting is exactly the role-drift failure this audit warns about.
  If two maps disagree, agents cannot resolve which doc owns a surface.
- **Owner doc(s):** `docs/DOCS_INDEX.md`.
- **Recommended follow-up:** Keep `DOCS_INDEX.md` as the single canonical role map. Any audit,
  reading path, or routing aid must declare itself subordinate to it (as this report does).

### 2. Agent Memory README contains contradictory shipped-vs-planned language

- **Risk:** `docs/AGENT_MEMORY/README.md` opens with `State: Implemented. All five AGENT-MEMORY
  slices delivered` but its body still carries planning-era wording ("upstream of any runtime
  implementation", "it does not claim that the runtime already has these memory surfaces", "Runtime
  acceptance remains future work"). A reader cannot tell whether the capability shipped.
- **Why it matters:** This is an internal contradiction in an owner-adjacent capability index. It
  either understates delivered work or overstates it, depending on which half the reader trusts.
- **Owner doc(s):** `docs/AGENT_MEMORY/README.md`; semantic authority remains in
  `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; current runtime posture remains in
  `docs/STATUS.md`.
- **Recommended follow-up:** Repair the README so the delivered slices read as shipped and any
  remaining companion-aware handling reads as an explicit follow-up, not as evidence the slices are
  unshipped. (Performed in this PR — see change B.) `DOCS_INDEX.md` row for
  `docs/AGENT_MEMORY/README.md` still labels it "Draft specification" and should be reconciled with
  the delivery record in a temporal-doc pass.

### 3. Companion UI Product Spec is correctly framed but high-risk

- **Risk:** `docs/COMPANION_UI_PRODUCT_SPEC.md` is correctly framed as target-state UX and is not a
  fourth authority surface alongside Panel/Chat/Automation. It remains high-risk because Companion UI
  is moving fast, so target-state wording can quietly be read as shipped reality.
- **Why it matters:** Fast-moving UX docs are the most likely to be mistaken for current truth as
  slices land.
- **Owner doc(s):** `docs/COMPANION_UI_PRODUCT_SPEC.md` for target-state;
  `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` and `docs/PANEL_AGENT.md` for interaction
  authority; `docs/STATUS.md` and `docs/HUMAN-FLOWS.md` for shipped reality.
- **Recommended follow-up:** Keep the target-state vs shipped boundary explicit in the spec; verify
  shipped claims against `STATUS.md` and tests on each Companion UI delivery.

### 4. Contextualization Layer docs must be reconciled before implementation

- **Risk:** `docs/CONTEXTUALIZATION_LAYER/**` is well-scoped docs-only vocabulary but must be
  reconciled with current `docs/FRONTMATTER.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`,
  `docs/COMPONENTS.md`, and the Agent Memory contracts before any implementation derives schema or
  runtime behavior from it.
- **Why it matters:** The layer introduces artifact-class and metadata vocabulary that, if
  implemented without reconciliation, could fork frontmatter or companion-note semantics.
- **Owner doc(s):** `docs/CONTEXTUALIZATION_LAYER/README.md` (index); `docs/FRONTMATTER.md`,
  `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/COMPONENTS.md`,
  `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` for the contracts to reconcile against.
- **Recommended follow-up:** Before opening implementation issues from this layer, cross-check each
  metadata/companion concept against the named current contracts and record any divergence.

### 5. Component maturity and runtime status must stay synchronized

- **Risk:** Component maturity in `docs/COMPONENTS.md` and shipped/runtime status in
  `docs/STATUS.md` can drift apart as slices land.
- **Why it matters:** If a component reads as mature in one doc and unshipped in the other, agents
  pick the convenient answer.
- **Owner doc(s):** `docs/COMPONENTS.md` (maturity/wiring), `docs/STATUS.md` (runtime status).
- **Recommended follow-up:** Treat maturity and status as a synchronized pair in temporal-doc
  reviews; update both in the same change when a component's reality moves.

### 6. Product action vocabulary must not silently become event vocabulary

- **Risk:** Product/design docs use action verbs (Find, Reorient, Resurface, Act, promote, revise).
  These must not silently become emitted runtime event names.
- **Why it matters:** Emitted event names are a contract. A product verb that leaks into runtime as
  an event name creates an unversioned, unsanctioned contract.
- **Owner doc(s):** `docs/EVENTS.md` (emitted event contract);
  `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (versioning).
- **Recommended follow-up:** Emitted event names belong in `docs/EVENTS.md`. A product doc using
  action vocabulary does not create an event contract unless `EVENTS.md` is updated.

### 7. DB / stores must remain machine mirrors, not semantic authority

- **Risk:** Databases, indexes, and stores can be treated as the source of truth instead of as
  derived projections / machine mirrors of vault artifacts.
- **Why it matters:** A machine mirror gaining semantic authority violates the vault-first,
  human-first invariant and creates a hidden source of truth.
- **Owner doc(s):** `docs/ARCHITECTURE.md`, `docs/COMPONENTS.md`,
  `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`,
  `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.
- **Recommended follow-up:** Keep DB/stores documented as mirrors/projections; never promote a
  projection to authority without a contract change in the owner docs.

### 8. `DOCS_INDEX.md` may need a short authority-boundary block

- **Risk:** `DOCS_INDEX.md` is large and table-heavy; the high-signal authority boundaries are
  spread across many rows and easy to miss.
- **Why it matters:** Agents need the few load-bearing authority rules quickly, without reading the
  full index.
- **Owner doc(s):** `docs/DOCS_INDEX.md`.
- **Recommended follow-up:** Add a concise authority-boundary block near the top of `DOCS_INDEX.md`
  that maps each authority kind to its owner doc and states the conflict-resolution rules.
  (Performed in this PR — see change C.)

### 9. Ops / release-channel docs need explicit applicability and verification metadata

- **Risk:** `docs/OPERATIONS.md`, `docs/ENVIRONMENTS.md`, and `docs/RELEASE_CHANNELS/**` describe
  operator actions whose applicability (which channel, which environment) and verification anchors
  are not always explicit.
- **Why it matters:** Operator docs without clear applicability are dangerous when prod/stable is in
  scope.
- **Owner doc(s):** `docs/OPERATIONS.md`, `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/README.md`.
- **Recommended follow-up:** Ensure each ops/release-channel doc states which channel/environment it
  applies to and its verification anchor; route through `temporal-doc-governance` where stale.

### 10. Design handoff docs are anchors; owner docs describe shipped reality

- **Risk:** Design handoff / snapshot docs can be read as current truth when they are source anchors
  or point-in-time records.
- **Why it matters:** A handoff snapshot mistaken for shipped reality reintroduces target-state
  claims into current-state reasoning.
- **Owner doc(s):** the relevant owner doc for the shipped area (e.g. `docs/STATUS.md`,
  `docs/ARCHITECTURE.md`, capability owner docs); handoff/snapshot docs as anchors only.
- **Recommended follow-up:** When a design handoff conflicts with an owner-doc writeback, the owner
  doc plus implementation evidence wins for shipped reality.

### 11. Cognitive concept docs are not shipped UX/runtime without evidence

- **Risk:** Concept docs under `docs/CONCEPTS/**` and cognitive-support specs describe intended
  behavior that can be misread as fully shipped UX/runtime.
- **Why it matters:** Concept-as-shipped is the most common target-state-vs-reality confusion.
- **Owner doc(s):** `docs/CONCEPTS/**` for semantics; `docs/STATUS.md`, tests, and owner docs for
  shipped confirmation.
- **Recommended follow-up:** Do not treat a concept or target-state doc as shipped without code/test
  evidence and owner-doc status.

### 12. External agentic-AI reports are background rationale only

- **Risk:** External AI reviews and agentic-AI reports can be cited as authority over repo docs.
- **Why it matters:** External reports are input, not authority; repo source of truth must win on
  conflict.
- **Owner doc(s):** repo SoT under `docs/` (per `DOCS_INDEX.md` role map).
- **Recommended follow-up:** Treat external agentic-AI reports as background rationale; the repo
  source of truth wins on any conflict.

## Non-goals

- This audit does not create a new canonical map.
- It does not rewrite architecture, change contracts, or alter shipped reality.
- It does not delete any document.
- It does not, by itself, reclassify docs in `DOCS_INDEX.md`; it only recommends follow-ups.
