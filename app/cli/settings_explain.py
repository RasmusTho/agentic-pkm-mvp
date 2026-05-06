from __future__ import annotations

import json
import os
from typing import Any, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config.database import resolve_runtime_database_url
from app.config.environment import active_environment
from app.health_contract import DEFAULT_CONTRACT
from app.settings.panel_actions_settings import load_panel_actions_settings, panel_action_ids
from app.settings.watcher_settings import invalid_allowed_actions, load_watcher_settings, resolve_auto_exec_state


def mask_dsn(dsn: str) -> str:
    if "://" not in dsn:
        return dsn
    parsed = urlsplit(dsn)
    netloc = parsed.netloc
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)

    if "@" in netloc:
        credentials, host_part = netloc.rsplit("@", 1)
        if ":" in credentials:
            user, _ = credentials.split(":", 1)
            masked_credentials = f"{user}:***"
        else:
            masked_credentials = "***"
        netloc = f"{masked_credentials}@{host_part}"

    if query_pairs:
        masked_pairs: list[tuple[str, str]] = []
        for key, value in query_pairs:
            if "password" in key.lower() or key.lower() in {"pwd", "pass"}:
                masked_pairs.append((key, "***"))
            else:
                masked_pairs.append((key, value))
        query = urlencode(masked_pairs, doseq=True)
    else:
        query = parsed.query

    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def build_settings_explain_payload() -> dict[str, Any]:
    db_url = resolve_runtime_database_url(os.environ)
    panel_settings = load_panel_actions_settings()
    watcher_settings = load_watcher_settings()
    auto_exec = resolve_auto_exec_state()
    allowed_action_ids = sorted(panel_action_ids(panel_settings))
    invalid_actions = invalid_allowed_actions(watcher_settings, allowed_action_ids)
    write_guard = DEFAULT_CONTRACT.evaluate()
    return {
        "environment": active_environment(),
        "database_url": mask_dsn(db_url),
        "panel_actions": {
            "action_count": len(panel_settings.catalog.actions),
            "action_ids": sorted(panel_settings.catalog.ids()),
            "paths": [str(path) for path in panel_settings.paths],
            "sources": [source.to_payload() for source in panel_settings.sources],
            "combined_sha": panel_settings.combined_sha,
        },
        "watcher_settings": {
            "auto_exec_env": watcher_settings.auto_exec_env,
            "auto_exec_default": watcher_settings.auto_exec_default,
            "allowed_actions": list(watcher_settings.allowed_actions),
            "auto_exec": {
                "enabled": auto_exec.enabled,
                "mode": "auto-exec" if auto_exec.enabled else "emit-only",
                "source": auto_exec.source,
                "raw_value": auto_exec.raw_value,
                "env_key": auto_exec.env_key,
                "default_enabled": auto_exec.default_enabled,
            },
            "allowlist": {
                "allowed_actions": list(watcher_settings.allowed_actions),
                "known_action_ids": allowed_action_ids,
                "invalid_actions": invalid_actions,
            },
            "paths": {
                "index_outbox": str(watcher_settings.paths.index_outbox),
                "watcher_tick_log": str(watcher_settings.paths.watcher_tick_log),
                "watcher_heartbeat": str(watcher_settings.paths.watcher_heartbeat),
                "worker_heartbeat": str(watcher_settings.paths.worker_heartbeat),
                "panel_event_log": str(watcher_settings.paths.panel_event_log),
            },
            "source": watcher_settings.source.to_payload(),
            "write_guard": {
                "writes_allowed": write_guard.get("writes_allowed"),
                "mode": write_guard.get("state"),
            },
        },
    }


def emit_settings_explain(payload: dict[str, Any], *, pretty: bool = True) -> None:
    kwargs: dict[str, Any] = {"sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    print(json.dumps(payload, **kwargs))


def main(argv: Sequence[str] | None = None) -> int:
    payload = build_settings_explain_payload()
    emit_settings_explain(payload, pretty=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
