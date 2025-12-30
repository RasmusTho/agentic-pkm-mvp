#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _fetch_json(url: str, timeout: float = 3.0) -> tuple[int | None, dict | None, str | None]:
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


def _print_line(label: str, value: str) -> None:
    print(f"- {label}: {value}")


def main() -> int:
    base_url = (os.getenv("API_BASE_URL") or "http://127.0.0.1:18000").rstrip("/")

    print("Alpha status")

    status_code, status_payload, status_err = _fetch_json(f"{base_url}/api/status")
    if status_code is None:
        _print_line("api", f"ERROR ({status_err})")
    else:
        _print_line("api", f"OK ({status_code})")

    health_code, health_payload, health_err = _fetch_json(f"{base_url}/api/health")
    if health_code is None:
        _print_line("health", f"ERROR ({health_err})")
    elif health_payload is None:
        _print_line("health", f"non-JSON ({health_code})")
    else:
        state = _get(health_payload, "state", default=_get(health_payload, "detail", "state", default="(missing)"))
        reason = _get(health_payload, "reason", default=_get(health_payload, "detail", "reason", default=""))
        writes_allowed = _get(health_payload, "writes_allowed", default="(missing)")
        reason_text = f" reason={reason}" if reason else ""
        _print_line("health", f"mode={state} writes_allowed={writes_allowed}{reason_text}")

    stores = None
    if isinstance(status_payload, dict):
        stores = status_payload.get("stores") or status_payload.get("store")
    store_backend = _get(stores, "backend", default=_get(stores, "object_store", "backend", default="(missing)"))
    objects = _get(stores, "objects", default=_get(stores, "object_store", "count", default="(missing)"))
    vectors = _get(stores, "vectors", default=_get(stores, "vector_index", "count", default="(missing)"))
    notes = _get(stores, "vault_notes", default=_get(stores, "notes", default="(missing)"))
    _print_line("stores", f"backend={store_backend} objects={objects} vectors={vectors} notes={notes}")

    watcher = None
    if isinstance(status_payload, dict):
        watcher = status_payload.get("watcher") or status_payload.get("watchers")
    heartbeat = _get(watcher, "heartbeat", default=_get(watcher, "last_seen", default="(missing)"))
    auto_exec = os.getenv("WATCHER_AUTO_EXEC", "0")
    applied = _get(watcher, "applied_actions", default=_get(watcher, "applied", default="(missing)"))
    skipped_dedup = _get(watcher, "skipped_dedup", default="(missing)")
    skipped_blocked = _get(watcher, "skipped_writes_blocked", default=_get(watcher, "skipped_blocked", default="(missing)"))
    _print_line(
        "watcher",
        f"heartbeat={heartbeat} auto_exec={auto_exec} applied={applied} skipped_dedup={skipped_dedup} skipped_blocked={skipped_blocked}",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
