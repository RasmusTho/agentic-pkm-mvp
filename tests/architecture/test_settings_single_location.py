from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CODE_ROOTS = ("api", "app", "mimer_runtime", "ops", "scripts", "tools")
SHELL_ROOTS = ("ops", "scripts", "tools")
CONFIG_ROOTS = (".github", "config", "configs", "ops", "scripts", "tools")
ALLOWED_COMPAT_LITERALS = {
    Path("app/settings/health_settings.py"): {"Settings/health.md"},
    Path("app/settings/locations.py"): {
        "@Settings",
        "_system/settings",
        "_system/settings/system-settings.yaml",
        "_system/Settings",
        "_system/Settings/health.md",
    },
    Path("app/settings/migration.py"): {"Settings/health.md"},
    Path("app/vault/manager.py"): {
        "@Settings",
        "_system/settings",
        "_system/Settings",
    },
    Path("app/watcher/settings_delta.py"): {"Settings/health.md"},
}
LEGACY_SEGMENTS = ("@Settings", "_system/settings", "_system/Settings")
SETTINGS_ARTIFACT_NAMES = {
    "agents.md",
    "global.md",
    "flows.settings.yaml",
    "health.md",
    "ingest.override.md",
    "llm_routing.md",
    "models.md",
    "providers.md",
    "routing.md",
    "standards.md",
    "system-settings.md",
    "system-settings.yaml",
    "watchers.md",
    "classifier.md",
    "companion-ui.md",
    "design-handoff.md",
    "embeddings.md",
    "instance.md",
    "local.md",
    "paths.md",
    "promotion.md",
    "qa.md",
    "reviewer.md",
    "vault.md",
    "workflow.md",
    "yggdrasil.md",
}


def _is_sanctioned_artifact_path(path_value: Path) -> bool:
    name = path_value.name
    if (
        len(path_value.parts) >= 2
        and path_value.parts[-2] == "agents"
        and path_value.suffix == ".md"
    ):
        suffix = ("settings", "agents", name)
        return (
            path_value.parts == suffix
            or path_value.parts[-4:] == ("vault", *suffix)
            or path_value.parts[-4:] == ("docs", *suffix)
            or path_value.parts[-4:] == ("VAULT_ROOT", *suffix)
        )
    canonical_suffix = ("settings", name)
    return (
        path_value.parts == canonical_suffix
        or path_value.parts[-3:] == ("vault", *canonical_suffix)
        or path_value.parts[-3:] == ("docs", *canonical_suffix)
        or path_value.parts[-3:] == ("VAULT_ROOT", *canonical_suffix)
    )


def _artifact_mentions(text: str) -> list[str]:
    names = "|".join(re.escape(name) for name in sorted(SETTINGS_ARTIFACT_NAMES))
    pattern = re.compile(rf"[A-Za-z0-9_@.:-]+(?:/[A-Za-z0-9_@.:-]+)*/(?:{names})")
    mentions = [match.group(0) for match in pattern.finditer(text)]
    agent_pattern = re.compile(
        r"[A-Za-z0-9_@.:-]+(?:/[A-Za-z0-9_@.:-]+)*/agents/[A-Za-z0-9_@.:-]+\.md"
    )
    mentions.extend(match.group(0) for match in agent_pattern.finditer(text))
    return list(dict.fromkeys(mentions))


def _literal_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return _literal_path(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _literal_path(node.left)
        right = _literal_path(node.right)
        if left is not None and right is not None:
            return f"{left.rstrip('/')}/{right.lstrip('/')}"
        if right is not None:
            return right
    return None


def _python_path_violations(relative: Path, source: str) -> set[str]:
    violations: set[str] = set()
    tree = ast.parse(source, filename=str(relative))
    for node in ast.walk(tree):
        value = _literal_path(node)
        if value is None:
            continue
        # Settings artifact paths never contain whitespace. Ignoring prose
        # constants keeps this structural gate focused on executable paths.
        if any(character.isspace() for character in value):
            continue
        normalized = value.replace("\\", "/")
        is_enumerated_compat_literal = normalized in ALLOWED_COMPAT_LITERALS.get(
            relative, set()
        )
        if not is_enumerated_compat_literal and any(
            segment in normalized for segment in LEGACY_SEGMENTS
        ):
            violations.add(f"{relative}:{node.lineno}: {value!r}")
        path_value = Path(normalized.removeprefix("vault://"))
        if (
            (
                path_value.name in SETTINGS_ARTIFACT_NAMES
                or (
                    len(path_value.parts) >= 2
                    and path_value.parts[-2] == "agents"
                    and path_value.suffix == ".md"
                )
            )
            and len(path_value.parts) > 1
            and not _is_sanctioned_artifact_path(path_value)
            and not is_enumerated_compat_literal
        ):
            violations.add(
                f"{relative}:{node.lineno}: settings artifact outside canonical root {value!r}"
            )
    return violations


def test_settings_artifact_path_shapes() -> None:
    for allowed in (
        "settings/llm_routing.md",
        "vault/settings/flows.settings.yaml",
        "settings/agents/classifier.md",
        "vault/settings/agents/reviewer.md",
        "docs/settings/flows.settings.yaml",
    ):
        assert _is_sanctioned_artifact_path(Path(allowed)), allowed
    for forbidden in (
        "other/llm_routing.md",
        "other/flows.settings.yaml",
        "other/settings/global.md",
        "vault/other/agents/classifier.md",
        "vault/rogue/agents/summarizer.md",
        "rogue/embeddings.md",
        "rogue/workflow.md",
        "rogue/system-settings.yaml",
    ):
        assert not _is_sanctioned_artifact_path(Path(forbidden)), forbidden

    mentions = _artifact_mentions(
        'path: "other/llm_routing.md"\nflow: other/flows.settings.yaml\n'
        "agent: vault/rogue/agents/summarizer.md\n"
        "embed: rogue/embeddings.md\n"
        "legacy: rogue/system-settings.yaml\n"
    )
    assert set(mentions) == {
        "other/llm_routing.md",
        "other/flows.settings.yaml",
        "vault/rogue/agents/summarizer.md",
        "rogue/embeddings.md",
        "rogue/system-settings.yaml",
    }


def test_compat_module_exemption_does_not_bypass_artifact_shape_gate() -> None:
    relative = Path("app/settings/locations.py")

    assert not _python_path_violations(relative, 'legacy = Path("@Settings")')
    assert _python_path_violations(relative, 'legacy = Path("@Settings/rogue")')
    violations = _python_path_violations(
        relative, 'rogue = Path("rogue/global.md")'
    )
    assert any("outside canonical root" in violation for violation in violations)


def test_production_scan_roots_cover_operational_surfaces() -> None:
    assert {"ops", "tools"}.issubset(PRODUCTION_CODE_ROOTS)
    assert {"ops", "tools"}.issubset(SHELL_ROOTS)
    assert {"configs", "ops", "tools"}.issubset(CONFIG_ROOTS)


def test_no_new_settings_paths() -> None:
    violations: set[str] = set()
    code_paths = [
        path
        for root_name in PRODUCTION_CODE_ROOTS
        for path in (ROOT / root_name).rglob("*.py")
        if (ROOT / root_name).is_dir()
    ]
    for path in sorted(code_paths):
        relative = path.relative_to(ROOT)
        violations.update(
            _python_path_violations(relative, path.read_text(encoding="utf-8"))
        )
    shell_paths = [
        path
        for root_name in SHELL_ROOTS
        for path in (ROOT / root_name).rglob("*.sh")
        if (ROOT / root_name).is_dir()
    ]
    for path in sorted(shell_paths):
        relative = path.relative_to(ROOT)
        normalized = path.read_text(encoding="utf-8").replace("\\", "/")
        for segment in LEGACY_SEGMENTS:
            if segment in normalized:
                violations.add(f"{relative}: shell contains retired settings path {segment!r}")
        for mention in _artifact_mentions(normalized):
            candidate = Path(mention.removeprefix("vault://"))
            if not _is_sanctioned_artifact_path(candidate):
                violations.add(
                    f"{relative}: shell contains noncanonical settings artifact {mention!r}"
                )
    operational_paths = {
        *(
            path
            for root_name in CONFIG_ROOTS
            for suffix in ("*.yml", "*.yaml")
            for path in (ROOT / root_name).rglob(suffix)
            if (ROOT / root_name).is_dir()
        ),
        *ROOT.glob("*compose*.yml"),
        *ROOT.glob("*compose*.yaml"),
    }
    for path in sorted(operational_paths):
        relative = path.relative_to(ROOT)
        normalized = path.read_text(encoding="utf-8").replace("\\", "/")
        for segment in LEGACY_SEGMENTS:
            if segment in normalized:
                violations.add(f"{relative}: operational config contains retired settings path {segment!r}")
        for mention in _artifact_mentions(normalized):
            candidate = Path(mention.removeprefix("vault://"))
            if not _is_sanctioned_artifact_path(candidate):
                violations.add(
                    f"{relative}: operational config contains noncanonical settings artifact {mention!r}"
                )
    assert not violations, (
        "new settings locations are forbidden outside the compat seam:\n"
        + "\n".join(sorted(violations))
    )
