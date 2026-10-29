"""All resource sampling/mutation happens in finite disposable child processes."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401


_RESOURCE_PARENT = r'''
import json, resource, subprocess, sys
hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
if hard != resource.RLIM_INFINITY and hard < 8192:
    print(json.dumps({"unsupported_test_capacity": True}))
    raise SystemExit(0)
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 8192))
before = resource.getrlimit(resource.RLIMIT_NOFILE)
completed = subprocess.run([sys.executable, "-c", sys.argv[1], *sys.argv[2:]],
                           capture_output=True, text=True, timeout=30)
assert resource.getrlimit(resource.RLIMIT_NOFILE) == before
print(json.dumps({"returncode": completed.returncode, "stdout": completed.stdout,
                  "stderr": completed.stderr, "parent_unchanged": True}))
'''

_RESOURCE_CHILD = r'''
import json, os, resource, sys, threading
from pathlib import Path
from app.ops import bws_control_installation as control

mode, base = sys.argv[1], Path(sys.argv[2])
initial_pid = os.getpid()
# The supported CLI runs on Linux. Other POSIX test hosts emulate only its
# kernel task-directory port; NOFILE accounting, syscalls and PID remain real.
if sys.platform != "linux":
    original_listdir = os.listdir
    os.listdir = lambda path: ([str(os.getpid())] if path == "/proc/self/task"
                               else original_listdir(path))
if mode == "adequate":
    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 8192))
elif mode == "hard-insufficient":
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 512))
before = resource.getrlimit(resource.RLIMIT_NOFILE)
sys._yggdrasil_bws_source_rpc_process = os.getpid()
if mode == "ineligible":
    del sys._yggdrasil_bws_source_rpc_process
application, backup = base / "application", base / "backup"
for directory in (application, backup, application / "app", application / "app/ops"):
    directory.mkdir(mode=0o755)
def root(path):
    info = path.stat()
    return control.Root(str(path), info.st_dev, info.st_ino, info.st_uid, info.st_gid, 0o755)
roots, backup_root = {"application": root(application)}, root(backup)
changes = (control.Change("application", "app/ops/new.py", None, None,
                          control._hash(b"NEW = True\n"), 0o644),)
payloads = {("application", "app/ops/new.py"): b"NEW = True\n"}
real_snapshot, real_setrlimit = control._source_descriptor_capacity_snapshot, resource.setrlimit
calls = []
def setter(which, limits):
    calls.append(limits)
    if mode == "setter-refused" and limits[0] > before[0]:
        raise OSError("synthetic admission failure")
    if mode == "restore-failed" and limits == before:
        raise OSError("synthetic restoration failure")
    real_setrlimit(which, limits)
resource.setrlimit = setter
if mode == "unknown":
    control._source_descriptor_capacity_snapshot = lambda: None
elif mode == "invalid":
    control._source_descriptor_capacity_snapshot = lambda: (0, True, 8192)
elif mode == "post-set-unknown":
    snapshots = iter((real_snapshot(), None))
    control._source_descriptor_capacity_snapshot = lambda: next(snapshots)
snapshot = real_snapshot()
required = snapshot[0] + control._source_descriptor_peak(roots, changes, backup_root, 19)
envelope = control._SourceDescriptorEnvelope()
if mode == "wrong-pid":
    envelope._pid = -1
release_thread = threading.Event()
worker = None
if mode == "shared-thread":
    worker = threading.Thread(target=release_thread.wait)
    worker.start()
reason, handle, runtime = None, None, None
closed = True
try:
    envelope.admit(roots, changes, backup_root, 19)
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == (max(before[0], required), before[1])
    assert len(calls) == (0 if mode == "adequate" else 1)
    if mode == "reused":
        envelope.admit(roots, changes, backup_root, 19)
    runtime = os.open(os.devnull, os.O_RDONLY)
    handle = control._prepare_full_source_files(
        roots=roots, changes=changes, payloads=payloads, backup_root=backup_root,
        bundle_name="child-only", source_inventory_fd_peak=19, runtime_fd_already_open=True,
    )
    control.apply_public_files(handle)
    assert (application / "app/ops/new.py").read_bytes() == payloads[changes[0].root, changes[0].path]
    control.compensate_public_files(handle)
    assert not (application / "app/ops/new.py").exists()
    if mode == "exception":
        raise RuntimeError("synthetic body failure")
except control.InstallationRefused as exc:
    reason = exc.reason
except RuntimeError:
    assert mode == "exception"
    reason = "body_exception"
finally:
    release_thread.set()
    if worker is not None:
        worker.join()
    if mode == "cleanup-unknown":
        closed = False
    else:
        if handle is not None:
            handle.close()
            assert not handle._fds
        if runtime is not None:
            os.close(runtime)
    envelope.close(owned_resources_closed=closed)
assert resource.getrlimit(resource.RLIMIT_NOFILE) == before
assert not list(backup.iterdir()) or reason in (None, "body_exception")
print(json.dumps({"reason": reason, "restored": True, "pid_unchanged": initial_pid == os.getpid(),
                  "hard_unchanged": resource.getrlimit(resource.RLIMIT_NOFILE)[1] == before[1]}))
'''


@pytest.mark.parametrize("mode,reason", [
    ("raise", None), ("adequate", None), ("exception", "body_exception"),
    ("unknown", "descriptor_capacity_unknown"), ("invalid", "descriptor_capacity_unknown"),
    ("post-set-unknown", "descriptor_capacity_unknown"),
    ("hard-insufficient", "descriptor_capacity_insufficient"),
    ("ineligible", "descriptor_capacity_ineligible"),
    ("wrong-pid", "descriptor_capacity_ineligible"),
    ("shared-thread", "descriptor_capacity_ineligible"),
    ("reused", "descriptor_capacity_ineligible"),
    ("setter-refused", "descriptor_capacity_admission_refused"),
    ("cleanup-unknown", "exit"), ("restore-failed", "exit"),
])
def test_source_descriptor_envelope_in_isolated_process(secure_tmp_path, mode, reason):
    completed = subprocess.run(
        [sys.executable, "-c", _RESOURCE_PARENT, _RESOURCE_CHILD, mode, str(secure_tmp_path)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=40,
    )
    assert completed.returncode == 0, completed.stderr
    outer = json.loads(completed.stdout)
    if outer.get("unsupported_test_capacity"):
        pytest.skip("the disposable child cannot establish the finite synthetic test ceiling")
    assert outer["parent_unchanged"] is True
    assert not outer["stderr"]
    if reason == "exit":
        assert outer["returncode"] == 78
        assert outer["stdout"] == ""
    else:
        assert outer["returncode"] == 0, outer
        result = json.loads(outer["stdout"])
        assert result == {"reason": reason, "restored": True,
                          "pid_unchanged": True, "hard_unchanged": True}
