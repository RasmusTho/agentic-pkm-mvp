"""Closed v2 payload contracts for the seven kernel topics at the write seam (#5704).

Audit #2899 F6: the original seven kernel topic schemas were open
(``additionalProperties: true``) and several required no consumer input. These
tests drive the real ``app/services/outbox.py::write_outbox_event`` seam (and the
real ``insert_object_and_outbox`` helper where producers go through it) against
a recording connection, so a rejection is proven to happen *before* any SQL is
executed and an acceptance is proven to stamp the new ``<topic>.v2`` ref.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.state_axes import _LEGACY_REVIEW_STATE_ALIASES, normalize_artifact_state_axes
from app.events.models import new_event
from app.events.topic_schema_registry import TopicSchemaViolation, current_schema_ref
from app.services.outbox import insert_object_and_outbox, write_outbox_event

pytestmark = pytest.mark.not_pg

KERNEL_TOPICS = (
    "ingest.object.created",
    "ingest.vault.changed",
    "ingest.object.deleted",
    "panel.scan.requested",
    "promote.intent.created",
    "note.move.workbench",
    "index.embedding.requested",
)

OBJECT_ID = "5f0c3a52-8d61-4f7e-9d0a-2b1f7c1e9a10"


class _RecordingConn:
    """Captures every INSERT the write seam executes; returns the row id."""

    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []

    def cursor(self) -> "_RecordingConn":
        return self

    def execute(self, sql: str, params: tuple) -> "_RecordingConn":
        self._params = params
        if sql.lower().lstrip().startswith("insert into outbox"):
            self.inserts.append((params[1], json.loads(params[2])))
        return self

    def fetchone(self):
        return (self._params[0],)

    def close(self) -> None:
        pass


def _write(topic: str, payload: dict[str, Any], conn: _RecordingConn, key: str) -> str:
    return write_outbox_event(
        new_event(event_type=topic, payload=payload), conn=conn, idempotency_key=key
    )


# (topic, payload, what makes it malformed)
_MALFORMED: list[tuple[str, dict[str, Any], str]] = [
    # missing required consumer input
    ("ingest.object.created", {"kind": "note", "title": "t"}, "missing identity"),
    ("ingest.object.created", {"uuid": "", "object_id": None}, "empty identity"),
    ("ingest.object.deleted", {"path": "/v/n.md", "deleted": True}, "missing identity"),
    ("ingest.vault.changed", {"mtime": 1.0, "hash": "h"}, "missing path"),
    ("panel.scan.requested", {"relative_path": ""}, "empty path"),
    ("promote.intent.created", {"instruction": "promote"}, "missing note"),
    ("promote.intent.created", {"note": {"title": "t", "path": "/v/n.md"}}, "note without uuid"),
    ("promote.intent.created", {"note": {"uuid": OBJECT_ID}}, "note without any path"),
    ("promote.intent.created", {"note_uuid": OBJECT_ID, "note_path": "/v/n.md"}, "no note.uuid for consumer"),
    ("note.move.workbench", {"params": {"destination_zone": "workbench"}}, "missing note_path"),
    ("index.embedding.requested", {}, "missing object_id"),
    # invalid field types
    ("ingest.object.created", {"uuid": OBJECT_ID, "frontmatter": "x: 1"}, "frontmatter type"),
    ("ingest.object.deleted", {"uuid": OBJECT_ID, "deleted": "yes"}, "deleted type"),
    ("ingest.vault.changed", {"vault_path": 7}, "vault_path type"),
    ("panel.scan.requested", {"vault_path": "/v/n.md", "mtime": [1]}, "mtime type"),
    ("promote.intent.created", {"note": "note-1"}, "note type"),
    ("note.move.workbench", {"note_path": "/v/n.md", "params": "workbench"}, "params type"),
    ("index.embedding.requested", {"object_id": 42}, "object_id type"),
    ("panel.scan.requested", {"vault_path": "/v/n.md", "_worker_retry_count": "1"}, "retry count type"),
    ("ingest.vault.changed", {"vault_path": "/v/n.md", "extensions": "x"}, "extensions type"),
    # undeclared top-level fields
    ("ingest.object.created", {"uuid": OBJECT_ID, "surprise": 1}, "undeclared field"),
    ("ingest.vault.changed", {"vault_path": "/v/n.md", "surprise": 1}, "undeclared field"),
    ("ingest.object.deleted", {"object_id": OBJECT_ID, "surprise": 1}, "undeclared field"),
    ("panel.scan.requested", {"vault_path": "/v/n.md", "surprise": 1}, "undeclared field"),
    ("promote.intent.created", {"note": {"uuid": OBJECT_ID, "path": "/v/n.md"}, "surprise": 1}, "undeclared field"),
    ("note.move.workbench", {"note_path": "/v/n.md", "surprise": 1}, "undeclared field"),
    ("index.embedding.requested", {"object_id": OBJECT_ID, "surprise": 1}, "undeclared field"),
]


def test_write_seam_rejects_malformed_kernel_payloads() -> None:
    assert {case[0] for case in _MALFORMED} == set(KERNEL_TOPICS)
    for index, (topic, payload, why) in enumerate(_MALFORMED):
        conn = _RecordingConn()
        with pytest.raises(TopicSchemaViolation) as excinfo:
            _write(topic, payload, conn, f"malformed-{index}")
        assert excinfo.value.schema_ref == f"{topic}.v2", why
        assert conn.inserts == [], f"{topic} ({why}) reached the database insert"


def _promotion_event_payload() -> dict[str, Any]:
    """The real rich producer shape from the panel agent graph."""
    from app.agents.panel_agent.graph import _promotion_event
    from app.events.panel import (
        NoteRef,
        PanelActionMapping,
        PanelInfo,
        PanelIntentAction,
        PanelIntentEvent,
        PanelIntentPayload,
    )

    action = PanelIntentAction(
        id="promote.evergreen",
        label="Make this note evergreen",
        checked=True,
        mapping=PanelActionMapping(
            id="promote.evergreen",
            intent_type="promotion",
            downstream_event="promote.intent.created",
            trust_verb="PROMOTE",
            params={"maturity": "evergreen"},
        ),
    )
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=OBJECT_ID, path="/vault/inbox/n.md"),
            panel=PanelInfo(panel_id="panel-1", instruction="promote", raw_block=""),
            actions=[action],
        )
    )
    return _promotion_event(intent, action).payload


def _legacy_panel_promotion_payload() -> dict[str, Any]:
    """The real legacy panel-agent shape written by ``app/watcher/registry.py``."""
    from app.agents.panel.events import panel_intent_to_event
    from app.agents.panel.intents import PanelIntent
    from app.settings.panel_actions import _entries_to_mappings

    (mapping,) = _entries_to_mappings(
        {
            "id": "promote.evergreen",
            "label": "Make this note evergreen",
            "intent_type": "promotion",
            "downstream_event": "review.promote.evergreen",
            "params": {"maturity": "evergreen"},
        }
    )
    event = panel_intent_to_event(
        PanelIntent(kind="action_triggered", action_text=mapping.text, action_id="promote.evergreen"),
        {mapping.text: mapping},
        note_id=OBJECT_ID,
        instruction_text="make it evergreen",
        note_path="/vault/inbox/n.md",
    )
    assert event is not None and event.event == "promote.intent.created"
    assert event.payload["downstream_event"] == "review.promote.evergreen"
    return event.payload


_RETRY_FIELDS = {
    "_worker_retry_count": 1,
    "_worker_retry_reason": "file_unstable",
    "_worker_retry_enqueued_at": "2026-10-01T00:00:00Z",
}

_WATCH = {
    "vault_path": "/vault/inbox/n.md",
    "relative_path": "inbox/n.md",
    "mtime": 1727740800.5,
    "hash": None,
    "watcher": "inbox",
}

# Direct write_outbox_event producer alternatives: (label, topic, payload).
_DIRECT_VARIANTS: list[tuple[str, str, dict[str, Any]]] = [
    ("cli pipe", "ingest.object.created", {"object_id": OBJECT_ID, "source_ref": "/tmp/in.txt", "trace_id": "t"}),
    ("watcher panel scan", "panel.scan.requested", dict(_WATCH)),
    ("worker panel retry", "panel.scan.requested", {**_WATCH, **_RETRY_FIELDS}),
    # run() copies the envelope event_id into the payload before dispatch, so a
    # retry re-emitted from the daemon loop carries it too.
    ("daemon-loop retry", "panel.scan.requested", {**_WATCH, **_RETRY_FIELDS, "event_id": "evt-1"}),
    ("panel graph promotion", "promote.intent.created", _promotion_event_payload()),
    ("legacy panel agent promotion", "promote.intent.created", _legacy_panel_promotion_payload()),
    (
        "note object without path, top-level note_path",
        "promote.intent.created",
        {"note": {"uuid": OBJECT_ID}, "note_path": "/vault/n.md", "action_id": "promote.evergreen"},
    ),
    (
        "orchestrator promotion",
        "promote.intent.created",
        {
            "note": {"uuid": OBJECT_ID, "path": "/vault/n.md", "title": "N"},
            "action": {"id": "promote", "label": "promote"},
            "instruction": "promote",
            "maturity": "evergreen",
            "review_state": "reviewed",
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
        },
    ),
    (
        "panel downstream zone move",
        "note.move.workbench",
        {
            "note_uuid": OBJECT_ID,
            "note_path": "/vault/inbox/n.md",
            "action_id": "note.move.workbench",
            "params": {"source_zone": "inbox", "destination_zone": "workbench", "custom": True},
        },
    ),
    ("embedding request", "index.embedding.requested", {"object_id": OBJECT_ID}),
    ("extension point", "index.embedding.requested", {"object_id": OBJECT_ID, "extensions": {"x": 1}}),
]

# insert_object_and_outbox producer alternatives (helper adds object_id/trace_id/event).
_HELPER_VARIANTS: list[tuple[str, str, dict[str, Any], str | None]] = [
    ("object store save", "ingest.object.created", {"uuid": OBJECT_ID, "kind": "note"}, OBJECT_ID),
    (
        "api ingest (real state-axes normalization of a legacy review_state)",
        "ingest.object.created",
        normalize_artifact_state_axes(
            {
                "uuid": OBJECT_ID,
                "title": "T",
                "review_state": sorted(_LEGACY_REVIEW_STATE_ALIASES)[0],
                "content": "body",
                "origin": "api",
                "trust": "user",
                "source_ref": "api",
            },
            default_review_state="draft",
        ),
        OBJECT_ID,
    ),
    (
        "vault sync create",
        "ingest.object.created",
        {
            "uuid": OBJECT_ID,
            "object_id": OBJECT_ID,
            "vault_uuid": "retained-uuid",
            "title": "T",
            "review_state": "draft",
            "maturity": None,
            "content": "body",
            "path": "/vault/n.md",
            "frontmatter": {"uuid": "retained-uuid"},
            "episode_ref": "unbound",
            "replay": {"source": "x"},
        },
        None,
    ),
    (
        "vault sync delete",
        "ingest.object.deleted",
        {
            "path": "/vault/n.md",
            "deleted": True,
            "reason": "vault_note_deleted",
            "source": "vault_sync.delete_note",
            "uuid": OBJECT_ID,
            "object_id": OBJECT_ID,
            "vault_uuid": "retained-uuid",
        },
        None,
    ),
    ("watcher vault change", "ingest.vault.changed", dict(_WATCH), None),
]


def test_kernel_producer_variants_pass_write_validation() -> None:
    covered: set[str] = set()
    for index, (label, topic, payload) in enumerate(_DIRECT_VARIANTS):
        conn = _RecordingConn()
        assert _write(topic, payload, conn, f"variant-{index}"), label
        (inserted_topic, stored), = conn.inserts
        assert inserted_topic == topic, label
        assert stored["meta"]["payload_schema"] == current_schema_ref(topic) == f"{topic}.v2", label
        covered.add(topic)
    for label, topic, payload, object_id in _HELPER_VARIANTS:
        conn = _RecordingConn()
        assert insert_object_and_outbox(payload, topic, "trace-1", object_id=object_id, conn=conn), label
        (inserted_topic, stored), = conn.inserts
        assert inserted_topic == topic, label
        assert stored["payload"]["event"] == topic, label
        assert stored["meta"]["payload_schema"] == f"{topic}.v2", label
        covered.add(topic)
    assert covered == set(KERNEL_TOPICS)
