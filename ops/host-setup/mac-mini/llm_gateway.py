#!/usr/bin/env python3
"""Yggdrasil llm-gateway — a tiny gaming-aware Ollama reverse proxy.

Presents ONE Ollama-compatible endpoint to the Yggdrasil runtime and routes:

  * embeddings  -> ALWAYS the local mini Ollama (preserve embedding identity;
                   see docs/LLM_ROUTING.md "Embedding identity protection")
  * chat / gen  -> the gaming PC when its gpu-warden reports the GPU is free,
                   otherwise the local mini model (graceful degrade)
  * everything else (tags/show/pull/ps/...) -> the local mini Ollama

There is no auth here on purpose: bind it to 127.0.0.1 and reach the gaming PC
over Tailscale only. Point Yggdrasil at it with:  OLLAMA_URL=http://127.0.0.1:11500

Env (set by run_gateway.sh from config.env):
  GATEWAY_MINI_URL     default http://127.0.0.1:11434
  GATEWAY_GAMING_URL   e.g.    http://gaming-pc:11434  (empty -> always local)
  GATEWAY_WARDEN_URL   e.g.    http://gaming-pc:9090   (empty -> trust gaming box)
  GATEWAY_PORT         default 11500
"""
from __future__ import annotations

import os
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

MINI = os.environ.get("GATEWAY_MINI_URL", "http://127.0.0.1:11434").rstrip("/")
GAMING = os.environ.get("GATEWAY_GAMING_URL", "").rstrip("/")
WARDEN = os.environ.get("GATEWAY_WARDEN_URL", "").rstrip("/")
WARDEN_TTL = float(os.environ.get("GATEWAY_WARDEN_TTL", "5"))
CONNECT_TIMEOUT = float(os.environ.get("GATEWAY_CONNECT_TIMEOUT", "2"))

EMBED_PATHS = ("/api/embeddings", "/api/embed", "/v1/embeddings")
CHAT_PATHS = ("/api/chat", "/api/generate", "/v1/chat/completions")

app = FastAPI(title="yggdrasil-llm-gateway")
# No global read timeout: model generation can be slow. Only bound the connect.
_client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=CONNECT_TIMEOUT))
_warden = {"ts": 0.0, "available": False}


async def gaming_available() -> bool:
    """Is the gaming GPU free right now? Cached for WARDEN_TTL seconds."""
    if not GAMING:
        return False
    if not WARDEN:
        return True  # no warden configured -> trust the box if it answers
    now = time.monotonic()
    if now - _warden["ts"] < WARDEN_TTL:
        return _warden["available"]
    available = False
    try:
        r = await _client.get(f"{WARDEN}/status", timeout=CONNECT_TIMEOUT)
        available = bool(r.json().get("available", False))
    except Exception:
        available = False  # warden down / unreachable -> stay local
    _warden.update(ts=now, available=available)
    return available


def upstream_for(path: str, gaming_ok: bool) -> str:
    if path.startswith(EMBED_PATHS):
        return MINI  # identity pin — embeddings never leave the mini
    if path.startswith(CHAT_PATHS) and gaming_ok:
        return GAMING
    return MINI


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "mini": MINI,
        "gaming": GAMING or None,
        "warden": WARDEN or None,
        "gaming_available": await gaming_available(),
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
async def proxy(path: str, request: Request):
    full = "/" + path
    is_chat = full.startswith(CHAT_PATHS)
    gaming_ok = await gaming_available() if is_chat else False
    upstream = upstream_for(full, gaming_ok)
    body = await request.body()
    fwd_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    async def send(base: str):
        req = _client.build_request(
            request.method,
            f"{base}{full}",
            content=body,
            headers=fwd_headers,
            params=request.query_params,
        )
        return await _client.send(req, stream=True)

    try:
        resp = await send(upstream)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError):
        if upstream != MINI:
            try:
                resp = await send(MINI)  # gaming box vanished mid-flight -> degrade
            except Exception:
                return JSONResponse({"error": "no ollama upstream reachable"}, 502)
        else:
            return JSONResponse({"error": "mini ollama unreachable"}, 502)

    hop = ("content-length", "transfer-encoding", "content-encoding")
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers={k: v for k, v in resp.headers.items() if k.lower() not in hop},
        background=BackgroundTask(resp.aclose),
    )
