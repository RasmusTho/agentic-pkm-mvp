"""Synthetic Codex-host source: no real Codex session or external effect."""
from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path
import sqlite3

import pytest

from scripts import codex_session_relations as relations


@pytest.fixture
def codex_source(tmp_path, monkeypatch):
    source = tmp_path / "state_5.sqlite"
    child = tmp_path / "child.jsonl"
    parent = tmp_path / "parent.jsonl"
    monkeypatch.setattr(relations, "STATE_DB", source)
    monkeypatch.setattr(relations, "CHILD_JOURNAL", child)
    monkeypatch.setattr(relations, "PARENT_JOURNAL", parent)
    writer = sqlite3.connect(source)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    writer.execute("CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, thread_source TEXT)")
    writer.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT NOT NULL, child_thread_id TEXT PRIMARY KEY NOT NULL, status TEXT NOT NULL)")
    writer.execute("CREATE TABLE vault_secret(value TEXT)")
    writer.execute("INSERT INTO threads VALUES (?, ?, ?)", (relations.CHILD, str(child), "subagent"))
    writer.execute("INSERT INTO threads VALUES (?, ?, ?)", (relations.PARENT, str(parent), "user"))
    writer.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", (relations.PARENT, relations.CHILD, "open"))
    writer.commit()
    yield {"source": source, "child": child, "parent": parent, "writer": writer}
    writer.close()


def test_fixed_source_and_import_boundary():
    assert not inspect.signature(relations.read_6561).parameters
    assert relations.STATE_DB == Path.home() / ".codex/state_5.sqlite"
    tree = ast.parse(Path(relations.__file__).read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    assert imports == {"__future__", "contextlib", "os", "pathlib", "sqlite3", "stat", "typing", "uuid"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"executescript", "executemany"} for node in ast.walk(tree))


def test_authorizer_denies_unrelated_tables_mutation_attach_and_unsafe_pragma(codex_source):
    db = sqlite3.connect(codex_source["source"])
    try:
        db.set_authorizer(relations._authorize)
        assert db.execute("SELECT id FROM threads WHERE id=?", (relations.CHILD,)).fetchall()
        for sql in ("SELECT * FROM vault_secret", "INSERT INTO vault_secret VALUES ('x')",
                    "PRAGMA writable_schema=ON", "ATTACH DATABASE ':memory:' AS other"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(sql)
    finally:
        db.close()


def test_readonly_projection_preserves_source_and_returns_only_target(codex_source):
    source = codex_source["source"]
    wal = Path(str(source) + "-wal")
    before = (hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(wal.read_bytes()).hexdigest())
    result = relations.read_6561()
    after = (hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(wal.read_bytes()).hexdigest())
    assert before == after
    assert result == {"source": str(source), "parent": relations.PARENT, "child": relations.CHILD,
        "child_rollout": str(codex_source["child"]), "parent_rollout": str(codex_source["parent"]),
        "child_thread_source": "subagent", "registered_children": []}


def test_unrelated_wal_changes_do_not_change_target_projection(codex_source):
    before = relations.read_6561()
    writer = codex_source["writer"]
    writer.execute("INSERT INTO threads VALUES (?, ?, ?)", ("unrelated", "/other", "user"))
    writer.commit()
    assert relations.read_6561() == before


def test_target_write_during_snapshot_is_seen_by_next_snapshot(codex_source, monkeypatch):
    writer = codex_source["writer"]
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    original = relations._schema
    inserted = False
    def schema(db):
        nonlocal inserted
        original(db)
        if not inserted:
            inserted = True
            writer.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                           (relations.CHILD, "00000000-0000-4000-8000-000000000001", "open"))
            writer.commit()
    monkeypatch.setattr(relations, "_schema", schema)
    assert relations.read_6561()["registered_children"] == []
    # Test-only immutable read intentionally ignores WAL, proving that the
    # committed child exists solely in WAL before the second real snapshot.
    source = codex_source["source"]
    immutable = sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        assert immutable.execute("SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?",
                                 (relations.CHILD,)).fetchall() == []
    finally:
        immutable.close()
    assert relations.read_6561()["registered_children"] == ["00000000-0000-4000-8000-000000000001"]


@pytest.mark.parametrize("mutation", ["child_path", "parent_path", "child_source", "upstream", "malformed_child"])
def test_wrong_target_or_malformed_child_refuses(codex_source, mutation):
    db = codex_source["writer"]
    if mutation == "child_path":
        db.execute("UPDATE threads SET rollout_path='/different' WHERE id=?", (relations.CHILD,))
    elif mutation == "parent_path":
        db.execute("UPDATE threads SET rollout_path='/different' WHERE id=?", (relations.PARENT,))
    elif mutation == "child_source":
        db.execute("UPDATE threads SET thread_source='user' WHERE id=?", (relations.CHILD,))
    elif mutation == "upstream":
        db.execute("UPDATE thread_spawn_edges SET parent_thread_id='different' WHERE child_thread_id=?", (relations.CHILD,))
    else:
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", (relations.CHILD, "not-a-uuid", "open"))
    db.commit()
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    source = tmp_path / "missing.sqlite"
    monkeypatch.setattr(relations, "STATE_DB", source)
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()
    assert not source.exists()
    assert list(tmp_path.iterdir()) == []


def test_symlink_source_refuses(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.write_bytes(b"not a database")
    link = tmp_path / "state_5.sqlite"
    link.symlink_to(actual)
    monkeypatch.setattr(relations, "STATE_DB", link)
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()


def test_wal_without_existing_shm_refuses_without_creating_it(tmp_path, monkeypatch):
    source = tmp_path / "state_5.sqlite"
    source.write_bytes(b"not a database")
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"synthetic")
    shm = Path(str(source) + "-shm")
    monkeypatch.setattr(relations, "STATE_DB", source)
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()
    assert not shm.exists()


def test_unqualified_schema_or_view_refuses(tmp_path, monkeypatch):
    source = tmp_path / "state_5.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE base(id TEXT, rollout_path TEXT, thread_source TEXT)")
        db.execute("CREATE VIEW threads AS SELECT * FROM base")
        db.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
    monkeypatch.setattr(relations, "STATE_DB", source)
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()


def test_only_fixed_sql_and_designated_importer_are_allowed():
    repo = Path(__file__).resolve().parents[2]
    source = repo / "scripts/codex_session_relations.py"
    tree = ast.parse(source.read_text())
    expected = {
        "PRAGMA query_only=ON", "PRAGMA trusted_schema=OFF", "BEGIN",
        "SELECT type, sql FROM sqlite_master WHERE name=?",
        "SELECT id, rollout_path, thread_source FROM threads WHERE id=?",
        "SELECT id, rollout_path FROM threads WHERE id=?",
        "SELECT parent_thread_id FROM thread_spawn_edges WHERE child_thread_id=?",
        "SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=? ORDER BY child_thread_id LIMIT ?",
    }
    observed = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"):
            assert node.args
            if isinstance(node.args[0], ast.Constant):
                observed.add(node.args[0].value)
            else:
                assert isinstance(node.args[0], ast.Name) and node.args[0].id == "pragma"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"eval", "exec", "__import__"}
    assert observed == expected
    pragmas = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
               and isinstance(node.value, str) and node.value.startswith("PRAGMA table_info(")}
    assert pragmas == {"PRAGMA table_info(threads)", "PRAGMA table_info(thread_spawn_edges)"}
    importers = []
    for root in (repo / "app", repo / "scripts"):
        for path in root.rglob("*.py"):
            parsed = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(parsed):
                is_importer = (isinstance(node, ast.ImportFrom)
                               and (node.module == "scripts.codex_session_relations" or
                                    (node.module == "scripts" and
                                     any(alias.name == "codex_session_relations" for alias in node.names))))
                is_importer |= (isinstance(node, ast.Import)
                                and any(alias.name == "scripts.codex_session_relations" for alias in node.names))
                if is_importer:
                    importers.append(str(path.relative_to(repo)))
    assert importers == ["app/builderops/legacy_codex_6561_guard.py"]


def test_world_writable_codex_database_refuses(codex_source):
    source = codex_source["source"]
    source.chmod(0o666)
    try:
        with pytest.raises(relations.RelationsUnavailable, match="unqualified"):
            relations.read_6561()
    finally:
        source.chmod(0o600)


def test_source_inode_change_during_readback_refuses(codex_source, monkeypatch):
    original = relations._source_identity
    calls = 0
    def changed():
        nonlocal calls
        value = original()
        calls += 1
        if calls == 2:
            main, wal, shm = value
            return ((main[0], main[1] + 1), wal, shm)
        return value
    monkeypatch.setattr(relations, "_source_identity", changed)
    with pytest.raises(relations.RelationsUnavailable, match="identity changed"):
        relations.read_6561()
    assert calls == 2


def test_replaced_database_during_open_is_rejected(codex_source, monkeypatch):
    import os
    import shutil
    source = codex_source["source"]
    replacement = source.with_name("replacement.sqlite")
    shutil.copyfile(source, replacement)
    original = relations._schema
    swapped = False
    def schema(db):
        nonlocal swapped
        original(db)
        if not swapped:
            swapped = True
            os.replace(replacement, source)
    monkeypatch.setattr(relations, "_schema", schema)
    with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
        relations.read_6561()
    assert swapped


def test_exclusive_lock_fails_closed_instead_of_creating_fallback(tmp_path, monkeypatch):
    source = tmp_path / "state_5.sqlite"
    writer = sqlite3.connect(source, timeout=0)
    try:
        writer.execute("CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, thread_source TEXT)")
        writer.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT NOT NULL, child_thread_id TEXT PRIMARY KEY NOT NULL, status TEXT NOT NULL)")
        writer.commit()
        writer.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(relations, "STATE_DB", source)
        with pytest.raises(relations.RelationsUnavailable, match="UNKNOWN"):
            relations.read_6561()
    finally:
        writer.close()
    assert not (tmp_path / "state_5.sqlite-wal").exists()


def test_wal_mode_without_sidecars_refuses_without_creating_them(tmp_path, monkeypatch):
    source = tmp_path / "state_5.sqlite"
    db = sqlite3.connect(source)
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.execute("CREATE TABLE data(value TEXT)")
    db.commit()
    db.close()
    wal, shm = Path(str(source) + "-wal"), Path(str(source) + "-shm")
    wal.unlink(missing_ok=True)
    shm.unlink(missing_ok=True)
    assert source.read_bytes()[18:20] == b"\x02\x02"
    monkeypatch.setattr(relations, "STATE_DB", source)
    with pytest.raises(relations.RelationsUnavailable, match="sidecars"):
        relations.read_6561()
    assert not wal.exists() and not shm.exists()
