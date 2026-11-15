"""Operator receipts are evidence inputs, not predecessor handoffs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import time

import pytest

from app.builderops.legacy_owner_recovery import (
    RecoveryEvidenceError,
    read_clean_candidate,
    read_expired_registration,
    read_live_predecessor,
    read_live_publication,
    read_operator_reconciliation,
    preflight_operator_pickup,
    validate_operator_reconciliation,
)
from scripts import agent_worktree
from app.dispatcher import leases
from app.dispatcher.events import JsonlEventWriter, event_history_digest
from app.dispatcher.models import EventRecord, TaskRecord
from app.dispatcher.store import SqliteStore


@pytest.fixture
def evidence():
    observed = {
        "successor": {"agent": "new-agent", "session": "new-session"},
        "predecessor": {"task_id": "github-RasmusTho--agentic-pkm-mvp-issue-6601", "repo": "RasmusTho/agentic-pkm-mvp",
                        "issue_number": 6601, "holder": "old-agent", "lease_id": "lease-old", "claim_event_id": "event-old",
                        "claim_event_digest": "a" * 64, "history_digest": "b" * 64, "session": None,
                        "expires_at": "2026-11-09T00:00:00Z"},
        "candidate": {"path": "/isolated/worktree", "branch": "codex/issue-6601",
                      "generation": "a" * 32, "head": "b" * 40, "tree": "e" * 40, "status_digest": "c" * 64},
        "registration": {"path": "/isolated/worktree", "branch": "codex/issue-6601",
                         "generation": "a" * 32, "owner": "old-session", "state": "expired",
                         "registered_at": "2026-11-08T00:00:00Z", "expires_at": "2026-11-09T00:00:00Z",
                         "authority_since": None, "registration_epoch": None, "history_digest": "f" * 64},
        "writer": {"state": "stopped", "delegations": "stopped", "restart": "reconciled",
                   "last_activity": "2026-11-09T00:00:00Z", "boot": "2026-11-14T22:00:00Z",
                   "sources": {"execution": ["fixture:execution"], "delegations": ["fixture:delegations"],
                               "restart": ["fixture:restart"]}},
        "publication": {"state": "reconciled", "pr": 6602, "head": "d" * 40,
                        "repo": "RasmusTho/agentic-pkm-mvp", "branch": "codex/issue-6601", "pr_state": "OPEN",
                        "body_sha256": "f" * 64,
                        "sources": {"attempts": ["fixture:attempt"], "github": ["fixture:github"]}},
    }
    receipt = {
        "issue": 6601,
        "mode": "operator",
        "account": "RasmusTho",
        "mandate": {"reference": "explicitly authorized issue 6601", "repo": "RasmusTho/agentic-pkm-mvp", "issue": 6601,
                    "effects": ["reconcile", "claim", "register", "acknowledge"]},
        **copy.deepcopy(observed),
    }
    comment = {
        "id": 123,
        "author_association": "OWNER",
        "user": {"login": "RasmusTho"},
        "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6601",
        "created_at": "2026-11-15T08:00:00Z",
        "updated_at": "2026-11-15T08:00:00Z",
        "body": json.dumps({"operator_reconciliation.v1": receipt}),
    }
    return comment, observed


def test_authenticated_operator_evidence_keeps_unpublished_candidate_distinct(evidence):
    comment, observed = evidence
    receipt, _, digest = validate_operator_reconciliation(
        comment, issue=6601, pr=6602, github_login="RasmusTho", **observed
    )
    assert receipt["predecessor"]["session"] is None
    assert len(digest) == 64
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="malformed"):
        agent_worktree._transfer_comment(comment, issue=6601, pr=6602)


def test_operator_preflight_reads_current_sources_and_refuses_claim_drift(evidence, tmp_path, monkeypatch):
    from app.builderops import legacy_owner_recovery as recovery

    comment, observed = evidence
    raw = json.loads(comment["body"])
    receipt = raw["operator_reconciliation.v1"]
    old_event = {"event_id": "event-old", "timestamp": "2026-11-08T00:00:00Z",
                 "task_id": observed["predecessor"]["task_id"], "event_type": "task.claimed",
                 "actor": "old-agent", "lease_id": "lease-old", "payload": {"ttl_minutes": 1440}}
    observed["predecessor"]["history_digest"] = event_history_digest([old_event])
    prior = {"path": observed["candidate"]["path"], "owner": "old-session"}
    observed["registration"]["history_digest"] = hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
    observed["registration"]["branch_history_digest"] = "9" * 64
    receipt.update(copy.deepcopy(observed))
    receipt.update({"branch": observed["candidate"]["branch"], "writable_worktree": observed["candidate"]["path"],
                    "predecessor_registration": prior, "branch_history_digest": "9" * 64,
                    "base": "1" * 40, "unpublished_candidate_head": observed["candidate"]["head"],
                    "changed_files": ["fixture.py"]})
    comment["body"] = json.dumps(raw)
    monkeypatch.setenv("CODEX_SESSION_ID", "new-session")
    monkeypatch.setattr(agent_worktree, "_read_github_transfer_comment", lambda _id, *, cwd: comment)
    monkeypatch.setattr(agent_worktree, "_default_registry_path", lambda cwd: tmp_path / "registry")
    monkeypatch.setattr(agent_worktree, "_locked_lifecycle_snapshot", lambda _path: {prior["path"]: prior})
    monkeypatch.setattr(agent_worktree, "_branch_history_digest", lambda _records, _branch: "9" * 64)
    monkeypatch.setattr(agent_worktree, "_operator_candidate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(recovery, "_github_read", lambda args, *, cwd: "[[]]" if "--slurp" in args else "RasmusTho\n")
    monkeypatch.setattr(recovery, "read_live_predecessor", lambda **_kwargs: observed["predecessor"])
    monkeypatch.setattr(recovery, "_read_task_events", lambda **_kwargs: [old_event])
    monkeypatch.setattr(recovery, "read_clean_candidate", lambda **_kwargs: observed["candidate"])
    monkeypatch.setattr(recovery, "read_expired_registration", lambda **_kwargs: observed["registration"])
    live_pr = {k: v for k, v in observed["publication"].items() if k != "sources"}
    live_pr["state"] = "open_pr_observed"
    monkeypatch.setattr(recovery, "read_live_publication", lambda **_kwargs: live_pr)
    monkeypatch.setattr(recovery, "_verify_pr_origin", lambda **_kwargs: None)

    args = dict(cwd=tmp_path, issue=6601, pr=6602, worktree=Path(prior["path"]),
                agent="new-agent", session="new-session", comment_id=123, workspace_root=tmp_path.parent / (tmp_path.name + "-model"))
    assert preflight_operator_pickup(**args)["predecessor"]["session"] is None
    monkeypatch.setattr(recovery, "read_live_predecessor", lambda **_kwargs: {**observed["predecessor"], "lease_id": "changed"})
    with pytest.raises(RecoveryEvidenceError, match="legacy claimant history is not eligible"):
        preflight_operator_pickup(**args)


def test_mixed_operator_and_predecessor_receipt_is_never_a_handoff(evidence):
    comment, _ = evidence
    payload = json.loads(comment["body"])
    payload["lifecycle_handoff_receipt.v1"] = {"successor": {"session": "new"}}
    comment["body"] = json.dumps(payload)
    for key in ("operator_reconciliation.v1", "lifecycle_handoff_receipt.v1"):
        with pytest.raises(agent_worktree.WorktreeLifecycleError, match="mixed authority"):
            agent_worktree._transfer_comment(comment, issue=6601, pr=6602, receipt_key=key)


def test_same_agent_with_a_new_session_is_not_mistaken_for_the_predecessor(evidence):
    comment, observed = evidence
    observed["successor"]["agent"] = observed["predecessor"]["holder"]
    receipt = json.loads(comment["body"])
    receipt["operator_reconciliation.v1"].update(copy.deepcopy(observed))
    comment["body"] = json.dumps(receipt)
    validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


def test_host_github_readback_checks_authenticated_account(evidence, tmp_path, monkeypatch):
    comment, observed = evidence
    comment_path = tmp_path / "comment.json"
    comment_path.write_text(json.dumps(comment), encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\nif [ "$4" = user ]; then printf "%s\\n" "$RECOVERY_TEST_LOGIN"; '
        'else cat "$RECOVERY_TEST_COMMENT"; fi\n', encoding="utf-8"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("RECOVERY_TEST_COMMENT", str(comment_path))
    monkeypatch.setenv("RECOVERY_TEST_LOGIN", "RasmusTho")
    receipt, _, _ = read_operator_reconciliation(123, cwd=tmp_path, issue=6601, pr=6602, **observed)
    assert receipt["issue"] == 6601

    monkeypatch.setenv("RECOVERY_TEST_LOGIN", "someone-else")
    with pytest.raises(RecoveryEvidenceError, match="readback is unavailable"):
        read_operator_reconciliation(123, cwd=tmp_path, issue=6601, pr=6602, **observed)


def test_live_github_publication_readback_refuses_duplicate_or_drift(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\ncase " $* " in *" --slurp "*) case " $* " in *" state=all "*) '
        'cat "$RECOVERY_TEST_PAGES" ;; *) exit 2 ;; esac ;; '
        '*" user "*) printf "%s\\n" "$RECOVERY_TEST_LOGIN" ;; '
        '*"/pulls/6602 "*) cat "$RECOVERY_TEST_PR" ;; '
        '*"/git/ref/heads/"*) cat "$RECOVERY_TEST_REF" ;; '
        '*) cat "$RECOVERY_TEST_REPO" ;; esac\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    pr_path, pages_path, repo_path, ref_path = (tmp_path / "pr.json", tmp_path / "pages.json",
                                               tmp_path / "repo.json", tmp_path / "ref.json")
    pr_data = {"number": 6602, "state": "open", "body": "fixture body", "head": {"ref": "codex/issue-6601", "sha": "d" * 40,
               "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}},
               "base": {"ref": "main", "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}}
    pr_path.write_text(json.dumps(pr_data), encoding="utf-8")
    repo_path.write_text(json.dumps({"full_name": "RasmusTho/agentic-pkm-mvp", "default_branch": "main"}),
                         encoding="utf-8")
    ref_path.write_text(json.dumps({"ref": "refs/heads/codex/issue-6601", "object": {"sha": "d" * 40}}),
                        encoding="utf-8")
    pages_path.write_text(json.dumps([[pr_data]]), encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("RECOVERY_TEST_LOGIN", "RasmusTho")
    monkeypatch.setenv("RECOVERY_TEST_PR", str(pr_path))
    monkeypatch.setenv("RECOVERY_TEST_PAGES", str(pages_path))
    monkeypatch.setenv("RECOVERY_TEST_REPO", str(repo_path))
    monkeypatch.setenv("RECOVERY_TEST_REF", str(ref_path))
    assert read_live_publication(cwd=tmp_path, pr=6602, branch="codex/issue-6601")["head"] == "d" * 40

    pages_path.write_text(json.dumps([[pr_data], [{"number": 9999, "state": "open"}]]), encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="duplicated or ambiguous"):
        read_live_publication(cwd=tmp_path, pr=6602, branch="codex/issue-6601")

    pages_path.write_text(json.dumps([[pr_data, {"number": 9999, "state": "closed"}]]), encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="duplicated or ambiguous"):
        read_live_publication(cwd=tmp_path, pr=6602, branch="codex/issue-6601")

    changed = copy.deepcopy(pr_data)
    changed["head"]["sha"] = "e" * 40
    pages_path.write_text(json.dumps([[changed]]), encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="duplicated or ambiguous"):
        read_live_publication(cwd=tmp_path, pr=6602, branch="codex/issue-6601")

    pages_path.write_text(json.dumps([[pr_data]]), encoding="utf-8")
    pr_data["head"]["ref"] = "changed-branch"
    pr_path.write_text(json.dumps(pr_data), encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="identity or head"):
        read_live_publication(cwd=tmp_path, pr=6602, branch="codex/issue-6601")


def test_clean_candidate_readback_preserves_dirty_work(tmp_path, monkeypatch):
    primary = tmp_path / "agentic-pkm-mvp"
    worktree = tmp_path / "checkout"
    subprocess.run(["git", "init", "-b", "main", str(primary)], check=True, capture_output=True)
    from app.builderops import legacy_git_config
    monkeypatch.setattr(legacy_git_config, "QUALIFIED_COMMON", (primary / ".git").resolve())
    monkeypatch.setattr(legacy_git_config, "_qualified_home", lambda: tmp_path)
    monkeypatch.setattr(legacy_git_config, "check_host_config", lambda: None)
    (primary / "candidate.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "add", "candidate.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(primary), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(primary), "worktree", "add", "-b", "codex/test-recovery", str(worktree)],
                   check=True, capture_output=True)
    generation = agent_worktree._worktree_generation(primary, worktree, create=True)
    agent_worktree.register_worktree(primary, worktree=worktree, owner="old-session", ttl_seconds=60,
                                    now=time.time() - 7200)
    clean = read_clean_candidate(cwd=primary, worktree=worktree)
    assert clean["generation"] == generation
    assert clean["branch"] == "codex/test-recovery"
    registration = read_expired_registration(cwd=primary, candidate=clean)
    assert registration["owner"] == "old-session"
    assert registration["state"] == "expired"
    registry = agent_worktree._default_registry_path(primary)
    with agent_worktree._locked_registry(registry) as payload:
        payload["worktrees"][str(worktree)]["transfer_registration"] = None
    with pytest.raises(RecoveryEvidenceError, match="not an exact expired record"):
        read_expired_registration(cwd=primary, candidate=clean)
    with agent_worktree._locked_registry(registry) as payload:
        del payload["worktrees"][str(worktree)]["transfer_registration"]
    changed_identity = {**clean, "generation": "f" * 32}
    with pytest.raises(RecoveryEvidenceError, match="not an exact expired record"):
        read_expired_registration(cwd=primary, candidate=changed_identity)

    other = tmp_path / "other-repo"
    subprocess.run(["git", "init", str(other)], check=True, capture_output=True)
    with pytest.raises(RecoveryEvidenceError, match="candidate (identity is unavailable|Git configuration is unsupported)"):
        read_clean_candidate(cwd=other, worktree=worktree)

    (worktree / "candidate.txt").write_text("unpublished change\n", encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="dirty"):
        read_clean_candidate(cwd=primary, worktree=worktree)
    assert (worktree / "candidate.txt").read_text(encoding="utf-8") == "unpublished change\n"
    (worktree / "candidate.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "update-index", "--assume-unchanged", "candidate.txt"],
                   check=True, capture_output=True)
    (worktree / "candidate.txt").write_text("hidden change\n", encoding="utf-8")
    with pytest.raises(RecoveryEvidenceError, match="hidden or unsupported index flags"):
        read_clean_candidate(cwd=primary, worktree=worktree)
    assert (worktree / "candidate.txt").read_text(encoding="utf-8") == "hidden change\n"


def test_registration_compares_observed_branch_history_under_lock(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    worktree = tmp_path / "checkout"
    repo.mkdir()
    worktree.mkdir()
    registry = tmp_path / "registry.json"
    branch = "codex/recovery"
    monkeypatch.setattr(agent_worktree, "_worktree_identity", lambda _cwd, _wt: (worktree, branch))
    monkeypatch.setattr(agent_worktree, "_worktree_generation", lambda _cwd, _wt, *, create: "a" * 32)
    agent_worktree.register_worktree(repo, worktree=worktree, owner="old", ttl_seconds=10,
                                    registry_path=registry, now=10)
    observed = agent_worktree._locked_lifecycle_snapshot(registry)
    digest = agent_worktree._branch_history_digest(observed, branch)
    with agent_worktree._locked_registry(registry) as payload:
        payload["worktrees"][str(worktree)]["heartbeat_at"] = 11
    changed = agent_worktree._locked_lifecycle_snapshot(registry)
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="observed branch history changed"):
        agent_worktree.register_worktree(repo, worktree=worktree, owner="new", registry_path=registry,
                                        now=30, expected_branch_history_digest=digest)
    assert agent_worktree._locked_lifecycle_snapshot(registry) == changed

    current_digest = agent_worktree._branch_history_digest(changed, branch)
    record = agent_worktree.register_worktree(repo, worktree=worktree, owner="new", registry_path=registry,
                                             now=30, expected_branch_history_digest=current_digest)
    assert record["owner"] == "new"
    assert record["prior_owner"]["owner"] == "old"
    assert record["prior_owner"]["released_at"] is None


def test_dispatcher_readback_observes_sessionless_claim_without_changing_it(tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    state_dir = tmp_path / "runtime" / "dispatcher"
    state_dir.mkdir(parents=True)
    store = SqliteStore(state_dir / "dispatcher.sqlite3", JsonlEventWriter(state_dir / "events.jsonl"))
    store.initialize()
    task_id = "github-RasmusTho--agentic-pkm-mvp-issue-6601"
    store.upsert_task(TaskRecord(task_id=task_id, issue_number=6601, title="fixture", status="ready", priority="high",
                                 source_anchor_refs=[], created_at="2020-01-01T00:00:00Z",
                                 updated_at="2020-01-01T00:00:00Z", repo="RasmusTho/agentic-pkm-mvp"))
    monkeypatch.setattr(leases, "_utc_now", lambda: "2020-01-01T00:00:00Z")
    _, old = leases.claim(store, task_id, "old-agent")
    before = store.list_events(task_id)

    observed = read_live_predecessor(cwd=tmp_path, issue=6601)
    assert observed["lease_id"] == old.lease_id
    assert observed["holder"] == "old-agent"
    assert observed["session"] is None
    assert store.list_events(task_id) == before
    assert store.get_task(task_id).lease_id == old.lease_id
    store.append_event(EventRecord(event_id="later-release", timestamp="2020-01-01T00:01:00Z", task_id=task_id,
                                   event_type="task.released", actor="old-agent", lease_id=old.lease_id,
                                   payload={"reason": "manual"}))
    with pytest.raises(RecoveryEvidenceError, match="claim history is ambiguous"):
        read_live_predecessor(cwd=tmp_path, issue=6601)


@pytest.mark.parametrize("field", ["successor", "predecessor", "registration", "candidate", "writer", "publication"])
def test_observation_drift_refuses_operator_evidence(evidence, field):
    comment, observed = evidence
    observed[field]["changed_after_receipt"] = True
    with pytest.raises(RecoveryEvidenceError, match="changed or could not be independently observed"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


@pytest.mark.parametrize("unknown", ["writer", "restart", "publication"])
def test_unknown_effects_never_satisfy_reconciliation(evidence, unknown):
    comment, observed = evidence
    if unknown == "writer":
        observed["writer"]["state"] = "unknown"
    elif unknown == "restart":
        observed["writer"]["restart"] = "unknown"
    else:
        observed["publication"]["state"] = "unknown"
    receipt = json.loads(comment["body"])
    receipt["operator_reconciliation.v1"].update(copy.deepcopy(observed))
    comment["body"] = json.dumps(receipt)
    with pytest.raises(RecoveryEvidenceError, match="outcome is unknown"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


def test_edited_or_foreign_comment_is_not_operator_authority(evidence):
    comment, observed = evidence
    comment["updated_at"] = "2026-11-15T08:01:00Z"
    with pytest.raises(RecoveryEvidenceError, match="not authenticated"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)

    comment["updated_at"] = comment["created_at"]
    comment["user"]["login"] = "someone-else"
    with pytest.raises(RecoveryEvidenceError, match="not authenticated"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


def test_operator_cannot_fabricate_predecessor_consent(evidence):
    comment, observed = evidence
    receipt = json.loads(comment["body"])
    receipt["operator_reconciliation.v1"]["predecessor_signature"] = "invented"
    comment["body"] = json.dumps(receipt)
    with pytest.raises(RecoveryEvidenceError, match="unexpected or missing fields"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


def test_operator_recovery_cannot_infer_publication_authority(evidence):
    comment, observed = evidence
    receipt = json.loads(comment["body"])
    receipt["operator_reconciliation.v1"]["mandate"]["effects"].append("merge")
    comment["body"] = json.dumps(receipt)
    with pytest.raises(RecoveryEvidenceError, match="scoped operator mandate"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


@pytest.mark.parametrize(("section", "key", "value"), [
    ("candidate", "generation", "not-a-generation"),
    ("candidate", "path", "relative/path"),
    ("candidate", "head", "not-a-commit"),
    ("publication", "repo", "someone/else"),
    ("publication", "branch", "other-branch"),
    ("predecessor", "task_id", "github-RasmusTho--agentic-pkm-mvp-issue-9999"),
    ("predecessor", "expires_at", "2099-01-01T00:00:00Z"),
    ("writer", "boot", "2026-11-08T00:00:00Z"),
])
def test_agreeing_but_invalid_evidence_is_still_refused(evidence, section, key, value):
    comment, observed = evidence
    observed[section][key] = value
    receipt = json.loads(comment["body"])
    receipt["operator_reconciliation.v1"].update(copy.deepcopy(observed))
    comment["body"] = json.dumps(receipt)
    with pytest.raises(RecoveryEvidenceError):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)


def test_operator_comment_cannot_also_be_a_predecessor_handoff(evidence):
    comment, observed = evidence
    receipt = json.loads(comment["body"])
    receipt["lifecycle_handoff_receipt.v1"] = {"issue": 6601}
    comment["body"] = json.dumps(receipt)
    with pytest.raises(RecoveryEvidenceError, match="not authenticated"):
        validate_operator_reconciliation(comment, issue=6601, pr=6602, github_login="RasmusTho", **observed)
