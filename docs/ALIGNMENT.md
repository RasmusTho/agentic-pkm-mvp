# Alignment Guide

## Why This Exists
- Keep the Agentic PKM API and agent tools aligned with the "Second-Brain" project goals.
- Protect the user's preferred way of working: short, concrete steps; iterate safely; default to open-source friendly solutions.
- Make expectations explicit so new changes can be checked against them quickly.

## Current Stage (Oct 2025)
- FastAPI backend in `app/` exposes `/`, `/items`, and `/context`.
- Agent workflow lives under `app/agent/`; `run_agent.py` is the CLI entry point.
- Data/context JSON drives memory and preferences for the agent.
- Alembic migrations are current with baseline `3ddfc7237248_baseline.py`.

## Near-Term Focus
- Rulla ut API-nyckel + rate limiting i deployment (env + Redis).
- Koppla loggar/metrics till observability-stack (t.ex. Grafana).
- Införa pre-commit-flöde (klar med hooks i repo, rulla ut i teamet).
- Planera data governance för arkiverade körningar (retention/purge regler).
- Bygg pipeline som flyttar chunkar från staging till huvudindex efter `trust="reviewed"`.
- Frontmatter-spec och API-kontrakt för /ingest och /recall (beskrivs nedan).
- Stage watcher och review endpoints finns nu; LangGraph-agent behöver kopplas mot `/ingest/pending` + `/ingest/review` för att automatisera QA & promotion.

## Operating Principles
- Bias for maintainable, well-tested changes; add tests when behavior shifts or bugs are fixed.
- Prefer configuration via environment variables and `.env`, never check secrets into git.
- Leverage DuckDB locally (`storage/agent.duckdb`) unless requirements change.
- Document new behaviors (README, docs/) alongside code so the agent's memory stays current.

## Collaboration Norms
- Communication: respond in Swedish or English; keep replies kort & konkret.
- Process: one focused change at a time, TDD där det passar.
- Privacy: inga hemligheter i prompts; stay within opened context when possible.

## Decision Log
- 2025-10-19: Observability hooks (JSON-loggar + Prometheus via `METRICS_ENABLED`) aktiverade i `app/observability.py`.
- 2025-10-19: Pre-commit hooks för ruff/mypy/pytest tillagda (`.pre-commit-config.yaml`).
- 2025-10-19: Arkivrotation tillåter retention via `--max-age-days` i `scripts/rotate_storage.py`.
- 2025-10-19: Lokal observability-stack dokumenterad i `docs/OBSERVABILITY_STACK.md` och Docker Compose-basen etablerad.
- 2025-10-19: Frontmatter- och API-kontrakt specificerade för agentflödet (docs/ALIGNMENT.md, README).
- 2025-10-19: Lokal watcher och vault-ingest (Obsidian `@Inbox`) implementerat via `app/ingest/watcher.py`.
- 2025-10-19: DuckDB-staging och review endpoints (`/ingest/pending`, `/ingest/review`) tillagda för agentstyrd QA.
- 2025-10-19: Semantic chunking & categorization scheman dokumenterade i alignment + system context.
- Äldre poster finns arkiverade i `docs/archive/decision-log-2025-10.md`.

## Inputs to implement
# Integrate system-level intents and lifecycle loops from "Second Brain Requirements"
# Add fields and logic to reflect learning, reflection, synthesis, communication and serendipitous discovery

## Frontmatter v0.2
```yaml
---
id: "<uuid>"
title: ""
object_type: [note|claim|concept|source|chunk|table|synthesis_note]
system_intent: [learn|reflect|synthesize|communicate]
origin: [internal|external]
created: "YYYY-MM-DD"
tags: [topic/…, project/…]
emergent_tags: [serendipity, collaboration, exploration]
trust: provisional|reviewed
source_ref: "<sha|url>"
amg:
  nodes: ["n:Concept/…","n:Entity/…"]
  edges: ["e:rel(type):A->B"]
chunks:
  algo: "recursive"
  size: 800
  overlap: 120
---
```

*Markdown filen ska alltid skrivas till Obsidian/vault med ovanstående frontmatter, följt av innehållet (t.ex. sammanfattning eller extraherad text).*

### Reflection & analytics updates
- `system_intent` styr var i cykeln (learn → reflect → synthesize → communicate) artefakten befinner sig och används för per-intent analys.
- `emergent_tags` markerar serendipity/collaboration/exploration-signaler och påverkar endast rapportering.
- Artefakter med `system_intent=reflect` och låg `clarity_score` (<0.6) eller `new_insight=true` placeras i `/storage/reflect/` för återinläsning (se logg `logs/reflection.json`).
- `synthesis_note` binder samman claims och loggar relationer `type="synthesizes"` under `logs/relations.jsonl`.
- Emergent analytics uppdateras i `logs/emergent_analytics.json` för grafiska dashboards.

### Lifecycle policies (uppdaterad)
6) **Reflection & feedback hooks** – artefakter med `system_intent=reflect` triggar nya capture-uppgifter när `clarity_score < 0.6` eller `new_insight=true`; varje händelse loggas och köas via `/storage/reflect/`.
7) **Emergent analytics** – summera antal per `system_intent` och `emergent_tags` för att visualisera balansen mellan exploration, lärande och kommunikation. Uppdaterad statistik lagras i `logs/emergent_analytics.json`.

## API-kontrakt (MVP)

### `POST /ingest`
- **Request** (`application/json`):
  ```json
  {
    "id": "3f0b4f86-...",
    "kind": "note",
    "source_ref": "obsidian/Foo.md",
    "payload": {"title": "Foo", "tags": ["topic/ai"]},
    "text": "alpha beta"
  }
  ```
- **Response** (`201 CREATED`):
  ```json
  {
    "ok": true,
    "object_id": "3f0b4f86-...",
    "dimensions": 1536,
    "model": "openai/text-embedding-3-large"
  }
  ```
- Samma `id` kan återanvändas för idempotent uppdatering (`ON CONFLICT` sätter payload och embedding).

### `POST /search`
- **Body**: `{ "query_text?": "...", "query_embedding?": [ ... ], "k": 10 }`
- **Response** (`200 OK`):
  ```json
  {
    "hits": [
      {
        "object_id": "3f0b4f86-...",
        "score": 0.0331,
        "payload": {"title": "Foo", "text": "alpha beta"}
      }
    ]
  }
  ```
- `query_text` ger FTS (GIN-index på `search_vector`), `query_embedding` ger pgvector, båda tillsammans ger hybrid (RRF).

### Testfall
- `tests/test_ingest_roundtrip.py` – säkerställer att ingest skriver metadata och embedding till pgvector-indexet.
- `tests/test_vector_query.py` – kontrollerar närmsta granne via vektorsök.
- `tests/test_hybrid_rrf.py` – verifierar Reciprocal Rank Fusion mellan FTS- och vektorresultat.

## Chunking v0.2 – Semantisk & Reviderbar

### Configuration
CHUNK_SIZE: 800
CHUNK_OVERLAP: 120
CHUNK_POLICY: semantic
CHUNK_SOURCE: headings|tokens
CHUNK_STATE: provisional|reviewed

### Metadata schema
{
  "chunk_id": "<uuid>",
  "doc_id": "<item_id>",
  "hash": "<sha1>",
  "state": "provisional|reviewed",
  "source_ref": "<url|git_sha>",
  "title": "<string>",
  "tags": ["..."],
  "trust": "provisional|reviewed",
  "size": 800,
  "created": "ISO8601",
  "policy": "semantic_v1"
}

### Promotion flow
provisional → review → approve → indexed (Postgres)

Embeddings skrivs direkt till Postgres `embeddings`; `state/trust` i payloaden avgör om poster ska exponeras i sökresultat. Promotion innebär att sätta `state=reviewed` och eventuellt berika payload (taggar, källor).

## Categorization v0.1 – Semantisk Labeling

### Schema
{
  "quality.class": "spam|ham|low_quality|medium|high",
  "credibility": "unverified|credible|expert_consensus",
  "factuality": "fact|hypothesis|opinion|satire",
  "source_type": "email|youtube|article|paper|transcript|chatlog",
  "topic.primary": "mathematics|psychology|biology|philosophy|politics|economics|literature|history|other",
  "topic.secondary": ["free-form tags"]
}

### Flow
QA_GATE → CATEGORIZE → CHUNK
CATEGORIZE output is validated and written into frontmatter and metadata index.

## Triage Criteria v0.1
- **Trust & kompletthet**: payloadens text ska vara fullständig, läsbar och fri från skräp/duplikat innan `state` höjs till `reviewed`.
- **Metadata**: säkerställ att JSONB innehåller `title`, `tags`, `source_ref`, `trust/state` och att `text` används för embedding.
- **Taggar & klassificering**: rapportera saknade obligatoriska taggar (t.ex. `topic/...`, projekt-taggar) eller inkonsekvenser mot roadmapen.
- **Kvalitetssignaler**: flagga dokument med extremt korta eller repetitiva texter som kräver manuell åtgärd.
- **Rekommenderad åtgärd**: uppdatera payload och kör `/ingest` igen med samma `id` för att skriva över poster (idempotent `ON CONFLICT`).
- **Automatisering**: framtida agent-version kan höja `trust` via `search_hybrid`-feedback – definiera heuristiker innan detta aktiveras.

## Recall Agent v0.1
- **Datakälla**: bygger på Postgres `objects` + `embeddings` (`search_hybrid`/`search_vector`).
- **Sökstrategi**: hybrid scoring (FTS + pgvector RRF) som returnerar `object_id`, `score`, `payload` (inkl. titel/text).
- **CLI**: `run_agent.py --task recall --input "query"` nyttjar samma sökväg och skriver ut toppträffar med källor.
- **Framåt**: fortsätt optimera pgvector-parametrar; utvärdera alternativa backends först om prestanda/problem uppstår.
