#!/usr/bin/env python3
"""Generate every Yggdrasil token output from the DTCG token source.

``tokens/*.json`` (except ``css-values.json``) are W3C Design Tokens (DTCG) files:
dimensions and durations are ``{"value", "unit"}``, cubic-beziers are arrays,
font families are arrays, and aliases use ``{token-name}``. ``css-values.json``
holds the CSS-native values DTCG cannot express exactly; they are emitted verbatim.

Usage:
    python3 design-system/yggdrasil/build.py          # write all outputs
    python3 design-system/yggdrasil/build.py --check  # exit 1 if any output is stale

Outputs are generated artifacts. Edit the files under ``tokens/`` and ``css/``,
never the outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

CSS_OUTPUTS = (
    "companion-ui/companion-app/colors_and_type.css",
    "app/web/static/colors_and_type.css",
)
# Tokens only (no element defaults or v1 utility classes), for surfaces that
# own their base styles, such as the Companion workspace pages.
# Written inside companion-ui/companion-app/ so the Companion image (which copies
# only that directory) serves it.
TOKENS_CSS_OUTPUT = "companion-ui/companion-app/yggdrasil-tokens.css"
# The same tokens-only sheet for the web Builder surfaces served from app/web/static.
TOKENS_CSS_OUTPUTS = (TOKENS_CSS_OUTPUT, "app/web/static/yggdrasil-tokens.css")
SWIFT_OUTPUT = "design-system/yggdrasil/dist/YggdrasilTokens.swift"
JSON_OUTPUT = "design-system/yggdrasil/dist/tokens.json"

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500"
    "&family=Space+Grotesk:wght@300;400;500;600"
    "&family=JetBrains+Mono:wght@400;500&display=swap');"
)


def _tokens(relative: str) -> dict[str, dict[str, str]]:
    payload = json.loads((HERE / "tokens" / relative).read_text(encoding="utf-8"))
    return payload["tokens"]


def load() -> dict[str, object]:
    css_values = json.loads((HERE / "tokens" / "css-values.json").read_text(encoding="utf-8"))
    return {
        "version": (HERE / "VERSION").read_text(encoding="utf-8").strip(),
        "primitives": _tokens("primitives.json"),
        "dark": _tokens("themes/dark.json"),
        "shell": _tokens("themes/shell.json"),
        "semantic": _tokens("semantic.json"),
        "css_dark": css_values["root"],
        "css_shell": css_values["shell"],
        "comfortable": _tokens("density/comfortable.json"),
        "compact": _tokens("density/compact.json"),
    }


_ALIAS = re.compile(r"^\{([a-z0-9-]+)\}$")


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


def css_value(entry: dict[str, object]) -> str:
    """Render one token value as CSS. DTCG aliases become var() references."""
    value, kind = entry["$value"], entry.get("$type")
    if isinstance(value, str):
        alias = _ALIAS.match(value)
        return f"var(--{alias.group(1)})" if alias else value
    if kind in ("dimension", "duration"):
        return f"{_num(value['value'])}{value['unit']}"
    if kind == "cubicBezier":
        return "cubic-bezier(" + ", ".join(_num(v) for v in value) + ")"
    if kind == "number":
        return _num(value)
    if kind == "fontFamily":
        return ", ".join(f"'{name}'" if " " in name else name for name in value)
    raise ValueError(f"cannot render {kind} value {value!r}")


def _block(
    selector: str, tokens: dict[str, dict[str, object]], indent: str = "", properties: tuple[str, ...] = ()
) -> str:
    lines = [f"{indent}{selector} {{"]
    lines += [f"{indent}  {prop};" for prop in properties]
    for name, entry in tokens.items():
        note = f"   /* {entry['$description']} */" if entry.get("$description") else ""
        lines.append(f"{indent}  --{name}: {css_value(entry)};{note}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def root_tokens(src: dict[str, object]) -> dict[str, dict[str, object]]:
    return {**src["dark"], **src["primitives"], **src["semantic"], **src["css_dark"], **src["comfortable"]}


def shell_overrides(src: dict[str, object]) -> dict[str, dict[str, object]]:
    return {**src["shell"], **src["css_shell"]}


REDUCED_MOTION = (
    "/* ============================================================\n   ACCESSIBILITY — reduced motion (always on)\n   ============================================================ */\n"
    "@media (prefers-reduced-motion: reduce) {\n"
    "  :root {\n    --duration-fast: 0ms;\n    --duration-base: 0ms;\n    --duration-slow: 0ms;\n  }\n"
    "  .fx-city::before, .fx-city::after, .fx-city > body::before, .fx-city > body::after { animation: none; }\n}"
)


def render_css(src: dict[str, object], *, include_base: bool = True) -> str:
    version = src["version"]
    shell_tokens = shell_overrides(src)
    header = (
        "/* ============================================================\n"
        f"   Yggdrasil Design System v{version} — Colors & Type\n"
        "   ============================================================\n"
        "   GENERATED from design-system/yggdrasil/ by build.py. Do not edit;\n"
        "   change the token source and run: python3 design-system/yggdrasil/build.py\n"
        "   Themes: Yggdrasil Dark (default) and Yggdrasil Light \"Shell\" (trial,\n"
        "   data-theme=\"light\" or \"system\"). Density: data-density=\"compact\".\n"
        "   ============================================================ */\n"
    )
    parts = [
        header,
        FONT_IMPORT,
        "",
        "/* ============================================================\n   BASE TOKENS — Yggdrasil Dark (default)\n   ============================================================ */",
        _block(":root", root_tokens(src)),
        "",
        *(
            [(HERE / "css" / "base.css").read_text(encoding="utf-8").rstrip("\n"), ""]
            if include_base
            else []
        ),
        "/* ============================================================\n   THEME — Yggdrasil Light \"Shell\" (trial, opt-in)\n   ============================================================ */",
        _block(':root[data-theme="light"]', shell_tokens, properties=("color-scheme: light",)),
        "",
        "@media (prefers-color-scheme: light) {\n"
        + _block(':root[data-theme="system"]', shell_tokens, "  ", properties=("color-scheme: light",))
        + "\n}",
        "",
        "/* ============================================================\n   DENSITY — compact (opt-in)\n   ============================================================ */",
        _block('[data-density="compact"]', src["compact"]),
        "",
        (HERE / "css" / "optin.css").read_text(encoding="utf-8").rstrip("\n"),
        "",
        REDUCED_MOTION,
    ]
    return "\n".join(parts) + "\n"


_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
_RGBA = re.compile(r"^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)$")
def resolve(tokens: dict[str, dict[str, object]], name: str, depth: int = 0) -> dict[str, object] | None:
    """Follow DTCG aliases to the entry that holds a concrete value."""
    entry = tokens.get(name)
    if entry is None or depth > 8:
        return None
    alias = _ALIAS.match(entry["$value"]) if isinstance(entry["$value"], str) else None
    return resolve(tokens, alias.group(1), depth + 1) if alias else entry


def resolve_colors(theme: dict[str, dict[str, object]]) -> dict[str, tuple[int, float]]:
    """Resolve colour roles to (rgb, opacity), following DTCG aliases."""

    def value(name: str) -> str | None:
        entry = resolve(theme, name)
        return entry["$value"] if entry and isinstance(entry["$value"], str) else None

    out: dict[str, tuple[int, float]] = {}
    for name, entry in theme.items():
        if entry.get("$type") != "color":
            continue
        raw = value(name)
        if raw is None:
            continue
        if hexm := _HEX.match(raw):
            out[name] = (int(hexm.group(1), 16), 1.0)
        elif rgba := _RGBA.match(raw):
            r, g, b = (int(rgba.group(i)) for i in (1, 2, 3))
            out[name] = ((r << 16) | (g << 8) | b, float(rgba.group(4)))
    return out


def theme_roles(src: dict[str, object], theme: str) -> dict[str, dict[str, str]]:
    roles = {**src["dark"], **src["semantic"]}
    if theme == "shell":
        roles.update(src["shell"])
    return roles


def _camel(name: str) -> str:
    head, *rest = name.split("-")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def render_swift(src: dict[str, object]) -> str:
    lines = [
        f"// GENERATED from design-system/yggdrasil/ (v{src['version']}) by build.py. Do not edit.",
        "import SwiftUI",
        "",
        "public enum YggdrasilTokens {",
        f"    public static let version = \"{src['version']}\"",
    ]
    for enum, theme in (("Dark", "dark"), ("Shell", "shell")):
        lines.append(f"    public enum {enum} {{")
        for name, (rgb, alpha) in resolve_colors(theme_roles(src, theme)).items():
            opacity = "" if alpha == 1.0 else f", opacity: {alpha}"
            lines.append(f"        public static let {_camel(name)} = Color(yggHex: 0x{rgb:06X}{opacity})")
        lines.append("    }")
    for enum, prefix in (("Spacing", "space-"), ("Radius", "radius-")):
        lines.append(f"    public enum {enum} {{")
        for name, entry in src["primitives"].items():
            value = entry["$value"]
            if name.startswith(prefix) and entry.get("$type") == "dimension" and value["unit"] == "px":
                lines.append(f"        public static let {_camel(name)}: CGFloat = {_num(value['value'])}")
        lines.append("    }")
    lines += [
        "}",
        "",
        "extension Color {",
        "    init(yggHex hex: UInt32, opacity: Double = 1) {",
        "        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,",
        "                  blue: Double(hex & 0xFF) / 255, opacity: opacity)",
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def flatten(src: dict[str, object]) -> dict[str, object]:
    """Every token per theme with aliases resolved to concrete CSS values."""

    def resolved(tokens: dict[str, dict[str, object]]) -> dict[str, str]:
        def one(name: str, depth: int = 0) -> str:
            value = css_value(resolve(tokens, name))
            ref = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)
            if ref and ref.group(1) in tokens and depth < 8:
                return one(ref.group(1), depth + 1)
            if depth < 8:
                # Inline references inside composite values (e.g. the Shell city
                # backdrop's palette colours) resolve to their static defaults.
                value = re.sub(
                    r"var\(--([a-z0-9-]+)\)",
                    lambda m: one(m.group(1), depth + 1) if m.group(1) in tokens else m.group(0),
                    value,
                )
            return value

        return {name: one(name) for name in tokens}

    dark = root_tokens(src)
    shell = {**dark, **shell_overrides(src)}
    return {
        "version": src["version"],
        "themes": {"dark": resolved(dark), "shell": resolved(shell)},
        "density": {"comfortable": resolved(src["comfortable"]), "compact": resolved(src["compact"])},
    }


def render_all(src: dict[str, object] | None = None) -> dict[str, str]:
    src = src or load()
    css = render_css(src)
    outputs = {path: css for path in CSS_OUTPUTS}
    tokens_only = render_css(src, include_base=False).replace(
        "— Colors & Type", "— Tokens only (no element defaults)", 1
    )
    outputs.update({path: tokens_only for path in TOKENS_CSS_OUTPUTS})
    outputs[SWIFT_OUTPUT] = render_swift(src)
    outputs[JSON_OUTPUT] = json.dumps(flatten(src), indent=2, ensure_ascii=False) + "\n"
    return outputs


def stale_outputs(root: Path = REPO_ROOT, outputs: dict[str, str] | None = None) -> list[str]:
    outputs = outputs or render_all()
    stale = []
    for relative, text in outputs.items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(relative)
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if any output is stale")
    args = parser.parse_args(argv)
    outputs = render_all()
    if args.check:
        stale = stale_outputs(outputs=outputs)
        for relative in stale:
            print(f"stale: {relative}")
        return 1 if stale else 0
    for relative, text in outputs.items():
        path = REPO_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
