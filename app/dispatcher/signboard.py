"""Signboard Markdown projection for dispatcher tasks.

**Legacy.** The dispatcher remains the operational source of truth, and since
#4401 the ``/signboard`` board is served directly from that store. This module
writes a one-way Markdown projection nothing in the product reads any more; it
is kept working for the builder hosts that still hold a board directory, behind
the ``export-signboard`` / ``signboard-validate`` operator commands. Physical
removal is a separate follow-up.

``STATUS_COLUMNS`` and ``canonical_status`` are *not* legacy: they are the single
source of the dispatcher's status/column vocabulary and the store-backed board
route derives its columns from them.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore
from app.vault.manager import get_vault_manager


# The Signboard export nests under the human's actively-selected vault so no
# CLI/automation caller ever has to type a manual path (dyslexia-friendly,
# no-manual-path-typing posture). This reuses the shipped Option 2
# active-vault-selection mechanism (``VaultManager`` / ``AppLocalSettingsStore``)
# rather than inventing a parallel "BuilderOps vault root" concept.
#
# This is the single source of the Signboard root default (#4198). The API
# route and the host launchers derive from ``default_signboard_root`` instead of
# carrying their own home-relative literal; three independent spellings of the
# same path is what let the board diverge in the first place.
DEFAULT_SIGNBOARD_SUBPATH = Path("BuilderOpsVault") / "agent-delivery"

_NOTES_HEADING = "## Notes"
_RECEIPTS_HEADING = "## Receipts"
_GENERATED_FILENAME_RE = re.compile(r".+--.+\.md$")

# A board records which dispatcher store owns it (#4370). The store resolves
# from the current working directory (``app/dispatcher/config.py ::
# load_paths`` -> ``_default_state_dir`` -> ``discover_primary_worktree``), so
# two checkouts of this repo on one host have two independent stores. Without
# this fact, ``--prune-absent`` reads "unknown to whichever store this process
# resolved" as "dead card": on 2026-07-29 it was run from the checkout that did
# not own the board and deleted 404 live cards.
#
# The stamp is a durable *identity*, never the store's path — a path is exactly
# the thing that cannot identify a store here, and a legitimate relocation must
# not read as a foreign store.
STORE_IDENTITY_META_KEY = "signboard_store_id"
STORE_STAMP_FILENAME = ".signboard-store.json"
STORE_STAMP_VERSION = 1


class NoActiveVaultError(RuntimeError):
    """Raised when a default Signboard export path is requested but no vault
    is currently selected via the active-vault-selection mechanism."""


class SignboardStoreOwnershipError(RuntimeError):
    """Raised when a destructive board operation cannot prove the board belongs
    to the dispatcher store this process resolved."""


def default_signboard_root() -> Path:
    """Resolve the default Signboard export root from the active vault.

    Reuses the existing shipped active-vault-selection mechanism
    (``app.vault.manager.get_vault_manager``) so callers never need to type a
    manual vault path. Raises :class:`NoActiveVaultError` when no vault is
    currently selected; callers should fall back to an explicit path or
    instruct the human to select a vault first.
    """

    manager = get_vault_manager()
    context = manager.context
    if context.status == "none":
        context = manager.load_last_active()
    if context.active_vault_path and context.status in {"selected", "uninitialized"}:
        return Path(context.active_vault_path).expanduser().resolve() / DEFAULT_SIGNBOARD_SUBPATH
    raise NoActiveVaultError(
        "no active vault is selected; pass an explicit path or select a vault first"
    )


STATUS_COLUMNS: dict[str, str] = {
    "backlog": "Backlog",
    "ready": "Ready",
    "claimed": "In Progress",
    "in_progress": "In Progress",
    "review": "Review",
    "blocked": "Blocked",
    "completed": "Done",
    "done": "Done",
}

VALID_STATUSES = frozenset(STATUS_COLUMNS.keys()) - {"done"}


def canonical_status(status: str) -> str:
    normalized = status.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized == "done":
        return "completed"
    if normalized not in VALID_STATUSES:
        allowed = ", ".join(sorted(VALID_STATUSES | {"done"}))
        raise ValueError(f"Unknown dispatcher status {status!r}; expected one of: {allowed}")
    return normalized


def column_for_status(status: str) -> str:
    normalized = canonical_status(status)
    return STATUS_COLUMNS.get(normalized, "Backlog")


def read_store_identity(store: SqliteStore) -> str | None:
    """Return the store's durable identity, or ``None`` when it has none yet.

    Read-only on purpose: ``validate_signboard`` must not write to the store,
    and a store that owns a stamped board necessarily already carries the
    identity that stamped it — so "no identity" is itself proof of non-ownership.
    """

    value = store.get_meta(STORE_IDENTITY_META_KEY)
    if value is None:
        return None
    return value.strip() or None


def resolve_store_identity(store: SqliteStore) -> str:
    """Return the store's durable identity, minting one on first use.

    The identity lives in the store's own metadata, so it travels with the
    store when the store moves and is never inherited by a different store.
    """

    existing = read_store_identity(store)
    if existing is not None:
        return existing
    minted = uuid.uuid4().hex
    store.set_meta(STORE_IDENTITY_META_KEY, minted)
    return minted


def read_board_store_id(board_root: Path) -> str | None:
    """Return the store id a board is stamped with, or ``None`` when unstamped.

    A stamp file that exists but cannot be read as a stamp also returns
    ``None``: every caller treats "cannot prove ownership" as "not owned", and
    the claim below keys on the file's *absence*, so a corrupted stamp keeps
    refusing until a human removes it instead of being silently re-claimed.
    """

    try:
        data = json.loads((Path(board_root) / STORE_STAMP_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    store_id = data.get("store_id")
    if not isinstance(store_id, str) or not store_id.strip():
        return None
    return store_id.strip()


def _claim_board_stamp(root: Path, store_id: str) -> None:
    """Stamp the board with its owning store, once.

    Written only when no stamp file exists at all. A board already stamped by
    another store is never re-stamped: a plain export must not become the way
    the prune guard gets defeated.
    """

    path = root / STORE_STAMP_FILENAME
    if path.exists():
        return
    path.write_text(
        json.dumps(
            {
                "generated_by": "dispatcher.signboard",
                "stamp_version": STORE_STAMP_VERSION,
                "store_id": store_id,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _board_has_generated_cards(root: Path) -> bool:
    if not root.is_dir():
        return False
    return any(_is_generated_card(path) for path in root.rglob("*.md"))


def _require_board_ownership(root: Path, store_id: str) -> None:
    """Refuse a destructive board operation this store cannot prove it owns."""

    board_store_id = read_board_store_id(root)
    if board_store_id == store_id:
        return
    if board_store_id is None:
        if not _board_has_generated_cards(root):
            # Nothing to lose: an unstamped board holding no generated cards
            # cannot be another store's board in any way a prune could harm,
            # so a first export may still prune in a single command.
            return
        raise SignboardStoreOwnershipError(
            f"board {root} carries no store-identity stamp but already holds generated cards; "
            "refusing to prune. Run 'export-signboard <path>' without --prune-absent from the "
            "checkout that owns this board to stamp it, then retry."
        )
    raise SignboardStoreOwnershipError(
        f"board {root} is stamped by dispatcher store {board_store_id!r}, but this process "
        f"resolved store {store_id!r}; refusing to prune. Cards absent from this store may "
        "simply belong to the other one — run the prune from the checkout that owns the board."
    )


def export_signboard(
    store: SqliteStore,
    board_root: Path,
    *,
    prune_absent: bool = False,
) -> dict[str, Any]:
    """Write dispatcher tasks as Markdown files grouped by kanban column.

    By default the exporter only removes prior generated files for task IDs
    that still exist in dispatcher, and it leaves unrelated human notes alone.
    That default leaves cards whose task ID has vanished from the store
    unreachable: ``signboard-validate`` reports them as ``stale_card`` and
    nothing could clear them, so the board grew monotonically (#4198).

    ``prune_absent`` is the opt-in repair for exactly those cards. It removes a
    generated card only when its task ID is absent from the store *and* the
    card carries no human-authored ``## Notes`` content; a stale card that does
    carry notes is kept and surfaced under ``retained_with_notes`` so a human
    decides its fate. Human material is never silently destroyed.

    A prune additionally requires that the board's store-identity stamp match
    this store (#4370). That check runs *before* anything is written or
    unlinked: the per-task cleanup below already unlinks stale generated cards
    of its own accord, so a refusal raised any later would not be total.
    """

    root = Path(board_root).expanduser()
    store_id = resolve_store_identity(store)
    if prune_absent:
        _require_board_ownership(root, store_id)

    root.mkdir(parents=True, exist_ok=True)
    for column in sorted(set(STATUS_COLUMNS.values())):
        (root / column).mkdir(parents=True, exist_ok=True)
    _claim_board_stamp(root, store_id)

    # Synchronization metadata is stored alongside tasks for dispatcher
    # compatibility, but it is not a user-facing Signboard card.
    tasks = [task for task in store.list_tasks() if task.status != "_meta"]
    written: list[str] = []
    for task in tasks:
        filename = _task_filename(task)
        target_column = column_for_status(task.status)
        target = root / target_column / filename

        # Preserve any human-authored content in the "## Notes" section of a
        # previously generated card for this task, wherever it currently
        # lives (the card may have moved columns/filenames since the last
        # export because status or title changed). The target's own existing
        # card, if any, is the freshest source; stale cards elsewhere are a
        # fallback so a rename/status-move doesn't drop notes.
        preserved_notes: str | None = None
        target_text = _read_card_text(target)
        if target_text is not None and _is_generated_card_text(target_text):
            preserved_notes = _extract_notes_section(target_text)

        for column in sorted(set(STATUS_COLUMNS.values())):
            for candidate in (root / column).glob(f"{task.task_id}--*.md"):
                if candidate == target:
                    continue
                candidate_text = _read_card_text(candidate)
                if candidate_text is not None and _is_generated_card_text(candidate_text):
                    if preserved_notes is None:
                        preserved_notes = _extract_notes_section(candidate_text)
                    candidate.unlink()

        # No further cleanup pass here: the glob above already unlinks every
        # stale *generated* card for this task_id (including one at this
        # exact filename in another column). A second pass keyed on filename
        # alone — without the _is_generated_card_text check — would delete a
        # non-generated file that happens to share the filename by
        # coincidence; that used to be a real bug, not defense in depth.

        target.write_text(_render_task(task, notes=preserved_notes), encoding="utf-8")
        written.append(str(target))

    pruned: list[str] = []
    retained_with_notes: list[str] = []
    if prune_absent:
        pruned, retained_with_notes = _prune_cards_absent_from_store(
            root,
            known_task_ids={task.task_id for task in tasks},
            expected_store_id=store_id,
        )

    return {
        "root": str(root),
        "store_id": store_id,
        "count": len(tasks),
        "columns": sorted(set(STATUS_COLUMNS.values())),
        "written": written,
        "pruned": pruned,
        "retained_with_notes": retained_with_notes,
    }


def _prune_cards_absent_from_store(
    root: Path, *, known_task_ids: set[str], expected_store_id: str
) -> tuple[list[str], list[str]]:
    """Remove empty generated cards whose task ID is gone from dispatcher.

    Returns ``(pruned, retained_with_notes)``. Malformed generated cards are
    left in place: ``signboard-validate`` already reports them under their own
    finding kind, and their task identity cannot be trusted for a delete.

    This is the deleting primitive, so it re-asserts board ownership itself
    rather than trusting its caller to have done it: "absent from the store" is
    only a fact about a card when the store is the one that owns the board.
    """

    _require_board_ownership(root, expected_store_id)

    pruned: list[str] = []
    retained_with_notes: list[str] = []
    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        text = _read_card_text(path)
        if text is None or not _is_generated_card_text(text):
            continue
        frontmatter = _parse_generated_frontmatter(text)
        if frontmatter is None or frontmatter["id"] in known_task_ids:
            continue
        if _has_human_authored_content(text):
            retained_with_notes.append(str(path))
            continue
        path.unlink()
        pruned.append(str(path))
    return pruned, retained_with_notes


def _has_human_authored_content(text: str) -> bool:
    """True when a generated card carries anything a human wrote into it.

    Both hand-editable sections count. ``## Notes`` is the documented one, and
    it is the only one re-export splices forward. ``## Receipts`` is the other
    section ``_render_task`` emits and always leaves empty, so any non-blank
    text below the generator's final heading is equally human-authored — and a
    stale card is precisely the case where re-export never touched it, so that
    text is still there. A prune must not be the thing that deletes it.
    """

    return (
        _extract_notes_section(text) is not None
        or _trailing_receipts_content(text) is not None
    )


def _trailing_receipts_content(text: str) -> str | None:
    """Return non-blank text below the card's final "## Receipts" heading."""

    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == _RECEIPTS_HEADING:
            start = index
    if start is None:
        return None
    trailing = "\n".join(lines[start + 1 :]).strip()
    return trailing or None


def validate_signboard(store: SqliteStore, board_root: Path) -> dict[str, Any]:
    """Return read-only findings for generated Signboard cards.

    Signboard is a derived projection. This intentionally never repairs cards
    or updates the dispatcher store; ``export-signboard`` remains the repair
    operation after a failing validation run — with ``--prune-absent`` when the
    findings include cards whose task ID no longer exists in the store.
    """
    root = Path(board_root).expanduser()
    tasks = {
        task.task_id: task
        for task in store.list_tasks()
        if task.status != "_meta"
    }
    findings: list[dict[str, str]] = []
    cards_by_task: dict[str, list[str]] = {}

    # Name a foreign-store comparison before the cards it explains (#4370).
    # Against someone else's board every card reads as ``stale_card``, and that
    # is the noise that hid the 2026-07-29 incident: 378 of 405 findings, each
    # individually true and collectively the wrong conclusion.
    board_store_id = read_board_store_id(root)
    foreign_store = board_store_id is not None and board_store_id != read_store_identity(store)
    if foreign_store:
        findings.append({
            "kind": "store_stamp_mismatch",
            "path": STORE_STAMP_FILENAME,
            "detail": (
                f"board is stamped by dispatcher store {board_store_id!r}, which is not the "
                "store this process resolved; cards reported below as absent from the store "
                "may simply belong to the other one"
            ),
        })

    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        relative_path = str(path.relative_to(root))
        text = _read_card_text(path)
        if text is None:
            if _GENERATED_FILENAME_RE.fullmatch(path.name):
                findings.append({
                    "kind": "unreadable_generated_card_candidate",
                    "path": relative_path,
                    "detail": "generated filename candidate could not be read",
                })
            continue
        if not _is_generated_card_text(text):
            continue

        frontmatter = _parse_generated_frontmatter(text)
        if frontmatter is None:
            findings.append({
                "kind": "malformed_generated_card",
                "path": relative_path,
                "detail": "generated card frontmatter is missing or invalid",
            })
            continue

        task_id = frontmatter["id"]
        status = frontmatter["status"]
        expected_column = column_for_status(status)
        actual_column = path.parent.name
        cards_by_task.setdefault(task_id, []).append(relative_path)
        if actual_column != expected_column or frontmatter["column"] != expected_column:
            findings.append({
                "kind": "column_status_mismatch",
                "path": relative_path,
                "detail": (
                    f"status {status!r} belongs in {expected_column!r}; "
                    f"card column is {actual_column!r} and frontmatter column is "
                    f"{frontmatter['column']!r}"
                ),
            })

        task = tasks.get(task_id)
        if task is None:
            findings.append({
                "kind": "stale_card",
                "path": relative_path,
                "detail": f"task {task_id!r} is absent from the dispatcher store",
            })
        elif actual_column != column_for_status(task.status):
            findings.append({
                "kind": "stale_card",
                "path": relative_path,
                "detail": (
                    f"task {task_id!r} now belongs in "
                    f"{column_for_status(task.status)!r}"
                ),
            })

    for task_id, paths in cards_by_task.items():
        if len(paths) > 1:
            findings.append({
                "kind": "duplicate_card",
                "path": ", ".join(paths),
                "detail": f"task {task_id!r} has {len(paths)} generated cards",
            })

    result: dict[str, Any] = {"root": str(root), "count": len(tasks), "findings": findings}
    if foreign_store:
        # Never name the prune here: on a foreign board that repair is the
        # command that destroys it (#4370).
        result["repair"] = (
            "this board belongs to another dispatcher store; run export-signboard from the "
            "checkout that owns it. Do not prune from here."
        )
    elif any(finding["kind"] == "stale_card" for finding in findings):
        # Name the repair in the lint output itself. A finding an operator
        # cannot act on is the bug this replaces (#4198).
        result["repair"] = "python -m app.dispatcher export-signboard [path] --prune-absent"
    return result


def _parse_generated_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the minimal generated-card schema without accepting loose YAML."""
    if not text.startswith("---\n"):
        return None
    try:
        _, raw_frontmatter, _ = text.split("---\n", 2)
        data = yaml.safe_load(raw_frontmatter)
    except (ValueError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None

    task_id = data.get("id")
    issue_number = data.get("issue_number")
    status = data.get("status")
    column = data.get("column")
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    if not isinstance(issue_number, int) or isinstance(issue_number, bool):
        return None
    if not isinstance(status, str) or not status.strip():
        return None
    if not isinstance(column, str) or not column.strip():
        return None
    try:
        canonical = canonical_status(status)
    except ValueError:
        return None
    return {"id": task_id, "status": canonical, "column": column}


def _task_filename(task: TaskRecord) -> str:
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", task.title.strip()).strip("-")
    title = title[:72].strip("-") or "task"
    return f"{task.task_id}--{title}.md"


def _read_card_text(path: Path) -> str | None:
    """Read a card's text, tolerating a missing/unreadable file (returns None)."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _is_generated_card_text(text: str) -> bool:
    return "generated_by: dispatcher.signboard" in text


def _is_generated_card(path: Path) -> bool:
    text = _read_card_text(path)
    return text is not None and _is_generated_card_text(text)


def _extract_notes_section(text: str) -> str | None:
    """Return the human-authored body of a card's "## Notes" section, if any.

    The section runs from just below the "## Notes" heading up to (but not
    including) the *last* "## Receipts" heading in the file — the only other
    heading ``_render_task`` ever generates, and always the final line of
    generated structure (nothing follows it but a trailing blank line). Using
    the last occurrence rather than the first means a human quoting the
    literal text "## Receipts" earlier in their own notes does not get
    mistaken for the real boundary; only the generator's actual trailing
    heading does. Returns ``None`` when there is no "## Notes" heading or the
    section is blank, so callers can fall back to the default stub.
    """

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _NOTES_HEADING)
    except StopIteration:
        return None

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == _RECEIPTS_HEADING:
            end = i

    section_lines = lines[start + 1 : end]
    while section_lines and section_lines[0] == "":
        section_lines.pop(0)
    while section_lines and section_lines[-1] == "":
        section_lines.pop()

    if not section_lines:
        return None
    return "\n".join(section_lines)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_yaml_scalar(v) for v in values) + "]"


def _render_task(task: TaskRecord, *, notes: str | None = None) -> str:
    source_refs = list(task.source_anchor_refs or [])
    github_url = ""
    labels: list[str] = []
    if task.sync_state:
        github_url = str(task.sync_state.get("url") or "")
        raw_labels = task.sync_state.get("labels") or []
        if isinstance(raw_labels, list):
            labels = [str(label) for label in raw_labels]

    frontmatter = [
        "---",
        "generated_by: dispatcher.signboard",
        f"id: {_yaml_scalar(task.task_id)}",
        f"issue_number: {task.issue_number}",
        f"title: {_yaml_scalar(task.title)}",
        f"status: {_yaml_scalar(canonical_status(task.status))}",
        f"column: {_yaml_scalar(column_for_status(task.status))}",
        f"priority: {_yaml_scalar(task.priority)}",
        f"repo: {_yaml_scalar(task.repo)}",
        f"claimed_by: {_yaml_scalar(task.claimed_by)}",
        f"linked_pr: {_yaml_scalar(task.linked_pr)}",
        f"blocked_reason: {_yaml_scalar(task.blocked_reason)}",
        f"github_url: {_yaml_scalar(github_url)}",
        f"labels: {_yaml_list(labels)}",
        f"source_anchor_refs: {_yaml_list(source_refs)}",
        f"updated_at: {_yaml_scalar(task.updated_at)}",
        "---",
        "",
    ]

    body = [
        f"# {task.title}",
        "",
        f"- Task: `{task.task_id}`",
        f"- Issue: `#{task.issue_number}`",
        f"- Status: `{canonical_status(task.status)}`",
        f"- Priority: `{task.priority}`",
    ]
    if task.repo:
        body.append(f"- Repo: `{task.repo}`")
    if task.claimed_by:
        body.append(f"- Claimed by: `{task.claimed_by}`")
    if task.linked_pr:
        body.append(f"- PR: `#{task.linked_pr}`")
    if task.blocked_reason:
        body.append(f"- Blocked: {task.blocked_reason}")
    if github_url:
        body.append(f"- GitHub: {github_url}")
    if source_refs:
        body.append(f"- Source anchors: {', '.join(source_refs)}")
    body.extend(["", _NOTES_HEADING, ""])
    if notes:
        body.extend([notes, ""])
    body.extend(["## Receipts", ""])
    return "\n".join(frontmatter + body)
