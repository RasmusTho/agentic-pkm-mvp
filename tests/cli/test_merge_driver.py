from pathlib import Path
from app.cli.merge_driver import run_merge

_counter = 0
def _tmpfile(tmp_path: Path, body: str) -> Path:
    global _counter
    _counter += 1
    p = tmp_path / f"n{_counter}.md"
    p.write_text(body, encoding="utf-8")
    return p

def test_merge_driver_resolved(tmp_path: Path):
    base = """---
uuid: u-test
kind: concept
review_state: draft
---
# T
base
"""
    a = """---
uuid: u-test
kind: concept
review_state: reviewed
---
# T
clean summary
"""
    b = """---
uuid: u-test
kind: concept
review_state: reviewed
---
# T
clean summary
"""
    ec = run_merge(
        _tmpfile(tmp_path, base),
        _tmpfile(tmp_path, a),
        _tmpfile(tmp_path, b),
    )
    assert ec == 0

def test_merge_driver_prompted(tmp_path: Path):
    base = """---
uuid: u-test
kind: concept
review_state: draft
---
# T
base
"""
    a = """---
uuid: u-test
kind: concept
review_state: reviewed
---
# T
A body
"""
    b = """---
uuid: u-OTHER
kind: concept
review_state: reviewed
---
# T
B body
"""
    ec = run_merge(
        _tmpfile(tmp_path, base),
        _tmpfile(tmp_path, a),
        _tmpfile(tmp_path, b),
    )
    # Different UUIDs => merge_driver must refuse automatic resolution
    assert ec != 0
