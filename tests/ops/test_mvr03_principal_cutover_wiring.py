"""Production wiring for the explicit MVR-03 principal cutover (#4524)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import yaml

from app.instance import principal_fence
from app.instance.local_operator_principal import (
    LocalOperatorPrincipalStore,
    PrincipalFloorNotRecordedError,
    PrincipalPreflightError,
    PROVENANCE_EXISTING_CREDENTIAL,
    SUBJECT_LOOPBACK,
)
from app.instance.principal_fence import (
    NATIVE_AUTH_PRODUCERS,
    PrincipalFenceError,
    compensate_principal_floor,
    discover_auth_producers,
    principal_floor_recorded,
)
from app.instance.runtime import main as instance_runtime_main
from app.instance.runtime import local_operator_storage_capability
from app.instance.runtime import open_local_operator_principal_store
from app.instance.vault_registry import RegistryError, VaultRegistryStore
from app.release_channels.channel_isolation_preflight import resolve_effective_dsn
from tests._mvr_default_vault_harness import REPO_ROOT, active_runtime, deployment_authority


def _cli(*args: str) -> dict[str, object]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(args))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def test_cutover_oneshot_resolves_the_request_path_posture(tmp_path: Path) -> None:
    """The one-shot and API consume one generated credential/proxy posture."""

    runtime_env = tmp_path / "runtime.env"
    declared_key = "test-product-gov-key"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/export_runtime_env.sh")],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "API_KEY": declared_key,
            "COMPANION_UI_PROXY_HOSTS": "companion-ui",
            "LLM_PROVIDER": "mock",
            "NO_VAULT_MODE": "1",
            "RUNTIME_ENV_PATH": str(runtime_env),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    oneshot = services["instance-state-init"]
    api = services["api"]
    assert oneshot["env_file"] == api["env_file"][:2]
    assert "HOST_SECRET_RUNTIME_ENV_FILE_API" not in json.dumps(oneshot["env_file"])
    assert (
        oneshot["environment"]["COMPANION_UI_PROXY_HOSTS"]
        == api["environment"]["COMPANION_UI_PROXY_HOSTS"]
    )

    lookup = {
        "WATCHER_RUNTIME_ENV_FILE": str(runtime_env),
        "COMPANION_UI_PROXY_HOSTS": "companion-ui",
    }
    for key in ("API_KEY", "COMPANION_UI_PROXY_HOSTS"):
        assert resolve_effective_dsn(
            REPO_ROOT / "docker-compose.yaml",
            "instance-state-init",
            key,
            environ=lookup,
            load_dotenv=False,
        ) == resolve_effective_dsn(
            REPO_ROOT / "docker-compose.yaml",
            "api",
            key,
            environ=lookup,
            load_dotenv=False,
        )

    mounts = json.dumps(oneshot["volumes"])
    for relative in NATIVE_AUTH_PRODUCERS:
        if relative.startswith("scripts/"):
            assert f"/run/principal-fence-native-producers/{relative}" in mounts
    for channel in ("dev", "test", "prod"):
        channel_config = (REPO_ROOT / "config/deploy" / f"{channel}.env").read_text(
            encoding="utf-8"
        )
        assert "MVR03_PRINCIPAL_LOOPBACK_LISTENER=0" in channel_config
    for native_launcher in ("scripts/deploy_channel.sh", "scripts/start_full_system.sh"):
        launcher = (REPO_ROOT / native_launcher).read_text(encoding="utf-8")
        assert 'export MVR03_PRINCIPAL_LOOPBACK_LISTENER="${' in launcher
    start_full_system = (REPO_ROOT / "scripts/start_full_system.sh").read_text(
        encoding="utf-8"
    )
    assert 'PKM_CHANNEL:-dev' in start_full_system


def test_missing_native_producer_path_fails_closed(tmp_path: Path) -> None:
    """A wrong mounted root cannot understate the native producer inventory."""

    root = tmp_path / "native-root"
    for relative in NATIVE_AUTH_PRODUCERS:
        if not relative.startswith("scripts/") or relative.endswith("start_full_system.sh"):
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)

    with pytest.raises(PrincipalFenceError, match="start_full_system.sh"):
        discover_auth_producers(
            compose_path=REPO_ROOT / "docker-compose.yaml",
            repo_root=root,
        )


def _wrapper_run(
    tmp_path: Path,
    *,
    cutover: bool,
    loopback: str = "0",
    fail_cutover: int = 0,
    verify_cutover: int = 1,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    tmp_path.mkdir(parents=True)
    event_log = tmp_path / "events.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = -c ]; then exec "$REAL_PYTHON" "$@"; fi\n'
        'printf \'python:%s\\n\' "$*" >> "$EVENT_LOG"\n'
        'case " $* " in\n'
        "  *' produce-legacy-owners '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{"writers_drained":false}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done; exit 2 ;;\n"
        "  *' controller-token '*) printf 'linux:%064d\\n' 0; exit 0 ;;\n"
        "  *' prove-quiescent '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done; exit 2 ;;\n"
        "  *' validate-legacy-owners '*)\n"
        '    while [ "$#" -gt 0 ]; do\n'
        '      if [ "$1" = --output ]; then printf \'{"writers_drained":true}\\n\' > "$2"; exit 0; fi\n'
        "      shift\n"
        "    done; exit 2 ;;\n"
        "esac\n"
        "exit 2\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    harness = tmp_path / "run-wrapper.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"source '{REPO_ROOT / 'scripts/lib/instance_state_deployment.sh'}'\n"
        "fake_compose() {\n"
        "  printf 'compose:%s\\n' \"$*\" >> \"$EVENT_LOG\"\n"
        "  case \" $* \" in\n"
        "    *' principal-verify-cutover-clean-failure '*) return \"${VERIFY_CUTOVER:-1}\" ;;\n"
        "    *' principal-cutover '*) return \"${FAIL_CUTOVER:-0}\" ;;\n"
        "  esac\n"
        "  return 0\n"
        "}\n"
        "prepare_instance_state_deployment fake_compose prod\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)
    ownership_root = tmp_path / "instance-ownership"
    ownership_root.mkdir()
    env = {
        **os.environ,
        "EVENT_LOG": str(event_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(ownership_root),
        "FAIL_CUTOVER": str(fail_cutover),
        "VERIFY_CUTOVER": str(verify_cutover),
        "REAL_PYTHON": sys.executable,
    }
    env.pop("MVR03_PRINCIPAL_CUTOVER", None)
    env.pop("MVR03_PRINCIPAL_LOOPBACK_LISTENER", None)
    if cutover:
        env["MVR03_PRINCIPAL_CUTOVER"] = "1"
        env["MVR03_PRINCIPAL_LOOPBACK_LISTENER"] = loopback
    result = subprocess.run(
        ["bash", str(harness)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, event_log.read_text(encoding="utf-8").splitlines()


def test_wrapper_runs_the_cutover_inside_the_stopped_window(tmp_path: Path) -> None:
    """Opt-in, ordering, arguments, and every shell failure edge are pinned."""

    disabled, disabled_events = _wrapper_run(tmp_path / "disabled", cutover=False)
    assert disabled.returncode == 0, disabled.stderr
    assert not any("principal-cutover" in event for event in disabled_events)

    success, events = _wrapper_run(tmp_path / "success", cutover=True)
    assert success.returncode == 0, success.stderr
    prove = next(i for i, event in enumerate(events) if "deployment-prove" in event)
    cutover = next(i for i, event in enumerate(events) if "principal-cutover" in event)
    finish = next(i for i, event in enumerate(events) if "deployment-finish" in event)
    assert prove < cutover < finish
    assert "--native-producer-root /run/principal-fence-native-producers" in events[cutover]
    assert "--floor-advanced" not in events[cutover]
    assert "--floor-registry-revision" not in events[cutover]
    assert "--loopback-listener" not in events[cutover]

    loopback, loopback_events = _wrapper_run(tmp_path / "loopback", cutover=True, loopback="1")
    assert loopback.returncode == 0, loopback.stderr
    assert all(
        "--loopback-listener" in event
        for event in loopback_events
        if "principal-cutover" in event
    )

    cutover_failure, failure_events = _wrapper_run(
        tmp_path / "cutover-failure", cutover=True, fail_cutover=1, verify_cutover=0
    )
    assert cutover_failure.returncode == 1
    assert not any("deployment-finish" in event for event in failure_events)
    assert any("deployment-release" in event for event in failure_events)

    compose_failure, compose_failure_events = _wrapper_run(
        tmp_path / "compose-failure", cutover=True, fail_cutover=1
    )
    assert compose_failure.returncode == 1
    assert not any("deployment-finish" in event for event in compose_failure_events)
    assert not any("deployment-release" in event for event in compose_failure_events)

    ambiguous, ambiguous_events = _wrapper_run(
        tmp_path / "ambiguous", cutover=True, fail_cutover=75
    )
    assert ambiguous.returncode == 75
    assert not any("deployment-finish" in event for event in ambiguous_events)
    assert not any("deployment-release" in event for event in ambiguous_events)

    # A killed cutover child can die after the floor commit but before the role
    # commit, bypassing in-process compensation. Its Compose/signal status is not
    # a clean-failure receipt, so the wrapper must preserve the stopped fence.
    crashed, crashed_events = _wrapper_run(
        tmp_path / "crashed-after-floor", cutover=True, fail_cutover=137
    )
    assert crashed.returncode == 137
    assert not any("deployment-finish" in event for event in crashed_events)
    assert not any("deployment-release" in event for event in crashed_events)

    unclassified, unclassified_events = _wrapper_run(
        tmp_path / "unclassified", cutover=True, fail_cutover=43
    )
    assert unclassified.returncode == 43
    assert not any("deployment-finish" in event for event in unclassified_events)
    assert not any("deployment-release" in event for event in unclassified_events)


def test_failed_bootstrap_compensates_floor_before_window_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real runtime producer removes its floor if role persistence never starts."""

    runtime, _, _ = active_runtime(tmp_path)
    proof, inventory = deployment_authority(runtime, runtime.layout.root / "missing-legacy.md")
    proof_path = runtime.ledger.root / "deployment-quiescence-proof.json"

    def _fail_before_write(self: LocalOperatorPrincipalStore, **kwargs: object) -> None:
        raise PrincipalPreflightError(
            "injected bootstrap failure",
            provisioning_action="retry after repairing the bootstrap producer",
        )

    monkeypatch.setattr(LocalOperatorPrincipalStore, "bootstrap", _fail_before_write)
    failed = _cli(*_cutover_args(runtime, inventory=inventory, proof_path=proof_path))
    assert failed["_exit_code"] == 1
    assert not principal_floor_recorded(runtime.registry)
    extensions = runtime.registry.load().extensions
    assert "fence" not in (extensions.get("principalState") or {})
    assert proof.nonce


def test_stale_floor_sample_cannot_commit_after_compensation(tmp_path: Path) -> None:
    """The floor guard samples inside the lock shared with compensation."""

    runtime, _, _ = active_runtime(tmp_path)
    floor, _, _ = _record_floor_in_proved_window(runtime)
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    stale_sample = principal_floor_recorded(runtime.registry)
    started = threading.Event()
    errors: list[BaseException] = []

    def _bootstrap_after_stale_sample() -> None:
        started.set()
        try:
            store.bootstrap(
                credential=None,
                subjects=(SUBJECT_LOOPBACK,),
                migration_provenance=PROVENANCE_EXISTING_CREDENTIAL,
                floor_guard=lambda: principal_floor_recorded(runtime.registry),
                _capability=local_operator_storage_capability(),
            )
        except BaseException as error:
            errors.append(error)

    # Hold the exact lock bootstrap must acquire. The waiting producer has seen
    # the old floor, but compensation wins before its callable guard executes.
    with store.cutover_lock():
        producer = threading.Thread(target=_bootstrap_after_stale_sample)
        producer.start()
        assert started.wait(timeout=1)
        compensate_principal_floor(
            runtime.registry,
            channel_id="prod",
            expected_registry_revision=int(floor["registry_revision"]),
            _capability=local_operator_storage_capability(),
        )
    producer.join(timeout=2)

    assert not producer.is_alive()
    assert stale_sample is True
    assert len(errors) == 1
    assert isinstance(errors[0], PrincipalFloorNotRecordedError)
    assert store.load() is None
    assert not principal_floor_recorded(runtime.registry)


def _record_floor_receipt(
    runtime: object, *, inventory: Path, proof_path: Path
) -> dict[str, object]:
    return _cli(
        "principal-record-floor",
        "--channel",
        "prod",
        "--registry-path",
        str(runtime.layout.registry_path),  # type: ignore[attr-defined]
        "--host-global-root",
        str(runtime.ledger.root),  # type: ignore[attr-defined]
        "--inventory-path",
        str(inventory),
        "--quiescence-proof-path",
        str(proof_path),
        "--compose-base",
        str(REPO_ROOT / "docker-compose.yaml"),
        "--native-producer-root",
        str(REPO_ROOT),
        "--loopback-listener",
        "--consumer",
        "bootstrap-init",
    )


def _record_floor_in_proved_window(
    runtime: object,
) -> tuple[dict[str, object], Path, Path]:
    proof, inventory = deployment_authority(
        runtime, runtime.layout.root / "missing-legacy.md"  # type: ignore[attr-defined]
    )
    proof_path = runtime.ledger.root / "deployment-quiescence-proof.json"  # type: ignore[attr-defined]
    floor = _record_floor_receipt(
        runtime, inventory=inventory, proof_path=proof_path
    )
    assert floor["_exit_code"] == 0, floor
    assert proof.nonce
    return floor, proof_path, inventory


def _cutover_args(runtime: object, *, inventory: Path, proof_path: Path) -> list[str]:
    attempt_id = "a" * 32
    return [
        "principal-cutover",
        "--channel",
        "prod",
        "--registry-path",
        str(runtime.layout.registry_path),  # type: ignore[attr-defined]
        "--host-global-root",
        str(runtime.ledger.root),  # type: ignore[attr-defined]
        "--inventory-path",
        str(inventory),
        "--quiescence-proof-path",
        str(proof_path),
        "--attempt-id",
        attempt_id,
        "--clean-failure-receipt-path",
        str(runtime.ledger.root / f"principal-cutover-clean-failure-{attempt_id}.json"),  # type: ignore[attr-defined]
        "--compose-base",
        str(REPO_ROOT / "docker-compose.yaml"),
        "--native-producer-root",
        str(REPO_ROOT),
        "--loopback-listener",
        "--existing-install",
        "--consumer",
        "bootstrap-init",
    ]


def _verify_cutover_receipt_args(
    runtime: object, *, proof_path: Path, attempt_id: str = "a" * 32
) -> list[str]:
    return [
        "principal-verify-cutover-clean-failure",
        "--channel",
        "prod",
        "--registry-path",
        str(runtime.layout.registry_path),  # type: ignore[attr-defined]
        "--host-global-root",
        str(runtime.ledger.root),  # type: ignore[attr-defined]
        "--quiescence-proof-path",
        str(proof_path),
        "--attempt-id",
        attempt_id,
        "--clean-failure-receipt-path",
        str(runtime.ledger.root / f"principal-cutover-clean-failure-{attempt_id}.json"),  # type: ignore[attr-defined]
    ]


def test_clean_failure_receipt_is_authenticated_current_and_one_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the runtime's current attempt-bound compensation receipt authorizes release."""

    def _fail_before_write(self: LocalOperatorPrincipalStore, **kwargs: object) -> None:
        raise PrincipalPreflightError("injected clean failure", provisioning_action="retry")

    runtime, _, _ = active_runtime(tmp_path / "valid")
    _, inventory = deployment_authority(
        runtime, runtime.layout.root / "missing-legacy.md"
    )
    proof = runtime.ledger.root / "deployment-quiescence-proof.json"
    monkeypatch.setattr(LocalOperatorPrincipalStore, "bootstrap", _fail_before_write)
    failed = _cli(*_cutover_args(runtime, inventory=inventory, proof_path=proof))
    assert failed["_exit_code"] == 1
    verified = _cli(*_verify_cutover_receipt_args(runtime, proof_path=proof))
    assert verified["_exit_code"] == 0
    replay = _cli(*_verify_cutover_receipt_args(runtime, proof_path=proof))
    assert replay["_exit_code"] == 1

    forged_runtime, _, _ = active_runtime(tmp_path / "forged")
    _, forged_inventory = deployment_authority(
        forged_runtime, forged_runtime.layout.root / "missing-legacy.md"
    )
    forged_proof = forged_runtime.ledger.root / "deployment-quiescence-proof.json"
    forged = _cli(
        *_cutover_args(
            forged_runtime, inventory=forged_inventory, proof_path=forged_proof
        )
    )
    assert forged["_exit_code"] == 1
    forged_path = (
        forged_runtime.ledger.root / "principal-cutover-clean-failure-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"
    )
    document = json.loads(forged_path.read_text(encoding="utf-8"))
    document["payload"]["attempt_id"] = "b" * 32
    forged_path.write_text(json.dumps(document), encoding="utf-8")
    forged_path.chmod(0o600)
    rejected = _cli(*_verify_cutover_receipt_args(forged_runtime, proof_path=forged_proof))
    assert rejected["_exit_code"] == 1

    stale_runtime, _, _ = active_runtime(tmp_path / "stale")
    _, stale_inventory = deployment_authority(
        stale_runtime, stale_runtime.layout.root / "missing-legacy.md"
    )
    stale_proof = stale_runtime.ledger.root / "deployment-quiescence-proof.json"
    stale = _cli(
        *_cutover_args(stale_runtime, inventory=stale_inventory, proof_path=stale_proof)
    )
    assert stale["_exit_code"] == 1
    stale_snapshot = stale_runtime.registry.load()
    stale_runtime.registry.commit_state(
        registrations=dict(stale_snapshot.registrations),
        removal_tombstones=dict(stale_snapshot.removal_tombstones),
        transfer_lineage=stale_snapshot.transfer_lineage,
        extensions=dict(stale_snapshot.extensions),
        expected_revision=stale_snapshot.revision,
        _capability=local_operator_storage_capability(),
    )
    stale_rejected = _cli(
        *_verify_cutover_receipt_args(stale_runtime, proof_path=stale_proof)
    )
    assert stale_rejected["_exit_code"] == 1

    nonce_runtime, _, _ = active_runtime(tmp_path / "nonce")
    _, nonce_inventory = deployment_authority(
        nonce_runtime, nonce_runtime.layout.root / "missing-legacy.md"
    )
    nonce_proof = nonce_runtime.ledger.root / "deployment-quiescence-proof.json"
    nonce_failed = _cli(
        *_cutover_args(
            nonce_runtime, inventory=nonce_inventory, proof_path=nonce_proof
        )
    )
    assert nonce_failed["_exit_code"] == 1
    changed_proof = json.loads(nonce_proof.read_text(encoding="utf-8"))
    changed_proof["nonce"] = "different-attempt"
    nonce_proof.write_text(json.dumps(changed_proof), encoding="utf-8")
    nonce_proof.chmod(0o600)
    nonce_rejected = _cli(
        *_verify_cutover_receipt_args(nonce_runtime, proof_path=nonce_proof)
    )
    assert nonce_rejected["_exit_code"] == 1


def test_compensation_is_lease_bound_and_preserves_a_preexisting_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only this attempt's advanced floor is compensatable under its live lease."""

    def _fail_before_write(self: LocalOperatorPrincipalStore, **kwargs: object) -> None:
        raise PrincipalPreflightError(
            "injected bootstrap failure", provisioning_action="retry"
        )

    # Changing the proof after this process records the floor makes the outcome
    # ambiguous: compensation is refused and the stopped fence remains.
    lease_runtime, _, _ = active_runtime(tmp_path / "lease")
    _, lease_inventory = deployment_authority(
        lease_runtime, lease_runtime.layout.root / "missing-legacy.md"
    )
    lease_proof = lease_runtime.ledger.root / "deployment-quiescence-proof.json"
    def _fail_after_losing_lease(
        self: LocalOperatorPrincipalStore, **kwargs: object
    ) -> None:
        lease_proof.write_text(
            json.dumps({"channel_id": "prod", "nonce": "not-this-lease"}),
            encoding="utf-8",
        )
        lease_proof.chmod(0o600)
        raise PrincipalPreflightError(
            "injected bootstrap failure after lease loss", provisioning_action="retry"
        )

    monkeypatch.setattr(LocalOperatorPrincipalStore, "bootstrap", _fail_after_losing_lease)
    refused = _cli(
        *_cutover_args(
            lease_runtime, inventory=lease_inventory, proof_path=lease_proof
        )
    )
    assert refused["_exit_code"] == 75
    assert principal_floor_recorded(lease_runtime.registry)
    monkeypatch.setattr(LocalOperatorPrincipalStore, "bootstrap", _fail_before_write)

    # The public command has no attempt-advance flag to forge. An existing floor
    # is recognized in-process as advanced=false and cannot be compensated.
    existing_runtime, _, _ = active_runtime(tmp_path / "existing")
    first_floor, existing_proof, existing_inventory = _record_floor_in_proved_window(
        existing_runtime
    )
    assert first_floor["floor_advanced"] is True
    with pytest.raises(SystemExit):
        instance_runtime_main(
            _cutover_args(
                existing_runtime,
                inventory=existing_inventory,
                proof_path=existing_proof,
            )
            + ["--floor-advanced"]
        )
    existing = _cli(
        *_cutover_args(
            existing_runtime,
            inventory=existing_inventory,
            proof_path=existing_proof,
        )
    )
    assert existing["_exit_code"] == 75
    assert principal_floor_recorded(existing_runtime.registry)


def test_registry_read_ambiguity_after_floor_preserves_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable post-floor revision keeps the lease/fence stopped (status 75)."""

    runtime, _, _ = active_runtime(tmp_path)
    _, inventory = deployment_authority(
        runtime, runtime.layout.root / "missing-legacy.md"
    )
    proof = runtime.ledger.root / "deployment-quiescence-proof.json"
    original_record = principal_fence.record_principal_floor
    original_load = VaultRegistryStore.load
    armed = False

    def _record_then_arm(*args: object, **kwargs: object) -> object:
        nonlocal armed
        receipt = original_record(*args, **kwargs)
        armed = True
        return receipt

    def _ambiguous_once(self: VaultRegistryStore) -> object:
        nonlocal armed
        if armed:
            armed = False
            raise RegistryError("injected unreadable post-floor revision")
        return original_load(self)

    monkeypatch.setattr(principal_fence, "record_principal_floor", _record_then_arm)
    monkeypatch.setattr(VaultRegistryStore, "load", _ambiguous_once)
    result = _cli(*_cutover_args(runtime, inventory=inventory, proof_path=proof))
    assert result["_exit_code"] == 75, result
    assert principal_floor_recorded(runtime.registry)
    assert "fence" in (runtime.registry.load().extensions.get("principalState") or {})


def test_committed_role_is_ambiguous_and_never_compensated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-rename failure preserves role/floor/fence and is never false success."""

    runtime, _, _ = active_runtime(tmp_path)
    _, inventory = deployment_authority(
        runtime, runtime.layout.root / "missing-legacy.md"
    )
    proof = runtime.ledger.root / "deployment-quiescence-proof.json"
    original_bootstrap = LocalOperatorPrincipalStore.bootstrap

    def _commit_then_fail(
        self: LocalOperatorPrincipalStore, **kwargs: object
    ) -> None:
        original_bootstrap(self, **kwargs)
        raise OSError("injected post-commit durability failure")

    monkeypatch.setattr(LocalOperatorPrincipalStore, "bootstrap", _commit_then_fail)
    result = _cli(*_cutover_args(runtime, inventory=inventory, proof_path=proof))
    assert result["_exit_code"] == 75, result
    assert principal_floor_recorded(runtime.registry)
    assert open_local_operator_principal_store(runtime.layout.registry_path).require()
    assert not list(runtime.ledger.root.glob("principal-cutover-clean-failure-*.json"))


def test_governed_compose_cutover_receipt_is_whitelist_redacted(tmp_path: Path) -> None:
    """No raw Compose/path/env bytes escape the guarded release-channel producer."""

    captured = tmp_path / "compose.out"
    captured.write_text(
        "raw=/Users/private/vault API_KEY=must-not-escape\n"
        '{"floor_advanced":true,"floor_recorded":true,"registry_revision":9,'
        '"raw_path":"/Volumes/private"}\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"source '{REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'}'; "
            f"_deploy_channel_redact_principal_cutover_receipt '{captured}'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "floor_advanced": True,
        "floor_recorded": True,
    }
    assert "/Users" not in result.stdout
    assert "/Volumes" not in result.stdout
    assert "must-not-escape" not in result.stdout
