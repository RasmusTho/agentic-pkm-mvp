# Local Agent Hooks

These hooks are local-session safety aids for builder agents. They do not handle GitHub events and
must not push, merge, close issues, edit labels, change Project state, post comments, or mutate
product/runtime state.

## SessionStart

Run the existing workspace preflight before local work:

```bash
scripts/agent_workspace_preflight.sh --allow-dirty
```

Agents with a captured branch/worktree should pass `--expected-branch` and `--expected-worktree`.

## PreToolUse: Bash

Check proposed shell commands with:

```bash
python3 scripts/local_agent_command_guard.py --command "$COMMAND"
```

Exit code `0` means the command is allowed. Exit code `1` means the command is blocked because it is
destructive, production/stable-affecting, secret/vault-affecting, or a GitHub mutation that belongs
to an explicit workflow step rather than a passive hook.

## Failure Mode

Hooks should fail closed for blocked commands and fail open for unavailable optional reporting. A
hook must not retry GitHub/API operations or create routine notifications.
