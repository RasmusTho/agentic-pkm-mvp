#!/usr/bin/env python3
"""Derive bounded GitHub Actions review risks from an actual Git workflow diff.

This is deliberately a small structural interpreter, not a general GitHub
Actions validator.  PyYAML's composed node tree retains mapping/sequence
boundaries and scalar content without relying on indentation or regex hunks.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


WORKFLOW_PREFIX = ".github/workflows/"
RISK_CONCURRENCY = "concurrency"
RISK_STATE_MACHINE = "state-machine"


class WorkflowReviewRiskError(ValueError):
    """Raised when workflow semantic evidence or its receipt is not trustworthy."""


@dataclass(frozen=True)
class WorkflowRiskEvidence:
    base_sha: str
    head_sha: str
    diff_digest: str
    risks: tuple[str, ...]
    workflow_paths: tuple[str, ...]


def infer_workflow_risks(before: str | None, after: str | None) -> set[str]:
    """Return risks whose bounded workflow semantics changed between documents."""

    previous = _workflow_semantics(before)
    current = _workflow_semantics(after)
    risks: set[str] = set()
    if previous["concurrency"] != current["concurrency"]:
        risks.add(RISK_CONCURRENCY)
    if previous["pull_request"] != current["pull_request"] or previous["job_if"] != current["job_if"]:
        risks.add(RISK_STATE_MACHINE)
    return risks


def workflow_risk_evidence_from_git(
    repo: Path, *, base: str = "origin/main", head: str = "HEAD"
) -> WorkflowRiskEvidence:
    """Inspect every workflow path in Git's real diff, rather than caller input."""

    base_sha = _git(repo, "rev-parse", "--verify", base).strip()
    head_sha = _git(repo, "rev-parse", "--verify", head).strip()
    paths = tuple(
        path
        for path in _git(repo, "diff", "--name-only", "--diff-filter=ACDMRT", base_sha, head_sha).splitlines()
        if _is_workflow_path(path)
    )
    diff = _git(repo, "diff", "--no-ext-diff", "--binary", base_sha, head_sha, "--", *paths) if paths else ""
    risks: set[str] = set()
    for path in paths:
        risks.update(
            infer_workflow_risks(
                _git_show_optional(repo, base_sha, path),
                _git_show_optional(repo, head_sha, path),
            )
        )
    return WorkflowRiskEvidence(
        base_sha=base_sha,
        head_sha=head_sha,
        diff_digest=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        risks=tuple(sorted(risks)),
        workflow_paths=paths,
    )


def validate_workflow_review_receipt(
    receipt_text: str, evidence: WorkflowRiskEvidence
) -> dict[str, Any]:
    """Require a pass receipt bound to the exact workflow diff and inferred risks."""

    try:
        receipt = json.loads(receipt_text)
    except json.JSONDecodeError as exc:
        raise WorkflowReviewRiskError("workflow review receipt must be valid JSON") from exc
    if not isinstance(receipt, dict):
        raise WorkflowReviewRiskError("workflow review receipt must be a JSON object")
    expected: dict[str, Any] = {
        "version": 1,
        "base_sha": evidence.base_sha,
        "head_sha": evidence.head_sha,
        "diff_digest": evidence.diff_digest,
        "risks": list(evidence.risks),
        "verdict": "pass",
        "scenario_matrix_complete": True,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise WorkflowReviewRiskError(
                f"workflow review receipt {field} does not bind the actual workflow diff"
            )
    if not isinstance(receipt.get("reviewer"), str) or not receipt["reviewer"].strip():
        raise WorkflowReviewRiskError("workflow review receipt requires a named reviewer")
    return receipt


def _workflow_semantics(document: str | None) -> dict[str, Any]:
    if document is None or not document.strip():
        return {"concurrency": None, "pull_request": None, "job_if": ()}
    try:
        root = yaml.compose(document, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise WorkflowReviewRiskError("workflow YAML cannot be structurally interpreted") from exc
    if root is None:
        return {"concurrency": None, "pull_request": None, "job_if": ()}
    if not isinstance(root, MappingNode):
        raise WorkflowReviewRiskError("workflow YAML root must be a mapping")
    concurrency = _mapping_value(root, "concurrency")
    trigger = _mapping_value(root, "on")
    jobs = _mapping_value(root, "jobs")
    return {
        "concurrency": _fingerprint(concurrency),
        "pull_request": _pull_request_trigger(trigger),
        "job_if": _job_admission_conditions(jobs),
    }


def _pull_request_trigger(node: Node | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ScalarNode):
        return _fingerprint(node) if node.value == "pull_request" else None
    if isinstance(node, SequenceNode):
        matching = [child for child in node.value if _is_pull_request_scalar(child)]
        return tuple(_fingerprint(child) for child in matching) or None
    if isinstance(node, MappingNode):
        value = _mapping_value(node, "pull_request")
        return _fingerprint(value) if value is not None else None
    return None


def _job_admission_conditions(jobs: Node | None) -> tuple[tuple[str, Any], ...]:
    if not isinstance(jobs, MappingNode):
        return ()
    admissions: list[tuple[str, Any]] = []
    for job_name, job in jobs.value:
        if not isinstance(job_name, ScalarNode) or not isinstance(job, MappingNode):
            continue
        # Only this direct job mapping is admission.  A nested `steps[*].if`,
        # including beneath a job literally named `steps`, is execution detail.
        condition = _mapping_value(job, "if")
        if condition is not None:
            admissions.append((job_name.value, _fingerprint(condition)))
    return tuple(admissions)


def _mapping_value(mapping: MappingNode, key: str) -> Node | None:
    for candidate, value in mapping.value:
        if isinstance(candidate, ScalarNode) and candidate.value == key:
            return value
    return None


def _is_pull_request_scalar(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.value == "pull_request"


def _fingerprint(node: Node | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ScalarNode):
        return ("scalar", node.tag, node.value)
    if isinstance(node, SequenceNode):
        return ("sequence", tuple(_fingerprint(item) for item in node.value))
    if isinstance(node, MappingNode):
        return (
            "mapping",
            tuple((_fingerprint(key), _fingerprint(value)) for key, value in node.value),
        )
    raise WorkflowReviewRiskError("workflow YAML contains an unsupported node")


def _is_workflow_path(path: str) -> bool:
    return path.startswith(WORKFLOW_PREFIX) and path.endswith((".yml", ".yaml"))


def _git_show_optional(repo: Path, ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode:
        return None
    return result.stdout


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise WorkflowReviewRiskError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout
