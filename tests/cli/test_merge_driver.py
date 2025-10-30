from pathlib import Path

from app.agents.merge_resolver.agent import merge_note_from_blobs

BASE = """---
uuid: u-merge
kind: concept
review_state: draft
---
# Topic
Initial state
"""

A = """---
uuid: u-merge
kind: concept
review_state: reviewed
---
# Topic
Crisp cleaned summary with structure.
"""

B = """---
uuid: u-merge
kind: concept
review_state: draft
---
# Topic
Crisp cleaned summary with structure.

## References
- [link-a](https://example.com/a)
"""


def test_merge_driver_contract(tmp_path: Path) -> None:
    base_path = tmp_path / "base.md"
    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"

    base_path.write_text(BASE, encoding="utf-8")
    a_path.write_text(A, encoding="utf-8")
    b_path.write_text(B, encoding="utf-8")

    merged, info = merge_note_from_blobs(BASE, A, B)

    assert info["status"] in {"resolved", "prompted", "conflict"}
    assert merged.startswith("---")
    assert "uuid:" in merged
    assert info["reason"].strip()
