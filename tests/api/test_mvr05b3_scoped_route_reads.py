"""MVR-05B3 (#6138): the remaining API read routes on the per-request ActiveContextSet.

``/api/artifacts/note``, ``/api/debug/panel`` and ``/api/eval-drafts`` are migrated
in place: a carrier-bearing request reads exactly its own bound binding under the
context-bound read window, write-free, confined to that binding (never an
initialized nested child, never a process-wide folder override out of it), and
without consulting the process-wide selection; a carrier-free request keeps the
legacy single-binding journey.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.vault.manager as vault_manager_module
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.eval.failure_capture import draft_unknown_classification_case
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

PANEL_NOTE = "# Panel\n\n- [ ] Promote this note\n"


def _tree(*roots: Path) -> dict[str, bytes]:
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture()
def two_vaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    root_a, root_b = Path(first.path), Path(second.path)
    initialize_test_vault(root_a)
    initialize_test_vault(root_b)
    (root_a / "note.md").write_text("# Alpha\n\nonly in A\n", encoding="utf-8")
    (root_b / "note.md").write_text("# Beta\n\nonly in B\n", encoding="utf-8")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    # The process-wide legacy selector names B; scoped requests select A.
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    manager.select_vault(root_b, remember=False)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", manager)
    selection_routes.reset_selection_store_for_tests()
    return TestClient(app), first, second


def _session(client: TestClient, binding_ids: list[str]) -> dict[str, str]:
    response = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": binding_ids}
    )
    assert response.status_code == 201, response.text
    return {"X-Active-Context-Session": response.json()["context_selection_id"]}


def _forbid_global_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.routes.vault_resolution as vault_resolution

    def fail(*_a, **_kw):
        pytest.fail("a scoped read consulted the process-wide vault selection")

    monkeypatch.setattr(vault_resolution, "get_vault_manager", fail)
    monkeypatch.setattr(vault_resolution, "resolve_optional_vault_root", fail)


def test_scoped_reads_use_the_bound_binding_not_the_process_selection(
    two_vaults, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, first, second = two_vaults
    root_a, root_b = Path(first.path), Path(second.path)
    (root_a / "panel.md").write_text(PANEL_NOTE, encoding="utf-8")
    draft = draft_unknown_classification_case(
        vault_root=root_a, utterance="ambiguous scoped case", trace_id="mvr05b3-scoped"
    )
    scoped = _session(client, [first.vault_binding_id])

    # Carrier-free requests keep the legacy single-binding journey (B).
    legacy_note = client.get("/api/artifacts/note", params={"note_path": "note.md"})
    assert legacy_note.status_code == 200, legacy_note.text
    assert "only in B" in legacy_note.json()["body"]
    legacy_drafts = client.get("/api/eval-drafts")
    assert legacy_drafts.status_code == 200, legacy_drafts.text
    assert draft.draft_id not in {d["draft_id"] for d in legacy_drafts.json()["drafts"]}
    legacy_panel = client.get("/api/debug/panel", params={"note_rel": "note.md"})
    assert legacy_panel.status_code == 200, legacy_panel.text
    assert legacy_panel.json()["panel_diagnostics"] is not None

    _forbid_global_resolution(monkeypatch)
    before = _tree(root_a, root_b)

    note = client.get("/api/artifacts/note", params={"note_path": "note.md"}, headers=scoped)
    assert note.status_code == 200, note.text
    assert "only in A" in note.json()["body"]
    assert note.json()["note_path"].startswith(str(root_a.resolve()))

    drafts = client.get("/api/eval-drafts", headers=scoped)
    assert drafts.status_code == 200, drafts.text
    assert [d["draft_id"] for d in drafts.json()["drafts"]] == [draft.draft_id]

    panel = client.get("/api/debug/panel", params={"note_rel": "panel.md"}, headers=scoped)
    assert panel.status_code == 200, panel.text
    assert [a["action_text"] for a in panel.json()["parsed_actions"]] == ["Promote this note"]
    # MVR-05B4c6: a scoped read gets its own non-mutating mapping probe.
    from app.settings import panel_actions

    slot_before = panel_actions._LAST_PANEL_ACTIONS_ERROR
    panel = client.get("/api/debug/panel", params={"note_rel": "panel.md"}, headers=scoped)
    assert panel.json()["panel_diagnostics"] is not None
    assert panel_actions._LAST_PANEL_ACTIONS_ERROR == slot_before

    # B's note does not exist in A: the scoped read never falls back to B.
    (root_b / "only-b.md").write_text("B only\n", encoding="utf-8")
    before[str(root_b / "only-b.md")] = b"B only\n"
    missing = client.get("/api/artifacts/note", params={"note_path": "only-b.md"}, headers=scoped)
    assert missing.status_code == 404, missing.text

    # Scoped reads are write-free.
    assert _tree(root_a, root_b) == before


def test_scoped_reads_stay_inside_the_bound_binding(two_vaults, monkeypatch) -> None:
    client, first, _second = two_vaults
    root_a = Path(first.path)
    child = root_a / "child"
    initialize_test_vault(child)
    (child / "secret.md").write_text("# Child\n\n- [ ] child action\n", encoding="utf-8")
    scoped = _session(client, [first.vault_binding_id])
    _forbid_global_resolution(monkeypatch)

    # A note owned by an initialized nested child vault is not served through
    # the parent binding.
    nested = client.get(
        "/api/artifacts/note", params={"note_path": "child/secret.md"}, headers=scoped
    )
    assert nested.status_code == 404, nested.text
    nested_panel = client.get(
        "/api/debug/panel", params={"note_rel": "child/secret.md"}, headers=scoped
    )
    assert nested_panel.status_code == 404, nested_panel.text

    for escape in ("../two/note.md", "/etc/hosts"):
        response = client.get("/api/artifacts/note", params={"note_path": escape}, headers=scoped)
        assert response.status_code == 400, (escape, response.text)

    # A process-wide system-folder override never takes a scoped read out of
    # the binding it is bound to.
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "../two/_system")
    escaped = client.get("/api/eval-drafts", headers=scoped)
    assert escaped.status_code == 409, escaped.text
    assert escaped.json()["detail"] == "active_context_read_unavailable"


def test_scoped_reads_refuse_many_bindings_and_render_zero_binding_as_no_vault(
    two_vaults, monkeypatch
) -> None:
    client, first, second = two_vaults
    many = _session(client, [first.vault_binding_id, second.vault_binding_id])
    empty = _session(client, [])
    _forbid_global_resolution(monkeypatch)

    for path, params in (
        ("/api/artifacts/note", {"note_path": "note.md"}),
        ("/api/debug/panel", {"note_rel": "note.md"}),
        ("/api/eval-drafts", {}),
    ):
        refused = client.get(path, params=params, headers=many)
        assert refused.status_code == 409, (path, refused.text)
        assert refused.json()["detail"] == "active_context_single_binding_required"

        no_vault = client.get(path, params=params, headers=empty)
        assert no_vault.status_code == 200, (path, no_vault.text)
        assert no_vault.json()["state"] == "vault_selection_required"
        assert no_vault.json()["reason"] == "no_vault_bound"
        # The scoped no-vault journey never offers the process-configured root.
        assert no_vault.json()["configured_vault_root"] is None


def test_scoped_eval_drafts_never_read_a_nested_child_vaults_system_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#6159 review: an initialized nested child vault is a hard read boundary."""

    from app.api.routes import eval_drafts as eval_routes

    parent = tmp_path / "parent"
    initialize_test_vault(parent)
    initialize_test_vault(parent / "child")
    (parent / "child" / "_system" / eval_routes.DRAFT_DIR_NAME).mkdir(parents=True)
    monkeypatch.setattr(eval_routes, "get_vault_system_dir_rel", lambda _root: "child/_system")

    assert eval_routes._scoped_drafts_dir_is_contained(parent) is False

    monkeypatch.setattr(eval_routes, "get_vault_system_dir_rel", lambda _root: "_system")
    assert eval_routes._scoped_drafts_dir_is_contained(parent) is True


def test_route_specific_write_targets_are_proved_against_the_sealed_root(tmp_path: Path) -> None:
    """#6159 review: a route's own write target must lie in the sealed compatibility root."""

    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api.compatibility_mutation import (
        require_compatibility_write_root,
        require_compatibility_write_target,
    )

    bound, other = tmp_path / "bound", tmp_path / "other"
    bound.mkdir()
    other.mkdir()
    sealed = SimpleNamespace(state=SimpleNamespace(compatibility_write_root=bound))
    unsealed = SimpleNamespace(state=SimpleNamespace())

    require_compatibility_write_target(sealed, bound / "note.md")
    require_compatibility_write_root(sealed, bound)
    for check, target in (
        (require_compatibility_write_target, other / "note.md"),
        (require_compatibility_write_root, other),
    ):
        with pytest.raises(HTTPException) as exc:
            check(sealed, target)
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "capability_not_ready"
    # Pre-floor journey (no sealed binding): the process selection is the only binding.
    require_compatibility_write_target(unsealed, other / "note.md")


def test_panel_confirm_and_meeting_close_check_their_real_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """#6159 review: both routes prove the target they actually write before any effect."""

    from fastapi import HTTPException

    import app.panel.confirmation as confirm_module
    from app.api.routes import heimdal_meeting as meeting_routes
    from app.api.routes import panel as panel_routes
    from app.heimdal import meeting_finalization

    checked: list[tuple[str, Path]] = []

    def refuse(kind):
        def _check(_request, target):
            checked.append((kind, Path(target)))
            raise HTTPException(status_code=409, detail="capability_not_ready")

        return _check

    monkeypatch.setattr(confirm_module, "staged_proposal_note_file", lambda _pid: Path("/elsewhere/note.md"))
    monkeypatch.setattr(panel_routes, "require_compatibility_write_target", refuse("panel"))
    monkeypatch.setattr(meeting_finalization, "configured_meeting_vault_root", lambda: Path("/elsewhere"))
    monkeypatch.setattr(meeting_routes, "require_compatibility_write_root", refuse("meeting"))
    effects: list[str] = []
    monkeypatch.setattr(confirm_module._service, "confirm", lambda *_a, **_k: effects.append("confirm"))
    monkeypatch.setattr(
        meeting_routes.meeting_ledger, "close_meeting_session", lambda **_k: effects.append("close")
    )
    monkeypatch.setattr(meeting_routes, "_assert_lan_posture", lambda *_a, **_k: None)
    client = TestClient(app)

    panel = client.post(
        "/api/panel/confirm",
        json={"proposal_id": "p-1", "artifact_id": "a-1", "action": "confirm", "idempotency_key": "k-1"},
    )
    meeting = client.post("/api/heimdal/meeting/s-1/close", json={"final_seq_count": 1})

    assert panel.status_code == 409, panel.text
    assert meeting.status_code == 409, meeting.text
    assert checked == [("panel", Path("/elsewhere/note.md")), ("meeting", Path("/elsewhere"))]
    assert effects == []


def test_voice_route_takes_the_selection_lock_before_the_write_window() -> None:
    """#6159 review: /ask/voice must not hold the ingress window around the selection lock."""

    import inspect

    from app.api import compatibility_mutation as mutation
    from app.api.routes import ask as ask_routes

    assert mutation._seals_inside(ask_routes.ask_voice)
    source = inspect.getsource(ask_routes.ask_voice)
    selection = source.index("compatibility_selection_window()")
    window = source.index("compatibility_write_target_window(request)")
    assert selection < window


def test_checkbox_projection_proves_its_own_root_against_the_sealed_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#6159 review: /panel/checkbox-projection resolves its own root; it must be the binding."""

    import app.panel.checkbox_projection as projection_module
    from app.panel.checkbox_projection import CheckboxProjectionHTTPError, CheckboxProjectionRequest

    stale_a, sealed_b = tmp_path / "a", tmp_path / "b"
    initialize_test_vault(stale_a)
    initialize_test_vault(sealed_b)
    (stale_a / "note.md").write_text("- [ ] task\n", encoding="utf-8")
    monkeypatch.setattr(projection_module, "resolve_optional_vault_root", lambda: stale_a)
    fields = CheckboxProjectionRequest.model_fields
    payload = {
        "note_path": "note.md",
        "expected_content_hash": "0" * 64,
        "idempotency_key": "kp-1",
    }
    for name, field in fields.items():
        if name not in payload and field.is_required():
            payload[name] = "x" if field.annotation is str else 0
    request = CheckboxProjectionRequest.model_validate(payload)

    with pytest.raises(CheckboxProjectionHTTPError) as exc:
        projection_module._service.project(request, sealed_root=sealed_b)

    assert exc.value.status_code == 409
    assert exc.value.response.block_reason == "capability_not_ready"
    assert (stale_a / "note.md").read_text(encoding="utf-8") == "- [ ] task\n"


def test_meeting_segment_admission_proves_the_meeting_root_first() -> None:
    """#6159 review: a meeting segment may re-finalize into the meeting root; prove it first."""

    import inspect

    from app.api.routes import heimdal_capture as capture_routes

    source = inspect.getsource(capture_routes.admit_media)
    assert source.index("require_compatibility_write_root(request, meeting_root)") < source.index(
        "media_ingress.admit_media_bytes("
    )
