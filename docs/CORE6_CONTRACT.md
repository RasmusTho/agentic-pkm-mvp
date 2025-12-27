State: SoT v4.10 Reality-MVP (vNext contract).
# Core-6 Contract (vNext)

The Core-6 contract defines the minimal metadata projection required for agent reasoning,
trust separation, and idempotent automation. Core-6 is intentionally stable and minimal.

## Purpose
- Provide a canonical identity and provenance surface for every object.
- Separate trust and review guardrails from mutable state axes.
- Keep automation deterministic by grounding it in a tiny, durable contract.

## Core-6 fields
- `uuid` - Stable object identity.
- `title` - Human-readable label for the object.
- `origin` - Provenance source (e.g., vault, external, capture pipeline).
- `source_ref` - Stable locator for the object (vault path, external URI, or system handle).
- `trust` - Trust/ownership level used for guardrails and promotion gating.
- `review_state` - Review gate used to protect reviewed content from unintended mutation.

## Projection rules
- Core-6 is a semantic contract, not a literal YAML requirement.
- Fields may be implicit or derived (e.g., `title` from filename, `source_ref` from vault path,
  `origin` from ingest context).
- The projection exists to support agent reasoning, trust separation, and idempotent automation.

## Not Core-6
- `zone` is not Core-6. It is a system-owned derived overlay.
- Temporal fields, priority, maturity, and salience are not Core-6.
- `kind` is not Core-6. It is a policy-routing field used by Note Kind Policies.

## Stability
Core-6 must remain stable and minimal. Changes require an explicit architecture update.
