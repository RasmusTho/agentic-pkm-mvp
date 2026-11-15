"""Bounded Claude stream observations for protected Issue delivery.

Provider output is observation only; the host owns admission and effects.
"""
from __future__ import annotations

import json
import re
from uuid import UUID
from typing import Any, Callable, Mapping

from app.builderops.epic_dispatch import IssueSessionLaunchError

_MAX_LINE_BYTES = 256 * 1024


def validate_claude_model(value: object) -> str:
    """Accept only a bounded, unambiguous direct-argv model identifier."""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", value) is None:
        raise ValueError("Claude model identifier is invalid")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ClaudeStreamObservation:
    """Collect one fresh native session and its terminal content result."""

    def __init__(self, expected_session_id: str, on_entry: Callable[[str], None] | None = None) -> None:
        try:
            if str(UUID(expected_session_id)) != expected_session_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("expected Claude session id must be a canonical UUID") from exc
        self.expected_session_id = expected_session_id
        self.session_id: str | None = None
        self.result: Mapping[str, Any] | None = None
        self.invalid = False
        self._on_entry = on_entry

    def observe(self, line: str) -> None:
        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            self.invalid = True
            return
        try:
            event = json.loads(line, object_pairs_hook=_unique_object)
        except (ValueError, TypeError):
            self.invalid = True
            return
        if not isinstance(event, Mapping):
            self.invalid = True
            return
        if event.get("session_id") != self.expected_session_id:
            self.invalid = True
            return
        kind = event.get("type")
        if kind not in {"system", "result"}:
            return
        if kind == "system" and event.get("subtype") != "init":
            return
        identity = event.get("session_id")
        if identity != self.expected_session_id:
            self.invalid = True
            return
        if kind == "system":
            if self.session_id is not None:
                self.invalid = True
                return
            self.session_id = identity
            if self._on_entry is not None:
                self._on_entry(identity)
            return
        if self.session_id != identity or self.result is not None or event.get("is_error") is not False or event.get("subtype") != "success":
            self.invalid = True
            return
        payload = event.get("result")
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > _MAX_LINE_BYTES:
            self.invalid = True
            return
        try:
            result = json.loads(payload, object_pairs_hook=_unique_object)
        except ValueError:
            self.invalid = True
            return
        if not isinstance(result, Mapping):
            self.invalid = True
            return
        self.result = dict(result)

    def terminal(self, returncode: int) -> dict[str, Any]:
        if self.invalid or returncode != 0 or self.session_id is None or self.result is None:
            raise IssueSessionLaunchError("Claude session observation is incomplete or contradictory", session_id=self.session_id)
        return {"session_id": self.session_id, "worker_receipt": dict(self.result)}
