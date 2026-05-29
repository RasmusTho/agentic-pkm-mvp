State: Concept contract (machine mirror and DB authority; target-state semantics hardening current runtime posture).
Doc role: Core SoT
Authority: Owns the machine-mirror and DB authority contract under Layer 6 (Machine Mirror) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`: which structures are mirrors, what authority they may and may not hold, and the rebuild/sync/retrieval/leakage-prevention semantics that keep them subordinate to the vault. Consolidates and hardens existing mirror semantics; it does not redefine the durable-surface or component owner docs.
Owner: Machine mirror / DB authority contract
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/COMPONENTS.md, docs/EMBEDDINGS.md, docs/DB_SCHEMA.md, docs/GLOSSARY.md (Healing), epic #1363, issue #1370.

# Machine Mirror and DB Authority Contract

The system runs on Postgres, pgvector, indexes, and caches. These are essential for performance and retrieval — and they are **mirrors**, not sources of truth. This contract hardens that boundary: it states what a machine mirror is, what authority it may hold (almost none), and the rebuild/sync/retrieval/leakage rules that keep DB and index state subordinate to the vault.

It is the Layer 6 detail for `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` and the mirror-row detail for `docs/SEMANTIC_AUTHORITY_MATRIX.md`.

## Canonical authority

The durable, authoritative set is the human-readable surface; machine mirrors sit beneath it.

- **Vault authority.** Human-readable Markdown (vault notes + system-owned companion notes) is the durable continuity set and the source of meaning. DB/index/cache state must be rebuildable from it (kernel constraint; owner: `SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`).
- **Frontmatter authority.** Durable artifact fields are defined by `docs/FRONTMATTER.md`. A mirror may *project* frontmatter (e.g. into store columns) but the frontmatter on the human surface is authoritative; the projected copy is not.
- **Receipt authority.** Receipts are governance-recorded durable records (Layer 4), **not** mirrors. A receipt is not rebuildable from the vault and must not be treated as a regenerable cache (owner: `MIRROR_RECEIPT_DECISION.md`, `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`).
- **Runtime authority boundary.** Runtime/session state (Layer 5) is ephemeral and also non-authoritative, but it is distinct from a mirror: a mirror is rebuildable from durable sources, while runtime state is discardable and not reconstructed (boundary owned by #1369).
- **Machine mirror limitation.** A mirror holds **no independent authority**. Its authority is exactly the authority of the source it projects, and only the `retrieval-visible` right (owner: `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6; `SEMANTIC_AUTHORITY_MATRIX.md` rule 4).

## Mirror types

The following are machine mirrors. All are rebuildable, none are authoritative.

| Mirror type | What it projects | Rebuild source |
| --- | --- | --- |
| DB representations (object/store rows) | Vault notes + companion notes + frontmatter | Re-ingest from vault + companion set |
| Vector indexes (embeddings) | Chunked artifact content | Re-chunk + re-embed from source artifacts (provider-tagged) |
| Retrieval caches | Prior retrieval/ranking results | Re-run retrieval |
| Render caches | Rendered views of artifacts | Re-render from source |
| Workspace aggregates | A composed view of the active working surface | Recompose from durable + runtime inputs |
| Search projections | Full-text / lexical (BM25) indexes | Re-index from source |
| Graph projections | The relation store / link graph | Rebuild from durable relations + provenance |

If a structure on this list would lose information on rebuild, it is **misclassified** — it is actually an artifact or a receipt and must be governed as one (owner: `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6, `MIRROR_RECEIPT_DECISION.md`).

## Mirror semantics

### Rebuild semantics

- Every mirror must be **fully reconstructable** from the durable set (vault notes + companion notes + receipts) without loss of meaning.
- Rebuild is a safe, repeatable operation: dropping and rebuilding a mirror must never change the system's semantics, only its performance/availability.
- Embeddings are provider-tagged and rebuilt under the embeddings rebuild policy; an embedding from a different provider/model is a different derived artifact, not an authoritative value (owner: `docs/EMBEDDINGS.md`).

### Indexing semantics

- Indexing derives retrieval/search structures from source artifacts. An index entry borrows the authority and use-rights of its source; it never adds any.
- Index freshness is a performance/consistency property, not an authority property: a stale index is *behind*, never *more correct than* the vault.

### Cache semantics

- Caches (retrieval, render) are disposable accelerators. They may be evicted at any time and must be reconstructable.
- A cache must never be the only place a value exists; if it is, the value was durable and is misplaced.

### Synchronization semantics

- Sync flows **from the durable surface to the mirror**, never the reverse as authority. The SyncLayer reacts to changed files; it does not treat the DB, iCloud, or Git as semantically primary (owner: `docs/GLOSSARY.md` SyncLayer).
- On divergence, the vault wins. A mirror that disagrees with the vault is stale and must heal toward the vault.

### Retrieval semantics

- Retrieval surfaces mirrors as candidates; admitting a candidate into working context is the separate `activatable` step governed by activation semantics (owner: `CONTEXT_ACTIVATION_SEMANTICS.md`).
- A retrieved mirror result carries its source's `validity`/`stale_after` posture; surfacing stale content without its marker is an error.
- Retrieval heuristics (ranking, salience, rerank) are derived projections and must never become durable authority.

### Identity / healing semantics

- Mirror identity heals toward the durable surface using the conservative priority order: frontmatter UUID → companion note → DB identity record → `source_ref`/path → content hash → semantic triage → new UUID (owner: `docs/GLOSSARY.md` Healing).
- The DB identity record is a mirror aid in this order; it is **below** frontmatter UUID and companion note, so the DB never overrides human-surface identity.

## Leakage prevention

The following are the failure modes this contract exists to prevent. Each is prohibited:

1. **Mirror state becoming semantic truth.** A value read from a DB row, index, or cache must not be written back to the human surface as authoritative without tracing to its authoritative source and passing governance (Layer 4).
2. **Runtime-derived metadata becoming canonical semantics.** Ranking scores, salience/zone overlays, retrieval timestamps, and similar derived metadata must not be persisted into frontmatter as durable fields.
3. **Retrieval heuristics becoming durable authority.** A heuristic that worked well in retrieval is still a heuristic; it does not earn durable standing by being useful.
4. **Implicit authority migration into DB/index layers.** No code path may make the DB the de facto source of truth by writing values that exist nowhere on the durable surface. If a value must be durable, it belongs in the vault/companion/receipt set, mirrored *from* there.

## Implementation boundary guidance

- Feature code must reach mirrors through the Store/Component abstractions, not DB internals directly (owner: `docs/COMPONENTS.md`; repo rule).
- A new store/index/cache must declare its rebuild source and confirm it loses no meaning on rebuild before it is added.
- Persisting any value to a mirror that does not exist on the durable surface is a design smell that must be resolved by either (a) making the value durable on the human surface, or (b) treating it as discardable runtime state — never by leaving the DB as its only home.

## Cross-references

- Parent semantic map (Layer 6) and authority topology: `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- Per-entity mirror authority flags: `docs/SEMANTIC_AUTHORITY_MATRIX.md` (Machine Mirror / DB / Embedding / Retrieval cache rows).
- Persistence-surface taxonomy (mirror vs receipt vs trace vs index/projection): `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`.
- Mirror vs receipt decision: `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.
- Artifact vs projection: `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`.
- Embeddings identity/rebuild: `docs/EMBEDDINGS.md`. Component catalog: `docs/COMPONENTS.md`. Schema: `docs/DB_SCHEMA.md`.
- Runtime vs durable boundary (distinct from mirror): `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1369).

## Verification path

This document is verified by the existence of:
- a **canonical authority** section constraining vault/frontmatter/receipt/runtime authority and stating the machine-mirror limitation;
- a **mirror types** list with rebuild sources;
- **rebuild / indexing / cache / synchronization / retrieval / identity-healing** semantics; and
- a **leakage-prevention** section prohibiting mirror state, runtime-derived metadata, and retrieval heuristics from becoming durable authority, aligned with the Contextualization Layer and the authority matrix.
