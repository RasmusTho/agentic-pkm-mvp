from __future__ import annotations

from pathlib import Path

from tests.helpers.subprocess_pythonpath import isolated_app_pythonpath


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_isolated_pythonpath_preserves_default_packages(tmp_path: Path) -> None:
    private_dir = tmp_path / "pythonpath"

    result = isolated_app_pythonpath(private_dir, REPO_ROOT)

    assert result == str(private_dir)
    assert (private_dir / "app").resolve() == REPO_ROOT / "app"
    assert (private_dir / "scripts").resolve() == REPO_ROOT / "scripts"


def test_isolated_pythonpath_exposes_existing_optional_package(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    optional_package = repo_root / "neutral_package"
    optional_package.mkdir(parents=True)
    private_dir = tmp_path / "pythonpath"

    isolated_app_pythonpath(
        private_dir,
        repo_root,
        optional_packages=("neutral_package",),
    )

    assert (private_dir / "neutral_package").resolve() == optional_package


def test_isolated_pythonpath_skips_missing_optional_package(tmp_path: Path) -> None:
    private_dir = tmp_path / "pythonpath"

    isolated_app_pythonpath(
        private_dir,
        tmp_path / "repo",
        optional_packages=("missing_package",),
    )

    assert not (private_dir / "missing_package").exists()
    assert not (private_dir / "missing_package").is_symlink()


def test_isolated_pythonpath_is_idempotent_for_optional_packages(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "app").mkdir(parents=True)
    (repo_root / "scripts").mkdir()
    optional_package = repo_root / "neutral_package"
    optional_package.mkdir()
    private_dir = tmp_path / "pythonpath"

    first = isolated_app_pythonpath(
        private_dir,
        repo_root,
        optional_packages=("neutral_package",),
    )
    second = isolated_app_pythonpath(
        private_dir,
        repo_root,
        optional_packages=("neutral_package",),
    )

    assert first == second == str(private_dir)
    assert (private_dir / "neutral_package").resolve() == optional_package
