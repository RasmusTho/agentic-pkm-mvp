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
) -> subprocess.CompletedProcess[str]:
    shell = """
set -euo pipefail
source "$1"
deploy_channel_model_access_runtime_env_preflight "$2"
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


def test_missing_optional_model_access_file_clears_inherited_values(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "missing-runtime.env"
    result = _run_preflight(
        runtime_env,
        inherited={key: "stale-parent-value" for key in MODEL_ACCESS_ENV_KEYS},
    )

    assert result.returncode == 0, result.stderr
    assert _reported_bindings(result) == {key: "" for key in MODEL_ACCESS_ENV_KEYS}
    assert "optional_missing" in result.stderr


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
