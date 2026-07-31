"""Docs/capability plane: read-time join for the BuilderOps cockpit registry.

Implements BUILDEROPS_COCKPIT/DOCS_PLANE_CAPABILITY_LANES.md (BOPS-COCKPIT-05,
#4451). The delivery graph's *shape* lives in the docs plane — specification
directories, task-doc frontmatter (``task_id``, ``github_issue``,
``depends_on``), and the machine-registered capability seed — while its
*state* lives in GitHub (audit: docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md,
findings F3/F5/F6). This module reads three named-in-spec sources at render
time and joins them to whatever thread (dispatcher task / GitHub issue) the
cockpit registry is already rendering:

- ``app/builderops/ckm/seed/capabilities.yaml`` — capability keys and their
  ``boundary_ref`` (a Level-2 control-boundary code, e.g. ``RCA``).
- ``docs/architecture/traceability-matrix.md`` — a hand-authored table whose
  ``Control boundaries`` column names a boundary and whose
  ``Implementation issues`` column lists ``#NNNN`` issues it implements. This
  is a *machine edge*: boundary -> capability -> issue, extracted verbatim.
- spec-directory task-doc frontmatter under ``docs/*/`` (any directory
  carrying a ``PARENT_FEATURE_ISSUE.md``, the parent-feature-spec pattern) —
  each task doc's own ``github_issue:``/``parent_capability:`` fields are a
  second machine edge, independent of the matrix.

Honesty rules this module enforces (mirrors ``cockpit_github_plane.py``):

- No cache survives a reload; every call to :func:`read_docs_plane` performs
  its own filesystem read.
- A failed or unreadable docs tree degrades to the refused-claim state
  (``state="unavailable"``) — never an empty-but-fabricated lane set.
- A thread with no machine edge in either source renders **freestanding**,
  in its own lane, with an ``amber`` capability rung — never guessed under a
  parent capability (decision: docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q4).
- Rung classes distinguish *no object exists in the system at all*
  (``absent`` — reserved for docs-plane-unconfigured or genuinely keyless
  rungs such as ``intention``) from *the object exists but names no edge for
  this thread* (``amber``, capability-only) and from *the only evidence is
  prose, not a machine field* (``derived`` — epic rung only, per audit F2/F6).

CKM stays a lens only (ADR-0057): this module never reads any CKM store, and
nothing here may be swapped for a CKM read without visibly regressing
ADR-0057 (the "CKM is a lens, never spine" cockpit test in
``tests/builderops/test_cockpit_docs_plane.py::test_ckm_is_lens_never_spine``
grep-guards this file for exactly that reason).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CapabilityNode",
    "SpecTaskDoc",
    "SpecDirInfo",
    "DocsPlaneSnapshot",
    "DocsPlaneResult",
    "DocsPlaneReadError",
    "read_docs_plane",
    "classify_capability",
    "classify_epic",
    "build_lanes",
    "unlinked_docs_threads",
]

_PARENT_FEATURE_DOC = "PARENT_FEATURE_ISSUE.md"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?", re.DOTALL)
_ISSUE_TOKEN_RE = re.compile(r"#(\d+)")
_LINK_STRIP_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:\-]+\|?$")


class DocsPlaneReadError(RuntimeError):
    """Raised when the docs plane cannot be read.

    Every raise site is caught by :func:`read_docs_plane`, which turns it into
    the refused-claim result the cockpit registry renders. This exception
    never escapes to a caller.
    """


@dataclass(frozen=True)
class CapabilityNode:
    id: str
    name: str
    boundary_ref: str | None


@dataclass(frozen=True)
class SpecTaskDoc:
    """One task doc's frontmatter, read from a spec directory."""

    spec_dir: str
    relative_path: str
    task_id: str | None
    github_issue: int | None
    parent_capability: str | None
    # "Structurally empty" tracking (issue AC2): the key was present in the
    # frontmatter mapping but its value was blank/None, distinct from the key
    # never having existed at all.
    parent_capability_empty: bool


@dataclass(frozen=True)
class SpecDirInfo:
    """One spec directory's epic-level linkage, from its ``PARENT_FEATURE_ISSUE.md``."""

    name: str
    epic_issue: int | None
    epic_rung_class: str  # "proven" | "derived" | "absent"
    child_task_ids: tuple[str, ...]
    prose_child_table_present: bool
    prose_child_count: int | None


@dataclass(frozen=True)
class DocsPlaneSnapshot:
    """Everything one live docs-plane read produced, for one cockpit render.

    Immutable and process-local: nothing here is persisted (mirrors decision
    Q5's no-cache posture, applied here to a filesystem source rather than a
    network one).
    """

    read_at: str
    capabilities: dict[str, CapabilityNode]
    boundary_to_capability: dict[str, str]
    matrix_issue_boundaries: dict[int, tuple[str, ...]]
    task_docs: tuple[SpecTaskDoc, ...]
    spec_dirs: dict[str, SpecDirInfo]

    def task_doc_for_issue(self, issue_number: int) -> SpecTaskDoc | None:
        for doc in self.task_docs:
            if doc.github_issue == issue_number:
                return doc
        return None


@dataclass(frozen=True)
class DocsPlaneResult:
    """The named-source-read shape :mod:`cockpit_registry` folds into ``sources``."""

    snapshot: DocsPlaneSnapshot | None
    state: str  # "fresh" | "unavailable"
    last_successful_read: str | None
    detail: str


def _read_text(path: Path, mtimes: list[float]) -> str:
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocsPlaneReadError(f"cannot read {path}: {exc}") from exc
    mtimes.append(stat.st_mtime)
    return text


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _state_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip().startswith("State:"):
            return line.strip()
    return None


def _issue_from_state_line(text: str) -> int | None:
    line = _state_line(text)
    if not line:
        return None
    match = _ISSUE_TOKEN_RE.search(line)
    return int(match.group(1)) if match else None


def _implementation_task_entries(text: str) -> list[str] | None:
    """Raw, non-empty lines under a ``## Implementation Tasks`` heading.

    ``None`` means the section is absent. An empty list means the section
    exists but named no entries. Every entry under this heading is prose by
    construction (F2: parent<->child edges are never expressed in
    frontmatter) — this is the "may be wrong" child-count source, never a
    ``proven`` one.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## implementation tasks"):
            start = i + 1
            break
    if start is None:
        return None
    entries: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped or _TABLE_SEP_RE.match(stripped):
            continue
        entries.append(stripped)
    return entries


def _looks_like_table_header(entry: str) -> bool:
    """A markdown table's own header row (``| Task | GitHub work item | ... |``).

    Heuristic: a pipe-delimited row naming no issue and no file path is read
    as column labels, not a data row, so it is excluded from the child count.
    """
    if not entry.startswith("|"):
        return False
    return not _ISSUE_TOKEN_RE.search(entry) and "/" not in entry


def _read_capabilities(path: Path, mtimes: list[float]) -> dict[str, CapabilityNode]:
    text = _read_text(path, mtimes)
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DocsPlaneReadError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DocsPlaneReadError(f"{path} did not parse to a mapping")
    nodes: dict[str, CapabilityNode] = {}
    for entry in payload.get("capabilities") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        node_id = str(entry["id"])
        nodes[node_id] = CapabilityNode(
            id=node_id,
            name=str(entry.get("name") or node_id),
            boundary_ref=(str(entry["boundary_ref"]) if entry.get("boundary_ref") else None),
        )
    return nodes


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _read_matrix(path: Path, mtimes: list[float]) -> dict[int, tuple[str, ...]]:
    """Parse ``Control boundaries`` -> ``Implementation issues`` matrix rows.

    Returns ``{issue_number: (boundary_ref, ...)}``. A row's ``Implementation
    issues`` cell can list several issues; each is joined to every boundary
    token the same row names.
    """
    text = _read_text(path, mtimes)
    header_cells: list[str] | None = None
    boundary_idx: int | None = None
    issues_idx: int | None = None
    edges: dict[int, set[str]] = {}
    for line in text.splitlines():
        if _TABLE_SEP_RE.match(line.strip()):
            continue
        cells = _split_table_row(line)
        if cells is None:
            continue
        if header_cells is None:
            if "Control boundaries" in cells:
                header_cells = cells
                boundary_idx = cells.index("Control boundaries")
                issues_idx = next(
                    (i for i, c in enumerate(cells) if "Implementation issues" in c),
                    None,
                )
            continue
        if boundary_idx is None or issues_idx is None:
            continue
        if len(cells) <= max(boundary_idx, issues_idx):
            continue
        boundary_cell = _LINK_STRIP_RE.sub(r"\1", cells[boundary_idx])
        boundary_tokens = {tok.strip() for tok in boundary_cell.split(",") if tok.strip()}
        if not boundary_tokens:
            continue
        for match in _ISSUE_TOKEN_RE.finditer(cells[issues_idx]):
            issue_number = int(match.group(1))
            edges.setdefault(issue_number, set()).update(boundary_tokens)
    return {issue: tuple(sorted(tokens)) for issue, tokens in edges.items()}


def _read_task_doc(spec_dir: str, path: Path, mtimes: list[float]) -> SpecTaskDoc | None:
    text = _read_text(path, mtimes)
    frontmatter = _parse_frontmatter(text)
    if frontmatter is None:
        return None
    task_id = frontmatter.get("task_id")
    raw_issue = frontmatter.get("github_issue")
    github_issue: int | None = None
    if isinstance(raw_issue, int):
        github_issue = raw_issue
    elif isinstance(raw_issue, str) and raw_issue.strip().lstrip("#").isdigit():
        github_issue = int(raw_issue.strip().lstrip("#"))
    capability_present = "parent_capability" in frontmatter
    raw_capability = frontmatter.get("parent_capability")
    capability_value = str(raw_capability).strip() if raw_capability else ""
    parent_capability = capability_value or None
    parent_capability_empty = capability_present and not capability_value
    return SpecTaskDoc(
        spec_dir=spec_dir,
        relative_path=path.name,
        task_id=str(task_id) if task_id else None,
        github_issue=github_issue,
        parent_capability=parent_capability,
        parent_capability_empty=parent_capability_empty,
    )


def _read_spec_dirs(
    docs_root: Path, mtimes: list[float]
) -> tuple[tuple[SpecTaskDoc, ...], dict[str, SpecDirInfo]]:
    if not docs_root.is_dir():
        raise DocsPlaneReadError(f"docs root not found or not a directory: {docs_root}")
    task_docs: list[SpecTaskDoc] = []
    spec_dirs: dict[str, SpecDirInfo] = {}
    for entry in sorted(docs_root.iterdir()):
        if not entry.is_dir():
            continue
        parent_doc = entry / _PARENT_FEATURE_DOC
        if not parent_doc.exists():
            continue  # not a parent-feature-spec directory
        parent_text = _read_text(parent_doc, mtimes)
        parent_frontmatter = _parse_frontmatter(parent_text)
        epic_issue: int | None = None
        epic_rung_class = "absent"
        if parent_frontmatter and isinstance(parent_frontmatter.get("github_issue"), int):
            epic_issue = parent_frontmatter["github_issue"]
            epic_rung_class = "proven"
        if epic_issue is None:
            derived_issue = _issue_from_state_line(parent_text)
            if derived_issue is not None:
                epic_issue = derived_issue
                epic_rung_class = "derived"
        entries = _implementation_task_entries(parent_text)
        prose_present = entries is not None
        prose_count: int | None = None
        if entries:
            data_entries = [e for e in entries if not _looks_like_table_header(e)]
            prose_count = len(data_entries) or None

        dir_task_ids: list[str] = []
        for child in sorted(entry.glob("*.md")):
            if child.name in (_PARENT_FEATURE_DOC, "README.md"):
                continue
            doc = _read_task_doc(entry.name, child, mtimes)
            if doc is None:
                continue
            task_docs.append(doc)
            if doc.task_id:
                dir_task_ids.append(doc.task_id)

        spec_dirs[entry.name] = SpecDirInfo(
            name=entry.name,
            epic_issue=epic_issue,
            epic_rung_class=epic_rung_class,
            child_task_ids=tuple(dir_task_ids),
            prose_child_table_present=prose_present,
            prose_child_count=prose_count,
        )
    return tuple(task_docs), spec_dirs


def _boundary_to_capability(capabilities: dict[str, CapabilityNode]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for node in capabilities.values():
        if node.boundary_ref and node.boundary_ref not in mapping:
            mapping[node.boundary_ref] = node.id
    return mapping


def read_docs_plane(
    *, capabilities_yaml_path: Path, matrix_path: Path, docs_root: Path
) -> DocsPlaneResult:
    """Read the docs/capability plane once. Never raises; refuses on failure.

    Freshness watermark: the latest mtime among every file actually read
    (capabilities.yaml, the matrix, and every spec-dir file examined) — the
    docs plane's own read time, per
    docs/BUILDEROPS_COCKPIT/DOCS_PLANE_CAPABILITY_LANES.md.
    """
    mtimes: list[float] = []
    try:
        capabilities = _read_capabilities(capabilities_yaml_path, mtimes)
        matrix_edges = _read_matrix(matrix_path, mtimes)
        task_docs, spec_dirs = _read_spec_dirs(docs_root, mtimes)
    except Exception as exc:  # noqa: BLE001 - any reader failure degrades to refusal
        # Broad on purpose, matching cockpit_github_plane.fetch_github_live:
        # the caller must never see an exception from this function. A
        # DocsPlaneReadError covers the read helpers' own OSError wrapping,
        # but an unreadable docs_root directory (PermissionError from
        # Path.iterdir()) or a malformed capabilities.yaml (e.g. parsing to
        # a non-list, raising TypeError) must degrade the same way — a
        # single source's failure must never crash the whole registry.
        return DocsPlaneResult(
            snapshot=None,
            state="unavailable",
            last_successful_read=None,
            detail=f"read failed: {exc}",
        )
    if not mtimes:
        watermark = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        watermark = datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    snapshot = DocsPlaneSnapshot(
        read_at=watermark,
        capabilities=capabilities,
        boundary_to_capability=_boundary_to_capability(capabilities),
        matrix_issue_boundaries=matrix_edges,
        task_docs=task_docs,
        spec_dirs=spec_dirs,
    )
    detail = (
        f"{len(task_docs)} task docs across {len(spec_dirs)} spec dirs,"
        f" {len(matrix_edges)} matrix-linked issues, {len(capabilities)} capabilities"
    )
    return DocsPlaneResult(
        snapshot=snapshot, state="fresh", last_successful_read=watermark, detail=detail
    )


def classify_capability(
    issue_number: int | None, snapshot: DocsPlaneSnapshot | None
) -> dict[str, Any]:
    """Classify one thread's capability rung and lane assignment.

    Precedence: spec-dir task-doc frontmatter (``parent_capability:``) wins
    over the traceability matrix, since it names the thread directly rather
    than through a shared control-boundary code; both are ``proven`` machine
    edges (issue AC1/Scope). No edge in either source renders freestanding
    with an ``amber`` rung (never ``absent`` — the capability system exists
    and was read; this thread specifically has no edge into it), per decision
    Q4 ("their own lane", not a shared bucket).
    """
    if issue_number is None or snapshot is None:
        return {
            "rung": {"name": "capability", "class": "absent", "value": None},
            "lane_key": None,
            "lane_name": None,
        }
    doc = snapshot.task_doc_for_issue(issue_number)
    if doc is not None and doc.parent_capability:
        return {
            "rung": {
                "name": "capability",
                "class": "proven",
                "value": doc.parent_capability,
                "chip": (
                    {"kind": "empty_field", "field": "parent_capability"}
                    if doc.parent_capability_empty
                    else None
                ),
            },
            "lane_key": f"capability:{doc.parent_capability}",
            "lane_name": doc.parent_capability,
        }
    boundaries = snapshot.matrix_issue_boundaries.get(issue_number)
    if boundaries:
        capability_id = next(
            (
                snapshot.boundary_to_capability[boundary]
                for boundary in boundaries
                if boundary in snapshot.boundary_to_capability
            ),
            None,
        )
        if capability_id and capability_id in snapshot.capabilities:
            node = snapshot.capabilities[capability_id]
            return {
                "rung": {"name": "capability", "class": "proven", "value": node.name},
                "lane_key": f"capability:{node.id}",
                "lane_name": node.name,
            }
    empty_field_chip = (
        {"kind": "empty_field", "field": "parent_capability"}
        if doc is not None and doc.parent_capability_empty
        else None
    )
    return {
        "rung": {
            "name": "capability",
            "class": "amber",
            "value": None,
            "chip": empty_field_chip,
        },
        "lane_key": f"freestanding:{issue_number}",
        "lane_name": None,
    }


def classify_epic(issue_number: int | None, snapshot: DocsPlaneSnapshot | None) -> dict[str, Any]:
    """Classify one thread's epic rung from its spec directory's parent linkage.

    ``proven`` only if the spec dir's own ``PARENT_FEATURE_ISSUE.md`` carries
    frontmatter naming its governing issue; ``derived`` if that link is only
    nameable via ``State:`` prose (F6); ``absent`` if the thread belongs to no
    known spec dir, or its spec dir names no epic issue at all. A prose-only
    ``## Implementation Tasks`` table adds a "child count may be wrong"
    caveat regardless of how the epic issue itself was found (F2: parent<->
    child edges are prose in both directions).
    """
    if issue_number is None or snapshot is None:
        return {"rung": {"name": "epic", "class": "absent", "value": None, "caveat": None}}
    doc = snapshot.task_doc_for_issue(issue_number)
    if doc is None:
        return {"rung": {"name": "epic", "class": "absent", "value": None, "caveat": None}}
    spec_dir = snapshot.spec_dirs.get(doc.spec_dir)
    if spec_dir is None or spec_dir.epic_issue is None:
        return {"rung": {"name": "epic", "class": "absent", "value": None, "caveat": None}}
    caveat = None
    if spec_dir.prose_child_table_present:
        count_text = (
            str(spec_dir.prose_child_count) if spec_dir.prose_child_count is not None else "an unknown number of"
        )
        caveat = (
            f"child count derived from a prose parent/child table ({count_text} entries seen);"
            " the actual filed-issue count may not match"
        )
    return {
        "rung": {
            "name": "epic",
            "class": spec_dir.epic_rung_class,
            "value": f"#{spec_dir.epic_issue}",
            "caveat": caveat,
        }
    }


def build_lanes(
    items: list[dict[str, Any]], snapshot: DocsPlaneSnapshot | None
) -> list[dict[str, Any]] | None:
    """Group already-classified items into capability lanes.

    Returns ``None`` when the docs plane could not be read — a refused claim,
    never an empty lane list (AC3). Lane count/size is uncapped (decision
    Q4); stacking at narrow widths is a frontend concern (BOPS-COCKPIT-06,
    #4453), out of scope here.
    """
    if snapshot is None:
        return None
    lanes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        lane = item.get("capability_lane")
        if not lane:
            continue
        key = lane["key"]
        if key not in lanes:
            lanes[key] = {
                "capability": lane["name"],
                "key": key,
                "rung": lane["rung"],
                "items": [],
            }
            order.append(key)
        lanes[key]["items"].append(
            {
                "issue_number": item.get("issue_number"),
                "task_id": item.get("id"),
                "title": item.get("title"),
                "band": item.get("band"),
            }
        )
    return [lanes[key] for key in order]


def unlinked_docs_threads(snapshot: DocsPlaneSnapshot | None) -> list[dict[str, Any]]:
    """Task docs with a ``task_id`` but no populated ``github_issue:`` field.

    Mirrors ``cockpit_registry._build_unsynced_threads``'s posture: these are
    surfaced as their own cards (``unlinked`` slice rung) rather than
    silently dropped, and they name known sibling ``task_id``s from the same
    spec directory as the "no issue link" chip's content (AC2). A dead docs
    source must not fabricate these cards — an empty list, matching the
    ``unsynced_threads`` precedent for a dead github-live source.
    """
    if snapshot is None:
        return []
    threads: list[dict[str, Any]] = []
    for doc in snapshot.task_docs:
        if doc.github_issue is not None:
            continue
        spec_dir = snapshot.spec_dirs.get(doc.spec_dir)
        siblings = [
            task_id
            for task_id in (spec_dir.child_task_ids if spec_dir else ())
            if task_id != doc.task_id
        ]
        chip_text = (
            f"no issue link; known children in {doc.spec_dir}: {', '.join(siblings)}"
            if siblings
            else f"no issue link; no other known children in {doc.spec_dir}"
        )
        chips = [{"kind": "no_issue_link", "text": chip_text}]
        if doc.parent_capability_empty:
            chips.append({"kind": "empty_field", "field": "parent_capability"})
        threads.append(
            {
                "id": f"docs-task-{doc.spec_dir}-{doc.task_id or doc.relative_path}",
                "kind": "docs_task",
                "task_id": doc.task_id,
                "spec_dir": doc.spec_dir,
                "rung": {"name": "slice", "class": "unlinked", "value": None},
                "chips": chips,
                "why_now": f"planned in docs/{doc.spec_dir}/ with no issue filed yet",
                "sources": ["docs-frontmatter"],
            }
        )
    return threads
