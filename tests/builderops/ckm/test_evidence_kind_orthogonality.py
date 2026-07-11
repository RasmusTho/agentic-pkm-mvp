"""INV-CKM-6 / OD-K3 fitness check: the CKM never touches the runtime
`evidence_role` dimension.

This asserts against the real package on disk (production call-site level):
it parses every ``.py`` file under ``app/builderops/ckm/`` with ``ast`` and
fails if any module imports a known runtime semantic-dimension module, or
references the runtime-reserved identifiers ``evidence_role``,
``authority_state``, or ``source_role`` anywhere (name, attribute, or string
literal). It is not a mock: it walks the actual shipped source tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CKM_PACKAGE_DIR = REPO_ROOT / "app" / "builderops" / "ckm"

# The runtime `evidence_role` dimension and its neighbors (INV-CKM-6). CKM's
# `evidence_kind` must never read, write, or map onto these.
FORBIDDEN_IDENTIFIERS = frozenset({"evidence_role", "authority_state", "source_role"})

# Modules known to define or carry the runtime evidence_role / semantic
# context dimension. The CKM package must never import from these.
FORBIDDEN_IMPORT_PREFIXES = (
    "app.retrieval",
    "app.context_dimensions",
    "app.agents",
    "app.heimdal",
    "app.expansion",
)


def _iter_ckm_python_files() -> list[Path]:
    assert CKM_PACKAGE_DIR.is_dir(), f"CKM package missing: {CKM_PACKAGE_DIR}"
    files = sorted(CKM_PACKAGE_DIR.rglob("*.py"))
    assert files, f"no Python files found under {CKM_PACKAGE_DIR}"
    return files


def _imported_module_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.module else []
    return [alias.name for alias in node.names]


def test_ckm_never_touches_runtime_evidence_role() -> None:
    violations: list[str] = []

    for path in _iter_ckm_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        rel_path = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for module_name in _imported_module_names(node):
                    if module_name and any(
                        module_name == prefix or module_name.startswith(f"{prefix}.")
                        for prefix in FORBIDDEN_IMPORT_PREFIXES
                    ):
                        violations.append(
                            f"{rel_path}:{node.lineno}: forbidden import of runtime module "
                            f"'{module_name}'"
                        )
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_IDENTIFIERS:
                violations.append(f"{rel_path}:{node.lineno}: forbidden identifier '{node.id}'")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_IDENTIFIERS:
                violations.append(f"{rel_path}:{node.lineno}: forbidden attribute '{node.attr}'")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in FORBIDDEN_IDENTIFIERS:
                    violations.append(
                        f"{rel_path}:{node.lineno}: forbidden string literal '{node.value}'"
                    )

    if violations:
        pytest.fail(
            "CKM orthogonality violation(s) — evidence_kind must stay orthogonal to the "
            "runtime evidence_role dimension (INV-CKM-6, OD-K3):\n" + "\n".join(violations)
        )
