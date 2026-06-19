State: Reference inventory of code import-boundary coupling, updated 2026-06-16 via #2085 (all namespace packages converted to regular packages). Snapshot, not a contract; the authoritative rule is `docs/adr/ADR-0013-code-dependency-direction.md` and `importlinter.ini`.
Doc role: Reference
Authority: Non-authoritative snapshot. Records current backward/past-contract import leaks and shared-hub fan-out so they can be tracked to follow-up FIX issues. Does not define the boundary rule (ADR-0013 does) and does not gate anything.
Owner: Architecture
Temporal class: Snapshot (point-in-time inventory; refresh when the boundary contract changes)
Review cadence: On change to `importlinter.ini` / ADR-0013 or the recorded leaks
Source of truth: `docs/adr/ADR-0013-code-dependency-direction.md` and `importlinter.ini` (this doc is a non-authoritative snapshot)
Last reviewed: 2026-06-16

# Import Boundary Inventory

Coupling snapshot taken while landing the directional import-boundary contract (#2070, ADR-0013).
The contract enforces one invariant — **nothing outside the interaction layer (`api`/`chat`/`cli`/`web`)
may import it** — non-blocking on PRs. This file records the leaks that contract surfaces, the leaks
it cannot yet see, and the shared-hub fan-out, each routed to a follow-up.

## A. Machine-enforced leaks (reported by `lint-imports --config importlinter.ini`)

| Leak | Kind | Fix direction | Follow-up |
|---|---|---|---|
| `app.panel.checkbox_projection → app.api.routes.artifacts` (l.23, private `_content_hash`) | cognition → interaction, into private | extract `_content_hash` to a foundation util both import downward | #2083 |
| `app.orientation.leave_point_cursor → app.api.routes.artifacts` (l.14, private `_content_hash`, `_extract_title`) | cognition → interaction, into private | shared-helper extraction | #2083 |
| `app.orientation.leave_point_cursor → app.chat.canvas_writer` (l.15, private `_split_frontmatter`) | cognition → interaction, into private | shared-helper extraction | #2083 |

The `app.observability.status_service → app.cli.health` cycle (and its two transitive rows via
`app.resurfacing.runtime` and `app.orientation.runtime`) is no longer present: #2084 (closed) relocated
the health seam so `_check_v6_seams` now lives in `app.observability.status_service` and `app.cli.health`
imports it downward, leaving `status_service` with no `app.cli` import. The contract no longer reports it.

## B. Not yet machine-enforced (intra-interaction only)

All `app/` subdirs are now regular packages (have `__init__.py`) as of #2085, so namespace-package
exclusions are no longer needed. `app.orientation` and `app.reasoning` are now covered by the
contract (and their violations appear in section A above, routed to #2083).

Intra-interaction private reaches are below module granularity and therefore still recorded manually:

| Leak | Kind | Fix direction | Follow-up |
|---|---|---|---|
| `app.api.routes.companion` / `app.api.routes.canvas → app.chat.canvas_writer` (private `_split_frontmatter` / `_body_contains_frontmatter`) | intra-interaction, past-contract | shared-helper extraction | #2083 |

## C. Shared-hub fan-out (foundation leaves — documented, not a leak)

These are foundation packages that many modules import. They are legitimate **only while they stay
leaves** (no upward imports). Tracked to keep them that way, not to remove them.

| Hub | Importers (distinct files) | Note |
|---|---|---|
| `app.events` | 63 | Keep leaf-like; `events.schema` reaching up into `settings.runtime` is the kind of edge to avoid |
| `app.settings` | 43 | Keep leaf-like; broad fan-out is acceptable only because it is a pure-contract leaf |

De-coupling or re-homing the hubs is out of scope here; this row exists so growth stays leaf-safe
(ADR-0013, "Foundation must stay acyclic and upward-free").

## References

- `docs/adr/ADR-0013-code-dependency-direction.md` — the governing decision
- `importlinter.ini` — the enforced contract
- `.github/workflows/import-linter.yaml` — non-blocking PR runner
- Follow-ups: #2083 (shared helpers), #2084 (obs↔cli cycle), #2085 (namespace packages)
