#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _line(label: str, value: str) -> str:
    return f"- {label}: {value}"


def _check_cmd(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        return False, "not found"
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or "error").strip()
    output = (result.stdout or result.stderr or "").strip()
    return True, output.splitlines()[0] if output else "ok"


def _vault_status(vault_root: str | None) -> str:
    if not vault_root:
        return "missing (set VAULT_ROOT)"
    path = Path(vault_root).expanduser()
    if not path.exists():
        return f"missing ({path})"
    if not path.is_dir():
        return f"not a directory ({path})"
    readable = os.access(path, os.R_OK)
    writable = os.access(path, os.W_OK)
    return f"ok ({path}) readable={readable} writable={writable}"


def _port_in_use(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _fetch_json(url: str, timeout: float = 2.0) -> tuple[bool, dict[str, Any] | None, str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, None, f"http {exc.code}"
    except Exception as exc:
        return False, None, str(exc)
    try:
        payload = json.loads(raw) if raw else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return False, None, "non-json"
    return True, payload, "ok"


def _failed_required_checks(health: dict[str, Any]) -> list[str]:
    checks = health.get("checks") or {}
    failed = []
    if isinstance(checks, dict):
        for name, payload in checks.items():
            if not isinstance(payload, dict):
                continue
            if payload.get("required") and payload.get("ok") is False:
                failed.append(name)
    return failed


def _ollama_route_selected(health: dict[str, Any]) -> bool:
    routes = health.get("checks", {}).get("llm_router", {}).get("selected_defaults", {})
    if not isinstance(routes, dict):
        return False
    for route in routes.values():
        if isinstance(route, dict) and (route.get("provider") or "").lower() == "ollama":
            return True
    return False


def _ollama_base_url(health: dict[str, Any] | None) -> str:
    if health:
        base = health.get("checks", {}).get("ollama", {}).get("base_url")
        if isinstance(base, str) and base.strip():
            return base.rstrip("/")
    return os.getenv("OLLAMA_URL", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")


def _check_ollama(base_url: str) -> tuple[bool, str]:
    url = f"{base_url}/api/tags"
    ok, _, detail = _fetch_json(url, timeout=2.0)
    if ok:
        return True, f"reachable ({base_url})"
    return False, f"unreachable ({base_url}): {detail}"


def main() -> int:
    lines = ["Alpha doctor"]

    docker_ok, docker_detail = _check_cmd(["docker", "--version"])
    lines.append(_line("docker", "ok" if docker_ok else f"missing ({docker_detail})"))

    compose_ok, compose_detail = _check_cmd(["docker", "compose", "version"])
    lines.append(_line("docker compose", "ok" if compose_ok else f"missing ({compose_detail})"))

    vault_root = os.getenv("VAULT_ROOT")
    lines.append(_line("vault", _vault_status(vault_root)))

    for port in (18000, 15432):
        in_use = _port_in_use(port)
        state = "in_use" if in_use else "free"
        lines.append(_line(f"port {port}", state))

    api_base = (os.getenv("API_BASE_URL") or "http://127.0.0.1:18000").rstrip("/")
    health_ok, health_payload, health_detail = _fetch_json(f"{api_base}/api/health")
    if health_ok and health_payload:
        required_ok = health_payload.get("required_ok")
        failed_required = _failed_required_checks(health_payload)
        failed_text = ",".join(failed_required[:3]) if failed_required else "none"
        lines.append(_line("api health", f"required_ok={required_ok} failed_required={failed_text}"))
    else:
        lines.append(_line("api health", f"unreachable ({health_detail})"))

    ollama_needed = False
    if health_payload and _ollama_route_selected(health_payload):
        ollama_needed = True
    else:
        env_provider = (os.getenv("LLM_FORCE_PROVIDER") or os.getenv("LLM_PROVIDER") or "").lower()
        if env_provider in {"ollama", "llm"}:
            ollama_needed = True

    if ollama_needed:
        base_url = _ollama_base_url(health_payload)
        ok, detail = _check_ollama(base_url)
        lines.append(_line("ollama", "ok" if ok else detail))
    else:
        lines.append(_line("ollama", "skipped"))

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
