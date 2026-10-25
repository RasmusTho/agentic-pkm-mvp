"""No-mock, opt-in UAT for the isolated Expansion Connect/Create/Accept path.

The runtime scenarios use real test-channel retrieval, synthesis, WriteGuard,
vault files, and the governed acceptance function. They never substitute a
provider, index, guard, or production function. The final synthetic test-actor
action is a separately authorized phase; see the companion runbook.
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from app.agents.panel.parser import parse_panel
from app.expansion.accept import DraftNotAcceptedError, accept_draft
from app.expansion.connect import ConnectPassConfig, run_connect_pass
from app.expansion.create import CreateRequest, OutputKind, SourceInput, run_create_pass
from app.index.artifact_metadata import compute_indexed_content_hash
from app.ops.channel_preflight import TEST_DB_HOST_PORT
from app.retrieval.capability import RetrievalRequest, retrieve
from app.stores import get_vector_index
from app.vault.paths import get_vault_system_dir_rel
from scripts.yaml_roundtrip import load_frontmatter

RUN_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_UAT"
TEST_ACTOR_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR"
EXPANSION_ACTOR_AUTHORIZATION_REF = (
    "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4826#issuecomment-6107736254"
)
EXPECTED_IDENTITY = {
    "provider": "ollama",
    "model": "bge-m3:latest",
    "dim": 1024,
    "normalize": True,
}
TEST_RUNTIME_VAULT_PATH = Path("/app/vault")
TEST_RUNTIME_OUTBOX_PATH = Path("/app/tmp-test/index-outbox.jsonl")
TEST_RUNTIME_HEARTBEAT_PATH = Path("/app/tmp-test/watcher_heartbeat.json")
TEST_COMPOSE_PROJECT = "pkm-test"
TEST_COMPOSE_NETWORK = "pkm-test_default"
TEST_COMPOSE_NETWORK_ID = "pkm-test-default-network-id"
TEST_RUNTIME_VOLUME_NAME = "pkm-test_runtime-tmp"
TEST_RUNTIME_SERVICES = ("api", "worker", "watcher")
HOST_TEST_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DATABASE_ENDPOINT_OVERRIDE_QUERY_KEYS = frozenset(
    {
        "database",
        "dbname",
        "host",
        "hostaddr",
        "load_balance_hosts",
        "port",
        "service",
        "servicefile",
        "target_session_attrs",
    }
)
CHANNEL_ENV_KEYS = (
    "PKM_ENVIRONMENT",
    "PKM_CHANNEL",
    "COMPOSE_PROJECT_NAME",
    "VAULT_ROOT_TEST",
    "VAULT_HOST_ROOT",
    "DATABASE_URL",
    "DB_DSN",
    "STORE_BACKEND",
    "INDEX_OUTBOX_PATH",
    "LLM_FORCE_PROVIDER",
    "LLM_FORCE_MODEL",
    "LLM_PROVIDER_ENFORCE",
    "LLM_PROVIDER",
    "LLM_CHAT_MODEL",
    "LLM_EMBED_MODEL",
    "REASONING_PROVIDER",
)
# Root pytest safety setup removes VAULT_ROOT and may normalize DB/provider
# settings. Capture only the explicit TEST selectors at import so this opt-in
# module can restore them inside its fixture without using the operator vault.
_CAPTURED_TEST_ENV = {name: os.getenv(name) for name in CHANNEL_ENV_KEYS}


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required for this isolated TEST UAT")
    return value


def _restore_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _CAPTURED_TEST_ENV.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _subprocess_env(vault_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["VAULT_ROOT"] = str(vault_root)
    environment["VAULT_ROOT_TEST"] = str(vault_root)
    return environment


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=False, capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2]
    )
    if result.returncode != 0:
        pytest.fail("cannot establish exact candidate identity from the current checkout")
    return result.stdout.strip()


def _candidate_identity() -> dict[str, str]:
    head = _git_value("rev-parse", "HEAD")
    base = _git_value("merge-base", "HEAD", "origin/main")
    if _git_value("status", "--porcelain"):
        pytest.fail("live UAT requires a clean checkout at the candidate SHA")
    return {"base_sha": base, "head_sha": head}


def _run_channel_command(args: list[str], *, vault_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=_subprocess_env(vault_root),
        cwd=Path(__file__).resolve().parents[2],
    )


def _assert_test_channel_preflight(vault_root: Path) -> None:
    result = _run_channel_command(
        ["ops", "channel-preflight", "--channel", "test", "--context", "host"],
        vault_root=vault_root,
    )
    # Do not echo preflight diagnostics: failure output can include the actual
    # value of a misbound environment variable.
    assert result.returncode == 0, "test-channel preflight failed; inspect the named bindings locally"


def _read_doctor(vault_root: Path) -> dict[str, Any]:
    result = _run_channel_command(["index", "doctor", "--strict", "--json"], vault_root=vault_root)
    assert result.returncode == 0, "strict index doctor failed; inspect its output locally"
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError("strict index doctor did not return JSON") from exc
    assert report.get("status") == "ok"
    assert report.get("issues") == []
    assert report.get("expected_identity") == EXPECTED_IDENTITY
    assert report.get("stored_identity") == EXPECTED_IDENTITY
    return report


def _assert_no_mock_reasoning_route() -> dict[str, str]:
    from app.settings.reasoning_route import resolve_effective_reasoning_route
    from app.reasoning.provider import OllamaDeliberationAgent, get_deliberation_agent

    backend = (os.getenv("REASONING_PROVIDER") or "").strip().lower()
    assert backend in {"", "llm", "ollama"}, "no-mock TEST UAT requires a supported live reasoning backend"
    assert (os.getenv("LLM_PROVIDER") or "").strip().lower() != "mock", (
        "no-mock TEST UAT refuses the reasoning provider's mock-agent fallback"
    )
    assert not (os.getenv("CI") == "1" and not backend), "no-mock TEST UAT refuses CI's implicit mock backend"
    agent = get_deliberation_agent()
    assert isinstance(agent, OllamaDeliberationAgent), "effective reasoning selection resolved to a mock or unknown agent"
    route = resolve_effective_reasoning_route()
    assert route.provider.strip().lower() != "mock", "no-mock TEST UAT refuses a mock effective reasoning route"
    return {"provider": route.provider, "model": route.model}


def _successful_cognition(frontmatter: dict[str, Any]) -> dict[str, Any]:
    proposed_by = frontmatter.get("proposed_by")
    cognition = proposed_by.get("cognition") if isinstance(proposed_by, dict) else None
    assert isinstance(cognition, dict), "Create draft lacks its cognition execution receipt"
    assert cognition.get("outcome") == "success", "Create cognition did not complete successfully"
    assert cognition.get("degraded") is False and cognition.get("degraded_reason") is None, (
        "Create cognition degraded to deterministic collation; do not report technical UAT PASS"
    )
    return cognition


def _outside_ai_panels(text: str) -> str:
    remaining: list[str] = []
    in_panel = False
    for line in text.splitlines(keepends=True):
        marker = line.strip()
        if marker == "%% AI:Start %%":
            assert not in_panel, "nested AI panel marker in a source note"
            in_panel = True
            continue
        if marker == "%% AI:End %%":
            assert in_panel, "unmatched AI panel end marker in a source note"
            in_panel = False
            continue
        if not in_panel:
            remaining.append(line)
    assert not in_panel, "unterminated AI panel in a source note"
    return "".join(remaining)


def _relative_source_path(raw: str, vault_root: Path) -> Path:
    candidate = (vault_root / raw).resolve()
    assert candidate.is_relative_to(vault_root), "a selected source escapes the TEST vault"
    assert candidate.is_file(), "a selected TEST source is missing"
    relative = candidate.relative_to(vault_root).as_posix()
    assert not relative.startswith("_system/drafts/"), "a staged draft cannot be a Connect/Create source"
    return candidate


def _source_input(path: Path, vault_root: Path) -> tuple[SourceInput, str]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(text)
    object_id = str(frontmatter.get("uuid") or f"path:{path.relative_to(vault_root).as_posix()}").strip()
    quote = next(
        (line.strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")),
        None,
    )
    assert quote, "a selected TEST source must contain a quotable body span"
    return (
        SourceInput(
            object_id=object_id,
            note_path=path.relative_to(vault_root).as_posix(),
            text=text,
            quoted_spans=(quote,),
            language=str(frontmatter.get("language") or "und"),
            review_state=str(frontmatter.get("review_state") or "reviewed"),
        ),
        str(frontmatter.get("domain") or "").strip(),
    )


def _shared_source_scope(scopes: tuple[str, str]) -> str:
    """Require the selected pair to share one explicit or unscoped domain."""
    assert scopes[0] == scopes[1], "the selected source pair must share one scope"
    return scopes[0] or "unscoped"


def _source_ref_matches(raw: str, path: Path, vault_root: Path) -> bool:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = vault_root / candidate
    try:
        return candidate.resolve() == path.resolve()
    except OSError:
        return False


def _canonical_absolute_path(raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            return None
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _is_isolated_test_database_binding(
    environment: dict[str, str],
    *,
    require_both: bool,
    expected_host: str | None = None,
    expected_hosts: frozenset[str] | None = None,
    expected_port: int | None = None,
) -> bool:
    """Classify DSNs in memory without exposing credentials in diagnostics."""
    values = [environment.get(name, "").strip() for name in ("DATABASE_URL", "DB_DSN")]
    configured = [value for value in values if value]
    if not configured or (require_both and len(configured) != len(values)):
        return False
    if len(configured) == 2 and configured[0] != configured[1]:
        return False
    try:
        from sqlalchemy.engine import make_url

        urls = [make_url(value) for value in configured]
    except Exception:
        return False
    return all(
        url.drivername.startswith("postgresql")
        and url.database == "app_test"
        and not DATABASE_ENDPOINT_OVERRIDE_QUERY_KEYS.intersection(
            str(key).lower() for key in url.query
        )
        and (expected_host is None or url.host == expected_host)
        and (expected_hosts is None or url.host in expected_hosts)
        and (expected_port is None or url.port == expected_port)
        for url in urls
    )


@dataclass(frozen=True)
class _TestWatcherBinding:
    container_id: str
    runtime_volume_name: str
    runtime_volume_mountpoint: Path
    database_host_port: int = int(TEST_DB_HOST_PORT)


@dataclass(frozen=True)
class _TestDatabaseBinding:
    container_id: str
    network_id: str
    address: str
    host_port: int


def _parse_test_database_service_inspect(payload: object) -> _TestDatabaseBinding | None:
    """Bind `db` to the one running pkm-test PostgreSQL service and network."""
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    container = payload[0]
    config = container.get("Config")
    state = container.get("State")
    container_id = container.get("Id")
    labels = config.get("Labels") if isinstance(config, dict) else None
    raw_environment = config.get("Env") if isinstance(config, dict) else None
    if (
        not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != TEST_COMPOSE_PROJECT
        or labels.get("com.docker.compose.service") != "db"
        or not isinstance(state, dict)
        or state.get("Status") != "running"
        or state.get("Running") is not True
        or not isinstance(container_id, str)
        or not container_id
        or not isinstance(raw_environment, list)
        or not all(isinstance(item, str) and "=" in item for item in raw_environment)
    ):
        return None
    environment: dict[str, str] = {}
    for item in raw_environment:
        key, value = item.split("=", 1)
        if key in environment:
            return None
        environment[key] = value
    if environment.get("POSTGRES_DB") != "app_test":
        return None

    network_settings = container.get("NetworkSettings")
    networks = network_settings.get("Networks") if isinstance(network_settings, dict) else None
    if not isinstance(networks, dict) or set(networks) != {TEST_COMPOSE_NETWORK}:
        return None
    endpoint = networks.get(TEST_COMPOSE_NETWORK)
    aliases = endpoint.get("Aliases") if isinstance(endpoint, dict) else None
    if not isinstance(aliases, list) or "db" not in aliases:
        return None
    network_id = endpoint.get("NetworkID")
    raw_address = endpoint.get("IPAddress")
    if not isinstance(network_id, str) or not network_id or not isinstance(raw_address, str):
        return None
    try:
        address = str(ipaddress.IPv4Address(raw_address))
    except ipaddress.AddressValueError:
        return None
    raw_ports = network_settings.get("Ports") if isinstance(network_settings, dict) else None
    port_bindings = raw_ports.get("5432/tcp") if isinstance(raw_ports, dict) else None
    if not isinstance(port_bindings, list) or not port_bindings:
        return None
    host_ports: set[int] = set()
    allowed_host_ips = {"", "0.0.0.0", "::", "127.0.0.1", "::1"}
    for binding in port_bindings:
        if not isinstance(binding, dict):
            return None
        raw_host_port = binding.get("HostPort")
        if (
            not isinstance(raw_host_port, str)
            or not raw_host_port.isdecimal()
            or binding.get("HostIp") not in allowed_host_ips
        ):
            return None
        host_ports.add(int(raw_host_port))
    if host_ports != {int(TEST_DB_HOST_PORT)}:
        return None
    return _TestDatabaseBinding(container_id, network_id, address, next(iter(host_ports)))


def _test_compose_default_network_matches(payload: object, network_id: str) -> bool:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return False
    network = payload[0]
    labels = network.get("Labels")
    return (
        network.get("Name") == TEST_COMPOSE_NETWORK
        and network.get("Id") == network_id
        and isinstance(labels, dict)
        and labels.get("com.docker.compose.project") == TEST_COMPOSE_PROJECT
        and labels.get("com.docker.compose.network") == "default"
    )


def _container_resolves_test_database_to_expected_address(container_id: str, address: str) -> bool:
    """Check Docker DNS inside a runtime container without opening a DB session."""
    resolution_probe = (
        "import json,socket; print(json.dumps(sorted({entry[4][0] for entry in "
        "socket.getaddrinfo('db',5432,family=socket.AF_INET,type=socket.SOCK_STREAM)})))"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", container_id, "python", "-c", resolution_probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        addresses = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return addresses == [address]


def _parse_test_runtime_service_inspect(
    payload: object,
    *,
    service: str,
    selected_vault_path: Path,
    expected_database_network_id: str,
) -> tuple[str, str] | None:
    """Validate one running TEST service against its actual Docker mounts."""
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    container = payload[0]
    config = container.get("Config")
    if not isinstance(config, dict):
        return None
    labels = config.get("Labels")
    state = container.get("State")
    container_id = container.get("Id")
    if (
        not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != TEST_COMPOSE_PROJECT
        or labels.get("com.docker.compose.service") != service
        or not isinstance(state, dict)
        or state.get("Status") != "running"
        or state.get("Running") is not True
        or not isinstance(container_id, str)
        or not container_id
    ):
        return None
    host_config = container.get("HostConfig")
    extra_hosts = host_config.get("ExtraHosts") if isinstance(host_config, dict) else None
    network_settings = container.get("NetworkSettings")
    networks = network_settings.get("Networks") if isinstance(network_settings, dict) else None
    if (
        not isinstance(host_config, dict)
        or extra_hosts not in (None, [])
        or not isinstance(networks, dict)
        or set(networks) != {TEST_COMPOSE_NETWORK}
    ):
        return None
    network = networks.get(TEST_COMPOSE_NETWORK)
    if not isinstance(network, dict) or network.get("NetworkID") != expected_database_network_id:
        return None
    raw_environment = config.get("Env")
    if not isinstance(raw_environment, list) or not all(isinstance(item, str) for item in raw_environment):
        return None
    environment: dict[str, str] = {}
    for item in raw_environment:
        if "=" not in item:
            return None
        key, value = item.split("=", 1)
        if key in environment:
            return None
        environment[key] = value
    if (
        environment.get("PKM_ENVIRONMENT") != "test"
        or environment.get("VAULT_ROOT") != str(TEST_RUNTIME_VAULT_PATH)
        or environment.get("VAULT_ROOT_TEST") != str(TEST_RUNTIME_VAULT_PATH)
        or environment.get("INDEX_OUTBOX_PATH") != str(TEST_RUNTIME_OUTBOX_PATH)
        or environment.get("WATCHER_HEARTBEAT_PATH") != str(TEST_RUNTIME_HEARTBEAT_PATH)
        or not _is_isolated_test_database_binding(
            environment,
            require_both=True,
            expected_host="db",
            expected_port=5432,
        )
    ):
        return None
    if service in {"api", "worker", "watcher"} and (
        environment.get("WATCHER_ENABLE") != "1"
        or environment.get("WATCHER_VAULT_PATH") != str(TEST_RUNTIME_VAULT_PATH)
    ):
        return None
    mounts = container.get("Mounts")
    if not isinstance(mounts, list) or not all(isinstance(mount, dict) for mount in mounts):
        return None
    runtime_destination = PurePosixPath("/app/tmp-test")
    for mount in mounts:
        raw_destination = mount.get("Destination")
        if not isinstance(raw_destination, str) or not raw_destination.startswith("/"):
            return None
        destination = PurePosixPath(raw_destination)
        if ".." in destination.parts:
            return None
        if destination != runtime_destination:
            try:
                destination.relative_to(runtime_destination)
            except ValueError:
                continue
            else:
                # Descendant mounts can shadow the heartbeat or outbox files
                # even when the parent runtime-tmp volume is correct.
                return None
    selected_vault = selected_vault_path.expanduser().resolve(strict=False)
    vault_mounts = [
        mount
        for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == str(TEST_RUNTIME_VAULT_PATH)
    ]
    runtime_mounts = [
        mount
        for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == "/app/tmp-test"
    ]
    if len(vault_mounts) != 1 or len(runtime_mounts) != 1:
        return None
    vault_mount = vault_mounts[0]
    runtime_mount = runtime_mounts[0]
    mounted_vault = _canonical_absolute_path(vault_mount.get("Source"))
    volume_name = runtime_mount.get("Name")
    if (
        vault_mount.get("Type") != "bind"
        or mounted_vault != selected_vault
        or runtime_mount.get("Type") != "volume"
        or runtime_mount.get("RW") is not True
        or volume_name != TEST_RUNTIME_VOLUME_NAME
    ):
        return None
    return container_id, volume_name


def _test_runtime_volume_mountpoint(payload: object, volume_name: str) -> Path | None:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    volume = payload[0]
    labels = volume.get("Labels")
    mountpoint = _canonical_absolute_path(volume.get("Mountpoint"))
    if (
        volume.get("Name") != volume_name
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or volume.get("Options") not in (None, {})
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != TEST_COMPOSE_PROJECT
        or labels.get("com.docker.compose.volume") != "runtime-tmp"
        or mountpoint is None
    ):
        return None
    return mountpoint


def _test_runtime_volume_matches(payload: object, volume_name: str) -> bool:
    return _test_runtime_volume_mountpoint(payload, volume_name) is not None


def _assert_host_outbox_separate_from_runtime_volume(
    outbox_path: Path,
    watcher_binding: _TestWatcherBinding,
    *,
    repo_root: Path | None = None,
) -> None:
    """Bind the host action outbox to this checkout and reject volume aliases."""
    canonical_root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=False)
    canonical_outbox = outbox_path.expanduser().resolve(strict=False)
    expected_outbox = (canonical_root / "tmp-test" / "index-outbox.jsonl").resolve(strict=False)
    if canonical_outbox != expected_outbox or not canonical_outbox.is_relative_to(canonical_root):
        raise AssertionError("host UAT outbox must be this checkout's tmp-test/index-outbox.jsonl")

    runtime_volume_root = watcher_binding.runtime_volume_mountpoint.resolve(strict=False)
    if canonical_outbox.is_relative_to(runtime_volume_root):
        raise AssertionError("host UAT outbox resolves inside the TEST runtime-tmp Docker volume")
    try:
        host_tmp_test = canonical_root / "tmp-test"
        volume_outbox = runtime_volume_root / canonical_outbox.name
        if (
            runtime_volume_root.exists()
            and (
                (host_tmp_test.exists() and os.path.samefile(host_tmp_test, runtime_volume_root))
                or (canonical_outbox.exists() and volume_outbox.exists() and os.path.samefile(canonical_outbox, volume_outbox))
            )
        ):
            raise AssertionError("host UAT outbox aliases the TEST runtime-tmp Docker volume")
    except OSError:
        # Docker Desktop volume mountpoints may exist only inside its VM. In
        # that case the canonical checkout-local binding above remains the
        # host-side identity evidence.
        pass


def _inspect_active_test_watcher(selected_vault_path: Path) -> _TestWatcherBinding:
    """Read-only inspect the live TEST services and pin the watcher container."""
    assert os.getenv("COMPOSE_PROJECT_NAME") == TEST_COMPOSE_PROJECT, (
        "the UAT must be explicitly bound to the pkm-test Compose project"
    )

    def inspect_service(service: str) -> tuple[str, object]:
        try:
            listed = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--no-trunc",
                    "--filter",
                    f"label=com.docker.compose.project={TEST_COMPOSE_PROJECT}",
                    "--filter",
                    f"label=com.docker.compose.service={service}",
                    "--format",
                    "{{.ID}}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AssertionError("cannot inspect the already-running TEST Docker services") from exc
        container_ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if listed.returncode != 0 or len(container_ids) != 1:
            raise AssertionError(f"expected exactly one running {service} in pkm-test")
        try:
            result = subprocess.run(
                ["docker", "inspect", container_ids[0]],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AssertionError("cannot read the active TEST Docker service configuration") from exc
        if result.returncode != 0:
            raise AssertionError(f"cannot inspect the active TEST {service} container")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"active TEST {service} inspection was malformed") from exc
        return container_ids[0], payload

    database_id, database_payload = inspect_service("db")
    database = _parse_test_database_service_inspect(database_payload)
    if database is None or database.container_id != database_id:
        raise AssertionError("the active db service is not the pkm-test app_test database")
    try:
        network_result = subprocess.run(
            ["docker", "network", "inspect", database.network_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError("cannot inspect the active TEST database network") from exc
    if network_result.returncode != 0:
        raise AssertionError("cannot inspect the active TEST database network")
    try:
        network_payload = json.loads(network_result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError("active TEST network inspection was malformed") from exc
    if not _test_compose_default_network_matches(network_payload, database.network_id):
        raise AssertionError("the active db service is not attached to pkm-test's default network")

    inspected: dict[str, tuple[str, str]] = {}
    for service in TEST_RUNTIME_SERVICES:
        container_id, payload = inspect_service(service)
        parsed = _parse_test_runtime_service_inspect(
            payload,
            service=service,
            selected_vault_path=selected_vault_path,
            expected_database_network_id=database.network_id,
        )
        if parsed is None:
            raise AssertionError(f"active TEST {service} mount or runtime binding does not match UAT")
        if parsed[0] != container_id:
            raise AssertionError(f"active TEST {service} identity changed during inspection")
        if not _container_resolves_test_database_to_expected_address(
            container_id, database.address
        ):
            raise AssertionError(f"active TEST {service} does not resolve db to the inspected TEST database")
        inspected[service] = parsed

    volume_names = {entry[1] for entry in inspected.values()}
    if len(volume_names) != 1:
        raise AssertionError("TEST api, worker, and watcher do not share one runtime-tmp volume")
    volume_name = next(iter(volume_names))
    try:
        volume_result = subprocess.run(
            ["docker", "volume", "inspect", volume_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError("cannot inspect the active TEST runtime volume") from exc
    if volume_result.returncode != 0:
        raise AssertionError("cannot inspect the active TEST runtime volume")
    try:
        volume_payload = json.loads(volume_result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError("active TEST volume inspection was malformed") from exc
    runtime_volume_mountpoint = _test_runtime_volume_mountpoint(volume_payload, volume_name)
    if runtime_volume_mountpoint is None:
        raise AssertionError("the watcher outbox is not in the pkm-test runtime-tmp volume")
    return _TestWatcherBinding(
        container_id=inspected["watcher"][0],
        runtime_volume_name=volume_name,
        runtime_volume_mountpoint=runtime_volume_mountpoint,
        database_host_port=database.host_port,
    )


def _index_source_hashes_match(rows: list[dict[str, Any]], sources: tuple[SourceInput, ...], vault_root: Path) -> bool:
    for source in sources:
        source_path = (vault_root / source.note_path).resolve()
        matching = [
            row
            for row in rows
            if _source_ref_matches(str(row.get("source_ref") or ""), source_path, vault_root)
        ]
        if len(matching) != 1:
            return False
        payload = matching[0].get("payload") or {}
        provenance = payload.get("provenance") or {}
        current_text = source_path.read_text(encoding="utf-8")
        if provenance.get("content_hash") != compute_indexed_content_hash(current_text):
            return False
    return True


@dataclass(frozen=True)
class _IngestWatcherSnapshot:
    timestamp: float
    scan_generation: int
    scan_in_progress: bool
    observation_status: str
    errors_total: int


def _read_ingest_watcher_snapshot(
    heartbeat_source: Path | str,
    *,
    expected_vault_path: Path,
    expected_outbox_path: Path,
    now: float,
    stale_seconds: float | None = None,
) -> _IngestWatcherSnapshot | None:
    """Return a fresh, healthy ingest watermark bound to the expected TEST runtime."""
    if stale_seconds is None:
        try:
            stale_seconds = float(os.getenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60"))
        except ValueError:
            return None
    if not math.isfinite(stale_seconds) or stale_seconds <= 0 or not math.isfinite(now):
        return None
    try:
        raw_payload = (
            heartbeat_source.read_text(encoding="utf-8")
            if isinstance(heartbeat_source, Path)
            else heartbeat_source
        )
        payload = json.loads(raw_payload)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    reported_vault_path = _canonical_absolute_path(payload.get("vault_path"))
    reported_outbox_path = _canonical_absolute_path(payload.get("outbox_path"))
    canonical_expected_vault = _canonical_absolute_path(str(expected_vault_path))
    canonical_expected_outbox = _canonical_absolute_path(str(expected_outbox_path))
    if (
        reported_vault_path is None
        or reported_outbox_path is None
        or canonical_expected_vault is None
        or canonical_expected_outbox is None
        or reported_vault_path != canonical_expected_vault
        or reported_outbox_path != canonical_expected_outbox
    ):
        return None
    timestamp = payload.get("ts")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    timestamp = float(timestamp)
    if not math.isfinite(timestamp) or timestamp > now or now - timestamp > stale_seconds:
        return None
    top_status = payload.get("status")
    if (
        not isinstance(top_status, str)
        or top_status not in {"healthy-idle", "catch-up"}
        or payload.get("paused") is not False
    ):
        return None
    watchers = payload.get("watchers")
    ingest = watchers.get("ingest") if isinstance(watchers, dict) else None
    if not isinstance(ingest, dict):
        return None
    scan_generation = ingest.get("scan_generation")
    errors_total = ingest.get("errors_total")
    scan_in_progress = ingest.get("scan_in_progress")
    observation_status = ingest.get("observation_status")
    if (
        isinstance(scan_generation, bool)
        or not isinstance(scan_generation, int)
        or scan_generation < 0
        or isinstance(errors_total, bool)
        or not isinstance(errors_total, int)
        or errors_total < 0
        or not isinstance(scan_in_progress, bool)
        or not isinstance(observation_status, str)
        or observation_status not in {"healthy-idle", "catch-up"}
        or ingest.get("scope_status") != "ok"
    ):
        return None
    return _IngestWatcherSnapshot(
        timestamp=timestamp,
        scan_generation=scan_generation,
        scan_in_progress=scan_in_progress,
        observation_status=observation_status,
        errors_total=errors_total,
    )


def _is_completed_post_draft_scan(
    baseline: _IngestWatcherSnapshot, current: _IngestWatcherSnapshot
) -> bool:
    return (
        current.timestamp > baseline.timestamp
        and current.scan_generation > baseline.scan_generation
        and not current.scan_in_progress
        and current.observation_status == "healthy-idle"
        and current.errors_total == baseline.errors_total
    )


def _wait_for_post_draft_ingest_scan(
    *,
    watcher_binding: _TestWatcherBinding,
    expected_vault_path: Path,
    expected_outbox_path: Path,
    timeout_seconds: float = 300.0,
) -> _IngestWatcherSnapshot:
    """Require a completed healthy ingest scan newer than the post-Create baseline."""

    def read_snapshot() -> _IngestWatcherSnapshot | None:
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    watcher_binding.container_id,
                    "cat",
                    str(TEST_RUNTIME_HEARTBEAT_PATH),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return _read_ingest_watcher_snapshot(
            result.stdout,
            expected_vault_path=expected_vault_path,
            expected_outbox_path=expected_outbox_path,
            now=time.time(),
        )

    baseline = read_snapshot()
    assert baseline is not None, "Create exclusion proof requires a fresh, healthy TEST watcher heartbeat"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        current = read_snapshot()
        if current is not None:
            if current.scan_generation < baseline.scan_generation:
                pytest.fail("TEST ingest watcher watermark reset during the post-draft observation")
            if current.errors_total < baseline.errors_total:
                pytest.fail("TEST ingest watcher error counter reset during the post-draft observation")
            if current.errors_total > baseline.errors_total:
                pytest.fail("TEST ingest watcher reported new errors during the post-draft observation")
            if _is_completed_post_draft_scan(baseline, current):
                return current
        time.sleep(1.0)
    pytest.fail(
        "no fresh, healthy, completed TEST ingest scan newer than the post-Create watermark "
        f"within {timeout_seconds:g}s"
    )


def _wait_for_index_convergence(
    sources: tuple[SourceInput, ...], vault_root: Path, *, timeout_seconds: float = 60.0
) -> tuple[list[dict[str, Any]], str]:
    """Wait for stable durable rows whose indexed hashes match current sources."""
    index = get_vector_index()
    deadline = time.monotonic() + timeout_seconds
    last_generation: str | None = None
    last_signature: tuple[tuple[str, str, str], ...] | None = None
    stable_observations = 0
    while time.monotonic() < deadline:
        generation_before = index.generation()
        rows = list(index.all_rows())  # exhaustive durable index read, never top-k
        generation_after = index.generation()
        signature = tuple(
            sorted(
                (
                    str(row.get("object_id") or ""),
                    str(row.get("source_ref") or ""),
                    str(((row.get("payload") or {}).get("provenance") or {}).get("content_hash") or ""),
                )
                for row in rows
            )
        )
        stable_read = generation_before == generation_after and signature == last_signature
        if stable_read and _index_source_hashes_match(rows, sources, vault_root):
            stable_observations += 1
        else:
            stable_observations = 0
        if stable_observations >= 2:
            return rows, generation_after
        last_generation = generation_after
        last_signature = signature
        time.sleep(1.0)
    pytest.fail(
        "the durable TEST index did not converge to the selected source hashes "
        f"within {timeout_seconds:g}s (last generation observed: {last_generation or 'none'})"
    )


def _draft_rows(rows: list[dict[str, Any]], draft_path: Path, draft_id: str, vault_root: Path) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        if str(row.get("object_id") or "") == draft_id or str(payload.get("artifact_id") or "") == draft_id:
            matched.append(row)
            continue
        if _source_ref_matches(str(row.get("source_ref") or ""), draft_path, vault_root):
            matched.append(row)
    return matched


@dataclass(frozen=True)
class UatContext:
    vault_root: Path
    outbox_path: Path
    watcher_binding: _TestWatcherBinding
    source_paths: tuple[Path, Path]
    sources: tuple[SourceInput, SourceInput]
    source_scope: str
    connect_query: str
    run_id: str
    receipt_path: Path
    candidate: dict[str, str]
    reasoning_route: dict[str, str]

    def receipt(self) -> dict[str, Any]:
        if not self.receipt_path.exists():
            return {}
        try:
            payload = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError("UAT receipt is unreadable; do not repeat an uncertain phase") from exc
        assert isinstance(payload, dict), "UAT receipt is not an object"
        return payload

    def record(self, **values: Any) -> None:
        payload = self.receipt()
        payload.setdefault("contract", "expansion-connect-create-accept-test-channel.v1")
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("candidate", self.candidate)
        payload.setdefault(
            "channel",
            {
                "name": "test",
                "preflight": "pass",
                "stored_embedding_identity": EXPECTED_IDENTITY,
                "vault_binding": "VAULT_ROOT_TEST",
                "database": "app_test",
                "reasoning_route": self.reasoning_route,
                "receipt_redacted": True,
            },
        )
        payload.update(values)
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        self.receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def uat_context(monkeypatch: pytest.MonkeyPatch) -> UatContext:
    if not _enabled(RUN_ENV):
        pytest.skip(f"opt-in no-mock TEST UAT; set {RUN_ENV}=1 after prerequisites are qualified")

    _restore_test_env(monkeypatch)
    assert os.getenv("PKM_ENVIRONMENT") == "test", "PKM_ENVIRONMENT must be explicitly test"
    assert os.getenv("PKM_CHANNEL") == "test", "PKM_CHANNEL must be explicitly test"
    assert os.getenv("COMPOSE_PROJECT_NAME") == TEST_COMPOSE_PROJECT, (
        "COMPOSE_PROJECT_NAME must be explicitly pkm-test"
    )
    assert os.getenv("STORE_BACKEND", "").strip().lower() == "postgres", "TEST UAT requires the Postgres backend"
    for name in ("LLM_PROVIDER", "LLM_FORCE_PROVIDER"):
        if (os.getenv(name) or "").strip().lower() == "mock":
            pytest.fail("no-mock TEST UAT refuses a mock model provider")

    test_root = Path(_required_env("VAULT_ROOT_TEST")).expanduser().resolve()
    assert test_root.is_dir(), "the pre-existing TEST vault must be reachable"
    host_vault = _canonical_absolute_path(os.getenv("VAULT_HOST_ROOT"))
    assert host_vault == test_root, "VAULT_HOST_ROOT must select the same host TEST vault as VAULT_ROOT_TEST"
    # pytest's root safety harness clears the ambiguous VAULT_ROOT. Rebind it
    # only from the independently required test-only selector before preflight.
    monkeypatch.setenv("VAULT_ROOT", str(test_root))
    watcher_binding = _inspect_active_test_watcher(test_root)
    assert _is_isolated_test_database_binding(
        {name: os.getenv(name, "") for name in ("DATABASE_URL", "DB_DSN")},
        require_both=False,
        expected_hosts=HOST_TEST_DATABASE_HOSTS,
        expected_port=watcher_binding.database_host_port,
    ), "the host TEST UAT DSN must use loopback and the inspected pkm-test published database port"
    _assert_test_channel_preflight(test_root)
    reasoning_route = _assert_no_mock_reasoning_route()
    candidate = _candidate_identity()
    raw_sources = [part.strip() for part in _required_env("UAT_EXPANSION_SOURCE_PATHS").split(",") if part.strip()]
    assert len(raw_sources) == 2, "UAT_EXPANSION_SOURCE_PATHS must name exactly two seeded source notes"
    source_paths = tuple(_relative_source_path(raw, test_root) for raw in raw_sources)
    assert source_paths[0] != source_paths[1], "the selected source pair must be distinct"
    source_data = tuple(_source_input(path, test_root) for path in source_paths)
    sources = tuple(item[0] for item in source_data)
    scopes = tuple(item[1] for item in source_data)
    source_scope = _shared_source_scope((scopes[0], scopes[1]))

    outbox_path = Path(_required_env("INDEX_OUTBOX_PATH")).expanduser().resolve()
    _assert_host_outbox_separate_from_runtime_volume(outbox_path, watcher_binding)
    run_id = _required_env("UAT_EXPANSION_RUN_ID")
    assert len(run_id) >= 8 and all(char.isalnum() or char in "-_" for char in run_id), "UAT run id must be filesystem-safe and unique"
    system_root = Path(get_vault_system_dir_rel(test_root))
    receipt_path = test_root / system_root / "receipts" / f"expansion-connect-create-accept-{run_id}.json"
    receipt_exists = receipt_path.exists()
    prior_receipt: dict[str, Any] = {}
    if receipt_exists:
        try:
            prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError("UAT run id already has an unreadable receipt; choose a fresh run id") from exc
    if _enabled(TEST_ACTOR_ENV):
        assert prior_receipt.get("technical_phase") == "pass", "synthetic action requires the prior technical PASS receipt"
        assert prior_receipt.get("candidate") == candidate, "candidate changed after technical PASS; start a fresh UAT"
        assert prior_receipt.get("run_id") == run_id, "receipt run id does not match the requested action"

    return UatContext(
        vault_root=test_root,
        outbox_path=outbox_path,
        watcher_binding=watcher_binding,
        source_paths=(source_paths[0], source_paths[1]),
        sources=(sources[0], sources[1]),
        source_scope=source_scope,
        connect_query=_required_env("UAT_EXPANSION_CONNECT_QUERY"),
        run_id=run_id,
        receipt_path=receipt_path,
        candidate=candidate,
        reasoning_route=reasoning_route,
    )


def test_test_channel_identity_and_doctor_are_strict(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert not receipt, "technical UAT run id must be fresh"
    report = _read_doctor(uat_context.vault_root)
    uat_context.record(
        technical_phase="doctor_pass",
        doctor={
            "status": report["status"],
            "expected_identity": report["expected_identity"],
            "stored_identity": report["stored_identity"],
            "issue_count": len(report["issues"]),
        },
    )


def test_connect_is_candidate_only_and_unchecked(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "doctor_pass", "run the strict identity/doctor phase first"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed during the UAT"
    before_text = {path: path.read_bytes().decode("utf-8") for path in uat_context.source_paths}
    before_frontmatter = {path: load_frontmatter(text)[0] for path, text in before_text.items()}
    before_markdown = {
        path.relative_to(uat_context.vault_root): path.read_bytes()
        for path in uat_context.vault_root.rglob("*.md")
    }
    top_hits = retrieve(RetrievalRequest(query=uat_context.connect_query, k=2)).hits
    selected_paths = set(uat_context.source_paths)
    assert len(top_hits) == 2, "the bounded Connect preflight must return exactly two top-ranked sources"
    assert all(any(_source_ref_matches(hit.source_ref, path, uat_context.vault_root) for path in selected_paths) for hit in top_hits), (
        "the query's top two results include a source outside the selected pair; Connect was not run"
    )
    assert all(any(_source_ref_matches(hit.source_ref, path, uat_context.vault_root) for hit in top_hits) for path in selected_paths), (
        "the query's top two results must contain both selected sources; Connect was not run"
    )
    drafts_dir = uat_context.vault_root / Path(get_vault_system_dir_rel(uat_context.vault_root)) / "drafts"
    drafts_before = set(drafts_dir.glob("*.md")) if drafts_dir.exists() else set()

    report = run_connect_pass(
        vault_root=uat_context.vault_root,
        queries=[uat_context.connect_query],
        config=ConnectPassConfig(retrieval_k=2),
        outbox_path=uat_context.outbox_path,
    )
    logical_pairs: dict[str, set[str]] = {}
    for finding in report.findings:
        logical_pairs.setdefault(finding.finding_id, set()).add(finding.note_uuid)
    selected_pair = {source.object_id for source in uat_context.sources}
    selected_finding_ids = {
        finding_id for finding_id, note_ids in logical_pairs.items() if selected_pair <= note_ids
    }
    assert selected_finding_ids, "Connect produced no one-finding same-scope result containing both selected identities"

    changed_paths = {
        path for path, original in before_text.items() if path.read_bytes().decode("utf-8") != original
    }
    after_markdown = {
        path.relative_to(uat_context.vault_root): path.read_bytes()
        for path in uat_context.vault_root.rglob("*.md")
    }
    assert after_markdown.keys() == before_markdown.keys(), "Connect created or removed a Markdown artifact"
    changed_markdown = {
        relative_path
        for relative_path, original in before_markdown.items()
        if after_markdown[relative_path] != original
    }
    selected_relative_paths = {
        path.relative_to(uat_context.vault_root) for path in uat_context.source_paths
    }
    assert changed_markdown <= selected_relative_paths, "Connect changed Markdown outside the selected source pair"
    for path in uat_context.source_paths:
        after = path.read_bytes().decode("utf-8")
        assert load_frontmatter(after)[0] == before_frontmatter[path], "Connect changed source frontmatter"
        assert _outside_ai_panels(before_text[path]) == _outside_ai_panels(after), "Connect changed source text outside its governed AI proposal block"
        panel_actions = parse_panel(after).actions
        expected = [
            f"[curation:{finding.finding_class.value}] {finding.proposed} (finding {finding.finding_id[:12]})"
            for finding in report.findings
            if finding.note_uuid == next(source.object_id for source in uat_context.sources if source.note_path == path.relative_to(uat_context.vault_root).as_posix())
            and finding.finding_id in selected_finding_ids
        ]
        assert expected, "the selected logical finding lacks its source-side proposal"
        for proposal in expected:
            matching_actions = [action for action in panel_actions if action.text == proposal]
            assert len(matching_actions) == 1, "selected source must contain one Connect proposal"
            assert not matching_actions[0].checked, "a Connect proposal must remain unchecked"
            assert matching_actions[0].option_id and matching_actions[0].proposal_pending, (
                "a Connect proposal must retain its persistent option and human-gate markers"
            )
    drafts_after = set(drafts_dir.glob("*.md")) if drafts_dir.exists() else set()
    assert drafts_after == drafts_before, "Connect created or removed a staged draft"
    assert changed_paths <= set(uat_context.source_paths), "Connect changed a path outside the selected source pair"
    uat_context.record(
        connect="candidate_only_unchecked",
        selected_source_ids=sorted(selected_pair),
        selected_source_scope=uat_context.source_scope,
        selected_finding_ids=sorted(selected_finding_ids),
        source_changes_within_governed_block=True,
        canonical_or_draft_artifacts_created=0,
    )


def test_create_stages_resolvable_sources_and_excludes_draft_from_retrieval(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("connect") == "candidate_only_unchecked", "run the Connect phase first"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed during the UAT"
    canonical_before = {
        path.relative_to(uat_context.vault_root).as_posix()
        for path in uat_context.vault_root.rglob("*.md")
        if "drafts" not in path.relative_to(uat_context.vault_root).parts
    }
    request = CreateRequest(
        kind=OutputKind.OVERVIEW,
        title=f"UAT Connect Create Accept {uat_context.run_id}",
        sources=uat_context.sources,
        question=uat_context.connect_query,
        trace_id=uat_context.run_id,
    )
    report = run_create_pass(request, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert report.activatable and report.draft_path and report.receipt_id, "Create did not produce one staged proposal"
    draft_path = (uat_context.vault_root / report.draft_path).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root), "Create draft escaped the TEST vault"
    frontmatter, draft_text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    assert frontmatter.get("kind") == "draft"
    assert frontmatter.get("derived_by") == "synthesis"
    assert frontmatter.get("authority_state") == "proposal"
    assert frontmatter.get("sources") == [source.object_id for source in uat_context.sources]
    cognition = _successful_cognition(frontmatter)
    acceptance_line = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    assert draft_text.count(acceptance_line) == 1, "Create did not write exactly one dedicated unchecked acceptance control"

    watcher_scan = _wait_for_post_draft_ingest_scan(
        watcher_binding=uat_context.watcher_binding,
        expected_vault_path=TEST_RUNTIME_VAULT_PATH,
        expected_outbox_path=TEST_RUNTIME_OUTBOX_PATH,
    )
    rows, generation = _wait_for_index_convergence(uat_context.sources, uat_context.vault_root)
    excluded = _draft_rows(rows, draft_path, draft_id, uat_context.vault_root)
    assert not excluded, "the staged draft is present in the exhaustive durable retrieval index"
    retrieval = retrieve(RetrievalRequest(query=uat_context.connect_query, k=100))
    assert all(
        not _source_ref_matches(hit.source_ref, draft_path, uat_context.vault_root)
        for hit in retrieval.hits
    ), "retrieval returned the staged draft"
    canonical_after = {
        path.relative_to(uat_context.vault_root).as_posix()
        for path in uat_context.vault_root.rglob("*.md")
        if "drafts" not in path.relative_to(uat_context.vault_root).parts
    }
    assert canonical_after == canonical_before, "Create wrote outside the staging directory"
    uat_context.record(
        draft_path=Path(report.draft_path).as_posix(),
        draft_id=draft_id,
        create_receipt_id=report.receipt_id,
        cognition={
            "outcome": cognition["outcome"],
            "degraded": cognition["degraded"],
            "degraded_reason": cognition.get("degraded_reason"),
            "claim_count": cognition.get("claims"),
            "inference_count": cognition.get("inferences"),
        },
        post_draft_watcher_scan={
            "status": "completed_healthy_ingest_scan",
            "runtime_binding": {
                "compose_project": TEST_COMPOSE_PROJECT,
                "services_verified": list(TEST_RUNTIME_SERVICES),
                "vault_bind_mount_verified": True,
                "shared_runtime_volume_verified": True,
                "runtime_volume": uat_context.watcher_binding.runtime_volume_name,
                "watcher_outbox": "runtime-tmp/index-outbox.jsonl",
            },
            "generation": watcher_scan.scan_generation,
            "errors_total": watcher_scan.errors_total,
        },
        index_convergence={
            "status": "stable_source_hashes_after_post_draft_watcher_scan",
            "generation": generation,
            "rows_scanned": len(rows),
        },
        draft_excluded_from_full_index=True,
        draft_excluded_from_retrieval=True,
        technical_phase="create_staged",
    )


def test_accept_rejects_unchecked_checkbox(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "create_staged", "run Connect and Create before acceptance checks"
    draft_path = (uat_context.vault_root / str(receipt["draft_path"])).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root)
    before_files = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md")}
    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    after_files = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md")}
    assert after_files == before_files, "unchecked acceptance wrote or removed a canonical artifact"
    assert draft_path.exists(), "unchecked draft must remain staged"
    uat_context.record(unchecked_acceptance="refused_without_write", technical_phase="pass", test_actor_action="pending")


def test_checked_checkbox_uses_only_governed_materialization_path(uat_context: UatContext) -> None:
    if not _enabled(TEST_ACTOR_ENV):
        pytest.skip(
            f"authorized synthetic actor phase; set {TEST_ACTOR_ENV}=1 only after current TEST "
            "qualification and the #4826 owner authorization are verified"
        )
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "pass", "synthetic action requires the prior complete technical PASS"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed after technical PASS"
    _assert_test_channel_preflight(uat_context.vault_root)
    _read_doctor(uat_context.vault_root)

    draft_path = (uat_context.vault_root / str(receipt["draft_path"])).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root)
    draft_id = str(receipt["draft_id"])
    text = draft_path.read_text(encoding="utf-8")
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_lower = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_upper = f"- [X] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1 and checked_lower not in text and checked_upper not in text, "the exact dedicated control is not in its one-time unchecked state"
    assert "test_actor_attempt" not in receipt, "an earlier action attempt is uncertain; reconcile it read-only and do not replay"

    uat_context.record(
        test_actor_attempt={
            "status": "started",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "checkbox_count": 1,
        }
    )
    draft_path.write_text(text.replace(unchecked, checked_lower, 1), encoding="utf-8")
    checked_text = draft_path.read_text(encoding="utf-8")
    assert checked_text.count(checked_lower) == 1 and unchecked not in checked_text
    uat_context.record(
        test_actor_attempt={
            "status": "checkbox_checked",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "checkbox_count": 1,
        }
    )

    result = accept_draft(draft_path, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert result.status == "accepted" and result.final_note_path and result.receipt_id
    final_path = (uat_context.vault_root / result.final_note_path).resolve()
    assert final_path.is_relative_to(uat_context.vault_root)
    final_frontmatter, final_body = load_frontmatter(final_path.read_text(encoding="utf-8"))
    assert final_frontmatter.get("sources") == [source.object_id for source in uat_context.sources]
    assert final_frontmatter.get("derived_by") == "synthesis"
    assert final_frontmatter.get("accepted_by") == "human"
    assert final_frontmatter.get("acceptance_receipt_id") == result.receipt_id
    assert not any("Accept this draft into the vault" in line for line in final_body.splitlines())
    uat_context.record(
        accepted={
            "status": "accepted",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "draft_path": Path(receipt["draft_path"]).as_posix(),
            "final_note_path": Path(result.final_note_path).as_posix(),
            "source_ids": [source.object_id for source in uat_context.sources],
            "acceptance_receipt_id": result.receipt_id,
            "derived_by": final_frontmatter["derived_by"],
            "accepted_by": final_frontmatter["accepted_by"],
        },
        disposition="synthetic_test_actor_acceptance_pass",
    )


@pytest.mark.parametrize(
    ("binding", "value", "message"),
    [
        ("PKM_ENVIRONMENT", None, "PKM_ENVIRONMENT must be explicitly test"),
        ("PKM_ENVIRONMENT", "development", "PKM_ENVIRONMENT must be explicitly test"),
        ("PKM_CHANNEL", None, "PKM_CHANNEL must be explicitly test"),
        ("PKM_CHANNEL", "prod", "PKM_CHANNEL must be explicitly test"),
        ("STORE_BACKEND", "memory", "TEST UAT requires the Postgres backend"),
    ],
)
def test_uat_context_rejects_non_test_bindings_before_channel_preflight(
    monkeypatch: pytest.MonkeyPatch, binding: str, value: str | None, message: str
) -> None:
    captured = {name: None for name in CHANNEL_ENV_KEYS}
    captured.update(
        {
            "PKM_ENVIRONMENT": "test",
            "PKM_CHANNEL": "test",
            "COMPOSE_PROJECT_NAME": TEST_COMPOSE_PROJECT,
            "STORE_BACKEND": "postgres",
            "DATABASE_URL": "postgresql://localhost/app_test",
        }
    )
    captured[binding] = value
    monkeypatch.setattr(sys.modules[__name__], "_CAPTURED_TEST_ENV", captured)
    monkeypatch.setenv(RUN_ENV, "1")

    def unexpected_preflight(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("channel preflight must not run for invalid TEST bindings")

    monkeypatch.setattr(sys.modules[__name__], "_assert_test_channel_preflight", unexpected_preflight)
    with pytest.raises(AssertionError, match=message):
        uat_context.__wrapped__(monkeypatch)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "degraded"},
        {"issues": [{"code": "identity_mismatch"}]},
        {"expected_identity": {"provider": "openai", "model": "wrong", "dim": 3, "normalize": False}},
        {"stored_identity": {"provider": "openai", "model": "wrong", "dim": 3, "normalize": False}},
        {"stored_identity": None},
    ],
)
def test_read_doctor_rejects_missing_or_mismatched_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    report: dict[str, Any] = {
        "status": "ok",
        "issues": [],
        "expected_identity": dict(EXPECTED_IDENTITY),
        "stored_identity": dict(EXPECTED_IDENTITY),
    }
    report.update(changes)
    result = subprocess.CompletedProcess(
        args=["app.cli", "index", "doctor"],
        returncode=0,
        stdout=json.dumps(report),
        stderr="",
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "_run_channel_command",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(AssertionError):
        _read_doctor(tmp_path)


def _watcher_heartbeat_payload() -> dict[str, Any]:
    return {
        "ts": 1000.0,
        "status": "healthy-idle",
        "paused": False,
        "vault_path": str(TEST_RUNTIME_VAULT_PATH),
        "outbox_path": str(TEST_RUNTIME_OUTBOX_PATH),
        "watchers": {
            "ingest": {
                "scan_generation": 4,
                "scan_in_progress": False,
                "errors_total": 2,
                "observation_status": "healthy-idle",
                "scope_status": "ok",
            }
        },
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(ts=900.0),
        lambda payload: payload.update(status="degraded"),
        lambda payload: payload.update(paused=True),
        lambda payload: payload["watchers"]["ingest"].update(observation_status="degraded"),
        lambda payload: payload["watchers"]["ingest"].update(scan_generation=True),
    ],
    ids=["stale", "degraded", "paused", "ingest-degraded", "malformed-watermark"],
)
def test_ingest_watcher_snapshot_fails_closed(
    tmp_path: Path, mutation: Any
) -> None:
    heartbeat_path = tmp_path / "watcher.json"
    payload = _watcher_heartbeat_payload()
    mutation(payload)
    heartbeat_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_ingest_watcher_snapshot(
        heartbeat_path,
        expected_vault_path=TEST_RUNTIME_VAULT_PATH,
        expected_outbox_path=TEST_RUNTIME_OUTBOX_PATH,
        now=1000.0,
    ) is None


def test_ingest_watcher_snapshot_rejects_malformed_json(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "watcher.json"
    heartbeat_path.write_text("{broken", encoding="utf-8")

    assert _read_ingest_watcher_snapshot(
        heartbeat_path,
        expected_vault_path=TEST_RUNTIME_VAULT_PATH,
        expected_outbox_path=TEST_RUNTIME_OUTBOX_PATH,
        now=1000.0,
    ) is None


def _runtime_container_inspect(service: str, vault_source: Path) -> list[dict[str, Any]]:
    return [
        {
            "Id": f"{service}-container-id",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": TEST_COMPOSE_PROJECT,
                    "com.docker.compose.service": service,
                },
                "Env": [
                    "PKM_ENVIRONMENT=test",
                    "VAULT_ROOT=/app/vault",
                    "VAULT_ROOT_TEST=/app/vault",
                    "DATABASE_URL=postgresql+psycopg://app:app@db:5432/app_test",
                    "DB_DSN=postgresql+psycopg://app:app@db:5432/app_test",
                    "INDEX_OUTBOX_PATH=/app/tmp-test/index-outbox.jsonl",
                    "WATCHER_HEARTBEAT_PATH=/app/tmp-test/watcher_heartbeat.json",
                    "WATCHER_ENABLE=1",
                    "WATCHER_VAULT_PATH=/app/vault",
                ],
            },
            "State": {"Status": "running", "Running": True},
            "HostConfig": {"ExtraHosts": None},
            "NetworkSettings": {
                "Networks": {
                    TEST_COMPOSE_NETWORK: {"NetworkID": TEST_COMPOSE_NETWORK_ID}
                }
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(vault_source),
                    "Destination": "/app/vault",
                    "RW": True,
                },
                {
                    "Type": "volume",
                    "Name": TEST_RUNTIME_VOLUME_NAME,
                    "Destination": "/app/tmp-test",
                    "RW": True,
                },
            ],
        }
    ]


def test_active_test_service_requires_actual_vault_bind_and_runtime_volume(tmp_path: Path) -> None:
    selected_vault = tmp_path / "selected-test-vault"
    selected_vault.mkdir()
    inspected = _runtime_container_inspect("watcher", selected_vault)

    assert _parse_test_runtime_service_inspect(
        inspected,
        service="watcher",
        selected_vault_path=selected_vault,
        expected_database_network_id=TEST_COMPOSE_NETWORK_ID,
    ) == ("watcher-container-id", TEST_RUNTIME_VOLUME_NAME)


def _database_service_inspect() -> list[dict[str, Any]]:
    return [
        {
            "Id": "db-container-id",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": TEST_COMPOSE_PROJECT,
                    "com.docker.compose.service": "db",
                },
                "Env": ["POSTGRES_DB=app_test"],
            },
            "State": {"Status": "running", "Running": True},
            "NetworkSettings": {
                "Networks": {
                    TEST_COMPOSE_NETWORK: {
                        "NetworkID": TEST_COMPOSE_NETWORK_ID,
                        "IPAddress": "172.30.0.2",
                        "Aliases": ["db", "pkm-test-db-1"],
                    }
                },
                "Ports": {
                    "5432/tcp": [
                        {"HostIp": "0.0.0.0", "HostPort": TEST_DB_HOST_PORT},
                        {"HostIp": "::", "HostPort": TEST_DB_HOST_PORT},
                    ]
                },
            },
        }
    ]


def test_active_test_database_is_bound_to_compose_default_network() -> None:
    database = _parse_test_database_service_inspect(_database_service_inspect())
    assert database == _TestDatabaseBinding(
        "db-container-id", TEST_COMPOSE_NETWORK_ID, "172.30.0.2", int(TEST_DB_HOST_PORT)
    )
    network = [
        {
            "Name": TEST_COMPOSE_NETWORK,
            "Id": TEST_COMPOSE_NETWORK_ID,
            "Labels": {
                "com.docker.compose.project": TEST_COMPOSE_PROJECT,
                "com.docker.compose.network": "default",
            },
        }
    ]
    assert _test_compose_default_network_matches(network, TEST_COMPOSE_NETWORK_ID)


def test_active_test_database_rejects_a_non_test_compose_network() -> None:
    inspected = _database_service_inspect()
    inspected[0]["NetworkSettings"]["Networks"][TEST_COMPOSE_NETWORK][
        "NetworkID"
    ] = "other-network-id"
    database = _parse_test_database_service_inspect(inspected)
    assert database is not None

    other_network = [
        {
            "Name": "other_default",
            "Id": database.network_id,
            "Labels": {
                "com.docker.compose.project": "other",
                "com.docker.compose.network": "default",
            },
        }
    ]
    assert not _test_compose_default_network_matches(other_network, database.network_id)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+psycopg://app:app@localhost:15434/app_test", True),
        ("postgresql+psycopg://app:app@127.0.0.1:15434/app_test", True),
        ("postgresql+psycopg://app:app@[::1]:15434/app_test", True),
        ("postgresql+psycopg://app:app@prod-db:15434/app_test", False),
        ("postgresql+psycopg://app:app@localhost:5432/app_test", False),
        (
            "postgresql+psycopg://app:app@prod-db:5432/app_test?application_name=:15434",
            False,
        ),
    ],
    ids=["localhost", "ipv4-loopback", "ipv6-loopback", "remote-host", "wrong-port", "port-text-is-not-binding"],
)
def test_host_test_database_binding_matches_loopback_and_published_port(
    url: str, expected: bool
) -> None:
    assert _is_isolated_test_database_binding(
        {"DATABASE_URL": url, "DB_DSN": url},
        require_both=False,
        expected_hosts=HOST_TEST_DATABASE_HOSTS,
        expected_port=int(TEST_DB_HOST_PORT),
    ) is expected


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, '["172.30.0.2"]\n', True),
        (0, '["172.30.0.3"]\n', False),
        (0, '["172.30.0.2", "172.30.0.3"]\n', False),
        (0, "not-json\n", False),
        (1, "", False),
    ],
    ids=["expected-db-address", "other-address", "ambiguous-dns", "malformed", "probe-failed"],
)
def test_test_database_dns_must_resolve_to_inspected_db(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args, returncode=returncode, stdout=stdout, stderr=""
        ),
    )
    assert _container_resolves_test_database_to_expected_address(
        "watcher-container-id", "172.30.0.2"
    ) is expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload[0]["Config"]["Env"].__setitem__(0, "POSTGRES_DB=app"),
        lambda payload: payload[0]["Config"]["Labels"].update(
            {"com.docker.compose.project": "pkm-prod"}
        ),
        lambda payload: payload[0]["NetworkSettings"]["Networks"][TEST_COMPOSE_NETWORK][
            "Aliases"
        ].remove("db"),
        lambda payload: payload[0]["NetworkSettings"]["Networks"].update(
            {"other": {"NetworkID": "other-network"}}
        ),
        lambda payload: payload[0]["NetworkSettings"]["Networks"][TEST_COMPOSE_NETWORK].update(
            IPAddress="not-an-ip"
        ),
        lambda payload: payload[0]["NetworkSettings"]["Ports"]["5432/tcp"][0].update(
            HostPort="15435"
        ),
        lambda payload: payload[0]["NetworkSettings"]["Ports"]["5432/tcp"][0].update(
            HostIp="192.0.2.15"
        ),
        lambda payload: payload[0]["NetworkSettings"].update(Ports={}),
    ],
    ids=[
        "wrong-database",
        "wrong-project",
        "missing-db-alias",
        "extra-network",
        "invalid-address",
        "wrong-published-port",
        "remote-published-address",
        "unpublished",
    ],
)
def test_active_test_database_rejects_mismatched_compose_or_network_binding(
    mutation: Any,
) -> None:
    inspected = _database_service_inspect()
    mutation(inspected)
    assert _parse_test_database_service_inspect(inspected) is None


def _set_inspected_environment(inspected: list[dict[str, Any]], key: str, value: str) -> None:
    environment = inspected[0]["Config"]["Env"]
    environment[:] = [entry for entry in environment if not entry.startswith(f"{key}=")]
    environment.append(f"{key}={value}")


def _set_inspected_database_endpoint_override(
    inspected: list[dict[str, Any]], query: str
) -> None:
    dsn = f"postgresql+psycopg://app:app@db:5432/app_test?{query}"
    _set_inspected_environment(inspected, "DATABASE_URL", dsn)
    _set_inspected_environment(inspected, "DB_DSN", dsn)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda inspected, other: inspected[0]["Mounts"][0].update(Source=str(other)),
        lambda inspected, _other: inspected[0]["Mounts"][1].update(Name="different_volume"),
        lambda inspected, _other: inspected[0]["Mounts"].append(
            {
                "Type": "bind",
                "Source": "/tmp/shadow-heartbeat",
                "Destination": "/app/tmp-test/watcher_heartbeat.json",
                "RW": True,
            }
        ),
        lambda inspected, _other: inspected[0]["Mounts"].append(
            {
                "Type": "bind",
                "Source": "/tmp/shadow-outbox",
                "Destination": "/app/tmp-test/index-outbox.jsonl",
                "RW": True,
            }
        ),
        lambda inspected, _other: _set_inspected_environment(
            inspected, "DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app"
        ),
        lambda inspected, _other: _set_inspected_environment(
            inspected, "DATABASE_URL", "postgresql+psycopg://app:app@prod-db:5432/app_test"
        ),
        lambda inspected, _other: _set_inspected_environment(
            inspected, "DB_DSN", "postgresql+psycopg://app:app@db:5432/app_dev"
        ),
        lambda inspected, _other: _set_inspected_database_endpoint_override(
            inspected, "hostaddr=192.0.2.15"
        ),
        lambda inspected, _other: _set_inspected_database_endpoint_override(
            inspected, "service=prod"
        ),
        lambda inspected, _other: _set_inspected_database_endpoint_override(
            inspected, "servicefile=%2Fetc%2Fpostgresql%2Fpg_service.conf"
        ),
        lambda inspected, _other: _set_inspected_database_endpoint_override(
            inspected, "host=prod-db"
        ),
        lambda inspected, _other: _set_inspected_database_endpoint_override(
            inspected, "target_session_attrs=read-write"
        ),
        lambda inspected, _other: inspected[0]["Config"]["Env"].remove("INDEX_OUTBOX_PATH=/app/tmp-test/index-outbox.jsonl"),
        lambda inspected, _other: inspected[0]["HostConfig"].update(
            ExtraHosts=["db:192.0.2.15"]
        ),
        lambda inspected, _other: inspected[0]["NetworkSettings"]["Networks"][
            TEST_COMPOSE_NETWORK
        ].update(NetworkID="other-network"),
        lambda inspected, _other: inspected[0]["NetworkSettings"]["Networks"].update(
            {"other": {"NetworkID": "other-network"}}
        ),
        lambda inspected, _other: inspected[0]["State"].update(Status="exited", Running=False),
        lambda inspected, _other: inspected[0]["Config"]["Labels"].update(
            {"com.docker.compose.project": "pkm-prod"}
        ),
    ],
    ids=[
        "wrong-vault-source",
        "different-runtime-volume",
        "shadowed-heartbeat",
        "shadowed-outbox",
        "production-database-url",
        "wrong-database-host",
        "mismatched-database-dsn",
        "hostaddr-endpoint-override",
        "service-endpoint-override",
        "servicefile-endpoint-override",
        "query-host-endpoint-override",
        "multi-host-selection-override",
        "wrong-outbox-config",
        "db-extra-host-override",
        "wrong-db-network",
        "extra-runtime-network",
        "stopped",
        "wrong-project",
    ],
)
def test_active_test_service_rejects_mismatched_mounts_or_runtime(
    tmp_path: Path, mutation: Any
) -> None:
    selected_vault = tmp_path / "selected-test-vault"
    selected_vault.mkdir()
    inspected = _runtime_container_inspect("watcher", selected_vault)
    other_vault = tmp_path / "other-vault"
    other_vault.mkdir()
    mutation(inspected, other_vault)

    assert _parse_test_runtime_service_inspect(
        inspected,
        service="watcher",
        selected_vault_path=selected_vault,
        expected_database_network_id=TEST_COMPOSE_NETWORK_ID,
    ) is None


def test_runtime_volume_must_belong_to_test_compose_project() -> None:
    volume = [
        {
            "Name": "pkm-test_runtime-tmp",
            "Driver": "local",
            "Scope": "local",
            "Options": None,
            "Mountpoint": "/var/lib/docker/volumes/pkm-test_runtime-tmp/_data",
            "Labels": {
                "com.docker.compose.project": "pkm-test",
                "com.docker.compose.volume": "runtime-tmp",
            },
        }
    ]
    assert _test_runtime_volume_matches(volume, TEST_RUNTIME_VOLUME_NAME)
    assert _test_runtime_volume_mountpoint(volume, TEST_RUNTIME_VOLUME_NAME) == Path(
        "/var/lib/docker/volumes/pkm-test_runtime-tmp/_data"
    ).resolve(strict=False)
    volume[0]["Labels"]["com.docker.compose.project"] = "pkm-prod"
    assert not _test_runtime_volume_matches(volume, TEST_RUNTIME_VOLUME_NAME)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Driver", "nfs"),
        ("Scope", "global"),
        ("Options", {"type": "none", "o": "bind", "device": "/checkout/tmp-test"}),
    ],
    ids=["non-local-driver", "non-local-scope", "bind-to-checkout-options"],
)
def test_runtime_volume_rejects_nonlocal_or_bind_backed_configuration(
    field: str, value: object
) -> None:
    volume = [
        {
            "Name": TEST_RUNTIME_VOLUME_NAME,
            "Driver": "local",
            "Scope": "local",
            "Options": None,
            "Mountpoint": "/var/lib/docker/volumes/pkm-test_runtime-tmp/_data",
            "Labels": {
                "com.docker.compose.project": TEST_COMPOSE_PROJECT,
                "com.docker.compose.volume": "runtime-tmp",
            },
        }
    ]
    volume[0][field] = value
    assert _test_runtime_volume_mountpoint(volume, TEST_RUNTIME_VOLUME_NAME) is None


def test_host_action_outbox_is_bound_to_checkout_and_separate_from_runtime_volume(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "checkout"
    host_tmp_test = repo_root / "tmp-test"
    host_tmp_test.mkdir(parents=True)
    volume_root = tmp_path / "docker-runtime-tmp"
    volume_root.mkdir()
    outbox_path = host_tmp_test / "index-outbox.jsonl"
    binding = _TestWatcherBinding("watcher-id", "pkm-test_runtime-tmp", volume_root)

    _assert_host_outbox_separate_from_runtime_volume(
        outbox_path,
        binding,
        repo_root=repo_root,
    )

    wrong_checkout_outbox = tmp_path / "another-checkout" / "tmp-test" / "index-outbox.jsonl"
    with pytest.raises(AssertionError, match="this checkout's tmp-test"):
        _assert_host_outbox_separate_from_runtime_volume(
            wrong_checkout_outbox,
            binding,
            repo_root=repo_root,
        )

    aliased_binding = _TestWatcherBinding(
        "watcher-id", "pkm-test_runtime-tmp", host_tmp_test
    )
    with pytest.raises(AssertionError, match="inside the TEST runtime-tmp"):
        _assert_host_outbox_separate_from_runtime_volume(
            outbox_path,
            aliased_binding,
            repo_root=repo_root,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vault_path", "/app/other-vault"),
        ("outbox_path", "/app/tmp/index-outbox.jsonl"),
        ("vault_path", None),
        ("outbox_path", "relative/index-outbox.jsonl"),
    ],
    ids=["wrong-vault", "wrong-outbox", "missing-vault", "relative-outbox"],
)
def test_ingest_watcher_snapshot_rejects_wrong_runtime_binding(
    tmp_path: Path, field: str, value: str | None
) -> None:
    heartbeat_path = tmp_path / "watcher.json"
    payload = _watcher_heartbeat_payload()
    payload[field] = value
    heartbeat_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_ingest_watcher_snapshot(
        heartbeat_path,
        expected_vault_path=TEST_RUNTIME_VAULT_PATH,
        expected_outbox_path=TEST_RUNTIME_OUTBOX_PATH,
        now=1000.0,
    ) is None


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (_IngestWatcherSnapshot(1001.0, 5, False, "healthy-idle", 2), True),
        (_IngestWatcherSnapshot(1000.0, 5, False, "healthy-idle", 2), False),
        (_IngestWatcherSnapshot(1001.0, 4, False, "healthy-idle", 2), False),
        (_IngestWatcherSnapshot(1001.0, 5, True, "catch-up", 2), False),
        (_IngestWatcherSnapshot(1001.0, 5, False, "healthy-idle", 3), False),
    ],
    ids=["later-completed-scan", "heartbeat-not-newer", "generation-not-newer", "still-running", "new-errors"],
)
def test_post_draft_scan_requires_a_new_clean_completed_generation(
    current: _IngestWatcherSnapshot, expected: bool
) -> None:
    baseline = _IngestWatcherSnapshot(1000.0, 4, False, "healthy-idle", 2)

    assert _is_completed_post_draft_scan(baseline, current) is expected


def test_runbook_documents_required_test_channel_guards() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runbook_path = repo_root / "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md"
    assert runbook_path.is_file()
    runbook = runbook_path.read_text(encoding="utf-8")
    for required in (
        "#issuecomment-6107736254",
        "#3320 tracks a separate TEST recovery/security decision and does not authorize this Expansion actor",
        "channel-preflight",
        "COMPOSE_PROJECT_NAME=pkm-test",
        "read-only inspects the already-running",
        "this checkout's `tmp-test/index-outbox.jsonl`",
        "rejects aliases into the inspected Docker volume mountpoint",
        "host action/audit outbox and watcher outbox are separate storage locations",
        "docker exec",
        "index doctor --strict --json",
        "index convergence",
        "completed `ingest` scan generation newer than the post-Create watermark",
        "post_draft_watcher_scan",
        "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR=1",
        "synthetic test actor",
        "expansion-connect-create-accept-test-channel.v1",
        "It never provisions, deploys, starts, restarts, re-indexes, repairs, or reconfigures a channel.",
        "effective reasoning route",
        "reflection-journal.md",
        "summary-request.md",
        "unscoped",
        "retrieval_k=2",
        "outcome: success",
    ):
        assert required in runbook
    assert "-k 'not checked_checkbox'" not in runbook
    assert "python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py\n```" in runbook
    docs_index = (repo_root / "docs/DOCS_INDEX.md").read_text(encoding="utf-8")
    assert "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md" in docs_index


@pytest.mark.parametrize("backend", ["openai", "unexpected", "mock", "golden"])
def test_no_mock_route_rejects_non_runtime_reasoning_backends(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    monkeypatch.setenv("REASONING_PROVIDER", backend)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(AssertionError, match="supported live reasoning backend"):
        _assert_no_mock_reasoning_route()


def test_no_mock_route_rejects_reasoning_provider_mock_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    with pytest.raises(AssertionError, match="mock-agent fallback"):
        _assert_no_mock_reasoning_route()


@pytest.mark.parametrize(
    "cognition",
    [
        {"outcome": "provider_failure", "degraded": True, "degraded_reason": "provider_failure"},
        {"outcome": "missing_input", "degraded": True, "degraded_reason": "missing_input"},
        {"outcome": "empty_output", "degraded": True, "degraded_reason": "empty_provider_output"},
    ],
)
def test_successful_cognition_gate_rejects_degraded_create(cognition: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="did not complete successfully"):
        _successful_cognition({"proposed_by": {"cognition": cognition}})


def test_successful_cognition_gate_rejects_inconsistent_degraded_flag() -> None:
    cognition = {"outcome": "success", "degraded": True, "degraded_reason": "provider_failure"}
    with pytest.raises(AssertionError, match="degraded to deterministic collation"):
        _successful_cognition({"proposed_by": {"cognition": cognition}})


def test_successful_cognition_gate_accepts_only_success_receipt() -> None:
    cognition = {"outcome": "success", "degraded": False, "degraded_reason": None, "claims": 2}
    assert _successful_cognition({"proposed_by": {"cognition": cognition}}) is cognition


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [(("work", "work"), "work"), (("", ""), "unscoped")],
)
def test_selected_sources_must_share_one_scope(scopes: tuple[str, str], expected: str) -> None:
    assert _shared_source_scope(scopes) == expected


@pytest.mark.parametrize("scopes", [("work", "personal"), ("work", "")])
def test_selected_sources_reject_mixed_scopes(scopes: tuple[str, str]) -> None:
    with pytest.raises(AssertionError, match="share one scope"):
        _shared_source_scope(scopes)
