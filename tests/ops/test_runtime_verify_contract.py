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


def test_prod_start_full_sets_verify_runtime_service_wait_seconds() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    prod_block_start = makefile.find("prod-start-full:")
    assert prod_block_start != -1, "prod-start-full target not found in Makefile"
    prod_block_end = makefile.find("\n\n", prod_block_start)
    prod_block = makefile[prod_block_start:prod_block_end if prod_block_end != -1 else None]
    assert "VERIFY_RUNTIME_SERVICE_WAIT_SECONDS" in prod_block, (
        "prod-start-full must set VERIFY_RUNTIME_SERVICE_WAIT_SECONDS to avoid false "
        "runtime verification failures caused by worker Docker healthcheck timing"
    )
    import re
    match = re.search(r"VERIFY_RUNTIME_SERVICE_WAIT_SECONDS=(\d+)", prod_block)
    assert match is not None
    wait_seconds = int(match.group(1))
    assert wait_seconds >= 20, (
        f"VERIFY_RUNTIME_SERVICE_WAIT_SECONDS={wait_seconds} is less than the worker "
        "Docker healthcheck interval (20s); prod verification will produce false failures"
    )
