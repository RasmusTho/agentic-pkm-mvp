"""Receipts v2 display-field enrichment (#3363).

``app/receipts/artifact_receipts.py`` projects governed outbox records
(``panel.action.logged`` / ``panel.action.blocked``) into read-only receipt
rows. This is an additive-only enrichment: every existing field
(``receipt_id``, ``trace_id``, ``action_id``, ``action_type``,
``artifact_uuid``, ``artifact_path``, ``path``, ``requested_by``,
``approved_by``, ``status``, ``timestamp``, ``state``) keeps its name and
value exactly as before. The projection additionally declares
``display_verb``, ``run_key``, ``run_label``, and ``target_absolute``, with
documented fallbacks (``"Recorded"`` / ``"Run"``) when the governed record
does not carry enough to name either — the projection never re-classifies
authority/status/state, it only adds legibility fields derived from what the
record already declares.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.receipts.artifact_receipts import (
    DISPLAY_VERB_FALLBACK,
    RUN_LABEL_FALLBACK,
    ArtifactReceiptTarget,
    receipts_for_artifacts,
)

_EXISTING_FIELDS = {
    "receipt_id",
    "trace_id",
    "action_id",
    "action_type",
    "artifact_uuid",
    "artifact_path",
    "path",
    "requested_by",
    "approved_by",
    "status",
    "timestamp",
    "state",
}


def _write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record))
            handle.write("\n")


def _project(vault_root: Path, outbox_path: Path, *, note_path: str, artifact_uuid: str | None = None):
    result = receipts_for_artifacts(
        [ArtifactReceiptTarget(artifact_uuid=artifact_uuid, note_path=note_path)],
        vault_root=vault_root,
        outbox_path=outbox_path,
    )
    assert result is not None
    return result[note_path]


def test_projection_declares_display_fields(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    # 1. Governed-capture confirm flow (app/panel/confirmation.py shape): a
    # plain-string ``source``, no verb-declaring fields in payload -> honest
    # fallback verb, but a mapped run label from the known component, and
    # run_key reusing trace_id per the issue contract.
    logged_record = {
        "event": "panel.action.logged",
        "event_id": "evt-logged-1",
        "trace_id": "trace-governed-1",
        "source": "panel_agent.confirmation",
        "timestamp": "2026-07-10T10:00:00Z",
        "payload": {
            "note_uuid": "uuid-1",
            "note_path": str(vault_root / "Inbox" / "inbox.md"),
            "proposal_id": "prop-1",
        },
    }
    # 2. A blocked receipt from the same run -- verb is always "Blocked",
    # never re-derived from payload.
    blocked_record = {
        "event": "panel.action.blocked",
        "event_id": "evt-blocked-1",
        "trace_id": "trace-governed-1",
        "source": "panel_agent.confirmation",
        "timestamp": "2026-07-10T10:01:00Z",
        "payload": {
            "note_uuid": "uuid-1",
            "note_path": "Inbox/inbox.md",
            "gate": "writeguard",
            "reason": "writes blocked",
        },
    }
    _write_records(outbox_path, [logged_record, blocked_record])

    rows = _project(vault_root, outbox_path, note_path="Inbox/inbox.md")
    assert len(rows) == 2
    by_action_type = {row["action_type"]: row for row in rows}

    logged_row = by_action_type["panel.action.logged"]
    # Additive-only: every pre-existing field keeps its name/value.
    assert _EXISTING_FIELDS <= set(logged_row.keys())
    assert logged_row["artifact_path"] == "Inbox/inbox.md"
    assert logged_row["path"] == "Inbox/inbox.md"
    assert logged_row["status"] == "logged"
    assert logged_row["state"] == "applied"
    # New fields, declared with documented fallbacks.
    assert logged_row["display_verb"] == DISPLAY_VERB_FALLBACK
    assert logged_row["run_key"] == "trace-governed-1"
    assert logged_row["run_label"] == "Governed capture"
    assert logged_row["target_absolute"] == str(vault_root / "Inbox" / "inbox.md")

    blocked_row = by_action_type["panel.action.blocked"]
    assert blocked_row["display_verb"] == "Blocked"
    assert blocked_row["run_key"] == "trace-governed-1"
    assert blocked_row["run_label"] == "Governed capture"
    # Payload declared a vault-relative path directly -- target_absolute is
    # reconstructed against vault_root.
    assert blocked_row["target_absolute"] == str((vault_root / "Inbox" / "inbox.md"))


def test_curation_reason_and_nested_source_map_to_display_fields(tmp_path: Path) -> None:
    """Curation proposal-writer records (#980-family shape): nested
    ``PanelEventSource``-style source object and a known ``reason`` value.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    record = {
        "event": "panel.action.logged",
        "event_id": "evt-curation-1",
        "trace_id": "trace-curation-1",
        "source": {
            "component": "curation.proposal_writer",
            "trigger": "curation_pass",
            "sot": "v5.0-runtime1",
        },
        "timestamp": "2026-07-10T09:00:00Z",
        "payload": {
            "note": {"uuid": "uuid-2", "path": "settings/workflow.md"},
            "finding_id": "f-1",
            "finding_class": "structure",
            "track": "propose",
            "reason": "curation_finding_proposed",
        },
    }
    _write_records(outbox_path, [record])

    rows = _project(vault_root, outbox_path, note_path="settings/workflow.md")
    assert len(rows) == 1
    row = rows[0]
    assert row["display_verb"] == "Proposed"
    assert row["run_label"] == "Curation pass"
    assert row["run_key"] == "trace-curation-1"
    assert row["target_absolute"] == str(vault_root / "settings" / "workflow.md")


def test_runtime_declared_display_fields_pass_through_verbatim(tmp_path: Path) -> None:
    """If a producer ever declares display_verb/run_key/run_label directly,
    the projection uses the declared value rather than deriving one -- the
    projection never overrides what the runtime already named.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    record = {
        "event": "panel.action.logged",
        "event_id": "evt-declared-1",
        "trace_id": "trace-declared-1",
        "source": "some.other.component",
        "timestamp": "2026-07-10T08:00:00Z",
        "payload": {
            "note_path": "settings/workflow.md",
            "display_verb": "Linked",
            "run_key": "custom-run-key",
            "run_label": "Vault sync",
        },
    }
    _write_records(outbox_path, [record])

    rows = _project(vault_root, outbox_path, note_path="settings/workflow.md")
    row = rows[0]
    assert row["display_verb"] == "Linked"
    assert row["run_key"] == "custom-run-key"
    assert row["run_label"] == "Vault sync"


def test_fallbacks_when_record_declares_nothing(tmp_path: Path) -> None:
    """No trace_id, no known source, no reason -- the record still declares
    the fields, using only the documented honest fallbacks.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    record = {
        "event": "panel.action.logged",
        "event_id": "evt-bare-1",
        "source": "unknown.component",
        "timestamp": "2026-07-10T07:00:00Z",
        "payload": {"note_path": "settings/workflow.md"},
    }
    _write_records(outbox_path, [record])

    rows = _project(vault_root, outbox_path, note_path="settings/workflow.md")
    row = rows[0]
    assert row["display_verb"] == DISPLAY_VERB_FALLBACK
    assert row["run_label"] == RUN_LABEL_FALLBACK
    # No trace_id declared: run_key falls back to the record's own receipt_id
    # so unrelated bare records never silently merge into one bucket.
    assert row["run_key"] == row["receipt_id"]


def test_target_absolute_none_when_no_path_declared(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    record = {
        "event": "panel.action.logged",
        "event_id": "evt-uuid-only-1",
        "trace_id": "trace-uuid-only",
        "source": "panel_agent.confirmation",
        "timestamp": "2026-07-10T06:00:00Z",
        "payload": {"note_uuid": "uuid-only-1"},
    }
    _write_records(outbox_path, [record])

    result = receipts_for_artifacts(
        [ArtifactReceiptTarget(artifact_uuid="uuid-only-1", note_path="Notes/anything.md")],
        vault_root=vault_root,
        outbox_path=outbox_path,
    )
    assert result is not None
    rows = result["Notes/anything.md"]
    assert len(rows) == 1
    assert rows[0]["target_absolute"] is None
