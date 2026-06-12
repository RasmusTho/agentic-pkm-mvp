from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from companion_ui.workspace import serve_dev_page, serve_production_page
from companion_ui.workspace.serve_dev_page import render_index_html


@dataclass(frozen=True)
class EndpointRef:
    method: str
    path: str
    active: bool
    reason: str
    source: str


class _EndpointParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[EndpointRef] = []
        self._hidden_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        inherited_hidden = self._hidden_stack[-1] if self._hidden_stack else False
        tag_hidden = (
            inherited_hidden
            or "hidden" in attr
            or attr.get("aria-hidden") == "true"
            or "display:none" in attr.get("style", "").replace(" ", "")
        )
        self._collect(tag, attr, tag_hidden)
        if tag.lower() not in self._VOID_TAGS:
            self._hidden_stack.append(tag_hidden)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        inherited_hidden = self._hidden_stack[-1] if self._hidden_stack else False
        tag_hidden = (
            inherited_hidden
            or "hidden" in attr
            or attr.get("aria-hidden") == "true"
            or "display:none" in attr.get("style", "").replace(" ", "")
        )
        self._collect(tag, attr, tag_hidden)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in self._VOID_TAGS and self._hidden_stack:
            self._hidden_stack.pop()

    def _collect(self, tag: str, attr: dict[str, str], hidden: bool) -> None:
        raw_path = attr.get("data-api-path", "").strip()
        if not raw_path:
            return
        method = attr.get("data-api-method", "GET").strip().upper() or "GET"
        if method == "LOCAL":
            return
        path = _normalize_path(raw_path)
        if not path.startswith("/api/"):
            return
        status = attr.get("data-affordance-status", "").strip().lower()
        disabled = (
            hidden
            or "disabled" in attr
            or attr.get("aria-disabled") == "true"
            or attr.get("data-disabled") == "true"
            or attr.get("data-blocked") == "true"
            or status in {"blocked", "unavailable", "disabled"}
        )
        reason = attr.get("data-disabled-reason") or attr.get("data-blocked-reason") or ""
        testid = attr.get("data-testid") or tag
        self.refs.append(
            EndpointRef(
                method=method,
                path=path,
                active=not disabled,
                reason=reason,
                source=f"data-api-path:{testid}",
            )
        )


_FETCH_RE = re.compile(
    r"fetch\(\s*['\"](?P<path>/api/[^'\"]+)['\"]\s*(?:,\s*(?P<opts>\{.*?\}))?\s*\)",
    re.S,
)
_POST_JSON_RE = re.compile(r"postJson\(\s*['\"](?P<path>/api/[^'\"]+)['\"]")
_METHOD_RE = re.compile(r"method\s*:\s*['\"](?P<method>[A-Z]+)['\"]")


class _FakeClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return {}

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {}


def _normalize_path(path: str) -> str:
    parsed = urlparse(path)
    return parsed.path or path


def _script_refs(html: str) -> list[EndpointRef]:
    refs: list[EndpointRef] = []
    for match in _POST_JSON_RE.finditer(html):
        refs.append(
            EndpointRef(
                method="POST",
                path=_normalize_path(match.group("path")),
                active=True,
                reason="",
                source="postJson literal",
            )
        )
    for match in _FETCH_RE.finditer(html):
        opts = match.group("opts") or ""
        method_match = _METHOD_RE.search(opts)
        method = method_match.group("method") if method_match else "GET"
        refs.append(
            EndpointRef(
                method=method,
                path=_normalize_path(match.group("path")),
                active=True,
                reason="",
                source="fetch literal",
            )
        )
    return refs


def _panel_proposal(proposal_id: str = "proposal-1875") -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "artifact_id": "artifact-1875",
        "description": "Move note to Projects",
        "evidence": {"action_class": "lifecycle.move", "trigger_summary": "route parity"},
        "status": "staged",
        "affordances": {"confirm": True, "correct": True, "reject": True},
    }


def _workspace_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "title": "Route Parity Note",
        "note_path": "Notes/route-parity.md",
        "artifact_id": "artifact-1875",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-route-parity",
        "body": "# Route parity\n\nBody.",
        "panel_rail": "Panel proposals",
        "panel_state": "proposals-staged",
        "panel_proposal_count": 1,
        "panel_proposals": [_panel_proposal()],
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-route-parity",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_id": "session-1875",
        "canvas_session_state": "active",
        "canvas_user_present": True,
        "canvas_can_edit_body": True,
        "canvas_recovery_needed": True,
        "canvas_conflict_detected": True,
        "canvas_undo_available": True,
        "canvas_session_persistence": "durable",
        "canvas_session_log_path": ".chats/canvas/session-1875.md",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_workspace_update_state": "available",
        "guard_workspace_update_reason": "explicit_dev_config",
        "guard_update_flow_available": True,
        "guard_workspace_update_governance_actions_enabled": True,
        "active_note_body_update_enabled": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "vault_browser_notes": [
            {
                "note_path": "Notes/route-parity.md",
                "title": "Route Parity Note",
                "uuid": "uuid-route-parity",
                "kind": "human_note",
                "zone": "notes",
                "review_state": "needs_review",
                "trust": "assert",
                "origin": "vault",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            }
        ],
        "vault_browser_total_notes": 1,
        "vault_browser_filtered_notes": 1,
        "vault_browser_read_only": True,
        "vault_browser_identity_available": True,
        "vault_browser_vault_name": "vault/dev",
        "vault_browser_vault_channel": "local-dev",
        "vault_browser_vault_provenance": "resolved",
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
    fields.update(overrides)
    return fields


def _render_refs(*, production_profile: bool = False) -> list[EndpointRef]:
    active_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/route-parity.md",
        fields=_workspace_fields(),
        production_profile=production_profile,
    )
    open_session_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/route-parity.md",
        fields=_workspace_fields(
            canvas_session_id="",
            canvas_session_state="idle",
            canvas_user_present=False,
            canvas_can_edit_body=False,
            canvas_recovery_needed=False,
            canvas_conflict_detected=False,
            canvas_undo_available=False,
        ),
        production_profile=production_profile,
    )
    parser = _EndpointParser()
    parser.feed(active_html)
    parser.feed(open_session_html)
    return parser.refs + _script_refs(active_html) + _script_refs(open_session_html)


def _handler(*, production_profile: bool = False) -> type:
    return serve_dev_page.make_handler(
        client=_FakeClient(),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
        production_profile=production_profile,
    )


def test_every_referenced_endpoint_is_proxied_or_hidden() -> None:
    handler_cls = _handler()
    refs = _render_refs()
    assert any(ref.path == "/api/panel/confirm" and ref.method == "POST" for ref in refs)

    expected_allowed = {
        ("POST", "/api/panel/confirm"),
        ("GET", "/api/companion/vault-related"),
        ("POST", "/api/companion/vault-browser/actions/queue-review"),
        ("POST", "/api/canvas/sessions"),
        ("POST", "/api/canvas/sessions/session-1875/edits"),
        ("DELETE", "/api/canvas/sessions/session-1875/edits/last"),
        ("DELETE", "/api/canvas/sessions/session-1875"),
        ("POST", "/api/canvas/sessions/session-1875/recovery/ack"),
    }
    missing_expected = [
        (method, path)
        for method, path in sorted(expected_allowed)
        if not handler_cls.route_allowed(method, path)
    ]
    assert missing_expected == []

    failures: list[str] = []
    missing_reasons: list[str] = []
    for ref in refs:
        if handler_cls.route_allowed(ref.method, ref.path):
            continue
        if ref.active:
            failures.append(f"{ref.method} {ref.path} from {ref.source}")
            continue
        if not ref.reason:
            missing_reasons.append(f"{ref.method} {ref.path} from {ref.source}")

    assert failures == []
    assert missing_reasons == []


def test_production_page_parity_matches() -> None:
    dev_handler = _handler(production_profile=False)
    production_handler = serve_production_page.make_handler(
        client=_FakeClient(),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
    )
    samples = {
        (ref.method, ref.path) for ref in _render_refs(production_profile=True)
    } | {
        ("GET", "/api/companion/tts/status"),
        ("GET", "/api/companion/tts/audio/" + "a" * 64 + ".wav"),
    }

    drift = [
        (method, path)
        for method, path in sorted(samples)
        if dev_handler.route_allowed(method, path)
        != production_handler.route_allowed(method, path)
    ]
    assert drift == []
