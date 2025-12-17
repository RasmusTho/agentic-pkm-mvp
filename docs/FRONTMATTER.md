State: Kernel-adjacent (warm-surface metadata contract; implementation-agnostic).

# Frontmatter — the warm-surface write contract

## Purpose

Frontmatter exists to support a human writing workflow, not to turn notes into database rows.

This document defines:
- The **minimal human-facing frontmatter philosophy**.
- The **write contract**: what the system may write automatically, what requires confirmation, and what must never be auto-applied.
- Where **receipts/cursors** belong (warm note vs system plane) and why.

See also:
- `docs/CONCEPTS/LAYERING_MODEL.md` (Domain/Plane/Trust/Zone)
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (ASSERT/SUGGEST/APPLY + evidence/receipts)

## Minimal human-facing philosophy

- **Frontmatter is small**: prefer a few stable fields over a sprawling schema.
- **Meaning stays in prose**: the note body remains the primary place the human expresses intent and nuance.
- **Metadata is assistive**: metadata improves retrieval, curation, and navigation, but must not become a second, competing authoring surface.

## Ownership: human vs system

Exact field names are intentionally not locked here; the ownership rules are what must remain stable.

### Human-owned (default)
The human owns fields that express meaning and intent, such as:
- Titles/names, summaries, tags, links/relations, and domain classification.
- Any explicit statements of truth, judgments, or commitments.

The system may propose changes to these (SUGGEST), but must not silently overwrite them.

### System-owned (bounded)
The system may maintain small, bounded metadata needed for safety and stability, such as:
- A stable identity handle (e.g., an id/uuid) when missing.
- A minimal state marker that represents an explicit workflow decision (only when authorized via APPLY).

System-written fields must be:
- Easy to distinguish from human prose/meaning.
- Backed by receipts (what wrote it, why, and under what intent).
- Safe to ignore without losing meaning.

## The write contract (automatic vs confirmed vs never)

Frontmatter writes must follow the trust semantics:

### May be automatic
- Non-semantic, stability-supporting fields (e.g., ensuring a stable identity handle) when missing.
- Only when the write does not change the human’s meaning and does not cross boundaries.

### Requires explicit confirmation
- Any write that changes meaning-bearing classification (domain, durable taxonomy, claims) or any durable workflow decision.
- Any write that is triggered by cross-domain or cross-plane use (materializing archive content into a warm note).

### Must never be auto-applied
- Destructive or irreversible changes.
- Silent boundary crossings (e.g., pulling external/cold material into a warm note without explicit intent).
- Upgrading low-provenance content into “confirmed truth” without explicit review.

## Receipts and cursors (where they live)

Receipts and cursors are operational artifacts:
- They belong primarily in the **system plane**, so they remain available and auditable without polluting the writing surface.
- They may be *mirrored* into the warm note only as a bounded, clearly non-authoritative status surface (for human convenience).

If a note displays status/receipts, it must remain clear that:
- The note body is still the human’s writing.
- Status/receipts are a reversible, inspectable overlay.
