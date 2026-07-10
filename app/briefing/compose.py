"""Compose and read the derived, read-only Daily Briefing note.

The briefing consumes the three existing durable source projections exactly once,
normalizes them into a deterministic schema, and atomically replaces one system-owned
dated note. It never writes back to a source or acquires authority over source state.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

import yaml

from app.domain.commitments import CommitmentRecord, query_next_and_waiting_commitments
from app.knowledge.contracts import WriteReceipt
from app.knowledge.write_ops import write_note_relative
from app.receipts.decision_receipt_log import iter_decision_receipts
from app.relevance.now_surface import collect_now_moments
from app.services.commitment_persistence import commitment_artifact_path, load_commitments
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

BRIEFING_ARTIFACT_CLASS = "daily_briefing"
BRIEFING_SCHEMA_VERSION = 1
BRIEFING_WRITE_ACTION = "briefing.write_note"
BRIEFINGS_DIR_NAME = "briefings"

SectionName: TypeAlias = Literal["commitments", "moments", "decision_receipts"]
SectionStatus: TypeAlias = Literal["available", "degraded"]
SECTION_ORDER: tuple[SectionName, ...] = (
    "commitments",
    "moments",
    "decision_receipts",
)
SECTION_TITLES: dict[SectionName, str] = {
    "commitments": "Commitments",
    "moments": "Moments",
    "decision_receipts": "Decision receipts",
}


class BriefingReadError(RuntimeError):
    """Raised when a present briefing note cannot be read as schema v1."""


class _InvalidSourceRecord(ValueError):
    """Internal stable classification for a malformed public-reader result."""


@dataclass(frozen=True)
class CommitmentBriefingItem:
    commitment_id: str
    commitment_kind: str
    state: str
    summary: str
    artifact_path: str
    target_ref: str | None = None


@dataclass(frozen=True)
class MomentBriefingItem:
    moment_id: str
    title: str
    need_basis: str
    urgency_band: str
    artifact_path: str
    surfaced_refs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DecisionReceiptBriefingItem:
    object_id: str
    vault_uuid: str | None
    key: str
    created_at: str
    receipt_path: str


BriefingItem: TypeAlias = (
    CommitmentBriefingItem | MomentBriefingItem | DecisionReceiptBriefingItem
)


@dataclass(frozen=True)
class BriefingSection:
    status: SectionStatus
    items: tuple[BriefingItem, ...]
    reason: str | None = None


@dataclass(frozen=True)
class BriefingNote:
    briefing_date: date
    degraded_sections: tuple[SectionName, ...]
    sections: dict[SectionName, BriefingSection]


def compose_briefing(
    *,
    vault_context: VaultContext,
    for_date: date,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> WriteReceipt:
    """Compose and atomically replace the dated briefing artifact.

    Source failures are isolated to their section. Addressing, guard, and write
    failures are global and leave the previous dated note intact.
    """

    vault_root = _vault_root(vault_context)
    system_dir = get_vault_system_dir_rel(vault_root)
    note_rel_path = (
        PurePosixPath(system_dir) / BRIEFINGS_DIR_NAME / f"{for_date.isoformat()}.md"
    ).as_posix()

    sections: dict[SectionName, BriefingSection] = {
        "commitments": _read_section(
            lambda: _read_commitments(vault_context=vault_context, vault_root=vault_root)
        ),
        "moments": _read_section(
            lambda: _read_moments(
                vault_context=vault_context,
                system_dir=system_dir,
            )
        ),
        "decision_receipts": _read_section(
            lambda: _read_decision_receipts(
                vault_root=vault_root,
                system_dir=system_dir,
                for_date=for_date,
            )
        ),
    }
    degraded = tuple(
        section_name
        for section_name in SECTION_ORDER
        if sections[section_name].status == "degraded"
    )
    note = BriefingNote(
        briefing_date=for_date,
        degraded_sections=degraded,
        sections=sections,
    )
    content = _render_note(note)

    # The production seam is guarded before the adapter creates a directory or temp file.
    write_guard.assert_writes_allowed(BRIEFING_WRITE_ACTION)
    return _atomic_write(
        vault_root=vault_root,
        note_rel_path=note_rel_path,
        content=content,
        write_guard=write_guard,
    )


def load_briefing(
    *,
    vault_context: VaultContext,
    for_date: date,
) -> BriefingNote | None:
    """Load one schema-v1 briefing, returning ``None`` only when it is absent."""

    vault_root = _vault_root(vault_context)
    system_dir = get_vault_system_dir_rel(vault_root)
    target = vault_root / system_dir / BRIEFINGS_DIR_NAME / f"{for_date.isoformat()}.md"
    if not target.exists():
        return None
    try:
        content = target.read_text(encoding="utf-8")
        frontmatter = _load_frontmatter(content)
        return _note_from_frontmatter(frontmatter, expected_date=for_date)
    except BriefingReadError:
        raise
    except Exception as exc:
        raise BriefingReadError("briefing note is unreadable") from exc


def _atomic_write(
    *,
    vault_root: Path,
    note_rel_path: str,
    content: str,
    write_guard: WriteGuard,
) -> WriteReceipt:
    """Stage through the FS adapter, then atomically install its complete file.

    The adapter receives the final locator even though its temporary vault root is
    private to this write. Its returned receipt therefore already names the final
    target and is returned unchanged after ``os.replace``.
    """

    target = (vault_root / note_rel_path).resolve()
    target.relative_to(vault_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    ) as staging_dir:
        staging_root = Path(staging_dir)
        receipt = write_note_relative(
            note_rel_path,
            content,
            vault_root=staging_root,
            action=BRIEFING_WRITE_ACTION,
            write_guard=write_guard,
        )
        staged_file = staging_root / note_rel_path
        os.replace(staged_file, target)
        return receipt


def _vault_root(context: VaultContext) -> Path:
    if not context.is_selected or not context.active_vault_path:
        raise ValueError("compose_briefing requires a selected vault context")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("compose_briefing requires an existing vault root")
    return root


def _read_section(reader: Any) -> BriefingSection:
    try:
        items = reader()
    except _InvalidSourceRecord:
        return BriefingSection(status="degraded", items=(), reason="invalid_source_record")
    except Exception:
        return BriefingSection(status="degraded", items=(), reason="source_read_failed")
    return BriefingSection(status="available", items=tuple(items))


def _read_commitments(
    *,
    vault_context: VaultContext,
    vault_root: Path,
) -> tuple[CommitmentBriefingItem, ...]:
    records = load_commitments(vault_context=vault_context)
    if not isinstance(records, list) or not all(
        isinstance(record, CommitmentRecord) for record in records
    ):
        raise _InvalidSourceRecord
    queried = query_next_and_waiting_commitments(records)
    selected: dict[str, tuple[int, CommitmentRecord]] = {}
    for group, group_records in enumerate((queried.next_items, queried.waiting_items)):
        for record in group_records:
            selected.setdefault(record.commitment_id, (group, record))
    for record in records:
        if record.commitment_kind == "review_return" and record.state != "done":
            selected.setdefault(record.commitment_id, (2, record))

    items: list[CommitmentBriefingItem] = []
    for _group, record in sorted(
        selected.values(), key=lambda pair: (pair[0], pair[1].commitment_id)
    ):
        if not record.commitment_id.strip():
            raise _InvalidSourceRecord
        items.append(
            CommitmentBriefingItem(
                commitment_id=record.commitment_id,
                commitment_kind=record.commitment_kind,
                state=record.state,
                summary=_one_line(record.summary or record.commitment_id),
                artifact_path=commitment_artifact_path(record.commitment_id, vault_root),
                target_ref=record.target_ref,
            )
        )
    return tuple(items)


def _read_moments(
    *,
    vault_context: VaultContext,
    system_dir: str,
) -> tuple[MomentBriefingItem, ...]:
    records = collect_now_moments(vault_context)
    if not isinstance(records, list):
        raise _InvalidSourceRecord
    items: list[MomentBriefingItem] = []
    for record in records:
        if not isinstance(record, dict):
            raise _InvalidSourceRecord
        moment_id = _required_text(record, "moment_id")
        title = _required_text(record, "title")
        need_basis = _required_text(record, "need_basis")
        urgency_band = _required_text(record, "urgency_band")
        raw_refs = record.get("surfaced_refs")
        if not isinstance(raw_refs, list):
            raise _InvalidSourceRecord
        surfaced_refs: list[dict[str, Any]] = []
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, dict):
                raise _InvalidSourceRecord
            ref = _required_text(raw_ref, "ref")
            why = _required_text(raw_ref, "why")
            normalized: dict[str, Any] = {"ref": ref, "why": _one_line(why)}
            uuid = raw_ref.get("uuid")
            if uuid is not None:
                if not isinstance(uuid, str) or not uuid.strip():
                    raise _InvalidSourceRecord
                normalized["uuid"] = uuid
            surfaced_refs.append(normalized)
        items.append(
            MomentBriefingItem(
                moment_id=moment_id,
                title=_one_line(title),
                need_basis=need_basis,
                urgency_band=urgency_band,
                artifact_path=(
                    PurePosixPath(system_dir) / "moments" / f"{moment_id}.md"
                ).as_posix(),
                surfaced_refs=tuple(surfaced_refs),
            )
        )
    urgency_order = {"routine": 0, "timely": 1, "pressing": 2, "critical": 3}
    items.sort(key=lambda item: (-urgency_order.get(item.urgency_band, -1), item.moment_id))
    return tuple(items)


def _read_decision_receipts(
    *,
    vault_root: Path,
    system_dir: str,
    for_date: date,
) -> tuple[DecisionReceiptBriefingItem, ...]:
    records = iter_decision_receipts(vault_root)
    if not isinstance(records, list):
        raise _InvalidSourceRecord
    window_end = datetime.combine(for_date, time.min, tzinfo=timezone.utc)
    window_start = window_end - timedelta(days=1)
    items: list[DecisionReceiptBriefingItem] = []
    for record in records:
        if not isinstance(record, dict):
            raise _InvalidSourceRecord
        object_id = _required_text(record, "object_id")
        key = _required_text(record, "key")
        created = _parse_datetime(_required_text(record, "created_at"))
        raw_uuid = record.get("vault_uuid")
        if raw_uuid is not None and (not isinstance(raw_uuid, str) or not raw_uuid.strip()):
            raise _InvalidSourceRecord
        if not window_start <= created < window_end:
            continue
        items.append(
            DecisionReceiptBriefingItem(
                object_id=object_id,
                vault_uuid=raw_uuid,
                key=key,
                created_at=_format_utc(created),
                receipt_path=(
                    PurePosixPath(system_dir)
                    / "receipts"
                    / "decisions"
                    / f"decisions-{created.strftime('%Y%m')}.jsonl"
                ).as_posix(),
            )
        )
    items.sort(
        key=lambda item: (
            item.created_at,
            item.key,
            item.object_id,
            item.vault_uuid or "",
        )
    )
    return tuple(items)


def _render_note(note: BriefingNote) -> str:
    frontmatter: dict[str, Any] = {
        "artifact_class": BRIEFING_ARTIFACT_CLASS,
        "schema_version": BRIEFING_SCHEMA_VERSION,
        "agent_maintained": True,
        "read_only": True,
        "authority_role": "derived",
        "briefing_date": note.briefing_date.isoformat(),
        "degraded_sections": list(note.degraded_sections),
        "sections": {
            name: _section_to_mapping(note.sections[name]) for name in SECTION_ORDER
        },
    }
    body = [
        f"# Daily Briefing — {note.briefing_date.isoformat()}",
        "",
        "> Derived, read-only briefing. Source artifacts remain authoritative.",
    ]
    for name in SECTION_ORDER:
        section = note.sections[name]
        body.extend(["", f"## {SECTION_TITLES[name]}", ""])
        if section.status == "degraded":
            body.append(f"This section could not be generated ({section.reason}).")
        elif not section.items:
            body.append("No items.")
        else:
            body.extend(_render_items(section.items))
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    rendered_body = "\n".join(body)
    return f"---\n{yaml_text}---\n{rendered_body}\n"


def _section_to_mapping(section: BriefingSection) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": section.status}
    if section.reason is not None:
        payload["reason"] = section.reason
    payload["items"] = [_item_to_mapping(item) for item in section.items]
    return payload


def _item_to_mapping(item: BriefingItem) -> dict[str, Any]:
    if isinstance(item, CommitmentBriefingItem):
        payload: dict[str, Any] = {
            "source": "commitment",
            "commitment_id": item.commitment_id,
            "commitment_kind": item.commitment_kind,
            "state": item.state,
            "summary": item.summary,
            "artifact_path": item.artifact_path,
        }
        if item.target_ref is not None:
            payload["target_ref"] = item.target_ref
        return payload
    if isinstance(item, MomentBriefingItem):
        return {
            "source": "moment",
            "moment_id": item.moment_id,
            "title": item.title,
            "need_basis": item.need_basis,
            "urgency_band": item.urgency_band,
            "artifact_path": item.artifact_path,
            "surfaced_refs": [dict(ref) for ref in item.surfaced_refs],
        }
    return {
        "source": "decision_receipt",
        "object_id": item.object_id,
        "vault_uuid": item.vault_uuid,
        "key": item.key,
        "created_at": item.created_at,
        "receipt_path": item.receipt_path,
    }


def _render_items(items: tuple[BriefingItem, ...]) -> list[str]:
    lines: list[str] = []
    for item in items:
        if isinstance(item, CommitmentBriefingItem):
            lines.append(f"- {item.summary} [{item.state}]")
            lines.append(f"  - Provenance: {item.artifact_path}")
            if item.target_ref is not None:
                lines.append(f"  - Target ref: {item.target_ref}")
        elif isinstance(item, MomentBriefingItem):
            lines.append(f"- {item.title} [{item.urgency_band}]")
            lines.append(f"  - Provenance: {item.artifact_path}")
            for ref in item.surfaced_refs:
                lines.append(f"  - Surfaced ref: {ref['ref']} — {ref['why']}")
        else:
            lines.append(f"- {item.key} ({item.created_at})")
            lines.append(
                "  - Provenance: "
                f"{item.receipt_path} · object_id={item.object_id} · "
                f"vault_uuid={item.vault_uuid if item.vault_uuid is not None else 'null'}"
            )
    return lines


def _load_frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        raise BriefingReadError("briefing note has no frontmatter")
    parts = content.split("---", 2)
    if len(parts) != 3:
        raise BriefingReadError("briefing note has malformed frontmatter")
    try:
        payload = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise BriefingReadError("briefing frontmatter is invalid") from exc
    if not isinstance(payload, dict):
        raise BriefingReadError("briefing frontmatter must be a mapping")
    return payload


def _note_from_frontmatter(
    frontmatter: dict[str, Any], *, expected_date: date
) -> BriefingNote:
    required_identity = {
        "artifact_class": BRIEFING_ARTIFACT_CLASS,
        "schema_version": BRIEFING_SCHEMA_VERSION,
        "agent_maintained": True,
        "read_only": True,
        "authority_role": "derived",
        "briefing_date": expected_date.isoformat(),
    }
    if any(frontmatter.get(key) != value for key, value in required_identity.items()):
        raise BriefingReadError("briefing identity or schema is incompatible")
    degraded_raw = frontmatter.get("degraded_sections")
    sections_raw = frontmatter.get("sections")
    if not isinstance(degraded_raw, list) or not isinstance(sections_raw, dict):
        raise BriefingReadError("briefing sections are invalid")
    if any(name not in SECTION_ORDER for name in degraded_raw):
        raise BriefingReadError("briefing degraded sections are invalid")
    degraded = tuple(name for name in SECTION_ORDER if name in degraded_raw)
    sections: dict[SectionName, BriefingSection] = {}
    for name in SECTION_ORDER:
        raw = sections_raw.get(name)
        if not isinstance(raw, dict):
            raise BriefingReadError("briefing section is missing")
        status = raw.get("status")
        reason = raw.get("reason")
        raw_items = raw.get("items")
        if status not in ("available", "degraded") or not isinstance(raw_items, list):
            raise BriefingReadError("briefing section shape is invalid")
        if reason is not None and not isinstance(reason, str):
            raise BriefingReadError("briefing section reason is invalid")
        items = tuple(_item_from_mapping(name, item) for item in raw_items)
        if status == "degraded" and items:
            raise BriefingReadError("degraded briefing section must have no items")
        sections[name] = BriefingSection(status=status, items=items, reason=reason)
    actual_degraded = tuple(
        name for name in SECTION_ORDER if sections[name].status == "degraded"
    )
    if actual_degraded != degraded:
        raise BriefingReadError("briefing degraded section markers disagree")
    return BriefingNote(
        briefing_date=expected_date,
        degraded_sections=degraded,
        sections=sections,
    )


def _item_from_mapping(name: SectionName, raw: Any) -> BriefingItem:
    if not isinstance(raw, dict):
        raise BriefingReadError("briefing item must be a mapping")
    try:
        if name == "commitments" and raw.get("source") == "commitment":
            return CommitmentBriefingItem(
                commitment_id=_required_text(raw, "commitment_id"),
                commitment_kind=_required_text(raw, "commitment_kind"),
                state=_required_text(raw, "state"),
                summary=_required_text(raw, "summary"),
                artifact_path=_required_text(raw, "artifact_path"),
                target_ref=_optional_text(raw, "target_ref"),
            )
        if name == "moments" and raw.get("source") == "moment":
            refs = raw.get("surfaced_refs")
            if not isinstance(refs, list) or not all(isinstance(ref, dict) for ref in refs):
                raise _InvalidSourceRecord
            return MomentBriefingItem(
                moment_id=_required_text(raw, "moment_id"),
                title=_required_text(raw, "title"),
                need_basis=_required_text(raw, "need_basis"),
                urgency_band=_required_text(raw, "urgency_band"),
                artifact_path=_required_text(raw, "artifact_path"),
                surfaced_refs=tuple(dict(ref) for ref in refs),
            )
        if name == "decision_receipts" and raw.get("source") == "decision_receipt":
            vault_uuid = raw.get("vault_uuid")
            if vault_uuid is not None and not isinstance(vault_uuid, str):
                raise _InvalidSourceRecord
            return DecisionReceiptBriefingItem(
                object_id=_required_text(raw, "object_id"),
                vault_uuid=vault_uuid,
                key=_required_text(raw, "key"),
                created_at=_required_text(raw, "created_at"),
                receipt_path=_required_text(raw, "receipt_path"),
            )
    except _InvalidSourceRecord as exc:
        raise BriefingReadError("briefing item shape is invalid") from exc
    raise BriefingReadError("briefing item discriminator is invalid")


def _required_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _InvalidSourceRecord
    return value.strip()


def _optional_text(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _InvalidSourceRecord
    return value.strip()


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _InvalidSourceRecord from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _InvalidSourceRecord
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _one_line(value: str) -> str:
    return " ".join(value.split())


__all__ = [
    "BRIEFING_WRITE_ACTION",
    "BriefingNote",
    "BriefingReadError",
    "BriefingSection",
    "CommitmentBriefingItem",
    "DecisionReceiptBriefingItem",
    "MomentBriefingItem",
    "compose_briefing",
    "load_briefing",
]
