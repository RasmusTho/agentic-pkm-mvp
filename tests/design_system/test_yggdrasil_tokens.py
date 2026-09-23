"""YDS-01 (#5627): the generated Yggdrasil token outputs.

The fixture ``colors_and_type.v1.css`` is the hand-maintained sheet as it was before
v2. It is the compatibility baseline: v2 may add tokens and opt-in rules, but it must
not change any v1 token or rule.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DS = REPO_ROOT / "design-system" / "yggdrasil"
BINDING = REPO_ROOT / "companion-ui" / "companion-app" / "colors_and_type.css"
V1 = Path(__file__).resolve().parent / "fixtures" / "colors_and_type.v1.css"

OPT_IN_MARKERS = ('[data-theme="light"]', '[data-theme="system"]', '[data-density="compact"]', '[data-focus="v2"]', ".fx-")


def _build():
    spec = importlib.util.spec_from_file_location("yggdrasil_build", DS / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _root_tokens(css: str) -> dict[str, str]:
    css = _strip_comments(css)
    start = css.index(":root {")
    body = css[start + len(":root {") : css.index("\n}", start)]
    return {name: " ".join(value.split()) for name, value in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body)}


def _rules(css: str) -> list[tuple[str, str]]:
    """Top-level (selector, normalized body) pairs, excluding the first :root token block."""
    css = _strip_comments(css)
    root_end = css.index("\n}", css.index(":root {")) + 2
    rules, depth, selector_start, body_start = [], 0, root_end, 0
    for index in range(root_end, len(css)):
        char = css[index]
        if char == "{":
            if depth == 0:
                selector = " ".join(css[selector_start:index].split())
                body_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append((selector, " ".join(css[body_start:index].split())))
                selector_start = index + 1
    return rules


def _luminance(rgb: int) -> float:
    channels = [((rgb >> shift) & 0xFF) / 255 for shift in (16, 8, 0)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_generated_binding_sheet_preserves_every_dark_token_value() -> None:
    v1 = _root_tokens(V1.read_text(encoding="utf-8"))
    generated = _root_tokens(BINDING.read_text(encoding="utf-8"))
    assert len(v1) == 95
    changed = {name: (value, generated.get(name)) for name, value in v1.items() if generated.get(name) != value}
    assert changed == {}


def test_new_rules_are_opt_in_and_legacy_rules_unchanged() -> None:
    v1_rules = _rules(V1.read_text(encoding="utf-8"))
    generated_rules = _rules(BINDING.read_text(encoding="utf-8"))
    missing = [rule for rule in v1_rules if rule not in generated_rules]
    assert missing == []
    legacy_focus = [rule for rule in generated_rules if rule[0] == ":focus-visible"]
    assert legacy_focus == [rule for rule in v1_rules if rule[0] == ":focus-visible"]
    added = [rule for rule in generated_rules if rule not in v1_rules]
    assert added, "v2 should add opt-in rules"
    not_opt_in = [
        selector
        for selector, body in added
        if not any(marker in selector or marker in body for marker in OPT_IN_MARKERS)
    ]
    assert not_opt_in == []


def test_generated_outputs_are_fresh(tmp_path: Path) -> None:
    build = _build()
    outputs = build.render_all()
    assert build.stale_outputs(outputs=outputs) == []
    for relative, text in outputs.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    edited = tmp_path / build.CSS_OUTPUTS[0]
    edited.write_text(edited.read_text(encoding="utf-8").replace("#070b12", "#070b13", 1), encoding="utf-8")
    assert build.stale_outputs(root=tmp_path, outputs=outputs) == [build.CSS_OUTPUTS[0]]


def test_role_surface_pairs_meet_wcag_aa() -> None:
    build = _build()
    source = build.load()
    contract = json.loads((DS / "tokens" / "contrast.json").read_text(encoding="utf-8"))
    failures = []
    for theme, pairs in contract["themes"].items():
        colors = build.resolve_colors(build.theme_roles(source, theme))
        assert not set(contract["decorative_only"]) & set(pairs["text"])
        for text in pairs["text"]:
            for surface in pairs["surfaces"]:
                (fg, fg_alpha), (bg, bg_alpha) = colors[text], colors[surface]
                assert fg_alpha == 1.0 and bg_alpha == 1.0
                light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
                ratio = (light + 0.05) / (dark + 0.05)
                if ratio < contract["minimum"]:
                    failures.append((theme, text, surface, round(ratio, 2)))
    assert failures == []


def test_swift_and_json_outputs_match_token_source() -> None:
    build = _build()
    source = build.load()
    swift = (REPO_ROOT / build.SWIFT_OUTPUT).read_text(encoding="utf-8")
    for enum, theme in (("Dark", "dark"), ("Shell", "shell")):
        section = swift.split(f"public enum {enum} {{", 1)[1].split("\n    }", 1)[0]
        for name, (rgb, _alpha) in build.resolve_colors(build.theme_roles(source, theme)).items():
            assert f"static let {build._camel(name)} = Color(yggHex: 0x{rgb:06X}" in section, (enum, name)
    assert f'version = "{source["version"]}"' in swift
    flattened = json.loads((REPO_ROOT / build.JSON_OUTPUT).read_text(encoding="utf-8"))
    assert flattened == build.flatten(source)
    assert flattened["themes"]["dark"]["accent"] == "#d4a843"
    assert flattened["themes"]["shell"]["accent"] == "#6b4d00"


def test_font_imports_use_google_fonts_only() -> None:
    css = BINDING.read_text(encoding="utf-8")
    imports = re.findall(r"@import url\('([^']+)'\)", css)
    assert imports
    assert all(url.startswith("https://fonts.googleapis.com/") for url in imports)
    assert "JetBrains+Mono" in imports[0]
    assert "bunny.net" not in css
