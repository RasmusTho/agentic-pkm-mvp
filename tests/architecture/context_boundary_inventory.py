"""MVR-05B1 (#6136): production request-entrypoint context-boundary inventory.

Two derived populations and one named list, compared as sets:

* **Entrypoint population** -- derived from the code, never re-typed: the router
  modules ``app/api/app.py`` registers with ``include_router`` (resolved through
  its own imports), every module under ``app/api/routes/``, the agent graph, the
  MCP vault tools, and every module under ``app/cli/`` (the CLI command
  registry in ``app/cli/__init__.py`` imports from that package).
* **Offender population** -- AST detection of *global* vault resolution inside
  that population: a reference to a global-resolution symbol, or a direct
  ``VAULT_ROOT`` / ``VAULT_DIR`` environment read. Detection is structural; the
  sanctioned scoped seam (``require_scoped_read_context``) is never consulted,
  so a module cannot satisfy the gate by mentioning it.
* **Compatibility-adapter allowlist** -- ``COMPATIBILITY_ADAPTERS``, one entry per
  ``(module, function)`` naming why it may resolve globally and which later stage
  retires it. The gate fails on an offender that is not listed and on a listed
  entry that no longer resolves globally (or resolves a different symbol set),
  so the list can only shrink: 05B2-05B4 each delete the entries they migrate,
  and hub #3860 records what remains.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Symbols whose use is a global (process-selected) vault lookup rather than a
# per-request ActiveContextSet. The last two are the in-package route wrappers
# around ``get_vault_manager``; naming them keeps a route from laundering a
# global lookup through its sibling helper.
GLOBAL_RESOLUTION_SYMBOLS = frozenset(
    {
        "get_vault_manager",
        "active_vault_root_or_selection_required",
        "resolve_optional_vault_root",
        "resolve_active_vault_root",
        "active_vault_selection_window",
    }
)
GLOBAL_ENV_NAMES = frozenset({"VAULT_ROOT", "VAULT_DIR"})
ENV_SYMBOL_PREFIX = "env:"

API_APP_MODULE = "app/api/app.py"
API_ROUTES_DIR = "app/api/routes"
CLI_DIR = "app/cli"
FIXED_ENTRYPOINT_MODULES = ("app/agents/ask/graph.py", "app/mcp/vault_tools.py")

# Modules under app/api/routes/ that app/api/app.py does not register, with the
# reason each is still request-handling code. A new unregistered module fails
# the gate until it is classified here; a listed module that becomes registered
# or disappears is stale.
UNREGISTERED_ROUTE_MODULES: dict[str, str] = {
    "app/api/routes/vault_resolution.py": (
        "shared global-resolution primitive imported by route modules; carries no route"
    ),
    "app/api/routes/ingest_binding.py": (
        "ingest binding helper imported by the ingest route; carries no route"
    ),
}

RETIRING_STAGES = frozenset(
    {
        "05B2",
        "05B3",
        "05B4",
        "retained:MVR-05C",
        "retained:MVR-06",
    }
)


@dataclass(frozen=True)
class CompatibilityAdapter:
    """One named legacy global-lookup adapter and the stage that retires it."""

    module: str
    scope: str
    symbols: frozenset[str]
    why: str
    retired_by: str


def _a(module: str, scope: str, symbols: str, why: str, retired_by: str) -> CompatibilityAdapter:
    return CompatibilityAdapter(module, scope, frozenset(symbols.split()), why, retired_by)


_COMPANION = "app/api/routes/companion.py"
_COMPANION_READ = "legacy companion read route still resolves the selected vault globally"
_COMPANION_PICKER = (
    "legacy single-binding picker/initialize/settings bridge; the selector is the process-wide "
    "VaultManager until the background lifecycles are bound"
)
_ROUTE_FAMILY = "legacy single-binding route still resolves the selected vault globally"
_RESOLUTION_PRIMITIVE = (
    "shared global-resolution primitive every legacy route delegates to; retired with the "
    "single-binding compatibility selector"
)
_CARRIER_NOTE = (
    "agent/MCP carrier resolves its vault from process selection or environment, not from a "
    "request-carried ActiveContextSet"
)
_CLI_NOTE = "operator CLI resolves its vault from process environment or selection, not a request"

COMPATIBILITY_ADAPTERS: tuple[CompatibilityAdapter, ...] = (
    _a("app/agents/ask/graph.py", "_active_recall_vault_id", "get_vault_manager", _CARRIER_NOTE, "05B4"),
    _a("app/agents/ask/graph.py", "_active_recall_vault_root", "get_vault_manager resolve_optional_vault_root", _CARRIER_NOTE, "05B4"),
    _a("app/api/routes/artifacts.py", "read_artifact_note", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/ask.py", "_voice_sessions_for_selected_vault", "resolve_active_vault_root", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/ask.py", "ask_voice", "active_vault_selection_window", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/canvas.py", "_get_vault_root", "resolve_active_vault_root", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/canvas.py", "_get_vault_root_or_picker", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/capture.py", "capture_to_inbox", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a(_COMPANION, "_active_companion_vault_root", "get_vault_manager resolve_optional_vault_root", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_memory_review_selection_required_response", "resolve_optional_vault_root", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_memory_review_vault_context", "get_vault_manager resolve_optional_vault_root", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_recent_vaults_response", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_resolve_browse_base", "resolve_optional_vault_root", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_setting_blocked_reason", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_vault_context_response", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "_vault_identity_state", "env:VAULT_ROOT get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "initialize_companion_vault", "get_vault_manager", _COMPANION_PICKER, "retained:MVR-06"),
    _a(_COMPANION, "read_companion_now", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "read_companion_vault_context", "get_vault_manager resolve_optional_vault_root", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "read_companion_vault_settings", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "read_today_briefing", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "reload_companion_vault", "get_vault_manager", _COMPANION_PICKER, "retained:MVR-06"),
    _a(_COMPANION, "select_companion_vault", "get_vault_manager", _COMPANION_PICKER, "retained:MVR-06"),
    _a(_COMPANION, "trigger_first_contact_briefing", "get_vault_manager", _COMPANION_READ, "05B2"),
    _a(_COMPANION, "update_companion_vault_setting", "get_vault_manager", _COMPANION_PICKER, "retained:MVR-06"),
    _a("app/api/routes/debug.py", "debug_panel", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/eval_drafts.py", "get_pending_eval_drafts", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/eval_drafts.py", "post_eval_draft_decision", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/provisional_memory.py", "post_provisional_memory", "active_vault_root_or_selection_required", _ROUTE_FAMILY, "05B3"),
    _a("app/api/routes/vault_resolution.py", "active_vault_root_or_selection_required", "resolve_active_vault_root", _RESOLUTION_PRIMITIVE, "retained:MVR-06"),
    _a("app/api/routes/vault_resolution.py", "active_vault_selection_window", "get_vault_manager", _RESOLUTION_PRIMITIVE, "retained:MVR-06"),
    _a("app/api/routes/vault_resolution.py", "resolve_active_vault_root", "get_vault_manager resolve_optional_vault_root", _RESOLUTION_PRIMITIVE, "retained:MVR-06"),
    _a("app/cli/__init__.py", "_resolve_mcp_vault_root_path", "env:VAULT_DIR", _CLI_NOTE, "05B4"),
    _a("app/cli/__init__.py", "_resolve_vault_root_path", "resolve_optional_vault_root", _CLI_NOTE, "05B4"),
    _a("app/cli/briefing.py", "_resolve_vault_context", "get_vault_manager", _CLI_NOTE, "05B4"),
    _a("app/cli/episodes.py", "_default_vault_root", "env:VAULT_ROOT", _CLI_NOTE, "05B4"),
    _a("app/cli/health.py", "_check_companion_diagnostics", "env:VAULT_ROOT", _CLI_NOTE, "05B4"),
    _a("app/cli/settings_explain.py", "build_settings_explain_payload", "env:VAULT_ROOT", _CLI_NOTE, "05B4"),
    _a("app/cli/vault.py", "vault_init", "get_vault_manager", _CLI_NOTE, "05B4"),
    _a("app/cli/youtube_inbox_dev.py", "_build_youtube_inbox_dev_services.global_sync_enabled", "get_vault_manager", _CLI_NOTE, "05B4"),
    _a("app/cli/youtube_inbox_dev.py", "drain", "get_vault_manager", _CLI_NOTE, "05B4"),
    _a("app/mcp/vault_tools.py", "_resolve_mcp_env_root", "env:VAULT_DIR", _CARRIER_NOTE, "05B4"),
    _a("app/mcp/vault_tools.py", "get_vault_root", "resolve_optional_vault_root", _CARRIER_NOTE, "05B4"),
)


def adapter_key(entry: CompatibilityAdapter) -> tuple[str, str]:
    return (entry.module, entry.scope)


# --------------------------------------------------------------------------- #
# Entrypoint inventory (derived)
# --------------------------------------------------------------------------- #


def _parse(relative: str) -> ast.Module:
    path = ROOT / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def _module_to_path(module: str) -> str:
    return module.replace(".", "/") + ".py"


def registered_router_modules() -> frozenset[str]:
    """Modules whose router ``app/api/app.py`` passes to ``include_router``."""

    tree = _parse(API_APP_MODULE)
    local_to_module: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                local_to_module[alias.asname or alias.name] = node.module
    registered: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in local_to_module
        ):
            registered.add(_module_to_path(local_to_module[node.args[0].id]))
    return frozenset(registered)


def _python_modules(relative_dir: str) -> frozenset[str]:
    return frozenset(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / relative_dir).glob("*.py")
        if p.name != "__init__.py"
    )


def unclassified_route_modules() -> frozenset[str]:
    """Route modules that are neither registered nor named in the classification."""

    present = _python_modules(API_ROUTES_DIR)
    return present - registered_router_modules() - frozenset(UNREGISTERED_ROUTE_MODULES)


def stale_route_classifications() -> frozenset[str]:
    """Classified-unregistered modules that are now registered or no longer exist."""

    present = _python_modules(API_ROUTES_DIR)
    stale = {
        module
        for module in UNREGISTERED_ROUTE_MODULES
        if module not in present or module in registered_router_modules()
    }
    return frozenset(stale)


def missing_registered_modules() -> frozenset[str]:
    """Registered router modules whose source file does not exist."""

    return frozenset(m for m in registered_router_modules() if not (ROOT / m).is_file())


def entrypoint_modules() -> tuple[str, ...]:
    """Every production request-handling module the gate scans, derived."""

    modules = set(registered_router_modules())
    modules |= _python_modules(API_ROUTES_DIR)
    modules |= set(FIXED_ENTRYPOINT_MODULES)
    # app.py both registers routers and defines its own request handlers.
    modules.add(API_APP_MODULE)
    modules |= _python_modules(CLI_DIR)
    modules |= {f"{CLI_DIR}/__init__.py"}
    return tuple(sorted(m for m in modules if (ROOT / m).is_file()))


# --------------------------------------------------------------------------- #
# Offender detection (AST)
# --------------------------------------------------------------------------- #


def _is_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ"
    )


ENV_READ_FUNCTIONS = frozenset({"getenv", "env_str"})
ENVIRON_READ_METHODS = frozenset({"get", "pop", "setdefault"})


def _name_id(node: ast.AST | None) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _env_names_in(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return ()
    return tuple(
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and element.value in GLOBAL_ENV_NAMES
    )


def _module_env_tuples(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Name-bound literal tuples/lists that carry a global vault env name."""

    bound: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        names = _env_names_in(value)
        if isinstance(target, ast.Name) and names:
            bound[target.id] = names
    return bound


class _Scanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.stack: list[str] = []
        self.found: dict[str, set[str]] = {}
        self._env_loop_names: dict[str | None, tuple[str, ...]] = {}
        self.env_tuples: dict[str, tuple[str, ...]] = {}

    def _record(self, symbol: str) -> None:
        self.found.setdefault(".".join(self.stack) or "<module>", set()).add(symbol)

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # An import alone is not a lookup; remember aliases so a renamed symbol
        # is still recognised when it is used.
        for alias in node.names:
            if alias.name in GLOBAL_RESOLUTION_SYMBOLS and alias.asname:
                self.aliases[alias.asname] = alias.name

    def visit_Name(self, node: ast.Name) -> None:
        canonical = self.aliases.get(node.id, node.id)
        if canonical in GLOBAL_RESOLUTION_SYMBOLS:
            self._record(canonical)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in GLOBAL_RESOLUTION_SYMBOLS:
            self._record(node.attr)
        self.generic_visit(node)

    def _record_env_names(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Constant) and node.value in GLOBAL_ENV_NAMES:
            self._record(ENV_SYMBOL_PREFIX + node.value)

    def visit_Call(self, node: ast.Call) -> None:
        # Only an actual environment read counts: ``os.getenv("VAULT_ROOT")``,
        # ``getenv(...)``, ``env_str(...)`` and ``os.environ.get/pop/setdefault``.
        # A bare literal (an error argument, a docstring) is not a lookup.
        func = node.func
        if node.args and (
            (isinstance(func, ast.Name) and func.id in ENV_READ_FUNCTIONS)
            or (isinstance(func, ast.Attribute) and func.attr in ENV_READ_FUNCTIONS)
            or (
                isinstance(func, ast.Attribute)
                and func.attr in ENVIRON_READ_METHODS
                and _is_environ(func.value)
            )
        ):
            self._record_env_names(node.args[0])
            loop_names = self._env_loop_names.get(_name_id(node.args[0]), ())
            for name in loop_names:
                self._record(ENV_SYMBOL_PREFIX + name)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_environ(node.value):
            self._record_env_names(node.slice)
            for name in self._env_loop_names.get(_name_id(node.slice), ()):
                self._record(ENV_SYMBOL_PREFIX + name)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        # ``for name in ("VAULT_ROOT", "VAULT_DIR"): os.getenv(name)`` reads both.
        names: tuple[str, ...] = ()
        if isinstance(node.target, ast.Name):
            if isinstance(node.iter, (ast.Tuple, ast.List)):
                names = _env_names_in(node.iter)
            elif isinstance(node.iter, ast.Name):
                # ``CANDIDATES = (..., "VAULT_ROOT")`` bound elsewhere in the module.
                names = self.env_tuples.get(node.iter.id, ())
        if names:
            assert isinstance(node.target, ast.Name)
            previous = self._env_loop_names.get(node.target.id)
            self._env_loop_names[node.target.id] = names
            self.generic_visit(node)
            if previous is None:
                self._env_loop_names.pop(node.target.id, None)
            else:
                self._env_loop_names[node.target.id] = previous
            return
        self.generic_visit(node)


def scan_source(source: str, filename: str = "<memory>") -> dict[str, frozenset[str]]:
    """Return ``{function scope: global-resolution symbols}`` for one module."""

    tree = ast.parse(source, filename=filename)
    scanner = _Scanner()
    scanner.env_tuples = _module_env_tuples(tree)
    scanner.visit(tree)
    return {scope: frozenset(symbols) for scope, symbols in scanner.found.items()}


def scan_production_entrypoints() -> dict[tuple[str, str], frozenset[str]]:
    """Measured offenders over the derived entrypoint population."""

    measured: dict[tuple[str, str], frozenset[str]] = {}
    for module in entrypoint_modules():
        source = (ROOT / module).read_text(encoding="utf-8")
        for scope, symbols in scan_source(source, module).items():
            measured[(module, scope)] = symbols
    return measured


def compare_to_allowlist(
    measured: dict[tuple[str, str], frozenset[str]],
    allowlist: tuple[CompatibilityAdapter, ...],
) -> tuple[list[str], list[str]]:
    """Return ``(unlisted_offenders, stale_or_mismatched_entries)``."""

    listed = {adapter_key(entry): entry for entry in allowlist}
    unlisted: list[str] = []
    stale: list[str] = []
    for key, symbols in sorted(measured.items()):
        entry = listed.get(key)
        if entry is None:
            unlisted.append(f"{key[0]} :: {key[1]} -> {sorted(symbols)}")
        elif entry.symbols != symbols:
            stale.append(
                f"{key[0]} :: {key[1]} lists {sorted(entry.symbols)} but resolves {sorted(symbols)}"
            )
    for key in sorted(set(listed) - set(measured)):
        stale.append(f"{key[0]} :: {key[1]} no longer resolves globally; delete the entry")
    return unlisted, stale
