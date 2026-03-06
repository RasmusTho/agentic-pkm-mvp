from __future__ import annotations

from app.knowledge.health import obsidian_dependency_status


def test_obsidian_dependency_status_fails_when_cli_missing() -> None:
    status = obsidian_dependency_status(which_fn=lambda _: None)
    assert status.ok is False
    assert status.cli_present is False


def test_obsidian_dependency_status_checks_installer_version_floor() -> None:
    status = obsidian_dependency_status(
        which_fn=lambda _: "/usr/local/bin/obsidian",
        get_installer_version=lambda: "1.12.3",
    )
    assert status.cli_present is True
    assert status.installer_ok is False
    assert status.ok is False


def test_obsidian_dependency_status_accepts_equal_or_higher_installer_version() -> None:
    status = obsidian_dependency_status(
        which_fn=lambda _: "/usr/local/bin/obsidian",
        get_installer_version=lambda: "1.12.4",
    )
    assert status.ok is True
    assert status.installer_ok is True


def test_obsidian_dependency_status_fails_on_unparseable_installer() -> None:
    status = obsidian_dependency_status(
        which_fn=lambda _: "/usr/local/bin/obsidian",
        get_installer_version=lambda: "unknown",
    )
    assert status.ok is False
