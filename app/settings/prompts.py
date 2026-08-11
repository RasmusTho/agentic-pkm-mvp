"""Canonical vault prompt resolution for the Settings Spine."""

from __future__ import annotations

import os
from pathlib import Path

from app.settings.locations import canonical_settings_root
from app.settings.models import DEFAULT_ASK_SYSTEM_PROMPT


ASK_PROMPT_RELATIVE_PATH = Path("prompts") / "ask.md"


def _markdown_body(text: str) -> str:
    """Return prompt Markdown without optional YAML front matter."""
    if text.startswith("---"):
        _, _, text = text.split("---", 2)
    return text.strip()


def resolve_ask_system_prompt(vault_root: Path | None = None) -> tuple[str, str]:
    """Resolve the ASK prompt and its safe provenance label."""
    root = vault_root or Path(os.getenv("VAULT_ROOT", "vault"))
    prompt_path = canonical_settings_root(root) / ASK_PROMPT_RELATIVE_PATH
    if not prompt_path.exists():
        return DEFAULT_ASK_SYSTEM_PROMPT, "registry:DEFAULT_ASK_SYSTEM_PROMPT"
    prompt = _markdown_body(prompt_path.read_text(encoding="utf-8"))
    if not prompt:
        raise ValueError(f"prompt file is empty: {ASK_PROMPT_RELATIVE_PATH}")
    return prompt, f"vault-shared:{ASK_PROMPT_RELATIVE_PATH.as_posix()}"


def validate_canonical_prompts(vault_root: Path | None = None) -> list[str]:
    """Validate canonical prompt files only; legacy documentation is not input."""
    root = vault_root or Path(os.getenv("VAULT_ROOT", "vault"))
    prompts_dir = canonical_settings_root(root) / "prompts"
    if not prompts_dir.exists():
        return []
    errors: list[str] = []
    for prompt_path in sorted(prompts_dir.glob("*.md")):
        try:
            if not _markdown_body(prompt_path.read_text(encoding="utf-8")):
                errors.append(f"{prompt_path.name}: prompt body is empty")
        except OSError as exc:
            errors.append(f"{prompt_path.name}: {exc}")
    return errors
