"""Canonical and one-release compatibility paths for vault settings (SET-2)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)

CANONICAL_SETTINGS_DIR_NAME = "settings"

# This is the only production module allowed to name the retired roots. Keeping
# the compatibility vocabulary here makes the architecture gate useful instead
# of spreading another generation of path guesses through loaders.
LEGACY_COMPILED_DIR = Path("@Settings")
LEGACY_SYSTEM_SETTINGS_DIR = Path("_system") / "settings"
LEGACY_SYSTEM_SETTINGS = LEGACY_SYSTEM_SETTINGS_DIR / "system-settings.yaml"
LEGACY_HEALTH_SETTINGS = Path("_system") / "Settings" / "health.md"


def canonical_settings_root(vault_root: Path) -> Path:
    root = Path(vault_root).expanduser().resolve()
    return contained_settings_path(root, root / CANONICAL_SETTINGS_DIR_NAME)


def contained_settings_path(root: Path, candidate: Path) -> Path:
    """Resolve one settings path and reject authority outside the vault."""

    resolved_root = root.expanduser().resolve()
    resolved_candidate = candidate.expanduser().resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError(f"settings path escapes vault root: {resolved_candidate}")
    return resolved_candidate


def resolve_settings_file(
    vault_root: Path,
    relative_path: Path | str,
    *,
    legacy_paths: tuple[Path, ...] = (),
) -> Path:
    """Resolve one settings artifact with canonical-wins compatibility.

    The returned canonical path may not exist. Legacy paths are consulted only
    when the canonical artifact itself is absent; values are never merged.
    Every legacy observation is loud on every resolution so operators retain a
    bounded one-release migration signal.
    """

    root = Path(vault_root).expanduser().resolve()
    relative = Path(relative_path)
    canonical = contained_settings_path(root, canonical_settings_root(root) / relative)
    resolved_legacy = [contained_settings_path(root, root / path) for path in legacy_paths]
    existing_legacy = [path for path in resolved_legacy if path.exists()]

    if canonical.exists():
        for legacy in existing_legacy:
            logger.warning(
                "settings: shadowed legacy settings %s; canonical is %s (legacy value ignored, never merged)",
                legacy,
                canonical,
            )
        return canonical

    if existing_legacy:
        selected, *shadowed = existing_legacy
        logger.warning(
            "settings: deprecated settings location %s still present; canonical is %s",
            selected,
            canonical,
        )
        for legacy in shadowed:
            logger.warning(
                "settings: shadowed legacy settings %s; selected compatibility source is %s",
                legacy,
                selected,
            )
        return selected

    return canonical


def resolve_compiled_sources(vault_root: Path) -> dict[Path, Path]:
    """Return compiled Markdown sources keyed by canonical-relative path.

    A canonical file shadows the same relative legacy file. Distinct legacy
    files remain readable during the compatibility release, which preserves a
    legacy-only key without merging a shadowed file's payload.
    """

    root = Path(vault_root).expanduser().resolve()
    canonical_root = canonical_settings_root(root)
    legacy_root = contained_settings_path(root, root / LEGACY_COMPILED_DIR)
    relative_paths: set[Path] = set()
    for source_root in (canonical_root, legacy_root):
        if source_root.exists():
            relative_paths.update(path.relative_to(source_root) for path in source_root.rglob("*.md"))

    resolved: dict[Path, Path] = {}
    for relative in sorted(relative_paths, key=str):
        resolved[relative] = resolve_settings_file(
            root,
            relative,
            legacy_paths=(LEGACY_COMPILED_DIR / relative,),
        )
    return resolved


def read_settings_mapping(path: Path) -> dict[str, object]:
    """Read canonical Markdown frontmatter or a legacy YAML mapping."""

    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".md":
        if not raw.startswith("---"):
            raise ValueError(f"settings Markdown must start with YAML frontmatter: {path}")
        parts = raw.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"settings Markdown frontmatter is not closed: {path}")
        raw = parts[1]
    payload = yaml.safe_load(raw) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"settings document must decode into a mapping: {path}")
    return payload


__all__ = [
    "CANONICAL_SETTINGS_DIR_NAME",
    "LEGACY_COMPILED_DIR",
    "LEGACY_HEALTH_SETTINGS",
    "LEGACY_SYSTEM_SETTINGS",
    "LEGACY_SYSTEM_SETTINGS_DIR",
    "canonical_settings_root",
    "contained_settings_path",
    "resolve_compiled_sources",
    "resolve_settings_file",
    "read_settings_mapping",
]
