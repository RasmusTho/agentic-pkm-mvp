"""Voice-memo capture adapter -- the Heimdal *watch* seam (#3025, Epic #3019 slice A6).

Covers the issue's two behavioral Acceptance Criteria:

- ``test_admits_only_under_grant`` -- grant active => admitted; no grant =>
  refused, via the real ledger call (`admit_raw_evidence`), no bypass.
- ``test_deletes_after_confirmed_ingest`` -- source deleted ONLY after
  durable persistence; if persistence fails, the source is retained and the
  failure is loud (raised + logged), never silent.

Plus negative/completeness coverage: unregistered sensor refusal (T5),
idempotent re-admission by content_identity, watch-cycle isolation (one bad
file does not starve the rest of the queue), and encryption-at-rest (the
store never sees plaintext).

Default (``not pg``) tests drive the real production call site
(`app.heimdal.capture_adapter.admit_capture_file` / `run_watch_cycle`)
against the memory-backed raw store and the memory-backed consent ledger --
both real production code paths, not a stub of either.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pytest

from app.heimdal import capture_adapter, raw_store
from app.heimdal.capture_adapter import (
    CAPTURE_CHAIN_V1,
    CaptureAdmissionError,
    CaptureFileNotStableError,
    SensorIdentity,
    UnregisteredSensorError,
    admit_capture_file,
    compute_content_identity,
    is_admissible_capture_file,
    list_candidate_files,
    register_sensor,
    run_watch_cycle,
)
from app.heimdal.consent_ledger import (
    SELF_RECORD_GRANT_REF,
    ConsentRefusedError,
    reset_memory_consent_ledger,
    revoke_consent,
)
from app.heimdal.raw_store import (
    all_raw_records,
    get_raw_record_by_content_identity,
    reset_memory_raw_store,
)

pytestmark = pytest.mark.not_pg

_TEST_KEY = bytes.fromhex(secrets.token_hex(32))
_UNGRANTED_SCOPE = "device+adapter:no-such-scope"


@pytest.fixture(autouse=True)
def _reset_heimdal_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    # #3112's still-downloading guard defaults to a real 0.5s sleep in
    # production; zero it out here so the ~15 existing admit_capture_file/
    # run_watch_cycle call sites in this file (which don't care about the
    # guard) don't each pay that cost. Tests that DO exercise the guard
    # pass an explicit stability_delay.
    monkeypatch.setattr(capture_adapter, "_STABILITY_CHECK_DELAY_SECONDS", 0.0)
    reset_memory_consent_ledger()
    reset_memory_raw_store()
    yield
    reset_memory_consent_ledger()
    reset_memory_raw_store()


def _write_memo(tmp_path: Path, name: str = "memo.m4a", content: bytes = b"fake audio bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _write_sidecar(memo: Path, payload: object) -> Path:
    sidecar = memo.with_name(f"{memo.name}.capture.json")
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return sidecar


# --- AC1: admitted only under an active grant -----------------------------


def test_admits_only_under_grant(tmp_path: Path) -> None:
    """Grant active (standing self_record grant) -> file is admitted and durably persisted."""
    memo = _write_memo(tmp_path)
    content_identity = compute_content_identity(memo.read_bytes())

    result = admit_capture_file(memo, key=_TEST_KEY)

    assert result.created is True
    assert result.record.content_identity == content_identity
    assert result.record.capture_chain == CAPTURE_CHAIN_V1
    assert result.record.consent["grant_ref"] == SELF_RECORD_GRANT_REF
    assert result.record.sensor["adapter"] == capture_adapter.ADAPTER_ID

    stored = get_raw_record_by_content_identity(content_identity)
    assert stored is not None
    assert stored.id == result.record.id


def test_refused_without_active_grant(tmp_path: Path) -> None:
    """No active grant for the scope -> refused loudly via the real ledger call, no bypass.

    Revokes the standing self_record grant for a scope this test controls,
    then drives `admit_capture_file` (the real production capture call
    site) directly -- proving refusal happens through
    `app.heimdal.consent_ledger.admit_raw_evidence`, not a local reimplementation.
    """
    memo = _write_memo(tmp_path)

    with pytest.raises(ConsentRefusedError) as excinfo:
        admit_capture_file(memo, scope=_UNGRANTED_SCOPE, key=_TEST_KEY)

    assert "HEIM-3" in str(excinfo.value)
    # Refused: source file is left in place, nothing was written to the raw store.
    assert memo.exists()
    assert all_raw_records() == []


def test_refused_after_revocation(tmp_path: Path) -> None:
    """A grant that is later revoked no longer admits capture (ledger re-checked every call)."""
    memo = _write_memo(tmp_path)
    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="operator")

    with pytest.raises(ConsentRefusedError):
        admit_capture_file(memo, key=_TEST_KEY)

    assert memo.exists()
    assert all_raw_records() == []


# --- AC2: delete-after-confirmed-ingest -----------------------------------


def test_deletes_after_confirmed_ingest(tmp_path: Path) -> None:
    """Source file is deleted ONLY after the raw record is durably persisted."""
    memo = _write_memo(tmp_path)
    assert memo.exists()

    result = admit_capture_file(memo, key=_TEST_KEY)

    assert result.source_deleted is True
    assert not memo.exists()
    # The durable record survives independently of the (now-deleted) source file.
    assert get_raw_record_by_content_identity(result.record.content_identity) is not None


def test_source_retained_when_persistence_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the durable write fails, the source file is retained (never deleted) and the failure is loud."""
    memo = _write_memo(tmp_path)

    def _boom(**kwargs):
        raise RuntimeError("simulated store outage")

    monkeypatch.setattr(raw_store, "insert_raw_record", _boom)

    with pytest.raises(CaptureAdmissionError) as excinfo:
        admit_capture_file(memo, key=_TEST_KEY)

    assert "simulated store outage" in str(excinfo.value)
    # Fail loud, fail safe: the memo is still on disk, still queued for retry.
    assert memo.exists()


# --- HCAP-07: optional capture-time metadata sidecars --------------------


def test_sidecar_consumed_into_raw_metadata(tmp_path: Path) -> None:
    """A valid sidecar lands atomically with raw evidence and is then deleted."""
    memo = _write_memo(tmp_path)
    sidecar_metadata = {
        "sidecar_version": 1,
        "device_id": "fixture-device-001",
        "recorded_start_at": "2026-07-07T14:02:11+02:00",
        "recorded_end_at": "2026-07-07T14:09:40+02:00",
        "timezone": "Europe/Stockholm",
        "interruptions": 1,
        "source_surface": "watch-relay",
        "location": {"lat": 59.3293, "lon": 18.0686, "precision_m": 100},
        "producer_private_field": "ignored by the hub",
    }
    sidecar = _write_sidecar(memo, sidecar_metadata)

    result = admit_capture_file(memo, key=_TEST_KEY)

    assert result.record.payload["capture_time_metadata"] == {
        key: value for key, value in sidecar_metadata.items() if key != "producer_private_field"
    }
    assert not memo.exists()
    assert not sidecar.exists()


def test_admission_unaffected_by_missing_or_malformed_sidecar(tmp_path: Path) -> None:
    """Missing and malformed sidecars are ignored, never an audio-admission failure."""
    missing = _write_memo(tmp_path, name="missing.m4a", content=b"missing sidecar")
    malformed = _write_memo(tmp_path, name="malformed.m4a", content=b"malformed sidecar")
    malformed_sidecar = malformed.with_name(f"{malformed.name}.capture.json")
    malformed_sidecar.write_text('{"sidecar_version": 999}', encoding="utf-8")

    missing_result = admit_capture_file(missing, key=_TEST_KEY)
    malformed_result = admit_capture_file(malformed, key=_TEST_KEY)

    assert missing_result.record.payload == {}
    assert malformed_result.record.payload == {}
    assert not missing.exists()
    assert not malformed.exists()
    # Invalid context is retained for diagnosis/recovery; it is never
    # destructively consumed merely because its sibling audio was admitted.
    assert malformed_sidecar.exists()


def test_sidecar_extension_not_admissible(tmp_path: Path) -> None:
    """The sidecar is metadata, not an independent audio capture candidate."""
    memo = _write_memo(tmp_path)
    sidecar = _write_sidecar(memo, {"sidecar_version": 1})

    assert not is_admissible_capture_file(sidecar)
    assert list_candidate_files(tmp_path) == [memo]


def test_valid_sidecar_is_retained_when_raw_persistence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sidecar deletion follows the same confirmed-write custody boundary as audio."""
    memo = _write_memo(tmp_path)
    sidecar = _write_sidecar(memo, {"sidecar_version": 1, "device_id": "fixture-device-001"})

    def _boom(**kwargs):
        raise RuntimeError("simulated store outage")

    monkeypatch.setattr(raw_store, "insert_raw_record", _boom)

    with pytest.raises(CaptureAdmissionError):
        admit_capture_file(memo, key=_TEST_KEY)

    assert memo.exists()
    assert sidecar.exists()


def test_retry_after_transient_failure_still_deletes_once_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capture that fails once and is retried succeeds and deletes on the second attempt."""
    memo = _write_memo(tmp_path)
    real_insert = raw_store.insert_raw_record
    calls = {"count": 0}

    def _flaky(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated transient outage")
        return real_insert(**kwargs)

    monkeypatch.setattr(raw_store, "insert_raw_record", _flaky)

    with pytest.raises(CaptureAdmissionError):
        admit_capture_file(memo, key=_TEST_KEY)
    assert memo.exists()

    # Restore only the patched function (not the whole monkeypatch context,
    # which would also revert the autouse STORE_BACKEND=memory env fixture).
    monkeypatch.setattr(raw_store, "insert_raw_record", real_insert)
    # Real retry: same file, same bytes -> same content_identity -> idempotent insert.
    result = admit_capture_file(memo, key=_TEST_KEY)
    assert result.source_deleted is True
    assert not memo.exists()


# --- #3112: still-downloading (truncated) file guard ----------------------


class _FakeStat:
    """Wraps a real ``os.stat_result``, overriding only ``st_size``.

    ``Path.is_file()`` (used by `list_candidate_files`, which runs before
    the stability check) also calls `.stat()` and needs a real ``st_mode``
    -- delegating everything but the faked field keeps that working.
    """

    def __init__(self, real: os.stat_result, st_size: int) -> None:
        self._real = real
        self.st_size = st_size

    def __getattr__(self, name: str):
        return getattr(self._real, name)


def test_refuses_still_growing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file whose size changes between the two stability reads is refused, not admitted (#3112).

    Deterministically simulates a mid-download file: the second `stat()`
    call for this path reports a different size than the first, exactly
    what a real size check would observe mid-write -- without a real
    sleep/thread (flaky-timing-free).
    """
    memo = _write_memo(tmp_path, content=b"partial-bytes")
    real_stat = Path.stat
    sizes = iter([7, 999])

    def _fake_stat(self: Path, *args, **kwargs):
        if self == memo:
            return _FakeStat(real_stat(self, *args, **kwargs), next(sizes, 999))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fake_stat)

    with pytest.raises(CaptureFileNotStableError) as excinfo:
        admit_capture_file(memo, key=_TEST_KEY, stability_delay=0.0)

    assert "still changing size" in str(excinfo.value)
    # Refused: source left in place (not read as truncated, not deleted), nothing durably written.
    assert memo.exists()
    assert all_raw_records() == []


def test_admits_stable_file_with_nonzero_delay(tmp_path: Path) -> None:
    """A file whose size is unchanged across the check is admitted normally, delay path exercised."""
    memo = _write_memo(tmp_path)

    result = admit_capture_file(memo, key=_TEST_KEY, stability_delay=0.01)

    assert result.created is True
    assert not memo.exists()


def test_run_watch_cycle_refuses_growing_file_and_retains_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A still-downloading file is refused-and-retained by the cycle that catches it (#3112).

    It is never admitted-then-deleted as truncated garbage: `refused` records
    the specific `CaptureFileNotStableError`, and the source file remains on
    disk for a later tick (the poller in `app.heimdal.capture_runtime`
    retries automatically) once the sync client finishes.
    """
    memo = _write_memo(tmp_path, content=b"partial-bytes")
    real_stat = Path.stat
    # 3 sizes, not 2: run_watch_cycle -> list_candidate_files -> is_file() makes
    # one stat() call before admit_capture_file's own two-read stability check
    # runs, so the *last two* reads (the ones the check actually compares) must
    # differ -- 7 (list scan) -> 50 -> 999 (stability check sees 50 != 999).
    sizes = iter([7, 50, 999])

    def _fake_stat(self: Path, *args, **kwargs):
        if self == memo:
            return _FakeStat(real_stat(self, *args, **kwargs), next(sizes, 999))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fake_stat)

    result = run_watch_cycle(tmp_path, key=_TEST_KEY, stability_delay=0.0)

    assert result.admitted == []
    assert len(result.refused) == 1
    assert result.refused[0][0] == memo
    assert isinstance(result.refused[0][1], CaptureFileNotStableError)
    assert memo.exists()
    assert all_raw_records() == []


# --- T5 mitigation: unregistered sensor refusal ---------------------------


def test_unregistered_sensor_refused(tmp_path: Path) -> None:
    memo = _write_memo(tmp_path)
    unregistered = SensorIdentity(adapter="rogue_adapter", version="v0", device="unknown")

    with pytest.raises(UnregisteredSensorError):
        admit_capture_file(memo, sensor=unregistered, key=_TEST_KEY)

    assert memo.exists()
    assert all_raw_records() == []


def test_register_sensor_allows_new_identity(tmp_path: Path) -> None:
    memo = _write_memo(tmp_path)
    new_sensor = SensorIdentity(adapter="second_device_adapter", version="v1", device="test-device")
    register_sensor(new_sensor.adapter, new_sensor.version)

    result = admit_capture_file(memo, sensor=new_sensor, key=_TEST_KEY)

    assert result.record.sensor["adapter"] == "second_device_adapter"


# --- Idempotency: duplicate content_identity does not double-admit -------


def test_duplicate_content_identity_is_idempotent(tmp_path: Path) -> None:
    memo_a = _write_memo(tmp_path, name="a.m4a", content=b"identical bytes")
    memo_b = _write_memo(tmp_path, name="b.m4a", content=b"identical bytes")

    result_a = admit_capture_file(memo_a, key=_TEST_KEY)
    result_b = admit_capture_file(memo_b, key=_TEST_KEY)

    assert result_a.created is True
    assert result_b.created is False
    assert result_a.record.id == result_b.record.id
    assert len(all_raw_records()) == 1
    # Both source files are still deleted -- each memo's own copy is redundant
    # once the (shared) content is durably persisted.
    assert not memo_a.exists()
    assert not memo_b.exists()


# --- Encryption at rest: plaintext never reaches the store ----------------


def test_raw_bytes_are_encrypted_at_rest(tmp_path: Path) -> None:
    plaintext = b"this is the secret voice memo content"
    memo = _write_memo(tmp_path, content=plaintext)

    result = admit_capture_file(memo, key=_TEST_KEY)

    assert plaintext not in result.record.ciphertext
    decrypted = raw_store.decrypt_raw_bytes(result.record.ciphertext, result.record.nonce, key=_TEST_KEY)
    assert decrypted == plaintext


def test_missing_encryption_key_refuses_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY", raising=False)
    memo = _write_memo(tmp_path)

    with pytest.raises(raw_store.RawStoreKeyMissingError):
        admit_capture_file(memo)  # no key= override, no env var -> must refuse

    assert memo.exists()


# --- Watch-folder scanning + cycle isolation ------------------------------


def test_list_candidate_files_filters_non_audio(tmp_path: Path) -> None:
    _write_memo(tmp_path, name="real.m4a")
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "notes.txt").write_text("not a memo")

    candidates = list_candidate_files(tmp_path)

    assert [p.name for p in candidates] == ["real.m4a"]
    assert is_admissible_capture_file(tmp_path / "real.m4a")
    assert not is_admissible_capture_file(tmp_path / "notes.txt")


def test_list_candidate_files_empty_when_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list_candidate_files(missing) == []


def test_run_watch_cycle_admits_all_and_deletes_sources(tmp_path: Path) -> None:
    _write_memo(tmp_path, name="one.m4a", content=b"memo one")
    _write_memo(tmp_path, name="two.m4a", content=b"memo two")

    outcome = run_watch_cycle(tmp_path, key=_TEST_KEY)

    assert len(outcome.admitted) == 2
    assert outcome.refused == []
    assert list(tmp_path.iterdir()) == []


def test_run_watch_cycle_one_refusal_does_not_starve_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One file's failure (simulated read error) does not block the other admissible files.

    Simulates a per-file failure by making `Path.read_bytes` raise for one
    specific candidate -- a realistic failure mode in a folder-watch cycle
    (e.g. a partially-synced iCloud placeholder) -- and proves the cycle
    still admits every other candidate and records the failure rather than
    aborting the whole scan.
    """
    good = _write_memo(tmp_path, name="good.m4a", content=b"good memo")
    bad = _write_memo(tmp_path, name="bad.m4a", content=b"bad memo")

    real_read_bytes = Path.read_bytes

    def _flaky_read_bytes(self: Path, *args, **kwargs):
        if self.name == "bad.m4a":
            raise OSError("simulated partially-synced file")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _flaky_read_bytes)

    outcome = run_watch_cycle(tmp_path, key=_TEST_KEY)

    assert len(outcome.admitted) == 1
    assert len(outcome.refused) == 1
    assert outcome.refused[0][0] == bad
    assert not good.exists()
    assert bad.exists()  # refused file retained, not silently dropped
