State: Active blocked validation hub #4693; no implementation delivery is claimed.
Doc role: Parent feature issue contract
Authority: The capability README owns the stable design and decomposition. The live GitHub parent
owns backlog and validation state after filing.

# Parent feature issue — devUI Focus + Conversation Port

## Context

The delivered devUI composition seam can read CKM and BuilderOps sources honestly, but the owner
does not yet have a subject-centred Focus view or a governed external Conversation Port. Provider
sessions remain provenance, and the existing Model Inquiry route is artifact-first and separate
from GitHub/repository delivery.

## Scope

- Deliver FCP-01 through FCP-04 in strict dependency order.
- Keep one stable Issue/capability subject across Focus, conversation context, command preview, and
  receipt.
- Preserve explicit source, correlation, freshness, coverage, cardinality, linkage, and limitation
  semantics.
- Reuse the existing Model Inquiry launcher/receipt without creating direct delivery effects.
- Keep Builder System Control as a separate follow-up lens and issue.
- Keep the parent as the live validation and receipt hub; it never receives `agent:ready`.

## Source Anchors

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Information architecture and hard boundary`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Cross-slice invariants`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Capability acceptance`

## SBS Impact

- Primary subsystem: Builder System / devUI owner experience
- Secondary subsystem(s): Model Inquiry workflow adapter
- Write class: target specification followed by bounded read/UI and existing-workflow adapter work
- Authority impact: none; projections and conversations remain non-authoritative
- Persistence impact: no new devUI persistence; existing Model Inquiry artifacts only
- Derived/rebuildable impact: Focus and future Builder System Control views are per-read/rebuildable
- Human knowledge impact: none
- Memory impact: no Product/Runtime or user-memory impact
- Retrieval/context impact: one scoped hash-bound ConversationContextPack
- Sync/deployment impact: local devUI only for the first slice
- External boundary impact: explicit external Codex/Claude handoff and configured Model Inquiry host
- New or changed contract: FocusView.v1, ConversationContextPack.v1,
  ConversationDisposition.v1, and TypedCommandProposal.v1
- Owner-doc impact: final acceptance reconciles `docs/DEVUI.md` current-state truth
- Transition debt impact: removes inferred session/work coupling and reduces owner reconstruction
- Fitness rule impact: adds hostile-correlation, freshness, exact-hash, no-store, and no-effect tests

## Constraints

- No child is ready before this specification merges and live readiness is reconciled.
- FCP-03 waits only for FCP-01. FCP-04 also waits for the separately authenticated action boundary
  in #4169 and destination-owned operation-key/readback support in the existing Model Inquiry
  artifacts. Neither nonvisual slice requires a design receipt.
- FCP-02 remains technically blocked until FCP-01/FCP-03/FCP-04 fixtures and the governed Yggdrasil
  design handoff are available. Later visual implementation is a separately derived slice.
- GitHub/repository delivery truth, workflow authority, and existing receipts remain external.
- No global provider session view, inferred correlation, transcript/task store, direct repository or
  GitHub mutation, or Builder System Control implementation.

## Acceptance Criteria

- [ ] Every child has a terminal delivery receipt or explicit superseding disposition.
  - Verify: runtime receipt: devui-focus-conversation-child-ledger.v1
- [ ] Every FCP invariant has focused, hostile-input, and cross-field-invariant evidence.
  - Verify: `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Cross-Task Invariants / Interaction Safety`.
- [ ] The accepted design handoff covers all required layout, accessibility, degraded, correlation,
      freshness, preview, and receipt states.
  - Verify: runtime receipt: yggdrasil-design-handoff.v1
- [ ] Authenticated Start/Hold and destination operation-key replay are proven against the existing
      artifact-first flow without any forbidden effect, unauthenticated launch, duplicate launch,
      or ambiguous retry.
  - Verify: runtime receipt: devui-start-model-inquiry-validation.v1
- [ ] Builder System Control remains a separate contract/issue and no meta-governance source is
      mixed into Focus subject state.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py`.
- [ ] Current-state owner docs are promoted only after the full capability acceptance gate.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`.

## Out of Scope

- Builder System Control implementation.
- General DDO command/receipt flow, direct delivery initiation, or lifecycle controls.
- Embedded chat, transcript/session store, global session ingestion, or task management.
- Expansion beyond the existing single-operator local read audience.

## Suggested Validation

- Run every child Issue's named tests and attach its PR/merge receipt to the parent.
- Validate the governed handoff and live Model Inquiry receipt only at their owning acceptance stage.
- Run `pytest -q tests/architecture/test_devui_focus_boundaries.py` and the focused browser suite.
- Reconcile `docs/DEVUI.md` only after all capability receipts exist.

## Source Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/DEVUI.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`

## Applies learning (optional)

- PR #4689 advisory Builder System devUI execution audit.

## Implementation Tasks

| Task | Issue | Initial lifecycle | Dependency |
| --- | --- | --- | --- |
| FCP-01 — Compose Subject-Centred Focus | #4694 | blocked until spec merge | none |
| FCP-03 — Open External Conversation Port | #4696 | blocked until FCP-01 delivery | FCP-01 |
| FCP-04 — Start Model Inquiry from Exact Preview | #4697 | blocked | FCP-03, authenticated boundary #4169, and Model Inquiry operation-key/readback support |
| FCP-02 — Validate Focus and Conversation Design | #4695 | blocked on stable fixtures and handoff availability | FCP-01, FCP-03, and FCP-04 |

Live backlog and capability-validation state is maintained on
[#4693](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4693).
The separate Builder System Control specification is tracked by
[#4698](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4698), not as a child.

## Verification Path

Each child resolves every named test or receipt on its PR and posts a compact result to the parent.
The parent ledger binds child Issue, PR, exact merge SHA, CI, design/inquiry receipt where relevant,
and any remaining limitation.

## Validation / Acceptance Path

The parent remains open after child delivery while exact source-state fixtures, design/accessibility
receipts, external-port non-authority, command freshness, authenticated operation-key replay, ambiguous
recovery, and owner-doc truth are verified together.
