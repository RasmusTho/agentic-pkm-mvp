"""NoteContext service — assembles rich, budget-constrained context for agents.

Reads from multiple surfaces (vault note, companion/metadata mirror, object store,
decisions store, relation index) and produces a structured, truncatable context
that replaces ad-hoc 800-char snippets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.agent.models import ContextItem
from app.services.note_log import note_log_path
from app.stores.base import DecisionsStore, ObjectStore, RelationIndex


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

DEFAULT_BUDGET_CHARS = 8_000  # ~2 000 tokens at 0.25 tok/char


@dataclass(frozen=True)
class ContextBudget:
    """Character-based budget with optional per-section caps."""

    total: int = DEFAULT_BUDGET_CHARS
    frontmatter: int | None = None
    body: int | None = None
    companion: int | None = None
    decisions: int | None = None
    relations: int | None = None

    def cap_for(self, section: str) -> int | None:
        return getattr(self, section, None)


# ---------------------------------------------------------------------------
# Section / Context models
# ---------------------------------------------------------------------------

TRUNCATED_MARKER = "[truncated]"

# Priority order — higher-priority sections are filled first.
SECTION_PRIORITY = ("frontmatter", "body", "companion", "decisions", "relations")


@dataclass
class NoteContextSection:
    name: str
    text: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    truncated: bool = False


@dataclass
class NoteContext:
    note_uuid: str
    sections: list[NoteContextSection] = field(default_factory=list)
    total_chars: int = 0

    # ------------------------------------------------------------------ #
    # Conversion to AgentState-compatible ContextItems
    # ------------------------------------------------------------------ #
    def to_context_items(self) -> list[ContextItem]:
        items: list[ContextItem] = []
        for sec in self.sections:
            if not sec.text:
                continue
            items.append(
                ContextItem(
                    id=f"{self.note_uuid}:{sec.name}",
                    text=sec.text,
                    tags=list(sec.tags),
                    source=sec.source or sec.name,
                )
            )
        return items


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_note(path: Path) -> tuple[dict[str, Any], str]:
    """Read a vault/companion note, returning (frontmatter, body)."""
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
        else:
            frontmatter = {}
            body = raw
    else:
        frontmatter = {}
        body = raw
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Truncate *text* to at most *limit* chars, appending a marker if cut."""
    if len(text) <= limit:
        return text, False
    cutoff = max(0, limit - len(TRUNCATED_MARKER))
    return text[:cutoff] + TRUNCATED_MARKER, True


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

class NoteContextAssembler:
    """Assembles a :class:`NoteContext` from all available surfaces.

    Dependencies are injected explicitly so the class is trivially testable
    without global singletons.
    """

    def __init__(
        self,
        *,
        vault_root: Path,
        object_store: ObjectStore | None = None,
        decisions_store: DecisionsStore | None = None,
        relation_index: RelationIndex | None = None,
        budget: ContextBudget | None = None,
    ) -> None:
        self.vault_root = vault_root
        self.object_store = object_store
        self.decisions_store = decisions_store
        self.relation_index = relation_index
        self.budget = budget or ContextBudget()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def assemble(
        self,
        note_uuid: str,
        vault_relative_path: str | Path,
        *,
        decision_keys: list[str] | None = None,
    ) -> NoteContext:
        """Build a budget-constrained :class:`NoteContext` for *note_uuid*."""
        remaining = self.budget.total
        ctx = NoteContext(note_uuid=note_uuid)

        # Collect raw section texts keyed by section name.
        raw: dict[str, tuple[str, list[str], str]] = {}  # name -> (text, tags, source)

        # --- vault note ------------------------------------------------
        fm, body = self._read_vault_note(vault_relative_path)
        if fm:
            fm_text = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
            raw["frontmatter"] = (fm_text, list(fm.get("tags", []) or []), "vault:frontmatter")
        if body:
            raw["body"] = (body, [], "vault:body")

        # --- companion / metadata mirror --------------------------------
        companion_text = self._read_companion(note_uuid, vault_relative_path)
        if companion_text:
            raw["companion"] = (companion_text, [], "companion")

        # --- object store -----------------------------------------------
        # Object-store data is folded into the frontmatter section as
        # supplementary metadata rather than a standalone section.

        # --- decisions --------------------------------------------------
        decisions_text = self._read_decisions(note_uuid, decision_keys or [])
        if decisions_text:
            raw["decisions"] = (decisions_text, [], "decisions")

        # --- relations --------------------------------------------------
        relations_text = self._read_relations(note_uuid)
        if relations_text:
            raw["relations"] = (relations_text, [], "relations")

        # --- budget-constrained assembly --------------------------------
        for name in SECTION_PRIORITY:
            if name not in raw:
                continue
            text, tags, source = raw[name]
            if remaining <= 0:
                break

            cap = self.budget.cap_for(name)
            effective_limit = min(remaining, cap) if cap is not None else remaining

            text, truncated = _truncate(text, effective_limit)
            sec = NoteContextSection(
                name=name,
                text=text,
                tags=tags,
                source=source,
                truncated=truncated,
            )
            ctx.sections.append(sec)
            remaining -= len(text)

        ctx.total_chars = self.budget.total - remaining
        return ctx

    # ------------------------------------------------------------------ #
    # Surface readers
    # ------------------------------------------------------------------ #

    def _read_vault_note(self, vault_relative_path: str | Path) -> tuple[dict[str, Any], str]:
        path = self.vault_root / vault_relative_path
        try:
            return _read_note(path)
        except Exception:
            return {}, ""

    def _read_companion(self, note_uuid: str, vault_relative_path: str | Path) -> str:
        companion = note_log_path(note_uuid, vault_relative_path)
        full = self.vault_root / companion
        try:
            _, body = _read_note(full)
            return body
        except Exception:
            return ""

    def _read_decisions(self, note_uuid: str, keys: list[str]) -> str:
        if not self.decisions_store or not keys:
            return ""
        parts: list[str] = []
        for key in keys:
            try:
                dec = self.decisions_store.latest(object_id=note_uuid, key=key)
            except Exception:
                continue
            if dec:
                parts.append(f"{key}: {json.dumps(dec['value'], default=str)}")
        return "\n".join(parts)

    def _read_relations(self, note_uuid: str) -> str:
        if not self.relation_index:
            return ""
        from uuid import UUID

        try:
            uid = UUID(note_uuid)
        except ValueError:
            return ""

        lines: list[str] = []
        for rel in ("supports", "extends", "contradicts", "derived_from"):
            try:
                neighbors = self.relation_index.neighbors(uid, rel=rel, k=10)
            except Exception:
                continue
            for n in neighbors:
                lines.append(f"{rel}: {n}")
        return "\n".join(lines)


__all__ = [
    "ContextBudget",
    "NoteContext",
    "NoteContextAssembler",
    "NoteContextSection",
    "SECTION_PRIORITY",
    "TRUNCATED_MARKER",
]
