"""Merged dev-compose regression contracts for Issues #3659 and #3875."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from app.release_channels.channel_isolation_preflight import (
    _load_compose,
    _resolve_key_through_chain,
    _service_env_file_layers,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
DEV_DSN = "postgresql+psycopg://app:app@db:5432/app_dev"

RUNTIME_SERVICES = ("api", "worker", "watcher")
VAULT_BINDING_KEYS = ("VAULT_ROOT", "VAULT_ROOT_DEV")

# Compose value interpolation tokens: $$, $VAR, ${VAR}, ${VAR:-def}, ${VAR-def}.
_VALUE_VAR_PATTERN = re.compile(
    r"\$(?:(?P<escaped>\$)|(?P<named>[A-Za-z_][A-Za-z0-9_]*)|\{(?P<braced>[^}]*)\})"
)
_BRACED_SIMPLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BRACED_DEFAULT = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<colon>:?)-(?P<default>.*)$"
)


def _environment_mapping(service_config: dict) -> dict[str, str]:
    environment = service_config.get("environment") or {}
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    return dict(item.split("=", 1) for item in environment)


def _merged_service_environment(service: str) -> dict[str, str]:
    """Model Compose's mapping merge for one service environment block."""
    base_service = _load_compose(BASE_COMPOSE)["services"][service]
    dev_service = _load_compose(DEV_COMPOSE)["services"][service]

    return {
        **_environment_mapping(base_service),
        **_environment_mapping(dev_service),
    }


def _interpolate_value(expr: str, lookup: Callable[[str], str | None]) -> str:
    """Interpolate a compose `environment:` value the way Compose does.

    Unlike env_file *path* interpolation, an empty result is a legal value
    here — Compose happily renders `${VAULT_ROOT:-}` to an explicit empty
    string, which is exactly the #3875 bug this module guards against.
    """
    out: list[str] = []
    pos = 0
    for match in _VALUE_VAR_PATTERN.finditer(expr):
        out.append(expr[pos:match.start()])
        pos = match.end()
        if match.group("escaped"):
            out.append("$")
            continue
        named = match.group("named")
        if named is not None:
            out.append(lookup(named) or "")
            continue
        braced = match.group("braced") or ""
        if _BRACED_SIMPLE.match(braced):
            out.append(lookup(braced) or "")
            continue
        default_match = _BRACED_DEFAULT.match(braced)
        assert default_match is not None, f"unsupported compose expression: {expr!r}"
        value = lookup(default_match.group("name"))
        if default_match.group("colon"):
            out.append(value if value else default_match.group("default"))
        else:
            out.append(value if value is not None else default_match.group("default"))
    out.append(expr[pos:])
    return "".join(out)


def _read_channel_env_value(env_file: Path, key: str) -> str:
    """Mirror scripts/lib/deploy_channel_compose.sh::_deploy_channel_env_value."""
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:]
    return ""


def _deploy_subshell_environment(
    channel_env_file: Path,
    parent_shell_env: Mapping[str, str],
) -> dict[str, str]:
    """Mirror deploy_channel_compose's governed env pinning for the subshell.

    The wrapper exports WATCHER_RUNTIME_ENV_FILE and VAULT_HOST_ROOT from the
    governed channel/runtime env files (or unsets them) so a stale parent
    shell cannot swap the selected runtime env or vault host root. It never
    passes the runtime env file as a Compose CLI --env-file (that would expose
    its DSNs to interpolation).
    """
    env = dict(parent_shell_env)

    runtime_env_ref = _read_channel_env_value(
        channel_env_file, "WATCHER_RUNTIME_ENV_FILE"
    )
    runtime_env_file: Path | None = None
    if runtime_env_ref:
        candidate = Path(runtime_env_ref)
        runtime_env_file = (
            candidate if candidate.is_absolute() else REPO_ROOT / runtime_env_ref
        )
        env["WATCHER_RUNTIME_ENV_FILE"] = runtime_env_ref
    else:
        env.pop("WATCHER_RUNTIME_ENV_FILE", None)

    vault_host_root = _read_channel_env_value(channel_env_file, "VAULT_HOST_ROOT")
    if (
        not vault_host_root
        and runtime_env_file is not None
        and runtime_env_file.is_file()
    ):
        vault_host_root = _read_channel_env_value(runtime_env_file, "VAULT_HOST_ROOT")
    if vault_host_root:
        env["VAULT_HOST_ROOT"] = vault_host_root
    else:
        env.pop("VAULT_HOST_ROOT", None)

    return env


def _effective_container_env_value(
    service: str,
    key: str,
    cli_env: Mapping[str, str],
    channel_env_file: Path,
) -> str | None:
    """Render the effective container value for *key* the way Compose does.

    Precedence modeled after the documented Compose semantics:

    1. A key declared in the merged service `environment:` mapping always wins
       over every `env_file:` layer; its value interpolates from the Compose
       CLI environment (invoking shell first, then the CLI --env-file values —
       here the channel env file) and NEVER from a service env_file.
    2. Otherwise the service's env_file chain resolves the key in declaration
       order, later files winning.
    3. Otherwise the key is absent from the container environment.
    """
    def lookup(name: str) -> str | None:
        if name in cli_env:
            return cli_env[name]
        value = _read_channel_env_value(channel_env_file, name)
        return value or None

    merged_environment = _merged_service_environment(service)
    if key in merged_environment:
        return _interpolate_value(merged_environment[key], lookup)

    base_service = _load_compose(BASE_COMPOSE)["services"][service]
    chain = _service_env_file_layers(base_service)
    resolution = _resolve_key_through_chain(key, chain, REPO_ROOT, lookup)
    assert resolution.error is None, resolution.error
    return resolution.value


def _write_deploy_fixtures(
    tmp_path: Path,
    runtime_vault_root: str,
    runtime_vault_root_dev: str,
) -> Path:
    """Write a synthetic channel-env + runtime-env fixture pair.

    Values are synthetic selectors only — never real operator vault paths.
    """
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        f"VAULT_ROOT={runtime_vault_root}\n"
        f"VAULT_ROOT_DEV={runtime_vault_root_dev}\n",
        encoding="utf-8",
    )
    channel_env = tmp_path / "dev.env"
    channel_env.write_text(
        "APP_IMAGE_TAG=0000000000000000000000000000000000000000\n"
        f"WATCHER_RUNTIME_ENV_FILE={runtime_env}\n",
        encoding="utf-8",
    )
    return channel_env


def test_dev_migrate_uses_app_dev_dsn() -> None:
    """The one-shot migration gate must target the same DB as dev services."""
    migrate_environment = _merged_service_environment("migrate")

    assert migrate_environment["DATABASE_URL"] == DEV_DSN
    assert migrate_environment["DB_DSN"] == DEV_DSN
    assert "/app_dev" in migrate_environment["DATABASE_URL"]
    assert "/app_dev" in migrate_environment["DB_DSN"]


def test_dev_runtime_services_forward_deploy_vault_bindings() -> None:
    """Vault selection rides the governed env_file chain, never an overlay key.

    A `VAULT_ROOT: ${VAULT_ROOT:-}` style key in the dev overlay is the #3875
    bug: Compose resolves `environment:` interpolations from the CLI shell
    only (the deploy wrapper deliberately never passes the runtime env file
    as a CLI --env-file), so during `deploy_channel.sh deploy dev` the key
    renders as an explicit empty string and overrides — blanks — the binding
    the base compose's env_file chain (config/runtime.defaults.env + the
    WATCHER_RUNTIME_ENV_FILE layer) supplies. The overlay must therefore not
    declare these keys at all.
    """
    for service in RUNTIME_SERVICES:
        merged_environment = _merged_service_environment(service)
        for key in VAULT_BINDING_KEYS:
            assert key not in merged_environment, (
                f"{service}.environment declares {key}; an interpolated overlay "
                "key blanks the governed runtime-env vault binding (#3875)"
            )

        base_service = _load_compose(BASE_COMPOSE)["services"][service]
        layer_paths = [
            layer.path_expr for layer in _service_env_file_layers(base_service)
        ]
        assert "./config/runtime.defaults.env" in layer_paths
        assert any("WATCHER_RUNTIME_ENV_FILE" in path for path in layer_paths), (
            f"{service} lost the WATCHER_RUNTIME_ENV_FILE env_file layer that "
            "carries the vault binding"
        )


def test_deploy_channel_preserves_runtime_env_vault_bindings(tmp_path: Path) -> None:
    """A dev deploy render keeps the runtime-env vault selectors non-empty.

    Models `scripts/deploy_channel.sh deploy dev` via deploy_channel_compose:
    the channel env file points WATCHER_RUNTIME_ENV_FILE at a runtime env file
    carrying vault selectors, and the rendered api/worker/watcher container
    environment must keep those selectors non-empty (Issue #3875 AC 1).
    """
    runtime_vault_root = "/synthetic/runtime-env/vault"
    runtime_vault_root_dev = "/synthetic/runtime-env/vault-dev"
    channel_env = _write_deploy_fixtures(
        tmp_path, runtime_vault_root, runtime_vault_root_dev
    )

    cli_env = _deploy_subshell_environment(channel_env, parent_shell_env={})

    expected = {
        "VAULT_ROOT": runtime_vault_root,
        "VAULT_ROOT_DEV": runtime_vault_root_dev,
    }
    for service in RUNTIME_SERVICES:
        for key, expected_value in expected.items():
            effective = _effective_container_env_value(
                service, key, cli_env, channel_env
            )
            assert effective, (
                f"{service} rendered an empty/absent {key}: the deploy blanked "
                "the runtime-env vault binding (#3875)"
            )
            assert effective == expected_value


def test_deploy_channel_runtime_env_vault_binding_ignores_parent_shell_stale_value(
    tmp_path: Path,
) -> None:
    """A stale parent shell cannot override the governed vault selection.

    The deploy wrapper pins WATCHER_RUNTIME_ENV_FILE from the governed channel
    env file, and the overlay declares no VAULT_ROOT/VAULT_ROOT_DEV
    interpolation keys — so stale parent-shell vault selectors have no path
    into the rendered container environment (Issue #3875 AC 2).
    """
    governed_vault_root = "/synthetic/governed/vault"
    governed_vault_root_dev = "/synthetic/governed/vault-dev"
    channel_env = _write_deploy_fixtures(
        tmp_path, governed_vault_root, governed_vault_root_dev
    )

    stale_runtime_env = tmp_path / "stale-runtime.env"
    stale_runtime_env.write_text(
        "VAULT_ROOT=/synthetic/stale-shell/vault\n"
        "VAULT_ROOT_DEV=/synthetic/stale-shell/vault-dev\n",
        encoding="utf-8",
    )
    stale_parent_shell = {
        "VAULT_ROOT": "/synthetic/stale-shell/vault",
        "VAULT_ROOT_DEV": "/synthetic/stale-shell/vault-dev",
        # A stale runtime-env pointer must lose to the governed channel value.
        "WATCHER_RUNTIME_ENV_FILE": str(stale_runtime_env),
    }

    cli_env = _deploy_subshell_environment(channel_env, stale_parent_shell)
    assert cli_env["WATCHER_RUNTIME_ENV_FILE"] != str(stale_runtime_env)

    expected = {
        "VAULT_ROOT": governed_vault_root,
        "VAULT_ROOT_DEV": governed_vault_root_dev,
    }
    for service in RUNTIME_SERVICES:
        for key, expected_value in expected.items():
            effective = _effective_container_env_value(
                service, key, cli_env, channel_env
            )
            assert effective == expected_value
            assert effective != stale_parent_shell[key], (
                f"{service} rendered the stale parent-shell {key}: ambient shell "
                "state overrode the governed channel selection (#3875)"
            )
