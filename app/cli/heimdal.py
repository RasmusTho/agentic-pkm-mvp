"""CLI entrypoint for the Heimdal capture-adapter runtime driver (#3094)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from app.heimdal.archive_capacity import build_archive_capacity_report
from app.heimdal.capture_runtime import (
    CaptureRuntimeConfig,
    CaptureRuntimeConfigError,
    resolve_config_for_supervised_run,
    run_capture_tick,
    run_forever,
)


@click.group(name="heimdal", help="Heimdal capture-adapter runtime controls.")
def heimdal_group() -> None:
    ...


@heimdal_group.command(
    name="capture-watch",
    help=(
        "Drive the Heimdal voice-memo capture adapter against "
        "HEIMDAL_CAPTURE_WATCH_DIR on an interval (HEIMDAL_CAPTURE_INTERVAL_SECONDS, "
        "default 30s). Use --once for a single tick instead of looping forever."
    ),
)
@click.option("--once", is_flag=True, help="Run a single tick and exit instead of looping forever.")
@click.option(
    "--max-ticks",
    type=int,
    default=None,
    help="Optional safety: stop after N ticks (ignored with --once; defaults to run forever).",
)
def capture_watch(once: bool, max_ticks: int | None) -> None:
    if once:
        # A manually-invoked diagnostic command: fail loud and exit
        # immediately on a config error, matching Heimdal's posture
        # everywhere else.
        try:
            cfg = CaptureRuntimeConfig.from_env()
        except CaptureRuntimeConfigError as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(
            "heimdal capture-watch: "
            f"watch_dir={cfg.watch_dir} interval_seconds={cfg.interval_seconds}"
        )
        result = run_capture_tick(cfg)
        if result is None:
            # `None` means the tick itself failed (e.g. the watch dir became
            # unreadable mid-scan) -- distinct from a real, successful empty
            # tick. Reporting {"admitted": 0, "refused": 0} here would be a
            # false-success signal for a manually-invoked diagnostic command;
            # fail loud instead, matching Heimdal's posture everywhere else.
            raise click.ClickException(
                "Tick failed -- see the logged error for details. "
                "The watch directory may be unreadable or unavailable."
            )
        summary = {"admitted": len(result.admitted), "refused": len(result.refused)}
        click.echo(json.dumps(summary, ensure_ascii=False))
        return

    # Supervised path (the compose service's default): see
    # `resolve_config_for_supervised_run`'s docstring for why this must not
    # exit immediately on a startup config error (#4362).
    cfg = resolve_config_for_supervised_run()

    click.echo(
        "heimdal capture-watch: "
        f"watch_dir={cfg.watch_dir} interval_seconds={cfg.interval_seconds}"
    )

    try:
        ticks = run_forever(cfg, max_ticks=max_ticks)
    except KeyboardInterrupt:
        click.echo("heimdal capture-watch: stopped via keyboard interrupt")
        return
    click.echo(f"heimdal capture-watch: stopped after {ticks} ticks")


@heimdal_group.command(
    name="capacity",
    help="Emit the aggregate-only Heimdal raw-evidence capacity receipt (HAR-01).",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    help="Vault containing _heimdal/settings.md with retention_window_days.",
)
def capacity(vault_root: Path) -> None:
    """Expose the redacted capacity health/receipt surface to operators."""
    try:
        receipt = build_archive_capacity_report(vault_root).as_dict()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(receipt, ensure_ascii=False))


__all__ = ["heimdal_group"]
