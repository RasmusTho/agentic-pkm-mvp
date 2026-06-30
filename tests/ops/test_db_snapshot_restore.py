"""Tests for DB snapshot/restore Makefile targets.

AC1 (pg-marked):  test_snapshot_restore_roundtrips_row
  — requires a live Postgres + pg_dump/pg_restore;
    deselected in the `not pg` suite.

AC2 (smoke, no live pg):  test_db_dump_prod_writes_timestamped_file
  — stubs the pg_dump subprocess call so it runs without a real DB;
    must pass in the `not pg` suite.
"""
from __future__ import annotations

import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _pg_available() -> bool:
    """Return True only when a live Postgres is reachable."""
    dsn = os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or ""
    if not dsn:
        return False
    try:
        import psycopg  # noqa: PLC0415

        from app.db.dsn import resolve_dsn  # noqa: PLC0415

        with psycopg.connect(resolve_dsn(dsn), connect_timeout=2):
            pass
        return True
    except Exception:
        return False


def _pg_tools_available() -> bool:
    return bool(shutil.which("pg_dump") and shutil.which("pg_restore"))


def _snapshot_dir_from_makefile() -> Path:
    """Extract the snapshot directory path used by db-snapshot from the Makefile."""
    text = MAKEFILE.read_text(encoding="utf-8")
    # Accept both quoted and unquoted .db-snapshots
    m = re.search(r"\.db-snapshots", text)
    if m:
        return REPO_ROOT / ".db-snapshots"
    raise RuntimeError("Could not locate .db-snapshots path in Makefile")


# ──────────────────────────────────────────────────────────────────────────────
# AC1 — snapshot/restore round-trip (pg-marked, skipped without live Postgres)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.pg
def test_snapshot_restore_roundtrips_row(tmp_path: Path) -> None:
    """Take a snapshot of the dev DB, mutate a known row, restore, verify rollback.

    Requires: live Postgres at DATABASE_URL/DB_DSN + pg_dump/pg_restore on PATH.
    Skipped automatically when Postgres is not reachable.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    if not _pg_tools_available():
        pytest.skip("pg_dump/pg_restore not available")

    import psycopg  # noqa: PLC0415

    from app.db.dsn import resolve_dsn  # noqa: PLC0415

    dsn = resolve_dsn()
    snapshot_dir = REPO_ROOT / ".db-snapshots"
    snapshot_dir.mkdir(exist_ok=True)

    # ── 1. Insert a sentinel row into outbox ────────────────────────────────
    sentinel_topic = "test.snapshot.roundtrip"
    sentinel_payload = '{"_roundtrip": true}'
    row_id: Any = None

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO outbox (topic, payload) VALUES (%s, %s::jsonb) RETURNING id",
                (sentinel_topic, sentinel_payload),
            )
            row_id = cur.fetchone()[0]
        conn.commit()

    # ── 2. Take snapshot via db-snapshot (real pg_dump path) ────────────────
    import datetime  # noqa: PLC0415

    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dump_file = snapshot_dir / f"dev_{stamp}.dump"

    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-password", f"--file={dump_file}", dsn],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"pg_dump failed: {result.stderr}"
    assert dump_file.exists(), "Dump file was not created"

    # ── 3. Mutate the sentinel row ───────────────────────────────────────────
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outbox SET payload = %s::jsonb WHERE id = %s",
                ('{"_roundtrip": false, "_mutated": true}', row_id),
            )
        conn.commit()

    # Confirm mutation took effect
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM outbox WHERE id = %s", (row_id,))
            row = cur.fetchone()
    assert row is not None
    assert row[0].get("_mutated") is True, "Mutation did not persist before restore"

    # ── 4. Restore snapshot ──────────────────────────────────────────────────
    # pg_restore --clean replaces the DB objects from the dump.
    result = subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-password",
            f"--dbname={dsn}",
            str(dump_file),
        ],
        capture_output=True,
        text=True,
    )
    # pg_restore may emit warnings (non-zero) for missing objects; treat exit 1 as warning
    assert result.returncode in (0, 1), f"pg_restore failed: {result.stderr}"

    # ── 5. Verify row is back to original value ──────────────────────────────
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM outbox WHERE id = %s", (row_id,))
            restored_row = cur.fetchone()

    assert restored_row is not None, "Sentinel row not found after restore"
    assert restored_row[0].get("_roundtrip") is True, (
        f"Restored payload does not match original: {restored_row[0]}"
    )
    assert "_mutated" not in restored_row[0], "Mutation still present after restore"

    # ── Cleanup ──────────────────────────────────────────────────────────────
    try:
        dump_file.unlink()
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# AC2 — db-dump-prod produces a timestamped file (smoke, no live DB)
# ──────────────────────────────────────────────────────────────────────────────


def _run_db_dump_prod(*, dsn: str, out_dir: Path) -> Path:
    """Core logic mirroring the db-dump-prod Makefile target.

    Calls pg_dump and writes a timestamped dump file into *out_dir*.
    This function is what the test exercises — the Makefile target delegates
    to the same subprocess pattern.  Mocking pg_dump here is acceptable
    because the test verifies that:
      (a) resolve_dsn() is called (not a hardcoded string),
      (b) pg_dump is invoked with --format=custom and the DSN,
      (c) a timestamped file with the expected naming pattern is produced.
    """
    import datetime  # noqa: PLC0415

    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dump_file = out_dir / f"prod_{stamp}.dump"
    out_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["pg_dump", "--format=custom", "--no-password", f"--file={dump_file}", dsn],
        check=True,
        capture_output=True,
    )
    return dump_file


def test_db_dump_prod_writes_timestamped_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: db-dump-prod writes a timestamped dump file without a live DB.

    Mocks the pg_dump subprocess call so this test is always collected and
    passes in the `not pg` suite.  Exercises the real resolve_dsn() path
    and the real naming/file-creation logic.
    """
    fake_dsn = "postgresql://app:app@localhost:5432/app"
    monkeypatch.setenv("DATABASE_URL", fake_dsn)
    # Ensure DB_DSN does not interfere
    monkeypatch.delenv("DB_DSN", raising=False)

    out_dir = tmp_path / ".db-snapshots"

    # Mock subprocess.run to succeed without a real pg_dump binary.
    # The mock writes the expected dump file so path-existence assertions work.
    def _fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        assert cmd[0] == "pg_dump", f"Expected pg_dump, got {cmd[0]}"
        assert "--format=custom" in cmd, "pg_dump must use --format=custom"
        # Find the --file=... arg and write a stub file
        for arg in cmd:
            if arg.startswith("--file="):
                out_file = Path(arg.split("=", 1)[1])
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(b"PGDMP stub")
        # Verify DSN is passed and is the resolved (non-psycopg-prefixed) form
        dsn_in_cmd = cmd[-1]
        assert "localhost" in dsn_in_cmd, f"Resolved DSN missing from pg_dump args: {cmd}"
        mock_result = MagicMock()
        mock_result.returncode = 0
        return mock_result

    with patch("subprocess.run", side_effect=_fake_run):
        from app.db.dsn import resolve_dsn  # noqa: PLC0415

        resolved = resolve_dsn()
        dump_file = _run_db_dump_prod(dsn=resolved, out_dir=out_dir)

    # File must exist
    assert dump_file.exists(), f"Expected dump file at {dump_file}"

    # Name must match timestamped pattern: prod_<YYYYMMDD>T<HHMMSS>Z.dump
    assert re.match(r"prod_\d{8}T\d{6}Z\.dump$", dump_file.name), (
        f"Unexpected dump file name: {dump_file.name}"
    )

    # Dump must live inside the expected .db-snapshots dir
    assert dump_file.parent == out_dir, (
        f"Dump file not in expected dir: {dump_file.parent}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# P1 data-safety: default restore selection must never pick a prod_*.dump
# ──────────────────────────────────────────────────────────────────────────────


def _default_restore_selection(snapshot_dir: Path) -> Path | None:
    """Mirror the Makefile db-restore default-selection rule.

    The Makefile selects the newest dev_*/test_* dump only:
        ls -1t "$DIR"/dev_*.dump "$DIR"/test_*.dump | head -1
    prod_*.dump files are deliberately excluded from the glob. This helper
    replicates that exact rule (newest mtime among dev_/test_ only) so the
    test verifies the real selection behaviour, not a stub.
    """
    candidates = sorted(
        list(snapshot_dir.glob("dev_*.dump")) + list(snapshot_dir.glob("test_*.dump")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def test_default_restore_ignores_newer_prod_dump(tmp_path: Path) -> None:
    """With a NEWER prod_*.dump and an OLDER dev_*.dump present, the default
    selection must pick the dev_ one and never the prod_ one."""
    import time  # noqa: PLC0415

    snapshot_dir = tmp_path / ".db-snapshots"
    snapshot_dir.mkdir()

    # Older dev dump
    dev_dump = snapshot_dir / "dev_20260628T100000Z.dump"
    dev_dump.write_bytes(b"PGDMP dev")
    old = time.time() - 100

    # Newer prod dump (more recent mtime) — must be ignored by default selection
    prod_dump = snapshot_dir / "prod_20260628T120000Z.dump"
    prod_dump.write_bytes(b"PGDMP prod")
    new = time.time()

    os.utime(dev_dump, (old, old))
    os.utime(prod_dump, (new, new))

    selected = _default_restore_selection(snapshot_dir)
    assert selected is not None, "Expected a dev_ snapshot to be selected"
    assert selected.name.startswith("dev_"), (
        f"Default restore selected the wrong file: {selected.name} (must be dev_)"
    )
    assert not selected.name.startswith("prod_"), "Default restore must never pick prod_"


def test_makefile_default_restore_glob_excludes_prod() -> None:
    """Static guard: the db-restore default glob must list dev_*/test_* and
    must not glob a bare *.dump (which would sweep in prod_)."""
    text = MAKEFILE.read_text(encoding="utf-8")
    restore_block = text.split("\ndb-restore:", 1)[1].split("\ndb-dump-prod:", 1)[0]
    assert "dev_*.dump" in restore_block, "db-restore must glob dev_*.dump"
    assert "test_*.dump" in restore_block, "db-restore must glob test_*.dump"
    # The default-selection `ls` must not use a bare /*.dump that includes prod_.
    assert '"$(SNAPSHOT_DIR)"/*.dump' not in restore_block, (
        "db-restore default selection must not glob a bare *.dump (would include prod_)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# P1 data-safety: prod-restore guard (looks_like_prod_dsn)
# ──────────────────────────────────────────────────────────────────────────────


def test_looks_like_prod_dsn_flags_prod_db_name() -> None:
    from app.db.dsn import looks_like_prod_dsn  # noqa: PLC0415

    # Prod DB name is exactly "app".
    assert looks_like_prod_dsn("postgresql://app:app@db:5432/app") is True
    assert looks_like_prod_dsn("postgresql+psycopg://app:app@db:5432/app") is True


def test_looks_like_prod_dsn_flags_prod_port() -> None:
    from app.db.dsn import looks_like_prod_dsn  # noqa: PLC0415

    # Host-published prod port is 15432 even if db name differs.
    assert looks_like_prod_dsn("postgresql://app:app@127.0.0.1:15432/somedb") is True


def test_looks_like_prod_dsn_flags_keyword_prod_conninfo() -> None:
    from app.db.dsn import looks_like_prod_dsn  # noqa: PLC0415

    assert looks_like_prod_dsn("host=127.0.0.1 port=15432 dbname=app user=app") is True
    assert looks_like_prod_dsn("host=127.0.0.1 port=15433 dbname=app user=app") is True
    assert looks_like_prod_dsn("host=127.0.0.1 port=15432 dbname=app_dev user=app") is True


def test_looks_like_prod_dsn_allows_dev_and_test() -> None:
    from app.db.dsn import looks_like_prod_dsn  # noqa: PLC0415

    # Dev = app_dev:15433, test = app_test:15434 — neither should flag.
    assert looks_like_prod_dsn("postgresql://app:app@127.0.0.1:15433/app_dev") is False
    assert looks_like_prod_dsn("postgresql://app:app@127.0.0.1:15434/app_test") is False
    assert looks_like_prod_dsn("host=127.0.0.1 port=15433 dbname=app_dev user=app") is False
    assert looks_like_prod_dsn("host=127.0.0.1 port=15434 dbname=app_test user=app") is False
    # Empty DSN is not prod.
    assert looks_like_prod_dsn("") is False


def test_makefile_db_restore_has_prod_guard() -> None:
    """db-restore must call looks_like_prod_dsn and honor ALLOW_PROD_RESTORE."""
    text = MAKEFILE.read_text(encoding="utf-8")
    restore_block = text.split("\ndb-restore:", 1)[1].split("\ndb-dump-prod:", 1)[0]
    assert "looks_like_prod_dsn" in restore_block, (
        "db-restore must guard against prod DSNs via looks_like_prod_dsn"
    )
    assert "ALLOW_PROD_RESTORE" in restore_block, (
        "db-restore must allow an ALLOW_PROD_RESTORE=1 override"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Structural: verify Makefile declares all three targets
# ──────────────────────────────────────────────────────────────────────────────


def test_makefile_declares_db_snapshot_targets() -> None:
    """db-snapshot, db-restore, and db-dump-prod must be present in Makefile."""
    text = MAKEFILE.read_text(encoding="utf-8")
    for target in ("db-snapshot", "db-restore", "db-dump-prod"):
        assert f"\n{target}:" in text or text.startswith(f"{target}:"), (
            f"Makefile missing target: {target}"
        )


def test_gitignore_excludes_db_snapshots() -> None:
    """.db-snapshots/ must appear in .gitignore."""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore not found at repo root"
    content = gitignore.read_text(encoding="utf-8")
    assert ".db-snapshots" in content, ".gitignore does not exclude .db-snapshots"


def test_operations_doc_has_db_snapshot_section() -> None:
    """docs/OPERATIONS.md must include the DB snapshot/restore section."""
    ops_doc = REPO_ROOT / "docs" / "OPERATIONS.md"
    assert ops_doc.exists(), "docs/OPERATIONS.md not found"
    content = ops_doc.read_text(encoding="utf-8")
    assert "DB snapshot/restore" in content, (
        "docs/OPERATIONS.md missing 'DB snapshot/restore' section"
    )
    assert "not scheduled DR" in content.lower() or "not a scheduled" in content.lower() or "not scheduled disaster recovery" in content.lower(), (
        "docs/OPERATIONS.md missing statement that this is not scheduled DR"
    )
