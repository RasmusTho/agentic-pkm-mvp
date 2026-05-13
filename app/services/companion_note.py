"""
Companion note service — system-owned identity file per vault note.

Path: vault/<system_dir>/companions/<uuid>.md
Contract: docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
Plan: docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md

Bounded field set (must NOT include review_state, maturity, kind, origin):
  uuid, source_ref, title, content_hash, ingest_state,
  last_ingested, created_by_instance, attachments[],
  identity_history[] (bounded to IDENTITY_HISTORY_MAX entries)

Healing log: vault/<system_dir>/heal_log.jsonl — append-only, conservative,
  one line per healing event with before/after and reason.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

_LEGACY_COMPANIONS_DIR = Path("_system/companions")
_LEGACY_HEAL_LOG_PATH = Path("_system/heal_log.jsonl")

# Matches ![[...]] embed syntax only — NOT plain [[note]] wiki-links.
_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")

# Maximum number of identity-history entries kept per companion note.
IDENTITY_HISTORY_MAX = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AttachmentRef:
    ref: str
    content_hash: str | None = None


@dataclass
class IdentityHistoryEntry:
    """One entry in a companion note's bounded identity-change history."""
    timestamp: str       # ISO 8601
    event: str           # "path_change" | "uuid_conflict" | "repair" | "cold_start" | "rebuild"
    before: dict         # snapshot of key identity fields before the event
    after: dict          # snapshot of key identity fields after the event
    reason: str          # human-readable explanation


@dataclass
class CompanionNote:
    uuid: str
    source_ref: str
    title: str
    content_hash: str
    ingest_state: str  # tracked | stale | soft_deleted
    last_ingested: str  # ISO 8601
    created_by_instance: str
    attachments: list[AttachmentRef] = field(default_factory=list)
    identity_history: list[IdentityHistoryEntry] = field(default_factory=list)


@dataclass
class ConflictLog:
    conflict: bool
    frontmatter_uuid: str
    companion_uuid: str
    winner: str
    reason: str


# ---------------------------------------------------------------------------
# Artifact identity triple (locked contract)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactIdentity:
    """
    The locked identity triple for a vault artifact.

    These three fields together are sufficient to establish continuity
    and rebuild runtime DB/index state from the file-based surfaces.

    - uuid:         canonical identity anchor (from frontmatter or companion)
    - vault_path:   vault-relative path (source_ref in companion)
    - content_hash: sha256 of stripped note body (tracks content version)
    """
    uuid: str
    vault_path: str
    content_hash: str


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def _companions_dir(vault_root: Path | None = None) -> Path:
    # Contract lock: companions are always under _system/companions.
    return _LEGACY_COMPANIONS_DIR


def _heal_log_path(vault_root: Path | None = None) -> Path:
    # Contract lock: heal log is always under _system/heal_log.jsonl.
    return _LEGACY_HEAL_LOG_PATH


def companion_path(uuid: str, vault_root: Path | None = None) -> Path:
    """Return the vault-relative path for a companion file."""
    return _companions_dir(vault_root) / f"{uuid}.md"


# ---------------------------------------------------------------------------
# Read / Write
# ---------------------------------------------------------------------------

def read_companion(vault_root: Path, uuid: str) -> CompanionNote | None:
    """Read companion note for uuid. Returns None if missing or unparseable."""
    path = vault_root / companion_path(uuid, vault_root)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        fm, _ = load_frontmatter(text)
    except Exception:
        return None
    return _fm_to_companion(fm)


def write_companion(vault_root: Path, companion: CompanionNote) -> None:
    """Write companion note to disk. Creates parent directories as needed."""
    path = vault_root / companion_path(companion.uuid, vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = _companion_to_fm(companion)
    content = dump_frontmatter(fm, "")
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def find_companion_by_content_hash(vault_root: Path, sha256: str) -> CompanionNote | None:
    """Scan all companions for one whose content_hash matches sha256."""
    companions_dir = vault_root / _companions_dir(vault_root)
    if not companions_dir.exists():
        return None
    for cand in companions_dir.glob("*.md"):
        try:
            fm, _ = load_frontmatter(cand.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(fm, dict) and fm.get("content_hash") == sha256:
            companion = _fm_to_companion(fm)
            if companion is not None:
                return companion
    return None


# ---------------------------------------------------------------------------
# Attachment scanning
# ---------------------------------------------------------------------------

def scan_attachments(text: str) -> list[AttachmentRef]:
    """
    Parse ![[...]] embed syntax from note body.
    Returns AttachmentRef list (content_hash=None; filled by caller if needed).
    Plain [[note]] wiki-links are ignored.
    """
    refs: list[AttachmentRef] = []
    seen: set[str] = set()
    for match in _EMBED_RE.finditer(text):
        raw = match.group(1)
        # Strip alias suffix: file.png|caption → file.png
        if "|" in raw:
            raw = raw.split("|", 1)[0]
        # Strip anchor: file.png#heading → file.png
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        ref = raw.strip()
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(AttachmentRef(ref=ref))
    return refs


# ---------------------------------------------------------------------------
# Healing — Part 3
# ---------------------------------------------------------------------------

def rebuild_companion_from_db(
    vault_root: Path,
    uuid: str,
    db_obj: dict,
    vault_note_fm: dict,
    *,
    source_ref: str = "",
    instance_id: str = "",
) -> CompanionNote:
    """
    Healing scenario B/C: companion missing but uuid is known.

    Uses db_obj fields when available, falls back to vault_note_fm.
    Always writes the result to disk.
    """
    resolved_source_ref = (
        db_obj.get("source_ref")
        or source_ref
        or vault_note_fm.get("source_ref", "")
    )
    resolved_title = (
        db_obj.get("title")
        or str(vault_note_fm.get("title", ""))
    )
    resolved_hash = db_obj.get("content_hash", "")

    companion = CompanionNote(
        uuid=uuid,
        source_ref=str(resolved_source_ref),
        title=str(resolved_title),
        content_hash=str(resolved_hash),
        ingest_state="tracked",
        last_ingested=_now_iso(),
        created_by_instance=instance_id,
    )
    write_companion(vault_root, companion)
    return companion


def repair_companion(
    vault_root: Path,
    uuid: str,
    *,
    source_ref: str = "",
    instance_id: str = "",
) -> CompanionNote:
    """
    Healing scenario D: companion file exists but is malformed, or is missing entirely.

    Conservative repair: valid existing fields are preserved; only missing/invalid
    required fields are filled with safe defaults.  Always writes the result to disk.
    """
    path = vault_root / companion_path(uuid, vault_root)
    existing_fm: dict = {}

    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            fm, _ = load_frontmatter(text)
            if isinstance(fm, dict):
                existing_fm = fm
        except Exception:
            pass

    # Preserve valid fields; fill gaps with safe defaults.
    resolved_source_ref = (
        str(existing_fm.get("source_ref", ""))
        or source_ref
    )
    resolved_title = str(existing_fm.get("title", ""))
    resolved_hash = str(existing_fm.get("content_hash", ""))
    resolved_state = str(existing_fm.get("ingest_state", "tracked"))
    if resolved_state not in {"tracked", "stale", "soft_deleted"}:
        resolved_state = "tracked"
    resolved_ingested = str(existing_fm.get("last_ingested", "") or _now_iso())
    resolved_instance = str(existing_fm.get("created_by_instance", "") or instance_id)

    # Parse existing attachments conservatively.
    attachments: list[AttachmentRef] = []
    for a in existing_fm.get("attachments") or []:
        if isinstance(a, dict) and a.get("ref"):
            attachments.append(AttachmentRef(
                ref=str(a["ref"]),
                content_hash=a.get("content_hash"),
            ))

    companion = CompanionNote(
        uuid=uuid,
        source_ref=resolved_source_ref,
        title=resolved_title,
        content_hash=resolved_hash,
        ingest_state=resolved_state,
        last_ingested=resolved_ingested,
        created_by_instance=resolved_instance,
        attachments=attachments,
    )
    write_companion(vault_root, companion)
    return companion


def resolve_uuid_conflict(
    frontmatter_uuid: str,
    companion_uuid: str,
) -> tuple[str, ConflictLog]:
    """
    Healing scenario E: vault note frontmatter.uuid ≠ companion.uuid.

    Frontmatter UUID wins by default (highest authority per ARTIFACT_MODEL_AND_LIFECYCLES).
    Returns (winner_uuid, ConflictLog).
    """
    if frontmatter_uuid == companion_uuid:
        return frontmatter_uuid, ConflictLog(
            conflict=False,
            frontmatter_uuid=frontmatter_uuid,
            companion_uuid=companion_uuid,
            winner=frontmatter_uuid,
            reason="no conflict — UUIDs match",
        )

    return frontmatter_uuid, ConflictLog(
        conflict=True,
        frontmatter_uuid=frontmatter_uuid,
        companion_uuid=companion_uuid,
        winner=frontmatter_uuid,
        reason=(
            "frontmatter UUID takes priority per ARTIFACT_MODEL_AND_LIFECYCLES "
            "healing priority order (step 1 > step 2); flagged for human review"
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _companion_to_fm(companion: CompanionNote) -> dict:
    fm: dict = {
        "uuid": companion.uuid,
        "source_ref": companion.source_ref,
        "title": companion.title,
        "content_hash": companion.content_hash,
        "ingest_state": companion.ingest_state,
        "last_ingested": companion.last_ingested,
        "created_by_instance": companion.created_by_instance,
    }
    if companion.attachments:
        fm["attachments"] = [
            {"ref": a.ref, "content_hash": a.content_hash}
            for a in companion.attachments
        ]
    if companion.identity_history:
        # Enforce IDENTITY_HISTORY_MAX: keep only the most recent entries.
        bounded = companion.identity_history[-IDENTITY_HISTORY_MAX:]
        fm["identity_history"] = [dataclasses.asdict(e) for e in bounded]
    return fm


def _fm_to_companion(fm: dict) -> CompanionNote | None:
    """Parse a frontmatter dict into a CompanionNote. Returns None if uuid missing."""
    if not isinstance(fm, dict):
        return None
    uuid = str(fm.get("uuid", "")).strip()
    if not uuid:
        return None
    attachments: list[AttachmentRef] = []
    for a in fm.get("attachments") or []:
        if isinstance(a, dict) and a.get("ref"):
            attachments.append(AttachmentRef(
                ref=str(a["ref"]),
                content_hash=a.get("content_hash"),
            ))
    identity_history: list[IdentityHistoryEntry] = []
    for entry in fm.get("identity_history") or []:
        if isinstance(entry, dict):
            try:
                identity_history.append(IdentityHistoryEntry(
                    timestamp=str(entry.get("timestamp", "")),
                    event=str(entry.get("event", "")),
                    before=entry.get("before") if isinstance(entry.get("before"), dict) else {},
                    after=entry.get("after") if isinstance(entry.get("after"), dict) else {},
                    reason=str(entry.get("reason", "")),
                ))
            except Exception:
                pass
    return CompanionNote(
        uuid=uuid,
        source_ref=str(fm.get("source_ref", "")),
        title=str(fm.get("title", "")),
        content_hash=str(fm.get("content_hash", "")),
        ingest_state=str(fm.get("ingest_state", "tracked")),
        last_ingested=str(fm.get("last_ingested", "")),
        created_by_instance=str(fm.get("created_by_instance", "")),
        attachments=attachments,
        identity_history=identity_history,
    )


__all__ = [
    "AttachmentRef",
    "CompanionNote",
    "ConflictLog",
    "IDENTITY_HISTORY_MAX",
    "IdentityHistoryEntry",
    "companion_path",
    "find_companion_by_content_hash",
    "read_companion",
    "rebuild_companion_from_db",
    "repair_companion",
    "resolve_uuid_conflict",
    "scan_attachments",
    "write_companion",
]
