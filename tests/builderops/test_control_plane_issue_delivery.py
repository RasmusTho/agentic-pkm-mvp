"""FCA-ID-A production admission and transaction recovery proofs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneConflictError,
    ControlPlaneScopeError,
    ControlPlaneUnavailableError,
)
from app.builderops.control_plane.store import PostgresBuilderOpsStore
from app.builderops.control_plane.service import create_app

pytestmark = pytest.mark.pg

REPOSITORY = "RasmusTho/agentic-pkm-mvp"


def _dsn() -> str:
    value = os.getenv("BUILDEROPS_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not value:
        pytest.skip("no explicit non-production BuilderOps PostgreSQL DSN configured")
    return value


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def store() -> PostgresBuilderOpsStore:
    base = _dsn()
    try:
        with psycopg.connect(base, connect_timeout=2, autocommit=True) as conn:
            schema = f"builderops_issue_delivery_{uuid4().hex}"
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable for BuilderOps issue-delivery test: {exc}")
    dsn = _schema_dsn(base, schema)
    value = PostgresBuilderOpsStore(dsn)
    value.initialize()
    try:
        yield value
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def registry(tmp_path: Path) -> CredentialRegistry:
    entries = []
    for credential_id, principal, token, scopes, kind in (
        (
            "owner",
            "owner:human",
            "owner-token",
            ["issue_delivery:approve", "issue_delivery:read", "status:read"],
            "human",
        ),
        ("reader", "destination:reader", "reader-token", ["issue_delivery:read"], "agent"),
        ("inquiry", "inquiry:agent", "inquiry-token", ["inquiries:approve"], "agent"),
        ("generic", "generic:agent", "generic-token", ["records:write"], "agent"),
    ):
        secret = tmp_path / f"{credential_id}.secret"
        secret.write_text(token, encoding="utf-8")
        entries.append(
            {
                "id": credential_id,
                "principal": principal,
                "secret_ref": f"host-secret:{credential_id}",
                "secret_file": str(secret),
                "scopes": scopes,
                "repositories": [REPOSITORY],
                "rotation_generation": 1,
                "principal_kind": kind,
            }
        )
    manifest = tmp_path / "credentials.json"
    manifest.write_text(json.dumps({"credentials": entries}), encoding="utf-8")
    return CredentialRegistry(manifest)


def _manifest(*, operation_key: str = "operation-5550") -> dict[str, object]:
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    return {
        "contract_version": "fca-issue-delivery.v1",
        "operation_type": "deliver_ready_issue",
        "approval_id": "approval-5550",
        "operation_key": operation_key,
        "repository": REPOSITORY,
        "issue": {
            "number": 5550,
            "node_id": "I_kwDOQEip6s8AAAACdXiyQA",
            "title": "task: admit exact one-Issue delivery approval",
            "state": "open",
            "body_hash": "a" * 64,
            "acceptance_criteria_hash": "b" * 64,
        },
        "source": {
            "revision": "main:a5f0e10b666e74c4b8de36a67563a99e30ee801d",
            "refs": ["github:issue:5550", "git:a5f0e10b666e74c4b8de36a67563a99e30ee801d"],
        },
        "context": {"pack_id": "context-5550", "content_hash": "c" * 64},
        "workflow": {
            "version": "fca-issue-delivery.v1",
            "content_hash": "d" * 64,
            "entrypoint": "app/builderops/epic_dispatch.py::dispatch_issue_sessions",
        },
        "destination": {
            "identity": "executor:local",
            "run_id": "run-5550",
            "channel": "dev",
            "base_ref": "main",
            "base_sha": "e" * 40,
        },
        "profile": {
            "content_hash": "f" * 64,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
        },
        "permitted_effects": [
            "repository_worktree",
            "issue_claim",
            "publication",
            "review_merge",
            "closure_reconciliation",
        ],
        "explicit_non_effects": [
            "deployment",
            "credential_provisioning",
            "owner_acceptance",
        ],
        "parent_evidence": {"kind": "none"},
        "expires_at": expiry,
        "owner_profile": {"kind": "human-owner"},
    }


def _client(store: PostgresBuilderOpsStore, registry: CredentialRegistry, token: str) -> BuilderOpsControlPlaneClient:
    service = create_app(store=store, credentials=registry)
    return BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://builderops", token=token),
        http_client=TestClient(service),
        max_retries=0,
    )


def test_issue_approval_production_admission(store, registry) -> None:
    owner = _client(store, registry, "owner-token")
    reader = _client(store, registry, "reader-token")
    inquiry = _client(store, registry, "inquiry-token")
    generic = _client(store, registry, "generic-token")
    manifest = _manifest()

    preview = owner.issue_delivery_preview(manifest=manifest)
    assert preview["state"] == "previewed"
    assert preview["manifest"]["operation_type"] == "deliver_ready_issue"
    assert preview["manifest"]["owner_principal"] == "owner:human"
    assert preview["manifest"]["authority_epoch"] == 1

    held = owner.issue_delivery_start(decision="hold", manifest=preview["manifest"])
    assert held["state"] == "held"
    assert held["effects"] == []
    assert store.authority_counts(REPOSITORY.lower())["records"] == 0

    started = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert started["state"] == "approved"
    assert started["approval"]["approval_manifest_hash"] == preview["manifest"]["approval_manifest_hash"]
    assert started["receipt"]["receipt_sequence"] > 0

    replay = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert replay["state"] == "approved"
    assert replay["replayed"] is True
    assert replay["receipt"]["receipt_sequence"] == started["receipt"]["receipt_sequence"]

    readback = reader.issue_delivery_readback(repository=REPOSITORY, approval_id="approval-5550")
    assert readback["state"] == "approved"
    assert readback["manifest"]["operation_key"] == "operation-5550"
    assert readback["operation"]["operation_key"] == "operation-5550"

    for client in (inquiry, generic):
        with pytest.raises(ControlPlaneScopeError):
            client.issue_delivery_preview(manifest=manifest)

    changed_source = dict(preview["manifest"])
    changed_source["source"] = {**changed_source["source"], "revision": "main:changed"}
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="start", manifest=changed_source)

    changed_key = dict(preview["manifest"])
    changed_key["operation_key"] = "operation-5550-new"
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="start", manifest=changed_key)


def test_issue_approval_transaction_recovery(store, registry, monkeypatch) -> None:
    owner = _client(store, registry, "owner-token")
    preview = owner.issue_delivery_preview(manifest=_manifest(operation_key="operation-recovery"))
    original = store.commit_record

    def fail_before_commit(**kwargs):  # type: ignore[no-untyped-def]
        return original(**kwargs, fault_at="after_authority_object")

    monkeypatch.setattr(store, "commit_record", fail_before_commit)
    with pytest.raises(ControlPlaneUnavailableError):
        owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    with pytest.raises(KeyError):
        store.get_record(REPOSITORY, "issue-delivery-approval:approval-5550")

    monkeypatch.setattr(store, "commit_record", original)
    recovered = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert recovered["state"] == "approved"
    assert recovered["replayed"] is False
    assert store.get_record(REPOSITORY, "issue-delivery-approval:approval-5550")["state"] == "approved"
