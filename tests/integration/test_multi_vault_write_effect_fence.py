"""Production write/receipt window cannot be crossed by authority changes."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from pathlib import Path

import pytest

from app.api.routes import capture
from app.instance.binding_effect_lease import BindingEffectLeaseManager
from tests.api.test_multi_vault_governed_writes import setup_capture
from tests._mvr03_principal_harness import principal_store
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_authority_change_cannot_cross_validation_write_window(tmp_path, monkeypatch):
    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    original = capture._emit_capture_event

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(capture, "_emit_capture_event", paused)
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )

    def exclusive():
        with leases.exclusive_change(
            first.vault_binding_id, channel_id=runtime.layout.channel_id, root=Path(first.path)
        ):
            return True

    with ThreadPoolExecutor(max_workers=3) as pool:
        write = pool.submit(
            client.post,
            "/api/companion/capture/scoped",
            headers=headers,
            json={"text": "Authorized effect", "target_binding_id": first.vault_binding_id},
        )
        assert entered.wait(timeout=5)
        changed = pool.submit(exclusive)
        revoked = pool.submit(
            principal_store(runtime).rotate_credential,
            credential="new-test-credential",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        for pending in (changed, revoked):
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.1)
        release.set()
        result = write.result(timeout=5)
        assert result.status_code == 200, result.text
        assert changed.result(timeout=5)
        revoked.result(timeout=5)
    assert "Authorized effect" in Path(first.path, "Inbox/inbox.md").read_text()
    assert (
        result.json()["governed_write"]["authority_receipt"]["receipt_id"]
        in (tmp_path / "outbox.jsonl").read_text()
    )


def test_relocation_cannot_cross_foreground_or_background_effect_windows_after_activation(
    tmp_path, monkeypatch
):
    """MVR-06C: activated relocation waits for, or out-revisions, every effect window.

    Real foreground scoped read, governed capture write, and supervised background effect
    windows each hold the shared lease; the production relocation waits for each of them.
    A request or lifecycle that resolved/validated before the relocation but reaches its
    lease afterwards is refused before touching either root.
    """

    from fastapi.testclient import TestClient

    from app.api.app import app
    from app.api.routes import active_context_selection as selections
    from app.api.routes import companion as companion_routes
    from app.instance.active_context_service import (
        ACTION_SELECTION_INSPECT,
        PERMISSION_SELECTION_READ,
        WRITE_CLASS_READ,
    )
    from app.instance.background_supervisor import BackgroundLifecycleStale
    from app.instance.binding_effect_lease import BindingEffectLeaseError
    from app.instance.context_bound_read import ContextBoundReadError, context_bound_read_window
    from tests._mvr06b_handoff_harness import mvr06b_instance, stub_settings_reload, supervisor
    from tests._mvr06c_relocation_harness import (
        copy_vault,
        enroll_only,
        initialized_registration,
        shared_refused,
    )

    runtime, _first, _extra = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setattr(capture, "_offer_question_registration_proposal", lambda **_: None)
    bound = initialized_registration(runtime, tmp_path / "bound")
    enroll_only(runtime, bound.vault_binding_id)
    binding = bound.vault_binding_id
    selections.reset_selection_store_for_tests()
    client = TestClient(app)
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding]}
    )
    assert created.status_code == 201, created.text
    headers = {"X-Active-Context-Session": created.json()["context_selection_id"]}
    background = supervisor(runtime, "watcher")
    assert background.start().status == "running"
    roots = [Path(bound.path)]

    def relocate_next():
        target = copy_vault(roots[-1], tmp_path / f"relocated-{len(roots)}")
        roots.append(target)
        return runtime.relocate(binding, target)

    entered, release = Event(), Event()

    def pause(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=10)

    original_list = companion_routes._list_vault_notes
    original_emit = capture._emit_capture_event

    def paused_read(root, q=""):
        pause()
        return original_list(root, q=q)

    def paused_emit(*args, **kwargs):
        pause()
        return original_emit(*args, **kwargs)

    def background_effect():
        with background.effect(binding) as lifecycle:
            pause()
            return lifecycle.root

    windows = (
        ("foreground_read", lambda: client.get("/api/companion/vault/notes/scoped", headers=headers)),
        (
            "governed_write",
            lambda: client.post(
                "/api/companion/capture/scoped",
                headers=headers,
                json={"text": "Authorized before relocation", "target_binding_id": binding},
            ),
        ),
        ("background_effect", background_effect),
    )
    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused_read)
    monkeypatch.setattr(capture, "_emit_capture_event", paused_emit)
    for name, effect in windows:
        entered.clear()
        release.clear()
        source = roots[-1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(effect)
            assert entered.wait(timeout=10), name
            moving = pool.submit(relocate_next)
            # The exclusive relocation waits for the authorized shared effect.
            with pytest.raises(TimeoutError):
                moving.result(timeout=0.5)
            assert runtime.registry.load().registrations[binding].path == str(source.resolve())
            release.set()
            outcome = running.result(timeout=10)
            relocated = moving.result(timeout=30)
        if name == "background_effect":
            assert outcome == source  # the authorized effect ran on the root it validated
        else:
            assert outcome.status_code == 200, (name, outcome.text)
        assert relocated.path == str(roots[-1].resolve())
        assert shared_refused(runtime, binding, source)
    assert "Authorized before relocation" in Path(roots[1], "Inbox/inbox.md").read_text()
    monkeypatch.setattr(companion_routes, "_list_vault_notes", original_list)
    monkeypatch.setattr(capture, "_emit_capture_event", original_emit)

    # A request resolved before the relocation that reaches its lease afterwards is refused.
    service = selections.build_selection_service(selections.get_selection_store())
    stale_context = service.resolve_request_context(
        derived=service.derive("trusted_loopback"),
        session_bearer=headers["X-Active-Context-Session"],
        override_bearer=None,
        action=ACTION_SELECTION_INSPECT,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_READ,
    ).snapshot
    validated = background.reconcile_all()[0]
    previous = roots[-1]
    relocate_next()
    with pytest.raises(ContextBoundReadError):
        with context_bound_read_window(stale_context, registry_store=runtime.registry):
            raise AssertionError("a stale request context touched a root")
    # A lifecycle validated before the relocation cannot effect on either root.
    with pytest.raises(BindingEffectLeaseError):
        with background.effect_leases.shared_effect(
            binding, channel_id=runtime.layout.channel_id, root=previous
        ):
            raise AssertionError("a stale lifecycle touched the old root")
    with pytest.raises(BackgroundLifecycleStale):
        background.require_current(validated)
    # The next request and the next background effect use only the new root.
    write = client.post(
        "/api/companion/capture/scoped",
        headers=headers,
        json={"text": "After relocation", "target_binding_id": binding},
    )
    assert write.status_code == 200, write.text
    assert "After relocation" in Path(roots[-1], "Inbox/inbox.md").read_text()
    assert "After relocation" not in Path(previous, "Inbox/inbox.md").read_text()
    with background.effect(binding) as lifecycle:
        assert lifecycle.root == roots[-1].resolve()
