Agentic PKM — Second-Brain Engine

System-of-Truth baseline: v4.10 (Reality-MVP, locked)
System-of-Truth forward line: v5.4 (PanelAgent Runtime + Watchers)

Agentic PKM är ett agentdrivet, eventstyrt och CI-säkrat system för personlig kunskapshantering.
Det använder ett mänskligt gränssnitt (Markdown-vault) och ett maskinellt ”System-of-Truth” bestående av Stores, Outbox-händelser och en flerstegs agent-pipeline.
SoT v4.10 är den låsta Reality-MVP-baslinjen. All ny utveckling sker på v5.x-linjen (Agentic PKM / PanelAgent / Satellite Sync / Yggdrasil).

<!-- DOCS-LINKS:BEGIN -->
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Status](docs/STATUS.md)
- [Diagrams](docs/DIAGRAMS.md)
<!-- DOCS-LINKS:END -->

What works today
- PER-loop ingestion for Obsidian notes with Core-6 projection into Stores + Outbox (Normalizer→PromotionAgent).
- Hybrid retrieval + ASK CLI over the vault plane; rerank/reasoning are flag-gated.
- Zones and planes defined: vault as human surface with minimal frontmatter; `external_raw` objects stay out of Obsidian but are indexed for answers.
- Deterministic CI via the eight-line contract (latency, eval, relations, diarization, reasoning, gates).

Reality-MVP (SoT v4.10) — what is included
- Hardened ingest of real Obsidian vault folders into ObjectStore + VectorIndex, with tolerant frontmatter handling, error tracking, and resume support.
- Minimal external ingest: a drop-folder (txt/md) feeding `external_raw` objects that are indexed but not rendered as notes in the vault.
- ASK FastAPI endpoint with answers + sources + latency, plus status API/CLI showing object counts per plane, ingest runs, and ASK metrics.
- Interim FastAPI-served GUI for status + ASK (no multi-user collaboration or advanced serendipity features yet).
- Orchestrator Runtime V1 for running external ingest plans, with dual execution paths: direct CLI (`ingest-external`) or plan-based orchestrator run via `orchestrate-external`.


I v4.10 är kärnan komplett:
	•	Store-abstraktion (ObjectStore, VectorIndex, RelationIndex, ReasoningStore)
	•	Outbox + Eventdriven pipeline
	•	Typed Relations + Promotion Gates
	•	Reasoning Layer v1 (Claim/Evidence/Inference)
	•	LLM-planering via Planner Agent
	•	A2A-protokoll för agent-till-agent kommunikation
	•	Orchestrator Runtime V1 för utvalda planer (t.ex. extern ingest) med A2A/MCP-hookar; mer avancerad orkestrering är v5.x-arbete.
	•	Fullt deterministisk CI via 8-line contract

🧭 Orchestrator Runtime (v4.10 — V1)

Orchestrator kör planer sekventiellt (flaggan `ORCHESTRATOR_ENABLE=1`):
- validerar steg och loggar `orchestrator.step.started|finished|error` för deterministisk spårbarhet,
- agent_call kör A2A-requests (default-agent svarar `not_implemented` om steget saknar stöd),
- tool_call validerar MCP-deskriptorer och kör mock/stubbar; interna verktyg inkluderar `internal.ingest_external` som kan köra extern drop-folder-ingest via orchestrator eller CLI (`orchestrate-external`).

Full LangGraph/MCP-bred orkestrering av hela pipelines (ingest → relate → reason → promote) är uttryckligen v5.x-arbete.

Det mänskliga lagret (vaulten) är frivilligt, men stöds alltid. Obsidian är endast en visuell client — systemets källa är Stores + Events.

⸻

🚀 Quickstart

Installera:

python -m pip install --upgrade pip
pip install -e .
pip install pytest

Kör pipeline med mock-LLM och memory backend:

export STORE_BACKEND=memory
export LLM_PROVIDER=mock
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

python -m app.cli pipe /tmp/demo.md
python -m app.fitness.report
python -m app.cli yggdrasil-init --root /tmp/yg-demo
LLM_TRACE_PATH=/tmp/llm-trace-sample.jsonl python -m app.cli llm-trace-sequence --latest --format mermaid > /tmp/llm-trace-seq.md

Du ska se 8-radig CI-sammanfattning:
LATENCY / EVAL / DELTA / RELATION COVERAGE / RELATIONS / DIARIZATION / REASONING / GATES

### Run Reality-MVP HTTP API locally

From the repo root:

```bash
source .venv/bin/activate

export STORE_BACKEND=pg
export DATABASE_URL="postgresql+psycopg://app:app@localhost:15432/app"
export VECTOR_BACKEND=pgvector

uvicorn app.main:app --reload --port 18000
```

- GET http://127.0.0.1:18000/api/status → system status snapshot
- POST http://127.0.0.1:18000/api/ask → ASK pipeline with sources + latency

### Bootstrap data for the dashboard & ASK

The dashboard and `/api/ask` will look “empty” until at least one object has been ingested into the ObjectStore and indexed. If the Stores table shows `vault: 0` and `external: 0` and ASK returns “No results found.”, it usually just means nothing has been ingested yet for the current `STORE_BACKEND` / `DATABASE_URL`.

From the repo root, run:

```bash
source .venv/bin/activate

export STORE_BACKEND=pg
export DATABASE_URL="postgresql+psycopg://app:app@localhost:15432/app"
export VECTOR_BACKEND=pgvector

python -m app.cli ingest-vault-root --limit 25
```

You can quickly verify that object counts are non-zero with:

```bash
python -m app.cli status
```

Then reload the dashboard at http://127.0.0.1:18000. The Stores table should show a non-zero object count for at least one store, and ASK will have something to retrieve.

If the Stores table still shows 0 objects after a successful ingest run, double-check that you are using the same STORE_BACKEND and DATABASE_URL settings when starting uvicorn and when running the ingest-vault-root CLI command.

⸻

🧠 Arkitektur — v4.10

Agent-pipeline

vault/markdown
    ↓ normalize        (Core-6 frontmatter)
    ↓ classify         (LLM or mock)
    ↓ chunk            (diarization-aware)
    ↓ embed            (VectorIndex + hybrid retrieval + optional rerank)
    ↓ relate           (typed relations)
    ↓ reason           (claims, evidence, inferences)
    ↓ plan             (Planner Agent — LLM or mock)
    ↓ orchestrate      (Orchestrator — executes plan via A2A + MCP)
    ↓ promote          (promotion gates + audit)

Stores (canonical persistence layer)

Store	Funktion
ObjectStore	Markdown-objekt + Outbox-event
VectorIndex	embeddings + hybrid retrieval + rerank
RelationIndex	typed relations + coverage/validity-guards
ReasoningStore	claim/evidence/inference-grafer
PlanStore (v4.10)	loggar planer + steps + execution graphs

All persistens går via Stores – aldrig direkt till DB.

⸻

🔁 Eventdriven modell

Alla agenter skriver Outbox-händelser:

object.created
index.object.embedded
relation.added
reasoning.claim.added
plan.created
a2a.request.created
a2a.response.created
promote.done

Outbox-formatet är identiskt mellan memory- och postgres-backends.
Händelser bär standardmetadata (event_type, trace_id, instance_id, created_at, source) så körningar kan spåras över tid och mellan instanser utan att ändra mänskliga flows.

⸻

📡 A2A-protokoll (Agent-to-Agent)

Infört i v4.8 och nu fullt implementerat i v4.10.
	•	JSON-schema valideras vid varje sändning.
	•	Request/Response/Error med spårbar trace_id.
	•	Alla agenter implementerar:

async def handle_agent_request(self, request: A2ARequest) -> A2AResponse:

A2A används av Orchestrator för att köra planer steg-för-steg.

⸻

🗺️ Planner Agent (LLM-driven planering)

Planner genererar strukturerade planer:

Plan:
  id: UUID
  steps: List[PlanStep]
  metadata: PlanMetadata

Planer genereras under ingest om:

export PLANNER_ENABLE=1

Provider:
	•	mock (deterministisk, CI-säker)
	•	llm (Ollama via OpenAI-kompatibel endpoint)

Alla planer loggas i PlanStore och Outbox.

⸻

🧭 Orchestrator Runtime (v4.10)

Orchestrator läser planer och exekverar dem via:
	1.	A2A-meddelanden mellan agenter (`send_agent_request` → `agent.error.created` när default-agent svarar `not_implemented`).
	2.	MCP-verktyg (validator + mock-resultat; `mcp.tool.call.started|finished` loggas, inga verktyg körs på riktigt).
	3.	Strict audit log (`orchestrator.step.*` för varje steg).

Stegvalidering (unik ID, uppfyllda dependencies) sker före körning. Exekveringen är sekventiell i v4.10A men flaggbar med `ORCHESTRATOR_ENABLE`. Fel går alltid via `orchestrator.step.error` så planstatus kan replikeras deterministiskt.

⸻

🧪 Reasoning Layer v1
	•	Claims
	•	Evidence
	•	Inferences

Allt valideras av schema.
Reasoning-resultat kopplas till relationsgrafen och påverkar promotion gates.

I CI används en 100% deterministisk MockDeliberationAgent.

⸻

🧵 Promotion Gates

Promotion kräver:
	•	Relation coverage ≥ 95%
	•	Minst 1 typed relation (om inte override är satt)
	•	Valid reasoning block
	•	Giltig diarization-chunking
	•	Outbox events skapade i rätt ordning

Overrides måste innehålla textreason.

⸻

⚙️ Miljövariabler (SoT v4.10)

Allmän drift

Flag	Default	Beskrivning
STORE_BACKEND	memory	memory / postgres
LLM_PROVIDER	mock	mock / ollama
AUDIT_LOG_PATH	unset	skriv JSONL-audit
LLM_MAX_RETRIES	3	bounded backoff
LLM_BASE_DELAY	0.1	retry-delay

Planner / Orchestrator

Flag	Default	Beskrivning
PLANNER_ENABLE	unset	aktiverar planer
PLANNER_PROVIDER	mock	mock / llm
ORCHESTRATOR_ENABLE	unset	aktiverar deterministiskt Orchestrator-skelett (A2A + MCP-mock)
MCP_REGISTRY_PATH	mcp.json	verktygsregister för Orchestrator

Relations & Promotion

Flag	Default	Beskrivning
PROMOTION_REQUIRE_RELATIONS	0	blockera orphans
PROMOTION_ALLOW_ORPHANS	unset	bypass
PROMOTION_ORPHAN_OVERRIDE_REASON	unset	krävs vid bypass

Rerank & Diarization

Flag	Default	Funktion
RERANK_ENABLE	unset	rerank hook
DIARIZE_ENABLE	unset	diarization
RERANK_PROVIDER	none	none/mock_ce/ce_local/ce_http


⸻

🧬 CI — 8-Line Contract

Alla körningar måste producera exakt:
	1.	LATENCY
	2.	EVAL
	3.	EVAL DELTA
	4.	RELATION COVERAGE
	5.	RELATIONS
	6.	DIARIZATION
	7.	REASONING
	8.	GATES

Referensvärden ligger i ops/quality/baselines.yaml.

⸻

🧭 Roadmap

v4.10 — Reality-MVP (Locked Baseline)
	•	Hardened ingest (vault + external) into ObjectStore/VectorIndex with tolerant frontmatter handling and resume/error tracking.
	•	Hybrid retrieval + ASK API with sources, plane/origin, and latency surfaced.
	•	Observability backend + status API/CLI + interim GUI for system status and ASK.
	•	Orchestrator Runtime V1 for external ingest plans (dual CLI/orchestrator path).
	•	8-line CI contract enforced as a gate for all runs.

Operational acceptance (4.10)
	•	Soak-runs on real vault and external sources (operational runs, not code changes).
	•	Fine-tuning thresholds and dashboards where needed.

v5.x — Agentic PKM / Forward Line
	•	PanelAgent / NoteInteractionAgent: AI panel actions mapped to Planner/Orchestrator.
	•	Satellite Sync: master–satellite protocol for second-brain instances (`docs/PROTOCOL_SATELLITE_SYNC.md`).
	•	Yggdrasil modules: Munin (media/memories), Brokkr (project workshop), Tyr (formal archives) as first-class domains on top of the Stores.
	•	Orchestrator/Reasoning 2.0: richer LangGraph/MCP-based execution, more pipelines, and deeper agentic planning built on the locked v4.10 baseline.

⸻

📚 Dokumentation
	•	ARCHITECTURE￼
	•	ROADMAP￼
	•	STATUS￼
	•	TESTING￼
	•	CI￼
	•	CHANGELOG￼
