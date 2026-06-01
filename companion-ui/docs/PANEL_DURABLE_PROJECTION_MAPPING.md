---
name: Panel Durable Vault-Visible Projection Mapping
description: Mapping from Panel confirmation/execution outcome to vault-visible state — checkbox semantics, receipt callout, event emissions, inverse-action, watcher compatibility, and runtime-sole-writer rule
doc_role: Projection mapping / spec
authority: Binding contract for any implementation that writes vault-visible state as a result of Panel confirmation. Must not be bypassed.
owner: v6.0 architecture / Panel runtime implementation lane
last_reviewed: 2026-05-17
governing_issues: "#1043"
related_issues: "#1042, #1039, #1040, #1041, #1022, #995, #996"
source_contracts:
  - companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
  - companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md
  - docs/PANEL_AGENT.md
---

# Panel Durable Vault-Visible Projection Mapping

## Purpose

Define the mapping from Panel confirmation/execution outcome to vault-visible
state.

This document is the contract for runtime writer behavior, vault-visible
projection, and watcher/runtime convergence. The first read-mode checkbox
projection slice is implemented through `POST /api/panel/checkbox-projection`;
future projection behavior must preserve the same mapping.

---

## Governing Principle

**The runtime is the sole writer of vault-visible state.**

The Companion UI must not write vault files directly. All durable vault-visible
mutations resulting from Panel confirmation route through the runtime's governed
execution path: policy → WriteGuard → idempotency → deterministic writer →
receipt → event emission.

The canonical human-facing confirmation signal is the checked Markdown checkbox
inside a valid Panel `AI-åtgärder` section:

```markdown
- [x] ...
```

Companion UI read-mode confirmation is only a request for the runtime to project
that same checkbox state. It is not a separate approval store, and the browser
click does not execute an agent action directly.

Vault state must remain readable and actionable in Obsidian even if Companion
UI is not running. The vault surface must not become dependent on Companion UI
presence for Panel state to make sense.

---

## Vault Panel Block: Obsidian-Compatible Semantics

The Panel runtime maintains a panel block within each managed note. The panel
block syntax is defined in `docs/PANEL_AGENT.md`. This mapping document
specifies how each Panel outcome maps to changes within that block.

The panel block uses Obsidian-compatible checkbox and callout syntax:

```markdown
> [!panel]+ AI Panel
> - [ ] ACTION_ID — description — evidence summary
> [!info]- AI status
> - ✅ ACTION_ID — outcome — timestamp
```

The vault surface must remain parseable by Obsidian and by the Panel watcher
without requiring Companion UI.

---

## Outcome → Vault State Mapping

### Proposed (unconfirmed)

**Trigger:** Panel agent stages a proposed intention. No user action yet.

**Vault state:**

- An unchecked checkbox entry appears in the panel working set:
  ```markdown
  - [ ] ACTION_ID — description — evidence summary
  ```
- No entry in the AI status callout.
- The proposed checkbox is written by the Panel agent runtime (not Companion UI)
  when it stages the proposal.

**Companion UI rendering:** `proposals-staged` state with the proposal row.

**Writer:** Runtime (Panel agent write path).

---

### Projected checked checkbox

**Trigger:** User clicks a runtime-declared eligible Panel option in Companion
UI read mode, and the backend validates the current note source, Panel identity,
option identity, WriteGuard, safe/degraded policy, and idempotency.

**Vault state (intermediate — execution pending):**

- The targeted checkbox is projected as checked inside the same valid Panel
  `AI-åtgärder` section:
  ```markdown
  - [x] ACTION_ID — description — evidence summary
  ```
- This checked checkbox is the durable human-facing confirmation signal.
- Projection and execution are distinct phases. Projection is the
  runtime-mediated checked-checkbox write/projection; execution is the normal
  Panel runtime observing or being triggered from that checked checkbox state.
- The AI status callout may include an intermediate `🔄 ACTION_ID — confirming`
  entry if the runtime writes an in-progress receipt.

**Companion UI rendering:** `confirming` → `executing` states.

**Writer:** Runtime via `POST /api/panel/checkbox-projection`. The staged
`POST /api/panel/confirm` implementation is not the source-backed checkbox
projection endpoint.

---

### Executed

**Trigger:** Runtime completes governed execution after observing or being
triggered from the checked Panel checkbox state.

**Vault state:**

- The proposed checkbox is **removed** from the panel working set:
  ```markdown
  ~~- [ ] ACTION_ID — description~~
  ```
  or simply deleted from the block, depending on Panel runtime conventions.
  The Panel agent runtime convention from `docs/PANEL_AGENT.md` governs exact
  syntax.
- The AI status callout is updated with an execution receipt:
  ```markdown
  > [!info]- AI status
  > - ✅ ACTION_ID — success — 2026-05-17T12:00:00Z
  > - Inverse: INVERSE_ACTION_ID (if declared)
  ```
- Event `panel.intent.executed` is emitted.
- Event `panel.action.triggered` is emitted.

**Companion UI rendering:** `receipt-displayed` state.

**Writer:** Runtime (deterministic note-writer, WriteGuard-cleared).

---

### Blocked

**Trigger:** Governed execution denied at policy gate, WriteGuard, allowlist,
or capability constraint.

**Vault state:**

- The proposed checkbox remains in the panel working set (the intention was
  not acted upon).
- The AI status callout is updated with a blocked receipt:
  ```markdown
  > [!info]- AI status
  > - 🚫 ACTION_ID — blocked — gate: writeguard — 2026-05-17T12:00:00Z
  > - Reason: WriteGuard denied: tag allowlist
  ```
- Event `panel.action.blocked` is emitted.

**Companion UI rendering:** `blocked` state with reason visible.

**Writer:** Runtime (blocked receipt writer).

---

### Rejected / Dismissed

**Trigger:** User explicitly rejects the proposal in Companion UI.

**Vault state:**

- The proposed checkbox is removed from the panel working set (the intention
  was declined).
- No receipt entry in the AI status callout (rejection is a UI decision, not
  an execution outcome). An optional minimal log entry may be written:
  ```markdown
  > [!info]- AI status
  > - ❌ ACTION_ID — dismissed — 2026-05-17T12:00:00Z
  ```
  Whether a dismissed entry is written is an implementation decision. The entry
  must not imply execution occurred.
- No event emission required for rejection, unless the runtime has a
  `panel.intent.dismissed` event in its inventory.

**Companion UI rendering:** Proposal row removed or marked dismissed.
Panel returns to `proposals-staged` (if other proposals remain) or `idle`.

**Writer:** Runtime (only if a separate reject/dismiss contract is specified).

**First-slice note:** reject/dismiss behavior is not part of the first read-mode
checkbox projection slice unless a separate implementation issue specifies it.

---

### Logged

**Trigger:** Policy route produces a "log for review" outcome rather than
direct execution.

**Vault state:**

- The proposed checkbox is moved to a logged/deferred section or removed from
  the active working set.
- The AI status callout is updated with a logged receipt:
  ```markdown
  > [!info]- AI status
  > - 📋 ACTION_ID — logged — 2026-05-17T12:00:00Z
  > - Deferred for review: policy required logging route
  ```
- Event `panel.action.logged` is emitted.

**Companion UI rendering:** `receipt-displayed` state with `logged` outcome.

**Writer:** Runtime (logging path).

---

### Partial-Complete

**Trigger:** A proposal decomposes into sub-actions; some succeed, some are
blocked.

**Vault state:**

- Executed sub-actions: removed from working set, receipt written.
- Blocked sub-actions: remain in working set with a blocked receipt.
- AI status callout entries written for each sub-action outcome individually.

**Companion UI rendering:** `partial-complete` state; per-proposal/sub-action
receipt rows visible.

**Writer:** Runtime (per-sub-action writer).

---

### Receipt-Displayed

**Trigger:** Companion UI has received and is displaying the execution receipt.

**Vault state:** No additional vault writes at this point. The vault-visible
state was written during the Executed/Blocked/Logged phase. `receipt-displayed`
is a Companion UI render state, not a vault state.

---

## Event Stream Emissions

The runtime must emit the following events when Panel confirmation outcomes are
written to the vault:

| Event | Trigger |
|---|---|
| `panel.intent.executed` | Execution succeeded; vault receipt written. |
| `panel.action.triggered` | Governed action was triggered (may precede `executed`). |
| `panel.action.logged` | Action logged rather than executed. |
| `panel.action.blocked` | Execution blocked at a gate; blocked receipt written. |

Event names and payloads must conform to the existing Panel runtime event
inventory in `docs/PANEL_AGENT.md`. This document does not modify those schemas.

---

## Inverse-Action Declaration

When the runtime executes a governed action, it must declare the inverse action
(the undo operation) in the receipt:

- `inverse_action` field in the receipt response (see
  `PANEL_CONFIRMATION_API_CONTRACT.md`).
- `Inverse: INVERSE_ACTION_ID` in the AI status callout receipt line.

The inverse action declaration enables future undo flows without requiring the
Companion UI to maintain local action history.

---

## Watcher Compatibility

The vault-visible state produced by Companion UI runtime-mediated checkbox
projection must be compatible with the CLI/watcher flow:

- A watcher processing the vault after Companion UI projection must see the
  same checked checkbox state as if the confirmation had come from Obsidian, a
  plain text editor, or a CLI-compatible flow.
- The watcher must not need to distinguish "projected via Companion UI" from
  "checked directly in vault Markdown."
- The AI status callout syntax must match the Panel agent runtime's established
  callout format from `docs/PANEL_AGENT.md`.

---

## CLI/Watcher Flow Equivalence

The durable vault projection produced by this confirmation path must be
equivalent to the checkbox + watcher path:

| Vault element | Checkbox + watcher | Projection endpoint/revision |
|---|---|---|
| Checked checkbox confirmation | ✅ (`- [x]` in Panel `AI-åtgärder`) | ✅ (runtime projects `- [x]`) |
| Executed checkbox removed | ✅ (watcher removes) | ✅ (runtime removes on execute) |
| AI status callout receipt | ✅ (watcher writes) | ✅ (runtime writes via endpoint) |
| Event emissions | ✅ (watcher emits) | ✅ (endpoint execution emits) |
| Inverse-action declared | ✅ | ✅ |
| Policy / WriteGuard applied | ✅ | ✅ |
| Idempotency enforced | ✅ | ✅ |

The two paths must converge on the same vault-visible state.

## Race and Idempotency Requirements

- Stale Companion UI content: reject with stale-content status; do not guess by label or rendered DOM position.
- Watcher overlap: projection and watcher execution must deduplicate through existing Panel idempotency keys and the durable `ai:option_id` option identity.
- Browser retries: the same `idempotency_key` returns the same result and must not write or execute twice.
- Already checked checkbox: treat as idempotent if it targets the same option and source generation; otherwise return current status.
- Option missing or moved: fail stale/not-found unless durable `option_id` and source hash validate an unambiguous move.
- Proposal section removed: fail stale/not-found; do not recreate the proposal.
- Duplicate labels: never target by label alone.
- Execution succeeds but UI stale: artifact refresh must show current vault state and receipt; do not re-submit.
- Projection succeeds but execution fails: keep the checked/projected confirmation status distinct from execution failure; surface blocked/failed runtime status through existing event/outbox/receipt conventions.

---

## Companion UI Must Not Write Vault Files Directly

**This is a hard boundary.**

The Companion UI must not:

- Write vault `.md` files directly.
- Update checkboxes directly.
- Write or modify the AI status callout directly.
- Apply mutations without routing through the runtime's governed write path.

Any vault-visible state change as a result of Panel confirmation must flow
through:

```
Companion UI read-mode checkbox click
  → source-backed projection request
  → runtime source/option validation
  → WriteGuard
  → idempotency check
  → deterministic note-writer projects - [x] (runtime-owned)
  → normal Panel execution observes or is triggered from checked checkbox
  → receipt
  → event emission
```

---

## Required Tests Before Implementation

The following tests must exist before or alongside projection implementation:

1. `test_panel_projection_checked_checkbox_written` — projection writes `- [x]`
   for the targeted option inside the valid Panel `AI-åtgärder` section.
2. `test_panel_projection_rejects_stale_source` — changed content/source hashes
   reject without guessing by label or DOM order.
3. `test_panel_projection_dedupes_watcher_overlap` — watcher overlap does not
   duplicate writes or execution.
4. `test_panel_projection_retry_idempotent` — duplicate browser retries with the
   same `idempotency_key` return the same status without duplicate writes.
5. `test_panel_projection_duplicate_labels_require_option_id` — duplicate labels
   are never targeted by label alone.
6. `test_panel_projection_executed_removes_checkbox` — after execution, the
   proposed checkbox is removed from the panel working set in the vault.
7. `test_panel_projection_executed_writes_receipt_callout` — after execution,
   the AI status callout contains the execution receipt with the correct format.
8. `test_panel_projection_blocked_preserves_checkbox` — after a block, the
   proposed checkbox remains in the working set.
9. `test_panel_projection_blocked_writes_blocked_receipt` — a blocked receipt
   entry appears in the AI status callout.
10. Reject/dismiss-scope only:
    `test_panel_projection_rejected_removes_checkbox_no_execution_receipt` —
    after rejection, the checkbox is removed and no execution receipt is written.
11. `test_panel_projection_watcher_compatible` — the vault state produced by
   the projection path is parseable by the watcher without special-casing.
12. `test_panel_projection_inverse_action_declared` — executed receipts include
   the inverse-action identifier.
13. `test_panel_projection_companion_ui_does_not_write_vault_directly` —
   architecture/import test asserting no vault-write code exists in
   `companion_ui/` modules.

---

## Open Questions (Deferred to Implementation)

1. **Exact checkbox removal syntax.** Does the runtime delete the checkbox line
   or annotate it as completed/archived? `docs/PANEL_AGENT.md` governs; this
   document defers.
2. **In-progress annotation.** Should the runtime write an intermediate
   `[>]` or `🔄` marker when execution begins but before it completes? This
   is an implementation decision; the vault must remain Obsidian-parseable.
3. **Dismissed log entry.** Is a dismissed/rejected receipt written to the
   vault? Minimal log entry is acceptable if it does not imply execution.
4. **Sub-action decomposition.** When a proposal decomposes into multiple
   sub-actions, how are they represented in the panel working set? Are they
   separate checkbox entries?
5. **Vault locking.** When multiple Companion UI sessions or CLI instances
   could write to the same note simultaneously, how does the runtime arbitrate?
   WriteGuard is expected to handle this; confirm here.
6. **Option identity marker.** Does the implementation promote `ai:id` into
   durable `option_id` with stronger generation rules, or introduce a new
   explicit marker such as `<!--ai:option_id=...-->`? This decision blocks
   implementation.

---

## Governing Boundary Statement

- This document is contract/spec only.
- No runtime writer behavior is implemented here.
- No vault files are written by this document.
- No watcher behavior is modified by this document.
- No existing runtime event schemas are altered by this document.
- The Companion UI must not write vault files directly.
- The runtime is the sole writer of vault-visible state.
- Vault state must remain Obsidian-compatible and watcher-compatible
  regardless of whether Companion UI is present.
