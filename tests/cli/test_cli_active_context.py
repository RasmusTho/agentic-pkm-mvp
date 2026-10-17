"""MVR-05B4a (#6160): each vault-bound CLI entrypoint resolves one explicit context.

Every vault-bound entrypoint named by the MVR-05B1 allowlist is invoked through
its production command (or the production entry function it shares with the
API). The CLI resolver is observed, not replaced: each invocation must call it
exactly once, take the instance default over every legacy vault environment key
when an instance registry is bound, honour an explicit option, and -- once
resolved -- never read a vault environment key or the process vault manager from
CLI code again.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from click.testing import CliRunner

import importlib

import app.config.paths as config_paths
import app.vault.manager as vault_manager_module
from app.cli import cli
from tests._mvr03_principal_harness import provisioned_instance

# ``app.cli`` re-exports click groups under some submodule names (``health``), so
# the modules are taken from the import system, never from package attributes.
cli_package = importlib.import_module("app.cli")
briefing_cli = importlib.import_module("app.cli.briefing")
episodes_cli = importlib.import_module("app.cli.episodes")
health_cli = importlib.import_module("app.cli.health")
settings_explain_cli = importlib.import_module("app.cli.settings_explain")
vault_cli_module = importlib.import_module("app.cli.vault")
vault_context_module = importlib.import_module("app.cli.vault_context")
youtube_cli = importlib.import_module("app.cli.youtube_inbox_dev")

VAULT_KEYS = frozenset(
    {"VAULT_ROOT", "VAULT_DIR", "MCP_VAULT_ROOT", "EPISODES_VAULT_ROOT", "WATCHER_VAULT_PATH"}
)
_CONSUMERS = (
    cli_package,
    briefing_cli,
    episodes_cli,
    health_cli,
    settings_explain_cli,
    vault_cli_module,
    youtube_cli,
)


class _Seal:
    """Counts resolutions and fails any CLI-side global read after the first one."""

    def __init__(self) -> None:
        self.calls = 0
        self.sealed = False
        self.violations: list[str] = []

    def reset(self) -> None:
        self.calls = 0
        self.sealed = False


def _cli_caller(depth: int = 2) -> str:
    module = sys._getframe(depth).f_globals.get("__name__", "")
    return module if module.startswith("app.cli") else ""


@pytest.fixture()
def seal(monkeypatch: pytest.MonkeyPatch) -> _Seal:
    state = _Seal()
    real_resolve = vault_context_module.resolve_cli_vault_context

    def _resolve(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        if state.sealed:
            state.violations.append("second resolution in one invocation")
        state.calls += 1
        try:
            return real_resolve(*args, **kwargs)
        finally:
            state.sealed = True

    for module in _CONSUMERS:
        monkeypatch.setattr(module, "resolve_cli_vault_context", _resolve)

    real_getenv = vault_context_module.os.getenv

    def _getenv(key: str, default: Any = None) -> Any:
        caller = _cli_caller()
        if state.sealed and key in VAULT_KEYS and caller:
            state.violations.append(f"{caller} read {key} after resolution")
        return real_getenv(key, default)

    monkeypatch.setattr(vault_context_module.os, "getenv", _getenv)

    def _poisoned(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def _call(*args: Any, **kwargs: Any) -> Any:
            caller = _cli_caller()
            if state.sealed and caller:
                state.violations.append(f"{caller} called {name} after resolution")
            return real(*args, **kwargs)

        return _call

    monkeypatch.setattr(
        vault_manager_module,
        "get_vault_manager",
        _poisoned("get_vault_manager", vault_manager_module.get_vault_manager),
    )
    monkeypatch.setattr(
        config_paths,
        "resolve_optional_vault_root",
        _poisoned("resolve_optional_vault_root", config_paths.resolve_optional_vault_root),
    )
    return state


@pytest.fixture()
def instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, first, _extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(tmp_path / "app-local.md"))
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    for key in VAULT_KEYS:
        monkeypatch.setenv(key, str(decoy))
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    return Path(first.path).expanduser().resolve(), decoy


def _invoke(*args: str) -> Any:
    result = CliRunner().invoke(cli, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result


def test_vault_bound_cli_resolves_one_context_per_invocation(
    instance, seal: _Seal, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    default_root, decoy = instance
    seen: dict[str, Any] = {}

    def run(label: str, action: Callable[[], Any]) -> None:
        seal.reset()
        action()
        assert seal.calls == 1, (label, seal.calls)
        assert not seal.violations, (label, seal.violations)

    # episodes tick: instance default wins over EPISODES_VAULT_ROOT/WATCHER_VAULT_PATH/VAULT_ROOT.
    monkeypatch.setattr(
        episodes_cli,
        "run_segmentation_tick",
        lambda *, vault_root: seen.__setitem__("tick", vault_root)
        or {"consumed": 0, "proposed": [], "open_segments": 0},
    )
    monkeypatch.setattr(
        episodes_cli,
        "run_recut_tick",
        lambda *, vault_root: {"recut_detected": 0, "accepted": 0, "bindings_corrected": 0},
    )
    run("episodes tick", lambda: _invoke("episodes", "tick", "--json"))
    assert Path(seen["tick"]).resolve() == default_root

    # episodes rebuild-projection: the explicit option is this invocation's selection.
    explicit = tmp_path / "explicit-vault"
    explicit.mkdir()
    monkeypatch.setattr(
        episodes_cli,
        "rebuild_episodes_projection",
        lambda vault_root: seen.__setitem__("rebuild", vault_root)
        or SimpleNamespace(total_notes=0, inserted=0, skipped_invalid=[]),
    )
    run(
        "episodes rebuild-projection",
        lambda: CliRunner().invoke(
            cli, ["episodes", "rebuild-projection", "--vault-root", str(explicit)]
        ),
    )
    assert Path(seen["rebuild"]).resolve() == explicit.resolve()

    # briefing tick: the picker-following command also takes the instance default.
    monkeypatch.setattr(
        briefing_cli,
        "scheduled_briefing_tick",
        lambda *, vault_context, **_k: seen.__setitem__("briefing", vault_context)
        or SimpleNamespace(generated=False, reason="test", for_date=None, to_dict=lambda: {}),
    )
    run("briefing tick", lambda: CliRunner().invoke(cli, ["briefing", "tick", "--json"]))
    assert Path(seen["briefing"].active_vault_path).resolve() == default_root

    # vault-layout-ensure (the shared _resolve_vault_root_path journey).
    import app.vault.layout as layout_module

    monkeypatch.setattr(
        layout_module,
        "ensure_vault_layout_report",
        lambda root: seen.__setitem__("layout", root)
        or (SimpleNamespace(system_folder="s", inbox_folder="i", desk_folder="d", note_path="n"), False, []),
    )
    run("vault-layout-ensure", lambda: _invoke("vault-layout-ensure", "--json"))
    assert Path(seen["layout"]).resolve() == default_root

    # vault init: the required --path is the context; the process manager is never used.
    class _Manager:
        def initialize_vault(self, path, **_kwargs):  # type: ignore[no-untyped-def]
            seen["init"] = path
            return SimpleNamespace(
                created_files=[], skipped_existing_files=[], context=SimpleNamespace(status="selected")
            )

    monkeypatch.setattr(vault_cli_module, "VaultManager", _Manager)
    run("vault init", lambda: _invoke("vault", "init", "--path", str(explicit), "--no-remember"))
    assert Path(seen["init"]).resolve() == explicit.resolve()

    # youtube-inbox-dev drain: one context for the whole drain pass.
    class _Queue:
        def claim_batch(self, _n):  # type: ignore[no-untyped-def]
            return []

        def reset_stale_in_progress(self, *_a, **_k):  # type: ignore[no-untyped-def]
            return 0

    # The dev/secret preflight is orthogonal to vault resolution.
    monkeypatch.setattr(youtube_cli, "_require_dev_and_secrets", lambda: None)
    monkeypatch.setattr(
        youtube_cli, "AcquisitionRequests", SimpleNamespace(for_runtime=lambda: _Queue())
    )
    monkeypatch.setattr(
        youtube_cli,
        "carrier_vault_context",
        lambda carrier: seen.__setitem__("drain", carrier)
        or SimpleNamespace(is_selected=True, active_vault_path=str(carrier.root)),
    )
    run(
        "youtube-inbox-dev drain",
        lambda: CliRunner().invoke(cli, ["youtube-inbox-dev", "drain", "--max", "1"]),
    )
    assert seen["drain"].root == default_root
    assert seen["drain"].source == "instance_default"

    # settings explain (shared payload entry).
    monkeypatch.setattr(
        settings_explain_cli, "resolve_settings_file", lambda root, *_a, **_k: seen.__setitem__(
            "explain", root
        ) or (decoy / "missing.md")
    )
    run("settings explain payload", settings_explain_cli.build_settings_explain_payload)

    # health: companion diagnostics inspect the resolved root, not VAULT_ROOT.
    for name in (
        "_check_ffmpeg",
        "_check_yt_dlp",
        "_check_outbox_path",
        "_check_dead_letters",
        "_check_panel_actions",
        "_check_obsidian_dependencies",
        "_check_llm_router",
        "_check_llm_providers",
        "_check_embedding_index",
        "_check_youtube_sync",
        "_watcher_runtime_status",
        "_worker_runtime_status",
        "_db_runtime_status",
        "_settings_ingestion_status",
        "_check_authority_spine",
    ):
        monkeypatch.setattr(health_cli, name, lambda *_a, **_k: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(health_cli, "_check_llm_access", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(health_cli, "_llm_runtime_status", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(health_cli, "check_v6_seams", lambda: {})
    monkeypatch.setattr(health_cli, "get_runtime_version", lambda: {"git_sha": "test"})
    monkeypatch.setattr(
        health_cli,
        "companion_diagnostics_summary",
        lambda root: seen.__setitem__("health", root) or {"duplicate_companion_count": 0},
    )
    run("health", health_cli.run_health)
    assert Path(seen["health"]).resolve() == default_root

    # The decoy legacy roots were never the resolved context of any invocation.
    assert decoy.resolve() not in {
        Path(str(value)).resolve()
        for key, value in seen.items()
        if key in {"tick", "layout", "health"}
    }


def test_cli_resolution_precedence_without_a_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an instance registry the named compatibility journey applies, then no-vault."""

    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
    for key in VAULT_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        vault_context_module, "_compatibility_process_selection",
        lambda: vault_manager_module.no_vault_context(),
    )
    resolve = vault_context_module.resolve_cli_vault_context

    assert resolve().is_no_vault
    assert resolve(default_path=Path("vault")).root == Path("vault")

    episodes_root = tmp_path / "episodes"
    monkeypatch.setenv("EPISODES_VAULT_ROOT", str(episodes_root))
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "missing-channel"))
    carrier = resolve(env_policy="episodes")
    assert carrier.root == episodes_root and carrier.provenance == "env:EPISODES_VAULT_ROOT"

    # A set-but-missing channel root fails loud for the validated policies.
    with pytest.raises(vault_context_module.CliVaultContextError):
        resolve(env_policy="channel")
    monkeypatch.setenv("MCP_VAULT_ROOT", str(tmp_path / "missing-mcp"))
    with pytest.raises(vault_context_module.CliVaultContextError):
        resolve(env_policy="mcp")

    # An explicit option always wins and reads nothing else.
    assert resolve(tmp_path / "x", env_policy="mcp").source == "explicit_selection"


def test_bound_registry_no_vault_is_authoritative_over_command_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#6168 review: a registry that selects no vault never yields a ./vault default."""

    runtime, _first, _extra, _record = provisioned_instance(tmp_path, set_instance_default=False)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    for key in VAULT_KEYS:
        monkeypatch.delenv(key, raising=False)
    resolve = vault_context_module.resolve_cli_vault_context

    carrier = resolve(default_path=Path("vault"))

    assert carrier.is_no_vault
    assert carrier.root is None


def test_configured_but_missing_registry_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#6168 review: only an unset registry variable selects the legacy journey."""

    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(tmp_path / "missing" / "registry.json"))
    fallback = tmp_path / "legacy"
    fallback.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(fallback))
    resolve = vault_context_module.resolve_cli_vault_context

    with pytest.raises(vault_context_module.CliVaultContextError):
        resolve(env_policy="channel")
