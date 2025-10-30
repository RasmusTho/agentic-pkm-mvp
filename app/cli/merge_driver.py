"""CLI stub for semantic Markdown merges.

The tool reads base/local/remote note variants, runs MergeResolverAgent,
and emits merged Markdown plus status metadata. Exit code conveys whether
human intervention is required (non-zero).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agents.merge_resolver.agent import merge_note_from_blobs


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_merge(base_path: Path, a_path: Path, b_path: Path) -> int:
    base = _read_text(base_path)
    a = _read_text(a_path)
    b = _read_text(b_path)

    merged, info = merge_note_from_blobs(base, a, b)
    status = info.get("status", "unknown")
    reason = info.get("reason", "")

    output = f"{merged}\n---\nMERGE_STATUS={status}\nMERGE_REASON={reason}\n"
    sys.stdout.write(output)
    sys.stdout.flush()

    return 0 if status == "resolved" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semantic Markdown merge driver stub")
    parser.add_argument("base_path", type=Path, help="Path to base version of the note")
    parser.add_argument("a_path", type=Path, help="Path to local version (ours)")
    parser.add_argument("b_path", type=Path, help="Path to remote version (theirs)")

    args = parser.parse_args(argv)
    return run_merge(args.base_path, args.a_path, args.b_path)


if __name__ == "__main__":  # pragma: no cover - exercised via __main__ guard in tests/CLI
    sys.exit(main())
