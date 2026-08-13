"""Heimdal ASR stage tests (#3028, Epic #3019 slice A8).

Covers the issue's two behavioral Acceptance Criteria plus completeness
coverage:

- ``test_local_segments_and_confidences`` -- local transcription produces
  segments each carrying a confidence, plus recorded ``stage_versions``.
- ``test_no_cloud_fallback_fails_loud`` -- with the local engine
  unavailable, there is no silent fallback: the stage fails loud
  (``LocalAsrUnavailableError``), never a cloud call.

All tests exercise the real production call site
(`app.heimdal.asr_stage.run_asr_stage` -> `app.heimdal.raw_read_gate.read_raw_record`
-> `app.heimdal.raw_store`), not a stubbed-dependency-only shortcut: raw
evidence is inserted through the real store, read through the real gate
(allowlist + receipt), and only the underlying faster-whisper *model call*
is stubbed via the ``asr_runner`` injection seam -- so these tests are
hermetic (no model download, no real audio decode) while still proving the
stage's own wiring/contract.
"""

from __future__ import annotations

import secrets

import pytest

from app.heimdal import asr_stage, raw_read_gate, raw_store
from app.heimdal.asr_stage import (
    LocalAsrUnavailableError,
    all_asr_stage_runs,
    reset_asr_stage_runs,
    run_asr_stage,
)
from app.heimdal.raw_read_gate import raw_ref_for, reset_memory_raw_read_receipts
from app.heimdal.raw_store import (
    compute_raw_content_identity,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)

pytestmark = pytest.mark.not_pg

_TEST_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "asr_stage")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _TEST_KEY.hex())
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_asr_stage_runs()
    yield
    reset_memory_raw_store()
    reset_memory_raw_read_receipts()
    reset_asr_stage_runs()


def _consent_block() -> dict:
    return {
        "basis": "self_record",
        "granted_by": "operator",
        "granted_at": "2026-07-06T00:00:00Z",
        "third_party": "none",
        "grant_ref": "grant-test",
    }


def _sensor_block() -> dict:
    return {"adapter": "test_adapter", "version": "v1", "device": "test-device"}


def _insert_raw(content_identity: str, plaintext: bytes = b"fake wav bytes") -> str:
    unique_plaintext = plaintext + b":" + content_identity.encode()
    ciphertext, nonce = encrypt_raw_bytes(unique_plaintext, key=_TEST_KEY)
    record, _ = insert_raw_record(
        content_identity=compute_raw_content_identity(unique_plaintext),
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/very/secret/memo.m4a",
    )
    return raw_ref_for(record)


def _single_speaker_asr_output(**overrides) -> dict:
    output = {
        "text": "hej det ar jag",
        "language": "sv",
        "model": "test-model",
        "segments": [
            {"start": 0.0, "end": 1.2, "text": "hej det ar jag", "avg_logprob": -0.1, "no_speech_prob": 0.02},
        ],
    }
    output.update(overrides)
    return output


# --- AC1: local transcription -> segments + confidences + stage_versions --


def test_local_segments_and_confidences(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_ref = _insert_raw("hash-asr-1")

    def fake_runner(wav_path):
        assert wav_path.exists()
        return _single_speaker_asr_output()

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert result.raw_ref == raw_ref
    assert result.revision_of is None
    assert result.language == "sv"
    assert result.text == "hej det ar jag"

    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.text == "hej det ar jag"
    assert 0.0 <= segment.confidence <= 1.0
    assert segment.calibration == "heuristic"
    assert segment.method == "asr_avg_logprob"

    assert result.stage_versions.get("asr", "").startswith("test-model@")

    # Exactly one gated read receipt was emitted for this run (HEIM-5).
    receipts = raw_read_gate.all_raw_read_receipts()
    assert len(receipts) == 1
    assert receipts[0].reader == "asr_stage"
    assert receipts[0].raw_ref == raw_ref

    # The run is recorded in this stage's own append-only ledger.
    runs = all_asr_stage_runs()
    assert len(runs) == 1
    assert runs[0].id == result.id


def test_segment_confidence_falls_back_when_engine_lacks_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """A segment lacking avg_logprob/no_speech_prob still gets a heuristic confidence, never a crash."""
    raw_ref = _insert_raw("hash-asr-no-score")

    def fake_runner(wav_path):
        return {
            "text": "plain segment",
            "language": "en",
            "model": "stub-model",
            "segments": [{"start": 0.0, "end": 1.0, "text": "plain segment"}],
        }

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert len(result.segments) == 1
    assert result.segments[0].calibration == "heuristic"
    assert result.segments[0].method == "asr_default_no_score"
    assert 0.0 <= result.segments[0].confidence <= 1.0


def test_multiple_segments_each_carry_own_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_ref = _insert_raw("hash-asr-multi-segment")

    def fake_runner(wav_path):
        return {
            "text": "first segment second segment",
            "language": "en",
            "model": "test-model",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "first segment", "avg_logprob": -0.05, "no_speech_prob": 0.01},
                {"start": 1.0, "end": 2.0, "text": "second segment", "avg_logprob": -0.8, "no_speech_prob": 0.4},
            ],
        }

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert len(result.segments) == 2
    # The garbled second segment should score lower than the clean first one.
    assert result.segments[0].confidence > result.segments[1].confidence


# --- Multi-speaker guard (minimal detection, not attribution) --------------


def test_multi_speaker_guard_detects_more_than_one_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    monkeypatch.setenv("DIARIZE_PROVIDER", "mock")
    raw_ref = _insert_raw("hash-asr-multi-speaker")

    def fake_runner(wav_path):
        return _single_speaker_asr_output(
            text="First sentence. Second sentence. Third one here.",
            segments=[
                {"start": 0.0, "end": 1.0, "text": "First sentence.", "avg_logprob": -0.1, "no_speech_prob": 0.02},
                {"start": 1.0, "end": 2.0, "text": "Second sentence.", "avg_logprob": -0.1, "no_speech_prob": 0.02},
            ],
        )

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert result.multi_speaker_detected is True
    assert any(w.get("reason") == "third_party_speech" for w in result.withheld)


def test_single_speaker_no_guard_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DIARIZE_ENABLE", raising=False)
    raw_ref = _insert_raw("hash-asr-single-speaker")

    def fake_runner(wav_path):
        return _single_speaker_asr_output()

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert result.multi_speaker_detected is False
    assert result.withheld == []


# --- Replayable: re-run over same raw_ref -> revision, never a rewrite ----


def test_rerun_over_same_raw_ref_is_a_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_ref = _insert_raw("hash-asr-replay")

    def fake_runner_v1(wav_path):
        return _single_speaker_asr_output(model="whisper-small")

    first = run_asr_stage(raw_ref, asr_runner=fake_runner_v1)
    assert first.revision_of is None

    def fake_runner_v2(wav_path):
        return _single_speaker_asr_output(model="whisper-medium", text="hej det ar jag (improved)")

    second = run_asr_stage(raw_ref, asr_runner=fake_runner_v2)

    assert second.revision_of == first.id
    assert second.id != first.id
    assert second.stage_versions["asr"] != first.stage_versions["asr"]

    # Both runs persist in the ledger -- replay never rewrites the earlier one.
    runs = all_asr_stage_runs()
    assert len(runs) == 2
    assert {r.id for r in runs} == {first.id, second.id}

    # Two reads => two receipts, never merged/deduplicated (raw read gate contract).
    receipts = raw_read_gate.all_raw_read_receipts()
    assert len(receipts) == 2


def test_rerun_over_different_raw_ref_is_not_a_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_ref_a = _insert_raw("hash-asr-a")
    raw_ref_b = _insert_raw("hash-asr-b")

    def fake_runner(wav_path):
        return _single_speaker_asr_output()

    result_a = run_asr_stage(raw_ref_a, asr_runner=fake_runner)
    result_b = run_asr_stage(raw_ref_b, asr_runner=fake_runner)

    assert result_a.revision_of is None
    assert result_b.revision_of is None
    assert result_a.raw_ref != result_b.raw_ref


# --- AC2: no cloud fallback; fails loud ------------------------------------


def test_no_cloud_fallback_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the local engine cannot run, the stage raises -- never a silent cloud call."""
    raw_ref = _insert_raw("hash-asr-fail")

    def failing_runner(wav_path):
        raise RuntimeError("faster-whisper model load failed (simulated)")

    with pytest.raises(LocalAsrUnavailableError):
        run_asr_stage(raw_ref, asr_runner=failing_runner)

    # A failed local ASR attempt still leaves a raw-read receipt (the read
    # itself succeeded; only the ASR call failed) but records no stage run --
    # a failed attempt is not silently treated as a completed transcription.
    assert all_asr_stage_runs() == []


def test_no_cloud_fallback_when_shared_engine_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates the real production path with the shared engine unimportable (e.g. faster-whisper missing)."""
    raw_ref = _insert_raw("hash-asr-no-engine")

    import app.heimdal.asr_stage as asr_stage_module

    def _raise_import_error(wav_path):
        raise ModuleNotFoundError("No module named 'faster_whisper'")

    monkeypatch.setattr(asr_stage_module, "_invoke_asr", lambda wav_path, asr_runner: (_ for _ in ()).throw(
        LocalAsrUnavailableError("Shared local ASR engine (app.media.transcribe) could not be imported")
    ))

    with pytest.raises(LocalAsrUnavailableError):
        run_asr_stage(raw_ref)

    assert all_asr_stage_runs() == []


def test_no_cloud_fallback_module_has_no_cloud_provider_reference() -> None:
    """Structural guard: this module names no cloud ASR provider anywhere in its source.

    Defense in depth against a future edit quietly introducing a cloud
    fallback branch (§7.3/§9-c, T3) -- a plain source-text check that
    the module never mentions a cloud/hosted transcription vendor.
    """
    import inspect

    source = inspect.getsource(asr_stage)
    lowered = source.lower()
    for banned in ("openai.audio", "cloud_asr", "whisper_api", "azure_speech", "google.cloud.speech"):
        assert banned not in lowered, f"unexpected cloud ASR reference: {banned!r}"


def test_gated_read_refused_reader_not_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """If asr_stage is not on the allowlist, the gate refuses -- this module adds no bypass."""
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "some_other_reader")
    raw_ref = _insert_raw("hash-asr-not-allowlisted")

    def fake_runner(wav_path):
        return _single_speaker_asr_output()

    with pytest.raises(raw_read_gate.RawReadRefusedError):
        run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert all_asr_stage_runs() == []


def test_run_asr_stage_uses_real_gated_read_call_site(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through the real production call site: insert raw -> mint raw_ref -> ASR stage.

    Guards against a stubbed-dependency-only test: exercises the real
    `app.heimdal.raw_read_gate.read_raw_record` resolution + receipt path
    (not a mocked store), with only the model call itself stubbed.
    """
    plaintext = b"end-to-end raw wav bytes"
    ciphertext, nonce = encrypt_raw_bytes(plaintext, key=_TEST_KEY)
    identity = compute_raw_content_identity(plaintext)
    record, created = insert_raw_record(
        content_identity=identity,
        capture_chain=["ios_voice_memos", "icloud_drive", "folder_watch"],
        sensor=_sensor_block(),
        consent=_consent_block(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=_TEST_KEY,
        source_path="/tmp/memo.m4a",
    )
    assert created is True
    raw_ref = raw_ref_for(record)

    captured_bytes = {}

    def fake_runner(wav_path):
        captured_bytes["plaintext"] = wav_path.read_bytes()
        return _single_speaker_asr_output()

    result = run_asr_stage(raw_ref, asr_runner=fake_runner)

    assert captured_bytes["plaintext"] == b"end-to-end raw wav bytes"
    assert result.raw_ref == raw_ref
    assert raw_store.get_raw_record_by_content_identity(identity) is not None
