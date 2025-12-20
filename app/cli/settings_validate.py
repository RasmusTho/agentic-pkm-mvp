from __future__ import annotations

import json
from typing import Sequence

from app.settings.validate import issues_to_json, validate_settings


def run_settings_validate(as_json: bool) -> int:
    issues = validate_settings()
    if as_json:
        print(json.dumps(issues_to_json(issues), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if not issues:
            print("settings validate: OK")
        else:
            print(f"settings validate: {len(issues)} issue(s)")
            for i in issues:
                ref = f" [{i.ref}]" if i.ref else ""
                print(f"- {i.code}{ref}: {i.message}")
    return 0 if not issues else 2
