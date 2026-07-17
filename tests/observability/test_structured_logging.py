"""Structured JSON logging for runtime service processes (#3895).

Contract for ``app/observability/logging_setup.py``: API, worker, and watcher
processes install one shared JSON formatter on the root logger at process
setup. Field names reuse the span-schema conventions of
``app/observability/log.py`` documented in
``docs/OBSERVABILITY.md :: JSON log and span schema`` (``trace_id``,
``status``, ``extra``) so service logs and instrumented spans correlate with
the same jq recipes. Call sites keep the stdlib ``logging.getLogger(__name__)``
API untouched.
"""

from __future__ import annotations

import io
import json
import logging

import pytest


@pytest.fixture()
def clean_root_logger():
    """Snapshot and restore root-logger handlers/level around a test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    for handler in saved_handlers:
        root.removeHandler(handler)
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def _make_record(
    msg: str = "hello world",
    level: int = logging.INFO,
    extra: dict | None = None,
) -> logging.LogRecord:
    logger = logging.getLogger("app.test.structured")
    return logger.makeRecord(
        logger.name, level, __file__, 42, msg, (), None, extra=extra
    )


# ---------------------------------------------------------------------------
# (1) Formatter renders a log record as valid JSON with the expected keys.
# ---------------------------------------------------------------------------


def test_formatter_renders_valid_json_with_expected_keys():
    from app.observability.logging_setup import JsonLogFormatter

    line = JsonLogFormatter().format(_make_record())
    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test.structured"
    assert payload["status"] == "ok"
    assert "timestamp" in payload


def test_formatter_marks_error_records_with_span_schema_status():
    from app.observability.logging_setup import JsonLogFormatter

    line = JsonLogFormatter().format(_make_record("boom", logging.ERROR))
    assert json.loads(line)["status"] == "error"


def test_formatter_surfaces_extra_fields_under_extra_key():
    from app.observability.logging_setup import JsonLogFormatter

    line = JsonLogFormatter().format(
        _make_record(extra={"note_path": "inbox/a.md", "attempts": 3})
    )
    payload = json.loads(line)
    assert payload["extra"] == {"note_path": "inbox/a.md", "attempts": 3}


def test_formatter_renders_exception_info():
    from app.observability.logging_setup import JsonLogFormatter

    try:
        raise ValueError("kaput")
    except ValueError:
        import sys

        record = _make_record("failed", logging.ERROR)
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonLogFormatter().format(record))
    assert "ValueError: kaput" in payload["exc"]
    assert payload["status"] == "error"


# ---------------------------------------------------------------------------
# (2) trace_id contextvar (app.observability.tracer) threads into log lines.
# ---------------------------------------------------------------------------


def test_trace_id_present_when_context_set():
    from app.observability.logging_setup import JsonLogFormatter
    from app.observability.tracer import start_span

    with start_span("test.span", trace_id="trace-ctx-1"):
        line = JsonLogFormatter().format(_make_record())
    assert json.loads(line)["trace_id"] == "trace-ctx-1"


def test_trace_id_absent_outside_context():
    from app.observability.logging_setup import JsonLogFormatter

    payload = json.loads(JsonLogFormatter().format(_make_record()))
    assert "trace_id" not in payload


def test_configured_logger_emits_json_line_with_trace_id(clean_root_logger):
    from app.observability.logging_setup import configure_json_logging
    from app.observability.tracer import start_span

    stream = io.StringIO()
    configure_json_logging(stream=stream)
    logger = logging.getLogger("app.test.structured.e2e")
    with start_span("test.span", trace_id="trace-e2e-1"):
        logger.info("worker starting interval=%s", 0.2)
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "worker starting interval=0.2"
    assert payload["trace_id"] == "trace-e2e-1"
    assert payload["status"] == "ok"


def test_configure_json_logging_is_idempotent(clean_root_logger):
    from app.observability.logging_setup import (
        JsonLogFormatter,
        configure_json_logging,
    )

    configure_json_logging(stream=io.StringIO())
    configure_json_logging(stream=io.StringIO())
    json_handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h.formatter, JsonLogFormatter)
    ]
    assert len(json_handlers) == 1


def test_reconfigure_json_logging_replaces_closed_capture_stream(clean_root_logger):
    from app.observability.logging_setup import (
        JsonLogFormatter,
        configure_json_logging,
    )

    closed_capture = io.StringIO()
    handler = configure_json_logging(stream=closed_capture)
    closed_capture.close()
    replacement = io.StringIO()

    rebound = configure_json_logging(stream=replacement)
    logging.getLogger("app.test.closed.capture").info("rebound")

    assert rebound is handler
    assert json.loads(replacement.getvalue())["message"] == "rebound"
    json_handlers = [
        candidate
        for candidate in logging.getLogger().handlers
        if isinstance(candidate.formatter, JsonLogFormatter)
    ]
    assert json_handlers == [handler]


# ---------------------------------------------------------------------------
# Process entrypoint wiring: API, worker, watcher.
# ---------------------------------------------------------------------------


def _root_has_json_handler() -> bool:
    from app.observability.logging_setup import JsonLogFormatter

    return any(
        isinstance(h.formatter, JsonLogFormatter)
        for h in logging.getLogger().handlers
    )


def test_api_app_factory_wires_json_formatter(clean_root_logger):
    from app.api.app import _create_app

    _create_app()
    assert _root_has_json_handler()


def test_api_request_log_lines_carry_request_trace_id(clean_root_logger):
    from fastapi.testclient import TestClient

    from app.api.app import _create_app
    from app.observability.logging_setup import configure_json_logging

    app = _create_app()
    stream = io.StringIO()
    # Idempotent re-call rebinds the handler installed by _create_app to a
    # capturable stream without adding a second handler.
    configure_json_logging(stream=stream)

    @app.get("/__structured_logging_probe")
    def _probe():  # pragma: no cover - exercised via TestClient below
        logging.getLogger("app.test.api.probe").info("inside request")
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/__structured_logging_probe", headers={"x-trace-id": "req-trace-1"}
    )
    assert response.status_code == 200
    lines = [json.loads(l) for l in stream.getvalue().strip().splitlines() if l]
    probe_lines = [p for p in lines if p.get("logger") == "app.test.api.probe"]
    assert probe_lines, f"no probe log line captured; got: {lines}"
    assert probe_lines[-1]["trace_id"] == "req-trace-1"


def test_worker_entrypoint_configures_json_logging(clean_root_logger, capsys):
    from app.workers import outbox_worker

    outbox_worker._ensure_logging_configured()
    assert _root_has_json_handler()

    outbox_worker.logger.info("worker starting")
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["logger"] == "app.workers.outbox_worker"
    assert payload["message"] == "worker starting"


def test_watcher_entrypoint_configures_json_logging(clean_root_logger, monkeypatch):
    from click.testing import CliRunner

    import app.cli.watcher as watcher_cli

    monkeypatch.delenv("WATCHER_ENABLE", raising=False)
    monkeypatch.setattr(watcher_cli, "_validate_settings_or_exit", lambda: None)

    def _stop(*args, **kwargs):
        raise RuntimeError("stop before watcher loop")

    monkeypatch.setattr(watcher_cli, "load_registry_config", _stop)

    result = CliRunner().invoke(watcher_cli.watcher_group, ["run"])
    assert result.exit_code != 0  # stopped deliberately after logging setup
    assert _root_has_json_handler()
