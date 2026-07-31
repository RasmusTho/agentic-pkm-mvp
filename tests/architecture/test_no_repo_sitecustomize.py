from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repo_root_pythonpath_startup_is_side_effect_free() -> None:
    """No root-level sitecustomize.py may exist in the repo.

    sitecustomize.py at the repo root would be silently imported by any
    subprocess that puts REPO_ROOT on PYTHONPATH, shadowing the real
    interpreter sitecustomize (e.g. Homebrew's site-packages wiring) and
    auto-importing app.* modules before user code runs.  Issue #4366 removes
    the file; this test ensures it never comes back.
    """
    assert not (REPO_ROOT / "sitecustomize.py").exists(), (
        "sitecustomize.py must not exist at the repo root (see issue #4366); "
        "placing the repo root on PYTHONPATH would shadow the real interpreter "
        "sitecustomize and silently import app.* at subprocess startup."
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; assert not [m for m in sys.modules if m == 'app' or m.startswith('app.')], f'unexpected app modules at startup: {[m for m in sys.modules if m == \"app\" or m.startswith(\"app.\")]}'",
        ],
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Subprocess with REPO_ROOT on PYTHONPATH imported app.* at startup.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_subprocess_helper_docstring_does_not_claim_repo_sitecustomize() -> None:
    """The subprocess_pythonpath helper must not claim sitecustomize.py exists.

    The old docstring contained the phrase 'kept for the decision-receipt hook'
    which asserted the repo-root sitecustomize.py was intentional.  After
    issue #4366 removes the file that claim is false and must not reappear.
    """
    helper = REPO_ROOT / "tests" / "helpers" / "subprocess_pythonpath.py"
    assert helper.exists(), f"Helper not found: {helper}"

    docstring_phrase = "kept for the decision-receipt hook"
    source = helper.read_text(encoding="utf-8")
    assert docstring_phrase not in source, (
        f"tests/helpers/subprocess_pythonpath.py still contains the phrase "
        f"{docstring_phrase!r}, which incorrectly asserts that a repo-root "
        f"sitecustomize.py exists.  Update the docstring after issue #4366."
    )
