"""MVR-05B production request-context resolution precedence (#6135, MVR-05B0).

The precedence is explicit selection (one-request override, then retained session), then the
explicit instance default, then the healthy no-vault state. Last-active picker history, the
process working directory, the legacy global vault manager, and any *other* binding are never
inputs, and an invalid explicit choice never degrades into any later step.

Every assertion here goes through the production request dependency
(`app.api.request_active_context.resolve_read_context`) with its real FastAPI dependencies,
or through a production scoped route on the shipped app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.agents.ask.graph as ask_graph
import app.vault.manager as vault_manager_module
from app.api.app import app
from app.api.request_active_context import resolve_read_context
from app.api.routes import active_context_selection as selection_routes
from app.instance.runtime import open_default_vault_service
from app.instance.vault_registry import KnownVaultRef
from app.vault.active_context_v1 import ActiveContextSetV1
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

pytestmark = pytest.mark.not_pg

SELECTION_URL = "/api/companion/active-context/selection"
NOTES_URL = "/api/companion/vault/notes/scoped"


def _probe_app() -> FastAPI:
    """Expose exactly what the production request dependency resolved.

    The dependency, its auth inputs, and its error mapping are production code; the probe
    only serializes the immutable snapshot it was handed.
    """

    probe = FastAPI()

    @probe.get("/probe")
    def resolved(
        context: ActiveContextSetV1 | None = Depends(resolve_read_context),
    ) -> dict[str, object]:
        if context is None:
            return {"context": None}
        return {
            "context": {
                "binding_ids": list(context.binding_ids),
                "provenance": context.selection_provenance,
                "posture": context.posture,
                "is_no_vault": context.is_no_vault,
                "generation": context.generation,
                "has_bearer_digest": context.selection_capability_digest is not None,
            }
        }

    return probe


@pytest.fixture()
def instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, first, extra, _record = provisioned_instance(
        tmp_path, extra_roots=("two", "three")
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    bindings = {"one": first, "two": extra[0], "three": extra[1]}
    registrations = runtime.registry.load().registrations
    for name, binding in bindings.items():
        root = Path(registrations[binding.vault_binding_id].path)
        (root / f"{name}-marker.md").write_text(f"# {name}\n", encoding="utf-8")
    return runtime, {name: binding.vault_binding_id for name, binding in bindings.items()}


def _create(client: TestClient, binding_id: str) -> str:
    response = client.post(SELECTION_URL, json={"vault_binding_ids": [binding_id]})
    assert response.status_code == 201, response.text
    return response.json()["context_selection_id"]


def _remember_last_active(runtime, binding_id: str) -> None:
    registration = runtime.registry.load().registrations[binding_id]
    runtime.registry.remember_registration(
        binding_id,
        KnownVaultRef(
            ref=registration.ref,
            path=registration.path,
            vault_id=registration.vault_id,
            local_instance_id=registration.local_instance_id,
            vault_name=registration.vault_name,
            last_opened_at="2026-10-15T00:00:00Z",
        ),
        make_active=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def test_resolution_precedence_and_fail_closed_behavior(
    instance, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, ids = instance
    one, two, three = ids["one"], ids["two"], ids["three"]

    # Every non-authority carrier points somewhere tempting and wrong: picker history and
    # the process CWD at `three`, and a global vault manager that must never be asked.
    _remember_last_active(runtime, three)
    monkeypatch.chdir(runtime.registry.load().registrations[three].path)
    for module in (vault_manager_module, ask_graph):
        monkeypatch.setattr(
            module,
            "get_vault_manager",
            lambda: pytest.fail("request resolution consulted the global vault manager"),
        )

    api = TestClient(app)
    probe = TestClient(_probe_app())

    def resolve(headers: dict[str, str] | None = None):
        return probe.get("/probe", headers=headers or {})

    # 1. No explicit selection: the explicit instance default, never last-active or CWD.
    default = resolve()
    assert default.status_code == 200, default.text
    assert default.json()["context"]["binding_ids"] == [one]
    assert default.json()["context"]["provenance"] == "instance_default"
    assert default.json()["context"]["has_bearer_digest"] is False

    # 2. A retained session outranks the instance default.
    session = _create(api, two)
    by_session = resolve({"X-Active-Context-Session": session})
    assert by_session.status_code == 200, by_session.text
    assert by_session.json()["context"]["binding_ids"] == [two]
    assert by_session.json()["context"]["provenance"] == "session_selection"
    assert by_session.json()["context"]["has_bearer_digest"] is True

    # 3. A one-request override outranks the session (and does not consume it).
    override = _create(api, three)
    by_override = resolve(
        {"X-Active-Context-Session": session, "X-Active-Context-Override": override}
    )
    assert by_override.status_code == 200, by_override.text
    assert by_override.json()["context"]["binding_ids"] == [three]
    assert resolve({"X-Active-Context-Session": session}).json()["context"]["binding_ids"] == [
        two
    ]

    # The same precedence holds on a shipped scoped route.
    scoped = api.get(NOTES_URL, headers={"X-Active-Context-Session": session})
    assert scoped.status_code == 200, scoped.text
    assert {note["vault_binding_id"] for note in scoped.json()["notes"]} == {two}

    # 4. An invalid explicit choice fails closed at its own precedence level. It never
    # degrades to the next level: not to the session, not to the default, not to the
    # last-active/CWD vault, and not to any other binding.
    for headers in (
        {"X-Active-Context-Session": "never-issued"},
        {"X-Active-Context-Override": "never-issued"},
        {"X-Active-Context-Session": session, "X-Active-Context-Override": "never-issued"},
    ):
        refused = resolve(headers)
        assert refused.status_code == 401, (headers, refused.text)
        assert refused.json()["detail"].startswith("reselection_required")
        assert "context" not in refused.json()

    # 5. With the default explicitly cleared through the production producer, an omitted
    # selection is the healthy no-vault state -- still not last-active or CWD.
    open_default_vault_service(runtime.layout.registry_path).clear()
    assert runtime.registry.load().default_vault_binding_id is None
    no_vault = resolve()
    assert no_vault.status_code == 200, no_vault.text
    assert no_vault.json()["context"]["binding_ids"] == []
    assert no_vault.json()["context"]["provenance"] == "no_vault"
    assert no_vault.json()["context"]["posture"] == "healthy"
    assert no_vault.json()["context"]["is_no_vault"] is True

    # ...and an invalid explicit choice is still a reselection, not that no-vault state.
    after_clear = resolve({"X-Active-Context-Session": "never-issued"})
    assert after_clear.status_code == 401, after_clear.text

    # Explicit selection still outranks the (now absent) default.
    assert resolve({"X-Active-Context-Session": session}).json()["context"]["binding_ids"] == [
        two
    ]

    # 6. A process restart forgets every selection: an omitted id resolves the current
    # instance policy (no-vault here), while a presented pre-restart id fails closed.
    selection_routes.reset_selection_store_for_tests()
    assert resolve().json()["context"]["provenance"] == "no_vault"
    stale = resolve({"X-Active-Context-Session": session})
    assert stale.status_code == 401, stale.text

    # Resolution never wrote picker history or the default as a side effect.
    after = runtime.registry.load()
    assert after.default_vault_binding_id is None
    assert after.last_active_vault_ref == after.registrations[three].ref

    # 7. Before an instance registry exists the process keeps the explicit pre-registry
    # no-vault journey: no context is resolved at all, and nothing is guessed from CWD.
    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH")
    pre_registry = resolve({"X-Active-Context-Session": session})
    assert pre_registry.status_code == 200, pre_registry.text
    assert pre_registry.json() == {"context": None}
