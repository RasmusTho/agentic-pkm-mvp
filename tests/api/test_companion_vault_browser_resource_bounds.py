from __future__ import annotations

import hashlib
import json
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent_memory.recall_retrieval import read_promoted_memories, retrieve_relevant_promoted
from app.api.app import app
from app.receipts import outbox_sources, promotion_receipts
from app.services import outbox as outbox_service
from tests.api._vault_test_helpers import bind_selected_vault
from tests.receipts.test_outbox_source_streaming import StreamingConnection


class _ObservedRecord(dict):
    __slots__ = ("__weakref__",)


class _LiveObjects:
    """Fail early on eager retention; never reproduce a live OOM in a test."""

    def __init__(self, limit: int) -> None:
        self.lock = threading.Lock()
        self.live = 0
        self.peak = 0
        self.limit = limit

    def watch(self, value):
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
            assert self.live <= self.limit, "reader retained unrelated source history"
        weakref.finalize(value, self.release)
        return value

    def release(self) -> None:
        with self.lock:
            self.live -= 1


def _promotion(event_id: str, *, timestamp: str, note_uuid: str, note_path: str, memory: bool = False) -> dict:
    return {
        "event": "promotion.transition.applied", "event_id": event_id, "timestamp": timestamp,
        "payload": {
            "artifact_uuid": note_uuid, "artifact_path": note_path,
            "vault_id": "vault-a",
            "transition_family": "agent_memory_materialization" if memory else "promotion",
            "target_maturity": "semantic_memory" if memory else "evergreen",
            "authority": {"requested_by": "fixture"},
            "basis": {"candidate_id": "candidate-a", "scope_id": "scope:work/project-alpha"},
            "outcome": {"status": "applied"},
            "artifact_linkage": {
                "artifact_uuid": note_uuid, "artifact_path": note_path, "candidate_id": "candidate-a",
            },
        },
    }


def _logged(event_id: str, timestamp: str, *, blocked: bool = False) -> dict:
    return {
        "event": "panel.action.blocked" if blocked else "panel.action.logged",
        "event_id": event_id, "timestamp": timestamp,
        "payload": {"note_path": "notes/0000.md"},
    }


def _snapshot(paths: list[Path]) -> dict:
    result = {}
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        stat = path.stat()
        result[str(path)] = stat.st_size, stat.st_mtime_ns, stat.st_mode, digest.hexdigest()
    return result


def _history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, count: int):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    for index in range(704):
        note = vault_root / "notes" / f"{index:04}.md"
        note.parent.mkdir(exist_ok=True)
        uuid = f"uuid: 00000000-0000-0000-0000-{index:012}\n" if index else ""
        note.write_text(f"---\n{uuid}title: Note {index}\nkind: human_note\n---\nSmall body.\n", encoding="utf-8")
    memory_path = "Agent Memory/retained.md"
    memory = vault_root / memory_path
    memory.parent.mkdir()
    memory.write_text(
        "---\nuuid: memory-a\nartifact_type: semantic_memory\nagent_promoted: true\n"
        "promoted_from_candidate_id: candidate-a\nscope_id: scope:work/project-alpha\n"
        "decided_at: '2026-10-10T00:00:00Z'\nsource_refs: [note:fixture]\n---\n"
        "# Retained preferences\nRead contracts before implementation.\n", encoding="utf-8",
    )
    bind_selected_vault(monkeypatch, vault_root)
    filler = _promotion("unselected", timestamp="2026-10-10T01:00:00Z", note_uuid="other", note_path="not-selected.md")
    filler["payload"]["basis"]["padding"] = "x" * 80
    early = _logged("oldest", "2026-10-10T00:00:00Z")
    promotion = _promotion("matching-promotion", timestamp="2026-10-10T04:00:00Z", note_uuid="00000000-0000-0000-0000-000000000001", note_path="different-path.md")
    collision = _promotion("collision", timestamp="2026-10-10T02:00:00Z", note_uuid="", note_path="notes/0000.md")
    memory_early = _promotion("memory-old", timestamp="2026-10-10T03:00:00Z", note_uuid="memory-a", note_path=memory_path, memory=True)
    memory_latest = _promotion("memory-latest", timestamp="2026-10-10T06:00:00Z", note_uuid="memory-a", note_path=memory_path, memory=True)
    # Timestamp order is deliberately different from source order.
    special = {0: early, 1: memory_early, count - 2: collision, count - 1: promotion}

    connections: list[StreamingConnection] = []

    def connect():
        rows = ((index, "promotion.transition.applied", special.get(index, dict(filler)), None) for index in range(count))
        connection = StreamingConnection(rows)
        connections.append(connection)
        return connection

    outbox = tmp_path / "outbox.jsonl"
    with outbox.open("wb") as handle:
        handle.write(json.dumps(early).encode("utf-8") + b"\n")  # Duplicate DB receipt.
        line = json.dumps(filler, separators=(",", ":")).encode("utf-8") + b"\n"
        for _ in range(count // 1000):
            handle.write(line * 1000)
        handle.write(line * (count % 1000))
        handle.write(json.dumps(_logged("collision", "2026-10-10T05:00:00Z", blocked=True)).encode("utf-8") + b"\n")
        handle.write(json.dumps(_logged("latest", "2026-10-10T07:00:00Z")).encode("utf-8") + b"\n")
        handle.write(json.dumps(memory_latest).encode("utf-8"))  # Complete, unterminated.
    lock_path = outbox.with_name(f".{outbox.name}.append.lock")
    lock_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(outbox_service, "_open_conn", connect)
    records = _LiveObjects(32)
    rows = _LiveObjects(32)
    original_coerce = outbox_sources._coerce_record
    original_jsonl = outbox_service.iter_jsonl_outbox_records
    original_project = promotion_receipts._project_transition_applied
    original_read_bytes = Path.read_bytes

    def coerce(value):
        return records.watch(_ObservedRecord(original_coerce(value)))

    def iter_jsonl(path):
        source = original_jsonl(path)
        try:
            for record in source:
                yield records.watch(_ObservedRecord(record))
        finally:
            source.close()

    def project(record, *, vault_root):
        row, reason = original_project(record, vault_root=vault_root)
        if row is not None:
            rows.watch(row)
        return row, reason

    def read_bytes(path):
        assert path != outbox, "receipt path must not read the whole JSONL file"
        return original_read_bytes(path)

    monkeypatch.setattr(outbox_sources, "_coerce_record", coerce)
    monkeypatch.setattr(outbox_service, "iter_jsonl_outbox_records", iter_jsonl)
    monkeypatch.setattr(promotion_receipts, "_project_transition_applied", project)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    paths = [*sorted(vault_root.rglob("*.*")), outbox, lock_path]
    return vault_root, outbox, connections, records, rows, paths


def _browser():
    client = TestClient(app)
    try:
        response = client.get("/api/companion/vault-browser", params={"limit": 250})
    finally:
        client.close()
    assert response.status_code == 200
    data = response.json()
    assert data["read_only"] is True and data["identity_available"] is True
    assert data["total_notes"] == data["filtered_notes"] == 705
    assert data["pagination"]["has_next"] is True
    assert len(data["notes"]) == 250
    by_path = {note["note_path"]: note for note in data["notes"]}
    assert by_path["notes/0000.md"]["uuid"] is None
    receipts = by_path["notes/0000.md"]["receipts"]
    assert [receipt["receipt_id"] for receipt in receipts] == ["oldest", "collision", "latest"]
    assert receipts[1]["action_type"] == "panel.action.blocked"  # Ordinary beats promotion duplicate.
    assert [row["receipt_id"] for row in by_path["notes/0001.md"]["receipts"]] == ["matching-promotion"]
    assert [row["receipt_id"] for row in by_path["Agent Memory/retained.md"]["receipts"]] == ["memory-old", "memory-latest"]
    return data


@pytest.mark.parametrize("history_count", [4096, 352_539])
def test_vault_browser_production_callsite_bounds_receipt_reads_without_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history_count: int,
) -> None:
    root, outbox, connections, records, rows, paths = _history(tmp_path, monkeypatch, count=history_count)
    before = _snapshot(paths)
    _browser()
    memories = read_promoted_memories(vault_root=root, outbox_path=outbox, active_vault_id="vault-a")
    assert [memory.promotion_id for memory in memories] == ["memory-old", "memory-latest"]
    assert records.peak <= 4 and rows.peak <= 8
    assert _snapshot(paths) == before
    assert all(connection.closed and connection.reader.closed for connection in connections)
    assert all(connection.reader.returned == history_count for connection in connections)
    if history_count == 352_539:
        assert outbox.stat().st_size >= 198_000_000


def test_repeated_concurrent_readers_preserve_projection_and_source_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, outbox, connections, records, rows, paths = _history(tmp_path, monkeypatch, count=4096)
    before = _snapshot(paths)
    expected = _browser()

    def recall():
        return retrieve_relevant_promoted(
            "contracts implementation", k=2, vault_root=root, outbox_path=outbox,
            active_scope_id="scope:work/project-alpha", active_vault_id="vault-a",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        browser_futures = [pool.submit(_browser) for _ in range(2)]
        recall_futures = [pool.submit(recall) for _ in range(2)]
        assert [future.result() for future in browser_futures] == [expected, expected]
        for future in recall_futures:
            candidates = future.result()
            assert [candidate.receipt_id for candidate in candidates] == ["memory-old", "memory-latest"]
            assert all(candidate.memory_scope_id == candidate.applied_scope_id == "scope:work/project-alpha" for candidate in candidates)
    assert _browser() == expected
    assert _snapshot(paths) == before
    assert records.peak <= 16 and rows.peak <= 32
    assert all(connection.closed and connection.reader.closed for connection in connections)


@pytest.mark.parametrize("consumer", ["browser", "promotion", "recall"])
def test_late_db_failure_discards_prior_matches_for_every_read_consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str) -> None:
    root, outbox, _connections, _records, _rows, paths = _history(tmp_path, monkeypatch, count=512)
    first = _promotion("prior-match", timestamp="2026-10-10T00:00:00Z", note_uuid="memory-a", note_path="Agent Memory/retained.md", memory=True)
    def db_rows():
        return ((index, "promotion.transition.applied", first if index == 0 else {"event": "runtime.trace"}, None) for index in range(512))

    connection = StreamingConnection(db_rows(), fail_after=1)
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)
    before = _snapshot(paths)
    if consumer == "browser":
        data = TestClient(app).get("/api/companion/vault-browser").json()
        assert data["notes"] and all("receipts" not in note for note in data["notes"])
    elif consumer == "promotion":
        result = promotion_receipts.query_promotion_receipts(vault_root=root, outbox_path=outbox)
        assert result.source_available is False and result.rows == () and result.non_authoritative_records == ()
    else:
        assert read_promoted_memories(vault_root=root, outbox_path=outbox, active_vault_id="vault-a") == []
        connection = StreamingConnection(db_rows(), fail_after=1)
        monkeypatch.setattr(outbox_service, "_open_conn", lambda: connection)
        assert retrieve_relevant_promoted("contracts", vault_root=root, outbox_path=outbox, active_vault_id="vault-a") == []
    assert connection.closed and connection.reader.closed
    assert _snapshot(paths) == before


@pytest.mark.parametrize("consumer", ["browser", "promotion", "recall"])
def test_late_jsonl_corruption_refuses_prior_matches_without_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str) -> None:
    root, outbox, _connections, _records, _rows, paths = _history(tmp_path, monkeypatch, count=512)
    with outbox.open("ab") as handle:
        handle.write(b'\n{"broken":')
    before = _snapshot(paths)
    if consumer == "recall":
        assert read_promoted_memories(vault_root=root, outbox_path=outbox, active_vault_id="vault-a") == []
    else:
        with pytest.raises(outbox_service.JsonlOutboxCorruptionError):
            if consumer == "browser":
                TestClient(app).get("/api/companion/vault-browser")
            else:
                promotion_receipts.query_promotion_receipts(
                    promotion_receipts.PromotionReceiptQuery(artifact_uuid="memory-a"),
                    vault_root=root, outbox_path=outbox,
                )
    assert _snapshot(paths) == before
