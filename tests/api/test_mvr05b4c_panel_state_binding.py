"""MVR-05B4c2 (#6212): panel proposal / idempotency state and panel receipts carry a binding.

``ProposalStore`` and ``ConfirmIdempotencyStore`` are keyed by (producing binding, id), and
every receipt event ``receipts_for_artifacts`` projects (``panel.action.logged`` and
``panel.action.blocked``) is stamped with its producing binding at emission. Scoped
``/workspace`` panel state, ``/vault-browser`` receipts and the ``/orientation`` governance
summary answer from the request binding only; unstamped legacy state is never shown to a
scoped read. The confirm path stays a carrier-free compatibility write.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.panel.confirmation as confirm_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import companion as companion_routes
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmResponse,
    ProposalStore,
    StagedProposal,
)
from app.receipts.artifact_receipts import (
    PRODUCING_BINDING_FIELD,
    ArtifactReceiptTarget,
    receipts_for_artifacts,
)
from app.instance.settings_rebind import _install_dormant_settings_rebind
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

SHARED_NOTE_UUID = "shared-note-uuid-6212"
SHARED_NOTE_PATH = "shared.md"


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    # The compatibility vault is the first binding: a registered id, not the sentinel.
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    for root in (Path(first.path), Path(second.path)):
        initialize_test_vault(root)
        (root / SHARED_NOTE_PATH).write_text(
            f"---\ntitle: Shared\nuuid: {SHARED_NOTE_UUID}\nkind: human_note\n"
            "review_state: reviewed\ntrust: assert\n---\n\nBody.\n",
            encoding="utf-8",
        )
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave-point.sqlite3"))
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    proposals = ProposalStore()
    idempotency = ConfirmIdempotencyStore()
    monkeypatch.setattr(confirm_module, "_proposal_store", proposals)
    monkeypatch.setattr(confirm_module, "_idempotency_store", idempotency)
    monkeypatch.setattr(
        companion_routes, "_MEMORY_CANDIDATE_REVIEW_QUEUE", MemoryCandidateReviewQueue()
    )
    return TestClient(app), first, second, proposals, idempotency, outbox


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _intent(label: str = "send report") -> PanelIntentEvent:
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=SHARED_NOTE_UUID, path=SHARED_NOTE_PATH),
            panel=PanelInfo(panel_id="panel-1", instruction=f"instruction for {label}"),
            actions=[PanelIntentAction(id=f"act-{label}", label=label, checked=True)],
        )
    )


def _stage(store: ProposalStore, proposal_id: str, artifact_id: str, *, binding, label="x"):
    store.stage(
        proposal_id,
        StagedProposal(artifact_id=artifact_id, intent_event=_intent(label)),
        binding=binding,
    )


def _response(artifact_id: str, key: str, *, status="logged", outcome="logged") -> ConfirmResponse:
    return ConfirmResponse(
        proposal_id=f"p-{key}",
        artifact_id=artifact_id,
        status=status,
        outcome=outcome,
        idempotency_key=key,
    )


def _workspace(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get(
        "/api/companion/workspace", params={"note_path": SHARED_NOTE_PATH}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _artifact_id(client: TestClient, headers: dict[str, str]) -> str:
    return _workspace(client, headers)["artifact"]["artifact_id"]


def test_scoped_workspace_panel_state_matches_only_request_binding(two_bindings) -> None:
    client, first, second, proposals, idempotency, _outbox = two_bindings
    headers_a = _headers(client, first.vault_binding_id)
    headers_b = _headers(client, second.vault_binding_id)
    artifact_id = _artifact_id(client, headers_a)
    assert _artifact_id(client, headers_b) == artifact_id  # the colliding panel UUID

    _stage(proposals, "prop-a", artifact_id, binding=first.vault_binding_id, label="A action")
    _stage(proposals, "prop-b1", artifact_id, binding=second.vault_binding_id, label="B one")
    _stage(proposals, "prop-b2", artifact_id, binding=second.vault_binding_id, label="B two")
    _stage(proposals, "prop-legacy", artifact_id, binding=None, label="legacy")
    idempotency.set("key-a", _response(artifact_id, "key-a"), binding=first.vault_binding_id)
    idempotency.set(
        "key-b",
        _response(artifact_id, "key-b", status="blocked", outcome="blocked"),
        binding=second.vault_binding_id,
    )
    before_p, before_i = dict(proposals._proposals), dict(idempotency._cache)

    panel_a = _workspace(client, headers_a)["panel"]
    panel_b = _workspace(client, headers_b)["panel"]

    assert [p["proposal_id"] for p in panel_a["proposals"]] == ["prop-a"]
    assert sorted(p["proposal_id"] for p in panel_b["proposals"]) == ["prop-b1", "prop-b2"]
    assert panel_a["proposal_count"] == 1 and panel_b["proposal_count"] == 2
    assert panel_a["receipt_count"] == 1 and panel_b["receipt_count"] == 1
    assert panel_a["latest_receipt_outcome"] == "logged"
    assert panel_b["latest_receipt_outcome"] == "blocked"
    assert panel_a["blocked_reason"] is None
    assert "prop-legacy" not in json.dumps([panel_a, panel_b])
    # A scoped read never writes.
    assert proposals._proposals == before_p and idempotency._cache == before_i

    # Carrier-free behavior: the legacy view is the live compatibility binding's
    # (here: the first binding's) entries plus unstamped ones, never the second's.
    legacy = companion_routes._panel_state(artifact_id)
    assert sorted(p["proposal_id"] for p in legacy.proposals) == ["prop-a", "prop-legacy"]
    assert legacy.receipt_count == 1


def test_blank_carrier_workspace_never_reads_panel_state(two_bindings) -> None:
    client, first, _second, proposals, _idempotency, _outbox = two_bindings
    artifact_id = _artifact_id(client, _headers(client, first.vault_binding_id))
    _stage(proposals, "prop-a", artifact_id, binding=first.vault_binding_id)
    _stage(proposals, "prop-legacy", artifact_id, binding=None)

    blank = client.get(
        "/api/companion/workspace",
        params={"note_path": SHARED_NOTE_PATH},
        headers={"X-Active-Context-Session": ""},
    )
    assert blank.status_code >= 400
    assert "prop-" not in blank.text


def _record(event: str, event_id: str, stamp: str | None, **extra) -> dict:
    payload = {"note_uuid": SHARED_NOTE_UUID, "note_path": SHARED_NOTE_PATH, **extra}
    if stamp is not None:
        payload[PRODUCING_BINDING_FIELD] = stamp
    return {
        "event": event,
        "event_id": event_id,
        "timestamp": "2026-10-18T10:00:00Z",
        "payload": payload,
    }


def _write_outbox(outbox: Path, records: list[dict]) -> None:
    outbox.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _receipt_ids(client: TestClient, headers: dict[str, str]) -> list[str]:
    response = client.get("/api/companion/vault-browser", headers=headers)
    assert response.status_code == 200, response.text
    note = next(n for n in response.json()["notes"] if n["note_path"].endswith(SHARED_NOTE_PATH))
    return sorted(r["receipt_id"] for r in note["receipts"])


def test_scoped_vault_browser_restores_receipts_for_binding(two_bindings) -> None:
    client, first, second, _proposals, _idempotency, outbox = two_bindings
    a, b = first.vault_binding_id, second.vault_binding_id
    _write_outbox(
        outbox,
        [
            _record("panel.action.logged", "logged-a", a),
            _record("panel.action.blocked", "blocked-a", a),
            _record("panel.action.logged", "logged-b", b),
            _record("panel.action.blocked", "blocked-b", b),
            _record("panel.action.logged", "logged-legacy", None),
            _record("panel.action.blocked", "blocked-legacy", None),
        ],
    )
    before = outbox.read_text(encoding="utf-8")

    assert _receipt_ids(client, _headers(client, a)) == ["blocked-a", "logged-a"]
    assert _receipt_ids(client, _headers(client, b)) == ["blocked-b", "logged-b"]
    assert outbox.read_text(encoding="utf-8") == before

    # Carrier-free: the legacy view shows unstamped and live-compatibility-stamped receipts,
    # never a scoped binding's, and keeps the None-versus-empty distinction.
    targets = [ArtifactReceiptTarget(artifact_uuid=SHARED_NOTE_UUID, note_path=SHARED_NOTE_PATH)]
    legacy = receipts_for_artifacts(targets, vault_root=Path(first.path), outbox_path=outbox)
    assert legacy is not None
    assert sorted(r["receipt_id"] for r in legacy[SHARED_NOTE_PATH]) == [
        "blocked-a",
        "blocked-legacy",
        "logged-a",
        "logged-legacy",
    ]
    assert (
        receipts_for_artifacts(
            targets, vault_root=Path(first.path), outbox_path=outbox.parent / "absent.jsonl"
        )
        is None
    )
    scoped_empty = receipts_for_artifacts(
        targets, vault_root=Path(first.path), outbox_path=outbox, binding="unknown-binding"
    )
    assert scoped_empty == {SHARED_NOTE_PATH: []}


def test_scoped_orientation_restores_memory_and_governance_summaries_for_binding(
    two_bindings,
) -> None:
    client, first, second, proposals, idempotency, _outbox = two_bindings
    queue = companion_routes._MEMORY_CANDIDATE_REVIEW_QUEUE

    def candidate(candidate_id: str) -> MemoryCandidate:
        return MemoryCandidate(
            candidate_id=candidate_id,
            title=candidate_id,
            memory_type=MemoryType.PREFERENCE_MEMORY,
            source_refs=[f"artifact_uuid:{SHARED_NOTE_UUID}"],
            generated_by="agent_memory.test",
        )

    queue.enqueue(candidate("cand-a"), binding=first.vault_binding_id)
    queue.enqueue(candidate("cand-b1"), binding=second.vault_binding_id)
    queue.enqueue(candidate("cand-b2"), binding=second.vault_binding_id)
    _stage(proposals, "prop-a", "artifact-x", binding=first.vault_binding_id)
    _stage(proposals, "prop-b1", "artifact-x", binding=second.vault_binding_id)
    _stage(proposals, "prop-b2", "artifact-x", binding=second.vault_binding_id)
    _stage(proposals, "prop-legacy", "artifact-x", binding=None)
    idempotency.set(
        "key-b",
        _response("artifact-x", "key-b", outcome="rejected"),
        binding=second.vault_binding_id,
    )

    def body(binding_id: str) -> dict:
        response = client.get("/api/companion/orientation", headers=_headers(client, binding_id))
        assert response.status_code == 200, response.text
        result = response.json()
        degraded = result.get("degraded_reasons", [])
        assert "governance_source_unavailable" not in degraded
        assert "memory_source_unavailable" not in degraded
        return result

    a, b = body(first.vault_binding_id), body(second.vault_binding_id)
    assert a["memory"]["pending_candidate_count"] == 1
    assert b["memory"]["pending_candidate_count"] == 2
    assert a["governance"]["pending_proposal_count"] == 1
    assert b["governance"]["pending_proposal_count"] == 2
    assert a["governance"]["pending_receipt_count"] == 0
    assert b["governance"]["pending_receipt_count"] == 1
    assert b["governance"]["latest_receipt_outcome"] == "rejected"

    legacy = companion_routes._orientation_governance_summary()
    assert legacy.pending_proposal_count == 2 and legacy.pending_receipt_count == 0


def test_store_views_are_keyed_by_binding() -> None:
    store = ProposalStore()
    cache = ConfirmIdempotencyStore()
    _stage(store, "same", "art", binding="binding-1", label="one")
    _stage(store, "same", "art", binding="binding-2", label="two")
    _stage(store, "same", "art", binding=None, label="legacy")

    assert store.get("same", binding="binding-1").binding_id == "binding-1"
    assert store.get("same", binding="binding-2").binding_id == "binding-2"
    assert store.get("same").binding_id is None  # legacy view
    assert store.get("same", binding="binding-3") is None
    assert store.count_for_artifact("art", binding="binding-2") == 1
    store.remove("same", binding="binding-1")
    assert store.get("same", binding="binding-1") is None
    assert store.get("same", binding="binding-2") is not None

    cache.set("k", _response("art", "k"), binding="binding-1")
    assert cache.get("k", binding="binding-2") is None
    assert cache.get("k") is None  # a scoped stamp is never in the legacy view
    cache.set("k", _response("art", "k"))  # default: sealed compatibility binding
    assert cache.get("k") is not None
    assert len(cache.responses_for(COMPATIBILITY_BINDING_ID)) == 1


def test_durable_store_keeps_scoped_state_process_local(tmp_path: Path) -> None:
    db = tmp_path / "panel.sqlite3"
    store = ProposalStore(db)
    cache = ConfirmIdempotencyStore(db)
    _stage(store, "legacy-prop", "art", binding=COMPATIBILITY_BINDING_ID)
    _stage(store, "scoped-prop", "art", binding="binding-1")
    cache.set("legacy-key", _response("art", "legacy-key"))
    cache.set("scoped-key", _response("art", "scoped-key"), binding="binding-1")

    reloaded = ProposalStore(db)
    reloaded_cache = ConfirmIdempotencyStore(db)
    # Reloaded rows carry no stamp: legacy view only, never adopted into a binding.
    assert [pid for pid, _ in reloaded.items_for()] == ["legacy-prop"]
    assert reloaded.items_for("binding-1") == []
    assert reloaded.items_for(COMPATIBILITY_BINDING_ID) == []
    assert reloaded_cache.get("legacy-key") is not None
    assert reloaded_cache.get("scoped-key") is None


def test_every_panel_receipt_emitter_stamps_the_compatibility_binding(tmp_path: Path) -> None:
    from app.agents.panel_agent.graph import _logged_event
    from app.curation import proposal_writer

    outbox = tmp_path / "outbox.jsonl"

    # app/panel/confirmation.py: logged and blocked.
    for name in ("panel.action.logged", "panel.action.blocked"):
        confirm_module._emit_projection_event(
            name,
            {"note_uuid": SHARED_NOTE_UUID, "note_path": SHARED_NOTE_PATH},
            trace_id="t",
            outbox_path=outbox,
        )
    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in records] == ["panel.action.logged", "panel.action.blocked"]
    for record in records:
        assert record["payload"][PRODUCING_BINDING_FIELD] == COMPATIBILITY_BINDING_ID

    # app/agents/panel_agent/graph.py
    intent = _intent()
    event = _logged_event(intent, intent.payload.actions[0], "reason")
    assert event.payload[PRODUCING_BINDING_FIELD] == COMPATIBILITY_BINDING_ID

    # app/curation/proposal_writer.py
    class _Finding:
        note_uuid = SHARED_NOTE_UUID
        finding_id = "f1"
        finding_class = type("C", (), {"value": "c"})()
        track = type("T", (), {"value": "propose"})()

    curation_outbox = tmp_path / "curation.jsonl"
    proposal_writer._emit_proposal_receipt(
        _Finding(), note_path=tmp_path / SHARED_NOTE_PATH, outbox_path=curation_outbox
    )
    curated = json.loads(curation_outbox.read_text(encoding="utf-8").splitlines()[0])
    assert curated["payload"][PRODUCING_BINDING_FIELD] == COMPATIBILITY_BINDING_ID


def test_production_paths_stamp_the_live_compatibility_binding(two_bindings) -> None:
    """Review repair: no injected binding; production stagers/confirm/emitters only.

    The compatibility vault is a registered binding with a real id. Producers must
    stamp that id (not the transitional sentinel) so a scoped request for that vault
    sees the state, another binding does not, and the carrier-free view is unchanged.
    """

    from unittest.mock import MagicMock

    from app.instance.compatibility_binding import live_compatibility_binding_id
    from app.write_guard import WriteGuard, WritesBlockedError

    client, first, second, proposals, idempotency, outbox = two_bindings
    live = live_compatibility_binding_id()
    assert live == first.vault_binding_id, "fixture must bind the compatibility vault"
    headers_a = _headers(client, first.vault_binding_id)
    headers_b = _headers(client, second.vault_binding_id)
    artifact_id = _artifact_id(client, headers_a)

    # Production stager (no binding argument).
    proposal_id = companion_routes._stage_queue_review_panel_proposal(
        {"note_path": SHARED_NOTE_PATH, "artifact_uuid": artifact_id}
    )
    assert proposals.get(proposal_id).binding_id == live

    # Production confirm path with a blocked guard: real emitter + idempotency set.
    guard = MagicMock(spec=WriteGuard)
    guard.assert_writes_allowed.side_effect = WritesBlockedError("blocked", "gate", "panel.confirm")
    service = confirm_module.PanelConfirmationService(
        proposals, idempotency, write_guard=guard, same_turn_ttl=0
    )
    response = service.confirm(
        confirm_module.ConfirmRequest(
            proposal_id=proposal_id, artifact_id=artifact_id, action="confirm", idempotency_key="k1"
        )
    )
    assert response.status == "blocked"
    record = json.loads(outbox.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "panel.action.blocked"
    assert record["payload"][PRODUCING_BINDING_FIELD] == live

    panel_a = _workspace(client, headers_a)["panel"]
    panel_b = _workspace(client, headers_b)["panel"]
    assert [p["proposal_id"] for p in panel_a["proposals"]] == [proposal_id]
    assert panel_a["receipt_count"] == 1 and panel_a["blocked_reason"]
    assert panel_b["proposals"] == [] and panel_b["receipt_count"] == 0
    summary = client.get("/api/companion/orientation", headers=headers_a).json()["governance"]
    assert summary["pending_proposal_count"] == 1 and summary["pending_receipt_count"] == 1
    other = client.get("/api/companion/orientation", headers=headers_b).json()["governance"]
    assert other["pending_proposal_count"] == 0

    assert _receipt_ids(client, headers_a) != []
    assert _receipt_ids(client, headers_b) == []
    # Carrier-free view still sees the compatibility-stamped state.
    legacy = companion_routes._panel_state(artifact_id)
    assert legacy.receipt_count == 1 and len(legacy.proposals) == 1
