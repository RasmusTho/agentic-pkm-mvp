from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tests.builderops.test_devui_runtime import (
    _managed_source,
    managed_sources as managed_sources,
)


pytestmark = pytest.mark.pg


def test_native_lease_activity_reaches_managed_overview(
    control_plane_store, envelope, request
) -> None:
    """Read the real PostgreSQL writers through service auth, HTTP client and GET."""
    store, source = control_plane_store, request.getfixturevalue("managed_sources")
    envelope = replace(envelope, repository="example/fixture", source_refs=("github-issue:501",))
    source.native_store = store
    source.epoch = store.readiness()["authority_epoch"]
    source.environment["DEVUI_BUILDEROPS_AUTHORITY_EPOCH"] = str(source.epoch)
    source.gh_mode.write_text("no_pull")
    request = {**source.tasks[0]["payload"], "status": "claimed"}
    store.commit_transition(
        envelope=envelope, task_id="task-1", to_state="ready",
        idempotency_key="activity-create", request={**request, "status": "ready"},
    )
    _, lease = store.claim_task(
        envelope=envelope, task_id="task-1", holder="task-worker",
        idempotency_key="activity-claim", request=request,
    )
    # Same resource id is legal in the disjoint generic lease namespace.
    store.claim_lease(
        envelope=envelope, resource_id="task-1", holder="generic-worker",
        idempotency_key="activity-generic", request={},
    )
    old = datetime.now(timezone.utc) - timedelta(days=15)
    with store._connect() as conn:
        conn.execute("UPDATE builderops_tasks SET updated_at = %s", (old,))
        conn.execute(
            "UPDATE builderops_leases SET updated_at = %s WHERE lease_kind = 'task'", (old,)
        )

    def read():
        listed = store.list_tasks(envelope.repository)
        prefixed = store.list_tasks(envelope.repository, task_prefix="task-")
        addressed = store.get_task(envelope.repository, "task-1")
        assert listed == prefixed == [addressed]
        assert addressed["lease"]["holder"] == "task-worker"
        assert addressed["lease"]["lease_kind"] == "task"
        with source.client() as client:
            response = client.get("/api/devui/overview")
        assert response.status_code == 200
        payload = response.json()
        assert _managed_source(payload, "dispatcher-store")["state"] == "fresh"
        assert _managed_source(payload, "github-live")["state"] == "fresh"
        assert _managed_source(payload, "docs-frontmatter")["state"] == "fresh"
        return addressed, payload

    before, payload = read()
    assert before["lease"]["updated_at"] == old
    assert payload["now"] == []
    args = dict(
        envelope=envelope, lease=lease, idempotency_key="activity-heartbeat",
        request={}, ttl_seconds=5400,
    )
    _, renewed = store.heartbeat_lease(**args)
    after, payload = read()
    assert after["updated_at"] == before["updated_at"]
    assert after["version"] == before["version"]
    assert after["lease"]["updated_at"] > old
    assert [item["display_label"] for item in payload["now"]] == ["Fixture work"]
    # Replay/restart reuses the committed activity, without manufacturing movement.
    replayed, _ = store.heartbeat_lease(**args)
    assert replayed.replayed
    assert store.get_task(envelope.repository, "task-1")["lease"] == after["lease"]
    source.native_store = type(store)(store.dsn)
    store.complete_task(
        envelope=envelope, lease=renewed, idempotency_key="activity-complete",
        request={**request, "status": "completed"},
    )
    terminal, payload = read()
    assert terminal["state"] == "completed"
    assert terminal["lease"]["expires_at"] <= datetime.now(timezone.utc)
    assert payload["now"] == []
