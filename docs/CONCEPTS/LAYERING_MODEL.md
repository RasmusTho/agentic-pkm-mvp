State: Concept contract (Domain/Plane/Trust/Zone; implementation-agnostic).

# Layering Model — Domain / Plane / Trust / Zone

## Purpose

This document defines the canonical boundary model for the system.

The four dimensions below are **orthogonal**: do not collapse them into one label, and do not use one dimension as a proxy for another.

## The four dimensions (orthogonal)

**Domain** — A human context boundary (e.g., work, private, creative). Domain is the primary scope for retrieval, suggestions, and actions. Domain separation exists to prevent accidental mixing and to keep intent clear.

**Plane** — Where an artifact lives and how it is exposed. Planes constrain what is shown or modified by default:
- **Warm plane**: the human-facing, editable writing surface.
- **Cold plane**: the “archive brain” of immutable or source-like objects (media, documents, project artifacts) that should be searchable/citable without being forced into the writing surface.
- **System plane**: operational/configuration/audit artifacts that support the system but are not user knowledge by default.

**Trust** — A provenance-based constraint on how information may be used. Trust governs what can be asserted as fact, what can only be suggested, and what requires explicit human confirmation before it changes durable user-facing artifacts.

**Zone** — A derived salience projection (e.g., active vs warm vs cold attention). Zones influence ranking and attention, not access control. Zone should be derived from signals where possible; manual tagging is optional and never required to keep the system usable.

## Contract rules (must hold)

1) **Domain is the primary boundary.** Default retrieval and actions are scoped to the active domain.
2) **Cross-domain access requires explicit intent.** If content from another domain is accessed, the system must make that boundary crossing visible and auditable.
3) **Plane constrains exposure.** The warm plane is the default surface for reading/writing; the cold plane is the default surface for source retrieval and citation; the system plane is not treated as knowledge unless explicitly requested.
4) **Plane changes do not redefine meaning.** Moving or duplicating material between warm/cold/system planes must not implicitly change its domain or trust.
5) **Trust constrains claims and edits.** Lower-trust material may inform suggestions, but higher-impact claims and durable edits require adequate evidence and (when appropriate) explicit human confirmation.
6) **Zone is derived, not a gate.** Zone affects prioritization, not permission; it must never override domain, plane, or trust boundaries.
7) **The stricter boundary wins.** When dimensions conflict or are unknown, default behavior must be conservative: avoid boundary crossings and prefer showing sources over making assertions.
8) **Every boundary crossing is explainable.** The human should be able to answer: “what crossed, from where to where, why, and under what constraints?”

## Cross-domain access modes

There are only two valid ways to access content across domains:

- **Ephemeral cross-domain include (one-shot)** — a one-time, explicitly requested inclusion for the current operation.
- **Cross-domain bridge (persistent)** — an explicitly authorized, auditable permission for repeated/reusable cross-domain exposure.

Anything else (implicit mixing, background widening, accidental bleed-through) violates this contract.

## Ephemeral cross-domain include (one-shot)

An ephemeral include is a deliberate one-time exception that allows referencing specific content from another domain **without creating a persistent bridge**.

Requirements:

- **Explicit user intent is required.** The user must clearly request the include (e.g., “include X from domain Y for this answer”).
- **The included set must be explicit.** The system must be able to enumerate what was included (specific artifacts or a clearly bounded subset).
- **A human-readable audit receipt is required.** The receipt must record, at minimum:
  - source domain(s) and target domain (the active domain),
  - what was included,
  - why it was included (the user request),
  - when it happened,
  - trust/usage constraints applied.
- **No persistent widening of default scope.** An ephemeral include must not:
  - change future default retrieval scope,
  - silently “remember” the inclusion as a standing permission,
  - imply that the domains are now mixed.
- **No bridge is created implicitly.** If repeated cross-domain access is desired, the system must ask for (and record) an explicit bridge.

## Cross-domain bridge (persistent)

A cross-domain bridge is an explicit, auditable permission to reference a bounded subset of material across domains **without collapsing them into one mixed space**. Bridges are the only acceptable mechanism for persistent, repeated cross-domain exposure.

### Required fields (minimal contract)

A bridge must record, at minimum:

- **Origin domain** and **target domain(s)**.
- **Purpose** (why the bridge exists).
- **Scope** (what may cross and what may not) expressed as a bounded allowlist; explicit denylists are allowed but do not replace an allowlist.
- **Permitted uses** (e.g., cite, summarize, suggest, apply) and **trust constraints** on those uses.
- **Authorization**: who authorized it (human vs automation acting under explicit human intent) and when.
- **Revocation semantics**: a bridge can be removed/disabled without changing the source artifacts.
- **Auditability**: the system must be able to produce a human-readable receipt for bridge creation, use, and revocation.

### Optional / recommended fields (extensions)

These fields are recommended to reduce long-term risk and friction but are not required by the minimal contract:

- **Expiry / TTL** and renewal rules.
- **Review cadence** (e.g., periodic confirmation that the bridge is still desired).
- **Risk classification** (low/medium/high) and rationale.
- **Change history** for scope or permitted uses.
- **Emergency disable** notes (how to quickly pause the bridge).

## Missing or unknown domain

Some artifacts may be missing a domain (unclassified) or have an unknown domain.

Safe degradation rules:

- **Treat as unscoped/unknown by default.** Unclassified content must not be assumed to belong to the active domain.
- **Exclude from cross-domain mechanisms by default.** Unknown-domain content must not be pulled into cross-domain access (ephemeral includes or bridges) unless it is **explicitly** included.
- **Prefer classification over inference.** The system should suggest classifying the content into a domain (or confirming it is intentionally unscoped) before it becomes part of routine retrieval.
- **Conservative conflict handling.** If domain metadata is contradictory or ambiguous, the stricter boundary wins; prefer source citations and explicit user confirmation.
