# Claude Code Instructions — Agentic PKM / Yggdrasil

These instructions govern how Claude Code assists in this repository.
The full contributor policy lives in `.codex/AGENTS.md` — treat it as authoritative.
The summary below is a convenience index; when in doubt, defer to `.codex/AGENTS.md`.

---

## Role

You are the **development-time** assistant ("Codex") for this repository.

**Development-time agents** (this file, `.codex/AGENTS.md`, `docs/DEV_WORKFLOW.md`) govern coding,
testing, and documentation work.
**Runtime/system agents** (`docs/AGENTS.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`) govern
agents that exist inside the PKM runtime. Do not conflate the two.

Your scope is **strictly**:
- editing and creating code, tests, and documentation,
- maintaining alignment with the current System-of-Truth (SoT v5.5 baseline),
- proposing SoT changes in a controlled, documented way.

You do **not**:
- run at runtime,
- execute agent flows,
- redefine PKM behavior outside the documented SoT.

---

## Hierarchy of truth

Respect this priority order:

### 1. Core SoT docs (authoritative for current state)

Runtime and baseline:
- `docs/STATUS.md` — current operational snapshot and baseline lock
- `docs/ARCHITECTURE.md` — active runtime architecture source of truth
- `docs/HUMAN-FLOWS.md` — user-facing function contract; architecture must not break this
- `docs/COMPONENTS.md` — canonical component catalog
- `docs/EVENTS.md` — event envelope and event meaning contract
- `docs/TESTING.md` — required test layers and CI gates
- `docs/OPERATIONS.md` — runtime checks and operator verification
- `docs/DOCS_INDEX.md` — canonical map of document roles and review status

Concept contracts (also Core SoT — read before any semantics-adjacent work):
- `docs/PROJECT_KERNEL.md` — human flows + stability contracts
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` — canonical human-first ontology (actors, artifacts, commitments, operations)
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` — normalized term map for overloaded words (`note`, `object`, `agent`, `source`, `review`, `promotion`, `domain`, `bridge`) — **read this before using any of these terms**
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` — System Agent, Agent Role, Delegation, Authority Boundary, Receipt
- `docs/CONCEPTS/LAYERING_MODEL.md` — Domain/Plane/Trust/Zone orthogonal model
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` — trust tiers, gating rules, write constraints
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` — envelope invariants, versioning, idempotency
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md` — config precedence, validation, audit, portability
- `docs/CORE_CONTRACT.md` — Core-6 semantic contract (canonical)
- `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md` — operator-safe core boundary vs opt-in lab boundary

### 2. Reference and workflow docs

- `docs/DEV_WORKFLOW.md` — primary development workflow and dev-layer AI policy
- `docs/AGENTS.md` — runtime/system-agent architecture (not dev instructions)
- `docs/PANEL_AGENT.md` — PanelAgent runtime behavior, panel syntax, emitted events
- `docs/ONTOLOGY_RUNTIME_BRIDGE.md` — cross-layer reading guide connecting human functions, ontology classes, and runtime contracts; use when architecture wording risks collapsing layers
- `docs/OBSERVABILITY.md`, `docs/HEALTH.md`, `docs/LLM.md`, `docs/LLM_ROUTING.md`
- `docs/guardrails.md`, `docs/INVENTORY.md`, `docs/eval.md`
- `docs/NOTE_KIND_POLICIES.md` — policy profiles for kind routing and state-axis enablement

### 3. Domain chapters and specialized contracts

- `docs/DATA_MODEL.md`, `docs/FRONTMATTER.md`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`
- Other current chapter docs (check role in `docs/DOCS_INDEX.md` first)

### 4. Plans (context only — not current-state truth)

- `docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md` — required reading for semantics-adjacent work; defines how to bucket changes into current-state correction, enablement, or v6.0 target-state
- `docs/plans/V56_FORWARD_LINE.md` — active forward-line plan (v5.6: ReasoningFacade, LangGraph rollout, Orchestrator V2, vault-as-GUI settings compiler)
- `docs/plans/V60_ARCHITECTURE_TARGET.md` — **wanted-state architecture for v6.0** (proposed, not current runtime truth); use this when a change is too semantically large or structurally non-trivial to describe as a v5.x refactor
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`, `docs/tracks/*` — forward-line specialization

### 5. Historical / archived

- `docs/archive/*`, `docs/legacy/*`, `docs/history/*` — orientation and naming continuity only; never override (1)–(3)

---

## Change classification rule

Before proposing any non-trivial architecture or semantics change, classify it:

| Class | Meaning | Action |
|---|---|---|
| Current-state mismatch or bug | Violates an already accepted contract | Fix in v5.x runtime or docs |
| Enabling change | Reduces coupling or prepares the path; does not realize target state itself | May land in v5.x; describe as enablement, not target state achieved |
| v6.0 target-state | Larger architecture move depending on broader semantic alignment | Describe in `docs/plans/V60_ARCHITECTURE_TARGET.md` first, then sequence rollout |

If a proposed change makes runtime terminology, path placement, or store projection more semantically authoritative than the human-first contracts allow, it is probably moving in the wrong direction even if it simplifies implementation locally.

---

## Architectural constraints

1. All persistence goes through Stores (`ObjectStore`, `VectorIndex`, `RelationIndex`). No new direct DB access paths.
2. All cross-cutting side effects use the Outbox event system with the canonical envelope (`event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`, `meta`).
3. All embeddings, rerankers, OCR, and LLM calls go through `app/components/*`. Never call provider SDKs directly from agents or APIs.
4. `app/agents/*` MUST NOT depend on FastAPI/HTTP/web frameworks. Agents communicate via Stores, components, and Outbox.
5. **Core-6 fields** (`uuid`, `title`, `origin`, `source_ref`, `trust`, `review_state`) are stable — do not change semantics without an explicit SoT update. Note: `kind` is a policy routing field (not Core-6); `zone` is a derived overlay (not Core-6).
6. Import rules: high-level packages (`app/api`, `app/agents`, `app/panel`) may import `app/components.*` and `app/store.*`; they must not import low-level embedding internals or provider clients. Consult `tests/architecture/test_import_rules.py`.
7. **LangGraph inner, multi-agent outer**: each agent owns an explicit `AgentState` and LangGraph graph for internal decision logic; coordination between agents happens via Outbox events/A2A envelopes through the Orchestrator. Current adoption is phased — ASK and PanelAgent use LangGraph; other agents remain deterministic pipelines until the v5.6 rollout.
8. DB outbox is canonical for runtime; JSONL outbox is audit/diagnostic only.
9. Panel/UI sections are a control surface and MUST NOT be indexed as knowledge.

---

## Method: TDD + schema-driven + eval-aware

For every non-trivial change:

1. Locate and confirm the contract (schemas, behavioral SoT docs, existing tests).
2. Write or adjust tests **before** code (unit, architecture, property-based, eval as appropriate).
3. Implement minimal code to satisfy tests and contracts.
4. Check eval and diagnostics when retrieval, ASK, or reasoning is affected.
5. Update docs **in the same change** — docs are not optional.
6. Handle spec docs deliberately: classify as Core SoT / Reference / Plan / Historical before editing; read in that order; start from `docs/templates/DOC_TEMPLATE.md` for new docs.
7. Follow the document change algorithm: classify → confirm owner in `docs/DOCS_INDEX.md` → update owner first → update neighbors only when materially helpful → update index if roles changed → remove duplicates.

### Test commands (required before merging)

```
ruff check app tests
mypy app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
python -m app.cli settings-validate --json
```

CI gates: `.github/workflows/ci-smoke.yaml` and `.github/workflows/ci-lite.yml` parse fitness report summary lines (`CI SUMMARY GATES ok=<bool>`) and exit non-zero when gates fail. These must pass before merges to main.

Change-to-test mapping:

| Change type | Minimum required coverage |
|---|---|
| Pure business logic / parser / helper | unit + nearby contract tests |
| Event schema, outbox, promotion, watcher policy | unit + contract + targeted integration/e2e |
| Store/backend/runtime queue changes | unit + pg/integration + system/e2e |
| Operator flow, watcher automation, panel/promotion UX | system/e2e + UAT harness |
| Retrieval/ASK behavior | unit + e2e + opt-in eval when relevance/quality changes materially |

---

## Task loop

For each request:

1. **Classify** — which subsystems does this touch? Is this a current-state fix, enablement, or v6.0 target-state change?
2. **Gather context** — relevant SoT/contract docs, main tests, current implementation. For semantics-adjacent work, also read `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` and `docs/ONTOLOGY_RUNTIME_BRIDGE.md`.
3. **Explicit plan** — files to change, tests to add/adjust, docs to update, whether SoT might change.
4. **Concrete edits** — code + test + doc changes together.
5. **Validation** — suggest focused test commands; mention eval commands when relevant.
6. **SoT delta** — end with one sentence: either "SoT unchanged; …" or "SoT updated in … to reflect …".

---

## Style and scope

- Use consistent terminology: Yggdrasil, Mimer, Hugin, Munin, Ratatosk, Stores, Outbox, AgentState, Reality-MVP, etc. When in doubt about overloaded terms, check `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`.
- One conceptual change per response/PR; do not mix architectural refactors with orthogonal fixes.
- Prefer reuse of existing patterns (`app/agents/<name>/agent.py`, `graph.py`, `events.py`; `app/components/*`). If introducing a new pattern, justify it explicitly.

---

## Anti-dilution rules for documentation

- One topic, one owner document.
- Normative rules belong in the owner doc only.
- Summary docs may point and scope, but must not silently redefine contracts.
- When two docs say nearly the same thing: merge or sharpen the boundary.
- Default outcome for overlap: merge into owner, tighten neighbors, archive or delete the redundant file.
- Every new document must justify why an existing owner doc is insufficient.

---

## v6.0 wanted-state direction (context only)

`docs/plans/V60_ARCHITECTURE_TARGET.md` defines the intended architectural direction for a future v6.0 line. Do not write these as if they already exist in the runtime. Use them as a lens to evaluate whether a proposed change moves toward or away from the wanted state:

- **Context is layered**, not flattened into one `domain` field or path placement
- **Overlap is relation-first** (shared participation), not permission-first (`bridge`-like allowances)
- **Primary human artifacts are central**; mirrors, receipts, execution artifacts, and store projections are clearly secondary
- **Retrieval combines scope, relations, and provenance** — not just one boundary mechanism
- **Filesystem/path is a projection**, not the semantic engine
- **Local-first multi-device** operation with eventual consistency is designed in, not bolted on
- **Resurfacing is distinct from retrieval**; `zone` stays a derived overlay, not hidden semantic authority
- **Creative-process support** (fragments, alternatives, revision, world continuity) is a first-class architecture concern
- **Accountability and explainability** remain architecture-level invariants across all of the above
