from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Dict, Optional

import click

LLM_CHECK_TIMEOUT = 5


def _dump(data: Dict[str, object], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _resolve_endpoint() -> tuple[Optional[str], Optional[str]]:
    base = os.getenv("OLLAMA_URL")
    if base:
        return base.rstrip("/"), "ollama"
    fallback = os.getenv("OPENAI_BASE_URL")
    if fallback:
        return fallback.rstrip("/"), "openai_compat"
    return None, None


def _ping_endpoint(base: str, provider: str) -> tuple[bool, Optional[str], int, str]:
    path = "/api/tags" if provider == "ollama" else "/models"
    url = f"{base}{path}"
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=LLM_CHECK_TIMEOUT) as response:
            response.read(1)
        latency = int((time.perf_counter() - start) * 1000)
        return True, None, latency, url
    except Exception as exc:
        latency = int((time.perf_counter() - start) * 1000)
        return False, str(exc), latency, url


def run_llm_check() -> Dict[str, object]:
    base, provider = _resolve_endpoint()
    payload: Dict[str, object] = {
        "ok": False,
        "url": base or "",
        "provider": provider,
        "error": None,
        "latency_ms": 0,
    }
    if not base or not provider:
        payload["error"] = "OLLAMA_URL or OPENAI_BASE_URL must be configured"
        return payload

    ok, error, latency, url = _ping_endpoint(base, provider)
    payload["ok"] = ok
    payload["error"] = error
    payload["url"] = url
    payload["latency_ms"] = latency
    return payload


@click.group(help="LLM diagnostics and reachability checks.")
def llm() -> None:
    pass


@llm.command(name="check", help="Check that the configured LLM/embedding endpoint is reachable.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON output.")
@click.option("--strict", "strict", is_flag=True, default=False, help="Exit non-zero when the LLM endpoint is unreachable.")
def check(as_json: bool, strict: bool) -> None:
    result = run_llm_check()
    _dump(result, as_json)
    if strict and not result.get("ok"):
        raise SystemExit(2)
