from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"
DOCS_INDEX = DOCS_ROOT / "DOCS_INDEX.md"

# Paths/prefixes that may omit a State: header because they are samples/templates
# not used at runtime.
STATE_OPTIONAL_PREFIXES: tuple[str, ...] = (
    "docs/examples/",
    "docs/adr/",
)
STATE_OPTIONAL_FILES: set[str] = set()

STATE_RE = re.compile(r"^State:\s", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"\A---\n(?=.*^name:\s)(?=.*^description:\s)", re.MULTILINE | re.DOTALL)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _load_index_paths() -> set[str]:
    if not DOCS_INDEX.exists():
        raise AssertionError("docs/DOCS_INDEX.md is missing; cannot enforce docs index contract.")
    paths: set[str] = set()
    for line in DOCS_INDEX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) < 3:
            continue
        path = parts[1]
        if not path or path in {"Path", "---"}:
            continue
        paths.add(path)
    return paths


def _has_state_contract(text: str) -> bool:
    return bool(STATE_RE.search(text) or FRONTMATTER_RE.search(text))


def _docs_paths() -> Iterable[Path]:
    return (p for p in DOCS_ROOT.rglob("*.md") if p.name != "DOCS_INDEX.md")


def _is_state_optional(path: Path) -> bool:
    rel = _rel(path)
    return rel in STATE_OPTIONAL_FILES or rel.startswith(STATE_OPTIONAL_PREFIXES)


def _is_covered_by_index_directory(rel: str, index_paths: set[str]) -> bool:
    parent_readme = str(Path(rel).parent / "README.md")
    return parent_readme in index_paths


def test_all_docs_have_state_or_are_exempt() -> None:
    missing: list[str] = []
    for path in _docs_paths():
        if _is_state_optional(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not _has_state_contract(text):
            missing.append(_rel(path))
    assert not missing, (
        "The following docs are missing a State: header. "
        "Add a State: line near the top or mark them state-optional in this test:\n"
        + "\n".join(sorted(missing))
    )


def test_all_docs_are_listed_in_docs_index() -> None:
    index_paths = _load_index_paths()
    missing: list[str] = []
    for path in _docs_paths():
        rel = _rel(path)
        if _is_state_optional(path):
            continue
        if rel not in index_paths and not _is_covered_by_index_directory(rel, index_paths):
            missing.append(rel)
    assert not missing, (
        "These docs are not listed in docs/DOCS_INDEX.md. "
        "Add rows to DOCS_INDEX.md for each:\n" + "\n".join(sorted(missing))
    )


def test_index_paths_exist() -> None:
    index_paths = _load_index_paths()
    broken: list[str] = []
    for rel in index_paths:
        if not rel.startswith("docs/"):
            continue
        if any(char in rel for char in "*?["):
            continue
        if not (REPO_ROOT / rel).exists():
            broken.append(rel)
    assert not broken, (
        "DOCS_INDEX.md references missing files under docs/. "
        "Remove or fix these paths:\n" + "\n".join(sorted(broken))
    )


def _heading_to_anchor(heading: str) -> str:
    """Convert a Markdown heading text to a GitHub-style anchor slug."""
    slug = heading.strip().lower()
    # Remove characters that are not alphanumeric, space, or hyphen
    slug = re.sub(r"[^\w\s-]", "", slug)
    # Replace spaces (and runs of spaces) with hyphens
    slug = re.sub(r"\s+", "-", slug)
    return slug


def _extract_headings(text: str) -> set[str]:
    """Return the set of anchor slugs for all ATX headings in a Markdown file."""
    anchors: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            anchors.add(_heading_to_anchor(m.group(1)))
    return anchors


def test_no_broken_intra_repo_anchors() -> None:
    """Assert that every intra-repo `file.md#anchor` link in DOCS_INDEX resolves.

    Parses DOCS_INDEX.md for Markdown links of the form [text](path/file.md#anchor)
    and bare inline references of the form `path/file.md#anchor`. For each, checks
    that the target file exists and that the heading anchor is present in that file.
    """
    index_text = DOCS_INDEX.read_text(encoding="utf-8")

    # Match both Markdown link targets and bare backtick references that contain #
    anchor_re = re.compile(
        r"(?:"
        r"\[(?:[^\]]*)\]\(([^)]+\.md#[^\s)]+)\)"  # [text](file.md#anchor)
        r"|"
        r"\(([^)]+\.md#[^\s)]+)\)"  # bare (file.md#anchor) fallback
        r")"
    )

    broken: list[str] = []
    seen: set[str] = set()

    for m in anchor_re.finditer(index_text):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        raw = raw.rstrip(")")

        if raw in seen:
            continue
        seen.add(raw)

        # Split on # — take the last # as the anchor delimiter
        if "#" not in raw:
            continue
        hash_idx = raw.index("#")
        file_part = raw[:hash_idx]
        anchor = raw[hash_idx + 1:]

        # Resolve relative to repo root; skip paths starting with http
        if file_part.startswith("http"):
            continue

        target = REPO_ROOT / file_part
        if not target.exists():
            broken.append(f"{raw} (file not found: {file_part})")
            continue

        target_text = target.read_text(encoding="utf-8", errors="ignore")
        target_anchors = _extract_headings(target_text)
        if anchor not in target_anchors:
            broken.append(f"{raw} (anchor '#{anchor}' not found in {file_part}; available: {sorted(target_anchors)[:5]}…)")

    assert not broken, (
        "DOCS_INDEX.md contains intra-repo file#anchor links that do not resolve. "
        "Fix or drop each broken link:\n" + "\n".join(sorted(broken))
    )
