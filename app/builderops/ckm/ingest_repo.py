"""Deterministic, local-only repository artifact ingestion for CKM-03.

The adapter deliberately reads files and the local git object database only.
It does not inspect remotes, invoke a network client, or write anywhere except
the additive BuilderOps CKM store supplied by its caller.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.builderops.ckm.store import CkmStore


@dataclass(frozen=True)
class RepoArtifact:
    """A normalized, deterministic local repository artifact."""

    natural_key: str
    artifact_kind: str
    payload_summary: str
    provenance: str
    source: str
    source_watermark: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _tree_watermark(items: Iterable[tuple[str, str]]) -> str:
    return _digest("\n".join(f"{key}:{value}" for key, value in sorted(items)).encode())


def _file_artifact(
    root: Path, path: Path, *, kind: str, summary: str, source: str
) -> RepoArtifact:
    relative = _relative(root, path)
    content_hash = _digest(path.read_bytes())
    return RepoArtifact(
        natural_key=relative,
        artifact_kind=kind,
        payload_summary=summary,
        provenance=json.dumps(
            {
                "source_ref": relative,
                "extraction_method": source,
                "content_sha256": content_hash,
                "payload_summary": summary,
            },
            sort_keys=True,
        ),
        source=source,
        source_watermark=content_hash,
    )


def _first_markdown_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(untitled)"


def _state_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("State:"):
            return line.strip()
    return "State: (not declared)"


def _has_task_id_frontmatter(text: str) -> bool:
    """Return whether the leading YAML frontmatter declares a task id."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if line.startswith("task_id:"):
            return True
    return False


def _doc_kind(relative: str, text: str) -> str:
    if relative.startswith("docs/adr/"):
        return "adr"
    if _has_task_id_frontmatter(text):
        return "spec"
    return "document"


def iter_docs(root: Path) -> Iterable[RepoArtifact]:
    for path in sorted((root / "docs").glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        yield _file_artifact(
            root,
            path,
            kind=_doc_kind(_relative(root, path), text),
            summary=f"{_first_markdown_heading(text)} — {_state_line(text)}",
            source="repo_docs",
        )


def _test_summary(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
    return ", ".join(sorted(names)) or "(no test functions)"


def iter_tests(root: Path) -> Iterable[RepoArtifact]:
    for path in sorted((root / "tests").glob("**/test_*.py")):
        yield _file_artifact(root, path, kind="test", summary=_test_summary(path), source="repo_tests")


def _source_summary(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstring = ast.get_docstring(tree)
    return docstring.splitlines()[0] if docstring and docstring.splitlines() else "(no module docstring)"


def iter_source(root: Path) -> Iterable[RepoArtifact]:
    for path in sorted((root / "app").glob("**/*.py")):
        yield _file_artifact(root, path, kind="source_file", summary=_source_summary(path), source="repo_source")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
    ).stdout


def iter_git(
    root: Path,
    previous_head: str | None,
    *,
    limit: int = 500,
    current_head: str | None = None,
) -> Iterable[RepoArtifact]:
    """Yield every commit since the git watermark in bounded local-git pages.

    ``limit`` is a page size, not a completeness cap.  Advancing the git
    watermark to ``HEAD`` after only one page would permanently hide the older
    commits from later incremental runs.
    """
    if limit < 1:
        raise ValueError("git_limit must be at least 1")
    current_head = current_head or _git(root, "rev-parse", "HEAD").strip()
    revision = f"{previous_head}..{current_head}" if previous_head else current_head
    skip = 0
    while True:
        log = _git(
            root,
            "log",
            f"--max-count={limit}",
            f"--skip={skip}",
            "--format=%H|%s",
            "--name-only",
            revision,
        )
        records: list[tuple[str, str, list[str]]] = []
        for line in log.splitlines():
            if len(line) > 41 and line[40] == "|" and all(char in "0123456789abcdef" for char in line[:40]):
                records.append((line[:40], line[41:], []))
            elif line and records:
                records[-1][2].append(line)
        for sha, subject, changed_paths in records:
            yield RepoArtifact(
                natural_key=f"git:{sha}", artifact_kind="commit", payload_summary=subject,
                provenance=json.dumps(
                    {
                        "sha": sha,
                        "changed_paths": changed_paths,
                        "extraction_method": "local_git_log",
                        "payload_summary": subject,
                    },
                    sort_keys=True,
                ),
                source="repo_git", source_watermark=sha,
            )
        if len(records) < limit:
            return
        skip += len(records)


def _ingest_tree(store: CkmStore, source: str, artifacts: Iterable[RepoArtifact]) -> dict[str, int | str]:
    materialized = list(artifacts)
    watermark = _tree_watermark((artifact.natural_key, artifact.source_watermark) for artifact in materialized)
    changed = 0
    for artifact in materialized:
        existing = store.get_artifact_by_source_ref(artifact.natural_key)
        if existing is not None and existing.watermark == artifact.source_watermark:
            continue
        store.upsert_artifact(source_ref=artifact.natural_key, artifact_kind=artifact.artifact_kind, source=artifact.source, watermark=artifact.source_watermark, provenance=artifact.provenance)
        changed += 1
    artifact_source = materialized[0].source if materialized else f"repo_{source}"
    removed = store.delete_artifacts_not_in(artifact_source, {artifact.natural_key for artifact in materialized})
    if store.get_watermark(source) != watermark:
        store.set_watermark(source, watermark)
    return {"artifacts": len(materialized), "changed": changed, "removed": removed, "watermark": watermark}


def ingest_repo(store: CkmStore, root: Path, *, git_limit: int = 500) -> dict[str, dict[str, int | str]]:
    """Ingest local repository artifacts, preserving idempotent source watermarks."""
    root = root.resolve()
    store.ensure_schema()
    result = {
        "docs": _ingest_tree(store, "docs", iter_docs(root)),
        "tests": _ingest_tree(store, "tests", iter_tests(root)),
        "source": _ingest_tree(store, "source", iter_source(root)),
    }
    previous_head = store.get_watermark("git")
    # Bind both traversal and the persisted watermark to one immutable snapshot.
    # A concurrent commit remains honestly pending for the next ingestion instead
    # of being hidden behind a watermark that was never traversed.
    head = _git(root, "rev-parse", "HEAD").strip()
    commits = list(
        iter_git(root, previous_head, limit=git_limit, current_head=head)
    )
    changed = 0
    for artifact in commits:
        if store.get_artifact_by_source_ref(artifact.natural_key) is None:
            store.upsert_artifact(source_ref=artifact.natural_key, artifact_kind=artifact.artifact_kind, source=artifact.source, watermark=artifact.source_watermark, provenance=artifact.provenance)
            changed += 1
    if previous_head != head:
        store.set_watermark("git", head)
    result["git"] = {"artifacts": len(commits), "changed": changed, "watermark": head}
    return result
