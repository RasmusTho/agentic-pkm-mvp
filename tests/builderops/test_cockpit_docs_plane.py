"""Tests for the docs/capability plane join (BOPS-COCKPIT-05, #4451).

Every test uses FIXTURE spec directories built under ``tmp_path`` — none of
these assertions depend on the shape of the live repo's ``docs/`` tree beyond
the schema/frontmatter conventions the issue itself names (``task_id``,
``github_issue``, ``parent_capability``, a ``PARENT_FEATURE_ISSUE.md`` marker,
a ``State:`` prose line, and a ``## Implementation Tasks`` section).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.builderops.cockpit_registry import build_registry
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore

REPO = "RasmusTho/agentic-pkm-mvp"

_CAPABILITIES_YAML = """\
capabilities:
  - id: cap-alpha
    stable_key: ckm-capability-9001
    name: Alpha Fixture Capability
    definition: test fixture capability
    parent: null
    boundary_ref: ALPHA
    seed_source: "test fixture"
"""

_MATRIX_MD = """\
State: test fixture traceability matrix.

# Fixture Traceability Matrix

| # | Principle / finding | Control boundaries | Implementation issues |
| --- | --- | --- | --- |
| 1 | Fixture principle. | ALPHA | #501, #502 |
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_store(tmp_path: Path) -> tuple[Path, SqliteStore]:
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    return db_path, store


def _task(*, status: str, issue_number: int, title: str = "a task", repo: str = REPO) -> TaskRecord:
    now = _now()
    return TaskRecord(
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        issue_number=issue_number,
        title=title,
        status=status,
        priority="med",
        repo=repo,
        source_anchor_refs=[],
        linked_pr=None,
        sync_state=None,
        created_at=now,
        updated_at=now,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_docs_fixture(docs_root: Path) -> None:
    """A minimal, valid docs/capability plane fixture with no edges at all.

    Used by tests that only need the docs plane to read successfully
    (``state="fresh"``) while producing zero matches for whatever thread the
    test is probing — i.e. a genuinely empty, honestly-read plane.
    """
    _write(docs_root / "capabilities.yaml", _CAPABILITIES_YAML)
    _write(docs_root / "matrix.md", _MATRIX_MD)
    # One spec dir that names no issues relevant to the probed thread.
    _write(
        docs_root / "UNRELATED_SPEC" / "PARENT_FEATURE_ISSUE.md",
        "State: Filed as GitHub Issue #999.\n\n# Unrelated Spec\n",
    )
    _write(
        docs_root / "UNRELATED_SPEC" / "SOME_TASK.md",
        (
            "---\n"
            "name: Some Task\n"
            "task_id: UNRELATED-01\n"
            "github_issue: 999\n"
            "parent_capability: Unrelated Capability\n"
            "---\n\n# Some Task\n"
        ),
    )


def _item_by_issue(payload: dict, issue_number: int) -> dict:
    for band in payload["bands"]:
        for item in band["items"]:
            if item["issue_number"] == issue_number:
                return item
    raise AssertionError(f"no item for issue {issue_number} in payload")


def _source(payload: dict, name: str) -> dict:
    return next(s for s in payload["sources"] if s["name"] == name)


# ---------------------------------------------------------------------------
# test_no_edge_means_freestanding_never_guessed
# ---------------------------------------------------------------------------


def test_no_edge_means_freestanding_never_guessed(tmp_path: Path) -> None:
    """A thread with no matrix row and no spec-dir frontmatter match must
    render freestanding, in its own lane, with an ``amber`` capability rung —
    never absorbed into an unrelated lane (decision Q4)."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=901, title="orphan thread"))

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root)

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        docs_root=docs_root,
        capabilities_yaml_path=docs_root / "capabilities.yaml",
        matrix_path=docs_root / "matrix.md",
    )

    assert _source(payload, "docs-frontmatter")["state"] == "fresh"

    item = _item_by_issue(payload, 901)
    rungs = {r["name"]: r for r in item["rungs"]}
    assert rungs["capability"]["class"] == "amber"
    assert rungs["capability"]["value"] is None

    assert item["capability_lane"]["key"] == "freestanding:901"
    assert item["capability_lane"]["name"] is None

    assert payload["capability_lanes"]["countable"] is True
    lanes = payload["capability_lanes"]["lanes"]
    freestanding_lanes = [lane for lane in lanes if lane["key"] == "freestanding:901"]
    assert len(freestanding_lanes) == 1
    lane = freestanding_lanes[0]
    assert lane["capability"] is None
    assert lane["rung"] == "amber"
    assert [item["issue_number"] for item in lane["items"]] == [901]

    # The orphan thread must never appear inside an unrelated named lane.
    for lane in lanes:
        if lane["key"] != "freestanding:901":
            assert 901 not in {item["issue_number"] for item in lane["items"]}


# ---------------------------------------------------------------------------
# test_honest_partials_for_weak_edges
# ---------------------------------------------------------------------------


def test_honest_partials_for_weak_edges(tmp_path: Path) -> None:
    """Covers the three honest-partial shapes the issue names:

    - a prose-only parent/child table renders a ``derived`` epic rung with a
      may-be-wrong-count caveat;
    - an unpopulated ``github_issue:`` field renders as its own ``unlinked``
      docs-only thread, naming known sibling children;
    - a structurally empty ``parent_capability:`` field renders a distinct
      "empty field" chip rather than being silently treated as content.
    """
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=701, title="linked child"))

    docs_root = tmp_path / "docs"
    _write(docs_root / "capabilities.yaml", _CAPABILITIES_YAML)
    _write(docs_root / "matrix.md", _MATRIX_MD)

    spec_dir = docs_root / "AGENT_MEMORY_FIXTURE"
    # Prose-only parent linkage: no frontmatter at all, only a State: line and
    # a "## Implementation Tasks" list — exactly the weak edge F2/F6 name.
    _write(
        spec_dir / "PARENT_FEATURE_ISSUE.md",
        (
            "State: Filed as GitHub Issue #700 and open; children in progress.\n\n"
            "# Agent Memory Fixture\n\n"
            "## Implementation Tasks\n\n"
            "1. `docs/AGENT_MEMORY_FIXTURE/TASK_ONE.md`\n"
            "2. `docs/AGENT_MEMORY_FIXTURE/TASK_TWO.md`\n"
        ),
    )
    _write(
        spec_dir / "TASK_ONE.md",
        (
            "---\n"
            "name: Task One\n"
            "task_id: AMF-01\n"
            "github_issue: 701\n"
            "parent_capability: Agent Memory Fixture\n"
            "---\n\n# Task One\n"
        ),
    )
    # TASK_TWO has a task_id but no github_issue field at all, and a
    # structurally empty parent_capability field.
    _write(
        spec_dir / "TASK_TWO.md",
        (
            "---\n"
            "name: Task Two\n"
            "task_id: AMF-02\n"
            'parent_capability: ""\n'
            "---\n\n# Task Two\n"
        ),
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        docs_root=docs_root,
        capabilities_yaml_path=docs_root / "capabilities.yaml",
        matrix_path=docs_root / "matrix.md",
    )

    assert _source(payload, "docs-frontmatter")["state"] == "fresh"

    # -- prose-only parent table: derived epic rung + may-be-wrong caveat --
    item = _item_by_issue(payload, 701)
    rungs = {r["name"]: r for r in item["rungs"]}
    assert rungs["epic"]["class"] == "derived"
    assert rungs["epic"]["value"] == "#700"
    assert rungs["epic"]["caveat"] is not None
    assert "may not match" in rungs["epic"]["caveat"] or "may be wrong" in rungs["epic"]["caveat"]

    # -- unpopulated github_issue: unlinked rung + named-children chip --
    docs_only = payload["docs_only_threads"]
    task_two = next(t for t in docs_only if t["task_id"] == "AMF-02")
    assert task_two["rung"]["class"] == "unlinked"
    no_issue_chip = next(c for c in task_two["chips"] if c["kind"] == "no_issue_link")
    assert "AMF-01" in no_issue_chip["text"]

    # -- structurally empty parent_capability: dashed "empty field" chip --
    empty_field_chip = next(c for c in task_two["chips"] if c["kind"] == "empty_field")
    assert empty_field_chip["field"] == "parent_capability"

    # TASK_ONE, being fully linked, must not appear as a docs-only thread.
    assert all(t["task_id"] != "AMF-01" for t in docs_only)


# ---------------------------------------------------------------------------
# test_docs_source_freshness_and_refusal
# ---------------------------------------------------------------------------


def test_docs_source_freshness_and_refusal(tmp_path: Path) -> None:
    """The docs plane is a named source with its own watermark; an unreadable
    docs tree refuses lane claims instead of rendering an empty lane set."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=1))

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root)

    fresh_payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        docs_root=docs_root,
        capabilities_yaml_path=docs_root / "capabilities.yaml",
        matrix_path=docs_root / "matrix.md",
    )
    fresh_source = _source(fresh_payload, "docs-frontmatter")
    assert fresh_source["state"] == "fresh"
    assert fresh_source["last_successful_read"] is not None
    assert fresh_payload["capability_lanes"]["countable"] is True
    # Issue #1 has no edge anywhere in this fixture, so it renders as its own
    # freestanding lane (test_no_edge_means_freestanding_never_guessed covers
    # this in depth) — a *populated* lane list, not an empty one, is the
    # honest "fresh read, zero matches for this thread" shape.
    lanes = fresh_payload["capability_lanes"]["lanes"]
    assert lanes == [
        {"capability": None, "key": "freestanding:1", "rung": "amber", "items": lanes[0]["items"]}
    ]

    # Case 1: docs plane not configured at all (the direct-call default).
    unconfigured_payload = build_registry(
        db_path=db_path, deploy_receipt_dir=tmp_path / "deploys"
    )
    unconfigured_source = _source(unconfigured_payload, "docs-frontmatter")
    assert unconfigured_source["state"] == "unavailable"
    assert unconfigured_source["last_successful_read"] is None
    assert unconfigured_payload["capability_lanes"] == {"countable": False, "lanes": None}
    assert unconfigured_payload["docs_only_threads"] == []

    # Case 2: configured but pointing at a docs tree that does not exist —
    # refusal, never a silently empty (and therefore falsely "complete")
    # lane set.
    missing_docs_root = tmp_path / "does-not-exist"
    broken_payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        docs_root=missing_docs_root,
        capabilities_yaml_path=docs_root / "capabilities.yaml",
        matrix_path=docs_root / "matrix.md",
    )
    broken_source = _source(broken_payload, "docs-frontmatter")
    assert broken_source["state"] == "unavailable"
    assert broken_payload["capability_lanes"] == {"countable": False, "lanes": None}
    assert broken_payload["docs_only_threads"] == []
    # The dispatcher-owned bands are unaffected by the unrelated docs-plane
    # failure — same posture as the github-live source's independent refusal.
    assert broken_payload["claim"]["kind"] == "counted"

    # Case 3: the capabilities.yaml file itself is missing.
    missing_capabilities_payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        docs_root=docs_root,
        capabilities_yaml_path=docs_root / "does-not-exist.yaml",
        matrix_path=docs_root / "matrix.md",
    )
    assert _source(missing_capabilities_payload, "docs-frontmatter")["state"] == "unavailable"
    assert missing_capabilities_payload["capability_lanes"] == {
        "countable": False,
        "lanes": None,
    }


# ---------------------------------------------------------------------------
# test_ckm_is_lens_never_spine
# ---------------------------------------------------------------------------


def test_ckm_is_lens_never_spine(tmp_path: Path) -> None:
    """No band, count, lane membership, or ordering may derive from CKM state
    (ADR-0057: CKM is a lens, never spine). This module must not read any CKM
    store at all for that decision, per the issue's own guidance ("if you're
    unsure whether to touch CKM — don't")."""
    import ast
    import inspect

    import app.builderops.cockpit_docs_plane as docs_plane_module

    source_text = inspect.getsource(docs_plane_module)
    tree = ast.parse(source_text)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    # The module may *mention* "app/builderops/ckm/seed/capabilities.yaml" as
    # a plain path string in its own docstring (that file is a legitimate,
    # named docs-plane source) — the guard is that it never *imports* the CKM
    # store/package, and never references the store's class, which is the
    # only way a CKM read could reach lanes/bands/counts.
    assert not any("ckm" in mod.lower() for mod in imported_modules), (
        "cockpit_docs_plane.py must never import any app.builderops.ckm"
        " module: lanes/bands/counts derive only from capabilities.yaml, the"
        " traceability matrix, and spec-dir frontmatter (ADR-0057: CKM is a"
        " lens, never spine)."
    )
    assert "CkmStore" not in source_text

    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=1))
    store.upsert_task(_task(status="in_progress", issue_number=2))

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root)

    def _run() -> dict:
        return build_registry(
            db_path=db_path,
            deploy_receipt_dir=tmp_path / "deploys",
            docs_root=docs_root,
            capabilities_yaml_path=docs_root / "capabilities.yaml",
            matrix_path=docs_root / "matrix.md",
        )

    without_ckm = _run()

    # A CKM-shaped store artifact happens to exist alongside the fixture, at
    # a plausible conventional path — it must have zero effect on lanes,
    # bands, or counts.
    ckm_dir = tmp_path / "runtime" / "builderops"
    ckm_dir.mkdir(parents=True, exist_ok=True)
    (ckm_dir / "ckm.sqlite3").write_bytes(b"not a real sqlite file, just a decoy")

    with_ckm = _run()

    def _strip_timestamps(payload: dict) -> dict:
        payload = dict(payload)
        payload.pop("generated_at", None)
        payload["claim"] = {k: v for k, v in payload["claim"].items() if k != "as_of"}
        payload["sources"] = [
            {k: v for k, v in s.items() if k != "last_successful_read"}
            for s in payload["sources"]
        ]
        return payload

    assert _strip_timestamps(without_ckm)["bands"] == _strip_timestamps(with_ckm)["bands"]
    assert (
        _strip_timestamps(without_ckm)["capability_lanes"]
        == _strip_timestamps(with_ckm)["capability_lanes"]
    )
    assert (
        _strip_timestamps(without_ckm)["docs_only_threads"]
        == _strip_timestamps(with_ckm)["docs_only_threads"]
    )
