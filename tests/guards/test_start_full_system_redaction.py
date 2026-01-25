from __future__ import annotations

from pathlib import Path


def test_capture_step_redacts_password_output() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    if "capture_step()" not in script:
        raise AssertionError("capture_step() not found in start_full_system.sh")
    if "run_db_probe()" not in script:
        raise AssertionError("run_db_probe() not found in start_full_system.sh")
    section = script.split("capture_step()", 1)[1].split("run_db_probe()", 1)[0]
    assert "grep -qi \"password\"" in section
    assert "snippet=\"[redacted]\"" in section
