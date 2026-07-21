"""Fail-closed evidence for the one-time BuilderOps SQLite store cutover.

The operator declares the participating repository roots.  This module does
not claim to discover arbitrary filesystems; it deterministically inventories
every legacy store below those declared roots and binds that result to a
non-empty, already-reconciled target database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import NAMESPACE_OID, UUID, uuid5


RECEIPT_SCHEMA = "builderops.host-store-cutover.v2"
_LEGACY_DB = "builderops.sqlite3"


class CutoverEvidenceError(ValueError):
    """Raised when cutover evidence cannot safely activate the implicit store."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _derived_epoch(host: str, user: str, participants: Any, inventory: Any, report: Any, target_identity: str) -> str:
    seed = {"host": host, "user": user, "participants": participants, "inventory": inventory, "reconciliation": report, "target_identity": target_identity}
    return str(uuid5(NAMESPACE_OID, hashlib.sha256(_canonical(seed)).hexdigest()))


def _evidence_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("receipt_sha256", None)
    target = result.get("target_store")
    if isinstance(target, Mapping):
        result["target_store"] = {"path": target.get("path"), "identity": target.get("identity")}
    return result


def _sha256_path(path: Path) -> str:
    before = _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _regular(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise CutoverEvidenceError("store changed while being inventoried")
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CutoverEvidenceError("cutover epoch must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _regular(path: Path) -> os.stat_result:
    entry = path.lstat()
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise CutoverEvidenceError("cutover evidence contains a non-regular path")
    return entry


def _participants(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise CutoverEvidenceError("participant inventory must be a non-empty ordered list")
    result: list[dict[str, str]] = []
    roots: set[Path] = set()
    repos: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise CutoverEvidenceError("participant inventory entry is invalid")
        repo, root = item.get("repository"), item.get("root")
        if not isinstance(repo, str) or not repo.strip() or not isinstance(root, str):
            raise CutoverEvidenceError("participant repository/root is invalid")
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir() or resolved in roots or repo in repos:
            raise CutoverEvidenceError("participant roots and repositories must be unique directories")
        roots.add(resolved)
        repos.add(repo)
        result.append({"repository": repo, "root": str(resolved)})
    return result


def discover_legacy_stores(participants: Any) -> list[dict[str, Any]]:
    """Return a deterministic complete inventory beneath declared roots."""
    stores: list[dict[str, Any]] = []
    for participant in _participants(participants):
        root = Path(participant["root"])
        def fail_walk(error: OSError) -> None:
            raise CutoverEvidenceError("participant inventory traversal failed") from error
        for directory, child_dirs, filenames in os.walk(root, followlinks=False, onerror=fail_walk):
            base = Path(directory)
            child_dirs[:] = sorted(name for name in child_dirs if not (base / name).is_symlink())
            if base.name != "builderops" or base.parent.name != "runtime" or _LEGACY_DB not in filenames:
                continue
            path = base / _LEGACY_DB
            entry = _regular(path)
            stores.append({
                "repository": participant["repository"], "path": str(path.resolve()),
                "sha256": _sha256_path(path), "size": entry.st_size, "mtime_ns": entry.st_mtime_ns,
            })
    return sorted(stores, key=lambda item: (item["repository"], item["path"]))


def _records(path: Path) -> list[dict[str, str]]:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute("SELECT id, payload FROM builderops_records ORDER BY id").fetchall()
    except sqlite3.Error as exc:
        raise CutoverEvidenceError("BuilderOps store is malformed or unreadable") from exc
    return [{"id": str(row[0]), "payload_sha256": hashlib.sha256(str(row[1]).encode()).hexdigest()} for row in rows]


def inspect_target(db_path: Path) -> dict[str, Any]:
    """Inspect an existing target without creating or initializing it."""
    entry = _regular(db_path)
    if entry.st_size == 0:
        raise CutoverEvidenceError("target store is empty")
    try:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            count = connection.execute("SELECT COUNT(*) FROM builderops_records").fetchone()[0]
            marker = connection.execute("SELECT value FROM builderops_meta WHERE key = 'host_store_cutover_v2'").fetchone()
    except sqlite3.Error as exc:
        raise CutoverEvidenceError("target store is not an initialized BuilderOps database") from exc
    if not isinstance(count, int) or count <= 0:
        raise CutoverEvidenceError("target store is empty")
    # The target necessarily changes after cutover as normal BuilderOps records
    # are appended.  Bind its identity and prove it was non-empty at receipt
    # production; validation then proves the same target remains non-empty,
    # rather than treating legitimate post-cutover writes as tampering.
    identity = hashlib.sha256(f"{entry.st_dev}:{entry.st_ino}:{db_path.resolve()}".encode()).hexdigest()
    records = _records(db_path)
    return {"path": str(db_path.resolve()), "record_count": count, "records_sha256": hashlib.sha256(_canonical(records)).hexdigest(), "identity": identity, "marker": marker[0] if marker else None}


def _stamp_target(db_path: Path, marker: Mapping[str, str]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT OR REPLACE INTO builderops_meta(key, value) VALUES (?, ?)", ("host_store_cutover_v2", _canonical(dict(marker)).decode()))
        connection.commit()


def _reconciliation(raw: Any, inventory: list[dict[str, Any]], target_path: Path) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise CutoverEvidenceError("reconciliation report must contain a store list")
    reported: dict[str, dict[str, Any]] = {}
    target_records = {(item["id"], item["payload_sha256"]) for item in _records(target_path)}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or not isinstance(item.get("disposition"), str):
            raise CutoverEvidenceError("reconciliation report entry is invalid")
        path, disposition = str(Path(item["path"]).resolve()), item["disposition"]
        if disposition not in {"migrated", "retained"} or path in reported:
            raise CutoverEvidenceError("reconciliation disposition is invalid")
        source = _records(Path(path))
        source_digest = hashlib.sha256(_canonical(source)).hexdigest()
        if item.get("source_records_sha256") not in {None, source_digest}:
            raise CutoverEvidenceError("reconciliation source evidence does not match legacy store")
        if disposition == "migrated" and not {(row["id"], row["payload_sha256"]) for row in source}.issubset(target_records):
            raise CutoverEvidenceError("migrated legacy records are not accounted for in target")
        reported[path] = {"path": path, "disposition": disposition, "source_records_sha256": source_digest, "source_record_count": len(source)}
    expected = {item["path"] for item in inventory}
    if set(reported) != expected:
        raise CutoverEvidenceError("reconciliation report does not account for every discovered legacy store")
    return [reported[path] for path in sorted(reported)]


def build_receipt(*, state_dir: Path, participants: Any, reconciliation: Any, actor: str) -> dict[str, Any]:
    """Build a receipt only after a real, non-empty target has been reconciled."""
    if not isinstance(actor, str) or not actor.strip():
        raise CutoverEvidenceError("cutover actor is required")
    cutoff = datetime.now(timezone.utc)
    participant_list = _participants(participants)
    inventory = discover_legacy_stores(participant_list)
    if any(item["mtime_ns"] > int(cutoff.timestamp() * 1_000_000_000) for item in inventory):
        raise CutoverEvidenceError("legacy store changed during reconciliation inventory")
    report = _reconciliation(reconciliation, inventory, state_dir / _LEGACY_DB)
    target = inspect_target(state_dir / _LEGACY_DB)
    host, user = __import__("platform").node().strip(), str(os.getuid())
    derived_epoch = _derived_epoch(host, user, participant_list, inventory, report, target["identity"])
    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA, "scope": "same-user-same-host",
        "host_id": host, "user_id": user,
        "actor": actor.strip(), "reconciliation_epoch": derived_epoch,
        "reconciled_at": cutoff.isoformat(),
        "participants": participant_list, "legacy_store_inventory": inventory,
        "reconciliation": report, "target_store": target,
    }
    payload["inventory_sha256"] = hashlib.sha256(_canonical(inventory)).hexdigest()
    payload["reconciliation_sha256"] = hashlib.sha256(_canonical(report)).hexdigest()
    # A producer must not stamp evidence from a snapshot that has already
    # drifted while source records were being inspected.  Re-run both source
    # discovery and reconciliation immediately before the sole write.
    final_inventory = discover_legacy_stores(participant_list)
    final_report = _reconciliation(reconciliation, final_inventory, state_dir / _LEGACY_DB)
    if final_inventory != inventory or final_report != report:
        raise CutoverEvidenceError("legacy store inventory drifted during reconciliation")
    evidence_digest = hashlib.sha256(_canonical(_evidence_projection(payload))).hexdigest()
    _stamp_target(state_dir / _LEGACY_DB, {"identity": target["identity"], "epoch": derived_epoch, "evidence_sha256": evidence_digest})
    payload["target_store"] = inspect_target(state_dir / _LEGACY_DB)
    payload["receipt_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def write_receipt(state_dir: Path, receipt: Mapping[str, Any]) -> Path:
    path = state_dir / "host-store-cutover-v1.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_canonical(dict(receipt)))
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def validate_receipt(state_dir: Path, payload: Any, *, host_id: str, user_id: str) -> None:
    """Recompute all producer bindings before a SQLite connection can be opened."""
    if not isinstance(payload, Mapping):
        raise CutoverEvidenceError("cutover receipt is not an object")
    try:
        receipt = dict(payload)
        signature = receipt.pop("receipt_sha256")
        if not isinstance(signature, str) or hashlib.sha256(_canonical(receipt)).hexdigest() != signature:
            raise CutoverEvidenceError("cutover receipt integrity binding is invalid")
        if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("scope") != "same-user-same-host":
            raise CutoverEvidenceError("cutover receipt schema is invalid")
        if receipt.get("host_id") != host_id or receipt.get("user_id") != user_id:
            raise CutoverEvidenceError("cutover receipt host/user binding is invalid")
        epoch = receipt.get("reconciliation_epoch")
        UUID(epoch)
        reconciled_at = _utc(str(receipt["reconciled_at"]))
        if reconciled_at > datetime.now(timezone.utc):
            raise CutoverEvidenceError("cutover receipt is stale or future-dated")
        participants = _participants(receipt.get("participants"))
        cwd = Path.cwd().resolve()
        roots = [Path(item["root"]) for item in participants]
        if sum(cwd == root or root in cwd.parents for root in roots) != 1:
            raise CutoverEvidenceError("current working directory is outside the participant inventory")
        inventory = discover_legacy_stores(participants)
        if inventory != receipt.get("legacy_store_inventory") or hashlib.sha256(_canonical(inventory)).hexdigest() != receipt.get("inventory_sha256"):
            raise CutoverEvidenceError("cutover receipt inventory is incomplete or stale")
        report = _reconciliation(receipt.get("reconciliation"), inventory, state_dir / _LEGACY_DB)
        if report != receipt.get("reconciliation") or hashlib.sha256(_canonical(report)).hexdigest() != receipt.get("reconciliation_sha256"):
            raise CutoverEvidenceError("cutover receipt reconciliation binding is invalid")
        target = inspect_target(state_dir / _LEGACY_DB)
        recorded_target = receipt.get("target_store")
        if not isinstance(recorded_target, Mapping) or recorded_target.get("path") != target["path"] or target["identity"] != recorded_target.get("identity") or target.get("marker") != recorded_target.get("marker") or target["record_count"] < int(recorded_target.get("record_count", 1)):
            raise CutoverEvidenceError("cutover target store is empty, changed, or unaccounted")
        marker = json.loads(str(target["marker"]))
        expected_epoch = _derived_epoch(host_id, user_id, participants, inventory, report, target["identity"])
        expected_digest = hashlib.sha256(_canonical(_evidence_projection(receipt))).hexdigest()
        if marker.get("identity") != target["identity"] or marker.get("epoch") != epoch or epoch != expected_epoch or marker.get("evidence_sha256") != expected_digest:
            raise CutoverEvidenceError("cutover target marker does not bind this receipt epoch")
        if any(item["mtime_ns"] > int(reconciled_at.timestamp() * 1_000_000_000) for item in inventory):
            raise CutoverEvidenceError("legacy store was written after reconciliation epoch")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, CutoverEvidenceError):
            raise
        raise CutoverEvidenceError("cutover receipt is malformed") from exc
