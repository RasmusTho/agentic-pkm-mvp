State: SoT v5.5 Reality-MVP baseline (locked); v5.6 delivered and closed; v6.0 seams baseline shipped at capability-seam level; broader v6 runtime/product consumption is v6.1+.
# Agentic PKM — Vault-First, Event-Driven PKM Runtime

**Why this exists.** Agentic PKM (Yggdrasil) is a local-first **cognitive prosthesis**: it helps a person capture, organize, understand, enhance, and apply knowledge — and act on it — without surrendering authorship. Unaided memory leaks; the system absorbs the bookkeeping burdens (holding open loops, losing fleeting thought, reorienting after time away, keeping sources attributable) so human attention goes to thinking. It pursues two classes of value: **Cognitive Maintenance** (preserve cognition — capture, recall, orientation, continuity) and **Cognitive Expansion** (improve cognition — reflection, synthesis, learning, decision quality). See [`docs/COGNITIVE_PROSTHESIS_CHARTER.md`](docs/COGNITIVE_PROSTHESIS_CHARTER.md) for the full thesis.

**How it's built to be trustworthy.** Because the prosthesis is *active* (agents act on the human's behalf), it is governed: the Markdown vault stays canonical and human-authored, and every machine action is bounded by authority, leaves a receipt, and is reversible. The runtime mechanism below *serves* that purpose — it does not replace it.

Agentic PKM is a vault-first, event-driven PKM runtime:
- The human writing surface (a Markdown vault) remains the canonical artifact.
- Derived stores (DB tables, indexes, embeddings) are rebuildable mirrors.
- The runtime is guarded by CI fitness gates and explicit safety switches (watcher auto-run, dedup/idempotency, optimistic writes).

Start here:
- `docs/STATUS.md` — current baseline reality (v5.5); v5.6 delivered and closed; v6.0 seams baseline shipped; broader v6 runtime/product consumption is v6.1+
- `docs/ARCHITECTURE.md` — active runtime architecture source of truth
- `docs/HUMAN-FLOWS.md` — user-facing behavior contract
- `docs/DOCS_INDEX.md` — map of the wider documentation set, including reference and historical docs

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
- **Explicit watcher mode:** runtime startup defaults to `WATCHER_AUTO_EXEC=1`; set `WATCHER_AUTO_EXEC=0` for emit-only mode. Default-on still runs through allowlist, per-note opt-out, and write-safety gates.
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
- Plan docs (target-state / future-direction — not current baseline): `docs/ROADMAP.md`, `docs/plans/V60_ARCHITECTURE_TARGET.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, `docs/plans/PROTOCOL_SATELLITE_SYNC.md`, and the docs under `docs/tracks/`
- Historical plan docs: `docs/plans/V56_FORWARD_LINE.md` (delivered/closed)
- Historical docs are no longer retained as live repo files; use git history for removed snapshots.

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
- `WATCHER_AUTO_EXEC=0` switches watcher to emit-only mode. Runtime/startup defaults to `WATCHER_AUTO_EXEC=1` when unset.
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

## License
This repository is currently source-available under a limited preview license.
It is intentionally not released as open source while the project is unstable.
See [LICENSE.md](LICENSE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Contributions
Contributions and collaborations are welcome by prior discussion. See
[CONTRIBUTING.md](CONTRIBUTING.md) for contribution and relicensing terms.

## Historical References
SoT v4.10 is the historical Reality-MVP foundation snapshot and is not current runtime truth. Read `docs/STATUS.md` and `docs/ARCHITECTURE.md` first; older snapshots have been removed from the live repo and should be recovered from git history only when needed.

The current baseline is v5.5; v5.6 is delivered and closed; v6.0 seams baseline is shipped at capability-seam level. Broader v6 runtime/product consumption is v6.1+ work — see `docs/plans/V60_ARCHITECTURE_TARGET.md` and `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` for target-state design direction.
