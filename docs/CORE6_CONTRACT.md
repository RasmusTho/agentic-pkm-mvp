State: SoT v4.10 Reality-MVP (vNext contract).
# Core-6 Contract (vNext, compatibility alias)

This document is retained for backwards references. The canonical Core-6 contract lives in
`docs/CORE_CONTRACT.md` and should be treated as authoritative.

## Core-6 fields (canonical)
| Field | Purpose | Ownership | Implicit/derived? |
| --- | --- | --- | --- |
| `uuid` | Stable object identity across stores and notes. | System-owned. | May be derived (e.g., generated on ingest) and projected into notes. |
| `title` | Human-facing label for the object. | Human-owned. | May be derived (e.g., filename) when unambiguous. |
| `origin` | Provenance source (vault, external, capture pipeline). | System-owned. | Derived from ingest context and source plane. |
| `source_ref` | Stable locator (vault path, external URI, or system handle). | System-owned. | Derived from the storage handle or vault path. |
| `trust` | Guardrail level for ownership and promotion decisions. | System-owned (human-authorized changes). | Derived from policy, provenance, or review actions. |
| `review_state` | Review gate protecting reviewed content from mutation. | System-owned (human-authorized changes). | Derived from review actions or policy defaults. |

## Not Core-6
The following are explicitly outside the Core-6 contract:
- `zone` (derived overlay).
- Temporal fields (dates, schedules, recency signals).
- Priority / impact.
- Maturity and salience.
- Note kind policies (policy routing, not core semantics).
