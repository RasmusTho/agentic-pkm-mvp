# app/config package — submodule-level imports only.
# Do NOT add eager re-exports here.  app/__init__.py imports from
# app.config.llm at module level; any re-export that transitively imports
# yaml (e.g. app.config.agent) will break automation-worktree entry points
# such as ``python3 -m app.builderops`` which must work without a .venv.
# Use explicit submodule imports instead:
#   from app.config.agent import AgentConfig
