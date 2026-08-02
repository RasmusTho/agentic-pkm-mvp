import os
import subprocess
import sys
from pathlib import Path

from app.agents.merge_resolver.agent import merge_note_from_blobs
from app.cli.merge_driver import run_merge

_REPO_ROOT = Path(__file__).resolve().parents[2]

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


def test_resolved_merge_writes_result_to_ours_path(tmp_path: Path):
    # Git's custom-merge-driver contract requires the result on %A (a_path).
    # a has no markdown link; b has one that a lacks, so the semantic merge's
    # link-carryover heuristic appends content that only exists on the incoming
    # (b) side -- proving a_path ends up with more than a verbatim copy of a.
    base = """---
uuid: u-write
kind: concept
review_state: draft
---
# T
base body
"""
    a = """---
uuid: u-write
kind: concept
review_state: reviewed
---
# T
ours body, no link
"""
    b = """---
uuid: u-write
kind: concept
review_state: reviewed
---
# T
theirs body with [a link](https://example.com/incoming)
"""
    base_path = _tmpfile(tmp_path, base)
    a_path = _tmpfile(tmp_path, a)
    b_path = _tmpfile(tmp_path, b)

    expected_merged, info = merge_note_from_blobs(base, a, b)
    assert info["status"] == "resolved"

    ec = run_merge(base_path, a_path, b_path)

    assert ec == 0
    written = a_path.read_text(encoding="utf-8")
    assert written == expected_merged
    # The incoming (b) side's link must be present in what git reads back.
    assert "https://example.com/incoming" in written


def test_diagnostic_trailer_never_enters_merged_file(tmp_path: Path):
    base = """---
uuid: u-trailer
kind: concept
review_state: draft
---
# T
base
"""
    a = """---
uuid: u-trailer
kind: concept
review_state: reviewed
---
# T
same body
"""
    b = """---
uuid: u-trailer
kind: concept
review_state: reviewed
---
# T
same body
"""
    a_path = _tmpfile(tmp_path, a)
    ec = run_merge(_tmpfile(tmp_path, base), a_path, _tmpfile(tmp_path, b))

    assert ec == 0
    written = a_path.read_text(encoding="utf-8")
    assert "MERGE_STATUS" not in written
    assert "MERGE_REASON" not in written


def test_prompted_and_uuid_mismatch_still_exit_nonzero(tmp_path: Path):
    # uuid mismatch is the one reachable non-resolved path today; the driver
    # must still fail closed (non-zero exit) and must not overwrite a_path with
    # anything -- git is left to report the conflict using its normal machinery.
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
    a_path = _tmpfile(tmp_path, a)
    ec = run_merge(_tmpfile(tmp_path, base), a_path, _tmpfile(tmp_path, b))

    assert ec != 0
    # a_path must be left exactly as git wrote it (OURS); the driver must not
    # silently substitute content on a non-resolved outcome.
    assert a_path.read_text(encoding="utf-8") == a


def _git(args, cwd, env):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_end_to_end_git_merge_through_driver_preserves_incoming(tmp_path: Path):
    # Exercise the production .gitattributes + `git config merge.semanticmd.driver`
    # path (the same wiring set up by `make setup-merge-driver`), not run_merge()
    # directly, so a regression in how git invokes/reads the driver is caught too.
    repo = tmp_path / "repo"
    repo.mkdir()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for k, v in {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        env[k] = v

    _git(["init", "-q"], repo, env)
    _git(["config", "commit.gpgsign", "false"], repo, env)
    _git(["config", "merge.semanticmd.name", "Semantic Markdown merge (test)"], repo, env)
    _git(
        ["config", "merge.semanticmd.driver", f"{sys.executable} -m app.cli.merge_driver %O %A %B"],
        repo, env,
    )
    (repo / ".gitattributes").write_text("*.md merge=semanticmd\n", encoding="utf-8")

    note = repo / "n.md"
    base_body = """---
uuid: u-e2e
kind: concept
review_state: draft
---
# T
base body, no link
"""
    note.write_text(base_body, encoding="utf-8")
    _git(["add", "."], repo, env)
    _git(["commit", "-q", "-m", "base"], repo, env)
    main_branch = _git(["branch", "--show-current"], repo, env).stdout.strip()

    _git(["checkout", "-q", "-b", "theirs"], repo, env)
    theirs_body = """---
uuid: u-e2e
kind: concept
review_state: reviewed
---
# T
theirs body with [incoming link](https://example.com/incoming)
"""
    note.write_text(theirs_body, encoding="utf-8")
    _git(["commit", "-q", "-am", "theirs edit"], repo, env)

    _git(["checkout", "-q", main_branch], repo, env)
    ours_body = """---
uuid: u-e2e
kind: concept
review_state: reviewed
---
# T
ours body, no link
"""
    note.write_text(ours_body, encoding="utf-8")
    _git(["commit", "-q", "-am", "ours edit"], repo, env)

    merge = subprocess.run(
        ["git", "merge", "-q", "--no-edit", "theirs"],
        cwd=repo, env=env, capture_output=True, text=True,
    )

    assert merge.returncode == 0, merge.stdout + merge.stderr
    merged_on_disk = note.read_text(encoding="utf-8")
    # The incoming side's content must have actually reached the working file --
    # this is the exact defect: a clean merge that discards THEIRS silently.
    assert "https://example.com/incoming" in merged_on_disk
    assert "MERGE_STATUS" not in merged_on_disk
    assert "MERGE_REASON" not in merged_on_disk
