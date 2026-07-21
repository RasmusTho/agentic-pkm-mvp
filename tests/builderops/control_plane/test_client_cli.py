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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.builderops.control_plane.client import ClientConfig, StaleLeaseError
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

    def create_inquiry(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_inquiry", kwargs))
        return {"object_id": kwargs["inquiry_id"], "state": kwargs["state"]}

    def heartbeat_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("heartbeat_task", kwargs))
        return {"result": {"state": "claimed"}}

    def complete_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete_task", kwargs))
        return {"result": {"state": "completed"}}

    def commit_attempt(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("commit_attempt", kwargs))
        return {"object_id": kwargs["attempt_id"], "state": kwargs["state"]}

    def commit_promotion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("commit_promotion", kwargs))
        return {"object_id": kwargs["promotion_id"], "state": kwargs["status"]}

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


def test_mutating_cli_reloads_manifest_and_rejects_stale_prior_route(
    tmp_path: Path, factory
) -> None:
    """A prior invocation's route cannot authorize a later mutation.

    This drives ``main()`` twice rather than only exercising the registry: after
    the first dispatch, removing the addressed repository manifest makes the
    second invocation fail before it constructs another client.
    """
    manifest_dir = _manifest_dir(tmp_path)
    args = [
        "--delivery-manifest-dir", str(manifest_dir), "--task-class", "implementation",
        "task-claim", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3968",
        "--stack", "builderops-control-plane", "--source-ref", "github:issue:3968",
        "--task-id", "issue-3968", "--idempotency-key", "claim-1",
    ]
    assert main(args, client_factory=factory) == 0
    assert len(factory.created) == 1

    (manifest_dir / "agentic-pkm-mvp.json").unlink()

    assert main(args, client_factory=factory) == 3
    assert len(factory.created) == 1


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


@pytest.mark.parametrize(
    "command_args",
    [
        [
            "record",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:3791",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "github:issue:3791",
            "--record-id",
            "record-1",
            "--record-type",
            "LearningSignal",
            "--state",
            "active",
            "--idempotency-key",
            "record-1",
        ],
        [
            "inquiry",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--scope",
            "issue:3791",
            "--stack",
            "builderops-control-plane",
            "--source-ref",
            "github:issue:3791",
            "--inquiry-id",
            "inquiry-1",
            "--state",
            "active",
            "--idempotency-key",
            "inquiry-1",
        ],
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
        [
            "task-heartbeat", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3791",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3791",
            "--lease", '{"repository":"rasmustho/agentic-pkm-mvp","resource_id":"issue-3791","holder":"client","fencing_token":1,"expires_at":"2026-07-17T00:00:00+00:00"}',
            "--idempotency-key", "heartbeat-1",
        ],
        [
            "task-complete", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3791",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3791",
            "--lease", '{"repository":"rasmustho/agentic-pkm-mvp","resource_id":"issue-3791","holder":"client","fencing_token":1,"expires_at":"2026-07-17T00:00:00+00:00"}',
            "--idempotency-key", "complete-1",
        ],
        [
            "lease-claim", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3791",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3791",
            "--resource-id", "promotion-1", "--idempotency-key", "lease-1",
        ],
        [
            "attempt", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3791",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3791",
            "--task-id", "issue-3791", "--attempt-id", "attempt-1", "--state", "started",
            "--lease", '{"repository":"rasmustho/agentic-pkm-mvp","resource_id":"issue-3791","holder":"client","fencing_token":1,"expires_at":"2026-07-17T00:00:00+00:00"}',
            "--idempotency-key", "attempt-1",
        ],
        [
            "promotion", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3791",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3791",
            "--promotion-id", "promotion-1", "--status", "prepared", "--idempotency-key", "promotion-1",
        ],
    ],
)
def test_mutating_commands_require_delivery_manifest_route(command_args: list[str], factory) -> None:
    """Every real mutating CLI dispatch fails before client construction without a route."""
    assert main(command_args, client_factory=factory) == 2
    assert factory.created == []


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
            "RasmusTho/example-second-repo",  # no manifest loaded for this repo
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
    # Route configuration is supplied so the malformed RepoRef is the gate
    # under test rather than the required manifest-dir check.
    # A missing directory is not reached because RepoRef.parse happens first.
    exit_code = main(
        [
            "--delivery-manifest-dir",
            "/does-not-matter",
            "--task-class",
            "implementation",
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
    assert factory.created == []


def test_promotion_update_accepts_fenced_lease_and_rejects_stale_lease(
    tmp_path: Path, factory
) -> None:
    manifest_dir = _manifest_dir(tmp_path)
    args = [
        "--delivery-manifest-dir", str(manifest_dir), "--task-class", "implementation",
        "promotion", "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3968",
        "--stack", "builderops-control-plane", "--source-ref", "github:issue:3968",
        "--promotion-id", "promotion-1", "--status", "approved", "--idempotency-key", "update-1",
        "--lease", '{"repository":"rasmustho/agentic-pkm-mvp","resource_id":"promotion:promotion-1","holder":"client","fencing_token":2,"expires_at":"2026-07-17T00:00:00+00:00","lease_kind":"generic"}',
    ]
    assert main(args, client_factory=factory) == 0
    [client] = factory.created
    assert client.calls[0][0] == "commit_promotion"
    assert client.calls[0][1]["lease"]["fencing_token"] == 2

    class _StalePromotionClient(_RecordingClient):
        def commit_promotion(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("commit_promotion", kwargs))
            raise StaleLeaseError("StaleFencingToken")

    stale_clients: list[_StalePromotionClient] = []

    def stale_factory(config: ClientConfig) -> _StalePromotionClient:
        client = _StalePromotionClient(config)
        stale_clients.append(client)
        return client

    assert main(args, client_factory=stale_factory) == 3
    assert stale_clients[0].calls[0][1]["lease"]["fencing_token"] == 2
    assert stale_clients[0].closed is True

    class _MissingLeaseClient(_RecordingClient):
        def commit_promotion(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("commit_promotion", kwargs))
            if kwargs["lease"] is None:
                raise StaleLeaseError("LeaseRequired")
            return super().commit_promotion(**kwargs)

    missing_clients: list[_MissingLeaseClient] = []

    def missing_factory(config: ClientConfig) -> _MissingLeaseClient:
        client = _MissingLeaseClient(config)
        missing_clients.append(client)
        return client

    missing_lease_args = [arg for arg in args if arg != "--lease"]
    missing_lease_args.remove(args[-1])
    assert main(missing_lease_args, client_factory=missing_factory) == 3
    assert missing_clients[0].calls[0][1]["lease"] is None
    assert missing_clients[0].closed is True


def test_wrapper_mutation_injects_required_delivery_route(tmp_path: Path) -> None:
    """The documented wrapper path carries the mandatory global route flags."""
    manifest_dir = _manifest_dir(tmp_path)
    root = Path(__file__).resolve().parents[3]
    env = os.environ | {
        "BUILDEROPS_PYTHON": sys.executable,
        "BUILDEROPS_API_URL": "http://127.0.0.1:1",
        "BUILDEROPS_API_TOKEN": "test-token",
        "BUILDEROPS_DELIVERY_MANIFEST_DIR": str(manifest_dir),
        "BUILDEROPS_TASK_CLASS": "implementation",
    }
    result = subprocess.run(
        [
            str(root / "scripts/builderops_api_client.sh"), "record",
            "--repository", "RasmusTho/agentic-pkm-mvp", "--scope", "issue:3968",
            "--stack", "builderops-control-plane", "--source-ref", "github:issue:3968",
            "--record-id", "record-1", "--record-type", "LearningSignal", "--state", "active",
            "--idempotency-key", "record-1",
        ],
        cwd=root, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 3
    assert "ControlPlaneUnavailableError" in result.stderr


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
