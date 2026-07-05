"""Heimdal event contract schemas (Epic #3019 slice A4, #3041).

Covers the issue's two behavioral Acceptance Criteria:

- ``test_published_v1_schema_valid`` -- a well-formed
  ``heimdal.observation.published.v1`` payload validates against its
  registered schema; a payload missing ``consent.grant_ref`` OR a required
  time-family field is rejected.
- ``test_stub_topics_registered`` -- the ``consent.granted``,
  ``consent.revoked``, and ``observation.corrected`` topics are present as
  contract-stubs: schema-representable (a well-formed payload validates
  against a registered schema), but with no runtime dependency -- neither
  topic is dispatched by ``app.workers.outbox_worker._dispatch_topic``, and
  none of the three modules involved (``app.heimdal.observation_log``,
  ``app.heimdal.publish``, ``app.heimdal.cursor_store``) reference them.

Validation reaches the real production entry point: this slice reuses the
KERNEL-08 topic schema registry (``app.events.topic_schema_registry``)
verbatim, the same choke point used at outbox write
(``app.services.outbox.write_outbox_event``) and dispatch
(``app.workers.outbox_worker._dispatch_topic``) for every other registered
topic -- not a private/stubbed validator invented for this test.
"""

from __future__ import annotations

import ast
import copy
import inspect

import pytest

import app.workers.outbox_worker as outbox_worker
from app.events.topic_schema_registry import (
    TopicSchemaViolation,
    is_registered_topic,
    validate_topic_payload,
)
from app.events.types import (
    HEIMDAL_CONSENT_GRANTED,
    HEIMDAL_CONSENT_REVOKED,
    HEIMDAL_OBSERVATION_CORRECTED,
    HEIMDAL_OBSERVATION_PUBLISHED,
)

pytestmark = pytest.mark.not_pg


def _valid_published_payload() -> dict:
    """A well-formed heimdal.observation.published.v1 payload per FABLE_COMPANION §1.3."""
    return {
        "observation_id": "obs-0001",
        "episode_id": "ep-0001",
        "sequence": 0,
        "revision_of": None,
        "supersedes": None,
        "observed_at_start": "2026-07-06T09:12:00+02:00",
        "observed_at_end": "2026-07-06T09:14:30+02:00",
        "clock_basis": "device_metadata",
        "captured_at": "2026-07-06T09:20:00+02:00",
        "attributions": [
            {
                "mention_id": "mention-speaker-1",
                "role": "speaker",
                "resolution": "resolved",
                "confidence": 1.0,
                "basis": "capture_context",
            }
        ],
        "entity_mentions": [
            {
                "mention_id": "mention-ent-1",
                "surface_form": "Northvolt-projektet",
                "kind_hint": "project",
                "resolution": "unresolved",
                "confidence": 0.62,
            }
        ],
        "modality": "speech",
        "content": "Idag pratade jag om Northvolt-projektet.",
        "content_structure": {"segments": [{"start": 0.0, "end": 3.2}]},
        "raw_ref": "raw:opaque-id-0001",
        "withheld": [],
        "confidence": {
            "transcription": {"score": 0.91, "method": "asr_avg_logprob", "calibration": "heuristic"},
            "attribution": {"score": 1.0, "calibration": "by_construction"},
            "entity_resolution": {"score": 0.62, "calibration": "heuristic"},
            "temporal": {"score": 0.95, "calibration": "heuristic"},
        },
        "provenance": {
            "sensor": "ios_voice_memos_adapter/v1",
            "capture_chain": ["ios_voice_memos", "icloud_drive", "folder_watch"],
            "content_hash": "sha256:" + "a" * 64,
            "content_identity": "sha256:" + "b" * 64,
            "stage_versions": {"asr": "whisper-small-1", "attribution": "v1", "resolution": "v1"},
            "raw_ref": "raw:opaque-id-0001",
        },
        "sensitivity": "private",
        "scope_hint": "operator_capture_private",
        "consent": {
            "basis": "self_record",
            "granted_by": "operator",
            "granted_at": "2026-01-01T00:00:00+00:00",
            "third_party": "none",
            "grant_ref": "grant-0001",
        },
    }


def test_published_v1_schema_valid() -> None:
    """A well-formed payload validates; missing consent.grant_ref or a required time field is rejected."""
    assert is_registered_topic(HEIMDAL_OBSERVATION_PUBLISHED)

    payload = _valid_published_payload()
    validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, payload)  # must not raise

    # Missing consent.grant_ref (HEIM-3) is rejected.
    missing_grant_ref = copy.deepcopy(payload)
    del missing_grant_ref["consent"]["grant_ref"]
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, missing_grant_ref)

    # An empty grant_ref is equally a violation -- the field must be a non-empty ref.
    empty_grant_ref = copy.deepcopy(payload)
    empty_grant_ref["consent"]["grant_ref"] = ""
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, empty_grant_ref)

    # Missing a required time-family field (observed_at_start, HEIM-10) is rejected.
    missing_time = copy.deepcopy(payload)
    del missing_time["observed_at_start"]
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, missing_time)

    # Missing consent entirely is rejected (consent required on every event, HEIM-3).
    missing_consent = copy.deepcopy(payload)
    del missing_consent["consent"]
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, missing_consent)

    # Missing at least one attribution is rejected (payload rule 1, §1.3).
    missing_attribution = copy.deepcopy(payload)
    missing_attribution["attributions"] = []
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, missing_attribution)

    # Missing provenance.content_hash/content_identity/capture_chain is rejected (payload rule 1).
    missing_provenance_field = copy.deepcopy(payload)
    del missing_provenance_field["provenance"]["content_hash"]
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, missing_provenance_field)


def test_published_v1_rejects_unknown_resolution_and_calibration_values() -> None:
    """Enum discipline: three-state resolution (HEIM-6/HEIM-11) and calibration markers are closed sets."""
    payload = _valid_published_payload()

    bad_resolution = copy.deepcopy(payload)
    bad_resolution["attributions"][0]["resolution"] = "guessed"
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, bad_resolution)

    bad_calibration = copy.deepcopy(payload)
    bad_calibration["confidence"]["transcription"]["calibration"] = "vibes"
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, bad_calibration)


def test_stub_topics_registered() -> None:
    """consent.granted / consent.revoked / observation.corrected are contract-stubs.

    Schema-representable now (a well-formed payload validates against a
    registered schema) with no runtime dependency: none of the three stub
    topics appear in the live dispatch table, and none are referenced by the
    Heimdal observation-log/publish modules that exist today.
    """
    stub_topics_and_payloads = {
        HEIMDAL_CONSENT_GRANTED: {
            "grant_ref": "grant-0001",
            "basis": "self_record",
            "granted_by": "operator",
            "granted_at": "2026-01-01T00:00:00+00:00",
        },
        HEIMDAL_CONSENT_REVOKED: {
            "grant_ref": "grant-0001",
            "revoked_at": "2026-02-01T00:00:00+00:00",
            "covered_episode_ids": ["ep-0001"],
        },
        HEIMDAL_OBSERVATION_CORRECTED: {
            "supersedes": "obs-0001",
            "corrects": "attribution_id",
            "replacement": {"resolution": "resolved", "confidence": 0.98},
            "basis": "stated",
            "actor": "operator",
        },
    }

    for topic, payload in stub_topics_and_payloads.items():
        assert is_registered_topic(topic), f"stub topic {topic!r} has no registered schema"
        validate_topic_payload(topic, payload)  # schema-representable: must not raise

    # No runtime dependency: none of these topics are branched on in the live
    # dispatch table (mirrors tests/events/test_topic_schema_registry.py's own
    # AST-walk technique, applied here as a negative assertion).
    source = inspect.getsource(outbox_worker._dispatch_topic)
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    dispatched: set[str] = set()
    for node in ast.walk(func_def):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            dispatched.add(node.value)

    for topic in stub_topics_and_payloads:
        assert topic not in dispatched, f"stub topic {topic!r} must not be dispatched yet"

    # No runtime dependency: the published-observation modules (A2, #3039)
    # don't import or reference any of the stub topic constants.
    for module in ("app.heimdal.observation_log", "app.heimdal.publish", "app.heimdal.cursor_store"):
        src = inspect.getsource(__import__(module, fromlist=["_"]))
        for topic in stub_topics_and_payloads:
            assert topic not in src, f"stub topic {topic!r} unexpectedly referenced in {module}"


def test_stub_topics_reject_incomplete_payloads() -> None:
    """Contract-stub schemas still enforce their required shape (§3.5 / §6.1 / §6.4)."""
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_CONSENT_GRANTED, {"basis": "self_record"})  # missing grant_ref

    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload(HEIMDAL_CONSENT_REVOKED, {})  # missing grant_ref/revoked_at

    with pytest.raises(TopicSchemaViolation):
        # missing 'replacement' -- corrections must carry the same-shape replacement fragment
        validate_topic_payload(
            HEIMDAL_OBSERVATION_CORRECTED,
            {"supersedes": "obs-0001", "corrects": "attribution_id", "basis": "stated"},
        )
