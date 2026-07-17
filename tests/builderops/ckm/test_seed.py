from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.ckm.seed import SeedManifestError, load_manifest, seed_capabilities
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    value = CkmStore(tmp_path / "builderops.sqlite3")
    value.ensure_schema()
    return value


def _manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "capabilities.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_manifest_covers_sbs_and_sources_resolve() -> None:
    entries = load_manifest()
    assert len({entry.stable_key for entry in entries}) == len(entries)
    roots = [entry for entry in entries if entry.parent is None]
    boundaries = [entry for entry in entries if entry.boundary_ref is not None and len(entry.slug) == 3]
    assert len(roots) == 8
    assert {entry.slug.upper() for entry in boundaries} == {
        "HIX", "WSP", "HKA", "SIP", "GOV", "EBF", "PDM", "DRI", "RCA", "MEM", "CAO", "EXE", "SFC", "OEF"
    }


def test_loader_rejects_duplicates_and_cycles(tmp_path: Path) -> None:
    duplicate = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: one, stable_key: stable-one, name: One, definition: First, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: one, stable_key: stable-two, name: Two, definition: Second, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    with pytest.raises(SeedManifestError, match="duplicate capability slug"):
        load_manifest(duplicate)

    cycle = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: one, stable_key: stable-one, name: One, definition: First, parent: two, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: two, stable_key: stable-two, name: Two, definition: Second, parent: one, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    with pytest.raises(SeedManifestError, match="parent cycle"):
        load_manifest(cycle)


def test_loader_rejects_duplicate_names_across_distinct_slugs(tmp_path: Path) -> None:
    # Public identity no longer depends on name, but the display-name uniqueness
    # contract still rejects two distinct stable capabilities with one name.
    duplicate_name = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: one, stable_key: stable-one, name: Same Name, definition: First, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: two, stable_key: stable-two, name: Same Name, definition: Second, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    with pytest.raises(SeedManifestError, match="duplicate capability name"):
        load_manifest(duplicate_name)


def test_seed_idempotent_and_incremental(store: CkmStore, tmp_path: Path) -> None:
    first = seed_capabilities(store)
    before = {item.name: item.to_dict() for item in store.list_capabilities()}
    second = seed_capabilities(store)
    assert first["changed"] == first["seeded"]
    assert second["changed"] == 0
    assert {item.name: item.to_dict() for item in store.list_capabilities()} == before

    manifest = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: root, stable_key: stable-root, name: Root, definition: Root definition, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: child, stable_key: stable-child, name: Child, definition: Child definition, parent: root, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    small_store = CkmStore(tmp_path / "small.sqlite3")
    small_store.ensure_schema()
    seed_capabilities(small_store, manifest_path=manifest)
    changed_manifest = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: root, stable_key: stable-root, name: Root, definition: Root definition changed, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: child, stable_key: stable-child, name: Child, definition: Child definition, parent: root, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    result = seed_capabilities(small_store, manifest_path=changed_manifest)
    assert result["changed"] == 1
    assert small_store.get_capability_by_name("Root").definition == "Root definition changed"


def test_seeded_rows_carry_provenance(store: CkmStore) -> None:
    seed_capabilities(store)
    assert all(
        capability.existence_provenance.startswith("seeded:docs/")
        for capability in store.list_capabilities()
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["ckm", "seed"],
        ["builderops", "ckm", "seed"],
    ],
)
def test_cli_ckm_seed_reachable_at_documented_and_nested_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    # docs/CAPABILITY_KNOWLEDGE_MODEL/*.md document every `ckm` subcommand as
    # `python -m app.builderops ckm <verb>` (no `builderops` segment). The
    # standalone entry point historically only exposed `ckm` nested under
    # `builderops`, so the documented path raised "No such command 'ckm'".
    db_path = tmp_path / "builderops.sqlite3"
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(db_path))
    monkeypatch.delenv("BUILDEROPS_VAULT_ROOT", raising=False)

    first = CliRunner().invoke(builderops_standalone_root, argv, catch_exceptions=False)
    assert first.exit_code == 0, first.output
    assert "seeded 31 capabilities, 31 changed" in first.output

    second = CliRunner().invoke(builderops_standalone_root, argv, catch_exceptions=False)
    assert second.exit_code == 0, second.output
    assert "seeded 31 capabilities, 0 changed" in second.output


def test_cli_ckm_seed_wraps_write_path_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(db_path))
    monkeypatch.delenv("BUILDEROPS_VAULT_ROOT", raising=False)

    def _boom(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("app.builderops.cli.seed_capabilities", _boom)

    result = CliRunner().invoke(
        builderops_standalone_root, ["ckm", "seed"], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert "database is locked" in result.output
    assert "idempotent" in result.output


def test_cli_ckm_seed_wraps_ensure_schema_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ensure_schema() runs before seed_capabilities() and can itself hit a
    # write-path sqlite error (e.g. lock contention creating the ckm_* DDL);
    # it must be covered by the same handling, not left to raise a raw
    # traceback outside the try block.
    db_path = tmp_path / "builderops.sqlite3"
    monkeypatch.setenv("BUILDEROPS_DB_PATH", str(db_path))
    monkeypatch.delenv("BUILDEROPS_VAULT_ROOT", raising=False)

    def _boom(self: CkmStore) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(CkmStore, "ensure_schema", _boom)

    result = CliRunner().invoke(
        builderops_standalone_root, ["ckm", "seed"], catch_exceptions=False
    )
    assert result.exit_code != 0
    assert "database is locked" in result.output
    assert "idempotent" in result.output
