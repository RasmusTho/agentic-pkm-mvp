Agentic PKM — Second-Brain Engine

System-of-Truth v4.10 (Active Baseline)

Agentic PKM är ett agentdrivet, eventstyrt och CI-säkrat system för personlig kunskapshantering.
Det använder ett mänskligt gränssnitt (Markdown-vault) och ett maskinellt ”System-of-Truth” bestående av Stores, Outbox-händelser och en flerstegs agent-pipeline.

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

Current focus — Reality-MVP
- Harden real-vault ingestion (selected folders) and provenance into ObjectStore + VectorIndex.
- Minimal external ingest (newsletters/PDFs) into `external_raw` objects indexed but not rendered as notes.
- Ship ASK FastAPI endpoint with answers + sources + latency plus status CLI/backend (object counts, ingest runs, ASK usage).
- Provide an interim FastAPI-served GUI for status + ASK; collaboration/multi-user and advanced serendipity/reflection features are explicitly deferred.


I v4.10 är kärnan komplett:
	•	Store-abstraktion (ObjectStore, VectorIndex, RelationIndex, ReasoningStore)
	•	Outbox + Eventdriven pipeline
	•	Typed Relations + Promotion Gates
	•	Reasoning Layer v1 (Claim/Evidence/Inference)
	•	LLM-planering via Planner Agent
	•	A2A-protokoll för agent-till-agent kommunikation
	•	Orchestrator runtime som exekverar planer och använder MCP-verktyg säkert
	•	Fullt deterministisk CI via 8-line contract

Orchestrator-skelettet (SoT v4.10A) kör varje plan deterministiskt när `ORCHESTRATOR_ENABLE=1`: varje steg loggar `orchestrator.step.started|finished|error`, agent-steg skickar riktiga A2A-requests (default-agent svarar med `not_implemented`) och MCP-steg kör mot stubbade `mock_result` utan side effects. CI får därmed full plan → exekvering-länk utan att röra disk eller externa verktyg.

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

Du ska se 8-radig CI-sammanfattning:
LATENCY / EVAL / DELTA / RELATION COVERAGE / RELATIONS / DIARIZATION / REASONING / GATES

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

I CI används en 100% deterministisk MockReasoner.

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

v4.10 — Delivered
	•	Full Orchestrator runtime
	•	Planner Agent exekverad via A2A
	•	MCP-tool integration
	•	PlanStore och execution graph
	•	Stabil ingestion → plan → orchestrate → promote

v4.11 — In progress
	•	Persistence för execution graphs
	•	Self-healing planner hints
	•	Time-travel debugging (event replay)

v5.x — Research
	•	Multi-agent reasoning (graph-level)
	•	Symbolic constraints (OWL/RDF)
	•	SetDB som fristående backend
	•	Hypergraph-query engine

⸻

📚 Dokumentation
	•	ARCHITECTURE￼
	•	ROADMAP￼
	•	STATUS￼
	•	TESTING￼
	•	CI￼
	•	CHANGELOG￼
