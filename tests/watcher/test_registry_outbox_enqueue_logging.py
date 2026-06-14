from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

import app.watcher.registry as registry

pytestmark = pytest.mark.not_pg


def _write_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: ingest
                scope_glob: "${VAULT_INBOX_DIR_REL}/**"
                debounce_ms: 0
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def test_registry_logs_db_outbox_enqueue_failures_with_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note = inbox / "uuidless.md"
    note.write_text("---\ntitle: uuidless\n---\n\nBody\n", encoding="utf-8")

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.services.outbox.insert_object_and_outbox", boom)
    monkeypatch.setattr(registry.__name__ + ".insert_object_and_outbox", boom)

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "📥 Inbox")
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))

    stop_file = tmp_path / "stop"
    monkeypatch.setenv("WATCHER_STOP_FILE", str(stop_file))
    if stop_file.exists():
        stop_file.unlink()

    monkeypatch.setenv("DB_DSN", "postgresql://example.invalid")

    caplog.set_level("ERROR")

    summaries = registry.run_registry_once(config_path)
    summary = summaries["ingest"]
    assert summary.get("enqueue_failures_total") == 1

    messages = [rec.getMessage() for rec in caplog.records]
    assert any("watcher db outbox enqueue failed" in msg for msg in messages)
    assert any("topic=ingest.vault.changed" in msg for msg in messages)
    assert any("relative_path=📥 Inbox/uuidless.md" in msg for msg in messages)

    assert any(rec.exc_info for rec in caplog.records)
