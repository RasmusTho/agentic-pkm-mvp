State: Concept contract (Domain/Plane/Trust/Zone; implementation-agnostic).

# Layering Model — Domain / Plane / Trust / Zone

## Purpose

This document defines the canonical boundary model for the system.

The four dimensions below are **orthogonal**: do not collapse them into one label, and do not use one dimension as a proxy for another.

Terminology note:
- older docs sometimes say `warm` / `cold`,
- and this document currently uses `writing plane` and `retention plane` as repo working terms,
- because this boundary is about cognitive function and exposure, not storage temperature or access frequency,
- but the literature does not yet justify treating those labels as final field-standard terminology; see
  `docs/research/cognitive-semantics-literature-memo.md`.
- likewise, the current `domain` term in this document should be read as a stricter scope/boundary
  concept, not necessarily as the full human semantics of belonging; see
  `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`.
- and the current `bridge` term should be read as a narrower runtime/policy mechanism for
  persistent cross-scope permission, not as the primary ontology of human overlap.

## The four dimensions (orthogonal)

**Domain** — A current operational scope/boundary for retrieval, suggestions, and actions (e.g.,
work, private, rpg). In broader human terms, lived belonging may be better modeled through
overlapping spheres and situated contexts; this document uses `domain` only for the stricter scoped
boundary layer.

**Plane** — Where an artifact lives and how it is exposed. The plane language below is current repo
working language, not a claim that the final literature-backed semantic labels are already settled.
Planes constrain what is shown or modified by default:
- **Writing plane**: the human-facing, editable writing surface.
- **Retention plane**: the retained-material surface of source-like or reference-bearing artifacts that should remain available for rediscovery, citation, inspection, and later reuse without being forced into the writing surface.
- **System plane**: operational/configuration/audit artifacts that support the system but are not user knowledge by default.

**Trust** — A provenance-based constraint on how information may be used. Trust governs what can be asserted as fact, what can only be suggested, and what requires explicit human confirmation before it changes durable user-facing artifacts.

**Zone** — A derived salience projection (e.g., foreground vs background attention). Zones influence ranking and attention, not access control. Zone should be derived from signals where possible; manual tagging is optional and never required to keep the system usable.

## Contract rules (must hold)

1) **Domain is the primary boundary.** Default retrieval and actions are scoped to the active domain.
2) **Cross-domain access requires explicit intent.** If content from another domain is accessed, the system must make that boundary crossing visible and auditable. Repeated or common cross-domain overlap is legitimate. At the human layer it may simply reflect shared participation; when runtime needs a durable permission structure, that crossing still requires explicit bounded authorization rather than implicit mixing.
3) **Plane constrains exposure.** The writing plane is the default surface for reading/writing; the retention plane is the default surface for source retrieval and citation; the system plane is not treated as knowledge unless explicitly requested.
4) **Plane changes do not redefine meaning.** Moving or duplicating material between writing/retention/system planes must not implicitly change its domain or trust.
5) **Trust constrains claims and edits.** Lower-trust material may inform suggestions, but higher-impact claims and durable edits require adequate evidence and (when appropriate) explicit human confirmation.
6) **Zone is derived, not a gate.** Zone affects prioritization, not permission; it must never override domain, plane, or trust boundaries.
7) **The stricter boundary wins.** When dimensions conflict or are unknown, default behavior must be conservative: avoid boundary crossings and prefer showing sources over making assertions.
8) **Every boundary crossing is explainable.** The human should be able to answer: “what crossed, from where to where, why, and under what constraints?”

## Default Scope Policy (Experiment)

This section is a **human-first policy experiment** intended to reduce friction while preserving domain separation. It is non-binding: we will validate the UX and safety posture before hardening it into a permanent rule.

Definitions:

- **Active Domain**: the current working context (e.g., `work`, `private`, `rpg`).
- **Global Evergreens**: a curated, explicit opt-in set of evergreen knowledge intended to be universally available across `work` and `private` contexts.
  - Global Evergreens are **not** “all private notes” (nor “everything”); they are a deliberate shared set.
  - Making something a Global Evergreen is itself an explicit boundary decision and must be auditable.
- **Default retrieval scope**: `Active Domain` + `Global Evergreens`.
- **Domain excludes**: additional safety filters applied to the default scope.
  - When `Active Domain = work`, exclude `rpg` by default.

Boundary posture:

- This experiment does **not** weaken Trust semantics: Trust still constrains whether material can be asserted, suggested, or applied.
- Global Evergreens are a standing cross-domain allowance (bridge-like in effect), but this
  document does not hard-commit how they are represented.

One-shot cross-domain include:

- A one-shot include may temporarily widen scope for a single operation.
- It requires explicit user intent, produces an audit receipt, does not create a persistent
  cross-domain allowance, and must not persistently widen default retrieval scope.
- See “Ephemeral cross-domain include (one-shot)” below.

## Cross-domain access modes

There are only two valid ways to access content across operational domains:

- **Ephemeral cross-domain include (one-shot)** — a one-time, explicitly requested inclusion for the current operation.
- **Persistent cross-domain allowance (`bridge` in current repo language)** — an explicitly
  authorized, auditable permission for repeated/reusable cross-domain exposure.

Anything else (implicit mixing, background widening, accidental bleed-through) violates this contract.

These two modes are not meant to imply that cross-domain access should be rare.
People often have genuine recurring overlap between contexts.
The contract claim is narrower: these are runtime-policy mechanisms for crossing operational scopes.
They are not the whole ontology of overlap.
At the broader human layer, overlap may already exist through shared participation across spheres or
contexts.

## Ephemeral cross-domain include (one-shot)

An ephemeral include is a deliberate one-time exception that allows referencing specific content
from another domain **without creating a persistent cross-domain allowance**.

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
- **No persistent cross-domain allowance is created implicitly.** If repeated cross-domain access is
  desired, the system must ask for (and record) an explicit allowance.

## Persistent cross-domain allowance (`bridge`)

A persistent cross-domain allowance is an explicit, auditable permission to reference a bounded
subset of material across domains **without collapsing them into one mixed space**. `Bridge` may
remain current repo working language for this narrower mechanism. These allowances are the only
acceptable mechanism for persistent, repeated cross-domain exposure at the operational-scope layer,
and they may be a normal part of the system when they reflect real overlap in the human's life.

### Required fields (minimal contract)

Such an allowance must record, at minimum:

- **Origin domain** and **target domain(s)**.
- **Purpose** (why the allowance exists).
- **Scope** (what may cross and what may not) expressed as a bounded allowlist; explicit denylists are allowed but do not replace an allowlist.
- **Permitted uses** (e.g., cite, summarize, suggest, apply) and **trust constraints** on those uses.
- **Authorization**: who authorized it (human vs automation acting under explicit human intent) and when.
- **Revocation semantics**: an allowance can be removed/disabled without changing the source
  artifacts.
- **Auditability**: the system must be able to produce a human-readable receipt for allowance
  creation, use, and revocation.

### Optional / recommended fields (extensions)

These fields are recommended to reduce long-term risk and friction but are not required by the
minimal contract:

- **Expiry / TTL** and renewal rules.
- **Review cadence** (e.g., periodic confirmation that the allowance is still desired).
- **Risk classification** (low/medium/high) and rationale.
- **Change history** for scope or permitted uses.
- **Emergency disable** notes (how to quickly pause the allowance).

## Missing or unknown domain

Some artifacts may be missing a domain (unclassified) or have an unknown domain.

Safe degradation rules:

- **Treat as unscoped/unknown by default.** Unclassified content must not be assumed to belong to the active domain.
- **Exclude from cross-domain mechanisms by default.** Unknown-domain content must not be pulled into cross-domain access (ephemeral includes or bridges) unless it is **explicitly** included.
- **Prefer classification over inference.** The system should suggest classifying the content into a domain (or confirming it is intentionally unscoped) before it becomes part of routine retrieval.
- **Conservative conflict handling.** If domain metadata is contradictory or ambiguous, the stricter boundary wins; prefer source citations and explicit user confirmation.
