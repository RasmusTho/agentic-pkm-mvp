State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Canonical semantic contract for the minimal object/note identity and provenance surface; neighboring docs may extend policy or persistence detail but must not redefine Core-6.
# Core Contract (Core-6)

Core-6 is the minimal, stable semantic contract that every note or object must project for agent
reasoning, trust separation, and idempotent automation. It is a contract of meaning, not a YAML
schema requirement.

Related docs:
- `docs/DATA_MODEL.md` for how Core-6 is mirrored in persistence surfaces
- `docs/NOTE_KIND_POLICIES.md` for policy-selected state axes outside Core-6
- `docs/FRONTMATTER.md` for warm-surface metadata ownership and write constraints

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
- The DB/system plane is a normalized mirror of the contract, not the source of truth.
- Policy-selected axes may extend the object view, but they do not become part of Core-6 unless this document changes.

## Not Core-6
The following are explicitly outside the Core-6 contract:
- `zone` (derived overlay).
- Temporal fields (dates, schedules, recency signals).
- Priority / impact.
- Maturity and salience.
- Note kind policies (policy routing, not core semantics).

## Stability
Core-6 must remain minimal and stable. Any change requires an explicit architecture update.
