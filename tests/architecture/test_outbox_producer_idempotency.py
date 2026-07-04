"""KERNEL-02 (#2764) grep gate: no outbox producer may omit the idempotency key.

Repo-wide static gate over ``app/``:

1. every ``write_outbox_event(...)`` callsite passes an explicit
   ``idempotency_key=`` keyword (the signature makes a keyless call a
   ``TypeError``; this gate catches it before runtime), and
2. every module that calls ``write_outbox_event`` derives its key through the
   single shared helper ``app.services.outbox.derive_idempotency_key`` (directly
   or via ``insert_object_and_outbox``) instead of inventing an ad-hoc scheme.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

# The defining module: write_outbox_event/derive_idempotency_key live here and
# insert_object_and_outbox derives its key inline, so the helper reference is
# the definition itself.
DEFINING_MODULE = APP_ROOT / "services" / "outbox.py"


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _iter_write_outbox_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "write_outbox_event":
            yield node


def test_no_keyless_callsites() -> None:
    keyless: list[str] = []
    missing_helper: list[str] = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        calls = list(_iter_write_outbox_calls(tree))
        for call in calls:
            if not any(kw.arg == "idempotency_key" for kw in call.keywords):
                keyless.append(f"{path.relative_to(APP_ROOT.parent)}:{call.lineno}")
        if calls and path != DEFINING_MODULE and "derive_idempotency_key" not in source:
            missing_helper.append(str(path.relative_to(APP_ROOT.parent)))

    assert not keyless, (
        "write_outbox_event callsites without an explicit idempotency_key= "
        f"(KERNEL-02 mandates deterministic keys on every outbox insert): {keyless}"
    )
    assert not missing_helper, (
        "modules calling write_outbox_event without the shared derivation helper "
        f"derive_idempotency_key (no ad-hoc key schemes): {missing_helper}"
    )


def test_write_outbox_event_signature_requires_key() -> None:
    """The optional-key path must not come back: keyword-only, no default."""
    tree = ast.parse(DEFINING_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "write_outbox_event":
            kwonly = {arg.arg: default for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)}
            assert "idempotency_key" in kwonly, "idempotency_key must be keyword-only"
            assert kwonly["idempotency_key"] is None, "idempotency_key must have no default"
            return
    raise AssertionError("write_outbox_event definition not found in app/services/outbox.py")
