from __future__ import annotations

import importlib.util
import ctypes
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest


def _root_harness():
    path = Path(__file__).resolve().parents[2] / "conftest.py"
    spec = importlib.util.spec_from_file_location("pytest_temp_root_subject", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    assert process.wait(timeout=10) == 0
    return process.pid


def _candidate(parent: Path, suffix: str, *, pid: int, age_days: int = 8) -> Path:
    root = parent / ("pkm-py-" + suffix)
    root.mkdir(mode=0o700)
    (root / "artifact.txt").write_text("synthetic test artifact")
    info = root.stat()
    old_ns = time.time_ns() - age_days * 24 * 60 * 60 * 1_000_000_000
    marker = root / ".agentic-pkm-pytest-owner.json"
    marker.write_text(json.dumps({"version": 1, "pid": pid, "created_ns": old_ns,
                                  "device": info.st_dev, "inode": info.st_ino}))
    marker.chmod(0o600)
    finished = root / ".agentic-pkm-pytest-finished.json"
    finished.write_text(json.dumps({"version": 1, "pid": pid, "finished_ns": old_ns,
                                    "device": info.st_dev, "inode": info.st_ino}))
    finished.chmod(0o600)
    os.utime(marker, ns=(old_ns, old_ns))
    os.utime(finished, ns=(old_ns, old_ns))
    os.utime(root, ns=(old_ns, old_ns))
    return root


def _harness(directory: Path) -> dict[str, str]:
    """Exercise the repository's actual root hook in a bounded pytest suite."""
    root = Path(__file__).resolve().parents[2]
    (directory / "conftest.py").write_bytes((root / "conftest.py").read_bytes())
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # CI's plugin-specific flags do not belong to this standalone child suite.
    # subprocess timeouts below independently bound each child's lifetime.
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = str(directory)
    return env


def test_untrusted_mount_skips_inherited_cleanup_and_refuses_default(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    parent = tmp_path / "inherited"
    parent.mkdir(mode=0o700)
    expired = _candidate(parent, "expired", pid=_dead_pid())
    conftest = suite / "conftest.py"
    with conftest.open("a") as target:
        target.write("\ndef _temp_mount_identity(fd):\n    raise OSError('synthetic noowners')\n")
    (suite / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    command = [sys.executable, "-m", "pytest", "-q"]
    run = subprocess.run(command, cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert expired.exists()
    assert any(path.name.startswith("pkm-py-") and path != expired for path in parent.iterdir())
    env.pop("PYTEST_DEBUG_TEMPROOT")
    env["TMPDIR"] = str(tmp_path)
    run = subprocess.run(command, cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode != 0
    assert "pytest temporary-root isolation failed" in run.stderr
    assert expired.exists()


def test_untrusted_marked_ancestor_is_not_modified_by_nested_pytest(tmp_path: Path) -> None:
    parent = _candidate(tmp_path, "untrusted-ancestor", pid=_dead_pid())
    marker = parent / ".agentic-pkm-pytest-owner.json"
    before = marker.stat().st_mtime_ns, marker.read_bytes()
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    with (suite / "conftest.py").open("a") as target:
        target.write("\ndef _temp_mount_identity(fd):\n    raise OSError('synthetic noowners')\n")
    (suite / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=suite, env=env,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (marker.stat().st_mtime_ns, marker.read_bytes()) == before
    assert not list(parent.glob(".agentic-pkm-pytest-child-*"))
    assert any(path.name.startswith("pkm-py-") for path in parent.iterdir())


def test_untrusted_parent_still_fences_qualified_marked_ancestor(tmp_path: Path) -> None:
    outer = _candidate(tmp_path, "qualified-ancestor", pid=_dead_pid())
    inner = outer / "inherited"
    inner.mkdir(mode=0o700)
    marker = outer / ".agentic-pkm-pytest-owner.json"
    before = marker.stat().st_mtime_ns
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env["PYTEST_DEBUG_TEMPROOT"] = str(inner)
    with (suite / "conftest.py").open("a") as target:
        target.write("\n_real_mount = _temp_mount_identity\n"
                     "def _temp_mount_identity(fd):\n"
                     f"    if os.fstat(fd).st_ino == {inner.stat().st_ino}:\n"
                     "        raise OSError('synthetic noowners')\n"
                     "    return _real_mount(fd)\n")
    ready, release = tmp_path / "ready", tmp_path / "release"
    env.update(READY=str(ready), RELEASE=str(release))
    (suite / "test_probe.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "def test_probe(tmp_path):\n"
        "    Path(os.environ['READY']).touch()\n"
        "    limit = time.monotonic() + 20\n"
        "    while not Path(os.environ['RELEASE']).exists():\n"
        "        assert time.monotonic() < limit\n"
        "        time.sleep(.01)\n"
    )
    process = subprocess.Popen([sys.executable, "-m", "pytest", "-q"], cwd=suite, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), "nested pytest did not reach the test"
        descriptor = os.open(marker, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
        os.utime(outer, ns=(old_ns, old_ns))
        _root_harness()._prune_expired_temp_roots(tmp_path)
        assert outer.exists()
    finally:
        release.touch()
        try:
            output, _ = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
    assert process.returncode == 0, output
    assert marker.stat().st_mtime_ns > before
    assert not list(outer.glob(".agentic-pkm-pytest-child-*"))
    assert any(path.name.startswith("pkm-py-") for path in inner.iterdir())


def test_cleanup_preserves_candidate_when_mount_identity_changes(tmp_path: Path, monkeypatch) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "expired", pid=_dead_pid())
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "artifact").write_text("preserve")
    real_lock, real_same = subject._lock_temp_parent, subject._same_temp_mount
    changed = False
    def lock_then_change(*args, **kwargs):
        nonlocal changed
        result = real_lock(*args, **kwargs)
        changed = True  # A changed mount is observed immediately before rename.
        return result
    monkeypatch.setattr(subject, "_lock_temp_parent", lock_then_change)
    monkeypatch.setattr(subject, "_same_temp_mount",
                        lambda *args: False if changed else real_same(*args))
    subject._prune_expired_temp_roots(tmp_path)
    assert changed and (expired / "artifact.txt").exists()
    assert (foreign / "artifact").read_text() == "preserve"
    quarantines = list(tmp_path.glob(".pytest-prune-*"))
    assert len(quarantines) == 1 and not list(quarantines[0].iterdir())


def test_replaced_empty_quarantine_is_not_removed_or_used(tmp_path: Path, monkeypatch) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "replace-quarantine", pid=_dead_pid())
    real_lock = subject._lock_temp_parent
    replacement = None
    def replace_after_lock(*args, **kwargs):
        nonlocal replacement
        result = real_lock(*args, **kwargs)
        replacement = next(tmp_path.glob(".pytest-prune-*"))
        replacement.rename(tmp_path / "detached-quarantine")
        replacement.mkdir(mode=0o700)
        return result
    monkeypatch.setattr(subject, "_lock_temp_parent", replace_after_lock)
    subject._prune_expired_temp_roots(tmp_path)
    assert replacement is not None and replacement.is_dir() and not list(replacement.iterdir())
    assert (tmp_path / "detached-quarantine").is_dir()
    assert (expired / "artifact.txt").exists()


def test_cleanup_preserves_same_device_nested_mount(tmp_path: Path, monkeypatch) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "mount", pid=_dead_pid())
    nested = expired / "nested"
    nested.mkdir()
    (nested / "foreign").write_text("preserve")
    os.utime(expired, ns=(1, 1))
    same_device = nested.stat().st_dev
    real_mount = subject._temp_mount_identity
    def mount_with_bind(fd):
        identity = real_mount(fd)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (same_device, nested.stat().st_ino):
            return (*identity, "different-mount-id")
        return identity
    monkeypatch.setattr(subject, "_temp_mount_identity", mount_with_bind)
    subject._prune_expired_temp_roots(tmp_path)
    assert (nested / "foreign").read_text() == "preserve"
    assert (expired / "artifact.txt").exists()
    assert not list(tmp_path.glob(".pytest-prune-*"))


def test_cleanup_preserves_special_entries_without_opening_them(tmp_path: Path) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "fifo", pid=_dead_pid())
    fifo = expired / "fifo"
    os.mkfifo(fifo)
    os.utime(expired, ns=(1, 1))
    subject._prune_expired_temp_roots(tmp_path)
    assert fifo.exists() and (expired / "artifact.txt").exists()


@pytest.mark.parametrize("limit", ["_TEMP_SCAN_SECONDS = 0", "_TEMP_SCAN_MAX_ENTRIES = 1"])
def test_cleanup_scan_budget_preserves_root_and_pytest_continues(tmp_path: Path, limit: str) -> None:
    parent, suite = tmp_path / "parent", tmp_path / "suite"
    parent.mkdir(mode=0o700)
    suite.mkdir()
    expired = _candidate(parent, "budget", pid=_dead_pid())
    env = _harness(suite)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    with (suite / "conftest.py").open("a") as target:
        target.write("\n" + limit + "\n")
    (suite / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=suite, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (expired / "artifact.txt").exists()
    assert not list(parent.glob(".pytest-prune-*"))


def test_candidate_tree_scan_stops_at_entry_budget(tmp_path: Path, monkeypatch) -> None:
    subject = _root_harness()
    (tmp_path / "first").touch()
    (tmp_path / "second").touch()
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        mount = subject._temp_mount_identity(fd)
        monkeypatch.setattr(subject, "_TEMP_SCAN_MAX_ENTRIES", 1)
        assert not subject._temp_tree_on_mount(fd, mount, time.monotonic() + 5)
    finally:
        os.close(fd)
    assert (tmp_path / "first").exists() and (tmp_path / "second").exists()


def test_mount_ownership_probe_and_real_noowners_volume(tmp_path: Path, monkeypatch) -> None:
    subject = _root_harness()
    class FakeStatFS:
        argtypes = None
        restype = None
        def __init__(self, flags, fstype=b"apfs"):
            self.flags, self.fstype = flags, fstype
        def __call__(self, _fd, pointer):
            result = ctypes.cast(pointer, ctypes.POINTER(subject._DarwinStatFS)).contents
            result.fstype = self.fstype
            result.flags = self.flags
            result.mountpoint = b"/synthetic"
            return 0
    monkeypatch.setattr(subject, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(subject.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(fstatfs=FakeStatFS(0)))
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert subject._temp_mount_identity(fd)[0] == "darwin"
        monkeypatch.setattr(subject.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(fstatfs=FakeStatFS(0x200000)))
        with pytest.raises(OSError, match="not qualified"):
            subject._temp_mount_identity(fd)
        monkeypatch.setattr(subject.ctypes, "CDLL", lambda *args, **kwargs:
                            SimpleNamespace(fstatfs=FakeStatFS(0, b"unverified")))
        with pytest.raises(OSError, match="not qualified"):
            subject._temp_mount_identity(fd)
    finally:
        os.close(fd)
    monkeypatch.undo()
    probe = os.environ.get("PYTEST_NOOWNERS_PROBE")
    if probe:
        assert sys.platform == "darwin"
        fd = os.open(probe, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with pytest.raises(OSError, match="not qualified"):
                subject._temp_mount_identity(fd)
        finally:
            os.close(fd)


def test_parallel_pytest_runs_use_unique_debug_temp_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--timeout=120 --timeout-method=thread")
    env = _harness(tmp_path)
    parent = tmp_path / "shared-parent"
    parent.mkdir(mode=0o700)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    (tmp_path / "test_probe.py").write_text(
        "import json, os, time\n"
        "from pathlib import Path\n"
        "def test_probe(tmp_path, tmp_path_factory):\n"
        "    report = Path(os.environ['REPORT'])\n"
        "    report.write_text(json.dumps({'root': os.environ.get('PYTEST_DEBUG_TEMPROOT'), "
        "'base': str(tmp_path_factory.getbasetemp()), 'fixture': str(tmp_path)}))\n"
        "    deadline = time.monotonic() + 20\n"
        "    while not Path(os.environ['PEER']).exists():\n"
        "        assert time.monotonic() < deadline, 'peer did not reach tmp_path'\n"
        "        time.sleep(0.01)\n"
    )
    reports = [tmp_path / "first.json", tmp_path / "second.json"]
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
            cwd=tmp_path,
            env={**env, "REPORT": str(report), "PEER": str(reports[1 - index])},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for index, report in enumerate(reports)
    ]
    try:
        for process in processes:
            output, _ = process.communicate(timeout=30)
            assert process.returncode == 0, output
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    results = [json.loads(report.read_text()) for report in reports]
    roots = [Path(result["root"]) for result in results]
    assert roots[0] != roots[1]
    for root, result in zip(roots, results):
        assert root.parent == parent
        assert root.is_dir()
        assert Path(result["base"]).is_relative_to(root)
        assert Path(result["fixture"]).is_relative_to(root)


@pytest.mark.parametrize("failure", ["creation", "validation"])
def test_temp_root_setup_fails_loud_when_namespace_cannot_be_created(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--timeout=120 --timeout-method=thread")
    env = _harness(tmp_path)
    env.pop("PYTEST_DEBUG_TEMPROOT", None)
    # Inject a filesystem failure through a plugin before root-hook configuration.
    (tmp_path / "broken_namespace.py").write_text(
        "import tempfile\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_configure(config):\n"
        "    def refuse(*args, **kwargs):\n"
        "        raise OSError('injected namespace failure')\n"
        + (
            "    tempfile.mkdtemp = refuse\n"
            if failure == "creation"
            else "    Path.write_bytes = refuse\n"
        )
    )
    (tmp_path / "test_probe.py").write_text(
        "from pathlib import Path\n"
        "Path('collected').touch()\n"
        "def test_probe(tmp_path):\n"
        "    Path('executed').touch()\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "broken_namespace", "-q", "-m", "not pg"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "pytest temporary-root isolation failed" in result.stdout + result.stderr
    assert "injected namespace failure" in result.stdout + result.stderr
    assert not (tmp_path / "collected").exists()
    assert not (tmp_path / "executed").exists()


def test_prunes_expired_inactive_roots_and_preserves_recent_and_active(tmp_path: Path) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "expired", pid=_dead_pid())
    recent = _candidate(tmp_path, "recent", pid=_dead_pid(), age_days=6)
    active = _candidate(tmp_path, "active", pid=os.getpid())
    subject._prune_expired_temp_roots(tmp_path)
    assert not expired.exists()
    assert (recent / "artifact.txt").read_text() == "synthetic test artifact"
    assert (active / "artifact.txt").read_text() == "synthetic test artifact"


def test_cleanup_fails_closed_for_unverifiable_or_active_roots(tmp_path: Path) -> None:
    subject = _root_harness()
    missing = tmp_path / "pkm-py-missing"
    missing.mkdir(mode=0o700)
    invalid = _candidate(tmp_path, "invalid", pid=_dead_pid())
    (invalid / subject._TEMP_OWNER).write_text("not json")
    duplicate = _candidate(tmp_path, "duplicate", pid=_dead_pid())
    marker = duplicate / subject._TEMP_OWNER
    marker.write_text(marker.read_text().replace('"version": 1', '"version": 1, "version": 1'))
    with pytest.raises(ValueError, match="duplicate"):
        subject._open_temp_owner(duplicate)
    overflow = _candidate(tmp_path, "overflow", pid=2**128)
    with pytest.raises(ValueError, match="unqualified"):
        subject._open_temp_owner(overflow)
    locked = _candidate(tmp_path, "locked", pid=_dead_pid())
    marker = locked / subject._TEMP_OWNER
    child = subprocess.Popen(
        [sys.executable, "-c", "import fcntl,sys; f=open(sys.argv[1]); "
         "fcntl.flock(f,fcntl.LOCK_SH); print('ready',flush=True); sys.stdin.read()", str(marker)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline() == "ready\n"
        subject._prune_expired_temp_roots(tmp_path)
        assert missing.exists() and invalid.exists() and duplicate.exists() and overflow.exists() and locked.exists()
    finally:
        if child.stdin is not None:
            child.stdin.close()
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()


def test_cleanup_is_confined_to_owned_direct_child_namespaces(tmp_path: Path) -> None:
    subject = _root_harness()
    outside = tmp_path / "outside"
    outside.mkdir()
    foreign = _candidate(outside, "foreign", pid=_dead_pid())
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    (parent / "pkm-py-symlink").symlink_to(foreign, target_is_directory=True)
    generic = parent / "pytest-generic"
    generic.mkdir()
    (generic / "artifact").write_text("retain")
    subject._prune_expired_temp_roots(parent)
    assert (foreign / "artifact.txt").read_text() == "synthetic test artifact"
    assert (generic / "artifact").read_text() == "retain"
    assert (parent / "pkm-py-symlink").is_symlink()


def test_cleanup_does_not_follow_links_inside_expired_root(tmp_path: Path) -> None:
    subject = _root_harness()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "protected").write_text("retain")
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    expired = _candidate(parent, "expired", pid=_dead_pid())
    (expired / "external-link").symlink_to(outside, target_is_directory=True)
    old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
    os.utime(expired, ns=(old_ns, old_ns))
    subject._prune_expired_temp_roots(parent)
    assert not expired.exists()
    assert (outside / "protected").read_text() == "retain"


def test_unverifiable_owner_process_is_retained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject = _root_harness()
    expired = _candidate(tmp_path, "unverifiable", pid=_dead_pid())

    def deny(_pid: int, _signal: int) -> None:
        raise PermissionError("process identity unavailable")

    monkeypatch.setattr(subject.os, "kill", deny)
    subject._prune_expired_temp_roots(tmp_path)
    assert (expired / "artifact.txt").read_text() == "synthetic test artifact"


def test_actual_pytest_hook_prunes_only_its_synthetic_parent(tmp_path: Path) -> None:
    env = _harness(tmp_path)
    parent = tmp_path / "controlled-parent"
    parent.mkdir(mode=0o700)
    expired = _candidate(parent, "expired", pid=_dead_pid())
    unknown = parent / "pkm-py-unknown"
    unknown.mkdir(mode=0o700)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    (tmp_path / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not expired.exists()
    assert unknown.exists()
    roots = [path for path in parent.iterdir() if path.name.startswith("pkm-py-")]
    assert len(roots) == 2
    created = next(path for path in roots if path != unknown)
    marker = created / ".agentic-pkm-pytest-owner.json"
    assert marker.is_file() and (marker.stat().st_mode & 0o777) == 0o600
    terminal = created / ".agentic-pkm-pytest-finished.json"
    assert terminal.is_file() and json.loads(terminal.read_text())["finished_ns"] >= json.loads(
        marker.read_text(),
    )["created_ns"]


def test_nested_pytest_retains_enclosing_namespace_lock(tmp_path: Path) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "outer", pid=_dead_pid())
    held = subject._temp_parent_locks(parent)
    try:
        subject._prune_expired_temp_roots(tmp_path)
        assert parent.exists()
    finally:
        for descriptor, root_fd, child_name in held:
            os.unlink(child_name, dir_fd=root_fd)
            os.close(root_fd)
            os.close(descriptor)
        old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
        os.utime(parent, ns=(old_ns, old_ns))
    subject._prune_expired_temp_roots(tmp_path)
    assert not parent.exists()


def test_nested_lifetime_lock_survives_concurrent_marker_timestamp_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "outer", pid=_dead_pid())
    marker = parent / subject._TEMP_OWNER
    marker_identity = (marker.stat().st_dev, marker.stat().st_ino)
    entered = threading.Event()
    updated = threading.Event()
    original_fstat = os.fstat

    def observed_fstat(descriptor):
        info = original_fstat(descriptor)
        if (info.st_dev, info.st_ino) == marker_identity and not entered.is_set():
            entered.set()
            assert updated.wait(5)
        return info

    def update_marker():
        if entered.wait(5):
            os.utime(marker, None)
            updated.set()

    thread = threading.Thread(target=update_marker)
    thread.start()
    held = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(subject.os, "fstat", observed_fstat)
            held = subject._temp_parent_locks(parent)
        parent_info = parent.stat()
        assert updated.is_set() and any(
            (os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino) == (parent_info.st_dev, parent_info.st_ino)
            for _, root_fd, _ in held
        )
        assert any(path.name.startswith(subject._TEMP_CHILD_PREFIX) for path in parent.iterdir())
        subject._prune_expired_temp_roots(tmp_path, now_ns=time.time_ns() + 8 * 24 * 60 * 60 * 1_000_000_000)
        assert parent.exists()  # The actual shared marker lock fences pruning.
    finally:
        for descriptor, root_fd, child_name in held:
            os.unlink(child_name, dir_fd=root_fd)
            os.close(root_fd)
            os.close(descriptor)
        thread.join(5)
        assert not thread.is_alive()


def test_existing_unqualified_ancestor_marker_is_not_legacy(tmp_path: Path) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "outer", pid=_dead_pid())
    marker = parent / subject._TEMP_OWNER
    marker.unlink()
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    marker.symlink_to(outside)
    with pytest.raises(OSError):
        subject._temp_parent_locks(parent)
    assert marker.is_symlink() and outside.read_text() == "preserve"


def test_nested_lifetime_refuses_marker_replacement_after_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "outer", pid=_dead_pid())
    marker = parent / subject._TEMP_OWNER
    original = parent / "original-marker"
    marker_info = marker.stat()
    flock = subject.fcntl.flock
    swapped = False

    def swap_after_lock(descriptor, operation):
        nonlocal swapped
        result = flock(descriptor, operation)
        info = os.fstat(descriptor)
        if (not swapped and (info.st_dev, info.st_ino) == (marker_info.st_dev, marker_info.st_ino)
                and operation == subject.fcntl.LOCK_SH | subject.fcntl.LOCK_NB):
            swapped = True
            marker.rename(original)
            marker.write_text("replacement")
            marker.chmod(0o600)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(subject.fcntl, "flock", swap_after_lock)
        with pytest.raises(OSError, match="namespace changed"):
            subject._temp_parent_locks(parent)
    assert swapped and original.is_file() and marker.read_text() == "replacement"


def test_abrupt_or_recent_completion_preserves_old_namespace(tmp_path: Path) -> None:
    subject = _root_harness()
    abrupt = _candidate(tmp_path, "abrupt", pid=_dead_pid())
    (abrupt / subject._TEMP_FINISHED).unlink()
    old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
    os.utime(abrupt, ns=(old_ns, old_ns))
    recent = _candidate(tmp_path, "recent-finish", pid=_dead_pid())
    info = recent.stat()
    (recent / subject._TEMP_FINISHED).write_text(json.dumps({
        "version": 1, "pid": json.loads((recent / subject._TEMP_OWNER).read_text())["pid"],
        "device": info.st_dev, "inode": info.st_ino, "finished_ns": time.time_ns(),
    }))
    subject._prune_expired_temp_roots(tmp_path)
    assert abrupt.exists() and recent.exists()


def test_abrupt_nested_run_preserves_finished_parent(tmp_path: Path) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "parent", pid=_dead_pid())
    held = subject._temp_parent_locks(parent)
    for descriptor, root_fd, _child_name in held:
        # Model death: OS closes descriptors, but no terminal cleanup runs.
        os.close(root_fd)
        os.close(descriptor)
    old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
    os.utime(parent, ns=(old_ns, old_ns))
    subject._prune_expired_temp_roots(tmp_path)
    assert parent.exists()


def test_nested_pytest_refreshes_parent_retention_after_real_completion(tmp_path: Path) -> None:
    subject = _root_harness()
    parent = _candidate(tmp_path, "outer", pid=_dead_pid())
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    (suite / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
                            cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(path.name.startswith(subject._TEMP_CHILD_PREFIX) for path in parent.iterdir())
    subject._prune_expired_temp_roots(tmp_path)
    assert parent.exists()  # its newly completed child has a full retention window
    subject._prune_expired_temp_roots(tmp_path, now_ns=time.time_ns() + 8 * 24 * 60 * 60 * 1_000_000_000)
    assert not parent.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux AF_UNIX regression")
def test_default_namespace_allows_unix_socket(tmp_path: Path) -> None:
    # Match the long fixture and socket name that exposed Linux's sun_path limit.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(tmp_path / "listener.sock"))


def test_legacy_namespace_is_preserved_and_nested_lifetime_is_held(tmp_path: Path) -> None:
    subject = _root_harness()
    current = _candidate(tmp_path, "legacy", pid=_dead_pid())
    legacy = tmp_path / "agentic-pkm-pytest-legacy"
    current.rename(legacy)
    held = subject._temp_parent_locks(legacy)
    assert any(os.fstat(root_fd).st_ino == legacy.stat().st_ino for _, root_fd, _ in held)
    try:
        subject._prune_expired_temp_roots(tmp_path)
        assert legacy.exists()
    finally:
        for descriptor, root_fd, child_name in held:
            os.unlink(child_name, dir_fd=root_fd)
            os.close(root_fd)
            os.close(descriptor)
    subject._prune_expired_temp_roots(tmp_path)
    assert legacy.exists()


def test_default_parent_is_private_and_unqualified_parent_is_not_pruned(tmp_path: Path) -> None:
    subject = _root_harness()
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir(mode=0o700)
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env.pop("PYTEST_DEBUG_TEMPROOT", None)
    env["TMPDIR"] = str(system_temp)
    report = tmp_path / "root.txt"
    env["REPORT"] = str(report)
    (suite / "test_probe.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_probe(tmp_path):\n    Path(os.environ['REPORT']).write_text(os.environ['PYTEST_DEBUG_TEMPROOT'])\n"
    )
    command = [sys.executable, "-m", "pytest", "-q", "-m", "not pg"]
    result = subprocess.run(command, cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    private = Path(report.read_text()).parent
    assert private.parent == system_temp and (private.stat().st_mode & 0o777) == 0o700
    assert subject._private_temp_parent(system_temp) == private
    inherited = tmp_path / "agentic-pkm-pytest-inherited"
    inherited.mkdir(mode=0o755)
    inherited.chmod(0o755)
    old = _candidate(inherited, "old", pid=_dead_pid())
    subject._prune_expired_temp_roots(inherited)
    assert old.exists()
    env["PYTEST_DEBUG_TEMPROOT"] = str(inherited)
    result = subprocess.run(command, cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(report.read_text()).parent == inherited
    assert old.exists()
    private_inherited = tmp_path / "private-inherited"
    private_inherited.mkdir(mode=0o700)
    unknown = _candidate(private_inherited, "unknown", pid=_dead_pid())
    (private_inherited / subject._TEMP_PARENT_LOCK).symlink_to(tmp_path / "foreign-lock")
    env["PYTEST_DEBUG_TEMPROOT"] = str(private_inherited)
    result = subprocess.run(command, cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(report.read_text()).parent == private_inherited
    assert unknown.exists()
    assert (private_inherited / subject._TEMP_PARENT_LOCK).is_symlink()


def test_cooperating_parent_locks_exclude_concurrent_changes(tmp_path: Path) -> None:
    subject = _root_harness()
    descriptor, identity = subject._lock_temp_parent(tmp_path, wait=True)
    try:
        info = tmp_path.stat()
        assert identity == (info.st_dev, info.st_ino)
        with pytest.raises(OSError, match="lock unavailable"):
            subject._lock_temp_parent(tmp_path, wait=False)
    finally:
        os.close(descriptor)
    other, _ = subject._lock_temp_parent(tmp_path, wait=False)
    os.close(other)


def test_unsafe_default_parent_fails_loud(tmp_path: Path) -> None:
    subject = _root_harness()
    parent = tmp_path / ("pkm-" + str(os.geteuid()))
    parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError, match="not private"):
        subject._private_temp_parent(tmp_path)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_broken_default_parent_lock_fails_loud_before_collection(tmp_path: Path, kind: str) -> None:
    subject = _root_harness()
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir(mode=0o700)
    parent = subject._private_temp_parent(system_temp)
    bad_lock = parent / subject._TEMP_PARENT_LOCK
    if kind == "symlink":
        bad_lock.symlink_to(tmp_path / "foreign-lock")
    else:
        os.mkfifo(bad_lock)
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env.pop("PYTEST_DEBUG_TEMPROOT", None)
    env["TMPDIR"] = str(system_temp)
    (suite / "test_probe.py").write_text("from pathlib import Path\nPath('collected').touch()\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
                            cwd=suite, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "pytest temporary-root isolation failed" in result.stdout + result.stderr
    assert not (suite / "collected").exists()
    assert bad_lock.is_symlink() if kind == "symlink" else bad_lock.exists()


def test_fifo_markers_refuse_without_blocking_cleanup_or_nested_start(tmp_path: Path) -> None:
    subject = _root_harness()
    bad_owner = _candidate(tmp_path, "bad-owner", pid=_dead_pid())
    owner_marker = bad_owner / subject._TEMP_OWNER
    owner_marker.unlink()
    os.mkfifo(owner_marker)
    bad_finish = _candidate(tmp_path, "bad-finish", pid=_dead_pid())
    finish_marker = bad_finish / subject._TEMP_FINISHED
    finish_marker.unlink()
    os.mkfifo(finish_marker)
    old_ns = time.time_ns() - 8 * 24 * 60 * 60 * 1_000_000_000
    os.utime(bad_owner, ns=(old_ns, old_ns))
    os.utime(bad_finish, ns=(old_ns, old_ns))
    harness = Path(__file__).resolve().parents[2] / "conftest.py"
    code = (
        "import importlib.util,sys\n"
        "from pathlib import Path\n"
        "spec=importlib.util.spec_from_file_location('subject',sys.argv[1])\n"
        "subject=importlib.util.module_from_spec(spec); spec.loader.exec_module(subject)\n"
        "subject._prune_expired_temp_roots(Path(sys.argv[2]))\n"
        "try: subject._temp_parent_locks(Path(sys.argv[3]))\n"
        "except OSError: print('refused',flush=True)\n"
        "else: raise SystemExit('FIFO ancestor was accepted')\n"
    )
    result = subprocess.run([sys.executable, "-c", code, str(harness), str(tmp_path), str(bad_owner)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "refused"
    assert (bad_owner / "artifact.txt").exists() and (bad_finish / "artifact.txt").exists()


def test_busy_parent_lock_has_bounded_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject = _root_harness()
    descriptor, _ = subject._lock_temp_parent(tmp_path, wait=True)
    try:
        values = iter((0.0, 31.0))
        with monkeypatch.context() as patch:
            patch.setattr(subject.time, "monotonic", lambda: next(values))
            with pytest.raises(subject._TempParentBusy, match="lock unavailable"):
                subject._lock_temp_parent(tmp_path, wait=True)
    finally:
        os.close(descriptor)


def test_normal_prune_does_not_block_new_pytest_start(tmp_path: Path) -> None:
    parent = tmp_path / "shared-parent"
    parent.mkdir(mode=0o700)
    expired = _candidate(parent, "expired", pid=_dead_pid())
    suite = tmp_path / "suite"
    suite.mkdir()
    env = _harness(suite)
    env["PYTEST_DEBUG_TEMPROOT"] = str(parent)
    (suite / "test_probe.py").write_text("def test_probe(tmp_path):\n    assert tmp_path.is_dir()\n")
    harness = Path(__file__).resolve().parents[2] / "conftest.py"
    cleaner_code = (
        "import importlib.util,sys\n"
        "from pathlib import Path\n"
        "spec=importlib.util.spec_from_file_location('subject',sys.argv[1])\n"
        "subject=importlib.util.module_from_spec(spec); spec.loader.exec_module(subject)\n"
        "original=subject.shutil.rmtree\n"
        "def paused(*args,**kwargs):\n"
        "    print('delete-paused',flush=True); sys.stdin.read(1); return original(*args,**kwargs)\n"
        "paused.avoids_symlink_attacks=original.avoids_symlink_attacks\n"
        "subject.shutil.rmtree=paused\n"
        "subject._prune_expired_temp_roots(Path(sys.argv[2]))\n"
    )
    cleaner = subprocess.Popen([sys.executable, "-c", cleaner_code, str(harness), str(parent)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert cleaner.stdout is not None
        assert select.select([cleaner.stdout], [], [], 10)[0]
        line = cleaner.stdout.readline()
        assert line == "delete-paused\n", cleaner.stderr.read() if cleaner.poll() is not None else line
        assert not expired.exists()  # renamed only after the parent's lock was held
        child = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "not pg"],
                               cwd=suite, env=env, capture_output=True, text=True, timeout=15)
        assert child.returncode == 0, child.stdout + child.stderr
        assert cleaner.poll() is None  # pytest completed while deletion was still paused
    finally:
        if cleaner.stdin is not None:
            cleaner.stdin.close()
        try:
            cleaner.wait(timeout=15)
        except subprocess.TimeoutExpired:
            cleaner.kill()
            cleaner.wait(timeout=10)
        if cleaner.stdout is not None:
            cleaner.stdout.close()
        if cleaner.stderr is not None:
            cleaner.stderr.close()
    assert cleaner.returncode == 0
