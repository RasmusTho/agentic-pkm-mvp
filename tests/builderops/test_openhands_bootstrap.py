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
