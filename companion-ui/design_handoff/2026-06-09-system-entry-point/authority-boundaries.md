# Authority boundaries — System Entry Point

## This design is

- **Visual / interaction guidance** for the entry point, the unified shell, and the system map, and for the way they compose the surfaces named in this package's README.
- **An interaction contract** limited to the state enum, transitions, `data-*` attributes, and intents enumerated in `implementation-contracts.md` and demonstrated in `prototype.html`.
- **A target-state proposal** until a normalized spec lands in `companion-ui/docs/`. The one exception: the entry point consumes the **shipped** read-only orientation contract (`WORKSPACE_ORIENTATION_CONTRACT.md`), and where this package describes that endpoint's *fields*, it cites that owner-doc.

## This design is not

- **Architecture authority.** Authority lives in the repo's owner-docs, specifically (referenced by name; treated as authoritative-but-external):
  - `docs/COMPANION_UI_PRODUCT_SPEC.md` — the Find / Reorient / Resurface / Act mode model.
  - `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/INTEGRATION_FABRIC_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md` — architecture spine.
  - `docs/INTERACTION_SURFACES_AND_AUTHORITY/` — Panel / Chat / Automation authority.
  - and the in-folder contracts: `WORKSPACE_ORIENTATION_CONTRACT.md`, `WORKSPACE_STATE_CONTRACT.md`, `COMPANION_UI_TARGET_ARCHITECTURE.md`, `UI_RUNTIME_BOUNDARIES.md`, `PANEL_COMPANION_UI_CONTRACT.md`, `CANVAS_SUGGESTION_FLOW.md`.
- **Runtime truth.** Runtime truth lives in shipped code, tests, `docs/STATUS.md`, and validation receipts. This package does not assert current shipped behavior except where it cites an in-folder owner-doc.
- **A schema.** It references fields (`leave_point`, `open_loops`, `mutation_intents`, `authority_role`, `source_ref`, …) the runtime exposes; it does not declare or modify them. Schema changes go through owner-doc PRs.
- **A new authority surface.** The entry point, shell, and system map are *renderers and routers*. None re-classifies runtime state, owns governance, or becomes a source of durable semantic truth.

## The boundary, restated

This boundary is absolute. A passage here that appears to contradict an owner-doc does **not** win — the owner-doc wins, and the passage is a proposal. Three specific cases are flagged in `design-notes.md §Conflicts` (palette, "don't build a shell yet", off-palette staging shell); in each the newer owner-doc / governance posture governs and this design defers.

## Invariants this design honors

- **Gated execution.** No surface mutates durable state outside the governed path: policy → validation → event pipeline → deterministic writer. In the prototype, `panel.confirm`, `vault.queue`, and `memory.accept` route through the pipeline (simulated with `console.log`); `suggestion.apply` uses the body-edit lane (`canvas_writer`, no receipt) per `CANVAS_SUGGESTION_FLOW.md`; nothing else writes.
- **Authority separation.** Chat is a canvas surface (margin rail), Panel is the command surface (palette), Automation is its own lane. The design keeps them visually and behaviorally distinct and never collapses them into one surface.
- **Server declares; UI renders.** Class, posture, trajectory state, governance counts, latest receipt outcome, and degraded posture are rendered as supplied. The UI never infers governance, memory authority, urgency, salience, or actionability locally.
- **Provenance visibility.** Every agent-contributed element shows source, trust state, and authority (`authority-tag`, provenance lines, the always-blue, always-labelled Hugin voice). Provenance is visible at interaction time, not only in a late audit surface.
- **Memory candidacy.** Orientation may emit a reference-only `mutation_intent`; promotion happens only through the governed memory review. "Unreviewed memory is not semantic authority" is stated on the surface.
- **Orientation is read-only.** The re-entry substrate surfaces and emits; it never applies. Cold (>14d) and runtime-unreachable states show no continuity claim they cannot back.
- **Low attentional load is a constraint.** A scarce displayed subset, counts over enumerations, no badges/urgency/notification escalation; resurfacing is why-now suggestion, never alerting.
- **Vault canonicality.** Obsidian is the system of record. The companion never reads or writes vault files directly; it is a client of the runtime API (`COMPANION_UI_TARGET_ARCHITECTURE.md`). Settings preferences are Local UI and byte-unchanged; capture and `queue_review` are the only writes, both governed.
- **Calendar and location are ungrounded.** The Context lane's time and place signals have no owner-doc source; they are proposals/placeholders and are labelled as such in the UI. They are read-only salience, never urgency, push, or task creation.

## What this design may suggest to owner-docs

Candidates for a normalized spec (owner-doc owners decide whether to accept any):
- An **entry-point / shell composition spec** capturing the state enum, transitions, and the document-anchor + overlay-layer + Chat + Panel composition.
- A **Settings / display-preference** surface spec confirming the local-state home and reset-to-canonical behavior (extends `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`).
- A **Capture → vault inbox** spec confirming the governed write path and the no-task-semantics guarantee.
- A **Context lane** spec (separately gated on Q15–Q16) defining agenda/location signals as `resurface.candidates` why-now inputs, never urgency.
- A reconciliation of the **palette discrepancy** between the design-system guide and `colors_and_type.css`.
- A note that the **second-UI-surface precondition** in `DESIGN_BRIEF.md` is now met, retiring the "do not extract a shell yet" guidance.
- Normalizing the **off-palette Panel staging shell** onto the canonical tokens.

## What this design must not suggest

- Any loosening of gated execution.
- Any new authority surface that bypasses the governed pipeline, or any write path that bypasses policy / validation / WriteGuard.
- Any collapse of Chat / Panel / Automation authority.
- Any silent promotion of agent memory into semantic knowledge.
- Any dashboard-style home, notification center, or urgency feed as the entry point.
- Any re-classification of runtime state by the UI.
