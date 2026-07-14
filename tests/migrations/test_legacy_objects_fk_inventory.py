"""Inventory guard for #3510's legacy objects FK cutover."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCOUNTED_CONSUMERS = {
    ("chunks", "object_id"),
    ("embeddings", "object_id"),
    ("relations", "src_id"),
    ("relations", "dst_id"),
    ("membership", "object_id"),
    ("membership", "set_id"),
    ("decisions", "object_id"),
    ("audit", "object_id"),
}


def test_all_legacy_objects_fk_consumers_are_accounted_for() -> None:
    discovered: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"(?P<column>object_id|set_id|src_id|dst_id)\s+UUID(?:\s+NOT NULL)?\s+"
        r"REFERENCES\s+(?:public\.)?objects\s*\(\s*id\s*\)",
        re.IGNORECASE,
    )
    table_pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS\s+(?:public\.)?(?P<table>[a-z_]+)\s*\("
        r"(?P<body>.*?)\n\s*\)\s*(?:;|\"\"\")",
        re.IGNORECASE | re.DOTALL,
    )

    for path in (REPO_ROOT / "app" / "alembic" / "versions").glob("*.py"):
        if path.name.startswith("7e4f2a1c9d30"):
            continue
        source = path.read_text(encoding="utf-8")
        for table_match in table_pattern.finditer(source):
            body = table_match.group("body")
            for column_match in pattern.finditer(body):
                discovered.add((table_match.group("table").lower(), column_match.group("column").lower()))

    migration_text = (
        REPO_ROOT
        / "app/alembic/versions/7e4f2a1c9d30_migrate_legacy_objects_fk_consumers.py"
    ).read_text(encoding="utf-8")
    for table, column in ACCOUNTED_CONSUMERS:
        assert f"('{table}', '{column}')" in migration_text or f'("{table}", "{column}")' in migration_text

    assert discovered <= ACCOUNTED_CONSUMERS
    assert {
        ("chunks", "object_id"),
        ("embeddings", "object_id"),
        ("relations", "src_id"),
        ("relations", "dst_id"),
        ("membership", "object_id"),
        ("decisions", "object_id"),
        ("audit", "object_id"),
    } <= discovered
