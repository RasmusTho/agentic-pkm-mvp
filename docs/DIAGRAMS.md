State: SoT v5.5 Reality-MVP baseline locked with v5.6 forward line notes. Diagrams here reflect the current runtime shape and should be updated when boundary maps or major flows change.
Doc role: Reference
Authority: Current visual companion to `docs/ARCHITECTURE.md`, `docs/COMPONENTS.md`, and `docs/EVENTS.md`; diagrams are explanatory and must not override the text contracts.
# Diagrams

This document contains current diagrams for the active runtime.

Use it as a visual companion to:
- `docs/ARCHITECTURE.md` for boundary and runtime shape
- `docs/COMPONENTS.md` for component ownership
- `docs/EVENTS.md` for event contracts
- `docs/DESIGN_PRINCIPLES.md` for the higher-level design rules that these diagrams do not own

Historical diagrams live in `docs/archive/architecture/DIAGRAMS.md`.

Reading note:
- these diagrams show current runtime wiring and operator-visible flow,
- not the full target-state architectural decomposition,
- and not the complete design-layer distinction between interaction, cognition, execution, memory, and governance.

## System Boundary

This diagram shows the current v5.5 runtime boundary: vault-first surfaces, repository-owned runtime code, and external runtime dependencies.

```mermaid
flowchart LR
  classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111827
  classDef dep fill:#fff7ed,stroke:#c2410c,color:#7c2d12
  classDef code fill:#ecfeff,stroke:#0e7490,color:#083344
  classDef iface fill:#eef2ff,stroke:#4338ca,color:#1e1b4b,stroke-width:2px

  subgraph EXT["Outside The System Boundary"]
    User["Human User"]
    ApiClient["API Client"]
    LlmProvider["LLM / Embedding Providers"]
  end

  subgraph DEP["Runtime Dependencies"]
    Vault["Obsidian Vault Filesystem"]
    Obsidian["Obsidian App"]
    Pg["Postgres + pgvector"]
    Obs["Prometheus / Grafana (optional)"]
  end

  subgraph CODE["Repository Runtime"]
    Api["FastAPI API"]
    Watcher["Registry Watcher"]
    Worker["Outbox Worker"]
    Ask["ASK / Retrieval"]
    Panel["Panel Runtime"]
    Ingest["Ingest Pipeline"]
    Settings["Settings / Contracts"]

    subgraph IFACE["Internal Boundaries"]
      VaultPort["VaultPort"]
      Stores["ObjectStore / VectorIndex / RelationIndex"]
      Outbox["DB Outbox (canonical)"]
    end
  end

  User --> Vault
  User --> Obsidian
  ApiClient --> Api
  Api --> Ask
  Ask --> Stores
  Ask --> LlmProvider

  Vault --> Watcher
  Watcher --> Panel
  Watcher --> Ingest
  Watcher --> Outbox

  Panel --> Outbox
  Ingest --> Stores
  Ingest --> Outbox
  Worker --> Outbox
  Worker --> Stores
  Worker --> VaultPort

  VaultPort --> Vault
  Stores --> Pg
  Outbox --> Pg
  Api --> Pg
  Api --> Obs
  Worker --> Obs
  Settings --> Api
  Settings --> Watcher
  Settings --> Worker

  class User,ApiClient,LlmProvider ext
  class Vault,Obsidian,Pg,Obs dep
  class Api,Watcher,Worker,Ask,Panel,Ingest,Settings code
  class VaultPort,Stores,Outbox iface
```

## Runtime Event Flow

This diagram shows the current canonical runtime loop: watcher and runtime components emit DB-outbox events, and the worker consumes them for indexing and follow-up side effects.

```mermaid
flowchart LR
  Vault["Vault Note Change"] --> Watcher["Registry Watcher"]
  Watcher --> Scan["panel.scan.requested / ingest.vault.changed"]
  Scan --> Outbox["DB Outbox (canonical queue)"]

  PanelCli["panel run-many / panel runtime"] --> PanelIntent["panel.intent.created / panel.intent.executed"]
  PanelIntent --> Outbox

  Ingest["Ingest Pipeline"] --> Store["ObjectStore"]
  Ingest --> IndexReq["index.embedding.requested"]
  IndexReq --> Outbox

  Outbox --> Worker["Outbox Worker"]
  Worker --> Indexer["Indexer Consumer"]
  Indexer --> Vector["VectorIndex"]
  Indexer --> IndexDone["index.embedding.created"]

  Worker --> Promotion["Promotion Consumer"]
  Promotion --> PromoteDone["promote.intent.created / promote.done"]

  Store --> Ask["ASK API / Retrieval"]
  Vector --> Ask
  IndexDone --> Ask
```

## Human-Facing Flow

This diagram emphasizes the user-visible path through vault notes, panel execution, and ASK.

```mermaid
flowchart TD
  User["Human User"] --> Note["Vault Note In Obsidian"]
  Note --> Fence["AI Panel / Action Fence"]
  Fence --> Watcher["Registry Watcher Or Manual Panel Run"]
  Watcher --> Panel["Panel Runtime"]
  Panel --> Intent["panel.intent.created"]
  Intent --> Exec["panel.intent.executed"]
  Exec --> Promote["Optional promote.intent.created"]
  Exec --> Ingest["Optional ingest / index follow-up"]

  Ingest --> Stores["Stores + Indexes"]
  Stores --> Ask["/api/ask"]
  Ask --> Answer["Answer + Sources"]
  Answer --> User
```

## Directional Reading Notes

- In the current runtime view, Panel appears as the mutation-capable interaction surface.
- ASK appears as the current question-answering surface, but should not be read as the long-term architectural center of retrieval or reasoning.
- These visuals emphasize current event and worker wiring; they do not replace the capability-oriented and system-of-systems framing in `docs/ARCHITECTURE.md` and `docs/DESIGN_PRINCIPLES.md`.

## Notes

- Canonical queue: DB outbox. JSONL remains audit/diagnostic only.
- Current watcher default: registry watcher, not the legacy snapshot watcher.
- Diagrams should be revised when runtime boundaries, major event paths, or operator entrypoints change.
