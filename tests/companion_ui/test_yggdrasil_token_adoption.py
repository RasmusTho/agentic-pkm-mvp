"""YDS-03 (#5629): Companion surfaces consume the generated Yggdrasil tokens.

- Named Companion modules carry no hex colours beyond their listed, justified exceptions;
  colours come from the served tokens sheet.
- ``var(--fg-3)`` never colours readable text: it is decorative-only in Yggdrasil v2.
- Yggdrasil Light "Shell" is a per-user display preference that is off by default.
"""

from __future__ import annotations

import re
from pathlib import Path

from companion_ui.workspace.serve_dev_page import YGGDRASIL_TOKENS_URL, vendor_static_assets
from companion_ui.workspace.settings_drawer import DISPLAY_PREF_CANONICAL
from tests.companion_ui.test_display_preferences import _html as render_workspace_html

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "companion-ui" / "companion-app"
PKG = APP / "companion_ui"

# Module -> justified hex literals that may remain.
HEX_CEILINGS: dict[str, tuple[str, ...]] = {
    # The help-guide error page renders when help_guide.html is missing, so it
    # cannot rely on the tokens sheet; the two authority-state colours have no
    # Yggdrasil role (a purple receipt tone and a neutral local tone).
    "workspace/serve_dev_page.py": ("#dce8f0", "#070b12", "#b98be0", "#6b7a90"),
    "workspace/settings_drawer.py": (),
    "workspace/system_map_overlay.py": (),
    "workspace/memory_review_drawer.py": (),
    "workspace/receipts_history.py": (),
    "workspace/vault_settings_panel.py": (),
    "workspace/guidance_layer.py": (),
    "workspace/overlay_host.py": (),
    "workspace/capture_modal.py": (),
    "renderer/link_preview.py": (),
    "renderer/note_outline.py": (),
}

FG3_CONSUMERS = [PKG / module for module in HEX_CEILINGS] + [
    APP / "canvas_suggestion_flow.html",
    APP / "canvas_suggestion_flow.css",
    APP / "converse_layout.html",
    APP / "converse_layout.css",
    APP / "panel_visual_shell.html",
    PKG / "workspace" / "help_guide.html",
]

# Not a colour: HTML entities such as "&#160;" are excluded by the lookbehind.
_HEX = re.compile(r"(?<![&\w])#[0-9a-fA-F]{6}\b|(?<![&\w])#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])")
_FG3_DECL = re.compile(r"(?P<prop>[a-z-]+)\s*:\s*[^;{}]*var\(--fg-3\b")
_FG3_ALLOWED_SELECTOR = re.compile(r"::placeholder|:disabled|\[disabled\]|\[aria-disabled")


def _selector_for(lines: list[str], index: int) -> str:
    while index > 0 and "{" not in lines[index]:
        index -= 1
    return lines[index].split("{")[0].strip()


def test_companion_modules_use_tokens_within_hex_ceiling() -> None:
    over = {}
    for module, allowed in HEX_CEILINGS.items():
        found = _HEX.findall((PKG / module).read_text(encoding="utf-8"))
        extra = sorted(set(found) - set(allowed))
        if extra or len(found) > len(allowed):
            over[module] = found
    assert over == {}
    # The tokens are actually served, so the removed inline copies are replaced.
    sheet = vendor_static_assets()[YGGDRASIL_TOKENS_URL][1].decode("utf-8")
    assert "--bg-base: #070b12;" in sheet
    assert ':root[data-theme="light"]' in sheet
    assert "SEMANTIC ELEMENT DEFAULTS" not in sheet


def test_fg3_only_on_allowlisted_selectors() -> None:
    readable = []
    for path in FG3_CONSUMERS:
        lines = path.read_text(encoding="utf-8").split("\n")
        for index, line in enumerate(lines):
            for match in _FG3_DECL.finditer(line):
                if match.group("prop") == "color" and not _FG3_ALLOWED_SELECTOR.search(_selector_for(lines, index)):
                    readable.append(f"{path.relative_to(REPO_ROOT)}:{index + 1}")
    assert readable == []


def test_light_theme_is_per_user_opt_in() -> None:
    html = render_workspace_html()
    # Tokens are linked, the page opts in to the v2 focus ring, and no theme is
    # forced: Dark is the default until the user chooses Light.
    assert f'<link rel="stylesheet" href="{YGGDRASIL_TOKENS_URL}">' in html
    assert '<html lang="en" data-focus="v2">' in html
    assert 'data-theme="light"' not in html.split("<head>", 1)[0]
    assert DISPLAY_PREF_CANONICAL["theme"] == "dark"
    # The choice is a display preference in the settings drawer, off by default.
    select = html.split('data-testid="display-pref-theme"', 1)[1].split("</select>", 1)[0]
    assert '<option value="dark">Dark</option>' in select
    assert '<option value="light">Light — Shell (trial)</option>' in select
    # It persists through the shipped per-user display-preference storage and
    # sets data-theme="light" only when the stored choice is "light".
    script = html[html.index("var storageKey = 'companion.displayPreferences.v1'") :]
    script = script[: script.index("</script>")]
    assert "theme: 'dark'" in script
    assert "if (prefs.theme === 'light') {\n        root.setAttribute('data-theme', 'light');" in script
    assert "root.removeAttribute('data-theme');" in script
    assert "window.localStorage.setItem(storageKey, JSON.stringify(prefs));" in script
    # The pre-paint bootstrap reads the same key so a Light choice does not flash Dark.
    assert (
        "if(p.theme==='light')document.documentElement.setAttribute('data-theme','light');" in html
    )


def test_every_token_reference_resolves() -> None:
    """Removing hex fallbacks must not leave a var(--x) that nothing defines (e.g. --danger)."""
    sheet = vendor_static_assets()[YGGDRASIL_TOKENS_URL][1].decode("utf-8")
    defined = set(re.findall(r"--([a-z0-9-]+)\s*:", sheet))
    sources = [path.read_text(encoding="utf-8") for path in FG3_CONSUMERS if path.suffix == ".py"]
    for text in sources:
        defined |= set(re.findall(r"--([a-z0-9-]+)\s*:", text))
        defined |= set(re.findall(r"setProperty\(\s*'--([a-z0-9-]+)'", text))
    used = {name for text in sources for name in re.findall(r"var\(--([a-z0-9-]+)\)", text)}
    assert sorted(used - defined) == []


def test_components_never_branch_on_theme() -> None:
    """Theme is a pure token/material swap: no consumer CSS selects on data-theme."""
    branching = [
        str(path.relative_to(REPO_ROOT))
        for path in FG3_CONSUMERS
        if re.search(r"\[data-theme[=\]]", path.read_text(encoding="utf-8"))
    ]
    assert branching == []


def test_orientation_pages_do_not_apply_the_stored_theme() -> None:
    """Orientation pages have no settings drawer, so they stay on the canonical Dark render."""
    from tests.companion_ui.test_reentry_orientation_treatment import _render_no_vault_orientation

    html = _render_no_vault_orientation()
    assert f'<link rel="stylesheet" href="{YGGDRASIL_TOKENS_URL}">' in html
    assert "document.documentElement.setAttribute('data-theme'" not in html


def test_missing_tokens_sheet_fails_startup(tmp_path, monkeypatch) -> None:
    import companion_ui.workspace.serve_dev_page as page

    monkeypatch.setattr(page, "_VENDOR_STATIC_CACHE", None)
    monkeypatch.setattr(page, "_YGGDRASIL_TOKENS_PATH", tmp_path / "missing.css")
    try:
        page.vendor_static_assets()
    except RuntimeError as exc:
        assert "yggdrasil" in str(exc).lower()
    else:
        raise AssertionError("a missing tokens sheet must stop startup")
