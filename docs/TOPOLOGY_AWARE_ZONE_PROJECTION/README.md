---
name: Topology-Aware Zone Projection Specification
description: Specification directory for the delivered topology-aware cognitive-distance projection (#1473) grounded in the #1488 topology authority decision.
type: specification
authority: SoT for the TOPOLOGY_AWARE_ZONE_PROJECTION capability boundary and its bounded task breakdown
source_of_truth: docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md ("Runtime topology authority decision (#1488)"), docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md §4.1/§4.3
related_docs:
  - docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md
  - docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md
  - docs/HUMAN-FLOWS.md
---

State: Delivered capability source spec for Issue #1473. Backend/API envelope #1554 (PR #1558), UI signal surfacing #1555 (PR #1561), and owner-doc promotion PR #1567 are merged; the parent/validation hub #1473 is closed. This directory remains the local spec evidence for what shipped. GitHub remains the authoritative backlog and validation record.

# Topology-Aware Zone Projection

This directory records the delivered capability captured in Issue #1473 — *topology-aware cognitive-distance projection* — and the bounded implementation tasks that shipped it. The split became possible because Issue #1488 (PR #1527) landed the topology authority/runtime decision in owner docs, which prescribes exactly what any topology-derived `zone` field must carry.

## Why this is splittable now (and what stays deferred)

The #1488 decision (`docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` → "Runtime topology authority decision (#1488)") fixed three things:

1. **The current source is named.** Vault Browser reads are active-vault only. `zone` is frontmatter-preferred (`frontmatter.zone`), with the first vault-relative path segment as deterministic fallback. There is **no** configured topology registry, multi-vault selector, graph projection, or semantic-neighborhood source authoritative for browser reads today.
2. **The envelope is named.** Any topology-derived browser field must carry `source`, `authority_role`, `provenance`, and `degradation`, and must degrade visibly to the frontmatter/path posture when a source is missing, stale, or conflicting.
3. **The deferral boundary is named.** A genuinely *new* topology source (registry / graph / semantic neighborhood) stays deferred until a runtime topology authority exists.

So the buildable work is **not** "invent a new topology source." It is: make the *existing* `zone` projection self-describing under the #1488 envelope, then surface those signals in the UI. The new-source variant remains deferred and is explicitly out of scope for this directory.

These documents are not issue templates and do not replace the GitHub issues. Each task spec anchors the spec-level intent, constraints, and acceptance shape; the GitHub issue created from it remains the canonical, executable task contract per `AGENTS.md` — agents implement against the issue, including its labels, readiness state, and any updated acceptance criteria, using these specs as the source-doc anchor.

## Capability boundary

The shipped Vault Browser `zone` projection describes itself: where each artifact's zone came from, what authority role that source holds, the concrete provenance, and the degradation state when the preferred source is absent or malformed. The UI surfaces those signals so zone does not become hidden semantic authority. The capability does **not** add a new topology source, change the `zone` frontmatter schema, or introduce semantic/vector ranking.

## Tasks (reading + execution order)

1. **[ZONE_PROJECTION_ENVELOPE.md](ZONE_PROJECTION_ENVELOPE.md)** — backend/API. Delivered by #1554 / PR #1558. Wraps the existing frontmatter-preferred/path-derived `zone` in the #1488 `source`/`authority_role`/`provenance`/`degradation` envelope in the Vault Browser API response.
2. **[SURFACE_ZONE_SIGNALS_IN_BROWSER_UI.md](SURFACE_ZONE_SIGNALS_IN_BROWSER_UI.md)** — Companion UI. Delivered by #1555 / PR #1561. Surfaces the zone source/authority/provenance/degradation in the Vault Browser UI.

Execution order (flat): `ZONE_PROJECTION_ENVELOPE -> SURFACE_ZONE_SIGNALS_IN_BROWSER_UI`.

## Parent / validation hub

The parent feature/validation hub was GitHub Issue #1473. Its local source lives at [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). #1473 closed after both children delivered and the owner-doc promotion in PR #1567 recorded the supported envelope posture.

## Acceptance criteria for the capability as a whole

- [x] The Vault Browser API returns, for every artifact `zone`, a `source` / `authority_role` / `provenance` / `degradation` envelope consistent with the #1488 decision. Verify: #1554 / PR #1558 backend tests asserted the envelope on frontmatter-zone, path-fallback, and malformed-frontmatter notes.
- [x] The Vault Browser UI surfaces the zone source/authority/degradation so a frontmatter-authored zone is visibly distinguishable from a path-derived fallback. Verify: #1555 / PR #1561 companion-ui tests asserted the rendered distinction.
- [x] No new topology source (registry/graph/semantic) is introduced; the `zone` frontmatter schema is unchanged; no semantic/vector ranking is added. Verify: #1554/#1555 diffs stayed additive to the existing frontmatter/path source.
- [x] Any zone-based ordering/overlay added surfaces its contributing signal and provenance. Verify: no new ordering was added by #1554/#1555.

Owner-doc promotion happened in PR #1567 after #1554/#1555 merged.

## Out of scope (still deferred)

- A configured topology registry, multi-vault selector, graph projection, or semantic/vector neighborhood source. These remain deferred per #1488 until a runtime topology authority exists.
- Changing the `zone` frontmatter schema or reclassifying artifact maturity/lifecycle/review state.
- Graph-primary browser UI.

## Navigation

- Topology authority decision: `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` ("Runtime topology authority decision (#1488)")
- Browser capability contract: `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` §4.1 (VaultArtifact / zone), §4.3 (VaultQuery / observable ranking)
- Runtime anchors: `app/api/routes/companion.py::_parse_note_artifact_metadata`, `::_zone_for_path`
