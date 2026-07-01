"""Keep docs/adr/INDEX.md current without destroying curated content.

INDEX.md is a curated governance artifact, not pure generator output:

  * Above the "# ADR Index" marker it carries a hand-written preamble — a
    "State:" caveat and a "v5.5 Baseline Delta" section — that tells a reader how
    to treat the ADRs (historical design records, not runtime truth).
  * Each entry uses a curated title and a status annotation (e.g. "(accepted,
    docs/governance)") that deliberately differs from the literal "# " heading
    inside the ADR file.

So this script is ADDITIVE, not authoritative. It never rewrites the preamble or
an existing entry; it only appends a generated stub line for any ADR file that is
not yet linked from the index, leaving a human to curate that line's title and
status. It also does not prune: ADRs are append-only governance records, so a
listed-but-missing file is surfaced by review, not silently deleted here.

Re-running it against an up-to-date INDEX.md changes nothing — `python3
scripts/adr_index.py` is idempotent (`git diff --quiet docs/adr/INDEX.md` stays
clean). The previous version regenerated the whole file from headings, which
wiped the preamble and every curated title on each run.
"""
from __future__ import annotations

import pathlib
import re

MARKER = "# ADR Index\n"
LINK_RE = re.compile(r"\]\(\./[^)]+\.md\)")
SKIP = {"readme.md", "index.md"}


def heading_title(path: pathlib.Path) -> str:
    """First-level `# ` heading of an ADR, used as the appended stub title."""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return path.stem


def update_index(adr_dir: pathlib.Path) -> list[str]:
    """Append stub entries for any unlisted ADR; preserve all curated content.

    Returns the list of ADR filenames newly appended (empty when already
    current, in which case the index file is left untouched).
    """
    index_path = adr_dir / "INDEX.md"
    adr_files = [p for p in sorted(adr_dir.glob("*.md")) if p.name.lower() not in SKIP]

    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    missing = [p for p in adr_files if f"](./{p.name})" not in existing]
    if not missing:
        return []

    lines = existing.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    # Anchor the insertion within the entry list (after the marker), so a relative
    # `.md` link in the preamble can't mis-place a stub: after the last existing
    # entry, else just under the marker, else append a fresh "# ADR Index" section.
    marker_idx = next((i for i, line in enumerate(lines) if line == MARKER), None)
    search_start = marker_idx + 1 if marker_idx is not None else 0
    last_link = max(
        (i for i in range(search_start, len(lines)) if LINK_RE.search(lines[i])),
        default=None,
    )
    if last_link is not None:
        insert_at = last_link + 1
    elif marker_idx is not None:
        insert_at = marker_idx + 1
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        else:
            lines.insert(insert_at, "\n")
            insert_at += 1
    else:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend([MARKER, "\n"])
        insert_at = len(lines)

    stubs = [f"- [{heading_title(p)}](./{p.name})\n" for p in missing]
    lines[insert_at:insert_at] = stubs
    index_path.write_text("".join(lines), encoding="utf-8")
    return [p.name for p in missing]


if __name__ == "__main__":
    appended = update_index(pathlib.Path("docs/adr"))
    if appended:
        print("docs/adr/INDEX.md: appended " + ", ".join(appended) + " (curate title/status)")
    else:
        print("docs/adr/INDEX.md: up to date; nothing to append.")
