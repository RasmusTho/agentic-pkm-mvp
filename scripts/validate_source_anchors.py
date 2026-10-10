#!/usr/bin/env python3
"""
Validate that GitHub Issues have a Source Anchors section with valid references.

Usage:
  python3 scripts/validate_source_anchors.py "issue body text"
  BODY="issue body text" python3 scripts/validate_source_anchors.py
  python3 scripts/validate_source_anchors.py < issue_body.txt

Exits with code 0 if valid, 1 if invalid.
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List


def extract_source_anchors_section(body: str) -> Optional[str]:
    """Extract the Source Anchors section from issue body."""
    pattern = r'^#{2,6}\s+Source Anchors\s*\n(.*?)(?=\n#{2,6}\s+|\Z)'
    match = re.search(pattern, body, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_anchors(section: str) -> List[Tuple[str, str | None]]:
    """
    Parse anchor entries from the Source Anchors section.

    Expected format:
    - `docs/ROADMAP.md :: ORCHV2-TDD`
    - `docs/STATUS.md :: SETTINGS-PROVENANCE`
    - `docs/PANEL_AGENT.md` :: accepted decision
    - `app/worker.py :: main`
    - `Makefile :: PYTHON/test/lint`
    - #1234 / PR #1235

    Returns list of (repo_path, locator) tuples for repository file references.
    GitHub issue/PR references are represented as ("#1234", None).
    """
    anchors: List[Tuple[str, str | None]] = []
    lines = section.split('\n')

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Accept quoted/unquoted repo paths, with a locator inside or after
        # the code span. Match the complete entry so locator prose cannot be
        # mistaken for a path. Markdown stable IDs are checked below; other
        # files are factual path references, not normative document authority.
        entry = re.sub(r'^[-*+]\s+', '', line)
        match = re.fullmatch(r'`?([^`\s]+?)`?(?:\s*::\s*([^`\n]+?)\s*)?`?', entry)
        if match:
            doc_path, anchor_id = match.groups()
            anchors.append((doc_path.strip(), anchor_id.strip() if anchor_id else None))
        elif _is_github_ref(line):
            anchors.append((line, None))

    return anchors


def _is_github_ref(ref: str) -> bool:
    return bool(re.search(r'(?:^|\s)(?:#\d+|PR\s+#\d+|pull request\s+#\d+)(?:\b|$)', ref, re.IGNORECASE))


def _looks_like_stable_anchor(anchor_id: str | None) -> bool:
    if not anchor_id:
        return False
    return bool(re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{2,}', anchor_id.strip()))


def find_anchor_in_doc(
    doc_path: str,
    anchor_id: str,
    repo_root: Path | None = None,
) -> bool:
    """
    Check if the anchor ID exists in the document.

    Anchors can be:
    1. Heading anchors: `## ANCHOR-ID-in-heading-text`
    2. Marked anchors: `<!-- anchor: ANCHOR-ID -->` or similar patterns
    """
    file_path = (repo_root or Path.cwd()) / doc_path

    if not file_path.exists():
        return False

    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception:
        return False

    # Check for anchor in markdown headings (e.g., `## Some Title ANCHOR-ID`)
    # Anchors are typically in uppercase with hyphens
    heading_pattern = rf'#+\s+.*\b{re.escape(anchor_id)}\b'
    if re.search(heading_pattern, content):
        return True

    # Check for explicit anchor markers
    # Format: <!-- anchor: ANCHOR-ID --> or similar
    explicit_pattern = rf'(?:<!--\s*anchor\s*:\s*{re.escape(anchor_id)}\s*-->|^# {re.escape(anchor_id)}\b)'
    if re.search(explicit_pattern, content, re.MULTILINE):
        return True

    # Check for anchor ID appearing as a standalone item identifier
    # (e.g., on a line with just the anchor, or in a list/code block context)
    anchor_line_pattern = rf'(?:^|\n)\s*(?:\*|-|·|`|\[)\s*{re.escape(anchor_id)}\s*(?:\]|$|`)'
    if re.search(anchor_line_pattern, content, re.MULTILINE):
        return True

    # Check for bullet anchors wrapped in emphasis/inline-code markers, with
    # trailing text after the ID (e.g. `- **I-E2 (Idempotent handlers).**`,
    # `- *ID* text`, `` - `ID` text``). Tolerates zero or more of `**`, `*`,
    # `__`, `` ` `` between the bullet marker and the anchor ID, and an
    # optional matching closing marker immediately after the ID (needed
    # because `_`/backtick are word-adjacent to the ID and defeat `\b`).
    emphasis_bullet_pattern = (
        rf'(?:^|\n)\s*(?:\*|-|·)\s*(?:\*\*|__|\*|`)*\s*{re.escape(anchor_id)}'
        rf'(?:\*\*|__|\*|`)?(?:\b|$)'
    )
    if re.search(emphasis_bullet_pattern, content, re.MULTILINE):
        return True

    return False


def validate_issue_body(
    body: str,
    repo_root: Path | None = None,
) -> Tuple[bool, List[str]]:
    """
    Validate an issue body.

    Returns (is_valid, error_messages).
    """
    errors = []

    # Check for Source Anchors section
    section = extract_source_anchors_section(body)
    if not section:
        errors.append("Issue is missing required `Source Anchors` section")
        return False, errors

    # Parse anchors
    anchors = parse_anchors(section)
    if not anchors:
        errors.append("Source Anchors section is empty or malformed. Expected format: `<repo path> :: <locator>`")
        return False, errors

    root = (repo_root or Path.cwd()).resolve()

    # Validate each anchor
    for doc_path, anchor_id in anchors:
        if _is_github_ref(doc_path):
            continue
        relative_path = Path(doc_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"Anchor path must be repository-relative: {doc_path}")
            continue
        file_path = root / relative_path
        resolved = file_path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"Anchor path escapes repository root: {doc_path}")
            continue
        if not file_path.exists():
            errors.append(f"Anchor file not found: {doc_path}")
            continue
        if not file_path.is_file():
            errors.append(f"Anchor path is not a file: {doc_path}")
            continue

        if doc_path.endswith('.md') and _looks_like_stable_anchor(anchor_id) and not find_anchor_in_doc(
            doc_path,
            anchor_id or "",
            root,
        ):
            errors.append(f"Anchor not found in {doc_path}: {anchor_id}")

    return len(errors) == 0, errors


def main():
    # Read input from args, then env var (for workflow-safe injection), then stdin.
    if len(sys.argv) > 1:
        body = sys.argv[1]
    else:
        body = os.getenv("BODY", "")
        if not body:
            body = sys.stdin.read()

    if not body.strip():
        print("Error: No issue body provided")
        sys.exit(1)

    is_valid, errors = validate_issue_body(body)

    if is_valid:
        print("✓ Source Anchors validation passed")
        sys.exit(0)
    else:
        print("✗ Source Anchors validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)


if __name__ == '__main__':
    main()
