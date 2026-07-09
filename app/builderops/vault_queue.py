"""File-first Builder Ops Vault helpers with shared advisory TTL claim signals."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.builderops.config import BuilderOpsPaths

STATUSES = ("Backlog", "Ready", "In Progress", "Review", "Blocked", "Done")


class VaultQueueError(ValueError):
    pass


@dataclass(frozen=True)
class Ticket:
    path: Path
    meta: dict[str, str]
    body: str

    @property
    def ticket_id(self) -> str:
        return self.meta.get("id", self.path.stem)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise VaultQueueError(f"invalid claim timestamp: {value}") from exc


def init_vault(root: Path) -> dict[str, Any]:
    root = root.expanduser()
    for status in STATUSES:
        (root / "agent-delivery" / status).mkdir(parents=True, exist_ok=True)
    claims = _claims_root(root, create=True)
    return {"root": str(root), "statuses": list(STATUSES), "advisory_claims_root": str(claims)}


def vault_paths(paths: BuilderOpsPaths) -> dict[str, Any]:
    return {
        "shared_vault_root": str(paths.vault_root) if paths.vault_root else None,
        "local_db_path": str(paths.db_path),
        "advisory_claims_root": str(paths.vault_root / ".builderops" / "claims") if paths.vault_root else None,
        "claims_scope": "shared TTL advisory coordination only; no distributed lock guarantee",
    }


def validate_vault(root: Path, paths: BuilderOpsPaths) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=False)
    errors: list[str] = []
    configured_root = paths.vault_root.resolve(strict=False) if paths.vault_root else None
    if configured_root is not None and configured_root != root:
        errors.append(
            f"validated root {root} does not match BUILDEROPS_VAULT_ROOT {configured_root}"
        )
    configured_db = paths.db_path.resolve(strict=False)
    if configured_db == root or root in configured_db.parents:
        errors.append(f"configured SQLite path is inside shared vault: {configured_db}")
    for path in _sqlite_candidates(root):
        errors.append(f"forbidden SQLite state in shared vault: {path}")
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
                if ticket.meta.get("status") != status:
                    errors.append(f"{path}: folder status {status!r} does not match YAML status {ticket.meta.get('status')!r}")
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
    return {"ok": not errors, "ticket_count": len(tickets), "errors": errors, "advisory_claims": claims, "claims_advisory": True}


def claim_ticket(
    root: Path,
    ticket_ref: str,
    *,
    agent: str,
    ttl_minutes: int,
) -> dict[str, Any]:
    ticket = resolve_ticket(root, ticket_ref)
    if ticket.path.parent.name != "Ready" or ticket.meta.get("status") != "Ready":
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
    ticket = resolve_ticket(root, ticket_ref)
    claims_root = _claims_root(root, create=False)
    own_claims = [path for path in claims_root.glob(f"{ticket.ticket_id}-{_safe_agent(agent)}-*.json") if _read_claim(path).get("agent") == agent]
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
    vault_root = root.expanduser().resolve(strict=False)
    directory = root.expanduser() / "agent-delivery" / status
    if directory.is_symlink():
        raise VaultQueueError(f"ticket status directory must not be a symlink: {directory}")
    resolved = directory.resolve(strict=False)
    _require_within_vault(resolved, vault_root, label="ticket status directory")
    return sorted(resolved.glob("*.md")) if resolved.exists() else []


def read_ticket(path: Path) -> Ticket:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise VaultQueueError(f"{path}: missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise VaultQueueError(f"{path}: malformed YAML frontmatter")
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if line.strip() and ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    ticket_id = meta.get("id", path.stem)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ticket_id):
        raise VaultQueueError(f"{path}: unsafe ticket id {ticket_id!r}")
    return Ticket(path=path, meta=meta, body=parts[2])


def _read_claim(path: Path) -> dict[str, str]:
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
    _parse_stamp(data["claimed_at"])
    _parse_stamp(data["expires_at"])
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
    vault_root = root.expanduser().resolve(strict=False)
    builderops_root = root.expanduser() / ".builderops"
    if builderops_root.is_symlink():
        raise VaultQueueError(f"BuilderOps state root must not be a symlink: {builderops_root}")
    builderops_resolved = builderops_root.resolve(strict=False)
    _require_within_vault(builderops_resolved, vault_root, label="BuilderOps state root")
    requested = root.expanduser() / ".builderops" / "claims"
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


def _sqlite_candidates(root: Path) -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".db", ".db3", ".sqlite", ".sqlite3"}:
            candidates.append(path)
            continue
        try:
            with path.open("rb") as handle:
                header = handle.read(16)
            if header == b"SQLite format 3\x00":
                candidates.append(path)
        except OSError as exc:
            raise VaultQueueError(f"unable to inspect vault file: {path}") from exc
    return candidates
