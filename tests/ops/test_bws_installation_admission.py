from __future__ import annotations

import json
import os
import stat
import uuid

import pytest

from app.ops import bws_installation_admission as admission
from app.ops import bws_installation_transaction as transaction


def _digest(char: str) -> str:
    return char * 64


def _patch_directories(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[object, object]:
    runtime = tmp_path / "runtime"
    receipts = tmp_path / "receipts"
    runtime.mkdir(mode=0o700)
    receipts.mkdir(mode=0o700)
    monkeypatch.setattr(admission, "_RUNTIME_DIRECTORY", runtime)
    monkeypatch.setattr(admission, "_RECEIPT_DIRECTORY", receipts)
    monkeypatch.setattr(admission, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(admission, "_OWNER_GID", os.getegid())
    caller = {
        "pid": os.getpid(), "uid": os.geteuid(), "gid": os.getegid(), "start_time": 42,
        "argv_sha256": _digest("1"), "executable_sha256": _digest("2"),
        "launcher_sha256": _digest("3"),
    }
    monkeypatch.setattr(admission, "_fixed_caller_identity", lambda _channel: dict(caller))
    monkeypatch.setattr(admission, "_proc_identity", lambda pid: {
        "pid": pid, "start_time": caller["start_time"], "argv_sha256": caller["argv_sha256"],
        "executable_sha256": caller["executable_sha256"],
    })

    def open_directory(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        return descriptor, os.fstat(descriptor)

    monkeypatch.setattr(admission, "_open_directory", open_directory)
    return runtime, receipts


def _request() -> dict[str, str]:
    return {
        "channel": "dev",
        "mode": "exclusive",
        "operation_id": str(uuid.uuid4()),
        "candidate_sha": "a" * 40,
        "image_digest": "sha256:" + _digest("b"),
        "bundle_name": "bws-source-install-test",
    }


def _receipt(request: dict[str, str], *, status: str = "installed") -> dict[str, object]:
    return {
        "schema": admission._RECEIPT_SCHEMA,
        "operation_id": request["operation_id"],
        "channel": request["channel"],
        "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"],
        "old_generation_sha256": None if status == "refused_before_backup" else _digest("c"),
        "new_generation_sha256": None if status == "refused_before_backup" else _digest("d"),
        "backup_manifest_sha256": None if status == "refused_before_backup" else _digest("e"),
        "status": status,
    }


def test_interrupted_owner_marker_refuses_shared_and_new_exclusive(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            pass

    marker = runtime / "dev.source-installation.lock"
    assert json.loads(marker.read_text())["operation_id"] == request["operation_id"]
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission("dev", mode="shared"):
            pytest.fail("an interrupted owner marker must refuse")
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**_request()):
            pytest.fail("an interrupted owner marker must not be adopted")


def test_terminal_receipt_precedes_shared_admission_and_next_fresh_owner(monkeypatch, tmp_path):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    receipt = _receipt(request)
    with admission.installation_admission(**request) as lease:
        assert lease.complete(receipt) == receipt

    marker = json.loads((runtime / "dev.source-installation.lock").read_text())
    saved_receipt = receipts / f"bws-source-installation-{request['operation_id']}.receipt.json"
    assert marker["operation_id"] == request["operation_id"]
    assert json.loads(saved_receipt.read_text()) == receipt

    with admission.installation_admission("dev", mode="shared"):
        pass

    next_request = _request()
    assert next_request["operation_id"] != request["operation_id"]
    with admission.installation_admission(**next_request) as next_lease:
        assert next_lease.complete(_receipt(next_request))["operation_id"] == next_request["operation_id"]


def test_terminal_checkout_binding_does_not_block_admission_after_checkout_removal(
    monkeypatch, tmp_path,
):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    checkout = tmp_path / "candidate"
    checkout.mkdir(mode=0o700)
    checkout_info = checkout.stat()
    checkout_verifier = admission._verify_checkout_caller
    caller = {
        "pid": os.getpid(), "uid": os.geteuid(), "gid": os.getegid(), "start_time": 42,
        "argv_sha256": _digest("1"), "executable_sha256": _digest("2"),
        "launcher_sha256": _digest("3"), "candidate_sha": request["candidate_sha"],
        "source_checkout": {
            "path": str(checkout), "device": checkout_info.st_dev, "inode": checkout_info.st_ino,
            "mode": stat.S_IMODE(checkout_info.st_mode), "revision": request["candidate_sha"],
            "script_sha256": _digest("4"),
        },
    }
    monkeypatch.setattr(admission, "_fixed_caller_identity", lambda _channel: dict(caller))
    monkeypatch.setattr(admission, "_verify_checkout_caller", lambda _caller: None)
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request))

    checkout.rmdir()
    monkeypatch.setattr(admission, "_verify_checkout_caller", checkout_verifier)
    with pytest.raises(admission.InstallationAdmissionRefused):
        admission._verify_live_caller(caller)

    assert admission.cleanup_must_skip("dev") is False
    with admission.installation_admission("dev", mode="shared"):
        pass
    fixed_caller = {
        key: value for key, value in caller.items() if key not in {"candidate_sha", "source_checkout"}
    }
    monkeypatch.setattr(admission, "_fixed_caller_identity", lambda _channel: fixed_caller)
    next_request = _request()
    with admission.installation_admission(**next_request) as next_lease:
        next_lease.complete(_receipt(next_request))
    assert json.loads((runtime / "dev.source-installation.lock").read_text())["operation_id"] == next_request[
        "operation_id"
    ]


def test_start_confirmation_waits_for_exact_one_use_grant_to_be_consumed(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    sleeps: list[float] = []

    def simulated_launcher_consume(delay: float) -> None:
        sleeps.append(delay)
        (runtime / admission._start_authorization_name("dev")).unlink()

    monkeypatch.setattr(admission.time, "sleep", simulated_launcher_consume)
    with admission.installation_admission(**request) as lease:
        generation = _digest("c")
        lease.authorize_service_start("candidate", generation)
        lease.confirm_service_start_consumed("candidate", generation)
        assert not (runtime / admission._start_authorization_name("dev")).exists()
        assert lease._start_authorization is None
        assert lease.complete(_receipt(request))["operation_id"] == request["operation_id"]

    assert sleeps == [admission._START_CONSUMPTION_POLL_SECONDS]


def test_start_confirmation_accepts_exact_grant_unlinked_after_open(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    name = admission._start_authorization_name("dev")
    permit_path = runtime / name
    unlinked = False
    original_fstat = os.fstat

    with admission.installation_admission(**request) as lease:
        generation = _digest("d")
        lease.authorize_service_start("candidate", generation)

        def unlink_before_fstat(descriptor: int) -> os.stat_result:
            nonlocal unlinked
            if not unlinked:
                try:
                    opened_bytes = os.pread(descriptor, 4097, 0)
                except OSError:
                    opened_bytes = b""
                if opened_bytes == lease._start_authorization:
                    permit_path.unlink()
                    unlinked = True
            return original_fstat(descriptor)

        monkeypatch.setattr(admission.os, "fstat", unlink_before_fstat)
        lease.confirm_service_start_consumed("candidate", generation)
        assert unlinked
        assert lease._start_authorization is None
        assert lease.complete(_receipt(request))["operation_id"] == request["operation_id"]


def test_historical_operation_id_cannot_be_replayed_after_a_later_owner(monkeypatch, tmp_path):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    first = _request()
    second = _request()
    with admission.installation_admission(**first) as lease:
        lease.complete(_receipt(first))
    with admission.installation_admission(**second) as lease:
        lease.complete(_receipt(second))

    first_receipt = receipts / f"bws-source-installation-{first['operation_id']}.receipt.json"
    saved_first_receipt = first_receipt.read_bytes()
    replay = {**first, "bundle_name": "replayed-with-new-bundle"}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**replay):
            pytest.fail("an old operation ID must be refused before replacing the owner marker")

    marker = json.loads((runtime / "dev.source-installation.lock").read_text())
    assert marker["operation_id"] == second["operation_id"]
    assert first_receipt.read_bytes() == saved_first_receipt


@pytest.mark.parametrize("tamper", ["receipt_missing", "receipt_status", "owner_channel"])
def test_completed_marker_requires_exact_matching_terminal_receipt(monkeypatch, tmp_path, tamper):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request))
    receipt_path = receipts / f"bws-source-installation-{request['operation_id']}.receipt.json"
    owner_path = runtime / "dev.source-installation.lock"
    if tamper == "receipt_missing":
        receipt_path.unlink()
    elif tamper == "receipt_status":
        document = json.loads(receipt_path.read_text())
        document["status"] = "compensated_stopped"
        receipt_path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    else:
        document = json.loads(owner_path.read_text())
        document["channel"] = "test"
        owner_path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
        os.chmod(owner_path, stat.S_IMODE(owner_path.stat().st_mode))

    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission("dev", mode="shared"):
            pytest.fail("receipt mismatch must refuse")


def test_receipt_is_operation_bound_and_rejects_unknown_fields(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    receipt = _receipt(request)
    receipt["source"] = "/private/source"
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as lease:
            lease.complete(receipt)


def test_exec_stop_post_skips_all_writes_while_shared_caller_is_active(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    with admission.installation_admission("dev", mode="shared"):
        assert admission.cleanup_must_skip("dev") is True
    assert admission.cleanup_must_skip("dev") is False
    assert not list(runtime.glob("*.receipt.json"))


def test_exec_stop_post_fails_closed_without_creating_a_missing_global_lock(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)

    assert admission.cleanup_must_skip("dev") is True
    assert list(runtime.iterdir()) == []


def test_shared_admission_creates_missing_private_runtime_directory(monkeypatch, tmp_path):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    runtime.rmdir()
    receipts.rmdir()

    with admission.installation_admission("dev", mode="shared"):
        assert runtime.is_dir()
        assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
        assert (runtime / admission._GLOBAL_LOCK).is_file()
        assert (runtime / "dev.source-installation.lock").is_file()


def test_exec_stop_post_skips_without_creating_missing_runtime_directory(monkeypatch, tmp_path):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    runtime.rmdir()
    receipts.rmdir()

    assert admission.cleanup_must_skip("dev") is True
    assert not runtime.exists()


def test_global_reservation_fences_cross_channel_callers_and_cleanup(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    with admission.installation_admission("dev", mode="shared"):
        assert admission.cleanup_must_skip("test") is True
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission(**{
                **_request(), "channel": "test",
            }):
                pytest.fail("a DEV ordinary caller must exclude TEST installation")

    request = _request()
    with admission.installation_admission(**request) as lease:
        assert admission.cleanup_must_skip("test") is True
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission("test", mode="shared"):
                pytest.fail("a DEV installation owner must exclude TEST callers")
        # The test-side cleanup must also fail closed while the DEV owner holds
        # the one global lock.
        assert admission.cleanup_must_skip("test") is True
        lease.complete(_receipt(request))


def test_pending_owner_in_either_channel_fences_both_after_flock_release(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            pass

    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission("test", mode="shared"):
            pytest.fail("a pending DEV owner must fence TEST after process exit")
    assert admission.cleanup_must_skip("test") is True


def test_exec_stop_post_skips_all_writes_for_pending_install_owner(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            assert admission.cleanup_must_skip("dev") is True
    assert admission.cleanup_must_skip("dev") is True
    assert json.loads((runtime / "dev.source-installation.lock").read_text())["operation_id"] == request["operation_id"]


def test_exec_stop_post_restores_normal_cleanup_only_after_installed_receipt(monkeypatch, tmp_path):
    _runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request))
        assert admission.cleanup_must_skip("dev") is True
    assert admission.cleanup_must_skip("dev") is False


def test_fully_restored_old_generation_releases_supported_callers(monkeypatch, tmp_path):
    runtime, _receipts = _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request, status="compensated_restored"))

    assert admission.cleanup_must_skip("dev") is False
    with admission.installation_admission("dev", mode="shared"):
        pass

    marker = json.loads((runtime / "dev.source-installation.lock").read_text())
    assert marker["operation_id"] == request["operation_id"]


@pytest.mark.parametrize("status", ["refused_before_backup", "refused_before_stop"])
def test_no_effect_refusal_receipt_releases_owner_for_a_fresh_operation(monkeypatch, tmp_path, status):
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request, status=status))

    next_request = _request()
    with admission.installation_admission(**next_request) as lease:
        assert lease.operation_id == next_request["operation_id"]
        lease.complete(_receipt(next_request))


def test_refused_before_backup_receipt_is_backward_compatible_and_validates_gate(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    assert admission._PREBACKUP_REFUSAL_GATES == transaction._PREBACKUP_REFUSAL_GATES
    request = _request()
    legacy = _receipt(request, status="refused_before_backup")
    diagnostic = {**legacy, "prebackup_gate": "descriptor_capacity"}

    with admission.installation_admission(**request) as lease:
        assert lease._validate_receipt(legacy) == legacy
        assert lease._validate_receipt(diagnostic) == diagnostic
        for gate in sorted(admission._PREBACKUP_REFUSAL_GATES):
            specific = {**legacy, "prebackup_gate": gate}
            assert lease._validate_receipt(specific) == specific
            invalid_status = {**_receipt(request), "prebackup_gate": gate}
            with pytest.raises(admission.InstallationAdmissionRefused):
                lease._validate_receipt(invalid_status)

        unknown_gate = {**diagnostic, "prebackup_gate": "private_exception_text"}
        with pytest.raises(admission.InstallationAdmissionRefused):
            lease._validate_receipt(unknown_gate)

        incompatible_status = {**_receipt(request), "prebackup_gate": "descriptor_capacity"}
        with pytest.raises(admission.InstallationAdmissionRefused):
            lease._validate_receipt(incompatible_status)

        lease.complete(diagnostic)

    with admission.installation_admission("dev", mode="shared"):
        pass


def test_stopped_compensation_keeps_caller_and_cleanup_fences(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        lease.complete(_receipt(request, status="compensated_stopped"))

    assert admission.cleanup_must_skip("dev") is True
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission("dev", mode="shared"):
            pytest.fail("a stopped compensation outcome must retain the fence")


def test_internal_callback_requires_same_live_exclusive_operation(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    with admission.installation_admission(**request) as lease:
        owner = admission.require_active_installation_owner(
            request["channel"], request["operation_id"], request["candidate_sha"],
            request["image_digest"],
            peer_credentials=(os.getpid(), os.geteuid(), os.getegid()),
        )
        assert owner["bundle_name"] == request["bundle_name"]
        with pytest.raises(admission.InstallationAdmissionRefused):
            admission.require_active_installation_owner(
                request["channel"], request["operation_id"], request["candidate_sha"],
                request["image_digest"], peer_credentials=(os.getpid() + 1, os.geteuid(), os.getegid()),
            )
        with pytest.raises(admission.InstallationAdmissionRefused):
            admission.require_active_installation_owner(
                request["channel"], str(uuid.uuid4()), request["candidate_sha"],
                request["image_digest"],
                peer_credentials=(os.getpid(), os.geteuid(), os.getegid()),
            )
        lease.complete(_receipt(request))


def test_fixed_caller_identity_rejects_other_launcher_actions(monkeypatch):
    monkeypatch.setattr(admission, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(admission, "_OWNER_GID", os.getegid())
    monkeypatch.setattr(admission.sys, "argv", ["/tmp/unrelated", "rpc", "dev"])

    with pytest.raises(admission.InstallationAdmissionRefused):
        admission._fixed_caller_identity("dev")


def test_root_control_leaf_receipts_preserve_closed_allowlist_parity(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    assert admission._ROOT_CONTROL_REFINEMENTS == transaction._ROOT_CONTROL_REFINEMENTS
    assert admission._PREBACKUP_REFUSAL_GATES == transaction._PREBACKUP_REFUSAL_GATES
    request = _request()
    legacy = _receipt(request, status='refused_before_backup')
    with admission.installation_admission(**request) as lease:
        for gate in sorted(admission._ROOT_CONTROL_REFINEMENT_GATES):
            receipt = {**legacy, 'prebackup_gate': gate}
            assert lease._validate_receipt(receipt) == receipt
        for gate in ('old_kernel_qualification', 'old_kernel_initial_root_control', None):
            receipt = legacy if gate is None else {**legacy, 'prebackup_gate': gate}
            assert lease._validate_receipt(receipt) == receipt
        valid = next(iter(admission._ROOT_CONTROL_REFINEMENT_GATES))
        for bad in (valid + 'PRIVATE_CANARY', valid.replace('__old__', '__foreign__'), [], {}, 7):
            if bad == valid:
                continue
            with pytest.raises(admission.InstallationAdmissionRefused):
                lease._validate_receipt({**legacy, 'prebackup_gate': bad})
        for status in ('installed', 'compensated_restored', 'compensated_stopped', 'unknown', 'refused_before_stop'):
            with pytest.raises(admission.InstallationAdmissionRefused):
                lease._validate_receipt({**_receipt(request, status=status), 'prebackup_gate': valid})
        lease.complete(legacy)


def test_initial_unit_property_receipts_match_finite_contract(monkeypatch, tmp_path):
    from app.ops import bws_installation_lifecycle as lifecycle
    from tests.ops.test_bws_installation_lifecycle import _UNIT_INITIAL_TRACE, _UNIT_VALUE_SITES
    expected = {(site, kind) for site in _UNIT_INITIAL_TRACE
                for kind in ('backend', 'decode', 'signature', 'shape')}
    expected |= {(site, 'value') for site in _UNIT_VALUE_SITES}
    assert admission._UNIT_PROPERTY_REFINEMENTS == transaction._UNIT_PROPERTY_REFINEMENTS == expected
    assert lifecycle._UNIT_PROPERTY_REFINEMENTS == expected
    assert admission._PREBACKUP_REFUSAL_GATES == transaction._PREBACKUP_REFUSAL_GATES
    _patch_directories(monkeypatch, tmp_path)
    request = _request()
    legacy = _receipt(request, status='refused_before_backup')
    with admission.installation_admission(**request) as lease:
        for site, kind in sorted(expected):
            gate = 'old_kernel_initial_unit_properties__' + site + '__' + kind
            receipt = {**legacy, 'prebackup_gate': gate}
            assert lease._validate_receipt(receipt) == receipt
            generated = transaction._receipt(request, status='refused_before_backup', old_generation=None,
                new_generation=None, backup_manifest=None, prebackup_gate=gate)
            assert generated['prebackup_gate'] == gate
        for gate in (None, 'old_kernel_qualification', 'old_kernel_initial_unit_properties',
                     'old_kernel_empty_control_unit_properties', 'old_kernel_initial_root_control',
                     'old_kernel_initial_root_control__captured_empty__old__hints__launcher_hint'):
            receipt = legacy if gate is None else {**legacy, 'prebackup_gate': gate}
            assert lease._validate_receipt(receipt) == receipt
        valid = 'old_kernel_initial_unit_properties__Service_Type__value'
        for bad in (valid + 'PRIVATE_CANARY', valid.replace('initial', 'empty_control'),
                    valid.replace('Service_Type', 'Unit_ActiveState'),
                    valid.replace('value', 'PRIVATE_CANARY'), [], {}, 7):
            with pytest.raises(admission.InstallationAdmissionRefused):
                lease._validate_receipt({**legacy, 'prebackup_gate': bad})
        for status in ('installed', 'compensated_restored', 'compensated_stopped', 'unknown', 'refused_before_stop'):
            with pytest.raises(admission.InstallationAdmissionRefused):
                lease._validate_receipt({**_receipt(request, status=status), 'prebackup_gate': valid})
        lease.complete(legacy)
