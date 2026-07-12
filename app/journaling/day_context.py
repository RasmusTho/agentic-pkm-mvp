"""Assemble the deterministic, read-only context for an evening reflection.

The assembler deliberately reads durable source artifacts only.  It does not
register the bundle, call a write guard, or otherwise acquire write authority.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.context_bundles.construction import build_inspectable_bundle
from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)
from app.knowledge_acquisition.candidate_writeback import ARTIFACT_CLASS, DEFAULT_SOURCES_DIR
from app.receipts.decision_receipt_log import decisions_receipts_dir, iter_decision_receipts
from app.services.commitment_persistence import commitment_artifact_path, load_commitments
from app.vault.manager import VaultContext
from scripts.yaml_roundtrip import load_frontmatter

SourceName = Literal["commitments", "decision_receipts", "captures"]
SOURCE_NAMES: tuple[SourceName, ...] = (
    "commitments",
    "decision_receipts",
    "captures",
)


class DayContextItem(BaseModel):
    """One source fact and the durable reference needed to inspect it."""

    provenance_ref: str
    content: dict[str, object]


class DayContextSection(BaseModel):
    """A source's facts, or an explicit statement that it could not be read."""

    status: Literal["available", "degraded"]
    items: tuple[DayContextItem, ...] = ()
    note: str | None = None

    def __getitem__(self, index: int) -> DayContextItem:
        return self.items[index]


class DayContextBundle(ContextBundle):
    """A ContextBundle-shaped envelope with journaling-specific source sections."""

    for_date: date
    degraded_sources: tuple[SourceName, ...] = ()
    sections: dict[SourceName, DayContextSection]

    @property
    def may_write(self) -> bool:
        """Compatibility shorthand; authority remains in the ContextBundle envelope."""
        return self.authority.may_write


def assemble_day_context(*, vault_context: VaultContext, for_date: date) -> DayContextBundle:
    """Return today's durable facts as a deterministic, provenance-cited bundle.

    Each source is isolated: a malformed artifact or I/O failure degrades only that
    source and is named in ``degraded_sources``.  An available source with no facts
    remains available and empty; it is never confused with a failed source.
    """
    vault_root = _vault_root(vault_context)
    readers = {
        "commitments": lambda: _read_commitments(vault_context, vault_root, for_date),
        "decision_receipts": lambda: _read_decision_receipts(vault_root, for_date),
        "captures": lambda: _read_captures(vault_root, for_date),
    }
    sections: dict[SourceName, DayContextSection] = {}
    degraded: list[SourceName] = []
    included: list[IncludedItem] = []
    for name in SOURCE_NAMES:
        try:
            items, source_items = readers[name]()
        except Exception:  # source failures are intentionally fail-legible
            sections[name] = DayContextSection(
                status="degraded", note=f"{name} could not be read"
            )
            degraded.append(name)
            continue
        sections[name] = DayContextSection(status="available", items=tuple(items))
        included.extend(source_items)

    # This production constructor remains the authoritative source for the envelope
    # shape.  Its demonstration content is replaced with the real, derived facts.
    base = build_inspectable_bundle(f"journaling-day-context-{for_date.isoformat()}")
    payload = base.model_dump()
    payload.update(
        created_at=datetime.combine(for_date, time.min, tzinfo=timezone.utc),
        trigger=BundleTrigger(type="journaling.day_context", source="durable-day-sources"),
        intended_use=["journaling_reflection"],
        scope=BundleScope(vaults=[str(vault_root)]),
        included=included,
        excluded=[],
        authority=AuthorityFlags(may_write=False),
        expiry=ExpiryPosture(reason=f"derived for local day {for_date.isoformat()}"),
        for_date=for_date,
        degraded_sources=tuple(degraded),
        sections=sections,
    )
    return DayContextBundle(**payload)


def _read_commitments(
    vault_context: VaultContext, vault_root: Path, for_date: date
) -> tuple[list[DayContextItem], list[IncludedItem]]:
    day_items: list[DayContextItem] = []
    included: list[IncludedItem] = []
    for record in load_commitments(vault_context=vault_context):
        artifact_path = commitment_artifact_path(record.commitment_id, vault_root)
        changed = datetime.fromtimestamp(
            (vault_root / artifact_path).stat().st_mtime, tz=timezone.utc
        ).astimezone()
        if changed.date() != for_date:
            continue
        content = {
            "commitment_id": record.commitment_id,
            "state": record.state,
            "target_ref": record.target_ref,
            "summary": record.summary,
            "changed_at": changed.isoformat(),
        }
        day_items.append(DayContextItem(provenance_ref=artifact_path, content=content))
        included.append(
            IncludedItem(
                artifact_id=record.commitment_id,
                path=artifact_path,
                reason="commitment artifact changed during the requested local day",
                source_role="commitment",
                provenance=ItemProvenance(origin=artifact_path),
            )
        )
    paired = sorted(zip(day_items, included), key=lambda pair: pair[0].provenance_ref)
    return [pair[0] for pair in paired], [pair[1] for pair in paired]


def _read_decision_receipts(
    vault_root: Path, for_date: date
) -> tuple[list[DayContextItem], list[IncludedItem]]:
    paired: list[tuple[DayContextItem, IncludedItem]] = []
    for record in iter_decision_receipts(vault_root):
        created = _parse_timestamp(record.get("created_at"))
        if created.astimezone().date() != for_date:
            continue
        object_id = _required_text(record, "object_id")
        key = _required_text(record, "key")
        vault_uuid = record.get("vault_uuid")
        if vault_uuid is not None and not isinstance(vault_uuid, str):
            raise ValueError("receipt vault_uuid must be text or null")
        receipt_path = (
            decisions_receipts_dir(vault_root)
            / f"decisions-{created.strftime('%Y%m')}.jsonl"
        ).relative_to(vault_root).as_posix()
        provenance_ref = f"{receipt_path}#{object_id}:{key}:{created.isoformat()}"
        content = {
            "object_id": object_id,
            "vault_uuid": vault_uuid,
            "key": key,
            "created_at": created.isoformat(),
        }
        paired.append(
            (
                DayContextItem(provenance_ref=provenance_ref, content=content),
                IncludedItem(
                    artifact_id=f"decision-receipt:{object_id}:{key}",
                    path=receipt_path,
                    reason="decision receipt created during the requested local day",
                    source_role="decision_receipt",
                    provenance=ItemProvenance(origin=provenance_ref),
                ),
            )
        )
    paired.sort(key=lambda pair: pair[0].provenance_ref)
    return [pair[0] for pair in paired], [pair[1] for pair in paired]


def _read_captures(
    vault_root: Path, for_date: date
) -> tuple[list[DayContextItem], list[IncludedItem]]:
    paired: list[tuple[DayContextItem, IncludedItem]] = []
    sources_dir = vault_root / DEFAULT_SOURCES_DIR
    if not sources_dir.exists():
        return [], []
    for path in sorted(sources_dir.glob("*.md")):
        frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        if not isinstance(frontmatter, dict) or frontmatter.get("artifact_class") != ARTIFACT_CLASS:
            continue
        created = _parse_timestamp(frontmatter.get("created"))
        if created.astimezone().date() != for_date:
            continue
        provenance = frontmatter.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("candidate provenance must be an object")
        content_identity = _required_text(provenance, "content_identity")
        artifact_path = path.relative_to(vault_root).as_posix()
        content = {
            "content_identity": content_identity,
            "created_at": created.isoformat(),
            "source_kind": provenance.get("source_kind"),
            "url": provenance.get("url"),
        }
        paired.append(
            (
                DayContextItem(provenance_ref=artifact_path, content=content),
                IncludedItem(
                    artifact_id=content_identity,
                    path=artifact_path,
                    reason="candidate capture created during the requested local day",
                    source_role="capture",
                    provenance=ItemProvenance(origin=artifact_path),
                ),
            )
        )
    paired.sort(key=lambda pair: pair[0].provenance_ref)
    return [pair[0] for pair in paired], [pair[1] for pair in paired]


def _vault_root(vault_context: VaultContext) -> Path:
    if not vault_context.active_vault_path:
        raise ValueError("assemble_day_context requires an active vault path")
    return Path(vault_context.active_vault_path).expanduser().resolve()


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


__all__ = [
    "DayContextBundle",
    "DayContextItem",
    "DayContextSection",
    "assemble_day_context",
]
