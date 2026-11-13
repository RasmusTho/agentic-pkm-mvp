"""Takeover and ambiguous-publication reconciliation for epic workers (#6617)."""

from __future__ import annotations

import json
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine
from tests.builderops.test_epic_workspace_lifecycle import _ckpt, _git
from tests.builderops.test_epic_workspace_openhands import _main, _setup


class StuckEngine(FakeEngine):
    """An engine that reports success for ``docker rm`` but leaves the container running."""

    def __call__(self, argv, **kwargs):
        if list(argv)[:2] == ["docker", "rm"]:
            self.calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return super().__call__(argv, **kwargs)


def _json(capsys):
    """The last JSON document printed since the previous read."""

    text, decoder, last, index = capsys.readouterr().out, json.JSONDecoder(), None, 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        last, index = decoder.raw_decode(text, index)
    return last


def _state(root):
    return ew._load_state(ew.Layout(root.resolve(), 6615))["issue_mappings"]["6617"]


def _write(path, data):
    path.write_text(json.dumps(data))
    return str(path)


def test_partial_work_and_ambiguous_publication_are_reconciled_before_takeover(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement the slice")
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    predecessor = _state(root)["conversation"]["id"]

    # Partial work, a push whose outcome is known, and a PR create whose response was lost.
    (checkout / "partial.py").write_text("def half():\n")
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push") == 0
    push = _json(capsys)
    pushed = _write(tmp_path / "push.json", {"sha": "a" * 40, "branch": "b/a"})
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", push["id"], "--result-file", pushed) == 0
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    pr_op = _json(capsys)
    assert pr_op["status"] == "intended"

    # An unresolved attempt of the same kind is never replayed.
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    assert "do not replay" in capsys.readouterr().err

    # Competing writer: the engine cannot remove the predecessor, so nothing is authorized.
    stuck = StuckEngine()
    stuck.containers.update(engine.containers)
    stuck.ports.update(engine.ports)
    stuck.labels.update(engine.labels)
    assert _main(root, stuck, server, "takeover", "--worker", "w-a", "--reason", "predecessor lost") == 2
    assert "not verified stopped" in capsys.readouterr().err
    mapping = _state(root)
    assert "takeover" not in mapping and mapping["conversation"]["status"] != ew.CONVERSATION_ENDED
    assert (checkout / "partial.py").exists()

    # The predecessor container vanished (killed). Takeover proves absence by engine readback,
    # checkpoints the files and, with no readback available, quarantines only the PR create.
    engine.containers.clear()
    engine.ports.clear()
    posts_before = len([c for c in server.calls if c[0] == "POST"])
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "predecessor lost") == 0
    taken = _json(capsys)
    mapping = _state(root)
    assert mapping["conversation"]["status"] == ew.CONVERSATION_ENDED and mapping["conversation"]["id"] == predecessor
    assert mapping["state"] == "stopped_verified" and mapping["takeover"]["status"] == "authorized"
    assert [c["ref"] for c in mapping["checkpoints"]] == ["refs/checkpoints/ckpt-0001"]
    assert _ckpt(root, "w-a", "show", "refs/checkpoints/ckpt-0001:partial.py") == "def half():"
    ops = {op["id"]: op for op in mapping["publication_ops"]}
    assert ops[push["id"]]["status"] == "confirmed"
    assert ops[pr_op["id"]]["status"] == "quarantined"
    blocked = taken["next_authorized_action"]["blocked_operations"]
    assert [b["id"] for b in blocked] == [pr_op["id"]]
    assert "Do NOT attempt" in taken["prompt"] and pr_op["id"] in taken["prompt"]
    # The file work is not blocked, only the affected operation; and nothing replayed it.
    assert taken["next_authorized_action"]["action"].endswith("implement")
    assert len([c for c in server.calls if c[0] == "POST"]) == posts_before
    assert not any(c[0] in ("gh", "curl") for c in engine.calls)
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2

    # Coordinator readback shows the PR exists: adopted, never created again.
    readback = _write(tmp_path / "rb.json", {"complete": True, "branch": "b/a", "pull_requests": [{"number": 6630, "url": "https://example.invalid/pr/6630", "state": "open", "branch": "b/a", "sha": "a" * 40}]})
    assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", pr_op["id"], "--readback-file", readback) == 0
    done = _json(capsys)
    assert done["status"] == "confirmed" and done["result"]["number"] == 6630
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    assert "already confirmed" in capsys.readouterr().err
    assert len([op for op in _state(root)["publication_ops"] if op["kind"] == "pr_create"]) == 1


def test_readback_quarantines_doubt_and_empty_readback_never_proves_settlement(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    (layout.checkout("w-a") / "x.py").write_text("x\n")
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    pr_op = _json(capsys)["id"]

    doubtful = (
        {"complete": False, "pull_requests": []},
        {"complete": True, "pull_requests": []},  # absence without the queried branch proves nothing
        {"complete": True, "branch": "other", "pull_requests": []},
        {"complete": True, "branch": "b/a", "pull_requests": [{"number": 1}, {"number": 2}]},
        {"complete": True, "branch": "b/a", "pull_requests": [{"number": 1}]},
        {"complete": True, "branch": "b/a", "pull_requests": [{"number": 1, "branch": "other", "sha": "a" * 40}]},
        {"complete": True},
    )
    for number, readback in enumerate(doubtful):
        file = _write(tmp_path / f"bad-{number}.json", readback)
        assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", pr_op, "--readback-file", file) == 0
        assert _json(capsys)["status"] == "quarantined"
    assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", pr_op) == 0
    assert _json(capsys)["status"] == "quarantined"  # no readback at all

    # A complete empty list is still compatible with a delayed original request.
    absent = _write(tmp_path / "absent.json", {pr_op: {"complete": True, "branch": "b/a", "pull_requests": []}})
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r", "--readback-file", absent) == 0
    taken = _json(capsys)
    assert [item["id"] for item in taken["next_authorized_action"]["blocked_operations"]] == [pr_op]
    assert taken["next_authorized_action"]["retry_authorized"] == []
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    ops = {op["id"]: op for op in _state(root)["publication_ops"]}
    assert len(ops) == 1 and ops[pr_op]["status"] == "quarantined"
    assert next_actions(root)["retry_authorized"] == []


def next_actions(root):
    return ew.next_authorized_action(_state(root))


def test_claude_worker_is_continued_by_codex_from_durable_records(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement the slice")
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    claude = _json(capsys)
    assert claude["engine"] == "claude-code"
    (layout.checkout("w-a") / "wip.py").write_text("wip\n")

    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "claude quota exhausted") == 0
    capsys.readouterr()
    # Successor start is refused until takeover; the predecessor wrote no summary.
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    capsys.readouterr()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "continue on codex") == 0
    capsys.readouterr()
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    capsys.readouterr()
    posts = lambda: [c for c in server.calls if c[0] == "POST"]  # noqa: E731
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--engine", "codex", "--continuation") == 0
    codex = _json(capsys)
    assert codex["engine"] == "codex" and codex["model"] == "gpt-6.1-terra" and codex["status"] == "created"
    text = posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert "Issue #6617" in text and "refs/checkpoints/ckpt-0001" in text and "implement" in text
    assert _state(root)["takeover"]["status"] == "consumed" and _state(root)["takeover"]["conversation_id"] == codex["id"]
    assert [c["engine"] for c in _state(root)["conversation_history"]] == ["claude-code"]

    # The single continuation is spent: no second writer, and takeover of a live worker is still verified.
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--continuation") == 2
    assert "could still write" in capsys.readouterr().err
    # ...and the way back (Codex -> Claude) is the same path.
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "back to claude") == 0
    assert _json(capsys)["generation"] == 2
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--engine", "claude-code", "--continuation") == 0
    assert _json(capsys)["model"] == "claude-sonnet-5-5"


def test_takeover_reconciles_a_checkout_on_a_different_branch(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    _git(layout.checkout("w-a"), "checkout", "--quiet", "-b", "drifted")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 0
    brief = _json(capsys)
    assert brief["branch"] == "b/a" and brief["execution_branch"] == "drifted"
    assert _state(root)["takeover"]["status"] == "authorized"
    assert _state(root)["checkpoints"][0]["branch"] == "drifted"


def test_takeover_treats_unreadable_evidence_as_unique_work(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    (layout.checkout("w-a") / ".git" / "HEAD").write_text("garbage\n")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "unreadable" in capsys.readouterr().err
    mapping = _state(root)
    assert mapping["takeover"]["status"] == "required" and mapping["work_at_stop"]["unique_work"] is True
    assert (layout.checkout("w-a") / ".git" / "HEAD").read_text() == "garbage\n"


def test_empty_lost_create_stays_blocked_across_restart_then_adopts_original(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    sha = _git(checkout, "rev-parse", "HEAD")
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    (checkout / "partial.py").write_text("preserve this\n")
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create", "--expect-sha", sha) == 0
    op = _json(capsys)["id"]
    empty = _write(tmp_path / "empty.json", {op: {"complete": True, "branch": "b/a", "pull_requests": []}})
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "lost response", "--readback-file", empty) == 0
    brief = _json(capsys)
    assert brief["next_authorized_action"]["blocked_operations"][0]["id"] == op
    assert brief["next_authorized_action"]["action"].endswith("implement")
    assert _ckpt(root, "w-a", "show", "refs/checkpoints/ckpt-0001:partial.py") == "preserve this"

    # A fresh controller can continue work and even start an unrelated publication kind.
    fresh = FakeEngine()
    assert _main(root, fresh, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    capsys.readouterr()
    assert _main(root, fresh, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    assert _main(root, fresh, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", sha) == 0
    push = _json(capsys)["id"]
    assert _main(root, fresh, server, "publication-complete", "--worker", "w-a", "--op", push, "--result-file", _write(tmp_path / "push.json", {"branch": "b/a", "sha": sha})) == 0
    capsys.readouterr()
    present = _write(tmp_path / "present.json", {"complete": True, "branch": "b/a", "pull_requests": [{"number": 23, "branch": "b/a", "sha": sha}]})
    assert _main(root, fresh, server, "publication-reconcile", "--worker", "w-a", "--op", op, "--readback-file", present) == 0
    assert _json(capsys)["result"]["number"] == 23
    assert _main(root, fresh, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    assert len(_state(root)["publication_ops"]) == 2
    assert (checkout / "partial.py").read_text() == "preserve this\n"


def test_legacy_empty_absence_and_missing_remote_branch_remain_unknown(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    sha = _git(layout.checkout("w-a"), "rev-parse", "HEAD")
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    op = _json(capsys)["id"]
    ew._mutate_mapping(layout, "w-a", lambda entry: entry["publication_ops"][0].update(status="absent_confirmed"))
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    assert next_actions(root)["blocked_operations"][0]["id"] == op
    assert next_actions(root)["retry_authorized"] == []
    empty = _write(tmp_path / "empty.json", {"complete": True, "branch": "b/a", "pull_requests": []})
    assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", op, "--readback-file", empty) == 0
    assert _json(capsys)["status"] == "quarantined"
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", sha) == 0
    push = _json(capsys)["id"]
    absent = _write(tmp_path / "branch.json", {"complete": True, "branch": {"name": "b/a", "exists": False}})
    assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", push, "--readback-file", absent) == 0
    assert _json(capsys)["status"] == "quarantined"
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", "a" * 40) == 2


def test_legacy_retried_create_cannot_misattribute_a_matching_pr(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    sha = _git(layout.checkout("w-a"), "rev-parse", "HEAD")
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create", "--expect-sha", sha) == 0
    first = _json(capsys)["id"]

    def legacy_retry(entry):
        prior = entry["publication_ops"][0]
        prior.update(status="absent_confirmed", superseded_by="pr_create-2")
        entry["publication_ops"].append({**prior, "id": "pr_create-2", "status": "intended", "retry_of": first})

    ew._mutate_mapping(layout, "w-a", legacy_retry)
    present = _write(tmp_path / "present.json", {"complete": True, "branch": "b/a", "pull_requests": [{"number": 23, "branch": "b/a", "sha": sha}]})
    for op in (first, "pr_create-2"):
        assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", op, "--readback-file", present) == 0
        assert _json(capsys)["status"] == "quarantined"
    # An operation-specific result can settle one attempt without erasing the other.
    result = _write(tmp_path / "result.json", {"number": 23, "branch": "b/a", "sha": sha})
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", "pr_create-2", "--result-file", result) == 0
    ops = {op["id"]: op for op in _state(root)["publication_ops"]}
    assert ops[first]["status"] == "quarantined" and ops["pr_create-2"]["status"] == "confirmed"
    assert _main(root, engine, server, "publication-reconcile", "--worker", "w-a", "--op", first, "--readback-file", present) == 0
    assert _json(capsys)["status"] == "quarantined"


def test_reconciled_execution_branch_retains_all_work_and_publisher_scope(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    checkout = layout.checkout("w-a")
    assert _main(root, engine, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    _git(checkout, "checkout", "-b", "b/actual")
    _git(checkout, "checkout", "-b", "b/side")
    (checkout / "side.py").write_text("side commit\n")
    _git(checkout, "add", "side.py")
    _git(checkout, "commit", "-m", "side")
    side = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "b/actual")
    (checkout / "README.md").write_text("stash content\n")
    _git(checkout, "stash", "push", "-m", "keep")
    stash = _git(checkout, "rev-parse", "refs/stash")
    (checkout / "stage.py").write_text("staged version\n")
    _git(checkout, "add", "stage.py")
    (checkout / "stage.py").write_text("worktree version\n")
    (checkout / ".git" / "info" / "exclude").write_text("*.cache\n")
    (checkout / "unique.cache").write_text("ignored content\n")
    head = _git(checkout, "rev-parse", "HEAD")
    capsys.readouterr()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "continue") == 0
    brief = _json(capsys)
    entry = _state(root)
    assert (brief["branch"], brief["execution_branch"]) == ("b/a", "b/actual")
    assert "publisher/claim branch is `b/a`" in brief["prompt"]
    assert entry["branch"] == "b/a" and entry["execution_branch"] == "b/actual"
    assert entry["takeover"]["head"] == head and entry["takeover"]["previous_execution_branch"] == "b/a"
    checkpoint = entry["checkpoints"][0]
    assert checkpoint["branch"] == "b/actual" and checkpoint["head"] == head
    assert _ckpt(root, "w-a", "show", f"{checkpoint['ref']}:stage.py") == "worktree version"
    assert _ckpt(root, "w-a", "show", f"{checkpoint['staged_ref']}:stage.py") == "staged version"
    assert _ckpt(root, "w-a", "show", f"{checkpoint['ref']}:unique.cache") == "ignored content"
    assert _ckpt(root, "w-a", "rev-parse", f"refs/retained/{side}") == side
    assert _ckpt(root, "w-a", "rev-parse", f"refs/retained/{stash}") == stash
    assert _git(checkout, "show", ":stage.py") == "staged version"
    assert (checkout / "stage.py").read_text() == "worktree version\n"
    assert _git(checkout, "rev-parse", "refs/heads/b/side") == side
    assert _git(checkout, "rev-parse", "refs/stash") == stash
    fresh = FakeEngine()
    assert _main(root, fresh, server, "continuation-brief", "--worker", "w-a") == 0
    assert _json(capsys)["execution_branch"] == "b/actual"
    assert _main(root, fresh, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    assert _git(checkout, "branch", "--show-current") == "b/actual"
    assert _main(root, fresh, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create", "--expect-sha", head) == 0
    assert _json(capsys)["branch"] == "b/a"  # parent gate still binds the original branch


def test_confirmed_push_allows_new_head_without_losing_prior_evidence(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    first = _git(checkout, "rev-parse", "HEAD")
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", first) == 0
    op1 = _json(capsys)["id"]
    result = _write(tmp_path / "first.json", {"branch": "b/a", "sha": first})
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", op1, "--result-file", result) == 0
    confirmed = _json(capsys)
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", op1, "--result-file", result) == 0
    assert _json(capsys) == confirmed
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", first) == 2
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "continue") == 0
    assert _main(root, engine, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    (checkout / "next.py").write_text("next\n")
    _git(checkout, "add", "next.py")
    _git(checkout, "commit", "-m", "next")
    second = _git(checkout, "rev-parse", "HEAD")
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", second) == 0
    op2 = _json(capsys)["id"]
    assert op2 != op1
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", second) == 2
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", "a" * 40) == 2
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", op2, "--result-file", _write(tmp_path / "second.json", {"branch": "b/a", "sha": second})) == 0
    entries = _state(root)
    ops = {op["id"]: op for op in entries["publication_ops"]}
    assert ops[op1] == confirmed and ops[op2]["status"] == "confirmed"
    assert {h["sha"] for h in entries["published_heads"]} >= {first, second}
    assert not ops[op1].get("superseded_by") and not ops[op2].get("retry_of")


def test_later_push_keeps_prior_head_usable_for_checkpoint_release(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    (checkout / "kept.py").write_text("captured\n")
    _git(checkout, "add", "kept.py")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "checkpoint") == 0
    ref = _state(root)["checkpoints"][0]["ref"]
    assert _main(root, engine, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    _git(checkout, "commit", "-m", "publish captured work")
    first = _git(checkout, "rev-parse", "HEAD")
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", first) == 0
    op1 = _json(capsys)["id"]
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", op1, "--result-file", _write(tmp_path / "first.json", {"branch": "b/a", "sha": first})) == 0
    (checkout / "next.py").write_text("later\n")
    _git(checkout, "add", "next.py")
    _git(checkout, "commit", "-m", "later")
    second = _git(checkout, "rev-parse", "HEAD")
    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", second) == 0
    op2 = _json(capsys)["id"]
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", op2, "--result-file", _write(tmp_path / "second.json", {"branch": "b/a", "sha": second})) == 0
    capsys.readouterr()
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", ref, "--published-commit", first) == 0
    assert _json(capsys)["released_by"] == first


def test_branch_changed_during_checkpoint_is_refused_even_with_same_head_and_refs(tmp_path, capsys, monkeypatch):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    _git(checkout, "checkout", "-b", "b/actual")
    _git(checkout, "branch", "b/alternate")
    (checkout / "partial.py").write_text("keep\n")
    original = ew._inspect
    calls = 0

    def inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            _git(checkout, "checkout", "b/alternate")
        return original(*args, **kwargs)

    monkeypatch.setattr(ew, "_inspect", inspect)
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "changed while the checkpoint" in capsys.readouterr().err
    assert _state(root)["takeover"]["status"] == "required"
    assert _state(root)["branch"] == "b/a" and not _state(root).get("execution_branch")
    assert (checkout / "partial.py").read_text() == "keep\n"


@pytest.mark.parametrize("changed", ["branch", "execution_branch", "checkout", "generation"])
def test_branch_adoption_refuses_changed_mapping_scope_or_generation(tmp_path, capsys, monkeypatch, changed):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    checkout = layout.checkout("w-a")
    _git(checkout, "checkout", "-b", "b/actual")
    (checkout / "partial.py").write_text("keep\n")
    original = ew._inspect
    calls = 0

    def inspect(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            def drift(entry):
                if changed == "generation":
                    entry["takeover"]["generation"] += 1
                else:
                    entry[changed] = "foreign"
            ew._mutate_mapping(layout, "w-a", drift)
        return result

    monkeypatch.setattr(ew, "_inspect", inspect)
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "changed during takeover" in capsys.readouterr().err
    assert _state(root)["takeover"]["status"] == "required"
    assert (checkout / "partial.py").read_text() == "keep\n"
    assert _state(root)["checkpoints"][0]["branch"] == "b/actual"
