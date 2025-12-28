State: SoT v4.10 Reality-MVP (vNext contract).
# Core Contract (Core-6 vNext)

Core-6 is the minimal, stable semantic contract that every note or object must project for agent
reasoning, trust separation, and idempotent automation. It is a contract of meaning, not a YAML
schema requirement.

## Purpose
- Define the smallest stable identity + provenance surface for every object.
- Keep guardrails (trust, review) separate from mutable state axes.
- Ensure deterministic automation even when metadata is implicit.

## Core-6 fields (canonical)
| Field | Purpose | Ownership | Implicit/derived? |
| --- | --- | --- | --- |
| `uuid` | Stable object identity across stores and notes. | System-owned. | May be derived (e.g., generated on ingest) and projected into notes. |
| `title` | Human-facing label for the object. | Human-owned. | May be derived (e.g., filename) when unambiguous. |
| `origin` | Provenance source (vault, external, capture pipeline). | System-owned. | Derived from ingest context and source plane. |
| `source_ref` | Stable locator (vault path, external URI, or system handle). | System-owned. | Derived from the storage handle or vault path. |
| `trust` | Guardrail level for ownership and promotion decisions. | System-owned (human-authorized changes). | Derived from policy, provenance, or review actions. |
| `review_state` | Review gate protecting reviewed content from mutation. | System-owned (human-authorized changes). | Derived from review actions or policy defaults. |

## Contract rules
- Core-6 is a semantic contract, not a literal YAML requirement.
- Absence of YAML does not imply absence of semantics; Core-6 may be implicit or derived.
- Notes are the human contract surface; they express intent and meaning.
- DB/SetDB is a normalized mirror of the contract, not the source of truth.

## Not Core-6
The following are explicitly outside the Core-6 contract:
- `zone` (derived overlay).
- Temporal fields (dates, schedules, recency signals).
- Priority / impact.
- Maturity and salience.
- Note kind policies (policy routing, not core semantics).

## Stability
Core-6 must remain minimal and stable. Any change requires an explicit architecture update.
