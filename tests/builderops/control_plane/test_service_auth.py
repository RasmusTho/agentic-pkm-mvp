from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane import AuthorityObjectResult, Lease, TransactionResult
from app.builderops.control_plane.auth import (
    CredentialConfigurationError,
    CredentialRegistry,
)
from app.builderops.control_plane.health import HealthService, OperationalStatus
from app.builderops.control_plane.service import (
    _assert_durable_payload_safe,
    create_app,
    database_environment,
)


class _Operational:
    def snapshot(self) -> OperationalStatus:
        return OperationalStatus(
            executor_heartbeat_state="healthy",
            recovery_pipeline_state="current",
            recovery_target_independent=True,
        )


class _Store:
    def __init__(self) -> None:
        self.claims: dict[str, tuple[TransactionResult, Lease]] = {}
        self.last_actor: str | None = None

    def readiness(self) -> dict[str, int]:
        return {"schema_version": 1, "authority_epoch": 1}

    def claim_lease(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_actor = kwargs["envelope"].actor
        key = kwargs["idempotency_key"]
        if key not in self.claims:
            lease = Lease(
                repository=kwargs["envelope"].repository,
                resource_id=kwargs["resource_id"],
                holder=kwargs["holder"],
                fencing_token=1,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                lease_kind="generic",
            )
            self.claims[key] = (
                TransactionResult(
                    repository=kwargs["envelope"].repository,
                    task_id=kwargs["resource_id"],
                    state="lease.claimed",
                    receipt_sequence=1,
                    recovery_lsn="0/1",
                    operation_key=None,
                ),
                lease,
            )
        result, lease = self.claims[key]
        if len([claim for claim in self.claims if claim == key]) and key in self.claims:
            return result, lease
        return result, lease

    def commit_record(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_actor = kwargs["envelope"].actor
        return AuthorityObjectResult(
            repository=kwargs["envelope"].repository,
            object_kind="record",
            object_id=kwargs["record_id"],
            state=kwargs["state"],
            receipt_sequence=2,
            recovery_lsn="0/2",
        )


def _registry(tmp_path: Path) -> CredentialRegistry:
    client_secret = tmp_path / "client.secret"
    read_secret = tmp_path / "read.secret"
    client_secret.write_text("client-token\n", encoding="utf-8")
    read_secret.write_text("read-token\n", encoding="utf-8")
    manifest = tmp_path / "credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "client",
                        "principal": "client:macbook",
                        "secret_ref": "host-secret:client",
                        "secret_file": str(client_secret),
                        "scopes": [
                            "health:read",
                            "status:read",
                            "metrics:read",
                            "leases:write",
                            "records:write",
                        ],
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    },
                    {
                        "id": "health-probe",
                        "principal": "probe:builder-host",
                        "secret_ref": "host-secret:probe",
                        "secret_file": str(read_secret),
                        "scopes": ["health:read"],
                        "rotation_generation": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return CredentialRegistry(manifest)


def _lease_payload() -> dict[str, object]:
    return {
        "envelope": {
            "repository": "RasmusTho/agentic-pkm-mvp",
            "scope": "issue:3790",
            "stack": "builderops-control-plane",
            "source_refs": ["github:issue:3790"],
        },
        "resource_id": "resource-1",
        "idempotency_key": "claim-resource-1",
        "request": {"command": "claim"},
        "ttl_seconds": 60,
    }


def _record_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "envelope": _lease_payload()["envelope"],
        "record_id": "learning-3790",
        "record_type": "LearningSignal",
        "state": "active",
        "payload": payload,
        "idempotency_key": "record-learning-3790",
    }


def test_scoped_api_auth_fails_closed(tmp_path: Path) -> None:
    store = _Store()
    registry = _registry(tmp_path)
    health = HealthService(store, registry, _Operational())  # type: ignore[arg-type]
    client = TestClient(create_app(store=store, credentials=registry, health=health))  # type: ignore[arg-type]

    assert client.get("/healthz").status_code == 401
    assert client.get("/healthz", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post(
        "/v1/leases/claim",
        headers={"Authorization": "Bearer read-token"},
        json=_lease_payload(),
    ).status_code == 403

    headers = {"Authorization": "Bearer client-token"}
    first = client.post("/v1/leases/claim", headers=headers, json=_lease_payload())
    replay = client.post("/v1/leases/claim", headers=headers, json=_lease_payload())
    assert first.status_code == replay.status_code == 200
    assert first.json()["lease"]["fencing_token"] == replay.json()["lease"]["fencing_token"] == 1
    assert first.json()["lease"]["holder"] == "client:macbook"
    assert store.last_actor == "client:macbook"
    assert "client-token" not in first.text

    assert client.get("/metrics", headers=headers).status_code == 200
    safe_record = client.post(
        "/v1/records",
        headers=headers,
        json=_record_payload(
            {
                "summary": "credential rotation observed",
                "secret_ref": "keychain:builderops/client",
                "fingerprint": "f" * 64,
                "credential_id": "builderops-client.2",
                "scopes": ["records:write", "leases:write"],
                "rotation_generation": 2,
                "token_length": len("client-token"),
            }
        ),
    )
    assert safe_record.status_code == 200
    for unsafe in (
        {"github_token": "github_pat_RAW"},
        {"github-token": "opaque-sensitive-value"},
        {"apiKey": "opaque-sensitive-value"},
        {"APIKey": "opaque-sensitive-value"},
        {"apikey": "opaque-sensitive-value"},
        {"privatekey": "opaque-sensitive-value"},
        {"session cookie": "opaque-sensitive-value"},
        {"fingerprint": "opaque-raw-database-password"},
        {"secret_ref": "inline:opaque-raw-provider-secret"},
        {"summary": "client-token"},
        {"summary": "x=client-token&y"},
        {"database": "postgresql://app:raw-password@db/builderops"},
    ):
        rejected = client.post(
            "/v1/records",
            headers=headers,
            json={**_record_payload(unsafe), "idempotency_key": f"reject-{len(str(unsafe))}"},
        )
        assert rejected.status_code == 400
        assert "raw" not in rejected.text.lower()

    # Removing the credential's metadata from the host-owned manifest revokes
    # it without persisting raw material or restarting the service.
    manifest = json.loads(registry.manifest_path.read_text())
    manifest["credentials"] = manifest["credentials"][1:]
    registry.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert client.get("/healthz", headers=headers).status_code == 401
    assert client.get(
        "/healthz", headers={"Authorization": "Bearer read-token"}
    ).status_code == 200


def test_database_dsn_resolves_from_secret_file(tmp_path: Path) -> None:
    dsn_file = tmp_path / "database.secret"
    dsn_file.write_text("postgresql://builderops:raw-secret@db/builderops\n", encoding="utf-8")
    resolved = database_environment({"BUILDEROPS_DATABASE_URL_FILE": str(dsn_file)})
    assert resolved["BUILDEROPS_DATABASE_URL"].endswith("@db/builderops")
    assert resolved["BUILDEROPS_DATABASE_URL_FILE"] == str(dsn_file)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda entry, secret: entry.update(secret_ref=secret),
        lambda entry, _secret: entry.update(id="bad id"),
        lambda entry, _secret: entry.update(principal="bad principal!"),
        lambda entry, _secret: entry.update(scopes=["records:write", "records:write"]),
        lambda entry, _secret: entry.update(scopes=["unbounded"]),
        lambda entry, _secret: entry.update(rotation_generation=True),
        lambda entry, _secret: entry.update(rotation_generation=1.5),
        lambda entry, _secret: entry.update(rotation_generation="1"),
        lambda entry, _secret: entry.update(id=123),
        lambda entry, _secret: entry.update(revoked="false"),
        lambda entry, _secret: entry.update(token_length="13"),
    ),
)
def test_malformed_credential_metadata_fails_secret_safe(
    tmp_path: Path, mutation
) -> None:  # type: ignore[no-untyped-def]
    secret = "bcp-client-RAW-MANIFEST-3790"
    secret_file = tmp_path / "secret"
    secret_file.write_text(secret, encoding="utf-8")
    entry = {
        "id": "client",
        "principal": "client:one",
        "secret_ref": "host-secret:client",
        "secret_file": str(secret_file),
        "scopes": ["records:write"],
        "rotation_generation": 1,
    }
    mutation(entry, secret)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"credentials": [entry]}), encoding="utf-8")
    registry = CredentialRegistry(manifest)

    with pytest.raises(CredentialConfigurationError) as raised:
        registry.status()
    assert secret not in str(raised.value)


def test_duplicate_credential_ids_and_verifiers_fail_closed(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("shared-secret", encoding="utf-8")
    base = {
        "id": "client",
        "principal": "client:one",
        "secret_ref": "host-secret:client",
        "secret_file": str(secret_file),
        "scopes": ["records:write"],
        "rotation_generation": 1,
    }
    manifest = tmp_path / "manifest.json"
    for second in (
        {**base, "principal": "client:two", "secret_ref": "host-secret:two"},
        {
            **base,
            "id": "client-two",
            "principal": "client:two",
            "secret_ref": "host-secret:two",
        },
    ):
        manifest.write_text(
            json.dumps({"credentials": [base, second]}), encoding="utf-8"
        )
        with pytest.raises(CredentialConfigurationError):
            CredentialRegistry(manifest).status()


def test_verifier_only_registered_bearer_cannot_be_embedded_in_durable_text(
    tmp_path: Path,
) -> None:
    secret = "client-token"
    manifest = tmp_path / "verifier-only.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "client",
                        "principal": "client:one",
                        "secret_ref": "host-secret:client",
                        "verifier_sha256": hashlib.sha256(secret.encode()).hexdigest(),
                        "token_length": len(secret),
                        "scopes": ["records:write"],
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = _Store()
    client = TestClient(create_app(store=store, credentials=CredentialRegistry(manifest)))  # type: ignore[arg-type]

    response = client.post(
        "/v1/records",
        headers={"Authorization": f"Bearer {secret}"},
        json=_record_payload({"summary": f"x={secret}&y"}),
    )

    assert response.status_code == 400


def test_verifier_only_registered_bearer_cannot_be_a_nested_mapping_key(
    tmp_path: Path,
) -> None:
    secret = "A7z9Q2m4K8p6"
    manifest = tmp_path / "opaque-verifier-only.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "opaque-client",
                        "principal": "client:opaque",
                        "secret_ref": "host-secret:opaque-client",
                        "verifier_sha256": hashlib.sha256(secret.encode()).hexdigest(),
                        "token_length": len(secret),
                        "scopes": ["records:write", "leases:write"],
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry = CredentialRegistry(manifest)
    store = _Store()
    client = TestClient(create_app(store=store, credentials=registry))  # type: ignore[arg-type]
    headers = {"Authorization": f"Bearer {secret}"}

    record = client.post(
        "/v1/records",
        headers=headers,
        json=_record_payload({"nested": {secret: "safe"}}),
    )
    lease_body = _lease_payload()
    lease_body["request"] = {"nested": {secret: "safe"}}
    lease = client.post("/v1/leases/claim", headers=headers, json=lease_body)

    assert record.status_code == 400
    assert lease.status_code == 400
    assert secret not in record.text
    assert secret not in lease.text
    assert store.claims == {}
    assert store.last_actor is None


def test_durable_text_scanning_has_per_field_and_request_work_bounds(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    store = _Store()
    client = TestClient(create_app(store=store, credentials=registry))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer client-token"}

    oversized_field = client.post(
        "/v1/records",
        headers=headers,
        json=_record_payload({"summary": "x" * 16_385}),
    )
    oversized_request = client.post(
        "/v1/records",
        headers=headers,
        json=_record_payload({f"field-{index}": "x" * 16_000 for index in range(17)}),
    )
    oversized_node_tree = client.post(
        "/v1/records",
        headers=headers,
        json=_record_payload({"values": list(range(10_001))}),
    )

    assert oversized_field.status_code == 400
    assert oversized_request.status_code == 400
    assert oversized_node_tree.status_code == 400
    assert store.last_actor is None


def test_raw_credentials_are_rejected_from_every_client_controlled_durable_field(
    tmp_path: Path,
) -> None:
    store = _Store()
    registry = _registry(tmp_path)
    canary = "raw-bearer/repo"
    canary_secret = tmp_path / "durable-canary.secret"
    canary_secret.write_text(canary + "\n", encoding="utf-8")
    manifest = json.loads(registry.manifest_path.read_text(encoding="utf-8"))
    manifest["credentials"].append(
        {
            "id": "durable-canary",
            "principal": "test:durable-canary",
            "secret_ref": "host-secret:durable-canary",
            "secret_file": str(canary_secret),
            "scopes": ["records:write"],
            "rotation_generation": 1,
        }
    )
    registry.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    health = HealthService(store, registry, _Operational())  # type: ignore[arg-type]
    client = TestClient(create_app(store=store, credentials=registry, health=health))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer client-token"}

    # The `repository` mutation is a distinct case: the credential is scoped to
    # exactly "RasmusTho/agentic-pkm-mvp" (see `_registry()`), so redirecting
    # the envelope at the canary-shaped repository string is caught by the
    # earlier, more specific repo-scope gate (403) before the request ever
    # reaches the durable-payload scanner. Every other field is untouched by
    # repo-scope routing and is still caught by the durable-payload scanner (400).
    lease_mutations = (
        (lambda body: body["envelope"].update(repository=canary), 403),
        (lambda body: body["envelope"].update(scope=canary), 400),
        (lambda body: body["envelope"].update(stack=canary), 400),
        (lambda body: body["envelope"].update(source_refs=[canary]), 400),
        (lambda body: body.update(resource_id=canary), 400),
        (lambda body: body.update(idempotency_key=canary), 400),
        (lambda body: body.update(request={"command": canary}), 400),
    )
    for mutate, expected_status in lease_mutations:
        body = _lease_payload()
        mutate(body)
        response = client.post("/v1/leases/claim", headers=headers, json=body)
        assert response.status_code == expected_status
        assert canary not in response.text

    record_mutations = (
        (lambda body: body["envelope"].update(repository=canary), 403),
        (lambda body: body["envelope"].update(scope=canary), 400),
        (lambda body: body["envelope"].update(stack=canary), 400),
        (lambda body: body["envelope"].update(source_refs=[canary]), 400),
        (lambda body: body.update(record_id=canary), 400),
        (lambda body: body.update(record_type=canary), 400),
        (lambda body: body.update(state=canary), 400),
        (lambda body: body.update(payload={"summary": canary}), 400),
        (lambda body: body.update(idempotency_key=canary), 400),
    )
    for mutate, expected_status in record_mutations:
        body = _record_payload({"summary": "safe"})
        mutate(body)
        response = client.post("/v1/records", headers=headers, json=body)
        assert response.status_code == expected_status
        assert canary not in response.text

    assert store.claims == {}
    assert store.last_actor is None


def _scoped_registry(tmp_path: Path) -> CredentialRegistry:
    """A normal MacBook client: repo-scoped writes, no executor/outbox scope."""
    secret = tmp_path / "normal.secret"
    secret.write_text("normal-token\n", encoding="utf-8")
    manifest = tmp_path / "scoped-credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "normal-client",
                        "principal": "client:macbook",
                        "secret_ref": "host-secret:normal-client",
                        "secret_file": str(secret),
                        "scopes": ["records:write", "leases:write", "tasks:write"],
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return CredentialRegistry(manifest)


def test_normal_client_cannot_use_executor_or_cross_repo_scope(tmp_path: Path) -> None:
    store = _Store()
    registry = _scoped_registry(tmp_path)
    health = HealthService(store, registry, _Operational())  # type: ignore[arg-type]
    client = TestClient(create_app(store=store, credentials=registry, health=health))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer normal-token"}

    # Positive control: the credential works for its own repository.
    granted = client.post(
        "/v1/records", headers=headers, json=_record_payload({"summary": "ok"})
    )
    assert granted.status_code == 200
    assert store.last_actor == "client:macbook"

    # A normal client credential holds no executor/outbox scope: the privileged
    # executor operation is forbidden (403), not silently downgraded.
    executor = client.post(
        "/v1/executor/outbox/claim",
        headers=headers,
        json={
            "envelope": _lease_payload()["envelope"],
            "operation_key": "outbox-3790",
            "worker_id": "worker:test-executor",
            "claim_ttl_seconds": 300,
        },
    )
    assert executor.status_code == 403

    # A credential scoped to one repository cannot address another repository;
    # the cross-repo write is rejected before it can reach the store.
    cross_repo = _record_payload({"summary": "ok"})
    cross_repo["envelope"] = {
        **_lease_payload()["envelope"],
        "repository": "OtherOwner/other-repo",
    }
    cross_repo["idempotency_key"] = "record-cross-repo"
    rejected = client.post("/v1/records", headers=headers, json=cross_repo)
    assert rejected.status_code == 403


def _unscoped_registry(tmp_path: Path) -> CredentialRegistry:
    """A credential with no ``repositories`` key and no ``all_repositories`` opt-in."""
    secret = tmp_path / "unscoped.secret"
    secret.write_text("unscoped-token\n", encoding="utf-8")
    manifest = tmp_path / "unscoped-credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "unscoped-client",
                        "principal": "client:unscoped",
                        "secret_ref": "host-secret:unscoped-client",
                        "secret_file": str(secret),
                        "scopes": ["records:write", "leases:write"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return CredentialRegistry(manifest)


def test_credential_with_no_repositories_key_cannot_address_any_repository(
    tmp_path: Path,
) -> None:
    """The default must fail closed: omitting ``repositories`` grants NO repo,
    not every repo. This is the explicit regression test for the credential
    fail-open default fixed for issue #3791 (a credential provisioned without
    listing repos previously had unrestricted cross-repo authority)."""
    store = _Store()
    registry = _unscoped_registry(tmp_path)
    client = TestClient(create_app(store=store, credentials=registry))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer unscoped-token"}

    for repository in (
        "RasmusTho/agentic-pkm-mvp",
        "RasmusTho/example-second-repo",
        "OtherOwner/other-repo",
    ):
        body = _record_payload({"summary": "ok"})
        body["envelope"] = {**body["envelope"], "repository": repository}
        body["idempotency_key"] = f"record-{repository.replace('/', '-')}"
        response = client.post("/v1/records", headers=headers, json=body)
        assert response.status_code == 403, (
            f"credential with no repositories/all_repositories should not "
            f"address {repository}, got {response.status_code}"
        )
    assert store.last_actor is None


def test_all_repositories_opt_in_is_explicit_and_distinct_from_empty_list(
    tmp_path: Path,
) -> None:
    """``all_repositories: true`` is a distinct, explicit opt-in (e.g. for the
    privileged executor); it must never be implied by an absent/empty
    ``repositories`` list, and combining both fails closed as ambiguous."""
    secret = tmp_path / "executor.secret"
    secret.write_text("executor-token\n", encoding="utf-8")
    manifest = tmp_path / "executor-credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "executor",
                        "principal": "executor:build-host",
                        "secret_ref": "host-secret:executor",
                        "secret_file": str(secret),
                        "scopes": ["records:write"],
                        "all_repositories": True,
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = _Store()
    client = TestClient(create_app(store=store, credentials=CredentialRegistry(manifest)))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer executor-token"}

    for repository in ("RasmusTho/agentic-pkm-mvp", "RasmusTho/example-second-repo"):
        body = _record_payload({"summary": "ok"})
        body["envelope"] = {**body["envelope"], "repository": repository}
        body["idempotency_key"] = f"executor-record-{repository.replace('/', '-')}"
        response = client.post("/v1/records", headers=headers, json=body)
        assert response.status_code == 200

    # Combining all_repositories with an explicit repositories list is
    # ambiguous and must fail closed at manifest-parse time, not silently
    # pick one interpretation.
    ambiguous_manifest = tmp_path / "ambiguous-credentials.json"
    ambiguous_manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "ambiguous",
                        "principal": "client:ambiguous",
                        "secret_ref": "host-secret:ambiguous",
                        "secret_file": str(secret),
                        "scopes": ["records:write"],
                        "all_repositories": True,
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CredentialConfigurationError):
        CredentialRegistry(ambiguous_manifest).status()


def test_fencing_token_key_in_free_form_payload_is_not_exempt(tmp_path: Path) -> None:
    """The structural ``fencing_token`` exemption is scoped to ``lease.fencing_token``
    with an int value; a free-form ``payload``/``request`` field that happens to
    be named ``fencing_token`` must still be rejected, even carrying a value
    that would NOT trip the weaker value-content heuristics (no bearer/ghp_/sk-/
    postgres:// shape, not equal to any registered credential) — proving the
    key-name-anywhere loophole (issue #3791 review finding C2) is closed."""
    store = _Store()
    registry = _registry(tmp_path)
    client = TestClient(create_app(store=store, credentials=registry))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer client-token"}

    plausible_but_unregistered = "foreign-service-opaque-credential-9f8e7d6c5b4a3210"

    # A top-level free-form payload field named "fencing_token" is rejected by
    # key-name alone (its parent is "payload", not "lease").
    smuggled = _record_payload({"fencing_token": plausible_but_unregistered})
    response = client.post("/v1/records", headers=headers, json=smuggled)
    assert response.status_code == 400
    assert plausible_but_unregistered not in response.text

    # Nesting an attacker-supplied "lease" key inside free-form payload content
    # must not resurrect the exemption either: the value is a string, not an
    # int, so the type gate still rejects it independent of the path match.
    nested = _record_payload({"lease": {"fencing_token": plausible_but_unregistered}})
    nested["idempotency_key"] = "record-nested-lease-fencing-token"
    nested_response = client.post("/v1/records", headers=headers, json=nested)
    assert nested_response.status_code == 400
    assert plausible_but_unregistered not in nested_response.text

    assert store.last_actor is None


def test_fencing_token_exemption_still_allows_the_legitimate_lease_field(
    tmp_path: Path,
) -> None:
    """Positive control: the real ``lease.fencing_token`` int field (as sent by
    every lease-carrying request the client issues) is unaffected by the C2
    narrowing — it is a direct child of a top-level ``lease`` object and its
    value is a genuine int."""
    registry = _registry(tmp_path)
    legitimate_request = {
        "envelope": {
            "repository": "RasmusTho/agentic-pkm-mvp",
            "scope": "issue:3790",
            "stack": "builderops-control-plane",
            "source_refs": ["github:issue:3790"],
        },
        "lease": {
            "resource_id": "issue-3790-task",
            "holder": "client:macbook",
            "fencing_token": 1,
            "expires_at": "2026-07-17T19:58:27.710736Z",
            "lease_kind": "task",
        },
        "idempotency_key": "heartbeat-legit",
        "request": {},
        "ttl_seconds": 5400,
    }
    # Must not raise: the exemption still covers the genuine typed field.
    _assert_durable_payload_safe(legitimate_request, registry)
