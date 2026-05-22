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


def _write_default_provider_settings(vault_root: Path) -> None:
    settings_dir = vault_root / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "providers.md").write_text(
        """---
uuid: 00000000-0000-0000-0000-000000000002
title: Providers
origin: user
review_state: evergreen
trust: internal
---
## Provider defaults
```yaml settings
llm:
  default_chat:
    kind: openai_compat
    base_url: "http://127.0.0.1:11434/v1"
    model: "llama3.1:8b"
```
""",
        encoding="utf-8",
    )


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


def _runtime_env_with_db(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    env.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app")
    return repo_root, out_path, env


def test_export_runtime_env_derives_openai_base_from_openai_base_url(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    env["OPENAI_BASE_URL"] = "http://host.docker.internal:11434/v1"
    env.pop("OPENAI_BASE", None)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^OPENAI_BASE=http://host\.docker\.internal:11434/v1/chat/completions$", text, re.M)


def test_export_runtime_env_propagates_explicit_openai_base(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    env["OPENAI_BASE"] = "https://api.example.invalid/v1/chat/completions"
    env.pop("OPENAI_BASE_URL", None)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^OPENAI_BASE=https://api\.example\.invalid/v1/chat/completions$", text, re.M)


def test_export_runtime_env_explicit_openai_base_wins_over_url(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    env["OPENAI_BASE_URL"] = "http://host.docker.internal:11434/v1"
    env["OPENAI_BASE"] = "https://api.example.invalid/v1/chat/completions"

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^OPENAI_BASE=https://api\.example\.invalid/v1/chat/completions$", text, re.M)
    assert "OPENAI_BASE=http://host.docker.internal:11434/v1" not in text


def test_export_runtime_env_propagates_openai_api_key(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    env["OPENAI_API_KEY"] = "sk-local"

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^OPENAI_API_KEY=sk-local$", text, re.M)


def test_export_runtime_env_resolves_llm_provider_from_settings_when_env_missing(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    _write_default_provider_settings(Path(env["VAULT_ROOT"]))
    env["LLM_PROVIDER"] = ""
    env["LLM_MODEL"] = ""
    env["OPENAI_BASE_URL"] = ""
    env["OPENAI_BASE"] = ""

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^LLM_PROVIDER=openai$", text, re.M)
    assert re.search(r"^LLM_MODEL=llama3\.1:8b$", text, re.M)
    assert re.search(r"^OPENAI_BASE_URL=http://127\.0\.0\.1:11434/v1$", text, re.M)
    assert re.search(r"^OPENAI_BASE=http://127\.0\.0\.1:11434/v1/chat/completions$", text, re.M)
