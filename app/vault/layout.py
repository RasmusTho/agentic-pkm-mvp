from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import shutil

import yaml

DEFAULT_SYSTEM_FOLDER = "⚙️ System"
DEFAULT_INBOX_FOLDER = "📥 Inbox"
DEFAULT_DESK_FOLDER = "🛠️ Workbench"
DEFAULT_ROOT_FOLDERS = [
    "📥 Inbox",
    "🛠️ Workbench",
    "🔍 Focus",
    "📁 Projects",
    "🧩 Areas",
    "💡 Knowledge",
    "🗂️ Reference",
    "🗄️ Archive",
    "⚙️ System",
]
LAYOUT_NOTE_NAME = "vault.layout.md"
SYSTEM_NOTE_TITLE = "Vault Structure – Human-First Orientation (Mimer)"


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


def _layout_note_path(vault_root: Path, system_folder: str) -> Path:
    filename = normalize_md_filename(LAYOUT_NOTE_NAME)
    return vault_root / system_folder / filename


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


def _render_default_note(layout: VaultLayout) -> str:
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
        "## Description\n"
        "- Edit the YAML frontmatter to change folder names or ingest defaults.\n"
        "- Folders listed here are created if missing; nothing is deleted.\n"
        "- Unknown folders are allowed to remain.\n\n"
        "## Guidance for agents\n"
        "- System notes live under the system folder.\n"
        "- Inbox is the capture surface for new notes.\n"
        "- Desk is the active workspace.\n"
        "- Root folders define human navigation anchors.\n"
    )
    return f"---\n{frontmatter}\n---\n\n{body}"


def _system_note_content() -> str:
    return (
        "---\n"
        "kind: system_doc\n"
        "title: Vault Structure – Human-First Orientation (Mimer)\n"
        "trust: asserted\n"
        "review_state: reviewed\n"
        "---\n\n"
        "# Vault Structure (Mimer)\n\n"
        "This document defines the **intended meaning and usage** of the root folders in the vault (Mimer).\n"
        "The vault is the **human-facing knowledge surface** of the Yggdrasil system.\n\n"
        "The purpose of this structure is to:\n"
        "- enable fast manual navigation, even without knowing exact names\n"
        "- enable fast, low-friction capture (“where should this go?”)\n"
        "- reflect human cognitive orientation, not system internals\n"
        "- remain stable even as metadata, policies, and agents evolve\n\n"
        "Folders express **orientation and context**, not state, type, or truth.\n\n"
        "---\n\n"
        "## Design Principles\n\n"
        "- Folder placement must be understandable without reading system documentation\n"
        "- Folders must not encode workflow state (active, reviewed, archived, etc.)\n"
        "- Metadata (Core-6, state axes, policies) defines behavior — folders define orientation\n"
        "- It must always be acceptable to place something quickly, imperfectly, and refine later\n\n"
        "If unsure where something belongs, **Inbox is always correct**.\n\n"
        "---\n\n"
        "## Root Folders\n\n"
        "### 📥 Inbox\n\n"
        "**Purpose:**  \n"
        "Immediate capture with zero decision cost.\n\n"
        "**Contains:**  \n"
        "- raw notes\n"
        "- quick thoughts\n"
        "- links\n"
        "- dumped ideas\n"
        "- newly imported material\n\n"
        "**Mental rule:**  \n"
        "> “I have something. I don’t want to think. Put it here.”\n\n"
        "Nothing is required to stay here forever, but nothing is forbidden from entering.\n\n"
        "---\n\n"
        "### 🛠️ Workbench\n\n"
        "**Purpose:**  \n"
        "Active work and experimentation.\n\n"
        "**Contains:**  \n"
        "- work-in-progress notes\n"
        "- drafts\n"
        "- sketches\n"
        "- analyses under construction\n"
        "- experimental material\n\n"
        "**Mental rule:**  \n"
        "> “I am actively working on this.”\n\n"
        "Workbench may be messy. That is intentional.\n\n"
        "---\n\n"
        "### 🔍 Focus\n\n"
        "**Purpose:**  \n"
        "Cognitive attention and current importance.\n\n"
        "**Contains:**  \n"
        "- active questions\n"
        "- decisions in progress\n"
        "- investigations\n"
        "- topics occupying mental bandwidth right now\n\n"
        "**Mental rule:**  \n"
        "> “This is in my head right now.”\n\n"
        "Focus is about **attention**, not volume or task tracking.\n\n"
        "---\n\n"
        "### 📁 Projects\n\n"
        "**Purpose:**  \n"
        "Time-bounded efforts with a goal or outcome.\n\n"
        "**Contains:**  \n"
        "- projects with a defined start and expected end\n"
        "- contextual material related to “getting something done”\n"
        "- project-specific notes, decisions, and references\n\n"
        "**Mental rule:**  \n"
        "> “This is something that should become finished.”\n\n"
        "Projects are containers of context, not task engines.\n\n"
        "---\n\n"
        "### 🧩 Areas\n\n"
        "**Purpose:**  \n"
        "Long-lived domains of responsibility or interest.\n\n"
        "**Contains:**  \n"
        "- hobbies\n"
        "- role-playing campaigns and worldbuilding\n"
        "- long-term interests\n"
        "- personal domains without a defined end\n\n"
        "**Examples:**  \n"
        "- Roleplaying\n"
        "- Home automation\n"
        "- Philosophy\n"
        "- Health\n"
        "- Creative writing\n\n"
        "**Mental rule:**  \n"
        "> “This is a part of my life, not a project.”\n\n"
        "Areas persist over time and may spawn multiple projects.\n\n"
        "---\n\n"
        "### 💡 Knowledge\n\n"
        "**Purpose:**  \n"
        "Understanding, thinking, and synthesis.\n\n"
        "**Contains:**  \n"
        "- concepts\n"
        "- mental models\n"
        "- explanations\n"
        "- evergreen notes\n"
        "- synthesized understanding\n\n"
        "**Mental rule:**  \n"
        "> “I keep this to understand the world better.”\n\n"
        "Knowledge is not time-bound and not owned by any single project or area.\n\n"
        "---\n\n"
        "### 🗂️ Reference\n\n"
        "**Purpose:**  \n"
        "Lookup and support material.\n\n"
        "**Contains:**  \n"
        "- instructions\n"
        "- checklists\n"
        "- manuals\n"
        "- policies\n"
        "- factual material meant to be consulted, not worked on\n\n"
        "**Mental rule:**  \n"
        "> “I want to be able to look this up.”\n\n"
        "Reference material should be stable and low-change.\n\n"
        "---\n\n"
        "### 🗄️ Archive\n\n"
        "**Purpose:**  \n"
        "Completed or parked material.\n\n"
        "**Contains:**  \n"
        "- finished projects\n"
        "- closed focus topics\n"
        "- historical material\n"
        "- things no longer relevant to current work or attention\n\n"
        "**Mental rule:**  \n"
        "> “This is done or not relevant right now.”\n\n"
        "Archive removes cognitive noise without deleting knowledge.\n\n"
        "---\n\n"
        "### ⚙️ System\n\n"
        "**Purpose:**  \n"
        "System configuration and governance.\n\n"
        "**Contains:**  \n"
        "- system documentation\n"
        "- policies\n"
        "- settings\n"
        "- templates\n"
        "- automation notes\n"
        "- architectural descriptions\n\n"
        "**Mental rule:**  \n"
        "> “This is about how the system works.”\n\n"
        "System content is not part of domain knowledge.\n\n"
        "---\n\n"
        "## Important Notes\n\n"
        "- Folder placement does **not** define truth, review status, or priority\n"
        "- Notes may move between folders over time without changing identity\n"
        "- Agents may suggest moves, but folder placement remains a human choice\n"
        "- If metadata is missing or incomplete, the folder structure must still work\n\n"
        "This structure reflects current intent and may evolve.\n"
        "Any changes should preserve the core principle: **human-first orientation**.\n"
    )


def load_or_create_layout(vault_root: Path) -> VaultLayout:
    note_path = _layout_note_path(vault_root, DEFAULT_SYSTEM_FOLDER)
    if note_path.exists():
        frontmatter = _load_frontmatter(note_path)
    else:
        frontmatter = {}

    system_folder = str(frontmatter.get("system_folder") or DEFAULT_SYSTEM_FOLDER)
    inbox_folder = str(frontmatter.get("inbox_folder") or DEFAULT_INBOX_FOLDER)
    desk_folder = str(frontmatter.get("desk_folder") or DEFAULT_DESK_FOLDER)
    root_folders = _normalize_optional_list(frontmatter.get("root_folders"))
    if not root_folders:
        root_folders = list(DEFAULT_ROOT_FOLDERS)
    include_folders = _normalize_optional_list(frontmatter.get("include_folders"))
    ignore_glob = _normalize_optional_list(frontmatter.get("ignore_glob"))
    version = str(frontmatter.get("version") or "1")

    layout = VaultLayout(
        system_folder=system_folder,
        inbox_folder=inbox_folder,
        desk_folder=desk_folder,
        root_folders=root_folders,
        include_folders=include_folders,
        ignore_glob=ignore_glob,
        note_path=note_path,
        version=version,
    )

    if not note_path.exists():
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_render_default_note(layout), encoding="utf-8")

    return layout


def ensure_system_note(vault_root: Path, system_folder: str) -> Path:
    note_path = _system_note_path(vault_root, system_folder)
    if note_path.exists():
        return note_path
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(_system_note_content(), encoding="utf-8")
    return note_path


def ensure_vault_layout_report(vault_root: Path) -> tuple[VaultLayout, bool, list[str]]:
    layout = load_or_create_layout(vault_root)
    warnings: list[str] = []
    migrated = False

    legacy_system = vault_root / "System"
    target_system = vault_root / layout.system_folder
    if legacy_system.exists() and not target_system.exists():
        if legacy_system.is_dir():
            shutil.move(str(legacy_system), str(target_system))
            migrated = True
        else:
            warnings.append("Legacy System path exists but is not a directory; leaving in place.")
    elif legacy_system.exists() and target_system.exists():
        warnings.append(
            f"Legacy System/ exists alongside {layout.system_folder}/; leaving legacy in place."
        )

    folders = set(layout.root_folders)
    folders.update({layout.system_folder, layout.inbox_folder, layout.desk_folder})
    if layout.include_folders:
        folders.update(layout.include_folders)
    for folder in sorted(folders):
        if not folder or folder == ".":
            continue
        (vault_root / folder).mkdir(parents=True, exist_ok=True)

    ensure_system_note(vault_root, layout.system_folder)

    return layout, migrated, warnings


def ensure_vault_layout(vault_root: Path) -> VaultLayout:
    layout, _, _ = ensure_vault_layout_report(vault_root)
    return layout


__all__ = [
    "DEFAULT_DESK_FOLDER",
    "DEFAULT_INBOX_FOLDER",
    "DEFAULT_ROOT_FOLDERS",
    "DEFAULT_SYSTEM_FOLDER",
    "LAYOUT_NOTE_NAME",
    "SYSTEM_NOTE_TITLE",
    "VaultLayout",
    "ensure_system_note",
    "ensure_vault_layout",
    "ensure_vault_layout_report",
    "load_or_create_layout",
    "normalize_md_filename",
]
