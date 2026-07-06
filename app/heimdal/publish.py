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

Full-payload assembly + validation (Epic #3019 slice A10, #3030). ``publish_observation``
above stays the low-level, schema-agnostic append primitive that earlier
slices' own tests exercise directly with deliberately partial payloads (A2's
plumbing tests, A3's quarantine tests) -- it is not rewritten here.
:func:`assemble_observation_payload` and :func:`publish_full_observation` are
this slice's addition: they build the complete ``heimdal.observation.published.v1``
payload per FABLE_COMPANION §1.3 (identity, bitemporal time, actors,
provenance families) from the upstream stage outputs (A8 ``TranscriptResult``,
A9 ``AttributionResult``), validate it against the registered schema (A4,
``app.events.topic_schema_registry.validate_topic_payload`` -- the same
choke point ``app.services.outbox.write_outbox_event`` uses for every other
registered topic, reused verbatim) BEFORE insert, and stamp
``provenance.content_hash`` in the same call that derives the idempotency key
and appends the row (KERNEL-06: provenance stamped in the same durable
write). A malformed payload raises :class:`TopicSchemaViolation` before any
insert is attempted -- fail loud, never insert-then-validate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.events.schema import make_outbox_event
from app.events.topic_schema_registry import validate_topic_payload
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


# ---------------------------------------------------------------------------
# Full-payload assembly + validated publish (A10, #3030)
# ---------------------------------------------------------------------------


def canonical_content_hash(content: Any) -> str:
    """sha256 of the canonicalized published content (FABLE_COMPANION §1.3 provenance).

    ``content_hash`` is "sha256 of the canonicalized published content,
    stamped in the same durable write as the event" (conform to KERNEL-06) --
    distinct from ``content_identity`` (the hash of the RAW evidence, minted
    upstream by :mod:`app.heimdal.raw_store`). Canonicalization mirrors
    :func:`app.services.outbox.payload_fingerprint`'s convention (sorted-key
    JSON, ``default=str`` for non-JSON-native values) so the same published
    content always hashes identically regardless of dict key order. Returns
    the ``"sha256:<hex>"`` form used throughout this payload family (mirrors
    ``content_identity``'s own prefix convention).
    """
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _attribution_to_dict(attribution: Any) -> Dict[str, Any]:
    if isinstance(attribution, Mapping):
        return dict(attribution)
    # Duck-types app.heimdal.attribution_stage.Attribution (a frozen dataclass)
    # without importing that module -- avoids a hard dependency edge from the
    # publish seam onto one specific stage's dataclass shape; any object
    # exposing these attributes assembles the same way.
    return {
        "mention_id": attribution.mention_id,
        "role": attribution.role,
        "resolution": attribution.resolution,
        "basis": attribution.basis,
        "confidence": getattr(attribution, "confidence", None),
    }


def _entity_mention_to_dict(mention: Any) -> Dict[str, Any]:
    if isinstance(mention, Mapping):
        return dict(mention)
    return {
        "mention_id": mention.mention_id,
        "surface_form": mention.surface_form,
        "resolution": mention.resolution,
        "kind_hint": getattr(mention, "kind_hint", None),
        "confidence": getattr(mention, "confidence", None),
        "span": getattr(mention, "span", None),
    }


def assemble_observation_payload(
    *,
    observation_id: str,
    episode_id: str,
    observed_at_start: str,
    attributions: Sequence[Any],
    confidence: Mapping[str, Any],
    provenance: Mapping[str, Any],
    consent: Mapping[str, Any],
    sensitivity: str = "private",
    sequence: Optional[int] = None,
    revision_of: Optional[str] = None,
    supersedes: Optional[str] = None,
    observed_at_end: Optional[str] = None,
    clock_basis: Optional[str] = None,
    captured_at: Optional[str] = None,
    entity_mentions: Optional[Sequence[Any]] = None,
    modality: Optional[str] = None,
    content: Optional[str] = None,
    content_structure: Optional[Mapping[str, Any]] = None,
    raw_ref: Optional[str] = None,
    withheld: Optional[Sequence[Mapping[str, Any]]] = None,
    scope_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble one ``heimdal.observation.published.v1`` payload (FABLE_COMPANION §1.3).

    Pure assembly: builds the field-family shape (identity, bitemporal time,
    actors, entities, content, confidence, provenance, sensitivity/consent)
    from already-computed stage outputs -- it does not call the ASR (A8) or
    attribution (A9) stages itself, and it does not validate or publish (see
    :func:`publish_full_observation` for the validating, publishing
    entrypoint that wraps this). ``attributions``/``entity_mentions`` accept
    either the stage dataclasses (``app.heimdal.attribution_stage.Attribution``
    / ``EntityMention``) or plain dicts, so callers do not need an extra
    conversion step. ``provenance.content_hash`` is intentionally NOT set
    here -- :func:`publish_full_observation` stamps it in the same durable
    write as the append (KERNEL-06), using this payload's own ``content``
    field as the canonicalized published content.
    """
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError(f"observation_id must be a non-empty string, got {observation_id!r}")
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise ValueError(f"episode_id must be a non-empty string, got {episode_id!r}")
    if not attributions:
        raise ValueError(
            "assemble_observation_payload requires at least one attribution "
            "(FABLE_COMPANION §1.3 payload rule 1)"
        )

    provenance_block: Dict[str, Any] = dict(provenance)
    if raw_ref is not None:
        provenance_block.setdefault("raw_ref", raw_ref)

    payload: Dict[str, Any] = {
        "observation_id": observation_id,
        "episode_id": episode_id,
        "sequence": sequence,
        "revision_of": revision_of,
        "supersedes": supersedes,
        "observed_at_start": observed_at_start,
        "observed_at_end": observed_at_end,
        "clock_basis": clock_basis,
        "captured_at": captured_at,
        "attributions": [_attribution_to_dict(a) for a in attributions],
        "entity_mentions": [_entity_mention_to_dict(m) for m in entity_mentions] if entity_mentions else [],
        "modality": modality,
        "content": content,
        "content_structure": dict(content_structure) if content_structure is not None else None,
        "raw_ref": raw_ref,
        "withheld": [dict(w) for w in withheld] if withheld else [],
        "confidence": dict(confidence),
        "provenance": provenance_block,
        "sensitivity": sensitivity,
        "scope_hint": scope_hint,
        "consent": dict(consent),
    }
    return payload


def publish_full_observation(
    *,
    topic: str,
    payload: Dict[str, Any],
    source: str,
    stage_versions: Mapping[str, Any] | None = None,
    trace_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> ObservationRow | None:
    """Validate and publish one fully-assembled observation payload (A10, #3030).

    The validating counterpart to :func:`publish_observation`: stamps
    ``provenance.content_hash`` (sha256 of the canonicalized ``content``,
    KERNEL-06) onto a copy of ``payload``, validates the result against the
    registered ``heimdal.observation.published.v1`` schema
    (``app.events.topic_schema_registry.validate_topic_payload`` -- the same
    choke point ``app.services.outbox.write_outbox_event`` uses, reused
    verbatim), and ONLY THEN appends it via :func:`publish_observation`. A
    malformed payload raises :class:`app.events.topic_schema_registry.TopicSchemaViolation`
    before any insert is attempted -- fail loud, never insert-then-validate.

    Revision-aware idempotency (delegated to :func:`publish_observation`):
    ``payload["observation_id"]`` is the fingerprint's ``source_id`` and
    ``stage_versions`` folds into the content fingerprint
    (:func:`observation_fingerprint`), so a re-processed revision of the same
    raw evidence (different ``stage_versions`` and/or a new ``revision_of``/
    ``supersedes`` value) derives a distinct, non-colliding key and always
    produces a new row, while a crash-retry of the identical revision dedups
    to the existing row (returns ``None``).
    """
    observation_id = payload.get("observation_id")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError(
            f"publish_full_observation requires payload['observation_id'] to be a "
            f"non-empty string, got {observation_id!r}"
        )

    stamped = dict(payload)
    provenance_block = dict(stamped.get("provenance") or {})
    provenance_block["content_hash"] = canonical_content_hash(stamped.get("content"))
    stamped["provenance"] = provenance_block

    validate_topic_payload(topic, stamped)

    return publish_observation(
        topic=topic,
        observation_id=observation_id,
        payload=stamped,
        source=source,
        stage_versions=stage_versions,
        trace_id=trace_id,
        meta=meta,
    )


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
    "assemble_observation_payload",
    "canonical_content_hash",
    "consume_observations",
    "derive_observation_idempotency_key",
    "observation_fingerprint",
    "publish_full_observation",
    "publish_observation",
    "read_observations_for_consumer",
]
