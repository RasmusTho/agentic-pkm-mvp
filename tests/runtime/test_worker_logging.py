import logging

from app.workers import outbox_worker


def test_worker_emits_startup_log(monkeypatch, capsys) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
        monkeypatch.setattr(outbox_worker, "poll_outbox_one", lambda: None)
        monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
        outbox_worker.run(
            interval=0,
            heartbeat_interval=0,
            startup_retries=1,
            retry_delay=0,
            log_heartbeat_interval=10,
            stop_after_ticks=1,
        )
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "worker starting" in combined
        assert "worker heartbeat" not in combined
    finally:
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.setLevel(original_level)
