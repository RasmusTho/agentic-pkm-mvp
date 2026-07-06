"""CLI entrypoint for the Heimdal capture-adapter runtime driver (#3094)."""

from __future__ import annotations

import json

import click

from app.heimdal.capture_runtime import (
    CaptureRuntimeConfig,
    CaptureRuntimeConfigError,
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
    try:
        cfg = CaptureRuntimeConfig.from_env()
    except CaptureRuntimeConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        "heimdal capture-watch: "
        f"watch_dir={cfg.watch_dir} interval_seconds={cfg.interval_seconds}"
    )

    if once:
        result = run_capture_tick(cfg)
        summary = {
            "admitted": len(result.admitted) if result is not None else 0,
            "refused": len(result.refused) if result is not None else 0,
        }
        click.echo(json.dumps(summary, ensure_ascii=False))
        return

    try:
        ticks = run_forever(cfg, max_ticks=max_ticks)
    except KeyboardInterrupt:
        click.echo("heimdal capture-watch: stopped via keyboard interrupt")
        return
    click.echo(f"heimdal capture-watch: stopped after {ticks} ticks")


__all__ = ["heimdal_group"]
