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
assert {'/api/devui/overview', '/healthz', '/version', '/devui/overview', '/api/devui/focus'} <= {r.path for r in app.routes}
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
        assert response.status_code == 503
        assert "candidate" in response.text
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
    state = SimpleNamespace(
        mode="ok", epoch=7, calls=[], http_calls=[], tasks=[task], addressed_tasks=[]
    )

    class Store:
        def readiness(self):
            state.calls.append("status")
            return {"schema_version": 1, "authority_epoch": state.epoch}

        def list_tasks(self, repository, **kwargs):
            state.calls.append(("list_tasks", repository))
            if hasattr(state, "native_store"):
                return state.native_store.list_tasks(repository, **kwargs)
            if state.mode == "unavailable":
                raise OSError("fixture-secret-never-export")
            if state.mode == "timeout":
                time.sleep(0.15)
            return copy.deepcopy(state.tasks)

        def get_task(self, repository, task_id):
            state.calls.append(("get_task", repository, task_id))
            if hasattr(state, "native_store"):
                return state.native_store.get_task(repository, task_id)
            if state.mode == "epoch_changed":
                state.epoch += 1
            row = copy.deepcopy(next(x for x in state.tasks if x["task_id"] == task_id))
            if state.mode == "mismatched":
                row["repository"] = "foreign/repository"
            if state.mode == "changed":
                row["version"] += 1
            if state.mode == "activity_changed":
                row["lease"]["updated_at"] = stamp
            state.addressed_tasks.append(copy.deepcopy(row))
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
    _package_managed_shell(root)
    manifest = json.loads((root / "manifest.json").read_text())
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
if endpoint.endswith('/issues/501'):
    result = {'number': 501, 'title': '<img src=x onerror=alert(1)> Managed work', 'state': 'open', 'html_url': 'https://github.com/example/fixture/issues/501', 'updated_at': '2026-09-13T10:00:00Z'}
    result['body'] = chr(10).join(['## Context', '', 'Fixture owner intent.', '', '## Scope', '', 'Fixture source scope.', '', '## Acceptance Criteria', '', '- [ ] Preserve fixture declarations.', '  - Verify: `tests/fixture.py::test_declaration`', '', '## Source Anchors', '', '- `docs/DEVUI.md :: Intent and evidence continuity`', '', '## Source Docs', '', '- `docs/DEVUI.md`', ''])
    if mode == 'identity_mismatch':
        result['html_url'] = 'https://github.com/foreign/repo/issues/501'
    if mode == 'canonical_case':
        result['html_url'] = 'https://github.com/Example/Fixture/issues/501'
    invalid_locators = {
        'locator_query': 'https://github.com/Example/Fixture/issues/501?source=other',
        'locator_userinfo': 'https://user@github.com/Example/Fixture/issues/501',
        'locator_wrong_path': 'https://github.com/Example/Fixture/pull/501',
        'locator_foreign_host': 'https://foreign.invalid/Example/Fixture/issues/501',
    }
    if mode in invalid_locators:
        result['html_url'] = invalid_locators[mode]
    if mode == 'wrong_number':
        result['number'] = 999
    if mode == 'wrong_kind':
        result['pull_request'] = {'url': 'foreign'}
    if mode == 'missing_title':
        result['title'] = ''
    if mode == 'bad_version':
        result['updated_at'] = 'invalid-time'
    if mode == 'malformed':
        print('{broken')
        raise SystemExit(0)
elif endpoint.endswith('/issues'):
    result = [{'number': 501, 'title': 'Fixture work', 'state': 'open', 'html_url': 'https://github.com/example/fixture/issues/501'}]
    if mode == 'canonical_case':
        result[0]['html_url'] = 'https://github.com/Example/Fixture/issues/501'
elif endpoint.endswith('/pulls'):
    result = [] if mode == 'no_pull' else [{'number': 502, 'title': 'Fixture PR', 'state': 'open', 'html_url': 'https://github.com/example/fixture/pull/502', 'body': 'Governing-Issue: #501', 'head': {'sha': 'd' * 40, 'ref': 'codex/fixture'}}]
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
    "case, moving, admitted",
    [
        ("native_heartbeat", True, True),
        ("lease_activity", True, True),
        ("expired_recent_activity", True, True),
        ("old_activity", False, True),
        ("missing_activity", False, True),
        ("fresh_task", True, True),
        ("newer_native_heartbeat", True, True),
        ("concurrent_heartbeat", True, True),
        ("malformed_activity", False, False),
        ("malformed_heartbeat", False, False),
        ("generic_lease", False, False),
    ],
)
def test_managed_source_preserves_native_activity(managed_sources, case, moving, admitted) -> None:
    import copy
    from datetime import datetime, timedelta, timezone

    from app.builderops.control_plane.store import PostgresBuilderOpsStore
    from app.builderops.devui_sources import _task

    source = managed_sources
    source.gh_mode.write_text("no_pull")
    now = datetime.now(timezone.utc)
    fresh, old = now.isoformat(), (now - timedelta(days=15)).isoformat()
    row = copy.deepcopy(source.tasks[0])
    row.update(state="claimed", updated_at=fresh if case == "fresh_task" else old)
    row["payload"].update(status="claimed", updated_at=old, last_heartbeat_at=None)
    if case in {"native_heartbeat", "newer_native_heartbeat"}:
        row["payload"]["last_heartbeat_at"] = fresh
    if case == "malformed_heartbeat":
        row["payload"]["last_heartbeat_at"] = "invalid"
    if case != "native_heartbeat":
        row.update(
            lease_holder="worker",
            fencing_token=1,
            expires_at=(now + timedelta(hours=1)).isoformat(),
            lease_kind="generic" if case == "generic_lease" else "task",
            lease_updated_at=fresh
            if case in {"lease_activity", "expired_recent_activity"}
            else old,
        )
        if case == "expired_recent_activity":
            row["expires_at"] = (now - timedelta(minutes=1)).isoformat()
        if case == "missing_activity":
            row.pop("lease_updated_at")
        if case == "malformed_activity":
            row["lease_updated_at"] = "invalid"
    source.tasks[:] = [dict(PostgresBuilderOpsStore._task_snapshot(row))]
    if case == "concurrent_heartbeat":
        source.mode = "activity_changed"
    with source.client() as client:
        response = client.get("/api/devui/overview")
    assert response.status_code == 200
    payload = response.json()
    assert _managed_source(payload, "dispatcher-store")["state"] == (
        "fresh" if admitted else "unavailable"
    )
    assert bool(payload["now"]) is moving
    assert _managed_source(payload, "github-live")["state"] == "fresh"
    assert _managed_source(payload, "docs-frontmatter")["state"] == "fresh"
    if admitted:
        import hashlib

        task = _task(source.tasks[0], repository="example/fixture")
        assert task["updated_at"] == row["updated_at"]
        assert task.get("last_heartbeat_at") == row["payload"]["last_heartbeat_at"]
        assert task.get("lease_updated_at") == row.get("lease_updated_at")
        digest = hashlib.sha256(
            json.dumps(source.addressed_tasks, sort_keys=True).encode()
        ).hexdigest()
        assert any(
            ref.endswith("#sha256=" + digest)
            for ref in _managed_source(payload, "dispatcher-store")["transport"]["source_refs"]
        )


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
    assert len(source.http_calls) == 4 + task_count
    assert source.http_calls[-1] == ("GET", "/v1/receipts/owner-facts/current")
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
        documents = _managed_source(client.get("/api/devui/overview").json(), "docs-frontmatter")
        assert documents["state"] == "fresh"
        refs = documents["transport"]["source_refs"]
        assert refs and not any("/assets/" in ref for ref in refs)
        assert set(refs) == {
            f"https://github.com/example/fixture/blob/{'a' * 40}/{name}#sha256={digest}"
            for name, digest in source.manifest["files"].items()
            if name.startswith("docs/")
        }
        assert all("assets/" + name in source.manifest["files"] for name in MANAGED_ROUTES.values())
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


MANAGED_ROUTES = {
    "/devui/overview": "overview.html",
    "/devui/focus": "focus.html",
    "/devui/assets/devui.css": "devui.css",
    "/devui/assets/overview.js": "overview.js",
    "/devui/assets/focus.js": "focus.js",
}
MANAGED_SUBJECT = "github:example/fixture#501"


def _package_managed_shell(root: Path) -> None:
    import hashlib
    import shutil

    source = ROOT / "companion-ui/companion-app/companion_ui/workspace/devui_candidate"
    shutil.copytree(source, root / "assets", dirs_exist_ok=True)
    shutil.copyfile(ROOT / "app/builderops/devui_managed.css", root / "assets/devui.css")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"].update(
        {
            "assets/" + name: hashlib.sha256((root / "assets" / name).read_bytes()).hexdigest()
            for name in MANAGED_ROUTES.values()
        }
    )
    manifest_path.write_text(json.dumps(manifest))


def test_managed_journey_serves_exact_packaged_asset_allowlist(managed_sources) -> None:
    source = managed_sources
    _package_managed_shell(source.root)
    with source.client() as client:
        for route, filename in MANAGED_ROUTES.items():
            query = {"subject": MANAGED_SUBJECT} if route == "/devui/focus" else {}
            response = client.get(route, params=query)
            assert response.status_code == 200
            assert response.content == (source.root / "assets" / filename).read_bytes()
            assert response.headers["cache-control"] == "no-store"
            assert "default-src 'none'" in response.headers["content-security-policy"]
        assert {r.path for r in client.app.routes} == set(MANAGED_ROUTES) | {
            "/api/devui/overview",
            "/api/devui/focus",
            "/version",
            "/healthz",
        }
        for route in ("/", "/devui", "/devui/assets/extra.js", "/api/devui/overview/synthesis"):
            assert client.get(route).status_code == 404
    assert source.http_calls == []
    assert not source.gh_calls.exists()


def test_managed_journey_boots_without_product_or_companion_gateway(tmp_path: Path) -> None:
    script = """
import importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in {'app.api', 'app.settings', 'app.auth', 'app.store', 'app.db', 'app.dispatcher'} or fullname.startswith('companion_ui'):
            raise AssertionError('forbidden boot: ' + fullname)
sys.meta_path.insert(0, Reject())
from app.builderops.devui_runtime import production_app
app = production_app()
assert '/devui/overview' in {r.path for r in app.routes}
assert '/api/devui/focus' in {r.path for r in app.routes}
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


def test_managed_focus_uses_admitted_repository_source_and_honest_states(managed_sources) -> None:
    source = managed_sources
    _package_managed_shell(source.root)
    with source.client() as client:
        response = client.get("/api/devui/focus", params={"subject": MANAGED_SUBJECT})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["subject"]["stable_id"] == MANAGED_SUBJECT
        assert (
            payload["subject"]["authority_ref"]["locator"]
            == "https://github.com/example/fixture/issues/501"
        )
        assert payload["receipts"] == payload["execution_observations"] == []
        assert payload["next_legal_step"]["legality"] == "unavailable"
        assert payload["conversation_port"]["availability"] == "unsupported"
        assert source.http_calls == [("GET", "/v1/receipts/owner-facts/current")]
        assert any(row["kind"] == "owner_facts_unavailable" for row in payload["limitations"])
        calls = source.gh_calls.read_text().splitlines()
        assert len(calls) == 1
        assert json.loads(calls[0])[:2] == ["api", "repos/example/fixture/issues/501"]
        for subject in ("github:foreign/repository#501", "capability:fixture"):
            refused = client.get("/api/devui/focus", params={"subject": subject})
            assert refused.status_code == 404
        assert source.gh_calls.read_text().splitlines() == calls
        for mode in ("unavailable", "identity_mismatch", "wrong_number", "wrong_kind", "missing_title", "bad_version", "malformed", "locator_query", "locator_userinfo", "locator_wrong_path", "locator_foreign_host"):
            source.gh_mode.write_text(mode)
            refused = client.get("/api/devui/focus", params={"subject": MANAGED_SUBJECT})
            assert refused.status_code == 404, (mode, refused.text)
            assert "fixture-secret-never-export" not in refused.text
        source.environment["DEVUI_GITHUB_ENABLED"] = "false"
        before = source.gh_calls.read_text()
        with source.client() as disabled:
            assert disabled.get("/api/devui/focus", params={"subject": MANAGED_SUBJECT}).status_code == 404
        assert source.gh_calls.read_text() == before

    assert source.http_calls == [("GET", "/v1/receipts/owner-facts/current")]
    assert any(row["kind"] == "owner_facts_unavailable" for row in payload["limitations"])


def test_managed_focus_projects_issue_declarations_through_existing_fields(managed_sources) -> None:
    source = managed_sources
    _package_managed_shell(source.root)
    with source.client() as client:
        response = client.get("/api/devui/focus", params={"subject": MANAGED_SUBJECT})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Fixture owner intent." in payload["owner_intent"]["summary"]
    assert "Fixture source scope." in payload["owner_intent"]["summary"]
    assert any(
        "Verify: `tests/fixture.py::test_declaration`" in item["claim"]
        for item in payload["evidence"]
    )
    source_ref = payload["subject"]["authority_ref"]
    assert source_ref["version"] == "2026-09-13T10:00:00Z"
    assert len(source_ref["content_hash"]) == 64
    assert all(
        item["coverage"] == "partial"
        for item in payload["evidence"][1:] + payload["governing_sources"][1:]
    )
    assert any(item["kind"] == "criterion_results_unassessed" for item in payload["limitations"])
    assert source.http_calls == [("GET", "/v1/receipts/owner-facts/current")]
    assert any(row["kind"] == "owner_facts_unavailable" for row in payload["limitations"])
    calls = [json.loads(line) for line in source.gh_calls.read_text().splitlines()]
    assert calls == [["api", "repos/example/fixture/issues/501"]]


@pytest.mark.parametrize("subject", ["github:example/fixture#501", "github:Example/Fixture#501"])
def test_managed_focus_preserves_canonical_repository_case(managed_sources, subject) -> None:
    source = managed_sources
    _package_managed_shell(source.root)
    source.environment["DEVUI_REPOSITORY"] = "Example/Fixture"
    source.gh_mode.write_text("canonical_case")
    with source.client() as client:
        response = client.get("/api/devui/focus", params={"subject": subject})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["subject"]["stable_id"] == subject
    assert payload["subject"]["authority_ref"]["locator"] == "https://github.com/Example/Fixture/issues/501"
    assert source.http_calls == [("GET", "/v1/receipts/owner-facts/current")]
    assert any(row["kind"] == "owner_facts_unavailable" for row in payload["limitations"])


def test_managed_journey_admission_and_typed_query_failure_matrix(managed_sources) -> None:
    source = managed_sources
    _package_managed_shell(source.root)
    paths = list(MANAGED_ROUTES) + [
        "/api/devui/overview",
        "/api/devui/focus",
        "/version",
        "/healthz",
    ]
    with source.client() as client:
        for path in paths:
            params = {"subject": MANAGED_SUBJECT} if path.endswith("/focus") else {}
            for headers in (
                {"Host": "evil.example"},
                {"Host": "127.0.0.1:8114"},
                {"Forwarded": "for=127.0.0.1"},
                {"X-Forwarded-Host": "localhost:8113"},
                {"X-Real-IP": "127.0.0.1"},
                {"Via": "proxy"},
            ):
                assert client.get(path, params=params, headers=headers).status_code == 403
            for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                assert client.request(method, path, params=params).status_code == 405
            if not path.endswith("/focus"):
                assert client.get(path + "?subject=x").status_code == 400
        for path in ("/devui/focus", "/api/devui/focus"):
            for query in (
                "",
                "?subject=",
                "?subject=%20",
                "?subject=a&subject=b",
                "?subject=x&extra=y",
                "?extra=x",
                "?subject=%ZZ",
                "?subject=%FF",
                "?subject",
                "?subject=github:x/y%230",
                "?subject=../../../secret",
                "?subject=github:x/y%231%00",
            ):
                assert client.get(path + query).status_code == 400, (path, query)
        for path in (
            "/devui/focus/",
            "/devui/assets/secrets.json",
            "/api/devui/composition",
            "/openapi.json",
        ):
            assert client.get(path).status_code == 404
    with TestClient(
        create_app(load_configuration(source.environment)),
        client=("192.0.2.5", 1000),
        base_url="http://127.0.0.1:8113",
    ) as remote:
        for path in paths:
            assert remote.get(path).status_code == 403
    assert source.http_calls == []
    assert not source.gh_calls.exists()


def test_managed_shell_api_and_asset_inventory_bind_one_candidate(managed_sources) -> None:
    import copy

    source = managed_sources
    _package_managed_shell(source.root)
    with source.client() as client:
        responses = [
            client.get("/devui/overview"),
            client.get("/devui/assets/devui.css"),
            client.get("/api/devui/overview"),
            client.get("/api/devui/focus", params={"subject": MANAGED_SUBJECT}),
        ]
        version = client.get("/version").json()
        for response in responses:
            assert response.status_code == 200
            assert response.headers["x-pkm-runtime-git-sha"] == version["source_sha"]
            assert response.headers["x-devui-image-digest"] == version["image_digest"]
            assert response.headers["x-devui-config-fingerprint"] == version["config_fingerprint"]
            assert response.headers["x-devui-asset-inventory"] == version["asset_inventory_sha256"]
        original = json.loads((source.root / "manifest.json").read_text())
        calls = list(source.http_calls)
        gh_calls = source.gh_calls.read_text()
        for mutation in ("missing", "sha", "inventory", "bytes", "extra"):
            manifest = copy.deepcopy(original)
            if mutation == "sha":
                manifest["source_sha"] = "d" * 40
            if mutation == "inventory":
                del manifest["files"]["assets/devui.css"]
            (source.root / "manifest.json").write_text(json.dumps(manifest))
            if mutation == "missing":
                (source.root / "manifest.json").unlink()
            if mutation == "bytes":
                (source.root / "assets/devui.css").write_text("body { color: red; }")
            if mutation == "extra":
                (source.root / "assets/extra.js").write_text("alert(1)")
            for route in (
                "/devui/overview",
                "/devui/assets/devui.css",
                "/api/devui/overview",
                "/api/devui/focus",
            ):
                params = {"subject": MANAGED_SUBJECT} if route.endswith("/focus") else {}
                refused = client.get(route, params=params)
                assert refused.status_code == 503, (mutation, route)
                assert "candidate" in refused.text.lower()
            assert source.http_calls == calls
            assert source.gh_calls.read_text() == gh_calls
            (source.root / "assets/extra.js").unlink(missing_ok=True)
            _package_managed_shell(source.root) if mutation != "missing" else None
            (source.root / "manifest.json").write_text(json.dumps(original))
def _install_first_read_observation(source, monkeypatch, *, retain=True):
    import copy
    from app.builderops import cockpit_github_plane
    from app.builderops.control_plane.client_cli import issue_source_task
    from app.ops.builderops_vm_rebuild_activation import build_activation_receipt
    from app.ops.devui_vm102_runtime_receipts import build_first_read_observation, canonical_digest
    from tests.ops.test_devui_vm102_runtime_receipts import _first_read_inputs

    inputs = _first_read_inputs()
    evidence, prerequisites = inputs["evidence"], inputs["prerequisites"]
    candidate = evidence["selection"]["candidate_identity"]
    candidate.update(source_sha=source.environment["DEVUI_SOURCE_SHA"],
                     control_plane_image_digest=source.environment["DEVUI_IMAGE_DIGEST"],
                     devui_image_digest=source.environment["DEVUI_IMAGE_DIGEST"],
                     devui_config_fingerprint=source.environment["DEVUI_CONFIG_FINGERPRINT"])
    activation = prerequisites["activation"]
    activation["candidate_identity"] = {key: candidate[key] for key in activation["candidate_identity"]}
    activation["migration"]["authority_epoch"] = source.epoch
    prerequisites["activation"] = build_activation_receipt({key: value for key, value in activation.items() if key != "evidence_fingerprint"})
    evidence["operator"]["activation_sha256"] = canonical_digest(prerequisites["activation"])
    evidence["selection"]["merged_main_sha"] = candidate["source_sha"]
    evidence["installed"]["candidate_identity"] = copy.deepcopy(candidate)
    evidence["installed"]["documents"] = {key: value for key, value in json.loads((source.root / "manifest.json").read_text())["files"].items() if not key.startswith("assets/")}
    issue = evidence["github"]["payload"]
    # Existing managed fixture documents are candidate-baked and exercised by
    # the real source reader; adapt only the external Issue bytes to those refs.
    doc = next(key for key in evidence["installed"]["documents"] if key.startswith("docs/") and key.endswith(".md"))
    issue["body"] = issue["body"].replace("docs/AGENT_ISSUE_DISPATCHER.md", doc)
    evidence["journey"]["inspected_documents"] = [doc]
    task = issue_source_task(issue, repository="example/fixture", number=501,
                            observed_at=evidence["exchange"]["observed_at"], authority_epoch=source.epoch)
    evidence["source"]["authority_epoch"] = evidence["exchange"]["authority_epoch"] = source.epoch
    request = evidence["exchange"]["request"]
    request["request"] = task
    import httpx
    body = httpx.Request("POST", "http://builderops/v1/tasks/transition", json=request).content
    evidence["exchange"]["request_body"] = body.decode()
    evidence["exchange"]["request_sha256"] = __import__("hashlib").sha256(body).hexdigest()
    row = evidence["task"]["payload"]
    row["payload"] = copy.deepcopy(task)
    source.tasks = [copy.deepcopy(row)]
    for name in ("browser", "journey"):
        evidence[name]["candidate_sha"] = candidate["source_sha"]
    evidence["journey"]["body_sha256"] = task["sync_state"]["body_sha256"]
    evidence["owner"]["journey_sha256"] = canonical_digest(evidence["journey"])
    original_gh = cockpit_github_plane._run_gh
    monkeypatch.setattr(cockpit_github_plane, "_run_gh", lambda args: copy.deepcopy(issue)
        if args == ["api", "repos/example/fixture/issues/501"] else original_gh(args))
    folder = Path(source.environment["DEVUI_VM102_RECEIPT_DIR"]) / "first-read"
    if not retain:
        return inputs, folder
    receipt = build_first_read_observation(**inputs)
    assert receipt["verdict"] == "pass", receipt
    folder.mkdir()
    (folder / "inputs.json").write_text(json.dumps(inputs))
    (folder / "observation.json").write_text(json.dumps(receipt))
    return inputs, folder


def test_first_read_observation_preserves_admission_and_authority_boundaries(managed_sources, monkeypatch):
    source = managed_sources
    _package_managed_shell(source.root)
    with source.client() as client:
        before = client.get("/api/devui/overview")
        assert before.status_code == 200
        assert before.headers["x-devui-first-read-observation"] == "refused"
        inputs, folder = _install_first_read_observation(source, monkeypatch)
        response = client.get("/api/devui/overview")
        assert response.status_code == 200
        assert response.headers["x-devui-first-read-observation"] == "available"
        providers = {item["role"]: item for item in response.json()["trust_frame"]["provider_states"]}
        assert providers["first_read_observation"]["status"] == "available"
        assert providers["vm102_evidence"]["status"] == "refused"
        assert client.get("/healthz").json()["complete_dev_system_health"] is False
        assert client.post("/api/devui/overview").status_code == 405
        assert client.get("/api/devui/overview", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
        (folder / "inputs.json").write_text("{partial")
        response = client.get("/api/devui/overview")
        assert response.status_code == 200
        assert response.headers["x-devui-first-read-observation"] == "refused"
        assert "github:example/fixture#501" in response.text
        (folder / "inputs.json").write_text(json.dumps(inputs))
        source.credential["scopes"] = ["status:read"]
        source.auth.write_text(json.dumps({"credentials": [source.credential]}))
        assert client.get("/api/devui/overview").headers["x-devui-first-read-observation"] == "refused"
        assert all(method == "GET" for method, _ in source.http_calls)
