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

    with pytest.raises(EntityRegisterError, match="complete successor complement"):
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

    with pytest.raises(EntityRegisterError, match="contradictory partial"):
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
    assert register.get_entry(source).lineage == ()
    register.merge(target, evolved, operation_id="target-evolution")

    assert register.ensure_merge_effects(
        source, target, operation_id="journal-operation"
    ) == MERGE_EFFECTS_COMPLETE
    assert register.resolve_target_evolution(
        source, target, operation_id="journal-operation"
    ) == evolved


def test_evolved_source_only_merge_backfills_lineage_but_refuses_missing_complement(
    tmp_path: Path,
) -> None:
    """Lineage backfill cannot turn a half-applied original merge into complete."""
    register = _effect_register(tmp_path)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    evolved = register.mint_canonical("Evolved")

    register.arm(fail_on_write=2)
    with pytest.raises(EntityRegisterError, match="simulated crash"):
        register.ensure_merge_effects(source, target)
    register.disarm()
    register.merge(target, evolved, operation_id="target-evolution")

    with pytest.raises(EntityRegisterError, match="original target complement"):
        register.ensure_merge_effects(
            source, target, operation_id="journal-operation"
        )
    source_entry = register.get_entry(source)
    assert source_entry is not None
    assert source_entry.lineage[-1]["operation_id"] == "journal-operation"
    assert source not in register.get_entry(target).merged_from
    assert source not in register.get_entry(evolved).merged_from


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

    with pytest.raises(EntityRegisterError, match="complete successor complement"):
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
    with pytest.raises(EntityRegisterError, match="contradictory notes"):
        register.merge_effect_state(a, b)


def test_merge_into_evolved_target_is_refused(tmp_path: Path) -> None:
    """Review F2 (#4350): INV-EROJ-7 / partial-failure matrix row 5. A target
    that has itself been merged away refuses both fresh application and
    resume — this slice cannot prove target-evolved recovery (EROJ-02)."""
    register = _effect_register(tmp_path)
    a = register.mint_canonical("Alpha")
    b = register.mint_canonical("Beta")
    c = register.mint_canonical("Gamma")

    # Crash after the source redirect for a -> b, then b evolves into c.
    register.arm(fail_on_write=2)
    with pytest.raises(EntityRegisterError, match="simulated crash"):
        register.ensure_merge_effects(a, b)
    register.disarm()
    register.merge(b, c)

    # Resume of the half-applied a -> b merge is refused, loudly.
    with pytest.raises(EntityRegisterError, match="target has evolved"):
        register.merge_effect_state(a, b)
    with pytest.raises(EntityRegisterError, match="target has evolved"):
        register.ensure_merge_effects(a, b)
    # The half-applied state was not silently completed.
    assert a not in register.get_entry(c).merged_from
    assert a not in register.get_entry(b).merged_from

    # Fresh application into a merged-away target is refused the same way —
    # a deliberate fail-closed behavior change to merge() (previously it
    # silently merged into the dead identity).
    d = register.mint_canonical("Delta")
    with pytest.raises(EntityRegisterError, match="target has evolved"):
        register.merge(d, b)
    assert register.get_entry(d).lifecycle == LIFECYCLE_CANONICAL
