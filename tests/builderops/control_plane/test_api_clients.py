"""BCP-04 AC1/AC2: authority commands use the remote API and fail closed.

These contract tests drive the real versioned client against a disposable
BCP-02 service (an in-memory store behind ``create_app``). They prove that the
representative MacBook commands cross the authenticated API boundary under one
authority epoch, and that any transport/auth failure raises a typed error
without leaving local authority, a SQLite/JSONL/JSON ledger, or a fabricated
GitHub lease behind.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneAuthError,
    ControlPlaneUnavailableError,
    StaleLeaseError,
)
from app.builderops.control_plane.models import (
    AuthorityObjectResult,
    Lease,
    TransactionResult,
)
from app.builderops.control_plane.service import create_app

REPO = "RasmusTho/agentic-pkm-mvp"
CANON = REPO.lower()


class InMemoryStore:
    """Minimal StorePort-shaped fake; records which methods the API reached."""

    def __init__(self) -> None:
        self.epoch = 1
        self.calls: list[str] = []
        self.records: dict[str, AuthorityObjectResult] = {}
        self._seq = 0

    def readiness(self) -> dict[str, int]:
        return {"schema_version": 1, "authority_epoch": self.epoch}

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def _lease(self, repository: str, resource_id: str, holder: str) -> Lease:
        return Lease(
            repository=repository,
            resource_id=resource_id,
            holder=holder,
            fencing_token=1,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=90),
            lease_kind="task",
        )

    def claim_task(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append("claim_task")
        result = TransactionResult(
            kw["envelope"].repository, kw["task_id"], "claimed", self._next(), "0/1", None
        )
        return result, self._lease(kw["envelope"].repository, kw["task_id"], kw["holder"])

    def heartbeat_lease(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append("heartbeat_lease")
        result = TransactionResult(
            kw["envelope"].repository, kw["lease"].resource_id, "heartbeat", self._next(), "0/2", None
        )
        return result, kw["lease"]

    def complete_task(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append("complete_task")
        return TransactionResult(
            kw["envelope"].repository, kw["lease"].resource_id, "completed", self._next(), "0/3", None
        )

    def commit_record(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(f"commit_record:{kw['record_type']}")
        result = AuthorityObjectResult(
            kw["envelope"].repository, "record", kw["record_id"], kw["state"], self._next(), "0/4"
        )
        self.records[kw["record_id"]] = result
        return result

    def get_record(self, repository: str, record_id: str):  # type: ignore[no-untyped-def]
        self.calls.append("get_record")
        result = self.records[record_id]
        return {
            "repository": result.repository,
            "object_id": result.object_id,
            "receipt_sequence": result.receipt_sequence,
            "state": result.state,
        }


def _registry(tmp_path: Path) -> CredentialRegistry:
    secret = tmp_path / "client.secret"
    secret.write_text("client-token\n", encoding="utf-8")
    manifest = tmp_path / "credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "client",
                        "principal": "client:macbook",
                        "secret_ref": "host-secret:client",
                        "secret_file": str(secret),
                        "scopes": [
                            "status:read",
                            "records:write",
                            "inquiries:write",
                            "tasks:write",
                            "receipts:read",
                        ],
                        "repositories": [REPO],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return CredentialRegistry(manifest)


def _client(store: InMemoryStore, registry: CredentialRegistry, token: str = "client-token"):
    transport = TestClient(create_app(store=store, credentials=registry))
    config = ClientConfig(base_url="http://builderops", token=token)
    return BuilderOpsControlPlaneClient(config, http_client=transport, max_retries=0)


def _envelope() -> dict[str, object]:
    return {
        "repository": REPO,
        "scope": "issue:3791",
        "stack": "builderops-control-plane",
        "source_refs": ["github:issue:3791"],
    }


def test_all_authority_commands_use_remote_api(tmp_path: Path) -> None:
    store = InMemoryStore()
    client = _client(store, _registry(tmp_path))

    # The client establishes exactly one authority epoch up front.
    assert client.authority_epoch == 1

    record = client.commit_record(
        envelope=_envelope(),
        record_id="learning-3791",
        record_type="LearningSignal",
        state="active",
        payload={"summary": "cutover"},
        idempotency_key="record-learning-3791",
    )
    inquiry = client.create_inquiry(
        envelope=_envelope(),
        inquiry_id="inquiry-3791",
        state="captured",
        payload={"question": "which route"},
        idempotency_key="inquiry-3791",
    )
    claim = client.claim_task(
        envelope=_envelope(),
        task_id="issue-3791",
        idempotency_key="claim-issue-3791",
    )
    heartbeat = client.heartbeat_task(
        envelope=_envelope(),
        lease=claim["lease"],
        idempotency_key="heartbeat-issue-3791",
    )
    complete = client.complete_task(
        envelope=_envelope(),
        lease=claim["lease"],
        idempotency_key="complete-issue-3791",
    )
    receipt = client.get_receipt(
        repository=REPO, object_kind="records", object_id="learning-3791"
    )

    # Every representative command actually crossed the API to the store.
    assert store.calls == [
        "commit_record:LearningSignal",
        "commit_record:ModelInquiry",
        "claim_task",
        "heartbeat_lease",
        "complete_task",
        "get_record",
    ]
    assert record["repository"] == CANON
    assert inquiry["object_id"] == "inquiry-3791"
    assert claim["lease"]["fencing_token"] == 1
    assert heartbeat["result"]["state"] == "heartbeat"
    assert complete["result"]["state"] == "completed"
    assert receipt["receipt_sequence"] == record["receipt_sequence"]

    # One authority epoch: after a recovery bumps the server epoch, the client
    # pinned to the prior epoch is fenced rather than mutating a new authority.
    store.epoch = 2
    with pytest.raises(StaleLeaseError):
        client.commit_record(
            envelope=_envelope(),
            record_id="learning-3791-b",
            record_type="LearningSignal",
            state="active",
            payload={},
            idempotency_key="record-learning-3791-b",
        )


def test_all_authority_commands_require_authentication(tmp_path: Path) -> None:
    store = InMemoryStore()
    client = _client(store, _registry(tmp_path), token="wrong-token")
    with pytest.raises(ControlPlaneAuthError):
        client.status()
    assert store.calls == []


def test_client_failure_never_creates_local_authority_fallback(tmp_path: Path) -> None:
    # Run inside an isolated working directory so any accidental local-authority
    # file would be observable.
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    prior = os.getcwd()
    os.chdir(workdir)
    try:
        # 1) Service unreachable -> typed unavailable error, no fallback.
        unreachable = BuilderOpsControlPlaneClient(
            ClientConfig(base_url="http://127.0.0.1:1", token="client-token"),
            max_retries=0,
        )
        with pytest.raises(ControlPlaneUnavailableError):
            unreachable.claim_lease(
                envelope=_envelope(),
                resource_id="resource-3791",
                idempotency_key="claim-resource-3791",
            )

        # 2) Credential rejected -> typed auth error, no fallback.
        store = InMemoryStore()
        rejected = _client(store, _registry(tmp_path), token="not-the-token")
        with pytest.raises(ControlPlaneAuthError):
            rejected.commit_record(
                envelope=_envelope(),
                record_id="learning-3791",
                record_type="LearningSignal",
                state="active",
                payload={},
                idempotency_key="record-learning-3791",
            )
        assert store.calls == []
    finally:
        os.chdir(prior)

    # No SQLite/JSONL/JSON authority, or any file at all, was created locally.
    created = [p.name for p in workdir.rglob("*") if p.is_file()]
    assert created == [], f"client created local authority artifacts: {created}"

    # The client holds no store/database/session handle to fall back onto.
    assert not hasattr(unreachable, "store")
    assert not hasattr(unreachable, "db")


def test_unreachable_service_is_retried_then_fails_closed(tmp_path: Path) -> None:
    attempts = {"count": 0}

    class Flaky(InMemoryStore):
        def readiness(self) -> dict[str, int]:  # type: ignore[override]
            attempts["count"] += 1
            raise RuntimeError("database down")

    store = Flaky()
    transport = TestClient(create_app(store=store, credentials=_registry(tmp_path)))
    client = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://builderops", token="client-token"),
        http_client=transport,
        max_retries=2,
    )
    with pytest.raises(ControlPlaneUnavailableError):
        client.status()
    # A 5xx is retried (idempotent) up to the bound, never swapped for a store.
    assert attempts["count"] == 3
