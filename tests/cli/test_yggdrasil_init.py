from click.testing import CliRunner

from app.cli import cli


def test_yggdrasil_init_scaffolds_directories(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["yggdrasil-init", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output

    mimer_root = tmp_path / "Mimer"
    assert (mimer_root / "Workspace").is_dir()
    settings_dir = mimer_root / "@Settings"
    assert settings_dir.is_dir()
    assert any(settings_dir.iterdir())
    assert (settings_dir / "system-settings.yaml").exists()
    assert (mimer_root / "⚙️ System").is_dir()
    assert (mimer_root / "📥 Inbox").is_dir()
    assert (mimer_root / "🛠️ Workbench").is_dir()
    assert (mimer_root / "⚙️ System" / "vault.layout.md").exists()

    for name in ["Hugin", "Munin", "Ratatosk", "Brokkr", "Tyr", "Heimdall"]:
        assert (tmp_path / name).is_dir()


def test_yggdrasil_init_uses_scaffolder(monkeypatch, tmp_path) -> None:
    called: list[str] = []

    class FakeScaffolder:
        def __init__(self, root) -> None:  # type: ignore[no-untyped-def]
            called.append(str(root))

        def scaffold(self):  # type: ignore[no-untyped-def]
            return {"root": [tmp_path], "created": [], "existed": []}

    monkeypatch.setattr("app.cli.YggdrasilScaffolder", FakeScaffolder)
    runner = CliRunner()
    result = runner.invoke(cli, ["yggdrasil-init", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert called
