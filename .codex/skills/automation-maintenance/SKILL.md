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

**Capturing learning:** if this work reveals a repeatable workflow gap, create a BuilderOps
`LearningSignal`; use `docs/learning-log.md` only as an explicit compatibility fallback.
