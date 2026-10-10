from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _python(path: Path, modules: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"available = {set(modules)!r}\n"
        "if len(sys.argv) == 3 and sys.argv[1] == '-c':\n"
        "    imports = sys.argv[2].removeprefix('import ').split('; import ')\n"
        "    sys.exit(0 if set(imports) <= available else 1)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    shutil.copyfile(Path("Makefile"), tmp_path / "Makefile")
    for candidate in ("python3.12", "python3", "python"):
        _python(tmp_path / "bin" / candidate, ())
    return tmp_path


def _make(workspace: Path, *args: str, override: str | None = None) -> str:
    env = dict(os.environ, PATH=f"{workspace / 'bin'}:{os.defpath}")
    for variable in ("PYTHON", "MAKEFLAGS", "MFLAGS", "MAKELEVEL"):
        env.pop(variable, None)
    if override is not None:
        env["PYTHON"] = override
    result = subprocess.run(
        [shutil.which("make") or "make", "-n", *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_partial_venv_falls_back_by_target(workspace: Path) -> None:
    _python(workspace / ".venv/bin/python", ("pytest",))
    # The first PATH candidate has ruff but lacks mypy; lint must skip it too.
    _python(workspace / "bin/python3.12", ("ruff",))
    _python(workspace / "bin/python3", ("ruff", "mypy"))
    output = _make(workspace, "test", "lint")
    assert ".venv/bin/python -m pytest" in output
    assert f"{workspace / 'bin/python3'} -m ruff" in output
    assert f"{workspace / 'bin/python3'} -m mypy" in output

    _python(workspace / ".venv/bin/python", ())
    _python(workspace / "bin/python3.12", ("pytest",))
    output = _make(workspace, "test", "lint")
    assert f"{workspace / 'bin/python3.12'} -m pytest" in output
    assert f"{workspace / 'bin/python3'} -m mypy" in output


def test_complete_venv_and_explicit_override_precedence(workspace: Path) -> None:
    _python(workspace / ".venv/bin/python", ("pytest", "ruff", "mypy"))
    _python(workspace / "bin/python3.12", ("pytest",))
    output = _make(workspace, "test", "lint")
    assert ".venv/bin/python -m pytest" in output
    assert ".venv/bin/python -m ruff" in output
    assert ".venv/bin/python -m mypy" in output

    # An explicit override stays authoritative even if it lacks the tools.
    for output in (
        _make(workspace, "test", "lint", "PYTHON=chosen-python"),
        _make(workspace, "test", "lint", override="chosen-python"),
    ):
        assert "chosen-python -m pytest" in output
        assert "chosen-python -m ruff" in output
        assert "chosen-python -m mypy" in output


def test_no_complete_candidate_preserves_failure_and_runtime_default(workspace: Path) -> None:
    _python(workspace / ".venv/bin/python", ())
    output = _make(workspace, "test", "lint", "eval")
    assert ".venv/bin/python -m pytest" in output
    assert ".venv/bin/python -m mypy" in output
    assert ".venv/bin/python -m app.eval.run" in output
