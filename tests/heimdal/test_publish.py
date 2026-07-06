"""Heimdal observation publish path: assemble, validate, insert (Epic #3019 slice A10, #3030).

Covers the issue's two behavioral Acceptance Criteria:

- ``test_revision_aware_idempotency`` -- a revision (re-run over the same raw
  evidence, e.g. an improved ``stage_versions``) publishes without colliding
  with or duplicating the prior observation; the idempotency key is
  revision-aware (distinct per revision, stable for a crash-retry of the SAME
  revision).
- ``test_payload_validates`` -- a well-formed payload assembled via
  :func:`app.heimdal.publish.assemble_observation_payload` validates against
  the §1.3 contract (the real registered schema, A4) and is durably inserted
  with ``provenance.content_hash`` stamped in the same write; a malformed
  payload is rejected BEFORE insert (no row is written).

All tests exercise the real production call sites:
``app.heimdal.publish.assemble_observation_payload`` /
``publish_full_observation`` (this slice), the real
``app.events.topic_schema_registry.validate_topic_payload`` choke point (A4,
the same one ``app.services.outbox.write_outbox_event`` uses for every other
registered topic), and the real append-only log
(``app.heimdal.observation_log``, A2) -- never a stubbed insert or a private
validator.
"""

from __future__ import annotations

import copy

import pytest

from app.events.topic_schema_registry import TopicSchemaViolation
from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal.attribution_stage import Attribution, EntityMention
from app.heimdal.cursor_store import reset_memory_cursor_store
from app.heimdal.observation_log import count_observations, reset_memory_observation_log
from app.heimdal.publish import (
    assemble_observation_payload,
    canonical_content_hash,
    publish_full_observation,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _reset_heimdal_stores():
    reset_memory_observation_log()
    reset_memory_cursor_store()
    yield
    reset_memory_observation_log()
    reset_memory_cursor_store()


def _consent_block() -> dict:
    return {
        "basis": "self_record",
        "granted_by": "operator",
        "granted_at": "2026-01-01T00:00:00+00:00",
        "third_party": "none",
        "grant_ref": "grant-self-record-v1",
    }


def _provenance_block(*, content_identity: str = "sha256:" + "b" * 64, stage_versions: dict | None = None) -> dict:
    return {
        "sensor": "ios_voice_memos_adapter/v1",
        "capture_chain": ["ios_voice_memos", "icloud_drive", "folder_watch"],
        "content_identity": content_identity,
        "stage_versions": stage_versions or {"asr": "whisper-small-1", "attribution": "v1"},
        "raw_ref": "heimraw:test-raw-1",
    }


def _confidence_block() -> dict:
    return {
        "transcription": {"score": 0.91, "method": "asr_avg_logprob", "calibration": "heuristic"},
        "attribution": {"score": 1.0, "calibration": "by_construction"},
    }


def _attributions() -> list[Attribution]:
    return [
        Attribution(
            mention_id="mention:speaker-1",
            role="speaker",
            resolution="resolved",
            basis="capture_context",
            confidence=1.0,
        )
    ]


def _entity_mentions() -> list[EntityMention]:
    return [
        EntityMention(
            mention_id="mention:ent-1",
            surface_form="Northvolt-projektet",
            resolution="unresolved",
            kind_hint="project",
            confidence=0.62,
        )
    ]


def _build_payload(
    *,
    observation_id: str,
    episode_id: str = "ep-0001",
    sequence: int | None = 0,
    revision_of: str | None = None,
    stage_versions: dict | None = None,
    content: str = "Idag pratade jag om Northvolt-projektet.",
    content_identity: str = "sha256:" + "b" * 64,
) -> dict:
    return assemble_observation_payload(
        observation_id=observation_id,
        episode_id=episode_id,
        sequence=sequence,
        revision_of=revision_of,
        observed_at_start="2026-07-06T09:12:00+02:00",
        observed_at_end="2026-07-06T09:14:30+02:00",
        clock_basis="device_metadata",
        captured_at="2026-07-06T09:20:00+02:00",
        attributions=_attributions(),
        entity_mentions=_entity_mentions(),
        modality="speech",
        content=content,
        content_structure={"segments": [{"start": 0.0, "end": 3.2}]},
        raw_ref="heimraw:test-raw-1",
        confidence=_confidence_block(),
        provenance=_provenance_block(content_identity=content_identity, stage_versions=stage_versions),
        sensitivity="private",
        scope_hint="operator_capture_private",
        consent=_consent_block(),
    )


def _publish(payload: dict, *, stage_versions: dict | None = None):
    return publish_full_observation(
        topic=HEIMDAL_OBSERVATION_PUBLISHED,
        payload=payload,
        source="heimdal.capture",
        stage_versions=stage_versions or payload["provenance"].get("stage_versions"),
    )


# --- AC1: revision-aware idempotency ------------------------------------------


def test_revision_aware_idempotency() -> None:
    """A revision (re-run over the same raw) publishes without colliding/duplicating.

    Same raw evidence (same ``content_identity``/``episode_id``), first run
    at ``stage_versions={"asr": "whisper-small-1", ...}``: publishes one row.
    A crash-retry of the EXACT SAME revision (identical payload, identical
    stage_versions) must dedup to the existing row (idempotent, no duplicate
    -- same key). A genuine revision (improved ``stage_versions``, carrying
    ``revision_of``) must produce a DISTINCT, non-colliding key and a NEW
    row -- never swallowed against the original.
    """
    original_payload = _build_payload(
        observation_id="obs-0001",
        stage_versions={"asr": "whisper-small-1", "attribution": "v1"},
    )

    first = _publish(original_payload)
    assert first is not None
    assert count_observations() == 1

    # Crash-retry: identical payload, identical stage_versions -> same key,
    # deduped (no new row, no collision error).
    retry_payload = copy.deepcopy(original_payload)
    retry = _publish(retry_payload)
    assert retry is None  # swallowed duplicate, per publish_observation contract
    assert count_observations() == 1

    # Revision: re-processing the SAME raw evidence through an improved ASR
    # model. New observation_id (a revision is a new observation per HEIM-1
    # -- the log never rewrites), revision_of references the prior
    # observation, stage_versions differs.
    revised_payload = _build_payload(
        observation_id="obs-0001-rev1",
        revision_of="obs-0001",
        sequence=1,
        stage_versions={"asr": "whisper-medium-2", "attribution": "v1"},
        content="Idag pratade jag om Northvolt-projektet igen, tydligare.",
    )
    revised = _publish(revised_payload, stage_versions={"asr": "whisper-medium-2", "attribution": "v1"})
    assert revised is not None
    assert count_observations() == 2  # distinct row, not swallowed against obs-0001

    assert first.idempotency_key != revised.idempotency_key
    assert first.id != revised.id

    # The revision's own key is stable across a repeat crash-retry too.
    revised_retry_payload = copy.deepcopy(revised_payload)
    revised_retry = _publish(revised_retry_payload, stage_versions={"asr": "whisper-medium-2", "attribution": "v1"})
    assert revised_retry is None
    assert count_observations() == 2


def test_revision_via_supersedes_also_distinct() -> None:
    """A correction (``supersedes``) is likewise a distinct, non-colliding publish."""
    original_payload = _build_payload(observation_id="obs-corr-base")
    original = _publish(original_payload)
    assert original is not None

    correction_payload = _build_payload(
        observation_id="obs-corr-base-c1",
        content="corrected transcript text",
    )
    correction_payload["supersedes"] = "obs-corr-base"
    correction = _publish(correction_payload)
    assert correction is not None
    assert count_observations() == 2
    assert original.idempotency_key != correction.idempotency_key


# --- AC2: payload validates / malformed rejected before insert ----------------


def test_payload_validates() -> None:
    """A well-formed payload validates and is durably inserted with content_hash stamped."""
    payload = _build_payload(observation_id="obs-valid-1")
    assert "content_hash" not in payload["provenance"]  # not stamped by assembly itself

    row = _publish(payload)
    assert row is not None
    assert count_observations() == 1

    stored_payload = row.envelope["payload"]
    assert stored_payload["provenance"]["content_hash"] == canonical_content_hash(payload["content"])
    assert stored_payload["provenance"]["content_hash"].startswith("sha256:")
    # Stamped in the SAME durable write (KERNEL-06) -- the row that exists
    # already carries the hash; there is no separate "stamp later" step.
    assert stored_payload["observation_id"] == "obs-valid-1"


def test_malformed_payload_rejected_before_insert() -> None:
    """A malformed payload is rejected before insert -- no row is written."""
    payload = _build_payload(observation_id="obs-invalid-1")

    # Missing consent.grant_ref (HEIM-3).
    missing_grant_ref = copy.deepcopy(payload)
    del missing_grant_ref["consent"]["grant_ref"]
    with pytest.raises(TopicSchemaViolation):
        _publish(missing_grant_ref)
    assert count_observations() == 0

    # Missing at least one attribution (payload rule 1).
    missing_attribution = copy.deepcopy(payload)
    missing_attribution["attributions"] = []
    with pytest.raises(TopicSchemaViolation):
        _publish(missing_attribution)
    assert count_observations() == 0

    # Missing a required time-family field (observed_at_start, HEIM-10).
    missing_time = copy.deepcopy(payload)
    del missing_time["observed_at_start"]
    with pytest.raises(TopicSchemaViolation):
        _publish(missing_time)
    assert count_observations() == 0

    # Missing provenance.content_identity/capture_chain (payload rule 1).
    missing_provenance = copy.deepcopy(payload)
    del missing_provenance["provenance"]["content_identity"]
    with pytest.raises(TopicSchemaViolation):
        _publish(missing_provenance)
    assert count_observations() == 0

    # A well-formed payload still succeeds afterward -- the rejections above
    # left no partial/poisoned state behind.
    valid = _publish(payload)
    assert valid is not None
    assert count_observations() == 1


def test_assemble_observation_payload_requires_at_least_one_attribution() -> None:
    with pytest.raises(ValueError):
        assemble_observation_payload(
            observation_id="obs-x",
            episode_id="ep-x",
            observed_at_start="2026-07-06T09:12:00+02:00",
            attributions=[],
            confidence=_confidence_block(),
            provenance=_provenance_block(),
            consent=_consent_block(),
        )


def test_assemble_observation_payload_accepts_plain_dict_attributions() -> None:
    """Assembly duck-types dataclass or dict attribution/mention inputs identically."""
    dict_payload = assemble_observation_payload(
        observation_id="obs-dict-1",
        episode_id="ep-0001",
        observed_at_start="2026-07-06T09:12:00+02:00",
        attributions=[
            {
                "mention_id": "mention:speaker-1",
                "role": "speaker",
                "resolution": "resolved",
                "basis": "capture_context",
                "confidence": 1.0,
            }
        ],
        confidence=_confidence_block(),
        provenance=_provenance_block(),
        consent=_consent_block(),
    )
    dataclass_payload = assemble_observation_payload(
        observation_id="obs-dc-1",
        episode_id="ep-0001",
        observed_at_start="2026-07-06T09:12:00+02:00",
        attributions=_attributions(),
        confidence=_confidence_block(),
        provenance=_provenance_block(),
        consent=_consent_block(),
    )
    assert dict_payload["attributions"] == dataclass_payload["attributions"]


def test_canonical_content_hash_stable_and_content_sensitive() -> None:
    """Same content -> same hash; different content -> different hash (canonicalized, not raw-string)."""
    assert canonical_content_hash("hello") == canonical_content_hash("hello")
    assert canonical_content_hash("hello") != canonical_content_hash("hello world")
    assert canonical_content_hash("hello").startswith("sha256:")
