"""Keep docs/adr/INDEX.md current without destroying curated content.

INDEX.md is a curated governance artifact, not pure generator output. It
originally carried a hand-written preamble (a "State:" caveat and a "v5.5
Baseline Delta" section) and curated per-entry status annotations; the previous
regenerator rewrote the whole file from ADR headings on every run and wiped
that content (PR #2402). Today's INDEX.md is therefore plain generator output —
this script exists so curated content can be reintroduced without being
destroyed again.

So this script is ADDITIVE, not authoritative. It never rewrites the preamble
or an existing entry; it only appends a generated stub line for any ADR file
that is not yet linked from the index, leaving a human to curate that line's
title and status. It does not prune either: ADRs are append-only governance
records, so a listed-but-missing file is reported as a warning for review, not
silently deleted here (no CI gate consumes that warning yet).

Re-running it against an up-to-date INDEX.md changes nothing — `python3
scripts/adr_index.py` is idempotent (`git diff --quiet docs/adr/INDEX.md` stays
clean).
"""
from __future__ import annotations

import pathlib
import re

MARKER = "# ADR Index\n"
# An index entry is a top-level bullet whose link targets a local .md file;
# anchoring on the bullet shape keeps prose links (preamble or footer) from
# mis-placing appended stubs.
ENTRY_RE = re.compile(r"^- \[[^\]]*\]\((?:\./)?[^)]+\.md\)")
INDEX_LINK_RE = re.compile(r"\]\((?:\./)?([^)/]+\.md)\)")
SKIP = {"readme.md", "index.md"}


def heading_title(path: pathlib.Path) -> str:
    """First-level `# ` heading of an ADR, used as the appended stub title."""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return path.stem


def linked_names(index_text: str) -> set[str]:
    """Filenames already linked from the index, `./`-prefixed or not."""
    return set(INDEX_LINK_RE.findall(index_text))


def stale_entries(adr_dir: pathlib.Path, index_text: str) -> list[str]:
    """Index-linked filenames whose ADR file no longer exists (report-only)."""
    return sorted(
        name
        for name in linked_names(index_text)
        if name.lower() not in SKIP and not (adr_dir / name).exists()
    )


def update_index(adr_dir: pathlib.Path) -> list[str]:
    """Append stub entries for any unlisted ADR; preserve all curated content.

    Returns the list of ADR filenames newly appended (empty when already
    current, in which case the index file is left untouched).
    """
    index_path = adr_dir / "INDEX.md"
    adr_files = [p for p in sorted(adr_dir.glob("*.md")) if p.name.lower() not in SKIP]

    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    already_linked = linked_names(existing)
    missing = [p for p in adr_files if p.name not in already_linked]
    if not missing:
        return []

    lines = existing.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    # Anchor the insertion within the entry list (after the marker): after the
    # last existing entry bullet, else just under the marker, else append a
    # fresh "# ADR Index" section.
    marker_idx = next((i for i, line in enumerate(lines) if line == MARKER), None)
    search_start = marker_idx + 1 if marker_idx is not None else 0
    last_entry = max(
        (i for i in range(search_start, len(lines)) if ENTRY_RE.match(lines[i])),
        default=None,
    )
    if last_entry is not None:
        insert_at = last_entry + 1
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
    adr_dir = pathlib.Path("docs/adr")
    appended = update_index(adr_dir)
    if appended:
        print("docs/adr/INDEX.md: appended " + ", ".join(appended) + " (curate title/status)")
    else:
        print("docs/adr/INDEX.md: up to date; nothing to append.")
    index_path = adr_dir / "INDEX.md"
    if index_path.exists():
        for name in stale_entries(adr_dir, index_path.read_text(encoding="utf-8")):
            print(f"WARNING: docs/adr/INDEX.md links missing file {name} (review; not auto-pruned)")
