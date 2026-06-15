"""`vault` CLI command group — initialize vault-settings for a selected vault.

`python -m app.cli vault init --path <root>` scaffolds the Design Handoff
settings files (vault.md, paths.md, workflow.md, design-handoff.md,
companion-ui.md, local.md) so the watcher can start against a vault that
predates the vault-settings foundation. Idempotent — existing files are kept,
never overwritten (issue #1991).
"""

from __future__ import annotations

from pathlib import Path

import click

from app.vault.manager import get_vault_manager
from app.vault.promotion_preflight import vault_settings_preflight

_ROLES = ["primary", "automationNode", "testNode", "readOnlySatellite"]


@click.group(help="Vault settings management.")
def vault() -> None:
    """Vault settings commands."""


@vault.command("init", help="Initialize Design Handoff settings for a vault (idempotent).")
@click.option("--path", "vault_path", required=True, type=click.Path(), help="Vault root path.")
@click.option("--name", "vault_name", default=None, help="Vault name (defaults to the folder name).")
@click.option(
    "--machine-role",
    default="primary",
    type=click.Choice(_ROLES),
    show_default=True,
    help="Machine role written to local.md (controls watcher/indexing permissions).",
)
@click.option("--remember/--no-remember", default=True, help="Remember as the last-active vault.")
def vault_init(vault_path: str, vault_name: str | None, machine_role: str, remember: bool) -> None:
    """Scaffold vault-settings files (idempotent) and select the vault."""

    result = get_vault_manager().initialize_vault(
        Path(vault_path),
        vault_name=vault_name,
        machine_role=machine_role,  # type: ignore[arg-type]
        remember=remember,
    )
    for created in result.created_files:
        click.echo(f"created  {created}")
    for existing in result.skipped_existing_files:
        click.echo(f"exists   {existing}")
    ctx = result.context
    click.echo(f"vault status: {ctx.status}")
    if ctx.status != "selected":
        detail = f": {ctx.validation_error}" if ctx.validation_error else ""
        raise click.ClickException(f"vault not selected after init; status={ctx.status}{detail}")


@vault.command("preflight", help="Report whether a vault is initialized enough to promote into.")
@click.option("--path", "vault_path", required=True, type=click.Path(), help="Vault root path.")
def vault_preflight(vault_path: str) -> None:
    """Print the vault-settings promotion preflight for ``--path``."""

    pf = vault_settings_preflight(Path(vault_path))
    click.echo(f"status: {pf.status}  initialized: {pf.initialized}  blocking: {pf.blocking}")
    if pf.detail:
        click.echo(f"detail: {pf.detail}")
    if pf.remedy:
        click.echo(f"remedy: {pf.remedy}")
    if pf.blocking:
        raise click.ClickException("vault is not promotion-ready")


__all__ = ["vault"]
