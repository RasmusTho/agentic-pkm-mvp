# Authority boundaries — Vault Action Layer

## This design is

- Visual + structural guidance for the agent tool authority surface.
- A proposal for the **5-tier taxonomy** and the **9-step pipeline**.
- A target-state interaction contract for the UI surface that renders action invocation
  and trace.

## This design is not

- Architecture authority. Authority lives in (to be authored)
  `docs/CONCEPTS/VAULT_ACTION_LAYER_CONTRACT.md` and the registry it points at.
- Runtime truth. Runtime truth lives in shipped code, tests, status docs, and validation
  receipts.
- A schema. The contract references fields the runtime exposes; it does not declare them.
- A claim about current runtime behavior.

## Invariants this design honors

- **Gated execution.** Every action passes the full 9-step pipeline. No step is optional.
- **Bounded actions, not raw primitives.** Tier 4 is empty. Agents act only through
  registry entries.
- **Adapter, not authority.** Obsidian and MCP may implement bounded actions; they may not
  bypass policy, write guard, idempotency, or receipts.
- **Refusal is first-class.** Every refusal produces a receipt with the refusing step
  named.
- **Authority separation.** Panel issues instructions; the classifier is server-side; the
  UI never re-classifies.

## What this design may suggest to owner-docs

- A new `VAULT_ACTION_LAYER_CONTRACT.md` owner-doc.
- A taxonomy entry in `INTERACTION_SURFACES_AND_AUTHORITY/`.
- Reference from `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` to the pipeline as the
  enforcement surface.

## What this design must not suggest

- Loosening the gated-execution invariant for any step.
- Tier-elevation at runtime.
- Obsidian or MCP as the primary mutation surface.
- Generic agent "tools" library decoupled from the registry.
