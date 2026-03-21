from __future__ import annotations

from scripts import bump_version


def test_bump_version_reads_live_settings_module() -> None:
    assert bump_version.SETTINGS_PATH.exists()
    assert bump_version.SETTINGS_PATH.name == "__init__.py"
    assert bump_version.read_current_version()
