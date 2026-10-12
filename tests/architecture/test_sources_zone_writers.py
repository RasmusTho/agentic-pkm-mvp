"""Fitness checks for the selected vault's Sources landing zone (#3414)."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

import app.knowledge_acquisition.candidate_writeback as candidate_writeback
from app.heimdal import (
    candidate_projection,
    cursor_store,
    meeting_finalization,
    meeting_ledger,
    observation_log,
)
from app.heimdal.publish import publish_observation
from app.knowledge_acquisition.candidate_writeback import (
    CandidateWritebackError,
    write_candidate_note,
)
from app.knowledge_acquisition.source_bundle import (
    SourceBundleError,
    materialize_youtube_source_bundle,
)
from app.knowledge_acquisition.source_frames import (
    CapturedFrame,
    SourceFramesError,
    _bundle_folder as source_frames_bundle_folder,
    capture_source_frames,
)
from app.mcp.vault_tools import VaultToolError, append_note
from app.settings.locations import canonical_settings_root
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_candidate_writeback import _assembled_candidate
from tests.knowledge_acquisition.test_source_frames import _moments as _source_moments
from tests.knowledge_acquisition.test_youtube_source_bundle import _source_material

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGURED_SOURCES = "ConfiguredSources"

# This is the full current writer census. Each public writer is exercised below through its
# production entry point; changing the census requires updating both the implementation map and
# the selected-vault assertions.
REGISTERED_SOURCE_WRITERS = {
    ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ("app/knowledge_acquisition/source_bundle.py", "materialize_youtube_source_bundle"),
    ("app/knowledge_acquisition/source_frames.py", "capture_source_frames"),
    ("app/heimdal/candidate_projection.py", "write_candidate_note"),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note"),
    ("app/heimdal/candidate_projection.py", "project_pending_candidates"),
    ("app/heimdal/meeting_finalization.py", "finalize_session"),
}

# Bare packaged names remain only in the resolver, read-only sampling, or pure path/classification
# helpers. These exact occurrences are reviewed exceptions; a new literal must be routed through
# the selected-vault resolver before it can be added here.
SOURCE_LITERAL_ALLOWLIST = {
    ("app/cli/alpha_human_flows.py", "_select_sample_files", "Sources"),
    ("app/heimdal/candidate_projection.py", "<module>", "Sources/Heimdal"),
    ("app/heimdal/candidate_projection.py", "<module>", "Sources/Reading/Karakeep"),
    ("app/heimdal/meeting_finalization.py", "<module>", "Sources/Meetings"),
    ("app/knowledge/adapters.py", "FsVaultAdapter.__init__", "Sources"),
    ("app/knowledge/multiwriter.py", "classify_note", "Sources"),
    ("app/knowledge/multiwriter.py", "classify_note_in_vault", "Sources"),
    ("app/knowledge_acquisition/candidate_writeback.py", "<module>", "Sources"),
    ("app/knowledge_acquisition/source_bundle.py", "<module>", "Sources/YouTube/_attachments"),
    ("app/vault/paths.py", "<module>", "Sources"),
}

# Every shipped Sources-root consumer is inventoried, including readers, resolver owners,
# classification helpers, bootstrap, app-agent, and capture exclusions. A new consumer fails this
# check until its role is understood and registered.
SOURCE_RESOLVER_CALLERS = {
    ("app/agents/panel_agent/policy.py", "watcher_panel_writeback_allowed"),
    ("app/api/routes/capture.py", "capture_to_inbox"),
    ("app/heimdal/candidate_projection.py", "write_candidate_note"),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note"),
    ("app/heimdal/candidate_projection.py", "project_pending_candidates"),
    ("app/heimdal/meeting_finalization.py", "meetings_dir_rel"),
    ("app/journaling/day_context.py", "_read_captures"),
    ("app/knowledge/service.py", "_build_adapter"),
    ("app/knowledge/service.py", "resolve_knowledge_port"),
    ("app/knowledge_acquisition/acquire.py", "_candidate_will_render"),
    ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ("app/knowledge_acquisition/source_bundle.py", "materialize_youtube_source_bundle"),
    ("app/knowledge_acquisition/source_frames.py", "_bundle_folder"),
    ("app/mcp/vault_tools.py", "append_note"),
    ("app/ops/karakeep_runtime.py", "child_preflight"),
    ("app/services/artifact_identity.py", "_is_create_once"),
    ("app/settings/mimer_scaffolder.py", "MimerScaffolder.scaffold"),
    ("app/vault/paths.py", "get_vault_sources_dir_rel"),
}

SOURCE_WRITE_EXCLUSIONS = {
    ("app/api/routes/capture.py", "capture_to_inbox"),
    ("app/mcp/vault_tools.py", "append_note"),
}

SOURCE_WRITE_SINKS = {
    "append_note_relative",
    "create_candidate_note_once",
    "write_note_from_absolute",
    "write_note_relative",
}
SOURCE_PATH_BUILDERS = {
    "_bundle_folder",
    "candidate_note_path",
    "get_vault_sources_dir_rel",
    "meetings_dir_rel",
    "reading_candidate_note_path",
    "resolve_vault_sources_dir_rel",
    "validate_youtube_attachment_root",
}


def _module_function_for(node_stack: list[ast.AST]) -> str:
    names = [
        node.name
        for node in node_stack
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not names:
        return "<module>"
    return ".".join(names[-2:]) if len(names) > 1 else names[-1]


def _source_code_inventory(repo_root: Path = REPO_ROOT) -> tuple[
    set[tuple[str, str, str]], set[tuple[str, str]], set[tuple[str, str]]
]:
    """Inventory Sources callers with a bounded, scope-aware AST binding model.

    The census follows visible app imports/re-exports and one path-helper -> sink-helper
    boundary. It deliberately does not evaluate Python or follow arbitrary dynamic calls.
    """
    literals: set[tuple[str, str, str]] = set()
    resolver_callers: set[tuple[str, str]] = set()
    source_write_callers: set[tuple[str, str]] = set()
    trees = {
        path.relative_to(repo_root).as_posix(): ast.parse(
            path.read_text(encoding="utf-8"), filename=path.relative_to(repo_root).as_posix()
        )
        for path in sorted((repo_root / "app").rglob("*.py"))
    }

    def module_for_file(relative: str) -> str:
        parts = relative[:-3].split("/")
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    module_for_relative = {relative: module_for_file(relative) for relative in trees}
    modules = {"app"}
    for module in module_for_relative.values():
        parts = module.split(".")
        modules.update(".".join(parts[:index]) for index in range(1, len(parts) + 1))

    def module_target(module: str) -> str:
        return f"module:{module}"

    def function_target(module: str, node: ast.AST, qualname: tuple[str, ...]) -> str:
        return f"function:{module}::{'.'.join(qualname)}@{node.lineno}"

    def module_import_name(
        node: ast.ImportFrom, current_module: str, relative: str
    ) -> str | None:
        if node.level == 0:
            return node.module
        current_parts = current_module.split(".")
        is_package_init = relative.endswith("/__init__.py") or relative == "app/__init__.py"
        package_parts = current_parts if is_package_init else current_parts[:-1]
        trim = node.level - 1
        if trim > len(package_parts):
            return None
        base = package_parts[: len(package_parts) - trim]
        if node.module:
            base.extend(node.module.split("."))
        return ".".join(base)

    # Identify every function by its full lexical identity, including source line. The
    # display labels used by the existing allowlists remain short and stable.
    function_by_node: dict[int, str] = {}
    function_nodes: dict[str, tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    parent_function: dict[str, str | None] = {}
    function_display: dict[str, str] = {}
    function_depth: dict[str, int] = {}
    module_stack: list[ast.AST] = []

    class FunctionIndex(ast.NodeVisitor):
        def __init__(self, relative: str) -> None:
            self.relative = relative
            self.module = module_for_relative[relative]

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            module_stack.append(node)
            self.generic_visit(node)
            module_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            lexical_nodes = [
                item
                for item in module_stack
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            qualname = tuple(item.name for item in lexical_nodes) + (node.name,)
            target = function_target(self.module, node, qualname)
            function_by_node[id(node)] = target
            function_nodes[target] = (self.relative, node)
            ancestors = [
                item
                for item in module_stack
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            parent_function[target] = (
                function_by_node[id(ancestors[-1])] if ancestors else None
            )
            function_depth[target] = len(ancestors)
            display_stack = [item for item in module_stack if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            display_stack.append(node)
            function_display[target] = _module_function_for(display_stack)
            module_stack.append(node)
            self.generic_visit(node)
            module_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    for relative, tree in trees.items():
        module_stack.clear()
        FunctionIndex(relative).visit(tree)

    module_specs: dict[str, dict[str, list[tuple[str, str]]]] = {
        module: {} for module in modules
    }
    module_targets: dict[str, dict[str, set[str]]] = {module: {} for module in modules}

    def add_binding(table: dict[str, set[str]], name: str, target: str) -> None:
        table.setdefault(name, set()).add(target)

    class ScopeBindings(ast.NodeVisitor):
        """Collect one lexical scope, walking branches but stopping at nested scopes."""

        def __init__(self, *, relative: str) -> None:
            self.relative = relative
            self.module = module_for_relative[relative]
            self.bindings: dict[str, set[str]] = {}
            self.from_specs: dict[str, list[tuple[str, str]]] = {}

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            target = function_by_node.get(id(node))
            if target:
                add_binding(self.bindings, node.name, target)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                if not alias.name.startswith("app"):
                    continue
                bound_name = alias.asname or alias.name.split(".")[0]
                bound_module = alias.name if alias.asname else alias.name.split(".")[0]
                if bound_module in modules:
                    add_binding(self.bindings, bound_name, module_target(bound_module))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            base = module_import_name(node, self.module, self.relative)
            if not base or not (base == "app" or base.startswith("app.")):
                return
            for alias in node.names:
                if alias.name == "*":
                    raise AssertionError(
                        f"static Sources census cannot resolve star import in {self.relative}:{node.lineno}; "
                        "replace it with explicit app imports"
                    )
                local_name = alias.asname or alias.name
                self.from_specs.setdefault(local_name, []).append((base, alias.name))

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Store):
                add_binding(self.bindings, node.id, "unknown:local-binding")

        def visit_arg(self, node: ast.arg) -> None:
            add_binding(self.bindings, node.arg, "unknown:local-argument")

    for relative, tree in trees.items():
        collector = ScopeBindings(relative=relative)
        for statement in tree.body:
            collector.visit(statement)
        table = module_targets[module_for_relative[relative]]
        for name, values in collector.bindings.items():
            table.setdefault(name, set()).update(values)
        for name, specs in collector.from_specs.items():
            module_specs[module_for_relative[relative]].setdefault(name, []).extend(
                specs
            )

    # Resolve package imports/re-exports to a fixed point over the finite app module graph.
    # Unions preserve all statically possible branch bindings; no execution order is guessed.
    changed = True
    while changed:
        changed = False
        for module, names in module_specs.items():
            for local_name, specs in names.items():
                for base, imported in specs:
                    before = len(module_targets[module].get(local_name, set()))
                    child_module = f"{base}.{imported}" if base else imported
                    if child_module in modules:
                        add_binding(module_targets[module], local_name, module_target(child_module))
                    for target in module_targets.get(base, {}).get(imported, set()):
                        add_binding(module_targets[module], local_name, target)
                    if len(module_targets[module].get(local_name, set())) != before:
                        changed = True

    def resolve_import_target(relative: str, base: str, imported: str) -> set[str]:
        found: set[str] = set()
        child_module = f"{base}.{imported}" if base else imported
        if child_module in modules:
            found.add(module_target(child_module))
        found.update(module_targets.get(base, {}).get(imported, set()))
        return found

    def scope_bindings(
        relative: str, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> dict[str, set[str]]:
        collector = ScopeBindings(relative=relative)
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
            *((function.args.vararg,) if function.args.vararg else ()),
            *((function.args.kwarg,) if function.args.kwarg else ()),
        ):
            collector.visit(argument)
        for statement in function.body:
            collector.visit(statement)
        result = {name: set(values) for name, values in collector.bindings.items()}
        for name, specs in collector.from_specs.items():
            for base, imported in specs:
                result.setdefault(name, set()).update(resolve_import_target(relative, base, imported))
        return result

    function_env: dict[str, dict[str, set[str]]] = {}
    for target in sorted(function_nodes, key=lambda item: function_depth[item]):
        relative, node = function_nodes[target]
        module = module_for_relative[relative]
        env = {name: set(values) for name, values in module_targets.get(module, {}).items()}
        parent = parent_function[target]
        if parent is not None:
            env.update({name: set(values) for name, values in function_env[parent].items()})
        local = scope_bindings(relative, node)
        env.update(local)
        function_env[target] = env

    def expression_targets(relative: str, expression: ast.expr, env: dict[str, set[str]]) -> set[str]:
        if isinstance(expression, ast.Name):
            if expression.id in env:
                return set(env[expression.id])
            if expression.id == "app":
                return {module_target("app")}
            return {f"symbol:{expression.id}"}
        if isinstance(expression, ast.Attribute):
            result: set[str] = set()
            for base_target in expression_targets(relative, expression.value, env):
                if base_target.startswith("module:"):
                    base = base_target.removeprefix("module:")
                    result.update(resolve_import_target(relative, base, expression.attr))
            # Preserve direct attribute calls used by the existing census, including
            # imported runtime objects whose implementation is outside app/.
            if expression.attr in SOURCE_PATH_BUILDERS | SOURCE_WRITE_SINKS | {
                "get_vault_sources_dir_rel",
                "resolve_vault_sources_dir_rel",
            }:
                result.add(f"symbol:{expression.attr}")
            return result
        return set()

    def function_named(target: str, names: set[str]) -> bool:
        if target.startswith("symbol:"):
            return target.removeprefix("symbol:") in names
        record = function_nodes.get(target)
        return bool(record and record[1].name in names)

    calls_by_function: dict[str, list[tuple[set[str], ast.Call]]] = {}
    for target, (relative, function) in function_nodes.items():
        calls: list[tuple[set[str], ast.Call]] = []

        class DirectCalls(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                return

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_Call(self, node: ast.Call) -> None:
                calls.append((expression_targets(relative, node.func, function_env[target]), node))
                self.generic_visit(node)

        visitor = DirectCalls()
        for statement in function.body:
            visitor.visit(statement)
        calls_by_function[target] = calls
        if any(
            any(function_named(callee, {"get_vault_sources_dir_rel", "resolve_vault_sources_dir_rel"}) for callee in callees)
            for callees, _call in calls
        ):
            resolver_callers.add((relative, function_display[target]))

    # Preserve literals and module-level resolver calls in the full source walk.
    for relative, tree in trees.items():
        module = module_for_relative[relative]
        env = {name: set(values) for name, values in module_targets.get(module, {}).items()}
        stack: list[ast.AST] = []

        class SourceFacts(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                stack.append(node)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, str) and (node.value == "Sources" or node.value.startswith("Sources/")):
                    literals.add((relative, _module_function_for(stack), node.value))

            def visit_Call(self, node: ast.Call) -> None:
                active_target = next(
                    (
                        function_by_node[id(item)]
                        for item in reversed(stack)
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and id(item) in function_by_node
                    ),
                    None,
                )
                active_env = function_env.get(active_target, env)
                if not any(
                    function_named(callee, {"get_vault_sources_dir_rel", "resolve_vault_sources_dir_rel"})
                    for callee in expression_targets(relative, node.func, active_env)
                ):
                    return self.generic_visit(node)
                active = function_display[active_target] if active_target else _module_function_for(stack)
                resolver_callers.add((relative, active))
                self.generic_visit(node)

        SourceFacts().visit(tree)

    builders_by_function = {
        target
        for target, calls in calls_by_function.items()
        if any(
            any(function_named(callee, SOURCE_PATH_BUILDERS) for callee in callees)
            for callees, _call in calls
        )
    }
    sinks_by_function = {
        target
        for target, calls in calls_by_function.items()
        if any(
            any(function_named(callee, SOURCE_WRITE_SINKS) for callee in callees)
            for callees, _call in calls
        )
    }
    source_write_callers.update(
        (function_nodes[target][0], function_display[target])
        for target in builders_by_function & sinks_by_function
    )

    # One explicit helper boundary: builder-containing helpers may feed a sink-containing
    # helper. Function IDs include full lexical scope and source line, avoiding basename
    # collisions between unrelated helpers.
    path_helpers = builders_by_function - sinks_by_function

    def is_source_path(relative: str, expression: ast.AST, env: dict[str, set[str]], names: set[str]) -> bool:
        for child in ast.walk(expression):
            if isinstance(child, ast.Name) and child.id in names:
                return True
            if isinstance(child, ast.Call):
                callees = expression_targets(relative, child.func, env)
                if any(
                    function_named(callee, SOURCE_PATH_BUILDERS)
                    or callee in path_helpers
                    for callee in callees
                ):
                    return True
        return False

    for target, calls in calls_by_function.items():
        relative, function = function_nodes[target]
        assignments: list[tuple[list[ast.expr], ast.expr]] = []

        class Assignments(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                return

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_Assign(self, node: ast.Assign) -> None:
                assignments.append((list(node.targets), node.value))
                self.generic_visit(node.value)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if node.value is not None:
                    assignments.append(([node.target], node.value))
                    self.generic_visit(node.value)

            def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
                assignments.append(([node.target], node.value))
                self.generic_visit(node.value)

        visitor = Assignments()
        for statement in function.body:
            visitor.visit(statement)
        source_names: set[str] = set()
        changed = True
        while changed:
            changed = False
            for targets, value in assignments:
                if is_source_path(relative, value, function_env[target], source_names):
                    for assigned in targets:
                        for child in ast.walk(assigned):
                            if isinstance(child, ast.Name) and child.id not in source_names:
                                source_names.add(child.id)
                                changed = True

        if any(
            any(
                callee in sinks_by_function or function_named(callee, SOURCE_WRITE_SINKS)
                for callee in callees
            )
            and any(
                is_source_path(relative, argument, function_env[target], source_names)
                for argument in (*call.args, *(keyword.value for keyword in call.keywords))
            )
            for callees, call in calls
        ):
            source_write_callers.add((relative, function_display[target]))

    return literals, resolver_callers, source_write_callers


def _configured_vault(root: Path, *, sources_dir: str = CONFIGURED_SOURCES) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    settings = canonical_settings_root(root) / "system-settings.md"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        "---\npaths:\n  sources_dir_rel: " + json.dumps(sources_dir) + "\n---\n",
        encoding="utf-8",
    )
    return VaultContext("selected", "vault-test", "Vault Test", str(root))


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _fixture_media():
    class FixtureMedia:
        def download_temporary_media(
            self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int
        ) -> Path:
            target = dest_dir / "fixture.mp4"
            target.write_bytes(b"fixture media")
            return target

        def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame:
            assert media_path.is_file()
            return CapturedFrame(
                image_bytes=b"\xff\xd8\xfffixture\xff\xd9",
                grayscale_32=bytes([127]) * (32 * 32),
            )

    return FixtureMedia()


def _publish_candidate_observation(*, karakeep: bool, observation_id: str) -> None:
    payload = {
        "observation_id": observation_id,
        "episode_id": observation_id,
        "content": f"Sensor candidate {observation_id}",
        "raw_ref": f"raw:{observation_id}",
        "provenance": {
            "sensor": "karakeep_rest" if karakeep else "fixture_sensor",
            "content_identity": "sha256:" + ("b" if karakeep else "a") * 64,
            "raw_ref": f"raw:{observation_id}",
            "capture_chain": ["fixture"],
        },
    }
    if karakeep:
        payload["content_structure"] = {
            "karakeep": {
                "item_kind": "link",
                "source_item_identity": observation_id,
                "source_url": "https://example.com/sources-zone",
                "tombstone": False,
            }
        }
    publish_observation(
        topic="heimdal.observation.published",
        observation_id=observation_id,
        payload=payload,
        source="test.sources-zone",
        stage_versions={"test": "1"},
    )


def _meeting_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vault: VaultContext) -> str:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", "9f" * 32)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "meeting-outbox.jsonl"))
    monkeypatch.setenv("HEIMDAL_MEETING_LEDGER_PATH", str(tmp_path / "meeting-ledger.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_PROJECTION_PATH", str(tmp_path / "meeting-projection.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_BLOCKS_PATH", str(tmp_path / "meeting-blocks.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_FINALIZATION_PATH", str(tmp_path / "meeting-finalization.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_VAULT_ROOT", str(vault.active_vault_path))
    session_id = f"zone-fitness-{uuid4()}"
    meeting_ledger.open_meeting_session(session_id=session_id, device_id="fixture-device")
    meeting_ledger.close_meeting_session(session_id=session_id, final_seq_count=0)
    return session_id


def test_zone_resolved_via_settings_not_literal() -> None:
    literals, resolver_callers, source_write_callers = _source_code_inventory()
    assert literals == SOURCE_LITERAL_ALLOWLIST
    assert resolver_callers == SOURCE_RESOLVER_CALLERS
    assert source_write_callers == REGISTERED_SOURCE_WRITERS | SOURCE_WRITE_EXCLUSIONS


def test_writer_inventory_follows_aliased_resolvers_and_write_helpers(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": "",
        "app/writers/__init__.py": (
            "from .exports import package_path as chain_path\n"
            "from .exports import package_sink as chain_sink\n"
        ),
        "app/writers/paths.py": (
            "def get_vault_sources_dir_rel():\n"
            "    return 'configured-sources'\n"
        ),
        "app/writers/inbox_paths.py": (
            "def get_vault_inbox_dir_rel():\n"
            "    return 'Inbox'\n"
        ),
        "app/writers/sinks.py": "def write_note_relative(path):\n    return path\n",
        "app/writers/helpers.py": (
            "import app.writers.paths as path_api\n"
            "from app.writers.sinks import write_note_relative as persist_note\n"
            "def build_source_path():\n"
            "    return path_api.get_vault_sources_dir_rel()\n"
            "def write_source_path(path):\n"
            "    return persist_note(path)\n"
        ),
        "app/writers/exports/__init__.py": (
            "from ..helpers import build_source_path as package_path\n"
            "from ..helpers import write_source_path as package_sink\n"
        ),
        "app/writers/relative.py": (
            "from . import helpers as helper_api\n"
            "from .sinks import write_note_relative as relative_sink\n"
            "def relative_sink_wrapper(path):\n"
            "    return relative_sink(path)\n"
            "def relative_import_writer():\n"
            "    path = helper_api.build_source_path()\n"
            "    return relative_sink_wrapper(path)\n"
        ),
        "app/writers/producer.py": (
            "from app.writers.helpers import build_source_path as make_path\n"
            "from app.writers.helpers import write_source_path as save_path\n"
            "from app.writers import chain_path, chain_sink\n"
            "from app.writers.paths import get_vault_sources_dir_rel as factory_resolve\n"
            "from app.writers.sinks import write_note_relative as factory_persist\n"
            "try:\n"
            "    from app.writers.helpers import build_source_path as try_path\n"
            "except ImportError:\n"
            "    from app.writers.helpers import build_source_path as try_path\n"
            "try:\n"
            "    from app.writers.helpers import write_source_path as try_sink\n"
            "except ImportError:\n"
            "    from app.writers.helpers import write_source_path as try_sink\n"
            "def newly_added_writer():\n"
            "    path = make_path()\n"
            "    return save_path(path)\n"
            "def package_reexport_writer():\n"
            "    path = chain_path()\n"
            "    return chain_sink(path)\n"
            "def try_import_writer():\n"
            "    path = try_path()\n"
            "    return try_sink(path)\n"
            "def branched_alias_writer(use_sources):\n"
            "    if use_sources:\n"
            "        from app.writers.paths import get_vault_sources_dir_rel as resolve_branch\n"
            "    else:\n"
            "        from app.writers.inbox_paths import get_vault_inbox_dir_rel as resolve_branch\n"
            "    from app.writers.sinks import write_note_relative as persist_branch\n"
            "    return persist_branch(f'{resolve_branch()}/branch.md')\n"
            "def unrelated_path_and_write_calls():\n"
            "    path = make_path()\n"
            "    return save_path('unrelated')\n"
            "def local_import_writer():\n"
            "    from app.writers.paths import get_vault_sources_dir_rel as resolve\n"
            "    from app.writers.sinks import write_note_relative as persist\n"
            "    return persist(f'{resolve()}/rogue.md')\n"
            "def nested_local_import_writer_3414():\n"
            "    from app.writers.paths import get_vault_sources_dir_rel as resolve_3414\n"
            "    from app.writers.sinks import write_note_relative as persist_3414\n"
            "    def make_path_3414():\n"
            "        return f'{resolve_3414()}/nested.md'\n"
            "    def persist_path_3414(path):\n"
            "        return persist_3414(path)\n"
            "    return persist_path_3414(make_path_3414())\n"
            "def shadowed_enclosing_resolver_3414():\n"
            "    from app.writers.paths import get_vault_sources_dir_rel as resolve_shadowed\n"
            "    from app.writers.sinks import write_note_relative as persist_shadowed\n"
            "    def write_inbox():\n"
            "        def resolve_shadowed():\n"
            "            return 'Inbox'\n"
            "        return persist_shadowed(resolve_shadowed())\n"
            "    return write_inbox()\n"
            "def factory_a_3414():\n"
            "    def make_path():\n"
            "        return f'{factory_resolve()}/a.md'\n"
            "    def persist_path(path):\n"
            "        return factory_persist(path)\n"
            "    def writer():\n"
            "        path = make_path()\n"
            "        return persist_path(path)\n"
            "    return writer()\n"
            "def factory_b_3414():\n"
            "    def make_path():\n"
            "        return 'Inbox/b.md'\n"
            "    def persist_path(path):\n"
            "        return path\n"
            "    def writer():\n"
            "        path = make_path()\n"
            "        return persist_path(path)\n"
            "    return writer()\n"
        ),
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    _literals, resolver_callers, source_write_callers = _source_code_inventory(tmp_path)

    assert ("app/writers/helpers.py", "build_source_path") in resolver_callers
    assert (
        "app/writers/producer.py",
        "nested_local_import_writer_3414.make_path_3414",
    ) in resolver_callers
    assert ("app/writers/producer.py", "newly_added_writer") in source_write_callers
    assert ("app/writers/producer.py", "package_reexport_writer") in source_write_callers
    assert ("app/writers/producer.py", "try_import_writer") in source_write_callers
    assert ("app/writers/producer.py", "branched_alias_writer") in source_write_callers
    assert ("app/writers/producer.py", "local_import_writer") in source_write_callers
    assert ("app/writers/producer.py", "nested_local_import_writer_3414") in source_write_callers
    assert ("app/writers/relative.py", "relative_import_writer") in source_write_callers
    assert ("app/writers/producer.py", "factory_a_3414.writer") in source_write_callers
    assert ("app/writers/producer.py", "factory_b_3414.writer") not in source_write_callers
    assert ("app/writers/producer.py", "shadowed_enclosing_resolver_3414.write_inbox") not in resolver_callers
    assert ("app/writers/producer.py", "shadowed_enclosing_resolver_3414.write_inbox") not in source_write_callers
    assert ("app/writers/producer.py", "unrelated_path_and_write_calls") not in source_write_callers


def test_writer_inventory_fails_closed_on_unresolved_star_import(tmp_path: Path) -> None:
    target = tmp_path / "app" / "writers.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("from app.helpers import *\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="cannot resolve star import"):
        _source_code_inventory(tmp_path)


def test_only_registered_writers_target_sources_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import objects as object_store_module
    from app.stores import reset_store_backends

    monkeypatch.delenv("VAULT_SOURCES_DIR_REL", raising=False)
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "Inbox/inbox.md")
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    vault = _configured_vault(tmp_path / "selected-vault")
    vault_root = Path(vault.active_vault_path or "")
    guard = _guard()
    observed: dict[str, str] = {}

    # YouTube candidate note and source bundle.
    youtube_candidate = _assembled_candidate()
    candidate_note = write_candidate_note(
        youtube_candidate, vault_context=vault, write_guard=guard
    )
    assert candidate_note.status == "written" and candidate_note.artifact_path
    observed["youtube_candidate"] = candidate_note.artifact_path

    proposal_candidate = replace(
        youtube_candidate, extraction_artifact_ids=("sources-zone-extraction",)
    )
    proposal = write_candidate_note(
        proposal_candidate,
        vault_context=vault,
        write_guard=guard,
        proposal_on_existing=True,
    )
    assert proposal.status == "proposal_written" and proposal.artifact_path
    observed["youtube_candidate_proposal"] = proposal.artifact_path

    _raw, transcript, bundle_candidate = _source_material(tmp_path / "youtube-material")
    bundle = materialize_youtube_source_bundle(
        bundle_candidate, transcript, vault_context=vault, write_guard=guard
    )
    assert bundle.status == "written"
    observed["youtube_bundle_transcript"] = bundle.transcript_path
    observed["youtube_bundle_manifest"] = bundle.manifest_path

    # The attached-frame writer is a separate production path under the same resolved root.
    moments, frame_transcript = _source_moments()
    frames = capture_source_frames(
        key_moments=moments,
        transcript=frame_transcript,
        item_ref="abcDEF12345",
        vault_context=vault,
        write_guard=guard,
        media_capture=_fixture_media(),
        temp_root=tmp_path / "media-temp",
    )
    assert frames.status == "frames_retained" and frames.manifest_path
    observed["youtube_frames_manifest"] = frames.manifest_path
    observed["youtube_frame"] = str(frames.frames[0]["path"])

    # Both Heimdal candidate classes use the real per-consumer projection entry point.
    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=False, observation_id="sources-zone-candidate")
    heimdal = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(heimdal) == 1 and heimdal[0].status == "written" and heimdal[0].artifact_path
    observed["heimdal_candidate"] = heimdal[0].artifact_path

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=True, observation_id="sources-zone-reading")
    reading = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(reading) == 1 and reading[0].status == "written" and reading[0].artifact_path
    observed["karakeep_reading_candidate"] = reading[0].artifact_path

    # Meeting close finalization writes the three registered material notes.
    session_id = _meeting_runtime(tmp_path, monkeypatch, vault)
    finalization = meeting_finalization.finalize_session(session_id)
    refs = finalization["receipt"]["artifact_refs"]
    observed.update({f"meeting_{name}": path for name, path in refs.items()})

    assert set(observed) == {
        "youtube_candidate",
        "youtube_candidate_proposal",
        "youtube_bundle_transcript",
        "youtube_bundle_manifest",
        "youtube_frames_manifest",
        "youtube_frame",
        "heimdal_candidate",
        "karakeep_reading_candidate",
        "meeting_transcript",
        "meeting_analysis",
        "meeting_user_notes",
    }
    assert all(path.startswith(f"{CONFIGURED_SOURCES}/") for path in observed.values())
    assert all((vault_root / path).is_file() for path in observed.values())

    # Each Sources producer rejects a target that overlaps the effective capture inbox before
    # publishing. These calls use the actual production writer entry points a second time.
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", candidate_note.artifact_path)
    with pytest.raises(CandidateWritebackError, match="overlaps effective capture note"):
        write_candidate_note(
            proposal_candidate,
            vault_context=vault,
            write_guard=guard,
            proposal_on_existing=True,
        )

    proposal_path = candidate_writeback._versioned_proposal_path(
        proposal_candidate, candidate_note.artifact_path
    )
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", proposal_path)
    with pytest.raises(CandidateWritebackError, match="overlaps effective capture note"):
        write_candidate_note(
            proposal_candidate,
            vault_context=vault,
            write_guard=guard,
            proposal_on_existing=True,
        )

    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", bundle.transcript_path)
    with pytest.raises(SourceBundleError, match="capture note"):
        materialize_youtube_source_bundle(
            bundle_candidate, transcript, vault_context=vault, write_guard=guard
        )

    alternate_frame_root = f"{CONFIGURED_SOURCES}/AlternateFrames"
    alternate_manifest = (
        source_frames_bundle_folder(
            vault_root,
            "abcDEF12345",
            frame_transcript,
            alternate_frame_root,
        )
        / "frames.json"
    ).as_posix()
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", alternate_manifest)
    with pytest.raises(SourceFramesError, match="overlaps effective capture note"):
        capture_source_frames(
            key_moments=moments,
            transcript=frame_transcript,
            item_ref="abcDEF12345",
            vault_context=vault,
            write_guard=guard,
            youtube_attachment_root=alternate_frame_root,
            media_capture=_fixture_media(),
            temp_root=tmp_path / "media-temp-retry",
        )

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=False, observation_id="sources-zone-candidate")
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", str(heimdal[0].artifact_path))
    blocked_candidate = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(blocked_candidate) == 1 and blocked_candidate[0].status == "blocked"

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=True, observation_id="sources-zone-reading")
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", str(reading[0].artifact_path))
    blocked_reading = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(blocked_reading) == 1 and blocked_reading[0].status == "blocked"

    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", refs["transcript"])
    with pytest.raises(meeting_finalization.MeetingFinalizationError, match="overlap the capture note"):
        meeting_finalization.finalize_session(session_id)

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    object_store_module._MEMORY_STORE.clear()
    reset_store_backends()


def test_capture_and_sources_zone_mutually_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.agents.panel_agent.policy import watcher_panel_writeback_allowed
    from app.api.app import app
    from tests.api._vault_test_helpers import bind_initialized_vault

    vault_root = tmp_path / "capture-vault"
    vault_root.mkdir()
    bind_initialized_vault(monkeypatch, vault_root, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "capture-outbox.jsonl"))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)

    response = TestClient(app).post(
        "/api/companion/capture", json={"text": "must not enter Sources"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert not (vault_root / "Inbox" / "inbox.md").exists()

    mcp_vault = tmp_path / "mcp-vault"
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", CONFIGURED_SOURCES)
    with pytest.raises(VaultToolError, match="inside the selected vault Sources zone"):
        append_note(
            title="Agent note",
            body="must stay outside Sources",
            vault_root=mcp_vault,
            relative_dir=f"{CONFIGURED_SOURCES}/AgentNotes",
        )
    assert not mcp_vault.exists()

    source_note = vault_root / CONFIGURED_SOURCES / "panel.md"
    source_note.parent.mkdir(parents=True, exist_ok=True)
    source_note.write_text("existing Sources note\n", encoding="utf-8")
    permitted_note = vault_root / "Inbox" / "panel.md"
    permitted_note.parent.mkdir(parents=True, exist_ok=True)
    permitted_note.write_text("existing permitted note\n", encoding="utf-8")

    assert watcher_panel_writeback_allowed(
        f"{CONFIGURED_SOURCES}/panel.md",
        vault_root=vault_root,
        sources_root_rel=CONFIGURED_SOURCES,
    ) is False
    assert watcher_panel_writeback_allowed(
        "Inbox/panel.md",
        vault_root=vault_root,
        sources_root_rel=CONFIGURED_SOURCES,
    ) is True
