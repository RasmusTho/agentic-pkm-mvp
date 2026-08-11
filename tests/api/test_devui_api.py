"""API contract for the read-only devUI composition route (#4682)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.auth as auth_module
from app.api.app import app
from app.api.routes import devui as devui_route
from app.builderops.devui_composition import compose_owner_snapshot
from app.builderops.ckm.contracts import (
    CkmContractError,
    CkmStateIdentity,
    CompletenessManifest,
    ErrorEnvelope,
    ObjectClassCompleteness,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    canonical_digest,
    canonical_query_digest,
)


def _focus_inputs(subject: str) -> dict:
    authority_ref = {
        "source_type": "github_issue",
        "source_id": "RasmusTho/agentic-pkm-mvp#4768",
        "version": "2026-08-11T17:53:40+00:00",
        "locator": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768",
    }
    claim = {
        "claim_id": "governing-subject",
        "claim": "The selected Issue is readable.",
        "source_ref": authority_ref,
        "availability": "available",
        "freshness": "fresh",
        "coverage": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": "2026-08-11T17:53:40+00:00",
        "limitation": None,
    }
    return {
        "subject": {
            "kind": "issue",
            "stable_id": subject,
            "authority_ref": authority_ref,
            "title": "Expose an admitted local Focus GET route",
        },
        "owner_intent": {"summary": "Read one governed Issue.", "source_ref": authority_ref},
        "governing_sources": [claim],
        "evidence": [{**claim, "claim_id": "subject-read"}],
        "receipts": [],
        "risks": [],
        "next_legal_step": {"workflow_ref": None, "actor_class": "system", "legality": "unavailable", "reason": "Read only."},
        "execution_observations": [],
        "conversation_port": {"availability": "unsupported", "reason": "Not delivered."},
        "limitations": [],
    }


def test_focus_route_returns_subject_matched_projection(monkeypatch) -> None:
    subject = "github:RasmusTho/agentic-pkm-mvp#4768"
    monkeypatch.setattr(devui_route, "read_focus_inputs", lambda requested: _focus_inputs(requested))

    response = TestClient(app).get("/api/devui/focus", params={"subject": subject})

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "focus-view.v1"
    assert payload["subject"]["stable_id"] == subject


def test_focus_route_fails_closed_for_unadmitted_or_unsupported_subjects(monkeypatch) -> None:
    def must_not_read(subject: str) -> dict:
        raise AssertionError(f"Focus inputs must not be read for unadmitted request: {subject}")

    monkeypatch.setattr(devui_route, "read_focus_inputs", must_not_read)
    remote = TestClient(app, client=("203.0.113.10", 50000))
    assert remote.get("/api/devui/focus", params={"subject": "devui_focus"}).status_code == 403

    monkeypatch.setattr(
        devui_route,
        "read_focus_inputs",
        lambda subject: (_ for _ in ()).throw(devui_route.FocusInputError("unsupported")),
    )
    response = TestClient(app).get("/api/devui/focus", params={"subject": "provider:session:1"})
    assert response.status_code == 404
    assert response.headers.get("location") is None
    assert TestClient(app).get("/api/devui/focus", params={"subject": ""}).status_code == 404


def test_focus_route_is_get_only_and_stateless(monkeypatch) -> None:
    subject = "github:RasmusTho/agentic-pkm-mvp#4768"
    calls: list[str] = []

    def reader(requested: str) -> dict:
        calls.append(requested)
        return _focus_inputs(requested)

    monkeypatch.setattr(devui_route, "read_focus_inputs", reader)
    client = TestClient(app)
    assert client.get("/api/devui/focus", params={"subject": subject}).status_code == 200
    assert client.get("/api/devui/focus", params={"subject": subject}).status_code == 200
    assert calls == [subject, subject]
    assert client.post("/api/devui/focus", params={"subject": subject}).status_code == 405
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/devui/focus")
    assert route.methods == {"GET"}


def test_focus_route_reuses_delivered_composer_without_root_join(monkeypatch) -> None:
    subject = "github:RasmusTho/agentic-pkm-mvp#4768"
    inputs = _focus_inputs(subject)
    seen: dict[str, object] = {}

    def composer(**kwargs: object) -> dict:
        seen.update(kwargs)
        return {"contract_version": "focus-view.v1", "subject": kwargs["subject"]}

    monkeypatch.setattr(devui_route, "read_focus_inputs", lambda requested: inputs)
    monkeypatch.setattr(devui_route, "compose_focus_view", composer)
    response = TestClient(app).get("/api/devui/focus", params={"subject": subject})

    assert response.status_code == 200
    assert seen == inputs
    assert "composition" not in seen


def _dispatcher_source(read_at: str) -> dict:
    return {
        "name": "dispatcher-store",
        "state": "fresh",
        "last_successful_read": read_at,
        "detail": "read succeeded",
        "stale_after_days": 7,
        "configured": True,
    }


def _empty_ckm_envelope() -> ResultEnvelope:
    completeness = CompletenessManifest(
        object_classes=(
            ObjectClassCompleteness(object_class="capability", included=0),
        ),
        complete=True,
    )
    snapshot = SnapshotManifest.build(
        state=CkmStateIdentity(epoch="epoch-1", state_revision=1),
        taxonomy_digest=canonical_digest({"taxonomy": "fixture"}),
        watermarks={},
        provenance=(),
        completeness=completeness,
        read_set={"capability": ()},
    )
    return ResultEnvelope(
        resource_type="capability",
        query_digest=canonical_query_digest(
            {"operation": "list_capabilities", "public_id": None}
        ),
        snapshot=snapshot,
        resources=(),
    )


def _ckm_envelope_with_display(display_name: str) -> ResultEnvelope:
    resource = ResourceDto(
        public_id="ckm_capability_example",
        resource_type="capability",
        display_name=display_name,
        lifecycle="confirmed",
        provenance=({"kind": "fixture"},),
        values={},
        candidate=False,
    )
    completeness = CompletenessManifest(
        object_classes=(
            ObjectClassCompleteness(object_class="capability", included=1),
        ),
        complete=True,
    )
    snapshot = SnapshotManifest.build(
        state=CkmStateIdentity(epoch="epoch-1", state_revision=1),
        taxonomy_digest=canonical_digest({"taxonomy": "fixture"}),
        watermarks={},
        provenance=(),
        completeness=completeness,
        read_set={"capability": (resource.public_id,)},
    )
    return ResultEnvelope(
        resource_type="capability",
        query_digest=canonical_query_digest(
            {"operation": "list_capabilities", "public_id": None}
        ),
        snapshot=snapshot,
        resources=(resource,),
    )


def test_devui_composition_route_is_get_only_and_read_only(monkeypatch) -> None:
    cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {
            "kind": "counted",
            "text": "one thread",
            "as_of": "2026-08-08T21:00:00+00:00",
        },
        "sources": [_dispatcher_source("2026-08-08T21:00:00+00:00")],
        "unread_planes": [],
        "withdrawn_counts": [],
    }
    ckm_envelope = _empty_ckm_envelope()
    ckm = ckm_envelope.to_dict()
    seen: list[Path] = []

    class ReadOnlyCkm:
        def __init__(self, db_path: Path) -> None:
            seen.append(db_path)

        def list_capabilities(self):
            return ckm_envelope

    monkeypatch.setattr(devui_route, "read_cockpit_registry", lambda: cockpit)
    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path("/state/builderops.sqlite3")),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", ReadOnlyCkm)

    client = TestClient(app)
    response = client.get("/api/devui/composition")

    assert response.status_code == 200
    assert response.json()["contract_version"] == "devui.composition.v1"
    assert response.json()["providers"]["work"]["payload"] == cockpit
    assert response.json()["providers"]["capabilities"]["payload"] == ckm
    assert seen == [Path("/state/builderops.sqlite3")]

    assert client.post("/api/devui/composition").status_code == 405
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/devui/composition"
    )
    assert route.methods == {"GET"}


def test_devui_composition_refuses_non_loopback_even_with_api_key(
    monkeypatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", "valid-key")

    def must_not_read() -> dict:
        raise AssertionError("local providers must not be read for a remote caller")

    monkeypatch.setattr(devui_route, "read_cockpit_registry", must_not_read)
    remote = TestClient(app, client=("203.0.113.10", 50000))

    response = remote.get(
        "/api/devui/composition",
        headers={"X-API-Key": "valid-key"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "devUI composition is available only to a local caller"
    }


def test_devui_composition_refuses_forwarded_remote_caller(monkeypatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    response = TestClient(app).get(
        "/api/devui/composition",
        headers={"X-Forwarded-For": "203.0.113.10"},
    )

    assert response.status_code == 403


def test_devui_composition_refuses_trusted_proxy_forwarding_loopback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        auth_module.settings,
        "companion_trusted_proxy_hosts",
        "172.18.0.1",
    )
    response = TestClient(app, client=("172.18.0.1", 50000)).get(
        "/api/devui/composition",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 403


def test_devui_composition_refuses_other_forwarded_identity_headers() -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))

    for name, value in (
        ("Forwarded", "for=127.0.0.1"),
        ("X-Real-IP", "127.0.0.1"),
        ("CF-Connecting-IP", "127.0.0.1"),
        ("X-Original-Forwarded-For", "127.0.0.1"),
        ("X-Envoy-External-Address", "127.0.0.1"),
    ):
        assert client.get(
            "/api/devui/composition",
            headers={name: value},
        ).status_code == 403

    assert client.get(
        "/api/devui/composition",
        headers={"Host": "attacker.example"},
    ).status_code == 403


def test_devui_composition_sanitizes_ckm_refusal_diagnostics(
    monkeypatch,
) -> None:
    secret = "/private/ckm.sqlite3"
    cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {
            "kind": "refused",
            "text": "source unavailable",
            "as_of": "2026-08-08T21:00:00+00:00",
        },
        "sources": [
            {
                **_dispatcher_source("2026-08-08T21:00:00+00:00"),
                "state": "unavailable",
                "last_successful_read": None,
                "detail": "read failed",
            }
        ],
        "unread_planes": [],
        "withdrawn_counts": [],
    }
    refusal = ErrorEnvelope(
        CkmContractError(
            code="unsupported_store",
            message=f"SQLite could not open {secret}",
            details={
                "path": secret,
                "reason": f"OperationalError while reading {secret}",
            },
        )
    )

    class RefusingCkm:
        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path

        def list_capabilities(self):
            return refusal

    monkeypatch.setattr(devui_route, "read_cockpit_registry", lambda: cockpit)
    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path(secret)),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", RefusingCkm)

    payload = TestClient(app).get("/api/devui/composition").json()
    contribution = payload["providers"]["capabilities"]

    assert contribution["refusal"] == {
        "code": "unsupported_store",
        "message": "CKM refused the read request",
        "details": {},
    }
    assert secret not in repr(payload)
    assert "OperationalError" not in repr(payload)


def test_devui_composition_isolates_unserializable_cockpit_payload(
    monkeypatch,
) -> None:
    malformed_cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {
            "kind": "counted",
            "text": "one thread",
            "as_of": "2026-08-08T21:00:00+00:00",
        },
        "sources": [_dispatcher_source("2026-08-08T21:00:00+00:00")],
        "unread_planes": [],
        "withdrawn_counts": [],
        "bands": {"moving": object()},
    }

    class HealthyCkm:
        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path

        def list_capabilities(self):
            return _empty_ckm_envelope()

    monkeypatch.setattr(
        devui_route,
        "read_cockpit_registry",
        lambda: malformed_cockpit,
    )
    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path("/state/builderops.sqlite3")),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", HealthyCkm)

    response = TestClient(app).get("/api/devui/composition")

    assert response.status_code == 200
    assert response.json()["providers"]["work"]["status"] == "refused"
    assert response.json()["providers"]["capabilities"]["status"] == "available"


def test_devui_composition_isolates_non_utf8_provider_strings(monkeypatch) -> None:
    healthy_cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {
            "kind": "counted",
            "text": "one thread",
            "as_of": "2026-08-08T21:00:00+00:00",
        },
        "sources": [_dispatcher_source("2026-08-08T21:00:00+00:00")],
        "unread_planes": [],
        "withdrawn_counts": [],
        "bands": {},
    }
    malformed_cockpit = {
        **healthy_cockpit,
        "bands": {"label": "bad\ud800"},
    }

    class Ckm:
        envelope = _empty_ckm_envelope()

        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path

        def list_capabilities(self):
            return self.envelope

    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path("/state/builderops.sqlite3")),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", Ckm)

    monkeypatch.setattr(
        devui_route,
        "read_cockpit_registry",
        lambda: malformed_cockpit,
    )
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/devui/composition"
    )
    assert response.status_code == 200
    assert response.json()["providers"]["work"]["status"] == "refused"
    assert response.json()["providers"]["capabilities"]["status"] == "available"

    monkeypatch.setattr(
        devui_route,
        "read_cockpit_registry",
        lambda: healthy_cockpit,
    )
    Ckm.envelope = _ckm_envelope_with_display("bad\ud800")
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/devui/composition"
    )
    assert response.status_code == 200
    assert response.json()["providers"]["work"]["status"] == "available"
    assert response.json()["providers"]["capabilities"]["status"] == "refused"


def test_overview_route_reuses_local_admission_and_exact_contract(monkeypatch) -> None:
    composition = {"contract_version": "devui.composition.v1"}
    expected = {"contract_version": "devui-overview-view.v1", "now": []}

    monkeypatch.setattr(devui_route, "compose_owner_snapshot", lambda **_: composition)
    monkeypatch.setattr(devui_route, "compose_overview_view", lambda **_: expected)

    client = TestClient(app)
    assert client.get("/api/devui/overview").json() == expected
    assert (
        TestClient(app, client=("203.0.113.10", 50000)).get("/api/devui/overview").status_code
        == 403
    )
    assert (
        client.get("/api/devui/overview", headers={"X-Forwarded-For": "203.0.113.10"}).status_code
        == 403
    )


def test_overview_route_preserves_no_source_withdrawals(monkeypatch) -> None:
    cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {"kind": "counted", "text": "one thread", "as_of": "2026-08-08T21:00:00+00:00"},
        "sources": [_dispatcher_source("2026-08-08T21:00:00+00:00")],
        "unread_planes": [],
        "withdrawn_counts": [],
    }
    composition = compose_owner_snapshot(
        cockpit_reader=lambda: cockpit,
        ckm_reader=_empty_ckm_envelope,
    )
    monkeypatch.setattr(devui_route, "compose_owner_snapshot", lambda **_: composition)

    payload = TestClient(app).get("/api/devui/overview").json()

    assert payload["needs_you"] == []
    assert payload["ready_to_try"] == []
    assert {(item["zone"], item["kind"]) for item in payload["limitations"]} == {
        ("needs_you", "classification_withdrawn"),
        ("ready_to_try", "classification_withdrawn"),
    }


def test_overview_route_is_get_only() -> None:
    client = TestClient(app)

    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/devui/overview").status_code == 405

    route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/devui/overview"
    )
    assert route.methods == {"GET"}


def test_overview_route_uses_live_composition_and_delivered_composer(monkeypatch) -> None:
    composition = {"contract_version": "devui.composition.v1"}
    seen: dict[str, object] = {}

    def composition_reader(**kwargs: object) -> dict:
        seen["composition"] = kwargs
        return composition

    def overview_composer(**kwargs: object) -> dict:
        seen["overview"] = kwargs
        return {"contract_version": "devui-overview-view.v1"}

    monkeypatch.setattr(devui_route, "compose_owner_snapshot", composition_reader)
    monkeypatch.setattr(devui_route, "compose_overview_view", overview_composer)

    response = TestClient(app).get("/api/devui/overview")

    assert response.status_code == 200
    assert seen == {
        "composition": {
            "cockpit_reader": devui_route.read_cockpit_registry,
            "ckm_reader": devui_route._read_ckm_capabilities,
        },
        "overview": {"composition": composition},
    }
