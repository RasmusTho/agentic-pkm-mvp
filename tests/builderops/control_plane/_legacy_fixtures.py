"""Shared fixtures for BCP-03 legacy-authority-migration tests.

Every builder writes a *real* legacy source in its true on-disk shape (via the
production SQLite/JSON stores and the real JSONL event writer where practical, or
the faithful file layout for the file-first inquiry store — receipts under
``{inquiry_dir}/receipts/<name>.json``, artifacts with the store's own
canonical-JSON-minus-hash-field ``artifact_hash`` scheme), so the read-only
adapters are exercised against genuine legacy data rather than a re-implemented
double.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.builderops.control_plane.legacy_migration import (
    ExpectedRoot,
    ObservedSource,
    WriterStatus,
    freeze_content_hash,
)
from app.builderops.epic_run_state import new_epic_run_state, save_epic_run_state
from app.builderops.store import SqliteBuilderOpsStore
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.store import SqliteStore

REPO = "RasmusTho/agentic-pkm-mvp"
# NormalizedRecord canonicalizes repo evidence via canonical_repository (F12),
# which lowercases — assertions compare against the canonical form.
REPO_CANON = "rasmustho/agentic-pkm-mvp"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now() -> datetime:
    return datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def iso_now() -> str:
    return _iso(now())


# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def write_builderops_sqlite(
    path: Path,
    *,
    with_ckm: bool = True,
    live_lease: bool = True,
    payload_repo: str | None = None,
) -> dict:
    """Create a real BuilderOps SQLite store with a record, idempotency key, and
    lease, plus co-resident CKM/CEG rows.

    ``payload_repo`` embeds repo evidence inside the record's JSON payload (the
    only place a BuilderOps record can carry it — there is no repo column).
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteBuilderOpsStore(path)
    store.initialize()
    extra = {"repo": payload_repo} if payload_repo else {}
    worklog = store.create_agent_worklog(
        summary="BCP-03 fixture worklog",
        body="fixture body for migration",
        task_context={"issue": 3789},
        source_refs=[{"ref_type": "github_issue", "ref": "#3789"}],
        created_by={"actor_type": "agent", "id": "codex-fixture"},
        idempotency_key="wl-bcp03-1",
        **extra,
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
    artifact (authority-bearing CEG rows)."""

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
                iso_now(),
                iso_now(),
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
                iso_now(),
                iso_now(),
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
                iso_now(),
                iso_now(),
                "high",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return "cap_bcp03_grown"


def write_dispatcher_sqlite(
    path: Path,
    *,
    repo: str = REPO,
    live_lease: bool = True,
    with_verification: bool = True,
) -> dict:
    """Create a real dispatcher SQLite store with a task, live lease, event, and
    (by default) verification runs/attempts/exceptions rows.

    ``verification_runs.repository`` is the per-row repo evidence;
    ``verification_attempts``/``verification_exceptions`` deliberately carry no
    repo column (schema truth) — the adapter must join via ``run_id``.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(path)
    store.initialize()
    created = iso_now()
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
    if with_verification:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "INSERT INTO verification_runs (run_id, idempotency_key, contract_version, "
                "repository, pr_number, head_sha, current_head_sha, stage, request_json, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "vrun-1",
                    "vkey-1",
                    "v3",
                    repo,
                    3929,
                    "abc123",
                    "abc123",
                    "verify",
                    "{}",
                    "queued",
                    created,
                    created,
                ),
            )
            conn.execute(
                "INSERT INTO verification_attempts (attempt_id, run_id, attempt_kind, ordinal, "
                "session_id, capability, reasoning_effort, context_hash, outcome, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "vatt-1",
                    "vrun-1",
                    "review",
                    1,
                    "sess-1",
                    "sonnet",
                    "high",
                    "ctx-hash-1",
                    "pass",
                    created,
                ),
            )
            conn.execute(
                "INSERT INTO verification_exceptions (exception_id, run_id, failure_class, "
                "head_sha, packet_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                ("vexc-1", "vrun-1", "ci_failure", "abc123", "{}", created, created),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-3789",
        "lease_id": "disp-lease-1",
        "run_id": "vrun-1" if with_verification else None,
    }


def write_dispatcher_events_jsonl(path: Path) -> dict:
    """Write dispatcher events through the REAL JsonlEventWriter, so the lines
    are exactly ``EventRecord.to_dict()`` (no top-level repo field exists)."""

    writer = JsonlEventWriter(path)
    created = iso_now()
    for ordinal in (1, 2):
        writer.append(
            EventRecord(
                event_id=f"jsonl-{ordinal}",
                timestamp=created,
                task_id="t1",
                event_type="created" if ordinal == 1 else "claimed",
                actor="agent:codex-fixture",
                lease_id=None,
                payload={"note": f"fixture-{ordinal}"},
            )
        )
    return {"event_ids": ["jsonl-1", "jsonl-2"]}


def write_epic_run_json(root: Path, *, run_id: str = "epic-3788-run-1") -> dict:
    root.mkdir(parents=True, exist_ok=True)
    state = new_epic_run_state(3788, run_id, child_queue=[3789, 3790])
    save_epic_run_state(state, root=root)
    return {"run_id": run_id}


def model_inquiry_artifact_hash(payload: Mapping) -> str:
    """Mirror model_inquiry._artifact_hash: sha256 over the canonical JSON of the
    payload minus its own artifact_hash field."""

    canonical = {key: value for key, value in payload.items() if key != "artifact_hash"}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_model_inquiry(root: Path, *, inquiry_id: str = "inq-bcp03-1", repo: str = REPO) -> dict:
    """Build a faithful file-first inquiry: manifest + receipts under
    ``receipts/<name>.json`` (the store's real layout — receipt files never share
    a filename prefix) + immutable content-addressed question/turn artifacts
    whose ``artifact_hash`` uses the store's real canonical-JSON scheme."""

    inquiry_dir = root / inquiry_id
    (inquiry_dir / "turns").mkdir(parents=True, exist_ok=True)
    (inquiry_dir / "receipts").mkdir(parents=True, exist_ok=True)

    question = {"artifact_id": "question", "text": "why migrate?"}
    question["artifact_hash"] = model_inquiry_artifact_hash(question)
    _write_json(inquiry_dir / "question.json", question)
    turn = {"artifact_id": "turn-000001", "text": "because fragmentation"}
    turn["artifact_hash"] = model_inquiry_artifact_hash(turn)
    _write_json(inquiry_dir / "turns" / "000001.json", turn)

    manifest = {
        "inquiry_id": inquiry_id,
        "repo": repo,
        "status": "completed",
        "question_artifact_id": "question",
        "question_artifact_hash": question["artifact_hash"],
        "start_receipt_id": "rcpt-start",
    }
    manifest["artifact_hash"] = model_inquiry_artifact_hash(manifest)
    _write_json(inquiry_dir / "manifest.json", manifest)

    started = {
        "id": "rcpt-start",
        "event_type": "inquiry_started",
        "inquiry_id": inquiry_id,
        "occurred_at": iso_now(),
    }
    _write_json(inquiry_dir / "receipts" / "inquiry-started.json", started)
    terminal = {
        "id": "rcpt-run-terminal",
        "event_type": "inquiry_run_terminal",
        "inquiry_id": inquiry_id,
        "occurred_at": iso_now(),
    }
    _write_json(inquiry_dir / "receipts" / "inquiry-run-terminal.json", terminal)
    return {
        "inquiry_id": inquiry_id,
        "artifact_ids": ["question", "turn-000001"],
        "receipt_files": ["inquiry-started.json", "inquiry-run-terminal.json"],
        "receipt_ids": ["rcpt-start", "rcpt-run-terminal"],
        "declared_hashes": {
            "question": question["artifact_hash"],
            "turn-000001": turn["artifact_hash"],
        },
    }


def _write_json(path: Path, value: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def write_state_producers(
    root: Path,
    *,
    live_lease: bool = True,
    dispatcher: bool = True,
    payload_repo: str | None = None,
) -> dict:
    """Write the per-worktree state producers under one root directory.

    ``dispatcher=False`` models a LINKED worktree: the dispatcher's real resolver
    writes only at the clone-set primary, so linked worktrees carry builderops +
    epic-run state but no dispatcher store.
    """

    written = {
        "builderops": write_builderops_sqlite(
            root / "runtime/builderops/builderops.sqlite3",
            live_lease=live_lease,
            payload_repo=payload_repo,
        ),
        "epic": write_epic_run_json(root / "runtime/builderops/epic-runs"),
    }
    if dispatcher:
        written["dispatcher"] = write_dispatcher_sqlite(
            root / "runtime/dispatcher/dispatcher.sqlite3", live_lease=live_lease
        )
        written["events"] = write_dispatcher_events_jsonl(root / "runtime/dispatcher/events.jsonl")
    return written


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
    """Materialize a two-host universe with real sources.

    MacBook: one primary worktree (env snapshot known-empty). Demerzel: a
    container mount plus the vault, with NO env snapshot (env=None) — exercising
    the remote-env limitation surfaced in the preflight receipt.
    """

    from app.builderops.control_plane.legacy_migration import (
        EnumeratedRoot,
        HostContext,
        RootKind,
        derive_expected_universe,
    )

    macbook_wt = tmp_path / "macbook" / "worktree-a"
    demerzel_mount = tmp_path / "demerzel" / "container-mount"

    write_state_producers(macbook_wt)
    write_state_producers(demerzel_mount)

    # Host-stable vault holding the file-first inquiry store.
    vault_root = tmp_path / "demerzel" / "vault"
    write_vault(vault_root)

    hosts = (
        HostContext(
            host="macbook",
            user="rasmus",
            roots=(EnumeratedRoot(RootKind.GIT_WORKTREE, str(macbook_wt), repo_identity=REPO),),
            env={},
        ),
        HostContext(
            host="demerzel",
            user="rasmus",
            roots=(
                EnumeratedRoot(RootKind.CONTAINER_MOUNT, str(demerzel_mount), repo_identity=REPO),
                EnumeratedRoot(RootKind.VAULT, str(vault_root), repo_identity=REPO),
            ),
            env=None,
        ),
    )
    expected_roots = derive_expected_universe(hosts)
    return {
        "hosts": hosts,
        "expected_roots": expected_roots,
        "macbook_worktree": macbook_wt,
        "demerzel_mount": demerzel_mount,
        "vault_root": vault_root,
    }
