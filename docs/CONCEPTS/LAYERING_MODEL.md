State: Concept contract (Domain/Plane/Trust/Zone; implementation-agnostic).

# Layering Model — Domain / Plane / Trust / Zone

This document defines the canonical boundary model for the system. The four dimensions below are orthogonal: do not collapse them into one label, and do not use one dimension as a proxy for another.

## The Four Dimensions (orthogonal)

**Domain** — A human context boundary (e.g., work, private, creative). Domain is the primary scope for retrieval, suggestions, and actions. Domain separation exists to prevent accidental mixing and to keep intent clear.

**Plane** — Where an artifact lives and how it is exposed. Planes constrain what is shown or modified by default:
- **Warm plane**: the human-facing, editable writing surface.
- **Cold plane**: the “archive brain” of immutable or source-like objects (media, documents, project artifacts) that should be searchable/citable without being forced into the writing surface.
- **System plane**: operational/configuration/audit artifacts that support the system but are not user knowledge by default.

**Trust** — A provenance-based constraint on how information may be used. Trust governs what can be asserted as fact, what can only be suggested, and what requires explicit human confirmation before it changes durable user-facing artifacts.

**Zone** — A derived salience projection (e.g., active vs warm vs cold attention). Zones influence ranking and attention, not access control. Zone should be derived from signals where possible; manual tagging is optional and never required to keep the system usable.

## Contract Rules (must hold)

1) **Domain is the primary boundary.** Default retrieval and actions are scoped to the active domain.
2) **Cross-domain access requires explicit intent.** If content from another domain is accessed, the system must make that boundary crossing visible and auditable.
3) **Plane constrains exposure.** The warm plane is the default surface for reading/writing; the cold plane is the default surface for source retrieval and citation; the system plane is not treated as knowledge unless explicitly requested.
4) **Plane changes do not redefine meaning.** Moving or duplicating material between warm/cold/system planes must not implicitly change its domain or trust.
5) **Trust constrains claims and edits.** Lower-trust material may inform suggestions, but higher-impact claims and durable edits require adequate evidence and (when appropriate) explicit human confirmation.
6) **Zone is derived, not a gate.** Zone affects prioritization, not permission; it must never override domain, plane, or trust boundaries.
7) **The stricter boundary wins.** When dimensions conflict or are unknown, default behavior must be conservative: avoid boundary crossings and prefer showing sources over making assertions.
8) **Every boundary crossing is explainable.** The human should be able to answer: “what crossed, from where to where, why, and under what constraints?”

## Cross-domain Bridges (concept)

A **cross-domain bridge** is an explicit, auditable permission to reference a bounded subset of material across domains without collapsing them into one mixed space. Bridges are the only acceptable mechanism for persistent, repeated cross-domain exposure.

A bridge must record, at minimum:
- Origin domain and target domain(s).
- Purpose and scope (what is allowed to cross, and what is not).
- References to the specific source artifacts being bridged (so provenance remains intact).
- Trust constraints (how the bridged material may be used: cite vs suggest vs apply).
- Who authorized the bridge (human vs automation acting under explicit human intent) and when.
- Revocation semantics (a bridge can be removed without changing the source artifacts).
