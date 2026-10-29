"""Authority transitions after real native waits, immediately before effects."""
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.api.routes import capture
from app.knowledge import adapters
from app.knowledge.placement import KnowledgePlacementOwner
from app.write_guard import DEFAULT_WRITE_GUARD
from tests._production_operation_harness import production_operation_host


@pytest.mark.parametrize("seam", ["path", "mkdir", "open"])
def test_capture_revalidates_after_actual_adapter_wait(tmp_path, monkeypatch, seam):
    host = production_operation_host(tmp_path, monkeypatch)
    native_append = adapters.FsVaultAdapter.append_note
    native_path = adapters.FsVaultAdapter._absolute_path
    native_mkdir, native_open = Path.mkdir, Path.open
    state = {"append": False, "cleared": False}

    def clear(current):
        if state["append"] and current == seam and not state["cleared"]:
            state["cleared"] = True
            host.clear_selection()

    def path(self, *args, **kwargs):
        result = native_path(self, *args, **kwargs)
        clear("path")
        return result

    def mkdir(self, *args, **kwargs):
        result = native_mkdir(self, *args, **kwargs)
        clear("mkdir")
        return result

    def opened(self, *args, **kwargs):
        result = native_open(self, *args, **kwargs)
        if args and args[0] == "a":
            clear("open")
        return result

    def append(self, *args, **kwargs):
        state["append"] = True
        try:
            return native_append(self, *args, **kwargs)
        finally:
            state["append"] = False

    monkeypatch.setattr(adapters.FsVaultAdapter, "append_note", append)
    monkeypatch.setattr(adapters.FsVaultAdapter, "_absolute_path", path)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", opened)
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command("artifact.capture", targets=[], expected_version=None,
                          arguments={"text": "forbidden after adapter wait"}))
    assert state["cleared"] and result.status_code == 200, result.text
    assert result.json()["status"] == "rejected", result.text
    assert all("forbidden after adapter wait" not in note.read_text() for note in host.root.rglob("*.md"))


@pytest.mark.parametrize("transition", ["clear", "expiry"])
def test_capture_final_health_callback_cannot_stale_authority(tmp_path, monkeypatch, transition):
    host = production_operation_host(tmp_path, monkeypatch)
    import app.api.operation_runtime as runtime
    compose = capture._compose_append_entry
    health = DEFAULT_WRITE_GUARD.assert_writes_allowed
    state = {"armed": False, "calls": 0, "changed": False}

    def composed(*args, **kwargs):
        result = compose(*args, **kwargs)
        state["armed"] = True
        return result

    def checked(action):
        result = health(action)
        if state["armed"]:
            state["calls"] += 1
            if state["calls"] == 2:
                state["changed"] = True
                if transition == "clear":
                    host.clear_selection()
                else:
                    monkeypatch.setattr(runtime, "time", lambda: 4102444800)
        return result

    monkeypatch.setattr(capture, "_compose_append_entry", composed)
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", checked)
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command("artifact.capture", targets=[], expected_version=None,
                          arguments={"text": "forbidden after health wait"}))
    assert state["changed"] and result.status_code == 200, result.text
    assert result.json()["status"] == "rejected", result.text
    assert all("forbidden after health wait" not in note.read_text() for note in host.root.rglob("*.md"))


def test_body_final_cas_rechecks_current_write_guard(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    original = host.note.read_bytes()
    snapshot = adapters._snapshot_descriptor_recovery
    state = {"blocked": False}
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn",
        lambda: {"state": "unhealthy" if state["blocked"] else "healthy"})

    def waited(*args, **kwargs):
        result = snapshot(*args, **kwargs)
        state["blocked"] = True
        return result

    monkeypatch.setattr(adapters, "_snapshot_descriptor_recovery", waited)
    result = host.client.post("/api/operations", headers=host.headers, json=host.command())
    assert state["blocked"] and result.status_code == 200, result.text
    assert result.json()["status"] == "rejected", result.text
    assert host.note.read_bytes() == original


def test_secondary_proposal_open_refusal_preserves_main_capture(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.standing_questions.registration import propose_question_registration
    from tests.standing_questions._registration_fixtures import completion_returning, registration_payload
    native_open = Path.open
    state = {"cleared": False}
    question = "Should we keep this exact question?"

    def offer(**kwargs):
        return propose_question_registration(capture_note_path=kwargs["vault_root"] / kwargs["note_rel"],
            vault_root=kwargs["vault_root"], trace_id=kwargs["trace_id"],
            complete=completion_returning(registration_payload(question)))

    def opened(self, *args, **kwargs):
        result = native_open(self, *args, **kwargs)
        if args and args[0] == "r+" and not state["cleared"]:
            state["cleared"] = True
            host.clear_selection()
        return result

    monkeypatch.setattr(capture, "_offer_question_registration_proposal", offer)
    monkeypatch.setattr(Path, "open", opened)
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command("artifact.capture", targets=[], expected_version=None,
                          arguments={"text": question}))
    assert state["cleared"] and result.status_code == 200, result.text
    assert result.json()["status"] == "convergence_pending", result.text
    assert result.json()["receipt"]["extensions"]["write"]["authority_receipt"]["receipt_id"]
    notes = "".join(note.read_text() for note in host.root.rglob("*.md"))
    assert question in notes and "Registrera stående fråga:" not in notes


@pytest.mark.parametrize("transition", ["selection", "health"])
def test_placement_final_parent_probe_cannot_stale_authority(tmp_path, monkeypatch, transition):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.api.routes.active_context_selection import build_selection_service, get_selection_store
    service = build_selection_service(get_selection_store())
    context = service.resolve_request_context(derived=service.derive("trusted_loopback"),
        session_bearer=host.selection["context_selection_id"], override_bearer=None,
        action="operation.artifact.rename", write_class="vault_placement", required_permission="write").snapshot
    owner = KnowledgePlacementOwner(vault_root=host.root, context_ref=context.context_id,
        vault_generation=str(context.generation), actor=context.principal_context.principal_id,
        active_context=context, target_binding_id=host.binding_id, registry_store=host.runtime.registry,
        context_is_current=lambda: True, authority_is_current=lambda _: True, filesystem="local-posix-v1")
    command = host.command("artifact.rename", expected_version=owner.source_generation("Notes/human.md", host.artifact_id),
        arguments={"name": "renamed.md", "destination_generation": owner.destination_generation("Notes/renamed.md")})
    native_seam, native_parents = KnowledgePlacementOwner._seam, KnowledgePlacementOwner._parents
    state = {"seam": False, "changed": False}

    @contextmanager
    def parents(self, *args, **kwargs):
        with native_parents(self, *args, **kwargs) as result:
            yield result
        if state["seam"] and not state["changed"]:
            state["changed"] = True
            if transition == "selection":
                host.clear_selection()
            else:
                monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "unhealthy"})

    def seam(self, *args, **kwargs):
        state["seam"] = True
        try:
            return native_seam(self, *args, **kwargs)
        finally:
            state["seam"] = False

    monkeypatch.setattr(KnowledgePlacementOwner, "_parents", parents)
    monkeypatch.setattr(KnowledgePlacementOwner, "_seam", seam)
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert state["changed"] and result.status_code == 200, result.text
    assert result.json()["status"] not in {"succeeded", "convergence_pending"}, result.text
    assert host.note.exists() and not (host.root / "Notes/renamed.md").exists()
