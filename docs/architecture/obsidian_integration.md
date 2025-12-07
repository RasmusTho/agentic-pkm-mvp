State: Legacy (archived); superseded by SoT v4.10 (see INGEST.md, OBSIDIANSYNC.md, HUMAN-FLOWS.md).
# Obsidian Integration & Lifecycle — SoT v4.3 Deep Dive

This addendum documents how SoT v4.3 connects the ingestion pipeline with an Obsidian vault while preserving the Core-6 data model and promotion governance.

## 1. File-first lifecycle (historical)
- Watcher-driven ingest with hash-based provenance was a v4.3 concept. Reality-MVP uses manual CLI ingest (`vault-alpha-ingest`) with UUID healing and HybridStore writes (see `docs/INGEST.md` and `docs/HUMAN-FLOWS.md`).

```mermaid
sequenceDiagram
    participant Obsidian
    participant Watcher
    participant Normalizer
    participant Classifier
    participant Chunker
    participant Indexer
    participant ReviewStack as Reviewer/SetEval/Projector

    Obsidian->>Watcher: file created/updated
    Watcher->>Normalizer: ingest.file.changed (path, hash)
    Normalizer->>Classifier: normalized object (core6, payload)
    Classifier->>Chunker: classification decision
    Chunker->>Indexer: chunks written
    Indexer->>ReviewStack: embeddings + stats
    ReviewStack-->>Obsidian: status updated (promotion state)
```

## 2. Promotion pathway (historical)
- Reviewer logs trust, citations, duplicate flags and produces `review` decisions + memory.
- SetEvaluator computes promotion score (`evaluate` decisions) using review, citation, embedding stats.
- Projector enforces `membership(set_id, object_id)` when `promote=true`, emitting audit and episodic memory entries.

```mermaid
sequenceDiagram
    participant Reviewer
    participant SetEvaluator
    participant Projector
    participant Sets
    Reviewer->>SetEvaluator: review decision (allow/trust/missing_citations)
    SetEvaluator->>Projector: evaluate decision (score >= threshold?)
    alt promote
        Projector->>Sets: UPSERT membership(set_id, object_id)
    else block
        Projector-->>Sets: skip (audit only)
    end
    Projector-->>Reviewer: promotion outcome (memory+audit)
```

## 3. Export workflow (historical)
- `scripts/export_objects.py` selects objects with `review_state="approved"` or `promote=true`.
- YAML frontmatter includes Core-6 plus `trust`, `maturity`, `evidence_level`, `review_state`, and provenance timestamps.
- Body contains normalized text; optional chunk appendices (`export/<id>_chunk_<n>.md`) for development.
- Audit excerpts and episodic snapshots appended for traceability.

```mermaid
sequenceDiagram
    participant ExportJob
    participant Postgres
    participant Vault
    ExportJob->>Postgres: SELECT objects JOIN decisions (review/evaluate)
    ExportJob->>Vault: write markdown with frontmatter + body
    ExportJob->>Vault: (dev) write chunk files export/<id>_chunk_<n>.md
    ExportJob-->>Postgres: audit export event (optional)
```

## 4. Rename/update reconciliation (historical)
- Describes a watcher comparing hashes. Reality-MVP has no watcher; path changes are handled via ingest CLI and VaultMirror reconciliation.

```mermaid
sequenceDiagram
    participant Watcher
    participant Postgres
    participant Deduper
    Watcher->>Postgres: lookup by file_hash
    alt hash match
        Postgres->>Postgres: update origin path, clear archived flag
    else new hash
        Watcher->>Deduper: candidate pair (old_id, new_id)
        Deduper->>Postgres: mark duplicate_of / keep canonical
    end
```

## 5. Backfill hygiene (historical)
- `make backfill` and view-based audits are not part of Reality-MVP; current ingest is rebuilt via CLI as needed.

## 6. Operational checklist (historical)
- Watch services/export jobs referenced here are not active in v4.10. Use `docs/INGEST.md` and `docs/OBSIDIANSYNC.md` for the current Obsidian vault integration (manual CLI ingest, UUID healing, panel stripping).
