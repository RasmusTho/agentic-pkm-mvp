State: SoT v4.10 Reality-MVP (current).
# Diagrams

These diagrams reflect the active Reality-MVP architecture (SoT v4.10). They are derived from `docs/SYSTEM_DESIGN_v4.10.md`, `docs/ARCHITECTURE.md`, `docs/COMPONENTS.md`, and `docs/HUMAN-FLOWS.md`. Rendered with Mermaid; export via `mmdc` if needed.

<!-- SECTION:DIAGRAMS:BEGIN -->
## System Context (C4 Level 1)
```mermaid
flowchart LR
    user["Human user"]:::actor
    obsidian["Obsidian vault (Mimer)"]:::actor
    api["PKM API / Agents (Yggdrasil)"]:::system
    ollama["Ollama LLM server"]:::ext
    db["Postgres / pgvector"]:::ext
    observability["Grafana / Prometheus / Loki"]:::ext
    git["Git / GitHub (code + docs + VaultMirror)"]:::ext

    user <--> obsidian
    user -->|ASK / CLI| api
    obsidian -->|vault sync / ingest| api
    api -->|LLM calls| ollama
    api -->|stores / vector| db
    api -->|metrics / logs| observability
    api -->|code + docs + VaultMirror| git

    classDef actor fill:#f0f8ff,stroke:#1a4,stroke-width:1px;
    classDef system fill:#e8f5ff,stroke:#06c,stroke-width:2px;
    classDef ext fill:#fdf6e3,stroke:#b58900,stroke-width:1px;
```
The Agentic PKM system sits between the human/vault surfaces and local dependencies: Postgres/pgvector for stores, Ollama for LLM/embeddings, and Grafana/Prometheus/Loki for observability. Git/GitHub hold code/docs and VaultMirror snapshots.

## Container / Runtime Topology (C4 Level 2)
```mermaid
flowchart LR
    subgraph host[Local host / Colima]
        api["FastAPI service 18000/8000"]
        agent["Agent runtime / workers"]
        pg["Postgres + pgvector 15432/5432"]
        ollama["Ollama 11434"]
        grafana["Grafana 3000"]
        prometheus["Prometheus 9090"]
        loki["Loki 3100"]
    end

    cli["CLI entrypoints"]:::actor
    obsidian["Obsidian vault (PKM-Alpha)"]:::actor
    git["Git/GitHub"]:::actor

    cli -->|ingest / ask| api
    obsidian -->|vault sync| api
    api --> agent
    api --> pg
    agent --> pg
    api --> ollama
    agent --> ollama
    api --> prometheus
    api --> loki
    grafana --> prometheus
    grafana --> loki
    git --> api

    classDef actor fill:#f0f8ff,stroke:#1a4,stroke-width:1px;
```
Ports align with `docs/SYSTEM_DESIGN_v4.10.md`: API 18000→8000, Postgres 15432→5432, Ollama 11434, Grafana 3000, Prometheus 9090, Loki 3100.

## Core Components (C4 Level 3)
```mermaid
flowchart TB
    subgraph app[Application Container]
        api_layer["API layer<br/>app/api"]
        cli_layer["CLI commands<br/>app/cli"]
        agents["Agents<br/>app/agents"]
        services["Services<br/>app/services"]
        components["Components<br/>embeddings/rerankers/LLM"]
        retrieval["Retrieval<br/>app/retrieval"]
        stores["Stores<br/>app/store, app/stores, Outbox"]
        eval["Eval/QA<br/>app/eval, tests"]
    end

    provider["Ollama / providers"]:::ext
    db["Postgres/pgvector"]:::ext
    vault["Obsidian vault"]:::ext

    api_layer --> agents
    api_layer --> services
    api_layer --> components
    cli_layer --> agents
    cli_layer --> services
    agents --> components
    agents --> services
    agents --> stores
    retrieval --> components
    retrieval --> stores
    services --> stores
    components --> provider
    stores --> db
    agents --> vault

    classDef ext fill:#fdf6e3,stroke:#b58900;
```
API/CLI call into agents/services; agents and retrieval depend on components and store abstractions (not raw DB or provider SDKs). Components encapsulate provider calls (Ollama). Stores wrap Postgres/pgvector and Outbox. See `docs/COMPONENTS.md` for detailed catalog and dependency rules, `docs/SYSTEM_DESIGN_v4.10.md` for topology, and `docs/HUMAN-FLOWS.md` for how humans experience these flows.

### Historical diagrams (superseded)
Older v4.5 ingestion/promotion diagrams are retained below for reference but are superseded by the Reality-MVP views above.

#### Ingestion → Stores → QA (v4.5)
```mermaid
flowchart LR
    CLI[CLI / API Source] -->|normalize| NORMALIZER[Normalizer Agent]
    NORMALIZER -->|save_object| OBJECTS[ObjectStore]
    OBJECTS -->|emit_outbox| OUTBOX[Index Outbox JSONL]
    OUTBOX -->|fan-in| VECTOR[VectorIndex]
    OUTBOX -->|provenance| REL[RelationIndex]
    VECTOR -->|hybrid_search| QA[QA Agent]
    QA -->|audit_log| AUDIT[Audit JSONL Buffer]
    QA -->|enforce_quality| GUARD[Guardrails]
    GUARD --> ANSWER[Answer + Sources]
```

#### Promotion → Reasoning Prep (v4.5)
```mermaid
flowchart TD
    INTENT["promote.intent.created"] --> PROMO["Promotion Agent"]
    PROMO -->|validate cooldown| CHECK["Policy + cooldown"]
    PROMO -->|update frontmatter| VAULT["ObjectStore"]
    PROMO -->|emit provenance| REL2["RelationIndex"]
    VAULT -->|emit_outbox=False| QUIET["(No loop)"]
    PROMO -->|promote.done| OUTBOX2["Index Outbox"]
    OUTBOX2 --> INDEXER["Index / Rerank Workers"]
    REL2 --> REASON["Reasoning Layer (RDF/OWL draft)"]
```

### Export to PNG/SVG
1. Install Mermaid CLI locally: `npm install -g @mermaid-js/mermaid-cli`.
2. Copy a block into an `.mmd` file or run `mmdc -i docs/DIAGRAMS.md -o artifacts/docs-diagrams.svg --page --scale 1`.
3. Store exported images under `docs/diagrams/` if they should be versioned; CI only requires the source Markdown.
<!-- SECTION:DIAGRAMS:END -->
