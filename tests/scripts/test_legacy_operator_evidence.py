from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from app.builderops import legacy_owner_recovery as recovery
from scripts import legacy_operator_evidence as evidence


def test_draft_reads_real_git_and_leaves_authority_unknown(tmp_path, monkeypatch):
    root = tmp_path / "agentic-pkm-mvp"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()
    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (root / "file").write_text("base\n")
    git("add", "file")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (root / "file").write_text("candidate\n")
    git("commit", "-qam", "candidate")
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    prior = {"owner": "former"}
    candidate = {"path": str(root), "branch": branch, "head": head, "generation": "a" * 32,
                 "tree": git("rev-parse", "HEAD^{tree}"), "status_digest": "b" * 64}
    registration = {"history_digest": hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest(),
                    "branch_history_digest": "c" * 64}
    publication = {"state": "open_pr_observed", "pr": 10, "branch": branch, "head": head}
    monkeypatch.setenv("CODEX_SESSION_ID", "successor")
    monkeypatch.setattr(evidence.legacy_git_config, "QUALIFIED_COMMON", (root / ".git").resolve())
    monkeypatch.setattr(evidence.legacy_git_config, "_qualified_home", lambda: tmp_path)
    monkeypatch.setattr(evidence.legacy_git_config, "check_host_config", lambda: None)
    monkeypatch.setattr(recovery, "read_live_predecessor", lambda **kw: {"repo": "fixture/repo"})
    monkeypatch.setattr(recovery, "read_clean_candidate", lambda **kw: candidate)
    monkeypatch.setattr(recovery, "read_expired_registration", lambda **kw: registration)
    monkeypatch.setattr(recovery, "read_live_publication", lambda **kw: publication)
    monkeypatch.setattr(recovery, "_verify_pr_origin", lambda **kw: None)
    monkeypatch.setattr(recovery, "_locked_raw_branch_snapshot", lambda *args, **kwargs: {str(root): prior})
    monkeypatch.setattr(evidence.agent_worktree, "_operator_branch_history_digest", lambda *args, **kwargs: "c" * 64)
    draft = evidence.build_draft(cwd=root, issue=1, pr=10, worktree=root, base=base,
                                 agent="agent", session="successor")["operator_reconciliation.v1"]
    assert draft["changed_files"] == ["file"]
    assert draft["predecessor_registration"] == prior
    assert draft["writer"]["state"] is None and draft["publication"]["state"] is None
    assert draft["mandate"]["reference"] is None
    comment = {"id": 1, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
               "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
               "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/1",
               "body": json.dumps({"operator_reconciliation.v1": draft})}
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.validate_operator_reconciliation(comment, issue=1, pr=10, github_login="RasmusTho",
            successor=draft["successor"], predecessor=draft["predecessor"], registration=registration,
            candidate=candidate, writer=draft["writer"], publication=draft["publication"])
    assert git("status", "--porcelain") == ""


def test_refuses_missing_actual_successor(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    with pytest.raises(recovery.RecoveryEvidenceError, match="successor identity"):
        evidence.build_draft(cwd=tmp_path, issue=1, pr=2, worktree=tmp_path,
                             base="a" * 40, agent="agent", session="other")


def test_draft_refuses_config_before_dispatcher_or_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_SESSION_ID", "successor")
    monkeypatch.setattr(evidence.legacy_git_config, "check_host_config", lambda: None)
    def refuse(**_kwargs):
        raise evidence.legacy_git_config.ConfigError("unsupported config")
    monkeypatch.setattr(evidence.legacy_git_config, "check", refuse)
    monkeypatch.setattr(recovery, "read_live_predecessor", lambda **_kwargs: pytest.fail("dispatcher read before config check"))
    with pytest.raises(recovery.RecoveryEvidenceError, match="Git configuration"):
        evidence.build_draft(cwd=tmp_path, issue=1, pr=2, worktree=tmp_path,
                             base="a" * 40, agent="agent", session="successor")
