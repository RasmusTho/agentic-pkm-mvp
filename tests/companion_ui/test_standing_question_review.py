from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.memory_review_drawer import memory_review_drawer_markup
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from companion_ui.workspace.standing_question_review import standing_question_review_script


class _FakeClient:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return {"questions": []}


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


def test_contradiction_marker_visually_distinct() -> None:
    markup = memory_review_drawer_markup()
    script = standing_question_review_script()
    assert "standing-question-contradiction-marker" in script
    assert "setAttribute('data-contradicts-standing-answer', 'true')" in script
    assert ".sq-contradiction-marker" in markup
    assert "var(--status-danger)" in markup
    assert "var(--destructive-muted)" in markup
    assert "border-left: 4px solid var(--status-danger)" in markup


def test_standing_question_list_uses_same_origin_proxy_and_declared_drawer() -> None:
    client = _FakeClient()
    handler_cls = make_handler(client=client, api_base_url="http://runtime")

    body = _drive_get(handler_cls, "/api/standing-questions?include_resolved=true")

    assert client.get_calls == [
        ("/api/standing-questions", {"include_resolved": "true"})
    ]
    assert b'"questions": []' in body
    assert handler_cls.route_allowed("GET", "/api/standing-questions")
    assert handler_cls.route_allowed(
        "GET", "/api/standing-questions/sq-123e4567-e89b-12d3-a456-426614174000"
    )
    assert handler_cls.route_allowed(
        "POST", "/api/standing-questions/sq-123e4567-e89b-12d3-a456-426614174000/dismiss"
    )
    assert 'data-drawer-tab="standing-questions"' in memory_review_drawer_markup()
    assert 'data-testid="standing-question-review"' in memory_review_drawer_markup()


def test_question_review_script_renders_untrusted_values_as_text() -> None:
    markup = render_index_html(api_base_url="http://127.0.0.1:18001")
    script = standing_question_review_script()
    assert "textContent = value == null ? '' : String(value)" in script
    assert ".innerHTML" not in script
    assert 'standing_question' in markup
