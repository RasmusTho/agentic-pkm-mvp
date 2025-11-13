from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .loader import read_text

FENCE_START = "```yaml settings"
FENCE_END = "```"


def writeback_settings_block(path: Path, canonical: Dict[str, Any]) -> None:
    markdown = read_text(path)
    body = yaml.safe_dump(canonical, allow_unicode=True, sort_keys=True)
    replacement = f"{FENCE_START}\n{body}{FENCE_END}"
    if FENCE_START in markdown:
        head, tail = markdown.split(FENCE_START, 1)
        if FENCE_END in tail:
            _, rest = tail.split(FENCE_END, 1)
            markdown = f"{head}{replacement}{rest}"
        else:
            markdown = f"{head}{replacement}"
    else:
        markdown = markdown.rstrip() + "\n\n" + replacement + "\n"
    path.write_text(markdown, encoding="utf-8")
