# Autonomous Operations Companion Interaction Handoff

Status: Design guidance only. This is a target-state interaction handoff for
Issue #5338; it is not an implementation specification, architecture authority,
or runtime receipt.

## Scope and authority

This handoff translates the `ygg.operation.v1` human flow into a bounded
Companion journey: discover resources, choose one admitted outcome, inspect the
frozen scope and policy, delegate once where required, observe the operation,
inspect its receipts, and use only contract-admitted recovery. It does not add a
route, component, visual primitive, token, API, or write path. The operation
kernel and owner-native services declare capability, authority, typed outcome,
and recovery posture; **server declares; UI renders**.

The referenced surfaces are existing Companion concepts, not claims that the
required operation controls are already shipped. Panel remains the command
surface, Chat remains a subordinate proposal/context surface, and Automation
remains a separate lane. The UI is transport for human intent and cannot create,
expand, or retry an ambiguous authority-bearing effect.

## Human-flow and Companion-surface map

| Contract stage | Existing Companion surface/component | Required interaction guidance | Authority boundary |
| --- | --- | --- | --- |
| Discover and select | Workspace shell and Vault Browser | Browse/filter resources, show title/path together with stable identity and provenance, then retain an explicit selection set. | Discovery is read-only; a path is locator data, not identity authority. |
| State an outcome | Workspace shell action entry and Panel | Offer only server-declared admitted operations for the selection; disclose unsupported capability rather than synthesizing an action. | Panel transports intent to the governed seam; it does not classify authority. |
| Inspect scope | Panel preview/diff and bounded batch review | Show affected identities, versions, context/vault generation, policy/trust crossings, reversibility, limits, and material uncertainty before confirmation. | Preview is not delegation and does not reserve an unconfirmed target set. |
| Delegate once | Panel confirmation | Confirm the immutable operation family, context, selector or explicit targets, maximum count, expiry/revocation, and partial-success policy once. | A client cannot broaden this delegation or add targets after confirmation. |
| Execute and observe | Workspace shell progress region and Panel activity | Show per-item progress separately for source effect, receipt persistence, and derived convergence. Keep progress passive until the kernel returns a typed outcome. | `convergence_pending` is observable work, not a reason to roll back a committed source effect. |
| Review outcome | Panel receipt/activity history and Vault Browser inspection | Keep completed, refused, skipped, conflicted, and recoverable items inspectable with stable receipt/provenance links. | A visible intent or spinner must not stand in for an owner-native effect and receipt. |
| Recover or correct | Panel conflict/recovery view | Offer resume, verify, retry, compensate, or restore only when the returned operation contract admits that action. | Unknown, stale, or ambiguous effects fail closed; no UI retry is implied. |

Progressive disclosure starts with the selection, declared capability, and
high-level impact. It expands into the frozen scope/policy before confirmation,
then into per-item outcomes, receipt metadata, and recovery evidence after the
operation. This avoids turning the Workspace shell into a dashboard while
keeping authority-bearing detail available when it matters.

## Failure and recovery states

| State | UI treatment | Permitted next step |
| --- | --- | --- |
| Loading | Preserve the current selection, announce that capability/preview/progress data is loading, and do not expose an enabled confirmation control. | Wait, retry the read when the server declares it safe, or return to selection. |
| Empty | Explain that no resource or no admitted operation matches the current context/filter without treating absence as a failure. | Adjust filter, context, or selection; never infer a target. |
| Denial | Show the server-declared refusal reason, relevant policy/context condition, and no false-success receipt. | Narrow scope, restore valid context, or request the owning human-intent action. |
| Conflict | Preserve both the selected stable identity and returned version/conflict evidence; do not overwrite or auto-merge. | Inspect, refresh/preflight, or take the contract-admitted correction route. |
| Partial failure | Render every item outcome and distinguish completed effects from refused, conflicted, pending, and recoverable work. | Verify completed receipts; resume only the returned recoverable subset. |
| Cancellation | State whether cancellation was accepted and which items are already terminal; retain their receipts. | Review the terminal/recoverable split; do not promise rollback. |
| Restart | Rehydrate the operation by request identity and durable item/receipt state rather than recreating client progress. | Observe, verify, or resume only if the kernel declares it recoverable. |
| Recovery | Present the typed recovery path and its preconditions, including stale-generation or ambiguity refusals. | Resume, verify, compensate, or restore only as returned; recovery must not imply success. |

For source success with delayed projections, show `convergence_pending` as a
separate, recoverable phase with its convergence obligation. It must not imply
success for an unknown source effect, and it must not silently hide a completed
source mutation.

## Accessibility and responsive behavior

- The selection list, action entry, preview, confirmation, progress, receipt,
  conflict, and recovery regions have a keyboard path in the same human-flow
  order. Escape exits a non-destructive disclosure; it never cancels an
  operation without an explicit contract-admitted cancellation action.
- Focus moves to a newly opened preview or conflict/recovery region with an
  explicit label, returns to its invoking control on dismissal, and never
  disappears behind a loading state. Destructive or authority-bearing actions
  retain a visible, named confirmation target.
- A screen reader receives concise, deduplicated live updates for state changes
  and per-item progress; receipt identity, typed outcome, and recovery status
  remain reachable as semantic text rather than color alone.
- At 200% zoom and in a narrow viewport, the flow becomes one ordered column:
  selection, impact/preview, confirmation, then status. Scope and receipt
  evidence remain available through disclosures; no horizontal-only control or
  hover-only explanation is required.
- In a wide viewport, the Workspace shell may retain the selected resources and
  Panel context beside progress/receipt detail, but reading order and keyboard
  order remain equivalent to the narrow layout. The layout adds no authority
  affordance.

## Review evidence

Review this interaction guidance against the human-flow contract before any
implementation issue expands the UI. The reviewer checks that each mapped stage
uses the named Companion surface, that the UI renders rather than reclassifies
authority, that all failure states preserve typed outcomes, and that the
keyboard, focus, screen reader, 200% zoom, narrow viewport, and wide viewport
behaviors above remain available. This is design-review evidence, not a claim
that a prototype, live UI audit, or runtime acceptance has occurred.

## Design validation receipt

- Workflow: `.codex/skills/yggdrasil-design-handoff/SKILL.md` was applied to
  classify this as a documentation-only interaction handoff.
- Classification: no visual artifact is generated or revised; this handoff adds
  no visual component, geometry, token, typography, motion, icon language, or
  authority affordance.
- Live design-system gate: not invoked because this change produces no visual
  generation, prototype, or constrained-reuse package. No live design-system
  selection, MCP system identity, project, or token-parity receipt is claimed.
- Validation boundary: the accompanying governance tests verify the documented
  interaction coverage; future visual work must reclassify and pass the live
  gate before generation.
- Runtime boundary: No runtime delivery is claimed. Implementation remains
  downstream in the bounded operations-workspace issue and owner-native
  operation contracts.
