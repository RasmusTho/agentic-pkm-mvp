from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

from companion_ui.workspace.serve_dev_page import is_explicit_loopback_host
from companion_ui.workspace.serve_production_page import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = REPO_ROOT / "scripts" / "prod_devui_gateway_preflight.py"


def test_devui_gateway_requires_explicit_loopback_host_publish(monkeypatch) -> None:
    compose = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8113:8113"' in compose
    assert "COMPANION_UI_BIND_HOST: 127.0.0.1" in compose
    assert "${COMPANION_UI_BIND_HOST" not in compose

    def resolve_declared_host(host: str, *_args: object, **_kwargs: object) -> list[tuple]:
        if host == "loopback.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        if host == "nonloopback.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.44", 0))]
        raise socket.gaierror(host)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_declared_host)
    monkeypatch.setenv("HOST", "0.0.0.0")

    cases = (
        (None, False),
        ("", False),
        ("0.0.0.0", False),
        ("*", False),
        ("192.168.1.10", False),
        ("172.18.0.1", False),
        ("100.64.0.10", False),
        ("nonloopback.example", False),
        ("unresolvable.example", False),
        ("127.0.0.1", True),
        ("::1", True),
        ("loopback.example", True),
    )

    for declared_host, expected_enabled in cases:
        if declared_host is None:
            monkeypatch.delenv("COMPANION_UI_BIND_HOST", raising=False)
        else:
            monkeypatch.setenv("COMPANION_UI_BIND_HOST", declared_host)

        config = load_config()

        assert config["host"] == "0.0.0.0"
        assert config["devui_external_bind_host"] == (declared_host or "")
        assert (
            is_explicit_loopback_host(config["devui_external_bind_host"])
            is expected_enabled
        )


def test_prod_deploy_preflight_rejects_missing_wildcard_or_ambient_bind(
    tmp_path: Path,
) -> None:
    canonical = subprocess.run(
        [sys.executable, str(PREFLIGHT), str(REPO_ROOT / "docker-compose.prod.yml")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert canonical.returncode == 0, canonical.stdout + canonical.stderr
    assert canonical.stdout.strip() == "prod devUI gateway preflight: ok"

    unsafe_variants = (
        "ports:\n  - \"127.0.0.1:8113:8113\"\nenvironment: {}\n",
        "ports:\n  - \"127.0.0.1:8113:8113\"\nenvironment:\n  COMPANION_UI_BIND_HOST: 0.0.0.0\n",
        "ports:\n  - \"${COMPANION_UI_BIND_HOST:-127.0.0.1}:8113:8113\"\nenvironment:\n  COMPANION_UI_BIND_HOST: ${COMPANION_UI_BIND_HOST:-}\n",
    )
    for index, content in enumerate(unsafe_variants):
        compose_file = tmp_path / f"unsafe-{index}.yml"
        compose_file.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(PREFLIGHT), str(compose_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 78
        assert "prod devUI gateway preflight: blocked" in result.stderr

    deploy_script = (REPO_ROOT / "scripts" / "deploy_channel.sh").read_text(
        encoding="utf-8"
    )
    assert "prod_devui_gateway_preflight.py" in deploy_script
