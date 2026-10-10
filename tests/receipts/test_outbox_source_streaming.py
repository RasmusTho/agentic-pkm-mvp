from __future__ import annotations

import json
import fcntl
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

import pytest

from app.receipts import outbox_sources
from app.services import outbox as outbox_service


class StreamingCursor:
    """A server cursor double that refuses client-wide buffering."""

    def __init__(self, connection: StreamingConnection, rows: Iterable[Any]) -> None:
        self.connection = connection
        self.rows = iter(rows)
        self.batch_sizes: list[int] = []
        self.closed = False
        self.returned = 0

    def execute(self, sql: str) -> None:
        assert sql.lower() == "select id, topic, payload, created_at from outbox order by created_at asc"
        assert self.connection.autocommit is False
        assert self.connection.read_only is True

    def fetchall(self):
        raise AssertionError("receipt sources must not fetchall")

    def fetchmany(self, size: int) -> list[Any]:
        self.batch_sizes.append(size)
        if self.connection.fail_after is not None and self.returned >= self.connection.fail_after:
            raise OSError("fixture source disconnected")
        rows = list(islice(self.rows, size))
        self.returned += len(rows)
        return rows

    def close(self) -> None:
        self.closed = True


class StreamingConnection:
    def __init__(self, rows: Iterable[Any], *, fail_after: int | None = None) -> None:
        self.autocommit = True
        self.read_only = False
        self.closed = False
        self.fail_after = fail_after
        self.reader = StreamingCursor(self, rows)

    def cursor(self, *, name: str | None = None) -> StreamingCursor:
        assert name, "a client cursor can buffer the whole result even with fetchmany"
        return self.reader

    def close(self) -> None:
        self.closed = True


def test_db_receipt_source_streams_complete_history_without_fetchall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = datetime(2026, 10, 10, tzinfo=timezone.utc)
    count = 10_003

    def rows():
        for index in range(count):
            if index % 2:
                yield {"id": index, "topic": "test.receipt", "payload": json.dumps({"value": index}), "created_at": timestamp}
            else:
                yield index, "test.receipt", {"value": index}, timestamp

    connection = StreamingConnection(rows())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)

    with outbox_sources.open_receipt_source_records(outbox_path=tmp_path / "missing.jsonl") as records:
        assert records is not None
        for index, record in enumerate(records):
            assert record["value"] == index
            assert record["event"] == record["event_type"] == "test.receipt"
            assert record["event_id"] == str(index)
            assert record["timestamp"] == record["created_at"] == "2026-10-10T00:00:00Z"
        assert index + 1 == count

    assert len(connection.reader.batch_sizes) > 1
    assert max(connection.reader.batch_sizes) < count
    assert connection.reader.returned == count
    assert connection.reader.closed and connection.closed


def test_jsonl_receipt_source_streams_complete_history_without_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "outbox.jsonl"
    count = 10_003
    with path.open("wb") as handle:
        for index in range(count):
            record = {"event_id": str(index), "payload": "före\u2028efter\u2029slut"}
            handle.write(json.dumps(record, ensure_ascii=False).encode("utf-8"))
            if index < count - 1:
                handle.write(b"\n\n")
    before = path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode

    def refuse_eager_read(self: Path) -> bytes:
        raise AssertionError("receipt sources must not read whole files")

    monkeypatch.setattr(Path, "read_bytes", refuse_eager_read)
    with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
        assert records is not None
        for index, record in enumerate(records):
            assert record["event_id"] == str(index)
            assert record["payload"] == "före\u2028efter\u2029slut"
        assert index + 1 == count
    with path.open("rb") as handle:
        assert handle.read() == before[0]
    assert (path.stat().st_mtime_ns, path.stat().st_mode) == before[1:]
    assert not path.with_name(f".{path.name}.append.lock").exists()


@pytest.mark.parametrize("suffix", [b'{"broken":', b'\xff', b'[]'])
def test_streamed_jsonl_fails_closed_after_valid_history(
    tmp_path: Path, suffix: bytes,
) -> None:
    path = tmp_path / "corrupt.jsonl"
    original = b'{"event_id":"valid"}\n' + suffix
    path.write_bytes(original)
    with pytest.raises(outbox_service.JsonlOutboxCorruptionError):
        with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
            assert records is not None
            list(records)
    assert path.read_bytes() == original


def test_streamed_sources_preserve_db_before_jsonl_order_and_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "outbox.jsonl"
    path.write_text('{"event_id":"jsonl"}\n', encoding="utf-8")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    connection = StreamingConnection([(1, "test.receipt", {"event_id": "db"}, None)])
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)
    with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
        assert records is not None
        assert [record["event_id"] for record in records] == ["db", "jsonl"]

    def unavailable():
        raise OSError("fixture source unavailable")

    monkeypatch.setattr(outbox_service, "_open_conn", unavailable)
    with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
        assert records is None  # Never make a configured-DB partial view authoritative.
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    path.write_text("", encoding="utf-8")
    with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
        assert records is not None and list(records) == []
    path.unlink()
    with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
        assert records is None


def test_streamed_db_late_failure_refuses_partial_history_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = StreamingConnection(((index, "test.receipt", {}, None) for index in range(10_003)), fail_after=1)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)
    with pytest.raises(outbox_sources.ReceiptSourceUnavailableError):
        with outbox_sources.open_receipt_source_records(outbox_path=tmp_path / "missing.jsonl") as records:
            assert records is not None
            list(records)
    assert connection.closed and connection.reader.closed


def test_streamed_db_closes_when_consumer_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = StreamingConnection(((index, "test.receipt", {}, None) for index in range(10_003)))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)
    with outbox_sources.open_receipt_source_records(outbox_path=tmp_path / "missing.jsonl") as records:
        assert records is not None
        assert next(records)["event_id"] == "0"
    assert connection.closed and connection.reader.closed


def test_streamed_jsonl_releases_existing_shared_lock_when_consumer_stops(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    path.write_text('{"event_id":"first"}\n{"event_id":"second"}', encoding="utf-8")
    lock = path.with_name(f".{path.name}.append.lock")
    lock.write_text("", encoding="utf-8")
    before = path.read_bytes(), lock.stat().st_mtime_ns
    with lock.open("r") as handle:
        with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
            assert records is not None and next(records)["event_id"] == "first"
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert (path.read_bytes(), lock.stat().st_mtime_ns) == before


@pytest.mark.parametrize("failure", [FileNotFoundError, OSError])
def test_jsonl_io_failure_after_valid_record_is_not_successful_eof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure) -> None:
    path = tmp_path / "outbox.jsonl"
    path.write_text('{"event_id":"first"}\n{"event_id":"second"}\n', encoding="utf-8")
    original_open = Path.open
    handles = []

    class FailingRead:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.handle.close()

        def __iter__(self):
            yield next(self.handle)
            raise failure("fixture read interrupted")

    def open_path(candidate, *args, **kwargs):
        handle = original_open(candidate, *args, **kwargs)
        if candidate == path and args == ("rb",):
            handles.append(handle)
            return FailingRead(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_path)
    with pytest.raises(outbox_service.JsonlOutboxCorruptionError):
        with outbox_sources.open_receipt_source_records(outbox_path=path) as records:
            assert records is not None
            list(records)
    assert handles and all(handle.closed for handle in handles)
