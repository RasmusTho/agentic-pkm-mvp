from __future__ import annotations

import socket
from pathlib import Path

from companion_ui.workspace.serve_dev_page import is_explicit_loopback_host
from companion_ui.workspace.serve_production_page import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_devui_gateway_requires_explicit_loopback_host_publish(monkeypatch) -> None:
    compose = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert '"${COMPANION_UI_BIND_HOST:-127.0.0.1}:8113:8113"' in compose
    assert "COMPANION_UI_BIND_HOST: ${COMPANION_UI_BIND_HOST:-}" in compose

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
