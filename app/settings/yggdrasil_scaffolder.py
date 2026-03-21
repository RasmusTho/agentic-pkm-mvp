from __future__ import annotations

import yaml
from pathlib import Path
from typing import List

from app.knowledge.write_ops import write_note_from_absolute
from app.vault.layout import ensure_vault_layout_report


class YggdrasilScaffolder:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / "Yggdrasil"

    def scaffold(self) -> dict[str, List[Path]]:
        yggdrasil_root = self.root.expanduser()
        module_paths = {
            "Mimer": yggdrasil_root / "Mimer",
            "Hugin": yggdrasil_root / "Hugin",
            "Munin": yggdrasil_root / "Munin",
            "Ratatosk": yggdrasil_root / "Ratatosk",
            "Brokkr": yggdrasil_root / "Brokkr",
            "Tyr": yggdrasil_root / "Tyr",
            "Heimdall": yggdrasil_root / "Heimdall",
        }

        created: list[Path] = []
        existed: list[Path] = []

        for path in module_paths.values():
            if path.exists():
                existed.append(path)
            else:
                created.append(path)
            path.mkdir(parents=True, exist_ok=True)

        mimer_subdirs = [
            "Index",
            "Workspace",
            "Ingress",
            "Projects",
            "Domains",
            "Corpus",
            "Sources",
            "Ontology",
            "Taxonomy",
            "Canon",
            "Archive",
            "Machina",
            "@Settings",
        ]
        mimer_root = module_paths["Mimer"]
        for subdir in mimer_subdirs:
            subdir_path = mimer_root / subdir
            if subdir_path.exists():
                existed.append(subdir_path)
            else:
                created.append(subdir_path)
            subdir_path.mkdir(parents=True, exist_ok=True)

        settings_dir = mimer_root / "@Settings"
        placeholder = settings_dir / "global.md"
        system_settings = settings_dir / "system-settings.yaml"

        if not placeholder.exists():
            self._write_settings_placeholder(mimer_root, placeholder)
            created.append(placeholder)
        else:
            existed.append(placeholder)

        if not system_settings.exists():
            self._write_default_system_settings(system_settings)
            created.append(system_settings)
        else:
            existed.append(system_settings)

        layout, _, _ = ensure_vault_layout_report(mimer_root)
        for folder in [layout.system_folder, layout.inbox_folder, layout.desk_folder]:
            folder_path = mimer_root / folder
            if folder_path.exists():
                existed.append(folder_path)
            else:
                created.append(folder_path)

        return {"root": [yggdrasil_root], "created": created, "existed": list(set(existed))}

    @staticmethod
    def _layout_defaults_template_path() -> Path:
        return Path(__file__).resolve().parents[2] / "docs" / "settings" / "default-vault-layout.yaml"

    @classmethod
    def _load_layout_defaults(cls) -> dict:
        payload = yaml.safe_load(cls._layout_defaults_template_path().read_text(encoding="utf-8")) or {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_settings_placeholder(vault_root: Path, placeholder: Path) -> None:
        content = "\n".join(
            [
                "---",
                "kind: settings",
                "scope: global",
                "module: Mimer",
                "system: Yggdrasil",
                "---",
                "",
                "# Global settings for Mimer (Yggdrasil)",
                "",
                "This is an initial placeholder created by the `yggdrasil-init` command.",
                "",
            ]
        )
        resolved_root = vault_root.expanduser().resolve()
        resolved_path = placeholder.expanduser().resolve()
        write_note_from_absolute(resolved_path, content, vault_root=resolved_root)

    @classmethod
    def _write_default_system_settings(cls, path: Path) -> None:
        defaults = cls._load_layout_defaults()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(defaults, sort_keys=False, allow_unicode=True).encode("utf-8")
        path.write_bytes(payload)


__all__ = ["YggdrasilScaffolder"]
