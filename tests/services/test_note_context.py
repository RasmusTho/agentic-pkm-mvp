"""Tests for NoteContextAssembler — hermetic, no real vault or Postgres."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from app.agent.models import ContextItem
from app.services.note_context import (
    ContextBudget,
    NoteContext,
    NoteContextAssembler,
    NoteContextSection,
    TRUNCATED_MARKER,
)
from app.stores.memory import MemoryDecisions, MemoryRelationIndex

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_note(path: Path, frontmatter: dict | None, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter:
        fm_dump = yaml.safe_dump(frontmatter, sort_keys=False).strip()
        path.write_text(f"---\n{fm_dump}\n---\n\n{body}", encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")


def _make_assembler(
    vault_root: Path,
    *,
    decisions: MemoryDecisions | None = None,
    relations: MemoryRelationIndex | None = None,
    budget: ContextBudget | None = None,
) -> NoteContextAssembler:
    return NoteContextAssembler(
        vault_root=vault_root,
        decisions_store=decisions,
        relation_index=relations,
        budget=budget or ContextBudget(),
    )


# ---------------------------------------------------------------------------
# Basic assembly
# ---------------------------------------------------------------------------

class TestBasicAssembly:
    def test_assembles_vault_note(self, tmp_path: Path) -> None:
        note_uuid = str(uuid4())
        rel = "Projects/my-note.md"
        _write_note(
            tmp_path / rel,
            {"title": "My Note", "tags": ["python", "pkm"]},
            "Hello world body content.",
        )

        asm = _make_assembler(tmp_path)
        ctx = asm.assemble(note_uuid, rel)

        names = [s.name for s in ctx.sections]
        assert "frontmatter" in names
        assert "body" in names
        assert ctx.note_uuid == note_uuid
        assert ctx.total_chars > 0

        body_sec = next(s for s in ctx.sections if s.name == "body")
        assert "Hello world body content." in body_sec.text

    def test_frontmatter_tags_propagated(self, tmp_path: Path) -> None:
        note_uuid = str(uuid4())
        rel = "note.md"
        _write_note(tmp_path / rel, {"tags": ["a", "b"]}, "body")

        ctx = _make_assembler(tmp_path).assemble(note_uuid, rel)
        fm_sec = next(s for s in ctx.sections if s.name == "frontmatter")
        assert fm_sec.tags == ["a", "b"]

    def test_missing_vault_note_produces_empty(self, tmp_path: Path) -> None:
        ctx = _make_assembler(tmp_path).assemble(str(uuid4()), "does/not/exist.md")
        assert ctx.sections == []
        assert ctx.total_chars == 0

    def test_note_without_frontmatter(self, tmp_path: Path) -> None:
        rel = "plain.md"
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("Just a body, no frontmatter.", encoding="utf-8")

        ctx = _make_assembler(tmp_path).assemble(str(uuid4()), rel)
        names = [s.name for s in ctx.sections]
        assert "frontmatter" not in names
        assert "body" in names


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    def test_total_budget_respected(self, tmp_path: Path) -> None:
        rel = "big.md"
        body = "x" * 5000
        _write_note(tmp_path / rel, {"title": "t"}, body)

        budget = ContextBudget(total=200)
        ctx = _make_assembler(tmp_path, budget=budget).assemble(str(uuid4()), rel)
        assert ctx.total_chars <= 200

    def test_per_section_cap(self, tmp_path: Path) -> None:
        rel = "capped.md"
        _write_note(tmp_path / rel, {"title": "t", "desc": "d" * 500}, "b" * 500)

        budget = ContextBudget(total=8000, frontmatter=50, body=50)
        ctx = _make_assembler(tmp_path, budget=budget).assemble(str(uuid4()), rel)

        fm = next((s for s in ctx.sections if s.name == "frontmatter"), None)
        body_sec = next((s for s in ctx.sections if s.name == "body"), None)

        if fm:
            assert len(fm.text) <= 50
        if body_sec:
            assert len(body_sec.text) <= 50

    def test_truncation_marker_present(self, tmp_path: Path) -> None:
        rel = "trunc.md"
        _write_note(tmp_path / rel, None, "w" * 1000)

        budget = ContextBudget(total=100)
        ctx = _make_assembler(tmp_path, budget=budget).assemble(str(uuid4()), rel)
        body_sec = next(s for s in ctx.sections if s.name == "body")
        assert body_sec.truncated is True
        assert body_sec.text.endswith(TRUNCATED_MARKER)

    def test_zero_budget_yields_nothing(self, tmp_path: Path) -> None:
        rel = "any.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")

        budget = ContextBudget(total=0)
        ctx = _make_assembler(tmp_path, budget=budget).assemble(str(uuid4()), rel)
        assert ctx.sections == []

    def test_priority_ordering_frontmatter_first(self, tmp_path: Path) -> None:
        """Frontmatter gets budget before body; body may be truncated."""
        rel = "prio.md"
        fm_text_raw = {"big_field": "F" * 300}
        body_text = "B" * 300
        _write_note(tmp_path / rel, fm_text_raw, body_text)

        # Budget barely fits frontmatter, body gets leftovers
        budget = ContextBudget(total=400)
        ctx = _make_assembler(tmp_path, budget=budget).assemble(str(uuid4()), rel)

        names = [s.name for s in ctx.sections]
        assert names.index("frontmatter") < names.index("body")
        # Body should be truncated since frontmatter ate most of the budget
        body_sec = next(s for s in ctx.sections if s.name == "body")
        assert body_sec.truncated is True


# ---------------------------------------------------------------------------
# Companion / metadata mirror
# ---------------------------------------------------------------------------

class TestCompanionNote:
    def test_companion_included(self, tmp_path: Path) -> None:
        note_uuid = str(uuid4())
        rel = "Projects/note.md"
        _write_note(tmp_path / rel, {"title": "t"}, "vault body")

        # Write a companion note at the expected mirror path
        from app.services.note_log import note_log_path

        companion_rel = note_log_path(note_uuid, rel)
        _write_note(
            tmp_path / companion_rel,
            {"type": "companion"},
            "Agent decided this is interesting.",
        )

        ctx = _make_assembler(tmp_path).assemble(note_uuid, rel)
        companion_sec = next((s for s in ctx.sections if s.name == "companion"), None)
        assert companion_sec is not None
        assert "Agent decided this is interesting" in companion_sec.text

    def test_missing_companion_graceful(self, tmp_path: Path) -> None:
        rel = "solo.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")

        ctx = _make_assembler(tmp_path).assemble(str(uuid4()), rel)
        names = [s.name for s in ctx.sections]
        assert "companion" not in names


# ---------------------------------------------------------------------------
# Decisions store
# ---------------------------------------------------------------------------

class TestDecisions:
    def test_decisions_included(self, tmp_path: Path) -> None:
        note_uuid = str(uuid4())
        rel = "d.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")

        ds = MemoryDecisions()
        ds.put(object_id=note_uuid, agent="triage", kind="label", key="interest", value={"score": 0.9})
        ds.put(object_id=note_uuid, agent="triage", kind="label", key="topic", value={"label": "engineering"})

        ctx = _make_assembler(tmp_path, decisions=ds).assemble(
            note_uuid, rel, decision_keys=["interest", "topic"]
        )
        dec_sec = next((s for s in ctx.sections if s.name == "decisions"), None)
        assert dec_sec is not None
        assert "interest" in dec_sec.text
        assert "0.9" in dec_sec.text
        assert "engineering" in dec_sec.text

    def test_no_decisions_store(self, tmp_path: Path) -> None:
        rel = "nd.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")
        ctx = _make_assembler(tmp_path).assemble(str(uuid4()), rel, decision_keys=["interest"])
        names = [s.name for s in ctx.sections]
        assert "decisions" not in names

    def test_no_keys_skips_decisions(self, tmp_path: Path) -> None:
        ds = MemoryDecisions()
        ds.put(object_id="x", agent="a", kind="k", key="k", value={"v": 1})
        rel = "nk.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")
        ctx = _make_assembler(tmp_path, decisions=ds).assemble(str(uuid4()), rel)
        names = [s.name for s in ctx.sections]
        assert "decisions" not in names


# ---------------------------------------------------------------------------
# Relation index
# ---------------------------------------------------------------------------

class TestRelations:
    def test_relations_included(self, tmp_path: Path) -> None:
        uid = uuid4()
        neighbor = uuid4()
        rel_path = "r.md"
        _write_note(tmp_path / rel_path, {"title": "t"}, "body")

        ri = MemoryRelationIndex()
        ri.link(uid, neighbor, rel="supports", payload={})

        ctx = _make_assembler(tmp_path, relations=ri).assemble(str(uid), rel_path)
        rel_sec = next((s for s in ctx.sections if s.name == "relations"), None)
        assert rel_sec is not None
        assert str(neighbor) in rel_sec.text
        assert "supports" in rel_sec.text

    def test_no_relation_index(self, tmp_path: Path) -> None:
        rel = "nr.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")
        ctx = _make_assembler(tmp_path).assemble(str(uuid4()), rel)
        names = [s.name for s in ctx.sections]
        assert "relations" not in names

    def test_invalid_uuid_skips_relations(self, tmp_path: Path) -> None:
        ri = MemoryRelationIndex()
        rel = "bad.md"
        _write_note(tmp_path / rel, {"title": "t"}, "body")
        ctx = _make_assembler(tmp_path, relations=ri).assemble("not-a-uuid", rel)
        names = [s.name for s in ctx.sections]
        assert "relations" not in names


# ---------------------------------------------------------------------------
# to_context_items conversion
# ---------------------------------------------------------------------------

class TestToContextItems:
    def test_converts_to_context_items(self, tmp_path: Path) -> None:
        note_uuid = str(uuid4())
        rel = "ci.md"
        _write_note(tmp_path / rel, {"title": "t", "tags": ["x"]}, "body text")

        ctx = _make_assembler(tmp_path).assemble(note_uuid, rel)
        items = ctx.to_context_items()

        assert len(items) >= 2
        assert all(isinstance(i, ContextItem) for i in items)
        assert all(i.id.startswith(note_uuid) for i in items)

    def test_empty_sections_skipped(self) -> None:
        ctx = NoteContext(note_uuid="u", sections=[
            NoteContextSection(name="empty", text="", source="s"),
            NoteContextSection(name="filled", text="content", source="s"),
        ])
        items = ctx.to_context_items()
        assert len(items) == 1
        assert items[0].id == "u:filled"

    def test_source_propagated(self) -> None:
        ctx = NoteContext(note_uuid="u", sections=[
            NoteContextSection(name="body", text="t", source="vault:body"),
        ])
        items = ctx.to_context_items()
        assert items[0].source == "vault:body"


# ---------------------------------------------------------------------------
# Full assembly with all surfaces
# ---------------------------------------------------------------------------

class TestFullAssembly:
    def test_all_surfaces(self, tmp_path: Path) -> None:
        uid = uuid4()
        note_uuid = str(uid)
        neighbor = uuid4()
        rel = "Projects/full.md"

        _write_note(tmp_path / rel, {"title": "Full", "tags": ["test"]}, "Full body.")

        from app.services.note_log import note_log_path

        comp_rel = note_log_path(note_uuid, rel)
        _write_note(tmp_path / comp_rel, {}, "Companion log entry.")

        ds = MemoryDecisions()
        ds.put(object_id=note_uuid, agent="a", kind="k", key="score", value={"v": 42})

        ri = MemoryRelationIndex()
        ri.link(uid, neighbor, rel="extends")

        ctx = _make_assembler(tmp_path, decisions=ds, relations=ri).assemble(
            note_uuid, rel, decision_keys=["score"]
        )

        section_names = {s.name for s in ctx.sections}
        assert section_names == {"frontmatter", "body", "companion", "decisions", "relations"}

        items = ctx.to_context_items()
        assert len(items) == 5

    def test_budget_constrains_lower_priority(self, tmp_path: Path) -> None:
        uid = uuid4()
        note_uuid = str(uid)
        rel = "tight.md"
        # Large body so it eats most of the budget
        _write_note(tmp_path / rel, {"title": "T"}, "B" * 5000)

        ri = MemoryRelationIndex()
        ri.link(uid, uuid4(), rel="supports")

        budget = ContextBudget(total=500)
        ctx = _make_assembler(tmp_path, relations=ri, budget=budget).assemble(
            note_uuid, rel
        )
        assert ctx.total_chars <= 500
        # Relations may be excluded entirely if budget is exhausted
        section_names = {s.name for s in ctx.sections}
        if "relations" in section_names:
            rel_sec = next(s for s in ctx.sections if s.name == "relations")
            assert rel_sec.truncated or len(rel_sec.text) < 100
