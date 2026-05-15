# Vault Action Layer / Agent Tool Authority

**Date:** 2026-05-14
**Status:** Design handoff · v1 · ready for review at crossing B
**Authority:** Visual + structural guidance — proposes a tool-authority taxonomy
**Owner-docs target:** `docs/CONCEPTS/VAULT_ACTION_LAYER_CONTRACT.md` (to be authored), `docs/INTERACTION_SURFACES_AND_AUTHORITY/`
**Linked issue:** #910 — Tool authority taxonomy
**Crossing target:** B

## What this is

Agents do not get raw filesystem powers. They get bounded, governed capabilities — named,
classified, gated, and receipted. This package designs the contract between Panel-style
agent instructions ("move this Inbox note to Workbench") and actual vault mutation.

It defines:

- a **9-step action pipeline** every vault mutation must pass through (intent → classify →
  bound → policy → guard → idempotency → execute → receipt → event),
- a **five-tier tool authority taxonomy** (read-only, proposal, bounded write,
  governance-bearing, forbidden),
- an explicit **Obsidian / MCP boundary** — adapter, not authority,
- a **concrete first action** designed end to end: `move_inbox_note_to_workbench`,
- **eight designed states**: allowed, denied (source), denied (destination), write-guard
  block, idempotent no-op, collision-resolved, success-with-receipt, receipt-inspection.

See `prototype.html` §02 for the pipeline diagram, §03 for the tier matrix, §04 for the
Obsidian/MCP boundary, §05 for the live action prototype, §06 for the state gallery.

## Influence

- **May influence:** tier names and ordering, pipeline-step naming, UI for action invocation
  and trace, receipt presentation, copy distinguishing refusal classes.
- **May not decide:** the registry contents, classifier semantics, policy / write-guard
  algorithms, idempotency key shape, collision-rule taxonomy, receipt schema.

## Files

- `prototype.html` — 11-section spec, 9-step pipeline, tier matrix, action prototype,
  8-state gallery.
- `design-notes.md`, `state-gallery.md`, `implementation-contracts.md`,
  `authority-boundaries.md`, `edge-states.md`, `open-questions.md`.

## Related

- Issue **#910** — the trigger.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` —
  the invariant the pipeline enforces.
- Sibling 2026-05-14 packages — this design depends on the
  Handoff Governance Pack's folder shape; receipts produced here are visible in the
  Runtime Proof Dashboard; promotion-to-action is the read-mode complement to
  Memory Candidate Review's promote-to-note.

## Disclaimers

- Design exploration is not architecture authority.
- Runtime truth lives in shipped code, tests, status docs, and validation receipts.
- This package proposes the taxonomy and the pipeline shape; promotion to an owner-doc is a
  separate decision.
- The gated-execution invariant is honored throughout.
