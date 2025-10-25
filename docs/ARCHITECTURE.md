# SoT v4.3 — Obsidian Integration & Lifecycle

## Scope
Extends v4.2 by connecting the ingestion pipeline (Normalizer → … → Projector) with the Obsidian vault.
Focus: file-based lifecycle, export, and synchronization between Postgres (SetDB/AMG) and Markdown sources.

---

## 1. File-first mirroring
- Every object with `core6.origin` pointing to a physical file in the vault stays mirrored.
- Filenames are cosmetic; `core6.id` is the canonical identity.
- Exported files include YAML frontmatter (Core-6 + agent metadata: `trust`, `maturity`, `evidence_level`, `review_state`).
- In development mode, chunk exports are written to `export/<id>_chunk_<n>.md`.

---

## 2. Lifecycle
- **Create:** New Markdown files in watch-path → normalized and stored.
- **Update:** Hash or mtime changes trigger re-ingest; `updated` is refreshed, `id` and `created` persist.
- **Delete:** Marked `archived=True` in DB; physical removal is manual.
- **Rename:** Detected by identical hash → `origin` updated, `id` preserved.
- **Conflict:** If identical title but differing hash → deduper agent selects canonical or adds suffix “(alt n)”.

---

## 3. Export pipeline
- `scripts/export_objects.py` exports all `objects` with `review_state="approved"` or `promote=True`.
- YAML frontmatter written first, followed by text.
- Audit + episodic memory appended for traceability.
- Command example:
  bash
  PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" \
  python scripts/export_objects.py --vault ~/Obsidian/PKM
- 
- ---
## **4. Synchronization strategy**

- A watcher (ingest/watcher.py) monitors vault/ and compares file hashes to DB.
    
- Events (created, modified, deleted, renamed) emit ingest.file.* messages to the internal WS queue.
    
- The queue triggers the appropriate agent chain.
    
- All events produce entries in audit and memory.episodic.
    

---

## **5. Maturity and promotion**

- review_state controls export eligibility.
    
- SetEvaluator + Projector handle promotion into “public sets”.
    
- Lifecycle states:
    
    - draft → reviewed → approved → published
        
    - rollback if trust < threshold.
        
    

---

## **6. Human-first workflow**

- Obsidian remains the editable source.
    
- The system mirrors changes transparently:
    
    - no file locks
        
    - full audit rollback
        
    - merge conflicts resolved via SetEvaluator.
        
    

---

## **7. Database & index extensions**

- Core tables (objects, chunks, embeddings, audit, decisions, memory) unchanged.
    
- New fields:
    
    - objects.archived (bool)
        
    - objects.file_hash (text)
        
    - objects.maturity (enum)
        
    
- New view:
    
    - v_promoted_objects (join of objects × decisions × sets).
        
    

---

## **8. Testing & next steps**

- New E2E test: tests/e2e/test_vault_sync.py simulates file changes and validates correct lifecycle handling.
    
- scripts/ingest_real.sh and export_objects.py used for live ingestion/export verification.
    
- Next: **SoT v4.4 — merge handling and collaborative conflict resolution.**
    
