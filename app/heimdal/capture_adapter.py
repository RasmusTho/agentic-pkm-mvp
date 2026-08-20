"""Voice-memo capture adapter -- the Heimdal *watch* seam (#3025, Epic #3019 slice A6).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
§1 (Heimdal owns watch -> fetch -> transcribe -> attribute -> publish) and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#5 (voice-memo capture
adapter is `build-now`, "the only component touching the source").

This module watches the iCloud Shortcut folder (discrete capture, posture A
-- FABLE_COMPANION §6, ADR-0049 §3) for new voice-memo files and is the
**only** code path that reads the watched folder or deletes a source file.
Everything downstream (ASR, attribution, publish -- A7 onward) consumes the
raw record this module writes, never the source file directly.

Pipeline for one candidate file, in order:

1. **Sensor registration check (T5 mitigation).** The adapter identity
   (`sensor = {adapter, version, device}`) must be registered
   (:func:`register_sensor` / :func:`is_sensor_registered`) before any file
   is admitted. An unregistered sensor identity refuses ingestion loudly --
   this is a configuration-time guard, not per-file, but it is re-checked
   on every capture attempt so a sensor cannot be silently deregistered out
   from under a running watch loop.
2. **Consent admission (HEIM-3), the one enforcement point.** The adapter
   calls `app.heimdal.consent_ledger.admit_raw_evidence(scope=...)` --
   never its own grant-resolution logic -- so the ledger stays the only
   signal->raw gate. No active grant means :class:`ConsentRefusedError`
   propagates un-caught: the memo is left in the watched folder (not
   deleted, not silently dropped) and the caller/CLI surfaces the refusal
   to the operator. No silent cloud fallback, no alternate admission path.
3. **Read + hash + encrypt.** The file is read once, hashed
   (`content_identity`, sha256 of the raw bytes -- the KAP-compatible join
   key) and encrypted at rest (`app.heimdal.raw_store.encrypt_raw_bytes`,
   AES-256-GCM). Plaintext bytes are never written to any store.
4. **Durable write, provenance stamped in the same call (KERNEL-06).**
   `app.heimdal.raw_store.insert_raw_record` writes ciphertext +
   `content_identity` + `capture_chain` + `sensor` + `consent` in one
   statement -- there is no separate "stamp provenance later" step.
4.5 **Receipt and lease the admission through the shared media seam** (CDLM-01,
   #4384). The generation-bound response lease is the authority for step 5;
   `app.heimdal.media_ingress.record_watched_folder_admission` records the
   durable-acceptance receipt (keyed by the sidecar's `capture_id` when it
   carries one, otherwise by content hash) so a Model-1 file is queryable
   through `GET /api/heimdal/capture/receipts`. A receipt or liveness failure
   leaves the source queued for an idempotent retry.
5. **Delete-after-confirmed-ingest.** The source file is removed **only**
   after step 4 returns successfully (the row is durably persisted, or was
   already durably persisted on a prior crash-retry -- `insert_raw_record`
   is idempotent by `content_identity`, so a retry of a partially-completed
   admission cannot double-write, and the delete is safe to attempt again).
   If the durable write raises, the source file is left in place
   (untouched, still queued) and the exception propagates -- fail loud,
   never a silent drop of the operator's memo.

`capture_chain` for v1 is fixed: `["ios_voice_memos", "icloud_drive",
"folder_watch"]` (FABLE_COMPANION §7.1 -- the pre-seam iCloud transit is a
stated, owner-acknowledged residual; this constant makes it legible on
every record forever).

Out of scope for this slice (per governing Issue #3025): ASR, attribution,
publish (A7+); always-on/ambient adapters; place/session grants; direct
device->host transfer (all v2); a second modality.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.heimdal import raw_store
from app.heimdal.consent_ledger import (
    SELF_RECORD_SCOPE,
    AdmittedEvidence,
    admit_raw_evidence,
)
from app.heimdal.raw_store import RawRecord

logger = logging.getLogger(__name__)

# v1 fixed capture chain (FABLE_COMPANION §1.1 provenance field table / §7.1).
CAPTURE_CHAIN_V1: List[str] = ["ios_voice_memos", "icloud_drive", "folder_watch"]

# Default adapter identity for the v1 voice-memo capture adapter. Callers may
# supply their own `SensorIdentity` (e.g. a different device label) but the
# adapter/version pair is this module's own identity.
ADAPTER_ID = "voice_memo_folder_watch"
ADAPTER_VERSION = "v1"

# Default consent scope this adapter admits under -- mirrors the standing
# self_record grant's scope exactly (app.heimdal.consent_ledger.SELF_RECORD_SCOPE).
DEFAULT_CAPTURE_SCOPE = SELF_RECORD_SCOPE

# Voice-memo file extensions the watch folder is expected to contain
# (iOS Voice Memos exports as .m4a via the Shortcut; a small allowlist keeps
# stray non-audio files -- e.g. .DS_Store -- from being treated as memos).
_ADMISSIBLE_EXTENSIONS = {".m4a", ".wav", ".caf", ".aac"}

# HCAP-07: capture clients may place an optional, versioned context sidecar
# next to an admitted audio file.  The suffix deliberately leaves the audio
# suffix intact (``memo.m4a.capture.json``), so a sidecar never qualifies for
# the audio extension allowlist above.
_CAPTURE_SIDECAR_SUFFIX = ".capture.json"
_CAPTURE_SIDECAR_VERSION = 1
_CAPTURE_SIDECAR_FIELDS = {
    "sidecar_version",
    "device_id",
    "recorded_start_at",
    "recorded_end_at",
    "timezone",
    "interruptions",
    "source_surface",
    "location",
    # CDLM-01 (#4384): an optional client-minted transfer id. When present, the
    # admission receipt is keyed by it instead of the content hash, so a client
    # that also uses the governed ingress lane can query one id across both
    # lanes. Retained here rather than in a second sidecar schema -- the
    # capture-time sidecar composes, it does not fork.
    "capture_id",
}

# How long to wait between the two size reads in the still-downloading guard
# (#3112). iCloud sync of a voice memo (seconds, not minutes) makes a short
# fixed delay sufficient without needing a real completion signal; tests pass
# 0.0 to skip the wait. Not configurable via env -- this is an internal
# implementation detail of admission, not an operator-facing knob.
_STABILITY_CHECK_DELAY_SECONDS = 0.5


class UnregisteredSensorError(RuntimeError):
    """Raised when the capture adapter's sensor identity is not registered (T5 mitigation)."""


class CaptureAdmissionError(RuntimeError):
    """Raised when a candidate file cannot be durably admitted.

    Wraps the underlying cause (consent refusal, store failure, I/O error)
    while making explicit that the source file was left in place -- never
    silently dropped or deleted on a failed admission.
    """


class CaptureFileNotStableError(CaptureAdmissionError):
    """Raised when a candidate file's size changed between two reads (#3112).

    A file still being written by a sync client (e.g. mid-download from
    iCloud) can be read as truncated/corrupt audio; admitting it would
    durably persist garbage and then delete the still-syncing source --
    unrecoverable, since the raw layer is append-only. The candidate is
    left in place and retried on a later watch-cycle tick once the sync
    client finishes.
    """


@dataclass(frozen=True)
class SensorIdentity:
    """The capture adapter's registered identity (T5 mitigation).

    `adapter` + `version` identify the code path; `device` identifies the
    physical capture device (operator-configured, e.g. "iphone-15-rasmus").
    Stamped verbatim into every raw record's `sensor` provenance field.
    """

    adapter: str
    version: str
    device: str

    def as_dict(self) -> Dict[str, str]:
        return {"adapter": self.adapter, "version": self.version, "device": self.device}


# Registered sensor identities (T5 mitigation): only a known adapter id +
# version may admit raw evidence. `device` is per-instance and not part of
# the registration key -- registering the adapter/version once covers every
# device running it. Registration is in-process/module-level for v1 (no
# separate registry table -- FABLE_COMPANION §11#5 does not call for one);
# a future slice may promote this to a durable register if a second sensor
# modality needs cross-process discoverability.
_KNOWN_SENSORS: Dict[tuple[str, str], bool] = {
    (ADAPTER_ID, ADAPTER_VERSION): True,
}


def register_sensor(adapter: str, version: str) -> None:
    """Register a capture-adapter identity as known (T5 mitigation).

    Idempotent. Must be called before :func:`admit_capture_file` will accept
    files captured under this ``(adapter, version)`` pair -- an unregistered
    identity is refused loudly (see :func:`_assert_sensor_registered`).
    """
    _KNOWN_SENSORS[(adapter, version)] = True


def is_sensor_registered(adapter: str, version: str) -> bool:
    return _KNOWN_SENSORS.get((adapter, version), False)


def _assert_sensor_registered(sensor: SensorIdentity) -> None:
    if not is_sensor_registered(sensor.adapter, sensor.version):
        raise UnregisteredSensorError(
            f"Capture refused (T5 mitigation): sensor identity {sensor.as_dict()!r} is not "
            "registered. Call app.heimdal.capture_adapter.register_sensor(adapter, version) "
            "before this adapter may admit raw evidence."
        )


def default_sensor_identity(*, device: Optional[str] = None) -> SensorIdentity:
    """The default v1 sensor identity. ``device`` defaults to $HEIMDAL_CAPTURE_DEVICE or 'unknown'."""
    resolved_device = device or os.environ.get("HEIMDAL_CAPTURE_DEVICE") or "unknown"
    return SensorIdentity(adapter=ADAPTER_ID, version=ADAPTER_VERSION, device=resolved_device)


def compute_content_identity(raw_bytes: bytes) -> str:
    """Hash of the raw evidence (KAP-compatible join key, FABLE_COMPANION §1.1)."""
    return hashlib.sha256(raw_bytes).hexdigest()


def _is_file_stable(path: Path, *, delay: Optional[float] = None) -> bool:
    """Whether ``path``'s size is unchanged across two reads ``delay`` seconds apart (#3112).

    A cheap, sync-client-agnostic guard against admitting a file that is
    still being written (e.g. iCloud mid-download): a growing/shrinking
    size means the bytes we would read are not the final content. Returns
    False (not stable) if the file disappears between reads or cannot be
    stat'd -- treated the same as "not ready yet", not an error, so the
    caller retries on a later tick.

    Residual: a file that finishes writing to a *different* size exactly
    between the two reads would read as stable while still not the final
    content. Inherent to any size-based heuristic without a real completion
    signal from the sync client; acceptable here since a false "stable" is
    retried like any other transient issue only in the sense that no data
    is lost (the source is only deleted after a successful durable write of
    whatever was read) -- but it IS a live gap, not a proof of completeness.

    ``delay=None`` resolves the module's `_STABILITY_CHECK_DELAY_SECONDS` at
    call time (not at def time), so a test's monkeypatch of that constant
    applies even to a direct call of this function, not just through
    :func:`admit_capture_file`.
    """
    resolved_delay = delay if delay is not None else _STABILITY_CHECK_DELAY_SECONDS
    try:
        size_before = path.stat().st_size
    except OSError:
        return False
    if resolved_delay > 0:
        time.sleep(resolved_delay)
    try:
        size_after = path.stat().st_size
    except OSError:
        return False
    return size_before == size_after


def is_admissible_capture_file(path: Path) -> bool:
    """Whether ``path`` looks like a voice-memo capture file (extension allowlist).

    Filters stray non-audio files (`.DS_Store`, partial/in-flight iCloud
    download placeholders such as `.icloud` sentinel files) out of the
    watched folder's candidate set. This is a hygiene filter, not a security
    boundary -- sensor registration + consent admission are the real gates.
    """
    return path.is_file() and path.suffix.lower() in _ADMISSIBLE_EXTENSIONS


def list_candidate_files(watch_dir: Path) -> List[Path]:
    """List admissible candidate files in ``watch_dir``, sorted for deterministic ordering."""
    if not watch_dir.exists():
        return []
    return sorted(p for p in watch_dir.iterdir() if is_admissible_capture_file(p))


def _capture_sidecar_path(audio_path: Path) -> Path:
    """Return the optional HCAP-07 sidecar path for an admitted audio file."""
    return audio_path.with_name(f"{audio_path.name}{_CAPTURE_SIDECAR_SUFFIX}")


def _load_capture_sidecar(audio_path: Path) -> Optional[Dict[str, Any]]:
    """Load a valid capture-time sidecar, retaining invalid input for operator repair.

    Sidecars are additive context, never an admission prerequisite.  A
    missing, unreadable, malformed, or unsupported sidecar is therefore
    logged and ignored; audio admission continues exactly as it did before.
    We only delete a sidecar once the raw-record write has confirmed it was
    consumed, preserving the same custody rule as the audio source.
    """
    sidecar_path = _capture_sidecar_path(audio_path)
    if not sidecar_path.exists():
        logger.info("Heimdal capture adapter: sidecar absent for %s.", audio_path)
        return None

    try:
        parsed = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Heimdal capture adapter: malformed sidecar %s ignored; audio admission continues: %s",
            sidecar_path,
            exc,
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "Heimdal capture adapter: malformed sidecar %s ignored; expected an object.", sidecar_path
        )
        return None

    version = parsed.get("sidecar_version")
    if isinstance(version, bool) or version != _CAPTURE_SIDECAR_VERSION:
        logger.warning(
            "Heimdal capture adapter: unsupported sidecar_version in %s ignored; audio admission continues.",
            sidecar_path,
        )
        return None

    metadata = {key: value for key, value in parsed.items() if key in _CAPTURE_SIDECAR_FIELDS}
    logger.info("Heimdal capture adapter: sidecar loaded for %s.", audio_path)
    return metadata


@dataclass(frozen=True)
class CaptureResult:
    """The outcome of admitting one candidate file."""

    record: RawRecord
    created: bool
    source_deleted: bool


def admit_capture_file(
    path: Path,
    *,
    sensor: Optional[SensorIdentity] = None,
    scope: str = DEFAULT_CAPTURE_SCOPE,
    capture_chain: Optional[List[str]] = None,
    key: Optional[bytes] = None,
    stability_delay: Optional[float] = None,
) -> CaptureResult:
    """Admit one candidate file: consent-gate, encrypt, durably persist, delete-after-ingest.

    This is the real production capture call site -- the pipeline described
    in this module's docstring, steps 1-5. Raises rather than returning a
    falsy/partial result on any failure:

    - :class:`UnregisteredSensorError` if ``sensor`` is not registered (T5).
    - :class:`app.heimdal.consent_ledger.ConsentRefusedError` if no active
      grant covers ``scope`` (HEIM-3) -- propagates un-caught from
      `admit_raw_evidence`, the one sanctioned signal->raw admission call.
    - :class:`CaptureAdmissionError` wrapping any failure in the durable
      write itself.
    - :class:`CaptureFileNotStableError` if the file is still being written
      (e.g. mid-download) -- see :func:`_is_file_stable` (#3112).

    ``stability_delay`` overrides the module's `_STABILITY_CHECK_DELAY_SECONDS`
    for this call (``None`` uses the module default) -- primarily so tests
    can drive the check deterministically without a real sleep.

    In every raised case, ``path`` is left on disk untouched: the source is
    deleted **only** after :func:`app.heimdal.raw_store.insert_raw_record`
    returns successfully (step 5 in the module docstring).
    """
    resolved_sensor = sensor or default_sensor_identity()
    _assert_sensor_registered(resolved_sensor)

    chain = list(capture_chain) if capture_chain is not None else list(CAPTURE_CHAIN_V1)

    # Step 2: consent admission is the FIRST thing that can refuse -- HEIM-3
    # must gate before we ever touch the file's bytes, so a refused capture
    # never reads (and never risks partially processing) the source file.
    admitted: AdmittedEvidence = admit_raw_evidence(scope=scope)

    # Step 2.5 (#3112): refuse a file that is still being written/downloaded
    # rather than reading a truncated snapshot of it. Checked after consent
    # (consent stays the first possible refusal, per the docstring above)
    # but before any bytes are read -- a growing/shrinking file never
    # reaches read_bytes/delete. `stability_delay=None` lets _is_file_stable
    # resolve the module default itself, at call time.
    if not _is_file_stable(path, delay=stability_delay):
        raise CaptureFileNotStableError(
            f"Capture refused: {path} is still changing size (mid-write/mid-download). "
            "Source file left in place; will be retried on a later watch-cycle tick."
        )

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise CaptureAdmissionError(
            f"Capture refused: could not read candidate file {path}: {exc}. "
            "Source file left in place."
        ) from exc

    content_identity = compute_content_identity(raw_bytes)

    # The sidecar is loaded only after the audio bytes are safely available,
    # but before the one durable raw-record write.  Its fields therefore land
    # atomically with the admitted evidence, rather than being stamped later.
    capture_sidecar = _load_capture_sidecar(path)

    encryption_key = key if key is not None else raw_store.resolve_raw_store_key()
    ciphertext, nonce = raw_store.encrypt_raw_bytes(raw_bytes, key=encryption_key)

    try:
        record, created = raw_store.insert_raw_record(
            content_identity=content_identity,
            capture_chain=chain,
            sensor=resolved_sensor.as_dict(),
            consent=admitted.consent.as_dict(),
            ciphertext=ciphertext,
            nonce=nonce,
            key_ref="v1-process-key",
            key=encryption_key,
            source_path=str(path),
            payload={"capture_time_metadata": capture_sidecar} if capture_sidecar is not None else None,
        )
    except Exception as exc:
        # Fail loud: the durable write did not confirm, so the source file
        # MUST remain queued for a future retry. Never delete on a failed
        # write -- that would silently destroy the operator's only copy.
        logger.error(
            "Heimdal capture adapter: durable write failed for %s (content_identity=%s): %s. "
            "Source file retained; memo remains queued.",
            path,
            content_identity,
            exc,
        )
        raise CaptureAdmissionError(
            f"Capture refused: raw record could not be durably persisted for {path}: {exc}. "
            "Source file left in place (not deleted)."
        ) from exc

    # Step 4.5 (CDLM-01, #4384): receipt the admission through the shared media
    # seam so a Model-1 file is queryable via
    # `GET /api/heimdal/capture/receipts` like any governed-lane capture. The
    # import is function-local to break the cycle (`media_ingress` imports this
    # module for the sensor/consent guards it reuses).
    #
    # The returned response-validity lease gates source cleanup. If receipt or
    # exact liveness validation fails, keep the source queued; the already-safe
    # raw row and append-only receipt/event seams make the next attempt
    # idempotent.
    from app.heimdal import media_ingress

    try:
        media_ingress.record_watched_folder_admission(
            record,
            capture_id=(capture_sidecar or {}).get("capture_id"),
            trace_id="",
        )
    except Exception as exc:
        logger.error(
            "Heimdal capture adapter: watched-folder response fence failed for %s "
            "(content_identity=%s): %s. Source file retained for retry.",
            path,
            content_identity,
            exc,
        )
        raise CaptureAdmissionError(
            f"Capture refused: receipt/liveness confirmation failed for {path}: {exc}. "
            "Source file left in place (not deleted)."
        ) from exc

    # Step 5: delete-after-confirmed-ingest. Only reached once insert_raw_record
    # has returned a row (either freshly created or the pre-existing row from
    # a prior crash-retry of the SAME evidence) -- the durable write is
    # confirmed either way, so the source copy is now redundant.
    source_deleted = _delete_source_file(path)
    if capture_sidecar is not None:
        sidecar_path = _capture_sidecar_path(path)
        if _delete_source_file(sidecar_path):
            logger.info("Heimdal capture adapter: sidecar consumed for %s.", path)

    return CaptureResult(record=record, created=created, source_deleted=source_deleted)


def _delete_source_file(path: Path) -> bool:
    """Delete the source file post-confirmed-ingest. Logs (does not raise) on failure.

    A delete failure after a confirmed durable write is not a capture
    failure -- the raw record is already safe -- but it is worth a loud log
    line so an operator notices a stale copy lingering in the watched
    folder (e.g. permissions issue).
    """
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.error(
            "Heimdal capture adapter: raw record for %s was durably persisted but the "
            "source file could not be deleted: %s. Operator should remove it manually.",
            path,
            exc,
        )
        return False


@dataclass(frozen=True)
class WatchCycleResult:
    """Summary of one watch-folder scan pass."""

    admitted: List[CaptureResult]
    refused: List[tuple[Path, Exception]]


def run_watch_cycle(
    watch_dir: Path,
    *,
    sensor: Optional[SensorIdentity] = None,
    scope: str = DEFAULT_CAPTURE_SCOPE,
    key: Optional[bytes] = None,
    stability_delay: Optional[float] = None,
) -> WatchCycleResult:
    """Scan ``watch_dir`` once and attempt to admit every candidate file.

    A single file's failure (consent refusal, unregistered sensor, durable
    write error, still-downloading per #3112) does not abort the cycle --
    it is recorded in ``refused`` and the loop continues to the next
    candidate, so one bad file cannot starve the rest of the queue. Every
    refusal is logged loudly (operator-notified in the sense that it is
    never silent) via the `logging` calls in :func:`admit_capture_file` and
    here. A still-downloading file is simply retried on the next tick --
    the poller (`app.heimdal.capture_runtime`) calls this repeatedly, so no
    special-casing is needed here beyond leaving it in ``refused``.
    """
    admitted: List[CaptureResult] = []
    refused: List[tuple[Path, Exception]] = []
    for candidate in list_candidate_files(watch_dir):
        try:
            result = admit_capture_file(
                candidate, sensor=sensor, scope=scope, key=key, stability_delay=stability_delay
            )
            admitted.append(result)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: one bad file must not abort the cycle
            logger.error(
                "Heimdal capture adapter: refused candidate %s: %s. Memo remains queued.",
                candidate,
                exc,
            )
            refused.append((candidate, exc))
    return WatchCycleResult(admitted=admitted, refused=refused)


__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "CAPTURE_CHAIN_V1",
    "DEFAULT_CAPTURE_SCOPE",
    "CaptureAdmissionError",
    "CaptureFileNotStableError",
    "CaptureResult",
    "SensorIdentity",
    "UnregisteredSensorError",
    "WatchCycleResult",
    "admit_capture_file",
    "compute_content_identity",
    "default_sensor_identity",
    "is_admissible_capture_file",
    "is_sensor_registered",
    "list_candidate_files",
    "register_sensor",
    "run_watch_cycle",
]
