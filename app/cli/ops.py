"""`ops` CLI group — test/promotion harness preflight + bootstrap (issue #1997).

`python -m app.cli ops channel-preflight` fail-loud validates the live env is
channel-correct. `python -m app.cli ops bootstrap-test-channel` is the single
idempotent bring-up of a correct test channel (vault init + canonical env +
preflight). Both are harness-only; neither changes product runtime behaviour.
"""

from __future__ import annotations

import json

import click

from app.ops.channel_preflight import channel_env_preflight, raise_if_blocking
from app.ops.test_channel_bootstrap import bootstrap_test_channel


@click.group(name="ops", help="Test/promotion harness preflight and bootstrap.")
def ops() -> None:
    """Operational harness commands."""


@ops.command("channel-preflight", help="Fail-loud check that the env is channel-correct.")
@click.option("--channel", default=None, help="Intended channel (default: derived from PKM_ENVIRONMENT).")
@click.option(
    "--context",
    type=click.Choice(["host", "container"]),
    default="host",
    show_default=True,
    help="Where the entrypoint runs (host DSN must be reachable, e.g. 127.0.0.1:15434).",
)
def ops_channel_preflight(channel: str | None, context: str) -> None:
    """Validate the current process env and refuse on mismatch."""
    result = channel_env_preflight(channel=channel, context=context)
    click.echo(result.format_report())
    if result.blocking:
        raise click.ClickException(
            "channel-env preflight failed: " + ", ".join(result.offending_vars)
        )


@ops.command(
    "bootstrap-test-channel",
    help="Idempotently bring up the test-channel config (vault init + canonical env + preflight).",
)
@click.option("--vault-root", "vault_root", default=None, help="The test vault root (else VAULT_ROOT_TEST/TEST_VAULT_ROOT, then repo-local vault-test).")
@click.option("--print-env", "print_env", is_flag=True, help="Print the canonical env as KEY=VALUE lines (for `eval`/`source`).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable JSON receipt.")
def ops_bootstrap_test_channel(vault_root: str | None, print_env: bool, as_json: bool) -> None:
    """Bring up a correct test channel (config layer) and self-check it."""
    result = bootstrap_test_channel(vault_root=vault_root)

    if print_env:
        for key, value in result.env.items():
            click.echo(f"{key}={value}")
        # `--print-env` is meant to be eval'd; still fail loud on a bad channel.
        raise_if_blocking(result.preflight)  # type: ignore[arg-type]
        return

    if as_json:
        click.echo(
            json.dumps(
                {
                    "ok": result.ok,
                    "vault_root": result.vault_root,
                    "vault_status": result.vault_status,
                    "created_files": list(result.created_files),
                    "skipped_files": list(result.skipped_files),
                    "preflight_ok": result.preflight.ok if result.preflight else None,
                    "offending_vars": list(result.preflight.offending_vars) if result.preflight else [],
                    "env": result.env,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        click.echo(f"vault: {result.vault_root}")
        click.echo(f"vault status: {result.vault_status}")
        for created in result.created_files:
            click.echo(f"created  {created}")
        for existing in result.skipped_files:
            click.echo(f"exists   {existing}")
        click.echo(result.preflight.format_report() if result.preflight else "(no preflight)")

    if not result.ok:
        raise click.ClickException("test-channel bootstrap is not channel-correct")


__all__ = ["ops"]
