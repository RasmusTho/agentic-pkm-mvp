"""Read-only reconciliation for promoted failure-capture drafts.

The report joins the existing vault draft identity to one explicit,
repository-relative integration reference. Golden cases are read as YAML and
schema fixtures are checked with ``ast``; fixture modules are never imported
or executed.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

import yaml

from app.eval.failure_capture import (
    DRAFT_DIR_NAME,
    DRAFT_KIND_CLASSIFICATION_CASE,
    DRAFT_KIND_SCHEMA_VIOLATION,
    DRAFT_STATUS_PROMOTED,
    read_draft,
)
from app.vault.paths import get_vault_system_dir_rel

REPORT_SCHEMA = "eval_draft_reconciliation.v1"
CLASSIFICATION_GOLDEN_PATH = "docs/eval/classification_golden.yaml"
_CASE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_TEST_NAME_RE = re.compile(r"test_[A-Za-z0-9_]+\Z")
_GOLDEN_REF_RE = re.compile(r"golden-case:([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\Z")
_SCHEMA_REF_RE = re.compile(r"schema-fixture:(.+)::(test_[A-Za-z0-9_]+)\Z")


def _existing_directory(path: Path, *, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} must be an existing directory") from exc
    if not resolved.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return resolved


def _confined_file(root: Path, relative_path: str) -> tuple[Path | None, str | None]:
    """Resolve a normalized repository-relative file without leaving root."""
    if not relative_path or "\\" in relative_path:
        return None, "malformed_repository_path"
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != relative_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None, "malformed_repository_path"

    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None, "symlink_repository_path"
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None, "missing_repository_path"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "repository_path_escapes_root"
    if not resolved.is_file():
        return None, "repository_path_not_file"
    return resolved, None


def _classification_case_counts(repository_root: Path) -> tuple[dict[str, int], str | None]:
    path, path_error = _confined_file(repository_root, CLASSIFICATION_GOLDEN_PATH)
    if path_error is not None or path is None:
        return {}, path_error or "classification_index_unavailable"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}, "classification_index_unreadable"
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != "classification_case.v1"
        or not isinstance(document.get("cases"), list)
    ):
        return {}, "classification_index_malformed"

    counts: dict[str, int] = {}
    for case in document["cases"]:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id")
        if isinstance(case_id, str) and _CASE_ID_RE.fullmatch(case_id):
            counts[case_id] = counts.get(case_id, 0) + 1
    return counts, None


def _integration_lines(notes: str | None) -> list[str]:
    if not isinstance(notes, str):
        return []
    return [
        line
        for line in notes.splitlines()
        if line.lstrip().startswith("integration_ref:")
    ]


def _unverified(
    *, lines: list[str], reason: str, reference: str | None = None
) -> dict[str, Any]:
    return {
        "reference": reference,
        "reference_lines": lines,
        "verified": False,
        "status": "unverified",
        "reason": reason,
        "resolved_target": None,
    }


def _resolve_reference(
    reference: str,
    *,
    lines: list[str],
    draft_kind: str,
    repository_root: Path,
    case_counts: dict[str, int],
    case_index_error: str | None,
) -> dict[str, Any]:
    golden_match = _GOLDEN_REF_RE.fullmatch(reference)
    if golden_match is not None:
        if draft_kind != DRAFT_KIND_CLASSIFICATION_CASE:
            return _unverified(
                lines=lines,
                reference=reference,
                reason="integration_reference_kind_mismatch",
            )
        case_id = golden_match.group(1)
        if case_index_error is not None:
            return _unverified(
                lines=lines, reference=reference, reason=case_index_error
            )
        count = case_counts.get(case_id, 0)
        if count == 0:
            return _unverified(
                lines=lines, reference=reference, reason="golden_case_not_found"
            )
        if count != 1:
            return _unverified(
                lines=lines, reference=reference, reason="golden_case_ambiguous"
            )
        return {
            "reference": reference,
            "reference_lines": lines,
            "verified": True,
            "status": "verified",
            "reason": None,
            "resolved_target": f"{CLASSIFICATION_GOLDEN_PATH}::cases[id={case_id}]",
        }

    schema_match = _SCHEMA_REF_RE.fullmatch(reference)
    if schema_match is None:
        return _unverified(
            lines=lines, reference=reference, reason="malformed_integration_reference"
        )
    if draft_kind != DRAFT_KIND_SCHEMA_VIOLATION:
        return _unverified(
            lines=lines,
            reference=reference,
            reason="integration_reference_kind_mismatch",
        )
    relative_path, test_name = schema_match.groups()
    if (
        not relative_path.startswith("tests/")
        or not relative_path.endswith(".py")
        or not _TEST_NAME_RE.fullmatch(test_name)
    ):
        return _unverified(
            lines=lines, reference=reference, reason="malformed_schema_fixture_reference"
        )
    path, path_error = _confined_file(repository_root, relative_path)
    if path_error is not None or path is None:
        return _unverified(
            lines=lines,
            reference=reference,
            reason=path_error or "schema_fixture_not_found",
        )
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    except (OSError, UnicodeError, SyntaxError):
        return _unverified(
            lines=lines, reference=reference, reason="schema_fixture_unreadable"
        )
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == test_name
    ]
    if not matches:
        return _unverified(
            lines=lines, reference=reference, reason="schema_fixture_test_not_found"
        )
    if len(matches) != 1:
        return _unverified(
            lines=lines, reference=reference, reason="schema_fixture_test_ambiguous"
        )
    return {
        "reference": reference,
        "reference_lines": lines,
        "verified": True,
        "status": "verified",
        "reason": None,
        "resolved_target": f"{relative_path}::{test_name}",
    }


def build_reconciliation_report(
    *, vault_root: Path, repository_root: Path
) -> dict[str, Any]:
    """Return a deterministic, read-only report for promoted drafts only."""
    vault = _existing_directory(vault_root, label="vault_root")
    repository = _existing_directory(repository_root, label="repository_root")
    drafts_dir = vault / get_vault_system_dir_rel(vault) / DRAFT_DIR_NAME
    if drafts_dir.is_symlink():
        raise ValueError("draft directory must not be a symlink")
    try:
        resolved_drafts_dir = drafts_dir.resolve(strict=True)
        resolved_drafts_dir.relative_to(vault)
    except FileNotFoundError:
        resolved_drafts_dir = None
    except ValueError as exc:
        raise ValueError("draft directory must stay within vault_root") from exc

    case_counts, case_index_error = _classification_case_counts(repository)
    records: list[dict[str, Any]] = []
    if resolved_drafts_dir is not None and resolved_drafts_dir.is_dir():
        for path in sorted(resolved_drafts_dir.glob("*.md"), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                continue
            draft = read_draft(vault, path.stem)
            if draft is None or draft.status != DRAFT_STATUS_PROMOTED:
                continue
            lines = _integration_lines(draft.notes)
            if draft.draft_id != path.stem:
                integration = _unverified(
                    lines=lines,
                    reference=lines[0].partition(" ")[2]
                    if len(lines) == 1
                    else None,
                    reason="draft_identity_mismatch",
                )
            elif not lines:
                integration = _unverified(lines=lines, reason="integration_reference_missing")
            elif len(lines) != 1:
                integration = _unverified(
                    lines=lines, reason="integration_reference_ambiguous"
                )
            else:
                line = lines[0]
                if not line.startswith("integration_ref: ") or line != line.strip():
                    integration = _unverified(
                        lines=lines,
                        reference=line.partition(":")[2].strip() or None,
                        reason="malformed_integration_reference_line",
                    )
                else:
                    reference = line[len("integration_ref: ") :]
                    if not reference or reference != reference.strip():
                        integration = _unverified(
                            lines=lines,
                            reference=reference or None,
                            reason="malformed_integration_reference_line",
                        )
                    else:
                        integration = _resolve_reference(
                            reference,
                            lines=lines,
                            draft_kind=draft.kind,
                            repository_root=repository,
                            case_counts=case_counts,
                            case_index_error=case_index_error,
                        )
            provenance_complete = (
                isinstance(draft.decided_by, str)
                and bool(draft.decided_by.strip())
                and isinstance(draft.decided_at, str)
                and bool(draft.decided_at.strip())
                and (draft.notes is None or isinstance(draft.notes, str))
            )
            records.append(
                {
                    "draft_id": path.stem,
                    "kind": draft.kind,
                    "status": draft.status,
                    "decision_provenance": {
                        "decided_by": draft.decided_by,
                        "decided_at": draft.decided_at,
                        "notes": draft.notes,
                        "complete": provenance_complete,
                    },
                    "integration": integration,
                    "needs_integration_review": not integration["verified"],
                }
            )

    return {
        "schema_version": REPORT_SCHEMA,
        "source": "eval.failure_capture.promoted_drafts",
        "promoted_count": len(records),
        "needing_integration_review_count": sum(
            record["needs_integration_review"] for record in records
        ),
        "drafts": records,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_reconciliation_report(
        vault_root=args.vault_root,
        repository_root=args.repository_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
