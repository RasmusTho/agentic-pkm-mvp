State: SoT v5.6 forward line kickoff (docs-first)
# SoT v5.6 Forward Line Kickoff

## Objective
Document the first v5.6 forward-line milestone so the team can keep v5.5 baseline stability while preparing the LangGraph + Reasoning + orchestrator rollout with explicit gating, provenance, and acceptance criteria.

## Pillars
- **Safe automation** — runtime/startup currently defaults `WATCHER_AUTO_EXEC=1`, but operators can force emit-only mode with `WATCHER_AUTO_EXEC=0`; safe rollout still requires allowlists, dedup counts, skipped receipts, and CI gates reporting `GATES.ok=true`.
- **LangGraph determinism** — PanelAgent's planner/Promotion consumer path (PanelActionIntent → planner → promotes) stays opt-in through CLI flags while telemetry validates the transition.
- **Traceable runtime** — Vault-as-GUI settings compiler, `app.cli.settings_explain`, and Status/CI docs describe the provenance/precedence of panel actions, watcher policy, and outbox paths.
- **Gateproof rollout** — `ci-smoke`, `ci-lite`, and `ci` jobs parse `CI SUMMARY GATES` and fail on `GATES.ok!=true`; the forward line must keep those signals green before any runtime-enable decision.

## Acceptance criteria
- The new `docs/STATUS.md` and `docs/ROADMAP.md` sections describe the v5.6 Now/Next/Later plan and trace to this document.
- The new watcher + panel plan states the required grooming: dedup guard coverage, concurrency instrumentation, and CLI exposure for letting operators inspect the allowlist and gating decisions.
- Shared ReasoningFacade/common graph scaffolding + LangGraph + Orchestrator V2 readiness (pilot scope) is described in the Next list before any broader automatic rollout.
- Fitness gates (status counters + `CI SUMMARY GATES`) remain the controlling signal for unlocking successive v5.6 stages.

## Definition of done (v5.6A / v5.6B)
- **v5.6A (Docs + pilot readiness)**: doc set updated, CLI exposures present, concurrency/dedup instrumentation passes, watcher auto-run instrumentation is traceable, and gates stay green on Pilot CLI run.
- **v5.6B (Reasoning + orchestrator)**: LangGraph rollout for the next agent pool passes gating metrics, orchestrator V2 experiment flag is documented, and onboarding runbooks (status, CI, ops) mention the new forward line status.

## Out of scope for this doc
No additional runtime-enable decision is implied by this doc: watcher auto-run still defaults to `WATCHER_AUTO_EXEC=1` in startup/runtime config, operators can force emit-only mode with `WATCHER_AUTO_EXEC=0`, LangGraph rollout remains opt-in, and orchestrator V2 toggles remain under feature flags until the gates confirm readiness.
