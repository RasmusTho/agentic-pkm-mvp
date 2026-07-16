"""Legacy authority inventory and deterministic read-only migration (BCP-03).

This module implements the migration *mechanism* for the independent BuilderOps
control plane (``docs/BUILDEROPS_CONTROL_PLANE/LEGACY_AUTHORITY_MIGRATION.md``).
It does not perform the production cutover (BCP-06 owns the freeze window); it
inventories every repo-owned legacy authority producer, freezes and hash-verifies
each source, imports authority identities/state/receipts into a target authority
sink under a new epoch, and reconciles the expected universe against the import
outcome so cutover can be gated.

Design constraints held here (all from the task spec):

* Producer/default-path inventory is the expected-source authority. Caller roots
  may add scope but never subtract expected coverage. An omitted or inaccessible
  expected root blocks acknowledgement.
* Source adapters are read-only and hash-verify; a source changed after freeze
  imports nothing further.
* Conflicting equal authority-bearing identities never use last-write-wins.
  Evidence-only ambiguity may remain plain quarantine; authority-bearing
  ambiguity/conflict blocks cutover until evidence-resolved or represented by a
  duplicate-preventing, non-authoritative tombstone.
* No legacy lease crosses the authority epoch — a legacy lease imports only as
  expired/tombstone evidence.
* ``RepoRef``/scope/stack are backfilled only from evidence-bound mappings, never
  defaulted from CWD or the import target.

The target authority is PostgreSQL in production; this module depends only on the
domain-neutral :class:`AuthoritySink` protocol so the deterministic pipeline is
verifiable against an in-memory adapter (BCP-01 established the explicit
non-production adapter seam). ``sink-payload`` writes deliberately avoid the vault
``ObjectStore`` sink primitives — this authority is the control-plane authority,
not the vault content plane.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class RootKind:
    PRODUCER_DEFAULT = "producer_default"
    GIT_WORKTREE = "git_worktree"
    CONTAINER_MOUNT = "container_mount"
    AUTOMATION = "automation"
    HOST_STABLE = "host_stable"
    VAULT = "vault"


class Disposition:
    IMPORTED = "imported"
    DEDUPLICATED = "deduplicated"
    EVIDENCE_QUARANTINED = "evidence_quarantined"
    AUTHORITY_TOMBSTONED = "authority_tombstoned"
    EXPIRED_LEASE = "expired_lease"
    MISSING = "missing"
    INACCESSIBLE = "inaccessible"
    EXCLUDED = "excluded"
    ARCHIVED = "archived"
    BLOCKED = "blocked"


class WriterStatus:
    LIVE = "live"
    QUIESCENT = "quiescent"
    UNKNOWN = "unknown"


# Source classes owned by repo producers.
SOURCE_BUILDEROPS_SQLITE = "builderops_sqlite"
SOURCE_DISPATCHER_SQLITE = "dispatcher_sqlite"
SOURCE_DISPATCHER_EVENTS_JSONL = "dispatcher_events_jsonl"
SOURCE_EPIC_RUN_JSON = "epic_run_json"
SOURCE_MODEL_INQUIRY_FILES = "model_inquiry_files"

# Root scopes describe how a producer's default path multiplies across a host.
_SCOPE_PER_WORKTREE = "per_worktree"
_SCOPE_VAULT_FILE_FIRST = "vault_file_first"

# Which enumerated root kinds a producer scope applies to. A per-worktree
# producer state directory can appear under a linked worktree, a container mount,
# an automation-managed state root, or a (now-superseded, #3686) host-stable
# SQLite candidate; the vault-file-first inquiry store lives under a vault root.
_SCOPE_APPLICABILITY: dict[str, frozenset[str]] = {
    _SCOPE_PER_WORKTREE: frozenset(
        {
            RootKind.GIT_WORKTREE,
            RootKind.CONTAINER_MOUNT,
            RootKind.AUTOMATION,
            RootKind.HOST_STABLE,
        }
    ),
    _SCOPE_VAULT_FILE_FIRST: frozenset({RootKind.VAULT}),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegacyMigrationError(RuntimeError):
    """Base error for fail-closed legacy-migration operations."""


class InventoryCoverageError(LegacyMigrationError):
    """Raised when caller input would subtract producer-derived coverage."""


class AcknowledgementRejected(LegacyMigrationError):
    """Raised when an inventory acknowledgement is stale, foreign, or incomplete."""


class SourceChangedError(LegacyMigrationError):
    """Raised when a frozen source's content hash changes before import."""


class AuthorityReplayError(LegacyMigrationError):
    """Raised when a tombstoned legacy key is replayed into the new epoch."""


# ---------------------------------------------------------------------------
# Producer manifest (the expected-source authority)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProducerSpec:
    """One repo-owned legacy authority producer and its default-path rule."""

    name: str
    source_class: str
    relative_default_path: str
    authority_bearing: bool
    root_scope: str
    env_override_keys: tuple[str, ...]
    description: str

    def applies_to(self, root_kind: str) -> bool:
        return root_kind in _SCOPE_APPLICABILITY[self.root_scope]


PRODUCER_MANIFEST: tuple[ProducerSpec, ...] = (
    ProducerSpec(
        name="builderops_store",
        source_class=SOURCE_BUILDEROPS_SQLITE,
        relative_default_path="runtime/builderops/builderops.sqlite3",
        authority_bearing=True,
        root_scope=_SCOPE_PER_WORKTREE,
        env_override_keys=("BUILDEROPS_STATE_DIR", "BUILDEROPS_DB_PATH"),
        description=(
            "BuilderOps records, leases, and idempotency keys, plus the "
            "co-resident CKM/Capability Evidence Graph tables (ADR-0062 A3) "
            "written through the same SQLite file."
        ),
    ),
    ProducerSpec(
        name="dispatcher_store",
        source_class=SOURCE_DISPATCHER_SQLITE,
        relative_default_path="runtime/dispatcher/dispatcher.sqlite3",
        authority_bearing=True,
        root_scope=_SCOPE_PER_WORKTREE,
        env_override_keys=("DISPATCHER_STATE_DIR", "DISPATCHER_DB_PATH"),
        description="Dispatcher tasks, leases, and verification runs/attempts/exceptions.",
    ),
    ProducerSpec(
        name="dispatcher_events",
        source_class=SOURCE_DISPATCHER_EVENTS_JSONL,
        relative_default_path="runtime/dispatcher/events.jsonl",
        authority_bearing=False,
        root_scope=_SCOPE_PER_WORKTREE,
        env_override_keys=("DISPATCHER_STATE_DIR", "DISPATCHER_EVENTS_PATH"),
        description="Append-only dispatcher event audit log (evidence).",
    ),
    ProducerSpec(
        name="epic_run_state",
        source_class=SOURCE_EPIC_RUN_JSON,
        relative_default_path="runtime/builderops/epic-runs",
        authority_bearing=True,
        root_scope=_SCOPE_PER_WORKTREE,
        env_override_keys=("BUILDEROPS_STATE_DIR",),
        description="deliver-issue-set epic run state JSON files.",
    ),
    ProducerSpec(
        name="model_inquiry",
        source_class=SOURCE_MODEL_INQUIRY_FILES,
        relative_default_path="model-inquiries",
        authority_bearing=True,
        root_scope=_SCOPE_VAULT_FILE_FIRST,
        env_override_keys=("BUILDEROPS_VAULT_ROOT",),
        description=(
            "File-first model inquiry manifests, receipts, and immutable "
            "content-addressed question/turn artifacts."
        ),
    ),
)

_PRODUCERS_BY_NAME: dict[str, ProducerSpec] = {p.name: p for p in PRODUCER_MANIFEST}


def producer(name: str) -> ProducerSpec:
    return _PRODUCERS_BY_NAME[name]


# ---------------------------------------------------------------------------
# Host enumeration and expected roots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnumeratedRoot:
    """A root discovered on a host by worktree/container/automation enumeration."""

    kind: str
    path: str
    # Evidence-bound repository identity for this root, when it is registered to
    # one (a linked worktree of a known repo). ``None`` means the repo provenance
    # of any authority found here is ambiguous and must be resolved, never
    # defaulted.
    repo_identity: str | None = None


@dataclass(frozen=True)
class HostContext:
    """One cutover host and the roots enumerated on it."""

    host: str
    user: str
    roots: tuple[EnumeratedRoot, ...] = ()


@dataclass(frozen=True)
class ExpectedRoot:
    """One expected legacy source location in the migration universe."""

    producer: str
    source_class: str
    host: str
    user: str
    root_kind: str
    path: str
    authority_bearing: bool
    repo_identity: str | None = None

    @property
    def key(self) -> str:
        return f"{self.host}:{self.producer}:{self.path}"


def derive_expected_universe(
    hosts: Sequence[HostContext],
    *,
    caller_roots: Sequence[ExpectedRoot] = (),
) -> tuple[ExpectedRoot, ...]:
    """Cross-product repo producers with each host's enumerated roots.

    Caller roots may only *add* to the producer-derived universe. Any caller root
    whose key collides with a producer-derived root but changes its identity is a
    coverage-subtraction attempt and fails closed.
    """

    derived: dict[str, ExpectedRoot] = {}
    for host in hosts:
        for root in host.roots:
            base = Path(root.path)
            for spec in PRODUCER_MANIFEST:
                if not spec.applies_to(root.kind):
                    continue
                path = str(base / spec.relative_default_path)
                expected = ExpectedRoot(
                    producer=spec.name,
                    source_class=spec.source_class,
                    host=host.host,
                    user=host.user,
                    root_kind=root.kind,
                    path=path,
                    authority_bearing=spec.authority_bearing,
                    repo_identity=root.repo_identity,
                )
                derived[expected.key] = expected

    universe = dict(derived)
    for extra in caller_roots:
        existing = derived.get(extra.key)
        if existing is not None and existing != extra:
            raise InventoryCoverageError(
                f"caller root {extra.key!r} conflicts with producer-derived coverage"
            )
        universe.setdefault(extra.key, extra)

    return tuple(sorted(universe.values(), key=lambda r: r.key))


# ---------------------------------------------------------------------------
# Coverage manifest and acknowledgement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservedSource:
    """A frozen observation of one expected root."""

    expected: ExpectedRoot
    present: bool
    accessible: bool
    schema_version: int | None
    size_bytes: int | None
    modified_at: str | None
    content_hash: str | None
    writer_status: str
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.present and self.accessible

    def as_manifest_entry(self) -> dict[str, Any]:
        return {
            "key": self.expected.key,
            "producer": self.expected.producer,
            "source_class": self.expected.source_class,
            "host": self.expected.host,
            "user": self.expected.user,
            "root_kind": self.expected.root_kind,
            "path": self.expected.path,
            "authority_bearing": self.expected.authority_bearing,
            "repo_identity": self.expected.repo_identity,
            "present": self.present,
            "accessible": self.accessible,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "content_hash": self.content_hash,
            "writer_status": self.writer_status,
        }


SourceProbe = Callable[[ExpectedRoot], ObservedSource]


@dataclass(frozen=True)
class CoverageManifest:
    """The frozen coverage inventory across the expected universe."""

    host: str
    user: str
    freshness_at: str
    sources: tuple[ObservedSource, ...]
    exclusions: Mapping[str, str]
    manifest_hash: str

    @property
    def blocking_roots(self) -> tuple[str, ...]:
        blocking: list[str] = []
        for source in self.sources:
            if source.expected.key in self.exclusions:
                continue
            if not source.usable:
                blocking.append(source.expected.key)
        return tuple(sorted(blocking))

    @property
    def is_blocking(self) -> bool:
        return bool(self.blocking_roots)

    def usable_sources(self) -> tuple[ObservedSource, ...]:
        return tuple(
            source
            for source in self.sources
            if source.usable and source.expected.key not in self.exclusions
        )


def build_coverage_manifest(
    expected_roots: Sequence[ExpectedRoot],
    *,
    probe: SourceProbe,
    host: str,
    user: str,
    freshness_at: str,
    exclusions: Mapping[str, str] | None = None,
) -> CoverageManifest:
    """Freeze every expected root into an observed source and hash the coverage."""

    exclusions = dict(exclusions or {})
    observed = tuple(
        sorted(
            (probe(root) for root in expected_roots),
            key=lambda source: source.expected.key,
        )
    )
    fingerprint = {
        "host": host,
        "user": user,
        "sources": [source.as_manifest_entry() for source in observed],
        "exclusions": dict(sorted(exclusions.items())),
    }
    return CoverageManifest(
        host=host,
        user=user,
        freshness_at=freshness_at,
        sources=observed,
        exclusions=exclusions,
        manifest_hash=_hash(fingerprint),
    )


@dataclass(frozen=True)
class InventoryAcknowledgement:
    """Host/user/freshness/manifest-hash-bound acknowledgement of the inventory."""

    host: str
    user: str
    manifest_hash: str
    acknowledged_at: str
    freshness_horizon_seconds: int


def accept_acknowledgement(
    manifest: CoverageManifest,
    ack: InventoryAcknowledgement,
) -> None:
    """Fail closed unless the acknowledgement binds this exact, complete inventory."""

    if manifest.is_blocking:
        raise AcknowledgementRejected(
            "expected roots missing or inaccessible: " + ", ".join(manifest.blocking_roots)
        )
    if ack.host != manifest.host or ack.user != manifest.user:
        raise AcknowledgementRejected(
            f"acknowledgement host/user {ack.host}/{ack.user} does not match "
            f"inventory {manifest.host}/{manifest.user}"
        )
    if ack.manifest_hash != manifest.manifest_hash:
        raise AcknowledgementRejected("acknowledgement manifest hash does not match inventory")
    frozen = _parse_iso(manifest.freshness_at)
    acked = _parse_iso(ack.acknowledged_at)
    if frozen is None or acked is None:
        raise AcknowledgementRejected("acknowledgement timestamps must be ISO-8601")
    delta = abs((acked - frozen).total_seconds())
    if delta > ack.freshness_horizon_seconds:
        raise AcknowledgementRejected(
            f"acknowledgement is stale: {delta:.0f}s exceeds "
            f"{ack.freshness_horizon_seconds}s freshness horizon"
        )


# ---------------------------------------------------------------------------
# Normalized authority records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactRef:
    """A content-hash reference to an immutable, externally stored artifact."""

    artifact_id: str
    content_hash: str
    location: str
    kind: str


@dataclass(frozen=True)
class NormalizedRecord:
    """One deterministically normalized legacy authority/evidence item."""

    source_ref: str
    object_kind: str
    identity_key: str
    authority_bearing: bool
    content_hash: str
    repo_ref: str | None
    scope: str | None
    stack: str | None
    provenance: Mapping[str, Any]
    payload: Mapping[str, Any]
    idempotency_keys: tuple[str, ...] = ()
    operation_keys: tuple[str, ...] = ()
    lease_state: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()

    @property
    def is_lease(self) -> bool:
        return self.object_kind == "lease"

    def summary(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "object_kind": self.object_kind,
            "identity_key": self.identity_key,
            "authority_bearing": self.authority_bearing,
            "content_hash": self.content_hash,
            "repo_ref": self.repo_ref,
            "scope": self.scope,
            "stack": self.stack,
            "idempotency_keys": list(self.idempotency_keys),
            "operation_keys": list(self.operation_keys),
            "lease_state": self.lease_state,
            "artifact_refs": [
                {"artifact_id": a.artifact_id, "content_hash": a.content_hash, "kind": a.kind}
                for a in self.artifact_refs
            ],
        }


# ---------------------------------------------------------------------------
# Read-only source adapters (versioned, deterministic, hash-verifying)
# ---------------------------------------------------------------------------


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _sqlite_primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk = [str(row[1]) for row in sorted(columns, key=lambda row: int(row[5])) if int(row[5]) > 0]
    return pk or ([str(columns[0][1])] if columns else [])


def _sqlite_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f"SELECT * FROM {table}")
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.absolute().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# Table -> (object_kind, authority_bearing, is_lease-flag) classification for the
# generic SQLite reader. Unknown tables (schema growth, e.g. new CKM tables) fall
# back to an authority-bearing record keyed by their primary key, so additive
# schema is import-covered by default.
_BUILDEROPS_TABLE_KINDS: dict[str, tuple[str, bool]] = {
    "builderops_records": ("builderops_record", True),
    "builderops_leases": ("lease", True),
    "builderops_idempotency_keys": ("builderops_idempotency", False),
    "builderops_meta": ("builderops_meta", False),
}
_DISPATCHER_TABLE_KINDS: dict[str, tuple[str, bool]] = {
    "dispatcher_tasks": ("dispatcher_task", True),
    "dispatcher_leases": ("lease", True),
    "dispatcher_events": ("dispatcher_event", False),
    "dispatcher_meta": ("dispatcher_meta", False),
    "verification_runs": ("verification_run", True),
    "verification_attempts": ("verification_attempt", True),
    "verification_exceptions": ("verification_exception", True),
}


def _scope_stack_for(producer_name: str, object_kind: str) -> tuple[str, str]:
    # Evidence-bound: derived deterministically from the producing store identity,
    # never from CWD or the import target.
    return (f"legacy:{producer_name}:{object_kind}", f"builderops-legacy:{producer_name}")


def _generic_sqlite_records(
    observed: ObservedSource,
    *,
    table_kinds: Mapping[str, tuple[str, bool]],
    default_authority_bearing: bool,
) -> list[NormalizedRecord]:
    expected = observed.expected
    path = Path(expected.path)
    records: list[NormalizedRecord] = []
    conn = _open_readonly(path)
    try:
        for table in _sqlite_tables(conn):
            pk_columns = _sqlite_primary_key(conn, table)
            object_kind, authority_bearing = table_kinds.get(
                table, (f"{expected.producer}:{table}", default_authority_bearing)
            )
            for row in _sqlite_rows(conn, table):
                identity = "|".join(str(row.get(col)) for col in pk_columns)
                source_ref = f"{expected.key}#{table}:{identity}"
                lease_state = None
                if object_kind == "lease":
                    lease_state = _lease_state(row, observed.modified_at)
                idempotency_keys: tuple[str, ...] = ()
                if table == "builderops_idempotency_keys":
                    idempotency_keys = (str(row.get("key")),)
                operation_keys: tuple[str, ...] = ()
                if "lease_id" in row and row.get("lease_id"):
                    operation_keys = (str(row["lease_id"]),)
                repo_ref = _repo_from_row(row) or expected.repo_identity
                scope, stack = _scope_stack_for(expected.producer, object_kind)
                # Authority-bearing rows keep their natural, globally unique
                # identity so a genuine cross-worktree collision (the #3686
                # fragmentation case) is detected; per-store evidence rows are
                # root-scoped so the same operational key in two databases is two
                # distinct evidence items, not a spurious conflict.
                base_identity = f"{table}:{identity}"
                identity_key = (
                    base_identity if authority_bearing else f"{expected.key}#{base_identity}"
                )
                records.append(
                    NormalizedRecord(
                        source_ref=source_ref,
                        object_kind=object_kind,
                        identity_key=identity_key,
                        authority_bearing=authority_bearing,
                        content_hash=_hash({"table": table, "row": row}),
                        repo_ref=repo_ref,
                        scope=scope,
                        stack=stack,
                        provenance={
                            "producer": expected.producer,
                            "host": expected.host,
                            "user": expected.user,
                            "path": expected.path,
                            "root_kind": expected.root_kind,
                            "table": table,
                            "schema_version": observed.schema_version,
                        },
                        payload=row,
                        idempotency_keys=idempotency_keys,
                        operation_keys=operation_keys,
                        lease_state=lease_state,
                    )
                )
    finally:
        conn.close()
    return sorted(records, key=lambda r: r.source_ref)


def _lease_state(row: Mapping[str, Any], freeze_at: str | None) -> str:
    released = row.get("released_at")
    if released:
        return "expired"
    expires = _parse_iso(str(row.get("expires_at")) if row.get("expires_at") else None)
    frozen = _parse_iso(freeze_at)
    if expires is None or frozen is None:
        return "unknown"
    return "live" if expires > frozen else "expired"


def _repo_from_row(row: Mapping[str, Any]) -> str | None:
    repo = row.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    return None


def read_builderops_sqlite(observed: ObservedSource) -> list[NormalizedRecord]:
    """Read BuilderOps records/leases/idempotency plus co-resident CKM/CEG tables."""

    return _generic_sqlite_records(
        observed,
        table_kinds=_BUILDEROPS_TABLE_KINDS,
        default_authority_bearing=True,
    )


def read_dispatcher_sqlite(observed: ObservedSource) -> list[NormalizedRecord]:
    """Read dispatcher tasks/leases/events/verification tables."""

    return _generic_sqlite_records(
        observed,
        table_kinds=_DISPATCHER_TABLE_KINDS,
        default_authority_bearing=True,
    )


def read_dispatcher_events_jsonl(observed: ObservedSource) -> list[NormalizedRecord]:
    """Read the append-only dispatcher event audit log (evidence)."""

    expected = observed.expected
    path = Path(expected.path)
    records: list[NormalizedRecord] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        event = json.loads(stripped)
        identity = str(event.get("event_id", index))
        scope, stack = _scope_stack_for(expected.producer, "dispatcher_event")
        records.append(
            NormalizedRecord(
                source_ref=f"{expected.key}#event:{identity}",
                object_kind="dispatcher_event",
                identity_key=f"{expected.key}#dispatcher_event:{identity}",
                authority_bearing=False,
                content_hash=_hash(event),
                repo_ref=_repo_from_row(event) or expected.repo_identity,
                scope=scope,
                stack=stack,
                provenance={
                    "producer": expected.producer,
                    "host": expected.host,
                    "user": expected.user,
                    "path": expected.path,
                    "root_kind": expected.root_kind,
                },
                payload=event,
            )
        )
    return records


def read_epic_run_json(observed: ObservedSource) -> list[NormalizedRecord]:
    """Read epic-run state JSON files (authority-bearing run state)."""

    expected = observed.expected
    root = Path(expected.path)
    records: list[NormalizedRecord] = []
    for path in sorted(root.glob("*.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        run_id = str(state.get("run_id", path.stem))
        scope, stack = _scope_stack_for(expected.producer, "epic_run")
        records.append(
            NormalizedRecord(
                source_ref=f"{expected.key}#run:{run_id}",
                object_kind="epic_run",
                identity_key=f"epic_run:{run_id}",
                authority_bearing=True,
                content_hash=_hash(state),
                repo_ref=expected.repo_identity,
                scope=scope,
                stack=stack,
                provenance={
                    "producer": expected.producer,
                    "host": expected.host,
                    "user": expected.user,
                    "path": str(path),
                    "root_kind": expected.root_kind,
                    "epic_issue_number": state.get("epic_issue_number"),
                },
                payload=state,
            )
        )
    return records


def read_model_inquiry_files(observed: ObservedSource) -> list[NormalizedRecord]:
    """Read file-first model inquiries: identity + receipts + immutable artifacts.

    The authoritative identity/state (manifest) and receipts normalize into the
    sink; the large question/turn artifacts stay external and are referenced by
    content hash, so no terminal authority state remains file-only.
    """

    expected = observed.expected
    root = Path(expected.path)
    records: list[NormalizedRecord] = []
    for inquiry_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest_path = inquiry_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        inquiry_id = str(manifest.get("inquiry_id", inquiry_dir.name))
        artifact_refs: list[ArtifactRef] = []
        for artifact_path in sorted(inquiry_dir.rglob("*.json")):
            if artifact_path.name in {"manifest.json"}:
                continue
            if artifact_path.name.startswith("receipt"):
                continue
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact_refs.append(
                ArtifactRef(
                    artifact_id=str(artifact.get("artifact_id", artifact_path.stem)),
                    content_hash=str(
                        artifact.get("artifact_hash") or _hash_bytes(_read_bytes(artifact_path))
                    ),
                    location=str(artifact_path),
                    kind=artifact_path.parent.name if artifact_path.parent != inquiry_dir else "root",
                )
            )
        scope, stack = _scope_stack_for(expected.producer, "model_inquiry")
        repo_ref = str(manifest.get("repo")) if manifest.get("repo") else expected.repo_identity
        records.append(
            NormalizedRecord(
                source_ref=f"{expected.key}#inquiry:{inquiry_id}",
                object_kind="model_inquiry",
                identity_key=f"model_inquiry:{inquiry_id}",
                authority_bearing=True,
                content_hash=_hash(manifest),
                repo_ref=repo_ref,
                scope=scope,
                stack=stack,
                provenance={
                    "producer": expected.producer,
                    "host": expected.host,
                    "user": expected.user,
                    "path": str(inquiry_dir),
                    "root_kind": expected.root_kind,
                },
                payload=manifest,
                artifact_refs=tuple(artifact_refs),
            )
        )
        for receipt_path in sorted(inquiry_dir.glob("receipt*.json")):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_id = str(receipt.get("id", receipt_path.stem))
            records.append(
                NormalizedRecord(
                    source_ref=f"{expected.key}#receipt:{receipt_id}",
                    object_kind="model_inquiry_receipt",
                    identity_key=f"{expected.key}#model_inquiry_receipt:{receipt_id}",
                    authority_bearing=False,
                    content_hash=_hash(receipt),
                    repo_ref=repo_ref,
                    scope=scope,
                    stack=stack,
                    provenance={
                        "producer": expected.producer,
                        "host": expected.host,
                        "user": expected.user,
                        "path": str(receipt_path),
                        "root_kind": expected.root_kind,
                        "inquiry_id": inquiry_id,
                    },
                    payload=receipt,
                )
            )
    return records


_READERS: dict[str, Callable[[ObservedSource], list[NormalizedRecord]]] = {
    SOURCE_BUILDEROPS_SQLITE: read_builderops_sqlite,
    SOURCE_DISPATCHER_SQLITE: read_dispatcher_sqlite,
    SOURCE_DISPATCHER_EVENTS_JSONL: read_dispatcher_events_jsonl,
    SOURCE_EPIC_RUN_JSON: read_epic_run_json,
    SOURCE_MODEL_INQUIRY_FILES: read_model_inquiry_files,
}


def default_reader(observed: ObservedSource) -> list[NormalizedRecord]:
    reader = _READERS.get(observed.expected.source_class)
    if reader is None:
        raise LegacyMigrationError(
            f"no read-only adapter for source class {observed.expected.source_class!r}"
        )
    return reader(observed)


def _hash_directory(root: Path) -> str:
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append((str(path.relative_to(root)), _hash_bytes(_read_bytes(path))))
    return _hash(entries)


def freeze_content_hash(expected: ExpectedRoot) -> str:
    """Compute the freeze-time content hash for an expected root's source."""

    path = Path(expected.path)
    if path.is_dir():
        return _hash_directory(path)
    return _hash_bytes(_read_bytes(path))


def normalize_sources(
    manifest: CoverageManifest,
    *,
    reader: Callable[[ObservedSource], list[NormalizedRecord]] = default_reader,
) -> list[NormalizedRecord]:
    """Read and normalize every usable frozen source, rejecting changed sources.

    Each source's content hash is re-verified against the frozen manifest before
    any record is produced; a single changed source fails closed and no records
    are returned (import nothing further).
    """

    records: list[NormalizedRecord] = []
    for observed in manifest.usable_sources():
        current = freeze_content_hash(observed.expected)
        if observed.content_hash is not None and current != observed.content_hash:
            raise SourceChangedError(
                f"source {observed.expected.key!r} changed after freeze "
                f"(frozen={observed.content_hash}, current={current})"
            )
        records.extend(reader(observed))
    return sorted(records, key=lambda r: r.source_ref)


# ---------------------------------------------------------------------------
# Import outcome vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConflictResolution:
    """An evidence-bound resolution for an authority conflict/ambiguity group."""

    object_kind: str
    identity_key: str
    kind: str  # "evidence" | "tombstone"
    winner_source_ref: str | None = None
    repo_ref: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class AuthorityTombstone:
    """A non-authoritative tombstone reserving legacy keys; cannot authorize."""

    object_kind: str
    identity_key: str
    reserved_identity_keys: frozenset[str]
    reserved_idempotency_keys: frozenset[str]
    reserved_operation_keys: frozenset[str]
    source_hashes: tuple[str, ...]
    reason: str

    def authorizes_effect(self) -> bool:
        return False

    def summary(self) -> dict[str, Any]:
        return {
            "object_kind": self.object_kind,
            "identity_key": self.identity_key,
            "reserved_identity_keys": sorted(self.reserved_identity_keys),
            "reserved_idempotency_keys": sorted(self.reserved_idempotency_keys),
            "reserved_operation_keys": sorted(self.reserved_operation_keys),
            "source_hashes": list(self.source_hashes),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class QuarantineItem:
    """Evidence-only quarantine; non-authoritative, cannot authorize an effect."""

    source_ref: str
    object_kind: str
    identity_key: str
    content_hash: str
    reason: str

    def authorizes_effect(self) -> bool:
        return False

    def summary(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "object_kind": self.object_kind,
            "identity_key": self.identity_key,
            "content_hash": self.content_hash,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExpiredLeaseEvidence:
    """A legacy lease imported only as expired evidence; cannot mutate."""

    source_ref: str
    identity_key: str
    holder: str
    legacy_expires_at: str | None
    legacy_state: str
    source_hash: str

    def authorizes_mutation(self) -> bool:
        return False

    def summary(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "identity_key": self.identity_key,
            "holder": self.holder,
            "legacy_expires_at": self.legacy_expires_at,
            "legacy_state": self.legacy_state,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True)
class BlockingConflict:
    """An unresolved authority conflict/ambiguity that blocks cutover."""

    object_kind: str
    identity_key: str
    reason: str
    source_refs: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "object_kind": self.object_kind,
            "identity_key": self.identity_key,
            "reason": self.reason,
            "source_refs": list(self.source_refs),
        }


# ---------------------------------------------------------------------------
# Authority sink
# ---------------------------------------------------------------------------


@runtime_checkable
class AuthoritySink(Protocol):
    """Domain-neutral target authority for imported legacy state."""

    def begin_epoch(self, *, epoch_id: str, fencing_base: int) -> None: ...

    def apply_authority_record(self, record: NormalizedRecord) -> bool: ...

    def record_tombstone(self, tombstone: AuthorityTombstone) -> None: ...

    def record_quarantine(self, item: QuarantineItem) -> None: ...

    def record_expired_lease(self, lease: ExpiredLeaseEvidence) -> None: ...

    def has_live_lease(self, identity_key: str) -> bool: ...

    def is_reserved(
        self,
        *,
        identity_key: str | None = None,
        idempotency_key: str | None = None,
        operation_key: str | None = None,
    ) -> bool: ...


class InMemoryAuthoritySink:
    """In-memory :class:`AuthoritySink` for deterministic non-production runs."""

    def __init__(self) -> None:
        self.epoch_id: str | None = None
        self.fencing_base: int | None = None
        self.applied: dict[tuple[str, str], str] = {}
        self.tombstones: dict[tuple[str, str], AuthorityTombstone] = {}
        self.quarantines: dict[str, QuarantineItem] = {}
        self.expired_leases: dict[str, ExpiredLeaseEvidence] = {}
        self._reserved_identities: set[str] = set()
        self._reserved_idempotency: set[str] = set()
        self._reserved_operations: set[str] = set()

    def begin_epoch(self, *, epoch_id: str, fencing_base: int) -> None:
        # Fail closed on an epoch rewind: fencing must be monotonic.
        if self.fencing_base is not None and fencing_base <= self.fencing_base:
            raise LegacyMigrationError(
                f"epoch fencing base must advance ({fencing_base} <= {self.fencing_base})"
            )
        self.epoch_id = epoch_id
        self.fencing_base = fencing_base

    def apply_authority_record(self, record: NormalizedRecord) -> bool:
        if record.is_lease:
            raise LegacyMigrationError("leases cannot be applied as live authority")
        for key in (record.identity_key, *record.idempotency_keys, *record.operation_keys):
            if self._is_reserved(key):
                raise AuthorityReplayError(
                    f"replay of tombstoned legacy key {key!r} is rejected as a manual conflict"
                )
        slot = (record.object_kind, record.identity_key)
        existing = self.applied.get(slot)
        if existing == record.content_hash:
            return False  # idempotent no-op
        self.applied[slot] = record.content_hash
        return True

    def record_tombstone(self, tombstone: AuthorityTombstone) -> None:
        self.tombstones[(tombstone.object_kind, tombstone.identity_key)] = tombstone
        self._reserved_identities |= set(tombstone.reserved_identity_keys)
        self._reserved_idempotency |= set(tombstone.reserved_idempotency_keys)
        self._reserved_operations |= set(tombstone.reserved_operation_keys)

    def record_quarantine(self, item: QuarantineItem) -> None:
        self.quarantines[item.source_ref] = item

    def record_expired_lease(self, lease: ExpiredLeaseEvidence) -> None:
        self.expired_leases[lease.source_ref] = lease

    def has_live_lease(self, identity_key: str) -> bool:
        return False  # no legacy lease is ever imported as live

    def _is_reserved(self, key: str) -> bool:
        return (
            key in self._reserved_identities
            or key in self._reserved_idempotency
            or key in self._reserved_operations
        )

    def is_reserved(
        self,
        *,
        identity_key: str | None = None,
        idempotency_key: str | None = None,
        operation_key: str | None = None,
    ) -> bool:
        return any(
            [
                identity_key is not None and identity_key in self._reserved_identities,
                idempotency_key is not None and idempotency_key in self._reserved_idempotency,
                operation_key is not None and operation_key in self._reserved_operations,
            ]
        )


# ---------------------------------------------------------------------------
# Import engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationReceipts:
    """Machine-readable receipts consumed by BCP-06."""

    preflight: Mapping[str, Any]
    dry_run: Mapping[str, Any]
    import_apply: Mapping[str, Any]
    reconciliation: Mapping[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "preflight": dict(self.preflight),
            "dry_run": dict(self.dry_run),
            "import_apply": dict(self.import_apply),
            "reconciliation": dict(self.reconciliation),
        }


@dataclass(frozen=True)
class ImportResult:
    """The deterministic outcome of one import pass."""

    epoch_id: str
    fencing_base: int
    dispositions: Mapping[str, str]
    imported: tuple[str, ...]
    deduplicated: tuple[str, ...]
    quarantined: tuple[str, ...]
    tombstoned: tuple[str, ...]
    expired_leases: tuple[str, ...]
    blocked: tuple[BlockingConflict, ...]
    dry_run: bool
    result_hash: str

    @property
    def cutover_blocked(self) -> bool:
        return bool(self.blocked)

    def summary(self) -> dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "fencing_base": self.fencing_base,
            "dispositions": dict(sorted(self.dispositions.items())),
            "imported": list(self.imported),
            "deduplicated": list(self.deduplicated),
            "quarantined": list(self.quarantined),
            "tombstoned": list(self.tombstoned),
            "expired_leases": list(self.expired_leases),
            "blocked": [conflict.summary() for conflict in self.blocked],
            "dry_run": self.dry_run,
            "cutover_blocked": self.cutover_blocked,
        }


def _group_records(
    records: Sequence[NormalizedRecord],
) -> dict[tuple[str, str], list[NormalizedRecord]]:
    groups: dict[tuple[str, str], list[NormalizedRecord]] = {}
    for record in records:
        groups.setdefault((record.object_kind, record.identity_key), []).append(record)
    for group in groups.values():
        group.sort(key=lambda r: r.source_ref)
    return groups


def _resolution_for(
    resolutions: Sequence[ConflictResolution],
    object_kind: str,
    identity_key: str,
) -> ConflictResolution | None:
    for resolution in resolutions:
        if resolution.object_kind == object_kind and resolution.identity_key == identity_key:
            return resolution
    return None


def _build_tombstone(
    object_kind: str,
    identity_key: str,
    group: Sequence[NormalizedRecord],
    reason: str,
) -> AuthorityTombstone:
    identity_keys = {identity_key}
    idempotency: set[str] = set()
    operations: set[str] = set()
    hashes: list[str] = []
    for record in group:
        identity_keys.add(record.identity_key)
        idempotency |= set(record.idempotency_keys)
        operations |= set(record.operation_keys)
        hashes.append(record.content_hash)
    return AuthorityTombstone(
        object_kind=object_kind,
        identity_key=identity_key,
        reserved_identity_keys=frozenset(identity_keys),
        reserved_idempotency_keys=frozenset(idempotency),
        reserved_operation_keys=frozenset(operations),
        source_hashes=tuple(sorted(hashes)),
        reason=reason,
    )


def import_records(
    records: Sequence[NormalizedRecord],
    *,
    sink: AuthoritySink,
    epoch_id: str,
    fencing_base: int = 1,
    resolutions: Sequence[ConflictResolution] = (),
    repo_mappings: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> ImportResult:
    """Deterministically import normalized records into a target authority sink.

    The pass is idempotent and restart-safe: applying the same records twice
    yields the same ``result_hash`` and no second authority row. Authority
    conflicts/ambiguities never resolve silently; they block unless
    evidence-resolved or duplicate-preventing tombstoned.
    """

    repo_mappings = dict(repo_mappings or {})
    groups = _group_records(records)

    dispositions: dict[str, str] = {}
    imported: list[str] = []
    deduplicated: list[str] = []
    quarantined: list[str] = []
    tombstoned: list[str] = []
    expired_leases: list[str] = []
    blocked: list[BlockingConflict] = []

    planned_apply: list[NormalizedRecord] = []
    planned_tombstones: list[AuthorityTombstone] = []
    planned_quarantines: list[QuarantineItem] = []
    planned_expired: list[ExpiredLeaseEvidence] = []

    for (object_kind, identity_key), group in sorted(groups.items()):
        resolution = _resolution_for(resolutions, object_kind, identity_key)

        # Leases never cross the epoch: import as expired evidence only.
        if object_kind == "lease":
            for record in group:
                evidence = ExpiredLeaseEvidence(
                    source_ref=record.source_ref,
                    identity_key=record.identity_key,
                    holder=str(record.payload.get("holder") or record.payload.get("actor") or ""),
                    legacy_expires_at=(
                        str(record.payload.get("expires_at"))
                        if record.payload.get("expires_at")
                        else None
                    ),
                    legacy_state=record.lease_state or "unknown",
                    source_hash=record.content_hash,
                )
                planned_expired.append(evidence)
                expired_leases.append(record.source_ref)
                dispositions[record.source_ref] = Disposition.EXPIRED_LEASE
            continue

        # Backfill repo provenance from evidence-bound mappings only.
        resolved_group = [_apply_repo_mapping(record, repo_mappings) for record in group]

        content_hashes = {record.content_hash for record in resolved_group}
        authority_records = [r for r in resolved_group if r.authority_bearing]

        # Divergent-content conflict.
        if len(content_hashes) > 1:
            if authority_records:
                outcome = _resolve_authority_group(
                    object_kind,
                    identity_key,
                    resolved_group,
                    resolution,
                    reason="divergent authority-bearing identities",
                )
                _record_group_outcome(
                    outcome,
                    dispositions,
                    imported,
                    tombstoned,
                    blocked,
                    planned_apply,
                    planned_tombstones,
                )
            else:
                # Evidence-only conflict may remain plain quarantine.
                for record in resolved_group:
                    item = QuarantineItem(
                        source_ref=record.source_ref,
                        object_kind=object_kind,
                        identity_key=identity_key,
                        content_hash=record.content_hash,
                        reason="evidence-only divergent content",
                    )
                    planned_quarantines.append(item)
                    quarantined.append(record.source_ref)
                    dispositions[record.source_ref] = Disposition.EVIDENCE_QUARANTINED
            continue

        # Ambiguous repo provenance (no evidence-bound repo).
        ambiguous = [r for r in resolved_group if r.repo_ref is None]
        if ambiguous:
            if authority_records:
                outcome = _resolve_authority_group(
                    object_kind,
                    identity_key,
                    resolved_group,
                    resolution,
                    reason="authority-bearing ambiguous repo provenance",
                )
                _record_group_outcome(
                    outcome,
                    dispositions,
                    imported,
                    tombstoned,
                    blocked,
                    planned_apply,
                    planned_tombstones,
                )
            else:
                for record in resolved_group:
                    item = QuarantineItem(
                        source_ref=record.source_ref,
                        object_kind=object_kind,
                        identity_key=identity_key,
                        content_hash=record.content_hash,
                        reason="evidence-only ambiguous repo provenance",
                    )
                    planned_quarantines.append(item)
                    quarantined.append(record.source_ref)
                    dispositions[record.source_ref] = Disposition.EVIDENCE_QUARANTINED
            continue

        # Clean group: import the canonical record once, dedup the rest.
        canonical = resolved_group[0]
        planned_apply.append(canonical)
        imported.append(canonical.source_ref)
        dispositions[canonical.source_ref] = Disposition.IMPORTED
        for record in resolved_group[1:]:
            deduplicated.append(record.source_ref)
            dispositions[record.source_ref] = Disposition.DEDUPLICATED

    # Apply the plan (unless dry-run). Tombstones first so replay of a reserved
    # key fails closed even within the same pass.
    if not dry_run:
        sink.begin_epoch(epoch_id=epoch_id, fencing_base=fencing_base)
        for tombstone in planned_tombstones:
            sink.record_tombstone(tombstone)
        for item in planned_quarantines:
            sink.record_quarantine(item)
        for evidence in planned_expired:
            sink.record_expired_lease(evidence)
        for record in planned_apply:
            applied = sink.apply_authority_record(record)
            if not applied and dispositions.get(record.source_ref) == Disposition.IMPORTED:
                dispositions[record.source_ref] = Disposition.DEDUPLICATED
                if record.source_ref in imported:
                    imported.remove(record.source_ref)
                    deduplicated.append(record.source_ref)

    result_body = {
        "epoch_id": epoch_id,
        "fencing_base": fencing_base,
        "dispositions": dict(sorted(dispositions.items())),
        "tombstones": sorted((t.summary() for t in planned_tombstones), key=_canonical),
        "quarantines": sorted((q.summary() for q in planned_quarantines), key=_canonical),
        "expired_leases": sorted((e.summary() for e in planned_expired), key=_canonical),
        "blocked": sorted((b.summary() for b in blocked), key=_canonical),
    }
    return ImportResult(
        epoch_id=epoch_id,
        fencing_base=fencing_base,
        dispositions=dispositions,
        imported=tuple(sorted(imported)),
        deduplicated=tuple(sorted(deduplicated)),
        quarantined=tuple(sorted(quarantined)),
        tombstoned=tuple(sorted(tombstoned)),
        expired_leases=tuple(sorted(expired_leases)),
        blocked=tuple(sorted(blocked, key=lambda b: (b.object_kind, b.identity_key))),
        dry_run=dry_run,
        result_hash=_hash(result_body),
    )


def _apply_repo_mapping(
    record: NormalizedRecord,
    repo_mappings: Mapping[str, str],
) -> NormalizedRecord:
    if record.repo_ref is not None:
        return record
    mapped = repo_mappings.get(record.source_ref) or repo_mappings.get(
        str(record.provenance.get("path", ""))
    )
    if mapped is None:
        return record
    return NormalizedRecord(
        source_ref=record.source_ref,
        object_kind=record.object_kind,
        identity_key=record.identity_key,
        authority_bearing=record.authority_bearing,
        content_hash=record.content_hash,
        repo_ref=mapped,
        scope=record.scope,
        stack=record.stack,
        provenance=record.provenance,
        payload=record.payload,
        idempotency_keys=record.idempotency_keys,
        operation_keys=record.operation_keys,
        lease_state=record.lease_state,
        artifact_refs=record.artifact_refs,
    )


@dataclass(frozen=True)
class _GroupOutcome:
    apply: tuple[NormalizedRecord, ...] = ()
    imported: tuple[str, ...] = ()
    deduplicated: tuple[str, ...] = ()
    tombstone: AuthorityTombstone | None = None
    tombstoned: tuple[str, ...] = ()
    blocked: BlockingConflict | None = None


def _resolve_authority_group(
    object_kind: str,
    identity_key: str,
    group: Sequence[NormalizedRecord],
    resolution: ConflictResolution | None,
    *,
    reason: str,
) -> _GroupOutcome:
    if resolution is None:
        return _GroupOutcome(
            blocked=BlockingConflict(
                object_kind=object_kind,
                identity_key=identity_key,
                reason=reason,
                source_refs=tuple(r.source_ref for r in group),
            )
        )
    if resolution.kind == "tombstone":
        tombstone = _build_tombstone(object_kind, identity_key, group, resolution.reason or reason)
        return _GroupOutcome(
            tombstone=tombstone,
            tombstoned=tuple(r.source_ref for r in group),
        )
    if resolution.kind == "evidence":
        winner = _select_winner(group, resolution)
        if winner is None:
            return _GroupOutcome(
                blocked=BlockingConflict(
                    object_kind=object_kind,
                    identity_key=identity_key,
                    reason=f"{reason}; evidence resolution names no valid winner",
                    source_refs=tuple(r.source_ref for r in group),
                )
            )
        resolved = winner
        if resolved.repo_ref is None and resolution.repo_ref is not None:
            resolved = _with_repo_ref(resolved, resolution.repo_ref)
        if resolved.repo_ref is None:
            return _GroupOutcome(
                blocked=BlockingConflict(
                    object_kind=object_kind,
                    identity_key=identity_key,
                    reason=f"{reason}; evidence winner still lacks repo provenance",
                    source_refs=tuple(r.source_ref for r in group),
                )
            )
        losers = tuple(r.source_ref for r in group if r.source_ref != resolved.source_ref)
        return _GroupOutcome(
            apply=(resolved,),
            imported=(resolved.source_ref,),
            deduplicated=losers,
        )
    return _GroupOutcome(
        blocked=BlockingConflict(
            object_kind=object_kind,
            identity_key=identity_key,
            reason=f"{reason}; unknown resolution kind {resolution.kind!r}",
            source_refs=tuple(r.source_ref for r in group),
        )
    )


def _select_winner(
    group: Sequence[NormalizedRecord],
    resolution: ConflictResolution,
) -> NormalizedRecord | None:
    if resolution.winner_source_ref is None:
        return None
    for record in group:
        if record.source_ref == resolution.winner_source_ref:
            return record
    return None


def _with_repo_ref(record: NormalizedRecord, repo_ref: str) -> NormalizedRecord:
    return NormalizedRecord(
        source_ref=record.source_ref,
        object_kind=record.object_kind,
        identity_key=record.identity_key,
        authority_bearing=record.authority_bearing,
        content_hash=record.content_hash,
        repo_ref=repo_ref,
        scope=record.scope,
        stack=record.stack,
        provenance=record.provenance,
        payload=record.payload,
        idempotency_keys=record.idempotency_keys,
        operation_keys=record.operation_keys,
        lease_state=record.lease_state,
        artifact_refs=record.artifact_refs,
    )


def _record_group_outcome(
    outcome: _GroupOutcome,
    dispositions: dict[str, str],
    imported: list[str],
    tombstoned: list[str],
    blocked: list[BlockingConflict],
    planned_apply: list[NormalizedRecord],
    planned_tombstones: list[AuthorityTombstone],
) -> None:
    for record in outcome.apply:
        planned_apply.append(record)
    for source_ref in outcome.imported:
        imported.append(source_ref)
        dispositions[source_ref] = Disposition.IMPORTED
    for source_ref in outcome.deduplicated:
        dispositions[source_ref] = Disposition.DEDUPLICATED
    if outcome.tombstone is not None:
        planned_tombstones.append(outcome.tombstone)
    for source_ref in outcome.tombstoned:
        tombstoned.append(source_ref)
        dispositions[source_ref] = Disposition.AUTHORITY_TOMBSTONED
    if outcome.blocked is not None:
        blocked.append(outcome.blocked)
        for source_ref in outcome.blocked.source_refs:
            dispositions[source_ref] = Disposition.BLOCKED


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationLedger:
    """Accounts for every expected producer/root and source item."""

    producers_accounted: Mapping[str, int]
    roots: Mapping[str, str]
    items: Mapping[str, str]
    coverage_gaps: tuple[str, ...]
    authority_replay_gaps: tuple[str, ...]
    ledger_hash: str

    @property
    def cutover_blocked(self) -> bool:
        return bool(self.coverage_gaps or self.authority_replay_gaps)

    def as_json(self) -> dict[str, Any]:
        return {
            "producers_accounted": dict(sorted(self.producers_accounted.items())),
            "roots": dict(sorted(self.roots.items())),
            "items": dict(sorted(self.items.items())),
            "coverage_gaps": list(self.coverage_gaps),
            "authority_replay_gaps": list(self.authority_replay_gaps),
            "cutover_blocked": self.cutover_blocked,
        }


def reconcile(
    *,
    expected_roots: Sequence[ExpectedRoot],
    manifest: CoverageManifest,
    records: Sequence[NormalizedRecord],
    import_result: ImportResult,
    archived: Mapping[str, str] | None = None,
) -> ReconciliationLedger:
    """Reconcile the expected universe against the import outcome.

    Every expected producer/root and every source item is accounted for; any
    unresolved coverage gap or authority-replay gap blocks cutover.
    """

    archived = dict(archived or {})
    observed_by_key = {source.expected.key: source for source in manifest.sources}
    records_by_root: dict[str, list[NormalizedRecord]] = {}
    for record in records:
        root_key = record.source_ref.split("#", 1)[0]
        records_by_root.setdefault(root_key, []).append(record)

    roots: dict[str, str] = {}
    producers_accounted: dict[str, int] = {}
    coverage_gaps: list[str] = []
    for expected in expected_roots:
        producers_accounted[expected.producer] = producers_accounted.get(expected.producer, 0) + 1
        key = expected.key
        if key in archived:
            roots[key] = Disposition.ARCHIVED
            continue
        if key in manifest.exclusions:
            roots[key] = Disposition.EXCLUDED
            continue
        observed = observed_by_key.get(key)
        if observed is None or not observed.present:
            roots[key] = Disposition.MISSING
            coverage_gaps.append(key)
            continue
        if not observed.accessible:
            roots[key] = Disposition.INACCESSIBLE
            coverage_gaps.append(key)
            continue
        roots[key] = Disposition.IMPORTED

    items: dict[str, str] = dict(import_result.dispositions)

    authority_replay_gaps = tuple(
        sorted(conflict.identity_key for conflict in import_result.blocked)
    )

    ledger_body = {
        "producers_accounted": dict(sorted(producers_accounted.items())),
        "roots": dict(sorted(roots.items())),
        "items": dict(sorted(items.items())),
        "coverage_gaps": sorted(coverage_gaps),
        "authority_replay_gaps": list(authority_replay_gaps),
    }
    return ReconciliationLedger(
        producers_accounted=producers_accounted,
        roots=roots,
        items=items,
        coverage_gaps=tuple(sorted(coverage_gaps)),
        authority_replay_gaps=authority_replay_gaps,
        ledger_hash=_hash(ledger_body),
    )


# ---------------------------------------------------------------------------
# Receipts and orchestration
# ---------------------------------------------------------------------------


def build_receipts(
    *,
    manifest: CoverageManifest,
    ack: InventoryAcknowledgement,
    dry_run_result: ImportResult,
    import_result: ImportResult,
    ledger: ReconciliationLedger,
) -> MigrationReceipts:
    """Assemble the preflight/dry-run/import/reconciliation receipts for BCP-06."""

    preflight = {
        "host": manifest.host,
        "user": manifest.user,
        "freshness_at": manifest.freshness_at,
        "manifest_hash": manifest.manifest_hash,
        "acknowledged_at": ack.acknowledged_at,
        "blocking_roots": list(manifest.blocking_roots),
        "source_count": len(manifest.sources),
        "usable_source_count": len(manifest.usable_sources()),
        # #3686 / PR #3695 fragmentation evidence is preserved in the coverage
        # entries: every enumerated worktree root is a distinct manifest source.
        "evidence_refs": ["issue:3686", "pr:3695"],
    }
    return MigrationReceipts(
        preflight=preflight,
        dry_run=dry_run_result.summary(),
        import_apply=import_result.summary(),
        reconciliation=ledger.as_json(),
    )


@dataclass(frozen=True)
class MigrationRun:
    """The full result of one orchestrated migration pass."""

    manifest: CoverageManifest
    records: tuple[NormalizedRecord, ...]
    dry_run_result: ImportResult
    import_result: ImportResult
    ledger: ReconciliationLedger
    receipts: MigrationReceipts

    @property
    def cutover_blocked(self) -> bool:
        return self.import_result.cutover_blocked or self.ledger.cutover_blocked


def run_migration(
    *,
    expected_roots: Sequence[ExpectedRoot],
    manifest: CoverageManifest,
    ack: InventoryAcknowledgement,
    sink: AuthoritySink,
    epoch_id: str,
    fencing_base: int = 1,
    reader: Callable[[ObservedSource], list[NormalizedRecord]] = default_reader,
    resolutions: Sequence[ConflictResolution] = (),
    repo_mappings: Mapping[str, str] | None = None,
    archived: Mapping[str, str] | None = None,
) -> MigrationRun:
    """Acknowledge, freeze-verify, dry-run, import, and reconcile in one pass."""

    accept_acknowledgement(manifest, ack)
    records = tuple(normalize_sources(manifest, reader=reader))
    dry_run_result = import_records(
        records,
        sink=sink,
        epoch_id=epoch_id,
        fencing_base=fencing_base,
        resolutions=resolutions,
        repo_mappings=repo_mappings,
        dry_run=True,
    )
    import_result = import_records(
        records,
        sink=sink,
        epoch_id=epoch_id,
        fencing_base=fencing_base,
        resolutions=resolutions,
        repo_mappings=repo_mappings,
        dry_run=False,
    )
    ledger = reconcile(
        expected_roots=expected_roots,
        manifest=manifest,
        records=records,
        import_result=import_result,
        archived=archived,
    )
    receipts = build_receipts(
        manifest=manifest,
        ack=ack,
        dry_run_result=dry_run_result,
        import_result=import_result,
        ledger=ledger,
    )
    return MigrationRun(
        manifest=manifest,
        records=records,
        dry_run_result=dry_run_result,
        import_result=import_result,
        ledger=ledger,
        receipts=receipts,
    )


__all__ = [
    "AcknowledgementRejected",
    "ArtifactRef",
    "AuthorityReplayError",
    "AuthoritySink",
    "AuthorityTombstone",
    "BlockingConflict",
    "ConflictResolution",
    "CoverageManifest",
    "Disposition",
    "EnumeratedRoot",
    "ExpectedRoot",
    "ExpiredLeaseEvidence",
    "HostContext",
    "ImportResult",
    "InMemoryAuthoritySink",
    "InventoryAcknowledgement",
    "InventoryCoverageError",
    "LegacyMigrationError",
    "MigrationReceipts",
    "MigrationRun",
    "NormalizedRecord",
    "ObservedSource",
    "PRODUCER_MANIFEST",
    "ProducerSpec",
    "QuarantineItem",
    "ReconciliationLedger",
    "RootKind",
    "SourceChangedError",
    "SourceProbe",
    "WriterStatus",
    "accept_acknowledgement",
    "build_coverage_manifest",
    "build_receipts",
    "default_reader",
    "derive_expected_universe",
    "freeze_content_hash",
    "import_records",
    "normalize_sources",
    "producer",
    "read_builderops_sqlite",
    "read_dispatcher_events_jsonl",
    "read_dispatcher_sqlite",
    "read_epic_run_json",
    "read_model_inquiry_files",
    "reconcile",
    "run_migration",
]
