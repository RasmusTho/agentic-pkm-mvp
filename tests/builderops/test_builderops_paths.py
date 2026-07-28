from __future__ import annotations

from pathlib import Path
import os

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops.boundary import BuilderOpsBoundary
from app.builderops.completeness_report import load_records_from_db
from app.builderops.config import load_paths
from app.builderops.store import SqliteBuilderOpsStore


def _run(args: list[str], env: dict[str, str]):
    return CliRunner().invoke(builderops_root, ["builderops", *args], env=env, catch_exceptions=False)


def test_resolves_shared_vault_and_local_state_independently(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    paths = load_paths(
        {
            "BUILDEROPS_VAULT_ROOT": str(vault),
            "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
        }
    )

    assert paths.vault_root == vault
    assert paths.db_path.parent != vault


def test_shared_vault_bootstrap_creates_advisory_claims_but_never_sqlite(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "init", str(vault), "--json"], env)

    assert result.exit_code == 0
    assert (vault / "agent-delivery" / "Ready").is_dir()
    assert not (vault / "builderops.sqlite3").exists()
    assert (vault / ".builderops" / "claims").is_dir()


def test_rejects_sqlite_but_allows_advisory_claim_state_inside_shared_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    _run(["vault", "init", str(vault), "--json"], env)
    (vault / "builderops.sqlite3").write_text("not a database", encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert "forbidden SQLite state" in result.output


def test_rejects_configured_sqlite_under_shared_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"

    with pytest.raises(ValueError, match="BUILDEROPS_DB_PATH"):
        load_paths(
            {
                "BUILDEROPS_VAULT_ROOT": str(vault),
                "BUILDEROPS_DB_PATH": str(vault / "builderops.sqlite3"),
            }
        )


def test_validate_rejects_mismatched_configured_root(tmp_path: Path) -> None:
    configured = tmp_path / "configured-vault"
    other = tmp_path / "other-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(configured),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "validate", str(other), "--json"], env)

    assert result.exit_code != 0
    assert "does not match BUILDEROPS_VAULT_ROOT" in result.output


def test_global_db_path_override_is_used_by_paths_and_validation(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "safe" / "builderops.sqlite3"),
    }
    override = vault / "override.sqlite3"

    paths = _run(
        ["--db-path", str(override), "vault", "paths", "--json"],
        env,
    )
    validated = _run(
        ["--db-path", str(override), "vault", "validate", str(vault), "--json"],
        env,
    )

    assert paths.exit_code != 0
    assert "BUILDEROPS_DB_PATH" in paths.output
    assert validated.exit_code != 0
    assert "BUILDEROPS_DB_PATH" in validated.output


def test_global_db_path_override_cannot_create_store_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    override = vault / "override.sqlite3"
    env = {"BUILDEROPS_VAULT_ROOT": str(vault)}

    result = _run(
        ["--db-path", str(override), "list", "--json"],
        env,
    )

    assert result.exit_code != 0
    assert "BUILDEROPS_DB_PATH" in result.output
    assert not override.exists()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("state.db", "not a database"),
        ("opaque-state", b"SQLite format 3\x00" + b"\x00" * 16),
    ],
)
def test_validate_rejects_nested_sqlite_file(
    tmp_path: Path,
    filename: str,
    content: str | bytes,
) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    nested = vault / "transient" / filename
    nested.parent.mkdir(parents=True)
    if isinstance(content, bytes):
        nested.write_bytes(content)
    else:
        nested.write_text(content, encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert str(nested) in result.output


def test_all_builderops_store_entrypoints_reject_sqlite_inside_shared_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    monkeypatch.setenv("BUILDEROPS_VAULT_ROOT", str(vault))

    direct_path = vault / "direct.sqlite3"
    with pytest.raises(ValueError, match="outside BUILDEROPS_VAULT_ROOT"):
        SqliteBuilderOpsStore(direct_path).initialize()
    assert not direct_path.exists()

    boundary_path = vault / "boundary.sqlite3"
    with pytest.raises(ValueError, match="outside BUILDEROPS_VAULT_ROOT"):
        BuilderOpsBoundary.from_path(boundary_path)
    assert not boundary_path.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    for name, open_store in (
        ("direct-link.sqlite3", lambda path: SqliteBuilderOpsStore(path).initialize()),
        ("boundary-link.sqlite3", lambda path: BuilderOpsBoundary.from_path(path)),
    ):
        linked_path = vault / name
        target = outside / name
        try:
            linked_path.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        with pytest.raises(ValueError, match="outside BUILDEROPS_VAULT_ROOT"):
            open_store(linked_path)
        assert not target.exists()

    readable_target = outside / "completeness.sqlite3"
    monkeypatch.delenv("BUILDEROPS_VAULT_ROOT")
    SqliteBuilderOpsStore(readable_target).initialize()
    monkeypatch.setenv("BUILDEROPS_VAULT_ROOT", str(vault))
    linked_report = vault / "completeness.sqlite3"
    linked_report.symlink_to(readable_target)

    records, storage = load_records_from_db(linked_report)

    assert records is None
    assert storage["available"] is False
    assert storage["reason"] == "unreadable_builderops_db"


def test_completeness_report_is_read_only_across_missing_path_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    db_path.write_bytes(b"existing")
    original_exists = Path.exists
    raced = False

    def disappears_after_discovery(path: Path) -> bool:
        nonlocal raced
        if path == db_path and not raced:
            raced = True
            path.unlink()
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", disappears_after_discovery)

    records, storage = load_records_from_db(db_path)

    assert records is None
    assert storage["available"] is False
    assert storage["reason"] == "unreadable_builderops_db"
    assert not os.path.lexists(db_path)


@pytest.mark.parametrize("ancestor", ["agent-delivery", ".builderops"])
def test_shared_vault_bootstrap_rejects_symlinked_ancestors_without_outside_writes(
    tmp_path: Path,
    ancestor: str,
) -> None:
    vault = tmp_path / "shared-vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    try:
        (vault / ancestor).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "init", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert "symlink" in result.output.lower()
    assert list(outside.iterdir()) == []


def test_validation_rejects_symlinked_sqlite_candidate_without_following_it(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "shared-vault"
    outside = tmp_path / "outside.sqlite3"
    vault.mkdir()
    outside.write_bytes(b"SQLite format 3\x00" + b"external-marker")
    candidate = vault / "linked.sqlite3"
    try:
        candidate.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert "symlink" in result.output.lower()
    assert outside.read_bytes() == b"SQLite format 3\x00" + b"external-marker"


def _simulate_evicted_vault(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Make every vault file look like an un-materialized iCloud file.

    On the real shared vault the first ``open()`` of an evicted file costs a
    network round-trip (measured ~1.0-1.2 s each), which is why validating a
    ~900-file vault did not terminate. Here the eviction is simulated and the
    opened paths are recorded, so the test can assert what the scan actually
    reads rather than how long it takes.
    """
    from app.builderops import vault_queue

    opened: list[Path] = []
    monkeypatch.setattr(vault_queue, "_content_is_local", lambda stat_result: False)

    real_open = Path.open

    def recording_open(self: Path, *args: object, **kwargs: object):
        opened.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)
    return opened


def test_vault_validate_detects_extensionless_sqlite_without_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confinement invariant holds without opening every vault file."""
    import sqlite3

    vault = tmp_path / "shared-vault"
    notes = vault / "model-inquiries"
    notes.mkdir(parents=True)
    for index in range(50):
        # Ordinary vault material: never a page-size multiple, so an evicted
        # copy must not be materialized just to read 16 bytes.
        (notes / f"note-{index:03d}.md").write_text("x" * (700 + index), encoding="utf-8")

    hidden = vault / "transient" / "opaque-state"
    hidden.parent.mkdir(parents=True)
    connection = sqlite3.connect(hidden)
    connection.execute("CREATE TABLE t (a INTEGER)")
    connection.commit()
    connection.close()
    assert hidden.suffix == ""
    assert hidden.stat().st_size % 512 == 0

    opened = _simulate_evicted_vault(monkeypatch)

    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert f"forbidden SQLite state in shared vault: {hidden}" in result.output

    # The database was read; the notes that cannot be database images were not.
    assert hidden in opened
    assert [path for path in opened if path.parent == notes] == []


def test_vault_validate_still_opens_local_files_for_the_header_sniff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing narrows for a normal local vault: the sniff is unchanged there.

    Local reads are cheap (a full 900-file vault sniffs in ~0.1 s), so an
    extension-less file that merely starts with the magic bytes is still
    caught exactly as before.
    """
    from app.builderops import vault_queue

    vault = tmp_path / "shared-vault"
    nested = vault / "transient" / "opaque-state"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)

    assert vault_queue._content_is_local(nested.stat()) is True
    assert vault_queue._sqlite_candidates(vault) == [nested]


def test_vault_validate_reports_scan_stats_and_preserves_symlink_rejection(
    tmp_path: Path,
) -> None:
    from app.builderops import vault_queue
    from app.builderops.config import load_paths

    vault = tmp_path / "shared-vault"
    vault.mkdir()
    (vault / "note.md").write_text("hello\n", encoding="utf-8")
    seen: list[dict[str, int]] = []

    payload = vault_queue.validate_vault(
        vault,
        load_paths(
            {
                "BUILDEROPS_VAULT_ROOT": str(vault),
                "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
            }
        ),
        on_progress=seen.append,
    )

    assert payload["sqlite_scan"]["files"] == 1
    assert payload["sqlite_scan"]["opened"] == 1
    assert payload["sqlite_scan"]["skipped_remote"] == 0
    assert seen == [{"files": 1, "opened": 0, "skipped_remote": 0, "elapsed_ms": 0}]

    outside = tmp_path / "outside.md"
    outside.write_text("elsewhere\n", encoding="utf-8")
    try:
        (vault / "linked.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(vault_queue.VaultQueueError, match="must not be a symlink"):
        vault_queue._sqlite_candidates(vault)
