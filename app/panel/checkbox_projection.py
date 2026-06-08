"""Runtime-mediated projection of Panel checkbox confirmations.

The browser never writes vault Markdown directly. This service validates the
current note source, projects the canonical ``- [x]`` checkbox state through
the governed backend writer path, then lets the normal Panel runtime observe
that checked state.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agents.panel.parser import is_ai_fence, parse_panel
from app.agents.panel.writeback import parse_action_line, stable_action_id
from app.agents.panel_agent.execution import refresh_panel_note_object, run_panel_note_execution
from app.api.routes.artifacts import _content_hash
from app.config.paths import resolve_vault_root
from app.knowledge.write_ops import write_note_from_absolute
from app.services.artifact_identity import resolve_note_artifact_identity
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError


ProjectionStatus = Literal[
    "projected",
    "already_projected",
    "queued",
    "executed",
    "blocked",
    "stale",
    "not_found",
    "not_selectable",
    "failed",
]

_CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_CHECKBOX_MARK_RE = re.compile(r"^(\s*-\s*\[)( )(\]\s*.*)$")


class SourceRange(BaseModel):
    start_line: int = Field(ge=0)
    end_line: int = Field(ge=0, description="Exclusive 0-based end line.")


class PanelSelectableOption(BaseModel):
    artifact_id: str
    note_path: str
    panel_id: str
    option_id: str
    action_id: str
    label: str
    checked: bool
    proposal_pending: bool
    source_range: SourceRange
    source_hash: str
    content_hash: str
    selectable: bool


class CheckboxProjectionRequest(BaseModel):
    artifact_id: str = Field(min_length=1)
    note_path: str = Field(min_length=1)
    panel_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    expected_content_hash: str = Field(min_length=1)
    expected_source_hash: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)

    @field_validator(
        "artifact_id",
        "note_path",
        "panel_id",
        "option_id",
        "expected_content_hash",
        "expected_source_hash",
        "idempotency_key",
        mode="before",
    )
    @classmethod
    def _strip_value(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CheckboxProjectionResponse(BaseModel):
    status: ProjectionStatus
    artifact_id: str
    note_path: str
    panel_id: str
    option_id: str
    content_hash_before: str
    content_hash_after: str
    receipt: dict | None = None
    block_reason: str | None = None
    idempotency_key: str


class CheckboxProjectionHTTPError(Exception):
    def __init__(self, status_code: int, response: CheckboxProjectionResponse) -> None:
        self.status_code = status_code
        self.response = response
        super().__init__(response.status)


class CheckboxProjectionIdempotencyStore:
    def __init__(self) -> None:
        self._cache: dict[str, CheckboxProjectionResponse] = {}

    def get(self, key: str) -> CheckboxProjectionResponse | None:
        return self._cache.get(key)

    def set(self, key: str, response: CheckboxProjectionResponse) -> None:
        self._cache[key] = response

    def clear(self) -> None:
        self._cache.clear()


def _source_line_hash(source_line: str) -> str:
    return hashlib.sha256(source_line.encode("utf-8")).hexdigest()


def _source_line_without_newline(raw_line: str) -> str:
    return raw_line.rstrip("\r\n")


def _valid_note_path(note_path_raw: str) -> str | None:
    note_path = (note_path_raw or "").split("#", 1)[0]
    candidate = PurePosixPath(note_path)
    if (
        not note_path
        or note_path.startswith("/")
        or ".." in candidate.parts
        or candidate.as_posix() in {"", "."}
        or not candidate.as_posix().endswith(".md")
    ):
        return None
    return candidate.as_posix()


def _vault_contained_abs_path(vault_root: Path, safe_note_path: str) -> Path | None:
    root_real = os.path.realpath(vault_root)
    target_real = os.path.realpath(os.path.join(root_real, safe_note_path))
    if target_real != root_real and not target_real.startswith(root_real + os.sep):
        return None
    return Path(target_real)


def _section_for_line(line: str) -> Literal["instruction", "actions", "logs"] | None:
    stripped = line.strip().lower()
    if stripped.startswith(("## ai-åtgärder", "### ai-åtgärder")):
        return "actions"
    if stripped.startswith(("## ai-instruktion", "### ai-instruktion")):
        return "instruction"
    if stripped.startswith(("## ai-logg", "### ai-logg")):
        return "logs"
    if stripped.startswith(("actions:", "åtgärder:")):
        return "actions"
    if stripped.startswith(("instruction:", "instruktion:")):
        return "instruction"
    if stripped.startswith(("log:", "logg:")):
        return "logs"
    return None


def _panel_ranges(markdown: str) -> list[tuple[str, int, int]]:
    parsed = parse_panel(markdown)
    ranges: list[tuple[str, int, int]] = []
    for index, (start, end) in enumerate(parsed.spans, start=1):
        ranges.append((f"panel-{index}", start, end))
    return ranges


def extract_panel_selectable_options(
    markdown: str,
    *,
    artifact_id: str,
    note_path: str,
    content_hash: str | None = None,
) -> list[PanelSelectableOption]:
    """Return source-backed Panel checkbox options eligible for UI projection.

    Options without an explicit durable ``ai:option_id`` marker are omitted.
    Ordinary Markdown tasks, code-block tasks, receipt checkboxes, and tasks
    outside a valid Panel ``AI-åtgärder`` section are not returned.
    """
    lines = markdown.splitlines()
    current_content_hash = content_hash or _content_hash(markdown)
    options: list[PanelSelectableOption] = []

    for panel_id, start, end in _panel_ranges(markdown):
        current_section: Literal["instruction", "actions", "logs"] | None = None
        code_fence: str | None = None
        lower_bound = max(0, start)
        upper_bound = min(len(lines) - 1, end)
        for line_index in range(lower_bound, upper_bound + 1):
            raw_line = lines[line_index]
            if is_ai_fence(raw_line):
                continue
            fence = _CODE_FENCE_RE.match(raw_line)
            if fence:
                marker = fence.group(1)[0]
                if code_fence == marker:
                    code_fence = None
                elif code_fence is None:
                    code_fence = marker
                continue
            if code_fence is not None:
                continue
            section = _section_for_line(raw_line)
            if section is not None:
                current_section = section
                continue
            if current_section != "actions":
                continue
            parsed = parse_action_line(raw_line)
            if parsed is None or parsed.option_id is None:
                continue
            action_id = parsed.action_id or stable_action_id(parsed.label)
            proposal_pending = parsed.proposal_marker is not None
            options.append(
                PanelSelectableOption(
                    artifact_id=artifact_id,
                    note_path=note_path,
                    panel_id=panel_id,
                    option_id=parsed.option_id,
                    action_id=action_id,
                    label=parsed.label,
                    checked=parsed.checked,
                    proposal_pending=proposal_pending,
                    source_range=SourceRange(start_line=line_index, end_line=line_index + 1),
                    source_hash=_source_line_hash(raw_line),
                    content_hash=current_content_hash,
                    selectable=bool(proposal_pending and not parsed.checked),
                )
            )
    return options


def _project_checked(markdown: str, *, line_index: int) -> str | None:
    lines = markdown.splitlines(keepends=True)
    if line_index < 0 or line_index >= len(lines):
        return None
    line = lines[line_index]
    source_line = _source_line_without_newline(line)
    newline = line[len(source_line):]
    match = _CHECKBOX_MARK_RE.match(source_line)
    if not match:
        return None
    lines[line_index] = f"{match.group(1)}x{match.group(3)}{newline}"
    return "".join(lines)


class CheckboxProjectionService:
    def __init__(
        self,
        *,
        idempotency_store: CheckboxProjectionIdempotencyStore | None = None,
        write_guard: WriteGuard | None = None,
    ) -> None:
        self._idempotency = idempotency_store or CheckboxProjectionIdempotencyStore()
        self._guard = write_guard or DEFAULT_WRITE_GUARD
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for_note(self, safe_note_path: str) -> threading.Lock:
        with self._locks_guard:
            if safe_note_path not in self._locks:
                self._locks[safe_note_path] = threading.Lock()
            return self._locks[safe_note_path]

    def project(self, request: CheckboxProjectionRequest) -> CheckboxProjectionResponse:
        cached = self._idempotency.get(request.idempotency_key)
        if cached is not None:
            return cached

        safe_note_path = _valid_note_path(request.note_path)
        if safe_note_path is None:
            response = self._response(
                request,
                status="not_selectable",
                note_path=request.note_path,
                before="",
                after="",
                block_reason="invalid_note_path",
            )
            raise CheckboxProjectionHTTPError(422, response)

        lock = self._lock_for_note(safe_note_path)
        with lock:
            cached = self._idempotency.get(request.idempotency_key)
            if cached is not None:
                return cached
            return self._project_locked(request, safe_note_path)

    def _project_locked(
        self,
        request: CheckboxProjectionRequest,
        safe_note_path: str,
    ) -> CheckboxProjectionResponse:
        vault_root = resolve_vault_root()
        note_path = _vault_contained_abs_path(vault_root, safe_note_path)
        if note_path is None or not note_path.is_file():
            response = self._response(
                request,
                status="not_found",
                note_path=safe_note_path,
                before="",
                after="",
                block_reason="note_not_found",
            )
            raise CheckboxProjectionHTTPError(404, response)

        current = note_path.read_text(encoding="utf-8")
        content_hash_before = _content_hash(current)
        if content_hash_before != request.expected_content_hash:
            response = self._response(
                request,
                status="stale",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="content_hash_mismatch",
            )
            raise CheckboxProjectionHTTPError(409, response)

        identity = resolve_note_artifact_identity(
            artifact_path=note_path,
            vault_root=vault_root,
            safe_note_path=safe_note_path,
            body=current,
            heal_missing_uuid=False,
        )
        if identity.artifact_id != request.artifact_id:
            response = self._response(
                request,
                status="not_found",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="artifact_mismatch",
            )
            raise CheckboxProjectionHTTPError(404, response)

        options = extract_panel_selectable_options(
            current,
            artifact_id=request.artifact_id,
            note_path=safe_note_path,
            content_hash=content_hash_before,
        )
        matches = [
            option
            for option in options
            if option.panel_id == request.panel_id and option.option_id == request.option_id
        ]
        if len(matches) != 1:
            response = self._response(
                request,
                status="not_found",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="option_not_found_or_ambiguous",
            )
            raise CheckboxProjectionHTTPError(404, response)
        option = matches[0]

        if option.source_hash != request.expected_source_hash:
            response = self._response(
                request,
                status="stale",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="source_hash_mismatch",
            )
            raise CheckboxProjectionHTTPError(409, response)

        if option.checked:
            response = self._response(
                request,
                status="already_projected",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
            )
            self._idempotency.set(request.idempotency_key, response)
            return response

        if not option.selectable:
            response = self._response(
                request,
                status="not_selectable",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="option_not_pending_or_selectable",
            )
            raise CheckboxProjectionHTTPError(422, response)

        try:
            self._guard.assert_writes_allowed("panel.checkbox_projection")
        except WritesBlockedError as exc:
            response = self._response(
                request,
                status="blocked",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason=str(exc),
            )
            self._idempotency.set(request.idempotency_key, response)
            return response

        projected = _project_checked(current, line_index=option.source_range.start_line)
        if projected is None:
            response = self._response(
                request,
                status="stale",
                note_path=safe_note_path,
                before=content_hash_before,
                after=content_hash_before,
                block_reason="source_line_no_longer_projectable",
            )
            raise CheckboxProjectionHTTPError(409, response)

        write_note_from_absolute(note_path, projected, vault_root=vault_root)
        written = note_path.read_text(encoding="utf-8")
        content_hash_after = _content_hash(written)

        response = self._execute_or_projected(
            request,
            note_path=note_path,
            safe_note_path=safe_note_path,
            rollback_text=current,
            raw_text=written,
            content_hash_before=content_hash_before,
            content_hash_after=content_hash_after,
        )
        self._idempotency.set(request.idempotency_key, response)
        return response

    def _execute_or_projected(
        self,
        request: CheckboxProjectionRequest,
        *,
        note_path: Path,
        safe_note_path: str,
        rollback_text: str,
        raw_text: str,
        content_hash_before: str,
        content_hash_after: str,
    ) -> CheckboxProjectionResponse:
        try:
            refresh_panel_note_object(
                note_uuid=request.artifact_id,
                note_path=note_path,
                raw_text=raw_text,
                trace_id=request.idempotency_key,
            )
            run_panel_note_execution(
                request.artifact_id,
                trace_id=request.idempotency_key,
                trigger="companion",
            )
        except Exception as exc:
            write_note_from_absolute(note_path, rollback_text, vault_root=resolve_vault_root())
            rolled_back = note_path.read_text(encoding="utf-8")
            return self._response(
                request,
                status="failed",
                note_path=safe_note_path,
                before=content_hash_before,
                after=_content_hash(rolled_back),
                block_reason=f"runtime_execution_failed:{type(exc).__name__}",
            )

        # Do not report execution without response-level receipt evidence.
        # The current runtime invocation may write its own durable callout, but
        # this endpoint does not observe or return that evidence.
        return self._response(
            request,
            status="projected",
            note_path=safe_note_path,
            before=content_hash_before,
            after=content_hash_after,
        )

    @staticmethod
    def _response(
        request: CheckboxProjectionRequest,
        *,
        status: ProjectionStatus,
        note_path: str,
        before: str,
        after: str,
        block_reason: str | None = None,
    ) -> CheckboxProjectionResponse:
        return CheckboxProjectionResponse(
            status=status,
            artifact_id=request.artifact_id,
            note_path=note_path,
            panel_id=request.panel_id,
            option_id=request.option_id,
            content_hash_before=before,
            content_hash_after=after,
            receipt=None,
            block_reason=block_reason,
            idempotency_key=request.idempotency_key,
        )


_idempotency_store = CheckboxProjectionIdempotencyStore()
_service = CheckboxProjectionService(idempotency_store=_idempotency_store)


__all__ = [
    "CheckboxProjectionHTTPError",
    "CheckboxProjectionIdempotencyStore",
    "CheckboxProjectionRequest",
    "CheckboxProjectionResponse",
    "CheckboxProjectionService",
    "PanelSelectableOption",
    "SourceRange",
    "_idempotency_store",
    "_service",
    "extract_panel_selectable_options",
]
