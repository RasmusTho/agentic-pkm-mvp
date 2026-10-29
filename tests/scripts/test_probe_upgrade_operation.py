"""Hermetic real readers/orchestration; only host/service/transport ports vary."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_upgrade_operation as operation  # noqa: E402
import upgrade_host_probe as carrier  # noqa: E402
import install_host_probe as installer  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


def packet(value="a" * 32):
    return {
        "issue": 6457,
        "parent_issue": 4076,
        "source_merge": operation.SOURCE_MERGE,
        "claim_holder": carrier.HOLDER,
        "lease_id": "lease-c186483a",
        "operation": value,
    }


class OfflineHost:
    """Actual private files, proc/cgroup metadata, and the exact command boundary."""

    def __init__(self, root, monkeypatch):
        self.root, self.monkeypatch = root, monkeypatch
        self.old, self.new, _ = carrier._source_pair()
        self.package = root / "package"
        self.script = self.package / operation.SCRIPT_REL
        self.config, self.template = root / "etc/prod.env", root / "etc/unit.service"
        self.incident, self.runtime = root / "state/alert-state.json", root / "runtime"
        self.proc, self.cgroup = root / "proc", root / "cgroup"
        self.operation_root = root / "operations"
        self.events, self.phases, self.sleeps = [], [], []
        self.clock = SimpleNamespace(monotonic=time.monotonic, sleep=self.sleeps.append)
        self.on_phase = self.after_start = None
        self.journal_rows = None
        self.starts, self.reuse_invocation = 0, False
        self.normal_launches = 0
        self.supervisor = None
        self.predecessor_supervisor = None
        self.original_pins = {}
        self.supervisor_starts = 0
        self.supervisor_launches = 0
        for relative, data in self.old.files.items():
            self.write(self.package / relative, data, 0o664)
        for parent in [self.package, *self.script.parents]:
            if parent.is_relative_to(root):
                parent.chmod(0o775)
        self.write(self.config, installer.render_probe_environment("prod").encode(), 0o644)
        self.write(
            self.template, self.old.files["config/systemd/yggdrasil-host-probe@.service"], 0o644
        )
        assert sha(self.config.read_bytes()) == operation.CONFIG_SHA256
        assert sha(self.template.read_bytes()) == operation.UNIT_SHA256
        self.write(self.runtime / "binding.json", b"private fake binding never read", 0o600)
        self.set_incident("11111111-1111-4111-8111-111111111111")
        self.write(
            self.proc / "sys/kernel/random/boot_id",
            b"11111111-2222-3333-4444-555555555555\n",
            0o644,
        )
        self.fields = self.configured_fields()
        self.set_active("c" * 32, 100)
        self.bind(operation)
        monkeypatch.setattr(carrier, "LOCAL_RECORD_ROOT", root / "local-records", raising=False)
        monkeypatch.setattr(operation.platform, "system", lambda: "Linux")
        monkeypatch.setattr(operation.platform, "node", lambda: "ygg-prod")
        uid = os.geteuid()
        account = operation.pwd.getpwuid(uid)
        monkeypatch.setattr(
            operation.grp, "getgrgid", lambda _: SimpleNamespace(gr_mem=[account.pw_name])
        )
        monkeypatch.setattr(operation.pwd, "getpwall", lambda: [account])
        monkeypatch.setattr(operation.os, "listxattr", lambda _: [], raising=False)
        monkeypatch.setattr(carrier, "time", self.clock)

    def bind(self, module):
        # Include assembled remote modules while leaving subprocess.wait's
        # shared stdlib polling clock real and outside the observation recorder.
        self.monkeypatch.setattr(module, "time", self.clock)
        for name, value in {
            "PACKAGE": self.package,
            "SCRIPT": self.script,
            "CONFIG": self.config,
            "TEMPLATE": self.template,
            "INCIDENT": self.incident,
            "RUNTIME_DIRECTORY": self.runtime,
            "PROC_ROOT": self.proc,
            "CGROUP_ROOT": self.cgroup,
            "OPERATION_ROOT": self.operation_root,
            "EXPECTED_UID": os.geteuid(),
            "EXPECTED_GID": os.getegid(),
            "INTERPRETER": Path(sys.executable),
            "ENGINE_SHA256": sha(b"offline-qualified-engine"),
            "_safe_command": self.command,
            "_open_directory": self.open_directory,
            **self.original_pins,
        }.items():
            self.monkeypatch.setattr(module, name, value, raising=False)

    def open_directory(self, path):
        # The substituted trust root is private pytest storage. Descendants and
        # source files still use the production no-follow/owner/mode readers.
        path = Path(path)
        assert path.is_relative_to(self.root)
        for part in (path, *path.parents):
            if not part.is_relative_to(self.root):
                break
            meta = part.lstat()
            if (
                not stat.S_ISDIR(meta.st_mode)
                or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o002
            ):
                raise operation.OperationFailure("directory_metadata")
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def write(self, path, data, mode=0o600):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def set_incident(self, correlation):
        self.write(
            self.incident,
            json.dumps(
                {
                    "status": "down",
                    "environment": "prod",
                    "ts": 1,
                    "correlation_id": correlation,
                    "failures": ["health required_ok=false"],
                }
            ).encode(),
        )

    def configured_fields(self):
        return {
            "LoadState": "loaded",
            "UnitFileState": "enabled",
            "FragmentPath": str(self.template),
            "DropInPaths": "",
            "User": "root",
            "Group": "root",
            "WorkingDirectory": str(self.package),
            "ExecStart": "{ argv[]="
            + str(Path(sys.executable))
            + " "
            + str(self.package / "ops/host-setup/linux/host_probe_launcher.py")
            + " --channel prod ; }",
            "EnvironmentFiles": str(self.config) + " (ignore_errors=no)",
            "KillMode": "control-group",
            "Restart": "on-failure",
            "TimeoutStopUSec": "30s",
            "NeedDaemonReload": "no",
            "ProtectSystem": "strict",
            "ReadWritePaths": "/root/.local/state/yggdrasil/secret-controller",
            "NRestarts": "0",
            "Job": "0",
            "Result": "success",
            "StandardOutput": "journal",
            "StandardError": "journal",
        }

    def process(self, pid, ppid, start, cgroup, command, environment=b"", cwd=None):
        root = self.proc / str(pid)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        tail = ["S", str(ppid)] + ["0"] * 17 + [str(start)]
        self.write(root / "stat", (str(pid) + " (python) " + " ".join(tail)).encode())
        self.write(root / "cgroup", ("0::" + cgroup + "\n").encode())
        self.write(root / "cmdline", b"\0".join(str(item).encode() for item in command) + b"\0")
        self.write(root / "environ", environment)
        for leaf, target in [("exe", Path(sys.executable).resolve()), ("cwd", cwd or self.package)]:
            link = root / leaf
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target)

    def set_active(self, invocation, pid):
        for path in list(self.proc.iterdir()):
            if path.name.isdigit() and (
                self.supervisor is None or path.name != self.supervisor["MainPID"]
            ):
                shutil.rmtree(path)
        cgroup = "/system.slice/system-yggdrasil.slice/" + operation.UNIT
        started = int(time.monotonic() * 1_000_000)
        self.fields.update(
            ActiveState="active",
            SubState="running",
            MainPID=str(pid),
            InvocationID=invocation,
            ControlGroup=cgroup,
            ExecMainStartTimestampMonotonic=str(started),
            InactiveEnterTimestampMonotonic="0",
        )
        self.process(
            pid,
            1,
            started,
            cgroup,
            [
                sys.executable,
                self.package / "ops/host-setup/linux/host_probe_launcher.py",
                "--channel",
                "prod",
            ],
        )
        environment = (
            "HOST_SECRET_BOOTSTRAP_CHANNEL=prod\0HOST_SECRET_BOOTSTRAP_CONSUMER=heimdal-external-alerts\0HOST_SECRET_RUNTIME_ENV_FILE="
            + str(self.runtime / "binding.json")
            + "\0"
        ).encode()
        self.process(
            pid + 1, pid, started + 1, cgroup, [sys.executable, self.script, "--loop"], environment
        )
        for member in (pid, pid + 1):
            descriptor = self.proc / str(member) / "fd/2"
            descriptor.parent.mkdir(mode=0o700)
            descriptor.symlink_to(f"socket:[{pid + 9000}]")
        self.write(
            self.cgroup / cgroup.lstrip("/") / "cgroup.procs", f"{pid}\n{pid + 1}\n".encode()
        )

    def records(self, messages=None, invocation=None):
        # Retained bootstrap Popen inherits journal stdout/stderr. Journald's
        # trusted metadata remains the launcher's, as documented for streams.
        pid = self.fields["MainPID"]
        messages = (
            messages
            or [
                "probe-down detected but outage already recorded; suppressing duplicate alert. environment=prod"
            ]
            * 2
        )
        return "\n".join(
            json.dumps(
                {
                    "MESSAGE": "2026-10-29 14:00:00,000 [prod-probe] INFO " + message,
                    "_SYSTEMD_INVOCATION_ID": invocation or self.fields["InvocationID"],
                    "_PID": pid,
                    "_TRANSPORT": "stdout",
                    "_SYSTEMD_CGROUP": self.fields["ControlGroup"],
                    "_STREAM_ID": "7" * 32,
                    "__MONOTONIC_TIMESTAMP": str(
                        int(self.fields["ExecMainStartTimestampMonotonic"]) + index + 1
                    ),
                    "__CURSOR": f"cursor-{index}",
                }
            )
            for index, message in enumerate(messages)
        )

    def command(self, argv, **_kwargs):
        if argv[0] == "/usr/bin/docker":
            return "offline-qualified-engine\n"
        if argv[:2] == ["/usr/bin/systemctl", "list-units"]:
            return operation.UNIT + " loaded active running probe\n"
        if argv[:2] == ["/usr/bin/systemctl", "show"]:
            fields = (
                self.fields
                if argv[2] == operation.UNIT
                else self.predecessor_supervisor
                if argv[2] == operation._operation_name(operation.ORIGINAL_OPERATION)
                and self.predecessor_supervisor is not None
                else self.supervisor
            )
            if fields is None:
                return (
                    "LoadState=not-found\nActiveState=inactive\nSubState=dead\nMainPID=0\nJob=0\n"
                )
            return "\n".join(key + "=" + value for key, value in fields.items()) + "\n"
        if argv[:3] == ["/usr/bin/systemctl", "stop", operation.UNIT]:
            self.events.append("stop")
            self.fields.update(
                ActiveState="inactive",
                SubState="dead",
                MainPID="0",
                InactiveEnterTimestampMonotonic=str(int(time.monotonic() * 1_000_000)),
            )
            self.write(self.cgroup / self.fields["ControlGroup"].lstrip("/") / "cgroup.procs", b"")
            for path in list(self.proc.iterdir()):
                if path.name.isdigit() and (
                    self.supervisor is None or path.name != self.supervisor["MainPID"]
                ):
                    shutil.rmtree(path)
            return ""
        if argv[:3] == ["/usr/bin/systemctl", "start", operation.UNIT]:
            self.events.append("start")
            self.starts += 1
            self.normal_launches += 1
            invocation = (
                "c" * 32 if self.reuse_invocation else format(12 + self.normal_launches, "032x")
            )
            self.set_active(invocation, 100 + self.normal_launches * 100)
            if self.after_start:
                self.after_start(self.starts)
            return ""
        if argv[0] == "/usr/bin/journalctl":
            assert "_SYSTEMD_INVOCATION_ID=" + self.fields["InvocationID"] in argv
            return self.journal_rows if self.journal_rows is not None else self.records()
        if argv[0] == "/usr/bin/systemd-run":
            self.supervisor_launches += 1
            name = next(arg.removeprefix("--unit=") for arg in argv if arg.startswith("--unit="))
            value = name.removeprefix("yggdrasil-probe-upgrade-6457-").removesuffix(".service")
            worker_root = self.operation_root / value
            cgroup = "/system.slice/" + name
            self.supervisor = {
                "LoadState": "loaded",
                "ActiveState": "active",
                "SubState": "running",
                "MainPID": str(os.getpid()),
                "InvocationID": "b" * 32,
                "ControlGroup": cgroup,
                "Job": "0",
                "Transient": "yes",
                "User": "root",
                "Group": "root",
                "ExecStart": "{ argv[]="
                + str(Path(sys.executable))
                + " -I -B "
                + str(worker_root / "worker.py")
                + " "
                + value
                + " ; }",
                "WorkingDirectory": str(worker_root),
                "RuntimeMaxUSec": "7min",
                "TimeoutStopUSec": "5s",
                "KillMode": "control-group",
                "Restart": "no",
                "StandardOutput": "null",
                "StandardError": "null",
            }
            self.process(
                os.getpid(),
                1,
                1234 + self.supervisor_launches * 100,
                cgroup,
                [sys.executable, "-I", "-B", worker_root / "worker.py", value],
                cwd=worker_root,
            )
            self.write(
                self.cgroup / cgroup.lstrip("/") / "cgroup.procs", f"{os.getpid()}\n".encode()
            )
            return ""
        if argv[:2] == ["/usr/bin/systemctl", "start"] and argv[2].startswith(
            "yggdrasil-probe-upgrade-6457-"
        ):
            self.supervisor_starts += 1
            root = Path(self.supervisor["WorkingDirectory"])
            value = root.name
            self.supervisor.update(
                ActiveState="active",
                SubState="running",
                MainPID=str(os.getpid()),
                InvocationID="f" * 32
                if self.supervisor_starts == 1
                else format(14 + self.supervisor_starts, "032x"),
            )
            self.process(
                os.getpid(),
                1,
                1234 + self.supervisor_starts,
                self.supervisor["ControlGroup"],
                [sys.executable, "-I", "-B", root / "worker.py", value],
                cwd=root,
            )
            self.write(
                self.cgroup / self.supervisor["ControlGroup"].lstrip("/") / "cgroup.procs",
                f"{os.getpid()}\n".encode(),
            )
            return ""
        raise AssertionError("unmodeled effect port: " + repr(argv))

    def journal(self, value):
        self.phases.append(json.loads(json.dumps(value)))
        operation._metadata_write(self.root / "test-phase.json", value)
        if self.on_phase:
            self.on_phase(value["phase"])

    def run(self):
        return operation.run(
            packet(),
            before_manifest=self.old.manifest,
            after_manifest=self.new.manifest,
            old_bytes=self.old.files[operation.SCRIPT_REL],
            new_bytes=self.new.files[operation.SCRIPT_REL],
            journal=self.journal,
        )

    def finish_supervisor(self):
        self.write(self.cgroup / self.supervisor["ControlGroup"].lstrip("/") / "cgroup.procs", b"")
        shutil.rmtree(self.proc / self.supervisor["MainPID"])
        self.supervisor.update(ActiveState="inactive", SubState="dead", MainPID="0")


@pytest.fixture
def host(tmp_path, monkeypatch):
    original_alarm = signal.getsignal(signal.SIGALRM)
    fixture = OfflineHost(tmp_path, monkeypatch)
    yield fixture
    signal.alarm(0)
    signal.signal(signal.SIGALRM, original_alarm)


def rendering_authority():
    return {
        "issue": operation.RENDERING_INSTALLATION_ISSUE,
        "body_sha256": operation.RENDERING_INSTALLATION_BODY_SHA256,
        "holder": "synthetic-verified-installation-owner",
        "session": "11111111-1111-4111-8111-111111111111",
        "branch": "codex/issue-6476-probe-rendering-install",
        "worktree": str(ROOT),
        "source_head": carrier._git("rev-parse", "HEAD"),
        "registration_generation": "6" * 32,
        "scope": "install-0172-to-17c2-on-ygg-prod-under-4076",
    }


@pytest.fixture
def successor_host(host, monkeypatch):
    """Produce honest legacy UNKNOWN via the real helper, then pin synthetic metadata.

    Only filesystem/host identities and their immutable hashes are substituted.
    Original production hashes remain independently asserted below. No observation
    marker or stubbed admission verdict participates in successor qualification.
    """
    original = operation.ORIGINAL_OPERATION
    request = carrier._request(
        original, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])

    def unqualified_start(_count):
        link = host.proc / host.fields["MainPID"] / "exe"
        link.unlink()
        link.symlink_to("/usr/bin/false")

    host.after_start = unqualified_start
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main(original)
    host.finish_supervisor()
    status = operation.remote_entry("status", request)
    assert status["status"] == "unknown" and status["phase"] == "start_intent"
    assert status["failure"] == "main_process_boundary" and status["supervisor"]["reaped"]
    host.after_start = None
    link = host.proc / host.fields["MainPID"] / "exe"
    link.unlink()
    link.symlink_to(Path(sys.executable).resolve())
    original_root = host.operation_root / original
    host.original_pins = {
        "ORIGINAL_REQUEST_SHA256": sha((original_root / "request.json").read_bytes()),
        "ORIGINAL_FILE_SHA256": {
            name: sha((original_root / name).read_bytes())
            for name in operation.ORIGINAL_FILE_SHA256
        },
    }
    host.bind(operation)
    host.predecessor_supervisor = dict(host.supervisor)
    host.supervisor = None
    host.old, host.new, _ = carrier._rendering_source_pair()
    host.legacy_request = request
    host.legacy_handle = prepared["handle"]
    host.original_bytes = {
        path: path.read_bytes()
        for path in [host.operation_root / "active.json", *original_root.iterdir()]
        if path.is_file()
    }
    host.events.clear()
    host.phases.clear()
    host.starts = 0
    return host


def successor_request(host, value="a" * 32):
    return carrier._request(
        value,
        "lease-abcdef",
        host.old,
        host.new,
        lease_expires_at="2099-01-01T00:00:00Z",
        installation_authority=rendering_authority(),
    )


class AssembledSuccessorTransport:
    """Execute the real serialized carrier program and its finite worker."""

    def __init__(self, host, monkeypatch, *, lose_authorization=False, phase_hook=None):
        self.host, self.monkeypatch = host, monkeypatch
        self.lose_authorization, self.phase_hook = lose_authorization, phase_hook
        self.calls = []
        self.module = None

    def __call__(self, payload):
        source = payload.decode()
        action = next(
            name
            for name in ("prepare", "authorize", "status", "reconcile")
            if f"remote_entry({name!r}," in source
        )
        self.calls.append(action)
        if (
            action == "status"
            and self.host.supervisor
            and self.host.supervisor["ActiveState"] == "active"
        ):
            self.monkeypatch.setenv("INVOCATION_ID", self.host.supervisor["InvocationID"])
            self.module.worker_main(self.host.supervisor["WorkingDirectory"].split("/")[-1])
            self.host.finish_supervisor()
        source = source.replace(
            "try:\n    _result=", "_test_transport.bind(_op)\ntry:\n    _result=", 1
        )
        namespace = {"_test_transport": self}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(source, "<assembled-successor-carrier>", "exec"), namespace)
        self.module = namespace["_op"]
        receipt = json.loads(output.getvalue())
        if action == "authorize" and self.lose_authorization:
            self.lose_authorization = False
            raise carrier.CarrierUnknown("lost original successor authorization response")
        return receipt

    def bind(self, module):
        self.host.bind(module)
        if self.phase_hook:
            write = module._metadata_write

            def after_durable_write(path, value, **kwargs):
                write(path, value, **kwargs)
                if path.name in {"phase.json", "reconcile-1-phase.json"}:
                    self.phase_hook(value["phase"], module)

            module._metadata_write = after_durable_write


def bind_successor_carrier(host, monkeypatch, **kwargs):
    transport = AssembledSuccessorTransport(host, monkeypatch, **kwargs)
    monkeypatch.setattr(carrier, "_ssh", transport)
    monkeypatch.setattr(
        carrier,
        "_lease_readback",
        lambda *_args, **_kwargs: {
            "lease_expires_at": "2099-01-01T00:00:00Z",
            "installation_authority": rendering_authority(),
        },
    )
    return transport


def assert_original_preserved(host):
    assert all(path.read_bytes() == raw for path, raw in host.original_bytes.items())
    # Execute the unchanged pre-successor follow reader, not a rewritten legacy
    # request or a successor-owned interpretation of its terminal result.
    pinned = ModuleType("pinned_original_operation")
    source = carrier._git_bytes(
        "show", "e0b5a1b0d3226247fc4f5469b1285844da13427e:scripts/probe_upgrade_operation.py"
    )
    exec(compile(source, "<pinned-original-follow>", "exec"), pinned.__dict__)
    host.bind(pinned)
    status = pinned.remote_entry("status", host.legacy_request)
    assert status["status"] == "unknown" and status["handle"] == host.legacy_handle
    assert status["failure"] == "main_process_boundary" and status["supervisor"]["reaped"]


def test_verified_rendering_successor_admission(successor_host, monkeypatch):
    host = successor_host
    before = host.incident.read_bytes()
    transport = bind_successor_carrier(host, monkeypatch)
    result = carrier.run("lease-abcdef", "a" * 32, rendering_successor=True)
    assert result["status"] == "committed", {
        key: result.get(key)
        for key in ("status", "failure", "phase", "recovery_failure", "recovery")
    }
    assert transport.calls == ["prepare", "authorize", "status"]
    assert host.events == ["stop", "start"]
    assert sha(host.script.read_bytes()) == operation.RENDERING_SCRIPT_SHA256
    assert result["source_manifest_sha256"] == operation.RENDERING_MANIFEST_SHA256
    assert host.incident.read_bytes() == before
    assert result["normal_cycles"]["completed_cycles"] == 2
    assert result["supervisor"]["reaped"]
    assert not list(host.script.parent.glob(".prod_probe.*.stage"))
    assert_original_preserved(host)


def test_successor_preserves_original_unknown_and_fence(successor_host, monkeypatch):
    host = successor_host
    transport = bind_successor_carrier(host, monkeypatch, lose_authorization=True)
    lost = carrier.run("lease-abcdef", "a" * 32, rendering_successor=True)
    assert lost["status"] == "unknown" and lost["handle"]
    followed = carrier.run("lease-abcdef", "a" * 32, "follow")
    assert followed["status"] == "committed" and followed["handle"] == lost["handle"]
    assert transport.calls.count("prepare") == transport.calls.count("authorize") == 1
    legacy = dict(host.legacy_request)
    legacy["packet"] = {**legacy["packet"], "operation": "d" * 32}
    with pytest.raises(
        operation.OperationFailure, match="original_operation_unresolved_or_committed"
    ):
        operation.remote_entry("prepare", legacy, programs=carrier._programs())
    with pytest.raises(
        operation.OperationFailure, match="original_operation_unresolved_or_committed"
    ):
        operation.remote_entry(
            "prepare", successor_request(host, "e" * 32), programs=carrier._programs()
        )
    assert host.events == ["stop", "start"]
    assert_original_preserved(host)


@pytest.mark.parametrize(
    "drift",
    [
        "active_helper",
        "foreign_fence",
        "partial_original",
        "changed_result",
        "continuation",
        "source",
        "retained",
        "config",
        "unit",
        "normal_invocation",
        "malformed_incident",
        "writer",
        "held_lock",
    ],
)
def test_successor_refuses_unqualified_current_state(successor_host, monkeypatch, drift):
    host = successor_host
    request = successor_request(host)
    root = host.operation_root / operation.ORIGINAL_OPERATION
    lock = None
    if drift == "active_helper":
        host.predecessor_supervisor.update(ActiveState="active", SubState="running", MainPID="999")
    elif drift == "foreign_fence":
        operation._metadata_write(
            host.operation_root / "active.json", {"operation": "9" * 32, "request_sha256": "9" * 64}
        )
    elif drift == "partial_original":
        (root / "handle.json").unlink()
    elif drift == "changed_result":
        operation._metadata_write(
            root / "result.json", {"status": "verified_observed_postconditions"}
        )
    elif drift == "continuation":
        operation._metadata_write(root / "reconcile-1.json", {"unqualified": True}, exclusive=True)
    elif drift == "source":
        host.script.write_bytes(b"foreign script")
    elif drift == "retained":
        (host.package / "ops/host-setup/mac-mini/notification_channels.py").write_bytes(b"foreign")
    elif drift == "config":
        host.config.write_bytes(b"foreign config")
    elif drift == "unit":
        host.fields["ExecStart"] += " foreign-command"
        host.fields["DropInPaths"] = "/foreign.service"
    elif drift == "normal_invocation":
        host.fields["InvocationID"] = "0" * 32
    elif drift == "malformed_incident":
        host.incident.write_bytes(b'{"status":"down"}')
    elif drift == "writer":
        monkeypatch.setattr(
            operation.pwd,
            "getpwall",
            lambda: [SimpleNamespace(pw_gid=os.getegid(), pw_uid=os.geteuid() + 1)],
        )
    else:
        lock = operation._resource_lock()
    try:
        with pytest.raises((operation.OperationFailure, FileNotFoundError)):
            operation.remote_entry("prepare", request, programs=carrier._programs())
        assert host.events == [] and host.supervisor is None
        assert not (host.operation_root / ("a" * 32)).exists()
        assert not (host.operation_root / "rendering-successor.json").exists()
    finally:
        if lock is not None:
            os.close(lock)


@pytest.mark.parametrize(
    "failure", ["interrupt_after_replace", "latest_ack_then_failed_cycles", "lost_start_ack"]
)
def test_successor_unknown_and_recovery_preserve_latest_incident(
    successor_host, monkeypatch, failure
):
    host = successor_host
    interrupted = False
    latest = {"bytes": host.incident.read_bytes()}

    def phase_hook(phase, _module):
        nonlocal interrupted
        if phase == "replaced" and failure == "interrupt_after_replace" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("finite helper interrupted after durable replacement")

    transport = bind_successor_carrier(host, monkeypatch, phase_hook=phase_hook)
    if failure == "latest_ack_then_failed_cycles":

        def latest_ack(count):
            if count == 1:
                host.set_incident("33333333-3333-4333-8333-333333333333")
                latest["bytes"] = host.incident.read_bytes()

        host.after_start = latest_ack
        host.journal_rows = "malformed final-cycle evidence"
    if failure == "lost_start_ack":
        command = host.command

        def lose_ack(argv, **kwargs):
            result = command(argv, **kwargs)
            if argv[:3] == ["/usr/bin/systemctl", "start", operation.UNIT]:
                raise operation.OperationFailure("lost_successor_start_ack", unknown=True)
            return result

        host.command = lose_ack
        host.bind(operation)
    result = carrier.run("lease-abcdef", "a" * 32, rendering_successor=True)
    if failure == "interrupt_after_replace":
        assert result["status"] == "unknown" and host.events == ["stop"]
        host.set_incident("44444444-4444-4444-8444-444444444444")
        latest["bytes"] = host.incident.read_bytes()
        result = carrier.run("lease-abcdef", "a" * 32, "reconcile")
        assert result["status"] == "rolled_back", result
        assert host.events == ["stop", "start"]
        assert transport.calls.count("prepare") == transport.calls.count("authorize") == 1
    elif failure == "latest_ack_then_failed_cycles":
        assert result["status"] == "rolled_back", result
        assert host.events == ["stop", "start", "stop", "start"]
    else:
        assert result["status"] == "unknown", result
        previous = host.events[:]
        again = carrier.run("lease-abcdef", "a" * 32, "reconcile")
        assert again["status"] == "unknown" and host.events == previous
    assert host.incident.read_bytes() == latest["bytes"]
    assert sha(host.script.read_bytes()) == (
        operation.RENDERING_SCRIPT_SHA256
        if failure == "lost_start_ack"
        else operation.NEW_SCRIPT_SHA256
    )
    assert_original_preserved(host)


def test_successor_and_pinned_legacy_paths_share_the_physical_lock(successor_host, monkeypatch):
    host = successor_host
    pinned = ModuleType("pinned_legacy_writer")
    source = carrier._git_bytes(
        "show", "e0b5a1b0d3226247fc4f5469b1285844da13427e:scripts/probe_upgrade_operation.py"
    )
    exec(compile(source, "<pinned-legacy-writer>", "exec"), pinned.__dict__)
    host.bind(pinned)
    attempts = []

    def queued_writers(phase, _module):
        if phase != "quiescent":
            return
        legacy = {
            **host.legacy_request,
            "packet": {**host.legacy_request["packet"], "operation": "d" * 32},
        }
        for module, request in ((pinned, legacy), (operation, successor_request(host, "e" * 32))):
            with pytest.raises(
                module.OperationFailure, match="probe_resource_owned_by_original_operation"
            ):
                module.remote_entry("prepare", request, programs=carrier._programs())
            attempts.append(request["packet"]["operation"])
        assert not (host.operation_root / ("d" * 32)).exists()
        assert not (host.operation_root / ("e" * 32)).exists()

    bind_successor_carrier(host, monkeypatch, phase_hook=queued_writers)
    result = carrier.run("lease-abcdef", "a" * 32, rendering_successor=True)
    assert result["status"] == "committed", result
    assert attempts == ["d" * 32, "e" * 32] and host.events == ["stop", "start"]
    assert_original_preserved(host)


@pytest.mark.parametrize(
    "corruption", ["partial_admission", "selector_digest", "normal_replaced", "lock_replaced"]
)
def test_successor_authorization_requalifies_persisted_admission(
    successor_host, monkeypatch, corruption
):
    host = successor_host
    request = successor_request(host)
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    root = host.operation_root / ("a" * 32)
    if corruption == "partial_admission":
        admission = operation._metadata_read(root / "admission.json")
        del admission["current_state"]["identity"]
        operation._metadata_write(root / "admission.json", admission)
    elif corruption == "selector_digest":
        pointer = operation._metadata_read(host.operation_root / "rendering-successor.json")
        pointer["admission_sha256"] = "0" * 64
        operation._metadata_write(host.operation_root / "rendering-successor.json", pointer)
    elif corruption == "normal_replaced":
        host.set_active("8" * 32, 800)
    else:
        lock = host.operation_root / "resource.lock"
        lock.rename(host.operation_root / "retained-resource.lock")
        host.write(lock, b"")
    with pytest.raises(operation.OperationFailure):
        operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    assert not (root / "go.json").exists() and host.events == []
    # A lost parent handle does not replay prepare or affect the probe. The
    # finite helper republishes its exact handle and expires without go.json.
    (root / "handle.json").unlink()
    clock = {"value": time.monotonic()}

    def bounded_clock():
        clock["value"] += 31.0
        return clock["value"]

    monkeypatch.setattr(
        operation, "time", SimpleNamespace(monotonic=bounded_clock, sleep=lambda _: None)
    )
    monkeypatch.setenv("INVOCATION_ID", host.supervisor["InvocationID"])
    assert operation.worker_main("a" * 32) == 78
    host.finish_supervisor()
    result = operation.remote_entry("status", request)
    assert result["status"] == "refused" and result["failure"] == "authorization_not_received"
    assert result["supervisor"]["reaped"] and host.events == []
    assert_original_preserved(host)


@pytest.mark.parametrize(
    "changed",
    ["live_issue", "source_issue", "live_body", "target_source", "before_manifest", "after_bytes"],
)
def test_successor_rejects_alternate_authority_or_source_before_host_contact(
    successor_host, monkeypatch, changed
):
    request = successor_request(successor_host)
    if changed in {"live_issue", "source_issue"}:
        request["packet"]["installation_authority"]["issue"] = (
            9000 if changed == "live_issue" else 6475
        )
    elif changed == "live_body":
        request["packet"]["installation_authority"]["body_sha256"] = "0" * 64
    elif changed == "target_source":
        request["packet"]["source_merge"] = operation.SOURCE_MERGE
    elif changed == "before_manifest":
        request["before_manifest"][operation.SCRIPT_REL]["sha256"] = operation.OLD_SCRIPT_SHA256
    else:
        request["new_base64"] = request["old_base64"]
    monkeypatch.setattr(
        operation,
        "_safe_command",
        lambda *_args, **_kwargs: pytest.fail("host contact before fixed binding"),
    )
    with pytest.raises(operation.OperationFailure):
        operation.remote_entry("prepare", request, programs=carrier._programs())
    assert not (successor_host.operation_root / "rendering-successor.json").exists()
    assert successor_host.events == []


@pytest.mark.parametrize(
    "drift",
    [
        None,
        "source_lease",
        "foreign_holder",
        "expired",
        "released",
        "blocked",
        "body",
        "session",
        "registration",
        "duplicate_worktree",
        "dirty",
        "program",
    ],
)
def test_successor_carrier_authenticates_fixed_live_claim_and_actual_session(monkeypatch, drift):
    from scripts import agent_worktree

    body = "synthetic exact installation contract for the one fixed transition"
    body_sha = sha(body.encode())
    monkeypatch.setattr(operation, "RENDERING_INSTALLATION_BODY_SHA256", body_sha)
    monkeypatch.setattr(carrier, "RENDERING_INSTALLATION_BODY_SHA256", body_sha)
    session = "11111111-1111-4111-8111-111111111111"
    branch = "codex/issue-6476-probe-rendering-install"
    monkeypatch.setenv("CODEX_THREAD_ID", "2" * 36 if drift == "session" else session)
    monkeypatch.setenv("CODEX_SESSION_ID", "inherited-root-is-not-the-owner")
    registry = {
        str(ROOT): {
            "owner": session,
            "branch": branch,
            "status": "active",
            "expires_at": time.time() + 3600,
            "generation": "6" * 32,
        }
    }
    if drift == "registration":
        registry[str(ROOT)]["branch"] = "codex/foreign"
    if drift == "duplicate_worktree":
        registry["/synthetic/other-worktree"] = dict(registry[str(ROOT)])
    monkeypatch.setattr(agent_worktree, "load_lifecycle_records", lambda _: registry)
    head = "8" * 40

    def git_port(*args):
        return {
            ("branch", "--show-current"): branch,
            ("status", "--porcelain"): "M script" if drift == "dirty" else "",
            ("rev-parse", "HEAD"): head,
        }[args]

    monkeypatch.setattr(carrier, "_git", git_port)

    def committed_port(_show, ref):
        path = ROOT / ref.partition(":")[2]
        return b"foreign committed program" if drift == "program" else path.read_bytes()

    monkeypatch.setattr(carrier, "_git_bytes", committed_port)
    task = {
        "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-6476",
        "repo": "RasmusTho/agentic-pkm-mvp",
        "issue_number": 6476,
        "status": "claimed",
        "claimed_by": "synthetic-current-holder",
        "lease_id": "lease-abcdef",
    }
    lease = {
        "lease_id": "lease-abcdef",
        "resource": "issue:6476",
        "holder": task["claimed_by"],
        "expires_at": "2099-01-01T00:00:00Z",
        "released_at": None,
    }
    issue = {
        "body": body,
        "state": "OPEN",
        "labels": [{"name": name} for name in ("type:task", "prio:high", "agent:in-progress")],
    }
    if drift == "source_lease":
        task.update(issue_number=6475, task_id="github-RasmusTho--agentic-pkm-mvp-issue-6475")
        lease["resource"] = "issue:6475"
    elif drift == "foreign_holder":
        lease["holder"] = "foreign"
    elif drift == "expired":
        lease["expires_at"] = "2000-01-01T00:00:00Z"
    elif drift == "released":
        lease["released_at"] = "2026-01-01T00:00:00Z"
    elif drift == "blocked":
        issue["labels"][-1] = {"name": "agent:blocked"}
    elif drift == "body":
        issue["body"] += " changed"
    calls = []

    def claim_port(argv, **_kwargs):
        calls.append(argv)
        value = (
            {"ok": True, "task": task, "lease": lease}
            if argv[1:3] == ["-m", "app.dispatcher"]
            else issue
        )
        return SimpleNamespace(returncode=0, stderr=b"", stdout=json.dumps(value).encode())

    monkeypatch.setattr(carrier, "_bounded_process", claim_port)
    if drift:
        with pytest.raises((carrier.CarrierRefusal, operation.OperationFailure)):
            carrier._lease_readback("lease-abcdef", rendering_successor=True)
    else:
        result = carrier._lease_readback("lease-abcdef", rendering_successor=True)
        authority = result["installation_authority"]
        assert authority["issue"] == 6476 and authority["holder"] == task["claimed_by"]
        assert authority["session"] == session and authority["source_head"] == head
        assert authority["branch"] == branch and authority["worktree"] == str(ROOT)
        assert authority["body_sha256"] == body_sha
    assert all("issue-6475" not in arg for argv in calls for arg in argv)


@pytest.mark.parametrize(
    "phase,events,new_script",
    [
        ("stop_intent", [], False),
        ("replace_intent", ["stop"], False),
        ("start_intent", ["stop"], True),
        ("recovery_stop_intent", ["stop", "start"], True),
        ("rollback_replace_intent", ["stop", "start", "stop"], True),
        ("recovery_start_intent", ["stop", "start", "stop"], False),
    ],
)
def test_successor_rechecks_resource_custody_at_each_effect(
    successor_host, monkeypatch, phase, events, new_script
):
    host = successor_host
    if "recovery" in phase or phase == "rollback_replace_intent":
        host.journal_rows = "injected unqualified cycle proof"

    def lose_selection(observed, module):
        if observed == phase:
            pointer = host.operation_root / "rendering-successor.json"
            value = module._metadata_read(pointer)
            value["request_sha256"] = "9" * 64
            module._metadata_write(pointer, value)

    bind_successor_carrier(host, monkeypatch, phase_hook=lose_selection)
    result = carrier.run("lease-abcdef", "a" * 32, rendering_successor=True)
    assert result["status"] == "unknown", result
    assert host.events == events
    assert sha(host.script.read_bytes()) == (
        operation.RENDERING_SCRIPT_SHA256 if new_script else operation.NEW_SCRIPT_SHA256
    )
    assert_original_preserved(host)


def test_real_operation_keeps_incident_source_closure_and_new_incarnation(host):
    assert operation.time is carrier.time and operation.time is not time
    incident = host.incident.read_bytes()
    result = host.run()
    assert result["status"] == "committed", result
    assert host.events == ["stop", "start"]
    assert host.script.read_bytes() == host.new.files[operation.SCRIPT_REL]
    assert host.incident.read_bytes() == incident
    assert result["normal_cycles"]["continuation_branch"] == "continued_incident_suppressed"
    assert result["old_invocation_sha256"] != result["new_invocation_sha256"]
    assert host.sleeps[0] == 125.0
    assert result["old_import_support"]["exit"] == result["candidate_child_support"]["exit"] == 0
    assert not list(host.package.rglob("*.pyc"))  # No installed-package import during preflight.


def test_real_orchestration_refuses_incarnation_drift_before_stop(host):
    def drift(phase):
        if phase == "qualified":
            host.set_active("f" * 32, 800)

    host.on_phase = drift
    result = host.run()
    assert result["status"] == "refused", result
    assert host.events == []
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]


def test_foreign_source_before_cutover_never_gets_recovery_start(host):
    def drift(phase):
        if phase == "replace_intent":
            host.script.write_bytes(b"foreign unreviewed source")

    host.on_phase = drift
    result = host.run()
    assert result["status"] == "unknown", result
    assert result["recovery_failure"] == "foreign_source_during_recovery"
    assert host.events == ["stop"]
    assert host.script.read_bytes() == b"foreign unreviewed source"


def test_rollback_captures_newest_ack_after_own_quiescence(host):
    newest = "22222222-2222-4222-8222-222222222222"
    host.after_start = lambda count: host.set_incident(newest) if count == 1 else None
    host.journal_rows = "unbound non-JSON journal"
    result = host.run()
    assert result["status"] == "rolled_back", result
    assert host.events == ["stop", "start", "stop", "start"]
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]
    assert json.loads(host.incident.read_bytes())["correlation_id"] == newest
    assert host.fields["ActiveState"] == "active"


def test_foreign_package_consumer_outside_named_unit_is_refused(host):
    host.process(999, 1, 999, "/system.slice/another.service", [sys.executable, host.script])
    result = host.run()
    assert result["failure"] == "additional_package_consumer"
    assert host.events == []


def test_old_new_invocation_equality_cannot_commit(host):
    host.reuse_invocation = True
    result = host.run()
    assert result["status"] != "committed"
    assert result["failure"] == "old_invocation_reused"


def test_invocation_filter_and_completed_recovery_are_enforced(host):
    old = operation._active_identity(operation._unit_fields())
    before = operation._incident_snapshot()
    host.journal_rows = host.records(invocation="f" * 32)
    with pytest.raises(operation.OperationFailure, match="foreign_journal_invocation"):
        operation._normal_cycles(old, before, sleep=lambda _: None)
    host.journal_rows = host.records(["probe ok: readyz=ok health=ok heartbeat=ok"] * 2)
    with pytest.raises(operation.OperationFailure, match="normal_cycles_unproven"):
        operation._normal_cycles(old, before, sleep=lambda _: None)


def test_recovery_confirmation_finishes_healthy_cycle_before_commit(host):
    identity = operation._active_identity(operation._unit_fields())
    before = operation._incident_snapshot()
    host.journal_rows = host.records(
        [
            "probe ok: readyz=ok health=ok heartbeat=ok",
            "discord webhook push confirmed: 200",
            "probe-recovered alert sent; outage state cleared: environment=prod",
            "probe ok: readyz=ok health=ok heartbeat=ok",
        ]
    )
    host.incident.unlink()
    result = operation._normal_cycles(identity, before, sleep=lambda _: None)
    assert result["completed_cycles"] == 2
    assert result["continuation_branch"] == "recovered_preserved_incident"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("_PID", "999", "foreign_journal_process"),
        ("_TRANSPORT", "journal", "foreign_journal_stream"),
        ("_SYSTEMD_CGROUP", "/system.slice/foreign.service", "foreign_journal_stream"),
        ("_STREAM_ID", "unbound", "foreign_journal_stream"),
    ],
)
def test_inherited_journal_peer_requires_exact_transport_and_lineage(host, field, value, reason):
    identity = operation._active_identity(operation._unit_fields())
    rows = [json.loads(line) for line in host.records().splitlines()]
    assert all(row["_PID"] == identity["pid"] for row in rows)
    for row in rows:
        row[field] = value
    host.journal_rows = "\n".join(json.dumps(row) for row in rows)
    with pytest.raises(operation.OperationFailure, match=reason):
        operation._normal_cycles(identity, operation._incident_snapshot())
    assert host.events == []


def test_normal_child_cannot_use_an_unrelated_journal_socket(host):
    descriptor = host.proc / "101/fd/2"
    descriptor.unlink()
    descriptor.symlink_to("socket:[99999]")
    result = host.run()
    assert result["status"] == "refused"
    assert result["failure"] == "normal_journal_stream_lineage"
    assert host.events == []


def test_completed_cycles_cannot_mix_journal_streams(host):
    identity = operation._active_identity(operation._unit_fields())
    rows = [json.loads(line) for line in host.records().splitlines()]
    rows[1]["_STREAM_ID"] = "8" * 32
    host.journal_rows = "\n".join(json.dumps(row) for row in rows)
    with pytest.raises(operation.OperationFailure, match="journal_stream_changed"):
        operation._normal_cycles(identity, operation._incident_snapshot())


@pytest.mark.parametrize("attribution", ["launcher", "child"])
def test_actual_systemd255_completed_rows_bind_only_normal_producer_lineage(host, attribution):
    """Replay observed metadata; normalize only message date and opaque cursors.

    Actual same-handle capture SHA967fc6f12bec595d965d2e2914759f304bef8d6dd549b07b71fb5bf446d3c516:
    systemd255.4 attributes these inherited-stderr rows to the normal child.
    The launcher variant retains the documented original-peer control.
    """
    main, child = 2849303, 2849343
    invocation = "7bb2d73939a0470ea9fe9adc13a74a3e"
    cgroup = r"/system.slice/system-yggdrasil\x2dhost\x2dprobe.slice/" + operation.UNIT
    host.set_active(invocation, main)
    environment = (host.proc / str(main + 1) / "environ").read_bytes()
    shutil.rmtree(host.proc / str(main + 1))
    host.fields.update(ControlGroup=cgroup, ExecMainStartTimestampMonotonic="4086739117159")
    host.process(
        main,
        1,
        408673910,
        cgroup,
        [
            sys.executable,
            host.package / "ops/host-setup/linux/host_probe_launcher.py",
            "--channel",
            "prod",
        ],
    )
    host.process(
        child, main, 408674026, cgroup, [sys.executable, host.script, "--loop"], environment
    )
    for pid in (main, child):
        descriptor = host.proc / str(pid) / "fd/2"
        descriptor.parent.mkdir(mode=0o700, exist_ok=True)
        if descriptor.is_symlink():
            descriptor.unlink()
        descriptor.symlink_to("socket:[332414554]")
    host.write(host.cgroup / cgroup.lstrip("/") / "cgroup.procs", f"{main}\n{child}\n".encode())
    host.journal_rows = "\n".join(
        json.dumps(
            {
                "MESSAGE": "2026-10-29 16:00:00,000 [prod-probe] INFO probe-down detected but outage already recorded; suppressing duplicate alert. environment=prod",
                "_PID": str(child if attribution == "child" else main),
                "_SYSTEMD_INVOCATION_ID": invocation,
                "_SYSTEMD_CGROUP": cgroup,
                "_TRANSPORT": "stdout",
                "_STREAM_ID": "bdac034dc61749258f1b1059f9457fc0",
                "__MONOTONIC_TIMESTAMP": str(stamp),
                "__CURSOR": "captured-cursor-" + str(index),
            }
        )
        for index, stamp in enumerate((4086740900365, 4086801037599))
    )
    identity = operation._active_identity(operation._unit_fields())
    result = operation._normal_cycles(identity, operation._incident_snapshot())
    assert result["completed_cycles"] == 2
    assert result["continuation_branch"] == "continued_incident_suppressed"
    assert result["journal_peer"] == (
        "normal_child_inherited_stderr"
        if attribution == "child"
        else "normal_launcher_inherited_stderr"
    )
    assert host.events == []


def test_completed_cycles_cannot_mix_launcher_and_child_attributions(host):
    identity = operation._active_identity(operation._unit_fields())
    rows = [json.loads(line) for line in host.records().splitlines()]
    rows[1]["_PID"] = identity["probe_child"]["pid"]
    host.journal_rows = "\n".join(json.dumps(row) for row in rows)
    with pytest.raises(operation.OperationFailure, match="journal_producer_changed"):
        operation._normal_cycles(identity, operation._incident_snapshot())
    assert host.events == []


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("drift", ["source", "configuration", "incident", "write_domain"])
def test_start_boundary_requalifies_after_actual_durable_intent(host, monkeypatch, recovery, drift):
    if recovery:
        host.journal_rows = "injected verification failure"
    phase = "recovery_start_intent" if recovery else "start_intent"
    newest = "33333333-3333-4333-8333-333333333333"
    injected = False
    started_hashes = []
    command = host.command

    def start_port(argv, **kwargs):
        if argv[:3] == ["/usr/bin/systemctl", "start", operation.UNIT]:
            started_hashes.append(sha(host.script.read_bytes()))
        return command(argv, **kwargs)

    def mutate_at_intent(value):
        nonlocal injected
        if value != phase:
            return
        injected = True
        if drift == "source":
            host.script.write_bytes(b"foreign source after the durable start intent\n")
        elif drift == "configuration":
            host.config.write_bytes(b"foreign configuration after intent\n")
        elif drift == "incident":
            host.set_incident(newest)
        else:
            monkeypatch.setattr(operation.os, "listxattr", lambda _: ["system.posix_acl_access"])

    monkeypatch.setattr(operation, "_safe_command", start_port)
    host.on_phase = mutate_at_intent
    result = host.run()
    assert injected and result["status"] in {"unknown", "rolled_back"}, result
    # A normal incident drift may restore old code using a newly captured,
    # preserved quiescent incident; no start crosses the failed guard.
    assert started_hashes == (
        [operation.NEW_SCRIPT_SHA256]
        if recovery
        else [operation.OLD_SCRIPT_SHA256]
        if drift == "incident"
        else []
    )
    if drift == "incident":
        assert json.loads(host.incident.read_bytes())["correlation_id"] == newest


def test_lost_start_ack_never_adopts_or_stops_a_foreign_incarnation(host, monkeypatch):
    command = host.command
    stopped = []

    def lose_ack_then_foreign(argv, **kwargs):
        if argv[:3] == ["/usr/bin/systemctl", "stop", operation.UNIT]:
            stopped.append(host.fields["InvocationID"])
        result = command(argv, **kwargs)
        if argv[:3] == ["/usr/bin/systemctl", "start", operation.UNIT]:
            host.set_active("9" * 32, 900)
            raise operation.OperationFailure("lost_start_ack_then_foreign", unknown=True)
        return result

    monkeypatch.setattr(operation, "_safe_command", lose_ack_then_foreign)
    result = host.run()
    assert result["status"] == "unknown", result
    assert result["recovery_failure"] == "original_start_ownership_unproven"
    assert stopped == ["c" * 32] and host.events == ["stop", "start"]
    assert host.fields["InvocationID"] == "9" * 32


def test_timestamp_cache_staleness_compiles_source_without_deleting_cache(host):
    import importlib.util

    cache = Path(importlib.util.cache_from_source(str(host.script)))
    raw = importlib.util.MAGIC_NUMBER + b"\0" * 12 + b"retained derived cache"
    host.write(cache, raw)
    result = operation._cache_inventory()
    assert result["prod_probe.py"]["loader_action"] == "compile_current_source"
    assert cache.read_bytes() == raw
    host.write(cache, importlib.util.MAGIC_NUMBER + (1).to_bytes(4, "little") + b"\0" * 8)
    with pytest.raises(operation.OperationFailure, match="unchecked_cache"):
        operation._cache_inventory()


def test_streaming_bound_and_deadline_reap_actual_private_children(tmp_path):
    before = time.monotonic()
    with pytest.raises(operation.OperationFailure, match="process_output_bound"):
        operation._bounded_process(
            [sys.executable, "-I", "-c", "import os,time;os.write(1,b'x'*65536);time.sleep(60)"],
            timeout=5,
            limit=4096,
            environment={},
        )
    with pytest.raises(operation.OperationFailure, match="process_deadline"):
        operation._bounded_process(
            [sys.executable, "-I", "-c", "import time;time.sleep(60)"],
            timeout=0.05,
            limit=4096,
            environment={},
        )
    assert time.monotonic() - before < 4


def test_supervisor_original_handle_cross_id_guard_and_no_prepare_replay(host):
    programs = carrier._programs()
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    first = operation.remote_entry("prepare", request, programs=programs)
    replay = operation.remote_entry("prepare", request, programs=programs)
    assert first["handle"] == replay["handle"]
    other = carrier._request(
        "e" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    with pytest.raises(operation.OperationFailure, match="original_operation_unresolved"):
        operation.remote_entry("prepare", other, programs=programs)
    assert not (host.operation_root / ("e" * 32)).exists()
    assert host.events == []


def test_actual_finite_worker_entry_and_terminal_cgroup_reap(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    assert operation.worker_main("a" * 32) == 0
    assert operation.remote_entry("status", request)["status"] == "pending"
    host.finish_supervisor()
    receipt = operation.remote_entry("status", request)
    assert receipt["status"] == "committed", receipt
    assert receipt["supervisor"]["reaped"] is True
    assert receipt["supervisor"]["cgroup_empty"] is True
    assert host.events == ["stop", "start"]


def test_carrier_unknown_preserves_original_handle_and_follow_does_not_apply(host, monkeypatch):
    monkeypatch.setattr(
        carrier, "_lease_readback", lambda _: {"lease_expires_at": "2099-01-01T00:00:00Z"}
    )
    lost = {"once": False}
    requests = []

    def transport(payload):
        source = payload.decode()
        requests.append(source)
        # Execute the actual assembled remote program. Bind only this fixture's
        # filesystem/host effect ports before its production remote_entry call.
        source = source.replace("try:\n    _result=", "_test_host.bind(_op)\ntry:\n    _result=", 1)
        namespace = {"_test_host": host}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(source, "<actual-remote-payload>", "exec"), namespace)
        value = json.loads(output.getvalue())
        if "remote_entry('authorize'" in source and not lost["once"]:
            lost["once"] = True
            raise carrier.CarrierUnknown("lost authorization acknowledgement")
        if "remote_entry('status'" in source and host.supervisor["ActiveState"] == "active":
            module = namespace["_op"]
            monkeypatch.setenv("INVOCATION_ID", "b" * 32)
            module.worker_main("a" * 32)
            host.finish_supervisor()
            return module.remote_entry("status", carrier._read_record("a" * 32)["request"])
        return value

    monkeypatch.setattr(carrier, "_ssh", transport)
    uncertain = carrier.run("lease-c186483a", "a" * 32)
    assert uncertain["status"] == "unknown"
    assert uncertain["operation"] == "a" * 32 and uncertain["handle"]
    followed = carrier.run("lease-c186483a", "a" * 32, "follow")
    assert followed["status"] == "committed", followed
    assert host.events == ["stop", "start"]
    with pytest.raises(carrier.CarrierRefusal, match="already exists"):
        carrier.run("lease-c186483a", "a" * 32)
    assert sum("remote_entry('prepare'" in text for text in requests) == 1
    assert sum("remote_entry('authorize'" in text for text in requests) == 1


def test_interrupted_original_worker_reconciles_exact_phase_once(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    original_write = operation._metadata_write
    crashed = {"once": False}

    def crash_after_durable_cutover(path, value, **kwargs):
        original_write(path, value, **kwargs)
        if path.name == "phase.json" and value.get("phase") == "replaced" and not crashed["once"]:
            crashed["once"] = True
            raise KeyboardInterrupt("finite injected worker interruption")

    monkeypatch.setattr(operation, "_metadata_write", crash_after_durable_cutover)
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main("a" * 32)
    assert host.script.read_bytes() == host.new.files[operation.SCRIPT_REL]
    assert host.events == ["stop"]
    host.finish_supervisor()
    interrupted = operation.remote_entry("status", request)
    assert interrupted["status"] == "unknown" and interrupted["supervisor"]["reaped"]
    other = carrier._request(
        "e" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    with pytest.raises(operation.OperationFailure, match="original_operation_unresolved"):
        operation.remote_entry("prepare", other, programs=carrier._programs())
    host.set_incident("33333333-3333-4333-8333-333333333333")
    pending = operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert pending["status"] == "pending"
    operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert host.supervisor_starts == 1
    monkeypatch.setenv("INVOCATION_ID", "f" * 32)
    operation.worker_main("a" * 32)
    host.finish_supervisor()
    result = operation.remote_entry("status", request)
    assert result["status"] == "rolled_back", result
    assert result["supervisor"]["reaped"] and result["supervisor"]["reconciliation"]
    assert host.events == ["stop", "start"]
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]
    assert (
        json.loads(host.incident.read_bytes())["correlation_id"]
        == "33333333-3333-4333-8333-333333333333"
    )
    assert (host.operation_root / ("a" * 32) / "result.json").exists()


@pytest.mark.parametrize(
    "orphan_generation,collision",
    [
        (None, None),
        (1, None),
        (2, None),
        (1, "foreign"),
        (2, "foreign"),
        (1, "malformed"),
        (2, "malformed"),
        (1, "scalar_alias"),
        (2, "scalar_alias"),
        (1, "nested_bool"),
        (2, "nested_bool"),
        (1, "nested_float"),
        (2, "nested_float"),
    ],
)
def test_interrupted_reconciliation_continues_latest_phase_after_reap(
    host, monkeypatch, orphan_generation, collision
):
    value = "a" * 32
    request = carrier._request(
        value, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    write = operation._metadata_write

    def interrupt_original(path, document, **kwargs):
        write(path, document, **kwargs)
        if path.name == "phase.json" and document.get("phase") == "replaced":
            raise KeyboardInterrupt("original worker interruption after durable cutover")

    monkeypatch.setattr(operation, "_metadata_write", interrupt_original)
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main(value)
    host.finish_supervisor()
    monkeypatch.setattr(operation, "_metadata_write", write)
    original_status = operation.remote_entry("status", request)
    assert original_status["status"] == "unknown" and original_status["supervisor"]["reaped"]
    root = host.operation_root / value
    original_phase = (root / "phase.json").read_bytes()
    original_result = (root / "result.json").read_bytes()
    host.set_incident("33333333-3333-4333-8333-333333333333")
    newest = host.incident.read_bytes()
    foreign = root / "foreign-observation.json"
    foreign.write_bytes(b"retained independent evidence\n")
    cache = host.script.parent / "__pycache__/prod_probe.cpython-313.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"latest cache bytes remain untouched\n")

    def continuation(generation):
        if generation != orphan_generation:
            return operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
        before = {path: path.read_bytes() for path in root.glob("*.json")}
        starts = host.supervisor_starts

        def interrupt_permission(path, document, **kwargs):
            write(path, document, **kwargs)
            if path.name == f"reconcile-{generation}.json":
                raise OSError("lost ACK after durable permission and before selector")

        monkeypatch.setattr(operation, "_metadata_write", interrupt_permission)
        with pytest.raises(OSError, match="before selector"):
            operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
        monkeypatch.setattr(operation, "_metadata_write", write)
        assert host.supervisor_starts == starts and host.events == ["stop"]
        permission = root / f"reconcile-{generation}.json"
        if collision == "foreign":
            foreign_record = json.loads(permission.read_bytes())
            foreign_record["request_sha256"] = "9" * 64
            permission.write_bytes(json.dumps(foreign_record).encode())
        elif collision == "malformed":
            permission.write_bytes(b"[unqualified foreign metadata\n")
        elif collision:
            altered = json.loads(permission.read_bytes())
            if collision == "scalar_alias":
                altered["generation"] = True if generation == 1 else float(generation)
            elif collision == "nested_bool":
                assert altered["context"]["old_identity"]["http_children_observed"] == 0
                altered["context"]["old_identity"]["http_children_observed"] = False
            else:
                altered["context"]["stop_intent_usec"] = float(
                    altered["context"]["stop_intent_usec"]
                )
            # Python value equality conflates these distinct JSON scalar types.
            assert altered == json.loads(permission.read_bytes())
            permission.write_bytes(operation._json_bytes(altered))
        preserved = permission.read_bytes()
        if collision:
            for _ in range(2):
                with pytest.raises(
                    operation.OperationFailure, match="reconciliation_permission_collision"
                ) as failed:
                    operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
                assert failed.value.unknown
            assert host.supervisor_starts == starts and host.events == ["stop"]
            result = None
        else:
            result = operation.remote_entry(
                "reconcile", request, expected_handle=prepared["handle"]
            )
            # Follow never starts another helper while this exact one is live.
            operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
            assert host.supervisor_starts == starts + 1
        assert permission.read_bytes() == preserved
        assert all(
            path.read_bytes() == raw
            for path, raw in before.items()
            if path.name != "reconcile.json"
        )
        if collision and root / "reconcile.json" in before:
            assert (root / "reconcile.json").read_bytes() == before[root / "reconcile.json"]
        if collision and root / "reconcile.json" not in before:
            assert not (root / "reconcile.json").exists()
        assert host.incident.read_bytes() == newest
        assert cache.read_bytes() == b"latest cache bytes remain untouched\n"
        assert foreign.read_bytes() == b"retained independent evidence\n"
        return result

    if continuation(1) is None:
        return
    replace = operation.os.replace
    renames = []

    def lose_reverse_rename_ack(source, destination, **kwargs):
        result = replace(source, destination, **kwargs)
        if destination == "prod_probe.py":
            renames.append(destination)
            raise OSError("lost acknowledgement after the actual reverse rename")
        return result

    monkeypatch.setattr(operation.os, "replace", lose_reverse_rename_ack)
    monkeypatch.setenv("INVOCATION_ID", host.supervisor["InvocationID"])
    operation.worker_main(value)
    # An original request cannot continue while its reconciliation helper is
    # still alive, even after that helper has durably reported UNKNOWN.
    pending = operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert pending["status"] == "pending" and host.supervisor_starts == 1
    host.finish_supervisor()
    monkeypatch.setattr(operation.os, "replace", replace)
    stopped = operation.remote_entry("status", request)
    assert stopped["status"] == "unknown" and stopped["supervisor"]["reaped"]
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]
    assert host.fields["ActiveState"] == "inactive"
    first_files = {
        name: (root / name).read_bytes()
        for name in (
            "reconcile-1.json",
            "reconcile-1-handle.json",
            "reconcile-1-phase.json",
            "reconcile-1-result.json",
        )
    }
    assert json.loads(first_files["reconcile-1-phase.json"])["phase"] == "rollback_replace_intent"
    resumed = continuation(2)
    if resumed is None:
        return
    assert resumed["status"] == "pending" and host.supervisor_starts == 2
    operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert host.supervisor_starts == 2
    monkeypatch.setenv("INVOCATION_ID", host.supervisor["InvocationID"])
    operation.worker_main(value)
    host.finish_supervisor()
    complete = operation.remote_entry("status", request)
    assert complete["status"] == "rolled_back", complete
    assert complete["handle"] == prepared["handle"] and complete["supervisor"]["reaped"]
    assert host.events == ["stop", "start"] and renames == ["prod_probe.py"]
    assert all((root / name).read_bytes() == data for name, data in first_files.items())
    assert (root / "phase.json").read_bytes() == original_phase
    assert (root / "result.json").read_bytes() == original_result
    assert host.incident.read_bytes() == newest
    assert cache.read_bytes() == b"latest cache bytes remain untouched\n"
    assert foreign.read_bytes() == b"retained independent evidence\n"
    operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert host.supervisor_starts == 2 and host.events == ["stop", "start"]


@pytest.mark.parametrize(
    "collision", [None, "scalar_bool", "scalar_float", "nested_bool", "nested_float"]
)
def test_actual_carrier_completes_own_orphan_permission_without_replay(
    host, monkeypatch, collision
):
    value = "a" * 32
    request = carrier._request(
        value, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    handle = prepared["handle"]
    operation.remote_entry("authorize", request, expected_handle=handle)
    write = operation._metadata_write

    def interrupt_original(path, document, **kwargs):
        write(path, document, **kwargs)
        if path.name == "phase.json" and document.get("phase") == "replaced":
            raise KeyboardInterrupt("interrupted original worker")

    monkeypatch.setattr(operation, "_metadata_write", interrupt_original)
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main(value)
    host.finish_supervisor()
    monkeypatch.setattr(operation, "_metadata_write", write)
    carrier._save_record(
        value,
        {
            "request": request,
            "source_head": operation.SOURCE_MERGE,
            "old_archive_sha256": host.old.archive_sha256,
            "handle": handle,
            "authorization_sent": True,
        },
        create=True,
    )
    monkeypatch.setattr(
        carrier, "_lease_readback", lambda _: {"lease_expires_at": "2099-01-01T00:00:00Z"}
    )
    lost = False
    requests = []

    def lose_permission_ack(path, document, **kwargs):
        nonlocal lost
        write(path, document, **kwargs)
        if path.name == "reconcile-1.json" and not lost:
            lost = True
            if collision:
                altered = json.loads(path.read_bytes())
                if collision.startswith("scalar"):
                    altered["generation"] = True if collision == "scalar_bool" else 1.0
                elif collision == "nested_bool":
                    altered["context"]["old_identity"]["http_children_observed"] = False
                else:
                    altered["context"]["stop_intent_usec"] = float(
                        altered["context"]["stop_intent_usec"]
                    )
                assert altered == document
                path.write_bytes(operation._json_bytes(altered))
            raise OSError("durable permission ACK lost before selector")

    def transport(payload):
        code = payload.decode()
        requests.append(code)
        if "remote_entry('status'" in code and host.supervisor_starts:
            monkeypatch.setenv("INVOCATION_ID", host.supervisor["InvocationID"])
            operation.worker_main(value)
            host.finish_supervisor()
        code = code.replace(
            "try:\n    _result=",
            "_private_host.bind(_op)\n_op._metadata_write=_private_write\ntry:\n    _result=",
            1,
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(
                compile(code, "<actual-serialized-carrier>", "exec"),
                {
                    "_private_host": host,
                    "_private_write": lose_permission_ack,
                },
            )
        return json.loads(output.getvalue())

    monkeypatch.setattr(carrier, "_ssh", transport)
    first = carrier.run("lease-c186483a", value, "reconcile")
    assert first["status"] == "unknown" and first["failure"] == "remote_operation_unhandled"
    root = host.operation_root / value
    orphan = (root / "reconcile-1.json").read_bytes()
    assert not (root / "reconcile.json").exists()
    assert carrier._read_record(value)["handle"] == handle and host.events == ["stop"]
    other = carrier._request(
        "e" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    with pytest.raises(operation.OperationFailure, match="original_operation_unresolved"):
        operation.remote_entry("prepare", other, programs=carrier._programs())
    final = carrier.run("lease-c186483a", value, "reconcile")
    if collision:
        assert (
            final["status"] == "unknown"
            and final["failure"] == "reconciliation_permission_collision"
        )
        again = carrier.run("lease-c186483a", value, "reconcile")
        assert (
            again["status"] == "unknown"
            and again["failure"] == "reconciliation_permission_collision"
        )
        assert not (root / "reconcile.json").exists()
        assert host.supervisor_starts == 0 and host.events == ["stop"]
        assert (root / "reconcile-1.json").read_bytes() == orphan
        assert carrier._read_record(value)["handle"] == handle
        assert all("remote_entry('reconcile'" in code for code in requests)
        return
    assert final["status"] == "rolled_back" and final["handle"] == handle
    assert final["supervisor"]["reaped"] and host.events == ["stop", "start"]
    assert (
        host.supervisor_starts == 1
        and host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]
    )
    assert (root / "reconcile-1.json").read_bytes() == orphan
    assert carrier._read_record(value)["handle"] == handle
    assert sum("remote_entry('reconcile'" in code for code in requests) == 2
    assert all(
        "remote_entry('prepare'" not in code and "remote_entry('authorize'" not in code
        for code in requests
    )


@pytest.mark.parametrize("effect", ["stop", "start"])
def test_lost_lifecycle_ack_reconciles_without_replay(host, monkeypatch, effect):
    command = host.command
    lost = {"once": False}

    def lose_after_effect(argv, **kwargs):
        result = command(argv, **kwargs)
        if argv[:3] == ["/usr/bin/systemctl", effect, operation.UNIT] and not lost["once"]:
            lost["once"] = True
            raise operation.OperationFailure("lost_lifecycle_ack", unknown=True)
        return result

    monkeypatch.setattr(operation, "_safe_command", lose_after_effect)
    result = host.run()
    assert result["status"] == ("rolled_back" if effect == "stop" else "unknown"), result
    assert (
        host.script.read_bytes()
        == (host.old if effect == "stop" else host.new).files[operation.SCRIPT_REL]
    )
    assert host.fields["ActiveState"] == "active"
    assert host.events == ["stop", "start"]
    if effect == "start":
        assert result["recovery_failure"] == "original_start_ownership_unproven"


def test_returnless_rename_is_observed_and_compensated_without_apply_replay(host, monkeypatch):
    original = operation.os.replace
    lost = {"once": False}

    def lose_after_rename(source, destination, **kwargs):
        result = original(source, destination, **kwargs)
        if destination == "prod_probe.py" and not lost["once"]:
            lost["once"] = True
            raise OSError("finite lost rename return")
        return result

    monkeypatch.setattr(operation.os, "replace", lose_after_rename)
    result = host.run()
    assert result["status"] == "rolled_back", result
    assert host.events == ["stop", "start"]
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]


def test_foreign_recovery_incarnation_is_not_stopped(host):
    host.journal_rows = "invalid journal"

    def foreign(phase):
        if phase == "recovery_stop_intent":
            host.set_active("9" * 32, 900)

    host.on_phase = foreign
    result = host.run()
    assert result["status"] == "unknown", result
    assert host.events == ["stop", "start"]
    assert host.fields["InvocationID"] == "9" * 32


def test_expired_prepare_has_no_operation_directory_or_probe_effect(host):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="1999-01-01T00:00:00Z"
    )
    with pytest.raises(operation.OperationFailure, match="operation_claim_expired"):
        operation.remote_entry("prepare", request, programs=carrier._programs())
    assert not host.operation_root.exists()
    assert host.events == []


def test_private_binding_metadata_and_retained_file_drift_refuse_before_effect(host):
    host.runtime.chmod(0o775)
    result = host.run()
    assert result["failure"] == "runtime_binding_directory_metadata"
    assert host.events == []
    host.runtime.chmod(0o700)
    (host.package / "ops/host-setup/mac-mini/notification_channels.py").write_bytes(b"foreign")
    result = host.run()
    assert result["failure"] == "public_manifest_mismatch"
    assert host.events == []


def test_reconcile_preserves_unknown_after_unbound_rollback_start(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    host.journal_rows = "injected verification failure"
    command = host.command

    def lose_restoration_ack(argv, **kwargs):
        value = command(argv, **kwargs)
        if argv[:3] == ["/usr/bin/systemctl", "start", operation.UNIT] and host.starts == 2:
            raise operation.OperationFailure("lost_restoration_ack", unknown=True)
        return value

    monkeypatch.setattr(operation, "_safe_command", lose_restoration_ack)
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main("a" * 32)
    host.finish_supervisor()
    status = operation.remote_entry("status", request)
    assert status["status"] == "unknown", status
    assert host.script.read_bytes() == host.old.files[operation.SCRIPT_REL]
    previous_effects = host.events[:]
    reconciled = operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert reconciled["status"] == "unknown", reconciled
    assert reconciled["recovery_failure"] == "original_start_ownership_unproven"
    assert host.supervisor_starts == 0
    assert host.events == previous_effects


def test_unpermitted_restarted_worker_preserves_original_phase(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    operation.remote_entry("prepare", request, programs=carrier._programs())
    phase_path = host.operation_root / ("a" * 32) / "phase.json"
    phase = phase_path.read_bytes()
    host.command(["/usr/bin/systemctl", "start", operation._operation_name("a" * 32)])
    monkeypatch.setenv("INVOCATION_ID", "f" * 32)
    with pytest.raises(operation.OperationFailure, match="worker_replay_or_foreign"):
        operation.worker_main("a" * 32)
    assert phase_path.read_bytes() == phase
    assert host.events == []


def test_local_original_handle_refuses_foreign_directory_and_preserves_collision(host):
    value = {"request": {"packet": {"operation": "a" * 32}}, "handle": None}
    carrier._save_record("a" * 32, value, create=True)
    record_path = carrier._record_path("a" * 32)
    foreign = record_path.with_suffix(".tmp")
    foreign.write_bytes(b"foreign stage evidence")
    with pytest.raises(FileExistsError):
        carrier._save_record("a" * 32, {**value, "handle": {"owned": True}})
    assert foreign.read_bytes() == b"foreign stage evidence"
    assert carrier._read_record("a" * 32)["handle"] is None
    record_path.parent.chmod(0o775)
    with pytest.raises(carrier.CarrierRefusal, match="directory ownership"):
        carrier._read_record("a" * 32)


def test_strict_target_transport_uses_bounded_pipes_and_scrubbed_environment(monkeypatch):
    observed = {}

    def private_port(argv, **kwargs):
        observed.update(argv=argv, **kwargs)
        return SimpleNamespace(
            returncode=0,
            stderr=b"",
            stdout=b'{"schema":"probe_installation.v1","operation":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"pending"}',
        )

    monkeypatch.setattr(carrier, "_bounded_process", private_port)
    receipt = carrier._ssh(b"fixed original request")
    assert receipt["operation"] == "a" * 32
    for option in [
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "ClearAllForwardings=yes",
        "ForwardAgent=no",
        "ControlPath=none",
        "PermitLocalCommand=no",
    ]:
        assert option in observed["argv"]
    assert observed["timeout"] == 30 and observed["limit"] == 1_048_576
    assert set(observed["environment"]) <= {"HOME", "PATH", "SSH_AUTH_SOCK"}
    assert observed["input_bytes"] == b"fixed original request"


def test_worker_publishes_original_handle_and_expires_without_authorization(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    operation.remote_entry("prepare", request, programs=carrier._programs())
    root = host.operation_root / ("a" * 32)
    (root / "handle.json").unlink()  # Parent died before returning/persisting its handle.
    clock = {"value": 0.0}

    def advancing_clock():
        clock["value"] += 31.0
        return clock["value"]

    monkeypatch.setattr(operation.time, "monotonic", advancing_clock)
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    assert operation.worker_main("a" * 32) == 78
    assert (root / "handle.json").exists()
    assert not (root / "go.json").exists()
    host.finish_supervisor()
    result = operation.remote_entry("status", request)
    assert result["status"] == "refused" and result["failure"] == "authorization_not_received"
    assert result["supervisor"]["reaped"] and host.events == []


def test_committed_original_operation_blocks_another_id(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main("a" * 32)
    host.finish_supervisor()
    other = carrier._request(
        "e" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    with pytest.raises(operation.OperationFailure, match="unresolved_or_committed"):
        operation.remote_entry("prepare", other, programs=carrier._programs())
    assert host.events == ["stop", "start"]


def test_altered_original_program_and_unbound_result_never_admit_recovery(host):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    original = host.operation_root / ("a" * 32) / "probe_script_swap_core.py"
    original.write_bytes(b"foreign operation source")
    with pytest.raises(operation.OperationFailure, match="operation_program_changed"):
        operation.remote_entry("reconcile", request, expected_handle=prepared["handle"])
    assert host.events == []


def test_inactive_shared_test_consumer_with_queued_job_refuses_before_stop(host, monkeypatch):
    command = host.command

    def queued_consumer(argv, **kwargs):
        if argv[:2] == ["/usr/bin/systemctl", "list-units"]:
            return (
                operation.UNIT
                + " loaded active running probe\nyggdrasil-host-probe@test.service loaded inactive dead test\n"
            )
        if argv[:3] == ["/usr/bin/systemctl", "show", "yggdrasil-host-probe@test.service"]:
            return "LoadState=loaded\nActiveState=inactive\nMainPID=0\nJob=123\nControlGroup=\n"
        return command(argv, **kwargs)

    monkeypatch.setattr(operation, "_safe_command", queued_consumer)
    result = host.run()
    assert result["failure"] == "additional_consumer_job_or_process"
    assert host.events == []


def test_actual_branch_drift_refuses_before_any_host_or_claim_contact(monkeypatch):
    monkeypatch.setattr(carrier, "_git", lambda *args: "codex/foreign-branch")
    monkeypatch.setattr(
        carrier, "_bounded_process", lambda *args, **kwargs: pytest.fail("unneeded contact")
    )
    with pytest.raises(carrier.CarrierRefusal, match="actual worktree branch"):
        carrier._lease_readback("lease-c186483a")


def test_readonly_original_follow_survives_claim_outage_but_recovery_cannot(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    record = {
        "request": request,
        "source_head": operation.SOURCE_MERGE,
        "old_archive_sha256": carrier.OLD_ARCHIVE_SHA256,
        "handle": None,
        "authorization_sent": True,
    }
    carrier._save_record("a" * 32, record, create=True)

    def unavailable(_):
        raise carrier.CarrierRefusal("claim read unavailable")

    monkeypatch.setattr(carrier, "_lease_readback", unavailable)
    calls = []

    def readonly(payload):
        calls.append(payload)
        assert b"remote_entry('status'" in payload
        return {
            "schema": "probe_installation.v1",
            "operation": "a" * 32,
            "status": "unknown",
            "failure": "original_phase_unresolved",
        }

    monkeypatch.setattr(carrier, "_ssh", readonly)
    followed = carrier.run("lease-c186483a", "a" * 32, "follow")
    assert (
        followed["status"] == "unknown" and followed["carrier"]["current_claim_verified"] is False
    )
    recovery = carrier.run("lease-c186483a", "a" * 32, "reconcile")
    assert (
        recovery["status"] == "unknown"
        and recovery["failure"] == "current_claim_unqualified_for_reconciliation"
    )
    assert len(calls) == 1 and host.events == []


def test_missing_local_original_handle_is_unknown_not_a_failed_effect(host, capsys):
    code = carrier.main(["--lease-id", "lease-c186483a", "--operation", "a" * 32, "--follow"])
    value = json.loads(capsys.readouterr().out)
    assert code == 79 and value["status"] == "unknown"
    assert value["operation"] == "a" * 32 and value["handle"] is None
    assert host.events == []


def test_terminal_result_for_another_operation_is_never_accepted(host, monkeypatch):
    request = carrier._request(
        "a" * 32, "lease-c186483a", host.old, host.new, lease_expires_at="2099-01-01T00:00:00Z"
    )
    prepared = operation.remote_entry("prepare", request, programs=carrier._programs())
    operation.remote_entry("authorize", request, expected_handle=prepared["handle"])
    monkeypatch.setenv("INVOCATION_ID", "b" * 32)
    operation.worker_main("a" * 32)
    host.finish_supervisor()
    result_path = host.operation_root / ("a" * 32) / "result.json"
    result = json.loads(result_path.read_bytes())
    result["operation"] = "e" * 32
    host.write(result_path, json.dumps(result).encode())
    with pytest.raises(operation.OperationFailure, match="terminal_result_binding"):
        operation.remote_entry("status", request)
    assert host.events == ["stop", "start"]
