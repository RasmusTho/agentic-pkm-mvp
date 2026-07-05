"""Entity register v0 tests — Epic #3019 slice A1 (#3038).

Covers the governing Issue's four acceptance criteria:

- `test_split_reverses_merge` — merge then a matching split restores the
  pre-merge identities (reversibility, red-team F5 gate).
- `test_resolve_three_state` — `resolve()` returns exactly one of the three
  resolution states, never a free-text name as canonical identity.
- `test_mint_provisional_and_redirect` — `mint_provisional` creates a
  provisional ref that `resolve_redirects` later folds into a canonical
  entity.
- `test_mutations_are_evented_markdown_canonical` — every mutating op emits
  a register mutation event, and canonical identity is stored as a `.md`
  note (read directly off disk), not a graph DB / relational table.

No network, no real Postgres: the DB outbox insert is driven through the
same in-memory `FakeOutboxConn` PK-conflict emulation
`tests/knowledge_acquisition/test_stage_events.py` uses, so `ON CONFLICT (id)
DO NOTHING` idempotency semantics are exercised exactly. Every test uses a
temp-vault fixture (`VaultContext` over `tmp_path`) — never a real vault.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.events.types import (
    HEIMDAL_REGISTER_ENTITY_MERGED,
    HEIMDAL_REGISTER_ENTITY_MINTED,
    HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED,
    HEIMDAL_REGISTER_ENTITY_SPLIT,
)
from app.heimdal.entity_register import (
    AmbiguousCandidates,
    ARTIFACT_CLASS,
    EntityRegister,
    EntityRegisterError,
    KIND_PERSON,
    LIFECYCLE_CANONICAL,
    LIFECYCLE_MERGED,
    ResolvedRef,
    UnresolvedProvisional,
    entity_note_path,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Shared fixtures / fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory emulation of the keyed outbox insert with PK-conflict semantics.

    Mirrors `tests/knowledge_acquisition/test_stage_events.py::FakeOutboxConn`
    exactly, so this module exercises the same `ON CONFLICT (id) DO NOTHING`
    contract `app.services.outbox.write_outbox_event` relies on.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts = params
            if row_id in self.rows:
                return _FakeCursor([])  # conflict: nothing inserted / returned
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover - psycopg parity
        pass

    def rows_for(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["topic"] == topic]


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


def _register(tmp_path: Path, *, conn: Any = None, guard: WriteGuard | None = None) -> EntityRegister:
    return EntityRegister(
        vault_context=_vault(tmp_path / "vault"),
        write_guard=guard or _allowing_guard(),
        conn=conn if conn is not None else FakeOutboxConn(),
    )


# ---------------------------------------------------------------------------
# AC: split(entity_id, partition_criteria) exists and a merge followed by a
# matching split restores the pre-merge identities (reversibility).
# ---------------------------------------------------------------------------


def test_split_reverses_merge(tmp_path: Path) -> None:
    conn = FakeOutboxConn()
    register = _register(tmp_path, conn=conn)

    anna = register.mint_canonical("Anna Svensson", kind=KIND_PERSON, aliases=["Anna"])
    anna_gym = register.mint_canonical("Anna från gymmet", kind=KIND_PERSON, aliases=["Anna G"])

    # A wrong human-confirmed merge conflates the two Annas.
    register.merge(anna_gym, anna)

    merged_entry = register.get_entry(anna_gym)
    assert merged_entry is not None
    assert merged_entry.lifecycle == LIFECYCLE_MERGED
    assert merged_entry.merged_into == anna
    assert register.resolve_redirects(anna_gym) == anna

    # Split reverses it: partition the target's folded aliases back apart.
    new_ids = register.split(
        anna,
        {"Anna från gymmet": ["Anna från gymmet", "Anna G"]},
    )
    assert len(new_ids) == 1
    restored_anna_gym = new_ids[0]

    # Reversibility: resolving the ORIGINAL pre-merge id now lands on the
    # restored (new) entity, not on the over-broad merge target.
    assert register.resolve_redirects(anna_gym) == restored_anna_gym
    assert register.resolve_redirects(anna_gym) != anna

    # The original canonical Anna is untouched as an independent identity.
    assert register.resolve_redirects(anna) == anna
    restored_entry = register.get_entry(restored_anna_gym)
    assert restored_entry is not None
    assert restored_entry.lifecycle == LIFECYCLE_CANONICAL
    assert restored_entry.split_from == anna
    assert "Anna G" in restored_entry.aliases

    # Append-only: the pre-merge merged note is never deleted, just re-pointed.
    still_present = register.get_entry(anna_gym)
    assert still_present is not None
    assert still_present.lifecycle == LIFECYCLE_MERGED
    assert still_present.merged_into == restored_anna_gym


def test_split_rejects_unknown_entity(tmp_path: Path) -> None:
    register = _register(tmp_path)
    with pytest.raises(EntityRegisterError):
        register.split("ent:does-not-exist", {"x": ["y"]})


# ---------------------------------------------------------------------------
# AC: resolve() returns exactly one of the three resolution states and never
# a free-text name as canonical identity.
# ---------------------------------------------------------------------------


def test_resolve_three_state(tmp_path: Path) -> None:
    register = _register(tmp_path)

    # 1. unresolved: nothing recorded yet -> mints a provisional entity, an
    #    id, never a bare string.
    unresolved = register.resolve("Northvolt-projektet")
    assert isinstance(unresolved, UnresolvedProvisional)
    assert unresolved.entity_id.startswith("ent:prov:")
    assert unresolved.surface_form == "Northvolt-projektet"

    # The third sighting of the same surface form links to the SAME
    # provisional entity (recurrence is linkable from the first sighting).
    again = register.resolve("Northvolt-projektet")
    assert isinstance(again, ResolvedRef)
    assert again.entity_id == unresolved.entity_id

    # 2. resolved: a single canonical match -> exactly one entity_id + confidence.
    canonical_id = register.mint_canonical("Anna Svensson", kind=KIND_PERSON, aliases=["Anna"])
    resolved = register.resolve("Anna")
    assert isinstance(resolved, ResolvedRef)
    assert resolved.entity_id == canonical_id
    assert 0.0 <= resolved.confidence <= 1.0

    # 3. ambiguous: two canonical entities share a surface form -> ranked
    #    candidates, no winner asserted.
    second_id = register.mint_canonical("Anna Karlsson", kind=KIND_PERSON, aliases=["Anna"])
    ambiguous = register.resolve("Anna")
    assert isinstance(ambiguous, AmbiguousCandidates)
    assert len(ambiguous.candidates) == 2
    assert {c.entity_id for c in ambiguous.candidates} == {canonical_id, second_id}

    # The return type is a closed union: never a bare string / None-as-name.
    for outcome in (unresolved, again, resolved, ambiguous):
        assert not isinstance(outcome, str)


# ---------------------------------------------------------------------------
# AC: mint_provisional creates a provisional ref that resolve_redirects can
# later fold into a canonical entity.
# ---------------------------------------------------------------------------


def test_mint_provisional_and_redirect(tmp_path: Path) -> None:
    register = _register(tmp_path)

    provisional = register.mint_provisional("Anna från gymmet", kind_hint=KIND_PERSON)
    assert provisional.entity_id.startswith("ent:prov:")

    # Before any merge, redirects resolve to the provisional entity itself.
    assert register.resolve_redirects(provisional.entity_id) == provisional.entity_id

    canonical_id = register.mint_canonical("Anna Svensson", kind=KIND_PERSON, aliases=["Anna"])
    register.merge(provisional.entity_id, canonical_id)

    # Now the provisional ref folds into the canonical entity.
    assert register.resolve_redirects(provisional.entity_id) == canonical_id

    entry = register.get_entry(provisional.entity_id)
    assert entry is not None
    assert entry.lifecycle == LIFECYCLE_MERGED
    assert entry.merged_into == canonical_id


def test_merge_rejects_unknown_ids(tmp_path: Path) -> None:
    register = _register(tmp_path)
    canonical_id = register.mint_canonical("Anna Svensson", kind=KIND_PERSON)
    with pytest.raises(EntityRegisterError):
        register.merge("ent:prov:missing", canonical_id)
    with pytest.raises(EntityRegisterError):
        register.merge(canonical_id, "ent:missing-target")


def test_merge_rejects_self_merge(tmp_path: Path) -> None:
    register = _register(tmp_path)
    canonical_id = register.mint_canonical("Anna Svensson", kind=KIND_PERSON)
    with pytest.raises(EntityRegisterError):
        register.merge(canonical_id, canonical_id)


# ---------------------------------------------------------------------------
# AC: every mutating op emits a register mutation event; canonical identity
# is stored as a `.md` note, not a graph DB.
# ---------------------------------------------------------------------------


def test_mutations_are_evented_markdown_canonical(tmp_path: Path) -> None:
    conn = FakeOutboxConn()
    vault_root = tmp_path / "vault"
    register = _register(tmp_path, conn=conn)

    # -- mint: canonical store is a `.md` note on disk, not a DB row --------
    canonical_id = register.mint_canonical("Northvolt", aliases=["Northvolt AB"])
    note_rel_path = entity_note_path(canonical_id)
    note_path = vault_root / note_rel_path
    assert note_path.exists(), "canonical identity must be a markdown note, not only an event/DB row"
    assert note_path.suffix == ".md"

    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "entity note must carry YAML frontmatter"
    _, _, rest = text.partition("---\n")
    frontmatter_text, _, _ = rest.partition("\n---")
    frontmatter = yaml.safe_load(frontmatter_text)
    assert frontmatter["entity_id"] == canonical_id
    assert frontmatter["artifact_class"] == ARTIFACT_CLASS
    assert frontmatter["lifecycle"] == LIFECYCLE_CANONICAL

    mint_rows = conn.rows_for(HEIMDAL_REGISTER_ENTITY_MINTED)
    assert len(mint_rows) == 1
    mint_payload = json.loads(mint_rows[0]["payload"])["payload"]
    assert mint_payload["entity_id"] == canonical_id

    # -- mint_provisional: also evented + also a note -----------------------
    provisional = register.mint_provisional("Northvolt-projektet")
    prov_note = vault_root / entity_note_path(provisional.entity_id)
    assert prov_note.exists()
    assert len(conn.rows_for(HEIMDAL_REGISTER_ENTITY_MINTED)) == 2

    # -- merge: evented ------------------------------------------------------
    register.merge(provisional.entity_id, canonical_id)
    merge_rows = conn.rows_for(HEIMDAL_REGISTER_ENTITY_MERGED)
    assert len(merge_rows) == 1
    merge_payload = json.loads(merge_rows[0]["payload"])["payload"]
    assert merge_payload == {"from_id": provisional.entity_id, "into_id": canonical_id}

    # -- split: evented (one event per resulting new entity) ----------------
    new_ids = register.split(canonical_id, {"Northvolt-projektet": ["Northvolt-projektet"]})
    split_rows = conn.rows_for(HEIMDAL_REGISTER_ENTITY_SPLIT)
    assert len(split_rows) == len(new_ids) == 1

    # -- resolve_redirects: evented -------------------------------------------
    register.resolve_redirects(canonical_id)
    redirect_rows = conn.rows_for(HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED)
    assert len(redirect_rows) == 1

    # No graph DB / relational table is the canonical store: the only durable
    # artifacts this test asserts against are `.md` files (read via Path
    # directly, no DB query) and outbox audit rows (lineage, not identity).
    register_dir = vault_root / "_heimdal" / "register"
    md_files = list(register_dir.glob("*.md"))
    assert md_files, "expected at least one canonical entity note on disk"
    for md_file in md_files:
        loaded = yaml.safe_load(md_file.read_text(encoding="utf-8").split("---\n", 2)[1])
        assert "entity_id" in loaded


def test_mint_blocked_by_write_guard_is_loud(tmp_path: Path) -> None:
    """Guard coverage: the real production write call site (`_write_entry` via
    `write_note_relative`) refuses to write when the runtime is in a
    write-blocked health state — this is not a helper tested in isolation,
    it is the exact seam every mutating op goes through."""
    register = _register(tmp_path, guard=_blocking_guard())
    with pytest.raises(WritesBlockedError):
        register.mint_canonical("Blocked Entity")

    # Nothing durable was written: no note, no event.
    vault_root = tmp_path / "vault"
    register_dir = vault_root / "_heimdal" / "register"
    assert not register_dir.exists() or not list(register_dir.glob("*.md"))
