# Design notes — Vault Action Layer

## Visual language

Inherits the shared Yggdrasil design system. Tier and outcome colours are deliberate:

- **Tier 0 (read-only)** uses **vault green** — safe, ambient, expected.
- **Tier 1 (proposal)** uses **cyan** — the same colour as receipts in flight; signals
  "queued for human".
- **Tier 2 (bounded write)** uses **amber** — staged-but-real, the active surface.
- **Tier 3 (governance-bearing)** uses **gold** — governance accent, matches Panel receipt vocabulary.
- **Tier 4 (forbidden)** uses **destructive red** — and the row is intentionally rendered as
  a non-action; it exists only to make the empty floor explicit.

The 9-step pipeline uses a band of soft borders rather than arrows. The visual contract is
"all nine steps run in order, every time". Arrows would imply some steps are skippable; the
contract is that they are not.

## Component vocabulary added by this package

- `.pipe` — the 9-step pipeline strip. Step variants colour-code by stage class
  (intent / classify / action / policy / guard / idempotency / execute / receipt / event).
- `.tier-table` — the five-tier matrix with colour-coded tier column.
- `.action-stage` — the live action sandbox: instruction (left) + resolved-action card +
  trace stream (right) + receipt strip (bottom).
- `.trace-line` (variants: `pass` `gate` `deny` `info` `idem`) — the per-step trace
  entries the operator audits.
- `.boundary` — two-column "allowed / not allowed" treatment for the Obsidian/MCP section.
  Vault green vs destructive red to make the boundary unambiguous.

## Why the action prototype is the way it is

- **Instruction is natural language; everything else is structured.** The panel prompt
  appears verbatim. From step 02 onward, the resolved-action card is mono — a structured
  record the operator can audit before the trace ever fires.
- **Trace is the receipt's narrative form.** Each `trace-line` corresponds 1:1 to a step
  of the pipeline. The receipt object is the durable form; the trace is the readable form
  of that same data.
- **Refusal is shape-equal to success.** A denied action's trace pane has the same number of
  lines as an allowed one, just with a refusal at the refusing step and the later steps
  absent. The operator does not have to read a different shape to learn what happened.

## Why Obsidian / MCP are deliberately not foregrounded

This is an aesthetic choice, not just a structural one. The vault action layer is a
contract; Obsidian and MCP are implementations. Rendering them as peer adapters in §04 —
behind the boundary, not in front of it — keeps the design from making any single
implementation look canonical.

## Out of scope

- Multi-action atomic transactions.
- Cross-vault actions (deferred to Tier 3 per §10).
- Action discovery / autocomplete UI in Panel.
- A "tools" library decoupled from the registry.
