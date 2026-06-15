"""Served-path wiring for the memory-review render surfaces (#2016).

The 2026-06-14 review-comment closure audit (parent #1984) flagged that the
materialized-memory and recall-provenance render helpers in
``memory_review_drawer.py`` were standalone — referenced only by unit tests,
never by the served Companion page. These tests pin the wiring at the serve
path: the ``/memory-review`` fragment the page server renders from the #1792
read endpoint must include the materialized-memory and recall-provenance
surfaces when the runtime payload declares them.

The render helpers stay pure (constraint); the wiring is asserted through the
page server's same-origin fragment route, not by re-deriving anything in the
client.
"""

from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.memory_review_drawer import (
    MEMORY_REVIEW_FRAGMENT_ROUTE,
    MEMORY_REVIEW_QUEUE_ENDPOINT,
    materialized_memory_surface,
    recall_provenance_surface,
)
from companion_ui.workspace.serve_dev_page import make_handler


class _FakeClient:
    def __init__(self, get_responses: dict[str, Any] | None = None) -> None:
        self.get_responses = get_responses or {}
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.get_responses.get(url, {})


def _drive_get(handler_cls: type, path: str) -> bytes:
    instance = handler_cls.__new__(handler_cls)
    instance.path = path
    instance.headers = {}
    chunks: list[bytes] = []
    instance.wfile = io.BytesIO()
    instance.wfile.write = chunks.append  # type: ignore[method-assign]
    instance.send_response = lambda *_: None  # type: ignore[method-assign]
    instance.send_header = lambda *_: None  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.do_GET()
    return b"".join(chunks)


def _materialized() -> dict[str, Any]:
    return {
        "title": "Promoted preference",
        "artifact_path": "Memory/promoted-pref.md",
        "promoted_from_candidate_id": "cand-7",
        "decided_by": "companion-ui:reviewer",
        "decided_at": "2026-06-14T10:00:00Z",
        "labels": ["preference"],
        "source_refs": ["Notes/source-7.md"],
        "agent_promoted": True,
        "artifact_class": "agentic_memory",
    }


def _recall() -> dict[str, Any]:
    return {
        "why_now": "Recalled for this turn from prior session context.",
        "receipt_reference": "recall-receipt-3",
        "authority_limits": ["non_authoritative", "advisory_only"],
        # Authority explicitly declared by the runtime.
        "may_answer": True,
        "may_propose": False,
        "may_write": False,
    }


def _queue_payload_with_surfaces() -> dict[str, Any]:
    return {
        "source": "agent_memory.review_queue",
        "pending_count": 0,
        "candidates": [],
        "materialized_memories": [_materialized()],
        "recall": _recall(),
        "source_ref": {
            "kind": "agent_memory.review_queue",
            "ref": "agent_memory.review_queue",
            "label": "memory candidate review queue",
        },
    }


def test_serve_path_renders_new_surfaces() -> None:
    """The served /memory-review fragment renders the materialized-memory and
    recall-provenance surfaces from the runtime payload (#2016 AC1)."""
    payload = _queue_payload_with_surfaces()
    client = _FakeClient(get_responses={MEMORY_REVIEW_QUEUE_ENDPOINT: payload})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")

    body = _drive_get(handler_cls, MEMORY_REVIEW_FRAGMENT_ROUTE).decode("utf-8")

    # The page server reads the #1792 queue endpoint same-origin.
    assert client.get_calls == [(MEMORY_REVIEW_QUEUE_ENDPOINT, {})]

    # Materialized-memory surface is wired into the served fragment.
    assert 'data-testid="materialized-memory-surface"' in body
    assert "Promoted preference" in body
    assert "Memory/promoted-pref.md" in body

    # Recall-provenance surface is wired into the served fragment, rendering
    # the runtime-declared authority verbatim (not re-derived by the UI).
    assert 'data-testid="memory-recall-provenance"' in body
    assert 'data-may-answer="true"' in body
    assert 'data-may-propose="false"' in body
    assert "recall-receipt-3" in body

    # The served fragment is exactly the pure helpers' output — the serve path
    # composes them, it does not re-implement them.
    assert materialized_memory_surface(_materialized()) in body
    assert recall_provenance_surface(_recall()) in body


def test_serve_path_omits_surfaces_when_runtime_does_not_declare_them() -> None:
    """Absent runtime data renders no fabricated surfaces — pull-based only."""
    payload = {
        "source": "agent_memory.review_queue",
        "pending_count": 0,
        "candidates": [],
        "source_ref": {
            "kind": "agent_memory.review_queue",
            "ref": "agent_memory.review_queue",
            "label": "memory candidate review queue",
        },
    }
    client = _FakeClient(get_responses={MEMORY_REVIEW_QUEUE_ENDPOINT: payload})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")

    body = _drive_get(handler_cls, MEMORY_REVIEW_FRAGMENT_ROUTE).decode("utf-8")

    assert 'data-testid="materialized-memory-surface"' not in body
    assert 'data-testid="memory-recall-provenance"' not in body
