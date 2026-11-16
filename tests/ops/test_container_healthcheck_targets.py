"""Guard compose healthchecks away from the expensive operator diagnostic route."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
_PROD_OLLAMA_BASE_URL = "http://ollama:11434"


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_unknown_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("", _construct_unknown_tag)


def _committed_compose_paths() -> list[Path]:
    """Return every tracked compose file, including nested YAML variants."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPO_ROOT / relative_path
        for relative_path in completed.stdout.decode().split("\0")
        if relative_path
        and Path(relative_path).suffix in {".yml", ".yaml"}
        and "compose" in Path(relative_path).name.lower()
    ]


def test_no_container_healthcheck_targets_api_health() -> None:
    compose_paths = _committed_compose_paths()
    assert compose_paths, "expected at least one committed Compose file"
    for compose_path in compose_paths:
        compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
        for service_name, service in (compose.get("services") or {}).items():
            healthcheck = service.get("healthcheck") or {}
            command = healthcheck.get("test")
            if command is None:
                continue
            rendered = " ".join(command) if isinstance(command, list) else str(command)
            assert "/api/health" not in rendered.lower(), (
                f"{compose_path.name}:{service_name} healthcheck must use /healthz or /readyz, "
                "not /api/health"
            )


def test_prod_api_and_worker_use_the_internal_ollama_service() -> None:
    """Prod must start and address its Compose-local Ollama provider (#3462)."""
    prod_compose = yaml.load(
        (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"),
        Loader=_ComposeLoader,
    ) or {}
    services = prod_compose.get("services") or {}

    ollama = services.get("ollama") or {}
    assert ollama.get("ports") == [], "prod must not publish Ollama's host port"

    for service_name in ("api", "worker"):
        service = services.get(service_name) or {}
        environment = service.get("environment") or {}
        assert environment.get("OLLAMA_BASE_URL") == _PROD_OLLAMA_BASE_URL
        assert "host.docker.internal" not in environment["OLLAMA_BASE_URL"]
        assert (service.get("depends_on") or {}).get("ollama") == {"condition": "service_healthy"}


def _effective_compose(channel: str | None) -> dict:
    compose_files = [REPO_ROOT / "docker-compose.yaml"]
    if channel is not None:
        compose_files.append(REPO_ROOT / f"docker-compose.{channel}.yml")
    arguments = [
        "docker",
        "compose",
        "--env-file",
        str(REPO_ROOT / "config" / "deploy" / f"{channel or 'dev'}.env"),
    ]
    for compose_file in compose_files:
        arguments.extend(("-f", str(compose_file)))
    arguments.extend(
        (
            "--profile",
            "*",
            "config",
            "--format",
            "json",
            "--no-env-resolution",
            "--no-interpolate",
        )
    )
    result = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _companion_healthcheck(channel: str) -> dict:
    return _effective_compose(channel)["services"]["companion-ui"]["healthcheck"]


def _run_effective_probe(
    healthcheck: dict,
    *,
    response_status: int = 200,
    response_delay: float = 0.0,
) -> subprocess.CompletedProcess[str]:
    command = healthcheck["test"]
    assert command[0] == "CMD-SHELL"

    class _ProbeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
            time.sleep(response_delay)
            self.send_response(response_status)
            self.end_headers()
            try:
                self.wfile.write(b"probe")
            except BrokenPipeError:
                pass

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = os.environ.copy()
    environment.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "PORT": str(server.server_address[1]),
        }
    )
    try:
        return subprocess.run(
            ["bash", "-c", command[1]],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=8,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_nonprod_ui_probe_admits_bounded_slow_readiness() -> None:
    """The effective DEV/TEST probe admits readiness slower than the old 2s cutoff."""
    for channel in ("dev", "test"):
        healthcheck = _companion_healthcheck(channel)
        command = healthcheck["test"]
        assert command[0] == "CMD-SHELL"
        assert "127.0.0.1:{port}/healthz" in command[1]
        assert "timeout=5" in command[1]
        assert healthcheck["timeout"] == "7s"
        assert _run_effective_probe(healthcheck, response_delay=2.25).returncode == 0


def test_nonprod_ui_probe_preserves_bounded_failure() -> None:
    """HTTP failures and responses past the finite request budget remain unhealthy."""
    for channel in ("dev", "test"):
        healthcheck = _companion_healthcheck(channel)
        assert _run_effective_probe(healthcheck, response_status=503).returncode != 0
        assert _run_effective_probe(healthcheck, response_delay=5.3).returncode != 0


def test_nonprod_ui_probe_budget_preserves_prod() -> None:
    """Only non-production overlays change the outer UI probe budget."""
    base_healthcheck = _effective_compose(None)["services"]["companion-ui"]["healthcheck"]
    prod_healthcheck = _effective_compose("prod")["services"]["companion-ui"]["healthcheck"]
    assert prod_healthcheck == base_healthcheck
    assert base_healthcheck["timeout"] == "3s"
    assert "timeout=2" in base_healthcheck["test"][1]

    for channel, port in (("dev", "8111"), ("test", "8112")):
        service = _effective_compose(channel)["services"]["companion-ui"]
        healthcheck = service["healthcheck"]
        assert healthcheck["interval"] == base_healthcheck["interval"]
        assert healthcheck["retries"] == base_healthcheck["retries"]
        environment = dict(item.split("=", 1) for item in service["environment"])
        assert environment["PORT"] == port
        assert environment["COMPANION_API_TIMEOUT_SECONDS"] == "30.0"
        assert environment["COMPANION_CAPTURE_TIMEOUT_SECONDS"] == (
            "${COMPANION_CAPTURE_TIMEOUT_SECONDS:-120.0}"
        )
