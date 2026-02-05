State: Legacy (archived).
# RUNBOOK — SoT v4.3 Ingestion & Vault Lifecycle

## 0. Snabbguide (TL;DR)
1) Starta DB/Redis:
   docker compose up -d db redis
2) Migrera schema:
   export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
   PYTHONPATH="$(pwd)" alembic upgrade head
3) Snabbtest (lokal DB):
   PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/e2e/test_pipe_graph.py
4) Starta API:
   docker compose up -d api
5) Hälsa:
   curl -sS http://127.0.0.1:18000/healthz

Noteringar:
- Använd INTE applypatch-kommandon.
- Undvik kommentarer i terminalraden som börjar med # — kör rena kommandon.

---

## 1. Miljö & variabler
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
export PYTHONPATH="$(pwd)"
python -V
alembic -v

## 2. Tjänster
Start:
  docker compose up -d db redis
Status/portar:
  docker compose ps
Loggar:
  docker compose logs -f db
  docker compose logs -f redis
Stoppa:
  docker compose stop db redis
Nedtagning:
  docker compose down

## 3. Databasoperationer
Migrera till head:
  PYTHONPATH="$(pwd)" alembic upgrade head
Visa heads:
  PYTHONPATH="$(pwd)" alembic heads
Lösa “Multiple heads”:
  PYTHONPATH="$(pwd)" alembic merge -m "merge heads" <id1> <id2>
  PYTHONPATH="$(pwd)" alembic upgrade head

Introspektion:
  docker compose exec db psql -U app -d app -c "\dt"
  docker compose exec db psql -U app -d app -c "SELECT COUNT(*) FROM objects;"

Backup/restore (dev):
  docker compose exec db pg_dump -U app app > backup.sql
  psql "$(echo $DATABASE_URL | sed 's|postgresql+psycopg://|postgresql://|')" < backup.sql

Reset (farligt – tar bort data):
  docker compose exec db psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  PYTHONPATH="$(pwd)" alembic upgrade head

## 4. Ingestion-pipeline (LangGraph)
Node-ordning (v4.3):
  Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector

Manuella anrop i tester:
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/agents/test_normalizer_graph.py
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/agents/test_chunker.py
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/agents/test_indexer.py
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/e2e/test_pipe_graph.py

## 5. LLM/Reasoning (lokalt via Ollama)
Starta Ollama (bakgrundstjänst):
  brew services start ollama
Stoppa:
  brew services stop ollama
Ladda modeller:
  ollama pull llama3.1:8b
  ollama pull deepseek-r1:8b
Kontroll:
  ollama list
  ollama ps

Konfig i appen (default via env):
  export LLM_PROVIDER="ollama"
  export LLM_MODEL="llama3.1:8b"
  export LLM_REASONING_MODEL="deepseek-r1:8b"

Snabb sanity mot adapter:
  python - <<'P2'
import os
from app.llm.adapter import generate
os.environ.setdefault("LLM_PROVIDER","ollama")
os.environ.setdefault("LLM_MODEL","llama3.1:8b")
print(generate([{"role":"user","content":"Svara kort på svenska: Vad gör Classifier?"}])[:160])
P2

Minne/CPU-tryck:
  - Stäng onödiga Docker-containrar när du kör lokala LLM.
  - Stoppa oanvända modeller: ollama stop <modell>

## 6. Backfill and Export
- Backfill pipeline hygiene:
  ```
  make backfill
  ```
- Manual export to Obsidian vault:
  ```
  PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" \
  python scripts/export_objects.py --vault ~/Obsidian/PKM
  ```
- Views to inspect outstanding items:
  - `SELECT * FROM view_objects_missing_chunks;`
  - `SELECT * FROM view_chunks_missing_embeddings;`
  - `SELECT * FROM view_objects_missing_review;`
  - `SELECT * FROM view_objects_ready_for_projection;`

## 7. Verifiera lokalt
- Kör hela verifikationsskriptet (CI-lite):
  ```
  PATH="$(pwd)/.venv/bin:$PATH" scripts/codex_verify.sh
  ```
- Om `psql` saknas lokalt kan `PSQL="docker compose exec -T postgres psql"` exporteras innan körning.
- Resultatet ska avslutas med `OK` samt redovisade objekt/chunk/embedding/audit-räknare.

## 8. Vanliga fel och snabba åtgärder
“FATAL: database ... does not exist”
  Skapa DB/roll:
    docker compose exec db psql -U app -d app -c "SELECT 1;" || true
  Om rollen saknas:
    docker compose exec db psql -U postgres -d postgres -c "CREATE ROLE app WITH LOGIN PASSWORD 'app' CREATEDB;"
    docker compose exec db psql -U postgres -d postgres -c "CREATE DATABASE app OWNER app;"
    docker compose exec db psql -U app -d app -c "CREATE EXTENSION IF NOT EXISTS vector;"
  Kör migrationer:
    PYTHONPATH="$(pwd)" alembic upgrade head

“connection refused” på 15432
  Starta DB:
    docker compose up -d db

Alembic “Multiple heads”
  Se heads:
    PYTHONPATH="$(pwd)" alembic heads
  Merge:
    PYTHONPATH="$(pwd)" alembic merge -m "merge heads" <id1> <id2>
    PYTHONPATH="$(pwd)" alembic upgrade head

KeyError: 'DATABASE_URL' i tester
  Kör med env:
    PYTHONPATH="$(pwd)" env DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q <testfil.py>

E2E faller på chunks/embeddings
  Säkerställ att Indexer körs i testet och att pgvector-index finns (CREATE EXTENSION vector).
  Kör om:
    PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/e2e/test_pipe_graph.py

Ollama connection refused (11434)
  Starta Ollama:
    brew services start ollama
  Verifiera:
    curl -sS http://127.0.0.1:11434/api/tags

## 9. Städning & artifacts
Repo-karta:
  scripts/repo_map.sh → skriver repo_tree.txt och repo_counts.txt
Sök backend-signaturer (säkra varningar):
  scripts/locate_search_backends.sh → bm25_hits.txt, embedding_hits.txt, dao_schema_hits.txt
Ta bort jättestora artifacts:
  rm -f embedding_hits.txt bm25_hits.txt dao_schema_hits.txt
  git update-index --assume-unchanged <fil>  # om genereras lokalt ofta

## 10. CI-snabbtest (≤ 2 min, < 500 docs)
Lokalt:
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q -k "not slow" --maxfail=1
Rök-test:
  PYTHONPATH="$(pwd)" env DATABASE_URL="$DATABASE_URL" pytest -q tests/e2e/test_pipe_graph.py

## 11. Spårbarhet (Audit)
Varje agent loggar audit med trace_id:
  SELECT * FROM audit WHERE trace_id='...';
Verifiera idempotens:
  SELECT COUNT(*) FROM objects WHERE id='...';

## 12. När eskalera
- Migreringar blockeras av oförenliga heads
- Orsaker till OOM kvarstår efter stängning av modeller/containers
- Indexering producerar 0 embeddings trots chunkar > 0
- E2E passerar inte lokalt men CI gör – mismatch i env/versioner
