"""Heimdal ASR stage -- local Whisper-class transcription over raw evidence
(#3028, Epic #3019 slice A8).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
:: Decision and specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#7 (ASR
stage: local Whisper-class, segment output + confidences, `stage_versions`,
multi-speaker guard, replayable -- "shared stage implementation with KAP
KA-02", §5.2).

This module is the Heimdal-side wrapper around the existing shared ASR
engine (`app.media.transcribe.run_asr`, faster-whisper) -- per FABLE_COMPANION
§5.2/§9-j/§9-k, the engine is shared library + model cache, invoked
**in-process inside each constituent's own trust boundary**, never a shared
service raw audio is shipped to. This module is Heimdal's in-seam wrapper:
it reads raw bytes only through the A7 gated path
(`app.heimdal.raw_read_gate.read_raw_record`, reader id ``"asr_stage"`` --
this module never resolves a `raw_ref` any other way and never touches
`raw_store` or a filesystem path directly), decodes them to a temp wav file
purely to satisfy `run_asr`'s file-based API, and always deletes that
temp file afterward -- the decrypted plaintext never persists to any
durable store.

Contract this module owns (issue Acceptance Criteria):

- **Segments + confidences (§2).** Each segment carries a `transcription`
  confidence derived from Whisper's `avg_logprob`/`no_speech_prob` when the
  real engine is used (`calibration="heuristic"` -- a Whisper logprob is
  not a calibrated probability, FABLE_COMPANION §2.1), degrading gracefully
  to a fixed heuristic default when a stub/mocked model does not expose
  those fields (still `calibration="heuristic"`, never silently claiming
  `by_construction`/`calibrated`).
- **`stage_versions` for replay lineage (§5.3/§9-k handoff).** Every
  transcription result records `{"asr": "<model>@<engine-version>"}` so a
  later replay with a different model/engine version is legibly a new
  stage version, not a duplicate.
- **Multi-speaker guard (minimal detection, v1).** This stage does not
  diarize (v2, richer detection is out of scope per the issue) -- it only
  *detects* more than one apparent speaker (via the existing
  `app.diarization.hook.apply_diarization` opt-in hook) and marks the
  result `multi_speaker_detected=True` plus a `withheld`-shaped note, so a
  downstream stage/consumer knows to apply degradation. It never guesses
  who spoke what beyond that hook's own output.
- **Replayable, never a rewrite (HEIM-1/HEIM-14).** Re-running this stage
  over the *same* `raw_ref` returns a `TranscriptResult` whose
  `revision_of` names the prior stage-run id for that `raw_ref` --
  demonstrated at this stage's own append-only run ledger
  (`all_asr_stage_runs`), independent of and prior to A10's durable
  publish path (which will fold `revision_of` into the published event).
  There is deliberately no update/delete API on that ledger.
- **Local ASR only; fail loud, never a silent cloud fallback (§7.3/§9-c,
  T3).** This module never dispatches to a cloud ASR provider. If the
  local engine is unavailable (`faster-whisper` missing) or otherwise
  raises, :func:`run_asr_stage` re-raises via :class:`LocalAsrUnavailableError`
  -- the caller (a real capture pipeline) leaves the memo queued and
  surfaces the failure to the operator, exactly per §9-c Option 1. Cloud
  ASR is not merely unconfigured here -- there is no cloud code path in
  this module at all to silently fall into.

Out of scope for this slice (per governing Issue #3028): attribution /
entity-mention resolution (A9); assembling and publishing the
`heimdal.observation.published.v1` event (A10, which will consume this
stage's `TranscriptResult` and fold its `stage_versions` + segments into
the payload); richer diarization-based third-party attribution (v2);
cloud ASR enablement (owner decision, §9-c).
"""

from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.diarization.hook import apply_diarization
from app.heimdal.raw_read_gate import read_raw_record

_READER_ID = "asr_stage"

# Bumped when this wrapper's own segment/confidence-shaping logic changes in
# a way that would produce a materially different transcription for the same
# raw evidence and model -- folded into `stage_versions["asr"]` alongside the
# underlying model name so a replay after a wrapper change is still legible
# as a distinct stage version, not just a model bump.
_ENGINE_VERSION = "heimdal-asr-stage-v1"


class LocalAsrUnavailableError(RuntimeError):
    """Raised when local ASR cannot run.

    Fail-loud (§7.3/§9-c, T3): this is the only failure path this module
    exposes for "ASR could not produce a transcript". There is no cloud
    fallback to degrade into -- a caller catching this must leave the memo
    queued and notify the operator, never retry against a cloud provider
    silently.
    """


@dataclass(frozen=True)
class TranscriptSegment:
    """One ASR segment: timing, text, and its own transcription confidence.

    Confidence is deliberately per-segment (FABLE_COMPANION §2): a single
    memo-level scalar would launder "this one sentence was garbled" into an
    average that hides exactly the span a consumer needs to distrust.
    """

    start: float
    end: float
    text: str
    confidence: float
    calibration: str
    method: str
    speaker_hint: Optional[str] = None


@dataclass(frozen=True)
class TranscriptResult:
    """The ASR stage's output for one gated read of one `raw_ref`.

    Not itself a published Heimdal event (A10 owns assembling and
    publishing `heimdal.observation.published.v1`) -- this is the
    stage-local artifact A10 will consume: segments, per-segment
    confidence, the `stage_versions` fragment this stage contributes, and
    the multi-speaker guard's detection result.
    """

    id: str
    raw_ref: str
    revision_of: Optional[str]
    language: Optional[str]
    text: str
    segments: List[TranscriptSegment]
    stage_versions: Dict[str, str]
    multi_speaker_detected: bool
    withheld: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class _AsrStageRunLedger:
    """In-process append-only record of ASR stage runs, keyed by `raw_ref`.

    Exists solely to make replay-as-revision (HEIM-14) demonstrable at this
    stage's own boundary, ahead of A10's durable publish path: the *first*
    run over a given `raw_ref` has `revision_of=None`; every subsequent run
    over the *same* `raw_ref` is a revision of the immediately prior run.
    Deliberately volatile (test/dev scoped, mirrors every other Heimdal
    memory-backend reset helper) and deliberately exposes no update/delete
    method -- a stage run, once recorded, is never edited.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_raw_ref: Dict[str, List[TranscriptResult]] = {}

    def latest_for(self, raw_ref: str) -> Optional[TranscriptResult]:
        with self._lock:
            rows = self._by_raw_ref.get(raw_ref)
            return rows[-1] if rows else None

    def record(self, result: TranscriptResult) -> None:
        with self._lock:
            self._by_raw_ref.setdefault(result.raw_ref, []).append(result)

    def all_runs(self) -> List[TranscriptResult]:
        with self._lock:
            return [row for rows in self._by_raw_ref.values() for row in rows]

    def clear(self) -> None:
        with self._lock:
            self._by_raw_ref.clear()


_RUN_LEDGER = _AsrStageRunLedger()


def reset_asr_stage_runs() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _RUN_LEDGER.clear()


def all_asr_stage_runs() -> List[TranscriptResult]:
    """Every recorded ASR stage run across all `raw_ref`s (diagnostic/test helper)."""
    return _RUN_LEDGER.all_runs()


def _segment_confidence(raw_segment: Dict[str, Any]) -> tuple[float, str, str]:
    """Derive one segment's `(score, calibration, method)` transcription confidence.

    Prefers the real faster-whisper per-segment `avg_logprob`/`no_speech_prob`
    fields when present (mapped into 0..1, FABLE_COMPANION §2.1: "ASR
    segment scores (Whisper avg-logprob mapped to 0..1, marked heuristic)").
    Falls back to a fixed heuristic default when the underlying engine
    (real or stubbed) does not expose those fields -- still `heuristic`,
    never silently upgraded to `calibrated`/`by_construction` (HEIM-6).
    """
    avg_logprob = raw_segment.get("avg_logprob")
    no_speech_prob = raw_segment.get("no_speech_prob")
    if isinstance(avg_logprob, (int, float)):
        # avg_logprob is typically in roughly [-1, 0] for confident speech;
        # clamp+rescale to 0..1 rather than exposing the raw log-probability.
        score = max(0.0, min(1.0, 1.0 + float(avg_logprob)))
        if isinstance(no_speech_prob, (int, float)):
            score = max(0.0, score * (1.0 - float(no_speech_prob)))
        return score, "heuristic", "asr_avg_logprob"
    return 0.5, "heuristic", "asr_default_no_score"


def _detect_multi_speaker(asr_output: Dict[str, Any]) -> tuple[bool, List[Dict[str, str]]]:
    """Minimal multi-speaker guard (v1): detect, do not attribute (§11#7/#8).

    Richer diarization-based attribution is v2 (issue Out of Scope). This
    reuses the existing opt-in diarization hook
    (`app.diarization.hook.apply_diarization`, `DIARIZE_ENABLE`) purely as a
    *speaker-count* signal: when it is enabled and reports more than one
    distinct speaker label, this stage marks the result
    `multi_speaker_detected=True` and returns the per-segment speaker
    hints (for a downstream consumer to apply degradation) -- it never
    resolves who the second speaker is.
    """
    diarized = apply_diarization(dict(asr_output))
    diarized_segments: List[Dict[str, Any]] = diarized.get("segments") or []
    speakers = {
        str(seg.get("speaker"))
        for seg in diarized_segments
        if isinstance(seg, dict) and seg.get("speaker") is not None
    }
    return (len(speakers) > 1), [
        {"speaker": str(seg.get("speaker", "spk_0")), "text": str(seg.get("text", ""))}
        for seg in diarized_segments
        if isinstance(seg, dict)
    ]


def run_asr_stage(
    raw_ref: str,
    *,
    purpose: str = "transcription",
    key: Optional[bytes] = None,
    asr_runner: Optional[Any] = None,
) -> TranscriptResult:
    """Transcribe the raw evidence behind `raw_ref` -- the real production entrypoint.

    Reads raw bytes **only** through the A7 gated path
    (`read_raw_record(raw_ref, reader="asr_stage", purpose=purpose)`) --
    never `raw_store` directly and never a filesystem path. The gate
    refuses the read loudly (`RawReadRefusedError`) if this reader is not
    on `HEIMDAL_RAW_READ_ALLOWLIST`; that refusal propagates unchanged
    (this module adds no alternate path around it).

    ``asr_runner`` is an injection seam for tests: a callable
    ``(wav_path: Path) -> Dict[str, Any]`` shaped exactly like
    `app.media.transcribe.run_asr`'s return value
    (``{"text", "segments", "language"}``, optionally per-segment
    ``avg_logprob``/``no_speech_prob``). Production callers omit it and get
    the real shared faster-whisper engine
    (`app.media.transcribe.run_asr`) -- this is the "no two whisper
    instances" reuse FABLE_COMPANION §5.2/§9-j/§9-k calls for, not a fresh
    engine. If the real engine cannot run (`faster-whisper` missing, or the
    engine call raises for any other reason), this function raises
    :class:`LocalAsrUnavailableError` -- **there is no cloud fallback code
    path in this module to degrade into** (§7.3/§9-c, T3): the caller must
    leave the memo queued and surface the failure, never retry silently
    against a cloud provider.

    Replayable (HEIM-1/HEIM-14): calling this again with the same
    ``raw_ref`` produces a new :class:`TranscriptResult` whose
    ``revision_of`` names the prior run's id for that `raw_ref` (tracked in
    this module's own append-only run ledger); it never mutates or
    replaces the earlier result.
    """
    gated = read_raw_record(raw_ref, reader=_READER_ID, purpose=purpose, key=key)

    wav_path = _write_temp_wav(gated.plaintext)
    try:
        asr_output = _invoke_asr(wav_path, asr_runner=asr_runner)
    finally:
        try:
            wav_path.unlink()
        except OSError:
            pass

    model_name = str(asr_output.get("model") or _default_model_name())
    stage_versions = {"asr": f"{model_name}@{_ENGINE_VERSION}"}

    multi_speaker_detected, speaker_segments = _detect_multi_speaker(asr_output)

    segments: List[TranscriptSegment] = []
    text_parts: List[str] = []
    raw_segments = asr_output.get("segments") or []
    for idx, raw_segment in enumerate(raw_segments):
        score, calibration, method = _segment_confidence(raw_segment)
        speaker_hint = None
        if multi_speaker_detected and idx < len(speaker_segments):
            speaker_hint = speaker_segments[idx].get("speaker")
        text = str(raw_segment.get("text", "")).strip()
        if text:
            text_parts.append(text)
        segments.append(
            TranscriptSegment(
                start=float(raw_segment.get("start", 0.0)),
                end=float(raw_segment.get("end", 0.0)),
                text=text,
                confidence=score,
                calibration=calibration,
                method=method,
                speaker_hint=speaker_hint,
            )
        )

    withheld: List[Dict[str, Any]] = []
    if multi_speaker_detected:
        withheld.append(
            {
                "reason": "third_party_speech",
                "note": (
                    "multi-speaker guard detected more than one apparent speaker; "
                    "richer diarization-based attribution is v2 -- this stage only "
                    "flags the presence, it does not attribute the second speaker"
                ),
            }
        )

    prior = _RUN_LEDGER.latest_for(raw_ref)
    result = TranscriptResult(
        id=str(uuid4()),
        raw_ref=raw_ref,
        revision_of=prior.id if prior is not None else None,
        language=asr_output.get("language"),
        text=" ".join(text_parts).strip(),
        segments=segments,
        stage_versions=stage_versions,
        multi_speaker_detected=multi_speaker_detected,
        withheld=withheld,
    )
    _RUN_LEDGER.record(result)
    return result


def _default_model_name() -> str:
    import os

    return os.getenv("ASR_MODEL", "base")


def _write_temp_wav(plaintext: bytes) -> Path:
    """Write decrypted raw bytes to a process-temp wav file for the engine call.

    The plaintext never touches a durable store -- this file lives only in
    the OS temp directory and `run_asr_stage` always deletes it (success or
    failure) before returning.
    """
    tmp_dir = Path(tempfile.gettempdir()) / "heimdal_asr_stage"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4()}.wav"
    tmp_path.write_bytes(plaintext)
    return tmp_path


def _invoke_asr(wav_path: Path, *, asr_runner: Optional[Any]) -> Dict[str, Any]:
    """Call the shared local ASR engine; never a cloud provider.

    ``asr_runner`` (test injection) is called directly. The production path
    calls the shared `app.media.transcribe.run_asr` engine (faster-whisper,
    FABLE_COMPANION §5.2/§9-j/§9-k "no two whisper instances") -- any
    failure (missing dependency, model load error, decode error) is
    re-raised as :class:`LocalAsrUnavailableError`; there is no except
    branch anywhere in this module that reaches for a cloud ASR call.
    """
    if asr_runner is not None:
        try:
            return dict(asr_runner(wav_path))
        except Exception as exc:  # pragma: no cover - defensive, mirrors prod branch
            raise LocalAsrUnavailableError(
                f"Local ASR (test runner) failed for {wav_path.name}: {exc}"
            ) from exc

    try:
        from app.media.transcribe import run_asr as _shared_run_asr
    except Exception as exc:
        raise LocalAsrUnavailableError(
            "Shared local ASR engine (app.media.transcribe) could not be imported: "
            f"{exc}. Local ASR only (§7.3/§9-c) -- there is no cloud fallback; the "
            "memo stays queued until local ASR is available."
        ) from exc

    try:
        return _shared_run_asr(wav_path)
    except Exception as exc:
        raise LocalAsrUnavailableError(
            f"Local ASR engine failed for {wav_path.name}: {exc}. Local ASR only "
            "(§7.3/§9-c) -- there is no cloud fallback; the memo stays queued and "
            "the operator must be notified."
        ) from exc


__all__ = [
    "LocalAsrUnavailableError",
    "TranscriptResult",
    "TranscriptSegment",
    "all_asr_stage_runs",
    "reset_asr_stage_runs",
    "run_asr_stage",
]
