---
name: automation-maintenance
description: "Inspect and maintain Codex app automations for this repository, especially cwd drift between the redirect workspace and the canonical repo root."
---

# Automation Maintenance

Use this governance skill when asked to inspect, repair, or report Codex app automations for this
repository.

Codex app automation definitions live under `$CODEX_HOME/automations/*/automation.toml` as local
operational state. They are not repo source truth and must not be committed into this repository.

## Canonical repository cwd

Canonical repo automations for `RasmusTho/agentic-pkm-mvp` must use:

```text
/Users/rasmusthornberg/code/agentic-pkm-mvp
```

An automation may use a different `cwds` entry only when its prompt or a repo issue documents a
specific justified exception. The redirect workspace
`/Users/rasmusthornberg/Documents/New project` is stale for this repository.

## Inspection workflow

1. Read `AGENTS.md` and this skill.
2. Inspect local automation definitions:
   ```bash
   AUTOMATION_HOME="${CODEX_HOME:-$HOME/.codex}/automations"
   find "$AUTOMATION_HOME" -maxdepth 2 -name automation.toml -print
   rg -n "agentic-pkm-mvp|Documents/New project|cwds|prompt|id" "$AUTOMATION_HOME"
   ```
3. Identify automations for this repo by `cwds`, prompt text, id, name, or memory references to
   `RasmusTho/agentic-pkm-mvp` or `agentic-pkm-mvp`.
4. For each matching automation, classify `cwds`:
   - `canonical`: every repo cwd points at `/Users/rasmusthornberg/code/agentic-pkm-mvp`
   - `redirect`: any repo cwd points at `/Users/rasmusthornberg/Documents/New project`
   - `stale`: any repo cwd points at another old worktree or branch workspace without a documented exception
   - `uncertain`: the automation appears related to this repo but the intended cwd is not clear
5. Do not inspect or mutate unrelated automations beyond listing them as skipped.

## Safe update behavior

- Prefer the Codex app automation update tool when it is available in the current environment.
- Update only the matching automation ids that are in scope.
- Preserve the existing prompt, schedule, model, status, and environment fields unless the task
  explicitly asks to change them.
- Change `cwds` to the canonical repo root only when the automation is clearly for this repo and no
  justified exception exists.
- If the update tool is unavailable, blocked, or ambiguous, do not edit `automation.toml` files by
  hand. Report exact pending changes instead.
- If durable follow-up is needed, create or update a GitHub Issue with the automation id, current
  cwd, intended cwd, and blocker. Do not treat local automation state as repo truth.

## BuilderOps CLI dependency setup

BuilderOps CLI commands require `click`, `pydantic`, and `sqlite3`.  Host Python
interpreters (e.g. `/opt/homebrew/bin/python3`) typically lack these packages.

**Supported invocation path for automation worktrees:**

```bash
# Option 1 — wrapper script (recommended; resolves venv automatically):
scripts/builderops_cli.sh builderops list --type LearningSignal --json
scripts/builderops_cli.sh builderops create-learning-signal \
  --summary "..." --content "..." --signal-type workflow \
  --source-ref github_issue:#1234 --json

# Option 2 — explicit venv python from the repo root or a worktree:
.venv/bin/python3 -m app.builderops builderops list --type LearningSignal --json
.venv/bin/python3 -m app.cli builderops list --type LearningSignal --json
```

`scripts/builderops_cli.sh` walks upward from the script directory to find the
nearest `.venv/bin/python3`; when a Codex app worktree lives outside the
canonical checkout tree, it also uses git worktree metadata to locate the
canonical checkout venv. It then runs `python3 -m app.builderops`.  It works
from the repo root and from git worktrees under `$CODEX_HOME/worktrees/`.

**One-time venv setup** (if no `.venv` exists yet):

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

Do not require agents to install deps globally or bypass the venv.  Do not fall
back to `docs/learning-log.md` as a substitute for BuilderOps CLI unavailability;
fix the Python interpreter instead.

## BuilderOps adoption checks

When maintaining repo automations, also inspect whether recurring prompts route BuilderOps material
without depending on human memory.

- Automations that inspect delivery learning must read BuilderOps `LearningSignal` records first and
  use `docs/learning-log.md` only for historical or explicit compatibility fallback entries.
- Automations that audit docs freshness must create or propose `DocsFreshnessRecord` material for
  high-churn review state instead of editing `docs/DOCS_INDEX.md` as an operational queue.
- Automations that inspect roadmap or issue movement must create or propose
  `RoadmapExecutionItem` material for execution state instead of turning `docs/ROADMAP.md` into a
  daily status log.
- Automations that discover cross-surface changes must create or propose `PromotionIntent` material
  before GitHub Issue, PR, ADR, owner-doc, skill, AGENTS, projection, or discard handling.
- Automation prompts should cite the repo-local skill they are following and should produce a short
  BuilderOps routing receipt: records created, projections/receipts updated, or `none` with a reason.

## Receipt shape

Every run must finish with a concise receipt:

```text
AUTOMATION MAINTENANCE RECEIPT
Reviewed: <automation ids or paths>
Changed: <id: old cwds -> new cwds, or "none">
Skipped: <unrelated ids and reason>
Pending: <exact intended changes not applied>
Residual uncertainty: <unknown ownership, missing tool, permission limits, or "none">
Follow-up Issue: <#n or "none">
```

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.
