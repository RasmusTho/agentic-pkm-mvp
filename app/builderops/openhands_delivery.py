"""Run one explicitly authorized OpenHands Builder issue, without publication.

A state directory fences duplicate starts. Ambiguous effects require readback;
this entry point does not establish qualification of the host isolation profile.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.validate_issue_readiness import (
    _declared_verify_targets,
    _extract_acceptance_items,
    _has_concrete_verify_marker,
    classify_issue_body,
    extract_sections,
)
from scripts.pr_body_generator import generate_pr_body_from_mapping, resolve_native_issue_authority
from scripts import agent_worktree

from app.builderops import openhands_service as service
from app.builderops import publication

REPOSITORY = "RasmusTho/agentic-pkm-mvp"
INSTRUCTIONS = ("AGENTS.md", ".codex/skills/README.md", ".codex/skills/issue-to-code/SKILL.md")
MODEL = "gpt-6.1-terra"
ACP_VERSION = "2.2.2"
SERVER_VERSION = "1.60.1"
_FULL_PUBLICATION_PATH = ".codex/skills/publish-pr/FULL_PATH.md"
# OpenHands normally forwards its full environment to ACP. Do not give the
# agent-server session key (or any other inherited API secret) to the worker.
_ACP_BOOTSTRAP = (
    "import os,sys; "
    "e={k:v for k,v in os.environ.items() if not any("
    "s in k.upper() for s in ('API_KEY','APIKEY','TOKEN','SECRET','PASSWORD'))}; "
    "os.execve(sys.argv[1],sys.argv[1:],e)"
)



class DeliveryError(RuntimeError):
    """Preparation or execution cannot safely proceed."""


def _pytest_pass_count(source: str) -> int:
    """Accept one unambiguous complete pytest summary across retained output."""
    summary = re.compile(
        r"^\s*(?:=+\s*)?((?:[0-9]+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)"
        r"(?:,\s*)?)+)(?:\s+(in\s+\S+)(?:\s+\([0-9:.]+\))?)?\s*(?:=+)?\s*$", re.IGNORECASE
    )
    summary_like = re.compile(
        r"^\s*(?:=+\s*)?[0-9]+ [a-z]+(?:,\s*[0-9]+ [a-z]+)*"
        r"(?:\s+in\s+\S+(?:\s+\([0-9:.]+\))?)?\s*(?:=+)?\s*$", re.IGNORECASE
    )
    no_tests = re.compile(r"^\s*(?:=+\s*)?no tests (?:ran|collected)\b.*$", re.IGNORECASE)
    lines = source.splitlines()
    matches = [match for line in lines if (match := summary.fullmatch(line))]
    # stdout and stderr have no reliable combined ordering or summary provenance.
    # A second summary, even a positive one, cannot displace the real result.
    if (len(matches) != 1 or matches[0].group(2) is None
            or sum(bool(summary_like.fullmatch(line)) for line in lines) != 1
            or any(no_tests.match(line) for line in lines)):
        return 0
    counts = re.findall(r"([0-9]+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)",
                        matches[0].group(1), re.IGNORECASE)
    if any(int(count) and kind.lower() != "passed" for count, kind in counts):
        return 0
    return sum(int(count) for count, kind in counts if kind.lower() == "passed")


class _BoundWorkerKey(str):
    """Require a worker to prove key possession on the same TCP connection."""


def _run(
    command: list[str], *, allowed: tuple[int, ...] = (0,), timeout: float = 30
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeliveryError(f"Could not run {command[0]} readback") from exc
    if result.returncode not in allowed:
        raise DeliveryError(f"{command[0]} readback failed (exit {result.returncode})")
    return result


def _json_result(command: list[str]) -> Any:
    try:
        return json.loads(_run(command).stdout)
    except ValueError as exc:
        raise DeliveryError(f"{command[0]} returned invalid JSON") from exc


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _repository(root: Path) -> tuple[Path, str]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise DeliveryError("Repository root must be a directory")
    git = ["git", "--no-replace-objects", "-C", str(root)]
    top = Path(_run([*git, "rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
    if root != top:
        raise DeliveryError("Repository path must be the worktree root")
    remote = _run([*git, "remote", "get-url", "origin"]).stdout.strip()
    if remote not in {
        f"https://github.com/{REPOSITORY}.git", f"https://github.com/{REPOSITORY}",
        f"git@github.com:{REPOSITORY}.git", f"git@github.com:{REPOSITORY}",
        f"ssh://git@github.com/{REPOSITORY}.git", f"ssh://git@github.com/{REPOSITORY}",
    }:
        raise DeliveryError("Origin is not the authorized repository")
    head = _run([*git, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"]).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise DeliveryError("Cannot establish repository base commit")
    return root, head


def preview(root: Path, issue_number: int, branch: str, worktree: Path) -> dict[str, Any]:
    """Read an issue, candidate destination and existing PRs; perform no writes."""
    if type(issue_number) is not int or issue_number <= 0:
        raise DeliveryError("Issue must be a positive integer")
    root, head = _repository(root)
    git = ["git", "--no-replace-objects", "-C", str(root)]
    if not branch or branch.startswith("-") or "\0" in branch:
        raise DeliveryError("Invalid branch")
    _run([*git, "check-ref-format", "--branch", branch])
    branch_check = _run(
        [*git, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], allowed=(0, 1)
    )
    local_branch_exists = branch_check.returncode == 0
    if not worktree.is_absolute():
        raise DeliveryError("Worktree must be an absolute path")
    worktree_exists = worktree.exists() or worktree.is_symlink()
    parent = worktree.parent.resolve(strict=True)
    worktree = parent / worktree.name
    if worktree == root or parent == root or root in parent.parents:
        raise DeliveryError("Worktree must be outside the source checkout")

    issue = _json_result([
        "gh", "issue", "view", str(issue_number), "--repo", REPOSITORY,
        "--json", "number,title,body,state,labels,url,updatedAt",
    ])
    if not isinstance(issue, dict) or issue.get("number") != issue_number:
        raise DeliveryError("Issue readback did not match the requested issue")
    if issue.get("url") != f"https://github.com/{REPOSITORY}/issues/{issue_number}":
        raise DeliveryError("Issue readback did not match the authorized repository")
    if issue.get("state") != "OPEN":
        raise DeliveryError("Issue is not open")
    title, body, updated = issue.get("title"), issue.get("body"), issue.get("updatedAt")
    if (not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip()
            or not isinstance(updated, str) or not updated.strip()):
        raise DeliveryError("Issue contract or update timestamp is missing")
    raw_labels = issue.get("labels")
    if not isinstance(raw_labels, list) or any(
        not isinstance(label, dict) or not isinstance(label.get("name"), str)
        for label in raw_labels
    ):
        raise DeliveryError("Issue labels are unavailable")
    labels = [label["name"] for label in raw_labels]
    if [label for label in labels if label.startswith("agent:")] != ["agent:ready"]:
        raise DeliveryError("Issue does not have exactly agent:ready as its agent state")
    report = classify_issue_body(body, issue_number=issue_number, labels=labels, repo_root=root)
    if report.readiness_classification != "ready_candidate":
        raise DeliveryError(f"Issue readiness: {report.readiness_classification}")

    prs = _json_result([
        "gh", "pr", "list", "--repo", REPOSITORY, "--head", branch, "--state", "all",
        "--limit", "100", "--json", "number,state,isDraft,headRefName,headRefOid,url",
    ])
    if not isinstance(prs, list) or len(prs) >= 100 or any(
        not isinstance(pr, dict) or pr.get("headRefName") != branch
        or type(pr.get("number")) is not int or not isinstance(pr.get("url"), str)
        or not isinstance(pr.get("state"), str) or type(pr.get("isDraft")) is not bool
        or not isinstance(pr.get("headRefOid"), str)
        for pr in prs
    ):
        raise DeliveryError("PR readback is ambiguous; reconcile manually")
    instructions = {}
    for path in INSTRUCTIONS:
        text = _run([*git, "show", f"{head}:{path}"]).stdout
        if not text.strip():
            raise DeliveryError(f"Required repository instruction is empty: {path}")
        instructions[path] = {"sha256": _sha(text), "content": text}
    return {
        "kind": "openhands_delivery_preview.v1",
        "repository": REPOSITORY,
        "base_commit": head,
        "planned_branch": branch,
        "planned_worktree": str(worktree),
        "destination_collisions": {"local_branch_exists": local_branch_exists,
                                   "worktree_exists": worktree_exists},
        "issue": {"number": issue_number, "title": title, "body": body, "url": issue["url"],
                  "updated_at": updated, "labels": labels, "body_sha256": _sha(body)},
        "instructions": instructions,
        "matching_prs": prs,
        "readiness": "ready_candidate",
        "execution": "not_started",
        "notice": "Read-only preview; re-read issue, branch and PR state before any effect; "
                  "PR results are advisory and do not prove uniqueness.",
    }



def _effect(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                check=False, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeliveryError(f"{command[0]} outcome is uncertain; inspect state before retry") from exc
    if result.returncode:
        raise DeliveryError(
            f"{command[0]} failed (exit {result.returncode}); inspect state before retry"
        )
    return result.stdout


def _validate_executables(
    python: Path, node: Path, acp: Path, settings_file: Path
) -> dict[str, Any]:
    for name, path in (("Python", python), ("Node", node)):
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise DeliveryError(f"{name} must be an existing absolute executable")
    if not acp.is_absolute() or not acp.is_file() or not os.access(acp, os.R_OK):
        raise DeliveryError("ACP must be an existing absolute readable script")
    metadata = None
    for parent in (acp.resolve().parent, *acp.resolve().parents):
        candidate = parent / "package.json"
        if candidate.is_file():
            try:
                package = json.loads(candidate.read_text())
            except (OSError, ValueError) as exc:
                raise DeliveryError("Cannot inspect ACP package metadata") from exc
            if isinstance(package, dict) and package.get("name") == "@agentclientprotocol/codex-acp":
                metadata = package
                break
    if metadata is None or metadata.get("version") != ACP_VERSION:
        raise DeliveryError(f"codex-acp {ACP_VERSION} package metadata is required")
    settings = service._settings(settings_file)
    version = _run([str(python), "-c", "from importlib.metadata import version; "
                   "print(version('openhands-agent-server'))"]).stdout.strip()
    allowed_versions = {SERVER_VERSION, "1.62.0"} if settings.get("acp_effort") is not None else {SERVER_VERSION}
    if version not in allowed_versions:
        raise DeliveryError("OpenHands agent-server version is not admitted")
    if settings.get("acp_effort") is not None:
        probe = _run([str(python), "-c", "from openhands.sdk.settings.model import ACPAgentSettings; "
                      "assert 'acp_effort' in ACPAgentSettings.model_fields; print('acp-effort-supported')"], timeout=90)
        if probe.stdout.strip() != "acp-effort-supported":
            raise DeliveryError("Installed OpenHands ACP effort support is unavailable")
    trusted_guard = Path(__file__).resolve().parents[2] / "scripts/openhands_guarded_codex"
    if Path(settings["guard_executable"]).resolve() != trusted_guard.resolve():
        raise DeliveryError("Settings do not select the repository's guarded Codex executable")
    return settings


def _save(directory: Path, state: dict[str, Any], phase: str) -> None:
    state["phase"] = phase
    service._write(directory, state)


def _include_git_metadata(settings: dict[str, Any], root: Path) -> dict[str, Any]:
    """Allow Git readback for a linked worktree without granting write access."""
    result = _run(["git", "--no-replace-objects", "-C", str(root), "rev-parse",
                   "--path-format=absolute", "--git-common-dir"])
    git_dir = Path(result.stdout.strip()).resolve(strict=True)
    if not git_dir.is_dir():
        raise DeliveryError("Git metadata directory is unavailable")
    roots = list(settings["sandbox_read_roots"])
    if str(git_dir) not in roots:
        roots.append(str(git_dir))
    args = list(settings["codex_config_args"])
    matching = [i for i, arg in enumerate(args)
                if arg.startswith("permissions.builder_factory.filesystem=")]
    if len(matching) != 1:
        raise DeliveryError("Expected one factory filesystem profile setting")
    entries = ",".join(f"{json.dumps(path)}=\"read\"" for path in roots)
    args[matching[0]] = ('permissions.builder_factory.filesystem={":minimal"="read",'
                         '":workspace_roots"="write",' + entries + "}")
    return {**settings, "sandbox_read_roots": roots, "codex_config_args": args}


def _state(directory: Path) -> dict[str, Any]:
    result = service._read(directory)
    if result is None or result.get("kind") != "openhands_delivery_run.v1":
        raise DeliveryError("No valid delivery state in this directory")
    return result


def _server_key(directory: Path, state: dict[str, Any]) -> str:
    server_dir = directory / "server"
    try:
        observed = service.status(server_dir, timeout=5)
    except service.ServiceError as exc:
        raise DeliveryError("Recorded service readback unavailable") from exc
    server = observed.get("state")
    if (observed.get("status") != "running" or not isinstance(server, dict)
            or server.get("workspace") != state["worktree"] or server.get("port") != state["port"]):
        raise DeliveryError("Recorded service or workspace cannot be verified")
    if not (server_dir / "session-api-key").is_file():
        raise DeliveryError("Recorded service session key is unavailable")
    if state.get("kind") == "openhands_owner_service.v1" and server.get("control_only") is True:
        # The separate model-free owner backend predates the worker challenge
        # and is not a delivery worker. Preserve its existing session route.
        return service._session_key(server_dir, create=False)
    if server.get("delivery_identity_challenge") is not True:
        raise DeliveryError("Recorded worker lacks the verified identity challenge")
    return _BoundWorkerKey(service._session_key(server_dir, create=False))


def _worker_http(port: int, key: str, method: str, path: str, payload: Any, timeout: float) -> tuple[int, Any]:
    """Authenticate the worker before sending its key on the same socket."""
    script = """import hashlib, hmac, http.client, json, secrets, sys
v=json.load(sys.stdin)
c=http.client.HTTPConnection('127.0.0.1',v['port'],timeout=v['timeout'])
nonce=secrets.token_hex(32)
c.request('GET','/api/_builder_identity?nonce='+nonce)
r=c.getresponse()
digest=r.read(256).decode('ascii')
expected=hmac.new(v['key'].encode(),nonce.encode(),hashlib.sha256).hexdigest()
if r.status != 200 or not hmac.compare_digest(digest,expected) or c.sock is None:
    raise ValueError('worker identity not established')
peer=c.sock
body=None if v['payload'] is None else json.dumps(v['payload']).encode()
if c.sock is not peer:
    raise ValueError('worker connection changed')
c.request(v['method'],'/api'+v['path'],body=body,headers={'X-Session-API-Key':v['key'],'Content-Type':'application/json'})
r=c.getresponse()
data=r.read(4194305)
if len(data)>4194304:
    raise ValueError('worker response too large')
print(json.dumps({'status':r.status,'body':json.loads(data) if data else None}))
"""
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input=json.dumps({"port": port, "key": key, "method": method, "path": path,
                              "payload": payload, "timeout": timeout}),
            text=True, capture_output=True, check=True, timeout=timeout,
            env={name: os.environ[name] for name in ("PATH", "LANG") if name in os.environ},
        )
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or type(data.get("status")) is not int:
            raise ValueError("invalid worker response")
        return data["status"], data.get("body")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        raise DeliveryError("Worker identity or API readback unavailable") from exc


def _http(
    port: int, key: str, method: str, path: str, payload: Any = None, *, timeout: float = 5
) -> tuple[int, Any]:
    if isinstance(key, _BoundWorkerKey):
        return _worker_http(port, key, method, path, payload, timeout)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api{path}", data=data, method=method,
        headers={"X-Session-API-Key": key, "Content-Type": "application/json"},
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any) -> None:
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    except (OSError, urllib.error.URLError) as exc:
        raise DeliveryError("OpenHands API unavailable or outcome uncertain") from exc
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError as exc:
        raise DeliveryError("OpenHands API returned invalid JSON") from exc


def _conversation(directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    key = _server_key(directory, state)
    code, data = _http(state["port"], key, "GET", f"/conversations/{state['conversation_id']}")
    if code != 200 or not isinstance(data, dict):
        raise DeliveryError(f"Conversation readback unavailable (HTTP {code})")
    workspace = data.get("workspace")
    if (str(data.get("id")) != state["conversation_id"] or not isinstance(workspace, dict)
            or workspace.get("working_dir") != state["worktree"]):
        raise DeliveryError("Conversation identity or workspace mismatch")
    if state.get("acp_effort") is not None:
        agent = data.get("agent")
        if (not isinstance(agent, dict) or agent.get("kind") != "ACPAgent"
                or agent.get("acp_server") != "codex" or agent.get("acp_model") != state.get("acp_model")
                or agent.get("acp_effort") != state.get("acp_effort")):
            raise DeliveryError("Conversation selection readback mismatch")
        if data.get("execution_status") in ("finished", "FINISHED") and (
                data.get("current_model_id") != state.get("acp_model")
                or data.get("current_effort") != state.get("acp_effort")):
            raise DeliveryError("Finished conversation model or effort not verified")
    return data


def _task_prompt(plan: dict[str, Any], *, auto_finish: bool = False, test_python: Path | None = None) -> str:
    issue = plan["issue"]
    instructions = "\n\n".join(
        f"### {path}\n{entry['content']}" for path, entry in plan["instructions"].items()
    )
    handoff = ""
    if auto_finish:
        handoff = (
            "Before finishing, write .codex-tmp/openhands-finish.json as a private mode 0600 "
            "file (create .codex-tmp if needed). It is an ignored local handoff, not a commit. "
            "Use exactly this JSON object: version=1, issue=<issue number>, title=<concise PR "
            "title>, paths=<array of every changed repository-relative path>, risk_surfaces=<an "
            "array chosen from auth, security, data, migration, concurrency, external-api, "
            "credential-durability, state-machine>, and body=<PR body inputs>. If no listed risk "
            "applies, use an empty array instead of inventing one. Body must have "
            "summary (nonempty array), sbs_impact (object containing primary_subsystem, "
            "secondary_subsystems, write_class, persistence_impact, derived_rebuildable_impact, "
            "new_or_changed_contract, owner_doc_impact, transition_debt_impact, boundary_risk), "
            "owner_doc_resolution (none or updated), builderops_records, and builderops_reason. "
            "Use the issue contract and actual changes. Do not include claim data, review or test "
            "verdicts, publication instructions, or unrelated paths. The host independently "
            "checks the changed paths, tests, review and publication gates.\n\n"
        )
    return (
        f"Implement {plan['repository']} issue #{issue['number']}: {issue['title']}.\n"
        "You are a bounded worker. Work only in the assigned workspace. Do not claim, "
        "commit, push, publish, merge, access credentials, or make external effects. "
        "The delivery host handles publication and independent verification.\n\n"
        f"{handoff}"
        + (f"Use the prepared test interpreter {test_python} for the task's tests. "
           "Do not install packages or access the network.\n\n" if test_python else "")
        +
        f"## Full issue contract\n{issue['body']}\n\n"
        f"## Repository builder instructions\n{instructions}"
    )


def start(directory: Path, root: Path, issue: int, authorized_issue: int, branch: str,
          worktree: Path, python: Path, port: int, settings_file: Path,
          node: Path, acp: Path, *, auto_finish: bool = False, test_python: Path | None = None,
          test_environment_lock_sha256: str | None = None, expected_base: str | None = None) -> dict[str, Any]:
    if issue != authorized_issue or issue <= 0:
        raise DeliveryError("Explicit authorization must name the selected issue")
    if not 1 <= port <= 65535:
        raise DeliveryError("Port must be 1–65535")
    settings = _validate_executables(python, node, acp, settings_file)
    directory = directory.resolve()
    with service._locked(directory):
        if service._read(directory) is not None:
            raise DeliveryError("A delivery is already recorded; inspect it before retry")
        plan = preview(root, issue, branch, worktree)
        if expected_base is not None and plan["base_commit"] != expected_base:
            raise DeliveryError("Default branch changed after environment preflight; retry admission")
        if any(plan["destination_collisions"].values()) or plan["matching_prs"]:
            raise DeliveryError("Existing branch, worktree or PR requires reconciliation")
        root = root.resolve(strict=True)
        settings = _include_git_metadata(settings, root)
        worktree = Path(plan["planned_worktree"])
        if directory == worktree or worktree in directory.parents:
            raise DeliveryError("Delivery state must be outside the worker worktree")
        # Bind the exact validated configuration; the caller's file may change later.
        bound_settings = directory / "settings.json"
        # An interrupted pre-state start can leave this file behind. The lock,
        # absent state and fresh destination readback establish that no work was
        # started, so replace only that unclaimed configuration atomically.
        fd, temp_name = tempfile.mkstemp(prefix=".settings-", dir=directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(settings, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, bound_settings)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        session_id = str(uuid.uuid4())
        prompt = _task_prompt(plan, auto_finish=auto_finish, test_python=test_python)
        state: dict[str, Any] = {
            "version": 1, "kind": "openhands_delivery_run.v1", "issue": issue,
            "repository": REPOSITORY, "root": str(root), "branch": branch,
            "worktree": str(worktree), "base_commit": plan["base_commit"],
            "issue_body_sha256": plan["issue"]["body_sha256"], "prompt_sha256": _sha(prompt),
            "session_id": session_id, "agent_id": f"openhands-{session_id}",
            "conversation_id": session_id, "port": port,
            "auto_finish": auto_finish,
        }
        if "acp_model" in settings:
            state["acp_model"] = settings["acp_model"]
        if "acp_effort" in settings:
            state["acp_effort"] = settings["acp_effort"]
        if test_python is not None:
            if not test_environment_lock_sha256 or not re.fullmatch(r"[0-9a-f]{64}", test_environment_lock_sha256):
                raise DeliveryError("Prepared test environment lock identity is required")
            state["test_environment_lock_sha256"] = test_environment_lock_sha256
        git = ["git", "--no-replace-objects", "-C", str(root)]
        _save(directory, state, "creating_worktree")
        _effect([*git, "worktree", "add", "-b", branch, str(worktree), plan["base_commit"]])
        _save(directory, state, "claiming")
        factory_root = Path(__file__).resolve().parents[2]
        claim = _effect([
            str(factory_root / "scripts/issue_pickup_claim.sh"), "--issue", str(issue),
            "--repo", REPOSITORY, "--target-worktree", str(worktree),
            "--readiness-repo-root", str(worktree), "--agent", state["agent_id"],
            "--session", session_id,
        ], cwd=root)
        receipts = [line for line in claim.splitlines() if line.startswith("pickup-claim-complete ")]
        if (len(receipts) != 1 or f"issue={issue} " not in receipts[0]
                or f"branch={branch} " not in receipts[0]
                or f"worktree={worktree} coordination_mode=" not in receipts[0]):
            raise DeliveryError("Claim receipt is ambiguous; reconcile before continuing")
        state["pickup_receipt"] = receipts[0]
        _save(directory, state, "registering_worktree")
        _effect([sys.executable, str(factory_root / "scripts/agent_worktree.py"),
                 "--cwd", str(root), "register", "--worktree", str(worktree),
                 "--owner", session_id])
        current_issue = _json_result([
            "gh", "issue", "view", str(issue), "--repo", REPOSITORY,
            "--json", "number,title,body,state,url",
        ])
        if (not isinstance(current_issue, dict) or current_issue.get("number") != issue
                or current_issue.get("state") != "OPEN" or current_issue.get("url") != plan["issue"]["url"]
                or current_issue.get("title") != plan["issue"]["title"]
                or current_issue.get("body") != plan["issue"]["body"]):
            raise DeliveryError("Issue contract changed after claim; reconcile before continuing")
        _save(directory, state, "starting_service")
        try:
            service.start(directory / "server", python, worktree, port, bound_settings)
        except (service.ServiceError, OSError, ValueError) as exc:
            raise DeliveryError("Service launch failed or is uncertain; inspect state") from exc
        key = _server_key(directory, state)
        # The server process may exist before it starts listening. Only retry the
        # read-only probe; never retry a conversation creation with an unknown outcome.
        deadline = time.monotonic() + 90
        while True:
            try:
                code, _ = _http(port, key, "GET", f"/conversations/{session_id}")
            except DeliveryError:
                if time.monotonic() >= deadline:
                    raise DeliveryError("OpenHands service did not become ready; inspect state")
                time.sleep(0.5)
                continue
            if code == 404:
                break
            raise DeliveryError(f"Conversation identity is not available (HTTP {code})")
        payload = {
            "conversation_id": session_id,
            "workspace": {"working_dir": str(worktree)},
            "agent_settings": {"agent_kind": "acp", "acp_server": "codex",
                               "acp_command": [str(python), "-c", _ACP_BOOTSTRAP, str(node), str(acp)],
                               "acp_model": settings.get("acp_model", MODEL),
                               **({"acp_effort": settings["acp_effort"]} if settings.get("acp_effort") is not None else {})},
            "autotitle": False,
            "initial_message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
        }
        _save(directory, state, "creating_conversation")
        code, response = _http(port, key, "POST", "/conversations", payload, timeout=120)
        if code != 201 or not isinstance(response, dict):
            raise DeliveryError(f"Conversation creation outcome needs reconciliation (HTTP {code})")
        workspace = response.get("workspace")
        if (str(response.get("id")) != session_id or not isinstance(workspace, dict)
                or workspace.get("working_dir") != str(worktree)):
            raise DeliveryError("Conversation creation identity mismatch; reconcile before retry")
        _save(directory, state, "active")
        execution_status = response.get("execution_status")
        if execution_status not in {"idle", "running", "paused", "waiting_for_confirmation", "finished"}:
            raise DeliveryError(
                f"Conversation was created but reported {execution_status!r}; inspect status"
            )
        return {
            "state": state, "conversation_status": execution_status,
            "note": ("Watcher launch is separate; check its lease-heartbeat status." if auto_finish else
                     "Lease and worktree heartbeats are not automated; maintain them during the run."),
        }


def _bounded_recovery_child(port: int, key: str, child_id: str, timeout: float) -> tuple[int, Any]:
    """Read a local child response with a hard process deadline and bounded body."""
    if isinstance(key, _BoundWorkerKey):
        return _worker_http(port, key, "GET", f"/conversations/{child_id}", None, timeout)
    script = """import json, sys, urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
v = json.load(sys.stdin)
request = urllib.request.Request(
    'http://127.0.0.1:%d/api/conversations/%s' % (v['port'], v['id']),
    headers={'X-Session-API-Key': v['key']})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
response = opener.open(request, timeout=v['timeout'])
body = response.read(262145)
assert len(body) <= 262144
print(json.dumps({'status': response.status, 'body': json.loads(body)}))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input=json.dumps({"port": port, "id": child_id, "key": key, "timeout": timeout}),
            text=True, capture_output=True, check=True, timeout=timeout,
            env={name: os.environ[name] for name in ("PATH", "LANG") if name in os.environ},
        )
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or type(result.get("status")) is not int:
            raise ValueError("invalid response")
        return result["status"], result.get("body")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        raise DeliveryError("Delegated conversation readback unavailable") from exc


def _recovery_server_key(directory: Path, state: dict[str, Any]) -> str:
    """Read an existing key and a stable service identity without lifecycle locks."""
    server_dir = directory / "server"
    observed = service._read(server_dir)
    if (not isinstance(observed, dict) or service._status(observed) != "running"
            or observed.get("workspace") != state.get("worktree") or observed.get("port") != state.get("port")):
        raise DeliveryError("Recorded recovery service is unavailable")
    if observed.get("delivery_identity_challenge") is not True:
        raise DeliveryError("Recorded worker lacks the verified identity challenge")
    key = _BoundWorkerKey(service._session_key(server_dir, create=False))
    confirmed = service._read(server_dir)
    if (not isinstance(confirmed, dict) or service._status(confirmed) != "running"
            or any(confirmed.get(k) != observed.get(k) for k in
                   ("pid", "started", "marker", "workspace", "port", "delivery_identity_challenge"))):
        raise DeliveryError("Recorded recovery service changed")
    return key


def _recovery_conversation(directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    key = _recovery_server_key(directory, state)
    code, data = _bounded_recovery_child(state["port"], key, state["conversation_id"], 5)
    if code != 200 or not isinstance(data, dict):
        raise DeliveryError("Recovery conversation readback unavailable")
    workspace = data.get("workspace")
    if (str(data.get("id")) != state["conversation_id"] or not isinstance(workspace, dict)
            or workspace.get("working_dir") != state["worktree"]):
        raise DeliveryError("Recovery conversation identity or workspace mismatch")
    return data


def _recovery_observation(directory: Path, state: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    """Collect bounded, read-only evidence without inferring that unknown execution stopped."""
    observation: dict[str, Any] = {
        "continuation": "blocked",
        "execution": {"status": "unknown", "reason": "Native execution and detached descendants are not tracked"},
        "delegated_work": {"status": "unknown", "reason": "Native delegated processes are not tracked"},
        "worktree": {"status": "unknown"},
        "publication": {"status": "unknown"},
    }
    deadline = time.monotonic() + 15

    def remaining(limit: float) -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("recovery observation deadline reached")
        return min(limit, seconds)

    server_dir = directory / "server"
    try:
        server = service._read(server_dir) if server_dir.is_dir() else None
        if (not isinstance(server, dict) or service._status(server) != "running"
                or server.get("workspace") != state.get("worktree") or server.get("port") != state.get("port")):
            raise ValueError("recorded service does not match the delivery")
        root_pid = server["pid"]
        def process_rows() -> dict[int, dict[str, Any]]:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,pgid=,lstart=,stat="],
                capture_output=True, text=True, check=True, timeout=remaining(2),
            )
            parsed: dict[int, dict[str, Any]] = {}
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) != 9:
                    raise ValueError("invalid process snapshot")
                pid, ppid, pgid = map(int, fields[:3])
                parsed[pid] = {"pid": pid, "parent_pid": ppid, "process_group": pgid,
                               "started": " ".join(fields[3:8]), "state": fields[8]}
            return parsed
        rows = process_rows()
        after = service._read(server_dir)
        identity_keys = ("pid", "started", "marker", "workspace", "port")
        if (root_pid not in rows or rows[root_pid]["started"] != server.get("started")
                or not isinstance(after, dict) or service._status(after) != "running"
                or any(after.get(k) != server.get(k) for k in identity_keys)):
            raise ValueError("service identity changed")
        owned = {root_pid}
        while True:
            expanded = owned | {pid for pid, row in rows.items() if row["parent_pid"] in owned}
            if expanded == owned:
                break
            owned = expanded
        if len(owned) > 33:
            raise ValueError("too many candidate descendants")
        for pid in sorted(owned):
            remaining(2)
            current = service._identity(pid)
            if current is None or current[0] != rows[pid]["started"]:
                raise ValueError("candidate process identity changed during observation")
        again = process_rows()
        for pid in owned:
            if pid not in again or any(again[pid][name] != rows[pid][name]
                                       for name in ("parent_pid", "process_group", "started")):
                raise ValueError("candidate ancestry changed during observation")
        final_server = service._read(server_dir)
        if (not isinstance(final_server, dict) or service._status(final_server) != "running"
                or any(final_server.get(k) != server.get(k) for k in identity_keys)):
            raise ValueError("recorded service changed during observation")
        observation["execution"]["candidate_descendant_count"] = len(owned - {root_pid})
        observation["execution"]["visibility"] = (
            "Candidate ancestry was rechecked, but process enumeration is not atomic; detached work may be missing"
        )
    except (service.ServiceError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass

    children = parent.get("sub_conversation_ids")
    if isinstance(children, list):
        try:
            key = _recovery_server_key(directory, state)
            queue = [(state["conversation_id"], child) for child in children]
            seen: set[str] = {state["conversation_id"]}
            details: list[dict[str, str]] = []
            while queue:
                if len(seen) > 32:
                    raise ValueError("too many delegated conversations")
                parent_id, child = queue.pop(0)
                child_id = str(uuid.UUID(child))
                if child_id != child or child_id in seen:
                    raise ValueError("invalid delegated conversation identity")
                seen.add(child_id)
                code, detail = _bounded_recovery_child(state["port"], key, child_id, remaining(3))
                if (code != 200 or not isinstance(detail, dict) or str(detail.get("id")) != child_id
                        or detail.get("parent_conversation_id") != parent_id
                        or not isinstance(detail.get("workspace"), dict)
                        or not isinstance(detail["workspace"].get("working_dir"), str)
                        or not isinstance(detail.get("execution_status"), str)
                        or not isinstance(detail.get("sub_conversation_ids"), list)):
                    raise ValueError("delegated conversation readback unavailable")
                workspace_state = "parent" if detail["workspace"]["working_dir"] == state["worktree"] else "unverified"
                details.append({"id": child_id, "parent_id": parent_id, "status": detail["execution_status"],
                                "workspace": workspace_state})
                queue.extend((child_id, nested) for nested in detail["sub_conversation_ids"])
            observation["delegated_work"]["openhands_conversations"] = details
        except (DeliveryError, service.ServiceError, OSError, ValueError, KeyError, TypeError, AttributeError):
            observation["delegated_work"]["openhands_readback"] = "unknown"

    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    def git(cwd: Path, *args: str) -> str:
        command = ["git", "--no-replace-objects", "-C", str(cwd), "-c", "core.fsmonitor=false",
                   "-c", "core.hooksPath=/dev/null", "-c", "diff.external=", *args]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True,
                                    env=env, timeout=remaining(2))
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeliveryError("Recovery Git readback is unavailable") from exc
        return result.stdout

    try:
        worktree = Path(state["worktree"]).resolve(strict=True)
        repo = Path(state["root"]).resolve(strict=True)
        config = git(worktree, "config", "--local", "--no-includes", "--name-only", "--list").splitlines()
        if any(key.startswith(("filter.", "include.", "includeif.", "core.fsmonitor", "extensions.worktreeconfig"))
               for key in config):
            raise ValueError("executable or included Git configuration is unsupported")
        root = git(worktree, "rev-parse", "--show-toplevel").strip()
        branch = git(worktree, "branch", "--show-current").strip()
        head = git(worktree, "rev-parse", "HEAD").strip()
        common = Path(git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).resolve(strict=True)
        repo_common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).resolve(strict=True)
        registered = git(repo, "worktree", "list", "--porcelain", "-z")
        records = [part.split("\0") for part in registered.split("\0\0") if part]
        if (Path(root).resolve(strict=True) != worktree or common != repo_common or branch != state["branch"]
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head)
                or sum(f"worktree {worktree}" in record and f"branch refs/heads/{branch}" in record
                       for record in records) != 1):
            raise ValueError("worktree identity mismatch")
        dirty = git(worktree, "status", "--porcelain=v1", "-z")
        observation["worktree"] = {"status": "observed", "branch": branch, "head": head,
                                   "dirty": bool(dirty), "status_sha256": _sha(dirty),
                                   "note": "Point-in-time readback; unverified execution may still change it"}
        if state.get("repository") == REPOSITORY:
            prs = publication._read_pr_history(publication.SubprocessExecutor(timeout_seconds=remaining(3)),
                                               worktree, REPOSITORY, branch)
            matches = []
            for pr in prs:
                head_data, base_data = pr.get("head"), pr.get("base")
                if (type(pr.get("number")) is not int or pr["number"] <= 0
                        or type(pr.get("draft")) is not bool or pr.get("state") not in {"open", "closed"}
                        or (pr.get("merged_at") is not None and not isinstance(pr.get("merged_at"), str))
                        or not isinstance(head_data, dict) or head_data.get("ref") != branch
                        or not isinstance(head_data.get("repo"), dict)
                        or head_data["repo"].get("full_name") != REPOSITORY
                        or not isinstance(base_data, dict) or not isinstance(base_data.get("repo"), dict)
                        or base_data["repo"].get("full_name") != REPOSITORY
                        or not isinstance(head_data.get("sha"), str)
                        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head_data["sha"])):
                    raise ValueError("PR identity is unavailable")
                matches.append({"number": pr["number"], "state": pr["state"], "draft": pr["draft"],
                                "merged": pr.get("merged_at") is not None, "head": head_data["sha"]})
            observation["publication"] = {"status": "ambiguous" if len(matches) > 1 else "observed",
                                          "matching_prs": matches}
    except (DeliveryError, publication.PublicationRefusal, publication.PublicationCommandError,
            OSError, KeyError, TypeError, ValueError):
        pass
    return observation


def status(directory: Path) -> dict[str, Any]:
    """Read atomic state without waiting for a long-running delivery operation."""
    try:
        info = directory.lstat()
    except FileNotFoundError as exc:
        raise DeliveryError("No valid delivery state in this directory") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise service.ServiceError("State directory must be private and owned by the current user")
    state = _state(directory)
    result: dict[str, Any] = {"state": state}
    server_dir = directory / "server"
    if server_dir.is_dir():
        try:
            result["service_status"] = service._status(service._read(server_dir))
        except (service.ServiceError, OSError) as exc:
            result["service_status_error"] = str(exc)
    if state["phase"] in {"creating_conversation", "active", "interrupting", "interrupted", "resuming"}:
        data: dict[str, Any] = {}
        try:
            data = (_recovery_conversation(directory, state)
                    if state["phase"] in {"interrupting", "interrupted", "resuming"}
                    else _conversation(directory, state))
        except (DeliveryError, service.ServiceError) as exc:
            result["conversation_readback_error"] = str(exc)
        else:
            result["conversation_status"] = data.get("execution_status")
            if state.get("acp_effort") is not None:
                result["current_model_id"] = data.get("current_model_id")
                result["current_effort"] = data.get("current_effort")
            result["sub_conversation_ids"] = data.get("sub_conversation_ids")
        if state["phase"] in {"interrupting", "interrupted", "resuming"}:
            result["recovery"] = _recovery_observation(directory, state, data)
    refreshed = _state(directory)
    if refreshed != state:
        return {"state": refreshed, "snapshot_notice": "Delivery state changed during status; retry for live readback"}
    return result


def cancel(directory: Path) -> dict[str, Any]:
    # A concurrent start may hold this lock during conversation creation.
    # Return an unresolved result rather than waiting indefinitely.
    with service._locked(directory, timeout=5):
        state = _state(directory)
        if state["phase"] not in {"creating_conversation", "active", "interrupting", "interrupted", "resuming"}:
            raise DeliveryError("Conversation outcome is uncertain; inspect before cancellation")
        observed = _conversation(directory, state)
        if observed.get("execution_status") == "paused":
            if state["phase"] not in {"interrupting", "interrupted"}:
                raise DeliveryError("Pause cause is unknown; inspect before continuing")
            _save(directory, state, "interrupted")
            return {"state": state, "conversation_status": "paused",
                    "note": "Delegated processes require independent cancellation verification"}
        if observed.get("execution_status") != "running":
            raise DeliveryError("Conversation is not running; no interrupt sent")
        key = _server_key(directory, state)
        try:
            with service._locked(directory / "input-fence", timeout=5):
                with service._locked(directory / "execution-fence", timeout=5):
                    _save(directory, state, "interrupting")
        except service.ServiceError as exc:
            raise DeliveryError("Cannot interrupt while delivery input is still being processed") from exc
        # The upstream handler can wait five seconds for ACP cancellation;
        # include time for the identity handshake and transport as well.
        code, _ = _http(state["port"], key, "POST", f"/conversations/{state['conversation_id']}/interrupt", timeout=15)
        if code != 200:
            raise DeliveryError(f"Interrupt outcome uncertain (HTTP {code})")
        try:
            confirmed = _conversation(directory, state)
        except DeliveryError as exc:
            return {"state": state, "cancel_status": "requested_unverified",
                    "conversation_readback_error": str(exc)}
        execution_status = confirmed.get("execution_status")
        if execution_status == "paused":
            _save(directory, state, "interrupted")
        return {"state": state, "conversation_status": execution_status,
                "cancel_status": "paused" if execution_status == "paused" else "requested_unverified",
                "note": "Delegated-process stop is unverified"}


def resume(directory: Path) -> dict[str, Any]:
    with service._locked(directory):
        state = _state(directory)
        if state["phase"] != "interrupted":
            raise DeliveryError("Only a previously interrupted conversation can be resumed")
        observed = _conversation(directory, state)
        if observed.get("execution_status") != "paused":
            raise DeliveryError("Only an observed paused conversation can be resumed")
        # OpenHands reports the conversation state, not whether the previous
        # native command and its descendants can still write. Until the runtime
        # can establish those identities and reconcile effects, replaying the
        # interrupted prompt can duplicate partially completed work.
        raise DeliveryError(
            "Continuation unavailable: previous execution and delegated work have not been "
            "independently reconciled; the recorded task and workspace are preserved"
        )


class DraftOnlyExecutor:
    """Extend the owning publication adapter without permitting a ready PR."""

    def __init__(self, delegate: publication.CommandExecutor | None = None) -> None:
        self.delegate = delegate or publication.SubprocessExecutor()

    def run(
        self, argv: Any, *, cwd: Path, input_text: str | None = None
    ) -> publication.CommandResult:
        command = list(argv)
        if command[:2] == ["git", "merge"]:
            raise publication.PublicationRefusal("unsupported", "Merge is not draft publication")
        if command and command[0] == "gh":
            if command[:3] == ["gh", "pr", "create"]:
                if "--draft" not in command:
                    command.append("--draft")
            elif (len(command) >= 7 and command[:4] == ["gh", "api", "--hostname", "github.com"]
                  and command[4] == "--method"):
                method, endpoint = command[5:7]
                allowed = (method == "GET" or
                           (method == "POST" and endpoint == f"repos/{REPOSITORY}/git/refs") or
                           (method == "PATCH" and re.fullmatch(
                               rf"repos/{re.escape(REPOSITORY)}/pulls/[1-9][0-9]*", endpoint)))
                if not allowed:
                    raise publication.PublicationRefusal("unsupported", "GitHub effect is not draft publication")
            else:
                raise publication.PublicationRefusal("unsupported", "GitHub operation is not draft publication")
        result = self.delegate.run(command, cwd=cwd, input_text=input_text)
        if (result.returncode == 0 and command[:2] == ["gh", "api"]
                and "GET" in command and f"repos/{REPOSITORY}/pulls" in command):
            try:
                prs = json.loads(result.stdout)
            except ValueError as exc:
                raise publication.PublicationRefusal("unknown", "PR history is not JSON") from exc
            if not isinstance(prs, list) or any(
                not isinstance(pr, dict) or pr.get("draft") is not True for pr in prs
            ):
                raise publication.PublicationRefusal(
                    "unknown", "PR history includes a non-draft or unknown PR"
                )
        return result


def _finished_run(directory: Path) -> dict[str, Any]:
    state = _state(directory)
    if state.get("repository") != REPOSITORY or state.get("phase") != "active":
        raise DeliveryError("Run is not an active delivery in the authorized repository")
    observed = _conversation(directory, state)
    if observed.get("execution_status") != "finished":
        raise DeliveryError("Worker conversation has not finished; publication refused")
    children = observed.get("sub_conversation_ids")
    if not isinstance(children, list):
        raise DeliveryError("Delegated conversation completion is unverified")
    if children:
        key = _server_key(directory, state)
        for child in children:
            try:
                child_id = str(uuid.UUID(child))
            except (ValueError, TypeError, AttributeError) as exc:
                raise DeliveryError("Delegated conversation identity is invalid") from exc
            code, detail = _http(state["port"], key, "GET", f"/conversations/{child_id}")
            if (code != 200 or not isinstance(detail, dict) or str(detail.get("id")) != child_id
                    or detail.get("parent_conversation_id") != state["conversation_id"]
                    or not isinstance(detail.get("workspace"), dict)
                    or detail["workspace"].get("working_dir") != state["worktree"]
                    or detail.get("execution_status") != "finished"
                    or detail.get("sub_conversation_ids") != []):
                raise DeliveryError("Delegated conversation completion is unverified")
    return state


def _require_normal_publication_route(risk_surfaces: tuple[str, ...]) -> None:
    """Preserve explicitly identified risk; do not manufacture review evidence."""
    unknown = set(risk_surfaces) - publication.RISK_SURFACES
    if unknown:
        raise DeliveryError(f"Unknown publication risk surfaces: {', '.join(sorted(unknown))}")
    risks = set(risk_surfaces)
    if risks:
        raise DeliveryError(
            f"High-risk publication ({', '.join(sorted(risks))}) requires "
            f"{_FULL_PUBLICATION_PATH}; use publish-full with independent review evidence"
        )


def publication_plan(
    directory: Path, paths: list[str], title: str, message: str, body_inputs: dict[str, Any],
    *, tier: int, risk_surfaces: tuple[str, ...], risk_assessment_complete: bool,
    review_gate_complete: bool, executor: publication.CommandExecutor | None = None,
) -> dict[str, Any]:
    """Read the live candidate and produce the owning workflow's publication plan."""
    with service._locked(directory):
        _require_normal_publication_route(risk_surfaces)
        state = _finished_run(directory)
        issue = state.get("issue")
        receipt = state.get("pickup_receipt")
        if type(issue) is not int or issue <= 0 or not isinstance(receipt, str):
            raise DeliveryError("Recorded issue or pickup receipt is unavailable")
        body = dict(body_inputs)
        if body.get("issue_number", issue) != issue or body.get("pickup_receipt", receipt) != receipt:
            raise DeliveryError("PR body conflicts with the recorded issue or pickup receipt")
        if body.get("lane") != "implementation":
            raise DeliveryError("This publisher supports the implementation lane only")
        body.update(issue_number=issue, pickup_receipt=receipt)
        worker_tree = Path(state["worktree"])
        runner = DraftOnlyExecutor(executor)
        # All-state history is read before constructing either a new or existing plan.
        history = publication._read_pr_history(runner, worker_tree, REPOSITORY, state["branch"])
        if len(history) > 1:
            raise DeliveryError("Multiple PRs share the branch; reconcile before publication")
        existing_pr = history[0].get("number") if history else None
        if history and (type(existing_pr) is not int or history[0].get("state") != "open"):
            raise DeliveryError("Existing PR history is terminal or ambiguous")
        request = publication.PublicationRequest(
            repository=REPOSITORY, worktree=worker_tree, branch=state["branch"], base_ref="main",
            intended_paths=tuple(paths), lane="implementation", tier=tier,
            risk_surfaces=risk_surfaces, risk_assessment_complete=risk_assessment_complete,
            review_gate_complete=review_gate_complete, governing_issue=issue,
            commit_message=message, pr_title=title, pr_body_inputs=body,
            existing_pr_number=existing_pr,
        )
        plan = publication.build_publication_plan(request, executor=runner)
        if plan["governing_issue"]["body_sha256"] != state.get("issue_body_sha256"):
            raise DeliveryError("Issue contract changed since the worker started")
        return plan


def _check_readback(
    executor: publication.CommandExecutor, worktree: Path, commit_sha: str
) -> dict[str, Any]:
    """Read current GitHub check runs and combined status for the exact commit."""
    prefix = ["gh", "api", "--hostname", "github.com", "--method", "GET"]
    result = executor.run([*prefix, f"repos/{REPOSITORY}/commits/{commit_sha}/check-runs",
                           "-f", "per_page=100"], cwd=worktree)
    if result.returncode:
        raise DeliveryError("PR exists but GitHub check-run readback is unavailable")
    try:
        runs = json.loads(result.stdout)
    except ValueError as exc:
        raise DeliveryError("PR exists but GitHub check-run readback is malformed") from exc
    if (not isinstance(runs, dict) or not isinstance(runs.get("check_runs"), list)
            or type(runs.get("total_count")) is not int
            or runs["total_count"] != len(runs["check_runs"])):
        raise DeliveryError("PR exists but GitHub check-run readback is incomplete")
    checks = []
    for check in runs["check_runs"]:
        if (not isinstance(check, dict) or check.get("head_sha") != commit_sha
                or not isinstance(check.get("name"), str)
                or not isinstance(check.get("status"), str)):
            raise DeliveryError("PR exists but GitHub check-run identity is ambiguous")
        checks.append({key: check.get(key) for key in ("id", "name", "status", "conclusion", "started_at", "html_url")})
    result = executor.run([*prefix, f"repos/{REPOSITORY}/commits/{commit_sha}/status",
                           "-f", "per_page=100"], cwd=worktree)
    if result.returncode:
        raise DeliveryError("PR exists but GitHub commit-status readback is unavailable")
    try:
        combined = json.loads(result.stdout)
    except ValueError as exc:
        raise DeliveryError("PR exists but GitHub commit-status readback is malformed") from exc
    if (not isinstance(combined, dict) or combined.get("sha") != commit_sha
            or not isinstance(combined.get("state"), str)
            or not isinstance(combined.get("statuses"), list)
            or type(combined.get("total_count")) is not int
            or combined["total_count"] != len(combined["statuses"])):
        raise DeliveryError("PR exists but GitHub commit-status identity is ambiguous")
    statuses = []
    for status_item in combined["statuses"]:
        if (not isinstance(status_item, dict) or not isinstance(status_item.get("context"), str)
                or not isinstance(status_item.get("state"), str)):
            raise DeliveryError("PR exists but GitHub commit-status readback is malformed")
        statuses.append({key: status_item.get(key) for key in ("context", "state", "target_url")})
    return {"commit": commit_sha, "check_runs": checks, "combined_status": combined["state"],
            "statuses": statuses}


def publish(
    directory: Path, plan: dict[str, Any], expected_hash: str,
    verified_hash: str, reviewed_hash: str,
    *, executor: publication.CommandExecutor | None = None,
) -> dict[str, Any]:
    """Apply an exact plan after host-side test and independent-review attestations."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or (
        expected_hash != verified_hash or expected_hash != reviewed_hash
    ):
        raise DeliveryError("Test and independent review attestations must name the exact plan hash")
    with service._locked(directory):
        state = _finished_run(directory)
        plan = publication._validated_plan(plan, expected_hash)
        _require_normal_publication_route(tuple(plan["risk_surfaces"]))
        if (plan.get("plan_sha256") != expected_hash
                or publication.publication_plan_hash(plan) != expected_hash
                or plan.get("repository") != REPOSITORY
                or plan.get("worktree") != state.get("worktree")
                or plan.get("git", {}).get("branch") != state.get("branch")
                or plan.get("governing_issue", {}).get("number") != state.get("issue")
                or plan.get("governing_issue", {}).get("body_sha256") != state.get("issue_body_sha256")
                or plan.get("pr", {}).get("body_inputs", {}).get("pickup_receipt") != state.get("pickup_receipt")):
            raise DeliveryError("Publication plan does not bind the recorded run and issue")
        runner = DraftOnlyExecutor(executor)
        previous_checks = None
        if plan["pr"].get("existing"):
            previous_checks = _check_readback(
                runner, Path(state["worktree"]), plan["pr"]["existing"]["head"]["sha"]
            )
        # Existing exact PRs may be reconciled early by the owning adapter, so
        # apply the same workspace and review gates for that path as well.
        publication._run_workspace_gate(runner, Path(state["worktree"]), plan)
        if plan["pr"].get("existing"):
            publication._run_review_gate(runner, Path(state["worktree"]), plan)
        # Persist the intended plan before any effect. The owning adapter re-reads
        # branch, issue, diff and PR state, and reconciles uncertain effects.
        existing = state.get("publication")
        if existing is not None and (not isinstance(existing, dict) or existing.get("plan_sha256") != expected_hash):
            raise DeliveryError("A different publication attempt is already recorded")
        state["publication"] = {**(existing or {}), "plan_sha256": expected_hash,
                                "state": "applying"}
        service._write(directory, state)
        receipt = publication.apply_publication_plan(
            plan, expected_plan_sha256=expected_hash, executor=runner,
        )
        state["publication"] = {"plan_sha256": expected_hash, "state": "readback_pending",
                                "receipt": receipt}
        service._write(directory, state)
        worktree = Path(state["worktree"])
        checks = _check_readback(runner, worktree, receipt["commit_sha"])
        _, remote_head, prs = publication._transition_readback(
            runner, worktree, plan, receipt["commit_sha"]
        )
        final_pr = publication._resolve_pr_history(plan, prs, receipt["commit_sha"])
        if (remote_head != receipt["commit_sha"] or final_pr is None or len(prs) != 1
                or final_pr.get("number") != receipt["pr"]["number"]):
            raise DeliveryError("Draft PR or branch changed during check readback")
        state["publication"] = {"plan_sha256": expected_hash, "state": "draft_published",
                                "receipt": receipt, "checks": checks}
        service._write(directory, state)
        return {"receipt": receipt, "draft": True, "checks": checks,
                "previous_checks": previous_checks,
                "validation": "Host supplied test and review attestations; independent evidence was not verified here."}


def _evidence_artifact(reference: Any, evidence_dir: Path, worktree: Path, *,
                       excluded_roots: tuple[Path, ...] = ()) -> tuple[str, str]:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise DeliveryError("Review or verification evidence path is missing")
    value = reference["path"]
    path = Path(value)
    if not path.is_absolute():
        path = evidence_dir / path
    path = path.resolve(strict=True)
    if (path == worktree or worktree in path.parents or not path.is_file()
            or any(path == root or root in path.parents for root in excluded_roots)):
        raise DeliveryError("Evidence must be a host-side file outside the worker worktree")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data or (reference.get("sha256") is not None and reference["sha256"] != digest):
        raise DeliveryError("Review or verification evidence is empty or has changed")
    try:
        return digest, data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DeliveryError("Review and verification evidence must be readable text") from exc



def _doc_writeback_path(target: str) -> str | None:
    """Accept a concrete, repository-relative document and heading declaration."""
    match = re.fullmatch(r"doc writeback at `((?:docs|\.codex)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.md) :: ([^`\n]+)`", target)
    if not match or any(part in {".", ".."} for part in match.group(1).split("/")):
        return None
    return match.group(1)


def _candidate_document_is_regular(worktree: Path, head: str, path: str) -> bool:
    """Read the exact candidate tree, without following worktree symlinks."""
    output = _run(["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(worktree),
                   "ls-tree", "-z", "--full-tree", head, "--", path]).stdout
    return re.fullmatch(r"100(?:644|755) blob [0-9a-f]{40}(?:[0-9a-f]{24})?\t" + re.escape(path) + "\x00", output) is not None


def _full_evidence(
    receipt_file: Path, state: dict[str, Any], head: str, base: str, issue_body: str,
    *, excluded_roots: tuple[Path, ...] = (),
    closing_contracts: dict[int, str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Check host-provided sources and their bindings; do not claim signer authentication."""
    receipt_file = receipt_file.resolve(strict=True)
    worktree = Path(state["worktree"]).resolve(strict=True)
    if (receipt_file == worktree or worktree in receipt_file.parents
            or any(receipt_file == root or root in receipt_file.parents for root in excluded_roots)):
        raise DeliveryError("Evidence receipt must be outside the worker worktree")
    raw = receipt_file.read_bytes()
    try:
        receipt = json.loads(raw)
    except ValueError as exc:
        raise DeliveryError("Full-path evidence receipt is not valid JSON") from exc
    if (not isinstance(receipt, dict) or receipt.get("version") != 1
            or receipt.get("repository") != REPOSITORY or receipt.get("issue") != state["issue"]
            or receipt.get("head_sha") != head or receipt.get("base_sha") != base):
        raise DeliveryError("Full-path evidence does not bind the current issue and candidate")
    risks = receipt.get("risk_surfaces")
    if (not isinstance(risks, list) or any(not isinstance(r, str) for r in risks)
            or len(set(risks)) != len(risks) or set(risks) - publication.RISK_SURFACES):
        raise DeliveryError("Full-path evidence does not contain the applicable risk classification")
    source_digests = []
    workflow_review = receipt.get("workflow_review_receipt")
    if workflow_review is not None:
        digest, _ = _evidence_artifact(workflow_review, receipt_file.parent, worktree, excluded_roots=excluded_roots)
        source_digests.append(digest)
    fallback = receipt.get("stateful_fallback", False)
    if type(fallback) is not bool or (
        fallback and receipt.get("stateful_fallback_matrix_complete") is not True
    ):
        raise DeliveryError("Stateful fallback requires its executable boundary matrix")
    if fallback and not risks:
        raise DeliveryError("Stateful fallback requires an applicable risk surface")
    review = receipt.get("review")
    if (not isinstance(review, dict) or review.get("verdict") != "pass"
            or review.get("head_sha") != head
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or review["reviewer"] in {state.get("agent_id"), state.get("session_id")}
            or review.get("blocking_findings") != []):
        raise DeliveryError("Independent convergence review is missing, blocking, or stale")
    digest, review_text = _evidence_artifact(review.get("evidence"), receipt_file.parent, worktree, excluded_roots=excluded_roots)
    source_digests.append(digest)
    if head not in review_text:
        raise DeliveryError("Review source does not identify the candidate commit")
    contracts = closing_contracts if closing_contracts else {state["issue"]: issue_body}
    scope_hashes = {str(number): _sha(body) for number, body in contracts.items()}
    scope_hashes[str(state["issue"])] = _sha(issue_body)
    multi_scope = len(scope_hashes) > 1
    if multi_scope and (review.get("scope_issue_body_sha256") != scope_hashes
                        or any(digest not in review_text for digest in scope_hashes.values())):
        raise DeliveryError("Independent review does not bind all current Issue contracts")
    targets = []
    for body in contracts.values():
        acceptance = extract_sections(body).get("acceptance criteria", "")
        items = _extract_acceptance_items(acceptance)
        if not items or any(not _has_concrete_verify_marker(item) for item in items):
            raise DeliveryError("Issue Verify targets cannot be resolved for this full path")
        for item in items:
            for raw_target in _declared_verify_targets(item):
                quoted = re.fullmatch(r"`([^`]+)`(?:\s+.*)?", raw_target)
                targets.append(quoted[1] if quoted else raw_target)
    if any(target.startswith("doc writeback at ") and not _doc_writeback_path(target) for target in targets):
        raise DeliveryError("Document writeback target cannot be resolved for independent review")
    doc_targets = list(dict.fromkeys(target for target in targets if _doc_writeback_path(target)))
    if doc_targets:
        from app.builderops import openhands_review
        try:
            parsed_review = openhands_review._parse_result(review_text, head, doc_targets)
        except openhands_review.ReviewError as exc:
            raise DeliveryError("Document writeback review source is incomplete or stale") from exc
        if ((not multi_scope and review.get("issue_body_sha256") != _sha(issue_body))
                or parsed_review["verdict"] != "pass"
                or any(check["result"] != "pass" for check in parsed_review["doc_writebacks"])):
            raise DeliveryError("Document writeback review did not establish a pass for the current Issue")
        changed = set(_run(["git", "--no-replace-objects", "-C", str(worktree), "diff", "--name-only", base, head, "--"]).stdout.splitlines())
        if any(_doc_writeback_path(target) not in changed for target in doc_targets):
            raise DeliveryError("Document writeback target was not changed in the candidate")
        for target in doc_targets:
            path = _doc_writeback_path(target)
            if path is None or not _candidate_document_is_regular(worktree, head, path):
                raise DeliveryError("Document writeback target is not a regular tracked candidate file")
    verification = receipt.get("verification")
    if not isinstance(verification, list) or (not verification and not doc_targets):
        raise DeliveryError("Candidate verification evidence is missing")
    covered = set(doc_targets)
    test_runs: dict[str, tuple[int, set[str]]] = {}
    for entry in verification:
        if (not isinstance(entry, dict) or not isinstance(entry.get("target"), str)
                or entry.get("head_sha") != head or entry.get("result") != "pass"):
            raise DeliveryError("Candidate verification is missing, failed, or stale")
        digest, source = _evidence_artifact(entry.get("evidence"), receipt_file.parent, worktree, excluded_roots=excluded_roots)
        source_digests.append(digest)
        target = entry["target"]
        if target.startswith("tests/"):
            passed = _pytest_pass_count(source)
            if not passed:
                raise DeliveryError("Test source does not substantiate a passing run")
            count, run_targets = test_runs.setdefault(digest, (passed, set()))
            run_targets.add(target)
            if len(run_targets) > count:
                raise DeliveryError("Test run has fewer passes than its claimed Verify targets")
        elif target not in source or not re.search(r"(?i)\bpass(?:ed)?\b", source):
            raise DeliveryError("Verification source does not substantiate its passing target")
        covered.add(target)
    if not set(targets).issubset(covered):
        scope = "governing" if closing_contracts is None else "closing"
        raise DeliveryError(f"Not every {scope} Issue Verify target has evidence")
    scope_binding = json.dumps(scope_hashes, sort_keys=True).encode() if closing_contracts is not None else b""
    return receipt, hashlib.sha256(raw + "\n".join(source_digests).encode() + scope_binding).hexdigest()


def _full_claim_readback(
    state: dict[str, Any], runner: publication.CommandExecutor, worktree: Path,
) -> None:
    from scripts.pr_body_generator import _validate_pickup_receipt

    receipt = state.get("pickup_receipt")
    if not isinstance(receipt, str):
        raise DeliveryError("Pickup receipt is unavailable")
    _validate_pickup_receipt(receipt, state["issue"])
    prefix = (f"pickup-claim-complete issue={state['issue']} branch={state['branch']} "
              f"worktree={worktree} coordination_mode=")
    if not receipt.startswith(prefix):
        raise DeliveryError("Pickup receipt does not bind the recorded branch and worktree")
    records = agent_worktree.load_lifecycle_records(Path(state["root"]))
    record = records.get(str(worktree))
    if (not isinstance(record, dict) or record.get("path") != str(worktree)
            or record.get("branch") != state["branch"] or record.get("owner") != state["session_id"]
            or record.get("status") != "active" or not isinstance(record.get("generation"), str)
            or not isinstance(record.get("expires_at"), (int, float))
            or isinstance(record["expires_at"], bool) or not math.isfinite(record["expires_at"])
            or record["expires_at"] <= time.time()):
        raise DeliveryError("Current worktree registration is missing, expired, or mismatched")
    if agent_worktree._worktree_generation(Path(state["root"]), worktree, create=False) != record["generation"]:
        raise DeliveryError("Worktree registration generation changed")
    dispatcher = re.search(
        r" coordination_mode=dispatcher-backed fallback_reason=none task_id=(\S+) "
        r"lease_id=(\S+) holder=(.+?) evidence=verified-dispatcher-lease$", receipt
    )
    if dispatcher:
        task_id, lease_id, holder = dispatcher.groups()
        if holder != state.get("agent_id"):
            raise DeliveryError("Pickup lease holder changed")
        result = publication._checked(
            runner, [sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
            Path(__file__).resolve().parents[2],
        )
        try:
            payload = json.loads(result.stdout)
            task, lease = payload["task"], payload["lease"]
            expires = datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
            valid = (payload.get("ok") is True and task.get("task_id") == task_id
                     and task.get("repo") == REPOSITORY and task.get("issue_number") == state["issue"]
                     and task.get("claimed_by") == holder and task.get("lease_id") == lease_id
                     and task.get("status") in {"claimed", "in_progress"}
                     and lease.get("lease_id") == lease_id and lease.get("holder") == holder
                     and lease.get("resource") == f"issue:{state['issue']}"
                     and lease.get("released_at") is None and expires > datetime.now(timezone.utc))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise DeliveryError("Dispatcher claim readback is malformed") from exc
        if not valid:
            raise DeliveryError("Dispatcher claim is no longer active or does not match")
        return
    fallback = re.search(r" evidence=github-comment:([1-9][0-9]*)$", receipt)
    if fallback is None:
        raise DeliveryError("Pickup receipt coordination mode is unsupported")
    result = publication._checked(
        runner, ["gh", "api", "--hostname", "github.com", "--method", "GET",
                 f"repos/{REPOSITORY}/issues/comments/{fallback[1]}"], worktree,
    )
    try:
        comment = json.loads(result.stdout)
        body = comment["body"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DeliveryError("Pickup comment readback is malformed") from exc
    if (not isinstance(body, str) or comment.get("id") != int(fallback[1])
            or not body.startswith("Pickup intent receipt: ")
            or f"agent={state['agent_id']} session={state['session_id']} " not in body
            or f"branch={state['branch']} worktree={worktree} " not in body
            or comment.get("issue_url") != f"https://api.github.com/repos/{REPOSITORY}/issues/{state['issue']}"
            or f"issue={state['issue']}" not in body):
        raise DeliveryError("Pickup comment does not bind the recorded run")


def _full_snapshot(
    state: dict[str, Any], runner: publication.CommandExecutor, paths: list[str],
    evidence_file: Path, *, expected: dict[str, Any] | None = None,
    native_claim_check: Callable[[dict[str, Any]], None] | None = None,
    excluded_evidence_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    worktree = Path(state["worktree"]).resolve(strict=True)
    if (Path(publication._git_text(runner, worktree, "rev-parse", "--show-toplevel")).resolve() != worktree
            or publication._git_text(runner, worktree, "branch", "--show-current") != state["branch"]):
        raise DeliveryError("Publication worktree or branch changed")
    head = publication._git_text(runner, worktree, "rev-parse", "HEAD")
    authority = publication._read_authority_snapshot(runner, worktree, REPOSITORY, "main")
    if not publication.GIT_SHA_RE.fullmatch(head):
        raise DeliveryError("Candidate commit identity is unavailable")
    if any(publication._changed_path_sets(runner, worktree)):
        raise DeliveryError("Full-path publication requires the reviewed candidate to be committed and clean")
    intended = set(publication._normalize_paths(paths, worktree))
    actual = publication._candidate_paths(runner, worktree, authority.base_sha, head)
    if not actual or actual != intended:
        raise DeliveryError("Candidate commit history does not match the intended file set")
    issue = publication._read_issue(runner, worktree, REPOSITORY, state["issue"])
    publication._require_publishable_issue(
        issue, state["issue"], claimed=(native_claim_check is None or
                                        state.get("claim_issue", state["issue"]) == state["issue"]))
    if issue["body_sha256"] != state.get("issue_body_sha256"):
        raise DeliveryError("Issue contract changed after the worker started")
    issue_result = publication._checked(
        runner, ["gh", "api", "--hostname", "github.com", "--method", "GET",
                 f"repos/{REPOSITORY}/issues/{state['issue']}"], worktree,
    )
    try:
        issue_raw = json.loads(issue_result.stdout)
        issue_body = issue_raw["body"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DeliveryError("Full issue contract readback is unavailable") from exc
    if not isinstance(issue_raw, dict) or not isinstance(issue_raw.get("labels"), list):
        raise DeliveryError("Full issue readback is malformed")
    raw_labels = [label.get("name") if isinstance(label, dict) else label
                  for label in issue_raw["labels"]]
    if (not isinstance(issue_body, str) or any(not isinstance(label, str) for label in raw_labels)
            or _sha(issue_body) != issue["body_sha256"] or issue_raw.get("number") != issue["number"]
            or str(issue_raw.get("state", "")).lower() != issue["state"]
            or issue_raw.get("title") != issue["title"] or sorted(raw_labels) != issue["labels"]):
        raise DeliveryError("Issue contract or lifecycle changed during readback")
    closing_contracts = None
    closing_snapshots = None
    if native_claim_check is not None:
        from app.builderops import openhands_pr_cycle as cycle
        numbers = state.get("closing_issues")
        if (not isinstance(numbers, list) or len(numbers) > publication.MAX_CLOSING_ISSUES
                or any(type(number) is not int or number <= 0 for number in numbers)
                or len(set(numbers)) != len(numbers)
                or state.get("claim_issue") not in {state["issue"], *numbers}):
            raise DeliveryError("Native closing Issue scope is unavailable")
        closing_contracts, closing_snapshots = {}, {}
        for number in numbers:
            if number == state["issue"]:
                current, raw_issue, body = issue, issue_raw, issue_body
            else:
                current = publication._read_issue(runner, worktree, REPOSITORY, number)
                result = publication._checked(
                    runner, ["gh", "api", "--hostname", "github.com", "--method", "GET",
                             f"repos/{REPOSITORY}/issues/{number}"], worktree)
                try:
                    raw_issue = json.loads(result.stdout)
                    body = raw_issue["body"]
                    labels = [label.get("name") if isinstance(label, dict) else label
                              for label in raw_issue["labels"]]
                except (ValueError, KeyError, TypeError) as exc:
                    raise DeliveryError("Closing Issue readback is unavailable") from exc
                if (not isinstance(body, str) or any(not isinstance(label, str) for label in labels)
                        or raw_issue.get("number") != current["number"]
                        or str(raw_issue.get("state", "")).lower() != current["state"]
                        or raw_issue.get("title") != current["title"]
                        or sorted(labels) != current["labels"] or _sha(body) != current["body_sha256"]):
                    raise DeliveryError("Closing Issue contract or lifecycle changed during readback")
            publication._require_publishable_issue(current, number)
            cycle._assert_unheld_issue(raw_issue)
            closing_contracts[number] = body
            closing_snapshots[str(number)] = current
    evidence, evidence_digest = _full_evidence(evidence_file, state, head, authority.base_sha, issue_body,
                                               excluded_roots=excluded_evidence_roots,
                                               closing_contracts=closing_contracts)
    if native_claim_check is not None and not {"concurrency", "state-machine"}.issubset(evidence["risk_surfaces"]):
        raise DeliveryError("Native repair evidence must cover concurrency and state-machine risks")
    if native_claim_check is None:
        _full_claim_readback(state, runner, worktree)
    remote = publication._read_remote_head(runner, worktree, state["branch"])
    prs = publication._read_pr_history(runner, worktree, REPOSITORY, state["branch"])
    workflow_review = evidence.get("workflow_review_receipt")
    workflow_path: str | None = None
    if workflow_review is not None:
        receipt_path = Path(workflow_review["path"])
        if not receipt_path.is_absolute():
            receipt_path = evidence_file.resolve().parent / receipt_path
        workflow_path = str(receipt_path.resolve(strict=True))
    snapshot = {"head": head, "base": authority.base_sha, "authority": authority.as_mapping(),
                "issue": issue, "paths": sorted(actual), "evidence_sha256": evidence_digest,
                "risk_surfaces": sorted(evidence["risk_surfaces"]),
                "stateful_fallback": evidence.get("stateful_fallback", False),
                "workflow_review_receipt": workflow_path,
                "remote": remote, "prs": prs}
    if native_claim_check is not None:
        snapshot["closing_issues"] = closing_snapshots
        native_claim_check(snapshot)
    if expected is not None and native_claim_check is not None and snapshot["closing_issues"] != expected["closing_issues"]:
        raise DeliveryError("Full-path closing Issue scope changed")
    if expected is not None:
        for key in ("head", "base", "authority", "issue", "paths", "evidence_sha256", "risk_surfaces", "stateful_fallback", "workflow_review_receipt"):
            if snapshot[key] != expected[key]:
                raise DeliveryError(f"Full-path candidate or evidence changed: {key}")
    return snapshot


def _exact_full_pr(
    snapshot: dict[str, Any], state: dict[str, Any], title: str, body: str,
) -> dict[str, Any] | None:
    prs = snapshot["prs"]
    if not prs:
        return None
    if len(prs) != 1:
        raise DeliveryError("Multiple PRs share the branch; reconciliation is required")
    pr = prs[0]
    if (pr.get("state") != "open" or pr.get("merged_at") is not None or pr.get("draft") is not True
            or type(pr.get("number")) is not int or pr.get("title") != title
            or (pr.get("body") or "") != body
            or publication._nested(pr, "head", "sha") != snapshot["head"]
            or publication._nested(pr, "head", "ref") != state["branch"]
            or publication._nested(pr, "head", "repo", "full_name") != REPOSITORY
            or publication._nested(pr, "base", "ref") != "main"
            or publication._nested(pr, "base", "sha") != snapshot["base"]
            or publication._nested(pr, "base", "repo", "full_name") != REPOSITORY):
        raise DeliveryError("Existing PR is not the exact open draft for this candidate")
    if snapshot["remote"] != snapshot["head"]:
        raise DeliveryError("Existing draft PR and remote branch do not match the candidate")
    return pr


def _full_review_gate(
    runner: publication.CommandExecutor, worktree: Path, state: dict[str, Any],
    snapshot: dict[str, Any], existing_pr: dict[str, Any] | None,
) -> None:
    factory_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(factory_root / "scripts/review_before_ci_gate.py"),
               "--lane", "implementation", "--risk-assessment-complete", "--review-gate-complete"]
    for path in snapshot["paths"]:
        command.extend(["--changed-file", path])
    for risk in snapshot["risk_surfaces"]:
        command.extend(["--risk-surface", risk])
    if snapshot["stateful_fallback"]:
        command.extend(["--stateful-fallback", "--stateful-fallback-matrix-complete"])
    if snapshot["workflow_review_receipt"]:
        command.extend(["--workflow-review-receipt", snapshot["workflow_review_receipt"]])
    command.extend(["--publication-mode", "existing" if existing_pr else "new",
                    "--github-repository", REPOSITORY])
    if existing_pr:
        command.extend(["--pr-scope-revalidation", "--pr-number", str(existing_pr["number"]),
                        "--governing-issue", str(state["issue"])])
    publication._checked(runner, command, worktree)


def _full_workspace_gate(
    runner: publication.CommandExecutor, worktree: Path, state: dict[str, Any]
) -> None:
    factory_root = Path(__file__).resolve().parents[2]
    publication._checked(
        runner, [str(factory_root / "scripts/agent_workspace_preflight.sh"), "--cwd", str(worktree),
                 "--expected-branch", state["branch"], "--expected-worktree", str(worktree),
                 "--base-branch", "main"], worktree,
    )


def _update_pr_readback(
    snapshot: dict[str, Any], state: dict[str, Any], previous: dict[str, Any],
    pr_number: int, title: str, body: str, *, native: bool = False,
) -> tuple[dict[str, Any], str, str]:
    prs = snapshot["prs"]
    if len(prs) != 1 or type(pr_number) is not int or pr_number <= 0:
        raise DeliveryError("Existing draft PR identity is missing or ambiguous")
    pr = prs[0]
    head = publication._nested(pr, "head", "sha")
    pr_body = pr.get("body")
    if (pr.get("number") != pr_number or pr.get("state") != "open"
            or pr.get("merged_at") is not None or pr.get("draft") is not (False if native else True)
            or publication._nested(pr, "head", "ref") != state["branch"]
            or publication._nested(pr, "head", "repo", "full_name") != REPOSITORY
            or publication._nested(pr, "base", "ref") != "main"
            or publication._nested(pr, "base", "sha") != snapshot["base"]
            or publication._nested(pr, "base", "repo", "full_name") != REPOSITORY
            or head not in {previous["head"], snapshot["head"]} or snapshot["remote"] != head
            or not isinstance(pr_body, str)):
        raise DeliveryError("Existing draft PR or branch does not match the recorded publication")
    authority = resolve_native_issue_authority(pr_body)
    closing = tuple(state.get("closing_issues", (state["issue"],))) if native else (state["issue"],)
    if (authority is None or authority.governing_issue != state["issue"]
            or tuple(authority.closing_issues) != closing):
        raise DeliveryError("Existing PR issue scope changed")
    old_metadata = pr.get("title") == previous["title"] and _sha(pr_body) == previous["body_sha256"]
    new_metadata = pr.get("title") == title and pr_body == body
    if not old_metadata and not new_metadata:
        raise DeliveryError("Existing draft PR title or body changed unexpectedly")
    if head == previous["head"] and not old_metadata:
        raise DeliveryError("Existing draft PR metadata changed before the reviewed push")
    return pr, "old" if head == previous["head"] else "new", "new" if new_metadata else "old"


def _publish_full_update(
    directory: Path, state: dict[str, Any], runner: publication.CommandExecutor,
    paths: list[str], title: str, body: str, evidence_file: Path,
    snapshot: dict[str, Any], binding: dict[str, Any], binding_hash: str, prior: dict[str, Any] | None,
    *, native_previous: dict[str, Any] | None = None,
    native_claim_check: Callable[[dict[str, Any]], None] | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
    excluded_evidence_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    native = native_previous is not None
    write = persist if persist is not None else lambda value: service._write(directory, value)
    worktree = Path(state["worktree"]).resolve(strict=True)
    retry = isinstance(prior, dict) and prior.get("binding_sha256") == binding_hash
    previous = prior.get("previous_candidate") if retry else (native_previous if native else prior.get("candidate"))
    pr_number = state.get("native_pr_number") if native else prior.get("pr_number")
    if type(pr_number) is not int or pr_number <= 0:
        raise DeliveryError("Previous publication has no valid PR number")
    if (not isinstance(previous, dict) or previous.get("issue") != state["issue"]
            or previous.get("branch") != state["branch"] or previous.get("base") != snapshot["base"]
            or not isinstance(previous.get("head"), str)
            or not publication.GIT_SHA_RE.fullmatch(previous["head"])
            or previous["head"] == snapshot["head"]
            or not isinstance(previous.get("title"), str)
            or not isinstance(previous.get("body_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", previous["body_sha256"])):
        raise DeliveryError("Previous published candidate does not bind an additive update")
    if native and prior is not None and not retry:
        raise DeliveryError("An earlier native publication remains unresolved or has different evidence")
    if not retry and not native and (prior.get("state") != "draft_published"
                      or prior.get("binding_sha256") != _sha(publication.canonical_json(previous))):
        raise DeliveryError("Earlier publication must be reconciled before an update")
    if retry and (prior.get("candidate") != binding or prior.get("state") not in {
        "update_prepared", "update_pushing", "update_pushed", "update_patching", "check_readback_pending",
        *({"native_published"} if native else set())
    }):
        raise DeliveryError("Existing draft update attempt is inconsistent")
    ancestor = runner.run(["git", "merge-base", "--is-ancestor", previous["head"], snapshot["head"]],
                          cwd=worktree)
    if ancestor.returncode != 0:
        raise DeliveryError("Reviewed candidate is not an additive successor to the published draft")
    pr, head_state, metadata_state = _update_pr_readback(snapshot, state, previous, pr_number, title, body, native=native)
    if not retry and (head_state != "old" or metadata_state != "old"):
        # Identical old and new metadata may classify as new; the old binding must still match exactly.
        old_body = pr.get("body") or ""
        if head_state != "old" or pr.get("title") != previous["title"] or _sha(old_body) != previous["body_sha256"]:
            raise DeliveryError("Existing draft no longer matches the prior publication")
    _full_workspace_gate(runner, worktree, state)
    _full_review_gate(runner, worktree, state, snapshot, pr)
    if not retry:
        state["full_publication"] = {"binding_sha256": binding_hash, "state": "update_prepared",
                                     "candidate": binding, "previous_candidate": previous,
                                     "pr_number": pr_number, "evidence_file": str(evidence_file.resolve())}
        write(state)
    attempt = state["full_publication"]
    if head_state == "old":
        if attempt["state"] != "update_prepared":
            raise DeliveryError("Earlier draft push remains unresolved; reconcile before retry")
        _full_workspace_gate(runner, worktree, state)
        snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot, native_claim_check=native_claim_check,
                                  excluded_evidence_roots=excluded_evidence_roots)
        pr, head_state, metadata_state = _update_pr_readback(snapshot, state, previous, pr_number, title, body, native=native)
        if head_state != "old":
            raise DeliveryError("Draft branch changed before push; reconcile before retry")
        attempt["state"] = "update_pushing"
        write(state)
        pushed = runner.run(["git", "push", "origin", f"{snapshot['head']}:refs/heads/{state['branch']}"],
                            cwd=worktree)
        snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot, native_claim_check=native_claim_check,
                                  excluded_evidence_roots=excluded_evidence_roots)
        pr, head_state, metadata_state = _update_pr_readback(snapshot, state, previous, pr_number, title, body, native=native)
        if head_state != "new":
            raise DeliveryError("Draft push outcome is uncertain; reconcile before retry")
        if pushed.returncode:
            attempt["push_reconciled"] = True
        attempt["state"] = "update_pushed"
        write(state)
    elif attempt["state"] == "update_prepared":
        raise DeliveryError("Draft branch changed before the recorded push; reconcile before retry")
    if native and metadata_state != "new":
        raise DeliveryError("Native PR metadata changed; reconcile before publication")
    if metadata_state == "old":
        if attempt["state"] in {"update_patching", "check_readback_pending"}:
            raise DeliveryError("Earlier draft metadata update remains unresolved; reconcile before retry")
        _full_review_gate(runner, worktree, state, snapshot, pr)
        snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot, native_claim_check=native_claim_check,
                                  excluded_evidence_roots=excluded_evidence_roots)
        pr, head_state, metadata_state = _update_pr_readback(snapshot, state, previous, pr_number, title, body, native=native)
        if head_state != "new" or metadata_state != "old":
            raise DeliveryError("Draft changed before metadata update; reconcile before retry")
        attempt["state"] = "update_patching"
        write(state)
        patched = runner.run(["gh", "api", "--hostname", "github.com", "--method", "PATCH",
                              f"repos/{REPOSITORY}/pulls/{pr_number}", "-f", f"title={title}",
                              "-f", f"body={body}"], cwd=worktree)
        snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot, native_claim_check=native_claim_check,
                                  excluded_evidence_roots=excluded_evidence_roots)
        pr, head_state, metadata_state = _update_pr_readback(snapshot, state, previous, pr_number, title, body, native=native)
        if head_state != "new" or metadata_state != "new":
            raise DeliveryError("Draft metadata update outcome is uncertain; reconcile before retry")
        if patched.returncode:
            attempt["metadata_reconciled"] = True
    attempt["state"] = "check_readback_pending"
    write(state)
    checks = _check_readback(runner, worktree, snapshot["head"])
    final = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot, native_claim_check=native_claim_check,
                                  excluded_evidence_roots=excluded_evidence_roots)
    final_pr, head_state, metadata_state = _update_pr_readback(final, state, previous, pr_number, title, body, native=native)
    if head_state != "new" or metadata_state != "new":
        raise DeliveryError("Updated draft changed during check readback")
    attempt.update(state="native_published" if native else "draft_published", checks=checks)
    write(state)
    return {"draft": not native, "pr_number": pr_number, "url": final_pr.get("html_url"),
            "commit_sha": snapshot["head"], "base_sha": snapshot["base"], "checks": checks,
            "evidence_file": str(evidence_file.resolve()), "evidence_sha256": snapshot["evidence_sha256"],
            "note": "Local sources and bindings checked; reviewer identity is host-attested."}


def publish_native_repair(
    layout: Any, pr: Mapping[str, Any], entry: Mapping[str, Any], identity: str,
    paths: list[str], evidence_file: Path, *, executor: publication.CommandExecutor | None = None,
) -> dict[str, Any]:
    """Publish one already-bound stopped repair to its exact existing native PR.

    This host-side callable does not create a PR, change metadata, schedule
    reviews, refresh admission, or merge. The caller supplies the original PR
    observation and controller admission; every effect is fenced by live reads.
    For multiple Issue contracts, review evidence must identify each current
    body hash in both its scope_issue_body_sha256 mapping and review source.
    Verify evidence covers every exact closing Issue; a distinct open parent
    remains a governing contract without requiring its unfinished targets.
    """
    from app.builderops import epic_workspace as workspace
    from app.builderops import openhands_pr_cycle as cycle

    worker = entry.get("worker")
    if not isinstance(worker, str):
        raise DeliveryError("Native worker identity is unavailable")
    workspace.validate_worker_id(worker)
    with cycle._single_advancement(layout), workspace._worker_lifecycle_lock(layout, worker):
        saved = cycle._find(layout, pr["number"], identity)
        source_worker = saved.get("repair_worker", worker)
        if source_worker == worker:
            return _publish_native_repair_locked(layout, pr, entry, identity, paths, evidence_file, executor=executor)
        with workspace._worker_lifecycle_lock(layout, source_worker):
            return _publish_native_repair_locked(layout, pr, entry, identity, paths, evidence_file, executor=executor)


def _publish_native_repair_locked(
    layout: Any, pr: Mapping[str, Any], entry: Mapping[str, Any], identity: str,
    paths: list[str], evidence_file: Path, *, executor: publication.CommandExecutor | None = None,
) -> dict[str, Any]:
    """Run the native publisher while its cycle and worker lifecycle locks are held."""
    from app.builderops import epic_run_state, epic_workspace as workspace
    from app.builderops import openhands_pr_cycle as cycle

    number, worker = pr.get("number"), entry.get("worker")
    if (type(number) is not int or number <= 0 or not isinstance(worker, str)
            or entry.get("number") != number or entry.get("head_sha") != pr.get("head_sha")
            or entry.get("native_session_owned") is not True or not isinstance(identity, str)
            or pr.get("draft") is not False or pr.get("restrictions")
            or not isinstance(pr.get("body"), str) or not isinstance(pr.get("title"), str)
            or re.search(r"\b(?:draft[ -]only|do[ -]not[ -]merge|do not merge|merge hold)\b", pr.get("body", ""), re.I)):
        raise DeliveryError("Native PR admission or original contract is unavailable")
    workspace.validate_worker_id(worker)
    runner = executor or publication.SubprocessExecutor()
    saved = cycle._find(layout, number, identity)
    source_worker = saved.get("repair_worker", worker)
    if not isinstance(source_worker, str):
        raise DeliveryError("Stopped repair source worker is unavailable")
    workspace.validate_worker_id(source_worker)
    candidate = saved.get("repair_candidate")
    original = saved.get("repair_authority_binding")
    result = saved.get("repair_result")
    if (not isinstance(candidate, dict) or candidate.get("status") != "awaiting_independent_review"
            or candidate.get("repository") != REPOSITORY or candidate.get("number") != number
            or candidate.get("identity") != identity or candidate.get("old_head") != pr.get("head_sha")
            or candidate.get("operation_id") != saved.get("repair_operation")
            or not isinstance(original, dict) or not isinstance(result, dict)
            or original.get("number") != number or original.get("head_sha") != pr.get("head_sha")
            or original.get("body") != pr.get("body") or original.get("title") != pr.get("title")
            or result.get("status") != "pending_trusted_publication"):
        raise DeliveryError("Stopped repair candidate is unavailable; bind it before publication")
    if source_worker != worker and candidate.get("source_worker") != source_worker:
        raise DeliveryError("Stopped repair candidate source worker changed")
    head, branch, path = candidate.get("candidate_head"), candidate.get("branch"), candidate.get("worktree")
    if (not isinstance(head, str) or not publication.GIT_SHA_RE.fullmatch(head)
            or not isinstance(branch, str) or not isinstance(path, str)
            or not Path(path).is_absolute() or str(Path(path).resolve()) != path
            or workspace._is_within(Path(path), layout.root.resolve())
            or path != entry.get("owner_worktree") or branch != original.get("branch")):
        raise DeliveryError("Registered publisher worktree or candidate is unavailable")
    worktree = Path(path)
    issue = original.get("governing_issue")
    hashes = original.get("governing_issue_hashes")
    if (type(issue) is not int or not isinstance(hashes, dict)
            or not isinstance(hashes.get("body_sha256"), str)
            or not isinstance(original.get("closing_issues"), list)
            or any(held in (number, issue) or re.search(rf"#{held}(?![0-9])", pr["body"])
                   for held in cycle.observation.HELD_ISSUES)):
        raise DeliveryError("Native Issue scope is unavailable")
    state = {"worktree": path, "branch": branch, "issue": issue,
             "issue_body_sha256": hashes["body_sha256"], "agent_id": entry.get("claimant"),
             "session_id": entry.get("session"), "closing_issues": original["closing_issues"],
             "claim_issue": original.get("claim_issue"), "native_pr_number": number}
    previous = {"issue": issue, "branch": branch, "head": pr["head_sha"],
                "title": pr["title"], "body_sha256": _sha(pr["body"])}
    prior = saved.get("repair_publication")
    if prior is not None and not isinstance(prior, dict):
        raise DeliveryError("Native publication attempt is unavailable")
    if prior is not None:
        state["full_publication"] = prior

    def check(snapshot: dict[str, Any]) -> None:
        current = cycle._find(layout, number, identity)
        mapping = cycle._mapping(layout, source_worker)
        if current.get("repair_candidate") != candidate or current.get("repair_result") != result:
            raise DeliveryError("Repair candidate changed during publication")
        generated = current.get("candidate_verification")
        if (isinstance(generated, dict) and generated.get("state") == "artifact_ready"
                and generated.get("evidence_file") == str(evidence_file)):
            dispatch = current.get("candidate_review_dispatch")
            review = current.get("candidate_review_receipt")
            reviewed = current.get("candidate_review_result")
            if (not isinstance(dispatch, dict) or not isinstance(dispatch.get("binding"), dict)
                    or cycle._digest(dispatch["binding"]) != dispatch.get("binding_sha256")
                    or dispatch["binding"].get("candidate") != candidate
                    or generated.get("binding_sha256") != dispatch.get("binding_sha256")
                    or generated.get("candidate_head") != head or generated.get("candidate_tree") != candidate.get("tree")
                    or not isinstance(review, dict) or review.get("binding_sha256") != dispatch.get("binding_sha256")
                    or not isinstance(review.get("raw_response"), str)
                    or hashlib.sha256(review["raw_response"].encode()).hexdigest() != review.get("raw_sha256")
                    or cycle._public_report(review["raw_response"]) != review.get("report")
                    or review.get("report_sha256") != cycle._digest(review.get("report"))
                    or review.get("native_proof") != current.get("candidate_review_execution_proof")
                    or not isinstance(reviewed, dict) or reviewed.get("state") != "awaiting_verify_evidence"
                    or hashlib.sha256(evidence_file.read_bytes()).hexdigest() != generated.get("evidence_sha256")):
                raise DeliveryError("Candidate Verify or independent review receipt changed")
            reviewer = dispatch.get("worker")
            if not isinstance(reviewer, str):
                raise DeliveryError("Candidate reviewer identity is unavailable")
            reviewer_mapping = cycle._mapping(layout, reviewer)
            cycle._review_stop_checkpoint(reviewer_mapping, current, require_receipt=True, prefix="candidate_review_")
            cycle._assert_stopped(layout, reviewer, reviewer_mapping)
            verifier, stop = generated.get("worker"), generated.get("stop_intent")
            if (not isinstance(verifier, str) or not isinstance(stop, dict)
                    or generated.get("stop_verified") is not True):
                raise DeliveryError("Candidate Verify stop receipt is unavailable")
            verify_mapping = cycle._mapping(layout, verifier)
            verify_work = workspace._completed_stop(verify_mapping, stop.get("stop_id"))
            if (verify_mapping.get("container_id") != stop.get("container_id")
                    or verify_work.get("head") != head or verify_work.get("uncommitted_count") != 0):
                raise DeliveryError("Candidate Verify stop or checkout changed")
            cycle._assert_stopped(layout, verifier, verify_mapping)
        cycle._review_stop_checkpoint(mapping, current, require_receipt=True, prefix="repair_")
        cycle._assert_stopped(layout, source_worker, mapping)
        intent = current["repair_stop_intent"]
        work = workspace._completed_stop(mapping, intent["stop_id"])
        checkpoint = work.get("checkpoint")
        if (not isinstance(checkpoint, dict) or checkpoint not in mapping.get("checkpoints", [])
                or checkpoint.get("status") != "preserved"
                or checkpoint.get("ref") != candidate.get("checkpoint_ref")
                or result.get("work_at_stop") != work or candidate.get("stop_id") != intent["stop_id"]
                or candidate.get("native_proof_sha256") != cycle._digest(current.get("repair_execution_proof"))):
            raise DeliveryError("Stopped author source or proof changed")
        if candidate.get("source_kind") in ("versioned_projection", "versioned_projection_explicit"):
            cycle._verify_repair_candidate_projection_locked(layout, source_worker, pr, current, mapping, candidate)
        elif (candidate.get("source_kind") is not None or checkpoint.get("ignored_count") != 0
              or checkpoint.get("tree") != candidate.get("tree")):
            raise DeliveryError("Stopped author source or proof changed")
        if source_worker != worker:
            cycle._verify_candidate_repair_history(layout, pr, entry, current, scope_check=False)
        if (snapshot.get("head") != head or publication._git_text(runner, worktree, "rev-parse", "HEAD^{tree}") != candidate.get("tree")):
            raise DeliveryError("Publisher candidate no longer matches the stopped source")
        rows = snapshot.get("prs")
        if not isinstance(rows, list) or len(rows) != 1:
            raise DeliveryError("Existing PR history is unavailable or ambiguous")
        observed = publication._nested(rows[0], "head", "sha")
        if observed not in (pr["head_sha"], head) or snapshot.get("remote") != observed:
            raise DeliveryError("PR or remote branch changed outside this publication")
        fresh_pr = {**pr, "head_sha": observed}
        fresh = cycle.native_authority(layout, fresh_pr, entry, purpose="repair")
        normalized = {**fresh, "head_sha": original.get("head_sha")}
        if not cycle._repair_authority_continues(original, normalized):
            raise DeliveryError("Native claim, PR contract or publisher registration changed")
        registration = fresh.get("worktree_owner")
        if (not isinstance(registration, dict) or registration.get("path") != path
                or registration.get("generation") != candidate.get("generation")
                or registration.get("registration_epoch") != candidate.get("registration_epoch")):
            raise DeliveryError("Native publisher registration changed")
        ops = mapping.get("publication_ops", [])
        attempt = current.get("repair_publication")
        own = attempt.get("operation_id") if isinstance(attempt, dict) else None
        if not isinstance(ops, list):
            raise DeliveryError("Publication operation history is unavailable")
        cycle._assert_repair_publications_settled({**mapping, "publication_ops": [
            op for op in ops if not isinstance(op, dict) or op.get("id") != own]})
        if own is not None:
            matched = [op for op in ops if isinstance(op, dict) and op.get("id") == own]
            if (len(matched) != 1 or matched[0].get("branch") != branch
                    or matched[0].get("expect_sha") != head
                    or matched[0].get("status") not in ("intended", "quarantined", "confirmed")):
                raise DeliveryError("Recorded publication operation changed")

    def persist(value: dict[str, Any]) -> None:
        attempt = value["full_publication"]
        def update(run_state: dict[str, Any]) -> dict[str, Any]:
            workspace._issue_for_worker(run_state, source_worker)
            mapping = workspace._worker_mapping(run_state, source_worker)
            records = [r for r in run_state["compact_receipts"] if isinstance(r, dict)
                       and r.get("kind") == "pr_cycle" and r.get("number") == number
                       and r.get("identity") == identity]
            if (len(records) != 1 or records[0].get("repair_candidate") != candidate
                    or mapping.get("state") != "stopped_verified"
                    or mapping.get("stop_id") != candidate.get("stop_id")
                    or mapping.get("work_at_stop") != result.get("work_at_stop")):
                raise DeliveryError("Stopped source or receipt changed before recording publication")
            row = records[0]
            old = row.get("repair_publication")
            if old is not None and (not isinstance(old, dict)
                    or old.get("binding_sha256") != attempt.get("binding_sha256")):
                raise DeliveryError("Another publication attempt is already recorded")
            ops = mapping.setdefault("publication_ops", [])
            if not isinstance(ops, list):
                raise DeliveryError("Publication history is unavailable")
            op_id = old.get("operation_id") if isinstance(old, dict) else None
            if attempt["state"] == "update_pushing" and op_id is None:
                cycle._assert_repair_publications_settled(mapping)
                op_id = f"branch_push-{len(ops) + 1}"
                ops.append({"id": op_id, "kind": "branch_push", "branch": branch,
                            "expect_sha": head, "status": "intended", "intent_at": workspace._now()})
            if op_id is not None:
                attempt["operation_id"] = op_id
                matches = [op for op in ops if isinstance(op, dict) and op.get("id") == op_id]
                if len(matches) != 1 or matches[0].get("expect_sha") != head:
                    raise DeliveryError("Publication operation identity changed")
                if attempt["state"] in ("update_pushed", "check_readback_pending", "native_published"):
                    op = matches[0]
                    op.update(status="confirmed", confirmed_at=workspace._now(),
                              result={"branch": branch, "sha": head, "number": number})
                    op.pop("reason", None)
                    workspace._record_published_head(mapping, op)
            if attempt["state"] == "native_published":
                attempt["published_head"] = head
                attempt["next_action"] = "refresh admission and perform new-head review, Verify and CI"
            row["repair_publication"] = dict(attempt)
            return run_state
        epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=update,
                                             expected_epic_issue_number=layout.epic)

    # Existing effects are read back even when new-write evidence has gone stale.
    if isinstance(prior, dict) and prior.get("state") == "update_pushing":
        old_binding, attempted = prior.get("previous_candidate"), prior.get("candidate")
        if (not isinstance(old_binding, dict) or old_binding.get("head") != pr["head_sha"]
                or old_binding.get("title") != pr["title"] or old_binding.get("body_sha256") != _sha(pr["body"])
                or not isinstance(attempted, dict) or attempted.get("head") != head
                or attempted.get("identity") != identity or prior.get("pr_number") != number
                or not isinstance(prior.get("operation_id"), str)):
            raise DeliveryError("Native publication intent is not bound to this candidate")
        remote = publication._read_remote_head(runner, worktree, branch)
        prs = publication._read_pr_history(runner, worktree, REPOSITORY, branch)
        if remote == head:
            observed = {"remote": remote, "prs": prs, "head": head, "base": old_binding.get("base")}
            _, head_state, metadata_state = _update_pr_readback(
                observed, state, old_binding, number, pr["title"], pr["body"], native=True)
            if head_state != "new" or metadata_state != "new":
                raise DeliveryError("Native publication readback is ambiguous")
            prior = {**prior, "state": "update_pushed", "push_reconciled": True}
            state["full_publication"] = prior
            persist(state)
    snapshot = _full_snapshot(state, runner, paths, evidence_file, native_claim_check=check,
                              excluded_evidence_roots=(layout.root.resolve(),))
    previous["base"] = snapshot["base"]
    binding = {"issue": issue, "branch": branch, "base": snapshot["base"], "head": head,
               "paths": snapshot["paths"], "title": pr["title"], "body_sha256": _sha(pr["body"]),
               "evidence_sha256": snapshot["evidence_sha256"], "risk_surfaces": snapshot["risk_surfaces"],
               "identity": identity, "repair_operation": saved["repair_operation"],
               "stop_id": candidate["stop_id"], "tree": candidate["tree"]}
    return _publish_full_update(layout.run_state_dir, state, runner, paths, pr["title"], pr["body"],
                                evidence_file, snapshot, binding, _sha(publication.canonical_json(binding)), prior,
                                native_previous=previous, native_claim_check=check, persist=persist,
                                excluded_evidence_roots=(layout.root.resolve(),))


def publish_full(
    directory: Path, paths: list[str], title: str, body_inputs: dict[str, Any],
    evidence_file: Path, *, executor: publication.CommandExecutor | None = None,
) -> dict[str, Any]:
    """Publish a clean, already-reviewed commit through the governed full path.

    A later reviewed descendant may update the same recorded draft when its
    previous head, body, issue, and unchanged base are independently re-read.

    --evidence-file is JSON with version=1, repository, issue, base_sha,
    head_sha, and risk_surfaces. It names review as {reviewer, verdict: "pass",
    head_sha, blocking_findings: [], evidence: {path}} and verification as a
    list of {target, result: "pass", head_sha, evidence: {path}}. Paths are
    absolute or relative to the receipt, outside the worker worktree. The review
    source must identify the commit; test output must show a passing run. The
    host supplies the reviewer identity and associates each target with its run.
    Optional stateful_fallback=true requires stateful_fallback_matrix_complete=true;
    workflow_review_receipt may name {path} for the existing workflow gate.
    This checks source files and bindings; reviewer identity remains host-attested.
    Manually supplied host evidence is trusted under that same host-attestation
    model; it does not authenticate a reviewer against a malicious host user.
    """
    if not title.strip():
        raise DeliveryError("Draft PR title is required")
    with service._locked(directory):
        state = _finished_run(directory)
        worktree = Path(state["worktree"]).resolve(strict=True)
        runner = DraftOnlyExecutor(executor)
        body_values = dict(body_inputs)
        if (body_values.get("lane") != "implementation"
                or body_values.get("issue_number", state["issue"]) != state["issue"]
                or body_values.get("pickup_receipt", state["pickup_receipt"]) != state["pickup_receipt"]):
            raise DeliveryError("PR body does not match the recorded implementation run")
        body_values.update(issue_number=state["issue"], pickup_receipt=state["pickup_receipt"])
        if body_values.get("final_review_rounds") != 1:
            raise DeliveryError("Full publication requires one independent final review round")
        body = generate_pr_body_from_mapping(body_values)
        authority = resolve_native_issue_authority(body)
        if (authority is None or authority.governing_issue != state["issue"]
                or tuple(authority.closing_issues) != (state["issue"],)):
            raise DeliveryError("Full path supports exactly the recorded issue as its closing scope")
        snapshot = _full_snapshot(state, runner, paths, evidence_file)
        binding = {"issue": state["issue"], "branch": state["branch"], "base": snapshot["base"],
                   "head": snapshot["head"], "paths": snapshot["paths"], "title": title,
                   "body_sha256": _sha(body), "evidence_sha256": snapshot["evidence_sha256"],
                   "risk_surfaces": snapshot["risk_surfaces"]}
        binding_hash = _sha(publication.canonical_json(binding))
        prior = state.get("full_publication")
        if isinstance(prior, dict) and (
            prior.get("binding_sha256") != binding_hash
            or (prior.get("previous_candidate") is not None and prior.get("state") != "draft_published")
        ):
            return _publish_full_update(directory, state, runner, paths, title, body, evidence_file,
                                        snapshot, binding, binding_hash, prior)
        if prior is not None and (not isinstance(prior, dict) or prior.get("binding_sha256") != binding_hash):
            raise DeliveryError("A different full-path publication attempt is already recorded")
        candidate = _exact_full_pr(snapshot, state, title, body)
        _full_workspace_gate(runner, worktree, state)
        _full_review_gate(runner, worktree, state, snapshot, candidate)
        if (candidate is None and isinstance(prior, dict)
                and prior.get("state") in {"creating_pr", "check_readback_pending", "draft_published"}):
            raise DeliveryError("Earlier draft creation remains unresolved; reconcile before retry")
        if (candidate is None and isinstance(prior, dict) and prior.get("state") == "reserving"
                and snapshot["remote"] is None):
            raise DeliveryError("Earlier branch reservation remains unresolved; reconcile before retry")
        if candidate is None and snapshot["remote"] not in {None, snapshot["base"], snapshot["head"]}:
            raise DeliveryError("Remote branch state is unexplained")
        if candidate is None and snapshot["remote"] is not None and prior is None:
            raise DeliveryError("Existing remote branch has no matching publication attempt")
        state["full_publication"] = {**(prior or {}), "binding_sha256": binding_hash,
                                     "state": "prepared", "candidate": binding,
                                     "evidence_file": str(evidence_file.resolve())}
        service._write(directory, state)
        if candidate is None and snapshot["remote"] is None:
            _full_workspace_gate(runner, worktree, state)
            snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
            if snapshot["remote"] is not None or snapshot["prs"]:
                raise DeliveryError("Branch or PR appeared before branch reservation")
            state["full_publication"]["state"] = "reserving"
            service._write(directory, state)
            reservation = runner.run([
                "gh", "api", "--hostname", "github.com", "--method", "POST",
                f"repos/{REPOSITORY}/git/refs", "-f", f"ref=refs/heads/{state['branch']}",
                "-f", f"sha={snapshot['base']}",
            ], cwd=worktree)
            snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
            if snapshot["remote"] != snapshot["base"] or snapshot["prs"]:
                raise DeliveryError("Branch reservation outcome is uncertain; reconcile before retry")
            if reservation.returncode != 0:
                # Exact base reservation was read back, as in the owning workflow.
                state["full_publication"]["reservation_reconciled"] = True
            state["full_publication"]["state"] = "reserved"
            service._write(directory, state)
        if candidate is None and snapshot["remote"] == snapshot["base"]:
            _full_workspace_gate(runner, worktree, state)
            snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
            if snapshot["remote"] != snapshot["base"] or snapshot["prs"]:
                raise DeliveryError("Branch or PR changed before push")
            state["full_publication"]["state"] = "pushing"
            service._write(directory, state)
            pushed = runner.run(["git", "push", "origin", f"{snapshot['head']}:refs/heads/{state['branch']}"],
                                cwd=worktree)
            snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
            if snapshot["remote"] != snapshot["head"] or snapshot["prs"]:
                raise DeliveryError("Push outcome is uncertain; reconcile before retry")
            if pushed.returncode != 0:
                state["full_publication"]["push_reconciled"] = True
            state["full_publication"]["state"] = "pushed"
            service._write(directory, state)
        if candidate is None:
            snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
            candidate = _exact_full_pr(snapshot, state, title, body)
            if candidate is None:
                if snapshot["remote"] != snapshot["head"]:
                    raise DeliveryError("Remote branch does not contain the reviewed commit")
                state["full_publication"]["state"] = "creating_pr"
                service._write(directory, state)
                created = runner.run([
                    "gh", "pr", "create", "--repo", f"github.com/{REPOSITORY}",
                    "--base", "main", "--head", state["branch"], "--title", title, "--body", body,
                ], cwd=worktree)
                snapshot = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
                candidate = _exact_full_pr(snapshot, state, title, body)
                if candidate is None:
                    raise DeliveryError("Draft creation outcome is uncertain; reconcile before retry")
                if created.returncode != 0:
                    state["full_publication"]["creation_reconciled"] = True
        state["full_publication"].update(state="check_readback_pending", pr_number=candidate["number"])
        service._write(directory, state)
        checks = _check_readback(runner, worktree, snapshot["head"])
        final = _full_snapshot(state, runner, paths, evidence_file, expected=snapshot)
        final_pr = _exact_full_pr(final, state, title, body)
        if final_pr is None or final_pr["number"] != candidate["number"]:
            raise DeliveryError("Draft PR or branch changed during check readback")
        state["full_publication"].update(state="draft_published", checks=checks)
        service._write(directory, state)
        return {"draft": True, "pr_number": candidate["number"], "url": candidate.get("html_url"),
                "commit_sha": snapshot["head"], "base_sha": snapshot["base"], "checks": checks,
                "evidence_file": str(evidence_file.resolve()),
                "evidence_sha256": snapshot["evidence_sha256"],
                "note": "Local sources and bindings checked; reviewer identity is host-attested."}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    view = commands.add_parser("preview", help="Read issue, instruction and PR evidence")
    launch = commands.add_parser("start", help="Start one explicitly authorized issue")
    for target in (view, launch):
        target.add_argument("--repo-root", type=Path, required=True)
        target.add_argument("--issue", type=int, required=True)
        target.add_argument("--branch", required=True)
        target.add_argument("--worktree", type=Path, required=True)
    launch.add_argument("--state-dir", type=Path, required=True)
    launch.add_argument("--authorize-issue", type=int, required=True)
    launch.add_argument("--python", type=Path, required=True)
    launch.add_argument("--port", type=int, required=True)
    launch.add_argument("--settings", type=Path, required=True)
    launch.add_argument("--node", type=Path, required=True)
    launch.add_argument("--acp", type=Path, required=True)
    for name in ("status", "cancel", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
    plan_parser = commands.add_parser("publish-plan", help="Build a read-only draft publication plan")
    plan_parser.add_argument("--state-dir", type=Path, required=True)
    plan_parser.add_argument("--path", action="append", required=True)
    plan_parser.add_argument("--title", required=True)
    plan_parser.add_argument("--commit-message", required=True)
    plan_parser.add_argument("--body-input-json", type=Path, required=True)
    plan_parser.add_argument("--tier", type=int, choices=(1, 2), required=True)
    plan_parser.add_argument("--risk-surface", action="append", default=[])
    plan_parser.add_argument("--risk-assessment-complete", action="store_true")
    plan_parser.add_argument("--review-gate-complete", action="store_true")
    full_parser = commands.add_parser(
        "publish-full", help="Publish a committed, independently reviewed draft",
        description=publish_full.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    full_parser.add_argument("--state-dir", type=Path, required=True)
    full_parser.add_argument("--path", action="append", required=True,
                             help="Each intended path in the candidate commit history")
    full_parser.add_argument("--title", required=True)
    full_parser.add_argument("--body-input-json", type=Path, required=True,
                             help="Inputs for scripts/pr_body_generator.py")
    full_parser.add_argument("--evidence-file", type=Path, required=True,
                             help="Host-side review and verification evidence JSON")
    publish_parser = commands.add_parser("publish", help="Publish one verified draft plan")
    publish_parser.add_argument("--state-dir", type=Path, required=True)
    publish_parser.add_argument("--plan-file", type=Path, required=True)
    publish_parser.add_argument("--expected-plan-sha256", required=True)
    publish_parser.add_argument("--verified-plan-sha256", required=True,
                                help="Host attests tests passed against this plan")
    publish_parser.add_argument("--reviewed-plan-sha256", required=True,
                                help="Host review attestation only; this does not verify independent review evidence")
    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            result = preview(args.repo_root, args.issue, args.branch, args.worktree)
        elif args.command == "start":
            result = start(args.state_dir, args.repo_root, args.issue, args.authorize_issue,
                           args.branch, args.worktree, args.python, args.port, args.settings,
                           args.node, args.acp)
        elif args.command == "status":
            result = status(args.state_dir)
        elif args.command == "cancel":
            result = cancel(args.state_dir)
        elif args.command == "resume":
            result = resume(args.state_dir)
        elif args.command == "publish-plan":
            body = json.loads(args.body_input_json.read_text())
            if not isinstance(body, dict):
                raise DeliveryError("PR body inputs must be a JSON object")
            result = publication_plan(
                args.state_dir, args.path, args.title, args.commit_message, body,
                tier=args.tier, risk_surfaces=tuple(args.risk_surface),
                risk_assessment_complete=args.risk_assessment_complete,
                review_gate_complete=args.review_gate_complete,
            )
        elif args.command == "publish-full":
            body = json.loads(args.body_input_json.read_text())
            if not isinstance(body, dict):
                raise DeliveryError("PR body inputs must be a JSON object")
            result = publish_full(args.state_dir, args.path, args.title, body, args.evidence_file)
        else:
            plan = json.loads(args.plan_file.read_text())
            if not isinstance(plan, dict):
                raise DeliveryError("Publication plan must be a JSON object")
            result = publish(args.state_dir, plan, args.expected_plan_sha256,
                             args.verified_plan_sha256, args.reviewed_plan_sha256)
    except (DeliveryError, service.ServiceError, publication.PublicationRefusal, publication.PublicationCommandError,
            agent_worktree.WorktreeLifecycleError, service.ServiceError, OSError, ValueError) as exc:
        print(f"openhands-delivery: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
