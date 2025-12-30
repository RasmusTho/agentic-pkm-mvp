#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable, Tuple

FetchResult = Tuple[int | None, dict | None, str | None]
FetchFunc = Callable[[str], FetchResult]


def _fetch_json(url: str, timeout: float = 3.0) -> FetchResult:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return exc.code, None, raw or None
    except Exception as exc:
        return None, None, str(exc)

    try:
        payload = json.loads(raw) if raw else None
    except Exception:
        payload = None
    return status, payload, None


def _get(obj: dict | None, *keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _line(label: str, value: str) -> str:
    return f"- {label}: {value}"


def _format_store_line(stores: list[dict]) -> str:
    if not stores:
        return "entries=0 objects=0 external=0, vault=0"
    total_objects = 0
    per_plane: dict[str, int] = {}
    for entry in stores:
        name = str(entry.get("name") or "(missing)")
        count = entry.get("object_count")
        if isinstance(count, int):
            total_objects += count
            per_plane[name] = per_plane.get(name, 0) + count
    external = per_plane.get("external", 0)
    vault = per_plane.get("vault", 0)
    return f"entries={len(stores)} objects={total_objects} external={external}, vault={vault}"


def render_status(fetch_json: FetchFunc, *, api_base_url: str) -> str:
    base_url = api_base_url.rstrip("/")
    lines: list[str] = ["Alpha status"]

    status_code, status_payload, status_err = fetch_json(f"{base_url}/api/status")
    if status_code is None:
        lines.append(_line("api", f"ERROR ({status_err})"))
        status_payload = None
    else:
        lines.append(_line("api", f"OK ({status_code})"))

    health_code, health_payload, health_err = fetch_json(f"{base_url}/api/health")
    if health_code is None:
        lines.append(_line("health", f"ERROR ({health_err})"))
        health_payload = None
    elif health_payload is None:
        lines.append(_line("health", f"non-JSON ({health_code})"))
    else:
        ok = _get(health_payload, "ok", default="(missing)")
        db_ok = _get(health_payload, "runtime", "db", "ok", default="(missing)")
        lines.append(_line("health", f"ok={ok} db_ok={db_ok}"))

        watcher = _get(health_payload, "runtime", "watcher", default={})
        watcher_status = _get(watcher, "status", default="(missing)")
        watcher_fresh = _get(watcher, "freshness_seconds", default="(missing)")
        watcher_paused = _get(watcher, "paused", default="(missing)")
        lines.append(
            _line(
                "watcher",
                f"status={watcher_status} freshness_s={watcher_fresh} paused={watcher_paused}",
            )
        )

        worker = _get(health_payload, "runtime", "worker", default={})
        worker_status = _get(worker, "status", default="(missing)")
        worker_fresh = _get(worker, "freshness_seconds", default="(missing)")
        worker_processed = _get(worker, "processed_total", default="(missing)")
        lines.append(
            _line(
                "worker",
                f"status={worker_status} freshness_s={worker_fresh} processed_total={worker_processed}",
            )
        )

        ffmpeg = _get(health_payload, "checks", "ffmpeg", default={})
        ffmpeg_ok = _get(ffmpeg, "ok", default=True)
        ffmpeg_detail = _get(ffmpeg, "detail", default="")
        if ffmpeg_ok is False:
            detail = f" ({ffmpeg_detail})" if ffmpeg_detail else ""
            lines.append(_line("optional", f"tool missing: ffmpeg{detail}"))

    if not isinstance(health_payload, dict):
        lines.append(_line("watcher", "status=(missing) freshness_s=(missing) paused=(missing)"))
        lines.append(_line("worker", "status=(missing) freshness_s=(missing) processed_total=(missing)"))

    if isinstance(status_payload, dict):
        sot_version = _get(status_payload, "sot_version", default="(missing)")
        sot_label = _get(status_payload, "sot_label", default="(missing)")
        lines.append(_line("sot", f"version={sot_version} label={sot_label}"))

        stores_list = status_payload.get("stores")
        if isinstance(stores_list, list):
            lines.append(_line("stores", _format_store_line(stores_list)))
        else:
            lines.append(_line("stores", "(missing)"))

        ingestion = status_payload.get("ingestion") or {}
        lines.append(
            _line(
                "ingestion",
                " ".join(
                    [
                        f"last_ok={_get(ingestion, 'last_run_ok', default='(missing)')}",
                        f"scanned={_get(ingestion, 'total_scanned', default='(missing)')}",
                        f"ingested={_get(ingestion, 'total_ingested', default='(missing)')}",
                        f"errors={_get(ingestion, 'total_errors', default='(missing)')}",
                        f"malformed={_get(ingestion, 'total_malformed', default='(missing)')}",
                    ]
                ),
            )
        )

        ask = status_payload.get("ask") or {}
        lines.append(
            _line(
                "ask",
                " ".join(
                    [
                        f"queries_24h={_get(ask, 'total_queries_24h', default='(missing)')}",
                        f"avg_latency_ms={_get(ask, 'avg_latency_ms_24h', default='(missing)')}",
                        f"errors_24h={_get(ask, 'error_count_24h', default='(missing)')}",
                    ]
                ),
            )
        )
    else:
        lines.append(_line("sot", "(missing)"))
        lines.append(_line("stores", "(missing)"))
        lines.append(_line("ingestion", "(missing)"))
        lines.append(_line("ask", "(missing)"))

    return "\n".join(lines)


def main() -> int:
    api_base_url = os.getenv("API_BASE_URL") or "http://127.0.0.1:18000"
    output = render_status(_fetch_json, api_base_url=api_base_url)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
