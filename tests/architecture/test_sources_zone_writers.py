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
    ("app/ops/native_operator_identity_restoration.py", "run_worker"),
}

# Bare packaged names remain only in the resolver or pure path/classification helpers. These exact
# occurrences are reviewed exceptions; a new literal must be routed through the selected-vault
# resolver before it can be added here.
SOURCE_LITERAL_ALLOWLIST = {
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
    ("app/api/routes/capture.py", "_capture_to_inbox"),
    ("app/cli/alpha_human_flows.py", "_select_sample_files"),
    ("app/heimdal/candidate_projection.py", "write_candidate_note"),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note"),
    ("app/heimdal/candidate_projection.py", "project_pending_candidates"),
    ("app/heimdal/meeting_finalization.py", "meetings_dir_rel"),
    ("app/journaling/day_context.py", "_read_captures"),
    # HKA placement excludes the selected Sources zone; it cannot write there.
    ("app/knowledge/placement.py", "KnowledgePlacementOwner._path"),
    ("app/knowledge/semantic.py", "KnowledgeSemanticOwner._path"),
    ("app/knowledge/service.py", "_build_adapter"),
    ("app/knowledge/service.py", "resolve_knowledge_port"),
    ("app/knowledge_acquisition/acquire.py", "_candidate_will_render"),
    ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ("app/knowledge_acquisition/source_bundle.py", "materialize_youtube_source_bundle"),
    ("app/knowledge_acquisition/source_frames.py", "_bundle_folder"),
    ("app/mcp/vault_tools.py", "append_note"),
    ("app/ops/karakeep_runtime.py", "child_preflight"),
    ("app/ops/native_operator_identity_restoration.py", "run_worker"),
    ("app/services/artifact_identity.py", "_is_create_once"),
    ("app/settings/mimer_scaffolder.py", "MimerScaffolder.scaffold"),
    ("app/vault/paths.py", "get_vault_sources_dir_rel"),
}

# These are the shipped direct callers of ``classify_note_in_vault``. Keeping this focused view
# beside the full default-bearing callsite map below makes changes to this classifier easy to read.
SOURCE_CLASSIFICATION_FORWARDING_CALLERS = {
    ("app/knowledge/adapters.py", "FsVaultAdapter._classify_target"): "self.sources_root_rel",
    ("app/knowledge/adapters.py", "ObsidianCliAdapter.write_note"): "self.sources_root_rel",
    ("app/services/artifact_identity.py", "_is_create_once"): "sources_root_rel",
    ("app/knowledge/placement.py", "KnowledgePlacementOwner._path"): "get_vault_sources_dir_rel(self.root)",
    ("app/knowledge/semantic.py", "KnowledgeSemanticOwner._path"): "get_vault_sources_dir_rel(self.root)",
    (
        "app/ops/native_operator_identity_restoration.py",
        "run_worker",
    ): "get_vault_sources_dir_rel(root)",
}

# Every shipped production helper or constructor whose packaged fallback names Sources. Values
# are (parameter name, positional argument index); None means the root is keyword-only. The
# fourth inventory records every resolved call to these targets and the value passed to the
# default-bearing parameter. Keeping the full caller map below makes a new caller fail closed even
# when it contains no literal or resolver call of its own.
SOURCE_DEFAULT_ROOT_ARGUMENTS = {
    "app.knowledge.multiwriter.classify_note": ("sources_root_rel", None),
    "app.knowledge.multiwriter.classify_note_in_vault": ("sources_root_rel", None),
    "app.knowledge_acquisition.candidate_writeback.candidate_note_path": ("sources_dir", None),
    "app.knowledge.adapters.FsVaultAdapter": ("sources_root_rel", None),
    "app.heimdal.candidate_projection.candidate_note_path": ("candidates_dir", None),
    "app.heimdal.candidate_projection.reading_candidate_note_path": ("candidates_dir", None),
    "app.knowledge_acquisition.source_bundle.validate_youtube_attachment_root": ("value", 0),
    "app.heimdal.meeting_finalization.meetings_dir_rel": ("vault_root", 0),
}

SOURCE_DEFAULT_ROOT_FORWARDING_CALLERS = {
    (
        "app/knowledge/semantic.py",
        "KnowledgeSemanticOwner._path",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("get_vault_sources_dir_rel(self.root)",),
    (
        "app/knowledge/placement.py",
        "KnowledgePlacementOwner._path",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("get_vault_sources_dir_rel(self.root)",),
    (
        "app/agents/panel_agent/policy.py",
        "watcher_panel_writeback_allowed",
        "app.knowledge.multiwriter.classify_note",
    ): ("Path(sources_root_rel).as_posix()",),
    (
        "app/knowledge/multiwriter.py",
        "classify_note_in_vault",
        "app.knowledge.multiwriter.classify_note",
    ): ("sources_root_rel or 'Sources'",),
    (
        "app/knowledge/adapters.py",
        "FsVaultAdapter._classify_target",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("self.sources_root_rel",),
    (
        "app/knowledge/adapters.py",
        "ObsidianCliAdapter.write_note",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("self.sources_root_rel",),
    (
        "app/services/artifact_identity.py",
        "_is_create_once",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("sources_root_rel",),
    (
        "app/knowledge_acquisition/candidate_writeback.py",
        "write_candidate_note",
        "app.knowledge_acquisition.candidate_writeback.candidate_note_path",
    ): ("sources_dir",),
    (
        "app/knowledge_acquisition/acquire.py",
        "_candidate_will_render",
        "app.knowledge_acquisition.candidate_writeback.candidate_note_path",
    ): ("get_vault_sources_dir_rel(vault_root)",),
    (
        "app/knowledge/service.py",
        "_build_adapter",
        "app.knowledge.adapters.FsVaultAdapter",
    ): ("sources_root_rel",),
    (
        "app/ops/native_operator_identity_restoration.py",
        "run_worker",
        "app.knowledge.multiwriter.classify_note_in_vault",
    ): ("get_vault_sources_dir_rel(root)",),
    (
        "app/heimdal/candidate_projection.py",
        "write_candidate_note",
        "app.heimdal.candidate_projection.candidate_note_path",
    ): ("candidates_dir",),
    (
        "app/heimdal/candidate_projection.py",
        "write_reading_candidate_note",
        "app.heimdal.candidate_projection.reading_candidate_note_path",
    ): ("candidates_dir",),
    (
        "app/knowledge_acquisition/source_bundle.py",
        "materialize_youtube_source_bundle",
        "app.knowledge_acquisition.source_bundle.validate_youtube_attachment_root",
    ): ("youtube_attachment_root",),
    (
        "app/knowledge_acquisition/source_frames.py",
        "_bundle_folder",
        "app.knowledge_acquisition.source_bundle.validate_youtube_attachment_root",
    ): ("youtube_attachment_root",),
    (
        "app/heimdal/meeting_finalization.py",
        "finalize_session",
        "app.heimdal.meeting_finalization.meetings_dir_rel",
    ): ("vault_root",),
}

SOURCE_WRITE_EXCLUSIONS = {
    ("app/api/routes/capture.py", "_capture_to_inbox"),
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
    return ".".join(names)


def _application_sources(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    return {
        path.relative_to(repo_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "app").rglob("*.py"))
    }


def _source_classification_forwarding_inventory(
    sources: dict[str, str],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Return resolved-root callsites for the filesystem-aware classifier."""
    return {
        (relative, scope): roots
        for (relative, scope, consumer), roots in _source_code_inventory(
            source_overrides=sources
        )[3].items()
        if consumer == "app.knowledge.multiwriter.classify_note_in_vault"
    }


def _source_default_root_forwarding_inventory(
    sources: dict[str, str] | None = None,
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """Return every alias-resolved caller of a shipped Sources-default consumer."""
    return _source_code_inventory(
        source_overrides=sources if sources is not None else _application_sources()
    )[3]


def _fs_adapter_forwards_resolved_sources_root(source: str) -> bool:
    """Require the filesystem adapter to pass its selected Sources root to classification."""
    tree = ast.parse(source)
    adapter = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "FsVaultAdapter"
        ),
        None,
    )
    if adapter is None:
        return False
    method = next(
        (
            node
            for node in adapter.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_classify_target"
        ),
        None,
    )
    if method is None:
        return False
    return any(
        isinstance(call.func, ast.Name)
        and call.func.id == "classify_note_in_vault"
        and any(
            keyword.arg == "sources_root_rel"
            and isinstance(keyword.value, ast.Attribute)
            and keyword.value.attr == "sources_root_rel"
            and isinstance(keyword.value.value, ast.Name)
            and keyword.value.value.id == "self"
            for keyword in call.keywords
        )
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
    )


def _fs_adapter_construction_forwards_resolved_sources_root(source: str) -> bool:
    """Require the production builder to pass its resolved root into the filesystem adapter."""
    tree = ast.parse(source)
    builder = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_build_adapter"
        ),
        None,
    )
    if builder is None:
        return False
    adapter_calls = [
        call
        for call in ast.walk(builder)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "FsVaultAdapter"
    ]
    if len(adapter_calls) != 1:
        return False
    call = adapter_calls[0]
    return (
        bool(call.args)
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "fs_root"
        and any(
            keyword.arg == "sources_root_rel"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "sources_root_rel"
            for keyword in call.keywords
        )
    )


def _obsidian_adapter_construction_forwards_resolved_sources_root(source: str) -> bool:
    """Require the production builder to pass its resolved root into the Obsidian adapter."""
    tree = ast.parse(source)
    builder = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_build_adapter"
        ),
        None,
    )
    if builder is None:
        return False
    adapter_calls = [
        call
        for call in ast.walk(builder)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "ObsidianCliAdapter"
    ]
    if len(adapter_calls) != 1:
        return False
    return any(
        keyword.arg == "sources_root_rel"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "sources_root_rel"
        for keyword in adapter_calls[0].keywords
    )


def _source_code_inventory(
    repo_root: Path = REPO_ROOT, *, source_overrides: dict[str, str] | None = None
) -> tuple[
    set[tuple[str, str, str]],
    set[tuple[str, str]],
    set[tuple[str, str]],
    dict[tuple[str, str, str], tuple[str, ...]],
    dict[str, tuple[str, int | None]],
]:
    """Inventory Sources callers with a bounded, scope-aware AST binding model.

    The census follows visible app imports/re-exports and one path-helper -> sink-helper
    boundary. It deliberately does not evaluate Python or follow arbitrary dynamic calls.
    """
    literals: set[tuple[str, str, str]] = set()
    resolver_callers: set[tuple[str, str]] = set()
    source_write_callers: set[tuple[str, str]] = set()
    default_root_forwarding_callers: dict[tuple[str, str, str], list[str]] = {}
    if source_overrides is None:
        trees = {
            path.relative_to(repo_root).as_posix(): ast.parse(
                path.read_text(encoding="utf-8"),
                filename=path.relative_to(repo_root).as_posix(),
            )
            for path in sorted((repo_root / "app").rglob("*.py"))
        }
    else:
        trees = {
            relative: ast.parse(source, filename=relative)
            for relative, source in source_overrides.items()
            if relative.startswith("app/") and relative.endswith(".py")
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

    def class_target(module: str, node: ast.ClassDef, qualname: tuple[str, ...]) -> str:
        return f"class:{module}::{'.'.join(qualname)}@{node.lineno}"

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
    class_by_node: dict[int, str] = {}
    class_nodes: dict[str, tuple[str, ast.ClassDef]] = {}
    parent_function: dict[str, str | None] = {}
    function_display: dict[str, str] = {}
    function_depth: dict[str, int] = {}
    module_stack: list[ast.AST] = []

    class FunctionIndex(ast.NodeVisitor):
        def __init__(self, relative: str) -> None:
            self.relative = relative
            self.module = module_for_relative[relative]

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            lexical_nodes = [
                item
                for item in module_stack
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            qualname = tuple(item.name for item in lexical_nodes) + (node.name,)
            target = class_target(self.module, node, qualname)
            class_by_node[id(node)] = target
            class_nodes[target] = (self.relative, node)
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

    def is_sources_root(value: object) -> bool:
        return isinstance(value, str) and (value == "Sources" or value.startswith("Sources/"))

    module_sources_names: dict[str, set[str]] = {}
    for relative, tree in trees.items():
        names = module_sources_names.setdefault(module_for_relative[relative], set())
        for statement in tree.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if isinstance(value, ast.Constant) and is_sources_root(value.value):
                    names.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )

    def root_expression(expression: ast.AST, module: str) -> bool:
        return any(
            (isinstance(node, ast.Constant) and is_sources_root(node.value))
            or (isinstance(node, ast.Name) and node.id in module_sources_names.get(module, set()))
            for node in ast.walk(expression)
        )

    def scope_uses_sources(body: list[ast.stmt], module: str) -> bool:
        found = False

        class RootReferences(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                return

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_Constant(self, node: ast.Constant) -> None:
                nonlocal found
                found = found or is_sources_root(node.value)

            def visit_Name(self, node: ast.Name) -> None:
                nonlocal found
                found = found or node.id in module_sources_names.get(module, set())

        visitor = RootReferences()
        for statement in body:
            visitor.visit(statement)
        return found

    def function_default_parameters(
        node: ast.FunctionDef | ast.AsyncFunctionDef, module: str
    ) -> list[tuple[str, int | None, ast.expr]]:
        positional = [*node.args.posonlyargs, *node.args.args]
        defaults: list[tuple[str, int | None, ast.expr]] = []
        if node.args.defaults:
            start = len(positional) - len(node.args.defaults)
            defaults.extend(
                (argument.arg, index, default)
                for index, (argument, default) in enumerate(
                    zip(positional[start:], node.args.defaults, strict=True), start
                )
            )
        defaults.extend(
            (argument.arg, None, default)
            for argument, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults, strict=True
            )
            if default is not None
        )
        direct = [item for item in defaults if root_expression(item[2], module)]
        if direct:
            return direct

        # A None default can select a packaged Sources fallback in the function body.
        if scope_uses_sources(node.body, module):
            root_named = [
                item
                for item in defaults
                if any(token in item[0].casefold() for token in ("source", "vault", "root"))
            ]
            if root_named:
                return root_named
            if len(defaults) == 1:
                return defaults
        return []

    observed_default_root_arguments: dict[str, tuple[str, int | None]] = {}
    for target, (relative, node) in function_nodes.items():
        if function_display[target] != node.name:
            continue
        module = module_for_relative[relative]
        parameters = function_default_parameters(node, module)
        if parameters:
            identity = f"{module}.{node.name}"
            if len(parameters) == 1:
                argument, positional_index, _default = parameters[0]
                observed_default_root_arguments[identity] = (argument, positional_index)
            else:
                observed_default_root_arguments[identity] = (
                    "<ambiguous-default-parameters>",
                    None,
                )

    for target, (relative, node) in class_nodes.items():
        class_qualname = target.split("::", 1)[1].rsplit("@", 1)[0]
        if class_qualname != node.name:
            continue
        constructor = next(
            (
                item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "__init__"
            ),
            None,
        )
        if constructor is None:
            continue
        module = module_for_relative[relative]
        parameters = function_default_parameters(constructor, module)
        if parameters:
            identity = f"{module}.{node.name}"
            if len(parameters) == 1:
                argument, positional_index, _default = parameters[0]
                if positional_index is not None:
                    positional_index -= 1  # Constructor calls omit implicit self.
                observed_default_root_arguments[identity] = (argument, positional_index)
            else:
                observed_default_root_arguments[identity] = (
                    "<ambiguous-default-parameters>",
                    None,
                )

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
            target = class_by_node.get(id(node))
            if target:
                add_binding(self.bindings, node.name, target)

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
        if record and record[1].name in names:
            return True
        class_record = class_nodes.get(target)
        return bool(class_record and class_record[1].name in names)

    default_root_consumers: dict[str, tuple[str, tuple[str, int | None]]] = {}
    for target, (relative, node) in function_nodes.items():
        if function_display[target] != node.name:
            continue
        qualified = f"{module_for_relative[relative]}.{node.name}"
        if qualified in SOURCE_DEFAULT_ROOT_ARGUMENTS:
            default_root_consumers[target] = (
                qualified,
                SOURCE_DEFAULT_ROOT_ARGUMENTS[qualified],
            )
    for target, (relative, node) in class_nodes.items():
        class_qualname = target.split("::", 1)[1].rsplit("@", 1)[0]
        if class_qualname != node.name:
            continue
        qualified = f"{module_for_relative[relative]}.{node.name}"
        if qualified in SOURCE_DEFAULT_ROOT_ARGUMENTS:
            default_root_consumers[target] = (
                qualified,
                SOURCE_DEFAULT_ROOT_ARGUMENTS[qualified],
            )

    def record_default_root_calls(
        relative: str,
        scope: str,
        calls: list[tuple[set[str], ast.Call]],
    ) -> None:
        for callees, call in calls:
            for target in callees & default_root_consumers.keys():
                qualified, (argument_name, positional_index) = default_root_consumers[target]
                roots = [
                    ast.unparse(keyword.value)
                    for keyword in call.keywords
                    if keyword.arg == argument_name
                ]
                if positional_index is not None and positional_index < len(call.args):
                    roots.append(ast.unparse(call.args[positional_index]))
                if len(roots) != 1:
                    roots = ["<missing-or-duplicate>"]
                default_root_forwarding_callers.setdefault(
                    (relative, scope, qualified), []
                ).extend(roots)

    calls_by_function: dict[str, list[tuple[set[str], ast.Call]]] = {}
    for target, (relative, function) in function_nodes.items():
        calls: list[tuple[set[str], ast.Call]] = []

        class DirectCalls(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                for default in (*node.args.defaults, *node.args.kw_defaults):
                    if default is not None:
                        self.visit(default)
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
        record_default_root_calls(relative, function_display[target], calls)
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
                callees = expression_targets(relative, node.func, active_env)
                if not any(
                    function_named(callee, {"get_vault_sources_dir_rel", "resolve_vault_sources_dir_rel"})
                    for callee in callees
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

    def scope_writes_source(
        relative: str,
        body: list[ast.stmt],
        env: dict[str, set[str]],
        calls: list[tuple[set[str], ast.Call]],
    ) -> bool:
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
        for statement in body:
            visitor.visit(statement)
        source_names: set[str] = set()
        changed = True
        while changed:
            changed = False
            for targets, value in assignments:
                if is_source_path(relative, value, env, source_names):
                    for assigned in targets:
                        for child in ast.walk(assigned):
                            if isinstance(child, ast.Name) and child.id not in source_names:
                                source_names.add(child.id)
                                changed = True

        return any(
            any(
                callee in sinks_by_function or function_named(callee, SOURCE_WRITE_SINKS)
                for callee in callees
            )
            and any(
                is_source_path(relative, argument, env, source_names)
                for argument in (*call.args, *(keyword.value for keyword in call.keywords))
            )
            for callees, call in calls
        )

    for target, calls in calls_by_function.items():
        relative, function = function_nodes[target]
        if scope_writes_source(relative, function.body, function_env[target], calls):
            source_write_callers.add((relative, function_display[target]))

    def direct_scope_calls(
        relative: str, body: list[ast.stmt], env: dict[str, set[str]]
    ) -> list[tuple[set[str], ast.Call]]:
        calls: list[tuple[set[str], ast.Call]] = []

        class DirectScopeCalls(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                for default in (*node.args.defaults, *node.args.kw_defaults):
                    if default is not None:
                        self.visit(default)
                return

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_Call(self, node: ast.Call) -> None:
                calls.append((expression_targets(relative, node.func, env), node))
                self.generic_visit(node)

        visitor = DirectScopeCalls()
        for statement in body:
            visitor.visit(statement)
        return calls

    def child_scope_env(
        relative: str, body: list[ast.stmt], parent_env: dict[str, set[str]]
    ) -> dict[str, set[str]]:
        collector = ScopeBindings(relative=relative)
        for statement in body:
            collector.visit(statement)
        local = {name: set(values) for name, values in collector.bindings.items()}
        for name, specs in collector.from_specs.items():
            for base, imported in specs:
                local.setdefault(name, set()).update(
                    resolve_import_target(relative, base, imported)
                )
        env = {name: set(values) for name, values in parent_env.items()}
        env.update(local)
        return env

    # Module and immediately executed class-body calls are production callsites too.
    # Nested functions/classes remain separate lexical scopes and use this same bounded
    # one-helper classifier, without evaluating arbitrary Python execution.
    for relative, tree in trees.items():
        module_env = {
            name: set(values)
            for name, values in module_targets.get(module_for_relative[relative], {}).items()
        }
        module_calls = direct_scope_calls(relative, tree.body, module_env)
        record_default_root_calls(relative, "<module>", module_calls)
        if scope_writes_source(
            relative, tree.body, module_env, module_calls
        ):
            source_write_callers.add((relative, "<module>"))

        class_scopes: list[tuple[ast.ClassDef, dict[str, set[str]], list[ast.AST]]] = []

        class ClassScopes(ast.NodeVisitor):
            def __init__(self) -> None:
                self.stack: list[ast.AST] = []
                self.env_stack = [module_env]

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                target = function_by_node.get(id(node))
                if target is None:
                    return
                self.stack.append(node)
                self.env_stack.append(function_env[target])
                for statement in node.body:
                    self.visit(statement)
                self.env_stack.pop()
                self.stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                # Class bodies execute when the class is created, including inside a function.
                # Their bare-name lookup sees the enclosing function/module bindings and the
                # class's own bindings, but nested classes and methods do not inherit a class
                # namespace as a lexical scope.
                env = child_scope_env(relative, node.body, self.env_stack[-1])
                self.stack.append(node)
                class_scopes.append((node, env, list(self.stack)))
                for statement in node.body:
                    self.visit(statement)
                self.stack.pop()

        class_visitor = ClassScopes()
        for statement in tree.body:
            class_visitor.visit(statement)
        for class_node, env, lexical_classes in class_scopes:
            lexical_names = [
                item.name
                for item in lexical_classes
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            label = (
                ".".join(lexical_names)
                if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) for item in lexical_classes)
                else _module_function_for(lexical_classes)
            )
            calls = direct_scope_calls(relative, class_node.body, env)
            record_default_root_calls(relative, label, calls)
            if any(
                any(
                    function_named(callee, {"get_vault_sources_dir_rel", "resolve_vault_sources_dir_rel"})
                    for callee in callees
                )
                for callees, _call in calls
            ):
                resolver_callers.add((relative, label))
            if scope_writes_source(relative, class_node.body, env, calls):
                source_write_callers.add((relative, label))

    return (
        literals,
        resolver_callers,
        source_write_callers,
        {key: tuple(values) for key, values in default_root_forwarding_callers.items()},
        observed_default_root_arguments,
    )


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
    (
        literals,
        resolver_callers,
        source_write_callers,
        default_root_callers,
        observed_default_root_arguments,
    ) = _source_code_inventory()
    assert literals == SOURCE_LITERAL_ALLOWLIST
    assert resolver_callers == SOURCE_RESOLVER_CALLERS
    assert source_write_callers == REGISTERED_SOURCE_WRITERS | SOURCE_WRITE_EXCLUSIONS
    assert default_root_callers == SOURCE_DEFAULT_ROOT_FORWARDING_CALLERS
    assert observed_default_root_arguments == SOURCE_DEFAULT_ROOT_ARGUMENTS
    adapter_source = (REPO_ROOT / "app/knowledge/adapters.py").read_text(encoding="utf-8")
    service_source = (REPO_ROOT / "app/knowledge/service.py").read_text(encoding="utf-8")
    assert _fs_adapter_construction_forwards_resolved_sources_root(service_source)
    assert _obsidian_adapter_construction_forwards_resolved_sources_root(service_source)
    assert _fs_adapter_forwards_resolved_sources_root(adapter_source)
    assert {
        (relative, scope): roots
        for (relative, scope, consumer), roots in default_root_callers.items()
        if consumer == "app.knowledge.multiwriter.classify_note_in_vault"
    } == {
        caller: (root_expression,)
        for caller, root_expression in SOURCE_CLASSIFICATION_FORWARDING_CALLERS.items()
    }


def test_adapter_forwarding_proof_rejects_missing_or_default_sources_root() -> None:
    service_source = (REPO_ROOT / "app/knowledge/service.py").read_text(encoding="utf-8")
    constructor_call = "return FsVaultAdapter(fs_root, sources_root_rel=sources_root_rel)"
    assert constructor_call in service_source
    assert _fs_adapter_construction_forwards_resolved_sources_root(service_source)

    without_constructor_forwarding = service_source.replace(
        constructor_call, "return FsVaultAdapter(fs_root)", 1
    )
    assert not _fs_adapter_construction_forwards_resolved_sources_root(
        without_constructor_forwarding
    )

    constructor_defaulted_to_packaged_root = service_source.replace(
        constructor_call,
        'return FsVaultAdapter(fs_root, sources_root_rel="Sources")',
        1,
    )
    assert not _fs_adapter_construction_forwards_resolved_sources_root(
        constructor_defaulted_to_packaged_root
    )

    obsidian_constructor_call = (
        "return ObsidianCliAdapter(\n"
        "            sources_root_rel=sources_root_rel,\n"
        "            vault_root=vault_root,\n"
        "        )"
    )
    assert obsidian_constructor_call in service_source
    assert _obsidian_adapter_construction_forwards_resolved_sources_root(service_source)
    without_obsidian_constructor_forwarding = service_source.replace(
        obsidian_constructor_call,
        "return ObsidianCliAdapter(vault_root=vault_root)",
        1,
    )
    assert not _obsidian_adapter_construction_forwards_resolved_sources_root(
        without_obsidian_constructor_forwarding
    )
    obsidian_constructor_defaulted = service_source.replace(
        obsidian_constructor_call,
        obsidian_constructor_call.replace(
            "sources_root_rel=sources_root_rel", 'sources_root_rel="Sources"'
        ),
        1,
    )
    assert not _obsidian_adapter_construction_forwards_resolved_sources_root(
        obsidian_constructor_defaulted
    )

    adapter_source = (REPO_ROOT / "app/knowledge/adapters.py").read_text(encoding="utf-8")
    forwarded_argument = "            sources_root_rel=self.sources_root_rel,\n"
    assert forwarded_argument in adapter_source
    assert _fs_adapter_forwards_resolved_sources_root(adapter_source)

    without_forwarding = adapter_source.replace(forwarded_argument, "", 1)
    assert not _fs_adapter_forwards_resolved_sources_root(without_forwarding)

    defaulted_argument = adapter_source.replace(
        forwarded_argument, '            sources_root_rel="Sources",\n', 1
    )
    assert not _fs_adapter_forwards_resolved_sources_root(defaulted_argument)


def test_classifier_callsite_inventory_rejects_missing_or_default_sources_root() -> None:
    application_sources = _application_sources()
    sources = {
        relative: application_sources[relative]
        for relative in (
            "app/knowledge/__init__.py",
            "app/knowledge/adapters.py",
            "app/knowledge/multiwriter.py",
            "app/knowledge/placement.py",
            "app/knowledge/semantic.py",
            "app/ops/native_operator_identity_restoration.py",
            "app/services/artifact_identity.py",
        )
    }
    expected = {
        caller: (root_expression,)
        for caller, root_expression in SOURCE_CLASSIFICATION_FORWARDING_CALLERS.items()
    }
    assert _source_classification_forwarding_inventory(sources) == expected

    aliased_caller = (
        "from app.knowledge.multiwriter import classify_note_in_vault as classify\n"
        "def aliased_classifier_writer():\n"
        "    return classify('note.md', sources_root_rel='ConfiguredSources')\n"
    )
    aliased_sources = dict(sources)
    aliased_sources["app/knowledge/aliased_classifier.py"] = aliased_caller
    alias_key = ("app/knowledge/aliased_classifier.py", "aliased_classifier_writer")
    aliased_sources["app/knowledge/function_local_classifier.py"] = (
        "def function_local_classifier_writer():\n"
        "    from app.knowledge.multiwriter import classify_note_in_vault as local_classify\n"
        "    return local_classify('note.md', sources_root_rel='ConfiguredSources')\n"
    )
    local_alias_key = (
        "app/knowledge/function_local_classifier.py",
        "function_local_classifier_writer",
    )
    assert _source_classification_forwarding_inventory(aliased_sources) == {
        **expected,
        alias_key: ("'ConfiguredSources'",),
        local_alias_key: ("'ConfiguredSources'",),
    }

    package_reexport_sources = dict(sources)
    package_reexport_sources["app/knowledge/__init__.py"] += (
        "\nfrom .multiwriter import classify_note_in_vault as exported_classifier\n"
    )
    package_reexport_sources["app/knowledge/reexported_classifier.py"] = (
        "from app.knowledge import exported_classifier as classify_alias\n"
        "def reexported_classifier_writer():\n"
        "    return classify_alias('note.md', sources_root_rel='ConfiguredSources')\n"
    )
    reexport_key = (
        "app/knowledge/reexported_classifier.py",
        "reexported_classifier_writer",
    )
    assert _source_classification_forwarding_inventory(package_reexport_sources) == {
        **expected,
        reexport_key: ("'ConfiguredSources'",),
    }

    module_alias_sources = dict(sources)
    module_alias_sources["app/knowledge/module_alias_classifier.py"] = (
        "import app.knowledge.multiwriter as classifier_module\n"
        "def module_alias_classifier_writer():\n"
        "    return classifier_module.classify_note_in_vault('note.md', "
        "sources_root_rel='ConfiguredSources')\n"
    )
    module_alias_key = (
        "app/knowledge/module_alias_classifier.py",
        "module_alias_classifier_writer",
    )
    assert _source_classification_forwarding_inventory(module_alias_sources) == {
        **expected,
        module_alias_key: ("'ConfiguredSources'",),
    }

    for alias_sources, relative, scope, call in (
        (aliased_sources, "app/knowledge/aliased_classifier.py", "aliased_classifier_writer", "classify"),
        (
            aliased_sources,
            "app/knowledge/function_local_classifier.py",
            "function_local_classifier_writer",
            "local_classify",
        ),
        (
            package_reexport_sources,
            "app/knowledge/reexported_classifier.py",
            "reexported_classifier_writer",
            "classify_alias",
        ),
        (
            module_alias_sources,
            "app/knowledge/module_alias_classifier.py",
            "module_alias_classifier_writer",
            "classifier_module.classify_note_in_vault",
        ),
    ):
        alias_call = f"return {call}('note.md', sources_root_rel='ConfiguredSources')"
        alias_missing = dict(alias_sources)
        alias_missing[relative] = alias_sources[relative].replace(
            ", sources_root_rel='ConfiguredSources'", "", 1
        )
        assert _source_classification_forwarding_inventory(alias_missing)[
            (relative, scope)
        ] == ("<missing-or-duplicate>",)
        alias_defaulted = dict(alias_sources)
        alias_defaulted[relative] = alias_sources[relative].replace(
            "sources_root_rel='ConfiguredSources'", "sources_root_rel='Sources'", 1
        )
        assert _source_classification_forwarding_inventory(alias_defaulted)[
            (relative, scope)
        ] == ("'Sources'",)
        assert alias_call in alias_sources[relative]

    for caller, root_expression in SOURCE_CLASSIFICATION_FORWARDING_CALLERS.items():
        relative, scope = caller
        forwarded = f"sources_root_rel={root_expression},\n"
        mutated = dict(sources)
        source = mutated[relative]
        if scope == "ObsidianCliAdapter.write_note":
            prefix, class_source = source.split("class ObsidianCliAdapter", maxsplit=1)
            assert forwarded in class_source
            class_source = class_source.replace(forwarded, "", 1)
            mutated[relative] = prefix + "class ObsidianCliAdapter" + class_source
        else:
            assert forwarded in source
            mutated[relative] = source.replace(forwarded, "", 1)
        assert _source_classification_forwarding_inventory(mutated) != expected

        packaged_default = dict(sources)
        source = packaged_default[relative]
        if scope == "ObsidianCliAdapter.write_note":
            prefix, class_source = source.split("class ObsidianCliAdapter", maxsplit=1)
            root_name = "self.sources_root_rel"
            class_source = class_source.replace(
                forwarded,
                forwarded.replace(f"={root_name}", '="Sources"', 1),
                1,
            )
            packaged_default[relative] = prefix + "class ObsidianCliAdapter" + class_source
        else:
            packaged_default[relative] = source.replace(
                forwarded, forwarded.replace(f"={root_expression}", '="Sources"', 1), 1
            )
        assert _source_classification_forwarding_inventory(packaged_default) != expected


def test_default_root_callsite_inventory_fails_closed_for_new_and_defaulted_callers() -> None:
    calls = {
        "app.knowledge.multiwriter.classify_note": (
            "from app.knowledge.multiwriter import classify_note as consumer",
            "consumer('note.md', WriteOperation.WRITE, sources_root_rel={root})",
        ),
        "app.knowledge.multiwriter.classify_note_in_vault": (
            "from app.knowledge.multiwriter import classify_note_in_vault as consumer",
            "consumer('note.md', WriteOperation.WRITE, vault_root='.', sources_root_rel={root})",
        ),
        "app.knowledge_acquisition.candidate_writeback.candidate_note_path": (
            "from app.knowledge_acquisition.candidate_writeback import candidate_note_path as consumer",
            "consumer(candidate, sources_dir={root})",
        ),
        "app.knowledge.adapters.FsVaultAdapter": (
            "from app.knowledge.adapters import FsVaultAdapter as consumer",
            "consumer('.', sources_root_rel={root})",
        ),
        "app.heimdal.candidate_projection.candidate_note_path": (
            "from app.heimdal.candidate_projection import candidate_note_path as consumer",
            "consumer(candidate, candidates_dir={root})",
        ),
        "app.heimdal.candidate_projection.reading_candidate_note_path": (
            "from app.heimdal.candidate_projection import reading_candidate_note_path as consumer",
            "consumer(candidate, candidates_dir={root})",
        ),
        "app.knowledge_acquisition.source_bundle.validate_youtube_attachment_root": (
            "from app.knowledge_acquisition.source_bundle import validate_youtube_attachment_root as consumer",
            "consumer({root})",
        ),
        "app.heimdal.meeting_finalization.meetings_dir_rel": (
            "from app.heimdal.meeting_finalization import meetings_dir_rel as consumer",
            "consumer({root})",
        ),
    }
    for index, (qualified, (import_line, call_template)) in enumerate(calls.items()):
        module, _, name = qualified.rpartition(".")
        assert name
        assert import_line.startswith(f"from {module} import {name} as ")
        relative = f"app/knowledge/new_default_root_caller_{index}.py"
        scope = f"new_default_root_caller_{index}"
        entry = (relative, scope, qualified)
        fixture_sources = {
            "app/__init__.py": "",
            "app/knowledge/__init__.py": "",
            "app/knowledge/multiwriter.py": (
                "def classify_note(*args, **kwargs):\n    return None\n"
                "def classify_note_in_vault(*args, **kwargs):\n    return None\n"
            ),
            "app/knowledge/adapters.py": "class FsVaultAdapter:\n    pass\n",
            "app/knowledge_acquisition/__init__.py": "",
            "app/knowledge_acquisition/candidate_writeback.py": (
                "def candidate_note_path(*args, **kwargs):\n    return ''\n"
            ),
            "app/heimdal/__init__.py": "",
            "app/heimdal/candidate_projection.py": (
                "def candidate_note_path(*args, **kwargs):\n    return ''\n"
                "def reading_candidate_note_path(*args, **kwargs):\n    return ''\n"
            ),
            "app/knowledge_acquisition/source_bundle.py": (
                "def validate_youtube_attachment_root(*args, **kwargs):\n    return ''\n"
            ),
            "app/heimdal/meeting_finalization.py": (
                "def meetings_dir_rel(*args, **kwargs):\n    return ''\n"
            ),
        }

        for root, expected_root in (
            ("'ConfiguredSources'", ("'ConfiguredSources'",)),
            (None, ("<missing-or-duplicate>",)),
            ("'Sources'", ("'Sources'",)),
        ):
            if root is None:
                # Drop only the default-bearing keyword while retaining all required arguments.
                call = call_template.format(root="'ConfiguredSources'")
                call = call.replace(", sources_root_rel='ConfiguredSources'", "")
                call = call.replace(", sources_dir='ConfiguredSources'", "")
                call = call.replace(", candidates_dir='ConfiguredSources'", "")
                call = call.replace("consumer('ConfiguredSources')", "consumer()")
            else:
                call = call_template.format(root=root)
            mutated = dict(fixture_sources)
            mutated[relative] = (
                f"{import_line}\n"
                f"def {scope}():\n"
                f"    return {call}\n"
            )
            inventory = _source_default_root_forwarding_inventory(mutated)
            assert inventory[entry] == expected_root
            assert set(inventory) == {entry}


def test_function_local_class_body_default_classifier_call_is_in_inventory() -> None:
    relative = "app/knowledge/function_local_class_default_classifier.py"
    qualified = "app.knowledge.multiwriter.classify_note_in_vault"
    class_sources = {
        "app/__init__.py": "",
        "app/knowledge/__init__.py": "",
        "app/knowledge/multiwriter.py": (
            "def classify_note_in_vault(*args, **kwargs):\n    return None\n"
        ),
    }
    class_sources[relative] = (
        "def enclosing_default_classifier():\n"
        "    class LocalDefaultClassifier:\n"
        "        from app.knowledge.multiwriter import classify_note_in_vault as classify\n"
        "        classify('note.md', WriteOperation.WRITE, vault_root='.')\n"
    )
    entry = (
        relative,
        "enclosing_default_classifier.LocalDefaultClassifier",
        qualified,
    )
    missing = _source_default_root_forwarding_inventory(class_sources)
    assert missing[entry] == ("<missing-or-duplicate>",)

    class_sources[relative] = class_sources[relative].replace(
        "vault_root='.')", "vault_root='.', sources_root_rel='ConfiguredSources')"
    )
    forwarded = _source_default_root_forwarding_inventory(class_sources)
    assert forwarded[entry] == ("'ConfiguredSources'",)

    class_sources[relative] = class_sources[relative].replace(
        "sources_root_rel='ConfiguredSources'", "sources_root_rel='Sources'"
    )
    defaulted = _source_default_root_forwarding_inventory(class_sources)
    assert defaulted[entry] == ("'Sources'",)


def test_default_root_census_detects_new_default_bearing_helpers() -> None:
    sources = _application_sources()
    relative = "app/knowledge/new_default_root_helper.py"
    sources[relative] = (
        "DEFAULT_NEW_SOURCE_ROOT = 'Sources/New'\n"
        "def newly_allowlisted_helper(sources_root_rel=DEFAULT_NEW_SOURCE_ROOT):\n"
        "    return sources_root_rel\n"
    )

    observed = _source_code_inventory(source_overrides=sources)[4]
    assert observed["app.knowledge.new_default_root_helper.newly_allowlisted_helper"] == (
        "sources_root_rel",
        0,
    )
    assert observed != SOURCE_DEFAULT_ROOT_ARGUMENTS


def test_eager_function_default_calls_are_recorded_in_enclosing_execution_scopes() -> None:
    relative = "app/knowledge/eager_default_callers.py"
    sources = {
        "app/__init__.py": "",
        "app/knowledge/__init__.py": "",
        "app/knowledge/adapters.py": (
            "class FsVaultAdapter:\n"
            "    def __init__(self, root, *, sources_root_rel='Sources'):\n"
            "        self.root = root\n"
        ),
        relative: (
            "from app.knowledge.adapters import FsVaultAdapter as Adapter\n"
            "def module_writer(adapter=Adapter('.')):\n"
            "    return adapter\n"
            "def enclosing():\n"
            "    def local_writer(adapter=Adapter('.')):\n"
            "        return adapter\n"
            "    class Writer:\n"
            "        def method(adapter=Adapter('.')):\n"
            "            return adapter\n"
        ),
    }

    inventory = _source_default_root_forwarding_inventory(sources)
    missing = ("<missing-or-duplicate>",)
    consumer = "app.knowledge.adapters.FsVaultAdapter"
    assert inventory[(relative, "<module>", consumer)] == missing
    assert inventory[(relative, "enclosing", consumer)] == missing
    assert inventory[(relative, "enclosing.Writer", consumer)] == missing

    sources[relative] = sources[relative].replace(
        "def module_writer(adapter=Adapter('.')):",
        "def module_writer(adapter=Adapter('.', sources_root_rel='ConfiguredSources')):",
        1,
    )
    inventory = _source_default_root_forwarding_inventory(sources)
    assert inventory[(relative, "<module>", consumer)] == ("'ConfiguredSources'",)


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
            "    def producer_layer_3414():\n"
            "        def make_path():\n"
            "            return f'{factory_resolve()}/a.md'\n"
            "        def persist_path(path):\n"
            "            return factory_persist(path)\n"
            "        def writer():\n"
            "            path = make_path()\n"
            "            return persist_path(path)\n"
            "        return writer()\n"
            "    return producer_layer_3414()\n"
            "def factory_b_3414():\n"
            "    def producer_layer_3414():\n"
            "        def make_path():\n"
            "            return 'Inbox/b.md'\n"
            "        def persist_path(path):\n"
            "            return path\n"
            "        def writer():\n"
            "            path = make_path()\n"
            "            return persist_path(path)\n"
            "        return writer()\n"
            "    return producer_layer_3414()\n"
        ),
        "app/writers/module_producer.py": (
            "from app.writers import chain_path as make_path, chain_sink as save_path\n"
            "save_path(make_path())\n"
        ),
        "app/writers/unrelated_module.py": (
            "from app.writers.helpers import build_source_path as make_path\n"
            "from app.writers.helpers import write_source_path as save_path\n"
            "make_path()\n"
            "save_path('unrelated')\n"
        ),
        "app/writers/class_producer.py": (
            "from app.writers import chain_path as make_path, chain_sink as save_path\n"
            "class Example:\n"
            "    save_path(make_path())\n"
            "class Unrelated:\n"
            "    make_path()\n"
            "    save_path('unrelated')\n"
        ),
        "app/writers/function_local_class.py": (
            "def outer_3414():\n"
            "    from app.writers.helpers import build_source_path as make_path\n"
            "    from app.writers.helpers import write_source_path as save_path\n"
            "    class Example:\n"
            "        save_path(make_path())\n"
            "    return Example\n"
            "outer_3414()\n"
            "def unrelated_outer_3414():\n"
            "    from app.writers.helpers import build_source_path as make_path\n"
            "    from app.writers.helpers import write_source_path as save_path\n"
            "    class Unrelated:\n"
            "        make_path()\n"
            "        save_path('Inbox/unrelated.md')\n"
            "    return Unrelated\n"
            "unrelated_outer_3414()\n"
        ),
        "app/writers/method_inbox_class_shadow.py": (
            "from app.writers.helpers import build_source_path as make_path\n"
            "from app.writers.helpers import write_source_path as save_path\n"
            "from app.writers.inbox_paths import get_vault_inbox_dir_rel\n"
            "class InboxClassShadow:\n"
            "    make_path = get_vault_inbox_dir_rel\n"
            "    def writer(self):\n"
            "        return save_path(make_path())\n"
        ),
        "app/writers/method_sources_class_shadow.py": (
            "from app.writers.inbox_paths import get_vault_inbox_dir_rel as make_path\n"
            "from app.writers.helpers import write_source_path as save_path\n"
            "class SourcesClassShadow:\n"
            "    from app.writers.helpers import build_source_path as make_path\n"
            "    def writer(self):\n"
            "        return save_path(make_path())\n"
        ),
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    (
        _literals,
        resolver_callers,
        source_write_callers,
        _classifier_callers,
        _default_consumers,
    ) = _source_code_inventory(tmp_path)

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
    factory_a_writer = ("app/writers/producer.py", "factory_a_3414.producer_layer_3414.writer")
    factory_b_writer = ("app/writers/producer.py", "factory_b_3414.producer_layer_3414.writer")
    assert factory_a_writer in source_write_callers
    assert factory_b_writer not in source_write_callers
    assert ("app/writers/module_producer.py", "<module>") in source_write_callers
    assert ("app/writers/class_producer.py", "Example") in source_write_callers
    assert ("app/writers/function_local_class.py", "outer_3414.Example") in source_write_callers
    assert ("app/writers/function_local_class.py", "outer_3414") not in source_write_callers
    assert ("app/writers/function_local_class.py", "unrelated_outer_3414.Unrelated") not in source_write_callers
    assert ("app/writers/method_inbox_class_shadow.py", "InboxClassShadow.writer") in source_write_callers
    assert ("app/writers/method_sources_class_shadow.py", "SourcesClassShadow.writer") not in source_write_callers
    assert (
        "app/writers/producer.py",
        "factory_a_3414.producer_layer_3414.make_path",
    ) in resolver_callers
    assert ("app/writers/producer.py", "shadowed_enclosing_resolver_3414.write_inbox") not in resolver_callers
    assert ("app/writers/producer.py", "shadowed_enclosing_resolver_3414.write_inbox") not in source_write_callers
    assert ("app/writers/producer.py", "unrelated_path_and_write_calls") not in source_write_callers
    assert ("app/writers/unrelated_module.py", "<module>") not in source_write_callers
    assert ("app/writers/class_producer.py", "Unrelated") not in source_write_callers

    producer_path = tmp_path / "app" / "writers" / "producer.py"
    producer_source = producer_path.read_text(encoding="utf-8")
    inbox_writer = (
        "def factory_b_3414():\n"
        "    def producer_layer_3414():\n"
        "        def make_path():\n"
        "            return 'Inbox/b.md'\n"
        "        def persist_path(path):\n"
        "            return path\n"
    )
    sources_writer = (
        "def factory_b_3414():\n"
        "    def producer_layer_3414():\n"
        "        def make_path():\n"
        "            return f'{factory_resolve()}/b.md'\n"
        "        def persist_path(path):\n"
        "            return factory_persist(path)\n"
    )
    assert inbox_writer in producer_source
    producer_path.write_text(
        producer_source.replace(inbox_writer, sources_writer, 1), encoding="utf-8"
    )
    (
        _literals,
        _resolver_callers,
        mutated_source_write_callers,
        _classifier_callers,
        _default_consumers,
    ) = _source_code_inventory(tmp_path)
    assert factory_a_writer in mutated_source_write_callers
    assert factory_b_writer in mutated_source_write_callers


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
