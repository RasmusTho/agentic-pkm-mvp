State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Current policy-routing model for note kinds and state-axis enablement; complements but does not redefine the semantic Core-6 contract.
# Note Kind Policies

The `kind` field is a policy-routing signal for notes and objects. It does not define a schema.
Instead, it selects which state axes are enabled, locked, or ignored by policy.

Policies are defined via vault-as-GUI settings and compiled into runtime policy bundles.

Related docs:
- `docs/CORE_CONTRACT.md` for the semantic contract that remains stable across kinds
- `docs/SETTINGS.md` for policy compilation and runtime settings resolution
- `docs/FRONTMATTER.md` for metadata ownership on the warm surface
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current recommendation on separating
  `review_state`, `maturity`, `promotion`, and execution-plan terminology

## Policy model
- `kind` routes policy; it does not define structure or schema.
- State axes are orthogonal and selectively enabled by policy.
- Policies can lock or force axis values and gate agent read/write permissions.
- Derived overlays (e.g., `zone`, recency, salience) remain system-owned and never become core axes.

Axis interpretation:
- `review_state` should be read as review/mutation posture.
- `maturity` should be read as development/standing when enabled.
- `promotion` should be read as a transition family that may affect one or more axes, not as an axis
  in itself.

## Example policy profiles

### task
- Meaningful fields: status/lifecycle, priority, due_date, scheduled_at, checklist items.
- Agent reads: task state, dates, priority, provenance, review/trust guardrails.
- Agent writes: status, priority, dates, checklist items when explicitly authorized; must not
  alter reviewed content without explicit intent.
- Locked/forced: origin=vault; review_state defaults to `draft` until explicitly reviewed.

### knowledge
- Meaningful fields: maturity (e.g. draft/developing/stable/evergreen), salience, trust, review_state.
- Agent reads: body, relations, maturity, salience signals, trust/review gates.
- Agent writes: proposals, summaries, links; edits require explicit intent when reviewed.
- Locked/forced: origin=vault; review_state gates mutation of reviewed content.

Normalization note:
- prefer `review_state` for review posture,
- prefer `maturity` for knowledge-development standing,
- avoid using `review_state` as the only durable sink for `evergreen`-like outcomes.

### reference
- Meaningful fields: provenance, citations, trust, optional freshness markers.
- Agent reads: source metadata, citations, trust/review gates.
- Agent writes: citations, summaries, source metadata; avoid rewriting reviewed excerpts
  without explicit intent.
- Locked/forced: origin=external unless explicitly captured from the vault.

Normalization note:
- external/raw intake states belong to intake/review policy, not to the same semantic bucket as
  maturity outcomes such as `evergreen`.

### log
- Meaningful fields: timestamped entries, append-only integrity, optional trust/review gates.
- Agent reads: chronological entries, provenance, review/trust guards.
- Agent writes: append entries and metadata; never rewrite prior entries without explicit intent.
- Locked/forced: origin=vault; review_state may be locked to `logged` or `reviewed`.

Clarification:
- logs and mirror artifacts may share policy concerns,
- but a log policy profile does not by itself define the receipt model for the whole system.

## Policy ownership
Policies are configured in vault settings (vault-as-GUI) and are the authoritative source for
which axes are enabled, locked, or ignored for a given `kind`.
