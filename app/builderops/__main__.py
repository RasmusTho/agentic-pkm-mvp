"""Standalone entry point for the BuilderOps CLI.

Allows running BuilderOps commands from any automation worktree without
importing the broader ``app.cli`` dependency chain (which requires yaml,
pydantic, watchfiles, httpx, and other optional packages). The command
implementation lives in :mod:`app.builderops.cli`, so importing it here does
NOT trigger ``app.cli``'s package initializer.

Usage::

    python3 -m app.builderops builderops list --type LearningSignal --json
    python3 -m app.builderops builderops create-learning-signal \\
        --summary "..." --content "..." --signal-type workflow \\
        --source-ref github_issue:#1234 --json
    python3 -m app.builderops builderops append-receipt ...

The ``builderops`` subcommand name is kept so that the invocation mirrors
``python3 -m app.cli builderops ...`` and automation scripts need no
special-case handling for each entry point.
"""

from __future__ import annotations

import click

from app.builderops.cli import builderops as builderops_cli


@click.group(help="BuilderOps Vault CLI (standalone entry point).")
def _root() -> None:
    ...


_root.add_command(builderops_cli, name="builderops")

if __name__ == "__main__":
    _root()
