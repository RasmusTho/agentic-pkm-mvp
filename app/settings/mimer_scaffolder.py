from __future__ import annotations

import yaml
from pathlib import Path
from typing import List

from app.knowledge.write_ops import write_note_from_absolute
from app.settings.default_vault_layout import load_default_vault_layout
from app.vault.layout import ensure_vault_layout_report
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Bootstrap action asserted at the scaffold seam. It is a member of the write
# guard's named bootstrap allow-list (``DEFAULT_BOOTSTRAP_ACTIONS`` in
# app/write_guard.py), so a genuine pre-vault-selection provision survives
# health-degraded states while a guard that denies the action still blocks the
# write (#2877; formal-model.md §2.3 T-scaffold, gap #1).
SCAFFOLD_ACTION = "yggdrasil.scaffold"


class MimerScaffolder:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / "Yggdrasil"

    def scaffold(self, *, write_guard: WriteGuard = DEFAULT_WRITE_GUARD) -> dict[str, List[Path]]:
        # Guard-at-seam: assert before any filesystem mutation so a blocked
        # scaffold is atomic — zero directories created, zero files written.
        # The seam consults the guard; the named bootstrap escape lives in the
        # guard's allow-list, not in an unconditional skip here.
        write_guard.assert_writes_allowed(SCAFFOLD_ACTION)
        mimer_root_dir = self.root.expanduser()
        module_paths = {
            "Mimer": mimer_root_dir / "Mimer",
            "Hugin": mimer_root_dir / "Hugin",
            "Munin": mimer_root_dir / "Munin",
            "Ratatosk": mimer_root_dir / "Ratatosk",
            "Brokkr": mimer_root_dir / "Brokkr",
            "Tyr": mimer_root_dir / "Tyr",
            "Heimdall": mimer_root_dir / "Heimdall",
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

        # Pass the scaffold's own bootstrap-escape action through so the
        # nested layout/system-note writes survive safe_mode/unhealthy too
        # (#2910) -- otherwise the port's own guard assertion inside those
        # writes would re-deny what this seam's own check already allowed.
        layout, _, _ = ensure_vault_layout_report(mimer_root, write_action=SCAFFOLD_ACTION)
        for folder in [layout.system_folder, layout.inbox_folder, layout.desk_folder]:
            folder_path = mimer_root / folder
            if folder_path.exists():
                existed.append(folder_path)
            else:
                created.append(folder_path)

        return {"root": [mimer_root_dir], "created": created, "existed": list(set(existed))}

    @classmethod
    def _load_layout_defaults(cls) -> dict:
        payload = load_default_vault_layout()
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
        # Pass the scaffold's own bootstrap-escape action through to the port
        # (#2910): the port now asserts WG with its own default action, which
        # is NOT on the bootstrap allow-list, so passing SCAFFOLD_ACTION here
        # is what lets a genuine pre-vault-selection provision survive
        # safe_mode/unhealthy after the seam-level check in scaffold() above
        # already passed -- otherwise the port's own assertion would re-deny
        # the write the outer seam just allowed through.
        write_note_from_absolute(resolved_path, content, vault_root=resolved_root, action=SCAFFOLD_ACTION)

    @classmethod
    def _write_default_system_settings(cls, path: Path) -> None:
        defaults = cls._load_layout_defaults()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(defaults, sort_keys=False, allow_unicode=True)
        # See _write_settings_placeholder above: same bootstrap-escape pass-through.
        write_note_from_absolute(
            path.expanduser().resolve(),
            payload,
            vault_root=path.parent.parent.expanduser().resolve(),
            action=SCAFFOLD_ACTION,
        )


__all__ = ["MimerScaffolder"]
