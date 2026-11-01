"""Qualify installed native browser bytes independently of deployment fixtures."""
from __future__ import annotations

import sys

import pytest


@pytest.mark.parametrize("fault", (None, "missing", "symlink", "ambiguous", "outside"))
def test_browser_probe_qualifies_installed_headless_shell(tmp_path, monkeypatch, capsys, fault):
    import hashlib
    import importlib.metadata
    import json
    import subprocess
    from types import SimpleNamespace
    from app.ops.native_operations_acceptance_runner import BROWSER_PROBE

    browser_root = tmp_path / "browsers"
    shell_root = browser_root / "chromium_headless_shell-1243"
    executable = shell_root / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    executable.parent.mkdir(parents=True)
    payload = b"finite synthetic installed shell payload"
    executable.write_bytes(payload)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
    advertised = shell_root
    if fault == "missing":
        executable.unlink()
    elif fault == "symlink":
        target = tmp_path / "foreign-browser"
        target.write_bytes(payload)
        executable.unlink()
        executable.symlink_to(target)
    elif fault == "ambiguous":
        (shell_root / "headless_shell").write_bytes(payload)
    elif fault == "outside":
        advertised = tmp_path / "elsewhere" / shell_root.name

    calls = []

    def cli(argv, **kwargs):
        assert argv == [sys.executable, "-I", "-m", "playwright", "install",
                        "--dry-run", "--only-shell", "chromium"]
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 20}
        calls.append(argv)
        return SimpleNamespace(stdout=(
            "Chrome Headless Shell (playwright chromium-headless-shell v1243)\n"
            f"  Install location:    {advertised}\n\n"
            f"FFmpeg\n  Install location:    {browser_root / 'ffmpeg-1011'}\n"))

    monkeypatch.setattr(subprocess, "run", cli)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.63.0" if name == "playwright" else None)
    if fault is None:
        exec(compile(BROWSER_PROBE, "<native-browser-probe>", "exec"), {})
        assert json.loads(capsys.readouterr().out) == {
            "playwright": "1.63.0", "executable": str(executable),
            "executable_sha256": hashlib.sha256(payload).hexdigest(),
        }
        assert not (browser_root / "chromium-1243").exists()
    else:
        with pytest.raises(ValueError, match="native browser"):
            exec(compile(BROWSER_PROBE, "<native-browser-probe>", "exec"), {})
        assert capsys.readouterr().out == ""
    assert len(calls) == 1
