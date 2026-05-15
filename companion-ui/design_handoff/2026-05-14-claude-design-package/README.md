# Claude Design Package — 2026-05-14

**Date:** 2026-05-14 (v1) · 2026-05-15 (v2 refinement)
**Status:** Design handoff · v2 · ready for review at crossing B (handoff → normalized spec)
**Authority:** Visual guidance only — process pattern + four UI surfaces
**Owner-docs touched:** read-only references; no owner-doc is modified by this package

## What this is

Five governed handoff packages, plus this index. Produced as a Claude Design exploration
under the `claude-design-context` brief; conform to the folder shape proposed by Package 01
(the Handoff Governance Pack — package 01 governs the process the other four were produced
under).

Open `index.html` for the executive summary, package cards, and the Implementation Intake
Summary.

## Implementation Intake Summary

The table below is the only document a repo maintainer should need to read in order to
decide what to import, what to schedule as issues, and what must remain design-only.

| Design artifact | What it is for | Related repo issue(s) | What **may** be implemented later | What **must not** be implemented directly | Architecture dependencies | Open questions |
|---|---|---|---|---|---|---|
| **01 · Handoff Governance Pack** | Process pattern that turns design explorations into governed implementation inputs. Six-link chain (`exploration → handoff → normalized spec → issue → PR → receipt`), maturity bar, three templates, review console. | **#901** | Folder shape adoption across `companion-ui/design_handoff/`; static review console rendered from the folder; maturity-checklist front-matter on existing READMEs. | A runtime review service. A new authority over owner-docs. A blocking gate on PRs (only on crossing B). | `docs/INTERACTION_SURFACES_AND_AUTHORITY/` (read-only); the governance pack does not modify it. | Where the console lives (suggest: static HTML); single vs. dual reviewer; superseded-package handling. |
| **02 · Runtime Proof / Health Dashboard** | Compact single-operator proof surface answering nine runtime-health questions; mirrors runtime state without acting on it. | **#865**, **#866**, **#850** + runtime stabilization issues | UI render against fixture snapshots; receipt-link disclosures on governed counts; nine state fixtures (incl. watcher OOM, worker poison, stale heartbeat, proof not-yet-run, proof failed-but-actionable). | Auto-remediation. UI-derived posture. A dashboard-as-control-plane direction. An ops-style alert channel. | `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` (invariant); future runtime-proof receipt contract (depends on, does not own). | Polling vs push transport; "blocked" terminology disambiguation (policy vs failure); proof history window. |
| **03 · Context Bundle Inspector** | Inspectable bridge object between retrieval, orientation, resurfacing, and write proposals — authority flags, included/excluded artifacts, ranked candidates, compact vs expanded mode. | **#894**, **#895**, **#896** | UI render against three fixture bundles (retrieval, orientation, write-proposal); compact-mode embedding next to chat turns; ranked-candidate column with score+outcome; six fail-state fixtures. | Re-ranking. Apply / writeback affordance. Memory promotion. Modification of the bundle schema. | `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` (read-only). | Default exclusion-visibility threshold; bundle-receipt taxonomy; "why now" field location for resurfacing bundles. |
| **04 · Memory Candidate Review Queue** | Pull-based queue for proposed agent memories with a persistent "unreviewed memory is not semantic authority" banner and explicit anti-inbox mitigations. | **#900** | UI render against ten fixture candidates; seven primary actions; conflict UI; promote-to-note path through governance; auto-archive policy implementation. | Auto-accept rules. A recall surface. Definition of memory class. Semantic-search across past memories. Notification badges in the shell. | `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` (read-only). | Confidence presentation (numeric vs banded); conflict-resolution UI (`keep both` validity); pacing-throttle policy; auto-archive default interval. |
| **05 · Vault Action Layer / Agent Tool Authority** | 9-step pipeline (`intent → classify → bound → policy → guard → idempotency → execute → receipt → event`), 5-tier tool taxonomy, Obsidian/MCP-as-adapter boundary, concrete first action (`move_inbox_note_to_workbench`). | **#910** + future tool-authority docs issue | First bounded action `move_inbox_note_to_workbench`; Tier-4 forbidden list as owner-doc; registry-write path; Obsidian adapter; MCP-exposed surface restricted to registry names. | A generic "agent tools" library decoupled from the registry. Obsidian/MCP as primary mutation authority. Runtime tier-elevation. Silent failure paths. | New owner-doc to author (`docs/CONCEPTS/VAULT_ACTION_LAYER_CONTRACT.md`); references `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` and `INTERACTION_SURFACES_AND_AUTHORITY/`. | Tier 1 vs Tier 3 distinction durability; idempotency window default; collision-rule taxonomy; cross-vault actions tier; classifier-confidence-to-tier coupling. |

## Packages

1. **`../2026-05-14-handoff-governance-pack/`** — Design Handoff Governance Pack.
2. **`../2026-05-14-runtime-proof-dashboard/`** — Runtime Proof / Health Dashboard.
3. **`../2026-05-14-context-bundle-inspector/`** — Context Bundle Inspector.
4. **`../2026-05-14-memory-candidate-review/`** — Memory Candidate Review Queue.
5. **`../2026-05-14-vault-action-layer/`** — Vault Action Layer / Agent Tool Authority. **(new in v2)**

See `CHANGELOG.md` for the v1 → v2 diff.

## What to import into the repo

The minimum-viable import is a single owner-doc per package (where applicable) plus the
prototype HTML as a design reference. Each package's prototype is self-contained — copy the
folder into `companion-ui/design_handoff/` and the file shape works.

- `companion-ui/design_handoff/2026-05-14-handoff-governance-pack/` → as-is.
- `companion-ui/design_handoff/2026-05-14-runtime-proof-dashboard/` → as-is.
- `companion-ui/design_handoff/2026-05-14-context-bundle-inspector/` → as-is.
- `companion-ui/design_handoff/2026-05-14-memory-candidate-review/` → as-is.
- `companion-ui/design_handoff/2026-05-14-vault-action-layer/` → as-is.
- `companion-ui/design_handoff/2026-05-14-claude-design-package/` → the index, this README,
  and the CHANGELOG.

## What should become issues later

These are the proposed normalized-spec authorings that the crossing-B reviewer would
authorize, and the first follow-on implementation issue under each.

| Package | Proposed normalized spec | First implementation issue |
|---|---|---|
| 01 | `docs/INTERACTION_SURFACES_AND_AUTHORITY/DESIGN_HANDOFF_GOVERNANCE.md` | Adopt folder shape across existing `companion-ui/design_handoff/` packages. |
| 02 | `docs/RUNTIME_PROOF_DASHBOARD.md` (UI guidance, target-state) | Render dashboard against nine fixture snapshots. |
| 03 | `docs/CONCEPTS/CONTEXT_BUNDLE_INSPECTOR_UI.md` (UI guidance) | Render inspector against three fixture bundles + six fail-state fixtures. |
| 04 | `docs/CONCEPTS/MEMORY_CANDIDATE_REVIEW_UI.md` (UI guidance) | Render queue against ten fixture candidates; wire seven primary actions. |
| 05 | `docs/CONCEPTS/VAULT_ACTION_LAYER_CONTRACT.md` (new owner-doc) | Register first bounded action `move_inbox_note_to_workbench@v1`; full pipeline against fixture vault. |

## What must remain design-only

These items are deliberately not in any of the proposed normalized specs and would be
rejected if they appeared in an implementation PR.

- Any **runtime claim** asserted by a design doc. The dashboard, inspector, queue, and
  action layer all render target-state behavior; only owner-docs and shipped code may assert
  current runtime behavior.
- **Auto-remediation** for runtime-proof states. Every action is the operator's explicit
  click.
- **UI-derived posture, class, authority, or classification.** The server declares; the UI
  renders.
- **Bundle schema changes** from package 03. The inspector renders the bundle contract; it
  does not modify it.
- **Memory class set additions** from package 04. The contract owns the class taxonomy.
- **Registry semantics** from package 05. Tier 4 stays empty; new bounded actions only via
  registry PRs.
- **Obsidian / MCP as the primary mutation path.** Adapter, not authority — this is a
  cross-package design constraint, not a workspace preference.

## How to read

- **For a crossing-B reviewer:** read this README, then `index.html`, then walk the maturity
  checklist in package 01 §03 against each of packages 02–05.
- **For Claude Code / Codex:** read each package's `README.md` and
  `implementation-contracts.md`, then `prototype.html` §07-§08 and the final "Handoff" section.
- **For an owner-doc reviewer:** read each package's `authority-boundaries.md` and
  `open-questions.md`; cross-reference the **Architecture dependencies** column above.

## Disclaimers

- Design exploration is not architecture authority. Architecture authority remains in repo
  owner-docs and contracts.
- Runtime truth remains in shipped code, tests, status docs, and validation receipts.
- This package proposes; it does not promote. Promotion happens at crossing B.
- The gated-execution invariant is honored across all five packages.
