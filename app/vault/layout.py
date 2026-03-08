from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.knowledge.locators import make_note_locator_from_absolute
from app.knowledge.service import resolve_knowledge_port


LAYOUT_NOTE_NAME = "vault.layout.md"
SYSTEM_NOTE_TITLE = "Vault Structure – Human-First Orientation (Mimer)"

_SETTINGS_REL_PATH = Path("_system") / "settings" / "system-settings.yaml"


@dataclass(frozen=True)
class VaultLayout:
    system_folder: str
    inbox_folder: str
    desk_folder: str
    root_folders: list[str]
    include_folders: list[str] | None
    ignore_glob: list[str] | None
    note_path: Path
    version: str = "1"


def normalize_md_filename(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return "note.md"
    while cleaned.lower().endswith(".md.md"):
        cleaned = cleaned[:-3]
    if not cleaned.lower().endswith(".md"):
        cleaned = f"{cleaned}.md"
    return cleaned


def _layout_note_filename() -> str:
    return normalize_md_filename(LAYOUT_NOTE_NAME)


def _system_note_path(vault_root: Path, system_folder: str) -> Path:
    filename = normalize_md_filename(SYSTEM_NOTE_TITLE)
    return vault_root / system_folder / filename


def _load_frontmatter(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_block = parts[1]
    try:
        data = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_optional_list(value: object | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [str(value).strip()] if str(value).strip() else []
    values = [item for item in values if item]
    return values or None


def _coerce_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_system_settings(vault_root: Path) -> dict[str, Any]:
    path = vault_root / _SETTINGS_REL_PATH
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _system_dir_hint(vault_root: Path) -> str:
    env_value = (os.getenv("VAULT_SYSTEM_DIR_REL") or "").strip()
    if env_value:
        return env_value

    settings = _read_system_settings(vault_root)
    raw_paths = settings.get("paths")
    if isinstance(raw_paths, dict):
        value = raw_paths.get("system_dir_rel")
        if isinstance(value, str) and value.strip():
            return value.strip()

    value2 = settings.get("system_dir_rel")
    if isinstance(value2, str) and value2.strip():
        return value2.strip()

    return ""


def _find_layout_note_candidates(vault_root: Path) -> list[Path]:
    explicit_rel = os.getenv("VAULT_LAYOUT_NOTE_REL")
    filename = _layout_note_filename()

    if explicit_rel and explicit_rel.strip():
        candidate = (vault_root / explicit_rel.strip()).expanduser()
        return [candidate]

    system_hint = _system_dir_hint(vault_root)
    if system_hint:
        candidate = vault_root / system_hint / filename
        if candidate.exists():
            return [candidate]

    matches: list[Path] = []
    try:
        children = sorted([p for p in vault_root.iterdir() if p.is_dir()])
    except FileNotFoundError:
        return []

    for child in children:
        candidate = child / filename
        if candidate.exists():
            matches.append(candidate)

    return matches


def _has_required_fields(frontmatter: dict[str, Any]) -> bool:
    return bool(
        _coerce_str(frontmatter.get("system_folder"))
        and _coerce_str(frontmatter.get("inbox_folder"))
        and _coerce_str(frontmatter.get("desk_folder"))
    )


def load_layout(vault_root: Path) -> VaultLayout:
    vault_root = vault_root.expanduser()
    matches = _find_layout_note_candidates(vault_root)

    if not matches:
        raise FileNotFoundError(
            "vault.layout.md not found. Provide VAULT_LAYOUT_NOTE_REL, or ensure the vault contains a layout note. "
            "You can create one by setting VAULT_SYSTEM_DIR_REL + VAULT_INBOX_DIR_REL + VAULT_DESK_DIR_REL and running "
            "`python -m app.cli vault-layout-ensure --vault-root <path>` ."
        )

    existing = [p for p in matches if p.exists()]

    # If multiple candidates exist, prefer ones with parseable required fields.
    if len(existing) > 1:
        valid = [p for p in existing if _has_required_fields(_load_frontmatter(p))]
        if len(valid) == 1:
            existing = valid
        elif len(valid) > 1:
            existing = valid

    # If still ambiguous, attempt deterministic selection using system_dir_rel.
    if len(existing) > 1:
        system_hint = _system_dir_hint(vault_root)
        if system_hint:
            preferred = vault_root / system_hint / _layout_note_filename()
            if preferred.exists() and preferred in existing:
                existing = [preferred]

    if len(existing) > 1:
        rels = ", ".join(str(p.relative_to(vault_root)) for p in sorted(existing))
        raise ValueError(
            "Multiple vault.layout.md notes found; set VAULT_LAYOUT_NOTE_REL to disambiguate. "
            f"Found: {rels}"
        )

    note_path = existing[0]
    frontmatter = _load_frontmatter(note_path)

    system_folder = _coerce_str(frontmatter.get("system_folder") or os.getenv("VAULT_SYSTEM_DIR_REL"))
    inbox_folder = _coerce_str(frontmatter.get("inbox_folder") or os.getenv("VAULT_INBOX_DIR_REL"))
    desk_folder = _coerce_str(frontmatter.get("desk_folder") or os.getenv("VAULT_DESK_DIR_REL"))

    if not system_folder or not inbox_folder or not desk_folder:
        raise ValueError(
            "vault.layout.md is missing required folder fields. Expected frontmatter keys: "
            "system_folder, inbox_folder, desk_folder (or set VAULT_SYSTEM_DIR_REL/VAULT_INBOX_DIR_REL/VAULT_DESK_DIR_REL)."
        )

    root_folders = _normalize_optional_list(frontmatter.get("root_folders"))
    if not root_folders:
        root_folders = [system_folder, inbox_folder, desk_folder]

    include_folders = _normalize_optional_list(frontmatter.get("include_folders"))
    ignore_glob = _normalize_optional_list(frontmatter.get("ignore_glob"))
    version = _coerce_str(frontmatter.get("version") or "1")

    return VaultLayout(
        system_folder=system_folder,
        inbox_folder=inbox_folder,
        desk_folder=desk_folder,
        root_folders=root_folders,
        include_folders=include_folders,
        ignore_glob=ignore_glob,
        note_path=note_path,
        version=version,
    )


def _render_layout_note(layout: VaultLayout) -> str:
    frontmatter = yaml.safe_dump(
        {
            "version": layout.version,
            "system_folder": layout.system_folder,
            "inbox_folder": layout.inbox_folder,
            "desk_folder": layout.desk_folder,
            "root_folders": layout.root_folders,
            "include_folders": layout.include_folders or [],
            "ignore_glob": layout.ignore_glob or [],
        },
        sort_keys=False,
        allow_unicode=True,
    ).strip()

    body = (
        "# Vault Layout Contract\n"
        "This note defines the vault layout contract for agents and ingest defaults.\n\n"
        "## Guidance\n"
        "- Configure folder names via YAML frontmatter.\n"
        "- Agents treat the inbox folder as the capture surface for new notes.\n"
        "- The desk folder is the active workspace.\n"
        "- Root folders define human navigation anchors.\n"
    )

    return f"---\n{frontmatter}\n---\n\n{body}"


def _write_note_via_knowledge_port(vault_root: Path, path: Path, content: str) -> None:
    resolved_root = vault_root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    locator = make_note_locator_from_absolute(resolved_path, vault_root=resolved_root)
    port = resolve_knowledge_port(vault_root=resolved_root)
    port.write_note(locator, content)


def load_or_create_layout(vault_root: Path) -> VaultLayout:
    vault_root = vault_root.expanduser()

    try:
        return load_layout(vault_root)
    except FileNotFoundError:
        pass

    system_folder = (os.getenv("VAULT_SYSTEM_DIR_REL") or "").strip()
    inbox_folder = (os.getenv("VAULT_INBOX_DIR_REL") or "").strip()
    desk_folder = (os.getenv("VAULT_DESK_DIR_REL") or "").strip()

    if not system_folder or not inbox_folder or not desk_folder:
        raise ValueError(
            "Cannot create vault.layout.md without explicit folder names. Set VAULT_SYSTEM_DIR_REL + "
            "VAULT_INBOX_DIR_REL + VAULT_DESK_DIR_REL (or create the note manually)."
        )

    note_path = vault_root / system_folder / _layout_note_filename()
    layout = VaultLayout(
        system_folder=system_folder,
        inbox_folder=inbox_folder,
        desk_folder=desk_folder,
        root_folders=[system_folder, inbox_folder, desk_folder],
        include_folders=None,
        ignore_glob=None,
        note_path=note_path,
        version="1",
    )

    note_path.parent.mkdir(parents=True, exist_ok=True)
    _write_note_via_knowledge_port(vault_root, note_path, _render_layout_note(layout))
    return layout


def ensure_system_note(vault_root: Path, system_folder: str) -> Path:
    note_path = _system_note_path(vault_root, system_folder)
    if note_path.exists():
        return note_path
    note_path.parent.mkdir(parents=True, exist_ok=True)
    _write_note_via_knowledge_port(
        vault_root,
        note_path,
        "# System Notes\n\nThis folder contains system configuration and operational notes.\n",
    )
    return note_path


def ensure_vault_layout_report(vault_root: Path) -> tuple[VaultLayout, bool, list[str]]:
    vault_root = vault_root.expanduser()
    layout = load_or_create_layout(vault_root)
    warnings: list[str] = []

    folders = set(layout.root_folders)
    folders.update({layout.system_folder, layout.inbox_folder, layout.desk_folder})
    if layout.include_folders:
        folders.update(layout.include_folders)

    for folder in sorted(folders):
        if not folder or folder == ".":
            continue
        (vault_root / folder).mkdir(parents=True, exist_ok=True)

    ensure_system_note(vault_root, layout.system_folder)

    migrated = False
    return layout, migrated, warnings


def ensure_vault_layout(vault_root: Path) -> VaultLayout:
    layout, _, _ = ensure_vault_layout_report(vault_root)
    return layout


__all__ = [
    "LAYOUT_NOTE_NAME",
    "SYSTEM_NOTE_TITLE",
    "VaultLayout",
    "ensure_system_note",
    "ensure_vault_layout",
    "ensure_vault_layout_report",
    "load_layout",
    "load_or_create_layout",
    "normalize_md_filename",
]
