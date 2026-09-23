#!/usr/bin/env python3
"""Generate every Yggdrasil token output from the DTCG token source.

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
    return {
        "version": (HERE / "VERSION").read_text(encoding="utf-8").strip(),
        "primitives": _tokens("primitives.json"),
        "dark": _tokens("themes/dark.json"),
        "shell": _tokens("themes/shell.json"),
        "semantic": _tokens("semantic.json"),
        "material_dark": _tokens("materials/dark.json"),
        "material_shell": _tokens("materials/shell.json"),
        "comfortable": _tokens("density/comfortable.json"),
        "compact": _tokens("density/compact.json"),
    }


def _block(selector: str, tokens: dict[str, dict[str, str]], indent: str = "") -> str:
    lines = [f"{indent}{selector} {{"]
    for name, entry in tokens.items():
        note = f"   /* {entry['$description']} */" if entry.get("$description") else ""
        lines.append(f"{indent}  --{name}: {entry['$value']};{note}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def render_css(src: dict[str, object]) -> str:
    version = src["version"]
    root_tokens = {**src["dark"], **src["primitives"], **src["semantic"], **src["material_dark"], **src["comfortable"]}
    shell_tokens = {**src["shell"], **src["material_shell"]}
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
        _block(":root", root_tokens),
        "",
        (HERE / "css" / "base.css").read_text(encoding="utf-8").rstrip("\n"),
        "",
        "/* ============================================================\n   THEME — Yggdrasil Light \"Shell\" (trial, opt-in)\n   ============================================================ */",
        _block(':root[data-theme="light"]', shell_tokens),
        "",
        "@media (prefers-color-scheme: light) {\n" + _block(':root[data-theme="system"]', shell_tokens, "  ") + "\n}",
        "",
        "/* ============================================================\n   DENSITY — compact (opt-in)\n   ============================================================ */",
        _block('[data-density="compact"]', src["compact"]),
        "",
        (HERE / "css" / "optin.css").read_text(encoding="utf-8").rstrip("\n"),
    ]
    return "\n".join(parts) + "\n"


_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
_RGBA = re.compile(r"^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)$")
_VAR = re.compile(r"^var\(--([a-z0-9-]+)\)$")


def resolve_colors(theme: dict[str, dict[str, str]]) -> dict[str, tuple[int, float]]:
    """Resolve colour roles to (rgb, opacity), following var() references."""

    def value(name: str, depth: int = 0) -> str | None:
        entry = theme.get(name)
        if entry is None or depth > 8:
            return None
        match = _VAR.match(entry["$value"])
        return value(match.group(1), depth + 1) if match else entry["$value"]

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
            if name.startswith(prefix) and entry["$value"].endswith("px"):
                lines.append(f"        public static let {_camel(name)}: CGFloat = {entry['$value'][:-2]}")
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
    plain = lambda tokens: {name: entry["$value"] for name, entry in tokens.items()}  # noqa: E731
    return {
        "version": src["version"],
        "primitives": plain(src["primitives"]),
        "themes": {
            "dark": plain({**src["dark"], **src["semantic"], **src["material_dark"]}),
            "shell": plain({**theme_roles(src, "shell"), **src["material_shell"]}),
        },
        "density": {"comfortable": plain(src["comfortable"]), "compact": plain(src["compact"])},
    }


def render_all(src: dict[str, object] | None = None) -> dict[str, str]:
    src = src or load()
    css = render_css(src)
    outputs = {path: css for path in CSS_OUTPUTS}
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
