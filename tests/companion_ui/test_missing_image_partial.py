"""Renderer degraded-state coverage for missing image partials."""

from __future__ import annotations

from companion_ui.renderer import render_vault_markdown


def test_missing_image_dashed_rectangle() -> None:
    rendered = render_vault_markdown("![alt text](attachments/missing.png)")

    assert 'data-testid="missing-image"' in rendered.html
    assert 'data-asset-state="missing"' in rendered.html
    assert (
        "<code>missing.png</code> &mdash; "
        "not found at <code>attachments/missing.png</code>"
    ) in rendered.html
    assert '<figcaption class="missing-image-alt">alt text</figcaption>' in rendered.html
