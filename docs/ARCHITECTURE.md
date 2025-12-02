# Architecture — SoT v4.10 Reality-MVP

System map: `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md` covers the high-level Yggdrasil modules and flows; this document remains the detailed technical architecture.

`docs/HUMAN-FLOWS.md` captures the intended human experience and interaction flows; any architecture change that alters user-facing behavior should be validated against that contract before shipping.

This architecture focuses on the runtime and data model for the Mimer module (the Obsidian vault + ingestion/indexing/agents) within the broader Yggdrasil system. A high-level overview of Yggdrasil’s modules and flows lives in `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`, and human interaction patterns in `docs/HUMAN-FLOWS.md`.

### Instance model (internal master/satellite plumbing)
- SettingsBundle innehåller `instance` med `id` (t.ex. `home`, `work`, `laptop`) och `role` (`master` eller `satellite`).
- Default när inget är konfigurerat: `id="home"` och `role="master"`, vilket matchar Reality-MVP:s singelruntime-fokus.
- Scope: endast intern plumbing som informerar events/loggar och framtida sync-topologi; ingen ändring av Obsidian-ytan eller frontmatter.

## Reality-MVP Orientation
- Primary focus: make ingestion of the real Obsidian vault stable, add a minimal external ingest path, expose a reliable ASK API, and ship observability plus an interim GUI so the system is usable end to end.
- Zoned cognition overlay (Active/ Warm/ Cold) applied on top of the knowledge base; zones are derived from signals (usage, recency, trust) rather than folder names.
- Two planes: Obsidian vault as the human graph (LYT + PARA) with minimal human frontmatter, and an external corpus plane (newsletters/emails/PDFs) that is indexed and retrievable but never rendered as Obsidian notes.
- Metadata backbone lives in Stores + SetDB/AMG: Core-6 frontmatter remains a projection for humans, while system metadata (signals, relations, usage counts, agent reflections) sits in the data layer.
- Collaboration/multi-user stays out of scope for Reality-MVP; the current work is single-user, vault-first reliability.

## Zoned Cognition Overlay
- Active (Hot): the few items currently competing for conscious attention; small, rotating set.
- Semi-Active (Warm): ongoing projects/areas referenced regularly but not hourly.
- Peripheral (Cold): long-term or background material that should stay searchable without cluttering the surface; Cold can still contain evergreen, high-value notes.
- Zones are orthogonal to lifecycle (inbox → processed/staging → evergreen → archived) and to temporal value (ephemeral vs normal vs evergreen longevity). A note can be evergreen and Cold, or ephemeral and Active.
- Zones are derived overlays driven by system metadata (recency, relations, usage), not mandatory folder/tag names; they can be projected into ASK responses and GUI status but do not dictate file layout.

## Planes and Metadata Surfaces
- Vault plane (Obsidian): the human graph of linkable notes; minimal human frontmatter is allowed/encouraged, but the system does not require heavy YAML. Notes belong here when the user might want to read or link them directly.
- External corpus plane: imported newsletters/emails/PDFs/raw docs that should be searchable and usable for answers but should not appear as notes. These objects live only in Stores/AMG with origins such as `origin: external_newsletter` and review states like `external_raw`.
- Human frontmatter vs system metadata: frontmatter is for user-facing fields (uuid, title, type/status/area); system metadata (signals, zone inference inputs, relations, promotions, usage counts) remains in SetDB/AMG and Stores. Core-6 remains a projection ({uuid, title, origin, review_state, trust, source_ref}) and is not the full truth.

### Note Log i metadata-spegeln
- För varje objekt/uuid i valvet finns en motsvarande `uuid.md` i metadata-spegeln (`System/Metadata/VaultMirror/<vault-relativ path>/`).
- Samma fil är metadata-spegel och per-note-logg: den samlar körningar från agenter, promotionshändelser, proveniens och ev. satellit-synk-bevis så att maskinhistoriken följer objektet oavsett backend.
- Note Log är portabel Markdown som kan flyttas via Git mellan instanser även om SetDB/AMG eller andra Stores skiljer sig.

## Reality-MVP Architecture Components
1) **Vault ingestion** — CLI/agent path to ingest selected Obsidian folders, normalize into Core-6 envelopes, persist in ObjectStore, emit Outbox events, chunk/index into VectorIndex, and keep provenance intact.
2) **External corpus ingest (minimal)** — a small drop folder/pipeline for real external documents ingested as `external_raw` objects, stored in ObjectStore and indexed without surfacing as vault notes.
3) **ASK API** — FastAPI endpoint returning answer text plus sources `{uuid, title, origin (vault/external), zone if known, path/source_ref}` and latency; uses hybrid retrieval over both planes with zone-aware overlays.
4) **Observability backend** — status service that aggregates per-store object counts (vault vs external), ingest timestamps/errors, and ASK query counts/latency; exposed via CLI and interim GUI.
5) **Interim GUI** — simple FastAPI-served page that shows status (object counts, last ingest, ASK stats) and an ASK input with answers + visible sources; explicitly a temporary observability/interaction surface.
All Reality-MVP components run on the existing PER-loop agents (Normalizer, Classifier, Chunker, CitationChecker, Indexer, Reviewer, Promotion Agent) and Store abstraction (ObjectStore, VectorIndex, RelationIndex) with Outbox-driven events and Projector/Planner/Reasoning layers kept as additive overlays.
Advanced zone logic, reflection workflows, serendipity, and collaboration are deferred until the Reality-MVP foundation is solid.

## Archival Baseline (SoT v4.5A Canon)
The sections below retain the v4.5A Canon details as a historical baseline; invariants still apply unless superseded by the Reality-MVP notes above.

## Purpose & Principles
- Human-first and agentisk PKM: agents stay assistive, preserve author context, and only advance maturity when a reviewer signs off.
- Observability-first to främja transparens: every agent emits structured audit spans plus deterministic fixtures so regressions reproduce in CI.
- Core-6 frontmatter & UUID identity: each object carries the Core-6 envelope (id, type, title, created, updated, origin) and a stable UUID threaded through stores and events.
- Store abstraction & Outbox events: ObjectStore, VectorIndex, and RelationIndex share a Store interface, while the Outbox broadcasts change events for asynchronous consumers.
- Separation of trust and audit: trust levels gate promotion; audit trails remain append-only so reviewers can replay any decision independently.

## Core Architecture

### Runtime Surfaces
Centralized reference for HTTP apps and ports during local development and docker-compose runs.

#### HTTP Apps
| Module | Variable | Purpose | Primary Routes / Notes | How to Run |
| --- | --- | --- | --- | --- |
| `app.main` | `app` | Reality-MVP PKM HTTP API (status + ASK + interim GUI) | `/api/status`, `/api/ask`, optional `/api/ingest`, `/api/search`, `/` serves static dashboard | `uvicorn app.main:app --reload --port 18000` (docker-compose maps container `8000` → host `18000`) |
| `app.legacy_http` | `app` | Legacy agent/interesting/demo endpoints | `/agent/health`, `/interesting`, `/dashboard`; uses stub repo in lifespan | `uvicorn app.legacy_http:app --reload --port 18001` (dev-only) |
| `app._legacy.main` | `app` | Deprecated pre-Reality API with rate limits/metrics | `/`, `/health`, `/version`, `/context`, `/items`, `/ingest`, `/search`, agent/ui routes; requires DB + settings | `uvicorn app._legacy.main:app --reload` (not recommended for new runs) |
| `api.app` | `app` | WS golden-data demo API | `/query` returns mock answer + citations from `golden/` | `uvicorn api.app:app --reload --port 8001` when needed |

#### Ports
| Service | Purpose | Default Port | How it’s exposed / notes |
| --- | --- | ---: | --- |
| Reality-MVP HTTP API | PKM status + ASK endpoints | 18000 | Run locally via `uvicorn app.main:app --reload --port 18000`; docker-compose exposes container `8000` on host `18000`. |
| Postgres (app DB) | Stores/agents persistence | 15432 | `db` service in `docker-compose.yaml` listens on 5432 in-container; default DSN `postgresql+psycopg://app:app@localhost:15432/app`. |
| OTLP collector (optional) | Traces via OpenTelemetry Collector | 4318 (HTTP) / 4317 (gRPC) | Endpoints configured in `otelcol.yaml`; point trace exporters at `http://localhost:4318` when running a collector. |
| Prometheus (optional) | Metrics scrape endpoint | 9090 | `ops/observability/docker-compose.yaml` publishes Prometheus on 9090. |
| Grafana (optional) | Observability UI | 3000 | `ops/observability/docker-compose.yaml` publishes Grafana on 3000 with admin/admin defaults. |

This table supersedes the prior `docs/PORTS.md` listing.

### Agents
- Normalizer — accepts capture payloads, enforces Core-6 fields, and strips unsafe metadata.
- Classifier — tags object type, topic facets, and routing hints for downstream agents.
- Chunker — segments normalized text into retrieval-ready spans plus embedding metadata stubs.
- Deduper — compares against prior hashes and emits relation records for duplicates or merges.
- CitationChecker — validates outbound references and attaches citation debt metrics.
- Indexer — materializes embeddings, syncs ObjectStore + VectorIndex, and raises `index.object.embedded`.
- Reviewer — enforces maturity gates, toggles trust levels, and prepares Projector contracts.
- Projector — publishes curated packets to downstream surfaces (docs, API, knowledge packs).
- PromotionAgent — final arbiter that commits promotion decisions to audit + Outbox while coordinating cooldowns.

### Store Layer
ObjectStore persists object envelopes and agent decisions; VectorIndex stores chunk vectors plus embedding metadata; RelationIndex captures graph edges (duplicate_of, cites, derived_from) for query-time traversal. Each store implements CRUD via the Store abstraction so the same agent code works against in-memory dicts or Postgres-backed engines.

### Event Choreography
1. `ingest.object.created` records capture acceptance and seeds the PER loop.
2. `ingest.object.normalized`, `.classified`, `.chunked`, `.deduped`, `.citation_checked` mark completion of each agent and carry `trace_id` plus payload diff.
3. `index.object.embedded` signals VectorIndex writes and unlocks the Reviewer.
4. `promote.pending` captures Reviewer approval; `promote.done` finalizes PromotionAgent moves and informs subscribers such as search indexing or set sync.
- Alla events bär `instance_id` från `SettingsBundle.instance.id` (default `home`) så audit/Outbox kan markera vilken runtime som emitterade händelsen och förbereda master/satellit utan att ändra vault-UX.

### PromotionAgent Rules
- Idempotent writes: promotion can be retried safely because target maturity and storage side effects are computed deterministically from audit trails.
- Cooldown windows: move requests within the same five-minute window are coalesced to prevent thrash when upstream agents reclassify the same object.
- `move_policy` guardrails: `move_policy=advance_only` prohibits demotions outside manual overrides, while `move_policy=force` is reserved for maintenance tasks and always logs a privileged audit entry.

## Ingestion Pipeline (PER loop)
Every agent follows Plan → Execute → Reflect. Plan inspects the latest event plus Core-6 envelope to decide whether work is required, Execute performs the mutation using the Store layer, and Reflect writes audit spans, metrics, and Outbox entries. Data hand-offs are immutable payloads: Normalizer emits `normalized_object`, Chunker emits `chunk_set`, Deduper adds a `relation_patch`, CitationChecker appends `citation_report`, and Indexer produces an `embedding_batch`. The Reviewer consumes the cumulative context to assert maturity, then Projector and PromotionAgent close the loop. Failed executions requeue themselves by emitting a retryable event with the same `trace_id`.

### Note Ingestion Defaults
- Obsidian notes are auto-healed by `ensure_note_uuid(path)` before Panel runs; UUIDs are written via the YAML round-trip helpers so frontmatter stays stable.
- Notes without UUIDs are still ingested and snapshotted; `_format_note_update_status` surfaces when a UUID was added during the run.
- `note_moves_enable` defaults to false in runtime/global settings; Planner demotes move/rename/re-file steps to log-only and Promotion logs `promote.skip.move` instead of moving files.
- Operators can enable moves later by setting `note_moves_enable: true` in `vault/@Settings/global` (propagates into `runtime/settings/global.yaml`).

### Diarization-aware Chunking (v4.6-C)
When `DIARIZE_ENABLE=1`, the ingestion pipeline now feeds diarization metadata (speaker, start, end) into `speaker_aware_chunks()` so spans are cut on speaker changes or size boundaries (O(n) over segment length). Each emitted chunk carries `{speaker,start,end,speaker_segments}` metadata that flows through `ingest_and_chunk()` to indexing, and the audit stream (`text.chunk.created`) records `speaker_count` so reviewers can trace diarization coverage. With the flag disabled, `build_chunks()` preserves the legacy token/character splitter to keep defaults inert and deterministic.
Oversized per-speaker segments are deterministically pre-split to respect `max_chars`; proportional start/end timestamps keep timelines monotonic without re-reading audio.

### Reasoning Layer (cross-agent capability + DeliberationAgent)
Reasoning är en tvärgående förmåga som alla agenter kan använda för planering, granskning och reflektion. Lagret är multi-mode (`app/reasoning/models.py`) snarare än en enkel JSON-extraktor. `ReasoningMode` definierar stödda lägen och `ReasoningRun` fångar varje körning (id, mode, trace_id, object_uuids, steps, result, status/error). Routern `run_reasoning(...)` i `app/reasoning/provider.py` orkestrerar:

- `claims`: existing claims/evidence/inferences extraction (backed by `ReasoningInput` + `ReasoningOutput`); still fixture-backed for mock runs (`data/golden/reasoning_samples.jsonl`) and Ollama-backed locally.
- `review`: lightweight review/critique of a note (summary/issues/suggestions), mock-deterministic in CI, LLM-backed locally.
- `ranking`: candidate ranking with reasons, mock-deterministic in CI, LLM-backed locally (SetEvaluator consumes this).
- `planning`: reserved/TBD.

Calls include `agent` and `kind` (e.g., `reasoning.claims`, `reasoning.review`, `reasoning.ranking`) for tracing. The pipeline still gates on `REASONING_ENABLE=1` and stores claims outputs in the ReasoningStore; other modes feed agents directly (Reviewer, SetEvaluator) while remaining observable via the JSONL trace. DeliberationAgent är den specialiserade multi-step-ASK-agenten som använder Reasoning Layer för att gå flera hopp, men samma mönster återanvänds av t.ex. Reviewer, SetEvaluator och Planner.

Invariants:
- `claims` is successful (`status="ok"`) only when at least one claim or evidence exists; fully empty `{claims:[], evidence:[], inferences:[]}` is `status="failed"`.
- `ranking` is successful only when the ranking list is non-empty and contains at least one non-empty reason; otherwise `status="failed"`.

## Persistence & Execution Modes
- `STORE_BACKEND=memory` is the default for CI and unit tests; it instantiates in-memory implementations of ObjectStore, VectorIndex, and RelationIndex with deterministic UUID seeds.
- `STORE_BACKEND=pg` connects to Postgres/pgvector for full-fidelity runs; migrations guarantee schema parity with the memory structs.
- VectorIndex persistence is optional JSONL snapshots: set `INDEX_PERSIST_PATH` when writing batches and `INDEX_PERSIST_LOAD` to bootstrap warm caches across runs.
- `audit_log()` always writes to the configured sink, falling back to `logs/audit.jsonl` when stdout/file destinations are unavailable, ensuring no audit gap.
- The LLM layer defaults to `LLM_PROVIDER=mock` with fixture responses for deterministic CI; production enabling switches providers via env, while `llm_retry()` applies exponential backoff and caps at three attempts per request.

## Retrieval Layer (Rerank & Hybrid Search)
Hybrid search merges BM25 (FTS) plus vector similarity, returning distinct object IDs with score provenance. `RerankerProvider` now ships a matrix of deterministic adapters (`none`, `mock_ce`, `ce_local`, `ce_http`) that are injected via dependency wiring; reranking remains inert until `RERANK_ENABLE=1`. Operators select providers with `RERANK_PROVIDER`, keep cost bounded using `RERANK_TOP_K`, and rely on `ce_local` when they need a deterministic cross-encoder heuristic during CI. `apply_optional_rerank()` (located in `app/retrieval/hybrid_rerank_hook.py`) is called at the end of `hybrid_search` after unioning lexical + vector matches; invariants: never drop items, only reorder the first `TOP_K`, and maintain stable IDs for downstream caching. The v4.6 track keeps the same plug-in model so tests can swap mocks without touching query code, while production can point to an HTTP cross-encoder when approvals land.

### Rerank Hook Placement
The adapter `app/retrieval/hook_adapter.py::maybe_rerank(query, items)` sits on the final step of `hybrid_search` after BM25/vector scores are normalized and merged. By default it returns items untouched; when `RERANK_ENABLE` is set it delegates to `apply_optional_rerank()` so PromotionAgent and downstream caches always observe deterministic payloads (id, text, score, snippet, metadata). Memory-mode CI keeps determinism because the mock cross-encoder is pure Python and respects the provided ordering contracts.

## Observability & CI
JSONL audit logs capture `trace_id`, agent name, inputs, and outputs for each PER step; correlated `span_id`s map to structured metrics for latency and retries. Deterministic CI runs use `pytest -q -m "not pg"`, memory stores, and mock LLMs to ensure reproducible timings. Outbox processing meets QAS-010 by keeping ingest-to-index latency ≤ 2 s, while search endpoints monitor QAS-003 with p95 latency < 250 ms under hybrid retrieval. Telemetry dashboards watch agent failure rates and promotion cooldown breaches so regressions are caught before shipping.

## Fitness Functions
- **QAS-003 Hybrid Search Latency** — `app.fitness.metrics.qas003_hybrid_latency()` warms the in-memory hybrid store with a deterministic corpus and times `hybrid_search()` invocations. CI fails if the measured p95 exceeds 250 ms, and the GitHub workflow prints the JSON report via `python -m app.fitness.report`.
- **QAS-010 Outbox→Index Propagation** — `app.fitness.metrics.qas010_outbox_to_index_latency()` simulates ingest events flowing from an in-memory outbox into `MemoryVectorIndex`. Each event measures emission-to-index duration; CI enforces a 2 s ceiling.
Both probes run in memory mode with `LLM_PROVIDER=mock` so they remain deterministic and guard regressions without external services.

### CI Gates (v4.6-D)
`python -m app.fitness.report` now emits seven CI summary lines (LATENCY, EVAL, EVAL DELTA, RELATION COVERAGE, RELATIONS, DIARIZATION, GATES). The first six capture raw metrics, while the GATES line reports whether thresholds were met plus any failure codes. Baselines live in `ops/quality/baselines.yaml` and are overridable via `THRESHOLDS_PATH`; tolerances are additive (e.g., latency ≤ baseline × 1.10, diarization chunk_p95_on ≤ chunk_p95_off × 0.95). The GitHub workflow tees the report into `tmp/ci_summary.log`, parses it via `parse_summary_lines()`, and fails fast if any line is missing or `ok=false`, ensuring every PR presents the same contract without network access.

## Relation Index v1 & Orphan Gate
`MemoryRelationIndex` and `PgRelationIndex` now implement `link()`, `neighbors()`, and `has_any()` so agents can assert provenance before publishing. PromotionAgent wires in `app.promotion.gates.ensure_object_has_relations()` — if no relation exists for a queued UUID the agent blocks promotion by default. Overrides require `PROMOTION_ALLOW_ORPHANS=1` plus `PROMOTION_ORPHAN_OVERRIDE_REASON`, which emits an `audit_log(action="promotion.orphan.override")` entry and a `promote.orphan.override` log line. This keeps the promoted surface free from orphaned knowledge while still allowing audited manual exceptions. CI also reports the ratio of promoted items with relations using the golden sample in `data/golden/relations.json`.

### Relation Layer v1
`app.stores.relation_index` provides deterministic extraction + registration helpers that scan frontmatter fields (`supports`, `extends`, `contradicts`, `derived_from`, `relations`, `related`, tag prefixes) and markdown sections such as “See also” / “Derived from”. The extractor normalizes targets, caps supported relation types to `{supports, extends, contradicts, derived_from}`, and deduplicates matches before `register_relation_candidates()` writes them via the configured `RelationIndex`. `prepare_relations_for_promotion()` runs these heuristics for every queue item, persists the links, and emits audit entries: `relation.added` for valid edges, `relation.missing` when parsing fails. When `PROMOTION_REQUIRE_RELATIONS=1`, promotion halts until at least one link is recorded, preserving determinism and blocking orphaned cards. The RelationIndex payload retains evidence (frontmatter field or body heading) so later graph tooling can trace why a link exists.

## Diarization Hook
`app.diarization.hook.apply_diarization()` post-processes ASR output inside `app/media/transcribe.py`. Flags:
- `DIARIZE_ENABLE` — master switch (defaults to off).
- `DIARIZE_PROVIDER` — `none|mock|external`; the mock provider yields alternating `spk_0`/`spk_1` segments without external dependencies, while the external provider calls `DIARIZE_HTTP_ENDPOINT` and falls back to mock on errors.
| Provider | Env | Behaviour |
| --- | --- | --- |
| `none` | `DIARIZE_ENABLE=0` or provider unset | Pass-through single segment. |
| `mock` | `DIARIZE_ENABLE=1`, `DIARIZE_PROVIDER=mock` | Splits text into alternating speakers deterministically. |
| `external` | `DIARIZE_PROVIDER=external`, `DIARIZE_HTTP_ENDPOINT=<url>` | Calls HTTP diarization API with fallback to mock. |
Segments preserve `{speaker, text}` metadata so downstream ingestion can attach speaker context without reprocessing audio.

## Golden Set Evaluation
`app.eval.golden.evaluate_golden_set()` loads `data/golden/corpus.jsonl` plus `data/golden/judgments.json`, stamps them into the hybrid store, and runs `precision@k` / `nDCG@k` over the synthetic queries. The evaluation runs as part of the not-pg test suite to guarantee that rerank and retrieval improvements never regress the baseline metrics; docs and CI reference the golden corpus as the agreed benchmark. `python -m app.fitness.report` compares ce_local against the baseline provider and emits `CI SUMMARY EVAL P@10=<val> nDCG@10=<val>` so regressions block merges automatically.

## Extensibility & v5 Direction
The v5 roadmap layers declarative reasoning (RDF/OWL/SHACL constraints) on top of the existing stores, enabling Reviewer and PromotionAgent to validate logic gates instead of bespoke Python checks. The Agent Memory Graph will evolve to persist reflective notes per object, informing future PER plans. Provenance and promotion governance will add policy bundles (who can promote, when to reset cooldowns) so humans stay accountable even as automation deepens.
## Settings Architecture — Vault-as-GUI, Code-as-Source

Control surface: `vault/@Settings/**`  
Runtime source of truth: `runtime/settings/**/*.yaml`

### Human → Machine pipeline
1) Markdown → Loader → Sektioner  
2) Sektioner → Parsers → Semantiska dicts  
3) Merge + Precedens → Compiler → Typning (Pydantic) + Secrets-resolve  
4) Artefakter skrivs till `runtime/settings/**` + `settings.changed` event

### Precedens
Process overrides > ENV/.env > Vault Markdown > Defaults

### Sekret
Vault refererar endast `${SECRET:NAME}`. Upplösning från `.env` eller SOPS-krypterade filer. Råvärden skrivs aldrig till Markdown eller `runtime/`.

### Hot-reload
Komponenter prenumererar på `settings.changed` och läser om idempotent.

### Markup-regler
- Checkrutor → bool
- Tvåkolumnstabell → nyckel: värde med dot-path
- ```yaml settings → auktoritativ sektion

## Agent Coordination Layer (A2A) — v4.8
A2A introduces a declarative agent-to-agent messaging fabric layered on Stores + Events + the PER loop. When `A2A_ENABLE=1`, the Outbox registers an additional channel that carries envelopes between agents without bypassing audit or promotion invariants, and every agent can opt into message handling via `handle_agent_message()` while continuing to emit the standard ingest events. The canonical schema (request/response/error) plus audit events (`agent.request.created`, `agent.response.created`, `agent.error.created`) now ship in-tree so tests can exercise protocol hooks while routing/orchestrator wiring remains feature-gated.

### Envelope Events
- `agent.request.created` — emitted when an agent wants follow-up work from another agent; carries `request_id`, `trace_id`, desired capability, and payload summary.
- `agent.response.created` — produced when the receiving agent completes the requested action and publishes outputs or state diffs in an append-only fashion.
- `agent.error` — emitted when the receiving agent cannot complete the requested action; includes retry hints and failure metadata so the Orchestrator can branch deterministically.
- `agent.critique.created` — optional critique or blocker event that lets downstream reviewers see peer feedback before a promotion decision.
Envelopes reuse Core-6 metadata and append an `a2a.intent` field so determinism and replay remain intact.

### Pipeline Hooks
Agents subscribe to A2A messages through the same PER scheduler: Plan inspects incoming envelopes (if enabled), Execute performs the requested action, and Reflect emits the response event plus standard audit spans. A2A never replaces Store interactions; it simply allows agents to chain themselves without introducing side channels. Hooks remain inert unless the flag is set, ensuring default CI paths stay unchanged.

### Sample Chain
Classifier can request deeper deliberation by emitting `agent.request.created(intent="reason")` for DeliberationAgent; once processed, DeliberationAgent answers via `agent.response.created` and can critique via `agent.critique.created`. PromotionAgent or Projector may then issue a follow-up request to Projector for packaging, giving a deterministic Classifier → DeliberationAgent → Projector chain that is fully audited yet optional, even though strukturerat resonemang är en tvärgående förmåga alla agenter använder.

## A2A Message Flow
The A2A protocol is intentionally narrow and mediated entirely by the Orchestrator. Envelopes remain internal:
- `agent.request.created` describes the capability being requested, the payload summary, and the Core-6 identifier/trace.
- `agent.response.created` captures deterministic outputs or state diffs in an append-only fashion.
- `agent.error` communicates blocked work plus retry metadata so the Orchestrator can branch or halt safely.
Agents never exchange envelopes peer-to-peer; the Orchestrator inspects the active plan, routes envelopes via `handle_agent_message()`, persists audit spans, and guarantees deterministic replays for CI. Flags keep orchestration inert until `A2A_ENABLE=1`, preserving the legacy ingest flow by default.

## MCP Integration Layer — v4.9
The PKM runtime exposes itself as an MCP server so external tools can orchestrate ingest/search flows without bespoke adapters. MCP endpoints mirror the internal Store/Agent APIs (e.g., `pipe_note`, `search_notes`, `get_claims`, `promote_object`, `list_relations`) and sit behind the same auth + audit envelope as the CLI.

### MCP Server Surface
Running with `MCP_ENABLE=1` starts an MCP server process bound to the local runtime; tool metadata describes inputs/outputs using the canonical schema so editors like Obsidian or ChatGPT can call them directly. Deterministic mocks remain available for CI so MCP startup is a no-op unless explicitly toggled.

### MCP Client Inside the Act Phase
Agents gain an optional ToolProvider wrapper that can dispatch MCP tool calls from within the Act phase. Calls remain synchronous, respect retry budgets, and emit `mcp.tool.invoked` audit lines. When disabled, the ToolProvider reverts to a no-op stub, keeping the act phase identical to current behaviour.

### Orchestrator-driven MCP Calls
When plans contain MCP tool steps, the Orchestrator invokes those tools through the ToolProvider on behalf of the currently scheduled agent, captures results, and resumes the workflow. Supported actions include vault writes/file ops, search, ingestion/normalization helpers, analytics routines, or curated external API queries. These calls either replace or complement the historical CLI commands while sharing the same audit envelope. Every invocation is audited with the originating plan step and is fully mocked under CI so the Planner Agent can rely on tool access without sacrificing determinism.

### Deterministic Tool Chains
`ToolProvider` abstracts whether calls hit the local MCP server, a mock provider, or an injected client. CI defaults to the mock provider so planners and agents can validate tool choreography without sockets. The abstraction keeps MCP additive: enable it to let external editors drive ingestion, search, relation updates, or promotion checks; leave it off to continue CLI-only execution.

### Compatibility Note
Legacy CLI workflows (`python -m app.cli pipe ...`) remain supported until the LangGraph-based Orchestrator runtime becomes the default surface. Operators can keep `PLANNER_ENABLE`, `A2A_ENABLE`, and `MCP_ENABLE` unset to preserve historical behaviour, then progressively opt into Planner Agent + Orchestrator + MCP flows without breaking scripted ingestion.

### ASK CLI flow
The `python -m app.cli ask "..."` command emits an `ask.query.received` event, optionally lets FlowProfiles pick a pattern, and routes the resulting plan through the Orchestrator. The CLI injects tool settings so MCP vault writes stay mocked by default, but operators can opt in via `--enable-mcp-vault`/`MCP_VAULT_ENABLE` plus a `VAULT_ROOT`. After execution it prints the selected flow/pattern, the plan summary, and any resulting `mcp.vault.append_note` paths so teams can demo the full question -> plan -> agent/tool -> vault pipeline without bespoke glue.

## LLM-Driven Planning Layer — v4.9
Planning is embedded directly into the PER loop, turning “Plan → Act → Reflect” into a concretely orchestrated, LLM-generated step. When `PLANNER_ENABLE=1`, the planner executes before each agent cycle, producing a structured plan that lists which agent should run, which MCP tools to call, and whether any A2A requests must be issued.

### Planner Inputs
The planner consumes the current object context (Core-6 + latest payload), a RelationIndex snapshot, declared agent capabilities, and the backlog of recent A2A envelopes. These inputs are encoded as JSON per the existing Reasoning Provider schema to keep prompts deterministic. `PlannerInput` (defined in `app/planner/provider.py`) mirrors this bundle and is the canonical payload handed to any planner backend.

### Plan Schema & Tool Descriptors
`app/planner/schema.py` defines the persisted plan contract: `Plan` (with `PlanMetadata`), `PlanStep`, and `ToolDescriptor`. Steps carry `kind=agent_call|tool_call|decision|note`, optional `agent/intent`, MCP tool names (e.g., `mcp.vault.append_note`) plus structured `tool_args`, dependencies, and metadata so plans replay deterministically. MCP tool descriptors live under `app/planner/tools.py` as a static registry (`MCP_TOOL_DESCRIPTORS`) the Planner Agent references when suggesting tool steps; each descriptor ships with a JSON-schema-like shape, explicit `allowed_args`, and a deterministic `mock_result` so the executor can validate payloads without touching real MCP tools. Tests assert that plan steps referencing those names remain valid even before we wire actual MCP execution.

### Planner Outputs & Execution
Planner responses must validate against the Plan schema, so downstream executors see a uniform structure regardless of backend. Plans may include `tool_call` and `agent_call` steps so multi-agent workflows chain without bespoke glue, and they can reference MCP tools by name through the ToolProvider abstraction. If the planner is disabled, the classical round-robin PER scheduler runs unchanged. When `PLANNER_ENABLE=1`, `app.agents.pipeline.maybe_plan_for_object()` emits a plan plus `planner.plan.created`, and when `ORCHESTRATOR_ENABLE=1` the same pipeline calls `maybe_execute_plan()` so the Orchestrator replays the plan immediately after ingest (deterministically mocked in CI).

### Deterministic Backends & Flags
`app/planner/provider.py` exposes `MockPlanner` (deterministic fixtures for CI) and `LLMPlanner` (Ollama-backed when `PLANNER_PROVIDER=llm` and `LLM_PROVIDER!=mock`). The provider falls back to the mock backend and emits `planner.plan.fallback` when misconfigured or when LLM output fails validation. `PLANNER_ENABLE=0` keeps the planner inert; when enabled, planner calls are audited via `planner.plan.created` (intake) plus `planner.plan.error`/`planner.plan.fallback` when issues occur so reviewers can trace every orchestrated decision alongside MCP and A2A traces.

## Planner Agent vs Orchestrator
### Planner Agent (LLM-driven)
An LLM-powered Planner Agent ingests the requested goal or intent, Core-6 metadata, the latest object text, a RelationIndex snapshot, recent reasoning outputs (`claims`, `evidence`, `inferences`), and the agent capability graph. It emits a structured plan object that enumerates execution steps, target agents, required A2A envelopes, any MCP tool invocations, dependencies, preconditions, and stop conditions. CI always runs the mock backend so the resulting plan remains deterministic, and the entire stage is gated behind `PLANNER_ENABLE`.

### Orchestrator (deterministic executor)
The Orchestrator is the deterministic execution layer (current PER-loop derivative with a LangGraph runtime on the horizon) that consumes the plan, schedules referenced agents, persists state transitions, and delivers A2A messages. It coordinates branching, retries, and structured state transitions while remaining backward compatible with the CLI `pipe` workflow until operators opt into the new runtime. Whenever the plan references MCP tools or additional agents, the Orchestrator sequences the calls, records audit spans, and guarantees replayability.

### Orchestrator Runtime — Execution Model (v4.10A)
AgentConfigs now guard agent_call steps: before invoking an agent, the orchestrator resolves its vault-defined AgentConfig and enforces enabled/flow/event boundaries. Misconfigured or disabled agents yield structured permission errors instead of crashes, keeping human-declared constraints in control while tool/decision steps remain unchanged.

`app/orchestrator/runtime.py` hosts the Orchestrator class plus a `MockPlanExecutor`. Plans are validated up front (unique IDs, dependency order, required agent/tool metadata). Each step emits `orchestrator.step.started|finished|error` with the plan/step identifiers so auditing can reconstruct the control flow. Execution stays deterministic because `MockPlanExecutor`:
- dispatches `agent_call` steps via `send_agent_request` (emitting `agent.request.created`) and immediately routes them through the default Agent handler, which responds with `agent.error.created` / `error_type=not_implemented`.
- enforces MCP tool contracts by loading descriptors, checking `allowed_args`, and returning the descriptor’s `mock_result`; every call emits `mcp.tool.call.started|finished`, and no sockets/filesystem work occurs in CI.
- records decision/note steps as structured audit payloads without mutating stores.

The current choreography is serialized and flag-gated (`PLANNER_ENABLE` + `ORCHESTRATOR_ENABLE`). Future LangGraph/parallel scheduling layers can reuse the same executor contract while preserving determinism.

```
Planner Agent
      │
      │ plan (Plan/PlanStep schema)
      ▼
Orchestrator.run_plan()
      ├─ agent_call → send_agent_request() → Agent.handle_agent_request() → agent.error.created (default stub)
      └─ tool_call  → MCP descriptor validation → mcp.tool.call.started/finished (mock_result, no side effects)
```

### Planner ↔ Reasoning Layer
Planner prompts reuse Reasoning Layer payloads so the Planner Agent stays grounded in deterministic state. The Planner inspects `ReasoningInput` bundles plus Core-6 frontmatter and relation graphs before proposing any step, which makes downstream audits straightforward and keeps plan generation tightly coupled to earlier reasoning outputs.

### Vault-first Flow & Agent Settings

Flow profiles now live in the vault under `vault/_system/flows/*.md`. Each Markdown file exposes YAML frontmatter parsed by `app.settings.flow_profiles` into a `FlowProfile` that focuses on intent, suggested agent/tool patterns, planner mode hints, and available prompt templates:

```yaml
---
flow_id: ingest
name: Ingest pipeline
event_triggers:
  - ingest.object.created
intent: Turn new raw text into structured, searchable knowledge.
suggested_patterns:
  - name: standard_ingest
    steps:
      - agent:normalizer
      - agent:classifier
planner_mode:
  strictness: advisory
  max_steps: 8
prompt_profiles:
  - id: ingest-default
    prompt_template_ref: prompts/planner/ingest-default.md
---
```

FlowProfiles express a human-defined strategy rather than a rigid plan: intent documents the goal, `suggested_patterns` lists example sequences the planner may follow, `planner_mode` sets advisory limits/strictness, and `prompt_profiles` enumerates the planner prompts available for that flow. Planner/Orchestrator remain unchanged in this PR; these profiles are read-only guidance until wired in.

Agent definitions follow the same docs-as-code contract in `vault/_system/agents/*.md`, loaded via
`app.settings.agents` into `AgentConfig` instances:

```yaml
---
agent_id: planner
agent_type: planner
flows:
  - ingest
  - promotion
tools:
  - summarize
  - planner.scratchpad
prompt_template_ref: planner.prompts.default
---
```

For this slice the Planner and Orchestrator keep their previous behaviour; the new loaders simply make
the vault-backed configuration available for upcoming integrations.

## AI panel: human-first note interaction
Notes may optionally expose a lightweight AI panel so humans drive intent directly in Markdown without custom syntax. Panels are delimited by forgiving AI comment fences (`%% ...AI... %%` after trimming spaces), where the first fence opens a panel, the second closes it, the third opens the next, etc. Inside a panel the schema is:
- **AI-instruktion** — free-text instructions that describe what the human wants from the system for this note.
- **AI-åtgärder** — markdown checkbox actions (`- [ ] ...` / `- [x] ...`) that the human can tick to request a discrete move.
- **AI-logg** — chronological bullet log of what the system already executed for the note.

Example:
```
%% AI:Start %%
## AI-instruktion
...
## AI-åtgärder
...
## AI-logg
...
%% AI:End %%
```

Fences are tolerant to label variations (any `%%` line containing `ai`); legacy notes that only use the headings without fences are still parsed as panels, but new panels should use fences. Panel content is not part of the knowledge base and must not be indexed or used for QA.

`PanelState` (pydantic) normalises these sections so agents can diff old vs. new states deterministically. The `PanelAgent` parses prior/current note bodies, emits `PanelIntent` records for newly-checked actions or instruction edits, and proposes updated Markdown by removing one-shot actions and appending a simple log entry (e.g., `- Action: "..."`). The agent remains local/in-memory for now: it is not wired to Planner/Orchestrator yet, but its output objects are ready for the future event pipeline.

Vault-first mappings under `vault/_system/panel-actions/*.md` (with docs fallback `docs/settings/panel-actions.md`) translate checkbox text into canonical event types. When PanelAgent detects a newly checked action it enriches the `PanelIntent` with that mapping and synthesizes structured `Event` objects (still kept in-memory for now) so upcoming wiring can hand intents to Planner/Orchestrator deterministically.

`handle_panel_update()` wraps this flow: it parses the panel, applies mappings, and when `PANEL_EVENTS_ENABLE=1` it dispatches each PanelAgent event through `handle_event()` so the existing Planner/Orchestrator pipeline runs (down to mock MCP tool calls in tests). With the flag disabled the integration stays dry-run and only returns rewritten markdown plus intent metadata, keeping panel edits local until the operator opts in.

`python -m app.cli panel-update path/to/note.md --old-path path/to/old.md` exposes this in the CLI for manual runs: it reads the note, executes `handle_panel_update()`, writes back the AI-åtgärder/log updates, and reports how many panel events were created/dispatched (respecting `PANEL_EVENTS_ENABLE` and `EVENT_ORCHESTRATOR_ENABLE`).

`NoteUpdateService` builds on that by treating the note UUID as the durable identity: `process_note_update()` loads the note, checks an optional expected path (stale detection), hydrates prior snapshots from `tmp/note_update_snapshots`, and runs `handle_panel_update()` before writing the updated markdown + snapshot. The `note-update` CLI batches this over one or more files (`python -m app.cli note-update vault/@Inbox --glob '*.md'`), emits per-note status, and summarizes processed/changed/dispatch counts. This is the same entrypoint future filesystem watchers will call when they notice edited notes, so behaviour stays deterministic whether triggered manually or automatically.

### Panel update vs Note update — when to use which
Two commands exist on purpose: `panel-update` runs the AI panel in isolation for a single note (instruction/actions/logg) without snapshots, stale detection, or watcher orchestration, while `note-update` runs the canonical UUID-first pipeline with snapshots, stale detection, and panel + event dispatch that note-scan and future watchers rely on. Use this quick guide to pick the right tool.

**Use `panel-update` when…**
- you want to test the AI panel behaviour directly,
- you are debugging checkbox mapping, instruction parsing, or log formatting,
- you only want to operate on a single file without invoking snapshots, stale detection, watcher logic, or UUID holistic update logic,
- you want fast iteration on panel designs.

**Use `note-update` when…**
- you want the system to update the note "for real",
- you want snapshot-aware, UUID-first safe writes with stale detection,
- you want panel output + event dispatch + orchestrator plans,
- you want behaviour consistent with note-scan and future watchers.
