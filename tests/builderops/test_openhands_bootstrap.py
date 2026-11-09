"""Bootstrap read grants cannot encompass retained state or source repositories."""

import pytest

from scripts.openhands_build_func_timeout import validate_read_roots


def test_bootstrap_read_roots_refuse_home_repo_and_install(tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = tmp_path / "install"
    for path in (home, source, install):
        path.mkdir()
    safe = home / "python/lib"
    safe.mkdir(parents=True)
    validate_read_roots([str(safe)], install, home, source)
    nested_state = install / "runs"
    nested_state.mkdir()
    for path in (tmp_path, home, source, install, nested_state):
        with pytest.raises(SystemExit, match="overlaps"):
            validate_read_roots([str(path)], install, home, source)


def test_bootstrap_read_roots_refuse_other_git_checkout(tmp_path):
    home, source, install, checkout = (tmp_path / name for name in ("home", "source", "install", "other"))
    for path in (home, source, install, checkout):
        path.mkdir()
    (checkout / ".git").mkdir()
    nested = checkout / "tools"
    nested.mkdir()
    for path in (checkout, nested):
        with pytest.raises(SystemExit, match="overlaps"):
            validate_read_roots([str(path)], install, home, source)


def test_bootstrap_read_roots_refuse_a_nested_checkout(tmp_path):
    home, source, install, library = (tmp_path / name for name in ("home", "source", "install", "library"))
    for path in (home, source, install, library):
        path.mkdir()
    (library / "nested/.git").mkdir(parents=True)
    with pytest.raises(SystemExit, match="contains a Git checkout"):
        validate_read_roots([str(library)], install, home, source)


def test_bootstrap_accepts_formula_inside_a_homebrew_prefix_checkout(tmp_path):
    home, source, install, brew = (tmp_path / name for name in ("home", "source", "install", "brew"))
    for path in (home, source, install, brew):
        path.mkdir()
    (brew / ".git").mkdir()
    (brew / "opt").mkdir()
    formula = brew / "Cellar/uv/1.0/bin"
    formula.mkdir(parents=True)
    validate_read_roots([str(formula)], install, home, source)
