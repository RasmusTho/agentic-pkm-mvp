from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from app.briefing.trigger import BriefingTriggerResult
from app.cli.briefing import briefing_group
from app.vault.manager import VaultContext


def _selected(vault: Path) -> VaultContext:
    vault.mkdir()
    return VaultContext(status="selected", active_vault_path=str(vault))


def test_tick_loads_remembered_vault_in_fresh_process(tmp_path: Path) -> None:
    context = _selected(tmp_path / "vault")
    manager = SimpleNamespace(
        context=VaultContext(status="none"),
        load_last_active=lambda: context,
    )
    result = BriefingTriggerResult(False, "outside_scheduled_window", date(2026, 7, 11))
    with (
        patch("app.cli.briefing.get_vault_manager", return_value=manager),
        patch("app.cli.briefing.scheduled_briefing_tick", return_value=result) as trigger,
    ):
        invocation = CliRunner().invoke(briefing_group, ["tick", "--json"])
    assert invocation.exit_code == 0, invocation.output
    trigger.assert_called_once()
    assert trigger.call_args.kwargs["vault_context"] == context


def test_regenerate_accepts_explicit_vault_root(tmp_path: Path) -> None:
    context = _selected(tmp_path / "vault")
    manager = SimpleNamespace(validate_vault=lambda root: context)
    result = BriefingTriggerResult(True, "manual_regenerate", date(2026, 7, 11))
    with (
        patch("app.cli.briefing.get_vault_manager", return_value=manager),
        patch("app.cli.briefing.regenerate_briefing", return_value=result) as trigger,
    ):
        invocation = CliRunner().invoke(
            briefing_group,
            [
                "regenerate",
                "--vault-root",
                str(tmp_path / "vault"),
                "--date",
                "2026-07-11",
                "--json",
            ],
        )
    assert invocation.exit_code == 0, invocation.output
    trigger.assert_called_once_with(vault_context=context, for_date=date(2026, 7, 11))
