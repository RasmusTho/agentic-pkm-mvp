#!/usr/bin/env python3
"""Build a compact CI failure context pack from GitHub Actions logs.

The collector treats logs, PR text, and workflow metadata as untrusted data. It
does not execute commands found in logs, rerun workflows, mutate PRs, or call
agent repair.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


FAILURE_CLASSES: tuple[str, ...] = (
    "pytest_failure",
    "ruff_failure",
    "governance_pr_contract_failure",
    "import_boundary_failure",
    "timeout_or_infra",
    "unknown_failure",
)

MAX_BLOCK_LINES = 35
MAX_BLOCK_CHARS = 6000


@dataclass(frozen=True)
class LogSource:
    name: str
    text: str


@dataclass(frozen=True)
class FailureContext:
    repository: str
    pr_number: int | None
    head_sha: str
    base_branch: str | None
    workflow_name: str
    run_id: str
    job_name: str
    check_name: str
    failing_step: str | None
    invoked_command: str | None
    failure_class: str
    first_useful_failure_block: str
    suspected_owner_script_or_test_file: str | None
    appears_caused_by_pr: str
    actionable_by_autonomous_repair: bool
    human_exception_required: bool
    unknowns_missing_evidence: list[str]
    safe_next_action: str


_OWNER_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bFAILED\s+(tests/[A-Za-z0-9_./-]+\.py(?:::[A-Za-z0-9_./:-]+)?)"),
    re.compile(r"\b(tests/[A-Za-z0-9_./-]+\.py(?:::[A-Za-z0-9_./:-]+)?)"),
    re.compile(r"\b(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))"),
    re.compile(r"\b(app/[A-Za-z0-9_./-]+\.py)"),
    re.compile(r"\b(\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)"),
    re.compile(r"\b(importlinter\.ini)"),
)


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", value)


def _strip_timestamp(line: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+", "", line)


def _clean_line(line: str) -> str:
    return _strip_timestamp(_strip_ansi(line)).rstrip()


def _read_sources(paths: Sequence[Path], zips: Sequence[Path]) -> list[LogSource]:
    sources: list[LogSource] = []
    for path in paths:
        sources.append(LogSource(name=str(path), text=path.read_text(encoding="utf-8")))
    for path in zips:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith("/"):
                    continue
                try:
                    text = archive.read(name).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                sources.append(LogSource(name=f"{path}:{name}", text=text))
    return sources


def _load_event(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _event_workflow_run(event: dict[str, object]) -> dict[str, object]:
    run = event.get("workflow_run")
    return run if isinstance(run, dict) else {}


def _first_pr_number(run: dict[str, object]) -> int | None:
    prs = run.get("pull_requests")
    if not isinstance(prs, list) or not prs:
        return None
    first = prs[0]
    if not isinstance(first, dict):
        return None
    number = first.get("number")
    return number if isinstance(number, int) else None


def _head_branch_base(run: dict[str, object]) -> str | None:
    prs = run.get("pull_requests")
    if not isinstance(prs, list) or not prs:
        return None
    first = prs[0]
    if not isinstance(first, dict):
        return None
    base = first.get("base")
    if not isinstance(base, dict):
        return None
    ref = base.get("ref")
    return ref if isinstance(ref, str) and ref else None


def _classify(text: str, source_name: str) -> str:
    haystack = f"{source_name}\n{text}".lower()
    if re.search(r"^[^:\n]+\.py:\d+:\d+:\s+[a-z]\d{3}\b", text, re.M | re.I) or re.search(
        r"\bFound \d+ errors?\b", text
    ):
        return "ruff_failure"
    if any(
        token in haystack
        for token in (
            "pr body must include",
            "direct repair block",
            "pr-contract",
            "issue is missing required sections",
            "governance-lane prs may only change approved surfaces",
        )
    ):
        return "governance_pr_contract_failure"
    if any(
        token in haystack
        for token in (
            "broken contracts",
            "forbidden import",
            "import-boundary",
            "import boundary",
        )
    ):
        return "import_boundary_failure"
    if any(
        token in haystack
        for token in (
            "timed out",
            "timeout-minutes",
            "the operation was canceled",
            "runner stopped",
            "no space left on device",
            "connection reset",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "rate limit exceeded",
        )
    ):
        return "timeout_or_infra"
    if re.search(r"\bFAILED\s+tests/|\bE\s+AssertionError\b|short test summary info", text):
        return "pytest_failure"
    return "unknown_failure"


def _line_score(line: str, failure_class: str) -> int:
    lower = line.lower()
    score = 0
    if "::error" in lower or "error:" in lower or "failed" in lower:
        score += 3
    if failure_class == "pytest_failure" and (
        "failed tests/" in lower or "short test summary" in lower or "assertionerror" in lower
    ):
        score += 8
    if failure_class == "ruff_failure" and re.search(r"\.py:\d+:\d+:\s+[a-z]\d{3}", line, re.I):
        score += 8
    if failure_class == "governance_pr_contract_failure" and (
        "pr body must include" in lower or "core.setfailed" in lower or "direct repair" in lower
    ):
        score += 8
    if failure_class == "import_boundary_failure" and (
        "broken contracts" in lower or "lint-imports" in lower or "forbidden import" in lower
    ):
        score += 8
    if failure_class == "timeout_or_infra" and (
        "timed out" in lower or "operation was canceled" in lower or "no space left" in lower
    ):
        score += 8
    return score


def _failure_block(text: str, failure_class: str) -> str:
    lines = [_clean_line(line) for line in text.splitlines()]
    if not lines:
        return ""
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        score = _line_score(line, failure_class)
        if score > best_score:
            best_index = index
            best_score = score
    start = max(0, best_index - 8)
    end = min(len(lines), best_index + MAX_BLOCK_LINES - 8)
    block = "\n".join(line for line in lines[start:end] if line.strip()).strip()
    return block[:MAX_BLOCK_CHARS]


def _extract_command(text: str) -> str | None:
    lines = [_clean_line(line) for line in text.splitlines()]
    for index, line in enumerate(lines):
        if line == "##[group]Run" and index + 1 < len(lines):
            return lines[index + 1].strip() or None
        if line.startswith("Run "):
            command = line.removeprefix("Run ").strip()
            return command or None
        if line.startswith("+ "):
            return line.removeprefix("+ ").strip() or None
    for pattern in (
        r"\b(pytest\s+[^\n]+)",
        r"\b(ruff\s+check[^\n]*)",
        r"\b(lint-imports\s+[^\n]*)",
        r"\b(python3?\s+scripts/[^\n]+)",
    ):
        match = re.search(pattern, text)
        if match:
            return _clean_line(match.group(1)).strip()
    return None


def _extract_failing_step(source_name: str, text: str, failure_class: str) -> str | None:
    path = source_name.split(":", 1)[-1]
    stem = Path(path).stem
    if stem and stem not in {"logs", "log"} and not stem.isdigit():
        return stem
    for line in text.splitlines():
        clean = _clean_line(line).strip()
        if clean.startswith("##[group]Run"):
            continue
        if _line_score(clean, failure_class) >= 8:
            return clean[:160]
    return None


def _infer_owner(text: str, source_name: str) -> str | None:
    haystack = f"{source_name}\n{text}"
    for pattern in _OWNER_PATH_PATTERNS:
        match = pattern.search(haystack)
        if match:
            return match.group(1)
    return None


def _rank_class(failure_class: str) -> int:
    order = {
        "governance_pr_contract_failure": 0,
        "ruff_failure": 1,
        "pytest_failure": 2,
        "import_boundary_failure": 3,
        "timeout_or_infra": 4,
        "unknown_failure": 5,
    }
    return order[failure_class]


def _select_primary(sources: Iterable[LogSource]) -> tuple[LogSource, str]:
    classified: list[tuple[int, int, LogSource, str]] = []
    all_sources = list(sources)
    for index, source in enumerate(all_sources):
        failure_class = _classify(source.text, source.name)
        if failure_class != "unknown_failure" or "error" in source.text.lower():
            classified.append((_rank_class(failure_class), index, source, failure_class))
    if not classified:
        if all_sources:
            scored_sources = sorted(
                enumerate(all_sources),
                key=lambda item: (
                    -sum(
                        token in item[1].text.lower()
                        for token in ("error", "failed", "unexpected", "exception")
                    ),
                    item[0],
                ),
            )
            return scored_sources[0][1], "unknown_failure"
        empty = LogSource(name="unknown", text="")
        return empty, "unknown_failure"
    _, _, source, failure_class = sorted(classified, key=lambda item: (item[0], item[1]))[0]
    return source, failure_class


def _unknowns(
    pr_number: int | None,
    base_branch: str | None,
    source: LogSource,
    command: str | None,
    owner: str | None,
) -> list[str]:
    missing: list[str] = []
    if pr_number is None:
        missing.append("PR mapping unavailable from workflow_run payload")
    if not base_branch:
        missing.append("base branch unavailable")
    if not source.text:
        missing.append("no log text available")
    if command is None:
        missing.append("invoked command not visible in retained log block")
    if owner is None:
        missing.append("owner script or test file not inferable from logs")
    return missing


def _safe_next_action(failure_class: str, actionable: bool, human_required: bool) -> str:
    if human_required:
        return "emit Human Exception packet with missing evidence; do not repair automatically"
    if failure_class == "timeout_or_infra":
        return "attach context pack to PR evidence; autonomous repair should wait for fresh evidence"
    if actionable:
        return "hand context pack to CI repair agent for bounded diagnosis on the PR branch"
    return "attach context pack to PR evidence and block repair until more evidence is available"


def _appears_caused_by_pr(failure_class: str, pr_number: int | None) -> str:
    if pr_number is None:
        return "unknown"
    if failure_class in {
        "pytest_failure",
        "ruff_failure",
        "governance_pr_contract_failure",
        "import_boundary_failure",
    }:
        return "likely"
    if failure_class == "timeout_or_infra":
        return "unclear"
    return "unknown"


def build_context(
    *,
    repository: str,
    run_id: str,
    sources: Sequence[LogSource],
    pr_number: int | None = None,
    head_sha: str = "",
    base_branch: str | None = None,
    workflow_name: str = "",
    job_name: str = "",
    check_name: str = "",
) -> FailureContext:
    source, failure_class = _select_primary(sources)
    block = _failure_block(source.text, failure_class)
    command = _extract_command(source.text)
    owner = _infer_owner(source.text, source.name)
    step = _extract_failing_step(source.name, source.text, failure_class)
    human_required = failure_class == "unknown_failure" and not block
    actionable = failure_class not in {"timeout_or_infra", "unknown_failure"} and bool(block)
    missing = _unknowns(pr_number, base_branch, source, command, owner)
    return FailureContext(
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        base_branch=base_branch,
        workflow_name=workflow_name,
        run_id=run_id,
        job_name=job_name or check_name or "unknown",
        check_name=check_name or workflow_name or "unknown",
        failing_step=step,
        invoked_command=command,
        failure_class=failure_class,
        first_useful_failure_block=block,
        suspected_owner_script_or_test_file=owner,
        appears_caused_by_pr=_appears_caused_by_pr(failure_class, pr_number),
        actionable_by_autonomous_repair=actionable,
        human_exception_required=human_required,
        unknowns_missing_evidence=missing,
        safe_next_action=_safe_next_action(failure_class, actionable, human_required),
    )


def render_markdown(context: FailureContext) -> str:
    owner = context.suspected_owner_script_or_test_file or "unknown"
    pr = f"#{context.pr_number}" if context.pr_number is not None else "unknown"
    unknowns = "\n".join(f"- {item}" for item in context.unknowns_missing_evidence) or "- none"
    block = context.first_useful_failure_block or "(no useful failure block found)"
    return "\n".join(
        [
            "# CI Failure Context",
            "",
            f"- Repository: `{context.repository}`",
            f"- PR: {pr}",
            f"- Head SHA: `{context.head_sha or 'unknown'}`",
            f"- Base branch: `{context.base_branch or 'unknown'}`",
            f"- Workflow: `{context.workflow_name or 'unknown'}`",
            f"- Run ID: `{context.run_id}`",
            f"- Job: `{context.job_name}`",
            f"- Check: `{context.check_name}`",
            f"- Failure class: `{context.failure_class}`",
            f"- Failing step: `{context.failing_step or 'unknown'}`",
            f"- Invoked command: `{context.invoked_command or 'unknown'}`",
            f"- Suspected owner: `{owner}`",
            f"- Appears caused by PR: `{context.appears_caused_by_pr}`",
            f"- Actionable by autonomous repair: `{context.actionable_by_autonomous_repair}`",
            f"- Human exception required: `{context.human_exception_required}`",
            f"- Safe next action: {context.safe_next_action}",
            "",
            "## First Useful Failure Block",
            "",
            "```text",
            block,
            "```",
            "",
            "## Unknowns / Missing Evidence",
            "",
            unknowns,
            "",
        ]
    )


def _write_outputs(context: FailureContext, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(asdict(context), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(context), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--base-branch", default="")
    parser.add_argument("--workflow-name", default="")
    parser.add_argument("--job-name", default="")
    parser.add_argument("--check-name", default="")
    parser.add_argument("--event-json", type=Path)
    parser.add_argument("--log-file", type=Path, action="append", default=[])
    parser.add_argument("--log-zip", type=Path, action="append", default=[])
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    event = _load_event(args.event_json)
    run = _event_workflow_run(event)
    repository_event = event.get("repository")
    repository = args.repository
    if not repository and isinstance(repository_event, dict):
        repository = str(repository_event.get("full_name", ""))
    run_id = args.run_id or str(run.get("id", ""))
    pr_number = args.pr_number if args.pr_number is not None else _first_pr_number(run)
    head_sha = args.head_sha or str(run.get("head_sha", ""))
    base_branch = args.base_branch or _head_branch_base(run)
    workflow_name = args.workflow_name or str(run.get("name", ""))
    check_name = args.check_name or workflow_name
    sources = _read_sources(args.log_file, args.log_zip)
    context = build_context(
        repository=repository,
        run_id=run_id,
        sources=sources,
        pr_number=pr_number,
        head_sha=head_sha,
        base_branch=base_branch,
        workflow_name=workflow_name,
        job_name=args.job_name,
        check_name=check_name,
    )
    _write_outputs(context, args.output_json, args.output_markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
