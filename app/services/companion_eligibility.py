"""
Companion note eligibility policy.

A source note is eligible for companion note creation only when it passes all checks.
Each check returns a structured reason so callers can log/emit why creation was deferred.

Eligibility reasons (ineligible):
  system_path            — note is inside a system/generated folder
  placeholder_title      — filename stem matches a known placeholder pattern
  empty_note             — note body has no meaningful non-frontmatter content
  cooldown_active        — note mtime is too recent; retry after next_check_after

Settings precedence:
  vault settings (@Settings/watchers.md companion: section)
  → env (COMPANION_CREATE_COOLDOWN_SECONDS, COMPANION_RENAME_COOLDOWN_SECONDS)
  → defaults (60s create, 20s rename)

Contract: docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_CREATE_COOLDOWN_ENV = "COMPANION_CREATE_COOLDOWN_SECONDS"
_RENAME_COOLDOWN_ENV = "COMPANION_RENAME_COOLDOWN_SECONDS"
_DEFAULT_CREATE_COOLDOWN = 60.0
_DEFAULT_RENAME_COOLDOWN = 20.0


@dataclass(frozen=True)
class CompanionSettings:
    """
    Cooldown settings for companion note creation.

    Precedence: vault settings → env → defaults.
    create_cooldown_seconds: wait this long after file creation before writing companion.
    rename_cooldown_seconds: wait this long after a rename/update before updating companion.
    Set either to 0.0 to disable the cooldown check.
    """
    create_cooldown_seconds: float
    rename_cooldown_seconds: float


def load_companion_settings(vault_root: Path | None = None) -> CompanionSettings:
    """
    Load companion settings.

    Reads vault settings file if vault_root is provided, falls back to env vars,
    then defaults. The vault settings format is::

        # @Settings/watchers.md (frontmatter)
        companion:
          create_cooldown_seconds: 60
          rename_cooldown_seconds: 20
    """
    # Try vault settings file first
    vault_create: float | None = None
    vault_rename: float | None = None
    if vault_root is not None:
        settings_path = vault_root / "@Settings" / "watchers.md"
        if settings_path.exists():
            try:
                import yaml
                text = settings_path.read_text(encoding="utf-8")
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        data = yaml.safe_load(parts[1]) or {}
                        if isinstance(data, dict):
                            companion_cfg = data.get("companion") or {}
                            if isinstance(companion_cfg, dict):
                                raw_c = companion_cfg.get("create_cooldown_seconds")
                                raw_r = companion_cfg.get("rename_cooldown_seconds")
                                if raw_c is not None:
                                    try:
                                        vault_create = float(raw_c)
                                    except (TypeError, ValueError):
                                        pass
                                if raw_r is not None:
                                    try:
                                        vault_rename = float(raw_r)
                                    except (TypeError, ValueError):
                                        pass
            except Exception:
                pass

    create_cooldown = vault_create if vault_create is not None else _load_float_env(
        _CREATE_COOLDOWN_ENV, _DEFAULT_CREATE_COOLDOWN
    )
    rename_cooldown = vault_rename if vault_rename is not None else _load_float_env(
        _RENAME_COOLDOWN_ENV, _DEFAULT_RENAME_COOLDOWN
    )
    return CompanionSettings(
        create_cooldown_seconds=create_cooldown,
        rename_cooldown_seconds=rename_cooldown,
    )


def _load_float_env(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Placeholder title detection
# ---------------------------------------------------------------------------

# Patterns that match known placeholder filenames (case-insensitive).
# Each pattern covers base name + optional trailing number.
_PLACEHOLDER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^namnl[öo]s(\s+\d+)?$", re.IGNORECASE | re.UNICODE),
    re.compile(r"^untitled(\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^new\s+note(\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^unnamed(\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^sans\s+titre(\s+\d+)?$", re.IGNORECASE),  # French
]


def is_placeholder_title(stem: str) -> bool:
    """Return True if stem is a known Obsidian/editor placeholder title."""
    normalized = stem.strip()
    if not normalized:
        return True
    return any(pattern.match(normalized) for pattern in _PLACEHOLDER_PATTERNS)


# ---------------------------------------------------------------------------
# Meaningful content detection
# ---------------------------------------------------------------------------

# Markdown constructs that are structural but carry no semantic content.
_STRUCTURAL_ONLY_RE = re.compile(
    r"^(\s*#.*|\s*---+\s*|\s*===+\s*|\s*\*{3,}\s*|\s*-{3,}\s*|\s*)$",
    re.MULTILINE,
)


def has_meaningful_content(body: str) -> bool:
    """
    Return True if body has at least one line with non-structural, non-whitespace content.

    'Structural' means: heading-only lines, horizontal rules, and blank lines.
    A body that is only headings and blank lines is not considered meaningful.
    """
    if not body or not body.strip():
        return False
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip headings (any level)
        if stripped.startswith("#"):
            continue
        # Skip horizontal rules (---  ***  ===)
        if re.match(r"^[-*=]{3,}$", stripped):
            continue
        # Non-empty, non-structural line found
        return True
    return False


# ---------------------------------------------------------------------------
# Eligibility result
# ---------------------------------------------------------------------------

@dataclass
class EligibilityResult:
    """
    Structured result of companion note eligibility check.

    eligible: True if companion creation may proceed.
    reason: 'eligible' | 'system_path' | 'placeholder_title' | 'empty_note'
            | 'cooldown_active'
    next_check_after: Unix timestamp after which the check should be retried
                      (set when reason == 'cooldown_active').
    """
    eligible: bool
    reason: str
    next_check_after: float | None = field(default=None)


# ---------------------------------------------------------------------------
# System folder detection
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PREFIXES = ("_system",)


def _is_system_path(note_path: Path, vault_root: Path) -> bool:
    """Return True if note_path is inside the vault's system folder."""
    try:
        rel = note_path.relative_to(vault_root)
    except ValueError:
        return False
    if not rel.parts:
        return False
    top = rel.parts[0].lower()
    # Always treat _system as system folder.
    if top == "_system":
        return True
    # Try to detect the layout-configured system folder.
    try:
        from app.vault.paths import get_vault_system_dir_rel
        system_dir = get_vault_system_dir_rel(vault_root)
        # Compare the top-level folder of the path against the configured system dir.
        if rel.parts[0] == system_dir or str(rel).startswith(system_dir + "/"):
            return True
        # Also check the first component of system_dir.
        system_parts = Path(system_dir).parts
        if system_parts and rel.parts[0] == system_parts[0]:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Main eligibility check
# ---------------------------------------------------------------------------

def check_companion_eligibility(
    note_path: Path,
    vault_root: Path,
    *,
    raw_body: str | None = None,
    file_mtime: float | None = None,
    cooldown_seconds: float = _DEFAULT_CREATE_COOLDOWN,
    now_timestamp: float | None = None,
) -> EligibilityResult:
    """
    Check whether a vault note is eligible for companion note creation.

    Checks are applied in priority order:
      1. system_path — note inside system/generated folder
      2. placeholder_title — filename stem is a known placeholder
      3. empty_note — note body has no meaningful content
      4. cooldown_active — note is too newly created/modified

    Args:
        note_path: Absolute path to the vault note.
        vault_root: Absolute path to the vault root.
        raw_body: Non-frontmatter body text of the note (stripped of frontmatter).
                  If None, file is read from disk.
        file_mtime: Unix timestamp of last file modification. If None, reads from disk.
        cooldown_seconds: Seconds the file must be unchanged before companion is created.
                          Pass 0.0 to disable cooldown check.
        now_timestamp: Current time as Unix timestamp. If None, uses time.time().

    Returns:
        EligibilityResult with eligible/reason/next_check_after.
    """
    # 1. System path check
    if _is_system_path(note_path, vault_root):
        return EligibilityResult(eligible=False, reason="system_path")

    # 2. Placeholder title check (based on filename stem, not derived title)
    stem = note_path.stem
    if is_placeholder_title(stem):
        return EligibilityResult(eligible=False, reason="placeholder_title")

    # Resolve raw_body if not supplied
    if raw_body is None:
        try:
            text = note_path.read_text(encoding="utf-8")
            # Strip frontmatter if present
            if text.startswith("---"):
                parts = text.split("---", 2)
                raw_body = parts[2].lstrip("\n") if len(parts) >= 3 else text
            else:
                raw_body = text
        except Exception:
            raw_body = ""

    # 3. Empty note check
    if not has_meaningful_content(raw_body):
        return EligibilityResult(eligible=False, reason="empty_note")

    # 4. Cooldown check (only if cooldown_seconds > 0)
    if cooldown_seconds > 0:
        if file_mtime is None:
            try:
                file_mtime = note_path.stat().st_mtime
            except Exception:
                file_mtime = 0.0
        now = now_timestamp if now_timestamp is not None else time.time()
        age = now - file_mtime
        if age < cooldown_seconds:
            next_check = file_mtime + cooldown_seconds
            return EligibilityResult(
                eligible=False,
                reason="cooldown_active",
                next_check_after=next_check,
            )

    return EligibilityResult(eligible=True, reason="eligible")


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

@dataclass
class OrphanedCompanion:
    """
    A companion note whose source note no longer exists at the expected path.

    This is informational only; callers decide whether to quarantine or report.
    The companion file is NOT deleted by find_orphaned_companions.
    """
    companion_path: Path   # absolute path to the companion file
    source_ref: str        # source_ref recorded in the companion
    companion: object      # the CompanionNote dataclass instance


def find_orphaned_companions(vault_root: Path) -> list[OrphanedCompanion]:
    """
    Scan all companion notes and return those whose source_ref no longer exists.

    This is a safe, read-only report. It does not delete or move any files.
    Use the result for human review or a separate quarantine operation.

    Args:
        vault_root: Absolute path to the vault root.

    Returns:
        List of OrphanedCompanion records for companion notes with missing sources.
    """
    from app.services.companion_note import _companions_dir
    from scripts.yaml_roundtrip import load_frontmatter

    companions_dir = vault_root / _companions_dir(vault_root)
    if not companions_dir.exists():
        return []

    orphans: list[OrphanedCompanion] = []
    for companion_file in companions_dir.glob("*.md"):
        try:
            text = companion_file.read_text(encoding="utf-8")
            fm, _ = load_frontmatter(text)
        except Exception:
            continue
        if not isinstance(fm, dict):
            continue
        source_ref = str(fm.get("source_ref", "")).strip()
        if not source_ref:
            continue
        source_path = vault_root / source_ref
        if not source_path.exists():
            # Lazy import to avoid circular dependency
            from app.services.companion_note import _fm_to_companion
            companion = _fm_to_companion(fm)
            if companion is not None:
                orphans.append(OrphanedCompanion(
                    companion_path=companion_file,
                    source_ref=source_ref,
                    companion=companion,
                ))
    return orphans


__all__ = [
    "CompanionSettings",
    "EligibilityResult",
    "OrphanedCompanion",
    "check_companion_eligibility",
    "find_orphaned_companions",
    "has_meaningful_content",
    "is_placeholder_title",
    "load_companion_settings",
]
