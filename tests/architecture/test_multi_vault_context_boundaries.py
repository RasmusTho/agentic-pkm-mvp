"""Structural guard for MVR-05B request consumers (MVR-05B1, #6136).

The gate scans the real production request entrypoints (derived, not listed),
detects global vault resolution by AST, and compares the measured offenders to a
named compatibility-adapter allowlist in both directions. The helper module
``context_boundary_inventory`` owns the derivation and the allowlist; 05B2-05B4
shrink the allowlist and never edit this test.
"""

from __future__ import annotations

import ast

import pytest

from tests.architecture import context_boundary_inventory as inventory
from tests.architecture.context_boundary_inventory import (
    COMPATIBILITY_ADAPTERS,
    ROOT,
    CompatibilityAdapter,
    adapter_key,
    compare_to_allowlist,
    scan_production_entrypoints,
    scan_source,
)

_MIGRATED_ROUTE_MODULES = ("app/api/routes/search.py",)
# The carrier allowlist entries MVR-05B4a (#6160) migrated.
_MIGRATED_CARRIER_ENTRIES = frozenset(
    {
        ("app/agents/ask/graph.py", "_active_recall_vault_id"),
        ("app/agents/ask/graph.py", "_active_recall_vault_root"),
        ("app/cli/__init__.py", "_resolve_mcp_vault_root_path"),
        ("app/cli/__init__.py", "_resolve_vault_root_path"),
        ("app/cli/briefing.py", "_resolve_vault_context"),
        ("app/cli/episodes.py", "_default_vault_root"),
        ("app/cli/health.py", "_check_companion_diagnostics"),
        ("app/cli/settings_explain.py", "build_settings_explain_payload"),
        ("app/cli/vault.py", "vault_init"),
        ("app/cli/youtube_inbox_dev.py", "_build_youtube_inbox_dev_services.global_sync_enabled"),
        ("app/cli/youtube_inbox_dev.py", "drain"),
        ("app/mcp/vault_tools.py", "_resolve_mcp_env_root"),
        ("app/mcp/vault_tools.py", "get_vault_root"),
    }
)
# Vault-bound CLI modules that now resolve only through app/cli/vault_context.py.
_MIGRATED_CARRIER_MODULES = (
    "app/cli/__init__.py",
    "app/cli/briefing.py",
    "app/cli/episodes.py",
    "app/cli/health.py",
    "app/cli/settings_explain.py",
    "app/cli/vault.py",
    "app/cli/youtube_inbox_dev.py",
)


def _names_in(relative: str, scope: str) -> set[str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == scope:
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
            }
    raise AssertionError(f"{scope} not found in {relative}")


def test_request_consumers_use_context_seam() -> None:
    """No request-bound production code resolves the vault globally outside the allowlist."""

    measured = scan_production_entrypoints()
    unlisted, _ = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert not unlisted, (
        "new direct global vault resolution in a production request entrypoint; route it "
        "through the scoped seam (app/api/request_active_context.py) instead of adding an "
        "allowlist entry:\n" + "\n".join(unlisted)
    )

    # The consumers already migrated by #5456 stay on the seam: they use it and
    # hold no allowlist entry.
    for module in _MIGRATED_ROUTE_MODULES:
        assert not [k for k in measured if k[0] == module], module
    assert not [k for k in measured if k == ("app/api/routes/ask.py", "ask")]
    assert "require_scoped_read_context" in _names_in(
        "app/api/routes/companion.py", "list_scoped_vault_notes"
    )
    assert ("app/api/routes/companion.py", "list_scoped_vault_notes") not in measured


def test_context_boundary_inventory_and_allowlist_are_exact() -> None:
    """Inventory is derived and fully classified; the allowlist is neither short nor stale."""

    assert not inventory.missing_registered_modules()
    assert not inventory.missing_fixed_entrypoints()
    assert not inventory.unclassified_route_modules(), (
        "request-handling route module is neither registered in app/api/app.py nor named in "
        "UNREGISTERED_ROUTE_MODULES"
    )
    assert not inventory.stale_route_classifications()

    modules = set(inventory.entrypoint_modules())
    assert {
        "app/api/routes/companion.py",
        "app/api/routers/agent.py",
        "app/agents/ask/graph.py",
        "app/mcp/vault_tools.py",
        "app/cli/__init__.py",
    } <= modules
    assert inventory.registered_router_modules() <= modules

    measured = scan_production_entrypoints()
    unlisted, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert not unlisted, "unlisted global resolution:\n" + "\n".join(unlisted)
    assert not stale, "stale or mismatched allowlist entries (the list may only shrink):\n" + "\n".join(
        stale
    )

    keys = [adapter_key(entry) for entry in COMPATIBILITY_ADAPTERS]
    assert len(keys) == len(set(keys)), "duplicate allowlist entry"
    # MVR-05B4a migrated every agent/MCP/CLI carrier entry; none may come back.
    assert set(keys).isdisjoint(_MIGRATED_CARRIER_ENTRIES)
    assert "05B4" not in inventory.RETIRING_STAGES
    for module in _MIGRATED_CARRIER_MODULES:
        assert not [k for k in measured if k[0] == module], module
    for entry in COMPATIBILITY_ADAPTERS:
        assert entry.module in modules, entry
        assert entry.why.strip(), entry
        assert entry.retired_by in inventory.RETIRING_STAGES, entry
        assert entry.symbols, entry


# --------------------------------------------------------------------------- #
# The gate must fail on what it claims to catch.
# --------------------------------------------------------------------------- #


def test_gate_fails_on_injected_unlisted_global_lookup() -> None:
    injected = scan_source(
        "from app.vault.manager import get_vault_manager\n"
        "def brand_new_route():\n"
        "    return get_vault_manager().context\n",
        "app/api/routes/injected.py",
    )
    measured = scan_production_entrypoints()
    measured[("app/api/routes/injected.py", "brand_new_route")] = injected["brand_new_route"]
    unlisted, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert unlisted == ["app/api/routes/injected.py :: brand_new_route -> ['get_vault_manager']"]
    assert not stale


def test_gate_fails_on_new_symbol_in_a_listed_function() -> None:
    entry = COMPATIBILITY_ADAPTERS[0]
    measured = scan_production_entrypoints()
    measured[adapter_key(entry)] = entry.symbols | {"env:VAULT_ROOT"}
    _, stale = compare_to_allowlist(measured, COMPATIBILITY_ADAPTERS)
    assert len(stale) == 1 and entry.scope in stale[0]


def test_gate_fails_on_stale_allowlist_entry() -> None:
    ghost = CompatibilityAdapter(
        "app/api/routes/capture.py",
        "migrated_away",
        frozenset({"get_vault_manager"}),
        "pretends to resolve globally",
        "05B3",
    )
    unlisted, stale = compare_to_allowlist(
        scan_production_entrypoints(), (*COMPATIBILITY_ADAPTERS, ghost)
    )
    assert not unlisted
    assert stale == ["app/api/routes/capture.py :: migrated_away no longer resolves globally; delete the entry"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    return get_vault_manager()\n", {"get_vault_manager"}),
        ("def f():\n    return mod.get_vault_manager()\n", {"get_vault_manager"}),
        (
            "from x import get_vault_manager as gvm\ndef f():\n    return gvm()\n",
            {"get_vault_manager"},
        ),
        (
            "from fastapi import Depends\ndef f(m=Depends(get_vault_manager)):\n    return m\n",
            {"get_vault_manager"},
        ),
        ("import os\ndef f():\n    return os.getenv('VAULT_ROOT')\n", {"env:VAULT_ROOT"}),
        ("import os\ndef f():\n    return os.environ.get('VAULT_DIR')\n", {"env:VAULT_DIR"}),
        ("import os\ndef f():\n    return os.environ['VAULT_ROOT']\n", {"env:VAULT_ROOT"}),
        (
            "def f():\n    return active_vault_root_or_selection_required()\n",
            {"active_vault_root_or_selection_required"},
        ),
        ("def f():\n    return resolve_optional_vault_root()\n", {"resolve_optional_vault_root"}),
        ("def f():\n    return resolve_active_vault_root()\n", {"resolve_active_vault_root"}),
        ("def f():\n    return resolve_vault_root()\n", {"resolve_vault_root"}),
        ("import os\ndef f():\n    return os.getenv(key='VAULT_ROOT')\n", {"env:VAULT_ROOT"}),
        ("def f():\n    return env_str(key='VAULT_DIR')\n", {"env:VAULT_DIR"}),
        (
            "from os import getenv as read_env\ndef f():\n    return read_env('VAULT_ROOT')\n",
            {"env:VAULT_ROOT"},
        ),
        (
            "from os import environ as env\ndef f():\n    return env.get('VAULT_DIR')\n",
            {"env:VAULT_DIR"},
        ),
        (
            "import os\ndef f():\n    for n in ('X', 'VAULT_DIR'):\n        v = os.getenv(n)\n",
            {"env:VAULT_DIR"},
        ),
        (
            "import os\nNAMES = ('X', 'VAULT_ROOT')\n"
            "def f():\n    for n in NAMES:\n        v = os.getenv(n)\n",
            {"env:VAULT_ROOT"},
        ),
        (
            "import os\nVAULT_KEY = 'VAULT_ROOT'\ndef f():\n    return os.getenv(VAULT_KEY)\n",
            {"env:VAULT_ROOT"},
        ),
        (
            "import os\nNAMES = ('VAULT_DIR',)\n"
            "def f():\n    return next(os.getenv(n) for n in NAMES)\n",
            {"env:VAULT_DIR"},
        ),
        (
            "import os\ndef f():\n    return [os.environ[n] for n in ('VAULT_ROOT',)]\n",
            {"env:VAULT_ROOT"},
        ),
    ],
)
def test_detector_sees_structural_forms_not_substrings(source: str, expected: set[str]) -> None:
    found = scan_source(source)
    assert set().union(*found.values()) == expected


def test_gate_tracks_all_vault_env_keys_nested_modules_and_environ_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """MVR-05B4a closes KD-55D38D90BD05, KD-88B6B1EC0D9A and KD-6BC9153BD3A2."""

    # KD-55D38D90BD05: every process-global vault env key is a recorded read.
    keys = ("VAULT_ROOT", "VAULT_DIR", "MCP_VAULT_ROOT", "EPISODES_VAULT_ROOT", "WATCHER_VAULT_PATH")
    assert inventory.GLOBAL_ENV_NAMES == frozenset(keys)
    for key in keys:
        found = scan_source(f"import os\ndef f():\n    return os.getenv({key!r})\n")
        assert found == {"f": frozenset({f"env:{key}"})}, key
    candidates = scan_source(
        "import os\nCANDIDATES = ('EPISODES_VAULT_ROOT', 'WATCHER_VAULT_PATH')\n"
        "def f():\n    for name in CANDIDATES:\n        os.getenv(name)\n"
    )
    assert candidates == {"f": frozenset({"env:EPISODES_VAULT_ROOT", "env:WATCHER_VAULT_PATH"})}

    # KD-6BC9153BD3A2: an assigned os.environ alias is still an environment read,
    # including chains, `or`/conditional fallbacks and parameter defaults.
    aliased = {
        "import os\ndef f():\n    env = os.environ\n    return env.get('VAULT_ROOT')\n": "VAULT_ROOT",
        "import os\nENV = os.environ\ndef f():\n    return ENV['MCP_VAULT_ROOT']\n": "MCP_VAULT_ROOT",
        "import os\ndef f():\n    a = os.environ\n    b = a\n    return b.get('VAULT_DIR')\n": "VAULT_DIR",
        "import os\ndef f(m=None):\n    env = m or os.environ\n    return env.get('WATCHER_VAULT_PATH')\n": (
            "WATCHER_VAULT_PATH"
        ),
        "import os\ndef f(m=None):\n    env = m if m is not None else os.environ\n"
        "    return env.get('EPISODES_VAULT_ROOT')\n": "EPISODES_VAULT_ROOT",
        "import os\ndef f(env=os.environ):\n    return env.get('VAULT_ROOT')\n": "VAULT_ROOT",
        "import os\ndef f(*, env=os.environ):\n    return env['VAULT_DIR']\n": "VAULT_DIR",
        "from os import environ as E\ndef f():\n    env = E\n    return env.get('VAULT_ROOT')\n": "VAULT_ROOT",
    }
    for source, key in aliased.items():
        assert set().union(*scan_source(source).values()) == {f"env:{key}"}, source
    # A plain mapping that is not the environment is not a process-global read.
    assert scan_source("def f():\n    env = {}\n    return env.get('VAULT_ROOT')\n") == {}

    # KD-88B6B1EC0D9A: nested route/CLI modules are part of the population and are
    # classified like top-level ones.
    fake_root = tmp_path
    for relative in (
        "app/api/routes/__init__.py",
        "app/api/routes/helpers/__init__.py",
        "app/api/routes/helpers/vault.py",
        "app/cli/__init__.py",
        "app/cli/tools/deep.py",
    ):
        path = fake_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr(inventory, "ROOT", fake_root)
    assert inventory._python_modules(inventory.API_ROUTES_DIR) == frozenset(
        {"app/api/routes/helpers/__init__.py", "app/api/routes/helpers/vault.py"}
    )
    assert inventory._python_modules(inventory.CLI_DIR) == frozenset({"app/cli/tools/deep.py"})
    monkeypatch.setattr(inventory, "registered_router_modules", lambda: frozenset())
    assert "app/api/routes/helpers/vault.py" in inventory.unclassified_route_modules()


def test_detector_ignores_import_only_comments_and_docstrings() -> None:
    source = (
        "from x import get_vault_manager\n"
        "def f():\n"
        '    """Mentions get_vault_manager and VAULT_ROOT in prose."""\n'
        "    # get_vault_manager()\n"
        "    return require_scoped_read_context()\n"
    )
    assert scan_source(source) == {}


def test_detector_ignores_vault_env_literals_outside_environment_reads() -> None:
    """#6152 review: an error argument naming VAULT_ROOT is not a global lookup."""

    source = (
        "def f():\n"
        "    raise VaultRootMisconfiguredError('VAULT_ROOT', 'unset')\n"
        "def g():\n"
        "    return {'VAULT_DIR': 1}\n"
    )
    assert scan_source(source) == {}


def test_gate_fails_when_a_fixed_entrypoint_disappears(monkeypatch: pytest.MonkeyPatch) -> None:
    """#6152 review: a renamed fixed entrypoint fails instead of leaving the population."""

    monkeypatch.setattr(
        inventory,
        "FIXED_ENTRYPOINT_MODULES",
        (*inventory.FIXED_ENTRYPOINT_MODULES, "app/agents/ask/renamed_graph.py"),
    )
    assert inventory.missing_fixed_entrypoints() == {"app/agents/ask/renamed_graph.py"}


def test_application_module_handlers_are_scanned() -> None:
    """#6152 review: app.py defines its own handlers, not only router registration."""

    assert inventory.API_APP_MODULE in inventory.entrypoint_modules()


def test_gate_fails_on_unclassified_request_module(monkeypatch: pytest.MonkeyPatch) -> None:
    real = inventory._python_modules

    def with_extra(relative_dir: str) -> frozenset[str]:
        extra = {"app/api/routes/surprise.py"} if relative_dir == inventory.API_ROUTES_DIR else set()
        return real(relative_dir) | frozenset(extra)

    monkeypatch.setattr(inventory, "_python_modules", with_extra)
    assert inventory.unclassified_route_modules() == frozenset({"app/api/routes/surprise.py"})


def test_gate_fails_on_stale_route_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(inventory.UNREGISTERED_ROUTE_MODULES, "app/api/routes/ghost.py", "gone")
    monkeypatch.setitem(inventory.UNREGISTERED_ROUTE_MODULES, "app/api/routes/ask.py", "registered")
    assert inventory.stale_route_classifications() == frozenset(
        {"app/api/routes/ghost.py", "app/api/routes/ask.py"}
    )


# --- MVR-05D: closed production outbox producer registry (#3862) ---------------

_OUTBOX_PRODUCER_CALLS = frozenset({"write_outbox_event", "insert_object_and_outbox"})
_OUTBOX_DEFINING_MODULE = "app/services/outbox.py"


def _outbox_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _discover_outbox_call_sites() -> tuple[list[tuple[str, str, int, str | None]], list[str]]:
    """Every production DB-outbox call site and every non-call alias of the seam."""

    sites: list[tuple[str, str, int, str | None]] = []
    aliases: list[str] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        relative = str(path.relative_to(ROOT))
        if relative == _OUTBOX_DEFINING_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        call_funcs = {
            id(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _outbox_call_name(node.func) in _OUTBOX_PRODUCER_CALLS
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _outbox_call_name(node.func) in _OUTBOX_PRODUCER_CALLS:
                chain: list[str] = []
                current = parents.get(node)
                while current is not None:
                    if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        chain.append(current.name)
                    current = parents.get(current)
                producer = next(
                    (
                        keyword.value.value
                        for keyword in node.keywords
                        if keyword.arg == "producer"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ),
                    None,
                )
                sites.append((relative, ".".join(reversed(chain)), node.lineno, producer))
            elif (
                isinstance(node, (ast.Name, ast.Attribute))
                and _outbox_call_name(node) in _OUTBOX_PRODUCER_CALLS
                and id(node) not in call_funcs
            ):
                # Passing the seam around (``emit = write_outbox_event``) would hide
                # an unregistered call site from this gate.
                aliases.append(f"{relative}:{node.lineno}")
    return sites, aliases


def test_vault_bound_outbox_producers_cannot_emit_legacy_envelopes() -> None:
    """MVR-05D: every production outbox call site is registered; none writes a legacy envelope."""

    from app.events.models import new_event
    from app.services import outbox as outbox_service
    from app.services.outbox_producers import (
        OUTBOX_ENVELOPE_VERSION,
        PRODUCER_REGISTRY,
        OutboxProducerRoutingError,
        UnregisteredOutboxProducerError,
    )

    sites, aliases = _discover_outbox_call_sites()
    assert sites, "the production outbox call-site scan found nothing"
    assert aliases == [], f"outbox seam referenced outside a direct call: {aliases}"

    unregistered = [
        f"{module}:{line} {function}" for module, function, line, producer in sites if producer is None
    ]
    assert unregistered == [], (
        "production outbox call sites without a literal registered producer= "
        f"(add them to app/services/outbox_producers.py): {unregistered}"
    )
    misplaced = []
    for module, function, line, producer in sites:
        registered = PRODUCER_REGISTRY.get(producer or "")
        if registered is None or (registered.module, registered.function) != (module, function):
            misplaced.append(f"{module}:{line} {function} -> {producer}")
    assert misplaced == [], f"producer ids that are unknown or belong to another call site: {misplaced}"

    used = {producer for *_rest, producer in sites}
    stale = sorted(set(PRODUCER_REGISTRY) - used)
    assert stale == [], f"registered producers with no production call site: {stale}"

    families = {producer.family for producer in PRODUCER_REGISTRY.values()}
    assert {"watcher", "api", "ingest", "capture", "heimdal", "shared"} <= families
    assert all(
        producer.routing in {"vault_bound", "global", "inherited"}
        for producer in PRODUCER_REGISTRY.values()
    )

    # Runtime half: the choke point never writes a legacy envelope, refuses an
    # unregistered producer, and refuses a routing-class contradiction.
    statements: list[tuple[str, tuple]] = []

    class _Conn:
        def execute(self, sql, params=()):
            statements.append((sql, tuple(params)))

            class _Cursor:
                def fetchone(self_inner):
                    return (params[0],)

            return _Cursor()

    key = outbox_service.derive_idempotency_key("mvr05d.guard", "source", "fingerprint")
    with pytest.raises(UnregisteredOutboxProducerError):
        outbox_service.write_outbox_event(
            new_event(event_type="mvr05d.guard", payload={}),
            conn=_Conn(),
            idempotency_key=key,
            producer="unregistered.call_site",
        )
    with pytest.raises(OutboxProducerRoutingError):
        outbox_service.write_outbox_event(
            new_event(event_type="mvr05d.guard", payload={}),
            conn=_Conn(),
            idempotency_key=key,
            vault_binding_id="explicitly-global",
            producer="ingest.vault_sync",
        )
    with pytest.raises(OutboxProducerRoutingError):
        outbox_service.write_outbox_event(
            new_event(event_type="mvr05d.guard", payload={}),
            conn=_Conn(),
            idempotency_key=key,
            vault_binding_id="binding-a",
            producer="shared.instance.default_vault",
        )
    assert statements == [], "a refused emission reached the outbox insert"

    for producer in (None, "ingest.vault_sync"):
        legacy_meta = {"vault_binding_id": "forged", "binding_revision": 99}
        outbox_service.write_outbox_event(
            new_event(event_type="mvr05d.guard", payload={}, meta=legacy_meta),
            conn=_Conn(),
            idempotency_key=key,
            vault_binding_id="binding-a",
            producer=producer,
        )
        sql, params = statements[-1]
        assert sql.lower().startswith("insert into outbox")
        stored = new_event(event_type="x").model_validate_json(params[2])
        meta = dict(stored.meta or {})
        assert meta["outbox_envelope"] == OUTBOX_ENVELOPE_VERSION
        assert meta["routing_class"] == "vault_bound"
        assert meta["vault_binding_id"] == "binding-a"
        assert "binding_revision" not in meta, "a forged source stamp survived re-stamping"
        assert meta["idempotency"] == {"legacy_key": key, "binding_scoped_key": params[0]}
        assert meta["producer_context"]["kind"] == "no_binding_runtime"
        assert meta["outbox_producer"] == producer
