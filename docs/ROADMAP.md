State: SoT v4.10 Reality-MVP (current core).
# Roadmap — Strategic Control

## Reality-MVP (current)
- Ship reliable single-user Reality-MVP: stable vault ingestion, minimal external ingest, ASK API, observability backend, and an interim GUI for status + ASK.
- Planes/zones: vault (human graph with minimal frontmatter) and external corpus (newsletters/emails/PDFs) indexed but not shown as Obsidian notes.
- Human flows and contracts are defined in `docs/HUMAN-FLOWS.md`; architecture and topology in `docs/SYSTEM_DESIGN_v4.10.md`, `docs/ARCHITECTURE.md`, and `docs/DIAGRAMS.md`.
- Component catalog, dependency rules, Outbox envelope, ASK graph, PanelAgent, eval stack, and onboarding docs are complete in SoT v4.10.

## Version ladder (delivered / historical)
| Version | Intent | State |
| --- | --- | --- |
| Reality-MVP (SoT v4.10) | Vault ingestion + external corpus plane + ASK API + observability + interim GUI | Active (current) |
| v4.4–v4.6 | Observability + Store abstraction + retrieval quality | Delivered (historical foundation) |
| v4.8 | A2A Protocol V1 + Orchestrator messaging hooks | Schema/mocks delivered; wiring deferred (flagged) |
| v4.9 | MCP Integration V1 + Planner Agent (LLM) plan schema | Delivered (schema, descriptors, mock/LLM planners) |
| v4.10 | Orchestrator Runtime V1 (LangGraph execution skeleton) | Delivered skeleton; mock-only; flag-gated |

## Next horizon — v5.x themes (planned)
- **RelationIndex / knowledge graph uplift**: Expand RelationIndex into a knowledge graph, wire ingestion and ASK to surface relations, and expose governance queries; update ARCHITECTURE/SYSTEM_DESIGN/COMPONENTS accordingly.
- **Reasoner / Planner above ASK**: Add explicit reasoning/planning stages to ASK (plan → retrieve → reason → answer), tighten eval around multi-hop reasoning and summarization quality.
- **PanelAgent → Planner/Orchestrator integration**: Route panel actions/events into Planner/Orchestrator so checkboxes trigger audited multi-step flows; update HUMAN-FLOWS and PANEL_AGENT to cover the end-to-end path.
- **Satellite sync / multi-instance**: Prototype master + satellite sync at the text/log level (Git/iCloud), based on `docs/PROTOCOL_SATELLITE_SYNC.md` and SYSTEM_DESIGN; keep DB replication out of scope.
- **Expanded observability**: Richer dashboards for ASK/ingest/panel/promotion flows; OTLP traces as an optional add-on; align with `docs/OBSERVABILITY_STACK.md`.

## Guiding principles
- Keep SoT v4.10 as the stable baseline; new work should land behind flags and retain deterministic CI paths.
- Prefer small, audited increments: update docs (ARCHITECTURE, SYSTEM_DESIGN, COMPONENTS, HUMAN-FLOWS) when new flows or stores appear.
- Eval remains opt-in diagnostics: deepen coverage as features mature without blocking core development by default.
