State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Warm-surface metadata ownership and write contract for frontmatter; complements Core-6 and human-flow rules without redefining semantic or operational ownership.

# Frontmatter — the warm-surface write contract

## Purpose

Frontmatter exists to support a human writing workflow, not to turn notes into database rows.

This document defines:
- The minimal human-facing frontmatter philosophy.
- The write contract: what the system may write automatically, what requires confirmation, and what must never be auto-applied.
- Where receipts/cursors belong (warm note vs system plane) and why.

See also:
- `docs/CONCEPTS/LAYERING_MODEL.md` (Domain/Plane/Trust/Zone)
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (ASSERT/SUGGEST/APPLY + evidence/receipts)
- `docs/CORE_CONTRACT.md` (Core-6 semantic contract)
- `docs/HUMAN-FLOWS.md` (human-facing behavior constraints for note mutation)
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
- A stable identity handle (e.g., uuid) when missing.
- VaultMirror fingerprint UUID reuse SHOULD also match normalized titles to avoid collisions on identical bodies.
- Guardrails like trust/review_state and derived overlays (zone/recency/salience).
- Policy-selected state markers only when authorized via APPLY.

System-written fields must be:
- Easy to distinguish from human prose/meaning.
- Backed by receipts (what wrote it, why, and under what intent).
- Safe to ignore without losing meaning.

For active warm notes, frontmatter should remain a bounded human-facing surface.
It should not become the only durable home for:
- execution traces,
- orchestration plans,
- low-level event receipts,
- or machine-only projections.

## The write contract (automatic vs confirmed vs never)

Frontmatter writes must follow the trust semantics:

### May be automatic
- Non-semantic, stability-supporting fields (e.g., ensuring a stable identity handle) when missing.
- Only when the write does not change the human’s meaning and does not cross boundaries.

### Requires explicit confirmation
- Any write that changes meaning-bearing classification (domain, durable taxonomy, claims) or any durable workflow decision.
- Any write that is triggered by cross-domain or cross-plane use (materializing archive content into a warm note).
- Any write that changes `maturity`, standing, or other durable artifact role unless an explicit
  policy allows automatic execution for that artifact class.

### Must never be auto-applied
- Destructive or irreversible changes.
- Silent boundary crossings (e.g., pulling external/cold material into a warm note without explicit intent).
- Upgrading low-provenance content into confirmed truth without explicit review.

## Receipts and cursors (where they live)

Receipts and cursors are operational artifacts:
- They belong primarily in the system plane, so they remain available and auditable without polluting the writing surface.
- They may be mirrored into the warm note only as a bounded, clearly non-authoritative status surface (for human convenience).

Mirror note / receipt clarification:
- the metadata mirror is a portable machine-side projection of a vault note,
- it may also surface receipt-like information,
- but it should not be treated as identical to the full receipt model unless a stricter contract
  says so.

If a note displays status/receipts, it must remain clear that:
- The note body is still the human’s writing.
- Status/receipts are a reversible, inspectable overlay.
