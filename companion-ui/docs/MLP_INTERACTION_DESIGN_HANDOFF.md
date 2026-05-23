---
name: Companion UI MLP Interaction Design Handoff
description: Curated MLP interaction-design handoff derived from Claude Design delivery, translated into implementation-ready slices under existing Companion UI/runtime authority contracts.
doc_role: Design input (subordinate)
authority: Not source of truth. Subordinate to product spec, surface contracts, runtime boundary docs, and shipped behavior.
owner: Companion UI product + runtime integration
status: Draft for implementation slicing
last_reviewed: 2026-05-21
source_artifact: Companion UI MLP Handoff.html
related_issues: "#1177, #1178, #1179, #1180"
---

# MLP Interaction Design Handoff

## 1. Purpose

This document curates the Claude Design MLP handoff into a repo-readable implementation input for #1180 under epic #1177 and foundations #1178 and #1179. It exists to translate the design artifact (`Companion UI MLP Handoff.html`) into bounded, implementation-ready slices that can be turned into remaining #1177 child issues.

## 2. Status and authority

- This document is design input, not source of truth.
- It is subordinate to:
  - `docs/COMPANION_UI_PRODUCT_SPEC.md`
  - `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
  - `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`
  - `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md`
  - `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
  - shipped runtime and UI behavior
- Companion UI is a shell/host, not a fourth authority surface.
- Vault/Markdown remains the human-readable canonical surface.
- Runtime owns policy, WriteGuard, idempotency, action handling, events, receipts, and durable projection.
- UI never writes vault files directly.
- UI never reclassifies server-declared proposals locally.
- Panel and Canvas remain separate surfaces with separate semantics.

## 3. MLP product promise

Companion UI is a calm shell that hosts canonical surfaces and never lies about who has authority.

## 4. MLP vertical slice

`Open note -> Reorient -> Canvas body edit -> Panel Act -> Receipt`

## 5. MLP includes

- real-note workspace loaded through runtime
- runtime/channel safety strip
- artifact identity / note path / content hash
- Reorient card
- Canvas body-edit session with preview/apply/undo/recovery
- Panel proposal review with evidence
- confirm/correct/reject via runtime
- receipt/block reason display
- Resurface read-only candidates unless persistence exists
- Find unavailable/candidate state

## 6. MLP excludes

- global inbox
- cross-note dashboard
- autonomous execution
- direct UI vault writes
- UI-side reclassification
- full Obsidian replacement
- full frontend rewrite
- memory promotion UX unless separately governed

## 7. Workspace layout guidance

- Main note area remains primary cognitive anchor.
- Companion rail hosts Reorient, Canvas session, Panel proposal, and outcome cards.
- Runtime safety strip is always visible when degraded/blocked/runtime-unavailable states exist.
- Active note header shows note title/path context and note-bound scope.
- Artifact identity pill shows canonical artifact identity and path resolution status.
- Content hash/version signal shows current hash and conflict/recovery relevance.
- Guard state is visible, never implied.
- Session state is visible (active, volatile, recovery-needed, conflict, blocked).
- Receipt visibility is persistent in-session; outcome is not hidden after action completes.
- Layout behavior:
  - Desktop: companion rail to the side of the note.
  - Narrow viewport: companion rail as bottom sheet; note remains visible.

## 8. Interaction flows

### Open note

- Runtime resolves active note and returns identity/path/hash + affordance statuses.
- UI renders shell and status cards only from runtime-declared state.

### Reorient

- Reorient card summarizes where work left off with bounded evidence links.
- Reorient remains advisory and never executes actions.

### Canvas body edit

- Canvas edit session runs note-body edits only.
- UI calls `POST /api/canvas/sessions/{id}/edits`; runtime owns writer path.
- Preview/apply/undo/recovery behavior is explicit.

### Canvas recovery/conflict

- On volatility/reopen/hash mismatch, UI enters recovery-needed or conflict-detected state.
- User must acknowledge before continuing write-affecting actions.

### Panel proposal review

- Panel shows server-declared proposal(s) with evidence disclosure.
- No local reclassification.

### Panel confirm/correct/reject

- Confirm/correct/reject all route through runtime contracts.
- Same-turn confirmation blocked copy is explicit:
  `Same-turn confirmation is not allowed. The proposal must be confirmed in a later interaction.`

### Receipt/block outcome

- Action outcome renders as receipt card or block reason card.
- If runtime returns inverse action, UI may display it as receipt context only; no direct apply shortcut.

## 9. State model

Each state includes: when it appears, copy guidance, allowed actions, forbidden actions.

- `active`: note loaded and writable via runtime; copy confirms ready; allow reorient/canvas/panel actions; forbid authority claims from UI-only state.
- `read-only`: runtime marks read-only or no persistence path; copy says read-only; allow inspect/review; forbid apply/confirm that implies mutation.
- `unavailable`: artifact/runtime cannot provide required payload; copy says unavailable; allow retry/fallback navigation; forbid fake-ready controls.
- `blocked`: guard/policy blocks action; copy includes reason; allow inspect reason + safe next step; forbid hidden continuation.
- `experimental`: non-baseline feature flag state; copy labels experimental; allow explicit opt-in actions; forbid presenting as stable default.
- `recovery-needed`: volatile session/re-entry requires acknowledgement; copy requests recovery acknowledgement; allow recover/reload; forbid silent edits.
- `conflict-detected`: content hash changed vs session base; copy explains mismatch; allow refresh/rebase/retry; forbid apply against stale base.
- `expired proposal`: proposal TTL elapsed; copy says proposal expired; allow request refreshed proposal; forbid confirm expired proposal.
- `same-turn blocked`: runtime disallows same-turn confirm; copy uses exact required wording; allow defer to later interaction; forbid same-turn execution bypass.
- `receipt-displayed`: runtime returns action outcome receipt; copy summarizes outcome and timestamp; allow inspect receipt context; forbid pretending action executed when only logged.
- `runtime unavailable`: runtime/channel unreachable; copy says runtime unavailable; allow retry/offline read-only; forbid mutation affordances.
- `artifact identity unresolved`: path/identity unresolved; copy says identity unresolved; allow reload/open note picker; forbid write-capable state.
- `Canvas disabled`: runtime reports Canvas disabled; copy says Canvas disabled; allow panel/reorient read paths; forbid canvas edits.
- `WriteGuard blocked`: runtime WriteGuard deny; copy shows WriteGuard blocked reason; allow inspect and corrective path; forbid local override.
- `Find unavailable`: no backend payload for find; copy says unavailable/candidate; allow passive candidate display; forbid functional search UX implication.
- `Resurface read-only`: resurfaced candidates without persistence; copy says read-only candidates; allow inspect/dismiss; forbid persistent controls (pin/snooze) unless persistence exists.

## 10. Component inventory

- `ActiveNoteHeader`: note-local scope header, title/path, workspace context.
- `RuntimeSafetyStrip`: always-visible degraded/blocked/runtime channel state.
- `ArtifactIdentityPill`: artifact identity and note path resolution state.
- `ContentHashPill`: content hash/version signal for conflict and recovery visibility.
- `CompanionRail`: host container for major rail cards.
- `AffordanceStatusBadge`: status indicator for each major rail card or actionable section.
- `ReorientCard`: daily reorientation summary card.
- `ReorientSection`: grouped reorient details and evidence links.
- `CanvasSessionCard`: Canvas session state, volatility, recovery affordances.
- `BodyEditComposer`: bounded body-edit prompt/composer entry.
- `BodyEditPreview`: staged edit preview before apply.
- `RecoveryBanner`: recovery-needed/conflict acknowledgement banner.
- `PanelProposalCard`: server-declared proposal row with action affordances.
- `ProposalEvidenceDisclosure`: expandable evidence and mapping disclosure.
- `ConfirmCorrectRejectControls`: runtime-routed decision controls.
- `ReceiptCard`: durable in-session action outcome view.
- `BlockReasonCard`: explicit blocked reason and next-step guidance.
- `ResurfaceCandidateCard`: read-only resurfaced candidate presentation.
- `FindCandidateCard`: unavailable/candidate find-state presentation.
- `EmptyStateCard`: no proposal/no candidate/no activity empty states.
- `ErrorStateCard`: runtime/channel/identity failure presentation.

## 11. Copy guidance

- WriteGuard blocked: `This action is blocked by WriteGuard. Review the policy reason before retrying.`
- Canvas disabled: `Canvas editing is currently disabled by runtime configuration.`
- in-memory / volatile session: `This session is currently in-memory and may not persist across interruptions.`
- proposal expired: `This proposal has expired. Request a refreshed proposal to continue.`
- same-turn blocked: `Same-turn confirmation is not allowed. The proposal must be confirmed in a later interaction.`
- body edit applied: `Body edit applied to the active note.`
- undo available: `Undo is available for the most recent body edit.`
- no undo available: `No undo is available for this session state.`
- no actionable Panel proposal: `No actionable Panel proposal is available for this note right now.`
- Find unavailable: `Find is unavailable because no backend candidate payload is available yet.`
- Resurface read-only: `These resurfaced candidates are read-only in this MLP.`
- runtime unavailable: `Runtime is unavailable. Showing read-only context until connection recovers.`
- artifact identity unresolved: `Artifact identity is unresolved. Reopen or reload the note to continue.`
- recovery acknowledgement required: `Recovery acknowledgement is required before continuing edits.`
- hash conflict detected: `Content hash conflict detected. Refresh to rebase before applying edits.`
- receipt available: `Receipt available: outcome recorded by runtime.`
- action logged, not executed: `Action was logged but not executed.`
- action rejected: `Action was rejected by runtime policy.`
- corrected action handled: `Corrected action submitted and handled by runtime.`

## 12. Implementation slices

### 12.1 Honest affordance statuses

- User value: users always see true capability/guard state.
- UI changes: add/normalize `AffordanceStatusBadge` on each major rail card/actionable section.
- Required runtime data: capability flags, guard states, channel status, proposal status.
- Acceptance criteria: no actionable control appears enabled when runtime says unavailable/blocked.
- Test hints: component rendering matrix from runtime state fixtures.
- Non-goals: redesigning all micro-rows with badges.
- Likely files: `companion-ui/companion-app/*status*`, `companion-ui/docs/*contract*`.

### 12.2 Better real-note workspace shell

- User value: immediate trust in active artifact identity.
- UI changes: `ActiveNoteHeader`, `ArtifactIdentityPill`, `ContentHashPill`, `RuntimeSafetyStrip`.
- Required runtime data: note path, artifact id, content hash/version, runtime channel state.
- Acceptance criteria: unresolved identity/hash conflict states are explicit and non-silent.
- Test hints: hash conflict and unresolved identity fixtures.
- Non-goals: global dashboard/inbox.
- Likely files: companion shell layout/components and handoff docs.

### 12.3 Canvas body-edit MLP

- User value: reliable note-body edit flow with preview/apply/undo/recovery.
- UI changes: `CanvasSessionCard`, `BodyEditComposer`, `BodyEditPreview`, `RecoveryBanner`.
- Required runtime data: canvas session id/state, edit preview payload, conflict/recovery metadata.
- Acceptance criteria: UI uses `POST /api/canvas/sessions/{id}/edits`; no direct vault writes.
- Test hints: apply/undo/recovery/conflict interaction tests.
- Non-goals: governance mutation in Canvas.
- Likely files: canvas session UI, contracts, API client wiring.

### 12.4 Panel / Act receipt MLP

- User value: clear decision path for proposal -> outcome.
- UI changes: `PanelProposalCard`, `ProposalEvidenceDisclosure`, `ConfirmCorrectRejectControls`, `ReceiptCard`, `BlockReasonCard`.
- Required runtime data: server-declared proposal classification, evidence, decision endpoint responses, receipts/block reasons.
- Acceptance criteria: Panel and Canvas semantics remain separate; same-turn blocked copy enforced.
- Test hints: confirm/correct/reject state transitions and block reason rendering.
- Non-goals: same-turn execution bypasses.
- Likely files: panel card components + interaction contract docs.

### 12.5 Reorient daily recovery view

- User value: faster interruption recovery with bounded context.
- UI changes: `ReorientCard` + `ReorientSection` in companion rail.
- Required runtime data: last activity summary, bounded evidence links, session state.
- Acceptance criteria: advisory only; no hidden execution.
- Test hints: no-data, stale-data, runtime-unavailable rendering.
- Non-goals: long-horizon planning board.
- Likely files: reorient card components, docs, fixtures.

### 12.6 Resurface read-only cleanup

- User value: resurfaced items feel useful without fake persistence.
- UI changes: `ResurfaceCandidateCard` and copy clarifying read-only nature.
- Required runtime data: resurfaced candidate payload + persistence capability flag.
- Acceptance criteria: no persistent-looking controls unless persistence exists.
- Test hints: persistence on/off snapshots.
- Non-goals: priority or urgency modeling.
- Likely files: resurfacing cards, copy tables, status badges.

### 12.7 Find unavailable / candidate state

- User value: explicit find limitations instead of dead controls.
- UI changes: `FindCandidateCard`, `EmptyStateCard`, `ErrorStateCard`.
- Required runtime data: find capability status, candidate payload presence, channel state.
- Acceptance criteria: when backend payload missing, UI states unavailable/candidate clearly.
- Test hints: unavailable/candidate/error permutations.
- Non-goals: shipping full find backend in this slice.
- Likely files: find state components and docs.

### 12.8 MLP production launch safety pass

- User value: trustworthy launch behavior under degraded/runtime edge cases.
- UI changes: guardrails + final copy/state audit across all major cards.
- Required runtime data: full state contract coverage.
- Acceptance criteria: authority boundaries and blocked/degraded visibility pass checklist below.
- Test hints: docs guard + targeted UI state regression tests.
- Non-goals: broad visual redesign.
- Likely files: component status handling, docs, test fixtures.

## 13. Risks and mitigations

- UI implying authority it does not have: explicit authority copy + runtime-owned outcome cards.
- UI hiding guard/degraded state: mandatory safety strip + status badges on major actionable sections.
- read-only controls looking actionable: disable/hide mutation controls and state why.
- Resurface feeling urgent: neutral copy and no urgency semantics.
- Panel and Canvas semantics collapsing: separate cards, state models, and action vocab.
- receipts feeling ephemeral: persistent in-session receipt visibility until dismissal/navigation.
- session volatility being hidden: explicit volatile/recovery-needed state and acknowledgement.
- technical metadata overwhelming user: progressive disclosure for evidence/hash detail.
- server-rendered shell becoming too complex: keep MLP slice bounded to required cards and states.

## 14. MLP definition of done

- [ ] Handoff doc exists at `companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`.
- [ ] Doc states it is design input, not source of truth.
- [ ] Doc references #1177, #1178, #1179, #1180.
- [ ] Vertical slice is exactly `Open note -> Reorient -> Canvas body edit -> Panel Act -> Receipt`.
- [ ] Panel and Canvas separation is explicit.
- [ ] Doc states UI never writes vault files directly.
- [ ] Doc states runtime owns policy, WriteGuard, idempotency, action handling, events, receipts, durable projection.
- [ ] Required corrections from review are applied.
- [ ] Implementation slices are concrete enough to produce remaining #1177 child issues.
- [ ] Full Claude Design zip is not committed wholesale.
