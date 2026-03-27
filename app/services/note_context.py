"""
NoteContext service — runtime context assembler for agents.

Assembles a rich, multi-surface view of a vault note from:
  1. Companion note  (_system/companions/<uuid>.md)
  2. Vault note file (frontmatter + body)
  3. Runtime stores  (ObjectStore → classification; RelationIndex → links)

Agents get structured context instead of raw 800-char snippets.

Plan: docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.companion_note import AttachmentRef, read_companion
from scripts.yaml_roundtrip import load_frontmatter


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ContextBudget:
    """Controls how much context to assemble."""
    max_body_chars: int = 2000
    include_relations: bool = True
    include_attachments: bool = True
    include_history: bool = False


@dataclass
class NoteContext:
    """Structured, multi-surface context for a single vault note."""
    uuid: str
    source_ref: str
    content_hash: str
    ingest_state: str
    attachments: list[AttachmentRef]
    frontmatter: dict[str, Any]
    body: str
    body_truncated: bool
    outgoing_links: list[str]
    backlinks: list[str]
    classification: dict[str, Any] | None
    executed_actions: list[str]
    kind_policy: dict[str, Any]
    trust_level: str


class NoteContextError(Exception):
    """Raised when context cannot be assembled (e.g. companion missing)."""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_note_context(
    uuid: str,
    vault_root: Path,
    *,
    budget: ContextBudget | None = None,
    object_store: Any = None,
    relation_index: Any = None,
) -> NoteContext:
    """
    Assemble a NoteContext for the given note uuid.

    Reads companion note, vault note frontmatter/body, and optionally
    queries runtime stores for classification and relation data.

    Gracefully degrades when surfaces are missing:
    - Missing companion → NoteContextError (companion is the identity anchor)
    - Missing vault note → empty frontmatter/body
    - Missing stores → classification=None, empty links
    """
    if budget is None:
        budget = ContextBudget()

    # --- Surface 1: Companion note (required identity anchor) ---
    companion = read_companion(vault_root, uuid)
    if companion is None:
        raise NoteContextError(f"No companion note found for uuid={uuid}")

    # --- Surface 2: Vault note file ---
    frontmatter, body, body_truncated = _read_vault_note(
        vault_root, companion.source_ref, budget.max_body_chars,
    )

    # --- Attachments ---
    attachments = list(companion.attachments) if budget.include_attachments else []

    # --- Trust level from frontmatter ---
    trust_level = str(frontmatter.get("trust", ""))

    # --- Surface 3: Runtime stores ---
    classification = _query_classification(uuid, object_store)
    executed_actions = _query_executed_actions(uuid, object_store)

    if budget.include_relations and relation_index is not None:
        outgoing_links = _query_outgoing_links(uuid, relation_index)
    else:
        outgoing_links = []

    # Backlinks not yet implemented in the relation index; always empty.
    backlinks: list[str] = []

    return NoteContext(
        uuid=uuid,
        source_ref=companion.source_ref,
        content_hash=companion.content_hash,
        ingest_state=companion.ingest_state,
        attachments=attachments,
        frontmatter=frontmatter,
        body=body,
        body_truncated=body_truncated,
        outgoing_links=outgoing_links,
        backlinks=backlinks,
        classification=classification,
        executed_actions=executed_actions,
        kind_policy={},
        trust_level=trust_level,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_vault_note(
    vault_root: Path, source_ref: str, max_body_chars: int,
) -> tuple[dict[str, Any], str, bool]:
    """Read vault note frontmatter and body. Returns ({}, "", False) if missing."""
    note_path = vault_root / source_ref
    if not note_path.exists():
        return {}, "", False

    try:
        text = note_path.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
    except Exception:
        return {}, "", False

    truncated = len(body) > max_body_chars
    if truncated:
        body = body[:max_body_chars]

    return frontmatter, body, truncated


def _query_classification(uuid: str, object_store: Any) -> dict[str, Any] | None:
    """Extract classification from the object store payload, if available."""
    if object_store is None:
        return None
    try:
        record = object_store.get(UUID(uuid))
        if record is None:
            return None
        payload = record.get("payload") if isinstance(record, dict) else {}
        if not isinstance(payload, dict):
            return None
        return payload.get("classification")
    except Exception:
        return None


def _query_executed_actions(uuid: str, object_store: Any) -> list[str]:
    """Extract executed actions from the object store payload, if available."""
    if object_store is None:
        return []
    try:
        record = object_store.get(UUID(uuid))
        if record is None:
            return []
        payload = record.get("payload") if isinstance(record, dict) else {}
        if not isinstance(payload, dict):
            return []
        actions = payload.get("executed_actions")
        if isinstance(actions, list):
            return [str(a) for a in actions]
        return []
    except Exception:
        return []


def _query_outgoing_links(uuid: str, relation_index: Any) -> list[str]:
    """Query outgoing links from the relation index."""
    try:
        # Use the protocol-style neighbors() method with a generic rel
        # The MemoryRelationIndex stores links by rel type, so we query
        # all relation types by checking has_any first, then neighbors.
        src = UUID(uuid)

        # Try to get all neighbors across all relation types.
        # The RelationIndex protocol exposes neighbors(src, rel=..., k=...)
        # We don't know all rel types, so we use a broad approach:
        # check if any relations exist, then gather links.
        if not relation_index.has_any(src):
            return []

        # The MemoryRelationIndex._links is keyed by rel type.
        # Use duck typing to iterate all relation types if available.
        links_map = getattr(relation_index, "_links", None)
        if links_map is not None:
            result: list[str] = []
            seen: set[str] = set()
            for rel_type, rel_map in links_map.items():
                for entry in rel_map.get(src, []):
                    dst_str = str(entry["dst"])
                    if dst_str not in seen:
                        seen.add(dst_str)
                        result.append(dst_str)
            return result

        # Fallback: try the neighbors method with common rel types
        return []
    except Exception:
        return []


__all__ = [
    "AttachmentRef",
    "ContextBudget",
    "NoteContext",
    "NoteContextError",
    "build_note_context",
]
