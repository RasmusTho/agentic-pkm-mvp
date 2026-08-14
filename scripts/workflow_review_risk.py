"""Infer GitHub Actions workflow risk and validate exact-bound local review evidence."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


WORKFLOW_PREFIX = ".github/workflows/"
WORKFLOW_SUFFIXES = (".yml", ".yaml")
WORKFLOW_INFERRED_RISKS = {"concurrency", "state-machine"}
WORKFLOW_REVIEW_RECEIPT_CONTRACT = "review-before-ci-workflow-risk.v1"
WORKFLOW_REVIEW_SCENARIOS = (
    "pull_request_opened",
    "pull_request_synchronize",
    "pull_request_reopened",
    "pure_metadata_edit",
    "base_ref_retarget",
    "source_revision_during_active_ci",
    "metadata_edit_during_code_ci",
    "main_push_during_pr_ci",
    "same_sha_rerun",
)
DEFAULT_RECEIPT_DIR = Path(".codex-tmp/review-before-ci")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CONCURRENCY_ROOT_RE = re.compile(r"^\s*concurrency\s*:", re.IGNORECASE)
_CONCURRENCY_CHILD_RE = re.compile(
    r"^\s*(?:group|cancel-in-progress)\s*:", re.IGNORECASE
)
_ON_KEY_RE = re.compile(r"^\s*['\"]?on['\"]?\s*:", re.IGNORECASE)
_PULL_REQUEST_BLOCK_RE = re.compile(
    r"^\s*pull_request(?:_target)?\s*:", re.IGNORECASE
)
_PULL_REQUEST_FILTER_RE = re.compile(
    r"^\s*(?:types|branches|branches-ignore|paths|paths-ignore)\s*:",
    re.IGNORECASE,
)
_EVENT_REFERENCE_RE = re.compile(
    r"\bgithub\.(?:event_name|event(?:\.[A-Za-z0-9_]+)+|ref|base_ref|head_ref)\b"
)
_PULL_REQUEST_FLOW_TRIGGER_RE = re.compile(
    r"^\s*['\"]?on['\"]?\s*:\s*.*\bpull_request(?:_target)?\b",
    re.IGNORECASE,
)
_IF_KEY_RE = re.compile(r"^\s*if\s*:")
_YAML_KEY_RE = re.compile(r"^\s*[A-Za-z0-9_.-]+\s*:")


class WorkflowReviewRiskError(ValueError):
    """Raised when workflow review evidence cannot be constructed safely."""


def infer_workflow_risk_surfaces(
    changed_files: Sequence[str], workflow_diff: str | None
) -> list[str]:
    """Infer protected workflow risk from the actual changed workflow patch."""

    workflow_paths = [path for path in changed_files if is_workflow_path(path)]
    if not workflow_paths or workflow_diff is None:
        return []

    inferred: set[str] = set()
    for hunk in _workflow_diff_hunks(workflow_diff):
        semantic_changed_indices = [
            index
            for index, line in enumerate(hunk)
            if _is_changed_diff_line(line)
            and _strip_diff_prefix(line).strip()
            and not _strip_diff_prefix(line).lstrip().startswith("#")
        ]
        if not semantic_changed_indices:
            continue
        if any(
            _CONCURRENCY_ROOT_RE.search(_strip_diff_prefix(hunk[index]))
            or _changed_line_belongs_to_key_chain(
                hunk, index, (_CONCURRENCY_ROOT_RE, _CONCURRENCY_CHILD_RE)
            )
            for index in semantic_changed_indices
        ):
            inferred.add("concurrency")
        if any(
            _PULL_REQUEST_FLOW_TRIGGER_RE.search(_strip_diff_prefix(hunk[index]))
            or _changed_line_belongs_to_key_chain(
                hunk, index, (_ON_KEY_RE, _PULL_REQUEST_BLOCK_RE)
            )
            or _changed_line_belongs_to_key_chain(
                hunk,
                index,
                (_ON_KEY_RE, _PULL_REQUEST_BLOCK_RE, _PULL_REQUEST_FILTER_RE),
            )
            for index in semantic_changed_indices
        ):
            inferred.add("state-machine")
        changed_if_admission = any(
            (if_index := _key_index_for_line(hunk, index, _IF_KEY_RE)) is not None
            and _EVENT_REFERENCE_RE.search(_yaml_key_block_text(hunk, if_index))
            is not None
            for index in semantic_changed_indices
        )
        if changed_if_admission:
            inferred.add("state-machine")
    return sorted(inferred)


def canonical_diff_sha256(diff_text: str) -> str:
    """Return the stable digest used to bind local review to a workflow patch."""

    return hashlib.sha256(_canonicalize_diff(diff_text).encode("utf-8")).hexdigest()


def validate_workflow_review_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    head_sha: str | None,
    base_sha: str | None,
    diff_sha256: str | None,
    inferred_risks: Sequence[str],
) -> list[str]:
    """Return fail-closed validation errors for a local workflow review receipt."""

    if receipt is None:
        return ["workflow review receipt is required"]
    errors: list[str] = []
    expected_keys = {
        "contract",
        "head_sha",
        "base_sha",
        "diff_sha256",
        "risk_surfaces",
        "verdict",
        "reviewer",
        "scenarios",
    }
    actual_keys = set(receipt)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        errors.append(f"receipt keys mismatch: missing={missing}, extra={extra}")
    if receipt.get("contract") != WORKFLOW_REVIEW_RECEIPT_CONTRACT:
        errors.append("receipt contract is not review-before-ci-workflow-risk.v1")
    if not _valid_sha(head_sha):
        errors.append("current head_sha must be an exact 40-character lowercase Git SHA")
    elif receipt.get("head_sha") != head_sha:
        errors.append("receipt head_sha does not match the current publishable head")
    if not _valid_sha(base_sha):
        errors.append("current base_sha must be an exact 40-character lowercase Git SHA")
    elif receipt.get("base_sha") != base_sha:
        errors.append("receipt base_sha does not match the current base")
    if diff_sha256 is None:
        errors.append("canonical workflow diff digest is unavailable")
    elif receipt.get("diff_sha256") != diff_sha256:
        errors.append("receipt diff_sha256 does not match the current workflow diff")
    expected_risks = sorted(set(inferred_risks) & WORKFLOW_INFERRED_RISKS)
    if receipt.get("risk_surfaces") != expected_risks:
        errors.append("receipt risk_surfaces do not exactly match inferred workflow risks")
    if receipt.get("verdict") != "pass":
        errors.append("receipt verdict must be pass")
    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append("receipt reviewer must be a non-empty string")
    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, Mapping):
        errors.append("receipt scenarios must be an object")
    else:
        if set(scenarios) != set(WORKFLOW_REVIEW_SCENARIOS):
            errors.append("receipt scenarios must exactly match the closed workflow scenario set")
        non_pass = sorted(name for name, verdict in scenarios.items() if verdict != "pass")
        if non_pass:
            errors.append(f"receipt scenarios are not all pass: {non_pass}")
    return errors


def build_workflow_review_receipt_template(
    *,
    head_sha: str,
    base_sha: str,
    workflow_diff: str,
    inferred_risks: Sequence[str],
) -> dict[str, Any]:
    """Return a pending, exact-bound receipt template for the required local review."""

    if not _valid_sha(head_sha) or not _valid_sha(base_sha):
        raise WorkflowReviewRiskError(
            "receipt templates require exact lowercase 40-character head and base SHAs"
        )
    risks = sorted(set(inferred_risks) & WORKFLOW_INFERRED_RISKS)
    if not risks:
        raise WorkflowReviewRiskError(
            "receipt templates are valid only for inferred workflow high risk"
        )
    return {
        "contract": WORKFLOW_REVIEW_RECEIPT_CONTRACT,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "diff_sha256": canonical_diff_sha256(workflow_diff),
        "risk_surfaces": risks,
        "verdict": "pending",
        "reviewer": "",
        "scenarios": {name: "pending" for name in WORKFLOW_REVIEW_SCENARIOS},
    }


def is_workflow_path(path: str) -> bool:
    return path.startswith(WORKFLOW_PREFIX) and path.endswith(WORKFLOW_SUFFIXES)


def _changed_line_belongs_to_key_block(
    hunk: Sequence[str], index: int, key_pattern: re.Pattern[str]
) -> bool:
    return _changed_line_belongs_to_key_chain(hunk, index, (key_pattern,))


def _changed_line_belongs_to_key_chain(
    hunk: Sequence[str],
    index: int,
    key_chain: Sequence[re.Pattern[str]],
) -> bool:
    """Return whether a changed line is a key or scalar value under a YAML key chain."""

    if not key_chain:
        return False
    key_index = index
    content = _strip_diff_prefix(hunk[key_index])
    if key_chain[-1].search(content) is None:
        found = _find_ancestor_key_index(
            hunk, before_index=key_index, key_pattern=key_chain[-1], descendant=content
        )
        if found is None:
            return False
        key_index = found
    for parent_pattern in reversed(key_chain[:-1]):
        child = _strip_diff_prefix(hunk[key_index])
        found = _find_ancestor_key_index(
            hunk, before_index=key_index, key_pattern=parent_pattern, descendant=child
        )
        if found is None:
            return False
        key_index = found
    return True


def _key_index_for_line(
    hunk: Sequence[str], index: int, key_pattern: re.Pattern[str]
) -> int | None:
    content = _strip_diff_prefix(hunk[index])
    if key_pattern.search(content):
        return index
    return _find_ancestor_key_index(
        hunk, before_index=index, key_pattern=key_pattern, descendant=content
    )


def _yaml_key_block_text(hunk: Sequence[str], key_index: int) -> str:
    key = _strip_diff_prefix(hunk[key_index])
    key_indent = len(key) - len(key.lstrip())
    block = [key]
    for line in hunk[key_index + 1 :]:
        if line.startswith(("diff --git ", "index ", "--- ", "+++ ", "@@")):
            break
        content = _strip_diff_prefix(line)
        stripped = content.strip()
        if not stripped:
            block.append(content)
            continue
        indent = len(content) - len(content.lstrip())
        if _YAML_KEY_RE.match(content) and indent <= key_indent:
            break
        block.append(content)
    return "\n".join(block)


def _find_ancestor_key_index(
    hunk: Sequence[str],
    *,
    before_index: int,
    key_pattern: re.Pattern[str],
    descendant: str,
) -> int | None:
    descendant_indent = len(descendant) - len(descendant.lstrip())
    for candidate_index in range(before_index - 1, -1, -1):
        previous = hunk[candidate_index]
        if previous.startswith(("diff --git ", "index ", "--- ", "+++ ", "@@")):
            continue
        candidate = _strip_diff_prefix(previous)
        stripped = candidate.strip()
        if not stripped or stripped.startswith("#"):
            continue
        candidate_indent = len(candidate) - len(candidate.lstrip())
        if candidate_indent >= descendant_indent:
            continue
        if key_pattern.search(candidate):
            return candidate_index
        if _YAML_KEY_RE.match(candidate):
            return None
    return None


def _workflow_diff_hunks(diff_text: str) -> list[list[str]]:
    canonical = _canonicalize_diff(diff_text)
    hunks: list[list[str]] = []
    current: list[str] = []
    current_is_workflow = False
    for line in canonical.splitlines():
        if line.startswith("diff --git "):
            if current and current_is_workflow:
                hunks.append(current)
            current = [line]
            current_is_workflow = ".github/workflows/" in line
            continue
        if line.startswith("@@"):
            if current and current_is_workflow and any(
                item.startswith("@@") for item in current
            ):
                hunks.append(current)
                current = []
            current.append(line)
            continue
        current.append(line)
    if current and current_is_workflow:
        hunks.append(current)
    if not hunks and canonical:
        return [canonical.splitlines()]
    return hunks


def _is_changed_diff_line(line: str) -> bool:
    return line.startswith(("+", "-")) and not line.startswith(("+++", "---"))


def _strip_diff_prefix(line: str) -> str:
    if _is_changed_diff_line(line) or line.startswith(" "):
        return line[1:]
    return line


def _canonicalize_diff(diff_text: str) -> str:
    canonical = diff_text.replace("\r\n", "\n").replace("\r", "\n")
    if canonical and not canonical.endswith("\n"):
        canonical += "\n"
    return canonical


def _valid_sha(value: str | None) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None
