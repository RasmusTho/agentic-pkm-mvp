from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app.builderops.devui_runtime import RuntimeConfigurationError, create_app, load_configuration


ROOT = Path(__file__).resolve().parents[2]


def _environment(path: Path) -> dict[str, str]:
    return {
        "VCS_REF": "a" * 40,
        "DEVUI_SOURCE_SHA": "a" * 40,
        "DEVUI_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "DEVUI_CONFIG_FINGERPRINT": "sha256:" + "c" * 64,
        "DEVUI_VM102_RECEIPT_DIR": str(path),
    }


def test_standalone_startup_boundary(tmp_path: Path) -> None:
    script = """
import importlib.abc, sys
class RejectProduct(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in {'app.api', 'app.settings', 'app.auth', 'app.store', 'app.db', 'app.dispatcher'}:
            raise AssertionError('Product/store import: ' + fullname)
sys.meta_path.insert(0, RejectProduct())
from app.builderops.devui_runtime import production_app
app = production_app()
assert {r.path for r in app.routes} == {'/api/devui/overview', '/healthz', '/version'}
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], **_environment(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
    for key in _environment(tmp_path):
        env = _environment(tmp_path)
        del env[key]
        with pytest.raises(RuntimeConfigurationError):
            load_configuration(env)
    with pytest.raises(RuntimeConfigurationError):
        load_configuration(_environment(tmp_path / "absent"))
    with pytest.raises(RuntimeConfigurationError):
        load_configuration({**_environment(tmp_path), "DEVUI_SOURCE_SHA": "d" * 40})


def test_managed_overview_admission(tmp_path: Path) -> None:
    app = create_app(load_configuration(_environment(tmp_path)))
    with TestClient(app, client=("127.0.0.1", 1000), base_url="http://127.0.0.1:8113") as client:
        response = client.get("/api/devui/overview")
        assert response.status_code == 200
        payload = response.json()
        assert "refused" in json.dumps(payload)
        assert "ready_to_try" in json.dumps(payload)
        for headers in (
            {"X-Forwarded-For": "127.0.0.1"},
            {"Forwarded": "for=127.0.0.1"},
            {"Host": "evil.example"},
        ):
            assert client.get("/api/devui/overview", headers=headers).status_code == 403
        assert client.post("/api/devui/overview").status_code == 405
        assert client.get("/api/devui/overview/extra").status_code == 404
        assert client.get("/api/devui/overview?upstream=http://evil.example").status_code == 400
        assert client.get("/api/devui/composition").status_code == 404
        assert client.get("/healthz").json()["complete_dev_system_health"] is False
    with TestClient(app, client=("192.0.2.5", 1000), base_url="http://127.0.0.1:8113") as client:
        assert client.get("/api/devui/overview").status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_managed_configuration_keeps_listener_private() -> None:
    import yaml

    config = yaml.safe_load((ROOT / "docker-compose.devui.yml").read_text())
    assert config["name"] == "builderops-devui"
    service = config["services"]["devui"]
    assert service["network_mode"] == "host"
    assert service["read_only"] is True
    assert service["command"] == ["python", "-m", "app.builderops.devui_runtime"]
    assert service["restart"] == "unless-stopped"
    assert service["volumes"][0]["read_only"] is True
    assert service["volumes"][0]["bind"]["create_host_path"] is False
    assert not {"ports", "env_file", "secrets"} & service.keys()


# These transports reach the production route, client, service authentication,
# gh subprocess reader and candidate-doc reader. Only source storage is a fixture.
@pytest.fixture
def managed_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    import copy
    import hashlib
    import socket
    import threading
    import time
    from datetime import datetime, timezone
    from types import SimpleNamespace

    import uvicorn
    from app.builderops import devui_runtime
    from app.builderops.control_plane.auth import CredentialRegistry
    from app.builderops.control_plane.service import create_app as create_service
    from app.builderops.control_plane.store import PostgresBuilderOpsStore
    from app.dispatcher.models import TaskRecord

    repo = "example/fixture"
    stamp = datetime.now(timezone.utc).isoformat()
    source_ref = f"/v1/receipts/records/evidence-1?repository={repo}"
    envelope = {
        "repository": repo,
        "scope": "delivery",
        "stack": "builderops",
        "actor": "fixture",
        "source_refs": [source_ref],
        "schema_version": 1,
    }
    task_payload = TaskRecord(
        task_id="task-1",
        repo=repo,
        issue_number=501,
        title="Fixture work",
        status="ready",
        priority="high",
        source_anchor_refs=[],
        created_at=stamp,
        updated_at=stamp,
        sync_state={"labels": []},
    ).to_dict()
    task_payload["private"] = "fixture-secret-never-export"
    task = dict(
        PostgresBuilderOpsStore._task_snapshot(
            {
                "repository": repo,
                "task_id": "task-1",
                "state": "ready",
                "version": 1,
                "updated_at": stamp,
                "authority_envelope": envelope,
                "payload": task_payload,
            }
        )
    )
    state = SimpleNamespace(mode="ok", epoch=7, calls=[], http_calls=[], tasks=[task])

    class Store:
        def readiness(self):
            state.calls.append("status")
            return {"schema_version": 1, "authority_epoch": state.epoch}

        def list_tasks(self, repository, **kwargs):
            state.calls.append(("list_tasks", repository))
            if state.mode == "unavailable":
                raise OSError("fixture-secret-never-export")
            if state.mode == "timeout":
                time.sleep(0.15)
            return copy.deepcopy(state.tasks)

        def get_task(self, repository, task_id):
            state.calls.append(("get_task", repository, task_id))
            if state.mode == "epoch_changed":
                state.epoch += 1
            row = copy.deepcopy(next(x for x in state.tasks if x["task_id"] == task_id))
            if state.mode == "mismatched":
                row["repository"] = "foreign/repository"
            if state.mode == "changed":
                row["version"] += 1
            return row

        def get_record(self, repository, record_id):
            state.calls.append(("get_receipt", repository, record_id))
            if state.mode == "receipt_missing":
                raise KeyError(record_id)
            if state.mode == "receipt_timeout":
                time.sleep(0.15)
            return {
                "repository": repository,
                "record_id": record_id,
                "record_type": "BuilderOpsReceipt",
                "state": "recorded",
                "version": 1,
                "updated_at": stamp,
                "authority_envelope": envelope,
                "payload": {"private": "fixture-secret-never-export"},
            }

    secret = tmp_path / "source-token"
    secret.write_text("fixture-secret-never-export")
    credential = {
        "id": "reader",
        "principal": "fixture-reader",
        "secret_ref": "host-secret:fixture/read",
        "secret_file": str(secret),
        "scopes": ["receipts:read", "status:read"],
        "repositories": [repo],
        "rotation_generation": 1,
    }
    auth = tmp_path / "source-auth.json"
    auth.write_text(json.dumps({"credentials": [credential]}))
    # Ordinary cases exercise the actual default policy. A cap-specific case
    # can explicitly model an independently configured larger source quota.
    settings = getattr(request, "param", {})
    monkeypatch.delenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", raising=False)
    if "rate_limit" in settings:
        monkeypatch.setenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", str(settings["rate_limit"]))
    service = create_service(store=Store(), credentials=CredentialRegistry(auth))

    @service.middleware("http")
    async def observe_request(request, call_next):
        state.http_calls.append((request.method, request.url.path))
        return await call_next(request)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(service, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started

    root = tmp_path / "candidate"
    (root / "docs" / "FIXTURE").mkdir(parents=True)
    (root / "docs" / "capabilities.yaml").write_text(
        "capabilities:\n  - id: fixture\n    name: Fixture capability\n    boundary_ref: FIXTURE\n"
    )
    (root / "docs" / "matrix.md").write_text(
        "| # | Principle | Control boundaries | Implementation issues |\n| --- | --- | --- | --- |\n| 1 | Fixture | FIXTURE | #501 |\n"
    )
    (root / "docs" / "FIXTURE" / "PARENT_FEATURE_ISSUE.md").write_text(
        "State: Filed as GitHub Issue #500.\n"
    )
    (root / "docs" / "FIXTURE" / "TASK.md").write_text(
        "---\ntask_id: FIXTURE-01\ngithub_issue: 501\nparent_capability: fixture\n---\n# Fixture requirement\n"
    )
    manifest = {
        "repository": repo,
        "source_sha": "a" * 40,
        "capabilities": "docs/capabilities.yaml",
        "matrix": "docs/matrix.md",
        "files": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*")
            if p.is_file()
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(devui_runtime, "CANDIDATE_ROOT", root, raising=False)

    gh_config = tmp_path / "gh-config"
    gh_config.mkdir()
    gh_calls = tmp_path / "gh-calls.jsonl"
    gh_mode = tmp_path / "gh-mode"
    gh_mode.write_text("ok")
    binary = tmp_path / "gh"
    binary.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['FIXTURE_GH_CALLS']).open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
mode = Path(os.environ['FIXTURE_GH_MODE']).read_text()
if mode == 'unavailable' or (mode == 'partial' and args[1].endswith('/status')):
    print('fixture-secret-never-export', file=sys.stderr)
    raise SystemExit(1)
endpoint = args[1]
if endpoint.endswith('/issues'):
    result = [{'number': 501, 'title': 'Fixture work', 'state': 'open', 'html_url': 'https://github.com/example/fixture/issues/501'}]
elif endpoint.endswith('/pulls'):
    result = [{'number': 502, 'title': 'Fixture PR', 'state': 'open', 'html_url': 'https://github.com/example/fixture/pull/502', 'body': 'Governing-Issue: #501', 'head': {'sha': 'd' * 40, 'ref': 'codex/fixture'}}]
elif endpoint.endswith('/status'):
    result = {'state': 'success'}
else:
    result = [{'name': 'main'}]
print(json.dumps(result))
"""
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GH_CONFIG_DIR", str(gh_config))
    monkeypatch.setenv("FIXTURE_GH_CALLS", str(gh_calls))
    monkeypatch.setenv("FIXTURE_GH_MODE", str(gh_mode))
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    env = {
        **_environment(receipts),
        "DEVUI_REPOSITORY": repo,
        "DEVUI_BUILDEROPS_AUTHORITY_EPOCH": "7",
        "BUILDEROPS_API_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
        "BUILDEROPS_API_TOKEN_FILE": str(secret),
        "DEVUI_GITHUB_ENABLED": "true",
        "GH_CONFIG_DIR": str(gh_config),
    }
    state.environment, state.auth, state.credential = env, auth, credential
    state.root, state.manifest, state.gh_mode, state.gh_calls = root, manifest, gh_mode, gh_calls
    state.client = lambda: TestClient(
        create_app(load_configuration(env)),
        client=("127.0.0.1", 1000),
        base_url="http://127.0.0.1:8113",
    )
    try:
        yield state
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def _managed_source(payload: dict, name: str) -> dict:
    work = next(x for x in payload["trust_frame"]["provider_states"] if x["role"] == "work")
    return next(x for x in work["snapshot"]["sources"] if x["name"] == name)


def _native_unprojected_tasks(source):
    """Use actual producer documents and the store's JSON response projection."""
    import copy
    from types import SimpleNamespace
    from unittest.mock import patch

    import httpx
    from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig
    from app.builderops.control_plane.client_cli import _dispatch
    from app.builderops.control_plane.store import PostgresBuilderOpsStore
    from app.dispatcher.verification_api import _run_document, project_verification_run
    from tests.dispatcher import verification_helpers

    posted = []

    def capture(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
        return httpx.Response(200, json={"authority_epoch": 7})

    with httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(capture)) as http:
        with BuilderOpsControlPlaneClient(
            ClientConfig(base_url="http://fixture", token="fixture-token"),
            http_client=http,
        ) as client:
            _dispatch(
                SimpleNamespace(
                    command="task-claim",
                    repository="example/fixture",
                    scope="delivery",
                    stack="builderops",
                    source_refs=["github-issue:501"],
                    task_id="task-cli",
                    idempotency_key="fixture-claim",
                    ttl_seconds=5400,
                ),
                client,
            )
    assert len(posted) == 1 and posted[0]["request"] == {}
    with patch.object(verification_helpers, "REPO", "example/fixture"):
        verification_request = verification_helpers.request()
    run = project_verification_run(verification_request)
    rows = []
    for task_id, payload in (
        ("task-cli", posted[0]["request"]),
        (run.run_id, _run_document(run)),
    ):
        row = copy.deepcopy(source.tasks[0])
        row.update(task_id=task_id, payload=payload)
        row["authority_envelope"]["source_refs"] = ["github-issue:501"]
        rows.append(dict(PostgresBuilderOpsStore._task_snapshot(row)))
    return rows


def test_managed_overview_reads_admitted_sources(managed_sources) -> None:
    managed_sources.tasks.extend(_native_unprojected_tasks(managed_sources))
    with managed_sources.client() as client:
        response = client.get("/api/devui/overview")
    assert response.status_code == 200
    payload = response.json()
    assert [x["display_label"] for x in payload["now"]] == ["Fixture work"]
    assert ("list_tasks", "example/fixture") in managed_sources.calls
    assert ("get_task", "example/fixture", "task-1") in managed_sources.calls
    assert ("get_receipt", "example/fixture", "evidence-1") in managed_sources.calls
    for name in ("dispatcher-store", "github-live", "docs-frontmatter"):
        source = _managed_source(payload, name)
        assert source["state"] == "fresh"
        assert source["transport"]["repository"] == "example/fixture"
        assert source["transport"]["source_refs"]
    assert _managed_source(payload, "docs-frontmatter")["transport"]["candidate_sha"] == "a" * 40
    assert _managed_source(payload, "dispatcher-store")["transport"]["authority_epoch"] == 7
    assert _managed_source(payload, "dispatcher-store")["transport"]["outcome"] == "partial"
    assert (
        len(_managed_source(payload, "dispatcher-store")["transport"]["unprojected_task_refs"]) == 2
    )
    assert any(x["role"] == "vm102_evidence" for x in payload["trust_frame"]["provider_states"])
    calls = [json.loads(line) for line in managed_sources.gh_calls.read_text().splitlines()]
    assert calls and all(
        call[:1] == ["api"] and call[1].startswith("repos/example/fixture/") for call in calls
    )


def test_managed_overview_keeps_unprojectable_tasks_explicit(managed_sources) -> None:
    managed_sources.tasks[:] = _native_unprojected_tasks(managed_sources)
    with managed_sources.client() as client:
        payload = client.get("/api/devui/overview").json()
    work = _managed_source(payload, "dispatcher-store")
    assert work["state"] == "unavailable" and work["transport"]["outcome"] == "partial"
    assert payload["now"] == []
    assert _managed_source(payload, "github-live")["state"] == "fresh"
    assert _managed_source(payload, "docs-frontmatter")["state"] == "fresh"


@pytest.mark.parametrize(
    "case",
    [
        "unavailable",
        "mismatched",
        "changed",
        "epoch_changed",
        "receipt_missing",
        "github_unavailable",
        "github_partial",
        "docs_missing",
        "docs_stale",
        "docs_mismatched",
        "bad_item",
        "task_cap",
        "duplicate_task",
        "timeout",
        "credential_revoked",
        "docs_extra",
        "docs_symlink",
        "receipt_timeout",
        "unprojected_bad_lease",
    ],
)
def test_managed_source_failure_matrix(managed_sources, case: str, monkeypatch) -> None:
    import copy

    source = managed_sources
    if case.startswith("github_"):
        source.gh_mode.write_text(case.removeprefix("github_"))
    elif case == "docs_missing":
        (source.root / "docs" / "FIXTURE" / "TASK.md").unlink()
    elif case == "docs_stale":
        for path in source.root.rglob("*"):
            os.utime(path, (1, 1))
    elif case == "docs_mismatched":
        (source.root / "docs" / "FIXTURE" / "TASK.md").write_text("foreign candidate")
    elif case == "bad_item":
        source.tasks.append({"repository": "example/fixture", "task_id": "broken", "payload": None})
    elif case == "task_cap":
        source.tasks[:] = [copy.deepcopy(source.tasks[0]) for _ in range(201)]
    elif case == "duplicate_task":
        source.tasks.append(copy.deepcopy(source.tasks[0]))
    elif case in {"timeout", "receipt_timeout"}:
        from app.builderops.control_plane import client as source_client

        monkeypatch.setattr(source_client, "_DEFAULT_TIMEOUT_SECONDS", 0.05)
        source.mode = case
    elif case == "credential_revoked":
        source.auth.write_text(json.dumps({"credentials": []}))
    elif case == "docs_extra":
        (source.root / "docs" / "FIXTURE" / "manifest.json").write_text("unaddressed input")
    elif case == "docs_symlink":
        task_doc = source.root / "docs" / "FIXTURE" / "TASK.md"
        task_doc.unlink()
        task_doc.symlink_to(source.auth)
    elif case == "unprojected_bad_lease":
        row = _native_unprojected_tasks(source)[0]
        row["lease"] = {"repository": "foreign/repo"}
        source.tasks.append(row)
    else:
        source.mode = case
    with source.client() as client:
        payload = client.get("/api/devui/overview").json()
    assert _managed_source(payload, "github-live")["state"] == (
        "unavailable" if case == "github_unavailable" else "fresh"
    )
    if case in {
        "unavailable",
        "mismatched",
        "changed",
        "epoch_changed",
        "bad_item",
        "task_cap",
        "duplicate_task",
        "timeout",
        "credential_revoked",
        "unprojected_bad_lease",
    }:
        assert _managed_source(payload, "dispatcher-store")["transport"]["outcome"] in {
            "unavailable",
            "refused",
            "partial",
            "mismatched",
        }
        assert _managed_source(payload, "docs-frontmatter")["state"] == "fresh"
        if case != "bad_item":
            assert payload["now"] == []
    else:
        assert [x["display_label"] for x in payload["now"]] == ["Fixture work"]
    if case.startswith("docs_"):
        docs = _managed_source(payload, "docs-frontmatter")
        assert docs["state"] == ("stale" if case == "docs_stale" else "unavailable")
        assert docs["transport"]["outcome"] != "available"
    if case == "github_partial":
        assert _managed_source(payload, "github-live")["transport"]["outcome"] == "partial"
    if case in {"receipt_missing", "receipt_timeout"}:
        assert _managed_source(payload, "verification-runs")["transport"]["outcome"] == "partial"


@pytest.mark.parametrize("task_count, available", [(117, True), (118, False)])
def test_managed_source_default_quota_withdrawal(
    managed_sources,
    task_count,
    available,
    monkeypatch,
) -> None:
    """Known P2 fanout boundary remains visible under the source's real default."""
    import copy
    from types import SimpleNamespace
    from app.builderops.control_plane import auth

    # Hold one real fixed window so a minute rollover cannot hide the quota.
    monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=lambda: 1.0))

    source = managed_sources
    first = source.tasks[0]
    source.tasks = []
    for index in range(task_count):
        row = copy.deepcopy(first)
        row["task_id"] = row["payload"]["task_id"] = f"task-{index}"
        row["payload"]["issue_number"] = index + 1
        row["authority_envelope"]["source_refs"] = []
        source.tasks.append(row)
    with source.client() as client:
        payload = client.get("/api/devui/overview").json()
    assert len(source.http_calls) == 3 + task_count
    assert bool(payload["now"]) is available
    work = _managed_source(payload, "dispatcher-store")
    assert work["state"] == ("fresh" if available else "unavailable")
    assert _managed_source(payload, "github-live")["state"] == "fresh"
    assert _managed_source(payload, "docs-frontmatter")["state"] == "fresh"


@pytest.mark.parametrize("managed_sources", [{"rate_limit": 10000}], indirect=True)
def test_managed_source_receipt_cap_with_qualified_larger_quota(managed_sources) -> None:
    source = managed_sources
    source.tasks[0]["authority_envelope"]["source_refs"] *= 201
    with source.client() as client:
        payload = client.get("/api/devui/overview").json()
    reads = [x for x in source.calls if isinstance(x, tuple) and x[0] == "get_receipt"]
    assert len(reads) == 200
    assert [x["display_label"] for x in payload["now"]] == ["Fixture work"]
    assert _managed_source(payload, "verification-runs")["transport"]["outcome"] == "partial"


def test_managed_source_scope_and_candidate_binding(managed_sources) -> None:
    source = managed_sources
    for changes in (
        {"DEVUI_REPOSITORY": "../foreign"},
        {"DEVUI_REPOSITORY": "foreign/repo"},
        {"DEVUI_BUILDEROPS_AUTHORITY_EPOCH": "-1"},
        {"BUILDEROPS_API_URL": "https://user:secret@host/"},
        {"BUILDEROPS_API_URL": "http://product.internal:8000"},
        {"COCKPIT_REGISTRY_DB": "/tmp/legacy.sqlite"},
        {"DEVUI_DOCS_ROOT": "/tmp/arbitrary"},
    ):
        with pytest.raises(RuntimeConfigurationError):
            load_configuration({**source.environment, **changes})
    source.environment["DEVUI_BUILDEROPS_AUTHORITY_EPOCH"] = "6"
    with source.client() as client:
        payload = client.get("/api/devui/overview").json()
    assert _managed_source(payload, "dispatcher-store")["transport"]["outcome"] == "mismatched"
    assert source.calls == ["status"]
    source.environment["DEVUI_BUILDEROPS_AUTHORITY_EPOCH"] = "7"
    source.tasks[0]["authority_envelope"]["source_refs"] = [
        "/v1/receipts/records/evidence-1?repository=foreign/repo"
    ]
    with source.client() as client:
        payload = client.get("/api/devui/overview").json()
    assert _managed_source(payload, "dispatcher-store")["state"] == "unavailable"
    assert not any(isinstance(call, tuple) and call[0] == "get_receipt" for call in source.calls)
    for scopes, repos in (
        (["status:read"], ["example/fixture"]),
        (["status:read", "receipts:read"], ["foreign/repo"]),
    ):
        source.auth.write_text(
            json.dumps(
                {"credentials": [{**source.credential, "scopes": scopes, "repositories": repos}]}
            )
        )
        with source.client() as client:
            payload = client.get("/api/devui/overview").json()
        assert payload["now"] == []
        assert _managed_source(payload, "dispatcher-store")["transport"]["outcome"] == "refused"
    absent = _environment(Path(source.environment["DEVUI_VM102_RECEIPT_DIR"]))
    with TestClient(
        create_app(load_configuration(absent)),
        client=("127.0.0.1", 1),
        base_url="http://127.0.0.1:8113",
    ) as client:
        payload = client.get("/api/devui/overview").json()
    for name in ("dispatcher-store", "github-live", "docs-frontmatter"):
        assert _managed_source(payload, name)["state"] == "unavailable"


def test_managed_source_admission_precedes_reads(
    managed_sources, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.builderops import cockpit_docs_plane, devui_runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("provider called before admission")

    monkeypatch.setattr(cockpit_docs_plane, "read_docs_plane", forbidden)
    monkeypatch.setattr(devui_runtime, "read_vm102_receipt_provider", forbidden)
    source = managed_sources
    for peer, headers, method, path, status in (
        ("192.0.2.5", {}, "GET", "/api/devui/overview", 403),
        ("127.0.0.1", {"Forwarded": "for=127.0.0.1"}, "GET", "/api/devui/overview", 403),
        ("127.0.0.1", {"X-Forwarded-Host": "localhost:8113"}, "GET", "/api/devui/overview", 403),
        ("127.0.0.1", {"Host": "other.invalid"}, "GET", "/api/devui/overview", 403),
        ("127.0.0.1", {}, "POST", "/api/devui/overview", 405),
        ("127.0.0.1", {}, "GET", "/api/devui/overview?repository=foreign/repo", 400),
    ):
        with TestClient(
            create_app(load_configuration(source.environment)),
            client=(peer, 1),
            base_url="http://127.0.0.1:8113",
        ) as client:
            assert client.request(method, path, headers=headers).status_code == status
    assert source.calls == []
    assert not source.gh_calls.exists()


def test_managed_source_credentials_remain_server_side(
    managed_sources, caplog: pytest.LogCaptureFixture
) -> None:
    source = managed_sources
    for mode in ("ok", "unavailable"):
        source.mode = mode
        source.gh_mode.write_text(mode)
        with source.client() as client:
            for path in ("/api/devui/overview", "/version", "/healthz"):
                assert "fixture-secret-never-export" not in client.get(path).text
    assert "fixture-secret-never-export" not in caplog.text
    assert "fixture-secret-never-export" not in repr(load_configuration(source.environment))


def test_managed_source_packaging_and_isolation_contract(managed_sources) -> None:
    import yaml

    dockerfile = (ROOT / "Dockerfile.builderops").read_text()
    requirements = (ROOT / "requirements-builderops.txt").read_text()
    assert "gh" in dockerfile and "COPY docs" in dockerfile
    assert "app.builderops.devui_sources" in dockerfile
    assert "SOURCE_REPOSITORY" in dockerfile
    assert "FROM scratch AS devui-source-inputs" in dockerfile
    assert "COPY --from=devui-source-inputs /devui-candidate" in dockerfile
    capability_path = "app/builderops/ckm/seed/capabilities.yaml"
    assert f"--capabilities {capability_path}" in dockerfile
    assert f"/devui-candidate/{capability_path}" in dockerfile
    ignore = (ROOT / "Dockerfile.builderops.dockerignore").read_text().splitlines()
    assert "**" in ignore and "!docs/**" in ignore and "!app/**" in ignore
    assert (ROOT / capability_path).is_file()
    assert (ROOT / "docs/architecture/traceability-matrix.md").is_file()
    assert "httpx==" in requirements and "PyYAML==" in requirements
    sources = yaml.safe_load((ROOT / "docker-compose.devui-sources.yml").read_text())["services"][
        "devui"
    ]
    assert "DEVUI_REPOSITORY" in sources["environment"]
    assert "DEVUI_BUILDEROPS_AUTHORITY_EPOCH" in sources["environment"]
    assert "BUILDEROPS_API_TOKEN" not in sources["environment"]
    assert all(
        x["read_only"] and x["bind"]["create_host_path"] is False for x in sources["volumes"]
    )
    assert not {"ports", "env_file"} & sources.keys()
    source = managed_sources
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.devui_sources",
            "--root",
            str(source.root),
            "--repository",
            "example/fixture",
            "--source-sha",
            "a" * 40,
            "--capabilities",
            "docs/capabilities.yaml",
            "--matrix",
            "docs/matrix.md",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((source.root / "manifest.json").read_text()) == source.manifest
    with source.client() as client:
        assert (
            _managed_source(client.get("/api/devui/overview").json(), "docs-frontmatter")["state"]
            == "fresh"
        )
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-image-build.yml").read_text())
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("with", {}).get("file") == "Dockerfile.builderops"
    ]
    assert (
        len(steps) == 1
        and "SOURCE_REPOSITORY=${{ github.repository }}" in steps[0]["with"]["build-args"]
    )


def _install_vm102_fixture(source) -> None:
    import runpy

    producer = runpy.run_path(str(ROOT / "tests/ops/test_devui_vm102_runtime_receipts.py"))
    bundle = producer["_bundle"]()
    root = Path(source.environment["DEVUI_VM102_RECEIPT_DIR"])
    for receipt in producer["_chain"](bundle):
        (root / f"{receipt['receipt_type']}.json").write_text(json.dumps(receipt))
    (root / "devui-runtime-prerequisites.json").write_text(json.dumps(bundle["prerequisites"]))
    candidate = bundle["evidence"]["candidate_identity"]
    source.environment.update(
        VCS_REF=candidate["source_sha"],
        DEVUI_SOURCE_SHA=candidate["source_sha"],
        DEVUI_IMAGE_DIGEST=candidate["devui_image_digest"],
        DEVUI_CONFIG_FINGERPRINT=candidate["devui_config_fingerprint"],
    )
    source.manifest["source_sha"] = candidate["source_sha"]
    (source.root / "manifest.json").write_text(json.dumps(source.manifest))


def test_managed_overview_rereads_sources_and_preserves_vm102(managed_sources) -> None:
    source = managed_sources
    _install_vm102_fixture(source)
    with source.client() as client:
        initial = client.get("/api/devui/overview").json()
        assert [x["display_label"] for x in initial["now"]] == ["Fixture work"]
        assert [x["display_label"] for x in initial["ready_to_try"]] == ["DevUI on VM 102"]
        source.gh_mode.write_text("unavailable")
        degraded = client.get("/api/devui/overview").json()
        assert [x["display_label"] for x in degraded["now"]] == ["Fixture work"]
        assert [x["display_label"] for x in degraded["ready_to_try"]] == ["DevUI on VM 102"]
        assert _managed_source(degraded, "github-live")["state"] == "unavailable"
        assert source.calls.count(("list_tasks", "example/fixture")) == 2
        (
            Path(source.environment["DEVUI_VM102_RECEIPT_DIR"]) / "devui-runtime-prerequisites.json"
        ).unlink()
        withdrawn = client.get("/api/devui/overview").json()
        assert withdrawn["ready_to_try"] == []
        assert [x["display_label"] for x in withdrawn["now"]] == ["Fixture work"]
