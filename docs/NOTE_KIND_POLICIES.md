State: SoT v4.10 Reality-MVP (vNext policy model).
# Note Kind Policies (vNext)

A note may declare a `kind` field (e.g., `task`, `knowledge`, `reference`, `log`).
The `kind` does not define schema. It selects a policy profile that constrains which
state axes are active and what agents are allowed to read or write.

Policies are defined in vault settings (vault-as-GUI) and compiled into runtime policy
bundles. The policies are explicit and do not imply inheritance or hard-coded hierarchies.

## Policy model
- `kind` is a policy-routing field, not a state axis.
- State axes are orthogonal and enabled or constrained by policy.
- Policies can lock or force axis values, and gate agent read/write permissions.
- Derived overlays (like `zone`) remain system-owned and never become core axes.

## Example policies
### task
- Enabled axes: status/lifecycle, priority, temporal planning (due_date, scheduled_at).
- Locked/forced: origin=vault; review_state defaults to `draft` until explicitly reviewed.
- Agent permissions: may update status, priority, dates, and checklist items; may not
  rewrite reviewed content without explicit intent.

### knowledge
- Enabled axes: maturity (draft/reviewed/evergreen), salience (policy-scored), trust gates.
- Locked/forced: origin=vault; review_state gates any mutation of reviewed content.
- Agent permissions: may propose edits, summaries, or links; write actions require explicit
  intent when review_state is `reviewed` or higher.

### reference
- Enabled axes: trust, provenance, and citation tracking; optional temporal freshness.
- Locked/forced: origin=external unless explicitly captured from the vault.
- Agent permissions: may append citations, summaries, or source metadata; avoid rewriting
  reviewed excerpts without explicit intent.

### log
- Enabled axes: temporal ordering, append-only integrity, optional trust gates.
- Locked/forced: origin=vault; review_state may be locked to `logged` or `reviewed`.
- Agent permissions: may append entries and metadata; never rewrite prior entries without
  explicit intent.

## Future code touchpoints (descriptive)
- Frontmatter validation: ensure Core-6 projection plus policy-selected axes are coherent.
- Agent write guards: enforce review_state and policy permissions before mutating content.
- Settings compiler: compile vault policy definitions into runtime-readable bundles.
- Index projection: project Core-6 + active axes + policy overlays into retrieval indices.
