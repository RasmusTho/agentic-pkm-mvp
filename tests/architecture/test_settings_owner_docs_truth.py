"""Guard the Settings owner-document boundary against target-state overclaiming."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_settings_owner_doc_names_current_and_target_boundaries() -> None:
    document = _read("docs/SETTINGS.md")

    assert "single owner for settings mechanism" in document
    assert "distinguishes the target" in document and "one-spine model" in document
    assert "Current\nruntime evidence is not yet one universal resolver" in document
    assert "app/vault/settings_service.py" in document
    assert "app/settings/prompts.py::resolve_ask_system_prompt" in document
    assert "app/settings/compiler.py" in document
    assert "app/settings/runtime.py::get_settings_bundle" in document
    assert "parent acceptance remains open on #3156" in document


def test_settings_spine_pointer_preserves_open_parent() -> None:
    spine = _read("docs/SETTINGS_SPINE/README.md")
    parent_pointer = _read("docs/SETTINGS_SPINE/PARENT_FEATURE_ISSUE.md")
    task = _read("docs/SETTINGS_SPINE/CONSOLIDATE_SETTINGS_OWNER_DOCS.md")
    index = _read("docs/DOCS_INDEX.md")

    assert "SETTINGS-08 owner-document slice is delivered" in spine
    assert "#3156 remains the final open" in spine
    assert "SETTINGS-05" in spine and "[ ] Vault selection" in spine
    assert "#3163" in parent_pointer and "delivered / closed" in parent_pointer
    assert "remains open and is the" in parent_pointer
    assert "parent closure remains with #3156" in parent_pointer
    assert "does not claim that the parent is closed" in " ".join(task.split())
    assert "parent #3156 remains open" in index
    assert "parent acceptance remains with #3156" in index


def test_deleted_settings_schema_has_no_operational_references() -> None:
    deleted_schema = ROOT / "docs/schema/system-settings.schema.json"
    assert not deleted_schema.exists()

    excluded_provenance = {
        Path("docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md"),
        Path("docs/SETTINGS_SPINE/CONSOLIDATE_SETTINGS_OWNER_DOCS.md"),
    }
    stale_references: list[str] = []
    for relative_root in ("docs", "app", "schemas"):
        for path in (ROOT / relative_root).rglob("*"):
            if not path.is_file() or path.relative_to(ROOT) in excluded_provenance:
                continue
            try:
                contents = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "docs/schema/system-settings.schema.json" in contents:
                stale_references.append(path.relative_to(ROOT).as_posix())

    assert stale_references == []
