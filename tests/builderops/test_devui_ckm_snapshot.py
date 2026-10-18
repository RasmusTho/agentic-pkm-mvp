from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import pytest

from app.builderops.ckm.contracts import ErrorEnvelope, ResultEnvelope, canonical_digest, canonical_json
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmStore
from app.builderops.devui_ckm_snapshot import (
    FILENAME, MAX_BYTES, build_private_snapshot, decode_private_snapshot, read_private_ckm,
)
from app.builderops.devui_composition import compose_owner_snapshot


def make_snapshot(tmp_path: Path, *, repository: str = "example/fixture") -> tuple[dict, Path]:
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    store.upsert_capability(identity_key="test:private", name="Private capability",
                            definition="Read-only context", lifecycle="confirmed",
                            existence_provenance="test:private-source")
    result = CkmQueryService(store.db_path).list_capabilities()
    assert isinstance(result, ResultEnvelope)
    return build_private_snapshot(result, repository=repository,
                                  captured_at=datetime.now(timezone.utc)), store.db_path


def _resign(value: dict) -> bytes:
    value = deepcopy(value)
    value["content_sha256"] = "sha256:" + canonical_digest({
        key: item for key, item in value.items() if key != "content_sha256"
    })
    return canonical_json(value).encode()


def test_real_ckm_query_round_trip_is_read_only(tmp_path: Path) -> None:
    value, db = make_snapshot(tmp_path)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    current = CkmQueryService(db).list_capabilities()
    raw = canonical_json(value).encode()
    decoded = decode_private_snapshot(raw, repository="example/fixture")
    assert isinstance(decoded.result, ResultEnvelope)
    assert isinstance(current, ResultEnvelope)
    assert decoded.result.to_dict() == current.to_dict() == value["result"]
    assert decoded.result.snapshot.effective_audience == "single_operator_local"
    assert decoded.transfer["scope"] == "captured_local_query_not_live_remote_query"
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("case", [
    "policy", "repository", "target", "partial", "digest", "resource", "stale", "future",
    "oversized", "symlink", "replaced", "same-bytes-replaced", "symlink-race",
    "duplicate-key", "unknown-field", "authoritative",
])
def test_managed_snapshot_refuses_invalid_or_stale_source(tmp_path: Path, monkeypatch, case: str) -> None:
    value, _ = make_snapshot(tmp_path)
    path = tmp_path / FILENAME
    raw = canonical_json(value).encode()
    if case in {"policy", "repository", "target", "unknown-field"}:
        value[{"target": "target_host", "unknown-field": "unexpected"}.get(case, case)] = "foreign"
        raw = _resign(value)
    elif case == "partial":
        value["result"]["snapshot"]["completeness"]["complete"] = False
        raw = _resign(value)
    elif case == "digest":
        value["content_sha256"] = "sha256:" + "0" * 64
        raw = canonical_json(value).encode()
    elif case == "resource":
        value["result"]["resources"] = []
        raw = _resign(value)
    elif case == "authoritative":
        value["result"]["projection"] = {"status": "authoritative", "authoritative": True}
        raw = _resign(value)
    elif case in {"stale", "future"}:
        delta = timedelta(days=-2 if case == "stale" else 2)
        value["captured_at"] = (datetime.now(timezone.utc) + delta).isoformat()
        raw = _resign(value)
    elif case == "oversized":
        raw = b" " * (MAX_BYTES + 1)
    elif case == "duplicate-key":
        raw = raw.replace(b'"contract":', b'"contract":"duplicate","contract":', 1)
    path.write_bytes(raw)
    if case == "symlink":
        target = tmp_path / "snapshot-target.json"
        path.rename(target)
        path.symlink_to(target)
    elif case in {"replaced", "same-bytes-replaced", "symlink-race"}:
        from app.builderops import devui_ckm_snapshot
        original = devui_ckm_snapshot.decode_private_snapshot

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if case == "replaced":
                path.write_bytes(raw + b" ")
            elif case == "same-bytes-replaced":
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(raw)
                replacement.replace(path)
            else:
                target = tmp_path / "link-target.json"
                target.write_bytes(raw)
                path.unlink()
                path.symlink_to(target)
            return result

        monkeypatch.setattr(devui_ckm_snapshot, "decode_private_snapshot", changed)
    result = read_private_ckm(tmp_path, repository="example/fixture")
    assert isinstance(result.result, ErrorEnvelope)
    assert result.transfer is None
    assert result.result.error.code.startswith("private_snapshot_")


def test_snapshot_failure_preserves_independent_sources(tmp_path: Path) -> None:
    from app.builderops.devui_receipts import read_vm102_receipt_provider
    from tests.builderops.test_devui_receipts import _write_chain

    captured = datetime.now(timezone.utc)
    stamp = captured.isoformat()
    _write_chain(tmp_path, observed_at=stamp)
    cockpit = {
        "authority": "read_time_join", "generated_at": stamp,
        "claim": {"kind": "counted", "text": "One observed thread", "as_of": stamp},
        "sources": [{"name": "github-live", "state": "fresh", "last_successful_read": stamp, "detail": "read succeeded", "stale_after_days": 7, "configured": True}],
        "unread_planes": [], "withdrawn_counts": [], "bands": {"working": []},
    }
    cockpit["sources"].append({**cockpit["sources"][0], "name": "dispatcher-store"})
    for raw in (None, b"{", b"[]"):
        if raw is not None:
            (tmp_path / FILENAME).write_bytes(raw)
        read = read_private_ckm(tmp_path, repository="example/fixture")
        composed = compose_owner_snapshot(
            cockpit_reader=lambda: cockpit, ckm_reader=lambda: read.result,
            receipt_reader=lambda: read_vm102_receipt_provider(tmp_path, now=captured),
        )
        assert composed["providers"]["work"]["status"] == "available"
        assert composed["providers"]["work"]["snapshot"]["sources"][0]["state"] == "fresh"
        assert composed["providers"]["vm102_evidence"]["status"] == "available"
        assert composed["providers"]["capabilities"]["status"] == "refused"
