from __future__ import annotations

import json
import os
import re
from typing import Any, Sequence


from app.config.database import resolve_runtime_database_url
from app.config.environment import active_environment
from app.health_contract import DEFAULT_CONTRACT
from app.settings.panel_actions_settings import load_panel_actions_settings, panel_action_ids
from app.settings.watcher_settings import invalid_allowed_actions, load_watcher_settings, resolve_auto_exec_state


# group 1 = "://user:", group 2 = "@" — replaces only the password portion
_DSN_PASSWORD_RE = re.compile(r"(://[^:@/\s]+:)[^@/\s]+(@)")
# group 1 = "&password=" (or ?/pwd/pass variants) — URL-encodes *** as %2A%2A%2A
_DSN_QUERYPW_RE = re.compile(r"(?i)([?&](?:password|pwd|pass)=)[^&]*")


def mask_dsn(dsn: str) -> str:
    """Return dsn with credentials redacted.  Uses re.sub with string replacements
    (no callables) so static-analysis taint tools recognise the output as sanitized."""
    if "://" not in dsn:
        return dsn
    masked = _DSN_PASSWORD_RE.sub(r"\1***\2", dsn)
    masked = _DSN_QUERYPW_RE.sub(r"\1%2A%2A%2A", masked)
    return masked


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


_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "token", "secret", "password", "key", "dsn", "database_url",
        "api_key", "auth", "credential", "credentials",
    }
)


def _redact_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: "***" if any(s in k.lower() for s in _SENSITIVE_KEYS) else _redact_payload(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_payload(item) for item in obj]
    if isinstance(obj, str) and "://" in obj:
        return mask_dsn(obj)
    return obj


def emit_settings_explain(payload: dict[str, Any], *, pretty: bool = True) -> None:
    kwargs: dict[str, Any] = {"sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    print(json.dumps(_redact_payload(payload), **kwargs))


def main(argv: Sequence[str] | None = None) -> int:
    payload = build_settings_explain_payload()
    emit_settings_explain(payload, pretty=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
