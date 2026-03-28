State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Writing-surface metadata ownership and write contract for frontmatter; complements Core-6 and human-flow rules without redefining semantic or operational ownership.

# Frontmatter — the writing-surface write contract

## Purpose

Frontmatter exists to support a human writing workflow, not to turn notes into database rows.

This document defines:
- The minimal human-facing frontmatter philosophy.
- The write contract: what the system may write automatically, what requires confirmation, and what must never be auto-applied.
- Where receipts/cursors belong (writing-surface note vs system plane) and why.

See also:
- `docs/CONCEPTS/LAYERING_MODEL.md` (Domain/Plane/Trust/Zone)
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (ASSERT/SUGGEST/APPLY + evidence/receipts)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (canonical `review_state` / `maturity` semantics)
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` (canonical mirror vs receipt separation)
- `docs/CORE_CONTRACT.md` (Core-6 semantic contract)
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` (companion note continuity/repair contract)
- `docs/HUMAN-FLOWS.md` (human-facing behavior constraints for note mutation)
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md` (artifact surfaces, authority matrix, healing order)
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` (current normalization recommendation for
  `review_state`, `maturity`, `promotion`, and mirror/receipt boundaries)

## Metadata layers

Frontmatter may contain multiple layers of metadata, each with distinct ownership and intent:

- Core Contract fields: the Core-6 contract (uuid, title, origin, source_ref, trust, review_state).
- State fields: policy-selected axes (e.g., status, maturity, priority, temporal fields) enabled by note kind policies.
- Derived / overlay fields: system-computed overlays (e.g., zone, recency, salience) that should remain system-owned.

Not all semantics must be explicit in YAML. Core-6 fields may be implicit or derived when unambiguous.

Normalization note:
- `review_state` is the review/mutation-posture axis.
- `maturity` is the development/standing axis when enabled by policy.
- `promotion` is a transition family and should not be reduced to a single frontmatter field even
  when the current runtime temporarily writes through `review_state`.
- legacy values such as `review_state: evergreen` remain compatibility cases, not preferred writes.

## Minimal human-facing philosophy

- Frontmatter is small: prefer a few stable fields over a sprawling schema.
- Meaning stays in prose: the note body remains the primary place the human expresses intent and nuance.
- Metadata is assistive: metadata improves retrieval, curation, and navigation, but must not become a second, competing authoring surface.

## Ownership: human vs system

Exact field names are intentionally not locked here; the ownership and write rules are what must remain stable.

### Human-owned (default)
The human owns fields that express meaning and intent, such as:
- Titles/names, summaries, tags, links/relations, and domain classification.
- Any explicit statements of truth, judgments, or commitments.

The system may propose changes to these (SUGGEST), but must not silently overwrite them.

### System-owned (bounded)
The system may maintain small, bounded metadata needed for safety and stability, such as:
- A stable identity handle (`uuid`) which must live in the file and is PKA-owned rather than
  Obsidian-owned.
- Companion-note and identity-healing reuse SHOULD consider normalized titles/aliases as
  Obsidian-facing continuity signals, but title is not by itself a sufficient global identity rule.
- `source_ref` as a vault-relative path continuity field when present, with the explicit limitation
  that it is mutable and secondary to stable identity records.
- Guardrails like trust/review_state and derived overlays (zone/recency/salience).
- Policy-selected state markers only when authorized via APPLY.

System-written fields must be:
- Easy to distinguish from human prose/meaning.
- Backed by receipts (what wrote it, why, and under what intent).
- Safe to ignore without losing meaning.

For active writing-surface notes, frontmatter should remain a bounded human-facing surface.
It should not become the only durable home for:
- execution traces,
- orchestration plans,
- low-level event receipts,
- or machine-only projections.

## The write contract (automatic vs confirmed vs never)

Frontmatter writes must follow the trust semantics:

### May be automatic
- Non-semantic, stability-supporting fields (e.g., ensuring or healing a stable `uuid`) when
  missing or lost.
- Only when the write does not change the human’s meaning and does not cross boundaries.

Healing-write clarification:
- `uuid` healing writes must go through `KnowledgePort`.
- Healing is scenario-bound and should follow the artifact-model authority matrix rather than an
  unconditional "frontmatter wins" rule.

### Requires explicit confirmation
- Any write that changes meaning-bearing classification (domain, durable taxonomy, claims) or any durable workflow decision.
- Any write that is triggered by cross-domain or cross-plane use (materializing retained content into a writing-surface note).
- Any write that changes `maturity`, standing, or other durable artifact role unless an explicit
  policy allows automatic execution for that artifact class.

### Must never be auto-applied
- Destructive or irreversible changes.
- Silent boundary crossings (e.g., pulling retained external material into a writing-surface note without explicit intent).
- Upgrading low-provenance content into confirmed truth without explicit review.

## Receipts and cursors (where they live)

Receipts and cursors are operational artifacts:
- They belong primarily in the system plane, so they remain available and auditable without polluting the writing surface.
- They may be mirrored into the writing-surface note only as a bounded, clearly non-authoritative status surface (for human convenience).

Companion note / receipt clarification:
- the companion note is the first-class system artifact for note continuity and repair,
- broader mirror language still applies to portability/projection concepts in some legacy docs,
- and neither companion notes nor mirror artifacts should be treated as identical to the full
  receipt model; see `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.

If a note displays status/receipts, it must remain clear that:
- The note body is still the human’s writing.
- Status/receipts are a reversible, inspectable overlay.
