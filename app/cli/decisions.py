"""`decisions` CLI group — decision-receipt log maintenance (feat #2969, issue #2973).

Wires the previously CLI-less projection maintenance functions
(``app/jobs/decisions_projection.py``, ``app/jobs/decisions_export.py``) so an
operator has one coherent, scriptable entry point instead of ad-hoc Python
one-liners. Per docs/audits/MIMER_WHOLE_SYSTEM_INTEGRATION_2026-07-05.md finding
G8, ``rebuild_decisions_projection``/``doctor_decisions_projection`` had zero
production call sites before this.

The operator-safe order for the slice-4 prod backfill (issue #2973) is:

    python -m app.cli decisions export           # 1. historical DB-only rows -> log
    python -m app.cli decisions doctor            # 2. verify DB == log (row-count parity)
    python -m app.cli decisions rebuild --yes      # 3. only after (1)+(2) confirm parity

Running `rebuild` before `export` on an environment with historical DB-only rows
replaces the compatibility binding's `decisions` rows and replays only what the log already has,
losing anything not yet exported (issue #2973, 2026-07-05 comment). `rebuild`
therefore requires an explicit `--yes` confirmation flag; there is no default-on
path to the truncating operation from this CLI.
"""
from __future__ import annotations

import json

import click

from app.jobs.decisions_export import DecisionExportError, export_decisions_to_receipt_log
from app.jobs.decisions_projection import (
    doctor_decisions_projection,
    rebuild_decisions_projection,
)


@click.group(name="decisions", help="Decision-receipt log maintenance commands (feat #2969).")
def decisions() -> None:
    """Decision-receipt log maintenance command group."""


@decisions.command(
    "export",
    help="One-time export of DB-only `decisions` rows into the canonical receipt log (idempotent, read-only over the DB).",
)
@click.option("--vault-root", type=click.Path(exists=False), default=None, help="Override vault root (else VAULT_ROOT).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON summary.")
def decisions_export(vault_root: str | None, as_json: bool) -> None:
    from pathlib import Path

    root = Path(vault_root) if vault_root else None
    try:
        summary = export_decisions_to_receipt_log(root)
    except DecisionExportError as exc:
        # Always fail loud (exit 2): a row the export cannot faithfully place
        # into the log is one `decisions rebuild` would silently lose.
        payload = {"ok": False, "error": str(exc)}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Export failed: {exc}")
        raise SystemExit(2) from exc

    payload = {
        "ok": True,
        "total_db_rows": summary.total_db_rows,
        "already_in_log": summary.already_in_log,
        "exported": summary.exported,
        "exported_rows": summary.exported_rows,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"total_db_rows={summary.total_db_rows} "
            f"already_in_log={summary.already_in_log} exported={summary.exported}"
        )
        for row in summary.exported_rows:
            click.echo(f"  exported: object_id={row['object_id']} key={row['key']} created_at={row['created_at']}")


@decisions.command("doctor", help="Assert the `decisions` DB projection matches the receipt log row-for-row.")
@click.option("--vault-root", type=click.Path(exists=False), default=None, help="Override vault root (else VAULT_ROOT).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON report.")
@click.option("--strict/--no-strict", default=True, show_default=True, help="Exit code 2 when DB and log disagree.")
def decisions_doctor(vault_root: str | None, as_json: bool, strict: bool) -> None:
    from pathlib import Path

    root = Path(vault_root) if vault_root else None
    report = doctor_decisions_projection(root)
    payload = {
        "ok": report.ok,
        "db_rows": report.db_rows,
        "log_rows": report.log_rows,
        "missing_in_db": report.missing_in_db,
        "extra_in_db": report.extra_in_db,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"ok={report.ok} db_rows={report.db_rows} log_rows={report.log_rows}")
        if report.missing_in_db:
            click.echo(f"  missing_in_db (in log, not yet in DB): {len(report.missing_in_db)}")
        if report.extra_in_db:
            click.echo(
                f"  extra_in_db (in DB, NOT YET EXPORTED to log): {len(report.extra_in_db)} "
                "-- run `decisions export` before any `decisions rebuild`"
            )
    if strict and not report.ok:
        raise SystemExit(2)


@decisions.command(
    "rebuild",
    help="Replace and replay the compatibility binding's `decisions` DB projection from the receipt log. Destructive — requires --yes.",
)
@click.option("--vault-root", type=click.Path(exists=False), default=None, help="Override vault root (else VAULT_ROOT).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON summary.")
@click.option(
    "--yes",
    "confirmed",
    is_flag=True,
    default=False,
    help="Required. Confirms you have run `decisions export` and `decisions doctor` (ok=true) first.",
)
def decisions_rebuild(vault_root: str | None, as_json: bool, confirmed: bool) -> None:
    from pathlib import Path

    if not confirmed:
        raise click.ClickException(
            "decisions rebuild replaces the compatibility binding's rows and replays the receipt log. "
            "Any DB row not yet represented in the log is lost. Run `decisions export` then "
            "`decisions doctor` (confirm ok=true) first, then re-run with --yes."
        )
    root = Path(vault_root) if vault_root else None
    summary = rebuild_decisions_projection(root)
    payload = {
        "total_receipts": summary.total_receipts,
        "inserted": summary.inserted,
        "relinked": summary.relinked,
        "skipped_orphans": summary.skipped_orphans,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"total_receipts={summary.total_receipts} inserted={summary.inserted} "
            f"relinked={summary.relinked} skipped_orphans={len(summary.skipped_orphans)}"
        )
