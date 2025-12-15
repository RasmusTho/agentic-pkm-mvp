from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.yaml_roundtrip import load_frontmatter  # type: ignore  # noqa: E402


def load_events(outbox: Path) -> List[dict]:
    events: List[dict] = []
    if not outbox.exists():
        raise SystemExit(f"Outbox not found: {outbox}")
    for idx, line in enumerate(outbox.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            ev["_line_index"] = idx
            events.append(ev)
        except Exception as exc:  # pragma: no cover - defensive
            raise SystemExit(f"Failed to parse outbox line {idx}: {exc}")
    return events


def assert_events(events: List[dict]) -> Tuple[List[dict], List[dict]]:
    promote_created = [e for e in events if e.get("event") == "promote.intent.created"]
    promote_done = [e for e in events if e.get("event") == "promote.done"]
    if not promote_created:
        raise SystemExit("No promote.intent.created events found")
    if not promote_done:
        raise SystemExit("No promote.done events found")

    for ev in promote_created:
        note = (ev.get("payload") or {}).get("note") or {}
        if not note.get("uuid"):
            raise SystemExit("promote.intent.created missing note.uuid")
        if not note.get("path"):
            raise SystemExit("promote.intent.created missing note.path")

    for ev in events:
        if ev.get("event") in {"panel.intent.created", "panel.intent.executed"}:
            note = (ev.get("payload") or {}).get("note") or {}
            if not note.get("uuid"):
                raise SystemExit(f"{ev.get('event')} missing note.uuid")
            if "path" in note and not note.get("path"):
                raise SystemExit(f"{ev.get('event')} has empty note.path")

    return promote_created, promote_done


def find_note_path(vault: Path, target_uuid: str) -> Optional[Path]:
    for path in vault.rglob("*.md"):
        fm, _ = load_frontmatter(path.read_text(encoding="utf-8"))
        raw = fm.get("uuid")
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        if isinstance(raw, str):
            cleaned = raw.strip()
            if cleaned.startswith("[[") and cleaned.endswith("]]" ):
                cleaned = cleaned[2:-2].strip()
            if cleaned == target_uuid:
                return path
    return None


def assert_frontmatter(promote_done: List[dict], vault: Path) -> None:
    for ev in promote_done:
        payload = ev.get("payload") or {}
        note_uuid = payload.get("note_uuid")
        desired_state = payload.get("state")
        note_path = payload.get("note_path") or (payload.get("note") or {}).get("path")
        if not note_uuid:
            raise SystemExit("promote.done missing note_uuid")
        path = Path(note_path) if note_path else None
        if path is None:
            path = find_note_path(vault, str(note_uuid))
        if path is None or not path.exists():
            raise SystemExit(f"Could not locate note for promote.done uuid={note_uuid}")
        fm, _ = load_frontmatter(path.read_text(encoding="utf-8"))
        raw_uuid = fm.get("uuid")
        if isinstance(raw_uuid, list) and len(raw_uuid) == 1:
            raw_uuid = raw_uuid[0]
        if isinstance(raw_uuid, str):
            cleaned = raw_uuid.strip()
            if cleaned.startswith("[[") and cleaned.endswith("]]" ):
                cleaned = cleaned[2:-2].strip()
        else:
            cleaned = str(raw_uuid)
        if cleaned != str(note_uuid):
            raise SystemExit(f"Frontmatter uuid mismatch in {path}: {cleaned} != {note_uuid}")
        if desired_state and fm.get("review_state") != desired_state:
            raise SystemExit(f"Frontmatter review_state mismatch in {path}: {fm.get('review_state')} != {desired_state}")


def assert_tick2_noop(events: List[dict]) -> None:
    no_change_runs = [e for e in events if e.get("event") == "watcher.run" and (e.get("payload") or {}).get("changed") == 0]
    if not no_change_runs:
        raise SystemExit("Expected a watcher.run with changed=0 from tick2")
    last_no_change_idx = max(ev["_line_index"] for ev in no_change_runs)
    later_promote_done = [e for e in events if e.get("event") == "promote.done" and e["_line_index"] > last_no_change_idx]
    if later_promote_done:
        raise SystemExit("Found promote.done events after tick2 watcher.run (expected no-op)")


def assert_writer_guard(repo_root: Path) -> None:
    consumer = (repo_root / "app" / "promotion" / "consumer.py").read_text(encoding="utf-8")
    if "apply_promotion_frontmatter" not in consumer:
        raise SystemExit("promotion.consumer missing apply_promotion_frontmatter usage")
    offenders = []
    whitelist = {repo_root / "app" / "agents" / "note_hygiene" / "agent.py"}
    for path in (repo_root / "app" / "agents").rglob("*.py"):
        if path in whitelist:
            continue
        text = path.read_text(encoding="utf-8")
        if "open(" in text and '"w"' in text:
            offenders.append(str(path))
    if offenders:
        raise SystemExit(f"Writer guard failed; agents writing files directly: {offenders}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify runtime-loop promotion smoke invariants")
    parser.add_argument("--outbox", required=True, type=Path)
    parser.add_argument("--vault", required=True, type=Path)
    args = parser.parse_args()

    events = load_events(args.outbox)
    promote_created, promote_done = assert_events(events)
    assert_frontmatter(promote_done, args.vault)
    assert_tick2_noop(events)
    assert_writer_guard(REPO_ROOT)
    print(
        f"OK: promote.intent.created={len(promote_created)}, promote.done={len(promote_done)}, "
        f"tick2_noop=yes, frontmatter_validated={len(promote_done)}"
    )


if __name__ == "__main__":
    main()
