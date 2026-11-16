---
name: Validate Focus and Conversation Design
description: Produce the governed Yggdrasil visual and interaction handoff for Focus, external conversation, and exact command preview.
task_id: FCP-02
github_issue: 4695
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Information architecture and hard boundary"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-01, FCP-03, FCP-04]
depends_on: [COMPOSE_SUBJECT_CENTRED_FOCUS.md, OPEN_EXTERNAL_CONVERSATION_PORT.md, START_MODEL_INQUIRY_FROM_PREVIEW.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / medium plus governed Yggdrasil design handoff"
capability_rationale: "Design normalization is bounded but must preserve exact authority and degraded-state semantics."
---

# Validate Focus and Conversation Design

## Purpose

Turn the stable Focus, Conversation Port, and Model Inquiry fixtures into an accepted Yggdrasil
handoff before visual implementation.

## What This Task Does

- Uses the existing Yggdrasil tokens/components and the governed design-handoff chain.
- Designs the stable subject header, progressive Focus evidence, external Conversation Port, context
  pack preview, typed command preview, Start/Hold confirmation, receipt, and ambiguous result.
- Resolves how a source-owned unresolved owner question appears along **Cockpit → Focus detail →
  governed Command/Receipt** without becoming a devUI backlog item, authority claim, or autonomous
  decision.
- Proves that Builder System Control is a separate route/context, not a Focus tab or provider view.
- Covers desktop, narrow, 200% zoom, keyboard, screen-reader naming, many-at-once, stale, unavailable,
  unread, unsupported, unlinked, missing, measured-empty, refused, and ambiguous states.
- Normalizes the accepted handoff into a durable component/interaction specification and receipt.

## Concretely

The handoff shows one Issue/capability header from Focus through pack preview, external handoff,
command preview, Hold/Start, and receipt. A separate Builder System Control entry visibly changes
the header to system scope and restores the previous Focus subject on return.

An unresolved owner question is demonstrated only from an explicit named owner-authority category,
governing source reference, and subject correlation. The interaction routes from Cockpit attention
to Focus detail and then, only when admitted, to an exact command/receipt boundary. Missing or
unsupported question evidence is shown honestly; provider reasoning alone neither resolves the
question nor advances its source lifecycle.

## Why This Matters

The authority boundary is partly interaction design: an ambiguous or visually merged read/action
surface can cause the owner to mistake provider prose for an executable or completed workflow.

## Acceptance Criteria

- [ ] A governed handoff package and normalized specification preserve all FCP invariants and use the
      live Yggdrasil design system without introducing an unapproved component vocabulary.
  - Verify: runtime receipt: yggdrasil-design-handoff.v1
- [ ] Conversation is visibly external/provenance-only, and source links/read-only analysis are
      visually distinct from the authority-bearing Start action.
  - Verify: runtime receipt: focus-conversation-command-preview.v1
- [ ] The design distinguishes every required source state without color-only meaning or false
      empty/healthy presentation.
  - Verify: runtime receipt: focus-source-state-matrix.v1
- [ ] Keyboard, focus order, screen-reader names, narrow, and 200% zoom preserve subject identity,
      evidence order, preview scope, and Start/Hold parity.
  - Verify: runtime receipt: focus-accessibility.v1
- [ ] Builder System Control has a distinct system-scope header and navigation return path; no
      control-lens claims leak into the Focus subject.
  - Verify: runtime receipt: focus-builder-system-boundary.v1
- [ ] Unresolved owner questions preserve Cockpit → Focus detail → governed Command/Receipt and do
      not create a parallel backlog, authority source, or autonomous decision path.
  - Verify: runtime receipt: focus-owner-question-journey.v1

## How to Verify (Pre-Merge)

- Validate the handoff package and normalized spec through the governed Yggdrasil workflow.
- Walk every named scenario and source-state fixture against the FCP invariants.
- Record keyboard, narrow, 200% zoom, screen-reader naming, and degraded-state evidence.
- Run `git diff --check` on the normalized repository artifacts.

## Out of Scope

- Frontend or backend implementation.
- External-provider automation when the governed design environment is unavailable.
- Builder System Control content design beyond the boundary/navigation proof.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `companion-ui/prompts/claude-design/README.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `companion-ui/companion-app/colors_and_type.css`

## Related GitHub Issues

Filed as child [#4695](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4695). Its fixture and
live-system prerequisites were revalidated before the design handoff below; parent #4693 retains
capability and owner acceptance.


## Normalized interaction handoff

This is a design specification over FCP-01, FCP-03 and FCP-04 contracts, not an implementation,
operator activation, live owner question, external conversation, or owner acceptance. The
[versioned static prototype](https://claude.ai/design/p/63da80e9-6d43-47c1-b400-10f4b1cb4199?file=fcp-02-2026-11-07%2Fprototype.html)
is illustrative and makes no workflow or network effect. The selected FCP-04 proposal is historical
and expired; in-window Start/Hold examples are links between inert design states.

### Component and interaction contract

1. **Subject header and source detail.** One Issue or governed capability remains named through
   Focus, pack preview, command preview and receipt. Situation, meaning, next legal step, governing
   source, five evidence axes, source timestamps, limitations and explicit correlation appear in
   that order. Navigation is ephemeral and never creates a subject or durable session.
2. **Owner question.** Cockpit attention is rendered only with a named Human Exception category,
   governing source reference and explicit correlation to the subject. Focus exposes those source
   facts and the existing route. Missing, unread, stale, unsupported or unlinked evidence withdraws
   the attention claim. Provider prose cannot answer the source question or create a backlog item.
3. **Conversation context.** The pack preview states purpose, included/excluded data, source states,
   expiry and exact hash before opening an available external adapter. The provider's reasoning is
   provenance-only and visually separate from a typed command; unavailable/unsupported adapter
   states leave readable Focus intact and never cause an undisclosed fallback.
4. **Exact Start/Hold.** Preview the exact question/hash, subject and pack hash, source versions,
   expiry, destination and version, effects/non-effects, approval rule and expected receipt. Start
   is available only when the source-owned authenticated admission says so; changed/expired inputs
   or unavailable destination withdraw it. Hold causes no effect. Show both controls with
   equivalent keyboard order and readable names. No pause/stop capability is implied.
5. **Receipt and ambiguity.** Return the destination-owned inquiry ID, final state, terminal
   receipt ID and report to the same subject. Ambiguous result preserves recovery state and never
   silently relaunches. An external conversation or displayed receipt does not authorize a later
   Issue, repository change or owner acceptance.
6. **Separate Builder System Control.** Navigation replaces Focus identity with `builder_system`
   and its own sources; returning restores the prior subject, without joining claims, eligibility
   or correlations. This boundary sketch does not design or deliver BSC contents.

### Fixture and scenario evidence

The stable fixture sources are `tests/builderops/test_devui_focus.py` (#4694),
`tests/builderops/test_devui_conversation_port.py` and
`app/builderops/devui_conversation_port.py::conversation_port_design_fixtures` (#4696), and
`tests/builderops/test_devui_model_inquiry_command.py` and
`app/builderops/devui_model_inquiry_command.py::model_inquiry_design_fixtures` (#4697). Their
subjects differ: Issue #4694, Issue #4696 and the `model-inquiry` capability. The pictured
single-subject owner question is a synthetic adaptation with an explicit synthetic source reference
and subject correlation; it is not a claimed correlation among those fixtures. All 44 tests across
the three fixture modules passed against the delivery candidate.

| Fixture or required scenario | Design treatment and boundary |
| --- | --- |
| Focus ready/partial/blocked/unsupported | Named subject and source-specific claim/limitation; blocked or unsupported never implies empty or legal action. |
| Pack exact hash/no action | Purpose, scope, expiry and hash; no-action ends without durable effect. |
| Pack unavailable/unsupported/stale/unlinked | Focus remains usable where supported; affected claim and Start are withdrawn, no fallback or inferred link. |
| Inquiry exact preview/start/hold | Same subject, exact question/hash, pack/proposal hashes, source and approval bindings; historical in-window pair is inert. Hold invokes nothing. |
| Inquiry stale/terminal/ambiguous/workflow unavailable | Changed or expired disables Start; terminal requires destination readback; ambiguity preserves recovery and forbids automatic retry; unavailable forbids reservation. |
| Owner question / BSC | Explicit synthetic owner category, source and correlation; BSC has its own system header and returns to subject without joining authority. |
| Many at once / five axes | The state gallery labels 19 simultaneous examples. Availability, freshness, coverage, cardinality and linkage are distinct; `measured_empty` requires a bounded readable result and watermark. |

### Design evidence receipts

These observed design/browser executions are stored and read back as existing `BuilderOpsReceipt`
records with `event_type=design_validation`; each named `.v1` identity is the record’s `action`,
not a separately registered schema. Source references bind the prototype SHA-256. They do not
claim Product runtime, deployment or owner acceptance.

- **`yggdrasil-design-handoff.v1`** (`receipt_20261107193843_36373947`) — `mixed` scope; live **Yggdrasil Design System** ID
  `f2b13410-af14-4875-8029-445352123f57`, selected when creating the private project. Live and
  repository token sheet `companion-ui/companion-app/colors_and_type.css` version `2.2.1` matched
  SHA-256 `edbc81c77209b5274b26b5e827191f95595f20d6bc5a97a17f7dd8751a774ba2`; parity **pass**.
  The prototype uses the system token/preview grammar with external font imports removed and local
  fallback fonts; no new canonical token or component is asserted. Prototype readback etag
  `1794079810143724`, SHA-256
  `264c3b6646214a59af2932077a097af683ede3f71709d6c365a738a2f8983756`; package README readback
  etag `1794080474044065`, SHA-256
  `5a19ae24e962c0ba4db6cf80b7eb71649fa967542226d99b329dd9787515821d`.
- **`focus-conversation-command-preview.v1`** (`receipt_20261107193844_02a8187a`) — the pictured external pack, provider provenance
  and exact inquiry preview are distinct; historical expiry, source revalidation, explicit
  effects/non-effects and authenticated Start/Hold rule are visible. No provider or action runs.
- **`focus-source-state-matrix.v1`** (`receipt_20261107193844_6730490e`) — the 19 named gallery examples and mapping above cover the
  required availability, freshness, coverage, cardinality and correlation distinctions with words
  and consequences, including many-at-once; the design does not replace real source fixtures.
- **`focus-accessibility.v1`** (`receipt_20261107193845_49f86fb9`) — Chrome desktop
  1440×900 and iPad-width 820×1180 were visually inspected. The exact prototype was read back
  and its byte-identical local copy was opened in Chrome: the browser displayed **200%** zoom and
  was restored to **100%** afterward. At actual 200%, Focus subject and evidence order, preview
  scope and Start/Hold pair were inspected; Tab reached both controls, Hold returned focus to the
  same subject, and illustrative Start navigated to the same-subject receipt. The accessibility
  tree exposed main, named navigation and links; this is not a complete VoiceOver operation test.
  JavaScript-off fragment navigation worked, and no cross-origin request or script exception was
  observed. Eight PDF pages were inspected as a contact sheet; physical print and detailed
  individual-page typesetting were not tested.

  | Mode | Subject identity | Evidence order | Preview scope | Start/Hold parity |
  | --- | --- | --- | --- | --- |
  | Desktop 1440 CSS px | `Model Inquiry` | Why → evidence/limitations → next step | Question → destination → effects → approval | Both examples visible; expired Start withdrawn |
  | iPad 820 CSS px | Same subject | Same DOM order | Same four scope headings | Both example links visible |
  | Narrow 390 CSS px | Same subject | Same DOM order | Same four scope headings | Both example links visible |
  | 720 CSS px | Same subject | Same DOM order | Same four scope headings | Keyboard exercised both example links and return |
  | Actual Chrome 200% | Same subject in Focus and receipt | Accessibility tree preserves why → evidence → next step | Accessibility tree preserves question → destination → effects → approval | Tab reached Start then Hold; both inert destinations exercised |
  | Screen-reader naming | Subject, main and navigation exposed in AX tree | AX tree retains evidence sequence | Question and scope names exposed | Start/Hold have distinct link names; expired Start is textual unavailable |

  Document width equalled viewport width in the four CSS-width tests. The screen-reader row is
  accessibility-tree naming evidence, not a full assistive-technology usability test.
- **`focus-builder-system-boundary.v1`** (`receipt_20261107193845_ed81b446`) — keyboard navigation entered the `builder_system`
  section and returned focus to the prior named Focus section, with no shared source claim. This
  proves only the static fragment-navigation example.
- **`focus-owner-question-journey.v1`** (`receipt_20261107193845_6a3ae9fe`) — the synthetic Cockpit question declares an
  external-facing Human Exception category, synthetic source reference and explicit subject
  correlation; Focus explains the boundary and routes to the separate preview. No source decision
  was read, created, answered or advanced by the prototype.

BuilderOps `PromotionIntent` `prom_20261107192702_8eb733e0` stages this design-to-doc proposal;
the normal PR is the authority boundary. Parent #4693 retains end-to-end acceptance, and actual
operator activation, accessible implementation, live owner trial and owner acceptance remain
separate.
