"""OpenHands-managed worker runtime for the epic workspace (#6616, owner revision 2026-11-12b)."""

from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, urlsplit

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo


class FakeAgentServer:
    """Minimal stand-in for the upstream agent-server REST surface."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str, dict | None]] = []
        self.conversations: dict[str, dict] = {}
        self.lose_next_create = False
        self.create_not_applied = False
        self.events: list[dict] = []
        self.final_responses: dict[str, str] = {}

    def __call__(self, method, port, key, path, body, timeout):
        assert key and len(key) >= 32
        self.calls.append((method, port, path, body))
        if method == "GET" and path.startswith("/conversations/search"):
            return 200, {"items": []}
        if method == "POST" and path == "/conversations":
            cid = body["conversation_id"]
            if not self.create_not_applied:
                self.conversations[cid] = {"id": cid, "execution_status": "running", "agent_settings": body["agent_settings"]}
            if self.lose_next_create:
                self.lose_next_create = False
                raise OSError("response lost")
            return 201, self.conversations[cid]
        if method == "GET" and "/events/search" in path:
            params = parse_qs(urlsplit(path).query)
            events = self.events[::-1] if params.get("sort_order") == ["TIMESTAMP_DESC"] else self.events
            return 200, {"items": events[:int(params.get("limit", ["100"])[0])]}
        if method == "GET" and path.endswith("/agent_final_response"):
            cid = path.split("/")[2]
            return 200, {"response": self.final_responses.get(cid, "")}
        if method == "GET" and path.startswith("/conversations/"):
            cid = path.rsplit("/", 1)[1]
            return (200, self.conversations[cid]) if cid in self.conversations else (404, None)
        raise AssertionError((method, path))


def _setup(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine, server = FakeEngine(), FakeAgentServer()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "implement") == 0
    capsys.readouterr()
    return root, engine, server


def _main(root, engine, server, *args):
    return ew.main(["--root", str(root), "--epic", "6615", *args], runner=engine, http=server)


def test_openhands_worker_runs_pinned_agent_server_inside_the_boundary(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    secret = tmp_path / "claude.env"
    secret.write_text("CLAUDE_CODE_OAUTH_TOKEN=placeholder\n")
    secret.chmod(0o600)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a", "--claude-env-file", str(secret)) == 0
    [run] = engine.runs()
    assert ew.OPENHANDS_IMAGE in run and run[-1] == ew.OPENHANDS_IMAGE  # upstream image, its own entrypoint
    assert "--read-only" in run and run[run.index("--cap-drop") + 1] == "ALL" and run[run.index("--user") + 1] == "1000:1000"
    assert run[run.index("--publish") + 1].startswith("127.0.0.1:") and run[run.index("--network") + 1] == "epicws"
    assert "/tmp:rw,exec,nosuid,size=768m" in run
    mounts = [run[i + 1] for i, a in enumerate(run) if a == "--mount"]
    layout = ew.Layout(root.resolve(), 6615)
    assert mounts == [
        f"type=bind,source={layout.checkout('w-a')},target=/workspace",
        f"type=bind,source={layout.home('w-a')},target=/home/worker",
    ]
    env_files = [run[i + 1] for i, a in enumerate(run) if a == "--env-file"]
    key_file = layout.epic_dir / "control" / "w-a.key"
    assert env_files == [str(secret), str(key_file)] and (key_file.stat().st_mode & 0o077) == 0
    assert "OH_CONVERSATIONS_PATH=/home/worker/openhands/conversations" in run
    assert "placeholder" not in json.dumps(run)
    state = ew._load_state(layout)["issue_mappings"]["6617"]
    assert state["runtime"] == "openhands" and state["state"] == "running" and state["credentials"]["claude"] == "oauth-token-env"

    # A second agent-server for the same worker is refused; the codex login dir is single-mount.
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    codex = tmp_path / "codex-home"
    codex.mkdir(mode=0o700)
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-b", "--issue", "6618", "--branch", "b/b", "--next-action", "x") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-b", "--codex-home", str(codex)) == 0
    run_b = engine.runs()[-1]
    assert f"type=bind,source={codex.resolve()},target=/run/codex-home" in run_b and "CODEX_HOME=/run/codex-home" in run_b
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-c", "--issue", "6619", "--branch", "b/c", "--next-action", "x") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-c", "--codex-home", str(codex)) == 2
    assert "already mounted" in capsys.readouterr().err


def test_one_writer_per_worker_and_unknown_creates_are_never_repeated(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement #6617 slice")
    posts = lambda: [c for c in server.calls if c[0] == "POST"]  # noqa: E731

    for bad in (["--engine", "codex", "--model", "gpt-astra"], ["--engine", "codex", "--model", "gpt-5"], ["--model", "astra-1"]):
        assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt), *bad) == 2
    assert posts() == []

    capsys.readouterr()
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    first = json.loads(capsys.readouterr().out)
    assert posts()[0][3]["agent_settings"] == {"agent_kind": "acp", "acp_server": "claude-code", "acp_model": "claude-sonnet-5-5"}
    assert posts()[0][3]["tags"] == {"epic": "6615", "issue": "6617", "worker": "w-a"}
    assert first["status"] == "created" and uuid.UUID(first["id"])

    # A live conversation is the worker's single writer: a second one is refused before any POST.
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--engine", "codex", "--prompt-file", str(prompt)) == 2
    assert "could still write" in capsys.readouterr().err and len(posts()) == 1

    # A verified stop ends it; takeover authorizes the successor conversation (other engine).
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "simulated handoff") == 0
    layout = ew.Layout(root.resolve(), 6615)
    assert ew._load_state(layout)["issue_mappings"]["6617"]["conversation"]["status"] == ew.CONVERSATION_ENDED
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "verified handoff") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    server.lose_next_create = True  # applied by the server, response lost
    capsys.readouterr()
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--engine", "codex", "--prompt-file", str(prompt)) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "created" and second["model"] == "gpt-6.1-terra" and len(posts()) == 2
    mapping = ew._load_state(layout)["issue_mappings"]["6617"]
    assert [c["id"] for c in mapping["conversation_history"]] == [first["id"]]

    # Lost response and not (yet) visible: stays unknown, blocks a new create, is never re-POSTed.
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "r") == 0
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "verified handoff") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    server.lose_next_create, server.create_not_applied = True, True
    capsys.readouterr()
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unknown"
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 2
    assert _main(root, engine, server, "conversation-reconcile", "--worker", "w-a") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unknown"
    assert len(posts()) == 3
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "end unknown create") == 0
    assert ew._load_state(layout)["issue_mappings"]["6617"]["conversation"]["status"] == ew.CONVERSATION_ENDED


def test_failure_classes_are_distinct_and_status_reports_them(tmp_path, capsys):
    cases = {
        "[-32000] Authentication required": "authentication",
        "ACPAuthRequired [-32000] Authentication required": "authentication",
        "Claude AI usage limit reached|1731456000": "quota_exhausted",
        "You've hit your usage limit. Try again later.": "quota_exhausted",
        'ACPPromptError [-32603] Internal error: You\'ve hit your weekly limit · resets 2am (UTC): {"errorKind": "rate_limit"}': "quota_exhausted",
        'ACP error: [-32603] Internal error: You\'ve hit your session limit · resets 9pm (UTC): {"errorKind": "rate_limit"}': "quota_exhausted",
        "YOU’VE HIT YOUR WEEKLY LIMIT": "quota_exhausted",
        "429 Too Many Requests": "task_failure",
        "gh: API rate limit exceeded": "task_failure",
        'File "x.py", line 429': "task_failure",
        "Your credit balance is too low to access the Anthropic API": "policy",
        "OAuth token has expired": "authentication",
        "refresh token was already used; please sign in again": "authentication",
        "docker: --network none": "task_failure",
        "prompt is too long: 210000 tokens > 200000 maximum": "context_exhausted",
        "connect ECONNRESET 1.2.3.4:443": "transient_network",
        "pytest exited 1": "task_failure",
        "": "unclassified",
    }
    for text, expected in cases.items():
        assert ew.classify_failure(text) == expected, text

    root, engine, server = _setup(tmp_path, capsys)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    prompt = tmp_path / "p.md"
    prompt.write_text("x")
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    server.events = [
        {"kind": "MessageEvent", "source": "user"},
        {"kind": "AgentErrorEvent", "error": "Claude AI usage limit reached"},  # tool-level: never classified
        {"kind": "ConversationErrorEvent", "code": "ACPAuthRequired", "detail": "[-32000] Authentication required"},
    ]
    capsys.readouterr()
    assert _main(root, engine, server, "conversation-status", "--worker", "w-a") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["failure_class"] == "authentication" and report["execution_status"] == "running"

    for detail in (
        'Internal error: You\'ve hit your weekly limit · resets 2am (UTC): {"errorKind": "rate_limit"}',
        'Internal error: You\'ve hit your session limit · resets 9pm (UTC): {"errorKind": "rate_limit"}',
    ):
        server.events = [{"kind": "ConversationErrorEvent", "code": "ACPPromptError", "detail": detail}]
        assert _main(root, engine, server, "conversation-status", "--worker", "w-a") == 0
        assert json.loads(capsys.readouterr().out)["failure_class"] == "quota_exhausted"

        server.events = [
            {"kind": "AgentErrorEvent", "error": detail},
            {"kind": "MessageEvent", "source": "agent", "detail": detail},
        ]
        assert _main(root, engine, server, "conversation-status", "--worker", "w-a") == 0
        assert json.loads(capsys.readouterr().out)["failure_class"] is None


def test_status_uses_latest_page_and_newest_error_and_message(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    prompt = tmp_path / "p.md"
    prompt.write_text("x")
    assert _main(root, engine, server, "conversation-start", "--worker", "w-a", "--prompt-file", str(prompt)) == 0
    quota = "You've hit your weekly limit · resets 2am (UTC)"
    server.events = (
        [{"kind": "MessageEvent", "source": "user", "detail": "old"} for _ in range(55)]
        + [
            {"kind": "ConversationErrorEvent", "detail": "Authentication required"},
            {"kind": "MessageEvent", "source": "agent", "detail": "older reply"},
            {"kind": "ConversationErrorEvent", "detail": quota},
            {"kind": "MessageEvent", "source": "agent", "detail": "newest reply"},
            {"kind": "AgentErrorEvent", "error": "Authentication required"},
        ]
    )
    capsys.readouterr()
    assert _main(root, engine, server, "conversation-status", "--worker", "w-a") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["failure_class"] == "quota_exhausted"
    assert report["last_agent_message"]["detail"] == "newest reply"
    assert len(report["event_kinds"]) == 50

    server.events = server.events[:55] + [
        {"kind": "AgentErrorEvent", "error": quota},
        {"kind": "MessageEvent", "source": "agent", "detail": quota},
    ]
    assert _main(root, engine, server, "conversation-status", "--worker", "w-a") == 0
    assert json.loads(capsys.readouterr().out)["failure_class"] is None
