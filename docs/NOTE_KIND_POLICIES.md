State: SoT v4.10 Reality-MVP (vNext policy model).
# Note Kind Policies (vNext)

The `kind` field is a policy-routing signal for notes and objects. It does not define a schema.
Instead, it selects which state axes are enabled, locked, or ignored by policy.

Policies are defined via vault-as-GUI settings and compiled into runtime policy bundles.

## Policy model
- `kind` routes policy; it does not define structure or schema.
- State axes are orthogonal and selectively enabled by policy.
- Policies can lock or force axis values and gate agent read/write permissions.
- Derived overlays (e.g., `zone`, recency, salience) remain system-owned and never become core axes.

## Example policy profiles

### task
- Meaningful fields: status/lifecycle, priority, due_date, scheduled_at, checklist items.
- Agent reads: task state, dates, priority, provenance, review/trust guardrails.
- Agent writes: status, priority, dates, checklist items when explicitly authorized; must not
  alter reviewed content without explicit intent.
- Locked/forced: origin=vault; review_state defaults to `draft` until explicitly reviewed.

### knowledge
- Meaningful fields: maturity (draft/reviewed/evergreen), salience, trust, review_state.
- Agent reads: body, relations, maturity, salience signals, trust/review gates.
- Agent writes: proposals, summaries, links; edits require explicit intent when reviewed.
- Locked/forced: origin=vault; review_state gates mutation of reviewed content.

### reference
- Meaningful fields: provenance, citations, trust, optional freshness markers.
- Agent reads: source metadata, citations, trust/review gates.
- Agent writes: citations, summaries, source metadata; avoid rewriting reviewed excerpts
  without explicit intent.
- Locked/forced: origin=external unless explicitly captured from the vault.

### log
- Meaningful fields: timestamped entries, append-only integrity, optional trust/review gates.
- Agent reads: chronological entries, provenance, review/trust guards.
- Agent writes: append entries and metadata; never rewrite prior entries without explicit intent.
- Locked/forced: origin=vault; review_state may be locked to `logged` or `reviewed`.

## Policy ownership
Policies are configured in vault settings (vault-as-GUI) and are the authoritative source for
which axes are enabled, locked, or ignored for a given `kind`.
