from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from app.config.database import default_database_name
from app.config.environment import ENV_DEV, ENV_TEST, active_environment
from app.health_contract import DEFAULT_CONTRACT
from app.settings.panel_actions_settings import load_panel_actions_settings, panel_action_ids
from app.settings.watcher_settings import invalid_allowed_actions, load_watcher_settings, resolve_auto_exec_state
from app.settings.runtime import get_settings_bundle


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


def _display_database_url() -> str:
    """Build a display-safe DSN that never reads POSTGRES_PASSWORD.

    The runtime DSN resolver reads POSTGRES_PASSWORD and embeds it into the
    DSN string — calling it from a display path would route the real password
    into the output payload (CodeQL py/clear-text-logging-sensitive-data).
    For an explicit DATABASE_URL/DB_DSN, hand off to mask_dsn (re.sub-based
    sanitizer).  Otherwise reconstruct the DSN here using only non-sensitive
    env vars, with the password hardcoded to "***".
    """
    explicit = (os.environ.get("DATABASE_URL", "") or os.environ.get("DB_DSN", "") or "").strip()
    if explicit:
        return mask_dsn(explicit)
    env_name = active_environment()
    if env_name == ENV_DEV:
        db_name = (os.environ.get("PKM_DB_NAME_DEV", "") or "").strip() or default_database_name(env_name)
    elif env_name == ENV_TEST:
        db_name = (os.environ.get("PKM_DB_NAME_TEST", "") or "").strip() or default_database_name(env_name)
    else:
        db_name = (os.environ.get("PKM_DB_NAME_PROD", "") or "").strip() or default_database_name(env_name)
    user = (os.environ.get("POSTGRES_USER", "") or "").strip() or "app"
    host = (os.environ.get("PKM_DB_HOST", "") or "").strip() or "db"
    port = (os.environ.get("PKM_DB_PORT", "") or "").strip() or "5432"
    return f"postgresql+psycopg://{quote(user)}:***@{host}:{port}/{db_name}"


def build_settings_explain_payload() -> dict[str, Any]:
    db_url = _display_database_url()
    panel_settings = load_panel_actions_settings()
    watcher_settings = load_watcher_settings()
    auto_exec = resolve_auto_exec_state()
    allowed_action_ids = sorted(panel_action_ids(panel_settings))
    invalid_actions = invalid_allowed_actions(watcher_settings, allowed_action_ids)
    write_guard = DEFAULT_CONTRACT.evaluate()
    settings_provider = None
    settings_model = None
    settings_base_url = None
    try:
        default_chat = get_settings_bundle().providers.llm.get("default_chat")
        if default_chat is not None:
            kind = (default_chat.kind or "").strip().lower()
            settings_provider = "openai" if kind in {"openai", "openai_compat"} else kind or None
            settings_model = (default_chat.model or "").strip() or None
            settings_base_url = (default_chat.base_url or "").strip() or None
    except Exception:
        pass
    if settings_provider is None and settings_model is None and settings_base_url is None:
        providers_md = Path(os.getenv("VAULT_ROOT", "vault")) / "@Settings" / "providers.md"
        if providers_md.exists():
            text = providers_md.read_text(encoding="utf-8")
            m = re.search(r"```yaml settings\s*(.*?)```", text, re.S)
            if m:
                block = m.group(1)
                in_default_chat = False
                for raw in block.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("default_chat:"):
                        in_default_chat = True
                        continue
                    if not in_default_chat:
                        continue
                    key, _, value = line.partition(":")
                    if not _:
                        continue
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key == "kind":
                        kind = value.lower()
                        settings_provider = "openai" if kind in {"openai", "openai_compat"} else (kind or None)
                    elif key == "model":
                        settings_model = value or None
                    elif key == "base_url":
                        settings_base_url = value or None
    env_provider = (os.getenv("LLM_PROVIDER") or "").strip() or None
    env_model = (os.getenv("LLM_MODEL") or "").strip() or None
    env_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    return {
        "environment": active_environment(),
        "database_url": db_url,
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
        "llm_provider": {
            "resolved": {
                "provider": env_provider or settings_provider,
                "model": env_model or settings_model,
                "openai_base_url": env_base_url or settings_base_url,
            },
            "provenance": {
                "provider": "env:LLM_PROVIDER" if env_provider else ("settings:providers.default_chat.kind" if settings_provider else "unresolved"),
                "model": "env:LLM_MODEL" if env_model else ("settings:providers.default_chat.model" if settings_model else "unresolved"),
                "openai_base_url": "env:OPENAI_BASE_URL" if env_base_url else ("settings:providers.default_chat.base_url" if settings_base_url else "unresolved"),
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
