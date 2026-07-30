from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _all_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            calls.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            calls.add(fn.attr)
    return calls


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _function_node(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected exactly one {name} in {path}"
    return matches[0]


def _call_names(node: ast.AST) -> list[str]:
    calls: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.append(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.append(child.func.attr)
    return calls


def test_note_locator_construction_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_calls = {
        REPO_ROOT / "app" / "knowledge" / "locators.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_calls:
                continue
            if "NoteLocator" in _all_calls(path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct NoteLocator(...) construction is forbidden outside app/knowledge/locators.py: "
        f"{offenders}"
    )


def test_obsidian_vault_name_env_is_read_only_in_vault_identity() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "vault_identity.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "OBSIDIAN_VAULT_NAME" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "OBSIDIAN_VAULT_NAME should be resolved only via app/knowledge/vault_identity.py: "
        f"{offenders}"
    )


def test_advanced_uri_builder_imports_are_constrained() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.references" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "build_obsidian_advanced_uri usage should stay in approved boundary modules: "
        f"{offenders}"
    )


def test_knowledge_adapters_are_resolved_only_via_service_boundary() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "service.py",
        # Candidate-only create-once publication reuses the existing private
        # descriptor-relative no-replace primitive without broadening the port.
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.adapters" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct app.knowledge.adapters imports are forbidden outside the service boundary: "
        f"{offenders}"
    )


def test_vault_note_writes_use_knowledge_port_helpers() -> None:
    guarded_files = {
        REPO_ROOT / "app" / "agents" / "note_hygiene" / "agent.py",
        REPO_ROOT / "app" / "services" / "vault_sync.py",
        REPO_ROOT / "app" / "services" / "note_uuid.py",
        REPO_ROOT / "app" / "settings" / "compiler.py",
        REPO_ROOT / "app" / "settings" / "writeback.py",
        REPO_ROOT / "app" / "settings" / "mimer_scaffolder.py",
        REPO_ROOT / "app" / "vault" / "layout.py",
        REPO_ROOT / "scripts" / "fs_watcher.py",
    }
    offenders: list[str] = []
    for path in guarded_files:
        if "write_text" in _all_calls(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Guarded vault-facing modules must not call Path.write_text directly; route writes via KnowledgePort helpers: "
        f"{offenders}"
    )


def test_knowledge_port_resolution_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "service.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "resolve_knowledge_port" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct resolve_knowledge_port usage is forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_absolute_locator_conversion_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "locators.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "make_note_locator_from_absolute" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct make_note_locator_from_absolute usage is forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_locator_module_imports_are_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "knowledge" / "adapters.py",
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "locators.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.locators" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct app.knowledge.locators imports are forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_legacy_fs_watcher_has_no_direct_vault_note_writes() -> None:
    watcher_path = REPO_ROOT / "scripts" / "fs_watcher.py"
    tree = ast.parse(watcher_path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "write_text":
            offenders.append(node.lineno)
    assert not offenders, (
        "Legacy fs watcher must write notes via VaultPort adapter methods, not direct Path.write_text: "
        f"{offenders}"
    )


def test_legacy_fs_watcher_does_not_depend_on_deprecated_sink_ports() -> None:
    watcher_path = REPO_ROOT / "scripts" / "fs_watcher.py"
    imports = _imports(watcher_path)
    assert "app.ports.sink" not in imports
    assert "app.ports.pg_sink" not in imports


def test_candidate_writer_topology_has_no_acquisition_long_lock() -> None:
    acquire_path = REPO_ROOT / "app" / "knowledge_acquisition" / "acquire.py"
    replay_path = REPO_ROOT / "app" / "knowledge_acquisition" / "replay.py"
    drain_path = REPO_ROOT / "app" / "knowledge_acquisition" / "acquisition_requests.py"
    writeback_path = REPO_ROOT / "app" / "knowledge_acquisition" / "candidate_writeback.py"

    def assert_function_calls(source: str, function_name: str, called_name: str) -> ast.FunctionDef:
        tree = ast.parse(source)
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        assert called_name in _call_names(function)
        return function

    def assert_default_drain_route(source: str) -> ast.FunctionDef:
        tree = ast.parse(source)
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "drain_one"
        )
        route_assignments = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "fn" for target in node.targets)
        ]
        assert len(route_assignments) == 1
        route_value = route_assignments[0].value
        assert isinstance(route_value, ast.BoolOp)
        assert isinstance(route_value.op, ast.Or)
        assert [value.id for value in route_value.values if isinstance(value, ast.Name)] == [
            "acquire_fn",
            "acquire_youtube",
        ]
        assert "fn" in _call_names(function)
        return function

    acquire_source = acquire_path.read_text(encoding="utf-8")
    replay_source = replay_path.read_text(encoding="utf-8")
    drain_source = drain_path.read_text(encoding="utf-8")
    acquire = assert_function_calls(
        acquire_source,
        "acquire_youtube",
        "write_candidate_note",
    )
    replay = assert_function_calls(replay_source, "run_replay", "write_candidate_note")
    drain = assert_default_drain_route(drain_source)

    forbidden_imports = {
        "fcntl",
        "multiprocessing",
        "threading",
    }
    assert _imports(writeback_path).isdisjoint(forbidden_imports)
    forbidden_calls = {"Lock", "RLock", "flock", "lockf", "Semaphore"}
    for function in (
        acquire,
        replay,
        drain,
        _function_node(writeback_path, "write_candidate_note"),
    ):
        assert set(_call_names(function)).isdisjoint(forbidden_calls)

    # Mutants preserve comments/docstrings but bypass a real function-scoped call.
    acquire_mutant = acquire_source.replace(
        "write_result: CandidateWriteResult = write_candidate_note(",
        "write_result: CandidateWriteResult = bypass_candidate_write(",
        1,
    )
    with pytest.raises(AssertionError):
        assert_function_calls(
            acquire_mutant,
            "acquire_youtube",
            "write_candidate_note",
        )

    replay_mutant = replay_source.replace(
        "write_result = write_candidate_note(",
        "write_result = bypass_candidate_write(",
        1,
    )
    with pytest.raises(AssertionError):
        assert_function_calls(replay_mutant, "run_replay", "write_candidate_note")

    with pytest.raises(AssertionError):
        assert_default_drain_route(
            drain_source.replace(
                "fn = acquire_fn or acquire_youtube",
                "fn = acquire_fn",
                1,
            )
        )


def test_create_once_stays_behind_knowledge_service_boundary() -> None:
    app_root = REPO_ROOT / "app"
    call_sites: list[tuple[str, str]] = []
    for path in _iter_py_files(app_root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if called != "create_candidate_note_once":
                continue
            owner: ast.AST | None = node
            while owner is not None and not isinstance(owner, ast.FunctionDef):
                owner = parents.get(owner)
            assert isinstance(owner, ast.FunctionDef)
            call_sites.append((str(path.relative_to(REPO_ROOT)), owner.name))

    assert call_sites == [
        # Meeting finalization (CDLM-08, #4388): create-once Sources-zone
        # artifacts written atomically through the same O_EXCL primitive,
        # WriteGuard-gated with its own action string.
        ("app/heimdal/meeting_finalization.py", "finalize_session"),
        ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ]
    writeback_path = app_root / "knowledge_acquisition" / "candidate_writeback.py"
    imports = [
        node
        for node in ast.walk(ast.parse(writeback_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.knowledge.write_ops"
        and any(alias.name == "create_candidate_note_once" for alias in node.names)
    ]
    assert len(imports) == 1

    acquisition_root = app_root / "knowledge_acquisition"
    for path in _iter_py_files(acquisition_root):
        assert "app.knowledge.adapters" not in _imports(path)
