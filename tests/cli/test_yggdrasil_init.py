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

    for name in ["Hugin", "Munin", "Ratatosk", "Brokkr", "Tyr", "Heimdall"]:
        assert (tmp_path / name).is_dir()
