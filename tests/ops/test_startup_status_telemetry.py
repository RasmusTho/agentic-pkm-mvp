from __future__ import annotations

import json
from pathlib import Path


def _extract_status_writer() -> str:
    script = Path("scripts/start_full_system.sh").read_text()
    marker = 'STARTUP_STATUS_PATH="$startup_status_path" python - <<\'PY\'\n'
    start = script.find(marker)
    assert start != -1, "startup status writer block not found"
    start += len(marker)
    end = script.find("\nPY\n", start)
    assert end != -1, "startup status writer block terminator not found"
    return script[start:end]


def test_startup_status_telemetry_shape(tmp_path, monkeypatch) -> None:
    code = _extract_status_writer()
    status_path = tmp_path / "startup_status.json"

    monkeypatch.setenv("STARTUP_STATUS_PATH", str(status_path))
    monkeypatch.setenv("START_MODE", "runtime")
    monkeypatch.setenv("PRE_FLIGHT_PASSED", "1")
    monkeypatch.setenv("PHASE", "db_probe")
    monkeypatch.setenv("LLM_PROBE_STEP", "llm_check")
    monkeypatch.setenv("LLM_PROBE_CMD", "python -m app.cli llm check --json")
    monkeypatch.setenv("LLM_PROBE_RC", "0")
    monkeypatch.setenv("LLM_PROBE_OUTPUT_SNIPPET", "{\"ok\": true}")
    monkeypatch.setenv("COMPOSE_UP_STEP", "db_api")
    monkeypatch.setenv("COMPOSE_UP_CMD", "compose_up --build db api")
    monkeypatch.setenv("COMPOSE_UP_RC", "2")
    monkeypatch.setenv("COMPOSE_UP_OUTPUT_SNIPPET", "compose failed")
    monkeypatch.setenv("DB_PROBE_STEP", "compose_ps_db")
    monkeypatch.setenv("DB_PROBE_CMD", "docker compose ps -q db")
    monkeypatch.setenv("DB_PROBE_RC", "1")
    monkeypatch.setenv("DB_PROBE_OUTPUT_SNIPPET", "no container")
    monkeypatch.setenv("STARTUP_SUCCEEDED", "true")
    monkeypatch.setenv("RUNTIME_VERIFIED", "true")
    monkeypatch.setenv("OPERATOR_INTERRUPTED", "false")

    exec_globals: dict[str, object] = {}
    exec(code, exec_globals, exec_globals)

    payload = json.loads(status_path.read_text())
    assert payload["phase"] == "db_probe"
    assert payload["llm_probe_step"] == "llm_check"
    assert payload["llm_probe_cmd"] == "python -m app.cli llm check --json"
    assert payload["llm_probe_rc"] == 0
    assert payload["llm_probe_output_snippet"] == '{"ok": true}'
    assert payload["compose_up_step"] == "db_api"
    assert payload["compose_up_cmd"] == "compose_up --build db api"
    assert payload["compose_up_rc"] == 2
    assert payload["compose_up_output_snippet"] == "compose failed"
    assert payload["db_probe_step"] == "compose_ps_db"
    assert payload["db_probe_cmd"] == "docker compose ps -q db"
    assert payload["db_probe_rc"] == 1
    assert payload["db_probe_output_snippet"] == "no container"
    assert payload["startup_succeeded"] is True
    assert payload["runtime_verified"] is True
    assert payload["operator_interrupted"] is False
