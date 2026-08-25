"""Operator entrypoint for the derived decision-calibration profile."""
from __future__ import annotations

import json
from pathlib import Path

import click

from app.jobs.calibration_projection import (
    CalibrationProjectionHazardError,
    rebuild_calibration_projection,
)


@click.group(name="calibration", help="Decision-calibration projection maintenance.")
def calibration() -> None:
    """Commands for derived decision-calibration views."""


@calibration.group(name="profile", help="Generated calibration-profile maintenance.")
def profile() -> None:
    """The profile is generated from vault-canonical outcome receipts."""


@profile.command("rebuild", help="Hazard-safe rebuild from the canonical outcome JSONL log.")
@click.option("--vault-root", type=click.Path(path_type=Path, exists=False), default=None)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON.")
def rebuild(vault_root: Path | None, as_json: bool) -> None:
    """Rebuild only when no database-only outcome receipt would be lost."""
    try:
        summary = rebuild_calibration_projection(vault_root)
    except CalibrationProjectionHazardError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "total_receipts": summary.total_receipts,
        "inserted": summary.inserted,
        "markdown_written": summary.markdown_written,
        "rollup": summary.rollup,
        "confidence_rollup": summary.confidence_rollup,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"total_receipts={summary.total_receipts} inserted={summary.inserted} "
            f"markdown_written={summary.markdown_written}"
        )
