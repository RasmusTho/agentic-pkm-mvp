"""ID-bound launch and checkpoint recovery, with simulated Docker and real Git."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_hardening import _layout, _mapping
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli
from tests.builderops.test_epic_workspace_lifecycle import _new_worker
from tests.builderops.test_epic_workspace_openhands import _main, _setup


def test_failed_start_holds_while_id_exists_then_settles_and_late_start_fails(tmp_path, capsys):
    root, _, server = _setup(tmp_path, capsys)

    class PortConflict(FakeEngine):
        fail_start = True
        fail_remove = True

        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "start"] and "--attach" not in argv and self.fail_start:
                return subprocess.CompletedProcess(argv, 125, "", "port already allocated")
            if list(argv)[:2] == ["docker", "rm"] and self.fail_remove:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return super().__call__(argv, **kwargs)

    engine = PortConflict()
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    cid = _mapping(root, 6617)["container_id"]
    assert engine.containers["w-a"] == "created"
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "port conflict") == 2
    assert _mapping(root, 6617)["state"] == "starting"
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    engine.fail_remove = False
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "port conflict") == 0
    assert engine(["docker", "start", cid], capture_output=True, text=True, check=False, timeout=30).returncode != 0
    engine.fail_start = False
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    assert _mapping(root, 6617)["container_id"] != cid


def test_controller_death_during_id_bound_start_cannot_restart_removed_id(tmp_path, capsys):
    root, _, server = _setup(tmp_path, capsys)

    class DyingClient(FakeEngine):
        die = True
        block_remove = True

        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "start"] and "--attach" not in argv and self.die:
                self.die = False
                # Model a request accepted by the daemon before the controller dies.
                super().__call__(argv, **kwargs)
                raise SystemExit("simulated controller death")
            if list(argv)[:2] == ["docker", "rm"] and self.block_remove:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return super().__call__(argv, **kwargs)

    engine = DyingClient()
    checkout = _layout(root).checkout("w-a")
    (checkout / "partial.py").write_text("partial\n")
    with pytest.raises(SystemExit):
        _main(root, engine, server, "openhands-start", "--worker", "w-a")
    cid = _mapping(root, 6617)["container_id"]
    assert engine.containers["w-a"] == "running"
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "death") == 2
    assert not _mapping(root, 6617).get("checkpoints")
    engine.block_remove = False
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "death") == 0
    assert _mapping(root, 6617)["checkpoints"]
    assert engine(["docker", "start", cid], capture_output=True, text=True, check=False, timeout=30).returncode != 0
    assert (checkout / "partial.py").read_text() == "partial\n"


def test_late_create_after_timeout_cannot_write_or_displace_successor(tmp_path, capsys):
    root, _, server = _setup(tmp_path, capsys)

    class LateCreate(FakeEngine):
        pending_create = None

        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "create"] and "--rm" not in argv and self.pending_create is None:
                self.pending_create = list(argv)
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return super().__call__(argv, **kwargs)

    engine = LateCreate()
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    assert _mapping(root, 6617)["container_id"] is None
    assert not [call for call in engine.calls if call[1] == "start"]
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "lost create") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0
    delayed = engine(engine.pending_create, capture_output=True, text=True, check=False, timeout=30)
    assert delayed.returncode != 0
    assert engine.containers["w-a"] == "running"


def test_death_after_create_before_record_can_settle_without_start(tmp_path, capsys):
    root, _, server = _setup(tmp_path, capsys)

    class DiedAfterCreate(FakeEngine):
        die = True

        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "create"] and "--rm" not in argv and self.die:
                self.die = False
                super().__call__(argv, **kwargs)
                raise SystemExit("simulated lost create response")
            return super().__call__(argv, **kwargs)

    engine = DiedAfterCreate()
    with pytest.raises(SystemExit):
        _main(root, engine, server, "openhands-start", "--worker", "w-a")
    assert _mapping(root, 6617)["container_id"] is None
    assert engine.containers["w-a"] == "created"
    assert not [call for call in engine.calls if call[1] == "start"]
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "lost response") == 0
    assert "w-a" not in engine.containers
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0


def test_death_after_intent_before_create_is_recoverable(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = _layout(root)
    ew._begin_start(layout, 6617, "w-a", runtime="openhands", started_at=ew._now())
    assert _mapping(root, 6617)["state"] == "starting"
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "client died") == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0


def test_legacy_unknown_run_without_id_is_not_cleared_by_absence(tmp_path, capsys):
    root, engine, _ = _setup(tmp_path, capsys)
    layout = _layout(root)
    ew._begin_start(layout, 6617, "w-a", runtime="openhands", started_at=ew._now())
    ew._record_worker(layout, 6617, launch_protocol=None)
    assert "legacy launch hold" in ew.next_authorized_action(_mapping(root, 6617))["action"]
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "legacy") == 2
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "legacy") == 2
    assert _mapping(root, 6617)["state"] == "starting"
    assert not [call for call in engine.calls if call[1] == "rm"]


def test_auto_removed_timed_out_checkpoint_is_not_false_unknown(tmp_path, capsys):
    root, _, _ = _setup(tmp_path, capsys)

    class AutoRemoved(FakeEngine):
        once = True

        def __call__(self, argv, **kwargs):
            if self.once and list(argv)[:2] == ["docker", "run"] and any("/control/checkpoints/" in arg for arg in argv):
                self.once = False
                name = argv[argv.index("--name") + 1]
                cid = self.ids.pop(name)
                self.pending.pop(cid)
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return super().__call__(argv, **kwargs)

    engine = AutoRemoved()
    (_layout(root).checkout("w-a") / "partial.txt").write_text("keep\n")
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "auto removed") == 2
    assert not _mapping(root, 6617).get("checkpoint_inspection_unknown")
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "retry") == 0
    assert _mapping(root, 6617)["checkpoints"]


def test_completed_checkpoint_write_with_lost_response_is_adopted_after_proof(tmp_path, capsys):
    root, _, _ = _setup(tmp_path, capsys)

    class LostResponse(FakeEngine):
        once = True
        unavailable = False
        refuse_remove = False

        def __call__(self, argv, **kwargs):
            argv = list(argv)
            if self.unavailable and argv[:2] == ["docker", "ps"] and "--no-trunc" in argv:
                return subprocess.CompletedProcess(argv, 1, "", "engine unavailable")
            if self.refuse_remove and argv[:2] == ["docker", "rm"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            result = super().__call__(argv, **kwargs)
            if self.once and argv[:2] == ["docker", "run"] and "update-ref" in argv and "--stdin" in argv:
                self.once = False
                self.unavailable = True
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return result

    engine = LostResponse()
    checkout = _layout(root).checkout("w-a")
    (checkout / "partial.txt").write_text("keep\n")
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "lost response") == 2
    marker = _mapping(root, 6617)["checkpoint_inspection_unknown"]
    assert marker["container_id"] in engine.pending
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "retry") == 2
    assert _mapping(root, 6617)["checkpoint_inspection_unknown"] == marker
    engine.unavailable = False
    engine.refuse_remove = True
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "writer remains") == 2
    assert _mapping(root, 6617)["checkpoint_inspection_unknown"] == marker
    engine.refuse_remove = False
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "retry") == 0
    [record] = _mapping(root, 6617)["checkpoints"]
    assert record["ref"] == "refs/checkpoints/ckpt-0001" and record["adopted"] is True
    assert (checkout / "partial.txt").read_text() == "keep\n"


def test_foreign_exact_name_is_never_removed(tmp_path, capsys):
    root, engine, _ = _setup(tmp_path, capsys)
    name = _layout(root).container_name("w-a")
    engine.ids[name] = "a" * 64
    engine.containers["w-a"] = "running"
    engine.labels["w-a"] = ["foreign.service=yes"]
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "scope") == 2
    assert "expected scope" in capsys.readouterr().err
    assert engine.containers["w-a"] == "running"
    assert not [call for call in engine.calls if call[1] == "rm"]


def test_concurrent_openhands_starts_serialize_port_selection(tmp_path, capsys):
    root, _, server = _setup(tmp_path, capsys)
    entered, finish = Event(), Event()

    class Delayed(FakeEngine):
        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "start"] and "--attach" not in argv and not entered.is_set():
                entered.set()
                assert finish.wait(10)
            return super().__call__(argv, **kwargs)

    engine = Delayed()
    _new_worker(root, engine, "unused", "w-b", 6618, branch="b/b")
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(_main, root, engine, server, "openhands-start", "--worker", "w-a")
        assert entered.wait(10)
        try:
            assert _main(root, engine, server, "openhands-start", "--worker", "w-b") == 2
        finally:
            finish.set()
        assert first.result(timeout=10) == 0
    assert _main(root, engine, server, "openhands-start", "--worker", "w-b") == 0
    assert engine.ports["w-a"] != engine.ports["w-b"]
