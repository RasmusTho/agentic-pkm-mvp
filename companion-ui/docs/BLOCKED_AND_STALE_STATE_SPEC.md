---
name: Companion UI Blocked and Stale State Spec
description: UX/state contract for held-boundary states: WriteGuard-blocked, stale-source, identity mismatch, and idempotent already-confirmed
doc_role: UX / state contract
authority: Binding UX-state contract for how held-boundary states are presented in Companion UI. The underlying guard behavior is owned by runtime code and docs/PANEL_AGENT.md. Where this doc disagrees with runtime behavior, runtime wins and this doc is corrected.
owner: Companion UI / product architecture
last_reviewed: 2026-06-07
source_contracts:
  - docs/PANEL_AGENT.md
  - docs/ARCHITECTURE.md
  - app/write_guard.py
  - app/panel/confirmation.py
  - app/panel/checkbox_projection.py
  - companion-ui/docs/COMPANION_UI_STATE_MAP.md
governing_issue: "new — create under #1638"
implementation_state: design_spike_target
---
State: Design-spike output. Specifies calm blocked/stale/idempotent presentation states. Captures the spec as of 2026-06-07.

# Companion UI Blocked and Stale State Spec

## Purpose

A held boundary is a success of the governance model, not a failure of the app. When WriteGuard blocks a write, a source hash is stale, or a confirmation is idempotent, the UI must present a calm, named, informative state, not a generic red error toast.

## Principle

- A held boundary preserves the user's intent and mutates nothing.
- The state names the gate/cause, states that nothing was mutated, and offers a path forward.
- It is visually distinct from an ordinary error and from a destructive warning.

## States

### Blocked — WriteGuard / policy

- **Trigger:** `panel.action.blocked` with `{gate, reason, proposal_id}`, or confirmation rejected by WriteGuard, safe mode, or per-note opt-out.
- **Shows:** gate, reason text, "intent preserved; nothing mutated," and the resolve action.
- **Affordances:** Resolve, Retry, Defer.
- **Class:** Proposal under guard; no receipt is written unless the runtime explicitly emits one.
- **Must not:** present as a generic error or discard the confirmed intent.

### Stale — source changed since generated

- **Trigger:** `expected_source_hash` or `expected_content_hash` mismatch at confirm/projection time.
- **Shows:** old vs new hash in short form, "source changed since this was generated," and a Regenerate affordance.
- **Affordances:** Regenerate, Discard.
- **Class:** Proposal under guard.
- **Must not:** allow confirm against the stale hash or conflate with a policy block.

### Blocked — identity mismatch

- **Trigger:** `artifact_id`, `note_path`, `option_id`, or source identity mismatch.
- **Shows:** which identity failed and a refresh/regenerate path.
- **Affordances:** Refresh source, Regenerate.
- **Must not:** infer durable `option_id` from rendered position to recover.

### Idempotent — already confirmed

- **Trigger:** projection/confirm returns `status=already_projected` or `already_confirmed` with no rewrite.
- **Shows:** "already applied — no change" and a link/pointer to the existing receipt when the runtime supplies one.
- **Class:** Receipt posture if a prior receipt exists; otherwise read-only idempotent projection.
- **Must not:** rewrite, double-count, or imply a new execution occurred.

## Visual contract

Use the authority/state palette from `companion-ui/docs/COMPANION_UI_VISUAL_ALIGNMENT_GUIDE.md`. Blocked uses the destructive token at low intensity; stale uses the amber/staged token; idempotent uses the receipt or canonical token. None of these states uses a full-bleed red alarm or modal.

## Acceptance criteria

- A WriteGuard block shows gate and reason, states intent is preserved, writes no new receipt unless runtime says so, and leaves the note unchanged.
- A stale proposal cannot be confirmed; Regenerate re-derives options from the current source.
- A stale-hash/identity block is visually and textually distinct from a policy block.
- An idempotent repeat shows already-applied/no-change copy and does not create a second execution.
- None of these states renders as a generic error toast or destructive alarm.

## Fixtures

`blocked_guard`, `stale_source`, `blocked_hash`, and `idempotent` belong in the cognitive-load UX fixture plan and scripted UAT.
