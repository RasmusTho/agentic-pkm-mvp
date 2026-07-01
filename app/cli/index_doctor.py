from __future__ import annotations

import json

import click

from app.cli.index_rebuild import index
from app.index.doctor import diagnose_index


@index.command("doctor", help="Check embedding/index identity drift and health.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable diagnostics.")
@click.option("--strict", is_flag=True, default=False, help="Exit with code 2 if problems are detected.")
@click.option("--warn/--no-warn", default=True, show_default=True, help="Always exit 0 but still print warnings.")
@click.option(
    "--coverage",
    is_flag=True,
    default=False,
    help=(
        "Also scan the bound vault for markdown notes with no store_objects row "
        "(#2324 coverage-gap detection). Read-only; opt-in because it walks the "
        "vault filesystem. Distinct from 'index reconcile' (#2297), which converges "
        "identity drift, not coverage gaps."
    ),
)
def doctor(as_json: bool, strict: bool, warn: bool, coverage: bool) -> None:
    if strict:
        warn = False
    result = diagnose_index(include_vault_coverage=coverage)
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
        mixed = result.get("mixed_identities") or []
        if mixed:
            click.echo("Mixed embedding identities (provider, model, dim, normalize):")
            for entry in mixed:
                click.echo(f"  - {tuple(entry)}")
            click.echo("Recommended repair: python -m app.cli index reconcile")
        completeness = result.get("metadata_completeness") or {}
        if completeness.get("missing_count"):
            click.echo(
                f"Metadata/provenance completeness gaps: {completeness['missing_count']} "
                f"of {completeness.get('checked', 0)} rows missing language/provenance/"
                "embedding-identity metadata."
            )
            samples = completeness.get("missing_sample_ids") or []
            if samples:
                click.echo(f"  Sample object ids: {', '.join(samples)}")
        vault_coverage = result.get("vault_coverage") or {}
        if vault_coverage.get("error"):
            click.echo(f"Vault coverage scan skipped: {vault_coverage['error']}")
        elif vault_coverage.get("missing_count"):
            click.echo(
                f"Coverage gap: {vault_coverage['missing_count']} of "
                f"{vault_coverage.get('checked', 0)} vault notes have no store_objects row."
            )
            samples = vault_coverage.get("missing_sample_paths") or []
            if samples:
                click.echo(f"  Sample paths: {', '.join(samples)}")
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


