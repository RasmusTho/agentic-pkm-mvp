from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import PanelRuntimeResult, execute_panel_intent
from app.events.panel import PanelIntentEvent
from app.services.outbox import coerce_outbox_event, write_outbox_event
from app.objects import DomainObject, ObjectStore
from scripts.yaml_roundtrip import load_frontmatter


@dataclass
class PanelNoteExecutionResult:
    intent_events: list[PanelIntentEvent]
    runtime_results: list[PanelRuntimeResult]

    @property
    def emitted_events(self) -> list[object]:
        emitted: list[object] = []
        for result in self.runtime_results:
            emitted.extend(list(result.emitted_events or []))
        return emitted

    @property
    def emitted_count(self) -> int:
        return len(self.intent_events) + sum(len(result.emitted_events or []) for result in self.runtime_results)


def use_db_outbox() -> bool:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg" or bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))


def refresh_panel_note_object(*, note_uuid: str, note_path: Path, raw_text: str, trace_id: str) -> None:
    store = ObjectStore()
    existing = store.get_object(note_uuid)
    frontmatter, _ = load_frontmatter(raw_text)
    payload = dict(existing.payload or {}) if existing is not None else {}
    payload.update(
        {
            "raw_text": raw_text,
            "frontmatter": frontmatter if isinstance(frontmatter, dict) else {},
            "origin": "vault",
        }
    )
    if existing is None:
        obj = DomainObject(
            uuid=note_uuid,
            kind="note",
            payload=payload,
            source_ref=str(note_path),
            created_at=datetime.now(timezone.utc),
        )
    else:
        existing.payload = payload
        existing.source_ref = str(note_path)
        obj = existing
    store.save_object(obj, emit_outbox=False, trace_id=trace_id or None)


def run_panel_note_execution(
    note_uuid: str,
    *,
    trace_id: str | None = None,
    outbox_path: Path | None = None,
    persist_created_to_db: bool = False,
    trigger: str = "cli",
) -> PanelNoteExecutionResult:
    intent_events = run_panel_intent_for_note(
        note_uuid,
        trace_id=trace_id,
        trigger=trigger,
        write_outbox=True,
        outbox_path=outbox_path,
    )
    if persist_created_to_db:
        for event in intent_events:
            outbox_event = coerce_outbox_event(event, default_source="panel_agent")
            if outbox_event is None:
                continue
            write_outbox_event(outbox_event, idempotency_key=outbox_event.event_id)
    runtime_results = [execute_panel_intent(event, outbox_path=outbox_path) for event in intent_events]
    return PanelNoteExecutionResult(intent_events=intent_events, runtime_results=runtime_results)


__all__ = [
    "PanelNoteExecutionResult",
    "refresh_panel_note_object",
    "run_panel_note_execution",
    "use_db_outbox",
]
