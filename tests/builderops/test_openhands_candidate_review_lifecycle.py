"""Reviewer assignment lifecycle alongside retained stopped author custody."""

import copy
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_openhands import _main, _setup


def test_isolated_reviewer_lifecycle_preserves_author_and_reconciles_same_create(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    author_checkout = layout.checkout("w-a")
    (author_checkout / "README.md").write_text("author repair\n")
    (author_checkout / ".git" / "info" / "exclude").write_text("private.txt\n")
    (author_checkout / "private.txt").write_text("retain private author work\n")
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "review") == 0
    author = copy.deepcopy(ew._load_state(layout)["issue_mappings"]["6617"])
    ew._reserve_review_worker(layout, 6617, "w-a", "w-review")
    ew._reserve_review_worker(layout, 6617, "w-a", "w-review")
    # Reservation remains a fence even if a continuation of the author is requested.
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "attempt restart") == 2
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "attempt restop") == 2

    # Fixture setup only: future candidate materialization must independently supply this checkout.
    checkout = layout.checkout("w-review")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(layout.source), str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "checkout", "--quiet", "-B", "b/review"], check=True)
    layout.home("w-review").mkdir(parents=True, exist_ok=True)
    ew._record_assigned_worker(layout, 6617, "w-review", state="created", branch="b/review",
                               checkout=str(checkout), next_action="review")
    engine.containers["w-a"] = "running"  # External engine readback contradicts the recorded stop.
    assert _main(root, engine, server, "openhands-start", "--worker", "w-review") == 2
    assert "w-review" not in engine.containers
    del engine.containers["w-a"]
    assert _main(root, engine, server, "openhands-start", "--worker", "w-review") == 0
    run = engine.runs()[-1]
    mounts = [run[i + 1] for i, value in enumerate(run) if value == "--mount"]
    assert all(str(author_checkout) not in mount for mount in mounts)
    assert all(str(ew._checkpoint_repo(layout, "w-a")) not in mount for mount in mounts)
    state = ew._load_state(layout)
    assert ew._issue_for_worker(state, "w-review") == 6617
    reviewer = ew._worker_mapping(state, "w-review")
    with pytest.raises(ew.EndpointUnavailable):
        with ew._endpoint_session(layout, "w-review", 9999, reviewer, engine):
            pass

    server.lose_next_create = True
    server.create_not_applied = True
    operation = "pr-completion-" + "a" * 64
    conversation = ew.start_conversation(layout, "w-review", engine="codex", model="gpt-6.1-terra",
                                         prompt="review", operation_id=operation, http=server, runner=engine)
    assert conversation["status"] == "unknown"
    assert ew.reconcile_worker_conversation(layout, "w-review", http=server, runner=engine)["status"] == "unknown"
    posts = [call for call in server.calls if call[0] == "POST"]
    assert len(posts) == 1
    payload = posts[0][3]
    assert payload["conversation_id"] == conversation["id"]
    assert payload["tags"] == {"epic": "6615", "issue": "6617", "worker": "w-review"}
    assert payload["agent_settings"] == {"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
    server.conversations[conversation["id"]] = {"id": conversation["id"], "execution_status": "running",
        "agent_settings": payload["agent_settings"], "tags": payload["tags"], "workspace": payload["workspace"]}
    assert ew.reconcile_worker_conversation(layout, "w-review", http=server, runner=engine)["status"] == "created"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    (checkout / "README.md").write_text("reviewer notes\n")
    assert _main(root, engine, server, "worker-stop", "--worker", "w-review", "--reason", "finished") == 0
    state = ew._load_state(layout)
    reviewer = ew._worker_mapping(state, "w-review")
    assert reviewer["state"] == "stopped_verified"
    assert reviewer["conversation"]["status"] == ew.CONVERSATION_ENDED
    assert reviewer["work_at_stop"]["checkpoint"] in reviewer["checkpoints"]
    current_author = dict(state["issue_mappings"]["6617"])
    current_author.pop("review_workers")
    assert current_author == author
    assert (author_checkout / "private.txt").read_text() == "retain private author work\n"
    assert {row["worker"] for row in ew.status(layout, runner=engine)["workers"]} == {"w-a", "w-review"}


def test_reviewer_reservation_refuses_unstopped_author_and_worker_collision(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    with pytest.raises(ew.LaunchRefused):
        ew._reserve_review_worker(layout, 6617, "w-a", "w-review")
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "review") == 0
    ew._reserve_review_worker(layout, 6617, "w-a", "w-review")
    with pytest.raises(ew.LaunchRefused):
        ew._reserve_review_worker(layout, 6617, "w-a", "w-review-2")
    with pytest.raises(ew.LaunchRefused):
        ew._reserve_worker(layout, 6618, "w-review", state="creating")
    with pytest.raises(ew.LaunchRefused):
        ew._reserve_review_worker(layout, 6617, "w-a", "w-a")
