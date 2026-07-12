from __future__ import annotations

from pathlib import Path

import pytest

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
        "  - {id: one, name: One, definition: First, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: one, name: Two, definition: Second, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    with pytest.raises(SeedManifestError, match="duplicate capability slug"):
        load_manifest(duplicate)

    cycle = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: one, name: One, definition: First, parent: two, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: two, name: Two, definition: Second, parent: one, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    with pytest.raises(SeedManifestError, match="parent cycle"):
        load_manifest(cycle)


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
        "  - {id: root, name: Root, definition: Root definition, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: child, name: Child, definition: Child definition, parent: root, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
    )
    small_store = CkmStore(tmp_path / "small.sqlite3")
    small_store.ensure_schema()
    seed_capabilities(small_store, manifest_path=manifest)
    changed_manifest = _manifest(
        tmp_path,
        "capabilities:\n"
        "  - {id: root, name: Root, definition: Root definition changed, parent: null, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n"
        "  - {id: child, name: Child, definition: Child definition, parent: root, seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
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
