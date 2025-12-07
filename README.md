State: SoT v4.10 Reality-MVP (current).
# Agentic PKM / Yggdrasil — Reality-MVP

Agentic PKM is a vault-first, agent-driven personal knowledge system. It pairs a human-facing Obsidian vault (Mimer) with a machine “System of Truth” (Stores, Outbox events, agents, retrieval) to ingest notes, answer questions, and keep provenance and quality guardrails intact.

## What this system is
- Single-user Reality-MVP focused on reliable vault ingestion, hybrid ASK retrieval, and basic observability.
- Human surface: Obsidian vault with minimal frontmatter; machine surface: ObjectStore + VectorIndex + Outbox-driven agents.
- See `docs/SYSTEM_DESIGN_v4.10.md` and `docs/ARCHITECTURE.md` for the full system design and internal contracts.

## Key capabilities (human flows)
- **Capture & Ingest** — Safe, idempotent ingest of vault notes into Stores + VaultMirror. (`docs/HUMAN-FLOWS.md`, `docs/COMPONENTS.md`)
- **ASK / Retrieval** — Hybrid search (BM25 + embeddings + optional rerank) with sources and latency. (`docs/AGENTS.md`, `docs/HUMAN-FLOWS.md`)
- **Panel Interaction** — PanelAgent turns in-note AI panels into intents/events without polluting the knowledge base. (`docs/PANEL_AGENT.md`)
- **Review & Promotion** — Promotion gates and provenance logged via Outbox and VaultMirror. (`docs/HUMAN-FLOWS.md`, `docs/STATUS.md`)
- **Eval/QA (opt-in)** — DeepEval and Ragas suites for diagnostics. (`docs/eval.md`)

## Quickstart (local)
Prereqs: Python 3.11+, Docker/Colima, Git. For LLM calls use Ollama (e.g., `llama3.1:8b`) via its OpenAI-compatible endpoint; Postgres/pgvector recommended for persistence (memory backend works for quick runs).

```bash
# clone and enter
git clone https://github.com/RasmusTho/agentic-pkm-mvp.git
cd agentic-pkm-mvp

# optional: create venv and install
python -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# run API with memory stores and mock LLM (fast path)
export STORE_BACKEND=memory
export LLM_PROVIDER=mock
PYTHONPATH="$(pwd)" uvicorn app.main:app --reload --port 18000
```

Ingest a sample vault folder and query:
```bash
python -m app.cli ingest-vault-root --limit 10
curl -X POST http://127.0.0.1:18000/api/ask -H "Content-Type: application/json" \
  -d '{"question": "What is the Reality-MVP focus?"}'
```

For Postgres/pgvector runs and observability details, see `docs/SYSTEM_DESIGN_v4.10.md`, `docs/OBSERVABILITY_STACK.md`, and `docs/OPERATIONS.md`.

## Architecture and components
- System topology: `docs/SYSTEM_DESIGN_v4.10.md`, `docs/DIAGRAMS.md`
- Internal architecture/contracts: `docs/ARCHITECTURE.md`
- Human flows and behaviors: `docs/HUMAN-FLOWS.md`
- Component catalog and dependency matrix: `docs/COMPONENTS.md`
- Agents overview: `docs/AGENTS.md`, `docs/PANEL_AGENT.md`

## Development workflow
- How to work on the codebase: `docs/DEV_WORKFLOW.md`
- AI-assisted development policy: `docs/AI_DEVELOPMENT.md`
- Testing and eval: `docs/TESTING.md`, `docs/eval.md`, `docs/CI.md`, `docs/QUALITY.md`, `docs/guardrails.md`

## Status and roadmap
- Current state: `docs/STATUS.md` (Reality-MVP, SoT v4.10)
- Planned work: `docs/ROADMAP.md`

## License
See `LICENSE` (if present in this repository).
