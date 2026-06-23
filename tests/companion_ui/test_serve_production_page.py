"""Tests for Companion UI production profile Operator overlay (issue #1758).

Verifies the "no dev/prod feature split" constraint: the production profile
must expose the same Operator overlay as the dev profile.

Constraint (issue #1758): "The overlay must be present in both the dev and
production profiles; the production profile must not strip it."
"""

from __future__ import annotations


def test_production_profile_exposes_operator_overlay() -> None:
    """The production shell HTML includes the Operator overlay toggle and drawer.

    No dev/prod feature split: production profile must not strip the overlay.
    """
    from companion_ui.workspace.serve_production_page import render_production_index_html

    html = render_production_index_html(
        api_base_url="http://127.0.0.1:18000",
        fields={
            "title": "Prod Note",
            "note_path": "Notes/prod.md",
            "artifact_id": "art-prod",
            "content_hash": "hash-prod",
            "body": "# Prod Note",
            "runtime_environment_label": "prod",
            "runtime_api_base_url_label": "local-prod",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": False,
            "guard_degraded": False,
        },
    )

    # CUIDR-04 (#2447): the floating Operator pill is removed from the front
    # edge; the operator layer is reached from the System Map operator node
    # (operator.open) in production too — no dev/prod feature split.
    assert 'class="operator-toggle"' not in html, (
        "the floating Operator pill must not render on the production front edge"
    )
    assert 'data-surface-id="operator"' in html and 'data-intent="operator.open"' in html, (
        "Production shell missing System Map operator node — violates "
        "no-dev/prod-feature-split constraint"
    )

    # Operator drawer host present
    assert 'data-testid="workspace-operator-host"' in html, (
        "Production shell missing Operator drawer host"
    )

    # Operator drawer present
    assert 'data-testid="workspace-operator-drawer"' in html, (
        "Production shell missing Operator drawer"
    )

    # Operator badge present in drawer header
    assert 'data-testid="workspace-operator-badge"' in html, (
        "Production shell missing Operator badge in drawer"
    )

    # The /operator route is referenced (lazy-load target)
    assert "/operator" in html, (
        "Production shell does not reference /operator lazy-load route"
    )


def test_production_operator_overlay_uses_same_proxy_routes() -> None:
    """The production overlay JS references /api/operator/* same-origin routes."""
    from companion_ui.workspace.serve_production_page import render_production_index_html

    html = render_production_index_html(api_base_url="http://127.0.0.1:18000")

    # The drawer JS must reference companionOperator (not a production-only alternative)
    assert "companionOperator" in html, (
        "Production shell missing companionOperator controller"
    )


def test_production_make_handler_includes_operator_proxy_routes() -> None:
    """The production make_handler handler class exposes /api/operator/* routes."""
    import io
    from typing import Any

    from companion_ui.workspace.serve_dev_page import make_handler

    class _FakeClient:
        def __init__(self) -> None:
            self.get_calls: list[tuple[str, dict[str, Any]]] = []

        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            self.get_calls.append((url, params))
            return {"ok": True}

        def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
            return {}

    client = _FakeClient()
    # Production profile=True
    handler_cls = make_handler(
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
    )

    instance = handler_cls.__new__(handler_cls)
    instance.path = "/api/operator/health"
    instance.wfile = io.BytesIO()
    instance.headers = {}

    status_code_holder: list[int] = []
    payload_holder: list[dict[str, Any]] = []

    def _send_json(sc: int, p: dict[str, Any]) -> None:
        status_code_holder.append(sc)
        payload_holder.append(p)

    instance._send_json = _send_json  # type: ignore[method-assign]
    instance.send_response = lambda *a: None  # type: ignore[method-assign]
    instance.send_header = lambda *a: None  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.wfile.write = lambda *a: None  # type: ignore[method-assign]

    instance.do_GET()

    assert status_code_holder == [200], (
        f"Expected 200 from /api/operator/health in production handler, got {status_code_holder}"
    )
    assert client.get_calls[-1][0] == "/api/health", (
        "Production handler did not proxy /api/operator/health -> /api/health"
    )
