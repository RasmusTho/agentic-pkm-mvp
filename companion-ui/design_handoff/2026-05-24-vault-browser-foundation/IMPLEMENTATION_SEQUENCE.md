# Vault Browser Foundation · Implementation Sequence

**Tracking issue:** #1261
**Status:** Planning guardrail · non-binding sequencing
**Authority:** Sequencing recommendation. Repo SoT (`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` and the docs listed below) remains authoritative. The Claude Design handoff at `2026-05-24-vault-browser-foundation/` is non-authoritative.

This document records the agreed execution order for the Vault Browser
Foundation workstream after the Claude Design handoff landed in #1259 (PR
#1262). It exists to prevent starting downstream UI work before the workspace
shell is aligned with the orientation contract, and to keep the issue
boundaries of #1253–#1257 stable.

## Authority

**Source of truth (overrides all design wording):**

- [`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`](../../../docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md)
- [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md)
- [`docs/COMPONENTS.md`](../../../docs/COMPONENTS.md)
- [`docs/HUMAN-FLOWS.md`](../../../docs/HUMAN-FLOWS.md)
- [`docs/FRONTMATTER.md`](../../../docs/FRONTMATTER.md)
- [`docs/EVENTS.md`](../../../docs/EVENTS.md)
- [`docs/AGENT_MEMORY/README.md`](../../../docs/AGENT_MEMORY/README.md)
- [`docs/CONTEXTUALIZATION_LAYER/README.md`](../../../docs/CONTEXTUALIZATION_LAYER/README.md)
- [`companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`](../../docs/PANEL_COMPANION_UI_CONTRACT.md)
- [`companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`](../../docs/MLP_INTERACTION_DESIGN_HANDOFF.md)
- [`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../docs/DESIGN_HANDOFF_GOVERNANCE.md)

**Non-authoritative design input:**

- [`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md) — Claude
  Design handoff, landed for #1259.
- [`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md) — design →
  issue mapping.

If a design recommendation conflicts with SoT, the SoT wins. Such conflicts
must route through `issue-maintenance-change-control` and never through silent
SoT edits.

## Current shipped baseline

- **#1251 / #1252** — long-term Vault Browser capability contract and
  read-only Vault Browser MLP v0 alignment. Delivered by PR #1258.
- **#1259** — Claude Design handoff landed as non-authoritative design
  artifact under `companion-ui/design_handoff/2026-05-24-vault-browser-foundation/`.
  Delivered by PR #1262.

The browser today: read-only Markdown enumeration, deterministic
text/path/title query, active vault/channel identity, hidden/system-folder
exclusion, explicit empty/error/identity-unavailable states.

## Execution sequence

Recommended order — top to bottom, do not skip:

| # | Issue | What | Why this position |
|---|---|---|---|
| 1 | **#1259** (done) | Land Claude Design handoff as non-authoritative artifact. | Makes design insight traceable and diffable before any downstream slice consumes it. |
| 2 | **#1261** (this) | Lock sequencing plan. | Prevents starting the wrong downstream slice. |
| 3 | **#1260** | Align Companion workspace shell with Vault Browser orientation contract. | The workspace is the surface the browser opens notes into. Without alignment, deeper UI work (#1255–#1257) lands in a cognitively noisy shell that re-renders frontmatter as body and leaks state vocabulary. |
| 4 | **#1253** | Normalized artifact metadata read model. | Server-owned read model is the foundation for filters, badges, inspector, and action surfaces. Blocks #1254, #1255 data tabs. |
| 5 | **#1254** | Deterministic metadata filters and badges. | Consumes #1253 read model. List-layer; required before inspector data tabs are useful, but inspector itself can move in parallel after #1253. |
| 6 | **#1255** | Artifact inspector panel. | Inspector data tabs (Metadata, Health, Provenance) consume #1253. Preview tab is independent. Honest placeholders for Links / Receipts. |
| 7 | **#1256** | Define and render VaultAction model. | Six-mode display contract. Cannot land cleanly until inspector exists to host the Actions tab; cannot collapse `bounded_system_write` and `governance_write`. |
| 8 | **#1257** | Show agent receipts and review posture in inspector. | Receipts + Activity tabs. Consumes #1256 (for action receipts) and #1255 (host tabs). Read-only — does not author receipts. |

### Why #1260 precedes deeper browser UI work

The §02 critique in [`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md)
identifies seven problems in the current workspace shell that would defeat the
browser's orientation contract if not addressed first:

- **C1.** Frontmatter rendered as note body — the user splits body from
  metadata manually every open. The inspector design assumes the workspace
  consumes parsed metadata via chrome, not as prose.
- **C2.** Three stacked safety/status rows with equal weight — degraded posture
  is invisible. The browser depends on a single legible posture surface so
  WriteGuard / degraded / blocked states cannot be silently buried.
- **C3.** Disabled affordances rendered as enabled — the addendum's rule
  already says "remove the button entirely in read-only." The Vault Browser's
  blocked-action treatment uses the same pattern.
- **C4.** Backend state vocabulary leaks (`E I`, `composer enabled · thinking`,
  `FIND · unavailable`). The browser's `data-*`-only state contract assumes
  user copy is written by humans, not exposed by the runtime.
- **C5.** Artifact identity strip visually buried. The browser's safety/identity
  strip is supposed to be permanent chrome; if the workspace can't host it as
  chrome, the browser inherits the same legibility loss.
- **C6.** Right rail filled with idle/unavailable stubs. The browser's empty /
  degraded / blocked rules assume the workspace doesn't pre-emptively fill the
  rail with state-machine labels.
- **C7.** The shell is currently shaped for a runtime engineer running UAT,
  not for the human-first cognitive prosthetic user described in
  `docs/HUMAN-FLOWS.md §0`.

Until C1–C5 are resolved, inspector tabs for Metadata / Health / Provenance
(#1255) and the action display matrix (#1256) cannot be evaluated for
legibility — the workspace re-renders frontmatter as body and the chrome the
inspector mirrors does not exist in a legible form.

### Why #1253 and #1254 can move after #1260

The read model (#1253) is a server/runtime concern with API + frontmatter
parsing semantics. It does not depend on the workspace-shell critique. It
*does* depend on #1260 by sequencing — once #1260 is unblocked and the shell
is corrected, the read model adds the data substrate that the filters (#1254),
inspector data tabs (#1255), and downstream surfaces consume.

If the landed design handoff or a downstream review reveals a stricter
dependency between #1260 and #1253/#1254 (e.g. a frontmatter-parsing boundary
moves), use `issue-maintenance-change-control` to record the change. Do not
silently re-scope.

### Why #1255, #1256, #1257 wait for #1260

Inspector tabs, action display, and receipts/review posture all surface
through chrome and a per-artifact identity strip. The workspace shell hosts
both. If the workspace renders frontmatter as body, leaks runtime vocabulary,
and buries identity, the inspector design from §09 of the design handoff
cannot be evaluated for legibility. Landing #1255/#1256/#1257 before #1260
would either re-introduce the C1–C5 problems or require a second pass to
unwind them.

## Issue-scope discipline

- Each downstream issue (#1253–#1257) ships in its own PR.
- Scope of #1253–#1257 is bound by their issue bodies. The design handoff is
  input, not a contract change. If the design implies scope changes, route
  through `issue-maintenance-change-control`.
- No silent re-scoping. If a slice's AC needs amendment, the Issue is amended
  first, then the PR follows.
- One issue → one PR by default. Combining is allowed only when repo workflow
  explicitly permits it and AC mapping remains separate.

## Stop conditions

Stop and escalate before continuing if any of the following are true:

- A repo-local skill contradicts this sequence.
- A SoT doc contradicts the design handoff. Preserve the conflict in
  [`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md) "Conflict-with-SoT
  log" and open an `issue-maintenance-change-control` issue.
- A downstream issue requires scope change — handle through
  `issue-maintenance-change-control` before implementation.
- A new event is required but `docs/EVENTS.md` ownership is unclear — update
  events in the same PR that introduces them.
- A proposed write bypasses WriteGuard / governance / receipts — never bypass.
- DB/store state would become authoritative over Vault/Markdown — never
  invert the source-of-truth direction.
- Required validation cannot run — fix the validation gap before merging.

## Future backlog candidates (not in this sequence)

The following design recommendations are **not** part of the #1253–#1257
foundation. They must not be implemented as part of this workstream. They are
captured here for visibility and should be converted into bounded issues only
via the `docs-to-issue` / `feature-breakdown` skills under a planning lane
(see Phase E in #1261's downstream tracking, or a fresh planning issue):

- Saved views (deterministic only).
- Timeline / activity browsing.
- Artifact relation read model.
- Links / relations inspector beyond placeholder.
- Graph view as secondary browsing mode (never landing; never default).
- Source / evidence dependency browser.
- Review campaigns.
- Guarded bulk operations.
- Resurfacing candidates view (read-only first).
- Duplicate candidates.
- Contradiction candidates.
- Agent activity explorer.
- Responsive / mobile read-only behavior.
- Visual hierarchy / density pass (workspace shell + browser, after #1260
  empirically validated).

See [`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md) "Future-backlog
candidates" for the per-item source-section references and §19 verdict tier
(must / near / defer / later).

## Core philosophy invariants

These hold across every slice in this sequence. They are not negotiable:

- **Human-first, vault-driven, local-first.** Markdown/Vault is the human
  control surface; stores/DB are machine mirrors.
- **Companion UI is a cognitive prosthetic, not autonomous authority.** It
  surfaces, ranks, and explains; it never auto-applies.
- **Human flow before agent automation.** No surface that collapses browsing,
  body-editing, governance, or agent proposal.
- **Explicit governance over hidden execution.** Receipts, traceability,
  trust, provenance, review posture are first-class signals.
- **Orientation, retrieval, and resurfacing are separate capabilities.** The
  browser does not become an inbox, a graph landing, or a notification feed.
- **No hidden writes.** Navigation does not mutate.
- **No UI-invented authority.** The UI renders what the runtime declares; it
  never reclassifies.
- **No DB/store state as source of truth.** Vault frontmatter and Markdown
  remain authoritative.
- **No LLM-mediated mutation without governance, guardrails, and receipts.**
- **No graph-first design.** Graph is a future optional view, never the
  default landing (capability contract §8).

## References

- [`README.md`](README.md) — design handoff package README.
- [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md) — source URL and input package.
- [`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md) —
  converted design handoff.
- [`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md) — design →
  issue mapping.
- [`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`](../../../docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md)
  — authoritative capability contract.
