from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

FieldMeta = Tuple[str, Any, str, Optional[List[str]], Optional[str]]

BEGIN = "<!-- BEGIN:settings:reference -->"
END = "<!-- END:settings:reference -->"


def _field_allowed(field) -> Optional[List[str]]:
    if hasattr(field.annotation, "__args__") and getattr(field.annotation, "__origin__", None) is None:
        return None
    constraints = getattr(field, "json_schema_extra", None)
    if isinstance(constraints, dict):
        allowed = constraints.get("allowed")
        if isinstance(allowed, list):
            return [str(item) for item in allowed]
    return None


def model_meta(model: BaseModel) -> Dict[str, FieldMeta]:
    meta: Dict[str, FieldMeta] = {}
    for name, field in model.__class__.model_fields.items():  # type: ignore[attr-defined]
        annotation = getattr(field.annotation, "__name__", str(field.annotation))
        default = field.default if field.default is not None else ""
        desc = field.description or ""
        allowed = _field_allowed(field)
        rng = None
        meta[name] = (annotation, default, desc, allowed, rng)
    return meta


def render_reference(title: str, model: BaseModel) -> str:
    meta = model_meta(model)
    lines = [
        f"### Reference — {title}",
        "",
        "| key | type | default | allowed | description |",
        "|-----|------|---------|---------|-------------|",
    ]
    for key, (typ, default, desc, allowed, _) in meta.items():
        allowed_str = ", ".join(allowed) if allowed else ""
        description = str(desc).replace("\n", " ")
        lines.append(f"| `{key}` | `{typ}` | `{default}` | `{allowed_str}` | {description} |")
    return "\n".join(lines)


def inject_reference(markdown: str, block: str) -> str:
    if BEGIN in markdown and END in markdown:
        head, tail = markdown.split(BEGIN, 1)
        _, remainder = tail.split(END, 1)
        return f"{head}{BEGIN}\n{block}\n{END}{remainder}"
    return markdown.rstrip() + f"\n\n{BEGIN}\n{block}\n{END}\n"
