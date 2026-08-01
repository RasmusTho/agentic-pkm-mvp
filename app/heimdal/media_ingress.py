"""Governed media admission seam (CDLM-01, issue #4384).

Specified by `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md`
and bound by INV-CDLM-1 / INV-CDLM-3 in that directory's `README.md`.

This module is the single place media bytes become durably accepted evidence.
`POST /api/heimdal/capture/media` (`app/api/routes/heimdal_capture.py`) is its
only HTTP caller; `app.heimdal.capture_adapter.admit_capture_file` reuses the
same receipt seam for the legacy watched-folder lane.

**The load-bearing rule (INV-CDLM-1).** A receipt means the original is durably
accepted -- not that an HTTP call succeeded. `admit_media_bytes` therefore runs
in exactly this order, and a failure at any step leaves no acknowledged state:

1. verify `content_sha256` against the received bytes (never trust the claim);
2. short-circuit on an existing receipt for `(capture_id, content_sha256)` --
   a replay re-admits nothing and emits no second event (INV-CDLM-3);
3. consent admission (HEIM-3) through `admit_raw_evidence`, the one sanctioned
   signal->raw gate -- never a local grant-resolution copy;
4. encrypt and durably write the raw object (idempotent by content hash);
5. commit the `heimdal.capture.media.admitted` outbox event;
6. **only then** persist the receipt, which is the acknowledgement itself.

Steps 4-6 are the same outbox-before-ack ordering the governed text capture
enforces (`app/api/routes/capture.py`, `docs/contracts/MIMER_CLIENT_CONTRACT.md`
§4.1). The ordering is asserted on the production route path by
`tests/heimdal/test_media_ingress.py::test_ack_requires_raw_write_and_committed_event`,
which fault-injects the real commit primitive.

The raw store is append-only, so a raw object written in step 4 survives a
failure in step 5. That is deliberate and is not an acknowledged artifact: the
client's resend completes admission idempotently over the same raw object and
only then receives a receipt (partial-failure matrix, "hub crash between raw
write and outbox commit"). Absence of a receipt is the honest answer, which is
exactly what #4369 lacked.

Session/segment ledger semantics are owned by `app.heimdal.meeting_ledger`
(CDLM-02, #4385): this seam stores `session_id`/`session_seq` opaquely in
lineage and hands them to the ledger hook (`_ledger_session_segment`) after the
receipt exists — it never interprets, orders, or validates them itself. Still
out of scope here: ASR or any derivation (CDLM-06), streaming/resumable
uploads, auth keys, and public ingress (owner-reserved).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.events.schema import make_outbox_event
from app.events.types import HEIMDAL_CAPTURE_MEDIA_ADMITTED
from app.heimdal import (
    capture_adapter,
    media_receipts,
    meeting_finalization,
    meeting_ledger,
    meeting_projection,
    raw_store,
)
from app.heimdal.capture_adapter import SensorIdentity
from app.heimdal.consent_ledger import MEDIA_CAPTURE_SCOPE, admit_raw_evidence
from app.heimdal.media_receipts import MediaReceipt
from app.heimdal.raw_read_gate import raw_ref_for
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services import outbox as outbox_service

logger = logging.getLogger(__name__)

MEDIA_ADMITTED_EVENT = HEIMDAL_CAPTURE_MEDIA_ADMITTED
_EVENT_SOURCE = "heimdal.capture.media"

# The two lanes that produce receipts. Both write the same receipt shape; they
# differ only in retention posture -- receipt-gated retention is an outbox-lane
# property (CDLM-03), never claimed for the legacy watched-folder lane.
LANE_MEDIA_INGRESS = "media_ingress"
LANE_WATCHED_FOLDER = "watched_folder"

# Provenance for a client-transferred capture: the device captured it and the
# governed HTTP seam admitted it. Deliberately distinct from
# `capture_adapter.CAPTURE_CHAIN_V1`, whose iCloud/folder-watch hops did not
# happen on this lane.
CAPTURE_CHAIN_MEDIA_INGRESS: List[str] = ["client_capture", "http_media_ingress"]

MEDIA_INGRESS_SOURCE_PATH = "heimdal-media-ingress"

# Sensor identity for this admission path (T5 mitigation). Registered at import
# because this module *is* the adapter -- the same producer-with-precondition
# pairing `capture_adapter._KNOWN_SENSORS` uses for the voice-memo adapter, so
# the guard can never be enabled without its registration shipping alongside.
MEDIA_ADAPTER_ID = "heimdal_media_ingress"
MEDIA_ADAPTER_VERSION = "v1"
capture_adapter.register_sensor(MEDIA_ADAPTER_ID, MEDIA_ADAPTER_VERSION)

# Per-kind byte caps. v1 is turn-based multipart, not streaming (resumable
# upload is explicitly out of scope), so every cap must be a size one request
# can hold. Override one kind with `HEIMDAL_MEDIA_MAX_BYTES_<KIND>`.
DEFAULT_MEDIA_KIND_MAX_BYTES: Dict[str, int] = {
    "audio": 128 * 1024 * 1024,
    "image": 32 * 1024 * 1024,
    "video": 512 * 1024 * 1024,
    "document": 64 * 1024 * 1024,
}
MEDIA_KINDS: tuple[str, ...] = tuple(DEFAULT_MEDIA_KIND_MAX_BYTES)
_MAX_BYTES_ENV_TEMPLATE = "HEIMDAL_MEDIA_MAX_BYTES_{kind}"

# The receipt query is a bounded batch, never an unbounded table read.
RECEIPT_QUERY_MAX_IDS = 100


class MediaKindUnsupportedError(ValueError):
    """The declared ``kind`` is outside the admitted media set."""


class MediaTooLargeError(ValueError):
    """The media bytes exceed the configured per-kind cap.

    Carries ``max_bytes`` so the client is told the actual bound rather than
    left to guess whether a smaller retry would succeed.
    """

    def __init__(self, message: str, *, kind: str, size_bytes: int, max_bytes: int) -> None:
        super().__init__(message)
        self.kind = kind
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class MediaCapConfigError(RuntimeError):
    """A per-kind cap override is present but unusable -- fail loud, never guess."""


class MediaHashMismatchError(ValueError):
    """The received bytes do not hash to the declared ``content_sha256``."""


class MediaAdmissionError(RuntimeError):
    """The durable raw write did not confirm; nothing was acknowledged."""


class MediaAdmissionEventPersistenceError(RuntimeError):
    """The admission event could not be committed, so no receipt was written.

    This is the INV-CDLM-1 refusal: the raw object may be durable, but without a
    committed admission event the caller must not be told the capture was
    accepted.
    """


@dataclass(frozen=True)
class MediaAdmission:
    """The outcome of one media admission attempt.

    ``idempotent_replay`` is True exactly when this transfer identity was already
    acknowledged: the receipt is the pre-existing one and no raw object was
    written. It does **not** promise nothing was appended to the audit log — a
    replay detected at the shared seam rather than at the pre-write short-circuit
    has already emitted its event. The invariant is one receipt identity, not one
    audit line.
    """

    receipt: MediaReceipt
    idempotent_replay: bool


def resolve_media_kind_max_bytes(kind: str) -> int:
    """Resolve the configured byte cap for ``kind``.

    Raises :class:`MediaKindUnsupportedError` for a kind outside
    :data:`MEDIA_KINDS` and :class:`MediaCapConfigError` for a present-but-
    unusable override -- a silently ignored cap would admit oversize evidence
    the operator believed was bounded.

    The route resolves every kind up front to derive its coarse read bound, so a
    `MediaCapConfigError` reaches a client from there rather than from an
    admission; that call site renders the published named refusal.
    """
    if kind not in DEFAULT_MEDIA_KIND_MAX_BYTES:
        raise MediaKindUnsupportedError(
            f"kind {kind!r} is not an admitted media kind; expected one of {list(MEDIA_KINDS)}."
        )
    env_var = _MAX_BYTES_ENV_TEMPLATE.format(kind=kind.upper())
    raw = (os.environ.get(env_var) or "").strip()
    if not raw:
        return DEFAULT_MEDIA_KIND_MAX_BYTES[kind]
    try:
        value = int(raw)
    except ValueError as exc:
        raise MediaCapConfigError(
            f"{env_var}={raw!r} is not a valid byte count; unset it or set a positive integer."
        ) from exc
    if value <= 0:
        raise MediaCapConfigError(
            f"{env_var}={raw!r} must be a positive byte count; a non-positive cap would "
            "refuse every capture of this kind."
        )
    return value


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _emit_admission_event(
    payload: Dict[str, Any], *, trace_id: str, receipt_id: str, content_sha256: str
) -> bool:
    """Commit the admission event; return True once at least one sink persisted it.

    Same sink discipline as the governed text capture
    (`app/api/routes/capture.py::_emit_capture_event`): the JSONL audit log is
    the required local accountability sink and the DB outbox mirror is used when
    a pg backend is configured. The DB write is keyed by a *derived* idempotency
    key, so a retry after a partial failure produces one row, not two.

    The sinks are reached through module attributes
    (`outbox_service.append_jsonl_outbox_event`) rather than direct imports so
    the enforcement test can fault-inject the real commit primitive instead of a
    stand-in for it.
    """
    evt = make_outbox_event(
        event=MEDIA_ADMITTED_EVENT,
        source=_EVENT_SOURCE,
        payload=payload,
        trace_id=trace_id,
    )
    emitted = False
    try:
        emitted = outbox_service.append_jsonl_outbox_event(
            _resolve_outbox_path(), evt, default_source=_EVENT_SOURCE
        )
    except Exception as exc:
        logger.warning(
            "media admission event jsonl write failed trace_id=%s err=%s", trace_id, exc
        )

    # Ask the outbox policy whether a self-owned write will actually connect,
    # instead of re-deriving that from STORE_BACKEND/DATABASE_URL here (#4214
    # D1). The local predicate was narrower than the connection's own resolver,
    # and since the memory-mode skip branch landed a skipped write returns
    # normally — which would make the `emitted = True` below report success for
    # an event no sink took, exactly the class #4214 exists to close.
    if not outbox_service.self_owned_write_would_skip():
        outbox_evt = outbox_service.coerce_outbox_event(evt, default_source=_EVENT_SOURCE)
        if outbox_evt is not None:
            try:
                outbox_service.write_outbox_event(
                    outbox_evt,
                    idempotency_key=outbox_service.derive_idempotency_key(
                        outbox_evt.event, receipt_id, content_sha256
                    ),
                )
                # Returning normally means the row exists: `write_outbox_event`
                # yields the new id on insert and "" when its ON CONFLICT
                # swallowed a duplicate. Unlike the governed text capture, whose
                # key is the per-emission random event_id and therefore always
                # inserts, this key is *derived* from the transfer identity — so
                # a swallowed duplicate is proof the event was already committed
                # by a prior attempt, not evidence that nothing was committed.
                # Treating "" as a failure would refuse such a capture forever.
                emitted = True
            except Exception as exc:
                logger.warning(
                    "media admission event db outbox write failed trace_id=%s err=%s",
                    trace_id,
                    exc,
                )
    return emitted


def record_media_admission(
    *,
    capture_id: str,
    content_sha256: str,
    raw_ref: str,
    kind: str,
    lane: str,
    trace_id: str,
    event_payload: Dict[str, Any],
    receipt_payload: Optional[Dict[str, Any]] = None,
) -> tuple[MediaReceipt, bool]:
    """Commit the admission event, then persist the receipt.

    Returns ``(receipt, newly_acknowledged)``. ``newly_acknowledged=False`` means
    this identity was already acknowledged, which is what lets the caller report
    ``idempotent_replay`` truthfully even when the acknowledgement was made by a
    concurrent request rather than by an earlier one this caller saw.

    This is the shared acknowledgement seam for both lanes, and the ordering
    inside it is the contract: the receipt is written **after** the event is
    committed, never before, because the receipt is the acknowledgement. A
    caller must only reach this function once the raw write is durable.

    An identity that is already acknowledged short-circuits here: it returns the
    existing receipt and emits **no** second event. The guard lives in this
    shared seam, not only in `admit_media_bytes`, because the watched-folder lane
    re-admits the same content on every tick whenever a source delete failed --
    without it, one file would emit an unbounded number of admission events while
    holding a single receipt, and CDLM-02/CDLM-06 would double-count it.

    Two concurrent admissions of the same identity can still both pass that
    unlocked read. The derived primary key makes the second receipt insert a
    no-op returning the first row, so the acknowledgement stays single; the DB
    outbox likewise dedupes on a derived idempotency key. Only the JSONL audit
    log can record the attempt twice, and an audit line is a trace, not an
    acknowledgement.

    Raises :class:`MediaAdmissionEventPersistenceError` when no sink accepted the
    event, or :class:`media_receipts.MediaReceiptPersistenceError` when the
    receipt itself could not be persisted. In both cases nothing is acknowledged.
    """
    already_acknowledged = media_receipts.get_media_receipt(capture_id, content_sha256)
    if already_acknowledged is not None:
        return already_acknowledged, False

    receipt_id = media_receipts.derive_receipt_id(capture_id, content_sha256)
    if not _emit_admission_event(
        event_payload,
        trace_id=trace_id,
        receipt_id=receipt_id,
        content_sha256=content_sha256,
    ):
        raise MediaAdmissionEventPersistenceError(
            f"admission event {MEDIA_ADMITTED_EVENT!r} was not persisted to any outbox sink "
            f"for capture_id={capture_id!r}; no receipt was written."
        )
    try:
        receipt, created = media_receipts.append_media_receipt(
            capture_id=capture_id,
            content_sha256=content_sha256,
            raw_ref=raw_ref,
            kind=kind,
            lane=lane,
            trace_id=trace_id,
            payload=dict(receipt_payload or {}),
        )
    except media_receipts.MediaReceiptPersistenceError:
        raise
    except Exception as exc:
        # Any storage failure here must surface as a *named* not-acknowledged
        # state rather than an unnamed error: the caller was about to tell a
        # client its capture was accepted.
        raise media_receipts.MediaReceiptPersistenceError(
            f"receipt for capture_id={capture_id!r} could not be persisted: {exc}. "
            "Nothing was acknowledged."
        ) from exc
    return receipt, created


def admit_media_bytes(
    media_bytes: bytes,
    *,
    capture_id: str,
    content_sha256: str,
    kind: str,
    captured_at: str,
    device_id: str,
    schema_version: int,
    session_id: Optional[str] = None,
    session_seq: Optional[int] = None,
    sidecar_extra: Optional[Dict[str, Any]] = None,
    trace_id: str,
    key: Optional[bytes] = None,
    scope: Optional[str] = None,
) -> MediaAdmission:
    """Admit one media original and return its durable-acceptance receipt.

    ``scope`` defaults to this lane's own standing consent scope
    (`consent_ledger.MEDIA_CAPTURE_SCOPE`), whose seeded grant's
    `capture_profile.modalities` names every kind in :data:`MEDIA_KINDS` -- so
    the consent block stamped onto a photo, video, or document references a
    grant that actually covers it. It borrowed the voice-memo lane's
    speech-only `self_record` grant until #4492; the two now revoke
    independently. A caller may still narrow it; no active grant for the
    resolved scope raises `ConsentRefusedError` (HEIM-3) before any bytes land.

    Raises the named refusals in the order the HTTP contract publishes them:
    :class:`MediaKindUnsupportedError` (415), :class:`MediaTooLargeError` (413),
    :class:`MediaHashMismatchError` (422), then :class:`MediaAdmissionError` /
    :class:`MediaAdmissionEventPersistenceError` /
    :class:`media_receipts.MediaReceiptPersistenceError` (500, nothing
    acknowledged).
    """
    max_bytes = resolve_media_kind_max_bytes(kind)
    size_bytes = len(media_bytes)
    if size_bytes > max_bytes:
        raise MediaTooLargeError(
            f"media of kind {kind!r} is {size_bytes} bytes, over the configured "
            f"{max_bytes}-byte cap; nothing was admitted.",
            kind=kind,
            size_bytes=size_bytes,
            max_bytes=max_bytes,
        )

    computed = capture_adapter.compute_content_identity(media_bytes)
    if computed != content_sha256:
        raise MediaHashMismatchError(
            f"declared content_sha256 {content_sha256!r} does not match the received bytes "
            f"({computed!r}); nothing was admitted."
        )

    # INV-CDLM-3: a resend after a lost response re-admits nothing. Checked
    # before consent/encryption/write so a replay costs one lookup.
    existing = media_receipts.get_media_receipt(capture_id, content_sha256)
    if existing is not None:
        # The replay must still reach the ledger (CDLM-02): if a prior attempt
        # acknowledged the capture but crashed before the ledger row landed, the
        # client's resend takes this branch — an idempotent ledger upsert here is
        # what heals that hole; a duplicate replay is a no-op.
        _ledger_session_segment(
            session_id=session_id,
            session_seq=session_seq,
            receipt=existing,
            trace_id=trace_id,
            media_bytes=media_bytes,
            kind=kind,
        )
        return MediaAdmission(receipt=existing, idempotent_replay=True)

    sensor = SensorIdentity(
        adapter=MEDIA_ADAPTER_ID, version=MEDIA_ADAPTER_VERSION, device=device_id
    )
    capture_adapter._assert_sensor_registered(sensor)

    resolved_scope = scope or MEDIA_CAPTURE_SCOPE
    admitted = admit_raw_evidence(scope=resolved_scope)

    lineage: Dict[str, Any] = {
        "modality": kind,
        "kind": kind,
        "lane": LANE_MEDIA_INGRESS,
        "capture_id": capture_id,
        "content_sha256": content_sha256,
        "captured_at": captured_at,
        "device_id": device_id,
        "schema_version": schema_version,
    }
    # Session fields are stored opaquely: CDLM-02 owns every ledger semantic
    # over them, so this lane must not interpret, order, or validate them.
    if session_id is not None:
        lineage["session_id"] = session_id
    if session_seq is not None:
        lineage["session_seq"] = session_seq
    if sidecar_extra:
        lineage["sidecar_extra"] = dict(sidecar_extra)

    encryption_key = key if key is not None else raw_store.resolve_raw_store_key()
    ciphertext, nonce = raw_store.encrypt_raw_bytes(media_bytes, key=encryption_key)
    try:
        # Idempotent by content hash: two captures of byte-identical content
        # share one raw object, so `lineage` here is the *first* admission's.
        # Each capture's own lineage lives on its own receipt, which is why the
        # receipt store is keyed by transfer identity and not by content hash.
        record, _raw_created = raw_store.insert_raw_record(
            content_identity=content_sha256,
            capture_chain=list(CAPTURE_CHAIN_MEDIA_INGRESS),
            sensor=sensor.as_dict(),
            consent=admitted.consent.as_dict(),
            ciphertext=ciphertext,
            nonce=nonce,
            key_ref="v1-process-key",
            source_path=MEDIA_INGRESS_SOURCE_PATH,
            payload=lineage,
        )
    except Exception as exc:
        logger.error(
            "Heimdal media ingress: durable write failed capture_id=%s content_sha256=%s: %s. "
            "Nothing acknowledged.",
            capture_id,
            content_sha256,
            exc,
        )
        raise MediaAdmissionError(
            f"media admission refused: the raw object could not be durably persisted for "
            f"capture_id={capture_id!r}: {exc}. Nothing was acknowledged."
        ) from exc

    raw_ref = raw_ref_for(record)
    # Both the event and the receipt carry the same lineage keys the raw record
    # got, minus the None-valued optional session fields, so neither the audit
    # log nor the receipt row records a field the client never sent.
    admission_metadata = {
        key_name: value
        for key_name, value in (
            ("device_id", device_id),
            ("captured_at", captured_at),
            ("schema_version", schema_version),
            ("session_id", session_id),
            ("session_seq", session_seq),
        )
        if value is not None
    }
    receipt, newly_acknowledged = record_media_admission(
        capture_id=capture_id,
        content_sha256=content_sha256,
        raw_ref=raw_ref,
        kind=kind,
        lane=LANE_MEDIA_INGRESS,
        trace_id=trace_id,
        event_payload={
            "capture_id": capture_id,
            "content_sha256": content_sha256,
            "raw_ref": raw_ref,
            "kind": kind,
            "lane": LANE_MEDIA_INGRESS,
            "receipt_id": media_receipts.derive_receipt_id(capture_id, content_sha256),
            **admission_metadata,
        },
        receipt_payload=admission_metadata,
    )
    _ledger_session_segment(
        session_id=session_id,
        session_seq=session_seq,
        receipt=receipt,
        trace_id=trace_id,
        media_bytes=media_bytes,
        kind=kind,
    )
    # A concurrent request may have acknowledged this identity between the
    # short-circuit above and the seam's own guard; report that truthfully rather
    # than claiming this call was the one that acknowledged it.
    return MediaAdmission(receipt=receipt, idempotent_replay=not newly_acknowledged)


def _ledger_session_segment(
    *,
    session_id: Optional[str],
    session_seq: Optional[int],
    receipt: MediaReceipt,
    trace_id: str,
    media_bytes: Optional[bytes] = None,
    kind: str = "",
) -> None:
    """Ledger one admission's `(session_id, session_seq)` (CDLM-02 hook).

    Runs after the receipt exists, on both the fresh and the replay path, so a
    resend heals a ledger hole left by a crash between acknowledgement and
    ledger write. A no-op when the client sent no session fields.

    A ledger persistence failure propagates (fail loud — whether it surfaces as
    `MeetingLedgerPersistenceError` or a raw store/driver error): the receipt
    is already durable and remains valid, but the caller must not
    report a fully recorded admission over a segment the ledger cannot answer
    for — the client's idempotent resend retries exactly this write. A recorded
    sequence *conflict* is not a failure: the admission acknowledged real
    bytes, and the conflict is surfaced through the gap report (fail closed on
    the ledger row, honest receipt on the transfer).
    """
    if session_id is None or session_seq is None:
        return
    segment_outcome = meeting_ledger.record_segment_admission(
        session_id=session_id,
        session_seq=session_seq,
        receipt_id=receipt.receipt_id,
        content_sha256=receipt.content_sha256,
        raw_ref=receipt.raw_ref,
        trace_id=trace_id,
    )
    # CDLM-06: the recorded (or replayed) segment triggers per-segment ASR
    # derivation and analysis re-derivation. Runs on both branches so a resend
    # completes a derivation an earlier crash left unfinished; an
    # already-derived content hash short-circuits on the durable derivation
    # row, so replays and restarts re-derive nothing. Never raises into the
    # admission path — a derivation problem is per-segment needs-attention
    # projection state, not an admission failure.
    if media_bytes is not None:
        meeting_projection.derive_segment(
            session_id=session_id,
            session_seq=session_seq,
            content_sha256=receipt.content_sha256,
            media_bytes=media_bytes,
            kind=kind,
        )
    # CDLM-08: any admission touching a closed session — a genuinely late
    # segment OR a replay-resend that just healed a failed derivation —
    # triggers post-close reconciliation. `maybe_refinalize` is internally
    # gated (closed session with an existing finalization only) and idempotent
    # per finalization state, so an unchanged state is a cheap no-op; it is
    # exception-isolated and the admission ack never depends on it.
    if segment_outcome.late or segment_outcome.outcome == meeting_ledger.OUTCOME_REPLAY:
        meeting_finalization.maybe_refinalize(session_id, trace_id=trace_id)


def record_watched_folder_admission(
    record: "raw_store.RawRecord",
    *,
    capture_id: Optional[str] = None,
    kind: str = "audio",
    trace_id: str = "",
) -> Optional[MediaReceipt]:
    """Receipt a watched-folder admission through the shared seam.

    The legacy (Model-1) lane is admitted and receipted hub-side so its files
    are queryable, but it stays **outside** the receipt-gated retention
    guarantee: that guarantee is an outbox-lane property (CDLM-03), and claiming
    it here is the forbidden outcome in the vertical's partial-failure matrix.
    A receipt failure is therefore logged loudly and returned as ``None`` rather
    than raised -- it must not change the watcher's existing
    delete-after-confirmed-ingest behavior, which #4362 owns.

    ``capture_id`` comes from the HCAP-07 sidecar when it carries one; otherwise
    the receipt is keyed by the content hash itself, so one query parameter serves
    both lanes. `media_receipts` is the authority on canonicalizing a spelling, so
    a sidecar UUID written differently than the client's HTTP request still
    resolves to one transfer identity; `canonical_capture_id` is called here for
    its other job -- a sidecar is untrusted client input whose values are not
    type-validated upstream, and a non-string `capture_id` must degrade to the
    content-hash key rather than raise. Everything here runs *after* the durable
    write, so an exception escaping into `admit_capture_file` would strand the
    source file as permanently "refused" on every tick.
    """
    content_sha256 = record.content_identity
    try:
        raw_ref = raw_ref_for(record)
        sidecar_capture_id = media_receipts.canonical_capture_id(capture_id)
        resolved_capture_id = sidecar_capture_id or content_sha256
        receipt, _newly_acknowledged = record_media_admission(
            capture_id=resolved_capture_id,
            content_sha256=content_sha256,
            raw_ref=raw_ref,
            kind=kind,
            lane=LANE_WATCHED_FOLDER,
            trace_id=trace_id,
            event_payload={
                "capture_id": resolved_capture_id,
                "content_sha256": content_sha256,
                "raw_ref": raw_ref,
                "kind": kind,
                "lane": LANE_WATCHED_FOLDER,
                "receipt_id": media_receipts.derive_receipt_id(
                    resolved_capture_id, content_sha256
                ),
            },
            receipt_payload=(
                {"sidecar_capture_id": sidecar_capture_id} if sidecar_capture_id else {}
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- the legacy lane must not gain a new failure mode
        logger.error(
            "Heimdal media receipts: watched-folder admission %s was durably written but "
            "could not be receipted: %s. The raw object is safe; the receipt query will "
            "answer 'unknown' for it until a later admission of the same content.",
            content_sha256,
            exc,
        )
        return None
    return receipt


def receipt_answer(receipt: Optional[MediaReceipt], capture_id: str) -> Dict[str, Any]:
    """Render one receipt-query answer: `admitted` with the receipt, or `unknown`.

    ``unknown`` is a first-class answer, not an error: it is how a client
    distinguishes "my response was lost" from "my capture never arrived"
    (INV-CDLM-3) after a crash or reconnect.

    Both branches echo the ``capture_id`` the caller **asked** for, not the
    canonical form, so answers stay positionally alignable with the request even
    when the client spelled its own UUID differently. The stable identity to key
    on is ``receipt_id``.
    """
    if receipt is None:
        return {"capture_id": capture_id, "outcome": "unknown"}
    return {
        "capture_id": capture_id,
        "outcome": "admitted",
        "receipt_id": receipt.receipt_id,
        "content_sha256": receipt.content_sha256,
        "raw_ref": receipt.raw_ref,
        "kind": receipt.kind,
        "lane": receipt.lane,
        "admitted_at": iso_timestamp(receipt.admitted_at),
    }


def iso_timestamp(value: datetime) -> str:
    """Render a receipt timestamp as a UTC ISO-8601 string with a `Z` suffix.

    One renderer for both the admission response and the receipt query, so the
    same receipt never appears with two different `admitted_at` spellings.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CAPTURE_CHAIN_MEDIA_INGRESS",
    "DEFAULT_MEDIA_KIND_MAX_BYTES",
    "LANE_MEDIA_INGRESS",
    "LANE_WATCHED_FOLDER",
    "MEDIA_ADAPTER_ID",
    "MEDIA_ADAPTER_VERSION",
    "MEDIA_ADMITTED_EVENT",
    "MEDIA_KINDS",
    "RECEIPT_QUERY_MAX_IDS",
    "MediaAdmission",
    "MediaAdmissionError",
    "MediaAdmissionEventPersistenceError",
    "MediaCapConfigError",
    "MediaHashMismatchError",
    "MediaKindUnsupportedError",
    "MediaTooLargeError",
    "admit_media_bytes",
    "iso_timestamp",
    "receipt_answer",
    "record_media_admission",
    "record_watched_folder_admission",
    "resolve_media_kind_max_bytes",
]
