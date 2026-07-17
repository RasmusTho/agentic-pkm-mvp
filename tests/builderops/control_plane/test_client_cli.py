"""BCP-04 S1/H1: the client CLI actually engages delivery-manifest routing on
a real dispatch path, and every RepoRef/routing failure is caught fail-closed.

These tests drive ``app.builderops.control_plane.client_cli.main()`` end to
end (argument parsing, route resolution, TTL-policy application, dispatch),
injecting a fake client so no network call is made. This is the "integration
test proving [routing] through THAT path, not just the standalone registry
test" requested by the issue #3791 review (finding S1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.builderops.control_plane.client import ClientConfig
from app.builderops.control_plane.client_cli import main


class _RecordingClient:
    """Fake client capturing every call main() makes, no network involved."""

    def __init__(self, config: ClientConfig) -> None:
        self.config = config
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def status(self) -> dict[str, Any]:
        self.calls.append(("status", {}))
        return {"authority_epoch": 1, "schema_version": 1}

    def claim_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("claim_task", kwargs))
        return {
            "result": {"state": "claimed"},
            "lease": {
                "repository": kwargs["envelope"]["repository"],
                "resource_id": kwargs["task_id"],
                "holder": "client:macbook",
                "fencing_token": 1,
                "expires_at": "2026-07-17T00:00:00+00:00",
                "lease_kind": "task",
            },
        }

    def claim_lease(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("claim_lease", kwargs))
        return {"result": {"state": "lease.claimed"}, "lease": {}}

    def commit_record(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("commit_record", kwargs))
        return {"object_id": kwargs["record_id"], "state": kwargs["state"]}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def factory():
    created: list[_RecordingClient] = []

    def _factory(config: ClientConfig) -> _RecordingClient:
        client = _RecordingClient(config)
        created.append(client)
        return client

    _factory.created = created  # type: ignore[attr-defined]
    return _factory


@pytest.fixture(autouse=True)
def _api_env(monkeypatch):
    monkeypatch.setenv("BUILDEROPS_API_URL", "https://example.invalid:1")
    monkeypatch.setenv("BUILDEROPS_API_TOKEN", "test-token")
    monkeypatch.delenv("BUILDEROPS_API_TOKEN_FILE", raising=False)


def _manifest_dir(tmp_path: Path, *, ttl_seconds: int = 1800) -> Path:
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / "agentic-pkm-mvp.json").write_text(
        json.dumps(
            {
                "repository": "RasmusTho/agentic-pkm-mvp",
                "routes": [
                    {
                        "stack": "builderops-control-plane",
                        "task_class": "implementation",
                        "policy": {"ttl_seconds": ttl_seconds, "tcd_route": "sonnet-high"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_delivery_manifest_routing_is_engaged_through_real_cli_dispatch(
    tmp_path: Path, factory, capsys
) -> None:
    """Routing is not just a standalone registry test: the real CLI dispatch
    path loads the manifest, resolves the route, and its policy actually
    changes the request the client transport receives (ttl_seconds)."""
    manifest_dir = _manifest_dir(tmp_path, ttl_seconds=1800)
    exit_code = main(
        [
            "--delivery-manifest-dir",
            str(manifest_dir),
            "--task-class",
            "implementation",
            "task-claim",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:3791",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "github:issue:3791",
            "--task-id",
            "issue-3791",
            "--idempotency-key",
            "claim-1",
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    [client] = factory.created
    assert client.calls[0][0] == "claim_task"
    # The route's advisory ttl_seconds reached the actual client call.
    assert client.calls[0][1]["ttl_seconds"] == 1800
    assert client.closed is True
    stderr = capsys.readouterr().err
    assert "resolved delivery route" in stderr
    assert "rasmustho/agentic-pkm-mvp" in stderr


def test_explicit_ttl_flag_wins_over_manifest_policy(tmp_path: Path, factory) -> None:
    manifest_dir = _manifest_dir(tmp_path, ttl_seconds=1800)
    exit_code = main(
        [
            "--delivery-manifest-dir",
            str(manifest_dir),
            "--task-class",
            "implementation",
            "task-claim",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:3791",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "github:issue:3791",
            "--task-id",
            "issue-3791",
            "--idempotency-key",
            "claim-1",
            "--ttl-seconds",
            "60",
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    [client] = factory.created
    assert client.calls[0][1]["ttl_seconds"] == 60


def test_no_manifest_dir_skips_routing_and_uses_hardcoded_default(factory) -> None:
    """Routing is opt-in: omitting --delivery-manifest-dir must not require a
    manifest to exist anywhere, and the historical hardcoded default applies."""
    exit_code = main(
        [
            "task-claim",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:3791",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "github:issue:3791",
            "--task-id",
            "issue-3791",
            "--idempotency-key",
            "claim-1",
        ],
        client_factory=factory,
    )
    assert exit_code == 0
    [client] = factory.created
    assert client.calls[0][1]["ttl_seconds"] == 5400


def test_missing_manifest_for_addressed_repo_fails_closed(tmp_path: Path, factory) -> None:
    manifest_dir = _manifest_dir(tmp_path)
    exit_code = main(
        [
            "--delivery-manifest-dir",
            str(manifest_dir),
            "--task-class",
            "implementation",
            "task-claim",
            "--repository",
            "RasmusTho/bifrost",  # no manifest loaded for this repo
            "--scope",
            "issue:1",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "x",
            "--task-id",
            "t1",
            "--idempotency-key",
            "k1",
        ],
        client_factory=factory,
    )
    assert exit_code == 3
    assert factory.created == []  # no client constructed; nothing was dispatched


def test_ambiguous_task_class_fails_closed(tmp_path: Path, factory) -> None:
    manifest_dir = _manifest_dir(tmp_path)
    exit_code = main(
        [
            "--delivery-manifest-dir",
            str(manifest_dir),
            "--task-class",
            "verification",  # not a route this manifest declares
            "task-claim",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:1",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "x",
            "--task-id",
            "t1",
            "--idempotency-key",
            "k1",
        ],
        client_factory=factory,
    )
    assert exit_code == 3
    assert factory.created == []


def test_manifest_dir_without_task_class_is_a_usage_error(tmp_path: Path, factory) -> None:
    manifest_dir = _manifest_dir(tmp_path)
    exit_code = main(
        [
            "--delivery-manifest-dir",
            str(manifest_dir),
            "task-claim",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:1",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "x",
            "--task-id",
            "t1",
            "--idempotency-key",
            "k1",
        ],
        client_factory=factory,
    )
    assert exit_code == 2
    assert factory.created == []


def test_malformed_repository_fails_closed_not_uncaught(factory) -> None:
    """H1 regression test: RepoRefError from _envelope()'s RepoRef.parse() must
    be caught as a fail-closed CLI error (exit 3), never an uncaught traceback."""
    exit_code = main(
        [
            "record",
            "--repository",
            "not-a-valid-repo",
            "--scope",
            "issue:1",
            "--stack",
            "s",
            "--source-ref",
            "x",
            "--record-id",
            "r1",
            "--record-type",
            "LearningSignal",
            "--state",
            "active",
            "--idempotency-key",
            "k1",
        ],
        client_factory=factory,
    )
    assert exit_code == 3
    [client] = factory.created
    assert client.calls == []
    assert client.closed is True


def test_routing_not_engaged_for_read_only_commands(tmp_path: Path, factory) -> None:
    """--delivery-manifest-dir is a no-op for non-routable commands (status,
    receipt) rather than an error, since they carry no (stack, task-class)."""
    manifest_dir = _manifest_dir(tmp_path)
    exit_code = main(
        ["--delivery-manifest-dir", str(manifest_dir), "status"],
        client_factory=factory,
    )
    assert exit_code == 0
    [client] = factory.created
    assert client.calls == [("status", {})]
