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
import httpx

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneAuthError,
    ControlPlaneConfigError,
    ControlPlaneProtocolError,
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
    config = ClientConfig(base_url="https://builderops.invalid", token=token)
    return BuilderOpsControlPlaneClient(config, http_client=transport, max_retries=0)


def _envelope() -> dict[str, object]:
    return {
        "repository": REPO,
        "scope": "issue:3791",
        "stack": "builderops-control-plane",
        "source_refs": ["github:issue:3791"],
    }


def test_control_plane_origin_validation_precedes_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ready": True}, request=request)

    accepted = ("https://builderops.invalid", "http://127.0.0.1:18100/")
    for base_url in accepted:
        env_config = ClientConfig.from_env(
            {"BUILDEROPS_API_URL": base_url, "BUILDEROPS_API_TOKEN": "synthetic-token"}
        )
        assert env_config.base_url == base_url.rstrip("/")
        with httpx.Client(
            transport=httpx.MockTransport(handler), base_url=env_config.base_url
        ) as http:
            with BuilderOpsControlPlaneClient(
                env_config, http_client=http, max_retries=0
            ) as client:
                assert client.status() == {"ready": True}

        direct_config = ClientConfig(base_url=base_url, token="synthetic-token")
        with httpx.Client(
            transport=httpx.MockTransport(handler), base_url=direct_config.base_url
        ) as http:
            with BuilderOpsControlPlaneClient(
                direct_config, http_client=http, max_retries=0
            ) as client:
                assert client.status() == {"ready": True}

    assert len(requests) == 4
    assert {request.url.scheme for request in requests} == {"https", "http"}
    assert all(request.headers["Authorization"] == "Bearer synthetic-token" for request in requests)

    rejected = (
        "http://builderops.invalid",
        "https://",
        "https://builderops.invalid:not-a-port",
        "https://builderops.invalid:",
        "https://user:synthetic-secret@builderops.invalid",
        "https://builderops.invalid?query=yes",
        "https://builderops.invalid?",
        "https://builderops.invalid#fragment",
        "https://builderops.invalid#",
        "https://builderops.invalid/v1",
        "https://bad host.invalid",
        "https://bad..host.invalid",
        "https://-bad.invalid",
        "http://localhost:18100",
        "https://builderops.invalid:0",
        "https://builderops.invalid:65536",
    )
    bypass_http = httpx.Client(transport=httpx.MockTransport(handler))
    for base_url in rejected:
        with pytest.raises(ControlPlaneConfigError) as env_error:
            ClientConfig.from_env(
                {"BUILDEROPS_API_URL": base_url, "BUILDEROPS_API_TOKEN": "synthetic-token"}
            )
        assert "synthetic-token" not in str(env_error.value)
        assert "synthetic-secret" not in str(env_error.value)

        with pytest.raises(ControlPlaneConfigError) as direct_error:
            ClientConfig(base_url=base_url, token="synthetic-token")
        assert "synthetic-token" not in str(direct_error.value)
        assert "synthetic-secret" not in str(direct_error.value)

        # A caller cannot bypass the config check by passing an object that
        # carries the public config fields without running dataclass creation.
        bypassed_config = object.__new__(ClientConfig)
        object.__setattr__(bypassed_config, "base_url", base_url)
        object.__setattr__(bypassed_config, "token", "synthetic-token")
        with pytest.raises(ControlPlaneConfigError) as client_error:
            BuilderOpsControlPlaneClient(
                bypassed_config, http_client=bypass_http
            )
        assert "synthetic-token" not in str(client_error.value)
        assert "synthetic-secret" not in str(client_error.value)

    assert len(requests) == 4
    bypass_http.close()


def test_control_plane_transport_refuses_proxy_and_redirect_routing(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            json={"accepted": True},
            headers={"Location": "https://collector.invalid/receive"},
            request=request,
        )

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "http://proxy.invalid:8080")

    real_httpx_client = httpx.Client
    owned_policy: dict[str, object] = {}

    def owned_client_factory(**kwargs: object) -> httpx.Client:
        owned_policy.update(kwargs)
        return real_httpx_client(
            transport=httpx.MockTransport(redirect), **kwargs  # type: ignore[arg-type]
        )

    monkeypatch.setattr("app.builderops.control_plane.client.httpx.Client", owned_client_factory)
    owned = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://builderops.invalid", token="synthetic-token"),
        max_retries=0,
    )
    assert owned_policy["trust_env"] is False
    assert owned_policy["verify"] is True
    assert owned_policy["follow_redirects"] is False
    with pytest.raises(ControlPlaneProtocolError, match="returned a redirect"):
        owned.issue_delivery_preview(manifest={"operation": "synthetic-operation"})
    assert len(requests) == 1
    assert requests[0].url.host == "builderops.invalid"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
    assert json.loads(requests[0].content) == {
        "manifest": {"operation": "synthetic-operation"}
    }
    owned.close()

    # A caller-supplied HTTPX client is a test seam, but its broader default
    # cannot turn a token-bearing request into an automatically followed hop.
    requests.clear()
    injected_http = real_httpx_client(
        transport=httpx.MockTransport(redirect),
        base_url="https://builderops.invalid",
        follow_redirects=True,
    )
    assert injected_http.follow_redirects is True
    injected = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://builderops.invalid", token="synthetic-token"),
        http_client=injected_http,
        max_retries=0,
    )
    with pytest.raises(ControlPlaneProtocolError, match="returned a redirect"):
        injected.issue_delivery_preview(manifest={"operation": "synthetic-operation"})
    assert len(requests) == 1
    assert requests[0].url.host == "builderops.invalid"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
    assert json.loads(requests[0].content) == {
        "manifest": {"operation": "synthetic-operation"}
    }

    requests.clear()
    for unsafe_path in (
        "https://collector.invalid/receive",
        "//collector.invalid/receive",
    ):
        with pytest.raises(ControlPlaneProtocolError, match="must be origin-relative"):
            injected.issue_delivery_preview(
                manifest={"operation": "synthetic-operation"}, path=unsafe_path
            )
    assert requests == []
    injected_http.close()


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
        expected_version=1,
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
        # 1) Synthetic transport failure -> typed unavailable error, no fallback.
        def fail_transport(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("synthetic connection refusal", request=request)

        unreachable_http = httpx.Client(
            transport=httpx.MockTransport(fail_transport),
            base_url="https://builderops.invalid",
        )
        unreachable = BuilderOpsControlPlaneClient(
            ClientConfig(base_url="https://builderops.invalid", token="client-token"),
            http_client=unreachable_http,
            max_retries=0,
        )
        try:
            with pytest.raises(ControlPlaneUnavailableError):
                unreachable.claim_lease(
                    envelope=_envelope(),
                    resource_id="resource-3791",
                    idempotency_key="claim-resource-3791",
                )
        finally:
            unreachable_http.close()

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
        ClientConfig(base_url="https://builderops.invalid", token="client-token"),
        http_client=transport,
        max_retries=2,
    )
    with pytest.raises(ControlPlaneUnavailableError):
        client.status()
    # A 5xx is retried (idempotent) up to the bound, never swapped for a store.
    assert attempts["count"] == 3


def test_malformed_409_body_raises_instead_of_silently_downgrading(tmp_path: Path) -> None:
    """H2: a truncated/non-JSON 409 body (e.g. proxy interference) must raise
    ControlPlaneProtocolError, matching the 2xx path's malformed-response
    handling, rather than silently returning an empty detail and downgrading
    what might have been a StaleLeaseError into a generic conflict."""

    class _MalformedTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, content=b"<not json at all>")

    http = httpx.Client(transport=_MalformedTransport(), base_url="https://builderops.invalid")
    client = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://builderops.invalid", token="client-token"),
        http_client=http,
        max_retries=0,
    )
    with pytest.raises(ControlPlaneProtocolError):
        client.status()
def test_issue_import_uses_authenticated_transition_and_addressed_readback(tmp_path, monkeypatch, capsys):
    import copy
    import hashlib
    from datetime import datetime, timezone
    from dataclasses import replace
    from app.builderops import cockpit_github_plane
    from app.builderops.control_plane.client_cli import main
    from tests.builderops.control_plane.test_client_cli import _import_source, _manifest_dir
    from tests.ops.test_devui_vm102_runtime_receipts import _first_read_inputs
    from app.ops.devui_vm102_runtime_receipts import build_first_read_observation, canonical_digest

    class SourceStore(InMemoryStore):
        def get_task(self, repository, task_id):
            self.calls.append(("get_task", repository, task_id))
            if not hasattr(self, "row"):
                raise KeyError(task_id)
            return copy.deepcopy(self.row)

        def commit_transition(self, **kw):
            self.calls.append("commit_transition")
            assert kw["outbox"] is kw["lease"] is kw["expected_states"] is kw["expected_version"] is None
            assert kw["to_state"] == "ready"
            if hasattr(self, "row"):
                assert self.request == kw
                return replace(self.result, replayed=True)
            self.request = kw
            self.row = {"repository": kw["envelope"].repository, "task_id": kw["task_id"],
                "state": "ready", "version": 1, "updated_at": source["updated_at"],
                "lease": None, "payload": kw["request"], "authority_envelope": kw["envelope"].as_json()}
            self.result = TransactionResult(kw["envelope"].repository, kw["task_id"], "ready", self._next(), "0/1", None)
            return self.result

    inputs = _first_read_inputs()
    source, store = _import_source(), SourceStore()
    source["body"] = source["body"].replace(".codex/skills/_shared/ISSUE_CONTRACT.md", "docs/AGENT_ISSUE_DISPATCHER.md").replace(".github/workflows/issue-pr-governance.yml", "docs/AGENT_ISSUE_DISPATCHER.md")
    monkeypatch.setattr(cockpit_github_plane, "_run_gh", lambda args: copy.deepcopy(source))
    monkeypatch.setenv("BUILDEROPS_API_URL", "https://builderops.invalid")
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "client-token")
    monkeypatch.delenv("BUILDEROPS_API_TOKEN_FILE", raising=False)
    registry = _registry(tmp_path)
    command = ["--delivery-manifest-dir", str(_manifest_dir(tmp_path)), "--task-class", "implementation",
        "task-import-issue", "--repository", REPO, "--scope", "issue:501", "--stack", "builderops-control-plane", "--issue", "501"]
    observed = []
    service = create_app(store=store, credentials=registry)
    @service.middleware("http")
    async def observe(request, call_next):
        observed.append((request.method, request.url.path, dict(request.query_params), request.headers.get("x-builderops-authority-epoch")))
        return await call_next(request)
    exchanges = []
    def capture_response(response):
        if response.request.method == "POST":
            response.read()
            exchanges.append((response.request.content, response.json()))
    def factory(config):
        transport = TestClient(service)
        transport.event_hooks = {"request": [], "response": [capture_response]}
        return BuilderOpsControlPlaneClient(config, http_client=transport, max_retries=0)

    for replayed in (False, True):
        assert main(command, client_factory=factory) == 0
        assert json.loads(capsys.readouterr().out)["transition_response"]["result"]["replayed"] is replayed
    writes = [item for item in observed if item[0] == "POST"]
    assert writes == [("POST", "/v1/tasks/transition", {}, "1")] * 2
    assert all(query == {"repository": CANON} for method, path, query, _ in observed if "/tasks/" in path and method == "GET")
    # Independently observe the real service exchange instead of reproducing
    # the importer's summary or a guessed HTTPX serialization formula.
    body, response = exchanges[0]
    request = json.loads(body)
    evidence = inputs["evidence"]
    evidence["source"]["repository"] = evidence["selection"]["repository"] = CANON
    stamp = datetime.now(timezone.utc).isoformat()
    for name in ("exchange", "github", "task", "journey", "owner"):
        evidence[name]["observed_at"] = stamp
    evidence["exchange"].update(request=request, request_body=body.decode(), response=response,
                                request_sha256=hashlib.sha256(body).hexdigest())
    evidence["github"]["payload"] = copy.deepcopy(source)
    evidence["task"]["payload"] = copy.deepcopy(store.row)
    evidence["journey"].update(started_at=stamp, subject=f"github:{CANON}#501", task_id=request["task_id"],
        issue_version=source["updated_at"], body_sha256=request["request"]["sync_state"]["body_sha256"])
    evidence["owner"]["journey_sha256"] = canonical_digest(evidence["journey"])
    assert build_first_read_observation(**inputs)["verdict"] == "pass"
    from app.builderops.control_plane.client import ControlPlaneConflictError
    before_calls = list(store.calls)
    with factory(ClientConfig(base_url="https://builderops.invalid", token="client-token")) as client:
        with pytest.raises(ControlPlaneConflictError, match="StateConflict"):
            client.transition_task(**{**request, "outbox": {"effect_type": "github.comment", "payload": {}}})
    assert store.calls == before_calls
    before = store._seq
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "wrong")
    assert main(command, client_factory=factory) == 3
    assert store._seq == before
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "client-token")
    manifest = tmp_path / "credentials.json"
    credentials = json.loads(manifest.read_text())
    credentials["credentials"][0]["scopes"].remove("tasks:write")
    manifest.write_text(json.dumps(credentials))
    assert main(command, client_factory=factory) == 3
    assert store._seq == before
    credentials["credentials"][0]["scopes"].append("tasks:write")
    manifest.write_text(json.dumps(credentials))
    def stale_factory(config):
        client = factory(config)
        assert client.authority_epoch == 1
        store.epoch = 2
        return client
    assert main(command, client_factory=stale_factory) == 3
    assert store._seq == before


def test_generic_lease_release_uses_api(tmp_path: Path) -> None:
    from tests.builderops.control_plane.test_service_auth import _registry as lease_registry, _Store

    class ReleaseStore(_Store):
        def release_lease(self, **kw):
            self.kw = kw
            return TransactionResult(kw['envelope'].repository, kw['lease'].resource_id,
                                     'lease.released', 3, '0/3', None)

    store = ReleaseStore()
    transport = TestClient(create_app(store=store, credentials=lease_registry(tmp_path)))
    client = BuilderOpsControlPlaneClient(ClientConfig(base_url='https://builderops.invalid', token='client-token'),
                                        http_client=transport, max_retries=0)
    claimed = client.claim_lease(envelope=_envelope(), resource_id='maintenance-fixture',
                                idempotency_key='claim-fixture', ttl_seconds=60)
    result = client.release_lease(envelope=_envelope(), lease=claimed['lease'],
                                  idempotency_key='release-fixture')
    assert result['result']['state'] == 'lease.released'
    assert result['result']['recovery_lsn'] == '0/3'
    assert store.kw['lease'].resource_id == claimed['lease']['resource_id']
    assert store.kw['envelope'].actor == 'client:macbook'
    assert store.kw['request'] == {}
    assert store.kw['idempotency_key'] == 'release-fixture'
