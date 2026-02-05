from __future__ import annotations

import json
import os
from pathlib import Path

import click

from app.runtime.runtime_loop import OutboxPathError, resolve_outbox_path
from app.settings.validate import validate_settings
from app.watcher.config import WatcherConfig
from app.watcher.events import emit_watcher_run_event
from app.watcher.registry import load_registry_config, run_registry_forever
from app.watcher.vault_watcher import run_watcher_daemon, run_watcher_tick
from app.watcher.watcher import run_once as watcher_run_once


def _echo_summary(summary: dict) -> None:
    parts = [
        f"changed={summary['changed']}",
        f"ingest_attempted={summary['ingest_attempted']}",
        f"ingested={summary['ingested']}",
        f"panel_candidates={summary['panel_candidates']}",
        f"panel_runs={summary['panel_runs']}",
        f"panel_promotions={summary['panel_promotions']}",
        f"applied_actions={summary.get('applied_actions', 0)}",
        f"skipped_policy={summary['panel_skipped_policy']}",
        f"skipped_limit={summary['panel_skipped_limit']}",
        f"skipped_auto_exec={summary.get('panel_skipped_auto_exec', 0)}",
        f"skipped_dedup={summary.get('skipped_dedup', 0)}",
        f"skipped_idempotent={summary.get('skipped_idempotent', 0)}",
        f"skipped_writes_blocked={summary.get('skipped_writes_blocked', 0)}",
        f"errors={summary['errors']}",
        f"dry_run={summary['dry_run']}",
        f"limit_exceeded={summary['limit_exceeded']}",
    ]
    click.echo("Watcher summary: " + " ".join(parts))

def _validate_settings_or_exit() -> None:
    issues = validate_settings()
    if issues:
        raise click.ClickException(f"settings validate failed: {len(issues)} issue(s)")

@click.group(name="watcher", help="Live watcher controls with scope, kill switch, and rate limits.")
def watcher_group() -> None:
    ...

@watcher_group.command(
    name="once",
    help="Run a single watcher scan respecting scope, debounce, and rate limits.",
)
def watcher_once() -> None:
    _validate_settings_or_exit()
    try:
        cfg = WatcherConfig.from_env()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if not cfg.enable:
        raise click.ClickException("WATCHER_ENABLE=1 required; export env and try again.")

    scope_env = (os.getenv("WATCHER_SCOPE_GLOB") or "").strip()
    provenance = "env:WATCHER_SCOPE_GLOB" if scope_env else "default:vaultwide"
    click.echo(
        "watcher scope resolved "
        f"vault_path={cfg.vault_path} scope_glob={cfg.scope_glob} provenance={provenance} inbox_source="
    )

    summary = watcher_run_once(cfg)
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("kill_switch") or summary.get("backoff_active") or summary.get("errors"):
        raise SystemExit(1)

@watcher_group.command(
    name="run",
    help="Run the watcher registry loop continuously with operator summaries.",
)
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=Path("configs/watchers.yaml"),
    show_default=True,
    help="Watcher registry config file.",
)
@click.option(
    "--max-ticks",
    type=int,
    default=None,
    help="Optional safety: stop after N ticks (defaults to run forever).",
)
def watcher_run(config: Path, max_ticks: int | None) -> None:
    _validate_settings_or_exit()
    try:
        cfg = load_registry_config(config)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not cfg.enable:
        raise click.ClickException("WATCHER_ENABLE=1 required; export env and try again.")

    scope_env = (os.getenv("WATCHER_SCOPE_GLOB") or "").strip()
    provenance = "env:WATCHER_SCOPE_GLOB" if scope_env else "default:vaultwide"
    click.echo(
        "watcher scope resolved "
        f"vault_path={cfg.vault_path} scope_glob={cfg.scope_glob} provenance={provenance} inbox_source="
    )

    watcher_names = ", ".join(spec.name for spec in cfg.specs)
    click.echo(
        "watcher registry: "
        f"config={cfg.config_path} vault={cfg.vault_path} outbox={cfg.outbox_path} "
        f"watchers=[{watcher_names}] stop_file={cfg.stop_file} tick_sleep={cfg.tick_sleep_seconds}"
    )

    try:
        run_registry_forever(cfg.config_path, max_ticks=max_ticks)
    except KeyboardInterrupt:
        click.echo("watcher: stopped via keyboard interrupt")

@click.command(
    name="vault-watcher-run",
    help=(
        "Single-shot vault watcher: detects changed notes via snapshot, ingests them, "
        "and optionally runs PanelAgent runtime."
    ),
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
    help=(
        "Snapshot file path (stores path→mtime). "
        "Defaults to <vault>/.agentic-pkm/vault_watcher_state.json."
    ),
)
@click.option("--skip-panel", is_flag=True, help="Skip running PanelAgent runtime.")
@click.option(
    "--emit-only",
    is_flag=True,
    help="Only emit panel.intent.created for panels (skip runtime) when panel runs are enabled.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changed notes without running ingest or panel runtime.",
)
@click.option(
    "--max-notes",
    type=int,
    default=50,
    show_default=True,
    help=(
        "Maximum number of changed notes to process; if exceeded, "
        "watcher aborts unless --force is set."
    ),
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
    try:
        outbox_path = resolve_outbox_path(None)
    except OutboxPathError as exc:
        raise click.ClickException(str(exc)) from exc

    summary, messages = run_watcher_tick(
        vault_root=resolved,
        snapshot_path=snapshot_path,
        skip_panel=skip_panel,
        emit_only=emit_only,
        dry_run=dry_run,
        max_notes=max_notes,
        force=force,
        outbox_path=outbox_path,
    )
    for msg in messages:
        click.echo(msg)

    if not summary.get("limit_exceeded") and not dry_run:
        emit_watcher_run_event(
            summary,
            vault_root=resolved,
            snapshot_path=summary.get("snapshot_path") or snapshot_path,
            outbox_path=outbox_path,
            trigger="vault_watcher_run",
        )

    if summary.get("limit_exceeded"):
        _echo_summary(summary)
        raise SystemExit(1)

    _echo_summary(summary)
    if summary.get("errors", 0) > 0:
        raise SystemExit(1)

@click.command(
    name="vault-watcher-daemon",
    help=(
        "Continuous vault watcher: polls for changed notes and runs ingest/panel; "
        "designed for Docker/daemon use."
    ),
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
    help=(
        "Snapshot file path (stores path→mtime). "
        "Defaults to /state/vault_watcher_state.json in Docker."
    ),
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
    help=(
        "Maximum number of changed notes to process; if exceeded, "
        "watcher aborts unless --force is set."
    ),
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
    try:
        outbox_path = resolve_outbox_path(None)
    except OutboxPathError as exc:
        raise click.ClickException(str(exc)) from exc

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
        outbox_path=outbox_path,
    )

__all__ = ["vault_watcher_run", "vault_watcher_daemon", "watcher_group"]
