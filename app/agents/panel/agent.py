from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from pydantic import BaseModel, Field

from app.agents.panel_agent.policy import contains_ai_panel_fence, proactive_assist_enabled
from app.events.schema import OutboxEvent
from app.store.object_store import DomainObject, ObjectStore
from app.settings.panel_actions import PanelActionMapping

from .events import panel_intent_to_event
from .intents import PanelIntent, enrich_panel_intents
from .parser import parse_panel
from .schema import PanelState

_ACTION_PATTERN = re.compile(r"^(\s*-\s*\[( |x|X)\]\s*)(.*?)(\s*<!--\s*ai:id=([A-Za-z0-9_.-]+)\s*-->)?\s*$")
_AI_STATUS_HEADER = "> [!info]- AI status"
_MAX_RECEIPTS = 20
_EXECUTED_FALLBACK: dict[str, set[str]] = {}

_SUGGESTED_ACTIONS = [
    "Make this note evergreen",
    "Create a separate summary note",
    "Archive this note",
]
_SUGGESTED_ACTIONS_START = "<!--ai:suggested_actions:start-->"
_SUGGESTED_ACTIONS_END = "<!--ai:suggested_actions:end-->"
_ASSIST_START = "<!--ai:assist:start-->"
_ASSIST_END = "<!--ai:assist:end-->"

_ACTION_KEYWORDS = {
    "promote.evergreen": ("evergreen",),
    "note.archive": ("archive", "arkivera"),
    "ingest.summary.create": ("summary", "sammanfatt"),
}


class PanelAgentResult(BaseModel):
    state: PanelState
    intents: list[PanelIntent]
    updated_markdown: str
    events: list[OutboxEvent] = Field(default_factory=list)


def _stable_action_id(text: str) -> str:
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()
    return digest[:8]


def _annotate_action_ids(markdown: str) -> str:
    lines = markdown.splitlines()
    changed = False
    for idx, line in enumerate(lines):
        match = _ACTION_PATTERN.match(line)
        if not match:
            continue
        label = (match.group(3) or "").strip()
        action_id = match.group(5)
        if action_id:
            continue
        action_id = _stable_action_id(label)
        prefix = match.group(1)
        lines[idx] = f"{prefix}{label} <!--ai:id={action_id}-->"
        changed = True
    if not changed:
        return markdown
    return "\n".join(lines)


def _parse_receipts(lines: list[str]) -> tuple[int | None, int | None, list[str]]:
    start = end = None
    receipts: list[str] = []
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(_AI_STATUS_HEADER.lower()):
            start = idx
            end = idx + 1
            j = idx + 1
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                content = lines[j].lstrip()[1:].lstrip()
                if content.startswith("- "):
                    receipts.append(content[2:].strip())
                j += 1
                end = j
            break
    return start, end, receipts


def _write_receipts(markdown: str, new_receipts: list[str], *, clear: bool, preferred_index: int | None) -> str:
    lines = markdown.splitlines()
    start, end, receipts = _parse_receipts(lines)
    if start is None and not new_receipts and not clear:
        return markdown
    if start is None:
        start = end = preferred_index
    receipts = [] if clear else receipts
    receipts = receipts + new_receipts
    if len(receipts) > _MAX_RECEIPTS:
        receipts = receipts[-_MAX_RECEIPTS:]
    block = [_AI_STATUS_HEADER]
    block.extend([f"> - {line}" for line in receipts])
    if start is None or end is None:
        insert_at = len(lines)
        if preferred_index is not None:
            insert_at = min(max(preferred_index, 0), len(lines))
        lines.append("")
        lines[insert_at:insert_at] = block
    else:
        lines[start:end] = block
    return "\n".join(lines)

def _split_frontmatter(markdown: str) -> tuple[list[str], list[str]]:
    lines = markdown.splitlines()
    if not lines:
        return [], []
    if lines[0].strip() != "---":
        return [], lines
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines[: idx + 1], lines[idx + 1 :]
    return [], lines


def _upsert_block(
    lines: list[str],
    *,
    search_start: int,
    search_end: int,
    insert_at: int,
    marker_start: str,
    marker_end: str,
    block: list[str],
) -> None:
    s = e = None
    for idx in range(search_start, search_end):
        if lines[idx].strip() == marker_start:
            s = idx
            break
    if s is not None:
        for j in range(s + 1, search_end):
            if lines[j].strip() == marker_end:
                e = j
                break
    if s is not None and e is not None and e >= s:
        lines[s : e + 1] = block
        return
    lines[insert_at:insert_at] = block


def _ensure_heading(lines: list[str], heading: str) -> int:
    target = heading.strip().lower()
    for idx, raw in enumerate(lines):
        if raw.strip().lower() == target:
            return idx
    lines.append(heading)
    return len(lines) - 1


def _ensure_panel_assist(markdown: str, *, create_if_missing: bool) -> str:
    if not markdown:
        markdown = ""
    state = parse_panel(markdown)
    if not state.fenced:
        if not create_if_missing:
            return markdown
        fm, rest = _split_frontmatter(markdown)
        panel_lines = [
            "%% AI %%",  # tolerant fence (parser matches any %%...ai...%% line)
            "## AI-instruktion",
            "",
            "## AI-åtgärder",
            _SUGGESTED_ACTIONS_START,
            *[f"- [ ] {label}" for label in _SUGGESTED_ACTIONS],
            _SUGGESTED_ACTIONS_END,
            "## AI-logg",
            _ASSIST_START,
            "- 💡 Suggested next actions are in the checklist above. Tick any you want me to run.",
            "- ❓ What kind of help do you want with this note?",
            _ASSIST_END,
            "%% AI %%",
            "",
        ]
        out: list[str] = []
        if fm:
            out.extend(fm)
            if out and out[-1].strip() != "":
                out.append("")
        out.extend(panel_lines)
        out.extend(rest)
        return "\n".join(out).rstrip("\n") + "\n"

    if not state.spans:
        return markdown
    start, end = state.spans[0]
    lines = markdown.splitlines()
    if start < 0 or end >= len(lines) or end <= start:
        return markdown

    panel = lines[start + 1 : end]

    actions_idx = _ensure_heading(panel, "## AI-åtgärder")
    logs_idx = _ensure_heading(panel, "## AI-logg")
    if logs_idx < actions_idx:
        logs_idx = _ensure_heading(panel, "## AI-logg")

    # Suggested actions block: insert right after actions heading.
    actions_insert_at = min(actions_idx + 1, len(panel))
    if actions_insert_at < len(panel) and panel[actions_insert_at].strip() != "":
        panel.insert(actions_insert_at, "")
        actions_insert_at += 1
    suggested_block = [
        _SUGGESTED_ACTIONS_START,
        *[f"- [ ] {label}" for label in _SUGGESTED_ACTIONS],
        _SUGGESTED_ACTIONS_END,
        "",
    ]
    _upsert_block(
        panel,
        search_start=0,
        search_end=len(panel),
        insert_at=actions_insert_at,
        marker_start=_SUGGESTED_ACTIONS_START,
        marker_end=_SUGGESTED_ACTIONS_END,
        block=suggested_block,
    )

    # Assist/Q block: insert right after logs heading.
    logs_idx = next((i for i, raw in enumerate(panel) if raw.strip().lower() == "## ai-logg"), logs_idx)
    logs_insert_at = min(logs_idx + 1, len(panel))
    if logs_insert_at < len(panel) and panel[logs_insert_at].strip() != "":
        panel.insert(logs_insert_at, "")
        logs_insert_at += 1
    assist_block = [
        _ASSIST_START,
        "- 💡 Suggested next actions are in the checklist above. Tick any you want me to run.",
        "- ❓ What kind of help do you want with this note?",
        _ASSIST_END,
        "",
    ]
    _upsert_block(
        panel,
        search_start=0,
        search_end=len(panel),
        insert_at=logs_insert_at,
        marker_start=_ASSIST_START,
        marker_end=_ASSIST_END,
        block=assist_block,
    )

    lines[start + 1 : end] = panel
    return "\n".join(lines).rstrip("\n") + "\n"


def _proactive_note_eligible(note_path: str | None) -> bool:
    if not note_path:
        return False
    path = Path(note_path)
    parts = set(path.parts)
    if ".obsidian" in parts:
        return False
    lowered = {p.lower() for p in parts}
    if "templates" in lowered:
        return False
    return True


def _infer_mapping_for_action_text(action_text: str, mappings: Dict[str, PanelActionMapping]) -> PanelActionMapping | None:
    direct = mappings.get(action_text)
    if direct is not None:
        return direct
    lowered = action_text.strip().lower()
    if not lowered:
        return None
    for action_id, keywords in _ACTION_KEYWORDS.items():
        if not any(k in lowered for k in keywords):
            continue
        for mapping in mappings.values():
            if mapping.action_id == action_id:
                return mapping
    return None


def _remove_actions_from_markdown(markdown: str, action_ids: set[str]) -> str:
    if not action_ids:
        return markdown
    result: list[str] = []
    for line in markdown.splitlines():
        match = _ACTION_PATTERN.match(line)
        if match:
            candidate_id = match.group(5)
            if candidate_id and candidate_id in action_ids:
                continue
        result.append(line)
    return "\n".join(result)


def _upsert_executed_ids(note_id: str, action_ids: Iterable[str]) -> None:
    new_ids = {aid for aid in action_ids if aid}
    if not new_ids:
        return
    store = ObjectStore()
    existing = store.get_object(note_id)
    payload = dict(existing.payload or {}) if existing else {}
    executed = set(payload.get("executed_action_ids") or [])
    executed |= new_ids
    payload["executed_action_ids"] = sorted(executed)
    try:
        if existing is None:
            obj = DomainObject(
                uuid=note_id,
                kind="note",
                payload=payload,
                source_ref=None,
                created_at=datetime.now(timezone.utc),
            )
        else:
            existing.payload = payload
            obj = existing
        store.save_object(obj, emit_outbox=False)
    except Exception:
        _EXECUTED_FALLBACK[note_id] = set(executed)
        return
    _EXECUTED_FALLBACK[note_id] = set(executed)


def handle_note_update(
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
    note_path: str | None = None,
    *,
    proactive_assist: bool = False,
) -> PanelAgentResult:
    base_markdown = new_markdown or ""
    has_ai = contains_ai_panel_fence(base_markdown)
    has_existing_panel = bool(parse_panel(base_markdown).spans)
    proactive_ok = proactive_assist and proactive_assist_enabled()
    create_panel = (
        (not has_ai)
        and proactive_ok
        and (not has_existing_panel)
        and _proactive_note_eligible(note_path)
    )
    assisted_markdown = _ensure_panel_assist(base_markdown, create_if_missing=create_panel)

    annotated_markdown = _annotate_action_ids(assisted_markdown)
    old_state = parse_panel(old_markdown or "")
    new_state = parse_panel(annotated_markdown)
    mappings = dict(action_mappings or {})

    store = ObjectStore()
    stored = store.get_object(note_id)
    executed_ids = set(_EXECUTED_FALLBACK.get(note_id, set()))
    if stored:
        executed_ids |= set((stored.payload or {}).get("executed_action_ids") or [])

    intents: list[PanelIntent] = []
    receipts: list[str] = []
    executed_now: list[str] = []
    remove_ids: set[str] = set()
    if (old_state.instruction_text or "").strip() != (new_state.instruction_text or "").strip():
        intents.append(PanelIntent(kind="instruction_updated", instruction_text=new_state.instruction_text.strip()))
    for action in new_state.actions:
        if not action.checked or not action.text:
            continue
        action_id = action.action_id or _stable_action_id(action.text)
        if action_id in executed_ids:
            remove_ids.add(action_id)
            continue
        inferred = _infer_mapping_for_action_text(action.text, mappings) if mappings else None
        intents.append(PanelIntent(kind="action_triggered", action_text=action.text, action_id=action_id))
        if inferred is not None and inferred.event_type:
            intents[-1] = intents[-1].model_copy(update={"event_type": inferred.event_type})
            if inferred.text and inferred.text not in mappings:
                mappings[inferred.text] = inferred
        receipts.append(f"✅ {action.text}")
        executed_now.append(action_id)

    # Freeform commands: clear status
    instruction_lower = (new_state.instruction_text or "").lower()
    clear_status = "clear status" in instruction_lower or "clear ai status" in instruction_lower

    if mappings:
        intents = enrich_panel_intents(intents, mappings)

    note_payload = {"uuid": note_id}
    if note_path:
        note_payload["path"] = note_path

    events: list[OutboxEvent] = []
    if new_state.spans or new_state.actions or new_state.instruction_text:
        panel_payload = {
            "note": note_payload,
            "instruction": new_state.instruction_text,
            "actions": [
                {"id": action.action_id, "label": action.text, "checked": action.checked} for action in new_state.actions
            ],
        }
        events.append(OutboxEvent(event="panel.intent.created", source="panel.agent", payload=panel_payload))
        events.append(OutboxEvent(event="panel.intent.executed", source="panel.agent", payload=panel_payload))
    for intent in intents:
        event = panel_intent_to_event(
            intent,
            mappings,
            note_id=note_id,
            instruction_text=new_state.instruction_text,
            note_path=note_path,
        )
        if event is not None:
            events.append(event)
            if intent.kind == "action_triggered" and intent.event_type:
                events.append(
                    OutboxEvent(
                        event="panel.action.triggered",
                        source="panel.agent",
                        payload={
                            "note": note_payload,
                            "action": {"id": intent.action_id, "label": intent.action_text},
                            "target_event": event.event,
                        },
                    )
                )

    updated_markdown = annotated_markdown
    ids_to_remove = set(executed_now) | remove_ids
    if ids_to_remove:
        updated_markdown = _remove_actions_from_markdown(updated_markdown, ids_to_remove)

    preferred_index = None
    if new_state.spans:
        _, end = new_state.spans[-1]
        preferred_index = end + 1
    updated_markdown = _write_receipts(
        updated_markdown,
        [entry for entry in receipts],
        clear=clear_status,
        preferred_index=preferred_index,
    )

    _upsert_executed_ids(note_id, executed_now)

    return PanelAgentResult(state=new_state, intents=intents, updated_markdown=updated_markdown, events=events)


__all__ = ["handle_note_update", "PanelAgentResult"]
