"""The source editor loads from a self-hosted bundle, not the esm.sh CDN.

Regression guard for the runtime CDN dependency that hung the product page and
false-failed the ``companion-ui-browser-runtime`` job (#2884): the workspace
shell used to statically ``import`` CodeMirror from the public ``esm.sh`` CDN in a
``<script type="module">``. A *static* module import gates ``DOMContentLoaded`` on
its resolution, so a slow/unreachable CDN hung the whole page — an availability +
supply-chain dependency baked into the runtime, not just the test harness.

These tests pin the fix:

* the served page (dev **and** production profile) references no ``esm.sh``
  CodeMirror URL;
* the editor is imported dynamically (``await import(...)``) from a same-origin
  ``/static/vendor`` URL, so a failed load can never gate ``DOMContentLoaded``;
* the vendored bundle is served by the handler and is a self-contained ESM
  module (no transitive network imports);
* the body-edit panel degrades to a plain textarea when the bundle is
  unreachable, so the write path survives offline.

Mermaid is intentionally still CDN-loaded: it is a *dynamic* import in a
``try/catch`` that already degrades to source (non-fatal). Full mermaid vendoring
is tracked separately — see ``vendor/README.md``.
"""

from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.serve_dev_page import (
    CODEMIRROR_MODULE_URL,
    make_handler,
    render_index_html,
    vendor_static_assets,
)

# Minimal fields that render the full note shell including the body-edit panel
# (``guard_update_flow_available`` gates the composer that hosts the editor).
_NOTE_FIELDS: dict[str, Any] = {
    "title": "Note",
    "note_path": "Notes/note.md",
    "artifact_id": "art-1",
    "content_hash": "hash-1",
    "body": "# Note body",
    "runtime_environment_label": "dev",
    "runtime_api_base_url_label": "local-dev",
    "guard_writeguard_status": "ok",
    "guard_canvas_enabled": True,
    "guard_degraded": False,
    "guard_update_flow_available": True,
    "guard_workspace_update_available": True,
}


def _dev_page() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_NOTE_FIELDS,
    )


def _prod_page() -> str:
    from companion_ui.workspace.serve_production_page import render_production_index_html

    return render_production_index_html(
        api_base_url="http://127.0.0.1:18000",
        note_path="Notes/note.md",
        fields=_NOTE_FIELDS,
    )


def test_page_has_body_edit_panel_fixture_precondition() -> None:
    """The test fixture actually renders the editor host (else the CDN asserts
    below would pass vacuously)."""
    for html in (_dev_page(), _prod_page()):
        assert 'id="body-edit-codemirror"' in html


def test_no_esm_sh_codemirror_import_in_served_page() -> None:
    """Neither profile references the esm.sh CodeMirror URLs anymore."""
    for label, html in (("dev", _dev_page()), ("prod", _prod_page())):
        assert "esm.sh/codemirror" not in html, f"{label} page still imports CodeMirror from esm.sh"
        assert "esm.sh/@codemirror" not in html, (
            f"{label} page still imports @codemirror/* from esm.sh"
        )


def test_editor_imported_dynamically_from_self_hosted_url() -> None:
    """The editor is a same-origin dynamic import — never a DCL-gating static import."""
    for label, html in (("dev", _dev_page()), ("prod", _prod_page())):
        assert CODEMIRROR_MODULE_URL in html, f"{label} page missing self-hosted editor URL"
        assert f"await import('{CODEMIRROR_MODULE_URL}')" in html, (
            f"{label} page must load the editor via dynamic import() so a failed "
            f"load cannot gate DOMContentLoaded"
        )
        # No top-level static `import ... from '<vendor url>'` (that would gate DCL).
        assert f"from '{CODEMIRROR_MODULE_URL}'" not in html, (
            f"{label} page uses a static import of the editor bundle — reintroduces "
            f"the DOMContentLoaded-gating failure mode (#2884)"
        )


def test_vendor_bundle_is_self_contained_esm() -> None:
    """The vendored bundle is served and carries no transitive network imports."""
    assets = vendor_static_assets()
    assert CODEMIRROR_MODULE_URL in assets, "editor bundle route not registered"
    content_type, body = assets[CODEMIRROR_MODULE_URL]
    assert "javascript" in content_type
    # A real bundle, not a stub (the esm.sh CodeMirror graph is hundreds of KB).
    assert len(body) > 100_000, f"vendored bundle implausibly small ({len(body)} bytes)"
    text = body.decode("utf-8", "replace")
    assert "export" in text, "bundle is not an ESM module"
    assert "esm.sh" not in text, "bundle still references esm.sh (not self-contained)"
    # Exports exactly what the page imports.
    for symbol in ("EditorView", "basicSetup", "markdown", "markdownLanguage", "oneDark"):
        assert symbol in text, f"bundle missing exported symbol {symbol!r}"


def test_handler_serves_vendor_bundle() -> None:
    """A GET for the vendor path returns the bundle bytes with a JS content-type,
    in the production profile too (no dev/prod feature split)."""

    class _FakeClient:
        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
            return {}

    handler_cls = make_handler(
        client=_FakeClient(),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
    )
    instance = handler_cls.__new__(handler_cls)
    instance.path = CODEMIRROR_MODULE_URL
    instance.headers = {}

    status: list[int] = []
    headers: dict[str, str] = {}
    sink = io.BytesIO()
    instance.send_response = lambda sc: status.append(sc)  # type: ignore[method-assign]
    instance.send_header = lambda k, v: headers.__setitem__(k, v)  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.wfile = sink  # type: ignore[assignment]

    instance.do_GET()

    assert status == [200], f"expected 200 for vendor asset, got {status}"
    assert "javascript" in headers.get("Content-Type", "")
    assert len(sink.getvalue()) > 100_000, "handler served an implausibly small body"


def test_body_edit_degrades_to_textarea_when_bundle_unreachable() -> None:
    """The offline fallback (plain textarea) and its wiring are present, so a
    failed editor load keeps the write path usable rather than dead."""
    for html in (_dev_page(), _prod_page()):
        # The fallback <textarea> is injected by the editor script's catch block,
        # so its testid appears as a JS string literal rather than static markup.
        assert "workspace-body-edit-fallback" in html
        assert "body-edit-fallback-textarea" in html
        # bodyEditor.submit/reset read the fallback element when CodeMirror is absent.
        assert "_cmFallbackTextarea" in html
