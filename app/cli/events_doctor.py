from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List

import click

DEFAULT_OUTBOX = Path(os.environ.get("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")).expanduser()


def _load_records(path: Path) -> List[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _trace_id_for_record(rec: dict[str, Any]) -> str:
    raw = rec.get("trace_id") or rec.get("traceId") or ""
    return str(raw) if raw is not None else ""


@click.command(name="events-doctor", help="Render a simple trace story from the index outbox JSONL.")
@click.option("--path", "path", type=click.Path(path_type=Path), default=None, help="Outbox JSONL path (defaults to INDEX_OUTBOX_PATH)")
@click.option("--trace-id", "trace_id", default=None, help="Trace ID to render (defaults to latest trace in file)")
def events_doctor(path: Path | None, trace_id: str | None) -> None:
    resolved = path.expanduser() if path is not None else DEFAULT_OUTBOX
    if not resolved.exists():
        raise click.ClickException(f"Outbox path not found: {resolved}")

    records = _load_records(resolved)
    if not records:
        click.echo("No events found.")
        return

    target_trace = trace_id
    if not target_trace:
        for rec in reversed(records):
            candidate = _trace_id_for_record(rec)
            if candidate:
                target_trace = candidate
                break

    filtered = records if not target_trace else [rec for rec in records if _trace_id_for_record(rec) == target_trace]
    if not filtered:
        click.echo(f"No events found for trace_id={target_trace or '<none>'}")
        return

    filtered.sort(key=lambda rec: rec.get("timestamp") or "")

    click.echo(f"Trace {target_trace or '<unknown>'}: {len(filtered)} event(s)")
    for rec in filtered:
        ts = rec.get("timestamp") or ""
        ev = rec.get("event") or rec.get("event_type") or rec.get("kind") or "unknown"
        source = rec.get("source") or "-"
        payload = rec.get("payload") or {}
        obj = payload.get("object_id") or payload.get("uuid") or rec.get("uuid")
        line = f"{ts} | {source} | {ev}"
        if obj:
            line += f" | object={obj}"
        click.echo(line)


__all__ = ["events_doctor"]
