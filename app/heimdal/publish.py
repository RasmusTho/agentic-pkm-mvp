"""Heimdal observation publish path -- the Heimdal <-> Mimer constituent seam (#3039).

ADR-0049 §1: Heimdal owns watch -> fetch -> transcribe -> attribute ->
published event; Mimer owns cognition from the handoff. This module is the
handoff: producers call :func:`publish_observation` to append an observation
event to the log; consumers call :func:`read_observations_for_consumer` /
:func:`consume_observations` to read forward from their own cursor. Neither
side ever touches the other's storage directly -- Mimer must not import
``app.heimdal.observation_log`` and read the table itself (issue Constraints:
"no direct DB imports across boundaries"); this module's read function is the
only sanctioned read path.

Envelope reuse (FABLE_COMPANION §1.2): the outer envelope is the existing
``app.events.schema.make_outbox_event``/``OutboxEvent`` shape verbatim.
``timestamp`` on that envelope is **emission time only**; observation time
(``observed_at_start``/``observed_at_end``, HEIM-10) belongs in the caller's
payload, this module does not read or set it.

Idempotency (KERNEL-02 discipline, reused verbatim from
``app.services.outbox.derive_idempotency_key``): the deterministic key is
``derive_idempotency_key(topic, source_id, content_fingerprint)``. Per
FABLE_COMPANION §4.2, ``source_id`` = the observation id and the fingerprint
should include ``stage_versions`` so a crash-retry of the same publication
(same observation, same stage versions) dedups, while a revision (new/changed
stage_versions) or correction produces a distinct key and a new row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.events.schema import make_outbox_event
from app.services.outbox import derive_idempotency_key, payload_fingerprint

from .cursor_store import advance_cursor, get_cursor
from .observation_log import ObservationRow, append_observation, read_observations_from

_TOPIC_FAMILY_PREFIX = "heimdal.observation."


def _validate_topic(topic: str) -> None:
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError(f"publish_observation requires a non-empty topic, got {topic!r}")
    if not topic.startswith(_TOPIC_FAMILY_PREFIX):
        raise ValueError(
            f"publish_observation topic {topic!r} must be in the "
            f"{_TOPIC_FAMILY_PREFIX!r} family (FABLE_COMPANION §1.1)"
        )


def derive_observation_idempotency_key(
    *,
    topic: str,
    observation_id: str,
    content_fingerprint: str,
) -> str:
    """Derive the deterministic key for one observation publication.

    Thin, named wrapper over the shared
    ``app.services.outbox.derive_idempotency_key`` (reused verbatim, not
    forked -- KERNEL-02/I-E1). ``observation_id`` is ``source_id``;
    ``content_fingerprint`` should already fold in whatever makes a
    republish of the SAME evidence produce the SAME key while a revision
    (improved ``stage_versions``) or correction produces a DIFFERENT one --
    see :func:`observation_fingerprint` for the recommended construction.
    """
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError(f"observation_id must be a non-empty string, got {observation_id!r}")
    _validate_topic(topic)
    return derive_idempotency_key(topic, observation_id, content_fingerprint)


def observation_fingerprint(
    payload: Mapping[str, Any],
    *,
    stage_versions: Mapping[str, Any] | None = None,
) -> str:
    """Build the content fingerprint for one observation publication.

    Folds ``stage_versions`` (FABLE_COMPANION §4.2/§5.2: ASR/attribution/
    resolution stage versions) into the fingerprinted content alongside the
    payload, mirroring the ``observation=`` marker pattern in
    ``app.services.outbox.insert_object_and_outbox`` and
    ``app.services.outbox.payload_fingerprint``'s documented ``exclude``
    convention: same observation + same stages -> same fingerprint (crash-
    retry dedups); same observation + different (improved) stages -> a
    different fingerprint, so replay/re-processing produces a genuinely new,
    distinct key (a revision), never swallowed against the original row.
    """
    source: Dict[str, Any] = dict(payload)
    if stage_versions is not None:
        if "__stage_versions__" in source:
            raise ValueError("payload field '__stage_versions__' is reserved for fingerprint scoping")
        source["__stage_versions__"] = dict(stage_versions)
    return payload_fingerprint(source, exclude=("trace_id",))


def publish_observation(
    *,
    topic: str,
    observation_id: str,
    payload: Dict[str, Any],
    source: str,
    stage_versions: Mapping[str, Any] | None = None,
    trace_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> ObservationRow | None:
    """Publish one observation event to the Heimdal observation log.

    Builds the reused outbox envelope (``make_outbox_event`` -- envelope
    ``timestamp`` is emission time only), derives the mandatory idempotency
    key from ``(topic, observation_id, fingerprint(payload, stage_versions))``,
    and appends to the append-only log (:func:`app.heimdal.observation_log.append_observation`).

    Returns the written :class:`ObservationRow`, or ``None`` when the
    idempotency key already exists (a crash-retry re-publish of the same
    evidence at the same stage versions -- idempotent, no duplicate row). A
    revision (changed ``stage_versions``) or a correction (caller passes a
    payload whose fingerprint differs, e.g. because it carries a new
    ``supersedes``/``revision_of`` value) derives a distinct key and always
    produces a new row.
    """
    _validate_topic(topic)
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError(f"observation_id must be a non-empty string, got {observation_id!r}")

    fingerprint = observation_fingerprint(payload, stage_versions=stage_versions)
    idempotency_key = derive_observation_idempotency_key(
        topic=topic,
        observation_id=observation_id,
        content_fingerprint=fingerprint,
    )
    envelope = make_outbox_event(
        topic,
        source=source,
        trace_id=trace_id,
        payload=dict(payload),
        meta=dict(meta or {}),
    )
    return append_observation(envelope, idempotency_key=idempotency_key)


def read_observations_for_consumer(consumer_id: str, *, limit: int | None = None) -> List[ObservationRow]:
    """Read the next unread observations for ``consumer_id``, without advancing its cursor.

    A consumer_id never seen before reads from sequence 0 (rebuild from
    event zero). Reading never mutates the cursor -- call
    :func:`advance_cursor_for_consumer` explicitly once the batch is
    durably processed downstream, so a crash between read and processing
    does not lose the batch (at-least-once delivery, FABLE_COMPANION §4.2).
    """
    position = get_cursor(consumer_id)
    return read_observations_from(position, limit=limit)


def advance_cursor_for_consumer(consumer_id: str, observations: List[ObservationRow]) -> None:
    """Advance ``consumer_id``'s cursor past the given (already-processed) observations.

    A no-op on an empty batch. Moves the cursor to ``max(sequence) + 1``
    among the given rows -- only this consumer's position changes.
    """
    if not observations:
        return
    next_position = max(row.sequence for row in observations) + 1
    advance_cursor(consumer_id, next_position)


def consume_observations(consumer_id: str, *, limit: int | None = None) -> List[ObservationRow]:
    """Read the next batch for ``consumer_id`` and advance its cursor past it.

    Convenience wrapper for callers that process synchronously and want
    read+advance in one call. Callers who need "durably process, then
    advance" semantics should call :func:`read_observations_for_consumer`
    and :func:`advance_cursor_for_consumer` separately instead.
    """
    batch = read_observations_for_consumer(consumer_id, limit=limit)
    advance_cursor_for_consumer(consumer_id, batch)
    return batch


__all__ = [
    "advance_cursor_for_consumer",
    "consume_observations",
    "derive_observation_idempotency_key",
    "observation_fingerprint",
    "publish_observation",
    "read_observations_for_consumer",
]
