State: Audit report (point-in-time semantic drift and boundary audit; advisory, not normative).
Doc role: Reference (audit)
Authority: Advisory audit of semantic consistency across the repo as of 2026-05-29, performed as the closing step of epic #1363. It identifies terminology drift, authority ambiguity, runtime leakage, and projection/relation drift, ranks the risks, and recommends remediation and follow-on issues. It is subordinate to the semantic map and the per-layer contracts; it does not itself define authority.
Temporal class: snapshot
Review cadence: per-release
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/CONCEPTS/ARTIFACT_TERMINOLOGY_NORMALIZATION.md, docs/CONCEPTS/RELATION_TAXONOMY.md, docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md, docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md, docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md, companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md, docs/CONCEPTS/ONTOLOGY_VOCABULARY.md, docs/DOC_DIVERGENCE_AUDIT.md, epic #1363, issue #1372.

# Semantic Drift and Boundary Audit

This is the closing audit of epic #1363. It checks whether the repo's semantics are consistent after the alignment work (#1364–#1371) and identifies where drift remains or could recur. It is a point-in-time snapshot, advisory only; it does not change any contract.

Method: the audit reads both the new semantic contracts and the existing repo surfaces, and uses targeted grep evidence where useful. Findings are ranked by long-term semantic impact, with remediation and follow-on issue recommendations.

## Summary

The epic itself remediates the four largest drift classes by giving each an explicit owner contract:

- terminology drift → `docs/CONCEPTS/ARTIFACT_TERMINOLOGY_NORMALIZATION.md` (#1366)
- authority ambiguity → `docs/SEMANTIC_AUTHORITY_MATRIX.md` (#1365) + `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (#1370)
- runtime leakage → `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1369)
- projection / relation drift → `companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md` (#1368) + `docs/CONCEPTS/RELATION_TAXONOMY.md` (#1367)

The dominant **residual** risk is not conceptual but **enforcement**: the new contracts are target-state semantics, not runtime-enforced invariants. The repo can now *state* the boundaries clearly; it does not yet *test* that code respects them. The secondary residual risk is **lexical lag**: legacy terms (notably `VaultMirror`) still appear in active and historical docs after the concept they named was superseded.

## Audit areas

### A. Terminology drift — LOW (largely remediated)

- **Finding:** `artifact_class` / `artifact_type` / `artifact_kind` were the headline overlap (24 / 14 / 8 files at audit time). The audit confirms these are now on **distinct axes** with one owner (`ARTIFACT_TERMINOLOGY_NORMALIZATION.md`, #1366): `artifact_class` = family, `artifact_type` = sub-type, `memory_type` = cognitive memory class, `kind`/`artifact_kind` = policy routing. No conflicting *family*-use of `artifact_kind` was found; its occurrences (`ARCHITECTURE.md`, `NOTE_KIND_POLICIES.md`) are legitimate policy-routing usage.
- **Residual:** the legacy term **`VaultMirror`** still appears in ~10 docs (mostly `docs/plans/**` historical, plus a few active surfaces under `SEPARATING_PERSISTENCE_SURFACES/**` and `INTERACTION_SURFACES_AND_AUTHORITY/**`) even though the companion-note migration that superseded it is settled. This is lexical lag, not a live contradiction.
- **Remediation:** a bounded terminology-sweep that (a) marks `VaultMirror` as deprecated in active docs, pointing to the companion-note contract, and (b) leaves historical `docs/plans/**` snapshots as-is or annotates them as historical.

### B. Authority ambiguity — LOW (remediated, enforcement pending)

- **Finding:** DB / index / cache authority and runtime persistence were the main ambiguity. They are now explicitly constrained: machine mirrors carry no independent authority (`MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`), every entity has explicit authority flags (`SEMANTIC_AUTHORITY_MATRIX.md`), and authority is never gained except through a governance transition (`SEMANTIC_SYSTEM_ARCHITECTURE.md` authority topology). Companion UI write semantics are resolved (no UI-owned truth; server-side classification).
- **Residual:** these are documented invariants, not enforced ones. Nothing fails CI if code writes a value that exists only in the DB, or persists a runtime field into frontmatter.
- **Remediation:** a fitness/architecture test (or `scripts/docs_guard.py` extension) that asserts the leakage-prevention rules at the points the repo can cheaply check (e.g. frontmatter field allowlist vs `FRONTMATTER.md`; a check that new stores declare a rebuild source).

### C. Runtime leakage — MEDIUM (boundary documented; code compression remains)

- **Finding:** the runtime/durable boundary is now explicit (`RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`): runtime/session/UI/overlay/retrieval state is discardable and must not pollute durable semantics.
- **Residual:** `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` "runtime seam notes" already document real code-level compression where runtime and semantic layers are not fully separated — e.g. `kind="note"` standing in for multiple artifact layers in ingest/sync paths, and `promotion` resolving directly into `review_state` mutation in both vault frontmatter and store payload. These are pre-existing and acknowledged, but they are the places most at risk of runtime semantics leaking into durable artifacts.
- **Remediation:** treat the ONTOLOGY_VOCABULARY runtime-seam notes as a backlog of code-alignment follow-ons; prioritize the promotion → `review_state` path since it writes durable frontmatter.

### D. Companion UI drift — LOW (no drift found)

- **Finding:** #1368 mapped every Companion UI contract onto Layer 7 and found them **already aligned** — Panel "does not own vault I/O" and "does not reclassify actions locally"; Workspace State has explicit Authority Rules + Durability Posture; Canvas separates body-edit from governance-bearing lanes; UI Runtime Boundaries forbid hidden app databases for meaning-bearing artifacts. No contract asserts UI-owned semantic truth.
- **Residual:** the alignment doc must be kept current as new Companion UI contracts are added; there is no automated check that a new contract satisfies the Layer 7 rules.
- **Remediation:** add the Layer 7 rules to the Companion UI contract-authoring checklist (lightweight, not a gate).

### E. Relation semantics drift — LOW (remediated)

- **Finding:** typed relations are now defined (`RELATION_TAXONOMY.md`), with the rule that generic links carry no hidden semantics and inferred relations are non-authoritative. Provenance relations (`derived_from`, `source_ref`, `supports`) are flagged to stay visible as provenance.
- **Residual:** the runtime relation store currently realizes most edges generically; the typed/provenance/inferred distinctions are target-state and not yet enforced at the store layer.
- **Remediation:** when the relation store is next touched, carry the relation `type` and an inferred/confirmed flag; until then the taxonomy is the authoring contract.

## Risk ranking

| Rank | Risk | Area | Severity | Likelihood | Why it matters long-term |
| --- | --- | --- | --- | --- | --- |
| 1 | Documented-but-unenforced boundaries | B, C, E | Medium | High | The biggest gap is that semantics are now clear but not tested; drift can re-enter through code without tripping any check. |
| 2 | Runtime/semantic compression in ingest/sync/promotion code | C | Medium | Medium | The promotion → `review_state` and `kind="note"` paths touch durable frontmatter and are the most likely real leakage points. |
| 3 | `VaultMirror` lexical lag in active docs | A | Low | Medium | A superseded term in active docs invites confusion and re-adoption. |
| 4 | Alignment/taxonomy docs going stale as new surfaces are added | D, E | Low | Medium | Without a lightweight authoring checklist, new contracts may not be mapped to the layers. |

## Remediation recommendations (consolidated)

1. **Enforcement seam (Rank 1).** Add a minimal fitness/guard check for the cheapest leakage rules: frontmatter field allowlist vs `FRONTMATTER.md`, and a "new store declares a rebuild source" check. Keep it lightweight; do not build a heavy enforcement framework.
2. **Code-alignment backlog (Rank 2).** Convert the `ONTOLOGY_VOCABULARY.md` runtime-seam notes into bounded follow-on issues, starting with the promotion → `review_state` durable-write path.
3. **Terminology sweep (Rank 3).** Deprecate `VaultMirror` in active docs (point to the companion-note contract); annotate `docs/plans/**` occurrences as historical.
4. **Authoring checklists (Rank 4).** Add the Layer 7 projection rules and the relation-taxonomy distinctions to the Companion UI and relation contract-authoring checklists.

## Ownership clarification recommendations

- The seven-layer map (`SEMANTIC_SYSTEM_ARCHITECTURE.md`) is the parent; each layer's detail has a single owner doc (now all created by #1363). Future semantic changes should update the owner doc first, then the map's summary — never the reverse.
- `docs/DOC_DIVERGENCE_AUDIT.md` remains the general documentation-role divergence advisory; this document is the **semantic-boundary** advisory. Neither is normative; both are subordinate to `docs/DOCS_INDEX.md` and the owner contracts.

## Follow-on issue recommendations

These are recommendations only; this audit does not file them.

1. **Add semantic-boundary fitness checks** — minimal guard for frontmatter allowlist + store rebuild-source declaration (Rank 1). Lane: governance/enabling.
2. **Resolve runtime/semantic compression in promotion path** — separate `promotion` transition semantics from direct `review_state` frontmatter mutation (Rank 2). Lane: implementation; requires owner-doc update.
3. **Deprecate `VaultMirror` in active docs** — terminology sweep pointing to companion-note contract (Rank 3). Lane: docs-authoring.
4. **Add Layer 7 + relation-taxonomy authoring checklists** — keep alignment docs current as surfaces are added (Rank 4). Lane: governance.

## Verification path

This document is verified by the existence of:
- audit findings across **terminology drift, authority ambiguity, runtime leakage, Companion UI drift, and relation semantics drift**;
- a **risk ranking** ordered by long-term semantic impact;
- **remediation recommendations** and **ownership clarification** recommendations; and
- **follow-on issue recommendations** that the audit explicitly does not file itself.

The audit reviewed both docs and implementation assumptions (via the ONTOLOGY_VOCABULARY runtime-seam notes and grep evidence) and prioritized risks by long-term semantic impact, with remediation paths aligned to the existing architecture direction.
