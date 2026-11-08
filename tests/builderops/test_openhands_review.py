import json
import sys
from pathlib import Path

import pytest

from app.builderops import openhands_review as review


def _fake_server(tmp_path: Path, *, account="chatgpt", workspace_mode="read", reroute=False) -> Path:
    script = tmp_path / "fake-codex"
    code = '''#!REVIEW_PYTHON
import json, os, sys
workspace = os.environ["OPENHANDS_FACTORY_WORKSPACE"]
roots = json.loads(os.environ["OPENHANDS_FACTORY_READ_ROOTS"])
head = "a" * 40
thread = "review-thread"
def send(message):
    print(json.dumps(message), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"id": request_id, "result": {}})
    elif method == "account/read":
        send({"id": request_id, "result": {"account": {"type": ACCOUNT}}})
    elif method == "config/read":
        filesystem = {":minimal": "read", ":workspace_roots": WORKSPACE_MODE}
        filesystem.update({root: "read" for root in roots})
        config = {"model": "gpt-6.1-terra", "model_provider": "openai",
                  "chatgpt_base_url": "https://chatgpt.com/backend-api/",
                  "features": {"multi_agent": False, "js_repl": False, "hooks": False,
                               "skill_mcp_dependency_install": False}, "web_search": "disabled",
                  "permissions": {"builder_factory": {"filesystem": filesystem, "network": {"enabled": False}}}}
        send({"id": request_id, "result": {"config": config}})
    elif method == "thread/start":
        send({"id": request_id, "result": {"thread": {"id": thread}, "cwd": workspace,
              "model": "gpt-6.1-terra", "modelProvider": "openai", "approvalPolicy": "never",
              "activePermissionProfile": {"id": "builder_factory"}}})
    elif method == "turn/start":
        turn = "review-turn"
        send({"id": request_id, "result": {"turn": {"id": turn}}})
        if REROUTE:
            send({"method": "model/rerouted", "params": {}})
        content = json.dumps({"head_sha": head, "verdict": "pass", "summary": "Reviewed actual diff", "findings": []})
        send({"method": "item/completed", "params": {"threadId": thread, "turnId": turn,
              "item": {"type": "agentMessage", "phase": "final_answer", "text": content}}})
        send({"method": "turn/completed", "params": {"threadId": thread,
              "turn": {"id": turn, "status": "completed", "error": None}}})
'''
    code = (code.replace("REVIEW_PYTHON", sys.executable).replace("ACCOUNT", repr(account))
            .replace("WORKSPACE_MODE", repr(workspace_mode)).replace("REROUTE", repr(reroute)))
    script.write_text(code)
    script.chmod(0o755)
    return script


@pytest.mark.parametrize("account,mode,passes", [("chatgpt", "read", True),
                                                  ("apiKey", "read", False),
                                                  ("chatgpt", "write", False)])
def test_review_uses_guarded_preflight_and_read_only_profile(tmp_path, account, mode, passes):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _fake_server(tmp_path, account=account, workspace_mode=mode)
    settings = {"codex_binary": str(executable), "sandbox_read_roots": [str(tmp_path)],
                "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']}
    args = review._read_only_args(settings)
    assert '":workspace_roots"="read"' in args[1]
    assert '":workspace_roots"="write"' not in args[1]
    if passes:
        result, text, thread = review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                                                  "Review this candidate", "worker-thread", timeout=10)
        assert result["verdict"] == "pass" and json.loads(text)["head_sha"] == "a" * 40
        assert thread == "review-thread"
    else:
        with pytest.raises(review.ReviewError, match="refused or failed") as error:
            review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                              "Review this candidate", "worker-thread", timeout=10)
        expected = "subscription authentication" if account == "apiKey" else "read-only sandbox profile"
        assert expected in str(error.value)


def test_review_rejects_ambiguous_or_conflicting_verdicts():
    head = "a" * 40
    with pytest.raises(review.ReviewError, match="not valid JSON"):
        review._parse_result("I cannot review this", head)
    with pytest.raises(review.ReviewError, match="not valid JSON"):
        review._parse_result('{"verdict":"unresolved","verdict":"pass"}', head)
    with pytest.raises(review.ReviewError, match="incomplete review"):
        review._parse_result(json.dumps({"head_sha": head, "verdict": "pass",
                                       "summary": "I cannot inspect the candidate", "findings": []}), head)
    with pytest.raises(review.ReviewError, match="conflicts"):
        review._parse_result(json.dumps({"head_sha": head, "verdict": "pass", "summary": "Reviewed",
                                       "findings": [{"severity": "P1", "description": "broken",
                                                     "file": "a.py", "line": 1}]}), head)


def test_review_fails_closed_on_model_reroute(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _fake_server(tmp_path, reroute=True)
    settings = {"codex_binary": str(executable), "sandbox_read_roots": [str(tmp_path)],
                "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']}
    with pytest.raises(review.ReviewError, match="model or process failure"):
        review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                          "Review this candidate", "worker-thread", timeout=10)


def test_review_imports_trusted_guard_before_competing_workspace_package(tmp_path):
    workspace = tmp_path / "workspace"
    package = workspace / "app/builderops"
    package.mkdir(parents=True)
    (workspace / "app/__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    marker = workspace / "untrusted-imported"
    (package / "openhands_proxy.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    executable = _fake_server(tmp_path)
    settings = {"codex_binary": str(executable), "sandbox_read_roots": [str(tmp_path)],
                "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']}
    result, _, _ = review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                                     "Review this candidate", "worker-thread", timeout=10)
    assert result["verdict"] == "pass"
    assert not marker.exists()


@pytest.mark.parametrize("stderr,expected", [
    ('Error: invalid transport in mcp_servers."claude-design"\nsecret-value', "inherited MCP transport"),
    ('Error: invalid :workspace_roots value\nsecret-value', "read-only workspace permission"),
    ("unexpected secret-value", "No recognized non-secret startup diagnostic"),
    ("x" * 100000 + "secret-value", "No recognized non-secret startup diagnostic"),
])
def test_review_startup_diagnostics_are_bounded_and_redacted(tmp_path, stderr, expected):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "failing-codex"
    executable.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write({stderr!r})\nsys.exit(73)\n")
    executable.chmod(0o755)
    settings = {"codex_binary": str(executable), "sandbox_read_roots": [str(tmp_path)],
                "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']}
    with pytest.raises(review.ReviewError) as error:
        review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                          "Review this candidate", "worker-thread", timeout=10)
    assert expected in str(error.value) and "exit 73" in str(error.value)
    assert "secret-value" not in str(error.value) and "claude-design" not in str(error.value)


def test_review_environment_does_not_include_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-value")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = _fake_server(tmp_path)
    settings = {"codex_binary": str(executable), "sandbox_read_roots": [str(tmp_path)],
                "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']}
    real_popen = review.subprocess.Popen
    captured = {}

    def popen(*args, **kwargs):
        captured.update(kwargs["env"])
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(review.subprocess, "Popen", popen)
    review.run_review(Path(sys.executable), settings, workspace, "a" * 40,
                      "Review this candidate", "worker-thread", timeout=10)
    assert "OPENAI_API_KEY" not in captured
    assert captured["OPENHANDS_FACTORY_READ_ONLY"] == "1"
