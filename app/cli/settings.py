from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from app.config.paths import resolve_system_settings_path
from app.services import settings as settings_service


def _resolve_section(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(part)
    return current


def _emit(output: Any, as_json: bool) -> None:
    if isinstance(output, (str, bytes)):
        print(output if isinstance(output, str) else output.decode("utf-8"))
        return
    if as_json:
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
        return
    print(yaml.safe_dump(output, sort_keys=False).strip())


def main(argv: list[str] | None = None) -> int:
    default_path = resolve_system_settings_path()
    if default_path is None or not default_path.exists():
        default_path = resolve_system_settings_path(vault_root=Path("vault"))
    parser = argparse.ArgumentParser(description="Inspect canonical system settings (SoT v4.3.1).")
    parser.add_argument("--path", type=Path, default=default_path, help="Path to canonical system-settings.yaml")
    parser.add_argument("--section", help="Dot path into the settings map, e.g. 'index.rules'")
    parser.add_argument("--policy", action="store_true", help="Emit the derived sync policy view")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of YAML")
    parser.add_argument("--reload", action="store_true", help="Bypass cache when loading settings")
    args = parser.parse_args(argv)

    settings = settings_service.load_settings(force=args.reload, path=args.path)
    if settings is None:
        parser.error(f"No system settings found at {args.path}")

    if args.policy:
        target: Any = settings_service.policy(settings)
    elif args.section:
        try:
            target = _resolve_section(settings, args.section)
        except KeyError as exc:
            parser.error(f"Section '{args.section}' not found (missing key: {exc.args[0]})")
    else:
        target = settings

    _emit(target, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
