# Implementation contract — Vault Action Layer

**Status:** Contract for UI integration · target-state
**Mutates:** nothing on its own
**Depends on:** action registry (owner-doc to be authored), policy contract,
write-guard contract, receipt store contract, outbox contract.

## Pipeline

The full nine-step pipeline (intent → classify → bound → policy → guard → idempotency →
execute → receipt → event) is defined in **`prototype.html` §02**. Implementation must run
all nine steps in order. No step may be skipped; refusals do not skip subsequent receipt
production.

## Tier taxonomy

Five tiers, defined in **`prototype.html` §03**. Tier is fixed at action registration; the
runtime does not re-tier at invoke time. Tier 4 is intentionally empty; expanding it
requires explicit per-agent policy.

## Action object & trace entry

See **`prototype.html` §08** for the target-state shape. Field names are illustrative;
owner-doc owns the schema.

## Data attributes

```html
<section
  data-testid="action-stage"
  data-action-id="va-..."
  data-action-name="<registry name>"
  data-tier="0 | 1 | 2 | 3"
  data-outcome="applied | denied | blocked | noop | resolved | error"
  data-step="<1..9>">
```

Per-trace-line:

```html
<div
  data-testid="trace-line"
  data-step="<1..9>"
  data-result="pass | refuse | noop | resolved | error">
```

## Intents

See **`prototype.html` §08** for the canonical intent table. Adding new intents requires
amendment to this document.

## Validation expectations

A passing receipt for this package would:

- Run all eight state fixtures through the pipeline.
- Confirm every refusal produces a receipt at the refusing step.
- Confirm the Obsidian adapter path executes the full pipeline.
- Confirm the MCP-exposed surface offers only registry actions.
- Confirm the receipt is durable and referenced from the status doc.

## What this contract does not say

- Which Obsidian / MCP library to use.
- How the classifier model is trained.
- How idempotency keys are computed (just that they exist and are deterministic).
- How the deterministic collision rule is implemented per action.
