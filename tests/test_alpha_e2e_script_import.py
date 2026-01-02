from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg


def test_alpha_e2e_import_from_non_root_cwd(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "alpha_e2e.py"
    snippet = "\n".join(
        [
            "import importlib.util",
            "from pathlib import Path",
            f"path = Path({str(script_path)!r})",
            "spec = importlib.util.spec_from_file_location('alpha_e2e', path)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
