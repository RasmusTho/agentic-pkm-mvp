from __future__ import annotations

from pathlib import Path


def test_makefile_exposes_verify_runtime_and_doctor_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "verify-runtime:" in makefile
    assert "doctor: verify-runtime" in makefile
    assert "persist-runtime-repairs:" in makefile


def test_verify_runtime_stack_uses_in_container_checks() -> None:
    script = Path("scripts/verify_runtime_stack.sh").read_text(encoding="utf-8")
    assert "docker compose ps" in script
    assert "python -m app.cli health --json" in script
    assert "python -m app.cli status" in script
    assert 'print(\n        f"ROUTE {task_kind}:' in script
    assert "EMBEDDING INDEX:" in script
    assert "required health ok=true" in script


def test_verify_runtime_stack_parses_multiline_health_meta() -> None:
    script = Path("scripts/verify_runtime_stack.sh").read_text(encoding="utf-8")
    assert "sed -n '1p'" in script
    assert "sed -n '2p'" in script
    assert "sed -n '3p'" in script
