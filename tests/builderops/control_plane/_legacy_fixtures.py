"""Shared fixtures for BCP-03 legacy-authority-migration tests.

Every builder writes a *real* legacy source in its true on-disk shape (via the
production SQLite/JSON stores where practical, or the faithful file layout for the
file-first inquiry store), so the read-only adapters are exercised against genuine
legacy data rather than a re-implemented double.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.builderops.control_plane.legacy_migration import (
    ExpectedRoot,
    ObservedSource,
    RootKind,
    WriterStatus,
    freeze_content_hash,
)
from app.builderops.store import SqliteBuilderOpsStore
from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.store import SqliteStore
from app.builderops.epic_run_state import new_epic_run_state, save_epic_run_state

REPO = "RasmusTho/agentic-pkm-mvp"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now() -> datetime:
    return datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def write_builderops_sqlite(path: Path, *, with_ckm: bool = True, live_lease: bool = True) -> dict:
    """Create a real BuilderOps SQLite store with a record, idempotency key, and
    lease, plus co-resident CKM/CEG rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteBuilderOpsStore(path)
    store.initialize()
    worklog = store.create_agent_worklog(
        summary="BCP-03 fixture worklog",
        body="fixture body for migration",
        task_context={"issue": 3789},
        source_refs=[{"ref_type": "github_issue", "ref": "#3789"}],
        created_by={"actor_type": "agent", "id": "codex-fixture"},
        idempotency_key="wl-bcp03-1",
    )
    lease = store.acquire_lease(
        worklog["id"],
        actor={"actor_type": "agent", "id": "codex-fixture"},
        ttl_seconds=5400 if live_lease else 1,
    )
    ckm_ids: dict[str, str] = {}
    if with_ckm:
        ckm_ids = _write_ckm_rows(path)
    return {"worklog_id": worklog["id"], "lease": lease, "ckm": ckm_ids}


def _write_ckm_rows(path: Path) -> dict[str, str]:
    """Apply the real CKM DDL into the same file and insert a capability +
    artifact + evidence edge (authority-bearing CEG rows)."""

    from app.builderops.ckm.schema import CKM_DDL_STATEMENTS

    conn = sqlite3.connect(path)
    try:
        for statement in CKM_DDL_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO ckm_capability (id, name, definition, parent_id, lifecycle, "
            "existence_provenance, boundary_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "cap_bcp03",
                "legacy-authority-migration",
                "CKM capability fixture",
                None,
                "candidate",
                "docs/BUILDEROPS_CONTROL_PLANE/LEGACY_AUTHORITY_MIGRATION.md",
                None,
                _iso(now()),
                _iso(now()),
            ),
        )
        conn.execute(
            "INSERT INTO ckm_artifact (id, source_ref, artifact_kind, source, watermark, "
            "provenance, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "art_bcp03",
                "docs/BUILDEROPS_CONTROL_PLANE/README.md",
                "doc",
                "docs",
                "wm-1",
                json.dumps({"source_ref": "docs/BUILDEROPS_CONTROL_PLANE/README.md"}),
                _iso(now()),
                _iso(now()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"capability_id": "cap_bcp03", "artifact_id": "art_bcp03"}


def add_ckm_schema_growth_row(path: Path) -> str:
    """Simulate a CKM schema addition after spec acceptance: add a column to
    ckm_capability and insert a row using it, proving generic import coverage."""

    conn = sqlite3.connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ckm_capability)")}
        if "confidence_note" not in columns:
            conn.execute("ALTER TABLE ckm_capability ADD COLUMN confidence_note TEXT")
        conn.execute(
            "INSERT INTO ckm_capability (id, name, definition, parent_id, lifecycle, "
            "existence_provenance, boundary_ref, created_at, updated_at, confidence_note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "cap_bcp03_grown",
                "post-freeze-capability",
                "added after spec acceptance",
                "cap_bcp03",
                "candidate",
                "docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md",
                None,
                _iso(now()),
                _iso(now()),
                "high",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return "cap_bcp03_grown"


def write_dispatcher_sqlite(path: Path, *, repo: str = REPO, live_lease: bool = True) -> dict:
    """Create a real dispatcher SQLite store with a task, live lease, and event."""

    path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(path)
    store.initialize()
    created = _iso(now())
    store.upsert_task(
        TaskRecord(
            task_id="github-RasmusTho--agentic-pkm-mvp-issue-3789",
            issue_number=3789,
            title="legacy authority migration",
            status="ready",
            priority="high",
            source_anchor_refs=["docs/BUILDEROPS_CONTROL_PLANE/LEGACY_AUTHORITY_MIGRATION.md"],
            created_at=created,
            updated_at=created,
            repo=repo,
        )
    )
    expiry = now() + timedelta(seconds=5400 if live_lease else -60)
    store.upsert_lease(
        LeaseRecord(
            lease_id="disp-lease-1",
            resource="github-RasmusTho--agentic-pkm-mvp-issue-3789",
            holder="agent:codex-fixture",
            ttl_seconds=5400,
            acquired_at=created,
            expires_at=_iso(expiry),
        )
    )
    store.append_event(
        EventRecord(
            event_id="disp-event-1",
            timestamp=created,
            task_id="github-RasmusTho--agentic-pkm-mvp-issue-3789",
            event_type="claimed",
            actor="agent:codex-fixture",
            lease_id="disp-lease-1",
            payload={"note": "fixture"},
        )
    )
    return {"task_id": "github-RasmusTho--agentic-pkm-mvp-issue-3789", "lease_id": "disp-lease-1"}


def write_dispatcher_events_jsonl(path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_id": "jsonl-1", "task_id": "t1", "event_type": "created", "repo": REPO},
        {"event_id": "jsonl-2", "task_id": "t1", "event_type": "claimed", "repo": REPO},
    ]
    path.write_text("\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n", "utf-8")
    return {"event_ids": ["jsonl-1", "jsonl-2"]}


def write_epic_run_json(root: Path, *, run_id: str = "epic-3788-run-1") -> dict:
    root.mkdir(parents=True, exist_ok=True)
    state = new_epic_run_state(3788, run_id, child_queue=[3789, 3790])
    save_epic_run_state(state, root=root)
    return {"run_id": run_id}


def write_model_inquiry(root: Path, *, inquiry_id: str = "inq-bcp03-1", repo: str = REPO) -> dict:
    """Build a faithful file-first inquiry: manifest + receipts + immutable
    content-addressed question/turn artifacts."""

    inquiry_dir = root / inquiry_id
    (inquiry_dir / "turns").mkdir(parents=True, exist_ok=True)

    question = {"artifact_id": "question", "artifact_hash": "qhash", "text": "why migrate?"}
    _write_json(inquiry_dir / "question.json", question)
    turn = {"artifact_id": "turn-000001", "artifact_hash": "thash", "text": "because fragmentation"}
    _write_json(inquiry_dir / "turns" / "000001.json", turn)

    manifest = {
        "inquiry_id": inquiry_id,
        "repo": repo,
        "status": "completed",
        "artifact_hash": "mhash",
        "question_artifact_id": "question",
        "question_artifact_hash": "qhash",
        "start_receipt_id": "rcpt-start",
    }
    _write_json(inquiry_dir / "manifest.json", manifest)

    receipt = {"id": "rcpt-start", "event_type": "inquiry_started", "inquiry_id": inquiry_id}
    _write_json(inquiry_dir / "receipt-start.json", receipt)
    return {"inquiry_id": inquiry_id, "artifact_ids": ["question", "turn-000001"]}


def _write_json(path: Path, value: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def write_state_producers(root: Path, *, live_lease: bool = True) -> dict:
    """Write all four per-worktree state producers under one root directory."""

    return {
        "builderops": write_builderops_sqlite(
            root / "runtime/builderops/builderops.sqlite3", live_lease=live_lease
        ),
        "dispatcher": write_dispatcher_sqlite(
            root / "runtime/dispatcher/dispatcher.sqlite3", live_lease=live_lease
        ),
        "events": write_dispatcher_events_jsonl(root / "runtime/dispatcher/events.jsonl"),
        "epic": write_epic_run_json(root / "runtime/builderops/epic-runs"),
    }


def write_vault(root: Path) -> dict:
    """Write the file-first model-inquiry store under a vault root."""

    return write_model_inquiry(root / "model-inquiries")


# ---------------------------------------------------------------------------
# Filesystem probe
# ---------------------------------------------------------------------------


def _schema_version(expected: ExpectedRoot) -> int | None:
    path = Path(expected.path)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        for meta in ("builderops_meta", "dispatcher_meta"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (meta,)
            ).fetchone()
            if exists:
                value = conn.execute(
                    f"SELECT value FROM {meta} WHERE key='schema_version'"
                ).fetchone()
                if value:
                    return int(value[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None


def make_probe(
    *,
    freshness_at: str,
    inaccessible: frozenset[str] = frozenset(),
    writer_status: Mapping[str, str] | None = None,
):
    """Return a :data:`SourceProbe` that observes real files on disk."""

    writer_status = dict(writer_status or {})

    def probe(expected: ExpectedRoot) -> ObservedSource:
        path = Path(expected.path)
        if expected.path in inaccessible:
            return ObservedSource(
                expected=expected,
                present=path.exists(),
                accessible=False,
                schema_version=None,
                size_bytes=None,
                modified_at=None,
                content_hash=None,
                writer_status=WriterStatus.UNKNOWN,
                detail="inaccessible",
            )
        if not path.exists():
            return ObservedSource(
                expected=expected,
                present=False,
                accessible=False,
                schema_version=None,
                size_bytes=None,
                modified_at=None,
                content_hash=None,
                writer_status=WriterStatus.UNKNOWN,
                detail="missing",
            )
        size = (
            sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            if path.is_dir()
            else path.stat().st_size
        )
        return ObservedSource(
            expected=expected,
            present=True,
            accessible=True,
            schema_version=_schema_version(expected),
            size_bytes=size,
            modified_at=freshness_at,
            content_hash=freeze_content_hash(expected),
            writer_status=writer_status.get(expected.key, WriterStatus.QUIESCENT),
        )

    return probe


# ---------------------------------------------------------------------------
# Host universe helpers
# ---------------------------------------------------------------------------


def build_full_universe(tmp_path: Path) -> dict:
    """Materialize a two-host universe with real sources under one worktree and a
    quiescent second worktree, returning hosts + expected-root helpers."""

    from app.builderops.control_plane.legacy_migration import (
        EnumeratedRoot,
        HostContext,
        derive_expected_universe,
    )

    macbook_wt = tmp_path / "macbook" / "worktree-a"
    demerzel_wt = tmp_path / "demerzel" / "container-mount"

    # Real sources under the MacBook worktree.
    write_builderops_sqlite(macbook_wt / "runtime/builderops/builderops.sqlite3")
    write_dispatcher_sqlite(macbook_wt / "runtime/dispatcher/dispatcher.sqlite3")
    write_dispatcher_events_jsonl(macbook_wt / "runtime/dispatcher/events.jsonl")
    write_epic_run_json(macbook_wt / "runtime/builderops/epic-runs")

    # Real sources under the Demerzel container mount.
    write_builderops_sqlite(demerzel_wt / "runtime/builderops/builderops.sqlite3")
    write_dispatcher_sqlite(demerzel_wt / "runtime/dispatcher/dispatcher.sqlite3")
    write_dispatcher_events_jsonl(demerzel_wt / "runtime/dispatcher/events.jsonl")
    write_epic_run_json(demerzel_wt / "runtime/builderops/epic-runs")

    # Host-stable vault holding the file-first inquiry store.
    vault_root = tmp_path / "demerzel" / "vault"
    write_model_inquiry(vault_root / "model-inquiries")

    hosts = (
        HostContext(
            host="macbook",
            user="rasmus",
            roots=(EnumeratedRoot(RootKind.GIT_WORKTREE, str(macbook_wt), repo_identity=REPO),),
        ),
        HostContext(
            host="demerzel",
            user="rasmus",
            roots=(
                EnumeratedRoot(RootKind.CONTAINER_MOUNT, str(demerzel_wt), repo_identity=REPO),
                EnumeratedRoot(RootKind.VAULT, str(vault_root), repo_identity=REPO),
            ),
        ),
    )
    expected_roots = derive_expected_universe(hosts)
    return {
        "hosts": hosts,
        "expected_roots": expected_roots,
        "macbook_worktree": macbook_wt,
        "demerzel_mount": demerzel_wt,
        "vault_root": vault_root,
    }
