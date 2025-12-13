from __future__ import annotations

import click
from pathlib import Path

from app.watcher.vault_watcher import run_watcher_daemon, run_watcher_tick


def _echo_summary(summary: dict) -> None:
    click.echo(
        "Watcher summary: "
        f"changed={summary['changed']} "
        f"ingest_attempted={summary['ingest_attempted']} ingested={summary['ingested']} "
        f"panel_candidates={summary['panel_candidates']} panel_runs={summary['panel_runs']} "
        f"panel_promotions={summary['panel_promotions']} "
        f"skipped_policy={summary['panel_skipped_policy']} skipped_limit={summary['panel_skipped_limit']} "
        f"errors={summary['errors']} dry_run={summary['dry_run']} limit_exceeded={summary['limit_exceeded']}"
    )


@click.command(
    name="vault-watcher-run",
    help="Single-shot vault watcher: detects changed notes via snapshot, ingests them, and optionally runs PanelAgent runtime.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Vault root (defaults to VAULT_ROOT or DEFAULT_VAULT_ROOT).",
)
@click.option(
    "--snapshot-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Snapshot file path (stores path→mtime). Defaults to <vault>/.agentic-pkm/vault_watcher_state.json.",
)
@click.option("--skip-panel", is_flag=True, help="Skip running PanelAgent runtime.")
@click.option(
    "--emit-only",
    is_flag=True,
    help="Only emit panel.intent.created for panels (skip runtime) when panel runs are enabled.",
)
@click.option("--dry-run", is_flag=True, help="Preview changed notes without running ingest or panel runtime.")
@click.option(
    "--max-notes",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of changed notes to process; if exceeded, watcher aborts unless --force is set.",
)
@click.option("--force", is_flag=True, help="Override max-notes safety guard.")
def vault_watcher_run(
    vault_root: Path | None,
    snapshot_path: Path | None,
    skip_panel: bool,
    emit_only: bool,
    dry_run: bool,
    max_notes: int,
    force: bool,
) -> None:
    from app.cli import _resolve_vault_root_path

    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")

    summary, messages = run_watcher_tick(
        vault_root=resolved,
        snapshot_path=snapshot_path,
        skip_panel=skip_panel,
        emit_only=emit_only,
        dry_run=dry_run,
        max_notes=max_notes,
        force=force,
    )
    for msg in messages:
        click.echo(msg)

    if summary.get("limit_exceeded"):
        _echo_summary(summary)
        raise SystemExit(1)

    _echo_summary(summary)
    if summary.get("errors", 0) > 0:
        raise SystemExit(1)


@click.command(
    name="vault-watcher-daemon",
    help="Continuous vault watcher: polls for changed notes and runs ingest/panel; designed for Docker/daemon use.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Vault root (defaults to VAULT_ROOT or DEFAULT_VAULT_ROOT).",
)
@click.option(
    "--snapshot-path",
    type=click.Path(path_type=Path),
    default=Path("/state/vault_watcher_state.json"),
    help="Snapshot file path (stores path→mtime). Defaults to /state/vault_watcher_state.json in Docker.",
)
@click.option("--skip-panel", is_flag=True, help="Skip running PanelAgent runtime.")
@click.option(
    "--emit-only",
    is_flag=True,
    help="Only emit panel.intent.created for panels (skip runtime) when panel runs are enabled.",
)
@click.option(
    "--poll-seconds",
    type=int,
    default=30,
    show_default=True,
    help="Delay between polls when no changes are detected.",
)
@click.option(
    "--cooldown-seconds",
    type=int,
    default=10,
    show_default=True,
    help="Delay after a run with changes to avoid rapid reprocessing on mounted volumes.",
)
@click.option(
    "--max-notes",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of changed notes to process; if exceeded, watcher aborts unless --force is set.",
)
@click.option("--force", is_flag=True, help="Override max-notes safety guard.")
def vault_watcher_daemon(
    vault_root: Path | None,
    snapshot_path: Path | None,
    skip_panel: bool,
    emit_only: bool,
    poll_seconds: int,
    cooldown_seconds: int,
    max_notes: int,
    force: bool,
) -> None:
    from app.cli import _resolve_vault_root_path

    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")

    def _log(summary: dict, messages: list[str]) -> None:
        for msg in messages:
            click.echo(msg)
        _echo_summary(summary)

    run_watcher_daemon(
        vault_root=resolved,
        snapshot_path=snapshot_path,
        skip_panel=skip_panel,
        emit_only=emit_only,
        dry_run=False,
        max_notes=max_notes,
        force=force,
        poll_seconds=poll_seconds,
        cooldown_seconds=cooldown_seconds,
        on_tick=_log,
    )


__all__ = ["vault_watcher_run"]
