from __future__ import annotations

import json
from typing import Any, Sequence

from app.settings.panel_actions_settings import load_panel_actions_settings
from app.settings.watcher_settings import load_watcher_settings


def build_settings_explain_payload() -> dict[str, Any]:
    panel_settings = load_panel_actions_settings()
    watcher_settings = load_watcher_settings()
    return {
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
            "paths": {
                "index_outbox": str(watcher_settings.paths.index_outbox),
                "watcher_tick_log": str(watcher_settings.paths.watcher_tick_log),
                "panel_event_log": str(watcher_settings.paths.panel_event_log),
            },
            "source": watcher_settings.source.to_payload(),
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
