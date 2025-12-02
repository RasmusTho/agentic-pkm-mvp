from __future__ import annotations

from pathlib import Path
from typing import List


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
        if not any(settings_dir.iterdir()):
            placeholder.write_text(
                "\n".join(
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
                ),
                encoding="utf-8",
            )
            created.append(placeholder)
        elif placeholder.exists():
            existed.append(placeholder)

        return {"root": [yggdrasil_root], "created": created, "existed": list(set(existed))}


__all__ = ["YggdrasilScaffolder"]
