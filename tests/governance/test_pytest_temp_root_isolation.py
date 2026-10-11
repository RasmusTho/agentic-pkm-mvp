from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def _harness(directory: Path) -> dict[str, str]:
    """Exercise the repository's actual root hook in a bounded pytest suite."""
    root = Path(__file__).resolve().parents[2]
    (directory / "conftest.py").write_bytes((root / "conftest.py").read_bytes())
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # CI's plugin-specific flags do not belong to this standalone child suite.
    # subprocess timeouts below independently bound each child's lifetime.
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = str(directory)
    return env


def test_parallel_pytest_runs_use_unique_debug_temp_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--timeout=120 --timeout-method=thread")
    env = _harness(tmp_path)
    parent = tmp_path / "shared-parent"
    parent.mkdir()
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    (tmp_path / "test_probe.py").write_text(
        "import json, os, time\n"
        "from pathlib import Path\n"
        "def test_probe(tmp_path, tmp_path_factory):\n"
        "    report = Path(os.environ['REPORT'])\n"
        "    report.write_text(json.dumps({'root': os.environ.get('PYTEST_DEBUG_TEMPROOT'), "
        "'base': str(tmp_path_factory.getbasetemp()), 'fixture': str(tmp_path)}))\n"
        "    deadline = time.monotonic() + 20\n"
        "    while not Path(os.environ['PEER']).exists():\n"
        "        assert time.monotonic() < deadline, 'peer did not reach tmp_path'\n"
        "        time.sleep(0.01)\n"
    )
    reports = [tmp_path / "first.json", tmp_path / "second.json"]
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
            cwd=tmp_path,
            env={**env, "REPORT": str(report), "PEER": str(reports[1 - index])},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for index, report in enumerate(reports)
    ]
    try:
        for process in processes:
            output, _ = process.communicate(timeout=30)
            assert process.returncode == 0, output
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    results = [json.loads(report.read_text()) for report in reports]
    roots = [Path(result["root"]) for result in results]
    assert roots[0] != roots[1]
    for root, result in zip(roots, results):
        assert root.parent == parent
        assert root.is_dir()
        assert Path(result["base"]).is_relative_to(root)
        assert Path(result["fixture"]).is_relative_to(root)


@pytest.mark.parametrize("failure", ["creation", "validation"])
def test_temp_root_setup_fails_loud_when_namespace_cannot_be_created(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--timeout=120 --timeout-method=thread")
    env = _harness(tmp_path)
    env.pop("PYTEST_DEBUG_TEMPROOT", None)
    # Inject a filesystem failure through a plugin before root-hook configuration.
    (tmp_path / "broken_namespace.py").write_text(
        "import tempfile\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_configure(config):\n"
        "    def refuse(*args, **kwargs):\n"
        "        raise OSError('injected namespace failure')\n"
        + (
            "    tempfile.mkdtemp = refuse\n"
            if failure == "creation"
            else "    Path.write_bytes = refuse\n"
        )
    )
    (tmp_path / "test_probe.py").write_text(
        "from pathlib import Path\n"
        "Path('collected').touch()\n"
        "def test_probe(tmp_path):\n"
        "    Path('executed').touch()\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "broken_namespace", "-q", "-m", "not pg"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "pytest temporary-root isolation failed" in result.stdout + result.stderr
    assert "injected namespace failure" in result.stdout + result.stderr
    assert not (tmp_path / "collected").exists()
    assert not (tmp_path / "executed").exists()
