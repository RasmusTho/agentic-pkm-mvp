"""YDS-04 (#5630): the web Builder surfaces consume the generated Yggdrasil tokens.

Covers Signboard, the legacy dashboard, the Cockpit, and the CKM overview. The managed
DevUI is out of scope here (#5637). Print styles are a deliberate exception: they
switch to black-on-white for paper and are excluded from the hex ceiling.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.builderops.ckm.overview_html import render_overview_html
from tests.builderops.ckm.test_overview_html import overview_store  # noqa: F401  (fixture)

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / "app" / "web" / "static"
TOKENS_SHEET = STATIC / "yggdrasil-tokens.css"
BINDING_SHEET = STATIC / "colors_and_type.css"

BUILDER_SURFACES = [
    STATIC / "signboard.css",
    STATIC / "signboard.html",
    STATIC / "signboard.js",
    STATIC / "index.html",
    STATIC / "cockpit.css",
    STATIC / "cockpit.js",
    STATIC / "cockpit.html",
    REPO_ROOT / "app" / "builderops" / "ckm" / "overview_html.py",
]
# Pages and the sheet each one loads. The Cockpit keeps the full binding sheet it
# already used; the others own their base styles and load the tokens-only sheet.
PAGES = {
    STATIC / "signboard.html": "/static/yggdrasil-tokens.css",
    STATIC / "index.html": "/static/yggdrasil-tokens.css",
    STATIC / "cockpit.html": "/static/colors_and_type.css",
}

_HEX = re.compile(r"(?<![&\w])#[0-9a-fA-F]{6}\b|(?<![&\w])#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])")
_READABLE_FG3 = re.compile(r"(?<![\w-])color:\s*var\(--fg-3\)")


def _without_print_blocks(text: str) -> str:
    out, index = [], 0
    while (start := text.find("@media print", index)) >= 0:
        out.append(text[index:start])
        depth, cursor = 0, text.index("{", start)
        while True:
            depth += {"{": 1, "}": -1}.get(text[cursor], 0)
            cursor += 1
            if depth == 0:
                break
        index = cursor
    out.append(text[index:])
    return "".join(out)


def test_builder_surfaces_use_tokens_within_hex_ceiling() -> None:
    offenders = {
        str(path.relative_to(REPO_ROOT)): _HEX.findall(_without_print_blocks(path.read_text(encoding="utf-8")))
        for path in BUILDER_SURFACES
    }
    assert {path: found for path, found in offenders.items() if found} == {}
    for page, sheet in PAGES.items():
        html = page.read_text(encoding="utf-8")
        assert f'<link rel="stylesheet" href="{sheet}">' in html, page.name
        assert '<html lang="en" data-density="compact" data-focus="v2">' in html, page.name


def test_fg3_only_on_allowlisted_selectors() -> None:
    readable = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in BUILDER_SURFACES
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1)
        if _READABLE_FG3.search(line)
    ]
    assert readable == []


def test_builder_token_references_resolve() -> None:
    defined = set(re.findall(r"--([a-z0-9-]+)\s*:", TOKENS_SHEET.read_text(encoding="utf-8")))
    defined |= set(re.findall(r"--([a-z0-9-]+)\s*:", BINDING_SHEET.read_text(encoding="utf-8")))
    unresolved = {}
    for path in BUILDER_SURFACES:
        text = path.read_text(encoding="utf-8")
        local = set(re.findall(r"--([a-z0-9-]+)\s*:", text)) | set(re.findall(r"setProperty\(\s*['\"]--([a-z0-9-]+)", text))
        missing = sorted(set(re.findall(r"var\(--([a-z0-9-]+)", text)) - defined - local)
        if missing:
            unresolved[str(path.relative_to(REPO_ROOT))] = missing
    assert unresolved == {}


def test_ckm_overview_embeds_the_generated_tokens(overview_store) -> None:  # noqa: F811
    rendered = render_overview_html(overview_store)
    assert "--bg-base: #070b12;" in rendered
    assert ':root[data-theme="light"]' in rendered
    assert "@import" not in rendered
    assert "--healthy:var(--vault); --unknown:var(--fg-2);" in rendered
    assert '<html lang="en" data-density="compact" data-focus="v2">' in rendered


def test_focus_rules_keep_the_v2_ring() -> None:
    """Pages opt in to data-focus="v2"; no local focus rule may suppress it or restore the 1px glow ring."""
    offenders = []
    for path in BUILDER_SURFACES:
        text = path.read_text(encoding="utf-8")
        for selector, body in re.findall(r"([^{}]*:focus[^{}]*)\{+([^{}]*)\}", text):
            flat = " ".join(body.split())
            if re.search(r"outline:\s*(none|0\b|1px)", flat) or "cyan-glow" in flat:
                offenders.append(f"{path.name}: {selector.strip()[-60:]}")
    assert offenders == []
