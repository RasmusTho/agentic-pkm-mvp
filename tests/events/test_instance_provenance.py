from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from app.events.schema import make_outbox_event
from app.outbox.events import emit_index_object_embedded


def test_runtime_events_include_instance_provenance_from_settings(monkeypatch) -> None:
    bundle = SimpleNamespace(instance=SimpleNamespace(id="work-laptop", role="satellite", environment="dev"))
    monkeypatch.setattr("app.events.schema.get_settings_bundle", lambda: bundle, raising=False)

    event = make_outbox_event("runtime.test", source="test", payload={"ok": True})
    record = event.model_dump(mode="json")

    assert record["meta"]["instance_provenance"] == {
        "instance_id": "work-laptop",
        "instance_role": "satellite",
        "environment": "dev",
    }


def test_instance_provenance_does_not_modify_artifact_identity(tmp_path, monkeypatch) -> None:
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    bundle = SimpleNamespace(instance=SimpleNamespace(id="home", role="master", environment="prod"))
    monkeypatch.setattr("app.events.schema.get_settings_bundle", lambda: bundle, raising=False)

    object_id = str(uuid4())
    source_ref = "vault/Notes/identity.md"
    emit_index_object_embedded(object_id=object_id, source_ref=source_ref)

    record = json.loads(outbox.read_text(encoding="utf-8").strip())
    assert record["uuid"] == object_id
    assert record["payload"]["object_id"] == object_id
    assert record["meta"]["source_ref"] == source_ref
    assert record["meta"]["instance_provenance"] == {
        "instance_id": "home",
        "instance_role": "master",
        "environment": "prod",
    }
