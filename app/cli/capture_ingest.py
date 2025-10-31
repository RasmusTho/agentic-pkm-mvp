from __future__ import annotations

import sys
import uuid as uuidlib
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import yaml

from app.store.object_store import ObjectStore, DomainObject
from app.agent.events import new_trace_id
from app.services.settings import policy

# This CLI reads stdin as a captured note, writes it to vault/@Inbox/,
# and registers it in the ObjectStore as a new object with provenance.


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_capture_uuid() -> str:
    return str(uuidlib.uuid4())


def _new_capture_id() -> str:
    # human-friendly slug we also use for filename
    return "cap-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_file(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    fm_block = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    text = f"---\n{fm_block}\n---\n{body.strip()}\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    raw_stdin = sys.stdin.read().strip()
    if not raw_stdin:
        print("no input", file=sys.stderr)
        sys.exit(1)

    ts = _now_utc()
    note_uuid = _new_capture_uuid()
    cap_id = _new_capture_id()

    # Build frontmatter (Core-6-ish projection)
    # We assume early stage 'inbox' / low trust quality.
    fm: dict[str, Any] = {
        "uuid": note_uuid,
        "title": cap_id,
        "origin": "capture_ingest",
        "review_state": "inbox",
        "trust": "ai|rule",
        "source_ref": cap_id,
        "created_at": ts.isoformat(),
    }

    body = raw_stdin

    # Write file into vault @Inbox (Obsidian-facing truth)
    inbox_dir = Path("vault/@Inbox")
    inbox_dir.mkdir(parents=True, exist_ok=True)
    file_path = inbox_dir / f"{cap_id}.md"
    _write_file(file_path, fm, body)

    # Build payload for DB mirror.
    # We intentionally mirror frontmatter + body so ObjectStore becomes canonical.
    payload: dict[str, Any] = {
        "frontmatter": fm,
        "body": body,
        "path": str(file_path),
        "policy": policy(),
    }

    dom_obj = DomainObject(
        uuid=note_uuid,
        kind="capture_note",
        payload=payload,
        source_ref=cap_id,
        created_at=ts,
    )

    trace_id = new_trace_id()

    store = ObjectStore()
    store.save_object(
        dom_obj,
        emit_outbox=True,
        trace_id=trace_id,
    )

    print(str(file_path))


if __name__ == "__main__":
    main()
