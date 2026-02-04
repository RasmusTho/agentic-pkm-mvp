from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_export_runtime_env(tmp_path: Path, env: dict[str, str]) -> Path:
    repo_root = Path(__file__).resolve().parents[2]

    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    runtime_env_path = tmp_path / "runtime.env"

    merged = dict(os.environ)
    merged.update(env)
    merged["VAULT_ROOT"] = str(vault_root)
    merged["RUNTIME_ENV_PATH"] = str(runtime_env_path)

    subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        check=True,
        env=merged,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert runtime_env_path.exists()
    return runtime_env_path


def test_export_runtime_env_does_not_write_scope_when_unset(tmp_path: Path) -> None:
    path = _run_export_runtime_env(tmp_path, env={})
    text = path.read_text(encoding="utf-8")
    assert "WATCHER_SCOPE_GLOB=" not in text


def test_export_runtime_env_does_not_write_scope_when_blank(tmp_path: Path) -> None:
    path = _run_export_runtime_env(tmp_path, env={"WATCHER_SCOPE_GLOB": "   "})
    text = path.read_text(encoding="utf-8")
    assert "WATCHER_SCOPE_GLOB=" not in text


def test_export_runtime_env_writes_scope_when_explicit(tmp_path: Path) -> None:
    path = _run_export_runtime_env(tmp_path, env={"WATCHER_SCOPE_GLOB": "custom/scope/**"})
    text = path.read_text(encoding="utf-8")
    assert "WATCHER_SCOPE_GLOB=custom/scope/**\n" in text


def test_export_runtime_env_overwrites_prior_runtime_env(tmp_path: Path) -> None:
    runtime_env_path = tmp_path / "runtime.env"
    runtime_env_path.write_text("WATCHER_SCOPE_GLOB=stale/**\n", encoding="utf-8")

    path = _run_export_runtime_env(tmp_path, env={})
    text = path.read_text(encoding="utf-8")
    assert "stale/**" not in text
    assert "WATCHER_SCOPE_GLOB=" not in text
