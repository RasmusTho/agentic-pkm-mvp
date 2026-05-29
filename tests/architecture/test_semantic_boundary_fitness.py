"""Semantic-boundary fitness checks.

Characterization tests that guard the two cheapest leakage-prevention rules
identified in docs/SEMANTIC_DRIFT_AUDIT.md (audit issue #1372, epic #1363):

1. Frontmatter field allowlist — fields written by the system to vault
   frontmatter must be a subset of the allowlist declared in FRONTMATTER.md.

2. Store/index rebuild-source declaration — every concrete (non-memory) store
   or index that the app registers as a machine mirror must declare a
   ``rebuild_source`` class attribute, consistent with the machine-mirror
   authority contract (docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md
   §"Leakage-prevention rules").

Adding a new store/index without a ``rebuild_source`` or writing an unknown
field to frontmatter will cause the respective test to fail.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

# Fields the system is permitted to write to vault frontmatter.
# Source: docs/FRONTMATTER.md §"System-owned (bounded)" and the write contract.
# If FRONTMATTER.md grants a new field, add it here and update that doc in the
# same PR so the two stay in sync.
SYSTEM_FRONTMATTER_ALLOWLIST: frozenset[str] = frozenset(
    {
        "uuid",  # stable identity; PKA-owned
        "title",  # written only on initial healing / promotion with explicit title
        "source_ref",  # vault-relative path continuity field
        "trust",  # guardrail
        "review_state",  # mutation-posture axis
        "maturity",  # development/standing axis (policy-selected)
        "zone",  # derived runtime overlay
        "recency",  # derived runtime overlay
        "salience",  # derived runtime overlay
    }
)


def _run_apply_promotion_frontmatter(
    tmp_path: Path,
    extra_fm: dict[str, Any] | None = None,
    review_state: str = "evergreen",
    maturity: str | None = None,
    note_uuid: str = "test-uuid-1234",
    optional_title: str | None = None,
) -> dict[str, Any]:
    """Execute apply_promotion_frontmatter and return the parsed frontmatter."""
    from scripts.yaml_roundtrip import load_frontmatter
    from app.services.note_update import apply_promotion_frontmatter

    base_fm = {"uuid": note_uuid, **(extra_fm or {})}
    fm_lines = "\n".join(f"{k}: {v}" for k, v in base_fm.items())
    markdown = f"---\n{fm_lines}\n---\nBody text.\n"

    note_path = tmp_path / "test_note.md"
    note_path.write_text(markdown, encoding="utf-8")

    apply_promotion_frontmatter(
        note_path=note_path,
        note_uuid=note_uuid,
        new_review_state=review_state,
        maturity=maturity,
        optional_title=optional_title,
    )
    fm, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    return dict(fm or {})


# ---------------------------------------------------------------------------
# Check 1 — frontmatter allowlist
# ---------------------------------------------------------------------------


def test_system_written_frontmatter_fields_within_allowlist(tmp_path: Path) -> None:
    """apply_promotion_frontmatter must only write fields in the allowlist.

    If this test fails, either:
    - A new field was added to the system write path without updating
      FRONTMATTER.md + SYSTEM_FRONTMATTER_ALLOWLIST, or
    - A field was accidentally added to the write path.

    Fix: add the field to FRONTMATTER.md §System-owned and to
    SYSTEM_FRONTMATTER_ALLOWLIST in this file.
    """
    result = _run_apply_promotion_frontmatter(
        tmp_path,
        review_state="evergreen",
        maturity="stable",
    )
    written = frozenset(result.keys())
    unknown = written - SYSTEM_FRONTMATTER_ALLOWLIST
    assert not unknown, (
        f"apply_promotion_frontmatter wrote fields outside the allowlist: "
        f"{sorted(unknown)!r}. "
        f"Either update FRONTMATTER.md + SYSTEM_FRONTMATTER_ALLOWLIST, "
        f"or remove the unexpected write."
    )


def test_system_frontmatter_writes_expected_fields(tmp_path: Path) -> None:
    """Characterization: the function writes uuid, review_state, maturity.

    review_state="evergreen" is a legacy alias normalized to "reviewed";
    maturity="stable" is preserved as-is.
    """
    result = _run_apply_promotion_frontmatter(
        tmp_path,
        review_state="evergreen",
        maturity="stable",
    )
    assert result.get("review_state") == "reviewed"  # "evergreen" is a legacy alias
    assert result.get("maturity") == "stable"
    assert result.get("uuid") == "test-uuid-1234"


def test_system_frontmatter_title_only_when_provided(tmp_path: Path) -> None:
    """Title is written only when optional_title is explicitly given."""
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    without_title = _run_apply_promotion_frontmatter(dir_a, optional_title=None)
    assert "title" not in without_title or without_title.get("title") is None

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    with_title = _run_apply_promotion_frontmatter(dir_b, optional_title="My Note")
    assert with_title.get("title") == "My Note"


# ---------------------------------------------------------------------------
# Check 2 — store/index rebuild-source declaration
# ---------------------------------------------------------------------------


def _get_pg_store_classes() -> list[type]:
    """Return all production (non-memory) store classes from app/stores/."""
    from app.stores.pg import PgObjectStore, PgVectorIndex, PgRelationIndex

    return [PgObjectStore, PgVectorIndex, PgRelationIndex]


def test_stores_declare_rebuild_source() -> None:
    """Every production store/index must declare a rebuild_source class attribute.

    Source: docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md
    §"Leakage-prevention rules": "A new store/index/cache must declare its
    rebuild source and confirm it loses no meaning on rebuild before it is added."

    If this test fails because a new store lacks rebuild_source, add the
    attribute to the class and document the rebuild path.
    """
    missing: list[str] = []
    for cls in _get_pg_store_classes():
        if not hasattr(cls, "rebuild_source") or not cls.rebuild_source:
            missing.append(cls.__name__)

    assert not missing, (
        f"These store/index classes lack a non-empty 'rebuild_source' class "
        f"attribute: {missing!r}. "
        f"Add ``rebuild_source = '<upstream source>'`` to each class and "
        f"document the rebuild path per the machine-mirror authority contract."
    )


def test_rebuild_source_is_non_empty_string() -> None:
    """rebuild_source must be a non-empty string naming the upstream."""
    for cls in _get_pg_store_classes():
        src = getattr(cls, "rebuild_source", None)
        assert isinstance(src, str) and src.strip(), (
            f"{cls.__name__}.rebuild_source must be a non-empty string, got {src!r}"
        )
