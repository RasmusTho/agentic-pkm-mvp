# Yggdrasil: Modules and Flows

High-level map of modules and how material moves between them. This orients intent and responsibilities; detailed technical design, data contracts, and runtime specifics live in `docs/ARCHITECTURE.md`.

In SoT v4.10 this codebase primarily implements the Mimer module (the Obsidian vault + ingestion/indexing/agents). The other Yggdrasil modules (Hugin, Munin, Ratatosk, Brokkr, Tyr, Heimdall) are currently partly conceptual and/or handled by external tools and file-system organization.

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
- Obsidian Git-automation (Obsidian Git-plugin eller motsvarande) är en nyckel i Mimers synkväv: den commitar/pushar/pullar Markdown-noter och per-note-loggar så text och loggar är portabla mellan instanser.
- Automationen ligger i Machina/Heimdall-lagret: infrastruktur vi lutar oss mot men inte helt styr själva.
- Eftersom Git kan skriva vid sidan av agenterna måste systemet tåla out-of-band-commits och merges; agenter kan inte anta att de är ensamma skribenter.

### Flows between Modules
- Brokkr contains full project folders; `Mimer/Projects` holds each project’s semantic brain (status, decisions, links) and references Brokkr outputs instead of copying them.
- Munin stores raw media; `Mimer/Sources` and `Mimer/Corpus` interpret, transcribe, and link to it with citations.
- Tyr stores formal records; Mimer captures interpretations, approvals, and downstream decisions while preserving pointers back to Tyr.
- Ratatosk is the ingestion path that moves material into Munin/Brokkr/Tyr and seeds appropriate stubs in Mimer so agents can classify, link, and plan follow-up work.

### Deployment & instances (high level)
- Yggdrasil kan köras som en eller flera logiska instanser för samma människa (t.ex. en “home”-master på en Mac mini plus satelliter på arbetslaptop eller kontorsmaskin).
- Varje runtime har `InstanceSettings` (`settings.instance.id` och `settings.instance.role`), med default `id: home`, `role: master` så Reality-MVP förblir en singel runtime.
- Alla events bär `instance_id` och märker vilken runtime som emitterade dem, så audit/Outbox kan särskilja master och framtida satelliter.
- Multi-instanssynk och master/satellit-protokoll är inte färdiga ännu; de dokumenteras separat när protokollet landar.
