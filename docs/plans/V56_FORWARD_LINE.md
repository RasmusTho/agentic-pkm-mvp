State: SoT v5.6 forward line kickoff (docs-first)
# SoT v5.6 Forward Line Kickoff

## Objective
Document the first v5.6 forward-line milestone so the team can keep v5.5 baseline stability while preparing the LangGraph + Reasoning + orchestrator rollout with explicit gating, provenance, and acceptance criteria.

## Pillars
- **Safe automation** — watcher auto-run remains disabled until allowlists, dedup counts, and skipped receipts are observable in status and event logs; enablement requires CI gates reporting `GATES.ok=true`.
- **LangGraph determinism** — PanelAgent's planner/Promotion consumer path (PanelActionIntent → planner → promotes) stays opt-in through CLI flags while telemetry validates the transition.
- **Traceable runtime** — Vault-as-GUI settings compiler, `app.cli.settings_explain`, and Status/CI docs describe the provenance/precedence of panel actions, watcher policy, and outbox paths.
- **Gateproof rollout** — `ci-smoke`, `ci-lite`, and `ci` jobs parse `CI SUMMARY GATES` and fail on `GATES.ok!=true`; the forward line must keep those signals green before any runtime-enable decision.
- **Agent context infrastructure** — VaultMirror is replaced by companion notes (`vault/_system/companions/<uuid>.md`) and a `NoteContext` assembler that gives agents structured multi-surface context instead of raw 800-char snippets. This is the prerequisite for meaningful agent quality improvements in v5.6+. Full plan: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md`. Parts 1–5 can ship independently; Parts 6–7 wire the Panel Agent improvement and should land before the PanelAgent 2.0 milestone.

## Acceptance criteria
- The new `docs/STATUS.md` and `docs/ROADMAP.md` sections describe the v5.6 Now/Next/Later plan and trace to this document.
- The new watcher + panel plan states the required grooming: dedup guard coverage, concurrency instrumentation, and CLI exposure for letting operators inspect the allowlist and gating decisions.
- ReasoningFacade + LangGraph + Orchestrator V2 readiness (pilot scope) is described in the Next list before any automatic rollout.
- Fitness gates (status counters + `CI SUMMARY GATES`) remain the controlling signal for unlocking successive v5.6 stages.

## Definition of done (v5.6A / v5.6B)
- **v5.6A (Docs + pilot readiness)**: doc set updated, CLI exposures present, concurrency/dedup instrumentation passes, and watchers autop-run instrumentation is traceable; gates stay green on Pilot CLI run.
- **v5.6B (Reasoning + orchestrator)**: LangGraph rollout for the next agent pool passes gating metrics, orchestrator V2 experiment flag is documented, and onboarding runbooks (status, CI, ops) mention the new forward line status.

## Out of scope for this doc
No runtime behavior changes are merged yet—watcher auto-run stays off, LangGraph rollout remains opt-in, and orchestrator V2 toggles remain under feature flags until the gates confirm readiness.
