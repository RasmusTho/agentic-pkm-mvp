from contextlib import nullcontext
import json

import pytest

from scripts import agent_worktree as aw
from scripts import git_archive_retirement as ar
from scripts import git_hygiene as gh

REF = "refs/archive/git-hygiene/20260717T100557Z/old-work"


@pytest.fixture
def phase(tmp_path, monkeypatch):
    root = tmp_path / "root"
    remote = tmp_path / "remote.git"
    root.mkdir()
    remote.mkdir()
    ar._git(root, ["init", "-b", "main"])
    ar._git(remote, ["init", "--bare", "."])
    ar._git(root, ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "base"])
    ar._git(root, ["checkout", "-b", "old"])
    ar._git(root, ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "old"])
    sha = ar._git(root, ["rev-parse", "HEAD"])
    ar._git(root, ["push", str(remote), f"HEAD:{REF}"])
    ar._git(root, ["checkout", "main"])
    aw._write_registry(aw._default_registry_path(root), {"schema": aw.REGISTRY_SCHEMA, "worktrees": {}})
    identity = gh.RepositoryIdentity(123, "RasmusTho/agentic-pkm-mvp", str(remote), str(remote))
    monkeypatch.setattr(gh, "_resolve_repository_identity", lambda *args: identity)
    monkeypatch.setattr(gh, "_read_protected_targets", lambda *args, **kwargs: gh.ProtectedAuthority(4728, 4813, "refs/heads/protected", "f" * 40))
    monkeypatch.setattr(gh, "_open_cleanup_pr_heads", lambda *args: {})
    monkeypatch.setattr(gh, "_dispatcher_authority_write_fence", lambda *args: nullcontext(None))
    monkeypatch.setattr(gh, "_dispatcher_snapshot_from_connection", lambda *args: [])
    kwargs = dict(targets={REF: sha}, snapshot_directory=tmp_path / "rescue", owner_discard="explicit owner discard")
    return root, remote, sha, kwargs


def test_success_independent_bundle(phase):
    root, remote, sha, kwargs = phase
    result = ar.retire_remote_legacy_archives(root, **kwargs)
    assert result["deleted"] == {REF: sha}
    assert result["state"] == "completed"
    assert ar._remote(root, str(remote), {REF: sha}) == {}
    manifest = ar._bundle(kwargs["snapshot_directory"], result)
    recovery = root.parent / "recover"
    recovery.mkdir()
    ar._git(recovery, ["init", "--bare", "."])
    ar._git(recovery, ["bundle", "unbundle", manifest["bundle"]])
    ar._git(recovery, ["cat-file", "-e", sha])


@pytest.mark.parametrize("ref", ["refs/heads/old", "refs/archive/git-hygiene/v1/" + "a" * 64])
def test_reject_wrong_namespace(phase, ref):
    root, _, sha, kwargs = phase
    kwargs["targets"] = {ref: sha}
    with pytest.raises(ValueError, match="namespace"):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert not kwargs["snapshot_directory"].exists()


@pytest.mark.parametrize("activity", ["head", "lease", "pr"])
def test_preserve_activity(phase, monkeypatch, activity):
    root, remote, sha, kwargs = phase
    if activity == "head":
        ar._git(root, ["checkout", "old"])
    elif activity == "lease":
        monkeypatch.setattr(gh, "_dispatcher_snapshot_from_connection", lambda *a: [
            {"kind": "lease", "record": {"released_at": None, "expires_at": "2099-01-01T00:00:00Z", "resource": "other"}}])
    else:
        monkeypatch.setattr(gh, "_open_cleanup_pr_heads", lambda *a: {"3:feature": sha})
    result = ar.retire_remote_legacy_archives(root, **kwargs)
    assert not result["deleted"]
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: sha}


def test_remote_advancement_cas(phase, monkeypatch):
    root, remote, sha, kwargs = phase
    real = ar._git
    newer = real(root, ["rev-parse", "HEAD"])

    def race(cwd, args):
        if args[:3] == ["push", "--atomic", "--no-verify"] and f":{REF}" in args:
            real(remote, ["update-ref", REF, newer])
        return real(cwd, args)

    monkeypatch.setattr(ar, "_git", race)
    with pytest.raises(RuntimeError, match="recreated"):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: newer}


def test_github_drift_compensates(phase, monkeypatch):
    root, remote, sha, kwargs = phase

    def heads(*args):
        return {} if ar._remote(root, str(remote), {REF: sha}) else {"3:changed": sha}

    monkeypatch.setattr(gh, "_open_cleanup_pr_heads", heads)
    with pytest.raises(RuntimeError, match="authority_drift"):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: sha}
    assert json.loads((kwargs["snapshot_directory"] / "archive-retirement.json").read_text())["state"] == "compensated"


def crash_after_push(root, kwargs, monkeypatch):
    real = ar._git

    def crash(cwd, args):
        result = real(cwd, args)
        if args[:3] == ["push", "--atomic", "--no-verify"]:
            raise KeyboardInterrupt("power loss after push")
        return result

    monkeypatch.setattr(ar, "_git", crash)
    with pytest.raises(KeyboardInterrupt):
        ar.retire_remote_legacy_archives(root, **kwargs)
    monkeypatch.setattr(ar, "_git", real)


def test_crash_retry_compensates_without_more_deletes(phase, monkeypatch):
    root, remote, sha, kwargs = phase
    crash_after_push(root, kwargs, monkeypatch)
    assert ar._remote(root, str(remote), {REF: sha}) == {}
    result = ar.retire_remote_legacy_archives(root, **kwargs)
    assert result["state"] == "compensated"
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: sha}


@pytest.mark.parametrize("change", ["bundle", "recreated", "identity", "schema"])
def test_retry_preserves_uncertain_state(phase, monkeypatch, change):
    root, remote, sha, kwargs = phase
    crash_after_push(root, kwargs, monkeypatch)
    expected = {}
    if change == "bundle":
        (kwargs["snapshot_directory"] / "repository.bundle").write_bytes(b"corrupt")
    elif change == "recreated":
        newer = ar._git(root, ["rev-parse", "HEAD"])
        ar._git(root, ["push", str(remote), f"{newer}:{REF}"])
        expected = {REF: newer}
    else:
        path = kwargs["snapshot_directory"] / "archive-retirement.json"
        receipt = json.loads(path.read_text())
        receipt["repository" if change == "identity" else "schema"] = "invalid"
        path.write_text(json.dumps(receipt))
    with pytest.raises(RuntimeError):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert ar._remote(root, str(remote), {REF: sha}) == expected


def test_lifecycle_drift_stops_before_push(phase, monkeypatch):
    root, remote, sha, kwargs = phase
    real = gh.create_rescue_snapshot

    def drift(*args):
        snapshot = real(*args)
        aw._write_registry(aw._default_registry_path(root), {"schema": aw.REGISTRY_SCHEMA, "worktrees": {"changed": {}}})
        return snapshot

    monkeypatch.setattr(gh, "create_rescue_snapshot", drift)
    with pytest.raises(RuntimeError, match="lifecycle_generation_drift"):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: sha}


def test_atomic_batch_and_serial_readback(phase):
    root, remote, sha, kwargs = phase
    other = REF + "-two"
    ar._git(root, ["push", str(remote), f"{sha}:{other}"])
    kwargs["targets"][other] = sha
    result = ar.retire_remote_legacy_archives(root, **kwargs)
    assert result["deleted"] == kwargs["targets"]
    assert len(result["batches"]) == 1
    assert result["batches"][0]["readback"] == "verified"
    assert ar._remote(root, str(remote), kwargs["targets"]) == {}


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/ordinary", REF])
def test_rescue_wrapper_rejects_other_namespaces(phase, ref):
    root, _, sha, kwargs = phase
    kwargs["targets"] = {ref: sha}
    with pytest.raises(ValueError, match="namespace"):
        ar.retire_remote_legacy_rescue_branches(root, **kwargs)


@pytest.mark.parametrize("activity", ["none", "open_original", "checked_original", "resumable_original"])
def test_rescue_wrapper_checks_original_branch(phase, monkeypatch, activity):
    root, remote, sha, kwargs = phase
    ref = "refs/heads/rescue/old"
    ar._git(root, ["push", str(remote), f"{sha}:{ref}"])
    kwargs["targets"] = {ref: sha}
    if activity == "open_original":
        monkeypatch.setattr(gh, "_open_cleanup_pr_heads", lambda *a: {"3:old": "a" * 40})
    elif activity == "checked_original":
        ar._git(root, ["checkout", "old"])
    elif activity == "resumable_original":
        monkeypatch.setattr(gh, "_dispatcher_snapshot_from_connection", lambda *a: [
            {"kind": "task", "record": {"status": "blocked", "branch": "old"}}])
    result = ar.retire_remote_legacy_rescue_branches(root, **kwargs)
    assert result["schema"] == ar.RESCUE_SCHEMA
    assert bool(result["deleted"]) == (activity == "none")
    assert ar._remote(root, str(remote), {ref: sha}) == ({} if activity == "none" else {ref: sha})


def test_rescue_wrapper_preserves_invalid_original_generation(phase):
    root, remote, sha, kwargs = phase
    ref = "refs/heads/rescue/old"
    ar._git(root, ["push", str(remote), f"{sha}:{ref}"])
    kwargs["targets"] = {ref: sha}
    old_path = str((root.parent / "old-checkout").resolve())
    aw._write_registry(aw._default_registry_path(root), {
        "schema": aw.REGISTRY_SCHEMA,
        "worktrees": {old_path: {"branch": "old", "expires_at": 1}},
    })
    result = ar.retire_remote_legacy_rescue_branches(root, **kwargs)
    assert not result["deleted"]
    assert ar._remote(root, str(remote), {ref: sha}) == {ref: sha}


def test_worktree_drift_after_push_compensates(phase, monkeypatch):
    root, remote, sha, kwargs = phase
    real = ar._git

    def drift(cwd, args):
        result = real(cwd, args)
        if args[:3] == ["push", "--atomic", "--no-verify"] and f":{REF}" in args:
            real(root, ["checkout", "old"])
        return result

    monkeypatch.setattr(ar, "_git", drift)
    with pytest.raises(RuntimeError, match="local_authority_drift"):
        ar.retire_remote_legacy_archives(root, **kwargs)
    assert ar._remote(root, str(remote), {REF: sha}) == {REF: sha}


@pytest.fixture
def closed_phase(phase, monkeypatch):
    root, remote, sha, kwargs = phase
    refs = ["refs/heads/closed-one", "refs/heads/closed-two"]
    ar._git(root, ["push", str(remote), *[f"{sha}:{ref}" for ref in refs]])
    targets = [{"ref": ref, "sha": sha, "pr": 100 + index} for index, ref in enumerate(refs)]
    kwargs["targets"] = targets
    payloads = {target["pr"]: {
        "number": target["pr"], "state": "closed", "draft": False,
        "merged": True, "merged_at": "2026-01-01T00:00:00Z", "closed_at": "2026-01-01T00:00:00Z",
        "head": {"ref": target["ref"].removeprefix("refs/heads/"), "sha": sha, "repo": {"id": 123}},
    } for target in targets}
    monkeypatch.setattr(gh, "_github_get", lambda cwd, endpoint: payloads[int(endpoint.rsplit("/", 1)[1])])
    return root, remote, sha, kwargs, payloads


def test_closed_pr_atomic_two_head_success(closed_phase):
    root, remote, _, kwargs, _ = closed_phase
    result = ar.retire_closed_pr_remote_batches(root, **kwargs)
    assert result["schema"] == ar.CLOSED_PR_SCHEMA
    assert len(result["deleted"]) == 2
    assert len(result["batches"]) == 1
    assert result["pr_targets"] == kwargs["targets"]
    assert not ar._remote(root, str(remote), result["targets"])


@pytest.mark.parametrize("moment", ["before", "after"])
def test_closed_pr_reopen_never_leaves_batch_deleted(closed_phase, monkeypatch, moment):
    root, remote, _, kwargs, payloads = closed_phase
    real = ar._git
    if moment == "before":
        payloads[101]["state"] = "open"
    else:
        def reopen(cwd, args):
            result = real(cwd, args)
            if args[:3] == ["push", "--atomic", "--no-verify"] and any(arg.startswith(":refs/heads/") for arg in args):
                payloads[101]["state"] = "open"
            return result
        monkeypatch.setattr(ar, "_git", reopen)
    with pytest.raises(RuntimeError, match="pr_authority_invalid"):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    refs = {target["ref"]: target["sha"] for target in kwargs["targets"]}
    assert ar._remote(root, str(remote), refs) == refs


def test_closed_pr_retry_metadata_mismatch_refuses_recovery(closed_phase, monkeypatch):
    root, remote, _, kwargs, _ = closed_phase
    real = ar._git

    def crash(cwd, args):
        result = real(cwd, args)
        if args[:3] == ["push", "--atomic", "--no-verify"]:
            raise KeyboardInterrupt("power loss")
        return result

    monkeypatch.setattr(ar, "_git", crash)
    with pytest.raises(KeyboardInterrupt):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    monkeypatch.setattr(ar, "_git", real)
    kwargs["targets"][0]["pr"] += 500
    with pytest.raises(RuntimeError, match="receipt_identity_mismatch"):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    refs = {target["ref"]: target["sha"] for target in kwargs["targets"]}
    assert not ar._remote(root, str(remote), refs)
    kwargs["targets"][0]["pr"] -= 500
    result = ar.retire_closed_pr_remote_batches(root, **kwargs)
    assert result["state"] == "compensated"
    assert ar._remote(root, str(remote), refs) == refs


def test_closed_pr_concurrent_advanced_head_is_preserved(closed_phase, monkeypatch):
    root, remote, _, kwargs, _ = closed_phase
    real = ar._git
    newer = real(root, ["rev-parse", "HEAD"])
    ref = kwargs["targets"][0]["ref"]

    def advance(cwd, args):
        if args[:3] == ["push", "--atomic", "--no-verify"]:
            real(remote, ["update-ref", ref, newer])
        return real(cwd, args)

    monkeypatch.setattr(ar, "_git", advance)
    with pytest.raises(RuntimeError, match="recreated"):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    refs = {target["ref"]: target["sha"] for target in kwargs["targets"]}
    refs[ref] = newer
    assert ar._remote(root, str(remote), refs) == refs


def test_closed_pr_post_push_recreation_restores_other_absent_head(closed_phase, monkeypatch):
    root, remote, _, kwargs, _ = closed_phase
    real = ar._git
    newer = real(root, ["rev-parse", "HEAD"])
    ref = kwargs["targets"][0]["ref"]

    def recreate(cwd, args):
        result = real(cwd, args)
        if args[:3] == ["push", "--atomic", "--no-verify"] and f":{ref}" in args:
            real(remote, ["update-ref", ref, newer])
        return result

    monkeypatch.setattr(ar, "_git", recreate)
    with pytest.raises(RuntimeError, match="recreated"):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    refs = {target["ref"]: target["sha"] for target in kwargs["targets"]}
    refs[ref] = newer
    assert ar._remote(root, str(remote), refs) == refs
    receipt = json.loads((kwargs["snapshot_directory"] / "archive-retirement.json").read_text())
    assert receipt["state"] == "recovery_required"


@pytest.mark.parametrize("target", [
    {"ref": "refs/heads/main", "sha": "a" * 40, "pr": 1},
    {"ref": "refs/heads/without-pr", "sha": "a" * 40},
])
def test_closed_pr_rejects_protected_or_missing_pr(phase, target):
    root, _, _, kwargs = phase
    kwargs["targets"] = [target]
    with pytest.raises(ValueError):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    assert not kwargs["snapshot_directory"].exists()


def test_closed_pr_rejects_rescue_namespace_with_active_original(phase):
    root, remote, sha, kwargs = phase
    ar._git(root, ["checkout", "old"])
    ref = "refs/heads/rescue/old"
    ar._git(root, ["push", str(remote), f"{sha}:{ref}"])
    kwargs["targets"] = [{"ref": ref, "sha": sha, "pr": 100}]
    with pytest.raises(ValueError, match="namespace"):
        ar.retire_closed_pr_remote_batches(root, **kwargs)
    assert not kwargs["snapshot_directory"].exists()
    assert ar._remote(root, str(remote), {ref: sha}) == {ref: sha}


@pytest.mark.parametrize("ref", ["refs/stash", "refs/heads/old", REF,
                                 "refs/recovered-stash/undated",
                                 "refs/recovered-stash/2026-07-06-old/nested"])
def test_recovered_stash_rejects_other_namespaces(phase, ref):
    root, _, sha, kwargs = phase
    kwargs["targets"] = {ref: sha}
    with pytest.raises(ValueError, match="namespace"):
        ar.retire_remote_dated_recovered_stashes(root, **kwargs)
    assert not kwargs["snapshot_directory"].exists()


@pytest.mark.parametrize("crash", [False, True])
def test_recovered_stash_retirement_and_crash_recovery(phase, monkeypatch, crash):
    root, remote, sha, kwargs = phase
    ref = "refs/recovered-stash/2026-07-06-old-work"
    ar._git(root, ["push", str(remote), f"{sha}:{ref}"])
    kwargs["targets"] = {ref: sha}
    real = ar._git

    def interrupt(cwd, args):
        result = real(cwd, args)
        if args[:3] == ["push", "--atomic", "--no-verify"]:
            raise KeyboardInterrupt("power loss")
        return result

    if crash:
        monkeypatch.setattr(ar, "_git", interrupt)
        with pytest.raises(KeyboardInterrupt):
            ar.retire_remote_dated_recovered_stashes(root, **kwargs)
        monkeypatch.setattr(ar, "_git", real)
    result = ar.retire_remote_dated_recovered_stashes(root, **kwargs)
    assert result["schema"] == ar.RECOVERED_STASH_SCHEMA
    assert result["state"] == ("compensated" if crash else "completed")
    assert ar._remote(root, str(remote), {ref: sha}) == ({ref: sha} if crash else {})
    ar._bundle(kwargs["snapshot_directory"], result)


@pytest.mark.parametrize("date", ["2026-99-99", "2026-02-30", "2026-02-29"])
def test_recovered_stash_rejects_invalid_calendar_date(phase, date):
    root, _, sha, kwargs = phase
    kwargs["targets"] = {f"refs/recovered-stash/{date}-old": sha}
    with pytest.raises(ValueError, match="calendar_date_invalid"):
        ar.retire_remote_dated_recovered_stashes(root, **kwargs)
    assert not kwargs["snapshot_directory"].exists()
