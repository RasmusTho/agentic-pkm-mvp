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
    pattern = r'### Source Anchors\s*\n(.*?)(?=\n### |\Z)'
    match = re.search(pattern, body, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_anchors(section: str) -> List[Tuple[str, str]]:
    """
    Parse anchor entries from the Source Anchors section.

    Expected format:
    - `docs/ROADMAP.md :: ORCHV2-TDD`
    - `docs/STATUS.md :: SETTINGS-PROVENANCE`

    Returns list of (doc_path, anchor_id) tuples.
    """
    anchors = []
    lines = section.split('\n')

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Extract from format: - `docs/PATH.md :: ANCHOR-ID`
        # or: docs/PATH.md :: ANCHOR-ID
        # Anchor ID can contain alphanumerics, spaces, hyphens, underscores
        match = re.search(r'`?([^`]+\.md)\s*::\s*([^`\n]+?)\s*`?$', line)
        if match:
            doc_path, anchor_id = match.groups()
            anchors.append((doc_path.strip(), anchor_id.strip()))

    return anchors


def find_anchor_in_doc(doc_path: str, anchor_id: str) -> bool:
    """
    Check if the anchor ID exists in the document.

    Anchors can be:
    1. Heading anchors: `## ANCHOR-ID-in-heading-text`
    2. Marked anchors: `<!-- anchor: ANCHOR-ID -->` or similar patterns
    """
    file_path = Path(doc_path)

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

    return False


def validate_issue_body(body: str) -> Tuple[bool, List[str]]:
    """
    Validate an issue body.

    Returns (is_valid, error_messages).
    """
    errors = []

    # Check for Source Anchors section
    section = extract_source_anchors_section(body)
    if not section:
        errors.append("Issue is missing required `### Source Anchors` section")
        return False, errors

    # Parse anchors
    anchors = parse_anchors(section)
    if not anchors:
        errors.append("Source Anchors section is empty or malformed. Expected format: `docs/PATH.md :: ANCHOR-ID`")
        return False, errors

    # Validate each anchor
    for doc_path, anchor_id in anchors:
        if not doc_path.endswith('.md'):
            errors.append(f"Invalid anchor path: '{doc_path}' must be a markdown file (.md)")
            continue

        file_path = Path(doc_path)
        if not file_path.exists():
            errors.append(f"Anchor file not found: {doc_path}")
            continue

        if not find_anchor_in_doc(doc_path, anchor_id):
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
