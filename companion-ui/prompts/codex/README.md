# Codex Prompts

Use this folder for prompts focused on workspace architecture, implementation staging, and refactor tasks.

Prompt posture:
- Preserve vault canonicality.
- Keep runtime state ephemeral unless explicitly persisted.
- Maintain compatibility with event-driven runtime and AgentState.

## Available prompts

- [`deliver-epic-autonomous-runner.md`](deliver-epic-autonomous-runner.md) — large-scope autonomous
  epic / issue-set delivery runner with TCD routing, narrow Human Exception handling, and a governed
  Claude Design handoff for interaction-design dependencies.
