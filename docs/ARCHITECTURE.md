# Architecture — SoT v4.4 Baseline

_Reference for structure, agents, events, and invariants. This supersedes older v4.2/v4.3 texts._

---

## 1) Runtime & Deployment

- **Language:** Python 3.14
- **App surfaces:** FastAPI API, LangGraph agents, background jobs
- **Persistence:** Postgres 16 + pgvector (SetDB/AMG)
- **Cache/Queue:** Redis (optional, bridge/coordination)
- **LLMs:** Local Ollama (llama3.1:8b, deepseek-r1:8b) and pluggable remotes
- **Packaging:** Docker Compose (db, redis, api)
- **Dev workflow:** VS Code Remote-SSH → Mac mini; Portainer for stacks
- **CLI:** `python -m app.agents.runner --agent <name>`

---

## 2) Data Model (SetDB / AMG)

Core tables:

- `objects(id UUID PK, kind text, source_ref text, payload jsonb, created_at timestamptz)`
- `chunks(id UUID PK, object_id UUID, idx int, payload jsonb, offset_start int, offset_end int, text text)`
- `embeddings(id UUID PK, object_id UUID, model text, dim int, vec vector)`
- `decisions(id UUID PK, object_id UUID, key text, value jsonb, created_at timestamptz)`
- `audit(id UUID PK, object_id UUID, agent text, action text, ts timestamptz, trace_id text, details jsonb)`
- `sets(id UUID PK, name text)` / `membership(id UUID PK, set_id UUID, object_id UUID)`
- `agent_memories(id UUID PK, run_id UUID, layer text, payload jsonb, provenance jsonb, created_at timestamptz)`

**Core-6** (`id`, `type`, `title`, `created`, `updated`, `origin`) lever i `objects.payload.core6` och är immutabla utanför Normalizer.

> **Pending refactor (documented):** Konsolidera identitet → ta bort `objects.id` och gör `uuid` till enda kanon (PK). Följd-migreringar uppdaterar FK och kodvägar.

---

## 3) Events, Outbox & Observability

- **Event log:** JSONL (`events.jsonl`) med `trace_id` på alla domänhändelser.
- **Topics (kärna):**
  - **Ingest:** `ingest.object.created`
  - **Merge:** `merge.intent.created` → `merge.prompt` → `merge.resolved | merge.conflict`
  - **Promotion:** `promote.intent.created` → `promote.done | promote.pending_move | promote.error`
  - **Hygiene:** `cleanup.intent.created` → `cleanup.done`
- **Tracing:** `app/observability/tracer.start_span()` (ContextVar-baserad). Jaeger via OTLP när endpoint är konfad.
- **Quality gates (CI mål):** QAS-003 (search p95 < 250 ms), QAS-010 (outbox→index ≤ 2 s); OpenAPI/AsyncAPI lint.

---

## 4) Agent Framework (PER)

Alla agenter följer **Plan → Act → Reflect** med audit + events och idempotens.

### 4.1 Ingestion & Curation Pipeline

| Stage | Agent | Input | Output | Notes |
|---|---|---|---|---|
| 1 | **Normalizer** | råtext/fil | `objects` (Core-6 stabil), audit | Immutables sätts, origin hash |
| 2 | **Classifier** | object | decisions(taxonomy/trust) | Taggar, risk/klass |
| 3 | **Chunker** | object | `chunks` | Logiska spans |
| 4 | **Deduper** | object/chunks | decisions(duplicate_of) | Near-dup |
| 5 | **CitationChecker** | chunks | decisions(citation) | Blockers vid saknad källa |
| 6 | **Indexer** | chunks | `embeddings` + stats | pgvector + BM25-lite |
| 7 | **Reviewer** | object + provenance | decisions(review) | Sammanställer källor |
| 8 | **SetEvaluator** | review | decisions(evaluate) | Poäng för promotion |
| 9 | **Projector** | evaluate | `membership` uppdaterad | Publicerar till sets |

### 4.2 Lifecycle & Governance

| Stage | Agent | Input | Output | Notes |
|---|---|---|---|---|
| A | **Promotion Agent** | `promote.intent.created` | `promote.done|pending_move|error` | Uppdaterar `review_state: promoted`, flytt batchas enl. policy |
| B | **MergeResolverAgent** | base, local, remote | `merge.resolved|prompt|conflict` | Semantisk 3-vägs merge (MD+YAML) |
| C | **NoteHygieneAgent** | note | `cleanup.done` | Archive/fix_structure/keep |

**Allmänna egenskaper:** PER-loop, audit med `trace_id`, deterministiska writes, återstartbar körning.

---

## 5) MergeResolverAgent (semantic, structure-aware)

**Mål:** Välj högst semantisk kvalitet; bevara provenance; minimera manuella konflikter.

**Inputs:** `base`, `local (A)`, `remote (B)`; YAML-frontmatter + body.

**Plan**
1) 3-vägs diff → **loci** för YAML-nycklar + Markdown-body (rubriknivåer kan nyttjas senare).  
2) Policyevaluering av invariants (immutables/enumprogression) före modell.

**Act**
- **LLM-Arbiter** (temp=0, strikt JSON-schema) beslutar per locus: `A|B|HYBRID|ASK`.
- **Heuristik fallback:** Om A saknar men B har unika länkar/fakta → HYBRID(A + refs från B).
- **Git-integration:** `.gitattributes` → `merge=semanticmd` → `app/services/merge_driver.py`.

**Reflect**
- Verifiera invariants + återbygg hash/version-vector.
- Emit `merge.resolved` eller `merge.prompt` (ASK-fall).

**Invariants**
- `uuid` och övriga immutables får inte ändras.
- `review_state` får endast röra sig frammåt (draft→reviewed→promoted).
- Proveniens union/dedup: källor förloras aldrig.
- Kodblock >80 rader i icke-kodnoter penaliseras i scoring.

---

## 6) NoteHygieneAgent (quality maintenance)

**Klassificering**
- **archive** – tom eller nästan tom → flytt till `Archive/Trash/YYYY-MM/<slug>.md`, emit `cleanup.done`.
- **fix_structure** – kort (≤ ~80 tokens) → generera `## Summary` + `## Pointers` från text + länkar.
- **keep** – behåll.

**Events:** `cleanup.done` inkluderar målpath och `uuid` för spårbarhet.

---

## 7) Search & Retrieval

- **Lexikal:** BM25-lite (tsvector) på `objects`.  
- **Semantisk:** pgvector per chunk; cosine-distans.  
- **Hybrid:** rank-merge före svarssammansättning.  
- **API:** `/search` (GET) med spårning (`x-trace-id` stöds).

---

## 8) Interfaces & Tools

- **/ingest** (POST) – skriver in objekt; outbox triggar Indexer.  
- **/search** (GET) – snabbsök.  
- **CLI verktyg:**  
  - `tools/events_cli.py` – summering/tail av `events.jsonl`.  
  - `tools/merge_prompt_export.py` – export av `merge.prompt` → Markdown-underlag.  
- **Git merge driver:** `.gitattributes` + `app/services/merge_driver.py`.

---

## 9) Configuration & Policy

- **System-settings:** YAML i vault, schema-validerad lokalt + i CI (mål).  
- **Merge-policy:** preferera koncis, välformulerad text; HYBRID bär över unika referenser/fakta; ASK när A/B är semantiskt nära.  
- **Promotion-policy:** cool-down, idle-detektion, idempotens på UUID-nivå; batch-move enligt `move_policy`.

---

## 10) Testing, CI & Fitness Functions

- **Unit & E2E:** Agenter, merge-fixturer, hygiene, indexer.  
- **Golden fixtures:** för HYBRID-sammanfogningar (planerad i v4.5).  
- **CI guards:**  
  - Schema-lint för LLM-svar (planerad).  
  - `make smoke` kör settings-validering + promotion-E2E.  
  - QAS-003 (search p95) och QAS-010 (outbox→index) aktiveras successivt.

---

## 11) Roadmap Hooks (v4.5 → v4.6)

- **v4.5:** Block-aware diff (rubrik/paragraph-ID), ASK-microflow CLI (A/B/HYBRID apply), golden fixtures + CI-vakter, policy-integration Merge→Reviewer→Projector.
- **v4.6:** Tokenoptimering vid fjärr-LLM, post-merge critique (aktivt lärande), förbättrade heuristiker.

