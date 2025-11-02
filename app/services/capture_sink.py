from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from app.services.capture_writer import bundle_to_markdown

# TODO: om din vault inte ligger här, ändra basen.
VAULT_BASE = Path("vault")
INBOX_DIR = VAULT_BASE / "@Inbox"

def write_capture_bundle(bundle: Dict[str, Any]) -> Path:
    """
    Tar ett triage-bundle, renderar markdown, och sparar som ny fil i @Inbox/.

    Filnamn: <capture_id>.md
    Returnerar Path till filen.
    """
    cap_id = bundle.get("capture_id","cap-unknown")
    md = bundle_to_markdown(bundle)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INBOX_DIR / f"{cap_id}.md"
    out_path.write_text(md, encoding="utf-8")

    return out_path
