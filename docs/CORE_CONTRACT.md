State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Canonical semantic contract for the minimal identity + provenance projection carried across the human/runtime boundary; neighboring docs may extend policy or persistence detail but must not redefine Core-6.
# Core Contract (Core-6)

Core-6 is the minimal, stable semantic projection that a human-facing artifact or ingestable artifact
must be able to carry across the human/runtime boundary for reasoning, trust separation, and
idempotent automation. It is a contract of meaning, not a YAML schema requirement.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` for the human-first ontology that distinguishes actors, artifacts, commitments, operations, roles, states, and receipts
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` for the normalized vocabulary around `note`, `object`, `source`, `agent`, `review`, and related overloaded terms
- `docs/DATA_MODEL.md` for how Core-6 is mirrored in persistence surfaces
- `docs/NOTE_KIND_POLICIES.md` for policy-selected state axes outside Core-6
- `docs/FRONTMATTER.md` for warm-surface metadata ownership and write constraints

## Purpose
- Define the smallest stable identity + provenance surface that can be shared between:
  - the human-facing artifact layer, and
  - runtime/storage projections of those artifacts.
- Keep guardrails (trust, review) separate from mutable state axes.
- Ensure deterministic automation even when metadata is implicit.

## Scope

Core-6 does not define the full ontology of the system.

It is intentionally narrower than:
- the full cognitive ontology in `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`,
- the full human flow model in `docs/HUMAN-FLOWS.md`,
- any persistence or event schema.

Core-6 is best understood as the smallest portable projection needed when an artifact crosses into
system reasoning, storage, retrieval, or automation.

In particular:
- it does **not** define all artifact types,
- it does **not** define commitment structures,
- it does **not** define all states, roles, or transitions,
- it does **not** make runtime storage language canonical for the domain.

## Core-6 fields (canonical)
| Field | Purpose | Ownership | Implicit/derived? |
| --- | --- | --- | --- |
| `uuid` | Stable artifact identity across notes, stores, and mirrors. | System-owned. | May be derived (e.g., generated on ingest) and projected into notes. |
| `title` | Human-facing label for the artifact. | Human-owned. | May be derived (e.g., filename) when unambiguous. |
| `origin` | Provenance source (vault, external, capture pipeline). | System-owned. | Derived from ingest context and source plane. |
| `source_ref` | Stable locator (vault path, external URI, or system handle). | System-owned. | Derived from the storage handle or vault path. |
| `trust` | Guardrail level constraining how the artifact may inform suggestions, assertions, or durable changes. | System-owned (human-authorized changes). | Derived from policy, provenance, or review actions. |
| `review_state` | Review gate protecting reviewed artifacts from mutation. | System-owned (human-authorized changes). | Derived from review actions or policy defaults. |

## Human-first interpretation

Core-6 must be interpreted through the human-first ontology:
- a `Vault Note` is a warm-surface human artifact,
- a runtime/store row is a projection or mirror,
- a source artifact is often a role played by an artifact in context,
- review and promotion are transitions/processes, not base entity types.

Core-6 therefore does not say that every domain thing is an `object`.
It says that when an artifact must cross from the human surface into runtime reasoning or storage,
these six semantic coordinates must remain stable.

## Contract rules
- Core-6 is a semantic contract, not a literal YAML requirement.
- Absence of YAML does not imply absence of semantics; Core-6 may be implicit or derived.
- Warm human-facing notes remain the primary human contract surface for vault-based work; they express intent and meaning.
- External/cold artifacts may also project Core-6 without becoming vault notes.
- The DB/system plane is a normalized mirror or projection of the contract, not the source of truth for human meaning.
- Policy-selected axes may extend the artifact view, but they do not become part of Core-6 unless this document changes.
- Runtime/storage terms such as `object`, `store_objects`, or payload-specific shapes may represent Core-6, but they do not define its meaning.

## Not Core-6
The following are explicitly outside the Core-6 contract:
- `zone` (derived overlay).
- Temporal fields (dates, schedules, recency signals).
- Priority / impact.
- Maturity and salience.
- Note kind policies (policy routing, not core semantics).
- Commitment structures such as project, next action, or review cycle.
- Receipts, plans, and other system artifacts used for coordination or accountability.
- Detailed relation models.
- Creative-state distinctions beyond the minimal identity/provenance projection.

## Stability
Core-6 must remain minimal and stable. Any change requires an explicit architecture update.
