"""Local persistent run-state for deliver-issue-set epic runs."""

from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback for local tooling.
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = 1
DEFAULT_EPIC_RUNS_DIR = Path("runtime/builderops/epic-runs")
TERMINAL_LEARNING_EVALUATION_OUTCOMES = (
    "applied",
    "already_satisfied",
    "issue_created",
    "promotion_pending",
    "debt_or_fitness_recorded",
    "discarded_or_superseded",
)

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_LIST_FIELDS = (
    "child_queue",
    "learning_evaluation_candidates",
    "review_findings",
    "reusable_constraints",
    "follow_ups",
    "stop_conditions",
    "dispatch_decisions",
    "compact_receipts",
)
_MERGE_MAPPING_FIELDS = (
    "issue_mappings",
    "validation_status",
)
_REPLACE_MAPPING_FIELDS = ("dispatcher_status",)
_STATE_FIELDS = (
    "schema_version",
    "epic_issue_number",
    "run_id",
    *_LIST_FIELDS,
    *_MERGE_MAPPING_FIELDS,
    *_REPLACE_MAPPING_FIELDS,
    "last_verified_head_sha",
)
_UPDATE_FIELDS = (
    *_LIST_FIELDS,
    *_MERGE_MAPPING_FIELDS,
    *_REPLACE_MAPPING_FIELDS,
    "last_verified_head_sha",
)
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.Lock] = {}


class EpicRunStateError(ValueError):
    """Raised when epic run-state input is invalid or unsafe."""


def validate_run_id(run_id: str) -> str:
    """Return a filesystem-safe run id for local JSON state files."""

    if not isinstance(run_id, str) or not run_id.strip():
        raise EpicRunStateError("run_id must be a non-empty string")
    normalized = run_id.strip()
    if not _RUN_ID_PATTERN.fullmatch(normalized):
        raise EpicRunStateError(
            "run_id must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return normalized


def epic_run_state_path(run_id: str, *, root: Path | str | None = None) -> Path:
    """Resolve the local JSON path for a run id without allowing traversal."""

    safe_run_id = validate_run_id(run_id)
    base = Path(root).expanduser() if root is not None else DEFAULT_EPIC_RUNS_DIR
    target = base / f"{safe_run_id}.json"

    base_resolved = base.resolve(strict=False)
    target_resolved = target.resolve(strict=False)
    if not _is_relative_to(target_resolved, base_resolved):
        raise EpicRunStateError("run-state path must stay under the epic runs root")
    return target


def new_epic_run_state(
    epic_issue_number: int,
    run_id: str,
    **updates: Any,
) -> dict[str, Any]:
    """Build a normalized in-memory state envelope for an epic run."""

    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "epic_issue_number": _normalize_epic_issue_number(epic_issue_number),
        "run_id": validate_run_id(run_id),
        "child_queue": [],
        "learning_evaluation_candidates": [],
        "issue_mappings": {},
        "validation_status": {},
        "review_findings": [],
        "reusable_constraints": [],
        "follow_ups": [],
        "stop_conditions": [],
        "dispatch_decisions": [],
        "dispatcher_status": {},
        "compact_receipts": [],
        "last_verified_head_sha": None,
    }
    if updates:
        return apply_epic_run_update(state, **updates)
    return normalize_epic_run_state(state)


def create_epic_run_state(
    epic_issue_number: int,
    run_id: str,
    *,
    root: Path | str | None = None,
    overwrite: bool = False,
    **updates: Any,
) -> dict[str, Any]:
    """Create or idempotently load a local epic run-state file."""

    path = epic_run_state_path(run_id, root=root)
    with _locked_run_state(path):
        if path.exists() and not overwrite:
            existing = deserialize_epic_run_state(path.read_text(encoding="utf-8"))
            expected_epic = _normalize_epic_issue_number(epic_issue_number)
            if existing["epic_issue_number"] != expected_epic:
                raise EpicRunStateError(
                    f"run_id {run_id!r} already belongs to epic "
                    f"{existing['epic_issue_number']}"
                )
            if updates:
                existing = apply_epic_run_update(existing, **updates)
                save_epic_run_state(existing, root=root)
            return existing

        state = new_epic_run_state(epic_issue_number, run_id, **updates)
        save_epic_run_state(state, root=root)
        return state


def load_epic_run_state(
    run_id: str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Load and normalize a local epic run-state file."""

    path = epic_run_state_path(run_id, root=root)
    return deserialize_epic_run_state(path.read_text(encoding="utf-8"))


def save_epic_run_state(
    state: Mapping[str, Any],
    *,
    root: Path | str | None = None,
) -> Path:
    """Persist a state envelope with deterministic JSON serialization."""

    normalized = normalize_epic_run_state(state)
    path = epic_run_state_path(normalized["run_id"], root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(serialize_epic_run_state(normalized), encoding="utf-8")
    tmp_path.replace(path)
    return path


def update_epic_run_state(
    run_id: str,
    *,
    root: Path | str | None = None,
    updater: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
    **updates: Any,
) -> dict[str, Any]:
    """Load, update, persist, and return a local epic run-state file."""

    path = epic_run_state_path(run_id, root=root)
    with _locked_run_state(path):
        state = deserialize_epic_run_state(path.read_text(encoding="utf-8"))
        if updater is not None:
            state = normalize_epic_run_state(updater(_json_clone(state)))
        if updates:
            state = apply_epic_run_update(state, **updates)
        save_epic_run_state(state, root=root)
        return state


def apply_epic_run_update(state: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    """Apply idempotent run-state updates to an in-memory state envelope."""

    normalized = normalize_epic_run_state(state)
    unknown = sorted(set(updates) - set(_UPDATE_FIELDS))
    if unknown:
        raise EpicRunStateError(f"unknown run-state update field(s): {unknown}")

    for field in _LIST_FIELDS:
        if field in updates and updates[field] is not None:
            normalized[field] = _merge_json_list(
                normalized[field],
                _normalize_list(updates[field], field),
            )

    for field in _MERGE_MAPPING_FIELDS:
        if field in updates and updates[field] is not None:
            normalized[field] = _merge_json_mapping(
                normalized[field],
                _normalize_mapping(updates[field], field),
            )

    for field in _REPLACE_MAPPING_FIELDS:
        if field in updates and updates[field] is not None:
            normalized[field] = _normalize_mapping(updates[field], field)

    if "last_verified_head_sha" in updates:
        normalized["last_verified_head_sha"] = _normalize_optional_string(
            updates["last_verified_head_sha"],
            "last_verified_head_sha",
        )

    return normalize_epic_run_state(normalized)


def record_dispatcher_status(
    state: Mapping[str, Any],
    dispatcher_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Record a dispatcher status snapshot without importing or changing dispatcher."""

    return apply_epic_run_update(state, dispatcher_status=dispatcher_status)


def unresolved_learning_evaluation_candidates(
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return run-state learning/evaluation candidates without terminal outcomes."""

    normalized = normalize_epic_run_state(state)
    return [
        _json_clone(candidate)
        for candidate in normalized["learning_evaluation_candidates"]
        if not _candidate_has_terminal_outcome(candidate)
    ]


def assert_learning_evaluation_candidates_terminal(
    state: Mapping[str, Any],
) -> None:
    """Fail when any learning/evaluation candidate lacks a terminal outcome."""

    unresolved = unresolved_learning_evaluation_candidates(state)
    if unresolved:
        identifiers = ", ".join(_candidate_display_id(item) for item in unresolved)
        raise EpicRunStateError(
            "learning/evaluation candidate(s) lack terminal outcome: "
            f"{identifiers}"
        )


def serialize_epic_run_state(state: Mapping[str, Any]) -> str:
    """Serialize state deterministically for compact local receipts and diffs."""

    return _pretty_dumps(normalize_epic_run_state(state))


def deserialize_epic_run_state(raw: str) -> dict[str, Any]:
    """Parse and normalize a serialized epic run-state envelope."""

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EpicRunStateError(f"invalid run-state JSON: {exc}") from exc
    return normalize_epic_run_state(decoded)


def normalize_epic_run_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and validate the top-level epic run-state envelope."""

    if not isinstance(state, Mapping):
        raise EpicRunStateError("run-state must be a JSON object")
    raw = _json_clone(dict(state))

    unknown = sorted(set(raw) - set(_STATE_FIELDS))
    if unknown:
        raise EpicRunStateError(f"unknown run-state field(s): {unknown}")

    schema_version = raw.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise EpicRunStateError(
            f"unsupported epic run-state schema_version: {schema_version!r}"
        )

    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "epic_issue_number": _normalize_epic_issue_number(
            raw.get("epic_issue_number")
        ),
        "run_id": validate_run_id(raw.get("run_id")),
        "last_verified_head_sha": _normalize_optional_string(
            raw.get("last_verified_head_sha"),
            "last_verified_head_sha",
        ),
    }

    for field in _LIST_FIELDS:
        if field == "learning_evaluation_candidates":
            normalized[field] = _normalize_learning_evaluation_candidates(
                raw.get(field, []),
                field,
            )
        else:
            normalized[field] = _normalize_list(raw.get(field, []), field)
    for field in (*_MERGE_MAPPING_FIELDS, *_REPLACE_MAPPING_FIELDS):
        normalized[field] = _normalize_mapping(raw.get(field, {}), field)

    return {field: normalized[field] for field in _STATE_FIELDS}


def _normalize_epic_issue_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpicRunStateError("epic_issue_number must be a positive integer")
    return value


def _normalize_optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpicRunStateError(f"{field} must be a non-empty string or null")
    return value.strip()


def _normalize_required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpicRunStateError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise EpicRunStateError(f"{field} must be a list")
    return _json_clone(value)


def _normalize_learning_evaluation_candidates(
    value: Any,
    field: str,
) -> list[dict[str, Any]]:
    items = _normalize_list(value, field)
    return [
        _normalize_learning_evaluation_candidate(item, f"{field}[{index}]")
        for index, item in enumerate(items)
    ]


def _normalize_learning_evaluation_candidate(
    value: Any,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EpicRunStateError(f"{field} must be an object")
    candidate = _json_clone(value)

    for required in ("source_refs", "upstream_artifact_hint", "evidence_kind"):
        if required not in candidate:
            raise EpicRunStateError(f"{field}.{required} is required")

    source_refs = candidate["source_refs"]
    if not isinstance(source_refs, list) or not source_refs:
        raise EpicRunStateError(f"{field}.source_refs must be a non-empty list")

    for required in ("upstream_artifact_hint", "evidence_kind"):
        candidate[required] = _normalize_required_string(
            candidate[required],
            f"{field}.{required}",
        )

    outcome = candidate.get("outcome")
    if outcome is not None:
        outcome = _normalize_required_string(outcome, f"{field}.outcome")
        if outcome not in TERMINAL_LEARNING_EVALUATION_OUTCOMES:
            raise EpicRunStateError(
                f"{field}.outcome must be one of "
                f"{list(TERMINAL_LEARNING_EVALUATION_OUTCOMES)}"
            )
        candidate["outcome"] = outcome

    return candidate


def _normalize_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EpicRunStateError(f"{field} must be an object")
    return _json_clone({str(key): item for key, item in value.items()})


def _merge_json_list(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged = _json_clone(existing)
    index = {_record_key(item): pos for pos, item in enumerate(merged)}

    for item in incoming:
        item_copy = _json_clone(item)
        key = _record_key(item_copy)
        if key in index:
            merged[index[key]] = _merge_json_value(merged[index[key]], item_copy)
        else:
            index[key] = len(merged)
            merged.append(item_copy)
    return merged


def _merge_json_mapping(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    merged = _json_clone({str(key): value for key, value in existing.items()})
    incoming_copy = _json_clone({str(key): value for key, value in incoming.items()})
    for key, value in incoming_copy.items():
        key_string = str(key)
        if key_string in merged:
            merged[key_string] = _merge_json_value(merged[key_string], value)
        else:
            merged[key_string] = value
    return merged


def _merge_json_value(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, Mapping) and isinstance(incoming, Mapping):
        return _merge_json_mapping(existing, incoming)
    if isinstance(existing, list) and isinstance(incoming, list):
        return _merge_json_list(existing, incoming)
    return _json_clone(incoming)


def _record_key(value: Any) -> str:
    if isinstance(value, Mapping):
        for field in (
            "id",
            "candidate_id",
            "issue_number",
            "issue",
            "pr_number",
            "receipt_id",
            "name",
            "key",
        ):
            record_value = value.get(field)
            if isinstance(record_value, (str, int)) and not isinstance(
                record_value, bool
            ):
                return f"{field}:{record_value}"
    return _compact_dumps(value)


def _candidate_has_terminal_outcome(candidate: Mapping[str, Any]) -> bool:
    return candidate.get("outcome") in TERMINAL_LEARNING_EVALUATION_OUTCOMES


def _candidate_display_id(candidate: Mapping[str, Any]) -> str:
    for field in ("id", "candidate_id"):
        value = candidate.get(field)
        if value is not None:
            return str(value)
    return _compact_dumps(candidate)


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(_compact_dumps(_json_safe(value)))
    except (TypeError, ValueError) as exc:
        raise EpicRunStateError("run-state values must be JSON serializable") from exc


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _compact_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _pretty_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


@contextmanager
def _locked_run_state(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    thread_lock = _thread_lock_for(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with thread_lock:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    lock_key = lock_path.resolve(strict=False)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[lock_key] = lock
        return lock


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_EPIC_RUNS_DIR",
    "SCHEMA_VERSION",
    "TERMINAL_LEARNING_EVALUATION_OUTCOMES",
    "EpicRunStateError",
    "apply_epic_run_update",
    "assert_learning_evaluation_candidates_terminal",
    "create_epic_run_state",
    "deserialize_epic_run_state",
    "epic_run_state_path",
    "load_epic_run_state",
    "new_epic_run_state",
    "normalize_epic_run_state",
    "record_dispatcher_status",
    "save_epic_run_state",
    "serialize_epic_run_state",
    "unresolved_learning_evaluation_candidates",
    "update_epic_run_state",
    "validate_run_id",
]
