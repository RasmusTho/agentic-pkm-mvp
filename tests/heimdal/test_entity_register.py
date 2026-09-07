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
from dataclasses import replace
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
    MERGE_EFFECTS_COMPLETE,
    MERGE_EFFECTS_NONE,
    MERGE_EFFECTS_SOURCE_ONLY,
    EntityRegister,
    EntityRegisterError,
    KIND_PERSON,
    LIFECYCLE_CANONICAL,
    LIFECYCLE_MERGED,
    RegisterEntry,
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
            row_id, topic, payload, created_at, attempts, legacy_key, vault_binding_id, *_ = params
            if row_id in self.rows:
                return _FakeCursor([])  # conflict: nothing inserted / returned
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
                "legacy_key": legacy_key,
                "vault_binding_id": vault_binding_id,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover - psycopg parity
        pass

    def rows_for(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["topic"] == topic]



class FakeSplitJournal:
    """Routing double; the separate pg suite proves durable journal transactions."""
    def __init__(self, conn: Any) -> None:
        self.records: dict[tuple[str, str], Any] = {}
        self.conn = conn

    def load_split(self, vault_identity: str, operation_id: str) -> Any:
        return self.records.get((vault_identity, operation_id))

    def prepare_split(self, record: Any) -> Any:
        key = (record.vault_identity, record.operation_id)
        if key in self.records:
            assert self.records[key].plan == record.plan
            return self.records[key]
        assert not any(r.vault_identity == record.vault_identity and not r.completed for r in self.records.values())
        self.records[key] = record
        return record

    def checkpoint_split(self, record: Any, checkpoint: str) -> Any:
        from app.heimdal.entity_review_operation_journal import split_checkpoint_keys
        if checkpoint not in record.checkpoints:
            assert split_checkpoint_keys(record.plan)[len(record.checkpoints)] == checkpoint
            record = replace(record, checkpoints=(*record.checkpoints, checkpoint))
            self.records[(record.vault_identity, record.operation_id)] = record
        return record

    def finish_split(self, record: Any) -> Any:
        from app.events.models import new_event
        from app.heimdal.entity_review_operation_journal import split_checkpoint_keys, split_event_id
        from app.services.outbox import write_outbox_event
        assert record.checkpoints == split_checkpoint_keys(record.plan)
        for payload in record.plan['events']:
            event = new_event(event_type=HEIMDAL_REGISTER_ENTITY_SPLIT, payload=payload, source='test')
            write_outbox_event(event, conn=self.conn, idempotency_key=split_event_id(record, payload))
        record = replace(record, completed=True)
        self.records[(record.vault_identity, record.operation_id)] = record
        return record

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
    conn = conn if conn is not None else FakeOutboxConn()
    return EntityRegister(
        vault_context=_vault(tmp_path / "vault"),
        write_guard=guard or _allowing_guard(),
        conn=conn,
        split_journal=FakeSplitJournal(conn),
    )


def test_empty_active_vault_id_fails_loud(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    with pytest.raises(EntityRegisterError, match="must not be empty"):
        EntityRegister(
            vault_context=VaultContext(
                status="selected",
                active_vault_id="",
                active_vault_path=str(vault_root),
            ),
            write_guard=_allowing_guard(),
        )


def test_operation_vault_identity_refuses_noncanonical_vault_schema(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "vault.md").write_text(
        "---\nschema: attacker.not-a-vault.v1\nvaultId: vault-synthetic\n---\n",
        encoding="utf-8",
    )
    register = EntityRegister(
        vault_context=VaultContext(
            status="selected",
            active_vault_id="vault-synthetic",
            active_vault_path=str(vault_root),
        ),
        write_guard=_allowing_guard(),
    )

    with pytest.raises(EntityRegisterError, match="canonical"):
        _ = register.operation_vault_identity


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


def test_lineage_round_trip_covers_every_merge_and_split_producer(tmp_path: Path) -> None:
    """EROJ-02 preserves producer-written lineage through note round-trips."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")

    register.merge(source, target, operation_id="operation-original")
    register.merge(target, evolved, operation_id="operation-target-merge")

    source_entry = register.get_entry(source)
    assert source_entry is not None
    assert source_entry.lineage == (
        {
            "predecessor_id": source,
            "successor_id": target,
            "operation_id": "operation-original",
            "mutation_kind": "merge",
        },
    )
    assert register.resolve_target_evolution(
        source, target, operation_id="operation-original"
    ) == evolved

    successor = register.split(
        evolved,
        {"Target successor": ["Target", "Source"]},
        operation_id="operation-target-split",
    )[0]
    assert register.resolve_target_evolution(
        source, target, operation_id="operation-original"
    ) == successor
    assert register.resolve_redirects(source) == successor


def test_direct_merge_derives_stable_lineage_identity_for_target_evolution(
    tmp_path: Path,
) -> None:
    """The public merge producer must not strand a later target evolution."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")

    register.merge(source, target)
    source_entry = register.get_entry(source)
    assert source_entry is not None
    direct_operation_id = source_entry.lineage[-1]["operation_id"]
    assert direct_operation_id == f"direct-merge:{source}:{target}"

    register.merge(target, evolved)
    assert register.resolve_target_evolution(
        source, target, operation_id=direct_operation_id
    ) == evolved


def test_target_split_ignores_partition_that_does_not_reclaim_original_source(
    tmp_path: Path,
) -> None:
    """EROJ-02 cannot choose an unrelated split partition for the original source."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source")
    other = register.mint_canonical("Other")
    target = register.mint_canonical("Target")
    register.merge(source, target, operation_id="original-operation")
    register.merge(other, target, operation_id="other-operation")

    unrelated = register.split(
        target,
        {"Other restored": ["Other"]},
    )[0]

    assert register.resolve_redirects(source) == target
    assert register.resolve_target_evolution(
        source, target, operation_id="original-operation"
    ) == target
    assert unrelated != target


def test_public_split_derives_lineage_for_reclaimed_source_recovery(tmp_path: Path) -> None:
    """A public split preserves a provable evolved target for an awaiting review."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.ensure_merge_effects(source, target, operation_id="review-operation")

    successor = register.split(target, {"Recovered source": ["Source", "S"]})[0]
    source_entry = register.get_entry(source)
    assert source_entry is not None
    split_links = [
        link for link in source_entry.lineage if link.get("mutation_kind") == "split"
    ]
    assert len(split_links) == 1
    assert split_links[0]["operation_id"].startswith(f"direct-split:{target}:")
    assert register.merge_effect_state(source, target) == MERGE_EFFECTS_COMPLETE
    assert register.resolve_target_evolution(
        source, target, operation_id="review-operation"
    ) == successor


def test_source_reclaimed_split_precedes_later_residual_target_merge(tmp_path: Path) -> None:
    """The original source's explicit split proof wins over later T evolution."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.ensure_merge_effects(source, target, operation_id="review-operation")
    successor = register.split(target, {"Recovered source": ["Source", "S"]})[0]
    residual_target = register.mint_canonical("Residual target")
    register.merge(target, residual_target)

    assert register.resolve_redirects(source) == successor
    assert register.resolve_target_evolution(
        source, target, operation_id="review-operation"
    ) == successor


def test_consecutive_source_reclaimed_splits_follow_each_lineage_hop(tmp_path: Path) -> None:
    """Each source-reclaim split hop remains eligible after the first one."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.ensure_merge_effects(source, target, operation_id="review-operation")

    first_successor = register.split(target, {"Recovered once": ["Source", "S"]})[0]
    second_successor = register.split(
        first_successor, {"Recovered twice": ["Source", "S"]}
    )[0]

    assert register.resolve_redirects(source) == second_successor
    assert register.resolve_target_evolution(
        source, target, operation_id="review-operation"
    ) == second_successor


def test_repointed_split_requires_complete_successor_complement(tmp_path: Path) -> None:
    """A split redirect without the successor complement is not lineage proof."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    register.merge(source, target, operation_id="review-operation")
    evolved = register.mint_canonical("Evolved")
    register.merge(target, evolved, operation_id="target-evolution")
    successor = register.split(evolved, {"Recovered target": ["Target", "Source"]})[0]
    successor_entry = register.get_entry(successor)
    assert successor_entry is not None
    register._write_entry(replace(successor_entry, merged_from=()))

    with pytest.raises(EntityRegisterError, match="complement"):
        register.resolve_target_evolution(
            source, target, operation_id="review-operation"
        )


def test_source_reclaimed_split_rejects_contradictory_partial_complement(
    tmp_path: Path,
) -> None:
    """Both split predecessor and successor retaining S is contradictory."""
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.ensure_merge_effects(source, target, operation_id="review-operation")
    successor = register.split(target, {"Recovered source": ["Source", "S"]})[0]
    target_entry = register.get_entry(target)
    assert target_entry is not None
    register._write_entry(replace(target_entry, merged_from=(source,)))

    with pytest.raises(EntityRegisterError, match="complement"):
        register.resolve_target_evolution(
            source, target, operation_id="review-operation"
        )
    assert register.get_entry(successor) is not None


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


# ---------------------------------------------------------------------------
# EROJ-01 (#4350): resumable merge-effect helpers — classification, idempotent
# completion, and every fail-closed branch (review F2/F6 on #4350).
# ---------------------------------------------------------------------------


class _EffectCrashRegister(EntityRegister):
    """Real register whose Nth armed note write raises, for exact-boundary
    crash construction; arming happens after fixture setup writes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fail_on: int | None = None
        self._writes = 0

    def arm(self, fail_on_write: int) -> None:
        self._fail_on = fail_on_write
        self._writes = 0

    def disarm(self) -> None:
        self._fail_on = None

    def _write_entry(self, entry: Any) -> None:
        if self._fail_on is not None:
            self._writes += 1
            if self._writes >= self._fail_on:
                raise EntityRegisterError("simulated crash mid-merge")
        super()._write_entry(entry)


def _effect_register(tmp_path: Path) -> _EffectCrashRegister:
    return _EffectCrashRegister(
        vault_context=_vault(tmp_path / "vault"),
        write_guard=_allowing_guard(),
        conn=FakeOutboxConn(),
    )


def test_merge_effect_state_classifies_all_note_shapes(tmp_path: Path) -> None:
    register = _effect_register(tmp_path)
    a = register.mint_canonical("Alpha", aliases=["Al"])
    b = register.mint_canonical("Beta")

    assert register.merge_effect_state(a, b) == MERGE_EFFECTS_NONE

    # Crash between the source-redirect write and the target-complement write.
    register.arm(fail_on_write=2)
    with pytest.raises(EntityRegisterError, match="simulated crash"):
        register.ensure_merge_effects(a, b)
    register.disarm()
    assert register.merge_effect_state(a, b) == MERGE_EFFECTS_SOURCE_ONLY
    assert register.get_entry(a).merged_into == b
    assert a not in register.get_entry(b).merged_from

    # Resume completes only the missing target side.
    assert register.ensure_merge_effects(a, b) == MERGE_EFFECTS_SOURCE_ONLY
    assert register.merge_effect_state(a, b) == MERGE_EFFECTS_COMPLETE
    assert a in register.get_entry(b).merged_from
    assert "Alpha" in register.get_entry(b).aliases

    # Idempotent: a fully applied merge is left untouched.
    assert register.ensure_merge_effects(a, b) == MERGE_EFFECTS_COMPLETE


def test_ensure_merge_effects_backfills_pre_lineage_completed_merge_before_evolution(
    tmp_path: Path,
) -> None:
    """A retry binds the journal operation to an old, already-complete effect."""
    register = _effect_register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")

    # Simulate an EROJ-01-era write that pre-dates EROJ-02 lineage.
    assert register.ensure_merge_effects(source, target) == MERGE_EFFECTS_NONE
    register._write_entry(replace(register.get_entry(source), lineage=(), complement_id=None))
    register._write_entry(replace(register.get_entry(target), complements=()))
    assert register.get_entry(source).lineage == ()
    register.merge(target, evolved, operation_id="target-evolution")

    assert register.ensure_merge_effects(
        source, target, operation_id="journal-operation"
    ) == MERGE_EFFECTS_COMPLETE
    assert register.resolve_target_evolution(
        source, target, operation_id="journal-operation"
    ) == evolved
    assert register.get_entry(target).complements[0]["operation_id"] == "journal-operation"


def test_evolved_source_only_merge_backfills_lineage_but_refuses_missing_complement(tmp_path: Path) -> None:
    """EROJ-03 refuses unrelated evolution until the partial relation is completed."""
    register = _effect_register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")
    register.arm(fail_on_write=2)
    with pytest.raises(EntityRegisterError, match="simulated crash"):
        register.ensure_merge_effects(source, target, operation_id="journal-operation")
    register.disarm()
    before = _relation_snapshot(register)
    with pytest.raises(EntityRegisterError, match="complement"):
        register.merge(target, evolved, operation_id="target-evolution")
    assert _relation_snapshot(register) == before
    register.ensure_merge_effects(source, target, operation_id="journal-operation")
    register.merge(target, evolved, operation_id="target-evolution")
    assert register.resolve_target_evolution(source, target, operation_id="journal-operation") == evolved


def test_target_evolution_rejects_merge_hop_without_successor_complement(
    tmp_path: Path,
) -> None:
    """Every evolved merge hop proves its own target-side effect before recovery."""
    register = _effect_register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")
    register.ensure_merge_effects(source, target, operation_id="journal-operation")
    register.merge(target, evolved, operation_id="target-evolution")

    evolved_entry = register.get_entry(evolved)
    assert evolved_entry is not None
    register._write_entry(
        replace(
            evolved_entry,
            merged_from=tuple(item for item in evolved_entry.merged_from if item != target),
            aliases=tuple(item for item in evolved_entry.aliases if item != "Target"),
        )
    )

    with pytest.raises(EntityRegisterError, match="complement"):
        register.resolve_target_evolution(
            source, target, operation_id="journal-operation"
        )


def test_target_evolution_prioritizes_cycle_detection_over_hop_complement(
    tmp_path: Path,
) -> None:
    """A cyclic lineage is deterministic even when its synthetic hop is incomplete."""
    register = _effect_register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    register.ensure_merge_effects(source, target, operation_id="journal-operation")
    target_entry = register.get_entry(target)
    assert target_entry is not None
    register._write_entry(
        replace(
            target_entry,
            lineage=({
                "predecessor_id": target,
                "successor_id": target,
                "operation_id": "cycle",
                "mutation_kind": "merge",
            },),
        )
    )

    with pytest.raises(EntityRegisterError, match="cycle"):
        register.resolve_target_evolution(
            source, target, operation_id="journal-operation"
        )


def test_merge_effect_helpers_fail_closed_on_unprovable_notes(tmp_path: Path) -> None:
    register = _effect_register(tmp_path)
    a = register.mint_canonical("Alpha")
    b = register.mint_canonical("Beta")
    c = register.mint_canonical("Gamma")

    # Unknown ids and self-merge.
    with pytest.raises(EntityRegisterError, match="unknown from_id"):
        register.merge_effect_state("ent:ghost", b)
    with pytest.raises(EntityRegisterError, match="unknown into_id"):
        register.merge_effect_state(a, "ent:ghost")
    with pytest.raises(EntityRegisterError, match="must differ"):
        register.merge_effect_state(a, a)

    # Foreign redirect: the source redirects to a different target than the
    # operation's original pair — unprovable, refused (EROJ-02 territory).
    register.merge(a, b)
    with pytest.raises(EntityRegisterError, match="refuses target-evolved recovery"):
        register.merge_effect_state(a, c)
    with pytest.raises(EntityRegisterError, match="refuses target-evolved recovery"):
        register.ensure_merge_effects(a, c)

    # Contradictory notes: the target claims the source in merged_from while
    # the source carries no redirect (constructed corruption) — fail closed.
    source_entry = register.get_entry(a)
    register._write_entry(  # simulate note corruption/hand-edit
        RegisterEntry(
            entity_id=source_entry.entity_id,
            kind=source_entry.kind,
            label=source_entry.label,
            aliases=source_entry.aliases,
            lifecycle=LIFECYCLE_CANONICAL,
            merged_into=None,
            merged_from=source_entry.merged_from,
            split_from=source_entry.split_from,
            created=source_entry.created,
        )
    )
    with pytest.raises(EntityRegisterError, match="complement"):
        register.merge_effect_state(a, b)


def test_merge_into_evolved_target_is_refused(tmp_path: Path) -> None:
    """A new merge into an already-merged target remains fail-closed."""
    register = _effect_register(tmp_path)
    a = register.mint_canonical("Alpha")
    b = register.mint_canonical("Beta")
    c = register.mint_canonical("Gamma")
    register.merge(b, c)
    before = _relation_snapshot(register)
    with pytest.raises(EntityRegisterError):
        register.ensure_merge_effects(a, b)
    assert _relation_snapshot(register) == before


def _relation_snapshot(register: EntityRegister) -> dict[str, str]:
    return {p.name: p.read_text() for p in (register.vault_root / '_heimdal/register').glob('*.md')}


def test_split_complement_ids_are_globally_unique_across_repeated_splits(tmp_path: Path) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical('Source', aliases=['S'])
    target = register.mint_canonical('Target')
    register.merge(source, target)
    complement_id = register.get_entry(source).complement_id
    assert complement_id
    for label in ('First', 'Second', 'Third'):
        target = register.split(target, {label: ['Source', 'S']})[0]
        assert register.get_entry(source).complement_id == complement_id
        records = [(e.entity_id, c) for e in register._all_entries() for c in e.complements]
        assert len(records) == 1
        assert records[0][0] == target
        assert records[0][1]['complement_id'] == complement_id
        assert records[0][1]['from_id'] == source


@pytest.mark.parametrize("implicit", [False, True])
def test_completed_split_replay_preserves_later_valid_evolution(tmp_path: Path, implicit: bool) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.merge(source, target, operation_id="original-merge")
    partition = {"First": ["Source", "S"]}
    operation = None if implicit else "original-split"
    successors = register.split(target, partition, operation_id=operation)
    later = register.split(successors[0], {"Second": ["Source", "S"]}, operation_id="later-split")[0]
    terminal = register.mint_canonical("Terminal")
    register.merge(later, terminal, operation_id="later-merge")
    before = _relation_snapshot(register)
    events_before = dict(register._conn.rows)
    assert register.split(target, partition, operation_id=operation) == successors
    assert _relation_snapshot(register) == before
    assert register._conn.rows == events_before
    assert register.resolve_target_evolution(source, target, operation_id="original-merge") == terminal


def test_implicit_split_distinguishes_a_later_matching_merge_from_retry(tmp_path: Path) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical("Source", aliases=["S"])
    target = register.mint_canonical("Target")
    register.merge(source, target)
    partition = {"Recovered": ["Source", "S"]}
    first = register.split(target, partition)
    later_source = register.mint_canonical("Source", aliases=["S"])
    assert later_source != source
    register.merge(later_source, target)

    second = register.split(target, partition)

    assert second != first
    assert register.get_entry(later_source).merged_into == second[0]
    assert register.get_entry(source).merged_into == first[0]
    before = _relation_snapshot(register)
    assert register.split(target, partition) == second
    assert _relation_snapshot(register) == before
    assert len(register._conn.rows_for(HEIMDAL_REGISTER_ENTITY_SPLIT)) == 2


@pytest.mark.parametrize('split_number', [1, 2])
@pytest.mark.parametrize('stop_at', range(1, 5))
@pytest.mark.parametrize('after_write', [False, True])
def test_second_split_crash_recovers_without_duplicate_complements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, split_number: int, stop_at: int, after_write: bool
) -> None:
    conn = FakeOutboxConn()
    register = _register(tmp_path, conn=conn)
    source = register.mint_canonical('Source', aliases=['S'])
    target = register.mint_canonical('Target', aliases=['T'])
    register.merge(source, target)
    if split_number == 2:
        target = register.split(target, {'First': ['Source', 'S', 'T']})[0]
    partition = {'Recovered': ['Source', 'S'], 'Other': ['T']}
    write = register._write_entry
    count = 0

    def crash(entry: RegisterEntry) -> None:
        nonlocal count
        count += 1
        if count == stop_at and not after_write:
            raise RuntimeError('injected split crash')
        write(entry)
        if count == stop_at and after_write:
            raise RuntimeError('injected split crash')

    monkeypatch.setattr(register, '_write_entry', crash)
    with pytest.raises(RuntimeError, match='injected split crash'):
        register.split(target, partition)
    monkeypatch.setattr(register, '_write_entry', write)
    ids = register.split(target, partition)
    assert register.split(target, partition) == ids
    assert len([e for e in register._all_entries() if e.split_from == target]) == 2
    assert len(conn.rows_for(HEIMDAL_REGISTER_ENTITY_SPLIT)) == 2 + (split_number - 1)
    assert register.resolve_redirects(source) == ids[0]
    assert len([c for e in register._all_entries() for c in e.complements]) == 1


@pytest.mark.parametrize('corruption', ['duplicate', 'missing', 'mismatch'])
def test_duplicate_complement_preflight_fails_before_pending_clear(tmp_path: Path, corruption: str) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical('Source')
    target = register.mint_canonical('Target')
    register.ensure_merge_effects(source, target, operation_id='op')
    entry = register.get_entry(target)
    if corruption == 'duplicate':
        other = register.mint_canonical('Other')
        register._write_entry(replace(register.get_entry(other), complements=entry.complements, merged_from=(source,)))
    elif corruption == 'missing':
        register._write_entry(replace(entry, complements=()))
    else:
        register._write_entry(replace(register.get_entry(source), complement_id='wrong'))
    before = _relation_snapshot(register)
    with pytest.raises(EntityRegisterError):
        register.ensure_merge_effects(source, target, operation_id='op')
    assert _relation_snapshot(register) == before


@pytest.mark.parametrize('corruption', [None, 'duplicate', 'missing', 'multiple-targets', 'cycle'])
def test_legacy_complement_backfill_is_deterministic_and_fail_loud(tmp_path: Path, corruption: str | None) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical('Source')
    target = register.mint_canonical('Target')
    register._write_entry(replace(register.get_entry(source), lifecycle=LIFECYCLE_MERGED, merged_into=target))
    register._write_entry(replace(register.get_entry(target), merged_from=(source,), aliases=('Source',)))
    if corruption == 'duplicate':
        register._write_entry(replace(register.get_entry(target), merged_from=(source, source)))
    elif corruption == 'missing':
        register._write_entry(replace(register.get_entry(target), merged_from=()))
    elif corruption == 'multiple-targets':
        other = register.mint_canonical('Other')
        register._write_entry(replace(register.get_entry(other), merged_from=(source,)))
    elif corruption == 'cycle':
        register._write_entry(replace(register.get_entry(target), lifecycle=LIFECYCLE_MERGED, merged_into=source))
        register._write_entry(replace(register.get_entry(source), merged_from=(target,)))
    before = _relation_snapshot(register)
    if corruption:
        with pytest.raises(EntityRegisterError):
            register.backfill_complements()
        assert _relation_snapshot(register) == before
    else:
        register.backfill_complements()
        first = register.get_entry(source).complement_id
        assert first == register.get_entry(target).complements[0]['complement_id']
        after = _relation_snapshot(register)
        register.backfill_complements()
        assert _relation_snapshot(register) == after
        # Reconstruct the same original legacy notes: deterministic across restarts.
        for name, content in before.items():
            (register.vault_root / '_heimdal/register' / name).write_text(content)
        register.backfill_complements()
        assert register.get_entry(source).complement_id == first


def test_all_relation_producers_supply_unique_complement_identity(tmp_path: Path) -> None:
    register = _register(tmp_path)
    target = register.mint_canonical('Target')
    direct = register.mint_provisional('Direct').entity_id
    review = register.mint_canonical('Review')
    register.merge(direct, target)
    register.ensure_merge_effects(review, target, operation_id='review-op')
    ids = {register.get_entry(s).complement_id for s in (direct, review)}
    assert len(ids) == 2 and None not in ids
    new = register.split(target, {'Separate': ['Direct']})[0]
    assert register.get_entry(new).complements[0]['into_id'] == target
    for entry in register._all_entries():
        assert RegisterEntry.from_frontmatter(entry.to_frontmatter()) == entry


def test_direct_merge_retry_preserves_relation_and_one_event(tmp_path: Path) -> None:
    conn = FakeOutboxConn()
    register = _register(tmp_path, conn=conn)
    source = register.mint_canonical('Source')
    target = register.mint_canonical('Target')
    register.merge(source, target)
    before = _relation_snapshot(register)
    register.merge(source, target)
    assert _relation_snapshot(register) == before
    assert len(conn.rows_for(HEIMDAL_REGISTER_ENTITY_MERGED)) == 1


def test_multiple_legacy_sources_backfill_together_and_resume_partial_backfill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register = _register(tmp_path)
    sources = [register.mint_canonical(label) for label in ('A', 'B')]
    target = register.mint_canonical('Target')
    for source in sources:
        register._write_entry(replace(register.get_entry(source), lifecycle=LIFECYCLE_MERGED, merged_into=target))
    register._write_entry(replace(register.get_entry(target), merged_from=tuple(sources)))
    write = register._write_entry
    count = 0
    def crash(entry):
        nonlocal count
        write(entry)
        count += 1
        if count == 1:
            raise RuntimeError('backfill crash')
    monkeypatch.setattr(register, '_write_entry', crash)
    with pytest.raises(RuntimeError):
        register.backfill_complements()
    monkeypatch.setattr(register, '_write_entry', write)
    register.backfill_complements()
    assert len(register.get_entry(target).complements) == 2
    assert {c['complement_id'] for c in register.get_entry(target).complements} == {
        register.get_entry(source).complement_id for source in sources}


def test_split_partition_conflict_does_not_backfill_legacy_notes(tmp_path: Path) -> None:
    register = _register(tmp_path)
    source = register.mint_canonical('Source')
    target = register.mint_canonical('Target')
    register._write_entry(replace(register.get_entry(source), lifecycle=LIFECYCLE_MERGED, merged_into=target))
    register._write_entry(replace(register.get_entry(target), merged_from=(source,)))
    before = _relation_snapshot(register)
    with pytest.raises(EntityRegisterError, match='multiple partitions'):
        register.split(target, {'A': ['Source'], 'B': ['Source']})
    assert _relation_snapshot(register) == before


def test_register_lock_preserves_two_concurrent_merge_complements(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    conn = FakeOutboxConn()
    register = _register(tmp_path, conn=conn)
    target = register.mint_canonical('Target')
    sources = [register.mint_canonical(label) for label in ('A', 'B')]
    barrier = Barrier(2)
    def merge(source):
        separate = _register(tmp_path, conn=conn)
        barrier.wait(timeout=5)
        separate.merge(source, target)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(merge, sources))
    assert set(register.get_entry(target).merged_from) == set(sources)
    assert len(register.get_entry(target).complements) == 2
    register._validated_entries()
