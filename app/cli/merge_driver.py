from __future__ import annotations
import sys
import re
from pathlib import Path
from typing import Tuple, Dict, Any

from app.agents.merge_resolver.agent import merge_note_from_blobs, normalize_uuid_scalar


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _parse_uuid(md: str) -> str | None:
    # Be tolerant of leading indentation / newlines in fixtures.
    md_trim = md.lstrip()

    if not md_trim.startswith("---"):
        return None

    parts = md_trim.split("---", 2)
    if len(parts) < 3:
        return None

    fm_block = parts[1]
    m = re.search(r"^uuid:\s*(.+)$", fm_block, flags=re.MULTILINE)
    if m:
        # Same identity semantics as the resolver (PR #4626 r3712514848):
        # degenerate scalars are no identity; quoting differences are not an
        # identity mismatch.
        return normalize_uuid_scalar(m.group(1))
    return None


def run_merge(base_path: Path, a_path: Path, b_path: Path) -> int:
    """
    base_path = %O  (BASE in git terms)
    a_path    = %A  (OURS / local working copy)
    b_path    = %B  (THEIRS / incoming)

    Exit codes:
      0 => auto-merged safely
      1 => needs human review
      2 => usage error

    Git's custom-merge-driver contract requires the merge result to be written to
    `a_path` (%A) — that is the path git reads the result back from. Diagnostics
    (MERGE_STATUS / MERGE_REASON) are informational only and must never be written
    into `a_path`; they go to stderr so they cannot contaminate merged markdown.
    """
    base = _read_text(base_path)
    a = _read_text(a_path)
    b = _read_text(b_path)

    uuid_a = _parse_uuid(a)
    uuid_b = _parse_uuid(b)

    # Safety rail:
    # If these two notes don't even share uuid, they're not the same logical note.
    # We refuse to silently merge. Leave a_path untouched so git's non-zero exit
    # surfaces this as a conflict for a human to resolve.
    if uuid_a and uuid_b and uuid_a != uuid_b:
        status = "conflict"
        reason = "uuid mismatch"
        sys.stderr.write(f"MERGE_STATUS={status}\nMERGE_REASON={reason}\n")
        sys.stderr.flush()
        return 1

    # Otherwise treat them as revisions of the same logical note and run semantic merge.
    merged, info = merge_note_from_blobs(base, a, b)

    status = info.get("status", "unknown")
    reason = info.get("reason", "")

    if status == "resolved":
        # Fulfil the merge-driver contract: git reads the result back from a_path.
        a_path.write_text(merged, encoding="utf-8")

    sys.stderr.write(f"MERGE_STATUS={status}\nMERGE_REASON={reason}\n")
    sys.stderr.flush()

    # Exit code policy:
    # - 0 => "resolved": safe automatic result
    # - 1 => anything else ("prompted", "conflict", ...)
    return 0 if status == "resolved" else 1


def main(argv: list[str]) -> int:
    # git custom merge driver calls us like:
    #   merge_driver BASE OURS THEIRS
    if len(argv) != 4:
        sys.stderr.write("usage: merge_driver BASE OURS THEIRS\n")
        return 2

    base_path = Path(argv[1])
    a_path = Path(argv[2])
    b_path = Path(argv[3])
    return run_merge(base_path, a_path, b_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
