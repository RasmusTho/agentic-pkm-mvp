"""Governed media ingress HTTP surface (CDLM-01, issue #4384).

Two routes, one contract:

- ``POST /api/heimdal/capture/media`` -- multipart `media` bytes plus a
  versioned `sidecar` JSON part. The 2xx response *is* the durable-acceptance
  receipt: it exists only after the raw-store write is durable and the
  ``heimdal.capture.media.admitted`` outbox event is committed (INV-CDLM-1).
  Ordering and the nothing-acknowledged failure path live in
  `app.heimdal.media_ingress`, which is also the seam the legacy watched-folder
  lane reuses; this module is transport, validation, and status mapping only.
- ``GET /api/heimdal/capture/receipts?capture_id=…`` -- bounded, repeatable
  batch query answering ``admitted`` or ``unknown`` per id. That is the client's
  reconnect answer after a lost response (INV-CDLM-3): ``unknown`` is a
  first-class answer, not an error.

**Posture (v1).** LAN / loopback / tailnet only, mirroring
`docs/contracts/MIMER_CLIENT_CONTRACT.md` §4's client-side rule from the hub
side: a request whose peer is a globally routable address is refused with 403
`public_ingress_refused` before any admission or disclosure work. Public ingress
is owner-reserved (R-EXTERNAL) and per-agent keys are the named next hardening
slice (client-contract gap F2), not something this route improvises.

Named error states, never blind-retryable — the client must branch on `error`:

| Status | `error` | Meaning |
| --- | --- | --- |
| 403 | `public_ingress_refused` | Peer is outside the LAN/loopback/tailnet posture |
| 415 | `unsupported_media_kind` | `kind` outside {audio, image, video, document} |
| 413 | `media_too_large` | Over the configured per-kind cap (`max_bytes` included) |
| 422 | `sidecar_schema_invalid` | Sidecar missing/malformed against the admission schema |
| 422 | `content_hash_mismatch` | Received bytes do not hash to `content_sha256` |
| 422 | `capture_id_required` / `too_many_capture_ids` | Receipt query outside its bounds |
| 503 | `receipt_store_unavailable` | Receipt store unreadable — never answered as `unknown` |
| 409 | `consent_refused` | No active consent grant (HEIM-3); nothing admitted |
| 500 | `raw_write_failed` / `admission_event_commit_failed` / `receipt_persistence_failed` / `raw_store_key_unavailable` / `media_cap_misconfigured` / `admission_failed` | State `not_acknowledged` |

`admission_failed` is the catch-all: no reachable failure on this seam may
surface as an unnamed 500, because "never blind-retryable" only holds if the
client always has an `error` to branch on.

**Where the per-kind cap is enforced.** The exact per-kind cap is not knowable
until the sidecar is parsed, because `kind` lives in the sidecar. So the read is
bounded twice: this module reads at most `max(per-kind caps) + 1` bytes into
memory and rejects anything longer with 413 before a `kind` is even known, and
`media_ingress.admit_media_bytes` then applies the specific per-kind cap. The
multipart parse itself is bounded by Starlette spooling large parts to disk. A
pre-parse `Content-Length` guard is deliberately not added on top: it would only
duplicate the byte bound already enforced here, less precisely.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from ipaddress import ip_address, ip_network
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Starlette's `UploadFile`, not FastAPI's: `request.form()` yields the Starlette
# type, and `fastapi.UploadFile` is a *subclass* of it, so an isinstance check
# against the FastAPI type silently misses every real part.
from starlette.datastructures import UploadFile

from app.events.models import new_trace_id
from app.heimdal import media_ingress, media_receipts
from app.heimdal.consent_ledger import ConsentRefusedError
from app.heimdal.media_ingress import (
    MediaAdmissionError,
    MediaAdmissionEventPersistenceError,
    MediaCapConfigError,
    MediaHashMismatchError,
    MediaKindUnsupportedError,
    MediaTooLargeError,
)
from app.heimdal.media_receipts import MediaReceiptPersistenceError
from app.heimdal.raw_store import RawStoreKeyMissingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/heimdal/capture", tags=["heimdal"])

# The admitted ingress posture, stated as explicit networks rather than
# `ip_address(...).is_private`: that property also covers documentation and
# reserved ranges and has drifted between Python versions, which is the wrong
# basis for a security posture. Loopback is checked separately.
_ADMITTED_PEER_NETWORKS = (
    ip_network("10.0.0.0/8"),  # RFC1918 LAN
    ip_network("172.16.0.0/12"),  # RFC1918 LAN
    ip_network("192.168.0.0/16"),  # RFC1918 LAN
    ip_network("169.254.0.0/16"),  # IPv4 link-local
    ip_network("100.64.0.0/10"),  # CGNAT — the range a tailnet assigns
    ip_network("fc00::/7"),  # IPv6 ULA (covers the tailnet's fd7a:115c:a1e0::/48)
    ip_network("fe80::/10"),  # IPv6 link-local
)

# `testclient` is Starlette's synthetic in-process peer, treated as loopback for
# the same reason `app.auth._is_loopback_host` does: an in-process call has no
# network hop to judge. Unlike that helper, an *empty* host is NOT admitted here:
# on this seam an unknown peer is not provably inside the posture, so it fails
# closed.
_LOOPBACK_HOST_NAMES = {"localhost", "testclient"}

_SIDECAR_SCHEMA_VERSIONS = (1,)

# The sidecar is a small metadata object; a megabyte is already far past any
# legitimate value and keeps a malformed part from being materialized whole.
_MAX_SIDECAR_BYTES = 1024 * 1024


class MediaSidecar(BaseModel):
    """The versioned admission sidecar.

    ``extra="allow"``, deliberately: this composes with the HCAP-07 capture-time
    metadata sidecar and with CDLM-02's later session fields rather than forking
    a second schema, so an unknown key is retained as opaque lineage instead of
    rejected. The *required* fields below are still strict.
    """

    model_config = ConfigDict(extra="allow")

    capture_id: str
    content_sha256: str
    kind: str
    captured_at: str
    device_id: str = Field(min_length=1)
    schema_version: int
    session_id: str | None = None
    session_seq: int | None = None

    @field_validator("capture_id")
    @classmethod
    def _uuid_capture_id(cls, value: str) -> str:
        """`capture_id` is a client-minted UUID, minted once at finalization.

        Validated here and *not* on the receipt query: a watched-folder receipt
        is keyed by its content hash, so the query must accept that form too.
        """
        try:
            UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("capture_id must be a client-minted UUID") from exc
        return value

    @field_validator("content_sha256")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("content_sha256 must be 64 lowercase hex characters")
        return normalized

    @field_validator("captured_at")
    @classmethod
    def _iso_captured_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("captured_at must be an ISO-8601 timestamp") from exc
        return value

    @field_validator("schema_version")
    @classmethod
    def _known_schema_version(cls, value: int) -> int:
        if value not in _SIDECAR_SCHEMA_VERSIONS:
            raise ValueError(
                f"schema_version {value!r} is not supported; expected one of "
                f"{list(_SIDECAR_SCHEMA_VERSIONS)}"
            )
        return value


class MediaReceiptResponse(BaseModel):
    """The durable-acceptance receipt returned by a successful admission.

    ``idempotent_replay`` is present and True only when this exact
    ``(capture_id, content_sha256)`` pair was already acknowledged: the receipt
    identity, raw ref, and ``admitted_at`` are the original ones, the raw store
    still holds a single object, and no second admission event was emitted.
    """

    outcome: Literal["admitted"] = "admitted"
    capture_id: str
    content_sha256: str
    receipt_id: str
    raw_ref: str
    kind: str
    admitted_at: str
    trace_id: str
    idempotent_replay: bool | None = None


class ReceiptQueryResponse(BaseModel):
    """Per-id recovery answers, positionally aligned with the requested ids."""

    receipts: list[dict[str, Any]]
    trace_id: str


def _trace_id(request: Request) -> str:
    return (
        getattr(request.state, "trace_id", None)
        or request.headers.get("x-trace-id")
        or new_trace_id()
    )


def _is_admitted_peer(host: str | None) -> bool:
    if host is None:
        return False
    if host in _LOOPBACK_HOST_NAMES:
        return True
    try:
        address = ip_address(host)
    except ValueError:
        # A name we cannot resolve to an address is not provably inside the
        # posture, so it is refused rather than assumed local.
        return False
    # A dual-stack listener reports an IPv4 LAN peer as `::ffff:192.168.1.5`;
    # judge it as the IPv4 address it is rather than false-refusing it.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_loopback:
        return True
    return any(address in network for network in _ADMITTED_PEER_NETWORKS)


def _assert_lan_posture(request: Request, trace_id: str) -> None:
    """Refuse operation outside the LAN/loopback/tailnet posture.

    Judged on the *immediate* peer only. `X-Forwarded-For` is deliberately not
    consulted: on this seam a forwarded header would let a public caller behind
    any relay assert a local address, which is precisely the ingress this slice
    must not open.
    """
    host = request.client.host if request.client else None
    if _is_admitted_peer(host):
        return
    logger.warning(
        "heimdal media ingress refused non-LAN peer host=%s trace_id=%s", host, trace_id
    )
    raise HTTPException(
        status_code=403,
        detail={
            "error": "public_ingress_refused",
            "message": (
                "Governed media ingress operates on loopback, LAN, or tailnet peers only; "
                "public ingress is not supported. Nothing was admitted."
            ),
            "trace_id": trace_id,
        },
    )


def _parse_sidecar(raw_sidecar: str, trace_id: str) -> MediaSidecar:
    try:
        parsed = json.loads(raw_sidecar)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "sidecar_schema_invalid",
                "message": f"The sidecar part is not valid JSON: {exc}. Nothing was admitted.",
                "trace_id": trace_id,
            },
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "sidecar_schema_invalid",
                "message": "The sidecar part must be a JSON object. Nothing was admitted.",
                "trace_id": trace_id,
            },
        )
    try:
        return MediaSidecar.model_validate(parsed)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "sidecar_schema_invalid",
                "message": "The sidecar does not satisfy the admission schema; nothing was admitted.",
                "violations": exc.errors(include_url=False),
                "trace_id": trace_id,
            },
        ) from exc


async def _part_bytes(name: str, part: Any, trace_id: str, *, max_bytes: int) -> bytes:
    """Read one multipart part as bytes, accepting both wire shapes.

    A client may send `sidecar` as a plain form field (the contract's own curl:
    `-F 'sidecar={…};type=application/json'`) or as a named part with a filename
    (what most native multipart builders produce). Both are valid multipart and
    both carry the same bytes, so the seam accepts either rather than refusing a
    well-formed request over a filename.

    ``max_bytes`` bounds what is materialized in memory. It reads one byte past
    the bound so an oversize part is detectable without holding all of it.
    """
    if part is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"{name}_part_required",
                "message": (
                    f"The multipart request must carry a {name!r} part. Nothing was admitted."
                ),
                "trace_id": trace_id,
            },
        )
    if isinstance(part, UploadFile):
        data = await part.read(max_bytes + 1)
    elif isinstance(part, bytes):
        data = part[: max_bytes + 1]
    else:
        data = str(part).encode("utf-8")[: max_bytes + 1]
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "media_too_large" if name == "media" else f"{name}_part_too_large",
                "message": (
                    f"The {name!r} part exceeds the largest configured bound of {max_bytes} "
                    "bytes; nothing was admitted."
                ),
                "max_bytes": max_bytes,
                "trace_id": trace_id,
            },
        )
    return data


@router.post(
    "/media",
    response_model=MediaReceiptResponse,
    response_model_exclude_none=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["media", "sidecar"],
                        "properties": {
                            "media": {
                                "type": "string",
                                "format": "binary",
                                "description": "The captured original's bytes.",
                            },
                            "sidecar": {
                                "type": "string",
                                "format": "binary",
                                "description": (
                                    "Versioned admission sidecar JSON: capture_id, "
                                    "content_sha256, kind, captured_at, device_id, "
                                    "schema_version, and optional session_id/session_seq."
                                ),
                            },
                        },
                    }
                }
            },
        }
    },
)
async def admit_media(request: Request) -> MediaReceiptResponse:
    """Admit one media original and return its durable-acceptance receipt.

    The body is parsed from the multipart form rather than declared as typed
    `File`/`Form` parameters so that a `sidecar` sent as a field and a `sidecar`
    sent as a named file part are both accepted; the OpenAPI body shape is
    declared explicitly above instead.
    """
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)

    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "multipart_invalid",
                "message": f"The request body is not a readable multipart form: {exc}.",
                "trace_id": trace_id,
            },
        ) from exc

    # The coarse bound: the largest cap any kind could resolve to. The exact
    # per-kind cap is applied by the admission seam once `kind` is known.
    largest_media_cap = max(
        media_ingress.resolve_media_kind_max_bytes(kind) for kind in media_ingress.MEDIA_KINDS
    )
    media_bytes = await _part_bytes(
        "media", form.get("media"), trace_id, max_bytes=largest_media_cap
    )
    raw_sidecar = (
        await _part_bytes(
            "sidecar", form.get("sidecar"), trace_id, max_bytes=_MAX_SIDECAR_BYTES
        )
    ).decode("utf-8", errors="replace")
    parsed = _parse_sidecar(raw_sidecar, trace_id)

    reserved = {
        "capture_id",
        "content_sha256",
        "kind",
        "captured_at",
        "device_id",
        "schema_version",
        "session_id",
        "session_seq",
    }
    sidecar_extra = {
        key: value for key, value in (parsed.model_extra or {}).items() if key not in reserved
    }

    try:
        admission = media_ingress.admit_media_bytes(
            media_bytes,
            capture_id=parsed.capture_id,
            content_sha256=parsed.content_sha256,
            kind=parsed.kind,
            captured_at=parsed.captured_at,
            device_id=parsed.device_id,
            schema_version=parsed.schema_version,
            session_id=parsed.session_id,
            session_seq=parsed.session_seq,
            sidecar_extra=sidecar_extra or None,
            trace_id=trace_id,
        )
    except MediaKindUnsupportedError as exc:
        raise HTTPException(
            status_code=415,
            detail={
                "error": "unsupported_media_kind",
                "message": str(exc),
                "supported_kinds": list(media_ingress.MEDIA_KINDS),
                "trace_id": trace_id,
            },
        ) from exc
    except MediaTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "media_too_large",
                "message": str(exc),
                "kind": exc.kind,
                "size_bytes": exc.size_bytes,
                "max_bytes": exc.max_bytes,
                "trace_id": trace_id,
            },
        ) from exc
    except MediaHashMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "content_hash_mismatch",
                "message": str(exc),
                "trace_id": trace_id,
            },
        ) from exc
    except ConsentRefusedError as exc:
        # HEIM-3 refusal: surfaced verbatim, never downgraded to a retryable
        # error and never worked around by a direct store write.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "consent_refused",
                "state": "not_acknowledged",
                "message": str(exc),
                "trace_id": trace_id,
            },
        ) from exc
    except MediaCapConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "media_cap_misconfigured",
                "state": "not_acknowledged",
                "message": str(exc),
                "trace_id": trace_id,
            },
        ) from exc
    except RawStoreKeyMissingError as exc:
        # Operator precondition, not a client error: without the raw-store key
        # nothing can be encrypted, so nothing can be admitted. Named and
        # remediable rather than an unnamed 500 the client cannot branch on.
        logger.error("heimdal media ingress refused: raw-store key unavailable: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "raw_store_key_unavailable",
                "state": "not_acknowledged",
                "message": (
                    "The encrypted raw store's key is not available to this process, so "
                    "nothing was admitted. Provision HEIMDAL_RAW_STORE_KEY for the api "
                    "service (see config/secrets/host_secret_contract.json)."
                ),
                "trace_id": trace_id,
            },
        ) from exc
    except MediaAdmissionError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "raw_write_failed",
                "state": "not_acknowledged",
                "message": (
                    "The original could not be durably written; no receipt was issued. "
                    "Re-send the same capture_id and content_sha256 — admission is idempotent."
                ),
                "trace_id": trace_id,
            },
        ) from exc
    except MediaAdmissionEventPersistenceError as exc:
        # INV-CDLM-1: the raw object may be durable, but without a committed
        # admission event nothing is acknowledged, so no receipt exists and the
        # recovery query still answers `unknown` for this capture.
        raise HTTPException(
            status_code=500,
            detail={
                "error": "admission_event_commit_failed",
                "state": "not_acknowledged",
                "message": (
                    "The admission event could not be committed, so no receipt was issued. "
                    "Re-send the same capture_id and content_sha256 — admission is idempotent."
                ),
                "trace_id": trace_id,
            },
        ) from exc
    except MediaReceiptPersistenceError as exc:
        # The third member of the nothing-acknowledged family: the receipt IS the
        # acknowledgement, so a receipt that is not durable must never be
        # reported as one, and never as an unnamed error the client cannot branch on.
        raise HTTPException(
            status_code=500,
            detail={
                "error": "receipt_persistence_failed",
                "state": "not_acknowledged",
                "message": (
                    "The durable-acceptance receipt could not be persisted, so none was "
                    "issued. Re-send the same capture_id and content_sha256 — admission is "
                    "idempotent."
                ),
                "trace_id": trace_id,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Catch-all so that *no* reachable failure on this seam can surface as an
        # unnamed 500. "Never blind-retryable" only holds if every failure the
        # client can hit carries an `error` it can branch on — an unregistered
        # sensor, an absent receipt table, a driver error, or anything a later
        # change introduces lands here rather than as a bare Internal Server
        # Error. The state is still the honest one: nothing was acknowledged.
        logger.exception(
            "heimdal media ingress failed unexpectedly trace_id=%s capture_id=%s",
            trace_id,
            parsed.capture_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "admission_failed",
                "state": "not_acknowledged",
                "message": (
                    f"Media admission failed and issued no receipt ({type(exc).__name__}). "
                    "Re-send the same capture_id and content_sha256 — admission is idempotent."
                ),
                "trace_id": trace_id,
            },
        ) from exc

    receipt = admission.receipt
    return MediaReceiptResponse(
        capture_id=receipt.capture_id,
        content_sha256=receipt.content_sha256,
        receipt_id=receipt.receipt_id,
        raw_ref=receipt.raw_ref,
        kind=receipt.kind,
        admitted_at=media_ingress.iso_timestamp(receipt.admitted_at),
        trace_id=trace_id,
        idempotent_replay=True if admission.idempotent_replay else None,
    )


@router.get("/receipts", response_model=ReceiptQueryResponse)
def query_receipts(
    request: Request,
    capture_id: list[str] = Query(default_factory=list),
) -> ReceiptQueryResponse:
    """Answer `admitted` or `unknown` for each requested capture id."""
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)

    requested = [value for value in capture_id if (value or "").strip()]
    if not requested:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "capture_id_required",
                "message": (
                    "At least one capture_id is required; the receipt query is a bounded "
                    "lookup, never a full receipt listing."
                ),
                "trace_id": trace_id,
            },
        )
    if len(requested) > media_ingress.RECEIPT_QUERY_MAX_IDS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "too_many_capture_ids",
                "message": (
                    f"{len(requested)} capture ids requested; the bounded batch limit is "
                    f"{media_ingress.RECEIPT_QUERY_MAX_IDS}. Split the query."
                ),
                "max_capture_ids": media_ingress.RECEIPT_QUERY_MAX_IDS,
                "trace_id": trace_id,
            },
        )

    try:
        found = media_receipts.find_media_receipts_by_capture_ids(requested)
    except Exception as exc:
        # A read failure must not be reported as `unknown`: "never arrived" is a
        # load-bearing answer a client acts on (CDLM-03 deletes originals against
        # it), so an unavailable store says so instead of answering wrongly.
        logger.exception("heimdal receipt query failed trace_id=%s", trace_id)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "receipt_store_unavailable",
                "message": (
                    f"The receipt store could not be read ({type(exc).__name__}); no "
                    "admission state is being asserted. Retry — this query is read-only."
                ),
                "trace_id": trace_id,
            },
        ) from exc

    answers = [media_ingress.receipt_answer(found.get(value), value) for value in requested]
    return ReceiptQueryResponse(receipts=answers, trace_id=trace_id)


__all__ = ["router", "MediaSidecar", "MediaReceiptResponse", "ReceiptQueryResponse"]
