from __future__ import annotations

import json

import click

from app.cli.index_rebuild import index
from app.index.doctor import diagnose_index


@index.command("doctor", help="Check embedding/index identity drift and health.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable diagnostics.")
@click.option("--strict", is_flag=True, default=False, help="Exit with code 2 if problems are detected.")
@click.option("--warn/--no-warn", default=True, show_default=True, help="Always exit 0 but still print warnings.")
def doctor(as_json: bool, strict: bool, warn: bool) -> None:
    if strict:
        warn = False
    result = diagnose_index()
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        expected = result.get("expected_identity") or {}
        stored = result.get("stored_identity") or {}
        click.echo(f"VectorIndex backend: {result['backend']}")
        click.echo(
            "Expected identity: provider={provider} model={model} dim={dim} normalize={normalize}".format(
                provider=expected.get("provider"),
                model=expected.get("model"),
                dim=expected.get("dim"),
                normalize=expected.get("normalize"),
            )
        )
        if stored:
            click.echo(
                "Stored identity: provider={provider} model={model} dim={dim} normalize={normalize}".format(
                    provider=stored.get("provider"),
                    model=stored.get("model"),
                    dim=stored.get("dim"),
                    normalize=stored.get("normalize"),
                )
            )
        else:
            click.echo("Stored identity: (missing)")
        if result.get("issues"):
            click.echo("Issues:")
            for entry in result["issues"]:
                click.echo(f"  - {entry}")
        if result.get("warnings"):
            click.echo("Warnings:")
            for entry in result["warnings"]:
                click.echo(f"  - {entry}")
    exit_code = 0
    if not warn and result.get("issues"):
        exit_code = 2
    if strict and result.get("issues"):
        exit_code = 2
    raise SystemExit(exit_code)


