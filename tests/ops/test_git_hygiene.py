import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from contextlib import nullcontext

import pytest

from scripts import git_hygiene


GENERATION = "a" * 32
REPOSITORY_ID = 1234
PUSH_URL = "git@github.com:RasmusTho/agentic-pkm-mvp.git"
FETCH_URL = "https://github.com/RasmusTho/agentic-pkm-mvp.git"
STANDARD_PR_BODY = "Governing-Issue: #5170\n\nFixes #5170\n"


def _targeted_candidate(**overrides):
    candidate = {
        "repository": "RasmusTho/agentic-pkm-mvp",
        "pull_request": 6000,
        "source_ref": "refs/heads/closed-unmerged",
        "source_sha": "a" * 40,
        "archive_ref": "",
        "owner": "builder-ops",
        "governing_issue": 5170,
        "no_issue_lane": None,
        "successor": "none",
        "retention_class": "safety_archive",
        "review_at": "2030-02-01T00:00:00Z",
        "discard": {"state": "retain", "receipt": None},
    }
    candidate.update(overrides)
    if not candidate["archive_ref"]:
        candidate["archive_ref"] = git_hygiene._archive_ref(
            REPOSITORY_ID, candidate["source_ref"], candidate["source_sha"]
        )
    return candidate


def _authenticated_contract(candidate) -> git_hygiene.PullContractIdentity:
    lane = candidate.no_issue_lane if isinstance(candidate, git_hygiene.Candidate) else candidate["no_issue_lane"]
    issue = candidate.governing_issue if isinstance(candidate, git_hygiene.Candidate) else candidate["governing_issue"]
    body = STANDARD_PR_BODY
    if lane is not None:
        body = (
            "## Change Lane\n"
            f"- [x] {'Governance' if lane == 'governance' else 'Docs authoring'} lane\n\n"
            "Final-Review-Rounds: 0\n"
        )
    return git_hygiene.PullContractIdentity(issue, lane, git_hygiene._sha256_pr_body(body))


def _remote_cleanup_transport(refs, commands, *, advance_before_delete=False):
    def fake(args: list[str], _cwd: Path):
        commands.append(args)
        if args[:2] == ["check-ref-format", args[1]]:
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:2] == ["ls-remote", "--exit-code"]:
            ref = args[-1]
            sha = refs.get(ref)
            return subprocess.CompletedProcess(["git", *args], 0 if sha else 2, f"{sha}\t{ref}\n" if sha else "", "")
        if args[0] == "fetch":
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:2] == ["cat-file", "-e"]:
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:2] == ["push", "--no-verify"] and ":refs/archive/" in args[-1]:
            sha, ref = args[-1].split(":", 1)
            if ref in refs:
                return subprocess.CompletedProcess(["git", *args], 1, "", "stale info")
            refs[ref] = sha
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:2] == ["push", "--no-verify"] and args[-1].startswith(":refs/heads/"):
            ref = args[-1][1:]
            if advance_before_delete:
                refs[ref] = "b" * 40
                return subprocess.CompletedProcess(["git", *args], 1, "", "stale info")
            refs.pop(ref, None)
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        raise AssertionError(args)
    return fake


def _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands):
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID,
        "RasmusTho/agentic-pkm-mvp",
        FETCH_URL,
        PUSH_URL,
    )
    protected = git_hygiene.ProtectedAuthority(
        issue_number=4728,
        pull_number=4813,
        pull_ref="refs/heads/codex/protected-4813",
        pull_sha="d" * 40,
    )
    monkeypatch.setattr(git_hygiene, "_resolve_repository_identity", lambda *_: identity)
    monkeypatch.setattr(git_hygiene, "_read_protected_targets", lambda *_args, **_kwargs: protected)
    monkeypatch.setattr(
        git_hygiene,
        "_read_candidate_pr",
        lambda _identity, candidate, **_kwargs: _authenticated_contract(candidate),
    )
    monkeypatch.setattr(
        git_hygiene, "_read_lifecycle_authority", lambda _cwd, _candidate: {}
    )
    monkeypatch.setattr(git_hygiene, "_lifecycle_conflicts", lambda *_: set())
    monkeypatch.setattr(git_hygiene, "_read_dispatcher_authority", lambda *_: [])
    monkeypatch.setattr(git_hygiene, "_git_common_dir", lambda _cwd: tmp_path / "common")
    monkeypatch.setattr(
        git_hygiene, "run_git_result", _remote_cleanup_transport(refs, commands)
    )
    return identity


def test_targeted_remote_cleanup_binds_complete_candidate_identity(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, {}, commands)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository="RasmusTho/agentic-pkm-mvp",
        candidates=[_targeted_candidate(owner="")],
    )
    assert report["ok"] is False
    assert report["error"] == "candidate_owner_invalid"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_requires_exact_archive_sha_readback(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"], candidate["archive_ref"]: "b" * 40}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["ok"] is False
    assert report["error"] == "archive_sha_mismatch"
    assert candidate["source_ref"] in refs


def test_targeted_remote_cleanup_cas_delete_stops_on_source_drift(tmp_path, monkeypatch) -> None:
    first, later = _targeted_candidate(), _targeted_candidate(source_ref="refs/heads/later")
    refs = {first["source_ref"]: first["source_sha"], later["source_ref"]: later["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    monkeypatch.setattr(git_hygiene, "run_git_result", _remote_cleanup_transport(refs, commands, advance_before_delete=True))
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=first["repository"], candidates=[first, later])
    assert report["ok"] is False
    assert report["error"] == "source_cas_delete_failed"
    assert later["source_ref"] in refs


def test_targeted_remote_cleanup_receipt_precedes_delete_and_completes_after_readback(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["ok"] is True
    receipts = tmp_path / "common" / "git-hygiene" / "targeted-remote-cleanup" / "v1" / "receipts"
    receipt = json.loads(next(receipts.glob("*.json")).read_text(encoding="utf-8"))
    assert receipt["state"] == "completed"
    assert receipt["identity"]["owner"] == "builder-ops"
    assert receipt["identity"]["authenticated_contract"] == {
        "governing_issue": 5170,
        "no_issue_lane": None,
        "pr_body_sha256": git_hygiene._sha256_pr_body(
            STANDARD_PR_BODY
        ),
    }
    assert candidate["source_ref"] not in refs


def test_targeted_remote_cleanup_retry_is_identity_bound_and_idempotent(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    first = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    before = len(commands)
    second = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert first["ok"] is second["ok"] is True
    assert not any(command[0] == "push" for command in commands[before:])


def test_archive_review_trigger_never_authorizes_archive_delete(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    commands: list[list[str]] = []
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["ok"] is True
    assert candidate["archive_ref"] in {candidate["archive_ref"]}
    assert not any(command[-1] == f":{candidate['archive_ref']}" for command in commands if command[0] == "push")


def test_targeted_remote_cleanup_rejects_wrong_origin_without_push(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, {}, commands)
    monkeypatch.setattr(
        git_hygiene,
        "_resolve_repository_identity",
        lambda *_: (_ for _ in ()).throw(RuntimeError("origin_repository_mismatch")),
    )
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["error"] == "origin_repository_mismatch"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_protects_live_pr_heads_without_push(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate(source_ref="refs/heads/codex/protected-4813")
    candidate["archive_ref"] = git_hygiene._archive_ref(REPOSITORY_ID, candidate["source_ref"], candidate["source_sha"])
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, {}, commands)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["error"] == "candidate_uses_protected_pull_head"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_preflights_archive_collisions_without_push(tmp_path, monkeypatch) -> None:
    first = _targeted_candidate()
    second = _targeted_candidate(source_ref="refs/heads/other", archive_ref=first["archive_ref"])
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, {}, commands)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=first["repository"], candidates=[first, second])
    assert report["error"] == "candidate_archive_ref_invalid"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_prepared_write_failure_never_deletes(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    monkeypatch.setattr(
        git_hygiene,
        "_crash_hook",
        lambda point: (_ for _ in ()).throw(OSError(point))
        if point == "after_prepared_dir_fsync"
        else None,
    )
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["ok"] is False
    assert candidate["source_ref"] in refs
    assert not any(command[-1].startswith(":refs/heads/") for command in commands if command[0] == "push")


def test_targeted_remote_cleanup_completed_write_failure_recovers_monotonically(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    monkeypatch.setattr(
        git_hygiene,
        "_crash_hook",
        lambda point: (_ for _ in ()).throw(OSError(point))
        if point == "before_completed_replace"
        else None,
    )
    first = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    monkeypatch.setattr(git_hygiene, "_crash_hook", lambda _point: None)
    second = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert first["ok"] is False and second["ok"] is True
    receipts = tmp_path / "common" / "git-hygiene" / "targeted-remote-cleanup" / "v1" / "receipts"
    assert json.loads(next(receipts.glob("*.json")).read_text())["state"] == "completed"


def test_targeted_remote_cleanup_post_delete_readback_failure_retains_prepared(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    base = _remote_cleanup_transport(refs, commands)
    def stale_delete(args, cwd):
        if args[:2] == ["push", "--no-verify"] and args[-1].startswith(":refs/heads/"):
            commands.append(args)
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        return base(args, cwd)
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    monkeypatch.setattr(git_hygiene, "run_git_result", stale_delete)
    report = git_hygiene.targeted_remote_cleanup(tmp_path, repository=candidate["repository"], candidates=[candidate])
    assert report["error"] == "post_delete_readback_failed"
    receipts = tmp_path / "common" / "git-hygiene" / "targeted-remote-cleanup" / "v1" / "receipts"
    assert json.loads(next(receipts.glob("*.json")).read_text())["state"] == "prepared"


def _closed_pull_payload(
    *,
    number=6000,
    state="closed",
    merged=False,
    merged_at=None,
    repo_id=REPOSITORY_ID,
    ref="closed-unmerged",
    sha="a" * 40,
    body=STANDARD_PR_BODY,
):
    return {
        "number": number,
        "state": state,
        "merged": merged,
        "merged_at": merged_at,
        "head": {"repo": {"id": repo_id}, "ref": ref, "sha": sha},
        "body": body,
    }


def test_targeted_remote_cleanup_requires_live_closed_unmerged_exact_pr(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    reads = 0
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)

    def read_pr(_identity, value, **_kwargs):
        nonlocal reads
        reads += 1
        return _authenticated_contract(value)

    monkeypatch.setattr(git_hygiene, "_read_candidate_pr", read_pr)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["ok"] is True
    assert reads >= 4  # batch, no-side-effect preflight, archive, delete


@pytest.mark.parametrize(
    "payload",
    [
        _closed_pull_payload(state="open"),
        _closed_pull_payload(merged=True, merged_at="2026-08-29T00:00:00Z"),
        _closed_pull_payload(repo_id=999),
        _closed_pull_payload(sha="b" * 40),
    ],
)
def test_targeted_remote_cleanup_rejects_open_merged_forked_or_drifted_pr(
    tmp_path, monkeypatch, payload
) -> None:
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, candidate.repository, FETCH_URL, PUSH_URL
    )
    monkeypatch.setattr(git_hygiene, "_github_get", lambda *_: payload)
    with pytest.raises(RuntimeError):
        git_hygiene._read_candidate_pr(identity, candidate, cwd=tmp_path)


# Regression for https://github.com/RasmusTho/agentic-pkm-mvp/pull/5172#discussion_r3886294181
@pytest.mark.parametrize(
    "candidate",
    [
        _targeted_candidate(governing_issue=9999),
        _targeted_candidate(governing_issue=None, no_issue_lane="governance"),
    ],
)
def test_targeted_remote_cleanup_authenticates_live_pr_governing_issue(
    tmp_path, monkeypatch, candidate
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, candidate["repository"], FETCH_URL, PUSH_URL
    )
    monkeypatch.setattr(
        git_hygiene,
        "_github_get",
        lambda *_: _closed_pull_payload(body="Governing-Issue: #5170\n\nFixes #5170\n"),
    )

    with pytest.raises(RuntimeError, match="candidate_pr_contract_mismatch"):
        git_hygiene._read_candidate_pr(
            identity, git_hygiene.Candidate(**candidate), cwd=tmp_path
        )


def test_targeted_remote_cleanup_authenticates_canonical_issue_free_lane(
    tmp_path, monkeypatch
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, "RasmusTho/agentic-pkm-mvp", FETCH_URL, PUSH_URL
    )
    body = (
        "## Change Lane\n"
        "- [ ] Docs authoring lane\n"
        "- [x] Governance lane\n\n"
        "Final-Review-Rounds: 0\n"
    )
    monkeypatch.setattr(
        git_hygiene, "_github_get", lambda *_: _closed_pull_payload(body=body)
    )
    candidate = git_hygiene.Candidate(
        **_targeted_candidate(governing_issue=None, no_issue_lane="governance")
    )

    contract = git_hygiene._read_candidate_pr(identity, candidate, cwd=tmp_path)

    assert contract.governing_issue is None
    assert contract.no_issue_lane == "governance"
    assert contract.pr_body_sha256 == git_hygiene._sha256_pr_body(body)


def test_targeted_remote_cleanup_rejects_issue_free_lane_mismatch(
    tmp_path, monkeypatch
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, "RasmusTho/agentic-pkm-mvp", FETCH_URL, PUSH_URL
    )
    body = (
        "## Change Lane\n"
        "- [ ] Docs authoring lane\n"
        "- [x] Governance lane\n\n"
        "Final-Review-Rounds: 0\n"
    )
    monkeypatch.setattr(
        git_hygiene, "_github_get", lambda *_: _closed_pull_payload(body=body)
    )
    candidate = git_hygiene.Candidate(
        **_targeted_candidate(governing_issue=None, no_issue_lane="docs-authoring")
    )

    with pytest.raises(RuntimeError, match="candidate_pr_contract_mismatch"):
        git_hygiene._read_candidate_pr(identity, candidate, cwd=tmp_path)


@pytest.mark.parametrize(
    ("body", "candidate"),
    [
        (
            "Governing-Issue: #5170\nGoverning-Issue: #5170\nFixes #5170\n",
            _targeted_candidate(),
        ),
        ("Governing-Issue: #5170\n", _targeted_candidate()),
        (
            "## Change Lane\n"
            "- [x] Docs authoring lane\n"
            "- [x] Governance lane\n\n"
            "Final-Review-Rounds: 0\n",
            _targeted_candidate(governing_issue=None, no_issue_lane="governance"),
        ),
    ],
)
def test_targeted_remote_cleanup_rejects_malformed_or_ambiguous_pr_contract(
    tmp_path, monkeypatch, body, candidate
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, candidate["repository"], FETCH_URL, PUSH_URL
    )
    monkeypatch.setattr(
        git_hygiene, "_github_get", lambda *_: _closed_pull_payload(body=body)
    )

    with pytest.raises(RuntimeError, match="candidate_pr_contract_mismatch"):
        git_hygiene._read_candidate_pr(
            identity, git_hygiene.Candidate(**candidate), cwd=tmp_path
        )


def test_targeted_remote_cleanup_treats_4728_as_protected_non_pull_issue(
    tmp_path, monkeypatch
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, "RasmusTho/agentic-pkm-mvp", FETCH_URL, PUSH_URL
    )
    issue = {
        "number": 4728,
        "state": "closed",
        "repository_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp",
    }
    responses = {
        "repos/RasmusTho/agentic-pkm-mvp/issues/4728": issue,
        "repos/RasmusTho/agentic-pkm-mvp/pulls/4813": _closed_pull_payload(
            number=4813, ref="codex/protected-4813", sha="d" * 40
        ),
    }
    monkeypatch.setattr(git_hygiene, "_github_get", lambda _cwd, endpoint: responses[endpoint])
    protected = git_hygiene._read_protected_targets(identity, cwd=tmp_path)
    assert protected.issue_number == 4728
    candidate = git_hygiene.Candidate(**_targeted_candidate(governing_issue=4728))
    with pytest.raises(RuntimeError, match="protected_number"):
        git_hygiene._validate_protected_candidate(candidate, protected)


def test_targeted_remote_cleanup_fails_when_4728_kind_or_lookup_is_ambiguous(
    tmp_path, monkeypatch
) -> None:
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, "RasmusTho/agentic-pkm-mvp", FETCH_URL, PUSH_URL
    )
    issue = {
        "number": 4728,
        "state": "closed",
        "repository_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp",
        "pull_request": {},
    }
    monkeypatch.setattr(git_hygiene, "_github_get", lambda *_: issue)
    with pytest.raises(RuntimeError, match="4728"):
        git_hygiene._read_protected_targets(identity, cwd=tmp_path)


@pytest.mark.parametrize("field", ["pull_request", "source_ref", "source_sha"])
def test_targeted_remote_cleanup_protects_4813_number_ref_and_sha(field) -> None:
    protected = git_hygiene.ProtectedAuthority(
        4728, 4813, "refs/heads/codex/protected-4813", "d" * 40
    )
    overrides = {
        "pull_request": 4813,
        "source_ref": protected.pull_ref,
        "source_sha": protected.pull_sha,
    }
    candidate_data = _targeted_candidate(**{field: overrides[field]})
    if field in {"source_ref", "source_sha"}:
        candidate_data["archive_ref"] = git_hygiene._archive_ref(
            REPOSITORY_ID, candidate_data["source_ref"], candidate_data["source_sha"]
        )
    with pytest.raises(RuntimeError):
        git_hygiene._validate_protected_candidate(
            git_hygiene.Candidate(**candidate_data), protected
        )


def _repository_payload():
    return {"id": REPOSITORY_ID, "full_name": "RasmusTho/agentic-pkm-mvp"}


def test_targeted_remote_cleanup_rejects_alternate_push_repository(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(git_hygiene, "_github_get", lambda *_: _repository_payload())

    def git_result(args, _cwd):
        value = FETCH_URL if "--push" not in args else "git@github.com:other/repo.git"
        return subprocess.CompletedProcess(args, 0, value + "\n", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", git_result)
    with pytest.raises(RuntimeError, match="origin_repository_mismatch"):
        git_hygiene._resolve_repository_identity(tmp_path, "RasmusTho/agentic-pkm-mvp")


def test_targeted_remote_cleanup_allows_fetch_https_push_ssh_for_same_repo(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(git_hygiene, "_github_get", lambda *_: _repository_payload())

    def git_result(args, _cwd):
        value = FETCH_URL if "--push" not in args else PUSH_URL
        return subprocess.CompletedProcess(args, 0, value + "\n", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", git_result)
    identity = git_hygiene._resolve_repository_identity(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    assert identity.fetch_url == FETCH_URL
    assert identity.push_url == PUSH_URL


def test_targeted_remote_cleanup_rereads_lifecycle_before_archive(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    reads = 0

    def lifecycle(_cwd, _candidate):
        nonlocal reads
        reads += 1
        return {} if reads == 1 else {"conflict": {}}

    monkeypatch.setattr(git_hygiene, "_read_lifecycle_authority", lifecycle)
    monkeypatch.setattr(git_hygiene, "_lifecycle_conflicts", lambda _c, _v, records: set(records))
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["error"] == "candidate_lifecycle_conflict"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_rereads_lifecycle_before_delete(tmp_path, monkeypatch) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    reads = 0

    def lifecycle(_cwd, _candidate):
        nonlocal reads
        reads += 1
        return {} if reads < 3 else {"conflict": {}}

    monkeypatch.setattr(git_hygiene, "_read_lifecycle_authority", lifecycle)
    monkeypatch.setattr(git_hygiene, "_lifecycle_conflicts", lambda _c, _v, records: set(records))
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["error"] == "candidate_lifecycle_conflict"
    assert candidate["source_ref"] in refs
    assert refs[candidate["archive_ref"]] == candidate["source_sha"]


def test_targeted_remote_cleanup_rereads_dispatcher_leases_at_both_boundaries(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    reads = 0

    def dispatcher(*_args):
        nonlocal reads
        reads += 1
        return []

    monkeypatch.setattr(git_hygiene, "_read_dispatcher_authority", dispatcher)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["ok"] is True
    assert reads == 3


def test_targeted_remote_cleanup_pr_contract_drift_before_delete_preserves_source(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    original = _authenticated_contract(git_hygiene.Candidate(**candidate))
    changed = git_hygiene.PullContractIdentity(
        governing_issue=original.governing_issue,
        no_issue_lane=original.no_issue_lane,
        pr_body_sha256="f" * 64,
    )
    reads = 0

    def read_pr(_identity, _candidate, **_kwargs):
        nonlocal reads
        reads += 1
        return changed if reads >= 4 else original

    monkeypatch.setattr(git_hygiene, "_read_candidate_pr", read_pr)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )

    assert report["error"] == "candidate_pr_contract_changed"
    assert refs[candidate["source_ref"]] == candidate["source_sha"]
    assert refs[candidate["archive_ref"]] == candidate["source_sha"]
    assert not any(
        command[-1] == f":{candidate['source_ref']}"
        for command in commands
        if command[0] == "push"
    )


def test_targeted_remote_cleanup_new_lease_after_archive_preserves_source(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    reads = 0

    def dispatcher(*_args):
        nonlocal reads
        reads += 1
        return [] if reads < 3 else [{"conflict": True}]

    monkeypatch.setattr(git_hygiene, "_read_dispatcher_authority", dispatcher)
    monkeypatch.setattr(
        git_hygiene,
        "_dispatcher_conflicts",
        lambda _c, _l, value, **_kwargs: set() if not value else {"lease"},
    )
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["error"] == "candidate_dispatcher_conflict"
    assert candidate["source_ref"] in refs
    assert candidate["archive_ref"] in refs


def test_targeted_remote_cleanup_uses_git_common_dir_store_across_worktrees(tmp_path) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "other", str(worktree)], check=True, capture_output=True)
    assert git_hygiene._git_common_dir(repo) == git_hygiene._git_common_dir(worktree)


def test_targeted_remote_cleanup_sanitizes_explicit_cwd_repository_context(
    tmp_path, monkeypatch
) -> None:
    from scripts import agent_worktree

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    for repo, remote in (
        (repo_a, "https://github.com/Owner/repo-a.git"),
        (repo_b, "https://github.com/Owner/repo-b.git"),
    ):
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", remote], check=True
        )
    registry_a = repo_a / ".git" / "agent-worktrees.json"
    registry_a.write_text(
        json.dumps({"schema": agent_worktree.REGISTRY_SCHEMA, "worktrees": {}}),
        encoding="utf-8",
    )
    (repo_b / ".git" / "agent-worktrees.json").write_text(
        "not-json", encoding="utf-8"
    )

    monkeypatch.setenv("GIT_DIR", str(repo_b / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(repo_b))
    monkeypatch.setenv("GIT_COMMON_DIR", str(repo_b / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(repo_b / ".git" / "index"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "test.marker")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "preserved")
    monkeypatch.setattr(
        git_hygiene,
        "_github_get",
        lambda _cwd, _endpoint: {"id": 101, "full_name": "Owner/repo-a"},
    )

    sanitized = git_hygiene._sanitized_git_environment()
    assert "GIT_DIR" not in sanitized
    assert "GIT_WORK_TREE" not in sanitized
    assert "GIT_COMMON_DIR" not in sanitized
    assert "GIT_INDEX_FILE" not in sanitized
    assert sanitized["GIT_CONFIG_COUNT"] == "1"
    assert git_hygiene.run_git(["config", "--get", "test.marker"], repo_a) == "preserved"

    identity = git_hygiene._resolve_repository_identity(repo_a, "Owner/repo-a")
    assert identity.fetch_url == "https://github.com/Owner/repo-a.git"
    assert identity.push_url == "https://github.com/Owner/repo-a.git"
    assert git_hygiene._git_common_dir(repo_a) == (repo_a / ".git").resolve()
    assert agent_worktree._default_registry_path(repo_a) == registry_a.resolve()
    assert agent_worktree.load_lifecycle_authority(
        repo_a, candidate_branch="codex/no-such-branch"
    ) == {}
    assert git_hygiene._canonical_dispatcher_db_path(repo_a) == (
        repo_a / "runtime" / "dispatcher" / "dispatcher.sqlite3"
    ).resolve()


def test_targeted_remote_cleanup_resource_key_rejects_disposition_rebinding(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    assert git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )["ok"] is True
    rebound = _targeted_candidate(owner="different-owner")
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=rebound["repository"], candidates=[rebound]
    )
    assert report["error"] == "receipt_identity_or_state_conflict"


def _start_lock_holder(lock_path: Path, ready_path: Path) -> subprocess.Popen:
    code = (
        "import pathlib,time; from scripts.git_hygiene import _resource_flock; "
        f"lock=pathlib.Path({str(lock_path)!r}); ready=pathlib.Path({str(ready_path)!r}); "
        "\nwith _resource_flock(lock):\n ready.write_text('ready')\n time.sleep(30)\n"
    )
    return subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).parents[2])


def _wait_ready(path: Path) -> None:
    deadline = time.time() + 5
    while time.time() < deadline and not path.exists():
        time.sleep(0.02)
    assert path.exists()


def test_targeted_remote_cleanup_flock_serializes_processes(tmp_path) -> None:
    lock = tmp_path / "resource.lock"
    ready = tmp_path / "ready"
    process = _start_lock_holder(lock, ready)
    try:
        _wait_ready(ready)
        with pytest.raises(RuntimeError, match="busy"):
            with git_hygiene._resource_flock(lock):
                pass
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_targeted_remote_cleanup_sigkill_releases_flock(tmp_path) -> None:
    lock = tmp_path / "resource.lock"
    ready = tmp_path / "ready"
    process = _start_lock_holder(lock, ready)
    _wait_ready(ready)
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    with git_hygiene._resource_flock(lock):
        pass
    assert lock.exists()


def test_targeted_remote_cleanup_without_prepared_receipt_cannot_adopt_absence(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["archive_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["error"] == "source_absent_without_prepared_receipt"


def test_targeted_remote_cleanup_prepared_absence_recovers_to_completed(
    tmp_path, monkeypatch
) -> None:
    candidate_data = _targeted_candidate()
    refs = {candidate_data["archive_ref"]: candidate_data["source_sha"]}
    commands: list[list[str]] = []
    identity = _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    candidate = git_hygiene.Candidate(**candidate_data)
    expected = git_hygiene._candidate_identity(
        identity, candidate, _authenticated_contract(candidate)
    )
    key = git_hygiene._receipt_resource_key(REPOSITORY_ID, candidate.source_ref)
    paths = git_hygiene._receipt_paths(tmp_path / "common", key)
    git_hygiene._replace_receipt(
        paths.receipt,
        git_hygiene.Receipt(git_hygiene.RECEIPT_SCHEMA, key, "prepared", expected),
    )
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate.repository, candidates=[candidate_data]
    )
    assert report["ok"] is True
    assert json.loads(paths.receipt.read_text())["state"] == "completed"


def test_targeted_remote_cleanup_atomic_transition_orders_fsync_replace_dirsync(
    tmp_path, monkeypatch
) -> None:
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    identity = git_hygiene.RepositoryIdentity(REPOSITORY_ID, candidate.repository, FETCH_URL, PUSH_URL)
    expected = git_hygiene._candidate_identity(
        identity, candidate, _authenticated_contract(candidate)
    )
    key = git_hygiene._receipt_resource_key(REPOSITORY_ID, candidate.source_ref)
    paths = git_hygiene._receipt_paths(tmp_path, key)
    events = []
    monkeypatch.setattr(git_hygiene, "_crash_hook", events.append)
    git_hygiene._replace_receipt(
        paths.receipt,
        git_hygiene.Receipt(git_hygiene.RECEIPT_SCHEMA, key, "prepared", expected),
    )
    assert events == [
        "before_prepared_temp_fsync",
        "after_prepared_temp_fsync",
        "before_prepared_replace",
        "after_prepared_replace",
        "before_prepared_dir_fsync",
        "after_prepared_dir_fsync",
    ]


def test_targeted_remote_cleanup_receipt_schema_is_exact_and_monotonic(tmp_path) -> None:
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    repository = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, candidate.repository, FETCH_URL, PUSH_URL
    )
    identity = git_hygiene._candidate_identity(
        repository, candidate, _authenticated_contract(candidate)
    )
    key = git_hygiene._receipt_resource_key(REPOSITORY_ID, candidate.source_ref)
    paths = git_hygiene._receipt_paths(tmp_path, key)
    prepared = git_hygiene.Receipt(
        git_hygiene.RECEIPT_SCHEMA, key, "prepared", identity
    )
    git_hygiene._replace_receipt(paths.receipt, prepared)
    payload = json.loads(paths.receipt.read_text(encoding="utf-8"))

    payload["extra"] = True
    paths.receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="schema"):
        git_hygiene._read_receipt(paths.receipt, expected=identity)
    payload.pop("extra")

    payload["identity_digest"] = "0" * 64
    paths.receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity"):
        git_hygiene._read_receipt(paths.receipt, expected=identity)
    payload["identity_digest"] = git_hygiene._identity_digest(identity)

    duplicate = json.dumps(payload)[:-1] + ',"state":"prepared"}'
    paths.receipt.write_text(duplicate, encoding="utf-8")
    with pytest.raises(RuntimeError, match="json"):
        git_hygiene._read_receipt(paths.receipt, expected=identity)

    paths.receipt.unlink()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    paths.receipt.symlink_to(target)
    with pytest.raises(RuntimeError, match="path"):
        git_hygiene._read_receipt(paths.receipt, expected=identity)
    paths.receipt.unlink()

    completed = git_hygiene.Receipt(
        git_hygiene.RECEIPT_SCHEMA, key, "completed", identity
    )
    git_hygiene._replace_receipt(paths.receipt, completed)
    with pytest.raises(RuntimeError, match="regression"):
        git_hygiene._replace_receipt(paths.receipt, prepared)


def test_targeted_remote_cleanup_reads_real_dispatcher_task_and_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord, TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    expires = "2099-01-01T00:00:00+00:00"
    lease = LeaseRecord(
        lease_id="lease-1",
        resource="issue:5170",
        holder="other-agent",
        ttl_seconds=60,
        acquired_at="2026-08-29T00:00:00+00:00",
        expires_at=expires,
    )
    store.upsert_lease(lease)
    store.upsert_task(
        TaskRecord(
            task_id="task-1",
            issue_number=5170,
            title="candidate",
            status="claimed",
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            claimed_by="other-agent",
            lease_id=lease.lease_id,
            lease_expires_at=expires,
            linked_pr="6000",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "live_dispatcher_claim"
    }


def test_targeted_remote_cleanup_dispatcher_missing_db_fails_closed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        git_hygiene,
        "_canonical_dispatcher_db_path",
        lambda _cwd: tmp_path / "missing.sqlite3",
    )
    with pytest.raises(RuntimeError, match="missing"):
        git_hygiene._read_dispatcher_authority(
            tmp_path, "RasmusTho/agentic-pkm-mvp"
        )


def test_targeted_remote_cleanup_ignores_dispatcher_env_database_bypass(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord
    from app.dispatcher.store import SqliteStore

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    canonical = repo / "runtime" / "dispatcher" / "dispatcher.sqlite3"
    canonical_store = SqliteStore(canonical)
    canonical_store.initialize()
    canonical_store.upsert_lease(
        LeaseRecord(
            lease_id="canonical-live",
            resource="branch:closed-unmerged",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )
    alternate = tmp_path / "alternate-empty.sqlite3"
    SqliteStore(alternate).initialize()
    monkeypatch.setenv("DISPATCHER_DB_PATH", str(alternate))

    assert git_hygiene._canonical_dispatcher_db_path(repo) == canonical.resolve()
    snapshot = git_hygiene._read_dispatcher_authority(
        repo, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "live_dispatcher_claim"
    }


def test_targeted_remote_cleanup_detects_orphan_live_branch_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_lease(
        LeaseRecord(
            lease_id="orphan-live",
            resource="branch:closed-unmerged",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "live_dispatcher_claim"
    }


def test_targeted_remote_cleanup_detects_orphan_live_issue_lease_only_when_relevant(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_lease(
        LeaseRecord(
            lease_id="unrelated-issue",
            resource="issue:9999",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()

    store.upsert_lease(
        LeaseRecord(
            lease_id="candidate-issue",
            resource="issue:5170",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "live_dispatcher_claim"
    }


# Regression for https://github.com/RasmusTho/agentic-pkm-mvp/pull/5172#discussion_r3886294181
def test_targeted_remote_cleanup_cannot_omit_leased_live_pr_governing_issue(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_lease(
        LeaseRecord(
            lease_id="actual-governing-issue",
            resource="issue:5170",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )
    candidate = git_hygiene.Candidate(
        **_targeted_candidate(governing_issue=None, no_issue_lane="governance")
    )
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, candidate.repository, FETCH_URL, PUSH_URL
    )
    monkeypatch.setattr(
        git_hygiene,
        "_github_get",
        lambda *_: _closed_pull_payload(body="Governing-Issue: #5170\n\nFixes #5170\n"),
    )

    with pytest.raises(RuntimeError, match="candidate_pr_contract_mismatch"):
        git_hygiene._read_candidate_pr(identity, candidate, cwd=tmp_path)

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    authenticated = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(authenticated, {}, snapshot) == {
        "live_dispatcher_claim"
    }


# Regression for https://github.com/RasmusTho/agentic-pkm-mvp/pull/5172#discussion_r3886294191
@pytest.mark.parametrize("status", ("backlog", "ready", "review", "blocked"))
def test_targeted_remote_cleanup_blocks_relevant_resumable_task_without_lease(
    tmp_path, monkeypatch, status
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id=f"candidate-{status}",
            issue_number=5170,
            title="candidate retained work",
            status=status,
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "nonterminal_dispatcher_task"
    }


@pytest.mark.parametrize("status", ("ready", "review", "claimed", "in_progress"))
def test_targeted_remote_cleanup_blocks_resumable_task_with_released_lease(
    tmp_path, monkeypatch, status
) -> None:
    from app.dispatcher.models import LeaseRecord, TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    expires = "2026-08-29T00:01:00+00:00"
    store.upsert_lease(
        LeaseRecord(
            lease_id=f"released-{status}",
            resource="issue:5170",
            holder="prior-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at=expires,
            released_at="2026-08-29T00:00:30+00:00",
            release_reason="review" if status == "review" else "manual",
        )
    )
    store.upsert_task(
        TaskRecord(
            task_id=f"candidate-released-{status}",
            issue_number=5170,
            title="candidate retained work",
            status=status,
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:30+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            claimed_by=None,
            lease_id=f"released-{status}",
            lease_expires_at=expires,
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "nonterminal_dispatcher_task"
    }


def test_targeted_remote_cleanup_blocks_review_task_with_expired_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord, TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    expires = "2020-01-01T00:01:00+00:00"
    store.upsert_lease(
        LeaseRecord(
            lease_id="expired-review",
            resource="issue:5170",
            holder="prior-agent",
            ttl_seconds=60,
            acquired_at="2020-01-01T00:00:00+00:00",
            expires_at=expires,
        )
    )
    store.upsert_task(
        TaskRecord(
            task_id="candidate-expired-review",
            issue_number=5170,
            title="candidate retained review",
            status="review",
            priority="high",
            source_anchor_refs=[],
            created_at="2020-01-01T00:00:00+00:00",
            updated_at="2020-01-01T00:01:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            lease_id="expired-review",
            lease_expires_at=expires,
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == {
        "nonterminal_dispatcher_task"
    }


def test_targeted_remote_cleanup_allows_canonical_completed_without_live_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="candidate-terminal-completed",
            issue_number=5170,
            title="candidate terminal work",
            status="completed",
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:30+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            lease_expires_at="2026-08-29T00:01:00+00:00",
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()


def test_targeted_remote_cleanup_accepts_real_claim_then_complete_transition(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.leases import claim
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.queue import complete
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="github-issue-5170",
            issue_number=5170,
            title="candidate producer transition",
            status="ready",
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            linked_pr="6000",
        )
    )

    claimed, lease = claim(store, "github-issue-5170", "producer-agent")
    assert claimed.status == "claimed"
    completed = complete(store, "github-issue-5170", "producer-agent")
    assert completed.status == "completed"
    assert completed.lease_id is None
    assert completed.lease_expires_at == lease.expires_at

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()


@pytest.mark.parametrize(
    "status", ("done", "delivered", "cancelled", "superseded", "released", "unknown")
)
def test_targeted_remote_cleanup_rejects_unknown_relevant_task_state(
    tmp_path, monkeypatch, status
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id=f"candidate-invalid-{status}",
            issue_number=5170,
            title="ambiguous candidate history",
            status=status,
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:30+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    with pytest.raises(RuntimeError, match="dispatcher_task_status_ambiguous"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_rejects_referenced_released_wrong_issue_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord, TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    expires = "2026-08-29T00:01:00+00:00"
    store.upsert_lease(
        LeaseRecord(
            lease_id="released-wrong-issue",
            resource="issue:9999",
            holder="prior-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at=expires,
            released_at="2026-08-29T00:00:30+00:00",
            release_reason="completed",
        )
    )
    store.upsert_task(
        TaskRecord(
            task_id="candidate-wrong-issue-lease",
            issue_number=5170,
            title="candidate terminal work",
            status="completed",
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-29T00:00:00+00:00",
            updated_at="2026-08-29T00:00:30+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            lease_id="released-wrong-issue",
            lease_expires_at=expires,
            linked_pr="6000",
        )
    )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    with pytest.raises(RuntimeError, match="dispatcher_task_lease_resource_mismatch"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_scopes_dispatcher_disagreement_to_candidate(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="unrelated-expired-history",
            issue_number=9999,
            title="unrelated",
            status="claimed",
            priority="low",
            source_anchor_refs=[],
            created_at="2026-08-01T00:00:00+00:00",
            updated_at="2026-08-01T00:00:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            claimed_by="old-agent",
            lease_id="missing-expired-lease",
            lease_expires_at="2026-08-01T00:01:00+00:00",
            linked_pr="9998",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()

    store.upsert_task(
        TaskRecord(
            task_id="relevant-expired-history",
            issue_number=5170,
            title="relevant",
            status="claimed",
            priority="high",
            source_anchor_refs=[],
            created_at="2026-08-01T00:00:00+00:00",
            updated_at="2026-08-01T00:00:00+00:00",
            repo="RasmusTho/agentic-pkm-mvp",
            claimed_by="old-agent",
            lease_id="missing-relevant-lease",
            lease_expires_at="2026-08-01T00:01:00+00:00",
            linked_pr="6000",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    with pytest.raises(RuntimeError, match="referenced_lease_missing"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_rejects_live_ambiguous_orphan_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_lease(
        LeaseRecord(
            lease_id="ambiguous-live",
            resource="",
            holder="other-agent",
            ttl_seconds=60,
            acquired_at="2026-08-29T00:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    with pytest.raises(RuntimeError, match="lease_identity_ambiguous"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_ignores_current_store_shaped_blank_repo_history(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="_sync_meta_github",
            issue_number=0,
            title="GitHub sync metadata",
            status="_meta",
            priority="low",
            source_anchor_refs=[],
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-11T00:00:00+00:00",
            repo="",
        )
    )
    for offset in range(35):
        issue = 3000 + offset
        store.upsert_task(
            TaskRecord(
                task_id=f"github-issue-{issue}",
                issue_number=issue,
                title=f"Legacy issue {issue}",
                status="blocked" if offset >= 33 else "completed",
                priority="low",
                source_anchor_refs=[f"github:issue:{issue}"],
                created_at="2026-07-01T00:00:00+00:00",
                updated_at="2026-07-11T00:00:00+00:00",
                repo="",
                blocked_reason="legacy no-repo row" if offset >= 33 else None,
            )
        )

    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    assert sum(item["kind"] == "task" for item in snapshot) == 36
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()


def test_targeted_remote_cleanup_ignores_blank_repo_unrelated_branch_history(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="github-issue-4000",
            issue_number=4000,
            title="unrelated branch history",
            status="completed",
            priority="low",
            source_anchor_refs=["branch:unrelated-closed-branch"],
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-11T00:00:00+00:00",
            repo="",
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    assert git_hygiene._dispatcher_conflicts(candidate, {}, snapshot) == set()


@pytest.mark.parametrize(
    ("issue", "status", "linked_pr", "anchors", "repository"),
    [
        (5170, "completed", None, ["github:issue:5170"], ""),
        (4000, "completed", "6000", ["github:issue:4000"], ""),
        (4000, "completed", None, ["branch:closed-unmerged"], ""),
        (4000, "claimed", None, ["github:issue:4000"], ""),
        (4000, "completed", None, ["github:issue:4000"], " "),
    ],
)
def test_targeted_remote_cleanup_rejects_adversarial_blank_repo_history(
    tmp_path, monkeypatch, issue, status, linked_pr, anchors, repository
) -> None:
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id=f"github-issue-{issue}",
            issue_number=issue,
            title="adversarial legacy row",
            status=status,
            priority="high",
            source_anchor_refs=anchors,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-11T00:00:00+00:00",
            repo=repository,
            linked_pr=linked_pr,
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    with pytest.raises(RuntimeError, match="task_identity_ambiguous"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_rejects_blank_repo_unreleased_lease(
    tmp_path, monkeypatch
) -> None:
    from app.dispatcher.models import LeaseRecord, TaskRecord
    from app.dispatcher.store import SqliteStore

    database = tmp_path / "dispatcher.sqlite3"
    monkeypatch.setattr(
        git_hygiene, "_canonical_dispatcher_db_path", lambda _cwd: database
    )
    store = SqliteStore(database)
    store.initialize()
    expires = "2026-08-01T00:01:00+00:00"
    store.upsert_lease(
        LeaseRecord(
            lease_id="expired-but-unreleased",
            resource="issue:4000",
            holder="old-agent",
            ttl_seconds=60,
            acquired_at="2026-08-01T00:00:00+00:00",
            expires_at=expires,
        )
    )
    store.upsert_task(
        TaskRecord(
            task_id="github-issue-4000",
            issue_number=4000,
            title="legacy unreleased row",
            status="completed",
            priority="low",
            source_anchor_refs=["github:issue:4000"],
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-11T00:00:00+00:00",
            repo="",
            lease_id="expired-but-unreleased",
            lease_expires_at=expires,
        )
    )
    snapshot = git_hygiene._read_dispatcher_authority(
        tmp_path, "RasmusTho/agentic-pkm-mvp"
    )
    candidate = git_hygiene.Candidate(**_targeted_candidate())
    with pytest.raises(RuntimeError, match="task_identity_ambiguous"):
        git_hygiene._dispatcher_conflicts(candidate, {}, snapshot)


def test_targeted_remote_cleanup_archive_create_is_expected_absence_cas(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    assert git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )["ok"] is True
    archive_push = next(command for command in commands if command[0] == "push" and ":refs/archive/" in command[-1])
    assert f"--force-with-lease={candidate['archive_ref']}:" in archive_push
    assert PUSH_URL in archive_push


def test_targeted_remote_cleanup_source_delete_is_expected_old_sha_cas(
    tmp_path, monkeypatch
) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    assert git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )["ok"] is True
    delete = next(command for command in commands if command[-1] == f":{candidate['source_ref']}")
    assert f"--force-with-lease={candidate['source_ref']}:{candidate['source_sha']}" in delete
    assert PUSH_URL in delete


@pytest.mark.parametrize(
    "crash_point",
    [
        "before_archive_push",
        "after_archive_push",
        "before_archive_readback",
        "after_archive_readback",
        "before_prepared_temp_fsync",
        "after_prepared_temp_fsync",
        "before_prepared_replace",
        "after_prepared_replace",
        "before_prepared_dir_fsync",
        "after_prepared_dir_fsync",
        "before_source_cas_acceptance",
        "after_source_cas_acceptance",
        "before_post_delete_readback",
        "after_post_delete_readback",
        "before_completed_temp_fsync",
        "after_completed_temp_fsync",
        "before_completed_replace",
        "after_completed_replace",
        "before_completed_dir_fsync",
        "after_completed_dir_fsync",
    ],
)
def test_targeted_remote_cleanup_crash_matrix(tmp_path, monkeypatch, crash_point) -> None:
    candidate = _targeted_candidate()
    refs = {candidate["source_ref"]: candidate["source_sha"]}
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    fired = False

    def crash(point):
        nonlocal fired
        if point == crash_point and not fired:
            fired = True
            raise OSError(f"crash:{point}")

    monkeypatch.setattr(git_hygiene, "_crash_hook", crash)
    first = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert first["ok"] is False
    monkeypatch.setattr(git_hygiene, "_crash_hook", lambda _point: None)
    retry = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=candidate["repository"], candidates=[candidate]
    )
    assert retry["ok"] is True
    assert candidate["source_ref"] not in refs
    assert refs[candidate["archive_ref"]] == candidate["source_sha"]


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value.update({"authority": {}}), "candidate_schema_invalid"),
        (lambda value: value.update({"pull_request": True}), "candidate_pull_request_invalid"),
        (lambda value: value.update({"governing_issue": True}), "candidate_issue_identity_ambiguous"),
        (lambda value: value.update({"no_issue_lane": "governance"}), "candidate_issue_identity_ambiguous"),
        (
            lambda value: value.update(
                {"governing_issue": None, "no_issue_lane": "arbitrary"}
            ),
            "candidate_no_issue_lane_invalid",
        ),
        (
            lambda value: value.update({"no_issue_lane": "arbitrary"}),
            "candidate_no_issue_lane_invalid",
        ),
        (lambda value: value.update({"owner": "Bad Owner"}), "candidate_owner_invalid"),
        (lambda value: value.update({"successor": "issue:0"}), "candidate_successor_invalid"),
        (lambda value: value.update({"review_at": "2030-02-30T00:00:00Z"}), "candidate_review_at_invalid"),
        (lambda value: value.update({"discard": {"state": "retain", "receipt": None, "extra": True}}), "candidate_discard_invalid"),
        (lambda value: value.update({"source_ref": "refs/heads/main"}), "candidate_source_ref_protected"),
        (lambda value: value.update({"archive_ref": "refs/archive/git-hygiene/v1/" + "0" * 64}), "candidate_archive_ref_invalid"),
    ],
)
def test_targeted_remote_cleanup_semantic_validation(
    tmp_path, monkeypatch, mutate, error
) -> None:
    candidate = _targeted_candidate()
    mutate(candidate)
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, {}, commands)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository="RasmusTho/agentic-pkm-mvp", candidates=[candidate]
    )
    assert report["error"] == error
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_batch_conflict_prevents_all_git_writes(
    tmp_path, monkeypatch
) -> None:
    first = _targeted_candidate()
    second = _targeted_candidate(
        pull_request=6001, source_ref="refs/heads/later", source_sha="b" * 40
    )
    refs = {
        first["source_ref"]: first["source_sha"],
        second["source_ref"]: "c" * 40,
    }
    commands: list[list[str]] = []
    _install_remote_cleanup_authority(monkeypatch, tmp_path, refs, commands)
    report = git_hygiene.targeted_remote_cleanup(
        tmp_path, repository=first["repository"], candidates=[first, second]
    )
    assert report["error"] == "source_identity_drift"
    assert not any(command[0] == "push" for command in commands)


def test_targeted_remote_cleanup_real_bare_remote_cas(tmp_path, monkeypatch) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    redirect_remote = tmp_path / "redirect-remote.git"
    redirect_repo = tmp_path / "redirect-repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "a").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "origin", "HEAD:refs/heads/closed-unmerged"], check=True, capture_output=True)
    subprocess.run(
        ["git", "init", "--bare", str(redirect_remote)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "init", str(redirect_repo)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(redirect_repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(redirect_repo), "config", "user.name", "Test"],
        check=True,
    )
    (redirect_repo / "b").write_text("b", encoding="utf-8")
    subprocess.run(["git", "-C", str(redirect_repo), "add", "b"], check=True)
    subprocess.run(
        ["git", "-C", str(redirect_repo), "commit", "-m", "redirect"],
        check=True,
        capture_output=True,
    )
    redirect_sha = subprocess.run(
        ["git", "-C", str(redirect_repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(redirect_repo), "remote", "add", "origin", str(redirect_remote)],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(redirect_repo),
            "push",
            "origin",
            "HEAD:refs/heads/closed-unmerged",
        ],
        check=True,
        capture_output=True,
    )
    identity = git_hygiene.RepositoryIdentity(
        REPOSITORY_ID, "RasmusTho/agentic-pkm-mvp", str(remote), str(remote)
    )
    candidate = _targeted_candidate(source_sha=sha)
    candidate["archive_ref"] = git_hygiene._archive_ref(
        REPOSITORY_ID, candidate["source_ref"], sha
    )
    monkeypatch.setattr(git_hygiene, "_resolve_repository_identity", lambda *_: identity)
    monkeypatch.setattr(
        git_hygiene,
        "_read_protected_targets",
        lambda *_args, **_kwargs: git_hygiene.ProtectedAuthority(
            4728, 4813, "refs/heads/protected", "d" * 40
        ),
    )
    monkeypatch.setattr(
        git_hygiene,
        "_read_candidate_pr",
        lambda _identity, value, **_kwargs: _authenticated_contract(value),
    )
    monkeypatch.setattr(
        git_hygiene, "_read_lifecycle_authority", lambda _cwd, _candidate: {}
    )
    monkeypatch.setattr(git_hygiene, "_lifecycle_conflicts", lambda *_: set())
    monkeypatch.setattr(git_hygiene, "_read_dispatcher_authority", lambda *_: [])
    monkeypatch.setenv("GIT_DIR", str(redirect_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(redirect_repo))
    monkeypatch.setenv("GIT_COMMON_DIR", str(redirect_repo / ".git"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(redirect_repo / ".git" / "objects"))
    report = git_hygiene.targeted_remote_cleanup(
        repo, repository=candidate["repository"], candidates=[candidate]
    )
    assert report["ok"] is True
    assert git_hygiene._remote_ref_sha(repo, str(remote), candidate["source_ref"]) is None
    assert git_hygiene._remote_ref_sha(repo, str(remote), candidate["archive_ref"]) == sha
    assert (
        git_hygiene._remote_ref_sha(
            redirect_repo, str(redirect_remote), candidate["source_ref"]
        )
        == redirect_sha
    )
    assert (
        git_hygiene._remote_ref_sha(
            redirect_repo, str(redirect_remote), candidate["archive_ref"]
        )
        is None
    )
    assert (repo / ".git" / "git-hygiene" / "targeted-remote-cleanup").is_dir()
    assert not (
        redirect_repo / ".git" / "git-hygiene" / "targeted-remote-cleanup"
    ).exists()


def _allow_lifecycle_authority(_targets):
    return nullcontext(lambda: None)


def test_preflight_reports_dirty_tree_and_in_progress_operation(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "MERGE_HEAD").write_text("abc123\n", encoding="utf-8")

    def fake_run_git(args: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        if args == ["status", "--porcelain"]:
            return " M docs/development/GITHUB_GOVERNANCE_SETUP.md"
        if args == ["branch", "--show-current"]:
            return "feature/work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="main",
        expected_worktree=str(tmp_path / "other"),
    )

    assert report["ok"] is False
    assert report["checks"]["dirty_tree"] is True
    assert report["checks"]["in_progress_operations"] == ["merge"]
    assert report["checks"]["branch_mismatch"] is True
    assert report["checks"]["worktree_mismatch"] is True


def test_preflight_allow_dirty_tolerates_dirty_tree_but_not_drift(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return " M .codex/skills/publish-pr/SKILL.md"
        if args == ["branch", "--show-current"]:
            return "governance-work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    # At the publish boundary the tree is intentionally dirty; with --allow-dirty
    # that is not a failure as long as branch and worktree match.
    ok_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="governance-work",
        expected_worktree=str(tmp_path),
        allow_dirty=True,
    )
    assert ok_report["ok"] is True
    assert ok_report["checks"]["dirty_tree"] is True
    assert ok_report["checks"]["dirty_tree_enforced"] is False

    # Branch drift still fails even with --allow-dirty.
    drift_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="some-other-branch",
        expected_worktree=str(tmp_path),
        allow_dirty=True,
    )
    assert drift_report["ok"] is False
    assert drift_report["checks"]["branch_mismatch"] is True

    # Without --allow-dirty the dirty tree fails as before.
    strict_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="governance-work",
        expected_worktree=str(tmp_path),
    )
    assert strict_report["ok"] is False
    assert strict_report["checks"]["dirty_tree_enforced"] is True


def test_preflight_reports_active_lease_conflict(tmp_path, monkeypatch) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.preflight_report(
        tmp_path,
        active_leases=[
            {
                "resource_id": "issue:561",
                "execution_id": "other-agent",
                "expires_at": 2000,
            },
            {
                "resource_id": "lane:governance",
                "execution_id": "expired-agent",
                "expires_at": 1000,
            },
        ],
        resource_ids={"issue:561", "lane:governance"},
        execution_id="this-agent",
        now=1500,
    )

    assert report["ok"] is False
    assert report["checks"]["lease_conflicts"] == [
        {
            "resource_id": "issue:561",
            "execution_id": "other-agent",
            "expires_at": 2000,
        }
    ]


def _fake_base_branch_run_git(tmp_path, git_dir):
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "feature/work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        if args == ["rev-parse", "main"]:
            return "local-main-sha"
        if args == ["rev-parse", "origin/main"]:
            return "origin-main-sha"
        raise AssertionError(f"unexpected git command: {args}")

    return fake_run_git


def _fake_merge_base_run(ancestor_pairs: set[tuple[str, str]]):
    def fake_run(args, **kwargs):
        assert args[:3] == ["git", "merge-base", "--is-ancestor"]
        ancestor, descendant = args[3], args[4]
        return_code = 0 if (ancestor, descendant) in ancestor_pairs else 1

        class Result:
            returncode = return_code

        return Result()

    return fake_run


def test_preflight_fails_base_branch_behind_when_head_lacks_remote(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _fake_base_branch_run_git(tmp_path, git_dir))
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _fake_merge_base_run({("main", "origin/main")}),
    )

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    assert report["ok"] is False
    assert report["checks"]["base_branch"] == {
        "base_branch": "main",
        "remote_ref": "origin/main",
        "local_sha": "local-main-sha",
        "remote_sha": "origin-main-sha",
        "status": "behind",
        "reason": "rebase_required",
        "head_contains_remote": False,
        "mismatch": True,
    }


def test_preflight_accepts_stale_local_base_when_head_contains_remote(
    tmp_path, monkeypatch
) -> None:
    # Doctrinal worktree flow: the branch was cut from the current origin/main,
    # but the local main ref is checked out in the root worktree and cannot be
    # fast-forwarded from here. The stale local ref must not fail the gate.
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _fake_base_branch_run_git(tmp_path, git_dir))
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _fake_merge_base_run({("main", "origin/main"), ("origin/main", "HEAD")}),
    )

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    assert report["ok"] is True
    assert report["checks"]["base_branch"] == {
        "base_branch": "main",
        "remote_ref": "origin/main",
        "local_sha": "local-main-sha",
        "remote_sha": "origin-main-sha",
        "status": "behind",
        "reason": "advisory_stale_local_ref",
        "head_contains_remote": True,
        "mismatch": False,
    }


def test_preflight_accepts_diverged_local_base_when_head_contains_remote(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _fake_base_branch_run_git(tmp_path, git_dir))
    # A shared root worktree may leave its local main ref diverged. That is
    # advisory when this isolated publication branch contains origin/main.
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _fake_merge_base_run({("origin/main", "HEAD")}),
    )

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    assert report["ok"] is True
    assert report["checks"]["base_branch"] == {
        "base_branch": "main",
        "remote_ref": "origin/main",
        "local_sha": "local-main-sha",
        "remote_sha": "origin-main-sha",
        "status": "diverged",
        "reason": "advisory_diverged_local_base_ref",
        "head_contains_remote": True,
        "mismatch": False,
    }


def test_behind_head_missing_remote_reason_distinct_from_diverged(
    tmp_path, monkeypatch
) -> None:
    """A failing 'behind' (HEAD missing origin/main) must carry a rebase-oriented
    reason that is distinct from the 'diverged' status reason — so operators can tell
    them apart without reading mismatch."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _fake_base_branch_run_git(tmp_path, git_dir))
    # HEAD does NOT contain origin/main -> mismatch=True (blocking behind)
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _fake_merge_base_run({("main", "origin/main")}),
    )

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    base = report["checks"]["base_branch"]
    assert base["status"] == "behind"
    assert base["mismatch"] is True
    # The reason must be rebase-oriented and must not equal "diverged"
    assert "reason" in base
    assert base["reason"] == "rebase_required"
    assert base["reason"] != "diverged"


def test_advisory_behind_not_reported_as_failure(
    tmp_path, monkeypatch
) -> None:
    """A non-failing 'behind' (HEAD already contains origin/main) must surface an
    advisory reason, not a failure reason — operators should see it as a warning, not
    an error."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _fake_base_branch_run_git(tmp_path, git_dir))
    # HEAD contains origin/main -> mismatch=False (advisory behind)
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _fake_merge_base_run({("main", "origin/main"), ("origin/main", "HEAD")}),
    )

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    base = report["checks"]["base_branch"]
    assert base["status"] == "behind"
    assert base["mismatch"] is False
    assert report["ok"] is True  # gate must not fail
    # The reason must be advisory, not a failure reason
    assert "reason" in base
    assert base["reason"] == "advisory_stale_local_ref"


def test_janitor_report_respects_active_lease_and_reports_candidates(
    tmp_path, monkeypatch
) -> None:
    missing_worktree = tmp_path / "missing-worktree"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["branch", "--merged"]:
            return "\n".join(
                [
                    "* main",
                    "  delivered-safe",
                    "  active-lane",
                    "  develop",
                ]
            )
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\n"
                "HEAD abc123\n"
                "branch refs/heads/main\n\n"
                f"worktree {missing_worktree}\n"
                "HEAD abc123\n"
                "branch refs/heads/orphaned-worktree\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "delivered-safe", "active-lane", "develop"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return "\n".join(
                [
                    "stash@{0}: WIP on main 1000000000: old work",
                    "stash@{1}: WIP on main 1999999999: current work",
                ]
            )
        if args == ["worktree", "prune", "--dry-run"]:
            return f"Removing worktrees/{missing_worktree.name}: gitdir file points to non-existent location"
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return " * [would prune] origin/stale-remote"
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.janitor_report(
        tmp_path,
        active_leases=[
            {
                "resource_id": "branch:active-lane",
                "execution_id": "agent-1",
                "expires_at": 3000000000,
            }
        ],
        stale_after_days=1,
        now=2000000000,
    )

    assert report["mode"] == "report-only"
    assert report["destructive_actions"] == []
    assert report["stale_merged_branches"] == ["delivered-safe"]
    assert report["orphaned_worktrees"] == [
        {"path": str(missing_worktree), "branch": "orphaned-worktree"}
    ]
    assert report["old_stashes"] == []
    assert report["prune_candidates"]["worktree"]
    assert report["prune_candidates"]["remote"] == [
        " * [would prune] origin/stale-remote"
    ]
    assert report["active_leases_respected"] == ["branch:active-lane"]


def test_janitor_plan_preserves_open_and_draft_pr_branches(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "feature-open", "feature-draft", "feature-merged"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={
            "feature-open": {"state": "OPEN", "isDraft": False},
            "feature-draft": {"state": "OPEN", "isDraft": True},
            "feature-merged": {"state": "MERGED", "isDraft": False},
        },
    )

    assert report["candidates"]["local_branches"] == [{"branch": "feature-merged"}]
    assert {
        (item["name"], item["reason"])
        for item in report["skipped"]
        if item["artifact"] == "local_branch"
    } >= {
        ("feature-open", "open_or_draft_pr"),
        ("feature-draft", "open_or_draft_pr"),
    }


@pytest.mark.parametrize("status", ("active", "released", "complete"))
def test_janitor_plan_preserves_branch_for_missing_registered_checkout(
    tmp_path,
    monkeypatch,
    status,
) -> None:
    missing_worktree = tmp_path / "missing"
    record = {
        "path": str(missing_worktree),
        "branch": "codex/registered",
        "generation": GENERATION,
        "owner": "owner",
        "status": status,
        "registered_at": 10,
        "heartbeat_at": 20,
        "expires_at": 30,
    }
    if status in {"released", "complete"}:
        record[f"{status}_at"] = 30
    else:
        record["expires_at"] = 200

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD root\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\ncodex/registered\n"
        if args == [
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/remotes/origin",
        ]:
            return "origin/codex/registered\n"
        if args in (
            ["stash", "list", "--date=unix"],
            ["worktree", "prune", "--dry-run"],
            ["remote", "prune", "origin", "--dry-run"],
        ):
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"codex/registered": {"state": "MERGED"}},
        lifecycle_records={str(missing_worktree): record},
        now=100,
    )

    assert report["candidates"]["local_branches"] == []
    assert report["candidates"]["remote_branches"] == []
    assert {
        (item["artifact"], item["reason"])
        for item in report["skipped"]
        if item.get("name") == "codex/registered"
    } == {
        ("local_branch", "lifecycle_registration"),
        ("remote_branch", "lifecycle_registration"),
    }


def test_janitor_plan_deletes_only_merged_unchecked_local_branch(
    tmp_path, monkeypatch
) -> None:
    other_worktree = tmp_path / "other"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {other_worktree}\nHEAD def\nbranch refs/heads/checked-clean\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "stable", "checked-clean", "merged-safe", "not-merged"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    def fake_is_ancestor(_cwd: Path, ancestor: str, descendant: str) -> bool:
        return ancestor == "merged-safe" and descendant == "origin/main"

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", fake_is_ancestor)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={
            "checked-clean": {"state": "MERGED"},
            "merged-safe": {"state": "MERGED"},
            "not-merged": {"state": "MERGED"},
        },
    )

    assert report["candidates"]["local_branches"] == [{"branch": "merged-safe"}]
    reasons = {
        item["name"]: item["reason"]
        for item in report["skipped"]
        if item["artifact"] == "local_branch"
    }
    assert reasons["stable"] == "protected_branch"
    assert reasons["checked-clean"] == "checked_out_worktree"
    assert reasons["not-merged"] == "not_merged_to_origin_main"


def test_janitor_plan_skips_dirty_worktree(tmp_path, monkeypatch) -> None:
    dirty_worktree = tmp_path / "dirty"
    dirty_worktree.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {dirty_worktree}\nHEAD def\nbranch refs/heads/codex/dirty\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\ncodex/dirty"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"codex/dirty": {"state": "MERGED"}},
    )

    assert report["candidates"]["worktrees"] == []
    assert any(
        item["artifact"] == "worktree" and item["reason"] == "dirty_worktree"
        for item in report["skipped"]
    )
    assert report["preservation_receipts"] == [
        {
            "artifact": "worktree",
            "path": str(dirty_worktree),
            "branch": "codex/dirty",
            "reason": "dirty_worktree",
            "action": "preserve",
            "next_action": "preserve local drift; inspect or commit it before any cleanup",
        }
    ]


def test_janitor_plan_skips_locked_worktree(tmp_path, monkeypatch) -> None:
    locked_worktree = tmp_path / "locked"
    locked_worktree.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {locked_worktree}\nHEAD def\nbranch refs/heads/codex/locked\nlocked active Claude session\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\ncodex/locked"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args in (["stash", "list", "--date=unix"], ["worktree", "prune", "--dry-run"], ["remote", "prune", "origin", "--dry-run"]):
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path, pr_states={"codex/locked": {"state": "MERGED"}}
    )

    assert report["reclaimable_worktrees"] == []
    assert report["preservation_receipts"][0]["reason"] == "locked_worktree"
    assert report["preservation_receipts"][0]["action"] == "preserve"


def test_janitor_plan_preserves_locked_missing_worktree(tmp_path, monkeypatch) -> None:
    missing_locked_worktree = tmp_path / "missing-locked"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {missing_locked_worktree}\nHEAD def\nbranch refs/heads/codex/locked-missing\nlocked active Claude session\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\ncodex/locked-missing"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args in (["stash", "list", "--date=unix"], ["worktree", "prune", "--dry-run"], ["remote", "prune", "origin", "--dry-run"]):
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path, pr_states={"codex/locked-missing": {"state": "MERGED"}}
    )

    assert report["orphaned_worktrees"] == []
    assert report["reclaimable_worktrees"] == []
    assert report["preservation_receipts"] == [
        {
            "artifact": "worktree",
            "path": str(missing_locked_worktree),
            "branch": "codex/locked-missing",
            "reason": "locked_worktree",
            "action": "preserve",
            "next_action": "preserve the lock; verify the owning session before any cleanup",
        }
    ]


def test_janitor_plan_remote_merged_branch_is_delete_candidate(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/merged-remote"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"merged-remote": {"state": "MERGED"}},
    )

    assert report["candidates"]["remote_branches"] == [{"branch": "merged-remote"}]


def test_janitor_plan_closed_unmerged_remote_requires_rescue(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/closed-unmerged"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
        now=2000000000,
    )

    assert report["candidates"]["remote_branches_requiring_rescue"] == [
        {
            "branch": "closed-unmerged",
            "rescue_ref": "refs/archive/git-hygiene/20330518T033320Z/closed-unmerged",
        }
    ]


def test_janitor_plan_unknown_github_state_skips_branch(tmp_path, monkeypatch) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\nunknown"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/unknown"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(tmp_path, pr_states={})

    assert report["candidates"]["local_branches"] == []
    assert report["candidates"]["remote_branches"] == []
    assert {
        (item.get("artifact"), item.get("name"), item.get("reason"))
        for item in report["skipped"]
    } >= {
        ("local_branch", "unknown", "unknown_github_state"),
        ("remote_branch", "unknown", "unknown_github_state"),
    }


def test_janitor_apply_creates_rescue_before_remote_delete(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []
    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {
                        "branch": "closed-unmerged",
                        "rescue_ref": "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged",
                    }
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert report["errors"][-1]["reason"] == "targeted_remote_cleanup_required"
    assert not any(command[0] == "push" for command in commands)


@pytest.mark.parametrize(
    (
        "active_lease_loader",
        "lifecycle_records",
        "lifecycle_authority_guard",
        "reason",
    ),
    (
        (
            None,
            {},
            _allow_lifecycle_authority,
            "authoritative_lease_reload_required",
        ),
        (
            lambda: [],
            None,
            _allow_lifecycle_authority,
            "registered_lifecycle_guard_required",
        ),
        (
            lambda: [],
            {},
            None,
            "authoritative_lifecycle_revalidation_required",
        ),
    ),
)
def test_janitor_apply_requires_explicit_cleanup_authority(
    tmp_path,
    monkeypatch,
    active_lease_loader,
    lifecycle_records,
    lifecycle_authority_guard,
    reason,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: commands.append(args),
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=active_lease_loader,
        lifecycle_records=lifecycle_records,
        lifecycle_authority_guard=lifecycle_authority_guard,
        pr_states={},
    )

    assert report["ok"] is False
    assert report["destructive_actions"] == []
    assert report["errors"][0]["reason"] == reason
    assert commands == []


def test_janitor_apply_rereads_lease_authority_before_removal(
    tmp_path,
    monkeypatch,
) -> None:
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    commands: list[list[str]] = []
    lease_reads = 0

    def load_leases():
        nonlocal lease_reads
        lease_reads += 1
        if lease_reads == 1:
            return []
        return [
            {
                "resource_id": f"worktree:{worktree}",
                "execution_id": "new-claim",
                "expires_at": 3000000000,
            }
        ]

    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: (
            commands.append(args)
            or subprocess.CompletedProcess(["git", *args], 0, "", "")
        ),
    )
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": [
                {
                    "path": str(worktree),
                    "branch": "codex/candidate",
                    "merge_proof": "merged_pr",
                }
            ],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
            "preservation_receipts": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=load_leases,
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={
            str(worktree): {
                "path": str(worktree),
                "branch": "codex/candidate",
                "generation": GENERATION,
                "owner": "completed-owner",
                "status": "complete",
                "registered_at": 10,
                "heartbeat_at": 20,
                "complete_at": 30,
                "expires_at": 30,
            }
        },
        pr_states={"codex/candidate": {"state": "MERGED"}},
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lease_authority_changed"
    assert lease_reads >= 2
    assert commands == [["fetch", "--prune", "origin"]]


def test_janitor_apply_rereads_lease_authority_before_branch_delete(
    tmp_path,
    monkeypatch,
) -> None:
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    commands: list[list[str]] = []
    lease_reads = 0

    def load_leases():
        nonlocal lease_reads
        lease_reads += 1
        if lease_reads < 4:
            return []
        return [
            {
                "resource_id": "branch:codex/candidate",
                "execution_id": "new-claim",
                "expires_at": 3000000000,
            }
        ]

    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: (
            commands.append(args)
            or subprocess.CompletedProcess(["git", *args], 0, "", "")
        ),
    )
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": [
                {
                    "path": str(worktree),
                    "branch": "codex/candidate",
                    "merge_proof": "merged_pr",
                }
            ],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
            "preservation_receipts": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=load_leases,
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"codex/candidate": {"state": "MERGED"}},
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lease_authority_changed"
    assert ["worktree", "remove", str(worktree)] in commands
    assert ["branch", "-D", "codex/candidate"] not in commands


def test_janitor_apply_aborts_when_fetch_fails(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []
    plan_called = False

    def fake_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 1, "", "offline")

    def forbidden_plan(*_args, **_kwargs):
        nonlocal plan_called
        plan_called = True
        raise AssertionError("plan must not run after failed fetch")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_result)
    monkeypatch.setattr(git_hygiene, "build_janitor_plan", forbidden_plan)

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={},
    )

    assert report["ok"] is False
    assert plan_called is False
    assert commands == [["fetch", "--prune", "origin"]]


@pytest.mark.parametrize(
    "malformed_expiry",
    (True, float("nan"), float("inf"), float("-inf")),
)
def test_janitor_apply_rejects_malformed_lease_expiry(
    tmp_path,
    monkeypatch,
    malformed_expiry,
) -> None:
    commands: list[list[str]] = []
    plan_called = False

    def fake_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    def forbidden_plan(*_args, **_kwargs):
        nonlocal plan_called
        plan_called = True
        raise AssertionError("plan must not run with malformed lease authority")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_result)
    monkeypatch.setattr(git_hygiene, "build_janitor_plan", forbidden_plan)

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [
            {
                "resource_id": "worktree:/repo/worktrees/active",
                "execution_id": "active-owner",
                "expires_at": malformed_expiry,
            }
        ],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={},
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "active_lease_authority_invalid"
    assert plan_called is False
    assert commands == [["fetch", "--prune", "origin"]]


def test_janitor_rescue_publication_works_from_guarded_main_checkout(
    tmp_path, monkeypatch
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", remote], check=True)
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "closed-unmerged"], cwd=repo, check=True)
    (repo / "branch.txt").write_text("rescue me\n", encoding="utf-8")
    subprocess.run(["git", "add", "branch.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "branch"], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "closed-unmerged"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)

    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        "test \"$(git symbolic-ref --short HEAD)\" != main || {\n"
        "  echo 'direct-main push rejected' >&2\n"
        "  exit 1\n"
        "}\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    rescue_ref = "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged"
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {"branch": "closed-unmerged", "rescue_ref": rescue_ref}
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    guarded_main = subprocess.run(
        ["git", "push", "origin", "main:refs/heads/main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert guarded_main.returncode != 0
    assert "direct-main push rejected" in guarded_main.stderr

    report = git_hygiene.janitor_apply(
        repo,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert report["errors"][-1]["reason"] == "targeted_remote_cleanup_required"
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", rescue_ref],
        cwd=remote,
        check=False,
    ).returncode != 0
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/closed-unmerged"],
        cwd=remote,
        check=False,
    ).returncode == 0
    guarded_main_after_cleanup = subprocess.run(
        ["git", "push", "origin", "main:refs/heads/main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert guarded_main_after_cleanup.returncode != 0
    assert "direct-main push rejected" in guarded_main_after_cleanup.stderr


def test_janitor_apply_does_not_delete_remote_when_rescue_push_fails(
    tmp_path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    rescue_refspec = (
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged:"
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged"
    )

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ["push", "--no-verify", "origin", rescue_refspec]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "rejected")
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {
                        "branch": "closed-unmerged",
                        "rescue_ref": "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged",
                    }
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert ["push", "--no-verify", "origin", ":refs/heads/closed-unmerged"] not in commands


def test_janitor_apply_does_not_delete_remote_when_rescue_verification_fails(
    tmp_path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    rescue_ref = "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged"

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ["ls-remote", "--exit-code", "origin", rescue_ref]:
            return subprocess.CompletedProcess(["git", *args], 2, "", "not found")
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {"branch": "closed-unmerged", "rescue_ref": rescue_ref}
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert ["push", "--no-verify", "origin", ":refs/heads/closed-unmerged"] not in commands


def test_janitor_rescue_delete_uses_exact_full_ref_for_ref_like_branch(
    tmp_path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    branch = "refs/heads/main"
    rescue_ref = f"refs/archive/git-hygiene/20260607T000000Z/{branch}"

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {"branch": branch, "rescue_ref": rescue_ref}
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={branch: {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert report["errors"][-1]["reason"] == "targeted_remote_cleanup_required"
    assert not any(command[0] == "push" for command in commands)


@pytest.mark.parametrize("branch", ["--force", "main"])
def test_janitor_rescue_transport_rejects_unsafe_branch(
    tmp_path, monkeypatch, branch: str
) -> None:
    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {
                        "branch": branch,
                        "rescue_ref": f"refs/archive/git-hygiene/20260607T000000Z/{branch}",
                    }
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={branch: {"state": "CLOSED"}},
    )

    assert report["ok"] is False
    assert not any(command[0] == "push" for command in commands)


def test_janitor_dry_run_integration_with_temp_repo(tmp_path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "codex/merged-branch"], cwd=repo, check=True)
    (repo / "merged.txt").write_text("merged\n", encoding="utf-8")
    subprocess.run(["git", "add", "merged.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "merged"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "merge", "--no-ff", "codex/merged-branch", "-m", "merge"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "unmerged-branch"], cwd=repo, check=True)
    (repo / "unmerged.txt").write_text("unmerged\n", encoding="utf-8")
    subprocess.run(["git", "add", "unmerged.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "unmerged"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(repo)], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "main"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", str(tmp_path / "clean-wt"), "codex/merged-branch"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "codex/dirty"], cwd=repo, check=True)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    subprocess.run(["git", "add", "dirty.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "dirty base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    dirty_wt = tmp_path / "dirty-wt"
    subprocess.run(["git", "worktree", "add", str(dirty_wt), "codex/dirty"], cwd=repo, check=True)
    (dirty_wt / "dirty.txt").write_text("local dirty\n", encoding="utf-8")
    missing_wt = tmp_path / "missing-wt"
    subprocess.run(["git", "worktree", "add", str(missing_wt), "-b", "codex/missing", "main"], cwd=repo, check=True)
    subprocess.run(["rm", "-rf", str(missing_wt)], check=True)

    report = git_hygiene.build_janitor_plan(
        repo,
        pr_states={
            "codex/merged-branch": {"state": "MERGED"},
            "unmerged-branch": {"state": "CLOSED"},
            "codex/dirty": {"state": "MERGED"},
            "codex/missing": {"state": "MERGED"},
        },
    )

    candidate = next(
        item
        for item in report["candidates"]["worktrees"]
        if item["path"] == str(tmp_path / "clean-wt")
    )
    assert candidate["branch"] == "codex/merged-branch"
    assert candidate["head"]
    assert candidate["merge_proof"] == "ancestor_of_origin_main"
    # The same enriched candidate is surfaced under the canonical reclaim key.
    assert candidate in report["reclaimable_worktrees"]
    assert any(item["branch"] == "codex/missing" for item in report["candidates"]["orphaned_worktrees"])
    assert any(
        item["artifact"] == "worktree" and item["branch"] == "codex/dirty" and item["reason"] == "dirty_worktree"
        for item in report["skipped"]
    )


def _reclaim_run_git(tmp_path, worktrees_porcelain: str, local_refs: str):
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return worktrees_porcelain
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return local_refs
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    return fake_run_git


def test_report_emits_reclaimable_worktrees_distinct_from_orphaned(
    tmp_path, monkeypatch
) -> None:
    """AC1: --mode report surfaces reclaimable_worktrees (present-but-merged,
    clean, non-lease, non-root), distinct from orphaned_worktrees."""
    clean_wt = tmp_path / "clean-wt"
    clean_wt.mkdir()
    missing_wt = tmp_path / "missing-wt"

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {clean_wt}\nHEAD def\nbranch refs/heads/deliver/foo\n\n"
        f"worktree {missing_wt}\nHEAD ghi\nbranch refs/heads/codex/gone\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(tmp_path, porcelain, "main\ndeliver/foo\ncodex/gone"),
    )
    # deliver/foo is an ancestor of origin/main (fast-forward merge).
    monkeypatch.setattr(
        git_hygiene,
        "_is_ancestor",
        lambda _cwd, ancestor, descendant: ancestor == "deliver/foo"
        and descendant == "origin/main",
    )
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.janitor_report(tmp_path)

    assert "reclaimable_worktrees" in report
    assert "orphaned_worktrees" in report
    reclaim_paths = {item["path"] for item in report["reclaimable_worktrees"]}
    orphaned_paths = {item["path"] for item in report["orphaned_worktrees"]}
    # The present-but-merged worktree is reclaimable.
    assert str(clean_wt) in reclaim_paths
    # The missing worktree is orphaned, not reclaimable — the two lists are distinct.
    assert str(missing_wt) in orphaned_paths
    assert reclaim_paths.isdisjoint(orphaned_paths)
    foo = next(item for item in report["reclaimable_worktrees"] if item["path"] == str(clean_wt))
    assert foo["branch"] == "deliver/foo"
    assert foo["merge_proof"] == "ancestor_of_origin_main"


def test_reclaimable_gates_on_merge_state_not_codex_prefix_squash_via_pr(
    tmp_path, monkeypatch
) -> None:
    """AC2: candidacy gates on merge state, not codex/ prefix; squash-merged
    branches (not ancestors) are caught via MERGED/CLOSED PR state."""
    squash_wt = tmp_path / "deliver-squash"
    squash_wt.mkdir()
    docs_wt = tmp_path / "docs-merged"
    docs_wt.mkdir()

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {squash_wt}\nHEAD def\nbranch refs/heads/deliver/squashed\n\n"
        f"worktree {docs_wt}\nHEAD ghi\nbranch refs/heads/docs/note\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(
            tmp_path, porcelain, "main\ndeliver/squashed\ndocs/note"
        ),
    )
    # Neither branch is an ancestor of origin/main (squash merge rewrites history).
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: False)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={
            "deliver/squashed": {"state": "MERGED", "isDraft": False, "number": 11},
            "docs/note": {"state": "CLOSED", "isDraft": False, "number": 12},
        },
    )

    reclaim = {item["path"]: item for item in report["reclaimable_worktrees"]}
    # Non-codex branches that are not ancestors are still reclaimable via PR state.
    assert str(squash_wt) in reclaim
    assert reclaim[str(squash_wt)]["merge_proof"] == "merged_pr"
    assert str(docs_wt) in reclaim
    assert reclaim[str(docs_wt)]["merge_proof"] == "closed_pr"
    # No worktree was skipped for a branch-prefix reason.
    assert not any(
        item.get("artifact") == "worktree" and item.get("reason") == "non_codex_branch"
        for item in report["skipped"]
    )


def test_reclaimable_skips_dirty_lease_open_pr_and_root_with_reasons(
    tmp_path, monkeypatch
) -> None:
    """AC4: dirty, lease-held, open-PR, and root worktrees are skipped with
    explicit reasons."""
    dirty_wt = tmp_path / "dirty"
    dirty_wt.mkdir()
    leased_wt = tmp_path / "leased"
    leased_wt.mkdir()
    openpr_wt = tmp_path / "open-pr"
    openpr_wt.mkdir()

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {dirty_wt}\nHEAD d1\nbranch refs/heads/feat/dirty\n\n"
        f"worktree {leased_wt}\nHEAD d2\nbranch refs/heads/feat/leased\n\n"
        f"worktree {openpr_wt}\nHEAD d3\nbranch refs/heads/feat/open\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(
            tmp_path, porcelain, "main\nfeat/dirty\nfeat/leased\nfeat/open"
        ),
    )
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(
        git_hygiene,
        "_worktree_dirty",
        lambda path: path == str(dirty_wt),
    )

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        active_leases=[
            {
                "resource_id": f"worktree:{leased_wt}",
                "execution_id": "agent-x",
                "expires_at": 3000000000,
            }
        ],
        pr_states={
            "feat/dirty": {"state": "MERGED", "isDraft": False},
            "feat/open": {"state": "OPEN", "isDraft": False},
        },
        now=2000000000,
    )

    reasons = {
        item["path"]: item["reason"]
        for item in report["skipped"]
        if item.get("artifact") == "worktree"
    }
    assert reasons[str(tmp_path)] == "root_worktree"
    assert reasons[str(dirty_wt)] == "dirty_worktree"
    assert reasons[str(leased_wt)] == "active_lease"
    assert reasons[str(openpr_wt)] == "open_or_draft_pr"
    assert any(
        item["path"] == str(leased_wt) and item["reason"] == "active_lease"
        for item in report["preservation_receipts"]
    )
    # None of the skipped worktrees leaked into reclaimable.
    reclaim_paths = {item["path"] for item in report["reclaimable_worktrees"]}
    assert reclaim_paths.isdisjoint(
        {str(tmp_path), str(dirty_wt), str(leased_wt), str(openpr_wt)}
    )


def test_reclaimable_unknown_merge_state_is_skipped_not_reclaimed(
    tmp_path, monkeypatch
) -> None:
    """A clean non-root worktree that is neither an ancestor nor PR-confirmed
    merged/closed is held back as unknown merge state, never reclaimed."""
    unknown_wt = tmp_path / "unknown"
    unknown_wt.mkdir()

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {unknown_wt}\nHEAD d1\nbranch refs/heads/feat/unknown\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(tmp_path, porcelain, "main\nfeat/unknown"),
    )
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: False)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    # pr_states present but missing this branch -> _pr_state returns "unknown".
    report = git_hygiene.build_janitor_plan(tmp_path, pr_states={})

    assert report["reclaimable_worktrees"] == []
    assert any(
        item.get("artifact") == "worktree"
        and item["path"] == str(unknown_wt)
        and item["reason"] == "unknown_merge_state"
        for item in report["skipped"]
    )


def test_janitor_apply_removes_reclaimable_worktree_and_branch(
    tmp_path, monkeypatch
) -> None:
    """AC3: --mode apply removes a verified-reclaimable worktree + its local
    branch. An ancestor-proven branch keeps the conservative ``git branch -d`` and
    the worktree remove never uses --force. (Force-delete for PR-proven
    non-ancestor branches is covered in tests/scripts/test_git_hygiene_reclaim.py.)
    """
    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": [
                {
                    "path": str(tmp_path / "deliver-foo"),
                    "branch": "deliver/foo",
                    "merge_proof": "ancestor_of_origin_main",
                }
            ],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"deliver/foo": {"state": "MERGED"}},
    )

    assert report["ok"] is True
    assert ["worktree", "remove", str(tmp_path / "deliver-foo")] in commands
    # Ancestor-proven branch keeps the conservative -d.
    assert ["branch", "-d", "deliver/foo"] in commands
    # The worktree remove never uses --force, and an ancestor branch is never
    # force-deleted.
    assert not any("--force" in cmd for cmd in commands)
    assert ["branch", "-D", "deliver/foo"] not in commands


def test_janitor_apply_skips_branch_delete_when_worktree_remove_fails(
    tmp_path, monkeypatch
) -> None:
    """If the worktree remove fails (e.g. became dirty), do not delete the branch."""
    commands: list[list[str]] = []
    target = str(tmp_path / "deliver-foo")

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        if args == ["worktree", "remove", target]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "is dirty")
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": [
                {"path": target, "branch": "deliver/foo", "merge_proof": "merged_pr"}
            ],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={"deliver/foo": {"state": "MERGED"}},
    )

    assert report["ok"] is False
    assert ["branch", "-d", "deliver/foo"] not in commands


def test_janitor_apply_preserves_worktrees_when_receipts_exist(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [{"branch": "merged-branch"}],
                "worktrees": [],
                "remote_branches": [{"branch": "merged-remote"}],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [{"ref": "stash@{0}"}],
            },
            "reclaimable_worktrees": [{"path": str(tmp_path / "safe"), "branch": "safe"}],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
            "preservation_receipts": [
                {
                    "artifact": "worktree",
                    "path": str(tmp_path / "locked"),
                    "branch": "locked",
                    "reason": "locked_worktree",
                    "action": "preserve",
                    "next_action": "preserve the lock; verify the owning session before any cleanup",
                }
            ],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={},
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "preservation_evidence_present"
    assert commands == [["fetch", "--prune", "origin"]]


def test_janitor_apply_worktree_reclaim_is_idempotent(tmp_path) -> None:
    """AC3 idempotency: a second apply over an already-reclaimed worktree is a
    no-op (nothing left to remove)."""
    # A real bare remote (not the repo itself) so the worktree-reclaim path is
    # isolated from the out-of-scope remote-branch cleanup: only `main` is
    # published, so the local `deliver/foo` is never seen as a merged remote ref.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", remote], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    # Non-codex branch, fast-forward merged into main (ancestor of origin/main).
    subprocess.run(["git", "checkout", "-b", "deliver/foo"], cwd=repo, check=True)
    (repo / "foo.txt").write_text("foo\n", encoding="utf-8")
    subprocess.run(["git", "add", "foo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "foo"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "merge", "--ff-only", "deliver/foo"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "origin"], cwd=repo, check=True)
    clean_wt = tmp_path / "deliver-foo-wt"
    subprocess.run(["git", "worktree", "add", str(clean_wt), "deliver/foo"], cwd=repo, check=True)

    pr_states = {"deliver/foo": {"state": "MERGED"}}

    lifecycle_records = {
        str(clean_wt.resolve()): {
            "path": str(clean_wt.resolve()),
            "branch": "deliver/foo",
            "generation": GENERATION,
            "owner": "completed-owner",
            "status": "complete",
            "registered_at": -20,
            "heartbeat_at": -10,
            "complete_at": 0,
            "expires_at": 0,
        }
    }
    first = git_hygiene.janitor_apply(
        repo,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records=lifecycle_records,
        pr_states=pr_states,
    )
    assert first["ok"] is True
    # The worktree was removed (no --force) and its local branch deleted.
    assert not clean_wt.exists()
    assert "deliver/foo" not in git_hygiene._local_branches(repo)
    assert any(
        action.get("artifact") == "worktree"
        and action.get("action") == "remove"
        and action.get("path") == str(clean_wt)
        for action in first["destructive_actions"]
    )

    # Re-run: the worktree and branch are gone, so there is nothing to reclaim.
    second = git_hygiene.janitor_apply(
        repo,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records=lifecycle_records,
        pr_states=pr_states,
    )
    assert second["ok"] is True
    assert second["reclaimable_worktrees"] == []
    assert not any(
        action.get("artifact") == "worktree" and action.get("action") == "remove"
        for action in second["destructive_actions"]
    )


def test_default_command_entrypoint_preserves_global_and_subcommand_args(
    monkeypatch,
) -> None:
    captured = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(git_hygiene, "main", fake_main)

    assert (
        git_hygiene.main_with_default_command(
            "preflight",
            [
                "--cwd",
                "/repo",
                "--lease-file",
                "/leases.json",
                "--expected-branch",
                "main",
                "--base-branch",
                "main",
            ],
        )
        == 0
    )

    assert captured["argv"] == [
        "--cwd",
        "/repo",
        "--lease-file",
        "/leases.json",
        "preflight",
        "--expected-branch",
        "main",
        "--base-branch",
        "main",
    ]


def test_default_command_entrypoint_keeps_explicit_command(monkeypatch) -> None:
    captured = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(git_hygiene, "main", fake_main)

    assert git_hygiene.main_with_default_command("janitor", ["janitor"]) == 0
    assert captured["argv"] == ["janitor"]


# ---------------------------------------------------------------------------
# in_shared_root() and require_dedicated_worktree preflight tests
# ---------------------------------------------------------------------------


def _make_subprocess_run_fake(git_dir_out: str, common_dir_out: str, returncode: int = 0):
    """Return a fake subprocess.run that answers --git-dir and --git-common-dir queries."""

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "rev-parse"]:
            flag = args[2] if len(args) > 2 else ""
            if flag == "--git-dir":
                return subprocess.CompletedProcess(args, returncode, git_dir_out, "")
            if flag == "--git-common-dir":
                return subprocess.CompletedProcess(args, returncode, common_dir_out, "")
        # fall through for any other subprocess calls (merge-base, etc.)
        return subprocess.CompletedProcess(args, 0, "", "")

    return fake_run


def test_in_shared_root_returns_true_in_primary_worktree(tmp_path, monkeypatch) -> None:
    """in_shared_root() returns True when --git-dir and --git-common-dir agree."""
    git_dir = str(tmp_path / ".git")
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _make_subprocess_run_fake(git_dir + "\n", git_dir + "\n"),
    )
    assert git_hygiene.in_shared_root(str(tmp_path)) is True


def test_in_shared_root_returns_false_in_linked_worktree(tmp_path, monkeypatch) -> None:
    """in_shared_root() returns False when --git-dir and --git-common-dir differ."""
    # In a linked worktree --git-dir points to a per-worktree sub-dir inside
    # .git/worktrees/<name> while --git-common-dir points to the shared .git root.
    linked_git_dir = str(tmp_path / ".git" / "worktrees" / "linked")
    common_dir = str(tmp_path / ".git")
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _make_subprocess_run_fake(linked_git_dir + "\n", common_dir + "\n"),
    )
    assert git_hygiene.in_shared_root(str(tmp_path)) is False


def test_in_shared_root_returns_false_on_subprocess_error(tmp_path, monkeypatch) -> None:
    """in_shared_root() returns False (never raises) when git commands fail."""
    monkeypatch.setattr(
        git_hygiene.subprocess,
        "run",
        _make_subprocess_run_fake("", "", returncode=128),
    )
    assert git_hygiene.in_shared_root(str(tmp_path)) is False


def test_in_shared_root_real_repo_vs_linked_worktree(tmp_path) -> None:
    """Integration: in_shared_root() is True in the primary repo and False in a
    linked worktree created by ``git worktree add``."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", str(linked), "-b", "wt-branch", "main"], cwd=repo, check=True)

    assert git_hygiene.in_shared_root(str(repo)) is True
    assert git_hygiene.in_shared_root(str(linked)) is False


def test_preflight_shared_root_flag_off_is_unchanged(tmp_path, monkeypatch) -> None:
    """When require_dedicated_worktree is False (default), behaviour is unchanged:
    shared_root_worktree is False in the checks dict and ok is not affected."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "feature/x"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    # Even if in_shared_root would return True, the flag being False must suppress it.
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: True)

    report = git_hygiene.preflight_report(tmp_path)

    assert report["checks"]["shared_root_worktree"] is False
    assert report["ok"] is True


def test_preflight_require_dedicated_worktree_fails_in_shared_root(
    tmp_path, monkeypatch
) -> None:
    """When require_dedicated_worktree=True and in_shared_root() returns True,
    preflight_report must set ok=False and shared_root_worktree=True."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: True)

    report = git_hygiene.preflight_report(tmp_path, require_dedicated_worktree=True)

    assert report["ok"] is False
    assert report["checks"]["shared_root_worktree"] is True


def test_preflight_require_dedicated_worktree_passes_in_linked_worktree(
    tmp_path, monkeypatch
) -> None:
    """When require_dedicated_worktree=True but in_shared_root() returns False
    (we are in a linked worktree), preflight_report must not add a failure for
    the worktree isolation check."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "feature/y"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: False)

    report = git_hygiene.preflight_report(tmp_path, require_dedicated_worktree=True)

    assert report["ok"] is True
    assert report["checks"]["shared_root_worktree"] is False


# ---------------------------------------------------------------------------
# CLI exit-code tests for --require-dedicated-worktree
# ---------------------------------------------------------------------------


def _make_clean_fake_run_git(tmp_path, git_dir):
    """Minimal fake_run_git for a clean worktree with no branch/worktree args expected."""

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "feature/z"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    return fake_run_git


def test_cli_require_dedicated_worktree_nonzero_in_shared_root(
    tmp_path, monkeypatch
) -> None:
    """main() returns a non-zero exit code when --require-dedicated-worktree is
    passed and in_shared_root() is True (simulates running in the shared root)."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _make_clean_fake_run_git(tmp_path, git_dir))
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: True)

    exit_code = git_hygiene.main(
        ["--cwd", str(tmp_path), "preflight", "--require-dedicated-worktree"]
    )

    assert exit_code != 0, "Expected non-zero exit when in the shared root worktree"


def test_cli_require_dedicated_worktree_zero_in_linked_worktree(
    tmp_path, monkeypatch
) -> None:
    """main() returns 0 when --require-dedicated-worktree is passed but
    in_shared_root() returns False (linked/dedicated worktree)."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _make_clean_fake_run_git(tmp_path, git_dir))
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: False)

    exit_code = git_hygiene.main(
        ["--cwd", str(tmp_path), "preflight", "--require-dedicated-worktree"]
    )

    assert exit_code == 0, "Expected zero exit when in a dedicated worktree"


def test_cli_without_require_flag_zero_even_if_in_shared_root(
    tmp_path, monkeypatch
) -> None:
    """When --require-dedicated-worktree is absent, main() returns 0 regardless
    of whether the cwd is the shared root (library default stays off)."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    monkeypatch.setattr(git_hygiene, "run_git", _make_clean_fake_run_git(tmp_path, git_dir))
    monkeypatch.setattr(git_hygiene, "in_shared_root", lambda *_a, **_kw: True)

    exit_code = git_hygiene.main(["--cwd", str(tmp_path), "preflight"])

    assert exit_code == 0, "Expected zero exit when flag is absent (library default is off)"


def test_janitor_apply_stash_drop_targets_survive_index_shift(tmp_path) -> None:
    """Regression for #4333: a stale positional stash index must never cause
    ``janitor_apply`` to drop a stash that was not itself a candidate.

    Real ``git stash`` state, newest to oldest after four ``git stash push``
    calls:

        stash@{0} B  (candidate: preserve-local-drift marker)
        stash@{1} X  (non-candidate, interleaved between the two candidates)
        stash@{2} A  (candidate: preserve-local-drift marker)
        stash@{3} Y  (non-candidate, sits below A)

    ``build_janitor_plan`` captures A's positional selector as ``stash@{2}``
    when the plan is built. Dropping B first (``stash@{0}``) shifts every
    entry below it up by one, so the stale ``stash@{2}`` now names Y, not A.
    The unfixed loop in ``janitor_apply`` drops B, then blindly drops
    whatever now sits at ``stash@{2}``: Y is destroyed as collateral damage
    and A survives untouched -- exactly the incident's signature (a marked
    candidate survives while an unrelated, unmarked entry is destroyed). The
    fix must re-resolve each candidate's stable commit identity immediately
    before dropping it, so both real candidates (A, B) are dropped and both
    non-candidates (X, Y) survive.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)

    def push_stash(content: str, message: str) -> str:
        (repo / "file.txt").write_text(content, encoding="utf-8")
        subprocess.run(["git", "stash", "push", "-m", message], cwd=repo, check=True)
        return subprocess.run(
            ["git", "rev-parse", "stash@{0}"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    sha_y = push_stash("y\n", "unrelated Y (oldest, becomes collateral target)")
    sha_a = push_stash("a\n", "preserve-local-drift A")
    sha_x = push_stash("x\n", "unrelated X (interleaved non-candidate)")
    sha_b = push_stash("b\n", "preserve-local-drift B")

    # Let real wall-clock time move past the pushes above so stale_after_days=0
    # reliably makes every entry's committer epoch compare as "old".
    time.sleep(1.1)

    def current_shas() -> set[str]:
        listing = subprocess.run(
            ["git", "stash", "list", "--format=%H"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        return set(listing)

    assert current_shas() == {sha_y, sha_a, sha_x, sha_b}

    report = git_hygiene.janitor_apply(
        repo,
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
        pr_states={},
        stale_after_days=0,
    )

    after = current_shas()

    # Exactly the two marked candidates were dropped ...
    assert sha_b not in after, "B (marked, index 0) should have been dropped"
    assert sha_a not in after, (
        "A (marked, index 2 at plan time) should have been dropped -- if this "
        "fails, A survived because the drop loop is still using a stale "
        "positional index instead of re-resolving A's identity"
    )
    # ... and both non-candidates survive untouched.
    assert sha_x in after, "X (unmarked, between the two candidates) must survive"
    assert sha_y in after, (
        "Y (unmarked, below A) must survive -- if this fails, Y was destroyed "
        "as collateral damage by a stale stash@{2} that shifted onto it after "
        "B's drop, reproducing the #4333 incident"
    )
    assert after == {sha_x, sha_y}
    assert report["ok"] is True, report["errors"]
