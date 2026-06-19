"""CRE-03 glance surface: renders vault-native moments, pull-only.

The companion-UI "now" surface is a read-only projection of materialized
moments. It renders them with source-linked provenance and shows no proactive
reach-out (no notification / push / alert affordance).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.relevance import (
    DeterministicRelevanceEvaluator,
    collect_now_moments,
    materialize_moment,
)
from app.vault.manager import VaultContext
from companion_ui.workspace.now_surface import render_now_surface_html

TODAY = date(2026, 6, 13)


def _build_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# 2026-06-13\n", encoding="utf-8")
    note = vault / "Projects" / "Contextual Relevance Engine.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\ndue: 2026-06-15\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )
    return vault


def test_now_surface_renders_vault_native_moments_pull_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _build_vault(tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    ctx = VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))

    moments = DeterministicRelevanceEvaluator(vault, today=TODAY).evaluate()
    assert moments
    materialize_moment(moments[0], vault_context=ctx, outbox_path=tmp_path / "r.jsonl")

    views = collect_now_moments(ctx)
    assert views, "glance surface should have materialized moments to render"
    html = render_now_surface_html(views)

    # Renders the computed moment, each linking to its source with provenance.
    assert 'data-testid="now-surface"' in html
    assert "Start of day — 2026-06-13" in html
    assert "Projects/Contextual Relevance Engine.md" in html
    assert "finish the scarcity gate" not in html  # source body is not copied in
    assert "Commitment due in 2 day" in html  # the source-linked "why" pointer is present

    # Pull-only: no proactive reach-out affordance whatsoever.
    assert 'data-pull-only="true"' in html
    assert 'data-surface="glance"' in html
    lowered = html.lower()
    for token in ("notification", "push", "alert", "<button"):
        assert token not in lowered, f"glance surface must not include a {token} affordance"


def test_ref_href_blocks_dangerous_scheme() -> None:
    """#2153 — a dangerous URL scheme on a ref must never reach the rendered href."""
    moment = {
        "moment_id": "m1",
        "title": "Moment",
        "surfaced_refs": [
            {"ref": "javascript:alert(1)", "why": "evil"},
            {"ref": "Projects/Contextual Relevance Engine.md", "why": "safe"},
        ],
    }
    html = render_now_surface_html([moment])
    hrefs = re.findall(r'href="([^"]*)"', html)

    # The dangerous scheme must not survive into any href (latent stored XSS).
    assert 'href="javascript' not in html.lower()
    assert not any("javascript:" in href.lower() for href in hrefs)
    # The label is still shown as inert text, just without a clickable href.
    assert "alert(1)" in html
    # A normal vault-relative ref still produces a working, space-encoded href.
    assert 'href="Projects/Contextual%20Relevance%20Engine.md"' in html


def test_empty_refs_omits_ul() -> None:
    """#2163 — a moment with no surfaced_refs renders no empty <ul>."""
    no_refs = {"moment_id": "m1", "title": "Moment", "surfaced_refs": []}
    absent = {"moment_id": "m2", "title": "Moment"}

    assert '<ul class="moment-refs">' not in render_now_surface_html([no_refs])
    assert '<ul class="moment-refs">' not in render_now_surface_html([absent])

    # When refs DO exist, the list is still rendered.
    with_ref = {
        "moment_id": "m3",
        "title": "Moment",
        "surfaced_refs": [{"ref": "Notes/x.md", "why": "linked"}],
    }
    assert '<ul class="moment-refs">' in render_now_surface_html([with_ref])


def test_protocol_relative_ref_is_not_live_href() -> None:
    """#2180 — a protocol-relative ref (//host) must not render a live external href."""
    moment = {
        "moment_id": "m1",
        "title": "Moment",
        "surfaced_refs": [
            {"ref": "//evil.com/pwn", "why": "open-redirect"},
            {"ref": "/\\evil.com/pwn", "why": "backslash variant"},
        ],
    }
    html = render_now_surface_html([moment])
    hrefs = re.findall(r'href="([^"]*)"', html)

    # Both protocol-relative refs render inert (no href at all) — asserted
    # structurally rather than by fragile URL-substring matching.
    assert hrefs == []
    assert html.count('data-blocked-ref="true"') == 2


def test_ref_href_allows_vault_relative_and_http() -> None:
    """#2180 — genuine relative paths and http/https refs still render a working href."""
    moment = {
        "moment_id": "m1",
        "title": "Moment",
        "surfaced_refs": [
            {"ref": "Projects/Plan.md", "why": "vault"},
            {"ref": "https://example.com/doc", "why": "external https"},
        ],
    }
    html = render_now_surface_html([moment])
    assert 'href="Projects/Plan.md"' in html
    assert 'href="https://example.com/doc"' in html


def test_unparseable_ref_fails_closed_without_crashing() -> None:
    """#2180 — a ref that breaks urlsplit (invalid IPv6 literal) renders inert,
    never aborting the whole surface."""
    moment = {
        "moment_id": "m1",
        "title": "Moment",
        "surfaced_refs": [
            {"ref": "/\\[bad", "why": "malformed"},
            {"ref": "Notes/ok.md", "why": "valid alongside"},
        ],
    }
    html = render_now_surface_html([moment])  # must not raise
    assert 'data-blocked-ref="true"' in html  # the malformed ref is inert
    assert 'href="Notes/ok.md"' in html  # the valid sibling still renders
