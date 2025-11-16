from __future__ import annotations

import sys
import uuid as uuidlib
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.events.models import new_trace_id
from app.services.settings import policy
from app.store.object_store import DomainObject, ObjectStore


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_capture_uuid() -> str:
    return str(uuidlib.uuid4())


def _new_capture_id() -> str:
    return "cap-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_file(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    frontmatter_block = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    path.write_text(f"---\n{frontmatter_block}\n---\n{body.strip()}\n", encoding="utf-8")


def main() -> None:
    raw_stdin = sys.stdin.read().strip()
    if not raw_stdin:
        print("no input", file=sys.stderr)
        sys.exit(1)

    timestamp = _now_utc()
    note_uuid = _new_capture_uuid()
    capture_id = _new_capture_id()

    frontmatter: dict[str, Any] = {
        "uuid": note_uuid,
        "title": capture_id,
        "origin": "capture_ingest",
        "review_state": "inbox",
        "trust": "ai|rule",
        "source_ref": capture_id,
        "created_at": timestamp.isoformat(),
    }

    body = raw_stdin
    inbox_dir = Path("vault/@Inbox")
    inbox_dir.mkdir(parents=True, exist_ok=True)
    file_path = inbox_dir / f"{capture_id}.md"
    _write_file(file_path, frontmatter, body)

    payload: dict[str, Any] = {
        "frontmatter": frontmatter,
        "body": body,
        "path": str(file_path),
        "policy": policy(),
    }

    domain_object = DomainObject(
        uuid=note_uuid,
        kind="capture_note",
        payload=payload,
        source_ref=capture_id,
        created_at=timestamp,
    )

    store = ObjectStore()
    store.save_object(domain_object, emit_outbox=True, trace_id=new_trace_id())

    print(str(file_path))


if __name__ == "__main__":
    main()
