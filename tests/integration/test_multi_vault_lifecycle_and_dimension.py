"""MVR-06D (#3866): the parent lifecycle-and-dimension acceptance target for MVR-06.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D) composed with the MVR-04
dimension authority contract (`GROUP_VAULT_BINDINGS_BY_DIMENSION.md :: Concretely`): a
`work` dimension over vaults A and B resolves to two independently authorized bindings;
grouping never enrols background work or upgrades access, and background lifecycles stay
isolated at zero, one, and many members. Every transition goes through a shipped producer:
the dimension and background-binding headless CLIs, the MVR-06D activation CLI, and the
production watcher and worker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.instance import background_supervisor
from app.instance.background_supervisor import (
    aggregate_background_health,
    process_background_supervisor,
    stored_intent,
)
from tests._mvr06_background_harness import cli
from tests._mvr06b_handoff_harness import (
    bind_runtime_env,
    configure_watcher,
    handoff_through_cli,
    mvr06a_instance,
    stub_settings_reload,
)
from tests._mvr06c_relocation_harness import initialized_registration
from tests._mvr06d_many_binding_harness import activate_many_binding


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch):
    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)
    background_supervisor._PROCESS_SUPERVISORS.clear()
    yield
    background_supervisor._PROCESS_SUPERVISORS.clear()


def _background(registry: str, command: str, binding: str) -> dict:
    receipt = cli(command, "--registry-path", registry, "--vault-binding-id", binding,
                  "--consumer", "cli")
    assert receipt["_exit_code"] == 0, receipt
    return receipt


def _resolve_members(registry: str) -> dict[str, dict]:
    resolved = cli("dimension-resolve", "--registry-path", registry, "--dimension-id", "work",
                   "--consumer", "cli")
    assert resolved["_exit_code"] == 0, resolved
    return {item["vault_binding_id"]: item for item in resolved["members"]}


def test_parent_dimension_background_acceptance(tmp_path, monkeypatch) -> None:
    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
    from app.watcher import registry as watcher_registry
    from app.workers import outbox_worker

    runtime, first, (second,) = mvr06a_instance(tmp_path)
    bind_runtime_env(monkeypatch, runtime, watcher=True)
    assert handoff_through_cli(runtime)["_exit_code"] == 0
    stub_settings_reload(monkeypatch)
    a = initialized_registration(runtime, tmp_path / "alpha")
    b = initialized_registration(runtime, tmp_path / "beta")
    config = configure_watcher(monkeypatch, tmp_path, runtime, Path(first.path))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    registry = str(runtime.layout.registry_path)
    pair = (a.vault_binding_id, b.vault_binding_id)

    intent_before = stored_intent(runtime.registry.load())

    # -- MVR-04: `work` over A and B, two bindings with two independent verdicts -------
    created = cli("dimension-create", "--registry-path", registry, "--dimension-id", "work",
                  "--display-name", "Work", "--vault-binding-id", pair[0],
                  "--vault-binding-id", pair[1], "--consumer", "cli")
    assert created["_exit_code"] == 0, created
    resolved = cli("dimension-resolve", "--registry-path", registry, "--dimension-id", "work",
                   "--consumer", "cli")
    assert resolved["_exit_code"] == 0, resolved
    members = {item["vault_binding_id"]: item for item in resolved["members"]}
    assert tuple(members) == pair
    assert all(item["authorization_epoch"] for item in members.values())
    assert json.dumps(resolved).find(a.path) == -1  # redacted: no content root

    # Grouping confers nothing: creating/resolving the dimension never enrols background
    # work or changes durable intent.
    assert stored_intent(runtime.registry.load()) == intent_before

    # -- zero: explicit-empty idles truthfully -----------------------------------------
    for member in intent_before.effective_binding_ids():
        _background(registry, "background-binding-remove", member)
    assert aggregate_background_health()["status"] == "idle"
    assert outbox_worker.run_once().state == "no_vault"

    # -- one: the dimension's first member under the singleton contract ----------------
    _background(registry, "background-binding-add", pair[0])
    one = process_background_supervisor("worker").reconcile()
    assert one.status == "running" and one.binding_id == pair[0]
    assert one.binding_revision == _resolve_members(registry)[pair[0]]["binding_revision"]
    # The second member is sealed until the matching dispatch contract is enabled.
    sealed = cli("background-binding-add", "--registry-path", registry,
                 "--vault-binding-id", pair[1], "--consumer", "cli")
    assert sealed["_exit_code"] != 0 and sealed["error"] == "capability_not_ready"

    # -- many: activation, then the whole resolved dimension, isolated per binding -----
    assert activate_many_binding(runtime)["_exit_code"] == 0
    background_supervisor._PROCESS_SUPERVISORS.clear()
    for member in resolved["vault_binding_ids"]:
        _background(registry, "background-binding-add", member)
    worker = process_background_supervisor("worker")
    lifecycles = {item.binding_id: item for item in worker.start_all()}
    members = _resolve_members(registry)
    assert tuple(sorted(lifecycles)) == tuple(sorted(pair))
    for binding, lifecycle in lifecycles.items():
        # Each lifecycle carries the dimension member's own binding revision and its own
        # binding-scoped context; the dimension grants nothing beyond each verdict.
        assert lifecycle.status == "running"
        assert lifecycle.context.binding_ids == (binding,)
        assert lifecycle.binding_revision == members[binding]["binding_revision"]
    assert lifecycles[pair[0]].context.context_id != lifecycles[pair[1]].context.context_id

    stamped: list[tuple[str, str]] = []
    real_emit = watcher_registry._emit_watch_event

    def emit(**kwargs):
        stamped.append(
            (resolve_scalar_binding_runtime().vault_binding_id,
             str(Path(kwargs["vault_root"]) / kwargs["rel_path"]))
        )
        return real_emit(**kwargs)

    monkeypatch.setattr(watcher_registry, "_emit_watch_event", emit)
    (Path(a.path) / "work-a.md").write_text("a\n", encoding="utf-8")
    (Path(b.path) / "work-b.md").write_text("b\n", encoding="utf-8")
    assert set(watcher_registry.run_registry_once(config)) == set(pair)
    by_note = {note: binding for binding, note in stamped}
    assert by_note[str(Path(a.path) / "work-a.md")] == pair[0]
    assert by_note[str(Path(b.path) / "work-b.md")] == pair[1]
    tick = outbox_worker.run_once()
    assert {item["scope"] for item in tick.many_binding["scopes"]} >= set(pair)

    # -- deleting the dimension leaves registrations and background intent untouched --
    deleted = cli("dimension-delete", "--registry-path", registry, "--dimension-id", "work",
                  "--consumer", "cli")
    assert deleted["_exit_code"] == 0, deleted
    snapshot = runtime.registry.load()
    assert set(pair) <= set(snapshot.registrations)
    assert set(stored_intent(snapshot).effective_binding_ids()) == set(pair)
    assert aggregate_background_health()["status"] == "healthy"
