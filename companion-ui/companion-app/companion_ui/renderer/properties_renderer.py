"""Read-only frontmatter properties renderer for Companion UI.

Properties display is intentionally inert. If editing frontmatter is requested,
route that work through Panel/governance instead of adding a renderer write path.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import html
from io import StringIO

from companion_ui.renderer.models import MarkdownDiagnostic, VaultMarkdownDocument


_FRONTMATTER_DIAGNOSTIC_CODES = frozenset(
    {
        "frontmatter_parse_error",
        "frontmatter_unterminated",
    }
)


@dataclass(frozen=True)
class PropertyField:
    key: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class RenderedProperties:
    html: str
    fields: tuple[PropertyField, ...]
    diagnostics: tuple[MarkdownDiagnostic, ...]
    write_calls: tuple[str, ...] = ()


class PropertiesRenderer:
    """Render YAML frontmatter as compact, read-only metadata HTML."""

    def __init__(
        self,
        *,
        test_id: str = "vault-properties",
        include_empty: bool = False,
    ) -> None:
        self._test_id = test_id
        self._include_empty = include_empty

    def render(self, document: VaultMarkdownDocument) -> RenderedProperties:
        diagnostics = tuple(
            diagnostic
            for diagnostic in document.diagnostics
            if diagnostic.code in _FRONTMATTER_DIAGNOSTIC_CODES
        )
        if document.frontmatter is None:
            if diagnostics:
                return self._render_diagnostic(diagnostics)
            return self._render_empty(diagnostics)
        if diagnostics:
            return self._render_diagnostic(diagnostics)

        fields = tuple(parse_frontmatter_fields(document.frontmatter))
        return RenderedProperties(
            html=self._render_fields(fields),
            fields=fields,
            diagnostics=diagnostics,
        )

    def _render_empty(self, diagnostics: tuple[MarkdownDiagnostic, ...]) -> RenderedProperties:
        if not self._include_empty:
            return RenderedProperties(html="", fields=(), diagnostics=diagnostics)
        html = (
            '<section class="vault-properties vault-properties-empty" '
            f'data-testid="{_e(self._test_id)}" '
            'data-frontmatter-present="false" '
            'data-readonly="true">'
            '<span class="vault-properties-label">No frontmatter</span>'
            "</section>"
        )
        return RenderedProperties(html=html, fields=(), diagnostics=diagnostics)

    def _render_diagnostic(self, diagnostics: tuple[MarkdownDiagnostic, ...]) -> RenderedProperties:
        items = "".join(
            '<li class="vault-properties-diagnostic" '
            f'data-diagnostic-code="{_e(diagnostic.code)}" '
            f'data-diagnostic-severity="{_e(diagnostic.severity)}">'
            f"{_e(diagnostic.message)}</li>"
            for diagnostic in diagnostics
        )
        html = (
            '<section class="vault-properties vault-properties-invalid" '
            f'data-testid="{_e(self._test_id)}" '
            'data-frontmatter-present="true" '
            'data-frontmatter-valid="false" '
            'data-readonly="true">'
            '<div class="vault-properties-header">'
            '<span class="vault-properties-label">Properties</span>'
            "</div>"
            f'<ul class="vault-properties-diagnostics">{items}</ul>'
            "</section>"
        )
        return RenderedProperties(html=html, fields=(), diagnostics=diagnostics)

    def _render_fields(self, fields: tuple[PropertyField, ...]) -> str:
        rows = "".join(_render_property_field(field) for field in fields)
        if not rows:
            rows = '<div class="vault-property vault-property-empty">(empty frontmatter)</div>'
        return (
            '<section class="vault-properties" '
            f'data-testid="{_e(self._test_id)}" '
            'data-frontmatter-present="true" '
            'data-frontmatter-valid="true" '
            'data-readonly="true">'
            '<div class="vault-properties-header">'
            '<span class="vault-properties-label">Properties</span>'
            "</div>"
            f'<dl class="vault-properties-list">{rows}</dl>'
            "</section>"
        )


def parse_frontmatter_fields(frontmatter: str) -> tuple[PropertyField, ...]:
    fields: list[PropertyField] = []
    pending_key: str | None = None
    pending_values: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_key, pending_values
        if pending_key is not None:
            fields.append(PropertyField(key=pending_key, values=tuple(pending_values)))
        pending_key = None
        pending_values = []

    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith((" ", "\t", "-")):
            if pending_key is None:
                continue
            if stripped.startswith("-"):
                pending_values.append(_normalize_scalar(stripped[1:].strip()))
            else:
                pending_values.append(_normalize_scalar(stripped))
            continue

        flush_pending()
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip()
        value = raw_value.strip()
        if not normalized_key:
            continue
        if value:
            fields.append(PropertyField(key=normalized_key, values=_parse_value(value)))
        else:
            pending_key = normalized_key
            pending_values = []

    flush_pending()
    return tuple(fields)


def _parse_value(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return ()
        return tuple(_normalize_scalar(item) for item in _split_inline_list(inner))
    return (_normalize_scalar(stripped),)


def _split_inline_list(value: str) -> tuple[str, ...]:
    reader = csv.reader(StringIO(value), skipinitialspace=True)
    try:
        row = next(reader)
    except csv.Error:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return tuple(part.strip() for part in row if part.strip())


def _normalize_scalar(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _render_property_field(field: PropertyField) -> str:
    key = field.key
    values = field.values
    property_type = "tags" if key == "tags" else "aliases" if key == "aliases" else "value"
    value_html = _render_property_values(values, property_type=property_type)
    return (
        '<div class="vault-property" '
        f'data-property-key="{_e(key)}" '
        f'data-property-type="{_e(property_type)}">'
        f"<dt>{_e(key)}</dt>"
        f"<dd>{value_html}</dd>"
        "</div>"
    )


def _render_property_values(values: tuple[str, ...], *, property_type: str) -> str:
    if not values:
        return '<span class="vault-property-empty-value">(empty)</span>'
    if property_type == "tags":
        return "".join(
            '<span class="vault-property-tag" data-readonly="true">'
            f"{_e(value)}</span>"
            for value in values
        )
    return "".join(
        '<span class="vault-property-value" data-readonly="true">'
        f"{_e(value)}</span>"
        for value in values
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
