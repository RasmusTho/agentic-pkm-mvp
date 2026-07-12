"""``python -m app.cli episodes rebuild-projection`` (#3532, ERE-02 follow-up).

Both docs describing this substrate (``docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md``
:: Concretely) already showed this command's invocation; the CLI itself only ever defined
``episodes tick``. This wires the documented verb to the existing
``app.jobs.episodes_projection.rebuild_episodes_projection`` (ERE-02) -- the full ground-truth
reconciliation path (TRUNCATE+replay), never a scheduled production step.

- AC3: the command exists and calls ``rebuild_episodes_projection``. Verify:
  ``test_rebuild_projection_command_invokes_rebuild``.

No Postgres needed: ``rebuild_episodes_projection`` is monkeypatched at the CLI module boundary,
mirroring how ``tests/cli/test_vault_watcher_cli.py`` and siblings test click commands without a
live backend.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.cli import episodes as episodes_cli_module
from app.jobs.episodes_projection import RebuildSummary


def test_rebuild_projection_command_invokes_rebuild(tmp_path: Path, monkeypatch) -> None:
    """AC3: the command exists, resolves ``--vault-root`` the same way as ``tick``, and calls
    ``app.jobs.episodes_projection.rebuild_episodes_projection`` -- the real production
    reconciliation path, not a reimplementation."""
    vault = tmp_path / "vault"
    calls: list[Path] = []

    def _fake_rebuild(vault_root: Path) -> RebuildSummary:
        calls.append(vault_root)
        return RebuildSummary(total_notes=2, inserted=2, skipped_invalid=[])

    monkeypatch.setattr(episodes_cli_module, "rebuild_episodes_projection", _fake_rebuild)

    runner = CliRunner()
    result = runner.invoke(cli, ["episodes", "rebuild-projection", "--vault-root", str(vault)])

    assert result.exit_code == 0, result.output
    assert calls == [vault]
    assert "total_notes=2" in result.output
    assert "inserted=2" in result.output
    assert "skipped_invalid=0" in result.output


def test_rebuild_projection_command_json_output(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    monkeypatch.setattr(
        episodes_cli_module,
        "rebuild_episodes_projection",
        lambda vault_root: RebuildSummary(total_notes=1, inserted=1, skipped_invalid=[]),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["episodes", "rebuild-projection", "--vault-root", str(vault), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"total_notes": 1, "inserted": 1, "skipped_invalid": []}


def test_rebuild_projection_command_defaults_vault_root_like_tick(monkeypatch) -> None:
    """Consistent with `tick`'s vault-root resolution (`_VAULT_ROOT_ENV_CANDIDATES`): with no
    `--vault-root` flag, the command falls back to the same environment-variable chain."""
    monkeypatch.delenv("EPISODES_VAULT_ROOT", raising=False)
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.setenv("VAULT_ROOT", "/tmp/some-vault-root-for-test")

    calls: list[Path] = []

    def _fake_rebuild(vault_root: Path) -> RebuildSummary:
        calls.append(vault_root)
        return RebuildSummary(total_notes=0, inserted=0, skipped_invalid=[])

    monkeypatch.setattr(episodes_cli_module, "rebuild_episodes_projection", _fake_rebuild)

    runner = CliRunner()
    result = runner.invoke(cli, ["episodes", "rebuild-projection"])

    assert result.exit_code == 0, result.output
    assert calls == [Path("/tmp/some-vault-root-for-test")]
