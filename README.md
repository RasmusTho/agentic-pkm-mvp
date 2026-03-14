State: SoT v5.5 Reality-MVP baseline (locked) with forward line v5.6 planned (docs-first).
# Agentic PKM — Vault-First, Event-Driven PKM Runtime

Agentic PKM is a vault-first, event-driven PKM runtime:
- The human writing surface (a Markdown vault) remains the canonical artifact.
- Derived stores (DB tables, indexes, embeddings) are rebuildable mirrors.
- The runtime is guarded by CI fitness gates and explicit safety switches (watcher auto-run, dedup/idempotency, optimistic writes).

Start here:
- `docs/STATUS.md` — current baseline reality (v5.5) + forward line (v5.6)
- `docs/ARCHITECTURE.md` — active runtime architecture source of truth
- `docs/HUMAN-FLOWS.md` — user-facing behavior contract
- `docs/DOCS_INDEX.md` — map of the wider documentation set, including reference and historical docs
- `docs/DOCS_REFACTOR_PLAN.md` — staged plan for simplifying the documentation set

Prereqs:
- Python **>= 3.12** (see `docs/DEPENDENCIES.md`).
- For full runtime: Docker + Docker Compose.

## What Works Today (SoT v5.5 Baseline)
- **Registry watcher (runtime default)** scans a bounded scope and enqueues events.
- **DB outbox is canonical** (worker queue). JSONL (`INDEX_OUTBOX_PATH`) is audit/diagnostic only.
- **Worker consumes DB outbox** and runs ingest/panel/promotion side-effects.
- **PanelAgent wiring is settings-backed** (catalog + mappings) and emits observable intent/execution events.
- **Health spine** (`/api/health` + heartbeats + write guard + incident log) provides deterministic operator signals.
- **CI fitness gates** parse `CI SUMMARY …` lines and fail merges when `GATES.ok != true`.

## Core Invariants
- **Explicit watcher mode:** runtime defaults to `WATCHER_AUTO_EXEC=1`; set `WATCHER_AUTO_EXEC=0` for emit-only mode.
- **Compatibility:** `index.embedding.created` is the current index completion event (legacy alias: `index.object.embedded`).
- **No hidden state:** events/logs include trace/provenance; outbox is the only canonical queue for side-effects.

## Docs
<!-- DOCS-LINKS:BEGIN -->
- [Docs Index](docs/DOCS_INDEX.md)
- [Status](docs/STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Diagrams](docs/DIAGRAMS.md)
- [Human Flows](docs/HUMAN-FLOWS.md)
- [Roadmap](docs/ROADMAP.md)
- [Operations](docs/OPERATIONS.md)
- [Events](docs/EVENTS.md)
- [Testing](docs/TESTING.md)
<!-- DOCS-LINKS:END -->

## Documentation Reading Order
- Core SoT: `docs/STATUS.md`, `docs/ARCHITECTURE.md`, `docs/HUMAN-FLOWS.md`, `docs/COMPONENTS.md`, `docs/EVENTS.md`, `docs/TESTING.md`, `docs/OPERATIONS.md`
- Reference docs: use `docs/DOCS_INDEX.md` to find implementation, operator, and development guidance outside the core set
- Plan docs: `docs/ROADMAP.md`, `docs/V56_FORWARD_LINE.md`, and the docs under `docs/tracks/`
- Historical docs: read only for background after the core docs; they are not current truth

## Quickstart (Developer / CI)
Install and run the fast test suite (no vault required):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"

make smoke
```

## Quickstart (Local Runtime With A Vault)
Bring up the full local stack (db + api + watcher + worker) via the operator script:

```bash
export VAULT_ROOT="/path/to/your/vault"
scripts/start_full_system.sh

curl -sS http://127.0.0.1:18000/api/health
curl -sS http://127.0.0.1:18000/api/status
```

Common safety switches:
- `WATCHER_AUTO_EXEC=0` switches watcher to emit-only mode (default is `1`).
- `WATCHER_SCOPE_GLOB="<inbox>/**"` restricts watcher scanning (default derives from vault layout/inbox).

## Golden Path (Alpha E2E)
The canonical “does the whole chain work?” contract lives in `docs/runbooks/E2E_ALPHA.md`.

```bash
export VAULT_ROOT="/path/to/vault"
make alpha-up
python -m scripts.alpha_e2e
make alpha-smoke
```

## CI Gates (Fitness Summary)
CI jobs parse `CI SUMMARY …` lines and fail merges when `GATES.ok != true`.
See `docs/TESTING.md` and `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`.

## Historical References
SoT v4.10 is the historical Reality-MVP foundation snapshot and is not current runtime truth. Read `docs/STATUS.md` and `docs/ARCHITECTURE.md` first; use the references below only for background:
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
- `docs/history/SOT_4X_HISTORY.md`

The current baseline is v5.5; forward-line work for v5.6 is tracked in `docs/V56_FORWARD_LINE.md`.
