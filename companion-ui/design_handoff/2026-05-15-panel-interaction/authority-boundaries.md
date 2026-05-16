State: Handoff package governance doc — authority boundaries for the 2026-05-15 panel interaction design.

# Authority Boundaries — Panel Interaction Design

**Package:** `companion-ui/design_handoff/2026-05-15-panel-interaction/`
**Crossing status:** A

---

## What this design is

This package is a **design exploration** of how the Companion UI should render the Panel interaction surface — the vault-native AI panel fence (`%% AI:Start %% … %% AI:End %%`) — more richly for human interaction.

Specifically, this design is:

- **Visual guidance** — how states look, how components are laid out, which interaction gestures apply.
- **Intent vocabulary** — proposed confirmation actions, proposed provenance display, proposed keyboard shortcut extensions.
- **Vault/UI correspondence** — for each UI state, what the Markdown in Obsidian looks like at the same moment. This correspondence is the core design claim.
- **Component reuse/diverge decisions** — which canvas suggestion flow components apply and which need panel-specific variants.

---

## What this design is not

### Not architecture authority

Architecture authority lives in:
- `docs/PANEL_AGENT.md` — shipped runtime contract (v5.6 baseline)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md` — Panel authority boundary spec
- `docs/CAPABILITY_CONTRACT_MODEL.md` — capability contract shape
- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` — subsystem map and kernel constraints

If this design conflicts with those documents, **the owner docs win**. The design passage should be treated as a proposal, not a correction.

### Not runtime truth

Runtime truth lives in shipped code, tests, and `docs/STATUS.md`. Design states and proposed events are target-state; they are not claims about current behavior unless the relevant passage explicitly cites a shipped owner doc.

The shipped Panel runtime is described in `docs/PANEL_AGENT.md §PanelAgent Runtime V1` and `§PanelAgent 2.0`. Those sections are current truth; this design renders from them and proposes richer UI rendering on top of them.

### Not a schema or event declaration

This design references event types (e.g., "a proposals-written event would be needed"), field names, and API paths. References here are **design dependencies to be confirmed by runtime**, not declarations. Schema and event contract changes go through owner-doc PRs and the governed issue pipeline.

### Not a vault panel syntax change

The current vault-native AI panel syntax is the data contract:

```markdown
%% AI:Start %%
## AI-instruktion
<freeform human instruction>

## AI-åtgärder
- [ ] <human-visible confirmable proposal>

## AI-logg
<optional append-only log>
%% AI:End %%

> [!info]- AI status
> - ✅ executed receipt
> - ⚠️ no-match/warning
> - ⏳ pending
```

**This design does not replace this syntax.** It does not introduce HTML comment run blocks or any alternative envelope. The AI fence is a durable note-local communication envelope, not a closed action grammar. The Companion UI renders from this syntax; it does not own or replace it.

### On HTML comment run blocks

If an interactive prototype in this package (e.g., `index.html`) contains a block of the form:

```html
<!-- companion:panel:run ... -->
```

or similar, treat it **only as an internal prototype/rendering projection**, not as a proposed SoT runtime contract. No SoT decision has accepted such a syntax. If and when a runtime projection mechanism is proposed, it must go through the governed owner-doc PR lane with an explicit SoT decision.

---

## Invariants this package must honor

The following invariants apply to every interpretation of this design package and to any normalized spec derived from it. They are restatements of kernel constraints from the shipped architecture.

### Stable envelope, flexible protocol

The vault-native panel syntax (`%% AI:Start %%` / headings / AI status callout) is the stable communication envelope. The interaction protocol — how the Companion UI renders proposals, how confirmation flows, how receipts display — may evolve. The envelope does not change with the protocol.

### Panel surface is note-bound

The Panel surface in the Companion UI is rendered in relation to the active note, not as a standalone inbox or notification surface. A Panel widget appears when a panel fence is detected in the active document. There is no persistent Panel inbox across all notes.

### Companion UI does not own vault I/O

The Companion UI renders vault artifacts more richly and supports interaction. It writes back to the vault through the runtime API. It is a client of the FastAPI runtime; it does not own vault I/O directly. Writes made in the Companion UI must produce the same vault artifact as the equivalent action taken in Obsidian.

### Runtime owns: interpretation, policy, write guard, idempotency, execution, receipts, and inverse-action declaration

The runtime (PanelAgent, note writer, event pipeline) owns:
- Interpreting `AI-instruktion` into actions
- Policy evaluation and write guard enforcement
- Idempotency of action execution
- Execution of confirmed actions
- Writing receipts into the AI status callout
- Declaring inverse actions (undo paths)

The Companion UI renders outputs from the runtime and surfaces human confirmation affordances. It does not execute, classify, or evaluate policy locally.

### UI never reclassifies actions locally

The Companion UI renders action proposals and their provenance (catalog action ID, cognition mode) as declared by the runtime. It does not reclassify, upgrade, or downgrade actions locally. Classification authority lives in the action catalog and PanelAgent.

### Proposals are not execution

An unchecked proposal in `AI-åtgärder` is not an execution. A proposal row in the Companion UI is not an execution. Execution happens only after explicit human confirmation of a specific proposal, routed through the runtime.

### No same-turn execution of newly generated proposals

When PanelAgent generates proposals from `AI-instruktion` (PA2-FREEFORM path), those proposals are written as unchecked checkboxes into `AI-åtgärder`. They do not execute in the same run. Execution requires a subsequent explicit confirmation (check in Obsidian or confirm in Companion UI) followed by a new PanelAgent run.

### No-match and blocked are first-class visible states

When PanelAgent ran and found no catalog match (`no-match`), or when a write guard or policy prevented execution (`blocked`), these are first-class states that the Companion UI must render distinctly. They are not silence, not an empty proposal list, and not an error. The human must be able to read what happened and what to do next.

### Future capability expansion is additive, not a replacement

Future PanelAgent behavior may include: clarification states, plan-staging, partial completion, capability-needed states, and multi-step panel sessions. These are additive capabilities under the same envelope. This design should be extensible toward them without being redesigned for them now.

---

## Authority layer summary

| Layer | Authority | Lives in |
|---|---|---|
| This design package | Visual guidance, interaction intent | `companion-ui/design_handoff/2026-05-15-panel-interaction/` |
| Normalized spec | Mapped design intent → Yggdrasil architecture language | `companion-ui/docs/PANEL_INTERACTION_SPEC.md` (pending) |
| Architecture contract | Capability model, surface authority, event contracts | `docs/PANEL_AGENT.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, `docs/CAPABILITY_CONTRACT_MODEL.md` |
| Runtime truth | Shipped behavior, test coverage, validation receipts | Code + tests + `docs/STATUS.md` |
