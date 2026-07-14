from pathlib import Path

import yaml


TASK_SOURCE_ANCHORS = {
    "WRITE_RECEIPT_PROVENANCE.md": (
        "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1, 4, 6"
    ),
    "REWRITTEN_NOTE_CONFLICT_STAGING.md": (
        "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1-2, 6"
    ),
    "ICLOUD_CONFLICT_QUARANTINE.md": (
        "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: item 3"
    ),
    "RECONCILE_AND_CLOSE_MULTIWRITER_ENACTMENT.md": (
        "docs/testing/invariant-tests.md :: INV-VW1, INV-VW3"
    ),
}
TASK_DIR = Path("docs/VAULT_MULTIWRITER_ENACTMENT")


def test_task_source_anchor_frontmatter_is_valid() -> None:
    for filename, expected_anchor in TASK_SOURCE_ANCHORS.items():
        document = (TASK_DIR / filename).read_text(encoding="utf-8")
        frontmatter = document.split("---", 2)[1]

        metadata = yaml.safe_load(frontmatter)

        assert metadata["source_anchor"] == expected_anchor
