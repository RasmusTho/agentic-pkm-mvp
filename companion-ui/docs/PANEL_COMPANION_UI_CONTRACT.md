---
name: Panel Companion UI Contract
description: Normalized contract for Panel as the artifact-local intent manifestation and confirmation surface in Companion UI — conceptual model, render states, confirmation write-back, and surface boundaries
doc_role: Surface contract
authority: SoT for Companion UI Panel render contract and Panel confirmation write-back contract. Binding on any Companion UI implementation of the Panel surface.
owner: v6.0 architecture / Companion UI product
last_reviewed: 2026-05-17
last_verified_against: |
  docs/PANEL_AGENT.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md,
  docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md,
  docs/COMPANION_UI_PRODUCT_SPEC.md,
  companion-ui/docs/UI_RUNTIME_BOUNDARIES.md,
  companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md,
  companion-ui/docs/CANVAS_SUGGESTION_FLOW.md
governing_issues: "#995, #996"
related_issues: "#1019 (closed — conceptual clarification), #978 (runtime hub), #979, #980, #1022 (epic)"
---

# Panel Companion UI Contract

## Purpose

Define Panel as the artifact-local intent manifestation and confirmation surface in Companion UI.

This document covers:

1. Panel conceptual contract (what Panel is and is not).
2. Panel render contract (states, rendering concepts, invariants).
3. Panel confirmation / write-back contract (confirmation semantics, write-back boundary, default approach).

This is a contract/docs-only document. It does not implement runtime behavior, UI components, vault write paths, or confirmation endpoints. Those belong to separate implementation issues.

---

## Part 1: Panel Conceptual Contract

### What Panel Is

Panel is the **artifact-local intent manifestation and confirmation surface**.

In one sentence: Panel is the artifact-local surface where the agent may manifest what it believes the user likely wants to do with a specific artifact before the user has fully formulated that intention as a command; the user recognizes, corrects, or confirms; and confirmed intent enters governed, receipt-bearing execution through the intent/event/note-writer pipeline.

Panel is:

- **Artifact-local.** Proposals are bounded to the specific artifact currently open. Panel is not a generic inbox, not a global suggestion surface, and not a cross-note operation surface.
- **Proposal-oriented before confirmation.** The agent surfaces likely user intentions as reviewable proposals. The user decides. The agent's output is not execution authority.
- **Confirmation-oriented at the execution boundary.** Once the user confirms an artifact-local proposed intention, that confirmed intent enters the governed execution path: policy, WriteGuard, idempotency, deterministic writer, receipt.
- **A surface where the agent manifests likely user intent for the specific artifact.** The agent may surface what the user likely wants to do next — a lifecycle move, a classification, a follow-up action — before the user has explicitly commanded it.
- **A place for the user to confirm, correct, reject, or ask for clarification.** The user remains the decision-maker.
- **Proposal-class output, not execution authority.** LLM output from Panel cognition (freeform path or instruction interpretation) is always in the proposal or clarification class. It is not promoted to governed-execution authority without explicit human confirmation.

### What Panel Is NOT

Panel is NOT:

- **Canvas Core** — the direct in-place note-body co-authoring surface for active user-present sessions. Canvas co-authors the artifact body; Panel governs what the artifact becomes or does as a system artifact.
- **Canvas body co-authoring** — the body-edit co-authoring posture of Canvas, which is direct, in-place, and undo-based.
- **Canvas bounded suggestion flow** — the staged discrete suggestion pattern (`CANVAS_SUGGESTION_FLOW.md`, issues #868–#874) used for body-edit previews and governance-bearing escape hatches inside Canvas.
- **Automation** — proactive or scheduled system action. Panel requires a present user; Automation acts within pre-authorized scope without a live interactive turn.
- **Background execution** — Panel does not act in the background. It waits for the user.
- **LLM-authoritative mutation** — the LLM may propose, but it does not authorize. Only confirmed human intent enters the governed execution path.
- **A persistent inbox** — Panel is note-bound. It is not a separate Panel inbox or notification surface.
- **A co-authoring or exploration surface** — Panel does not externalize open-ended thought like Chat/Canvas. It externalizes bounded, artifact-local likely intention.

### Surface Boundary Statement

Panel and Canvas are both first-class Companion UI surfaces. They must not be collapsed. The defining difference:

- Canvas co-authors the artifact body.
- Panel governs what the artifact becomes or does as a system artifact.

See also: `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md :: Distinction from Panel`.

---

## Part 2: Panel Render Contract

### Rendering Principle

Panel renders richer affordances from durable vault-visible state and runtime status. Panel does not own vault I/O. Panel does not reclassify actions locally. Panel renders the server-declared classification of proposals.

### Note-Bound / Artifact-Local Anchoring

- Panel is rendered as a note-bound surface: inline or as an overlay anchored to the active note, not as a standalone page or global inbox.
- Panel is contextually associated with the specific artifact currently open.
- One artifact, one Panel surface context. Panel does not aggregate proposals across notes.

### Panel States

The following states are required. Implementations must handle all of them.

#### Required states

| State | Description |
|---|---|
| `idle` | Panel is present but no agent activity is in progress and no proposals are staged. |
| `running` | Agent is processing the artifact context; proposals are being generated. |
| `proposals-staged` | One or more artifact-local proposed intentions have been surfaced and are awaiting user decision. |
| `confirming` | User has accepted a proposal; confirmation is being submitted to the runtime. |
| `executing` | Confirmed intent is being executed through the governed runtime path. |
| `receipt-displayed` | Execution is complete; receipt/outcome is visible to the user. |
| `no-match` | Panel ran but produced no actionable proposals for this artifact context. |
| `blocked` | Execution was blocked (policy gate, WriteGuard, allowlist, or capability constraint). Blocked state must be visible and must carry a reason. |

#### Future-compatible states

These states are named for forward compatibility. Implementations are not required to implement them now, but must not design the state machine in ways that preclude them.

| State | Purpose |
|---|---|
| `clarification-needed` | Agent needs more information from the user before surfacing proposals. |
| `plan-staged` | An ordered multi-step plan has been proposed but not yet confirmed. |
| `capability-needed` | The requested action exceeds the current capability/allowlist. |
| `partial-complete` | Some proposals in a set have been executed; others are still staged or blocked. |

### Rendering Concepts

#### Proposal rows

Each staged artifact-local proposed intention renders as a distinct proposal row. A proposal row must include:

- A human-readable description of the proposed intention.
- The canonical action ID (for runtime matching; may be hidden in the visual layer but must be present for confirmation).
- Provenance/evidence for why this proposal was generated (see below).
- Affordances: confirm, correct/edit, reject, and optionally ask for clarification.

Proposal rows must not be bulk-accepted. Each proposal requires individual user decision.

#### Evidence / provenance visibility

At confirmation time, the user must be able to inspect why this proposal was generated:

- What artifact state or instruction triggered the proposal.
- Which catalog action or capability class it maps to.
- The cognition route used (rule, freeform, plan-based).

Evidence visibility must be available at minimum at confirmation time. It may be collapsible in default view.

#### Status / receipt visibility

- The AI status callout in the vault (`> [!info]- AI status`) remains the canonical in-vault receipt surface.
- Companion UI may render a richer status/receipt view alongside or instead of the raw callout text.
- Receipt visibility must include: action taken, outcome (success, blocked, logged), and timestamp.
- Receipts must not be ephemeral in Companion UI; they must persist until the user dismisses them or navigates away.

#### Confirm / correct / reject affordances

Every proposal row must provide:

- **Confirm:** submit the proposal for governed execution.
- **Correct / edit:** adjust the proposal before submitting (e.g., change parameters, override the suggested action ID).
- **Reject / dismiss:** decline the proposal without any execution.

Confirm is not the only allowed action. Correct and reject are first-class affordances.

#### No-match and blocked as visible states

`no-match` and `blocked` are not silent failures. They must be rendered as visible, actionable states:

- `no-match`: display a clear indicator that the Panel ran but found no actionable proposals. Allow the user to provide a freeform instruction or close the Panel.
- `blocked`: display the reason for blocking (policy gate, capability constraint, etc.). Allow the user to inspect what was blocked and why.

#### UI does not reclassify actions locally

The Companion UI Panel must not reclassify action types, capability classes, or governance categories locally. Classification logic lives in the runtime. The UI renders what the server declares.

#### UI does not own vault I/O

The Companion UI Panel does not write vault files directly. All durable vault-visible mutations route through the runtime's governed execution path: policy, WriteGuard, idempotency, deterministic note-writer, receipt.

### Distinction from Canvas Suggestion Flow

Panel rendering shares some visual vocabulary with Canvas bounded suggestion flow but is a categorically different surface.

| Dimension | Panel | Canvas Bounded Suggestion Flow |
|---|---|---|
| **Surface function** | Artifact-local intent manifestation and confirmation | Staged discrete body-edit preview and governance-bearing escape hatch |
| **Default posture** | Proposal-oriented; user confirms artifact lifecycle/classification moves | Stage → preview → apply/queue/discard for body edits and governance escapes |
| **Scope** | Artifact lifecycle, classification, commitment, follow-up actions | Note body edits and governance-bearing suggestions from Canvas |
| **Governing issues** | #995, #996 | #868–#874 |
| **Spec** | This file | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` |

Visual component reuse is acceptable where semantics genuinely match. The Panel state machine, interaction posture, and confirmation path must remain distinct.

---

## Part 3: Panel Confirmation / Write-Back Contract

### Confirmation Semantics

**Confirmation is the point where the user recognizes, corrects, or accepts an agent-manifested artifact-local intention.**

Confirmation is:

- **Explicit and named.** The user takes a deliberate action (confirm, correct, or reject) for each proposal. There is no implicit confirmation.
- **Reversible before execution begins.** The user may correct or reject a proposal at any time before the confirm action is submitted.
- **Not a Canvas body-edit undo.** Panel confirmation and Canvas co-authoring undo are separate mechanisms for categorically different operations.
- **Scoped to the specific proposal.** Confirming one proposal does not auto-confirm others.

### Write-Back Boundary

The write-back boundary is the contract between Companion UI and the runtime at the moment the user confirms a Panel proposal.

**What the Companion UI is allowed to do:**

- Display richer confirmation affordances than Obsidian checkboxes.
- Submit a named confirmation event or request to the runtime for a specific proposal.
- Show confirmation status (confirming → executing → receipt) as the runtime progresses.
- Display the receipt when execution completes.

**What the Companion UI must NOT do:**

- Write vault files directly.
- Apply mutations without routing through the governed runtime path.
- Execute a proposal in the same turn it was generated unless the existing governed runtime explicitly supports it (same-turn execution of newly generated proposals is NOT allowed by default).
- Bypass WriteGuard, policy gate, idempotency checks, or capability/allowlist constraints.
- Mark a proposal as confirmed without notifying the runtime.
- Treat UI confirmation state as authoritative over runtime execution state.

**What the runtime owns:**

- Policy evaluation.
- WriteGuard.
- Idempotency.
- Execution of the governed action.
- Receipts and inverse-action declaration.
- Durable vault-visible projection.
- Event emission (`panel.intent.executed`, `panel.action.triggered`, `panel.action.logged`, downstream intents).

### Two Approaches Compared

Two confirmation write-back approaches are compared. **Direct Companion UI vault write-back is not viable under this contract** — the UI must not write vault files directly. Any checkbox-compatible projection must be performed by the runtime through the governed write path.

#### Approach 1: Runtime-mediated checkbox projection + watcher-compatible semantics

The Companion UI signals confirmation to the runtime (e.g., via a lightweight call or event). The runtime then writes the confirmed checkbox into the vault panel block through the governed write path (policy / WriteGuard / idempotency), and the watcher re-runs the Panel runtime loop on the resulting vault state.

> **Important:** The Companion UI does not write to the vault directly. The runtime is the sole writer. The checkbox in the vault panel block is a runtime-produced projection of the confirmed intent, not a UI-produced write.

**Strengths:**
- Preserves full Obsidian-compatible semantics (the checkbox in vault is the canonical confirmation artifact).
- Durable vault-visible projection is identical to the CLI flow.
- No new high-level endpoint required beyond a thin runtime notification.

**Weaknesses:**
- Confirmation latency depends on watcher cadence after the runtime write.
- Companion UI has no direct feedback loop about execution progress or outcome.
- The UI cannot distinguish "waiting for watcher" from "watcher failed" without additional status polling.
- Same-turn execution of newly generated proposals is not supported (which is correct by constraint, but the latency is higher).

#### Approach 2: Dedicated confirm endpoint

The Companion UI calls a dedicated runtime endpoint (e.g., `POST /api/panel/confirm`) that accepts a specific proposal/intent ID, marks it confirmed, and triggers governed execution synchronously or with a status callback.

**Strengths:**
- Direct feedback loop: Companion UI can display `confirming → executing → receipt` states immediately.
- No dependency on watcher cadence.
- Enables richer UX: loading states, cancellation, failure display.
- Confirmation remains explicit and named (the endpoint call is the authorization signal).

**Weaknesses:**
- Requires a new runtime endpoint (out of scope for this contract; must be a separate implementation issue).
- Must still produce a durable vault-visible projection and Obsidian-compatible receipt so the vault surface remains consistent.
- Adds a new integration boundary that must be governed and tested.

### Proposed Default

**Prefer a dedicated runtime confirm endpoint for Companion UI confirmation.**

Rationale:
- Richer UX feedback without watcher latency.
- Direct, named confirmation signal (the endpoint call is the authority event).
- Better failure visibility (blocked, policy-rejected, partial-complete states are immediately observable).

**While preserving durable vault-visible projection / Obsidian-compatible semantics:**
- The runtime endpoint must produce the same durable vault-visible output as the checkbox + watcher flow: a receipt in the AI status callout, executed checkboxes removed from the panel working set, and event stream emissions.
- Obsidian-compatible panel/checkbox semantics must remain possible. The vault surface must not become dependent on Companion UI being present for panel state to make sense.

**Do NOT implement the endpoint in this contract.** The endpoint is a follow-up implementation issue. The decision recorded here is: prefer the dedicated endpoint approach; require it to produce Obsidian-compatible durable vault-visible projection.

### Same-Turn Execution Constraint

Same-turn execution of newly generated proposals is NOT allowed unless the existing governed runtime explicitly supports it. This constraint is inherited from `docs/PANEL_AGENT.md :: PA2-FREEFORM` and `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.

In Companion UI terms:
- A proposal displayed in `proposals-staged` state must not auto-execute in the same UI interaction that generated it.
- The user must perform an explicit confirm action before execution begins.
- This applies regardless of how low-risk the proposal appears.

### Mapping to Obsidian Checkbox Semantics

The durable vault-visible projection must remain Obsidian-compatible:

- Confirmed and executed proposals result in the executed checkbox being removed from the panel working set and a receipt entry being written to the AI status callout.
- Proposed but unconfirmed intentions appear as suggested unchecked checkboxes in the vault panel block.
- The vault panel state must remain readable and actionable in Obsidian even if Companion UI is not running.

Companion UI may render these states more richly, but must not produce a vault state that diverges from what the Panel runtime and Obsidian expect.

### Runtime State / API Dependencies

The following runtime state and APIs are required for the confirmation write-back path. These are named here as dependencies; their implementation belongs to separate issues.

Required for dedicated confirm endpoint approach:
- A confirm endpoint that accepts a proposal/intent ID and initiates governed execution.
- A status/receipt polling or callback mechanism so the UI can display `confirming → executing → receipt` states.
- A mapping from endpoint response to durable vault-visible receipt.

Required for all approaches:
- Runtime exposure of current Panel state for the active note (proposals staged, executing, blocked, no-match, receipt).
- Proposal ID / intent ID that can be referenced across the confirmation request.
- Receipt payload with enough information to render `receipt-displayed` state in the UI.

Open questions deferred to implementation:
- Exact endpoint path and request/response schema.
- Whether status feedback is synchronous (polling) or async (webhook/SSE).
- How Companion UI discovers the current Panel state on note open (polling, initial load, or event subscription).
- How cancellation of a confirming or executing proposal is handled.

---

## Implementation-Readiness Boundaries

This contract is docs-only. The following are **not** decided here:

- Panel component library or editor library.
- Exact visual design (tokens, spacing, animation).
- Confirm endpoint path or request/response schema.
- Event contract changes.
- Obsidian plugin implementation.
- Production-ready Panel component shell.

### Open Questions for Implementation Lane

1. **Confirm endpoint schema.** What fields does the confirm request carry? What does the response include? How does the UI correlate a confirm request to a receipt?
2. **Panel state discovery on note open.** How does Companion UI learn the current Panel state for the active note (are there proposals already staged? is there a receipt to display)?
3. **Clarification-needed state interaction.** When the Panel needs more information from the user, how does the UI surface that without collapsing into a chat interface?
4. **Proposal row correction UX.** When the user wants to correct a proposal before confirming, what does the edit affordance look like? Does it open an inline editor, a modal, or a freeform instruction field?
5. **Receipt retention.** How long does the Companion UI keep a receipt visible? Does it persist across note navigations?
6. **Partial-complete state.** When some proposals in a set are confirmed and others are not, how does the Panel state machine track and display the mixed state?

---

## Acceptance Criteria

The following acceptance criteria map directly to issues #995 and #996.

### Render contract (#995)

- [x] A normalized render contract exists for Companion UI Panel rendering (this file).
- [x] Contract defines Panel as artifact-local intent manifestation and confirmation, not merely command execution and not Canvas co-authoring.
- [x] Contract defines all required states: idle, running, proposals-staged, confirming, executing, receipt-displayed, no-match, blocked.
- [x] Contract names future-compatible states: clarification-needed, plan-staged, capability-needed, partial-complete.
- [x] Contract states that no-match and blocked are first-class visible states.
- [x] Contract defines proposal row provenance visibility at confirmation time.
- [x] Contract explicitly says UI never reclassifies actions locally.
- [x] Contract explicitly says Panel is note-bound and not a standalone inbox.
- [x] Contract identifies reuse/divergence from Canvas Suggestion Flow and states that reuse is allowed only where semantics genuinely match.
- [x] Contract preserves the distinction between Panel, Canvas co-authoring, and Canvas bounded suggestion flow.

### Confirmation write-back contract (#996)

- [x] Contract compares runtime-mediated checkbox projection + watcher-compatible semantics versus dedicated confirm endpoint, and states that direct Companion UI vault write-back is not viable.
- [x] Contract records the proposed default (dedicated confirm endpoint) and rationale.
- [x] Contract states confirmation means the user has recognized, corrected, or accepted an agent-manifested artifact-local intention.
- [x] Contract states UI performs no direct vault I/O.
- [x] Contract defines confirmation as explicit, named, and reversible before execution begins.
- [x] Contract states runtime owns policy, WriteGuard, idempotency, execution, receipts, and inverse-action declaration.
- [x] Contract defines durable vault-visible result after confirmation/execution, including how Companion UI confirmation maps back to Obsidian-compatible panel/checkbox semantics.
- [x] Contract lists required runtime state/API/event dependencies without prematurely changing event contracts.
- [x] Contract references #979 and #980 for runtime execution and receipt behavior.
- [x] Contract explicitly excludes Canvas direct body co-authoring from this confirmation path.
- [x] Contract states same-turn execution of newly generated proposals is NOT allowed unless the existing governed runtime explicitly supports it.

---

## Follow-Up Recommendations

After this contract is accepted, the following implementation issues are recommended:

1. **Panel render model / component shell.** Create a Companion UI Panel component shell that renders the Panel surface states (idle, running, proposals-staged, etc.) against a stub data model. No runtime integration yet.
2. **Panel proposal row / status rendering.** Implement the proposal row component (description, provenance visibility, confirm/correct/reject affordances) and the status/receipt display.
3. **Panel confirm / correct / reject affordances.** Implement the confirmation interaction: explicit per-proposal confirm, correct, and reject actions.
4. **Panel confirmation endpoint / API contract.** Create a bounded implementation issue for the runtime confirm endpoint. Define the request/response schema, governed execution wiring, and receipt mapping.
5. **Durable vault-visible projection mapping.** Verify that confirmation via Companion UI produces the same vault-visible receipt and checkbox state as the CLI/watcher flow.

---

## Related Docs

- `docs/PANEL_AGENT.md` — PanelAgent runtime contract (shipped behavior, event payloads, syntax)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md` — Panel authority boundary
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` — three surfaces and non-collapsibility argument
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` — gated-execution invariant
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` — Chat/Panel integration boundary
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — Companion UI product model
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — cognitive boundary constraints and integration boundary rules
- `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md` — Canvas Agent MVP surface contract (includes Panel vs Canvas distinction table)
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — Canvas bounded suggestion flow spec (#868–#874)

## Governing Issues

- `#995` — task: define Companion UI Panel render contract
- `#996` — task: define Companion UI Panel confirmation write-back contract
- `#1019` — docs: clarify Panel as artifact-local intent manifestation surface (closed; conceptual clarification)
- `#1022` — [Epic] Companion UI / UX surface implementation map

---

**Status:** Normalized contract. Docs-only. Ready for implementation issue creation.
