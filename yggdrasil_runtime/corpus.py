"""Corpus loader — the synthetic anti-contamination corpus is the runtime store for this slice.

Loads ``tests/evals/fixtures/<group>/*.md``, parses the flat ``key: value`` frontmatter, and builds a
schema-conformant ``MetadataBundle`` per doc (a runtime equivalent of the ``tests/evals/_helpers.py``
semantics — without importing from ``tests/``). No real vault, no DB, no durable mutation.

The corpus uses ``authority_state: accepted`` for several docs; canonical standing requires an
``authority_receipt_ref`` (``MetadataBundle`` fails loud otherwise), so accepted/canonical docs get a
synthesized corpus receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yggdrasil_runtime.metadata import CANONICAL_AUTHORITY_STATES, MetadataBundle

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "evals" / "fixtures"

# The five scope groups (mirrors tests/evals/_helpers.py::GROUPS).
GROUPS: tuple[str, ...] = (
    "work_project_alpha",
    "work_project_beta",
    "private_programming",
    "rpg_worldbuilding",
    "general_programming",
)

# Deterministic synthesized provenance timestamp (corpus docs carry no real capture time).
_CORPUS_CREATED_AT = "2026-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class CorpusDoc:
    """A corpus document: its schema-conformant metadata bundle plus its body text."""

    metadata_bundle: MetadataBundle
    text: str


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading ``---`` frontmatter block of flat ``key: value`` lines."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1 :])
    return meta, body


def _bundle_for(group: str, path: Path, meta: dict[str, str]) -> MetadataBundle:
    object_id = f"artifact:{group}/{path.stem}"
    authority_state = meta["authority_state"]
    # Accepted/canonical corpus docs need a receipt (governed standing); synthesize one.
    receipt = (
        f"receipt:corpus:{object_id}" if authority_state in CANONICAL_AUTHORITY_STATES else None
    )
    return MetadataBundle(
        object_id=object_id,
        object_type="artifact",
        scope_id=meta["scope_id"],
        source_role=meta["source_role"],
        authority_state=authority_state,
        evidence_role=meta["evidence_role"],
        sensitivity=meta["sensitivity"],
        suppression_state="visible",
        created_by="corpus:synthetic",
        created_at=_CORPUS_CREATED_AT,
        provenance_event_ids=[f"prov:corpus:{object_id}"],
        sphere=meta.get("sphere"),
        authority_receipt_ref=receipt,
    )


def load_group(group: str) -> list[CorpusDoc]:
    docs: list[CorpusDoc] = []
    group_dir = FIXTURES_DIR / group
    for path in sorted(group_dir.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        docs.append(CorpusDoc(metadata_bundle=_bundle_for(group, path, meta), text=body))
    return docs


def load_corpus() -> list[CorpusDoc]:
    """Load every fixture doc across the five scope groups as MetadataBundle-carrying CorpusDocs."""
    docs: list[CorpusDoc] = []
    for group in GROUPS:
        docs.extend(load_group(group))
    return docs
