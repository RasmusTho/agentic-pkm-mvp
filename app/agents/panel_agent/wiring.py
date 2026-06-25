from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable

import yaml

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root

DEFAULT_PANEL_ACTION_WIRING_PATH = Path("docs/settings/panel-action-wiring.yaml")
VAULT_WIRING_RELATIVE = Path("System/Config/panel-action-wiring.yaml")


class WiringConfigError(ValueError):
    ...


def _warn(message: str) -> None:
    try:
        print(f"Warning: {message}", file=sys.stderr)
    except Exception:
        pass


def _candidate_paths(path: Path | None = None) -> Iterable[Path]:
    if path is not None:
        yield Path(path)
        return
    env_path = os.getenv("PANEL_ACTION_WIRING_PATH")
    if env_path:
        yield Path(env_path)
    # Route through the canonical optional resolver rather than reading VAULT_ROOT
    # directly, so wiring-config discovery honours the same no-vault semantics as
    # the HTTP path (#2476: non-HTTP vault readers funnel through canonical resolver).
    #
    # Wiring discovery is OPTIONAL config with a DEFAULT fallback, so a
    # set-but-missing VAULT_ROOT must not abort it: a stale HTTP VAULT_ROOT would
    # otherwise raise here and stop watcher/worker-bound background panel
    # execution (bound via WATCHER_VAULT_PATH and threaded into
    # execute_panel_intent) before the threaded vault is ever used. Mirror
    # cognition/runtime: treat a misconfigured root as "no vault-derived
    # candidate" and fall through to the default.
    try:
        vault_root = resolve_optional_vault_root()
    except VaultRootMisconfiguredError:
        vault_root = None
    if vault_root is not None:
        yield vault_root.expanduser() / VAULT_WIRING_RELATIVE
    yield DEFAULT_PANEL_ACTION_WIRING_PATH


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise WiringConfigError(f"wiring config not found: {path}")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise WiringConfigError(f"invalid JSON in {path}: {exc}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WiringConfigError(f"invalid YAML in {path}: {exc}")
    if raw is None:
        raise WiringConfigError(f"empty wiring config: {path}")
    if not isinstance(raw, dict):
        raise WiringConfigError(f"wiring config must be a mapping: {path}")
    return raw


def _validate_entry(entry: dict, path: Path) -> tuple[str, str]:
    if not isinstance(entry, dict):
        raise WiringConfigError(f"entry must be a mapping in {path}")
    action_id = entry.get("id")
    if not isinstance(action_id, str) or not action_id.strip():
        raise WiringConfigError(f"entry missing string id in {path}")
    action_id = action_id.strip()
    kind = entry.get("kind") or "event"
    if kind not in {"event", "intent"}:
        raise WiringConfigError(f"unsupported kind '{kind}' in {path}")
    target = entry.get("event_type") or entry.get("target_event") or entry.get("intent_type")
    if not isinstance(target, str) or not target.strip():
        raise WiringConfigError(f"entry '{action_id}' missing target_event/event_type in {path}")
    return action_id, target.strip()


def _parse_wiring(data: dict, path: Path) -> Dict[str, str]:
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise WiringConfigError(f"wiring config must contain an 'actions' list in {path}")
    wiring: Dict[str, str] = {}
    for entry in actions:
        action_id, target = _validate_entry(entry, path)
        wiring[action_id] = target
    return wiring


def load_action_wiring(path: Path | None = None) -> Dict[str, str]:
    errors: list[str] = []
    for candidate in _candidate_paths(path):
        try:
            data = _load_yaml(candidate)
            wiring = _parse_wiring(data, candidate)
            if errors:
                _warn("; ".join(errors))
            return wiring
        except WiringConfigError as exc:
            errors.append(str(exc))
            continue
    if errors:
        _warn("; ".join(errors))
    return {}


def get_action_wiring() -> Dict[str, str]:
    wiring = load_action_wiring()
    if wiring:
        return wiring
    if DEFAULT_PANEL_ACTION_WIRING_PATH.exists():
        try:
            data = _load_yaml(DEFAULT_PANEL_ACTION_WIRING_PATH)
            return _parse_wiring(data, DEFAULT_PANEL_ACTION_WIRING_PATH)
        except WiringConfigError:
            return {}
    return {}


def get_default_action_wiring() -> Dict[str, str]:  # backward compatibility
    return get_action_wiring()


__all__ = [
    "load_action_wiring",
    "get_action_wiring",
    "get_default_action_wiring",
    "DEFAULT_PANEL_ACTION_WIRING_PATH",
    "VAULT_WIRING_RELATIVE",
]
