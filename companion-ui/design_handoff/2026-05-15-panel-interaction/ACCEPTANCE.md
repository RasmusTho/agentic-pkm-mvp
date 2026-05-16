State: Governance status record — accepts the 2026-05-15 Panel Interaction handoff package as Crossing-A design input, with explicit accept/defer classifications. Not architecture authority. Not runtime truth.

# Acceptance Record — Panel Interaction Design Handoff (2026-05-15)

**Package:** `companion-ui/design_handoff/2026-05-15-panel-interaction/`
**Acceptance date:** 2026-05-16
**Governing issue:** #994
**Parent hub:** #978
**Governance:** `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

---

## Governance status

- **Crossing status:** A (archived). Maturity checklist not yet passed; Crossing B requires human review of `open-questions.md` and confirmation that no Crossing-B-blocking items remain unresolved.
- **Authority status:** Visual guidance and design intent only. This package is not architecture authority and not runtime truth.
- **Owner-doc precedence:** Where this package and any `docs/**` owner doc disagree, the owner doc wins; the design passage is a proposal, not a correction.

This record formalizes acceptance of the package as a governed design-handoff input under the chain defined in `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`. It does not promote any design claim to architecture or runtime.

---

## Owner direction reaffirmed

- **Stable envelope, flexible protocol.** The vault-native AI panel syntax (`%% AI:Start %%` / `## AI-instruktion` / `## AI-åtgärder` / `## AI-logg` / AI status callout) is the durable note-local communication envelope. The Companion UI render protocol may evolve; the envelope does not change with it.
- **AI fence is a communication envelope, not a closed action grammar.** Restated by the package in `authority-boundaries.md §Not a vault panel syntax change` and `§Stable envelope, flexible protocol`.
- **Companion UI does not own vault I/O.** It is a client of the FastAPI runtime; writes route through runtime APIs and produce the same vault artifact as the equivalent Obsidian action.
- **No HTML-comment run block as SoT.** Any `<!-- companion:panel:run ... -->` block is **proposed / internal projection only**, never an accepted replacement for the AI-fence envelope. See `authority-boundaries.md §On HTML comment run blocks` and `open-questions.md §Q7` (Resolved — no internal projection mechanism via vault content mutations).

---

## Accepted (as design intent at Crossing A)

The following package contents are accepted as design-layer input. They are not promoted to architecture or runtime contract by this acceptance; they become authoritative only after Crossing B and a normalized spec PR.

- **Layered framing.** Vault-native data contract vs Companion UI render layer; the relationship between the two is the core design claim.
- **State enum (eight visible states).** `idle`, `running`, `proposals-staged`, `confirming`, `executing`, `receipt-displayed`, `no-match`, `blocked`. Future states (`clarifying`, `plan-staged`, `partial-complete`, `capability-needed`) noted for extensibility, not for current implementation.
- **Allowed transitions and forbidden transitions.** Including the explicit prohibition of `running → executing` and `proposals-staged → executing` (no same-turn execution of newly generated proposals).
- **Vault Markdown ↔ Companion UI correspondence.** The per-state side-by-side mapping is accepted as the design's core deliverable shape.
- **Component inventory direction.** New Panel-specific components (`PanelWidget`, `ProposalRow`, `PanelNoMatchState`, `PanelBlockedState`, `PanelRunningIndicator`, `PanelReceiptStrip`) and reuse-vs-diverge intent against the canvas suggestion flow vocabulary.
- **`no-match` and `blocked` as first-class states.** Not silence, not empty proposal lists, not generic errors.
- **Provenance visible at confirmation time.** Catalog action label + cognition mode badge always visible; deeper provenance on expand.
- **Note-bound Panel surface.** Panel widget appears in relation to the active note; no standalone Panel inbox.
- **Gated execution invariant.** Proposals are not execution; explicit, named, reversible confirmation; runtime owns interpretation, policy, write guard, idempotency, execution, receipts, and inverse-action declaration.
- **Authority-layer table** in `authority-boundaries.md` distinguishing design / normalized spec / architecture contract / runtime truth.

## Accepted as policy resolution

- **Q7 (HTML comment run block):** Resolved by policy — **no HTML-comment run block is accepted as a vault communication channel**. Any such block in a prototype is internal projection only. A reversal would require an explicit owner-doc PR.

---

## Deferred (Resolve-in-normalized-spec)

These items are accepted as triaged questions to be resolved when the normalized spec at `companion-ui/docs/PANEL_INTERACTION_SPEC.md` is authored after Crossing B. Proposed defaults are recorded in `open-questions.md` but are not adopted by this acceptance.

- **Q1** — Panel surface placement (inline with active note vs sidebar/overlay).
- **Q2** — Companion UI → vault confirmation write-back path (checkbox + re-run vs dedicated confirm endpoint). Primary normalized-spec deliverable.
- **Q3** — Panel run-state detection (polling vs SSE/WebSocket vs dedicated panel-state endpoint).
- **Q4** — Multi-panel notes presentation (list vs tabs vs single-active).
- **Q5** — Proposal provenance depth at-a-glance vs on expand.
- **Q6** — `no-match` / `blocked` vault representation and whether `panel.intent.executed` needs a `no_match_reason` / `block_reason` field. Runtime extension question.

## Deferred (Defer-to-implementation-issue)

- **Q8** — Confirmation idempotency on retry. Runtime owns idempotency; Companion UI surfaces errors and allows manual retry; this is resolved at implementation time.

---

## Not accepted

- Any reading of the package as architecture authority or runtime truth.
- Any HTML-comment run block as accepted SoT or replacement for the AI-fence envelope.
- Any modification of the current vault panel syntax or heading structure.
- A standalone Panel inbox surface decoupled from the active note.
- Bulk-accept / auto-accept affordances or same-turn auto-execution of generated proposals.
- Companion UI re-classifying actions locally or owning vault I/O directly.
- Schema or event declarations (e.g., `proposals-written`, `panel.confirm`). Those remain design dependencies to be resolved against `docs/PANEL_AGENT.md`, `docs/EVENTS.md`, and the runtime contract.

---

## Next steps (out of scope for this acceptance)

1. Complete the Claude Design session and add `prototype.html` to the package.
2. Human reviews `open-questions.md`; confirms triage; signs off Crossing B.
3. Author normalized spec at `companion-ui/docs/PANEL_INTERACTION_SPEC.md`.
4. Extract bounded GitHub implementation issues via `docs-to-issue`.

Runtime work continues under #978 and its children (#979, #980, #981, #982, #984). This acceptance does not unblock or replace any of that work.

---

## References

- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `companion-ui/docs/OVERLAY_GRAMMAR.md`
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`
- `docs/PANEL_AGENT.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/HUMAN-FLOWS.md`
- Issues: #977, #978, #981, #994
