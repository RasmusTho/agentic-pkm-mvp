State: Kernel-adjacent (governance of persistence, boundaries, and audit; implementation-agnostic).

# Data Governance — canonical artifacts, boundaries, and audit

## Purpose

Data governance protects three invariants:
- **Durability**: the human’s knowledge survives upgrades, refactors, and rebuilds.
- **Safety**: domain and trust boundaries prevent accidental leakage and laundering.
- **Legibility**: the system can explain what happened, why, and what it used.

This document aligns with the kernel and the concept contracts:
- Layering model: `docs/CONCEPTS/LAYERING_MODEL.md`
- Trust semantics: `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- Archive exposure: `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- Event compatibility: `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`
- Config-as-product: `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`

## Canonical artifacts vs derived artifacts

**Canonical artifacts** are the durable sources of meaning:
- **Warm artifacts**: human-authored, editable notes (the writing surface).
- **Cold artifacts**: archived source material (documents/media/projects) that remain retrievable and citable without being forced into the writing surface.

Canonical artifacts must be portable, readable without the system, and carry stable identity + provenance.

**Derived artifacts** are rebuildable views:
- Indexes, embeddings, projections, caches, summaries, and other machine views.
- Operational traces, receipts, and audit records (durable for observability, but not the only copy of meaning).

Derived artifacts may be persisted for performance and auditability, but they must never become the only remaining copy of meaning.

## Boundary model (Domain / Plane / Trust / Zone)

All governance decisions are expressed through the orthogonal boundary dimensions:
- **Domain**: primary scope boundary (work/private/creative, etc.).
- **Plane**: where an artifact lives (warm writing surface, cold archive, system plane).
- **Trust**: provenance constraint on how information may be used.
- **Zone**: salience/ranking overlay (never a permission gate).

See `docs/CONCEPTS/LAYERING_MODEL.md` for canonical definitions and the cross-domain bridge concept.

## Trust semantics (ASSERT / SUGGEST / APPLY)

Trust governs *how* information may be used:
- **ASSERT**: what may be presented as true (requires stronger evidence and provenance).
- **SUGGEST**: what may be proposed (must remain clearly reversible and non-authoritative).
- **APPLY**: what may be changed/written/done (requires explicit intent + receipts).

See `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`.

## What is persisted where (conceptual)

This system has three persistence surfaces:

### Warm surface (human writing)
- Canonical, editable notes.
- Minimal, human-first metadata.
- No silent rewriting of meaning; durable changes require explicit APPLY intent.

### Cold surface (archive brain)
- Canonical source artifacts intended for retrieval and citation.
- Exposure is gated by domain + trust and follows the archive exposure modes (discover/cite/preview/materialize).

### System plane (operations + audit)
- Receipts, audits, traces, and other operational records that make the system legible.
- Rebuildable indexes and machine views.
- Configuration artifacts and their validation/audit receipts.

System-plane persistence must avoid polluting the warm writing surface while remaining inspectable and portable.

## Audit and receipts are first-class

Every meaningful use of trust, boundaries, or configuration must be auditable.

At a minimum, receipts must allow a human to reconstruct:
- What happened (ASSERT/SUGGEST/APPLY).
- What inputs/sources were used (with provenance and trust posture).
- What boundary context was in effect (domain/plane; any bridges).
- What changed (if anything) and how to reverse it.

Receipts are conceptually separate from the writing surface: they may be presented in the UI, but they must remain available even if UI affordances change.
