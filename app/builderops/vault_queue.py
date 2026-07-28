"""File-first Builder Ops Vault helpers with shared advisory TTL claim signals."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.builderops.config import BuilderOpsPaths

STATUSES = ("Backlog", "Ready", "In Progress", "Review", "Blocked", "Done")
STATUS_COLUMNS = {
    "backlog": "Backlog",
    "ready": "Ready",
    "claimed": "In Progress",
    "in_progress": "In Progress",
    "review": "Review",
    "blocked": "Blocked",
    "completed": "Done",
    "done": "Done",
}


class VaultQueueError(ValueError):
    pass


@dataclass(frozen=True)
class Ticket:
    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def ticket_id(self) -> str:
        return str(self.meta["id"])

    @property
    def status_column(self) -> str:
        return _ticket_status_column(self.meta)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone offset required")
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise VaultQueueError(f"invalid claim timestamp: {value}") from exc


def init_vault(root: Path) -> dict[str, Any]:
    root = root.expanduser()
    _trusted_vault_root(root)
    root.mkdir(parents=True, exist_ok=True)
    vault_root = _trusted_vault_root(root).resolve(strict=True)
    delivery = root / "agent-delivery"
    _prepare_directory(delivery, vault_root, label="agent-delivery root")
    for status in STATUSES:
        _prepare_directory(delivery / status, vault_root, label="ticket status directory")
    claims = _claims_root(root, create=True)
    return {"root": str(root), "statuses": list(STATUSES), "advisory_claims_root": str(claims)}


def vault_paths(paths: BuilderOpsPaths) -> dict[str, Any]:
    return {
        "shared_vault_root": str(paths.vault_root) if paths.vault_root else None,
        "local_db_path": str(paths.db_path),
        "advisory_claims_root": str(paths.vault_root / ".builderops" / "claims") if paths.vault_root else None,
        "claims_scope": "shared TTL advisory coordination only; no distributed lock guarantee",
    }


def validate_vault(
    root: Path,
    paths: BuilderOpsPaths,
    *,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, Any]:
    requested_root = root.expanduser()
    errors: list[str] = []
    sqlite_scan: dict[str, int] = {"files": 0, "opened": 0, "skipped_remote": 0, "elapsed_ms": 0}
    try:
        root = _trusted_vault_root(requested_root)
    except VaultQueueError as exc:
        message = str(exc)
        return {
            "ok": False,
            "ticket_count": 0,
            "errors": [message],
            "advisory_claims": {
                "root": str(requested_root / ".builderops" / "claims"),
                "claims": [],
                "errors": [message],
            },
            "claims_advisory": True,
            "sqlite_scan": sqlite_scan,
        }
    configured_root = None
    if paths.vault_root is not None:
        try:
            configured_root = _trusted_vault_root(paths.vault_root)
        except VaultQueueError as exc:
            errors.append(str(exc))
    if configured_root is not None and configured_root != root:
        errors.append(
            f"validated root {root} does not match BUILDEROPS_VAULT_ROOT {configured_root}"
        )
    configured_db = paths.db_path.resolve(strict=False)
    if configured_db == root or root in configured_db.parents:
        errors.append(f"configured SQLite path is inside shared vault: {configured_db}")
    try:
        found, sqlite_scan = _scan_sqlite_candidates(root, on_progress=on_progress)
        for path in found:
            errors.append(f"forbidden SQLite state in shared vault: {path}")
    except VaultQueueError as exc:
        errors.append(str(exc))
    tickets: list[Ticket] = []
    for status in STATUSES:
        try:
            ticket_paths = _ticket_paths(root, status)
        except VaultQueueError as exc:
            errors.append(str(exc))
            continue
        for path in ticket_paths:
            try:
                ticket = read_ticket(path)
                if ticket.status_column != status:
                    errors.append(
                        f"{path}: folder status {status!r} does not match "
                        f"YAML status {ticket.meta.get('status')!r}"
                    )
                tickets.append(ticket)
            except VaultQueueError as exc:
                errors.append(str(exc))
    try:
        claims_root = _claims_root(root, create=False)
        claims = _claim_summary(claims_root)
        errors.extend(claims["errors"])
    except VaultQueueError as exc:
        errors.append(str(exc))
        claims = {"root": str(root / ".builderops" / "claims"), "claims": [], "errors": [str(exc)]}
    return {
        "ok": not errors,
        "ticket_count": len(tickets),
        "errors": errors,
        "advisory_claims": claims,
        "claims_advisory": True,
        "sqlite_scan": sqlite_scan,
    }


def claim_ticket(
    root: Path,
    ticket_ref: str,
    *,
    agent: str,
    ttl_minutes: int,
) -> dict[str, Any]:
    agent = agent.strip()
    if not agent:
        raise VaultQueueError("agent must be non-empty")
    ticket = resolve_ticket(root, ticket_ref)
    if ticket.path.parent.name != "Ready" or ticket.status_column != "Ready":
        raise VaultQueueError(f"ticket {ticket.ticket_id} is not Ready")
    if ttl_minutes <= 0:
        raise VaultQueueError("ttl-minutes must be positive")
    claims_root = _claims_root(root, create=True)
    claim_path = claims_root / f"{ticket.ticket_id}-{_safe_agent(agent)}-{uuid.uuid4().hex}.json"
    now = _now()
    claim = {"ticket_id": ticket.ticket_id, "agent": agent, "claimed_at": _stamp(now), "expires_at": _stamp(now + timedelta(minutes=ttl_minutes))}
    temp_path = claims_root / f".{claim_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temp_path.write_text(json.dumps(claim, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_path, claim_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return {"ticket": {"id": ticket.ticket_id, "path": str(ticket.path)}, "claim": claim, "claim_path": str(claim_path), "claim_scope": "shared-advisory"}


def release_ticket(root: Path, ticket_ref: str, *, agent: str) -> dict[str, Any]:
    agent = agent.strip()
    if not agent:
        raise VaultQueueError("agent must be non-empty")
    ticket = resolve_ticket(root, ticket_ref)
    claims_root = _claims_root(root, create=False)
    own_claims = []
    for path in claims_root.glob("*.json"):
        claim = _read_claim(path)
        if claim["ticket_id"] == ticket.ticket_id and claim["agent"] == agent:
            own_claims.append(path)
    if not own_claims:
        raise VaultQueueError(f"ticket {ticket.ticket_id} has no advisory claim by {agent}")
    for claim_path in own_claims:
        claim_path.unlink()
    return {"ticket": {"id": ticket.ticket_id}, "released": True, "claim_scope": "shared-advisory"}


def resolve_ticket(root: Path, ticket_ref: str) -> Ticket:
    matches = [ticket for status in STATUSES for ticket in _tickets(root, status) if ticket.ticket_id == ticket_ref or ticket.path.stem == ticket_ref]
    if len(matches) != 1:
        raise VaultQueueError(f"ticket not found or ambiguous: {ticket_ref}")
    return matches[0]


def _tickets(root: Path, status: str) -> list[Ticket]:
    return [read_ticket(path) for path in _ticket_paths(root, status)]


def _ticket_paths(root: Path, status: str) -> list[Path]:
    vault_root = _trusted_vault_root(root)
    delivery = root.expanduser() / "agent-delivery"
    if delivery.is_symlink():
        raise VaultQueueError(f"agent-delivery root must not be a symlink: {delivery}")
    delivery_resolved = delivery.resolve(strict=False)
    _require_within_vault(delivery_resolved, vault_root, label="agent-delivery root")
    directory = delivery / status
    if directory.is_symlink():
        raise VaultQueueError(f"ticket status directory must not be a symlink: {directory}")
    resolved = directory.resolve(strict=False)
    _require_within_vault(resolved, vault_root, label="ticket status directory")
    paths = sorted(resolved.glob("*.md")) if resolved.exists() else []
    for path in paths:
        if path.is_symlink():
            raise VaultQueueError(f"ticket file must not be a symlink: {path}")
        _require_within_vault(path.resolve(strict=True), vault_root, label="ticket file")
    return paths


def read_ticket(path: Path) -> Ticket:
    if path.is_symlink():
        raise VaultQueueError(f"ticket file must not be a symlink: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VaultQueueError(f"unable to read ticket: {path}") from exc
    if not text.startswith("---\n"):
        raise VaultQueueError(f"{path}: missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise VaultQueueError(f"{path}: malformed YAML frontmatter")
    try:
        meta = yaml.load(parts[1], Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise VaultQueueError(f"{path}: malformed YAML frontmatter") from exc
    if not isinstance(meta, dict):
        raise VaultQueueError(f"{path}: YAML frontmatter must be a mapping")
    ticket_id = meta.get("id")
    if not isinstance(ticket_id, str) or not ticket_id.strip():
        raise VaultQueueError(f"{path}: ticket id must be a non-empty string")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ticket_id):
        raise VaultQueueError(f"{path}: unsafe ticket id {ticket_id!r}")
    _ticket_status_column(meta)
    return Ticket(path=path, meta=meta, body=parts[2])


def _read_claim(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise VaultQueueError(f"advisory claim file must not be a symlink: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VaultQueueError(f"invalid advisory claim state: {path}") from exc
    required = ("ticket_id", "agent", "claimed_at", "expires_at")
    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in required
    ):
        raise VaultQueueError(f"invalid advisory claim state: {path}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", data["ticket_id"]):
        raise VaultQueueError(f"invalid advisory claim state: {path}")
    try:
        claimed_at = _parse_stamp(data["claimed_at"])
        expires_at = _parse_stamp(data["expires_at"])
    except VaultQueueError as exc:
        raise VaultQueueError(f"invalid advisory claim state: {path}: {exc}") from exc
    if expires_at <= claimed_at:
        raise VaultQueueError(f"invalid advisory claim time window: {path}")
    return data


def _claim_summary(root: Path) -> dict[str, Any]:
    active = []
    errors = []
    now = _now()
    for path in sorted(root.glob("*.json")) if root.exists() else []:
        try:
            claim = _read_claim(path)
            active.append({"ticket_id": claim.get("ticket_id"), "agent": claim.get("agent"), "stale": _parse_stamp(claim["expires_at"]) <= now})
        except VaultQueueError as exc:
            errors.append(str(exc))
    return {"root": str(root), "claims": active, "errors": errors}


def _safe_agent(agent: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", agent).strip("-") or "agent"


def _claims_root(root: Path, *, create: bool) -> Path:
    expanded_root = root.expanduser()
    vault_root = _trusted_vault_root(expanded_root)
    builderops_root = expanded_root / ".builderops"
    if builderops_root.is_symlink():
        raise VaultQueueError(f"BuilderOps state root must not be a symlink: {builderops_root}")
    builderops_resolved = builderops_root.resolve(strict=False)
    _require_within_vault(builderops_resolved, vault_root, label="BuilderOps state root")
    requested = expanded_root / ".builderops" / "claims"
    if requested.is_symlink():
        raise VaultQueueError(f"advisory claims root must not be a symlink: {requested}")
    resolved = requested.resolve(strict=False)
    _require_within_vault(resolved, vault_root, label="advisory claims root")
    if create:
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink():
            raise VaultQueueError(f"advisory claims root must not be a symlink: {requested}")
        resolved = requested.resolve(strict=False)
        _require_within_vault(resolved, vault_root, label="advisory claims root")
    return resolved


def _require_within_vault(candidate: Path, vault_root: Path, *, label: str) -> None:
    if candidate == vault_root or vault_root not in candidate.parents:
        raise VaultQueueError(f"{label} escapes shared vault: {candidate}")


_SQLITE_HEADER_MAGIC = b"SQLite format 3\x00"
_SQLITE_EXTENSIONS = frozenset({".db", ".db3", ".sqlite", ".sqlite3"})

# The smallest page size the SQLite file format allows. Every database image is
# a whole number of pages, and every legal page size (512..65536, powers of two)
# is a multiple of this, so a database image's size is always a non-zero
# multiple of 512 bytes.
_SQLITE_PAGE_UNIT = 512

# macOS `st_flags` bit marking a file whose metadata is local but whose content
# is not — an iCloud Drive "dataless" file. Reading one byte of it triggers an
# on-demand materialization over the network.
_SF_DATALESS = 0x40000000


def _content_is_local(stat_result: os.stat_result) -> bool:
    """True when the file's bytes are already on this disk.

    A synchronized vault (iCloud Drive) evicts file *contents* while keeping
    metadata local. Opening such a file costs a network round-trip — measured
    at ~1.0-1.2 s per file, which is what made `vault validate` fail to
    terminate on the real shared vault (#4199). ``SF_DATALESS`` is the direct
    macOS signal; zero allocated blocks against a non-zero logical size is the
    portable fallback for the same state.
    """

    if getattr(stat_result, "st_flags", 0) & _SF_DATALESS:
        return False
    return not (stat_result.st_size > 0 and getattr(stat_result, "st_blocks", 1) == 0)


def _may_be_sqlite_image(size: int) -> bool:
    """True when ``size`` is consistent with a SQLite database image.

    Used only to decide whether materializing an evicted file is worth it. It
    can never hide a real database: a SQLite image is always a whole number of
    pages, so its size is always a non-zero multiple of 512. What it does skip
    is an evicted file that merely *starts* with the magic bytes without being
    a database image — which is not the thing the confinement invariant exists
    to catch, and which is still sniffed whenever the content is local.
    """

    return size >= _SQLITE_PAGE_UNIT and size % _SQLITE_PAGE_UNIT == 0


def _sqlite_candidates(root: Path) -> list[Path]:
    """Return every file in the vault that is (or could be) a SQLite database."""

    return _scan_sqlite_candidates(root)[0]


def _scan_sqlite_candidates(
    root: Path,
    *,
    on_progress: Callable[[dict[str, int]], None] | None = None,
) -> tuple[list[Path], dict[str, int]]:
    """Scan for SQLite candidates and report what the scan actually did.

    Files whose content is already local are sniffed exactly as before: full
    header check, no narrowing. The only change is that an *evicted* file is
    materialized solely when its size is consistent with a database image, so a
    synchronized vault no longer costs one network round-trip per Markdown
    note. Symlink rejection is unchanged and still happens before any read.
    """

    started = time.monotonic()
    stats = {"files": 0, "opened": 0, "skipped_remote": 0, "elapsed_ms": 0}
    root = _trusted_vault_root(root)
    if not root.exists():
        return [], stats
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise VaultQueueError(f"vault entry must not be a symlink: {path}")
        try:
            stat_result = path.stat()
        except OSError:
            # ``Path.is_file()`` swallowed this before the stat-first rewrite;
            # keep that tolerance so an entry that vanishes mid-walk (a live
            # synchronized vault) is skipped rather than failing validation.
            continue
        if not stat.S_ISREG(stat_result.st_mode):
            continue
        stats["files"] += 1
        if on_progress is not None:
            on_progress(dict(stats))
        if path.suffix.lower() in _SQLITE_EXTENSIONS:
            candidates.append(path)
            continue
        if not _content_is_local(stat_result) and not _may_be_sqlite_image(stat_result.st_size):
            stats["skipped_remote"] += 1
            continue
        stats["opened"] += 1
        try:
            with path.open("rb") as handle:
                header = handle.read(16)
        except OSError as exc:
            raise VaultQueueError(f"unable to inspect vault file: {path}") from exc
        if header == _SQLITE_HEADER_MAGIC:
            candidates.append(path)
    stats["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return candidates, stats


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _ticket_status_column(meta: dict[str, Any]) -> str:
    if any(not isinstance(key, str) for key in meta):
        raise VaultQueueError("ticket frontmatter keys must be strings")
    raw_status = meta.get("status")
    if not isinstance(raw_status, str) or not raw_status.strip():
        raise VaultQueueError("ticket status must be a non-empty string")
    normalized = raw_status.strip().lower().replace(" ", "_").replace("-", "_")
    column = STATUS_COLUMNS.get(normalized)
    if column is None:
        raise VaultQueueError(f"unknown ticket status: {raw_status!r}")
    raw_column = meta.get("column")
    if raw_column is not None:
        if not isinstance(raw_column, str) or raw_column not in STATUSES:
            raise VaultQueueError(f"unknown ticket column: {raw_column!r}")
        if raw_column != column:
            raise VaultQueueError(
                f"ticket status {raw_status!r} does not match column {raw_column!r}"
            )
    return column


def _prepare_directory(path: Path, vault_root: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise VaultQueueError(f"{label} must not be a symlink: {path}")
    path.mkdir(parents=False, exist_ok=True)
    if path.is_symlink():
        raise VaultQueueError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve(strict=True)
    _require_within_vault(resolved, vault_root, label=label)
    return resolved


def _trusted_vault_root(root: Path) -> Path:
    expanded = Path(root).expanduser()
    if expanded.is_symlink():
        raise VaultQueueError(f"shared vault root must not be a symlink: {expanded}")
    absolute = expanded.absolute()
    for ancestor in absolute.parents:
        if ancestor.is_symlink():
            raise VaultQueueError(
                f"shared vault path ancestor must not be a symlink: {ancestor}"
            )
    return expanded.resolve(strict=False)
