from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_COMPOSE_LIB = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
MODEL_ACCESS_ENV_KEYS = (
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
)


def _run_preflight(
    runtime_env: Path,
    *,
    inherited: dict[str, str] | None = None,
    channel_action: str | None = None,
) -> subprocess.CompletedProcess[str]:
    shell = """
set -euo pipefail
source "$1"
if [ -n "$3" ]; then
  action="$3"
  deploy_channel_model_access_preflight "$2.product-runtime" "$2"
else
  deploy_channel_model_access_runtime_env_preflight "$2"
fi
for key in \
  MODEL_ACCESS_CODEX_VLAN_ENDPOINT \
  MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE \
  MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT \
  MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY; do
  printf '%s=%s\\n' "$key" "${!key-}"
done
"""
    environment = os.environ.copy()
    for key in MODEL_ACCESS_ENV_KEYS:
        environment.pop(key, None)
    if inherited:
        environment.update(inherited)
    return subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "model-access-preflight",
            str(DEPLOY_COMPOSE_LIB),
            str(runtime_env),
            channel_action or "",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _reported_bindings(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return {
        key: line.removeprefix(f"{key}=")
        for line in result.stdout.splitlines()
        for key in MODEL_ACCESS_ENV_KEYS
        if line.startswith(f"{key}=")
    }


def _run_alias_check(runtime_env: Path, model_access_env: Path) -> subprocess.CompletedProcess[str]:
    shell = 'source "$1"; _deploy_channel_runtime_env_aliases_model_access_file "$2" "$3"'
    return subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "model-access-alias-check",
            str(DEPLOY_COMPOSE_LIB),
            str(runtime_env),
            str(model_access_env),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_snapshot(
    runtime_env: Path,
    model_access_env: Path,
    snapshot: Path,
) -> subprocess.CompletedProcess[str]:
    shell = 'source "$1"; _deploy_channel_snapshot_runtime_env_file "$2" "$3" "$4"'
    return subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "model-access-snapshot",
            str(DEPLOY_COMPOSE_LIB),
            str(runtime_env),
            str(model_access_env),
            str(snapshot),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_model_access_preflight_exports_only_valid_path_references(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "runtime.env"
    expected = {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://192.0.2.25:8443",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": "/run/model-access/codex-client/ca.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": "/run/model-access/codex-client/client.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": "/run/model-access/codex-client/client.key",
    }
    runtime_env.write_text(
        "".join(f"{key}={value}\n" for key, value in expected.items()),
        encoding="utf-8",
    )

    result = _run_preflight(
        runtime_env,
        inherited={key: "stale-parent-value" for key in MODEL_ACCESS_ENV_KEYS},
    )

    assert result.returncode == 0, result.stderr
    assert _reported_bindings(result) == expected
    assert "allowlist_validated" in result.stderr


@pytest.mark.parametrize("channel_action", ["deploy", "rollback"])
def test_missing_optional_model_access_file_clears_inherited_values(
    tmp_path: Path,
    channel_action: str,
) -> None:
    runtime_env = tmp_path / "missing-runtime.env"
    result = _run_preflight(
        runtime_env,
        inherited={key: "stale-parent-value" for key in MODEL_ACCESS_ENV_KEYS},
        channel_action=channel_action,
    )

    assert result.returncode == 0, result.stderr
    assert _reported_bindings(result) == {key: "" for key in MODEL_ACCESS_ENV_KEYS}
    assert "optional_missing" in result.stderr


@pytest.mark.parametrize("recovery", ["automatic", "explicit"])
def test_rollback_retains_valid_existing_model_access_bindings(
    tmp_path: Path, recovery: str,
) -> None:
    from app.model_access.executor_network_policy import resolve_executor_paths
    from tests.deploy.test_deploy_channel import _deploy_events, _run_deploy, _run_rollback
    from tests.deploy.test_deploy_channel_script import (
        _commit_prefloor_successor, _deploy_harness, _seed_previous_pin,
    )

    root, env, previous_sha = _deploy_harness(tmp_path)
    target_sha = _commit_prefloor_successor(root, "configured recovery")
    _seed_previous_pin(root, previous_sha)
    model_access_env = tmp_path / "model-access-runtime.env"
    expected = {"MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://192.0.2.25:8443"}
    for key, filename in zip(MODEL_ACCESS_ENV_KEYS[1:], ("ca.pem", "client.pem", "client.key")):
        reference = tmp_path / filename
        reference.write_text("synthetic fixture\n")
        expected[key] = str(reference)
    model_access_env.write_text("".join(f"{key}={value}\n" for key, value in expected.items()))
    for relative in ("scripts/deploy_channel.sh", "scripts/lib/deploy_channel_compose.sh"):
        path = root / relative
        path.write_text(path.read_text().replace(
            "/etc/yggdrasil/model-access/runtime.env", str(model_access_env),
        ))
    docker = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
    injection = '''if [[ "$*" == *"up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"* ]]; then
  printf 'model-access-bindings %s|%s|%s|%s\\n' \\
    "${MODEL_ACCESS_CODEX_VLAN_ENDPOINT:-}" "${MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT:-}" "${MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY:-}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
fi
'''
    docker.write_text(docker.read_text().replace("set -eu\n", "set -eu\n" + injection, 1))
    for key in MODEL_ACCESS_ENV_KEYS:
        env[key] = "stale-parent-value"
    if recovery == "automatic":
        env.update(FAKE_SHA=target_sha, FAKE_POSTDEPLOY_SMOKE="fail", FAKE_POSTDEPLOY_SMOKE_RC="73")
        result = _run_deploy(root, env, target_sha)
        assert result.returncode == 73, result.stdout + result.stderr
        expected_recreates = 2
    else:
        _seed_previous_pin(root, target_sha)
        env["FAKE_SHA"] = previous_sha
        result = _run_rollback(root, env, previous_sha)
        assert result.returncode == 0, result.stdout + result.stderr
        expected_recreates = 1
    bindings = [line.removeprefix("model-access-bindings ").split("|")
                for line in _deploy_events(env) if line.startswith("model-access-bindings ")]
    assert len(bindings) == expected_recreates
    for values in bindings:
        actual = dict(zip(MODEL_ACCESS_ENV_KEYS, values, strict=True))
        assert actual == expected
        # The same real resolver used by required Product callers must accept
        # the references handed to service recreation; no network call occurs.
        resolved = resolve_executor_paths(
            "profile.codex_remote_host", environment=actual,
            policy_path=REPO_ROOT / "config/model_access/executor_network_paths.yaml",
        )
        assert resolved[0].endpoint == expected[MODEL_ACCESS_ENV_KEYS[0]]
        assert resolved[0].client_certificate == (
            expected[MODEL_ACCESS_ENV_KEYS[2]], expected[MODEL_ACCESS_ENV_KEYS[3]],
        )
    assert "stale-parent-value" not in result.stdout + result.stderr


@pytest.mark.parametrize("contents", [
    "UNSUPPORTED_KEY=untrusted-canary\n",
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://user:untrusted-canary@example.test\n",
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://example.test\n"
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://other.test\n",
])
def test_rollback_clears_invalid_optional_bindings_without_promoting_them(
    tmp_path: Path, contents: str,
) -> None:
    runtime_env = tmp_path / "model-access-runtime.env"
    runtime_env.write_text(contents)
    result = _run_preflight(runtime_env, channel_action="rollback",
                            inherited={key: "stale-parent-value" for key in MODEL_ACCESS_ENV_KEYS})
    assert result.returncode == 0, result.stderr
    assert _reported_bindings(result) == {key: "" for key in MODEL_ACCESS_ENV_KEYS}
    assert "untrusted-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "contents,secret_marker",
    [
        ("API_KEY=do-not-log-this-secret\n", "do-not-log-this-secret"),
        (
            "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://user:do-not-log-this-secret@192.0.2.25\n",
            "do-not-log-this-secret",
        ),
        (
            "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY=-----BEGIN PRIVATE KEY-----\n",
            "BEGIN PRIVATE KEY",
        ),
    ],
)
def test_invalid_model_access_file_fails_closed_without_echoing_values(
    tmp_path: Path,
    contents: str,
    secret_marker: str,
) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(contents, encoding="utf-8")

    result = _run_preflight(runtime_env)

    assert result.returncode == 78
    assert "invalid_contents" in result.stderr
    assert secret_marker not in result.stdout + result.stderr


def test_model_access_preflight_rejects_duplicate_keys(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://192.0.2.25:8443\n"
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://192.0.2.26:8443\n",
        encoding="utf-8",
    )

    result = _run_preflight(runtime_env)

    assert result.returncode == 78
    assert "invalid_contents" in result.stderr


def test_runtime_env_alias_to_model_access_file_is_detected(tmp_path: Path) -> None:
    model_access_env = tmp_path / "model-access-runtime.env"
    model_access_env.write_text("MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://example.test\n")
    runtime_env_alias = tmp_path / "runtime.env"
    runtime_env_alias.symlink_to(model_access_env)
    distinct_runtime_env = tmp_path / "other-runtime.env"
    distinct_runtime_env.write_text("LLM_PROVIDER=mock\n")

    alias_result = _run_alias_check(runtime_env_alias, model_access_env)
    distinct_result = _run_alias_check(distinct_runtime_env, model_access_env)

    assert alias_result.returncode == 0
    assert distinct_result.returncode == 1


def test_private_runtime_snapshot_pins_contents_and_rejects_model_access_alias(
    tmp_path: Path,
) -> None:
    model_access_env = tmp_path / "model-access-runtime.env"
    model_access_env.write_text(
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT=https://example.test\n",
        encoding="utf-8",
    )
    runtime_env = tmp_path / "runtime.env"
    runtime_contents = "LLM_PROVIDER=codex_cli\nDATABASE_URL=postgresql://example\n"
    runtime_env.write_text(runtime_contents, encoding="utf-8")
    snapshot = tmp_path / "runtime.snapshot"
    snapshot.write_text("", encoding="utf-8")
    snapshot.chmod(0o600)

    snapshot_result = _run_snapshot(runtime_env, model_access_env, snapshot)

    assert snapshot_result.returncode == 0, snapshot_result.stderr
    assert snapshot.read_text(encoding="utf-8") == runtime_contents
    assert snapshot.stat().st_mode & 0o777 == 0o600

    runtime_alias = tmp_path / "runtime-alias.env"
    runtime_alias.symlink_to(model_access_env)
    rejected_snapshot = tmp_path / "rejected.snapshot"
    rejected_snapshot.write_text("unchanged\n", encoding="utf-8")
    rejected_snapshot.chmod(0o600)

    alias_result = _run_snapshot(runtime_alias, model_access_env, rejected_snapshot)

    assert alias_result.returncode == 78
    assert "runtime_env_snapshot" in alias_result.stderr
    assert rejected_snapshot.read_text(encoding="utf-8") == "unchanged\n"


def test_compose_helper_does_not_trust_ambient_preflight_marker() -> None:
    library = DEPLOY_COMPOSE_LIB.read_text(encoding="utf-8")
    deploy_script = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")

    assert "DEPLOY_CHANNEL_MODEL_ACCESS_PREFLIGHT_COMPLETE" not in library
    assert "DEPLOY_CHANNEL_MODEL_ACCESS_PREFLIGHT_COMPLETE" not in deploy_script
