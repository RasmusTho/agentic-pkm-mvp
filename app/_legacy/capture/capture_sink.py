from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app._legacy.capture.capture_writer import bundle_to_markdown

VAULT_BASE = Path("vault")
INBOX_DIR = VAULT_BASE / "@Inbox"


def write_capture_bundle(bundle: Dict[str, Any]) -> Path:
    capture_id = bundle.get("capture_id", "cap-unknown")
    markdown = bundle_to_markdown(bundle)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INBOX_DIR / f"{capture_id}.md"
    out_path.write_text(markdown, encoding="utf-8")
    return out_path
