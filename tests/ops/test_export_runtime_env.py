import ast
import os
import re
import subprocess
from pathlib import Path

import pytest


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
    settings_dir = vault_root / "settings"
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


def test_export_runtime_env_writes_container_vault_root(tmp_path: Path) -> None:
    """The container-facing ``VAULT_ROOT`` must be the in-container mount path.

    Compose loads this file via service ``env_file:`` so its values become the
    *container* environment read by ``resolve_vault_root()``. Writing the host
    path here makes in-container resolution raise ``VaultRootMisconfiguredError``
    and the API 503s (issue #2141).
    """
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    host_vault = env["VAULT_ROOT"]

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^VAULT_ROOT=/app/vault$", text, re.M)
    # The host path must not be the container's VAULT_ROOT.
    assert f"VAULT_ROOT={host_vault}" not in text


def test_export_runtime_env_writes_host_root_for_mount_interpolation(tmp_path: Path) -> None:
    """The host path is preserved under ``VAULT_HOST_ROOT`` for compose to
    interpolate the bind-mount source ``${VAULT_HOST_ROOT:-...}:/app/vault``.

    Wrappers (cold_boot.sh, verify_runtime_stack.sh) pass this file as
    ``docker compose --env-file`` without exporting a shell ``VAULT_ROOT``, so
    the host path must live in the file under a distinct name (issue #2141).
    """
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    host_vault = env["VAULT_ROOT"]

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(rf"^VAULT_HOST_ROOT={re.escape(host_vault)}$", text, re.M)


def test_export_runtime_env_container_vault_root_matches_compose_mount(tmp_path: Path) -> None:
    """The container VAULT_ROOT must equal the legacy compatibility bind-mount target.

    Guards against re-introducing a container VAULT_ROOT that diverges from the
    fixed `/app/vault` mount target (which would regress to the #2141 503). After
    #2386 the `/app/vault` mount lives in the explicit ``docker-compose.legacy-vault.yml``
    overlay, not the base compose, but the container-facing VAULT_ROOT it carries
    is still `/app/vault`.
    """
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    legacy_compose = (repo_root / "docker-compose.legacy-vault.yml").read_text(encoding="utf-8")
    assert ":/app/vault\"" in legacy_compose  # the fixed mount target (explicit overlay)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^VAULT_ROOT=/app/vault$", text, re.M)


def test_legacy_app_vault_mount_requires_explicit_vault(tmp_path: Path) -> None:
    """Any retained ``/app/vault`` compatibility mount requires an explicit vault.

    The base compose must carry no ``/app/vault`` fallback, and the legacy
    overlay's mount source must use the required-variable form
    (``${VAULT_HOST_ROOT:?...}``) so an unset ``VAULT_ROOT`` / ``VAULT_HOST_ROOT``
    cannot select it via a ``./vault`` fallback.
    """
    repo_root = Path(__file__).resolve().parents[2]
    import yaml

    base_data = yaml.safe_load((repo_root / "docker-compose.yaml").read_text(encoding="utf-8"))
    base_sources: list[str] = []
    base_mounts: list[str] = []
    for service in base_data.get("services", {}).values():
        for vol in service.get("volumes", []) or []:
            base_mounts.append(str(vol))
            base_sources.append(str(vol).split(":", 1)[0])
    assert not any(v.endswith(":/app/vault") for v in base_mounts), (
        "base compose must not carry a /app/vault fallback mount"
    )
    assert not any("./vault" in s for s in base_sources), (
        "base compose must not carry a ./vault fallback source"
    )

    legacy = (repo_root / "docker-compose.legacy-vault.yml").read_text(encoding="utf-8")
    legacy_lines = [
        line.strip()
        for line in legacy.splitlines()
        if line.strip().endswith(':/app/vault"')
    ]
    assert legacy_lines, "expected the /app/vault mount in the legacy overlay"
    for line in legacy_lines:
        # Required-variable form: an unset VAULT_HOST_ROOT errors out rather than
        # synthesizing ./vault — the mount cannot be selected by a no-vault startup.
        assert "${VAULT_HOST_ROOT:?" in line, line
        assert "./vault" not in line, line


def test_export_runtime_env_no_vault_omits_both_vault_vars(tmp_path: Path) -> None:
    """No-vault idle posture (#2005) writes neither VAULT_ROOT nor VAULT_HOST_ROOT."""
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    env["NO_VAULT_MODE"] = "1"
    env.pop("LLM_PROVIDER", None)

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert not re.search(r"^VAULT_ROOT=", text, re.M)
    assert not re.search(r"^VAULT_HOST_ROOT=", text, re.M)
    assert re.search(r"^LLM_PROVIDER=mock$", text, re.M)


def test_export_runtime_env_no_vault_preserves_llm_provider(tmp_path: Path) -> None:
    """The idle runtime env keeps the preflight-validated provider selector."""
    repo_root, out_path, env = _runtime_env_base(tmp_path)
    env["NO_VAULT_MODE"] = "1"
    env["LLM_PROVIDER"] = "synthetic-no-vault-provider"

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line.startswith("LLM_PROVIDER=")] == [
        "LLM_PROVIDER=synthetic-no-vault-provider"
    ]


def test_compose_volume_source_uses_host_root_var() -> None:
    """Every legacy vault bind mount must source from VAULT_HOST_ROOT.

    Guards the issue #2141 contract: the mount source is the host path
    (VAULT_HOST_ROOT), independent of the container-facing VAULT_ROOT=/app/vault
    that the same runtime env file carries. After #2386 the mount lives in the
    explicit ``docker-compose.legacy-vault.yml`` overlay and uses the
    required-variable form so it cannot fall back to ``./vault``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.legacy-vault.yml").read_text(encoding="utf-8")
    mount_lines = [
        line.strip()
        for line in compose.splitlines()
        if line.strip().endswith(':/app/vault"')
    ]
    assert mount_lines, "expected at least one /app/vault bind mount in the legacy overlay"
    for line in mount_lines:
        assert "${VAULT_HOST_ROOT:?" in line
        assert "./vault" not in line


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


def _install_settings_location_import_failure(
    tmp_path: Path, env: dict[str, str], *, fail_on_import: int
) -> None:
    """Inject a deterministic failure into a child Python process only.

    ``export_runtime_env.sh`` runs Python from the repository root, so shadowing
    the checked-out ``app`` package is not reliable. ``sitecustomize`` instead
    adds a narrow import hook for the exact required module while leaving every
    installed package and the successful path untouched.
    """
    hook_dir = tmp_path / "python-hook"
    hook_dir.mkdir()
    counter_path = tmp_path / "settings-location-import-count"
    (hook_dir / "sitecustomize.py").write_text(
        """\
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

_counter = Path(os.environ["PKM_SETTINGS_LOCATION_IMPORT_COUNTER"])
_fail_on = int(os.environ["PKM_SETTINGS_LOCATION_IMPORT_FAIL_ON"])


class _FailSettingsLocations(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "app.settings.locations":
            return None
        count = int(_counter.read_text() if _counter.exists() else "0") + 1
        _counter.write_text(str(count))
        if count == _fail_on:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ImportError("injected settings-location import failure")


sys.meta_path.insert(0, _FailSettingsLocations())
""",
        encoding="utf-8",
    )
    inherited_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(hook_dir), inherited_pythonpath) if part
    )
    env["PKM_SETTINGS_LOCATION_IMPORT_COUNTER"] = str(counter_path)
    env["PKM_SETTINGS_LOCATION_IMPORT_FAIL_ON"] = str(fail_on_import)


@pytest.mark.parametrize(
    ("fail_on_import", "provider"),
    [(1, "mock"), (2, "ollama")],
    ids=("primary-provider-resolution", "ollama-provider-resolution"),
)
def test_export_runtime_env_fails_loudly_when_settings_location_import_fails(
    tmp_path: Path, fail_on_import: int, provider: str
) -> None:
    """Each required settings-location import exposes its original failure."""
    repo_root, _, env = _runtime_env_with_db(tmp_path)
    env["LLM_PROVIDER"] = provider
    if provider == "ollama":
        env["OLLAMA_URL"] = "http://ollama:11434"
    _install_settings_location_import_failure(tmp_path, env, fail_on_import=fail_on_import)

    result = subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "injected settings-location import failure" in result.stderr
    assert "NameError: name 'resolve_settings_file' is not defined" not in result.stderr
    assert "NameError: name 'LEGACY_COMPILED_DIR' is not defined" not in result.stderr


def test_export_runtime_env_import_failure_paths_do_not_leave_unbound_location_helpers() -> None:
    """The two embedded blocks import required location helpers outside fallbacks."""
    script = (Path(__file__).resolve().parents[2] / "scripts/export_runtime_env.sh").read_text(
        encoding="utf-8"
    )
    blocks = re.findall(r"python3 - <<'PY' >> \"\$runtime_env_path\"\n(.*?)\nPY", script, re.S)
    assert len(blocks) == 2

    for block in blocks:
        tree = ast.parse(block)
        location_imports = [
            statement
            for statement in tree.body
            if isinstance(statement, ast.ImportFrom)
            and statement.module == "app.settings.locations"
        ]
        assert len(location_imports) == 1
        assert {
            alias.name for alias in location_imports[0].names
        } == {"LEGACY_COMPILED_DIR", "resolve_settings_file"}
        assert all(
            "app.settings.locations" not in ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
        )


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


def test_export_runtime_env_operator_env_overrides_settings(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    _write_default_provider_settings(Path(env["VAULT_ROOT"]))
    env["LLM_PROVIDER"] = "mock"
    env["LLM_MODEL"] = "operator-model"
    env["OPENAI_BASE_URL"] = "https://operator.example/v1"

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    text = out_path.read_text(encoding="utf-8")
    assert re.search(r"^LLM_PROVIDER=mock$", text, re.M)
    assert re.search(r"^LLM_MODEL=operator-model$", text, re.M)
    assert re.search(r"^OPENAI_BASE_URL=https://operator\.example/v1$", text, re.M)
    assert re.search(r"^OPENAI_BASE=https://operator\.example/v1/chat/completions$", text, re.M)


def test_export_runtime_env_no_duplicate_provider_keys(tmp_path: Path) -> None:
    repo_root, out_path, env = _runtime_env_with_db(tmp_path)
    _write_default_provider_settings(Path(env["VAULT_ROOT"]))
    env["LLM_PROVIDER"] = ""
    env["LLM_MODEL"] = ""
    env["OPENAI_BASE_URL"] = ""
    env["OPENAI_BASE"] = ""

    subprocess.check_call(["bash", "scripts/export_runtime_env.sh"], cwd=str(repo_root), env=env)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.startswith("LLM_PROVIDER=")) == 1
    assert sum(1 for line in lines if line.startswith("LLM_MODEL=")) == 1
    assert sum(1 for line in lines if line.startswith("OPENAI_BASE_URL=")) == 1
