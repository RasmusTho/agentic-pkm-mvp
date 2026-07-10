"""File-first Builder Ops Vault queue.

The vault contract is intentionally small: one ticket is one Markdown file with
flat YAML frontmatter, status is represented by both folder and frontmatter, and
transient claims live under ``.builderops/claims``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from collections.abc import Iterator

import fcntl


STATUSES = ("Backlog", "Ready", "In Progress", "Review", "Blocked", "Done")
STATUS_BY_NORMALIZED = {s.lower().replace(" ", "_"): s for s in STATUSES}
DEFAULT_TTL_MINUTES = 120
SAFE_TICKET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "med": 2, "low": 3}
REQUIRED_TICKET_FIELDS = {
    "id",
    "title",
    "status",
    "github_issue",
    "github_pr",
    "priority",
    "agent_state",
    "owner",
    "labels",
    "updated_at",
}
DISPATCHER_STATUS_MAP = {
    "backlog": "Backlog",
    "ready": "Ready",
    "review": "Review",
    "blocked": "Blocked",
    "completed": "Done",
    "done": "Done",
}
AGENT_CONTRACT = """# Builder Ops Vault Agent Contract

This vault is the active Builder System work queue.

Rules:
- Do not use GitHub GraphQL.
- Do not use GitHub Project v2 automation.
- Do not use `gh project`.
- Treat Markdown files as the operational source of truth.
- One ticket equals one Markdown file.
- Status is represented by folder and YAML `status`; both must match.
- Use `.builderops/claims/*.json` for transient agent claims.
- Use `.builderops/locks/*.lock` for same-host mutation serialization only.
- Treat iCloud-synchronized claims as advisory across devices, not as distributed locks.
- Do not edit another agent's claimed ticket unless the claim is expired.
- Write receipts only for meaningful state changes.
- GitHub updates must use REST only.
- Temporary operations data must not be committed to the product repo.
"""


class VaultQueueError(ValueError):
    """Raised when the Builder Ops Vault contract is violated."""


@dataclass(frozen=True)
class Ticket:
    path: Path
    body: str
    meta: dict[str, Any]

    @property
    def ticket_id(self) -> str:
        return str(self.meta.get("id") or self.path.stem)

    @property
    def status(self) -> str:
        return normalize_status(str(self.meta.get("status") or ""))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise VaultQueueError(f"invalid timestamp: {value}") from exc


def normalize_status(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "claimed":
        return "In Progress"
    if normalized == "done":
        return "Done"
    status = STATUS_BY_NORMALIZED.get(normalized)
    if status is None:
        raise VaultQueueError(f"unknown status {value!r}; expected one of: {', '.join(STATUSES)}")
    return status


def init_vault(root: Path) -> dict[str, Any]:
    root = root.expanduser()
    for status in STATUSES:
        (root / "agent-delivery" / status).mkdir(parents=True, exist_ok=True)
    (root / ".builderops" / "claims").mkdir(parents=True, exist_ok=True)
    (root / ".builderops" / "locks").mkdir(parents=True, exist_ok=True)
    (root / ".builderops" / "receipts").mkdir(parents=True, exist_ok=True)
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text(AGENT_CONTRACT, encoding="utf-8")
    return {"root": str(root), "statuses": list(STATUSES), "agents_contract": str(agents)}


def validate_vault(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    root = root.expanduser()
    errors: list[str] = []
    tickets: list[Ticket] = []
    agents_contract = root / "AGENTS.md"
    if not agents_contract.is_file():
        errors.append(f"{root}: missing AGENTS.md vault contract")
    elif "# Builder Ops Vault Agent Contract" not in agents_contract.read_text(encoding="utf-8"):
        errors.append(f"{agents_contract}: invalid Builder Ops Vault agent contract")
    for status in STATUSES:
        status_dir = root / "agent-delivery" / status
        if not status_dir.is_dir():
            errors.append(f"{status_dir}: missing status directory")
    if not claims_dir(root).is_dir():
        errors.append(f"{claims_dir(root)}: missing claims directory")
    if not locks_dir(root).is_dir():
        errors.append(f"{locks_dir(root)}: missing locks directory")
    for path in ticket_paths(root):
        try:
            tickets.append(read_ticket(path))
        except VaultQueueError as exc:
            errors.append(str(exc))
    seen_ids: dict[str, Path] = {}
    for ticket in tickets:
        missing_fields = sorted(REQUIRED_TICKET_FIELDS - ticket.meta.keys())
        if missing_fields:
            errors.append(f"{ticket.path}: missing required fields: {', '.join(missing_fields)}")
        expected = normalize_status(ticket.path.parent.name)
        try:
            actual = ticket.status
        except VaultQueueError as exc:
            errors.append(f"{ticket.path}: {exc}")
            continue
        if actual != expected:
            errors.append(
                f"{ticket.path}: folder status {expected!r} does not match YAML status {actual!r}"
            )
        previous = seen_ids.get(ticket.ticket_id)
        if previous is not None:
            errors.append(f"duplicate ticket id {ticket.ticket_id!r}: {previous} and {ticket.path}")
        if not SAFE_TICKET_ID.fullmatch(ticket.ticket_id):
            errors.append(
                f"{ticket.path}: unsafe ticket id {ticket.ticket_id!r}; "
                "use letters, digits, dot, underscore, or hyphen"
            )
        priority = str(ticket.meta.get("priority") or "").strip().lower()
        if priority not in PRIORITY_RANK:
            errors.append(f"{ticket.path}: unknown priority {priority!r}")
        if not isinstance(ticket.meta.get("labels"), list):
            errors.append(f"{ticket.path}: labels must be a flat list")
        try:
            parse_ts(str(ticket.meta.get("updated_at") or ""))
        except VaultQueueError as exc:
            errors.append(f"{ticket.path}: {exc}")
        seen_ids[ticket.ticket_id] = ticket.path

    now = now or utc_now()
    active_claims = []
    stale_claims = []
    for claim_path in claims_dir(root).glob("*.json"):
        try:
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            ticket_id = str(claim["ticket_id"])
            agent = str(claim["agent"]).strip()
            claimed_at = parse_ts(str(claim["claimed_at"]))
            expires_at = parse_ts(str(claim.get("expires_at")))
            if not agent:
                raise VaultQueueError("claim agent is empty")
            if claimed_at >= expires_at:
                raise VaultQueueError("claim expiry must be after claimed_at")
            if claim_path != claim_path_for_id(root, ticket_id):
                raise VaultQueueError("claim filename does not match ticket_id")
            ticket_path = seen_ids.get(ticket_id)
            if ticket_path is None:
                raise VaultQueueError(f"claim references unknown ticket {ticket_id!r}")
        except (KeyError, OSError, json.JSONDecodeError, VaultQueueError) as exc:
            errors.append(f"{claim_path}: invalid claim file ({exc})")
            continue
        item = {"path": str(claim_path), **claim}
        if expires_at <= now:
            stale_claims.append(item)
        else:
            active_claims.append(item)
            ticket = next(item for item in tickets if item.ticket_id == ticket_id)
            if ticket.meta.get("agent_state") != "Claimed" or ticket.meta.get("owner") != agent:
                errors.append(f"{claim_path}: active claim does not match ticket owner/agent_state")

    return {
        "ok": not errors,
        "ticket_count": len(tickets),
        "active_claims": active_claims,
        "stale_claims": stale_claims,
        "errors": errors,
    }


def next_ticket(root: Path, *, now: datetime | None = None) -> Ticket | None:
    now = now or utc_now()
    for ticket in sorted(tickets_in_status(root, "Ready"), key=ticket_queue_key):
        claim = read_claim(root, ticket.ticket_id)
        if claim is None or parse_ts(str(claim["expires_at"])) <= now:
            return ticket
    return None


def ticket_queue_key(ticket: Ticket) -> tuple[int, str]:
    priority = str(ticket.meta.get("priority") or "").strip().lower()
    return (PRIORITY_RANK.get(priority, len(PRIORITY_RANK)), str(ticket.path))


def import_dispatcher_tasks(
    root: Path,
    tasks: Iterable[Mapping[str, Any]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.expanduser()
    validation = validate_vault(root)
    if not validation["ok"]:
        raise VaultQueueError("vault must validate before dispatcher import")
    existing_tickets = list_tickets(root)
    existing_ids = {ticket.ticket_id for ticket in existing_tickets}
    existing_issues = {
        str(ticket.meta.get("github_issue"))
        for ticket in existing_tickets
        if ticket.meta.get("github_issue") not in {None, ""}
    }
    planned: list[Ticket] = []
    skipped: list[dict[str, str]] = []
    for task in tasks:
        task_id = str(task.get("task_id") or "").strip()
        issue_number = str(task.get("issue_number") or "").strip()
        status = str(task.get("status") or "").strip().lower().replace(" ", "_")
        if not task_id or not issue_number:
            skipped.append({"task_id": task_id, "reason": "missing task_id or issue_number"})
            continue
        try:
            require_safe_ticket_id(task_id)
        except VaultQueueError as exc:
            skipped.append({"task_id": task_id, "reason": str(exc)})
            continue
        if task_id in existing_ids or issue_number in existing_issues:
            skipped.append({"task_id": task_id, "reason": "vault ticket already exists"})
            continue
        if status in {"claimed", "in_progress"}:
            skipped.append(
                {
                    "task_id": task_id,
                    "reason": "active dispatcher work must be released or completed before import",
                }
            )
            continue
        vault_status = DISPATCHER_STATUS_MAP.get(status)
        if vault_status is None:
            skipped.append({"task_id": task_id, "reason": f"unsupported status {status!r}"})
            continue
        priority = str(task.get("priority") or "medium").strip().lower()
        if priority not in PRIORITY_RANK:
            skipped.append({"task_id": task_id, "reason": f"unsupported priority {priority!r}"})
            continue
        sync_state = task.get("sync_state")
        raw_labels = sync_state.get("labels", []) if isinstance(sync_state, Mapping) else []
        labels = [str(label) for label in raw_labels] if isinstance(raw_labels, list) else []
        updated_at = str(task.get("updated_at") or "")
        try:
            parse_ts(updated_at)
        except VaultQueueError as exc:
            skipped.append({"task_id": task_id, "reason": str(exc)})
            continue
        title = str(task.get("title") or task_id)
        source_refs = [str(ref) for ref in (task.get("source_anchor_refs") or [])]
        body_lines = [f"# {title}", "", f"GitHub Issue: #{issue_number}"]
        if source_refs:
            body_lines.extend(["", "## Source Anchors", "", *[f"- {ref}" for ref in source_refs]])
        body_lines.extend(["", "## Receipts", ""])
        ticket = ticket_with_updates_and_receipts(
            Ticket(
                path=root / "agent-delivery" / vault_status / f"{task_id}.md",
                meta={
                    "id": task_id,
                    "title": title,
                    "status": vault_status,
                    "github_issue": int(issue_number) if issue_number.isdigit() else issue_number,
                    "github_pr": task.get("linked_pr") or "",
                    "priority": priority,
                    "agent_state": "Idle",
                    "owner": "",
                    "labels": labels,
                    "updated_at": updated_at,
                },
                body="\n".join(body_lines),
            ),
            {},
            ["imported from dispatcher transition store"],
        )
        planned.append(ticket)
        existing_ids.add(task_id)
        existing_issues.add(issue_number)

    if apply:
        for ticket in planned:
            write_ticket(ticket)
    return {
        "apply": apply,
        "imported": [ticket_payload(ticket) for ticket in planned] if apply else [],
        "planned": [ticket_payload(ticket) for ticket in planned],
        "skipped": skipped,
    }


def claim_ticket(
    root: Path,
    ticket_ref: str,
    *,
    agent: str,
    session: str | None = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    now: datetime | None = None,
    takeover_stale: bool = False,
) -> dict[str, Any]:
    now = now or utc_now()
    agent = agent.strip()
    if not agent:
        raise VaultQueueError("agent must not be empty")
    if ttl_minutes <= 0:
        raise VaultQueueError("ttl_minutes must be greater than zero")
    initial = resolve_ticket(root, ticket_ref)
    require_safe_ticket_id(initial.ticket_id)
    with ticket_lock(root, initial.ticket_id):
        ticket = resolve_ticket(root, initial.ticket_id)
        existing = read_claim(root, ticket.ticket_id)
        if existing is not None:
            expires_at = parse_ts(str(existing["expires_at"]))
            if expires_at > now:
                raise VaultQueueError(
                    f"ticket {ticket.ticket_id} is already claimed by {existing.get('agent')}"
                )
            if not takeover_stale:
                raise VaultQueueError(
                    f"ticket {ticket.ticket_id} has stale claim; pass --takeover-stale to claim"
                )
            if ticket.status not in {"Ready", "In Progress"}:
                raise VaultQueueError(
                    f"ticket {ticket.ticket_id} is {ticket.status!r}; stale takeover requires "
                    "Ready or In Progress"
                )
            claim_path(root, ticket.ticket_id).unlink()
        elif ticket.status != "Ready":
            raise VaultQueueError(
                f"ticket {ticket.ticket_id} is {ticket.status!r}; only Ready tickets can be claimed"
            )

        acquired = now
        expires = acquired + timedelta(minutes=ttl_minutes)
        claim = {
            "ticket_id": ticket.ticket_id,
            "agent": agent,
            "claimed_at": format_ts(acquired),
            "expires_at": format_ts(expires),
            "session": session or "",
        }
        write_claim_atomic(root, ticket.ticket_id, claim)
        takeover_receipt = ""
        if existing is not None:
            takeover_receipt = (
                f"stale claim takeover by {agent}; previous claim expired {existing['expires_at']}"
            )
        updated = ticket_with_updates_and_receipts(
            ticket,
            {
                "status": "In Progress",
                "agent_state": "Claimed",
                "owner": agent,
                "updated_at": format_ts(acquired),
            },
            [
                line
                for line in (
                    takeover_receipt,
                    f"claimed by {agent}; expires {format_ts(expires)}",
                )
                if line
            ],
            now=acquired,
            path=root.expanduser() / "agent-delivery" / "In Progress" / ticket.path.name,
        )
        try:
            updated = write_ticket(updated)
            if ticket.path != updated.path and ticket.path.exists():
                ticket.path.unlink()
        except Exception:
            claim_path(root, ticket.ticket_id).unlink(missing_ok=True)
            raise
        return {"ticket": ticket_payload(updated), "claim": claim}


def move_ticket(root: Path, ticket_ref: str, status: str, *, actor: str) -> dict[str, Any]:
    initial = resolve_ticket(root, ticket_ref)
    with ticket_lock(root, initial.ticket_id):
        ticket = resolve_ticket(root, initial.ticket_id)
        ensure_mutation_allowed(root, ticket, actor=actor)
        next_status = normalize_status(status)
        target_dir = root.expanduser() / "agent-delivery" / next_status
        target_dir.mkdir(parents=True, exist_ok=True)
        next_path = target_dir / ticket.path.name
        releases_claim = next_status in {"Backlog", "Ready", "Blocked", "Done"}
        receipts = [f"moved to {next_status} by {actor}"]
        if releases_claim and read_claim(root, ticket.ticket_id) is not None:
            receipts.append(f"claim released by {actor} on transition to {next_status}")
        updated = ticket_with_updates_and_receipts(
            ticket,
            {
                "status": next_status,
                "agent_state": "Idle" if releases_claim else ticket.meta.get("agent_state", "Idle"),
                "owner": "" if releases_claim else ticket.meta.get("owner", ""),
                "updated_at": format_ts(utc_now()),
            },
            receipts,
            path=next_path,
        )
        updated = write_ticket(updated)
        if ticket.path != next_path and ticket.path.exists():
            ticket.path.unlink()
        if releases_claim:
            claim_path(root, ticket.ticket_id).unlink(missing_ok=True)
        return {"ticket": ticket_payload(updated)}


def renew_ticket(
    root: Path,
    ticket_ref: str,
    *,
    agent: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    agent = agent.strip()
    if not agent:
        raise VaultQueueError("agent must not be empty")
    if ttl_minutes <= 0:
        raise VaultQueueError("ttl_minutes must be greater than zero")
    initial = resolve_ticket(root, ticket_ref)
    with ticket_lock(root, initial.ticket_id):
        ticket = resolve_ticket(root, initial.ticket_id)
        claim = read_claim(root, ticket.ticket_id)
        if claim is None:
            raise VaultQueueError(f"ticket {ticket.ticket_id} has no claim")
        if claim.get("agent") != agent:
            raise VaultQueueError(
                f"ticket {ticket.ticket_id} is claimed by {claim.get('agent')}, not {agent}"
            )
        expires_at = parse_ts(str(claim.get("expires_at")))
        if expires_at <= now:
            raise VaultQueueError(
                f"ticket {ticket.ticket_id} claim expired; use claim --takeover-stale"
            )
        renewed = dict(claim)
        renewed["expires_at"] = format_ts(now + timedelta(minutes=ttl_minutes))
        write_claim_replace(root, ticket.ticket_id, renewed)
        return {"ticket": ticket_payload(ticket), "claim": renewed}


def note_ticket(root: Path, ticket_ref: str, note: str, *, actor: str) -> dict[str, Any]:
    initial = resolve_ticket(root, ticket_ref)
    with ticket_lock(root, initial.ticket_id):
        ticket = resolve_ticket(root, initial.ticket_id)
        ensure_mutation_allowed(root, ticket, actor=actor)
        if not note.strip():
            raise VaultQueueError("note must not be empty")
        now = utc_now()
        updated = write_ticket(
            ticket_with_updates_and_receipts(
                ticket,
                {"updated_at": format_ts(now)},
                [f"note by {actor}: {note}"],
                now=now,
            )
        )
        return {"ticket": ticket_payload(updated)}


def release_ticket(root: Path, ticket_ref: str, *, agent: str) -> dict[str, Any]:
    initial = resolve_ticket(root, ticket_ref)
    with ticket_lock(root, initial.ticket_id):
        ticket = resolve_ticket(root, initial.ticket_id)
        claim = read_claim(root, ticket.ticket_id)
        if claim is None:
            raise VaultQueueError(f"ticket {ticket.ticket_id} has no claim")
        if claim.get("agent") != agent:
            raise VaultQueueError(
                f"ticket {ticket.ticket_id} is claimed by {claim.get('agent')}, not {agent}"
            )
        updated = ticket_with_updates_and_receipts(
            ticket,
            {"agent_state": "Idle", "owner": "", "updated_at": format_ts(utc_now())},
            [f"released by {agent}"],
        )
        updated = write_ticket(updated)
        claim_path(root, ticket.ticket_id).unlink()
        return {"ticket": ticket_payload(updated)}


def list_tickets(root: Path) -> list[Ticket]:
    return [read_ticket(path) for path in ticket_paths(root)]


def ticket_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    board = root.expanduser() / "agent-delivery"
    for status in STATUSES:
        status_dir = board / status
        if not status_dir.exists():
            continue
        for path in sorted(status_dir.glob("*.md")):
            paths.append(path)
    return paths


def tickets_in_status(root: Path, status: str) -> list[Ticket]:
    status = normalize_status(status)
    return [
        read_ticket(path) for path in (root.expanduser() / "agent-delivery" / status).glob("*.md")
    ]


def resolve_ticket(root: Path, ticket_ref: str) -> Ticket:
    matches = [
        ticket
        for ticket in list_tickets(root)
        if ticket.ticket_id == ticket_ref
        or ticket.path.stem == ticket_ref
        or str(ticket.meta.get("github_issue") or "") == ticket_ref.lstrip("#")
    ]
    if not matches:
        raise VaultQueueError(f"ticket not found: {ticket_ref}")
    if len(matches) > 1:
        raise VaultQueueError(f"ambiguous ticket ref {ticket_ref!r}")
    return matches[0]


def read_ticket(path: Path) -> Ticket:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VaultQueueError(f"cannot read ticket {path}: {exc}") from exc
    if not text.startswith("---\n"):
        raise VaultQueueError(f"{path} is missing YAML frontmatter")
    try:
        _start, yaml_text, body = text.split("---\n", 2)
    except ValueError as exc:
        raise VaultQueueError(f"{path} has malformed YAML frontmatter") from exc
    return Ticket(path=path, meta=parse_frontmatter(yaml_text), body=body.lstrip("\n"))


def write_ticket(ticket: Ticket, *, path: Path | None = None) -> Ticket:
    path = path or ticket.path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(render_ticket(ticket.meta, ticket.body), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return Ticket(path=path, meta=dict(ticket.meta), body=ticket.body)


def ticket_with_updates_and_receipts(
    ticket: Ticket,
    updates: dict[str, Any],
    receipts: list[str],
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> Ticket:
    meta = dict(ticket.meta)
    meta.update(updates)
    body = ticket.body.rstrip()
    stamp = format_ts(now or utc_now())
    if receipts and "## Receipts" not in body:
        body = f"{body}\n\n## Receipts\n"
    for line in receipts:
        body = f"{body}\n- {stamp} - {line}"
    return Ticket(path=path or ticket.path, meta=meta, body=f"{body}\n")


def parse_frontmatter(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise VaultQueueError(f"unsupported frontmatter line: {raw!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = parse_value(value.strip())
    return meta


def parse_value(value: str) -> Any:
    if value == "":
        return ""
    if value in {"[]", "[ ]"}:
        return []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed_list = json.loads(value)
        except json.JSONDecodeError:
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [parse_value(part.strip()) for part in inner.split(",")]
        if not isinstance(parsed_list, list):
            raise VaultQueueError(f"unsupported frontmatter list: {value!r}")
        return parsed_list
    if value.startswith('"') and value.endswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise VaultQueueError(f"invalid quoted frontmatter value: {value!r}") from exc
        if not isinstance(parsed, str):
            raise VaultQueueError(f"unsupported quoted frontmatter value: {value!r}")
        return parsed
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.isdigit():
        return int(value)
    return value


def render_ticket(meta: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key in sorted(meta):
        lines.append(f"{key}: {render_value(meta[key])}")
    lines.extend(["---", "", body.lstrip("\n").rstrip(), ""])
    return "\n".join(lines)


def render_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(render_value(v) for v in value) + "]"
    if value is None:
        return '""'
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def ticket_payload(ticket: Ticket) -> dict[str, Any]:
    return {"path": str(ticket.path), "meta": ticket.meta}


def claims_dir(root: Path) -> Path:
    return root.expanduser() / ".builderops" / "claims"


def locks_dir(root: Path) -> Path:
    return root.expanduser() / ".builderops" / "locks"


@contextmanager
def ticket_lock(root: Path, ticket_id: str) -> Iterator[None]:
    require_safe_ticket_id(ticket_id)
    directory = locks_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ticket_id}.lock"
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def claim_path(root: Path, ticket_id: str) -> Path:
    require_safe_ticket_id(ticket_id)
    return claim_path_for_id(root, ticket_id)


def claim_path_for_id(root: Path, ticket_id: str) -> Path:
    return claims_dir(root) / f"{ticket_id}.json"


def require_safe_ticket_id(ticket_id: str) -> None:
    if not SAFE_TICKET_ID.fullmatch(ticket_id):
        raise VaultQueueError(
            f"unsafe ticket id {ticket_id!r}; use letters, digits, dot, underscore, or hyphen"
        )


def read_claim(root: Path, ticket_id: str) -> dict[str, Any] | None:
    path = claim_path(root, ticket_id)
    if not path.exists():
        return None
    try:
        claim = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultQueueError(f"invalid claim file {path}: {exc}") from exc
    if not isinstance(claim, dict):
        raise VaultQueueError(f"invalid claim file {path}: expected JSON object")
    missing = {"ticket_id", "agent", "claimed_at", "expires_at"} - claim.keys()
    if missing:
        raise VaultQueueError(f"invalid claim file {path}: missing {', '.join(sorted(missing))}")
    if str(claim["ticket_id"]) != ticket_id:
        raise VaultQueueError(f"invalid claim file {path}: ticket_id mismatch")
    if not str(claim["agent"]).strip():
        raise VaultQueueError(f"invalid claim file {path}: agent is empty")
    claimed_at = parse_ts(str(claim["claimed_at"]))
    expires_at = parse_ts(str(claim["expires_at"]))
    if claimed_at >= expires_at:
        raise VaultQueueError(f"invalid claim file {path}: expiry must be after claimed_at")
    return claim


def ensure_mutation_allowed(
    root: Path,
    ticket: Ticket,
    *,
    actor: str,
    now: datetime | None = None,
) -> None:
    actor = actor.strip()
    if not actor:
        raise VaultQueueError("actor must not be empty")
    claim = read_claim(root, ticket.ticket_id)
    if claim is None:
        return
    expires_at = parse_ts(str(claim.get("expires_at")))
    if expires_at > (now or utc_now()) and claim.get("agent") != actor:
        raise VaultQueueError(
            f"ticket {ticket.ticket_id} is claimed by {claim.get('agent')}, not {actor}"
        )


def write_claim_atomic(root: Path, ticket_id: str, claim: dict[str, Any]) -> None:
    path = claim_path(root, ticket_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(claim, indent=2, sort_keys=True) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise VaultQueueError(f"ticket {ticket_id} already has a claim") from exc
    finally:
        if tmp.exists():
            tmp.unlink()


def write_claim_replace(root: Path, ticket_id: str, claim: dict[str, Any]) -> None:
    path = claim_path(root, ticket_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(claim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
