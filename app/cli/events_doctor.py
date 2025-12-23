from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from app.outbox.events import INDEX_OUTBOX_PATH


DEFAULT_OUTBOX_PATH = Path(INDEX_OUTBOX_PATH)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _event_name(rec: Dict[str, Any]) -> str:
    return str(rec.get("event") or rec.get("event_type") or "").strip()


def _trace_id(rec: Dict[str, Any]) -> str:
    return str(rec.get("trace_id") or "").strip()


def _timestamp(rec: Dict[str, Any]) -> str:
    return str(rec.get("timestamp") or rec.get("created_at") or "").strip()


def _stage(event: str) -> str:
    if not event:
        return "unknown"
    return event.split(".", 1)[0]


def _pick_trace_id(rows: List[Dict[str, Any]], trace_id: str, latest: bool) -> str:
    if trace_id:
        return trace_id
    if not latest:
        return ""
    for rec in reversed(rows):
        tid = _trace_id(rec)
        if tid:
            return tid
    return ""


def _build_story(rows: List[Dict[str, Any]], trace_id: str) -> Dict[str, Any]:
    filtered = [r for r in rows if _trace_id(r) == trace_id] if trace_id else []
    events: List[Dict[str, Any]] = []
    stages: List[str] = []
    for r in filtered:
        ev = _event_name(r)
        st = _stage(ev)
        if st not in stages:
            stages.append(st)
        events.append(
            {
                "event": ev,
                "timestamp": _timestamp(r),
                "source": r.get("source"),
                "event_id": r.get("event_id"),
                "stage": st,
            }
        )
    first_ts = events[0]["timestamp"] if events else ""
    last_ts = events[-1]["timestamp"] if events else ""
    return {
        "trace_id": trace_id,
        "count": len(events),
        "stages": stages,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "events": events,
    }


@click.group(help="Event inspection utilities.")
def events() -> None:
    ...


@events.command("doctor", help="Summarize a single trace_id flow from the outbox JSONL.")
@click.option("--outbox", "outbox_path", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--trace-id", "trace_id", default="", help="Trace ID to inspect.")
@click.option("--latest", is_flag=True, default=False, help="Use the latest trace_id in the outbox when none is provided.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON.")
def doctor(outbox_path: Optional[Path], trace_id: str, latest: bool, as_json: bool) -> None:
    path = (outbox_path or DEFAULT_OUTBOX_PATH).expanduser()
    rows = _read_jsonl(path)
    picked = _pick_trace_id(rows, trace_id=trace_id, latest=latest)
    if not picked:
        raise SystemExit(2)

    story = _build_story(rows, picked)
    if story.get("count", 0) == 0:
        raise SystemExit(2)

    if as_json:
        click.echo(json.dumps(story, ensure_ascii=False))
        raise SystemExit(0)

    click.echo(f"Trace: {story['trace_id']}")
    click.echo(f"Events: {story['count']}")
    click.echo(f"Stages: {', '.join(story['stages']) if story['stages'] else '(none)'}")
    click.echo("")
    for idx, ev in enumerate(story["events"], start=1):
        ts = ev.get("timestamp") or ""
        src = ev.get("source") or ""
        click.echo(f"{idx:02d}. {ts} {ev['event']} (stage={ev['stage']} source={src})")
    raise SystemExit(0)


__all__ = ["events"]
