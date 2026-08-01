"""MVR-03 (#3857): the delegated local-operator principal producer.

Before this slice the runtime had credentials but no principal. These tests prove the
missing producer exists for every real deployment posture, that production API and CLI
resolve the *same* record, that rotation preserves the role, and that ambiguous, missing, or
unsafe state fails loud with an explicit provisioning action.
"""

from __future__ import annotations

import json
import os
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
from app.api.app import app
from app.instance.local_operator_principal import (
    LOCAL_OPERATOR_PRINCIPAL_SCHEMA,
    PROVENANCE_EXISTING_CREDENTIAL,
    PROVENANCE_ZERO_KEY_LOOPBACK,
    AuthPosture,
    LocalOperatorPrincipalStore,
    PrincipalFloorNotRecordedError,
    PrincipalPreflightError,
    fingerprint_credential,
    preflight_auth_posture,
)
from app.instance.principal_fence import principal_floor_recorded, record_principal_floor
from app.instance.runtime import main as instance_runtime_main
from app.instance.runtime import open_local_operator_principal_store
from tests._mvr03_principal_harness import (
    complete_inventory,
    principal_record_path,
    provisioned_instance,
    run_principal_cutover,
)
from tests._mvr_default_vault_harness import active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

SELECTION_URL = "/api/companion/active-context/selection"


def _cli(*args: str) -> dict:
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(args))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def _existing_credential_posture(raw_key: str) -> AuthPosture:
    return AuthPosture(
        configured_credentials=1,
        credential_fingerprint=fingerprint_credential(raw_key),
        loopback_listener_proven=True,
        companion_proxy_configured=False,
    )


def test_existing_single_user_auth_migrates_to_distinct_delegated_role(
    tmp_path, monkeypatch
) -> None:
    """One configured credential becomes an opaque role, distinct from every other id."""

    runtime, first, _ = active_runtime(tmp_path)
    raw_key = "existing-single-user-key"
    posture = _existing_credential_posture(raw_key)

    # -- ordering: no durable role write before the floor -------------------------------
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    assert not principal_floor_recorded(runtime.registry)
    with pytest.raises(PrincipalFloorNotRecordedError):
        store.bootstrap(
            credential_fingerprint=posture.credential_fingerprint,
            subjects=preflight_auth_posture(posture),
            migration_provenance=PROVENANCE_EXISTING_CREDENTIAL,
            floor_recorded=False,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert not principal_record_path(runtime).exists(), (
        "a refused bootstrap must leave old auth state authoritative and write nothing"
    )

    record = run_principal_cutover(runtime, posture=posture, existing_install=True)

    # -- the record is private, versioned, and opaque -----------------------------------
    record_path = principal_record_path(runtime)
    assert record_path.exists()
    assert record_path.stat().st_mode & 0o777 == 0o600
    assert record_path.parent.stat().st_mode & 0o777 == 0o700
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["schema"] == LOCAL_OPERATOR_PRINCIPAL_SCHEMA
    assert payload["revision"] == 1
    assert payload["migration_provenance"] == PROVENANCE_EXISTING_CREDENTIAL

    # The raw key never reaches durable state; only its fingerprint does.
    assert raw_key not in record_path.read_text(encoding="utf-8")
    assert payload["credential_fingerprint"] == fingerprint_credential(raw_key)

    # The role id is distinct from the credential, its fingerprint, and appInstallId.
    snapshot = runtime.registry.load()
    role_id = record.local_operator_role_id
    assert role_id not in (raw_key, payload["credential_fingerprint"], snapshot.app_install_id)
    assert snapshot.app_install_id not in role_id
    assert raw_key not in role_id

    # -- production API and CLI resolve the same record ---------------------------------
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)
    created = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert created.status_code == 201, created.text
    assert created.json()["context"]["principal_id"] == role_id

    cli = _cli(
        "principal-show",
        "--registry-path",
        str(runtime.layout.registry_path),
        "--consumer",
        "cli",
    )
    assert cli["_exit_code"] == 0
    assert cli["local_operator_role_id"] == role_id
    assert cli["credential_bound"] is True
    # The CLI receipt is redaction-safe.
    assert raw_key not in json.dumps(cli)
    assert payload["credential_fingerprint"] not in json.dumps(cli)

    # -- rotation preserves the role id -------------------------------------------------
    rotated = _cli(
        "principal-rotate-credential",
        "--registry-path",
        str(runtime.layout.registry_path),
        "--credential",
        "rotated-key",
        "--consumer",
        "cli",
    )
    assert rotated["_exit_code"] == 0
    assert rotated["local_operator_role_id"] == role_id, "rotation must not mint a new role"
    assert rotated["revision"] == 2
    # Rotation did not disable the already-supported loopback subject.
    assert "trusted_loopback" in rotated["subjects"]
    assert "api_key_credential" in rotated["subjects"]

    # -- ambiguous / missing / unsafe state fails loud ----------------------------------
    with pytest.raises(PrincipalPreflightError) as ambiguous:
        preflight_auth_posture(
            AuthPosture(
                configured_credentials=2,
                credential_fingerprint=None,
                loopback_listener_proven=False,
                companion_proxy_configured=False,
            )
        )
    assert "ambiguous" in str(ambiguous.value)
    assert ambiguous.value.provisioning_action

    missing_store = LocalOperatorPrincipalStore(tmp_path / "nowhere" / "principal.json")
    with pytest.raises(PrincipalPreflightError) as missing:
        missing_store.require()
    assert "principal-bootstrap" in missing.value.provisioning_action

    record_path.chmod(0o644)
    try:
        with pytest.raises(PrincipalPreflightError) as unsafe:
            open_local_operator_principal_store(runtime.layout.registry_path).load()
        assert "mode is unsafe" in str(unsafe.value)
    finally:
        record_path.chmod(0o600)

    partial = tmp_path / "partial-state"
    partial.mkdir(mode=0o700)
    partial_path = partial / "local-operator-principal.json"
    partial_path.write_text(
        json.dumps({"schema": LOCAL_OPERATOR_PRINCIPAL_SCHEMA, "revision": 1}),
        encoding="utf-8",
    )
    partial_path.chmod(0o600)
    with pytest.raises(PrincipalPreflightError) as partial_error:
        LocalOperatorPrincipalStore(partial_path).load()
    assert "partial principal record" in str(partial_error.value)


def test_zero_key_loopback_and_trusted_companion_proxy_map_to_local_role(
    tmp_path, monkeypatch
) -> None:
    """Auth-disabled installs keep working: both server-proven subjects bind the role."""

    runtime, first, _ = active_runtime(tmp_path)
    posture = AuthPosture(
        configured_credentials=0,
        credential_fingerprint=None,
        loopback_listener_proven=True,
        companion_proxy_configured=True,
    )
    record = run_principal_cutover(runtime, posture=posture, existing_install=True)
    assert record.migration_provenance == PROVENANCE_ZERO_KEY_LOOPBACK
    assert record.subjects == ("trusted_loopback", "trusted_companion_proxy")
    assert record.credential_fingerprint is None

    # Both subjects resolve to the *same* delegated role.
    loopback = record.principal_for("trusted_loopback")
    proxy = record.principal_for("trusted_companion_proxy")
    assert loopback.principal_id == proxy.principal_id == record.local_operator_role_id
    assert loopback.principal_kind == "delegated_operator_role"

    # Production selection and the governed-write class both keep working with no key.
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    from app.settings import settings

    original = settings.api_key
    settings.api_key = None
    try:
        client = TestClient(app)  # loopback
        created = client.post(
            SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id]}
        )
        assert created.status_code == 201, created.text
        assert created.json()["context"]["principal_id"] == record.local_operator_role_id
    finally:
        settings.api_key = original

    # A forwarded header cannot claim either server-derived subject.
    assert record.principal_for("trusted_loopback").subject == "trusted_loopback"
    with pytest.raises(PrincipalPreflightError):
        record.principal_for("api_key_credential")


def test_zero_key_nontrusted_nonloopback_fails_principal_preflight(tmp_path) -> None:
    """Every other zero-credential non-loopback posture fails until provisioning."""

    with pytest.raises(PrincipalPreflightError) as error:
        preflight_auth_posture(
            AuthPosture(
                configured_credentials=0,
                credential_fingerprint=None,
                loopback_listener_proven=False,
                companion_proxy_configured=False,
            )
        )
    assert "no server-derivable principal" in str(error.value)
    assert "governed credential provisioning" in error.value.provisioning_action

    # And the HTTP gate refuses the spoofing attempt independently: an untrusted
    # non-loopback peer sending a forwarded-for header claiming loopback is still judged on
    # its immediate address.
    runtime, first, extra, record = provisioned_instance(tmp_path)
    os.environ["INSTANCE_VAULT_REGISTRY_PATH"] = str(runtime.layout.registry_path)
    selection_routes.reset_selection_store_for_tests()
    from app.settings import settings

    original = settings.api_key
    settings.api_key = None
    try:
        remote = TestClient(app, client=("203.0.113.55", 44100))
        spoofed = remote.post(
            SELECTION_URL,
            json={"vault_binding_ids": []},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert spoofed.status_code == 401
        assert "API key required" in spoofed.json()["detail"]
    finally:
        settings.api_key = original
        os.environ.pop("INSTANCE_VAULT_REGISTRY_PATH", None)


def test_configured_key_preserves_local_and_trusted_proxy_subjects(
    tmp_path, monkeypatch
) -> None:
    """A configured key does not disable the loopback / proxy subjects."""

    runtime, first, _ = active_runtime(tmp_path)
    raw_key = "configured-key"
    posture = AuthPosture(
        configured_credentials=1,
        credential_fingerprint=fingerprint_credential(raw_key),
        loopback_listener_proven=True,
        companion_proxy_configured=True,
    )
    record = run_principal_cutover(runtime, posture=posture)
    assert set(record.subjects) == {
        "trusted_loopback",
        "trusted_companion_proxy",
        "api_key_credential",
    }
    # All three map to one role.
    assert {
        record.principal_for(subject).principal_id for subject in record.subjects
    } == {record.local_operator_role_id}

    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    from app.settings import settings

    original = settings.api_key
    settings.api_key = raw_key
    try:
        # Middleware-admitted keyless loopback still resolves the local role.
        loopback_client = TestClient(app)
        admitted = loopback_client.post(SELECTION_URL, json={"vault_binding_ids": []})
        assert admitted.status_code == 201, admitted.text
        assert admitted.json()["context"]["principal_id"] == record.local_operator_role_id

        # A nontrusted peer still requires the key ...
        remote = TestClient(app, client=("203.0.113.77", 44101))
        assert remote.post(SELECTION_URL, json={"vault_binding_ids": []}).status_code == 401
        # ... and succeeds with it, resolving the same role.
        with_key = remote.post(
            SELECTION_URL,
            json={"vault_binding_ids": []},
            headers={"X-API-Key": raw_key},
        )
        assert with_key.status_code == 201, with_key.text
        assert with_key.json()["context"]["principal_id"] == record.local_operator_role_id
    finally:
        settings.api_key = original

    # Only an explicit governed posture change may revoke a subject, and it is atomic.
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    revoked = store.revoke_subject(
        "trusted_companion_proxy", _capability=STORAGE_MUTATION_CAPABILITY
    )
    assert "trusted_companion_proxy" not in revoked.subjects
    assert revoked.local_operator_role_id == record.local_operator_role_id
    assert revoked.revision == record.revision + 1


def test_fresh_channel_bootstrap_and_fixtures_use_the_same_producer(tmp_path) -> None:
    """New channel bootstrap and test fixtures produce the record the same way.

    A separate fixture path would be the classic invariant-without-producers defect the
    repo's `Invariant -> producers` rule exists to prevent, so this pins that the fixture
    harness and the headless CLI converge on one record.
    """

    runtime, first, _ = active_runtime(tmp_path)
    record_principal_floor(
        runtime.registry,
        inventory=complete_inventory(),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    bootstrapped = _cli(
        "principal-bootstrap",
        "--registry-path",
        str(runtime.layout.registry_path),
        "--loopback-proven",
        "--consumer",
        "bootstrap-init",
    )
    assert bootstrapped["_exit_code"] == 0
    role_id = bootstrapped["local_operator_role_id"]

    # The fixture harness resolves the same record rather than minting a second one.
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    assert store.require().local_operator_role_id == role_id

    # Bootstrap is idempotent for the same posture: re-running channel init does not mint
    # a rival identity.
    again = _cli(
        "principal-bootstrap",
        "--registry-path",
        str(runtime.layout.registry_path),
        "--loopback-proven",
        "--consumer",
        "api",
    )
    assert again["local_operator_role_id"] == role_id
    assert again["revision"] == 1

    # Without the floor, the same CLI refuses rather than writing.
    other = tmp_path / "second"
    other.mkdir()
    fresh_runtime, fresh_first, _ = active_runtime(other)
    refused = _cli(
        "principal-bootstrap",
        "--registry-path",
        str(fresh_runtime.layout.registry_path),
        "--loopback-proven",
        "--consumer",
        "api",
    )
    assert refused["_exit_code"] == 1
    assert "floor" in refused["error"]
    assert not Path(principal_record_path(fresh_runtime)).exists()
