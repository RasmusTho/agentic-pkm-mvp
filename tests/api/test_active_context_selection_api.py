"""MVR-03 (#3857): the production selection endpoints.

These are the four commands `docs/MULTI_VAULT_RUNTIME/VERSION_ACTIVE_CONTEXT_SELECTION.md`
requires -- create, replace, inspect, clear -- exercised as production HTTP, not as direct
store calls.
"""

from __future__ import annotations

import ast
import inspect
import logging

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
from app.api.app import app
from app.vault.manager import get_vault_manager
from tests._mvr03_principal_harness import provisioned_instance
from tests._mvr_default_vault_harness import active_runtime

SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0], record


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_production_selection_lifecycle_is_scoped_and_global_free(instance, client) -> None:
    """Create -> inspect -> replace -> clear, all scoped, none touching global state."""

    runtime, first, second, _ = instance
    manager = get_vault_manager()
    global_before = manager.context

    created = client.post(SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id]})
    assert created.status_code == 201, created.text
    bearer = created.json()["context_selection_id"]
    headers = {"X-Active-Context-Session": bearer}

    inspected = client.get(SELECTION_URL, headers=headers)
    assert inspected.status_code == 200
    assert inspected.json()["context"]["vault_binding_ids"] == [first.vault_binding_id]

    replaced = client.put(
        SELECTION_URL,
        json={"vault_binding_ids": [second.vault_binding_id]},
        headers=headers,
    )
    assert replaced.status_code == 200
    assert replaced.json()["context"]["vault_binding_ids"] == [second.vault_binding_id]
    assert replaced.json()["context"]["generation"] == 2

    cleared = client.delete(SELECTION_URL, headers=headers)
    assert cleared.status_code == 200
    assert cleared.json() == {"cleared": True}

    # After clear the bearer is gone; it fails closed rather than resolving a default.
    assert client.get(SELECTION_URL, headers=headers).status_code == 401

    # -- #2223 authentication is enforced in addition to the bearer --------------------
    monkeypatched_client = TestClient(app, client=("203.0.113.9", 5000))
    from app.settings import settings

    original_key = settings.api_key
    try:
        settings.api_key = "configured-key"
        # Non-loopback, no key at all.
        assert (
            monkeypatched_client.post(SELECTION_URL, json={"vault_binding_ids": []}).status_code
            == 401
        )
        # Non-loopback, wrong key.
        assert (
            monkeypatched_client.post(
                SELECTION_URL,
                json={"vault_binding_ids": []},
                headers={"X-API-Key": "wrong"},
            ).status_code
            == 401
        )
    finally:
        settings.api_key = original_key

    # -- process-global VaultManager was never mutated ----------------------------------
    assert manager.context == global_before

    # Structural, not just behavioural: the router does not reference the global manager,
    # and it is not the legacy `/api/companion/vault/select` adapter.
    tree = ast.parse(inspect.getsource(selection_routes))
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            referenced.add(node.module or "")
    for forbidden in ("get_vault_manager", "VaultManager", "select_vault", "app.vault.manager"):
        assert forbidden not in referenced

    # The legacy global adapter still exists and is a *different*, named surface.
    legacy = client.get("/api/companion/vault/context")
    assert legacy.status_code == 200
    assert "/vault/select" != SELECTION_URL


def test_unauthenticated_callers_are_rejected_before_instance_state_is_read(
    tmp_path, monkeypatch
) -> None:
    """The #2223 gate runs before any instance state is touched.

    Pins the *ordering*, not just the outcome. If the gate moved back inside the handler,
    an unauthenticated non-loopback caller would get a 503 that discloses whether a registry
    is bound and whether a principal is provisioned — an information leak to a caller who
    was never admitted. Both provisioning states are checked, because they are two different
    503s.
    """

    from app.settings import settings

    selection_routes.reset_selection_store_for_tests()
    remote = TestClient(app, client=("203.0.113.10", 40000))
    original = settings.api_key
    settings.api_key = "configured-key"
    try:
        # (a) no registry bound at all
        monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
        for verb, kwargs in (
            ("post", {"json": {"vault_binding_ids": []}}),
            ("put", {"json": {"vault_binding_ids": []}}),
            ("get", {}),
            ("delete", {}),
        ):
            response = getattr(remote, verb)(SELECTION_URL, **kwargs)
            assert response.status_code == 401, (
                f"{verb.upper()} leaked pre-auth state: {response.status_code} {response.text}"
            )
            assert "registry" not in response.text
            assert "principal" not in response.text

        # (b) registry bound, but no delegated role provisioned
        runtime, _, _ = active_runtime(tmp_path)
        monkeypatch.setenv(
            "INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path)
        )
        for verb, kwargs in (
            ("post", {"json": {"vault_binding_ids": []}}),
            ("put", {"json": {"vault_binding_ids": []}}),
            ("get", {}),
            ("delete", {}),
        ):
            response = getattr(remote, verb)(SELECTION_URL, **kwargs)
            assert response.status_code == 401, (
                f"{verb.upper()} leaked provisioning state: "
                f"{response.status_code} {response.text}"
            )
            assert "principal-bootstrap" not in response.text
    finally:
        settings.api_key = original


def test_binding_selection_endpoints_derive_workspace_and_cognitive_dimensions_server_side(
    instance, client
) -> None:
    """Explicit binding intent only; every cognitive field is server-derived."""

    runtime, first, second, principal_record = instance

    created = client.post(SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id]})
    assert created.status_code == 201
    context = created.json()["context"]

    snapshot = runtime.registry.load()
    # Workspace derived from the (absent) WSP workspace binding -> the typed no_workspace
    # state, never inferred from the selected vault or its path.
    assert context["workspace"] == "no_workspace:"
    assert first.path not in str(context)
    # Canonical server-owned scope fallback.
    assert context["scope"] == "default"
    # Canonical legal defaults.
    assert context["sphere_memberships"] == []
    assert context["situated_identity"] is None
    # Principal and instance identity from auth/GOV and the registry, not the request.
    assert context["principal_id"] == principal_record.local_operator_role_id
    assert context["instance_identity"] == snapshot.app_install_id

    # Any client-authored cognitive or authority field is rejected, not ignored. A silent
    # ignore would let a caller believe it had set context it did not set.
    rejected_fields = {
        "workspace_id": "w-1",
        "workspace": "w-1",
        "scope": "private",
        "sphere_memberships": ["secret"],
        "situated_identity": "root",
        "principal_id": "someone-else",
        "principal_kind": "human",
        "action": "hka.write_note",
        "write_class": "governed_content",
        "permission": "hka.write",
        "required_permission": "hka.write",
        # MVR-04 (#3858) unsealed `dimension_id` as selection intent; the *projection*
        # shapes stay rejected, and a dimension id combined with explicit bindings is
        # refused separately below rather than merged.
        "dimension_filter": ["dim-1"],
        "dimension": {"members": ["binding-1"]},
        "dimension_revision": 7,
        "context_id": "ctx-forged",
        "generation": 99,
        "selection_capability_digest": "0" * 64,
        "expires_at": 9_999_999_999,
    }
    for field, value in rejected_fields.items():
        for verb, kwargs in (
            ("post", {}),
            (
                "put",
                {"headers": {"X-Active-Context-Session": created.json()["context_selection_id"]}},
            ),
        ):
            response = getattr(client, verb)(
                SELECTION_URL,
                json={"vault_binding_ids": [first.vault_binding_id], field: value},
                **kwargs,
            )
            assert response.status_code == 422, (
                f"{verb.upper()} accepted client-authored {field!r}: {response.text}"
            )

    # `dimension_id` is legitimate MVR-04 intent, but it is an alternative to explicit
    # bindings, never an addition to them: a union would be a client-authored projection
    # wearing a stored dimension's name.
    both = client.post(
        SELECTION_URL,
        json={"vault_binding_ids": [first.vault_binding_id], "dimension_id": "dim-1"},
    )
    assert both.status_code == 400, both.text
    assert "never both" in both.json()["detail"]

    # None of the rejected attempts reached the stored snapshot.
    read_back = client.get(
        SELECTION_URL,
        headers={"X-Active-Context-Session": created.json()["context_selection_id"]},
    ).json()["context"]
    assert read_back["scope"] == "default"
    assert read_back["sphere_memberships"] == []
    assert read_back["situated_identity"] is None
    assert read_back["principal_id"] == principal_record.local_operator_role_id

    # MVR-04 (#3858) added dimension *provenance* to the response, and an explicitly
    # enumerated selection carries none: no rejected attempt turned this into a dimension
    # selection, and the field is absent-valued rather than fabricated.
    assert read_back["dimension_id"] is None
    assert read_back["dimension_revision"] is None

    # An unknown binding id is refused rather than silently dropped.
    unknown = client.post(SELECTION_URL, json={"vault_binding_ids": ["never-registered"]})
    assert unknown.status_code == 404


def test_selection_bearer_is_redacted_from_success_failure_logs_and_receipts(
    instance, client, caplog
) -> None:
    """The raw bearer appears in exactly one place: the create response body.

    Success and failure paths are both checked, because a failure path is where a bearer is
    most likely to leak -- into a validation error or an exception message.
    """

    runtime, first, second, _ = instance

    with caplog.at_level(logging.DEBUG):
        created = client.post(
            SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id]}
        )
        assert created.status_code == 201
        bearer = created.json()["context_selection_id"]
        headers = {"X-Active-Context-Session": bearer}

        # success paths
        inspected = client.get(SELECTION_URL, headers=headers)
        replaced = client.put(
            SELECTION_URL,
            json={"vault_binding_ids": [second.vault_binding_id]},
            headers=headers,
        )
        # failure paths
        unknown_bearer = "leaky-bearer-value-should-not-appear"
        stale = client.get(
            SELECTION_URL, headers={"X-Active-Context-Session": unknown_bearer}
        )
        invalid_body = client.post(SELECTION_URL, json={"scope": "private"})
        missing_bearer = client.get(SELECTION_URL)

    assert inspected.status_code == 200
    assert replaced.status_code == 200
    assert stale.status_code == 401
    assert invalid_body.status_code == 422
    assert missing_bearer.status_code == 400

    # The bearer never appears in any success or failure response body other than create.
    for response in (inspected, replaced, stale, invalid_body, missing_bearer):
        assert bearer not in response.text
    # Nor does the presented (unknown) one get echoed back.
    assert unknown_bearer not in stale.text

    # Only the non-reversible digest is present in bounded context identity ...
    digest = inspected.json()["context"]["selection_capability_digest"]
    assert len(digest) == 64
    assert digest != bearer
    assert bearer not in digest

    # ... and the digest is genuinely non-reversible in the sense that matters here: it is
    # a one-way function of the bearer, so it cannot be replayed as one.
    assert client.get(SELECTION_URL, headers={"X-Active-Context-Session": digest}).status_code == 401

    # Application and access logs, traces, and metric labels are all captured by caplog in
    # this process; none of them carries the bearer.
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert bearer not in log_text
    assert unknown_bearer not in log_text

    # The receipt-safe projection is structurally bearer-free.
    store = selection_routes.get_selection_store()
    receipt_fields = set(
        selection_routes.SelectionContext.model_fields  # type: ignore[attr-defined]
    )
    assert "context_selection_id" not in receipt_fields
    assert "selection_capability_digest" in receipt_fields
    assert len(store) >= 1
