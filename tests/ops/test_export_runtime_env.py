import os
import re
import subprocess
from pathlib import Path


def _runtime_env_base(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo_root = Path(__file__).resolve().parents[2]
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    out_path = tmp_path / "runtime.env"
    env = os.environ.copy()
    env["VAULT_ROOT"] = str(vault_root)
    env["RUNTIME_ENV_PATH"] = str(out_path)
    return repo_root, out_path, env


def test_export_runtime_env_emits_uid_gid(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    env.pop("LOCAL_UID", None)
    env.pop("LOCAL_GID", None)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^VAULT_ROOT=.+$", text, re.M)
    assert re.search(r"^LOCAL_UID=\d+$", text, re.M)
    assert re.search(r"^LOCAL_GID=\d+$", text, re.M)


def test_export_runtime_env_emits_watcher_runtime_env_file(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_base(tmp_path)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert f"WATCHER_RUNTIME_ENV_FILE={out_path}\n" in text


def test_export_runtime_env_derives_ollama_host_from_ollama_url(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    env["LLM_PROVIDER"] = "ollama"
    env["OLLAMA_URL"] = "http://ollama:11434"
    env.pop("OLLAMA_BASE_URL", None)
    env.pop("OLLAMA_HOST", None)
    env.pop("OPENAI_BASE_URL", None)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^OLLAMA_HOST=http://ollama:11434$", text, re.M)
    assert re.search(r"^OLLAMA_URL=http://ollama:11434$", text, re.M)
