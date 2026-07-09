"""File-first Builder Ops Vault helpers with shared advisory TTL claim signals."""

from __future__ import annotations

import json
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
    claims = root / ".builderops" / "claims"
    claims.mkdir(parents=True, exist_ok=True)
    return {"root": str(root), "statuses": list(STATUSES), "advisory_claims_root": str(claims)}


def vault_paths(paths: BuilderOpsPaths) -> dict[str, Any]:
    return {
        "shared_vault_root": str(paths.vault_root) if paths.vault_root else None,
        "local_db_path": str(paths.db_path),
        "advisory_claims_root": str(paths.vault_root / ".builderops" / "claims") if paths.vault_root else None,
        "claims_scope": "shared TTL advisory coordination only; no distributed lock guarantee",
    }


def validate_vault(root: Path, paths: BuilderOpsPaths) -> dict[str, Any]:
    root = root.expanduser()
    errors: list[str] = []
    forbidden = [root / "builderops.sqlite3"]
    for path in forbidden:
        if path.exists():
            errors.append(f"forbidden local operational state in shared vault: {path}")
    tickets: list[Ticket] = []
    for status in STATUSES:
        for path in sorted((root / "agent-delivery" / status).glob("*.md")):
            try:
                ticket = read_ticket(path)
                if ticket.meta.get("status") != status:
                    errors.append(f"{path}: folder status {status!r} does not match YAML status {ticket.meta.get('status')!r}")
                tickets.append(ticket)
            except VaultQueueError as exc:
                errors.append(str(exc))
    claims = _claim_summary(root / ".builderops" / "claims")
    return {"ok": not errors, "ticket_count": len(tickets), "errors": errors, "advisory_claims": claims, "claims_advisory": True}


def claim_ticket(root: Path, ticket_ref: str, *, agent: str, paths: BuilderOpsPaths, ttl_minutes: int, takeover_stale: bool = False) -> dict[str, Any]:
    ticket = resolve_ticket(root, ticket_ref)
    if ticket.meta.get("status") != "Ready":
        raise VaultQueueError(f"ticket {ticket.ticket_id} is not Ready")
    if ttl_minutes <= 0:
        raise VaultQueueError("ttl-minutes must be positive")
    claim_path = root.expanduser() / ".builderops" / "claims" / f"{ticket.ticket_id}-{_safe_agent(agent)}-{uuid.uuid4().hex}.json"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    claim = {"ticket_id": ticket.ticket_id, "agent": agent, "claimed_at": _stamp(now), "expires_at": _stamp(now + timedelta(minutes=ttl_minutes))}
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text(json.dumps(claim, sort_keys=True) + "\n", encoding="utf-8")
    return {"ticket": {"id": ticket.ticket_id, "path": str(ticket.path)}, "claim": claim, "claim_path": str(claim_path), "claim_scope": "shared-advisory"}


def release_ticket(root: Path, ticket_ref: str, *, agent: str, paths: BuilderOpsPaths) -> dict[str, Any]:
    ticket = resolve_ticket(root, ticket_ref)
    claims_root = root.expanduser() / ".builderops" / "claims"
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
    directory = root.expanduser() / "agent-delivery" / status
    return [read_ticket(path) for path in sorted(directory.glob("*.md"))] if directory.exists() else []


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
    return Ticket(path=path, meta=meta, body=parts[2])


def _read_claim(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultQueueError(f"invalid local claim state: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("expires_at"), str):
        raise VaultQueueError(f"invalid local claim state: {path}")
    return data


def _claim_summary(root: Path) -> dict[str, Any]:
    active = []
    now = _now()
    for path in sorted(root.glob("*.json")) if root.exists() else []:
        claim = _read_claim(path)
        active.append({"ticket_id": claim.get("ticket_id"), "agent": claim.get("agent"), "stale": _parse_stamp(claim["expires_at"]) <= now})
    return {"root": str(root), "claims": active}


def _safe_agent(agent: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", agent).strip("-") or "agent"
