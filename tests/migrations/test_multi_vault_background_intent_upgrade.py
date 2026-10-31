"""MVR-06A (#3863): the MVR-06 minimum-runtime floor precedes every background write.

Unmarked on purpose, like `test_local_operator_principal_upgrade.py`: this is a private
instance-state *file* migration and runs in the default `pytest -q -m "not pg"` gate.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.instance.background_authority import (
    BackgroundAuthorityPreflightError,
    BackgroundRuntimeRoleStore,
    background_role_path,
)
from app.instance.background_intent import (
    BACKGROUND_INTENT_KEY,
    BackgroundBindingIntent,
)
from app.instance.mvr05_cutover import (
    discover_db_producer_fence,
    validate_mvr05_runtime_floor,
)
from app.instance.runtime import (
    _preflight_runtime,
    _require_runtime_floor,
    local_operator_principal_path,
)
from app.instance.vault_registry import (
    BACKGROUND_INTENT_REGISTRY_SCHEMA,
    CURRENT_REGISTRY_SCHEMA,
    CapabilityNotReadyError,
    RegistryError,
    VaultRegistryStore,
)
from tests._mvr06_background_harness import (
    mvr05_instance,
    run_background_cutover_through_cli,
)
from tests._mvr_default_vault_harness import REPO_ROOT
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

#: The last pre-MVR-06 image on main: MVR-05D (#3862, PR #6492).
MVR05D_IMAGE_SHA = "92e6740a46cf8f5b4fd8b54e50715443e321b352"


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch):
    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def previous_registry_image():
    """The MVR-05D image's own registry reader, executed unmodified."""

    source = subprocess.check_output(
        ["git", "show", f"{MVR05D_IMAGE_SHA}:app/instance/vault_registry.py"],
        cwd=REPO_ROOT,
        text=True,
    )
    module = types.ModuleType("tests._mvr06a_previous_registry_image")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, "mvr05d-registry-image.py", "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(module.__name__, None)


def _preflight(runtime, consumer: str) -> int:
    return _preflight_runtime(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        consumer=consumer,
    )


def _lineage(runtime) -> dict[str, object]:
    """Everything the MVR-06 cutover could change, minus the monotonic revision."""

    snapshot = runtime.registry.load()
    return {
        "schema": snapshot.schema,
        "runtimeFloors": snapshot.extensions.get("runtimeFloors"),
        "intent": snapshot.extensions.get(BACKGROUND_INTENT_KEY),
        "registrations": sorted(snapshot.registrations),
        "default": snapshot.default_vault_binding_id,
        "settings_rebind": snapshot.settings_rebind,
        "principal": local_operator_principal_path(runtime.layout.registry_path).read_bytes(),
        "role_exists": background_role_path(runtime.layout.registry_path).exists(),
    }


def _assert_previous_image_refuses(runtime, previous) -> None:
    path = runtime.layout.registry_path
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="schema mismatch"):
        previous.VaultRegistryStore(path).read_existing()
    # Its recovering load cannot heal or rewrite the qualified generation either.
    with pytest.raises(RuntimeError):
        previous.VaultRegistryStore(path).load()
    assert path.read_bytes() == before


def test_background_role_and_intent_set_mvr06_floor_before_first_write(
    tmp_path: Path, previous_registry_image
) -> None:
    # -- 1. ordering: floor durable before the role, role before the intent ---------------
    runtime, _first, _extra, _operator = mvr05_instance(tmp_path / "ordered")
    untouched = _lineage(runtime)
    assert untouched["schema"] == CURRENT_REGISTRY_SCHEMA
    assert untouched["runtimeFloors"]["minimumRuntimeSchema"] == "mvr-05"
    assert untouched["intent"] is None and untouched["role_exists"] is False
    # The previous image runs against untouched MVR-05 state.
    previous_registry_image.VaultRegistryStore(runtime.layout.registry_path).read_existing()

    observed: list[tuple[str, str, object, bool]] = []
    real_write = BackgroundRuntimeRoleStore._write
    real_install = VaultRegistryStore.install_background_intent

    def _durable(store_path: Path) -> tuple[str, object]:
        on_disk = VaultRegistryStore(store_path).read_existing()
        return on_disk.schema, (on_disk.extensions.get("runtimeFloors") or {}).get(
            "minimumRuntimeSchema"
        )

    def recording_write(self, record):  # type: ignore[no-untyped-def]
        schema, floor = _durable(runtime.layout.registry_path)
        observed.append(("role", schema, floor, False))
        return real_write(self, record)

    def recording_install(self, intent, **kwargs):  # type: ignore[no-untyped-def]
        schema, floor = _durable(self.path)
        observed.append(
            ("intent", schema, floor, background_role_path(self.path).exists())
        )
        return real_install(self, intent, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BackgroundRuntimeRoleStore, "_write", recording_write)
        patch.setattr(VaultRegistryStore, "install_background_intent", recording_install)
        receipt = run_background_cutover_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert observed == [
        ("role", BACKGROUND_INTENT_REGISTRY_SCHEMA, "mvr-06", False),
        ("intent", BACKGROUND_INTENT_REGISTRY_SCHEMA, "mvr-06", True),
    ]
    complete = _lineage(runtime)
    assert complete["intent"] == BackgroundBindingIntent.staged_compatibility().as_payload()
    assert complete["role_exists"] is True
    assert complete["principal"] == untouched["principal"]
    assert complete["settings_rebind"] == untouched["settings_rebind"]

    # -- 2. every older API/watcher/worker is blocked before registry/auth access --------
    _assert_previous_image_refuses(runtime, previous_registry_image)
    for consumer in ("api", "watcher", "worker"):
        assert _preflight(runtime, consumer) == 0
    with pytest.raises(CapabilityNotReadyError, match="blocks scalar"):
        _require_runtime_floor(runtime.registry.load(), scalar_runtime=True)

    # A legacy extension writer cannot lower the floor, and later deployments' MVR-05
    # floor step is an already-recorded no-op rather than a mismatch.
    with pytest.raises(RegistryError, match="MVR-06 runtime floor cannot be changed"):
        runtime.registry.set_extension_state(
            principal_state={},
            background_state={},
            runtime_floors={"minimumRuntimeSchema": "mvr-05"},
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert validate_mvr05_runtime_floor(
        runtime.registry.load(),
        discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml"),
    )
    # The intent field is unrepresentable without its floor.
    snapshot = runtime.registry.load()
    frontmatter = runtime.registry._frontmatter_from_snapshot(snapshot)
    frontmatter["schema"] = CURRENT_REGISTRY_SCHEMA
    frontmatter["runtimeFloors"] = {
        key: value
        for key, value in frontmatter["runtimeFloors"].items()
        if key != "mvr06FloorCutover"
    } | {"minimumRuntimeSchema": "mvr-05"}
    with pytest.raises(RegistryError, match="floor must commit before the first intent"):
        runtime.registry._snapshot_from_frontmatter(frontmatter)

    # -- 3. injected faults leave untouched MVR-05/MVR-03 state ---------------------------
    faults = {
        "floor": (VaultRegistryStore, "advance_mvr06_runtime_floor"),
        "role": (BackgroundRuntimeRoleStore, "_write"),
        "intent": (VaultRegistryStore, "install_background_intent"),
    }
    for name, (owner, method) in faults.items():
        faulted, _, _, _ = mvr05_instance(tmp_path / f"fault-{name}")
        before = _lineage(faulted)

        def _fail(*_args, _name=name, **_kwargs):  # type: ignore[no-untyped-def]
            raise RegistryError(f"injected {_name} fault")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(owner, method, _fail)
            failed = run_background_cutover_through_cli(faulted)
        assert failed["_exit_code"] == 1 and f"injected {name} fault" in failed["error"]
        assert _lineage(faulted) == before, name
        # Untouched means the previous image still reads it, and the background
        # consumers run on the unchanged legacy path.
        previous_registry_image.VaultRegistryStore(
            faulted.layout.registry_path
        ).read_existing()
        assert _preflight(faulted, "worker") == 0
        # A clean retry then commits one complete lineage.
        retried = run_background_cutover_through_cli(faulted)
        assert retried["_exit_code"] == 0, retried
        assert _lineage(faulted)["intent"] is not None

    # -- 4. a kill mid-cutover leaves a fenced partial lineage that only converges -------
    for name, (owner, method) in (
        ("after-floor", (BackgroundRuntimeRoleStore, "_write")),
        ("after-role", (VaultRegistryStore, "install_background_intent")),
    ):
        killed, _, _, _ = mvr05_instance(tmp_path / f"kill-{name}")

        def _kill(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt  # no in-process compensation can run

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(owner, method, _kill)
            with pytest.raises(KeyboardInterrupt):
                run_background_cutover_through_cli(killed)
        partial = _lineage(killed)
        assert partial["schema"] == BACKGROUND_INTENT_REGISTRY_SCHEMA
        assert partial["intent"] is None
        assert partial["role_exists"] is (name == "after-role")
        # Neither an older image nor an MVR-06 background consumer can run on it.
        _assert_previous_image_refuses(killed, previous_registry_image)
        for consumer in ("watcher", "worker"):
            with pytest.raises(BackgroundAuthorityPreflightError, match="incomplete"):
                _preflight(killed, consumer)
        role_before = (
            BackgroundRuntimeRoleStore(background_role_path(killed.layout.registry_path))
            .load()
        )
        # Rerunning the cutover completes exactly one lineage, reusing any role.
        converged = run_background_cutover_through_cli(killed)
        assert converged["_exit_code"] == 0, converged
        assert converged["floor_advanced"] is False
        if role_before is not None:
            assert converged["background_runtime_role_id"] == (
                role_before.background_runtime_role_id
            )
            assert converged["role_created"] is False
        assert _preflight(killed, "worker") == 0

    # -- 5. unproven compensation keeps the window stopped instead of guessing -----------
    unproven, _, _, _ = mvr05_instance(tmp_path / "unproven")

    def _fail_intent(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RegistryError("injected intent fault")

    def _fail_compensation(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RegistryError("injected compensation fault")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(VaultRegistryStore, "install_background_intent", _fail_intent)
        patch.setattr(
            VaultRegistryStore, "compensate_mvr06_runtime_floor", _fail_compensation
        )
        refused = run_background_cutover_through_cli(unproven)
    assert refused["_exit_code"] == 1
    assert "compensation is unproven" in refused["error"]
    assert "keep the deployment stopped" in refused["provisioning_action"]

    # -- 6a. a role write that landed but raised is reconciled before the floor drops ----
    landed, _, _, _ = mvr05_instance(tmp_path / "landed-role")
    landed_before = _lineage(landed)
    original_write = BackgroundRuntimeRoleStore._write

    def _write_then_fail(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_write(self, *args, **kwargs)  # os.replace done ...
        raise OSError("injected directory fsync fault")  # ... bootstrap never returns

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BackgroundRuntimeRoleStore, "_write", _write_then_fail)
        failed = run_background_cutover_through_cli(landed)
    assert failed["_exit_code"] == 1 and "injected directory fsync fault" in failed["error"]
    # The floor came down only together with the role: no delegation without its floor.
    assert _lineage(landed) == landed_before
    previous_registry_image.VaultRegistryStore(landed.layout.registry_path).read_existing()

    # -- 6. an intent that committed before a later failure is never compensated ---------
    committed, _, _, _ = mvr05_instance(tmp_path / "committed")
    original_install = VaultRegistryStore.install_background_intent

    def _commit_then_fail(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_install(self, *args, **kwargs)
        raise RegistryError("injected post-commit fault")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(VaultRegistryStore, "install_background_intent", _commit_then_fail)
        refused = run_background_cutover_through_cli(committed)
    assert refused["_exit_code"] == 1
    assert "compensation is unproven" in refused["error"]
    kept = _lineage(committed)
    # The committed lineage keeps its floor, intent, and role; nothing was discarded.
    assert kept["schema"] == BACKGROUND_INTENT_REGISTRY_SCHEMA
    assert kept["intent"] is not None and kept["role_exists"] is True
    assert _preflight(committed, "worker") == 0
