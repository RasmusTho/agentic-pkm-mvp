State: Historical (SoT v4.10). Module map retained for reference; it may not reflect the v5.5 baseline wiring.

Historical reference only:
- Use this document for naming continuity and background orientation.
- Do not treat it as the active system map for current behavior; use `docs/ARCHITECTURE.md` and `docs/HUMAN-FLOWS.md` first.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Yggdrasil: Modules and Flows

High-level map of modules and how material moves between them. This orients intent and responsibilities; detailed technical design, data contracts, and runtime specifics live in `docs/ARCHITECTURE.md`.

In SoT v4.10 this codebase primarily implements the Mimer module (the Obsidian vault + ingestion/indexing/agents). The other Yggdrasil modules (Hugin, Munin, Ratatosk, Brokkr, Tyr, Heimdall) are currently partly conceptual and/or handled by external tools and file-system organization.

| Module | Role / Domain | Concrete artefacts (v4.10) |
| --- | --- | --- |
| Mimer | Knowledge surface | Obsidian vault PKM-Alpha (+ sub-vaults) |
| Hugin | Agents / reasoning | `app/agents/*`, ASK graph, PanelAgent, DeliberationAgent |
| Munin | Media & raw memories (planned v5.x) | Planned; see ROADMAP for media/raw ingestion |
| Ratatosk | Ingest & pipelines | `app/ingest/*`, CLI `pipe`, Outbox events |
| Brokkr | Project workshop (planned v5.x) | Planned: project workspaces/tools |
| Tyr | Formal archives (planned v5.x) | Planned: admin/records integration |
| Heimdall | Infra & observability | Observability stack (Grafana/Prometheus/Loki) |

See `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md` for how these modules map onto deployment topology and surfaces.

## Modules at a glance
- **Mimer — Knowledge (Obsidian vault)**: Human-first vault with notes, ontology, and semantic links; minimal frontmatter plus UUID identity. Acts as the cognitive graph that threads together interpretations of media, records, and projects. Provides Core-6 projections and references (e.g., `source_ref`) into other modules without duplicating their artifacts. This is the same vault historically referred to as PKM-Alpha.
- **Hugin — Intelligence & agents**: Hosts agent profiles, policies, reasoning traces, plans, and experiments. Runs ASK/QA, reasoning loops, and evaluator workflows that read from Mimer and stores, then emit structured spans and decisions. Optimized for explainable, replayable agentic behavior rather than storage.
- **Munin — Media & raw memory**: Holds photos, audio, video, recordings, and ebooks/audiobooks in original or lightly processed form. Serves as the media source of truth; derived transcripts or annotations link back into Mimer via citations and `source_ref`. Supports indexing hooks without altering the originals.
- **Ratatosk — Ingestion & pipelines**: Inbox and ETL flows that capture material from devices, apps, or external feeds. Normalizes and routes payloads into Munin/Brokkr/Tyr as appropriate while seeding stubs in Mimer for interpretation. Prioritizes idempotent, auditable moves with Outbox events for agents.
- **Brokkr (tentative) — Project workshops**: One folder per project holding all deliverables (slides, code exports, spreadsheets, CAD, renders). Mirrors execution outputs while Mimer/Projects hosts the semantic view (decisions, status, links). Encourages co-location of artifacts and narratives without mixing storage responsibilities.
- **Tyr — Formal records**: Receipts, invoices, contracts, legal/admin documents, and mail archives. Acts as the immutable record system; interpretations, summaries, and decisions based on these records live in Mimer, preserving provenance and trust levels.
- **Heimdall — Infra & observability**: Deployment/configuration plus system logs, metrics, dashboards, and runbooks. Ensures agents and services stay observable, with runtime health surfaced to operators and feedback loops back into agent policies when needed.

### Mimer: Knowledge Module (Obsidian Vault)
Mimer is the cognitive hub. It hosts human-authored notes and semantic structures while linking to other modules via explicit references (e.g., `source_ref` to Munin/Tyr/Brokkr). Internal folders:
- `Index/`: entry points, maps, and dashboards for navigation.
- `Workspace/`: active working notes and scratchpads.
- `Ingress/`: newly captured items awaiting triage.
- `Projects/`: semantic “brain” per project (status, decisions, links to Brokkr artifacts).
- `Domains/`: area notes and domain knowledge.
- `Corpus/`: interpreted content derived from sources (e.g., transcripts, summaries).
- `Sources/`: source cards pointing to Munin media, Tyr records, or Brokkr outputs.
- `Ontology/`: schemas, types, and relationship definitions.
- `Taxonomy/`: controlled vocabularies and tags.
- `Canon/`: evergreen, durable knowledge.
- `Archive/`: retired or cold material kept for reference.
- `Machina/`: AI/agent scaffolding, prompts, and panel definitions tied to the vault surface.

### Hugin vs Heimdall
- Hugin owns agents and reasoning: profiles, policies, reasoning traces, generated plans, experiments, and ASK/QA logic.
- Heimdall owns runtime and observability: deployment/configuration, system logs, metrics, dashboards, and operational runbooks.
- "Agents conceptually belong to Hugin (intelligence), while Heimdall is responsible for infrastructure and observability. Hugin holds the 'mind', Heimdall the 'machinery'."

### Git & Obsidian automation
- Obsidian Git automation (Obsidian Git plugin or equivalent) is a key part of Mimer’s sync fabric: it commits/pushes/pulls Markdown notes and per-note logs so text and logs stay portable between instances.
- The automation lives in the Machina/Heimdall layer: infrastructure we rely on but do not fully control.
- Because Git can write alongside agents, the system must tolerate out-of-band commits and merges; agents cannot assume they are the only writers.

### Flows between Modules
- Brokkr contains full project folders; `Mimer/Projects` holds each project’s semantic brain (status, decisions, links) and references Brokkr outputs instead of copying them.
- Munin stores raw media; `Mimer/Sources` and `Mimer/Corpus` interpret, transcribe, and link to it with citations.
- Tyr stores formal records; Mimer captures interpretations, approvals, and downstream decisions while preserving pointers back to Tyr.
- Ratatosk is the ingestion path that moves material into Munin/Brokkr/Tyr and seeds appropriate stubs in Mimer so agents can classify, link, and plan follow-up work.

### Deployment & instances (high level)
- Yggdrasil can run as one or more logical instances for the same human (e.g., a “home” master on a Mac mini plus satellites on a work laptop or office machine).
- Each runtime has `InstanceSettings` (`settings.instance.id` and `settings.instance.role`), defaulting to `id: home`, `role: master` so Reality-MVP remains a single runtime.
- All events carry `instance_id` to mark which runtime emitted them, letting audit/Outbox distinguish master and future satellites.
- Multi-instance sync and master/satellite protocols are not finalized; they will be documented separately once the protocol lands.
