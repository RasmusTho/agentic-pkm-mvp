"""Takeover and ambiguous-publication reconciliation for epic workers (#6617)."""

from __future__ import annotations

import json
import subprocess

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


def test_readback_quarantines_doubt_and_permits_one_retry_only_on_proven_absence(tmp_path, capsys):
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

    # Takeover applies the coordinator's readback per operation: proven absence, not a guess.
    absent = _write(tmp_path / "absent.json", {pr_op: {"complete": True, "branch": "b/a", "pull_requests": []}})
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r", "--readback-file", absent) == 0
    taken = _json(capsys)
    assert taken["next_authorized_action"]["blocked_operations"] == []
    assert taken["next_authorized_action"]["retry_authorized"] == ["pr_create"]
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    retry = _json(capsys)
    assert retry["retry_of"] == pr_op and retry["status"] == "intended"
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    ops = {op["id"]: op for op in _state(root)["publication_ops"]}
    assert ops[pr_op]["superseded_by"] == retry["id"]
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


def test_takeover_refuses_a_checkout_on_the_wrong_branch(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    _git(layout.checkout("w-a"), "checkout", "--quiet", "-b", "drifted")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "run-state records 'b/a'" in capsys.readouterr().err
    assert "takeover" not in _state(root) or _state(root)["takeover"]["status"] != "authorized"


def test_takeover_treats_unreadable_evidence_as_unique_work(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    (layout.checkout("w-a") / ".git" / "HEAD").write_text("garbage\n")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "unreadable" in capsys.readouterr().err
    mapping = _state(root)
    assert mapping["takeover"]["status"] == "required" and mapping["work_at_stop"]["unique_work"] is True
    assert (layout.checkout("w-a") / ".git" / "HEAD").read_text() == "garbage\n"
