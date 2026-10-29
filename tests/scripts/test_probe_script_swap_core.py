"""Finite filesystem proof for the one-file production probe swap."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
import probe_script_swap_core as core  # noqa: E402

OLD = b"old reviewed probe\n"
NEW = b"fixed reviewed probe with child\n"
OPERATION = "a" * 32


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def fixture_dir():
    with tempfile.TemporaryDirectory(prefix="4076-swap-offline-") as value:
        root = Path(value)
        root.chmod(0o775)
        leaf = root / core.LEAF
        leaf.write_bytes(OLD)
        leaf.chmod(0o664)
        (root / "preserved-config").write_bytes(b"original config")
        (root / "preserved-incident").write_bytes(b"confirmed active acknowledgment")
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield root, descriptor
        finally:
            os.close(descriptor)


def swap(descriptor: int, *, before=OLD, after=NEW, callback=lambda: None):
    return core.swap_script(
        descriptor,
        digest(before),
        after,
        digest(after),
        OPERATION,
        callback,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )


def assert_preserved(root: Path, incident=b"confirmed active acknowledgment"):
    assert (root / "preserved-config").read_bytes() == b"original config"
    assert (root / "preserved-incident").read_bytes() == incident
    assert not list(root.glob(".prod_probe.4076-*.stage"))


def test_real_swap_accepts_producer_mode_and_preserves_neighbors(fixture_dir):
    root, descriptor = fixture_dir
    result = swap(descriptor)
    assert result["replace_returned"] is True
    assert (root / core.LEAF).read_bytes() == NEW
    assert (root / core.LEAF).stat().st_mode & 0o777 == 0o664
    assert_preserved(root)


def test_code_rollback_retains_newer_acknowledgment(fixture_dir):
    root, descriptor = fixture_dir
    swap(descriptor)
    (root / "preserved-incident").write_bytes(b"new confirmed recovery")
    swap(descriptor, before=NEW, after=OLD)
    assert (root / core.LEAF).read_bytes() == OLD
    assert_preserved(root, b"new confirmed recovery")


@pytest.mark.parametrize(
    "mutate", ["symlink", "hardlink", "world_write", "wrong_mode", "foreign_owner"]
)
def test_metadata_drift_refuses_before_stage(fixture_dir, mutate):
    root, descriptor = fixture_dir
    if mutate == "symlink":
        other = root / "foreign"
        other.write_bytes(OLD)
        (root / core.LEAF).unlink()
        (root / core.LEAF).symlink_to(other)
    elif mutate == "hardlink":
        os.link(root / core.LEAF, root / "retained-link")
    elif mutate == "world_write":
        root.chmod(0o777)
    elif mutate == "wrong_mode":
        (root / core.LEAF).chmod(0o666)
    with pytest.raises(core.SwapFailure) as error:
        if mutate == "foreign_owner":
            core.swap_script(
                descriptor,
                digest(OLD),
                NEW,
                digest(NEW),
                OPERATION,
                lambda: None,
                expected_uid=os.geteuid() + 1,
                expected_gid=os.getegid(),
            )
        else:
            swap(descriptor)
    assert error.value.replace_attempted is False
    if mutate == "symlink":
        assert (root / core.LEAF).is_symlink()
    else:
        assert (root / core.LEAF).read_bytes() == OLD
    assert_preserved(root)


def test_bad_digest_and_stage_collision_preserve_foreign_artifacts(fixture_dir):
    root, descriptor = fixture_dir
    stage = root / f".prod_probe.4076-{OPERATION}.stage" / "prod_probe.py.new"
    stage.parent.mkdir(mode=0o700)
    stage.write_bytes(b"foreign existing artifact")
    with pytest.raises(core.SwapFailure):
        core.swap_script(
            descriptor,
            digest(OLD),
            NEW,
            digest(OLD),
            OPERATION,
            lambda: None,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )
    assert stage.read_bytes() == b"foreign existing artifact"
    assert (root / core.LEAF).read_bytes() == OLD
    assert (root / "preserved-config").read_bytes() == b"original config"
    assert (root / "preserved-incident").read_bytes() == b"confirmed active acknowledgment"


def test_partial_write_failure_keeps_old_code(fixture_dir):
    root, descriptor = fixture_dir
    real_write = core.os.write
    calls = 0

    def fail_after_partial(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:3])
        raise OSError("finite injected write failure")

    with patch.object(core.os, "write", side_effect=fail_after_partial):
        with pytest.raises(core.SwapFailure) as error:
            swap(descriptor)
    assert error.value.replace_attempted is False
    assert (root / core.LEAF).read_bytes() == OLD
    assert_preserved(root)


def test_lost_quiescence_and_foreign_slot_are_not_overwritten(fixture_dir):
    root, descriptor = fixture_dir

    def no_longer_quiescent():
        raise ValueError("unit or directory chain changed")

    with pytest.raises(core.SwapFailure) as error:
        swap(descriptor, callback=no_longer_quiescent)
    assert error.value.replace_attempted is False
    assert (root / core.LEAF).read_bytes() == OLD

    foreign = root / "foreign"
    foreign.write_bytes(b"foreign replacement")

    def replace_slot():
        os.replace(foreign, root / core.LEAF)

    with pytest.raises(core.SwapFailure) as error:
        swap(descriptor, callback=replace_slot)
    assert error.value.replace_attempted is False
    assert (root / core.LEAF).read_bytes() == b"foreign replacement"


def test_replace_failure_is_attempted_and_response_loss_is_unknown(fixture_dir):
    root, descriptor = fixture_dir
    with patch.object(core.os, "replace", side_effect=OSError("finite failure")):
        with pytest.raises(core.SwapFailure) as error:
            swap(descriptor)
    assert error.value.replace_attempted is True
    assert error.value.replace_returned is False
    assert (root / core.LEAF).read_bytes() == OLD
    assert_preserved(root)

    real_replace = core.os.replace

    def commit_then_error(*args, **kwargs):
        real_replace(*args, **kwargs)
        raise OSError("response lost after rename")

    with patch.object(core.os, "replace", side_effect=commit_then_error):
        with pytest.raises(core.SwapFailure) as error:
            swap(descriptor)
    assert error.value.replace_attempted is True
    assert error.value.replace_returned is False
    assert (root / core.LEAF).read_bytes() == NEW
    swap(descriptor, before=NEW, after=OLD)
    assert (root / core.LEAF).read_bytes() == OLD


def test_derived_cache_and_foreign_stage_are_not_removed(fixture_dir):
    root, descriptor = fixture_dir
    cache = root / "__pycache__"
    cache.mkdir()
    artifact = cache / "prod_probe.qualified-cache.pyc"
    artifact.write_bytes(b"pre-existing cache")
    swap(descriptor)
    artifact.write_bytes(b"new normal derived cache")
    swap(descriptor, before=NEW, after=OLD)
    assert artifact.read_bytes() == b"new normal derived cache"

    stage = root / f".prod_probe.4076-{OPERATION}.stage" / "prod_probe.py.new"
    foreign = root / "foreign-stage"
    foreign.write_bytes(b"another owner's artifact")

    def replace_stage_and_fail():
        os.replace(foreign, stage)
        raise ValueError("ownership changed")

    with pytest.raises(core.SwapFailure):
        swap(descriptor, callback=replace_stage_and_fail)
    assert stage.read_bytes() == b"another owner's artifact"
    assert (root / core.LEAF).read_bytes() == OLD


def test_foreign_named_stage_is_rejected_before_replace(fixture_dir):
    root, descriptor = fixture_dir
    stage = root / f".prod_probe.4076-{OPERATION}.stage" / "prod_probe.py.new"
    foreign = root / "foreign-stage-returned"

    def replace_stage_and_return():
        foreign.write_bytes(b"foreign unreviewed source")
        foreign.chmod(0o664)
        os.replace(foreign, stage)

    with pytest.raises(core.SwapFailure) as error:
        swap(descriptor, callback=replace_stage_and_return)
    assert error.value.replace_attempted is False
    assert (root / core.LEAF).read_bytes() == OLD
    assert stage.read_bytes() == b"foreign unreviewed source"


def test_group_mode_is_accepted_but_inherited_acl_write_domain_is_not(fixture_dir, monkeypatch):
    root, descriptor = fixture_dir
    monkeypatch.setattr(core.os, "listxattr", lambda _: ["system.posix_acl_default"], raising=False)
    with pytest.raises(core.SwapFailure) as error:
        swap(descriptor)
    assert error.value.replace_attempted is False
    assert (root / core.LEAF).read_bytes() == OLD
    assert_preserved(root)
