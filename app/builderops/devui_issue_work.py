"""Read-only continuity from one governed Issue to its supervised work/results.

No task state or approval lives here. GitHub supplies the observations; the
existing coding-agent workflow must freshly establish eligibility and ownership.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.builderops import cockpit_github_plane as github


_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)\Z")
_AGENT_STATES = {"agent:ready", "agent:in-progress", "agent:blocked", "agent:needs-human"}
_MAX_PULLS = 5


def issue_handoff(issue: Mapping[str, Any], source_ref: Mapping[str, Any]) -> tuple[str, str]:
    """Return observed state and bounded recourse, never an execution grant."""
    state = issue.get("state")
    raw_labels = issue.get("labels")
    labels_known = isinstance(raw_labels, list) and all(
        isinstance(label, dict) and isinstance(label.get("name"), str)
        for label in raw_labels
    )
    labels = sorted({label["name"] for label in raw_labels if label["name"] in _AGENT_STATES}) if isinstance(raw_labels, list) and labels_known else []
    if not isinstance(state, str) or state not in {"open", "closed"} or not labels_known or len(labels) > 1:
        observation = "The Issue's work state is missing or contradictory; readiness is not established."
        request = "Inspect the current Issue and reconcile its work state before proposing implementation."
    elif state == "closed":
        observation = "GitHub reports this Issue as closed. Closure alone does not establish delivery or availability to try."
        if labels:
            observation += " An active agent label remains and needs reconciliation."
        request = "Review the linked result, explain how to try it and its limitations. Do not reopen or reimplement work from this snapshot."
    elif labels == ["agent:ready"]:
        observation = "GitHub labels this open Issue agent:ready. Eligibility and exclusive ownership still need a fresh check."
        request = "If the current Issue is eligible and unclaimed, implement its bounded scope through the existing issue-to-code workflow."
    elif labels == ["agent:in-progress"]:
        observation = "GitHub labels this Issue in progress. This label alone does not prove a worker is running."
        request = "Find the existing work, lease and linked PR. Continue only with valid ownership; do not launch duplicate work."
    elif labels:
        observation = f"GitHub labels this Issue {labels[0]}. Work is waiting on its recorded blocker or owner input."
        request = "Read the recorded blocker and resolve authorized bounded recovery. Do not claim implementation while the Issue is blocked."
    else:
        observation = "This open Issue has no agent pickup label; it is not established as ready for implementation."
        request = "Review the Issue contract and existing work; establish readiness through the repository workflow before any implementation."
    if not isinstance(issue.get("body"), str):
        observation += " The Issue body was not readable in this snapshot."
        request = "Read the full current Issue before assessing any work; this snapshot does not contain its contract."

    handoff = (
        f"{observation}\n\n"
        "This DevUI page cannot launch or control work. For supervised work, send this request to your coding agent:\n\n"
        f"Work from the exact Issue {source_ref['locator']}. {request} "
        "Read the full current Issue and repository instructions, including source anchors, constraints and acceptance criteria. "
        "Check current readiness, claims and linked PRs; use the existing pickup workflow before edits. "
        "Keep the Issue context through implementation, validation, PR and result. Return the exact PR, checks, how to try the result, "
        "and remaining limitations. This snapshot is context, not approval or a current readiness guarantee.\n\n"
        f"Observed Issue version: {str(source_ref['version'])[:80]}. "
        f"Body SHA-256: {source_ref.get('content_hash', 'unavailable')}. "
        "Return to this Issue's Focus page and refresh to read current results."
    )
    return observation, handoff


def _governs(body: Any, issue_number: int) -> bool:
    """Only one unfenced canonical marker establishes this bounded relation."""
    if not isinstance(body, str):
        return False
    markers: list[int] = []
    fence: str | None = None
    in_comment = False
    for line in body.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        # Fence contents are literal, including HTML comment delimiters. In
        # particular, a comment in the opening info string cannot hide a fence.
        if fence is not None:
            if match:
                marker, suffix = match.groups()
                if marker[0] == fence[0] and len(marker) >= len(fence) and not suffix.strip():
                    fence = None
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if match:
            fence = match[1]
            continue
        if "<!--" in line:
            in_comment = "-->" not in line.split("<!--", 1)[1]
            continue
        if re.match(r"^ {0,3}Governing-Issue\s*:", line, re.IGNORECASE):
            marker_match = re.fullmatch(r"Governing-Issue: #([1-9][0-9]*)", line, re.IGNORECASE)
            if marker_match is None:
                return False
            markers.append(int(marker_match[1]))
    return markers == [issue_number]


def _stamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def read_issue_focus_results(repository: str, issue_number: int) -> dict[str, Any]:
    """Read only PRs addressed by this Issue's bounded timeline, including merged PRs."""
    if not _REPOSITORY.fullmatch(repository) or type(issue_number) is not int or issue_number < 1:
        raise ValueError("an exact repository and Issue number are required")
    result: dict[str, Any] = {
        "pulls": [], "limitations": [],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        owner, name = repository.split("/")
        events = github._paged_rest(owner, name, f"issues/{issue_number}/timeline", page_size=100, max_pages=2)
    except github.GithubReadError:
        result["limitations"].append("Linked PRs could not be read completely from the selected Issue's timeline. Refresh to retry; no result state is inferred.")
        return result

    numbers: list[int] = []
    for event in reversed(events):
        if not isinstance(event, dict):
            result["limitations"].append("An unreadable timeline entry was omitted; the result list may be incomplete.")
            continue
        if event.get("event") != "cross-referenced":
            continue
        source = event.get("source")
        candidate = source.get("issue") if isinstance(source, dict) else None
        if not isinstance(candidate, dict) or not candidate.get("pull_request"):
            continue
        url = candidate.get("html_url")
        match = _PR_URL.fullmatch(url) if isinstance(url, str) else None
        if match is None:
            result["limitations"].append("An invalid PR reference was omitted; the result list may be incomplete.")
            continue
        if match[1].casefold() != repository.casefold():
            continue
        number = int(match[2])
        if number not in numbers:
            numbers.append(number)
    if len(numbers) > _MAX_PULLS:
        result["limitations"].append("Only the five most recently referenced PRs were inspected; older result state remains unassessed.")

    for number in numbers[:_MAX_PULLS]:
        try:
            pull = github._run_gh(["api", f"repos/{repository}/pulls/{number}", "--method", "GET"])
            if not isinstance(pull, dict):
                raise ValueError()
            url = pull.get("html_url")
            match = _PR_URL.fullmatch(url) if isinstance(url, str) else None
            base = pull.get("base")
            base_repo = base.get("repo") if isinstance(base, dict) else None
            head = pull.get("head")
            sha = head.get("sha") if isinstance(head, dict) else None
            if (
                type(pull.get("number")) is not int or pull["number"] != number
                or match is None or match[1].casefold() != repository.casefold() or int(match[2]) != number
                or not isinstance(base_repo, dict) or str(base_repo.get("full_name", "")).casefold() != repository.casefold()
                or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                or not _stamp(pull.get("updated_at")) or pull.get("state") not in {"open", "closed"}
                or type(pull.get("merged")) is not bool
            ):
                raise ValueError()
            if not _governs(pull.get("body"), issue_number):
                continue
            state = pull["state"]
            merge_sha = pull.get("merge_commit_sha") if pull["merged"] else None
            if pull["merged"]:
                if state != "closed" or not _stamp(pull.get("merged_at")) or not isinstance(merge_sha, str) or not _SHA.fullmatch(merge_sha):
                    raise ValueError()
                state = "merged"
            elif pull.get("merged_at") is not None:
                raise ValueError()
            fact = {
                "number": number, "url": url, "state": state, "head_sha": sha,
                "merge_sha": merge_sha, "updated_at": pull["updated_at"],
                "body_sha256": hashlib.sha256(pull["body"].encode()).hexdigest(),
            }
            result["pulls"].append(fact)
        except (github.GithubReadError, ValueError, TypeError):
            result["limitations"].append(f"PR #{number} could not be read reliably; its current result state remains unassessed.")
    result["limitations"] = list(dict.fromkeys(result["limitations"]))
    if not result["pulls"] and not result["limitations"]:
        result["limitations"].append("No explicitly governed PR was found in this Issue's current timeline. This does not establish that work has not started.")
    return result


def append_issue_results(inputs: dict[str, Any], results: Mapping[str, Any]) -> None:
    """Project repository observations in the existing Focus fields."""
    authority = inputs["subject"]["authority_ref"]
    for pull in results["pulls"]:
        digest = hashlib.sha256(json.dumps(pull, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        source = {
            "source_type": "github_pull_request", "source_id": f"{authority['source_id'].split('#')[0]}#{pull['number']}",
            "locator": pull["url"], "version": pull["updated_at"], "content_hash": digest,
        }
        summary = (
            f"PR #{pull['number']} is {pull['state']}: {pull['url']}. "
            f"Observed head: {pull['head_sha']}. "
            + (f"Merge commit: {pull['merge_sha']}. " if pull["merge_sha"] else "")
            + f"Inspect checks: {pull['url']}/checks. Check outcomes, deployment, trial and acceptance are not assessed by this read."
        )
        inputs["evidence"].append({
            "claim_id": f"issue-pr:{pull['number']}:{digest[:16]}", "claim": summary,
            "source_ref": source, "availability": "available", "freshness": "fresh",
            "coverage": "partial", "cardinality": "nonempty", "linkage": "linked",
            "captured_at": results["captured_at"], "limitation": "Repository observation only; no delivery or owner outcome is inferred.",
        })
        inputs["receipts"].append({
            "receipt_ref": pull["url"], "source_ref": source,
            "correlation": {"status": "linked", "method": "governed_reference", "authority_ref": dict(authority)},
        })
    for reason in results["limitations"]:
        inputs["limitations"].append({
            "kind": "issue_results_unassessed", "reason": reason,
            "source_ref": dict(authority), "evidence_state": "partial", "linkage": "linked",
        })
