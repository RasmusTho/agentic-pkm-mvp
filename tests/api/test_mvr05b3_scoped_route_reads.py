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
    # Process-global panel-action diagnostics are not reported as the binding's.
    assert panel.json()["panel_diagnostics"] is None

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
