"""Focused fixed DEV adapter proof. OS files are private; all effects fake."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import probe_dev_outage_operation as target

PUBLIC = Path(__file__).resolve().parents[2]
LIVE_PINS = {
    key: getattr(target, key)
    for key in ("ARCHIVE_SHA256", "ARCHIVE_BYTES", "MANIFEST_SHA256", "SOURCE_HASHES")
}
SOURCE_FILES = (
    "app/__init__.py",
    "app/ops/__init__.py",
    "app/ops/builder_executor_keyring.py",
    "app/ops/builderops_alert_secret.py",
    "app/ops/builderops_probe.py",
    "app/ops/builderops_probe_secret.py",
    "app/ops/builderops_startup.py",
    "app/ops/builderops_vm_rebuild_activation.py",
    "app/ops/bws_control_installation.py",
    "app/ops/bws_installation_admission.py",
    "app/ops/bws_installation_lifecycle.py",
    "app/ops/bws_installation_transaction.py",
    "app/ops/bws_secret_admin.py",
    "app/ops/bws_secret_reader.py",
    "app/ops/bws_token_push.py",
    "app/ops/channel_preflight.py",
    "app/ops/devsystem_vm102_component_inventory.py",
    "app/ops/devui_ckm_snapshot.py",
    "app/ops/devui_component_promotion.py",
    "app/ops/devui_secret.py",
    "app/ops/devui_vm102_runtime_receipts.py",
    "app/ops/ere_real_day_qualification.py",
    "app/ops/heavy_acceptance.py",
    "app/ops/heavy_acceptance_runner.py",
    "app/ops/heimdal_cold_volume.py",
    "app/ops/host_secret_bootstrap.py",
    "app/ops/host_secret_contract.py",
    "app/ops/host_secret_controller.py",
    "app/ops/karakeep_deploy.py",
    "app/ops/karakeep_runtime.py",
    "app/ops/native_journaling_acceptance.py",
    "app/ops/native_journaling_acceptance_runner.py",
    "app/ops/native_journaling_transport.py",
    "app/ops/native_operator_identity_restoration.py",
    "app/ops/native_source_admission.py",
    "app/ops/native_source_bootstrap.py",
    "app/ops/native_source_identity_diagnostics.py",
    "app/ops/native_source_identity_persistence.py",
    "app/ops/native_source_identity_supportable_repair.py",
    "app/ops/native_web_acceptance.py",
    "app/ops/native_web_acceptance_runner.py",
    "app/ops/native_web_daily.py",
    "app/ops/native_web_fixture.py",
    "app/ops/native_web_reports.py",
    "app/ops/native_web_runtime.py",
    "app/ops/pg_acceptance.py",
    "app/ops/pg_acceptance_runner.py",
    "app/ops/postgres_deploy.py",
    "app/ops/postgres_deploy_host.py",
    "app/ops/postgres_deploy_linux.py",
    "app/ops/product_tars_channel_topology.py",
    "app/ops/secret_admin.py",
    "app/ops/tars_qualification.py",
    "app/ops/test_channel_bootstrap.py",
    "app/ops/voice_test_channel_acceptance.py",
    "config/secrets/host_secret_contract.json",
    "config/systemd/yggdrasil-host-probe@.service",
    "ops/host-setup/linux/host_probe_launcher.py",
    "ops/host-setup/mac-mini/notification_channels.py",
    "ops/host-setup/mac-mini/prod_probe.py",
)
_FIXTURE_SOURCE = None


def fixture_source():
    global _FIXTURE_SOURCE
    if _FIXTURE_SOURCE is None:
        import tarfile, io

        files = {name: (PUBLIC / name).read_bytes() for name in SOURCE_FILES}
        directories = sorted(
            {str(parent) for name in files for parent in Path(name).parents if str(parent) != "."}
        )
        document = {
            "schema": "probe_source_archive.v1",
            "source_commit": target.SOURCE_COMMIT,
            "package_paths": list(target.PACKAGE_PATHS),
            "directories": directories,
            "files": {
                name: {"archive_mode": "0o664", "size": len(data), "sha256": target.sha(data)}
                for name, data in files.items()
            },
        }
        raw_manifest = json.dumps(document, sort_keys=True, indent=2).encode() + b"\n"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name in directories:
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                item.mode = 0o775
                archive.addfile(item)
            for name, data in files.items():
                item = tarfile.TarInfo(name)
                item.mode = 0o664
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        raw_archive = buffer.getvalue()
        _FIXTURE_SOURCE = (
            raw_archive,
            raw_manifest,
            {name: target.sha(files[name]) for name in LIVE_PINS["SOURCE_HASHES"]},
        )
    return _FIXTURE_SOURCE


def fixture_program():
    """The entire current entry; only external source-artifact pins are fixtures."""
    raw = Path(target.__file__).read_text()
    archive, manifest, hashes = fixture_source()
    for old, new in (
        (LIVE_PINS["ARCHIVE_SHA256"], target.sha(archive)),
        (LIVE_PINS["MANIFEST_SHA256"], target.sha(manifest)),
        *[(LIVE_PINS["SOURCE_HASHES"][name], value) for name, value in hashes.items()],
    ):
        raw = raw.replace(old, new)
    raw = raw.replace(
        "ARCHIVE_BYTES = " + format(LIVE_PINS["ARCHIVE_BYTES"], "_"),
        "ARCHIVE_BYTES = " + str(len(archive)),
    )
    return raw.encode()


def execute_serialized_program(payload, dependencies):
    """Execute the unchanged carrier payload with external platform ports only."""
    import builtins, contextlib, io

    actual_import = builtins.__import__
    ports = {
        name: getattr(dependencies, name)
        for name in (
            "os",
            "subprocess",
            "selectors",
            "signal",
            "time",
            "socket",
            "fcntl",
            "grp",
            "pwd",
        )
    }
    ports["sys"] = dependencies.process

    def platform_import(name, globals=None, locals=None, fromlist=(), level=0):
        if globals and globals.get("__name__") == "fixed_dev_program" and name in ports:
            return ports[name]
        return actual_import(name, globals, locals, fromlist, level)

    output = io.StringIO()
    with (
        patch("builtins.__import__", side_effect=platform_import),
        contextlib.redirect_stdout(output),
    ):
        exec(compile(payload, "actual-fixed-dev-carrier", "exec"), {})
    return output.getvalue().encode()


class Clock:
    fixture_only = True

    def __init__(self):
        self.value = 1000.0
        self.epoch = 1_800_000_000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds
        self.epoch += seconds


class RawSocket:
    def __init__(self, api):
        self.api = api
        self.family, self.type = api.AF_INET, api.SOCK_STREAM
        self.descriptor, self.inheritable = 77, True
        self.address, self.port = "0.0.0.0", 0
        self.options = {api.SO_ACCEPTCONN: 0, api.SO_REUSEADDR: 0, api.SO_REUSEPORT: 0}
        self.calls = []
        self.close_unknown = False

    def fileno(self):
        return self.descriptor

    def set_inheritable(self, value):
        self.calls.append(("inherit", value))
        self.inheritable = value

    def get_inheritable(self):
        return self.inheritable

    def bind(self, address):
        self.calls.append(("bind", address))
        if address != ("127.0.0.1", 0):
            raise AssertionError("wrong bind")
        self.address, self.port = "127.0.0.1", 43891

    def getsockname(self):
        return self.address, self.port

    def getsockopt(self, level, option):
        assert level == self.api.SOL_SOCKET
        return self.options[option]

    def close(self):
        self.calls.append(("close",))
        if self.close_unknown:
            raise OSError("synthetic close result lost")
        self.descriptor = -1


class SocketAPI:
    fixture_only = True
    AF_INET, SOCK_STREAM, SOL_SOCKET, SO_ACCEPTCONN, SO_REUSEADDR, SO_REUSEPORT = range(1, 7)

    def __init__(self):
        self.created = []
        self.modify = None

    def socket(self, family, kind):
        assert (family, kind) == (self.AF_INET, self.SOCK_STREAM)
        value = RawSocket(self)
        if self.modify:
            self.modify(value)
        self.created.append(value)
        return value


class DescriptorAPI:
    fixture_only = True

    def __init__(self):
        self.inode = 789

    def fstat(self, descriptor):
        assert descriptor == 77
        return SimpleNamespace(st_dev=9, st_ino=self.inode, st_mode=stat.S_IFSOCK | 0o600)


class Namespace:
    fixture_only = True

    def __init__(self):
        self.value = "synthetic-net:[51917]"

    def __call__(self):
        return self.value


def base_binding(clock):
    return target.Binding(
        target="synthetic-dev-target",
        transport="synthetic-keeper-transport",
        standing_reference="synthetic-dev-ownership-standing",
        expected_role="Product Runtime DEV",
        window_start=clock.value - 1,
        window_end=clock.value + 1800,
        boot_id="a" * 32,
        net_namespace="synthetic-net:[51917]",
        producer_route="synthetic-native-worker-route",
        package="/var/lib/synthetic-owned-dev-package",
        sdk="/qualified/synthetic-sdk/bin/python3",
        sdk_realpath="/qualified/synthetic-sdk/bin/python3.12",
        config="/qualified/synthetic-dev.env",
        state_file="/qualified/synthetic-dev/incident.json",
        heartbeat="/qualified/producer/arbitrary-heartbeat.json",
        heartbeat_backing="synthetic-worker-backing-inode-501",
        worker_pid="707",
        worker_start="b" * 64,
        api_base="http://synthetic-dev-api.invalid:47777",
        observation_max_age=5.0,
    )


def unit_metadata(binding, clock):
    fields = {key: "" for key in target.UNIT_KEYS}
    fields.update(
        Id=target.UNIT,
        Names=target.UNIT,
        LoadState="loaded",
        ActiveState="active",
        SubState="running",
        UnitFileState="enabled",
        MainPID="4141",
        InvocationID="1" * 32,
        ControlGroup="/system.slice/system-yggdrasil\\x2dhost\\x2dprobe.slice/" + target.UNIT,
        ExecMainStartTimestampMonotonic="900000000",
        InactiveEnterTimestampMonotonic="0",
        NRestarts="0",
        Job="",
        NeedDaemonReload="no",
        FragmentPath="/qualified/synthetic-template@.service",
        DropInPaths="/qualified/synthetic-original.conf",
        User="root",
        Group="root",
        WorkingDirectory=binding.package,
        ExecStart="{ path="
        + binding.sdk
        + " ; argv[]="
        + binding.sdk
        + " "
        + binding.package
        + "/"
        + target.LAUNCHER
        + " --channel dev ; ignore_errors=no ; }",
        EnvironmentFiles=binding.config + " (ignore_errors=no)",
        Environment="PYTHONPATH="
        + binding.package
        + " HOST_SECRET_RUNTIME_DIRECTORY=/run/yggdrasil-host-probe-dev",
        KillMode="control-group",
        Restart="on-failure",
        TimeoutStopUSec="30s",
        Type="simple",
        NotifyAccess="none",
        ExecStop="",
        ExecStopPost="",
        SendSIGKILL="yes",
        KillSignal="15",
        FinalKillSignal="9",
        TimeoutStopFailureMode="terminate",
        RuntimeDirectory="yggdrasil-host-probe-dev",
        StateDirectory="yggdrasil-host-probe-dev",
        LoadCredentialEncrypted=":".join(target.DEV_CREDENTIAL),
        StandardOutput="journal",
        StandardError="journal",
        ProtectSystem="strict",
        PrivateTmp="yes",
        PrivateDevices="yes",
        NoNewPrivileges="yes",
        ReadWritePaths="/qualified/normal-controller",
        ReadOnlyPaths="/qualified/normal-heartbeat-backing",
        RestrictAddressFamilies="AF_UNIX AF_INET AF_INET6",
        UMask="0077",
    )
    return fields


class Command:
    fixture_only = True

    def __init__(self, owner):
        self.owner = owner
        self.calls, self.effects = [], []
        self.lose = None
        self.reap, self.closes = "reaped", "closed"
        self.on_start = None

    def run(self, argv, **kw):
        self.calls.append((argv, kw))
        if kw["effect"]:
            self.effects.append(argv)
        if self.lose == argv[1]:
            raise target.Unknown("synthetic original transport lost")
        if argv[0] == "/usr/bin/journalctl":
            cursor_arg = next(item for item in argv if item.startswith("--after-cursor="))
            boundary = int(cursor_arg.split("fixture-cursor-", 1)[1])
            data = b"\n".join(
                json.dumps(row).encode()
                for row in self.owner.rows
                if int(row["__CURSOR"].split("-")[-1]) > boundary
            )
        elif argv == target.systemd("reload_for_temporary_dev"):
            envelope = self.owner.installation
            if (self.owner.root / envelope.artifact).exists():
                self.owner.binding = envelope.selected
                updated = unit_metadata(envelope.selected, self.owner.clock)
                updated.update(
                    ActiveState="inactive",
                    SubState="dead",
                    MainPID="0",
                    InvocationID="",
                    ExecMainStartTimestampMonotonic="0",
                    ControlGroup="",
                )
                updated["FragmentPath"] = (
                    "/run/systemd/system/" + target.UNIT
                    if envelope.absent
                    else envelope.original["FragmentPath"]
                )
                updated["DropInPaths"] = (
                    ""
                    if envelope.absent
                    else "/run/systemd/system/" + target.UNIT + ".d/" + Path(envelope.artifact).name
                )
                self.owner.unit = updated
            else:
                self.owner.binding = envelope.binding
                self.owner.unit = dict(envelope.original)
            data = b""
        elif argv == target.systemd("show"):
            data = manager_show(argv, self.owner.unit)
        elif argv == target.dev_credential_property():
            data = manager_credential_property(argv, self.owner.unit)
        elif argv == target.systemd("stop"):
            self.owner.unit.update(
                ActiveState="inactive",
                SubState="dead",
                MainPID="0",
                InactiveEnterTimestampMonotonic=str(int(self.owner.clock.value * 1_000_000)),
            )
            data = b""
        elif argv == target.systemd("start"):
            self.owner.incarnation += 1
            identity = str(self.owner.incarnation) * 32
            self.owner.unit.update(
                ActiveState="active",
                SubState="running",
                MainPID=str(4140 + self.owner.incarnation),
                InvocationID=identity,
                ExecMainStartTimestampMonotonic=str(int(self.owner.clock.value * 1_000_000)),
                ControlGroup="/system.slice/system-yggdrasil\\x2dhost\\x2dprobe.slice/"
                + target.UNIT,
            )
            if self.on_start:
                self.on_start()
            data = b""
        else:
            raise AssertionError("non-finite command")
        return target.CommandResult(data, kw["original_handle"], 0, self.reap, self.closes)


class RuntimeReader:
    fixture_only = True

    def __init__(self, owner):
        self.owner = owner
        self.modify = None
        self.calls = 0

    def read(self, binding, *, original_handle, timeout):
        self.calls += 1
        assert timeout > 0
        owner, unit = self.owner, self.owner.unit
        active = unit["ActiveState"] == "active"
        creator = child = None
        if active:
            creator_pid = unit["MainPID"]
            creator = target.Process(
                creator_pid,
                "1",
                target.sha(("creator-" + creator_pid).encode()),
                0,
                unit["ControlGroup"],
                binding.sdk_realpath,
                binding.package,
                (binding.sdk, binding.package + "/" + target.LAUNCHER, "--channel", "dev"),
                9,
                551,
                "socket:[551]",
                binding.net_namespace,
                ("CREDENTIALS_DIRECTORY",),
            )
            child_pid = str(int(creator_pid) + 100)
            child = target.Process(
                child_pid,
                creator_pid,
                target.sha(("child-" + child_pid).encode()),
                0,
                unit["ControlGroup"],
                binding.sdk_realpath,
                binding.package,
                (binding.sdk, binding.package + "/" + target.PROBE, "--loop"),
                9,
                551,
                "socket:[551]",
                binding.net_namespace,
                (
                    "HOST_SECRET_RUNTIME_ENV_FILE",
                    "HOST_SECRET_BOOTSTRAP_CHANNEL",
                    "HOST_SECRET_BOOTSTRAP_CONSUMER",
                ),
            )
        config = (
            owner.files.read("config")
            if owner.files.config_fd is not None
            else owner.files._read(owner.files.names["config"], absent=True)
        )
        value = target.Runtime(
            original_handle,
            binding.target,
            binding.transport,
            binding.standing_reference,
            binding.expected_role,
            binding.producer_route,
            binding.boot_id,
            owner.clock.value,
            owner.clock.epoch,
            unit["InvocationID"],
            unit["ControlGroup"],
            (creator.pid, child.pid) if active else (),
            creator,
            child,
            str(owner.incarnation + 3) * 32,
            "fixture-cursor-" + str(owner.serial),
            tuple(target.SOURCE_HASHES.items()),
            target.MANIFEST_SHA256,
            "heimdal-external-alerts",
            "non-prod",
            "shared/discord.webhook",
            config.content_sha256 if config is not None else "",
            (child.pid,) if active else (),
            (binding.standing_reference,),
            (),
            binding.api_base + "/readyz",
            200,
            binding.api_base + "/api/health",
            200,
            b'{"required_ok":true}',
            binding.worker_pid,
            binding.worker_start,
            binding.heartbeat,
            binding.heartbeat_backing,
        )
        if self.modify:
            value = self.modify(value)
        return value


class SourceLog:
    def __init__(self, owner):
        self.owner = owner

    def _emit(self, level, message, args):
        owner = self.owner
        owner.serial += 1
        # Logging calls have distinct monotonic observations in this fixture.
        owner.clock.advance(0.00001)
        runtime = owner.runtime.read(
            owner.binding, original_handle=owner.caller.original_handle, timeout=1
        )
        owner.rows.append(
            {
                "MESSAGE": "2026-10-30 12:00:00,000 [prod-probe] " + level + " " + (message % args),
                "_BOOT_ID": owner.binding.boot_id,
                "_SYSTEMD_UNIT": target.UNIT,
                "_SYSTEMD_INVOCATION_ID": owner.unit["InvocationID"],
                "_SYSTEMD_CGROUP": owner.unit["ControlGroup"],
                "_TRANSPORT": "stdout",
                "_STREAM_ID": runtime.stream,
                "_PID": runtime.creator.pid,
                "__MONOTONIC_TIMESTAMP": str(int(owner.clock.value * 1_000_000)),
                "__CURSOR": "fixture-cursor-" + str(owner.serial),
            }
        )

    def info(self, message, *args):
        self._emit("INFO", message, args)

    def warning(self, message, *args):
        self._emit("WARNING", message, args)

    def error(self, message, *args):
        self._emit("ERROR", message, args)

    def exception(self, message, *args):
        self._emit("ERROR", message, args)


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return b'{"id":"123","channel_id":"456","webhook_id":"789"}'


class Harness:
    def __init__(self, root):
        self.root, self.clock = root, Clock()
        self.binding = base_binding(self.clock)
        self.unit = unit_metadata(self.binding, self.clock)
        self.incarnation, self.serial, self.rows, self.deliveries = 1, 0, [], []
        self.installation = None
        self.api, self.descriptors, self.namespace = SocketAPI(), DescriptorAPI(), Namespace()
        self.command, self.runtime = Command(self), RuntimeReader(self)
        handle = target.Handle(
            "synthetic-dev-operation", self.binding.transport, self.binding.target
        )
        self.caller = target.Caller(
            handle,
            self.clock,
            self.command,
            self.runtime,
            target.SocketFactory(self.api, self.descriptors, self.namespace),
            self.clock.value + 1800,
            600,
            max_reads=1024,
        )
        self.healthy = (
            "PROBE_ENVIRONMENT=dev\nPROBE_ALERT_CHANNEL=discord\nPROBE_BASE_URL="
            + self.binding.api_base
            + "\nPROBE_STATE_FILE="
            + self.binding.state_file
            + "\nWORKER_HEARTBEAT_PATH="
            + self.binding.heartbeat
            + "\nWORKER_HEARTBEAT_STALE_SECONDS=601\nPROBE_INTERVAL_SECONDS=61\n"
        ).encode()
        for name, data in {
            "dev.env": self.healthy,
            "arbitrary-producer.json": json.dumps({"ts": self.clock.epoch}).encode(),
            "shared-prod": b"shared bytes and production invocation",
            "ack-history": b"existing ACK/controller history",
            "unknown-fences": b"original5b47 UNKNOWN\nsuccessor329 UNKNOWN\n",
        }.items():
            path = root / name
            path.write_bytes(data)
            path.chmod(0o600)
        self.files = target.PrivateFiles(
            root,
            self.caller,
            {
                "config": "dev.env",
                "incident": "incident.json",
                "heartbeat": "arbitrary-producer.json",
                "shared_prod": "shared-prod",
                "ack_history": "ack-history",
                "unknown_fences": "unknown-fences",
            },
        )
        self.adapter = target.DevProbeAdapter(self.binding, self.caller, self.files)
        self.notification, self.probe = self.load_source()
        self.probe.ALERT_STATE_FILE = root / "incident.json"
        self.probe.log = self.notification.log = SourceLog(self)
        self.probe.time = SimpleNamespace(
            time=lambda: self.clock.epoch,
            monotonic=self.clock,
            sleep=lambda _: (_ for _ in ()).throw(
                AssertionError("source sleep is outside run_probe fixture")
            ),
        )
        self.channel = self.notification.DiscordChannel.__new__(self.notification.DiscordChannel)
        self.channel._webhook_url, self.channel._webhook_id = (
            "https://synthetic-webhook.invalid/fixture",
            "789",
        )

    def load_source(self):
        notification = ModuleType("notification_channels")
        probe = ModuleType("offline_dev_source_probe")
        sources = {}
        for relative, digest in target.SOURCE_HASHES.items():
            data = (PUBLIC / relative).read_bytes()
            if target.sha(data) != digest:
                raise AssertionError("public source drift")
            sources[relative] = data
        with patch("logging.basicConfig"):
            exec(
                compile(
                    sources["ops/host-setup/mac-mini/notification_channels.py"],
                    "pinned-public-notification",
                    "exec",
                ),
                notification.__dict__,
            )
            with patch.dict(sys.modules, {"notification_channels": notification}):
                exec(compile(sources[target.PROBE], "pinned-public-probe", "exec"), probe.__dict__)
        return notification, probe

    def source_cycle(self):
        values = target.parse_config(self.files.read("config").data)
        healthy = values["PROBE_BASE_URL"] == self.binding.api_base

        def http_get(url, **kwargs):
            if healthy:
                return 200, {"required_ok": True}
            raise ConnectionRefusedError("synthetic held non-listening port")

        def opened(request, **kwargs):
            self.deliveries.append(json.loads(request.data)["content"])
            return Response()

        with (
            patch.object(
                self.notification.urllib.request,
                "build_opener",
                return_value=SimpleNamespace(open=opened),
            ),
            patch.object(self.notification.ssl, "create_default_context", return_value=object()),
        ):
            result = self.probe.run_probe(
                base_url=values["PROBE_BASE_URL"],
                heartbeat_path=str(self.root / "arbitrary-producer.json"),
                heartbeat_stale_seconds=float(values["WORKER_HEARTBEAT_STALE_SECONDS"]),
                channel=self.channel,
                http_get=http_get,
                environment="dev",
            )
        incident_path = self.root / "incident.json"
        if incident_path.exists() and stat.S_IMODE(incident_path.stat().st_mode) != 0o600:
            # Native unit UMask=0077 creates 0600 once. Repeating chmod here
            # would mutate ctime during a suppression that leaves state intact.
            incident_path.chmod(0o600)
        return result

    def fault_start(self):
        self.adapter.admit()
        self.adapter.reserve_fault()
        self.adapter.stop_owned()
        self.adapter.swap_base_url()
        self.adapter.start_owned()

    def fault_evidence(self):
        self.source_cycle()
        self.adapter.normal_transitions()
        for _ in range(3):
            self.clock.advance(61)
            self.source_cycle()
            self.adapter.normal_transitions()

    def restore(self):
        self.adapter.stop_owned()
        self.adapter.swap_base_url(restore=True)
        self.adapter.start_owned()
        self.source_cycle()
        self.adapter.normal_transitions()
        return self.adapter.finish_restoration()

    def close(self):
        self.files.close()
        for value in self.api.created:
            value.close_unknown = False
            if value.fileno() != -1:
                value.close()


class FixedDevAdapterTests(unittest.TestCase):
    def setUp(self):
        archive, manifest, source_hashes = fixture_source()
        self.source_pins = patch.multiple(
            target,
            ARCHIVE_SHA256=target.sha(archive),
            ARCHIVE_BYTES=len(archive),
            MANIFEST_SHA256=target.sha(manifest),
            SOURCE_HASHES=source_hashes,
        )
        self.source_pins.start()
        self.temp = tempfile.TemporaryDirectory(prefix="fixture-", dir=target.PREP)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.h = Harness(self.root)
        self.guards = [
            patch("subprocess.Popen", side_effect=AssertionError("no real child")),
            patch("socket.socket", side_effect=AssertionError("no real socket")),
            patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")),
            patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("no network")),
        ]
        for guard in self.guards:
            guard.start()

    def tearDown(self):
        self.h.close()
        for guard in reversed(self.guards):
            guard.stop()
        self.temp.cleanup()
        self.source_pins.stop()

    def fresh(self):
        """Independent hostile case; never clear an original handle's UNKNOWN."""
        self.h.close()
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory(prefix="fixture-", dir=target.PREP)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.h = Harness(self.root)
        return self.h

    def installation(self, *, absent=True):
        h = self.h
        h.caller.max_bytes = 32 * 1024 * 1024
        h.caller.max_reads = 4096
        for name in ("var-lib", "volatile-systemd"):
            (h.root / name).mkdir(mode=0o700)
        h.unit.update(
            ActiveState="inactive",
            SubState="dead",
            MainPID="0",
            InvocationID="",
            ControlGroup="",
            ExecMainStartTimestampMonotonic="0",
            DropInPaths="",
        )
        if absent:
            h.unit.update(
                LoadState="not-found",
                UnitFileState="not-found",
                FragmentPath="",
                LoadCredentialEncrypted="[unprintable]",
            )
        qualification = target.InstallationQualification(
            "/var/lib",
            7,
            83,
            0,
            0,
            0o755,
            h.binding.sdk,
            h.binding.sdk_realpath,
            7,
            84,
            0,
            0,
            0o755,
            target.sha(b"synthetic-qualified-SDK"),
            None if absent else h.unit["FragmentPath"],
            None if absent else (PUBLIC / target.TEMPLATE).read_bytes(),
        )
        envelope = target.TemporaryDevInstallation(h.files, h.binding, qualification)
        h.installation = envelope
        archive, manifest, _ = fixture_source()
        return envelope, archive, manifest

    def run_installed_sequence(self, envelope):
        h = self.h
        h.adapter = envelope.activate()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        h.adapter.swap_base_url()
        h.adapter.start_owned()
        h.fault_evidence()
        h.restore()
        return envelope.restore_and_cleanup()

    def test_native_entry_and_missing_effect_ports_refuse_unconditionally(self):
        with self.assertRaisesRegex(target.Refusal, target.UNBOUND_OFFLINE_DRAFT):
            target.native_entry(self.h.binding, approved=True)
        with self.assertRaisesRegex(target.Refusal, target.UNBOUND_OFFLINE_DRAFT):
            target.Caller(
                self.h.caller.handle,
                self.h.clock,
                object(),
                self.h.runtime,
                self.h.caller.socket_factory,
                2800,
                600,
            )
        self.assertEqual([], self.h.command.effects)

    def test_complete_real_source_pair_atomic_restore_and_preservation(self):
        h = self.h
        original = h.files.read("config")
        protected = {
            key: h.files.read(key) for key in ("shared_prod", "ack_history", "unknown_fences")
        }
        h.fault_start()
        self.assertEqual(0, len(h.rows), "no completed healthy cycle prerequisite")
        held = h.api.created[0]
        self.assertEqual([("inherit", False), ("bind", ("127.0.0.1", 0))], held.calls)
        h.fault_evidence()
        active_incident = h.files.read("incident")
        self.assertEqual(
            (1, 3, 2, 0),
            (
                h.adapter.transitions.down,
                h.adapter.transitions.repeat_markers,
                h.adapter.transitions.completed_repeats,
                h.adapter.transitions.recovery,
            ),
        )
        self.assertNotEqual(-1, held.fileno())
        result = h.restore()
        restored = h.files.read("config")
        self.assertEqual(
            (original.data, original.mode, original.uid, original.gid, original.mtime_ns),
            (restored.data, restored.mode, restored.uid, restored.gid, restored.mtime_ns),
        )
        self.assertNotEqual(original.inode, restored.inode)
        self.assertEqual(protected, {key: h.files.read(key) for key in protected})
        self.assertIsNone(h.files.read("incident"))
        self.assertIsNotNone(active_incident)
        self.assertEqual(2, len(h.deliveries))
        correlation = h.adapter.transitions.correlation
        self.assertTrue(all("correlation_id: " + correlation in item for item in h.deliveries))
        self.assertEqual(
            ["stop", "start", "stop", "start"], [argv[1] for argv in h.command.effects]
        )
        self.assertEqual(-1, held.fileno())
        self.assertFalse(result["native_entry_enabled"])
        self.assertFalse(result["live_acceptance"])
        self.assertFalse(any(name.startswith(".owned-dev-config-") for name in os.listdir(h.root)))

    def test_independent_unhealthy_or_unbound_producer_first_fail_has_no_effects(self):
        variants = [
            lambda r: replace(r, health_body=b'{"required_ok":false,"ok":true}'),
            lambda r: replace(r, readyz_status=503),
            lambda r: replace(r, heartbeat_backing="unrelated"),
            lambda r: replace(r, active_owner_references=("foreign",)),
            lambda r: replace(r, pending_controller_operations=("existing-operation",)),
            lambda r: replace(r, route="unqualified-route"),
        ]
        for modify in variants:
            with self.subTest(modify=modify):
                self.fresh().runtime.modify = modify
                with self.assertRaises((target.Refusal, target.Unknown)):
                    self.h.adapter.admit()
                self.assertEqual([], self.h.command.effects)
                self.assertEqual([], self.h.api.created)
        self.assertEqual(self.h.healthy, (self.root / "dev.env").read_bytes())

    def test_existing_invalid_incident_and_stale_or_future_heartbeat_refuse(self):
        incident = self.root / "incident.json"
        incident.write_bytes(b"unparseable")
        incident.chmod(0o600)
        with self.assertRaisesRegex(target.Refusal, "preexisting_incident"):
            self.h.adapter.admit()
        incident.unlink()
        for timestamp in (self.h.clock.epoch - 1000, self.h.clock.epoch + 1):
            (self.root / "arbitrary-producer.json").write_text(json.dumps({"ts": timestamp}))
            with self.assertRaisesRegex(target.Refusal, "heartbeat_stale_or_future"):
                self.h.adapter.admit()
        self.assertEqual([], self.h.command.effects)

    def test_unit_alias_mask_or_active_unresolved_identity_refuse(self):
        for key, value in (
            ("Names", target.UNIT + " aliased.service"),
            ("UnitFileState", "masked"),
            ("NRestarts", "1"),
            ("MainPID", "0"),
            ("NeedDaemonReload", "yes"),
        ):
            with self.subTest(key=key):
                self.fresh()
                original = self.h.unit[key]
                self.h.unit[key] = value
                with self.assertRaises((target.Refusal, target.Unknown)):
                    self.h.adapter.admit()
                self.h.unit[key] = original
        self.assertEqual([], self.h.command.effects)

    def test_creator_pid_alone_does_not_prove_normal_child_or_stream(self):
        variants = [
            lambda r: replace(r, child=None),
            lambda r: replace(r, child=replace(r.child, parent="9999")),
            lambda r: replace(
                r, child=replace(r.child, stderr_inode=552, stderr_target="socket:[552]")
            ),
            lambda r: replace(r, child=replace(r.child, argv=r.child.argv[:-1] + ("--once",))),
            lambda r: replace(
                r,
                child=replace(
                    r.child, environment_keys=r.child.environment_keys + ("BWS_ACCESS_TOKEN",)
                ),
            ),
        ]
        for modify in variants:
            with self.subTest(modify=modify):
                self.fresh().runtime.modify = modify
                with self.assertRaises((target.Refusal, target.Unknown)):
                    self.h.adapter.admit()
        self.assertEqual([], self.h.command.effects)

    def test_alias_hardlink_and_file_slot_change_refuse_before_config_write(self):
        h = self.h
        path = self.root / "dev.env"
        path.rename(self.root / "original.env")
        path.symlink_to("original.env")
        with self.assertRaises((target.Refusal, OSError)):
            h.files.read("config")
        h = self.fresh()
        path = self.root / "dev.env"
        os.link(path, self.root / "alias.env")
        with self.assertRaisesRegex(target.Refusal, "alias"):
            h.files.read("config")
        (self.root / "alias.env").unlink()
        h.adapter.admit()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        path.write_bytes(h.healthy + b"UNEXPECTED=value\n")
        with self.assertRaises(target.Unknown):
            h.adapter.swap_base_url()
        self.assertEqual(["stop"], [argv[1] for argv in h.command.effects])

    def test_real_atomic_replace_loss_is_sticky_and_not_retried_or_cleaned_blindly(self):
        h = self.h
        h.adapter.admit()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        real_replace = os.replace

        def lose_after_replace(*args, **kwargs):
            real_replace(*args, **kwargs)
            raise OSError("synthetic rename acknowledgement lost")

        with patch.object(target.os, "replace", side_effect=lose_after_replace):
            with self.assertRaises(OSError):
                h.adapter.swap_base_url()
        self.assertTrue(h.caller.unknown_reasons)
        effects = list(h.command.effects)
        with self.assertRaises(target.Unknown):
            h.adapter.swap_base_url()
        with self.assertRaises(target.Unknown):
            h.adapter.start_owned()
        self.assertEqual(effects, h.command.effects)
        self.assertIn(
            b"PROBE_BASE_URL=http://127.0.0.1:43891\n", (self.root / "dev.env").read_bytes()
        )

    def test_socket_namespace_options_inode_and_close_uncertainty(self):
        h = self.h
        h.adapter.admit()
        h.namespace.value = "foreign-net:[1]"
        with self.assertRaises(target.Unknown):
            h.adapter.reserve_fault()
        self.assertEqual([], h.api.created)

    def test_socket_listening_or_reuse_is_rejected_and_known_socket_closed(self):
        h = self.h
        h.adapter.admit()
        h.api.modify = lambda value: value.options.update({h.api.SO_ACCEPTCONN: 1})
        with self.assertRaises(target.Unknown):
            h.adapter.reserve_fault()
        self.assertEqual(-1, h.api.created[0].fileno())
        self.assertEqual([], h.command.effects)

    def test_socket_close_unknown_blocks_recovery_start_after_real_file_restore(self):
        h = self.h
        h.fault_start()
        h.fault_evidence()
        h.adapter.stop_owned()
        h.api.created[0].close_unknown = True
        with self.assertRaises(target.Unknown):
            h.adapter.swap_base_url(restore=True)
        self.assertEqual(h.healthy, (h.root / "dev.env").read_bytes())
        self.assertTrue((h.root / "incident.json").exists())
        effects = list(h.command.effects)
        with self.assertRaises(target.Unknown):
            h.adapter.start_owned()
        self.assertEqual(effects, h.command.effects)

    def test_start_transport_loss_keeps_original_handle_and_no_second_start(self):
        h = self.h
        h.adapter.admit()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        h.adapter.swap_base_url()
        h.command.lose = "start"
        original_handle = h.caller.original_handle
        with self.assertRaises(target.Unknown):
            h.adapter.start_owned()
        self.assertEqual({"fault_quiescent"}, h.adapter.start_intents)
        with self.assertRaises(target.Unknown):
            h.adapter.start_owned()
        self.assertEqual(original_handle, h.caller.original_handle)
        self.assertEqual(1, len([argv for argv in h.command.effects if argv[1] == "start"]))

    def test_unreaped_stop_and_changed_incarnation_have_no_compensation(self):
        h = self.h
        h.adapter.admit()
        h.command.reap = "unknown"
        with self.assertRaises(target.Unknown):
            h.adapter.stop_owned()
        self.assertTrue(h.caller.unknown_reasons)
        self.assertEqual([], h.command.effects, "the unqualified show refuses before stop")

    def test_phase_and_whole_budget_cover_local_preflight_and_bound_reads(self):
        h = self.h
        h.clock.advance(601)
        with self.assertRaises(target.Unknown):
            h.adapter.admit()
        self.assertEqual([], h.command.calls)
        self.assertEqual([], h.command.effects)

    def test_immediate_child_down_is_not_skipped_by_post_start_cursor(self):
        h = self.h
        h.adapter.admit()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        h.adapter.swap_base_url()
        h.command.on_start = h.source_cycle
        h.adapter.start_owned()
        self.assertEqual("fixture-cursor-0", h.adapter.transitions.cursor)
        self.assertGreater(h.serial, 0)
        h.adapter.normal_transitions()
        self.assertEqual(1, h.adapter.transitions.down)

    def test_two_markers_only_prove_one_completed_later_repeat_and_no_time_shortcut(self):
        h = self.h
        h.fault_start()
        h.source_cycle()
        h.adapter.normal_transitions()
        for _ in range(2):
            h.clock.advance(61)
            h.source_cycle()
            h.adapter.normal_transitions()
        self.assertEqual(1, h.adapter.transitions.completed_repeats)
        h.clock.advance(120)
        h.adapter.normal_transitions()
        self.assertEqual(1, h.adapter.transitions.completed_repeats)
        h.adapter.stop_owned()
        with self.assertRaises(target.Unknown):
            h.adapter.swap_base_url(restore=True)

    def test_failed_confirmation_iteration_error_wrong_creator_or_replayed_cursor_unknown(self):
        h = self.h
        h.fault_start()
        h.source_cycle()
        # The source emitted real confirmed/down. Metadata claiming child PID
        # instead of the inherited stream creator must fail even with correct text.
        original = h.rows[0]["_PID"]
        h.rows[0]["_PID"] = str(int(original) + 100)
        with self.assertRaises(target.Unknown):
            h.adapter.normal_transitions()
        self.assertEqual(0, h.adapter.transitions.down)
        self.assertEqual(1, len(h.deliveries))

    def test_real_source_delivery_failure_cannot_become_down_or_trigger_retry(self):
        h = self.h
        h.fault_start()
        h.channel.send = lambda *args: (_ for _ in ()).throw(
            h.notification.NotificationDeliveryError("unconfirmed")
        )
        h.source_cycle()
        self.assertFalse((h.root / "incident.json").exists())
        with self.assertRaises(target.Unknown):
            h.adapter.normal_transitions()
        effects = list(h.command.effects)
        with self.assertRaises(target.Unknown):
            h.adapter.normal_transitions()
        self.assertEqual(effects, h.command.effects)
        self.assertEqual(0, h.adapter.transitions.down)
        self.assertEqual(["stop", "start", "stop"], [argv[1] for argv in h.command.effects])

    def test_wrong_confirmation_correlation_duplicate_cursor_or_error_is_unknown(self):
        variants = ("unconfirmed", "correlation", "cursor", "iteration")
        for kind in variants:
            with self.subTest(kind=kind):
                h = self.fresh()
                h.fault_start()
                h.source_cycle()
                if kind == "unconfirmed":
                    h.rows = [row for row in h.rows if target.CONFIRMED not in row["MESSAGE"]]
                elif kind == "correlation":
                    # A different persisted identity during later suppression
                    # cannot be accepted as continuation of the observed outage.
                    h.adapter.normal_transitions()
                    saved = json.loads((h.root / "incident.json").read_bytes())
                    saved["correlation_id"] = "11111111-1111-4111-8111-111111111111"
                    (h.root / "incident.json").write_text(json.dumps(saved))
                    h.clock.advance(61)
                    h.source_cycle()
                elif kind == "cursor":
                    h.rows[1]["__CURSOR"] = h.rows[0]["__CURSOR"]
                else:
                    h.rows[1]["MESSAGE"] = (
                        "2026-10-30 12:00:00,000 [prod-probe] ERROR probe iteration failed: environment=dev"
                    )
                with self.assertRaises(target.Unknown):
                    h.adapter.normal_transitions()
                self.assertTrue(h.caller.unknown_reasons)

    def test_preserved_history_advance_refuses_cleanup_without_rewind(self):
        h = self.h
        h.fault_start()
        (h.root / "ack-history").write_bytes(b"new ACK event must survive")
        with self.assertRaises(target.Unknown):
            h.adapter.normal_transitions()
        self.assertEqual(b"new ACK event must survive", (h.root / "ack-history").read_bytes())
        self.assertEqual(["stop", "start"], [argv[1] for argv in h.command.effects])

    def test_public_custody_is_exact_and_setup_failure_reaps_closes_all_fake_pipes(self):
        source = (PUBLIC / "scripts/probe_upgrade_operation.py").read_text()
        closed, killed, waited = [], [], []

        class Pipe:
            def __init__(self, descriptor):
                self.descriptor = descriptor

            def fileno(self):
                return self.descriptor

            def close(self):
                closed.append(self.descriptor)

        process = SimpleNamespace(
            stdin=Pipe(1),
            stdout=Pipe(2),
            stderr=Pipe(3),
            pid=777,
            poll=lambda: None,
            wait=lambda **kw: waited.append(kw),
            returncode=0,
        )
        fake_subprocess = SimpleNamespace(
            fixture_only=True,
            Popen=lambda *args, **kw: process,
            PIPE="fake-pipe",
            CompletedProcess=object,
            TimeoutExpired=TimeoutError,
        )
        selectors = SimpleNamespace(
            fixture_only=True,
            DefaultSelector=lambda: (_ for _ in ()).throw(
                OSError("synthetic selector creation failed")
            ),
        )
        fake_os = SimpleNamespace(fixture_only=True, killpg=lambda *args: killed.append(args))
        signals = SimpleNamespace(fixture_only=True, SIGKILL=9)
        clock = SimpleNamespace(fixture_only=True, monotonic=self.h.clock)
        safe = target.load_public_custody(
            source,
            subprocess_port=fake_subprocess,
            selector_port=selectors,
            os_port=fake_os,
            signal_port=signals,
            clock_port=clock,
        )
        with self.assertRaises(Exception):
            safe(["FIXTURE_NO_EXECUTABLE"], timeout=1, limit=100, effect=True)
        self.assertEqual([(777, 9)], killed)
        self.assertEqual([{"timeout": 2.0}], waited)
        self.assertEqual({1, 2, 3}, set(closed))
        self.assertEqual([], self.h.command.effects)

    def test_absent_dev_exclusive_staging_real_finite_drill_and_exact_absence_restore(self):
        h = self.h
        envelope, archive, manifest = self.installation(absent=True)
        (h.root / "dev.env").unlink()
        original_unit = dict(h.unit)
        selected = envelope.prepare(archive, manifest, h.healthy)
        self.assertRegex(selected.package, r"^/var/lib/ygg-dev-probe-[0-9a-f]{32}$")
        self.assertEqual(
            61,
            len([name for name in envelope.owned if name.startswith(envelope.source_name + "/")]),
        )
        artifact = (h.root / envelope.artifact).read_bytes()
        self.assertTrue(artifact.startswith((PUBLIC / target.TEMPLATE).read_bytes()))
        self.assertIn(b"--channel dev\n", artifact)
        self.assertNotIn(b"StandardOutput=append", artifact)
        result = self.run_installed_sequence(envelope)
        self.assertFalse((h.root / "dev.env").exists())
        self.assertEqual(original_unit, h.unit)
        self.assertEqual([], os.listdir(h.root / "var-lib"))
        self.assertEqual([], os.listdir(h.root / "volatile-systemd"))
        self.assertEqual("absent", result["original_service"])
        self.assertFalse(result["native_entry_enabled"])
        self.assertEqual(2, len(h.deliveries))

    def test_inactive_canonical_template_gets_only_volatile_dropin_then_restores_enablement(self):
        h = self.h
        envelope, archive, manifest = self.installation(absent=False)
        original_unit = dict(h.unit)
        original_config = h.files.read("config")
        template = envelope.qualification.original_template_bytes
        envelope.prepare(archive, manifest, h.healthy)
        self.assertTrue(envelope.artifact.startswith("volatile-systemd/" + target.UNIT + ".d/"))
        self.assertTrue(
            (h.root / envelope.artifact).read_bytes().startswith(b"[Service]\nWorkingDirectory=")
        )
        result = self.run_installed_sequence(envelope)
        self.assertEqual(original_unit, h.unit)
        self.assertEqual(original_config, h.files.read("config"))
        self.assertEqual("enabled", h.unit["UnitFileState"])
        self.assertEqual(template, envelope.qualification.original_template_bytes)
        self.assertEqual("inactive", result["original_service"])
        self.assertEqual([], os.listdir(h.root / "volatile-systemd"))

    def test_staging_digest_alias_or_custom_unit_refuses_before_install_effect(self):
        envelope, archive, manifest = self.installation(absent=False)
        with self.assertRaisesRegex(target.Refusal, "source_digest"):
            envelope.prepare(archive[:-1] + b"x", manifest, self.h.healthy)
        self.assertEqual([], self.h.command.effects)
        self.h.unit["DropInPaths"] = "/qualified/foreign-custom.conf"
        with self.assertRaisesRegex(target.Refusal, "foreign_or_custom"):
            envelope.prepare(archive, manifest, self.h.healthy)
        self.assertEqual([], self.h.command.effects)
        self.assertEqual([], os.listdir(self.h.root / "var-lib"))

    def test_staged_source_drift_refuses_first_start_without_adopting_changed_bytes(self):
        h = self.h
        envelope, archive, manifest = self.installation(absent=True)
        envelope.prepare(archive, manifest, h.healthy)
        probe = h.root / envelope.source_name / target.PROBE
        probe.write_bytes(probe.read_bytes() + b"\n# unowned mutation\n")
        with self.assertRaisesRegex(target.Unknown, "source_or_unit_drift"):
            envelope.activate()
        self.assertEqual(["daemon-reload"], [argv[1] for argv in h.command.effects])
        self.assertTrue((h.root / envelope.artifact).exists())

    def test_staged_cleanup_refuses_foreign_artifact_before_any_source_or_unit_unlink(self):
        h = self.h
        envelope, archive, manifest = self.installation(absent=True)
        envelope.prepare(archive, manifest, h.healthy)
        h.adapter = envelope.activate()
        h.adapter.reserve_fault()
        h.adapter.stop_owned()
        h.adapter.swap_base_url()
        h.adapter.start_owned()
        h.fault_evidence()
        h.restore()
        unowned = h.root / envelope.source_name / "unqualified-cache.pyc"
        unowned.write_bytes(b"foreign bytes")
        unowned.chmod(0o600)
        with self.assertRaisesRegex(target.Unknown, "unqualified_sdk_cache"):
            envelope.restore_and_cleanup()
        self.assertTrue(unowned.exists())
        self.assertTrue((h.root / envelope.artifact).exists())
        self.assertTrue((h.root / envelope.source_name / target.PROBE).exists())
        self.assertFalse((h.root / "incident.json").exists())


class LinuxMeta:
    def __init__(
        self, inode, *, mode=0o600, kind=stat.S_IFREG, size=0, uid=0, gid=0, stamp=1_000_000_000
    ):
        self.st_dev, self.st_ino, self.st_mode = 9, inode, kind | mode
        self.st_uid, self.st_gid, self.st_nlink, self.st_size = uid, gid, 1, size
        self.st_mtime_ns = self.st_ctime_ns = stamp


class MemoryLinuxOS:
    """Fake kernel boundary with realistic proc text and stat/link semantics."""

    def __init__(self, kernel):
        self.kernel, self.files, self.meta, self.links, self.fds, self.pipes = (
            kernel,
            {},
            {},
            {},
            {},
            {},
        )
        self.next_fd, self.next_inode, self.opened, self.closed = 2000, 3000, [], []
        # The fake filesystem hosts the imported source at the registered caller
        # path even when pytest imports its bytes from a different CI checkout.
        # Capture before remote roles temporarily change the module's __file__.
        imported_program = target.__file__
        self.path = SimpleNamespace(
            realpath=lambda path: (
                target.LOCAL_DEV_PROGRAM
                if path == imported_program
                else kernel.scope.binding.sdk_realpath
                if path == kernel.scope.binding.sdk
                else path
            )
        )
        self.current_directory = target.LOCAL_DEV_WORKTREE
        self.writable_paths = None
        self.mount_writes = []
        self.environ = {"HOME": "/synthetic-local-home"}
        for key in (
            "O_RDONLY",
            "O_WRONLY",
            "O_CREAT",
            "O_EXCL",
            "O_NOFOLLOW",
            "O_NONBLOCK",
            "O_CLOEXEC",
            "O_DIRECTORY",
            "SEEK_SET",
        ):
            setattr(self, key, getattr(os, key))
        self.add("/", b"", mode=0o755, directory=True)

    def getcwd(self):
        return self.current_directory

    def require_write(self, action, path, *, parent=False):
        if self.writable_paths is None:
            return
        permission = str(Path(path).parent) if parent else path
        if not any(
            permission == root or permission.startswith(root + "/") for root in self.writable_paths
        ):
            raise OSError(30, "Read-only file system", path)
        self.mount_writes.append((action, path, permission))

    def add(self, path, data=b"", *, mode=0o600, directory=False, inode=None, uid=0):
        if path != "/":
            parent = str(Path(path).parent)
            if parent not in self.meta:
                self.add(parent, mode=0o755, directory=True)
        self.next_inode += 1
        self.meta[path] = LinuxMeta(
            inode or self.next_inode,
            mode=mode,
            kind=stat.S_IFDIR if directory else stat.S_IFREG,
            size=len(data),
            uid=uid,
        )
        if not directory:
            self.files[path] = bytes(data)

    def full(self, path, dir_fd=None):
        if path.startswith("/"):
            return path
        return str(Path(self.fds[dir_fd][0]) / path)

    def _dynamic(self, path):
        if path == self.kernel.scope.binding.state_file:
            real = self.kernel.h.root / "native-incident.json"
            if not real.exists():
                self.files.pop(path, None)
                self.meta.pop(path, None)
            else:
                data = real.read_bytes()
                meta = real.stat()
                self.files[path] = data
                self.meta[path] = LinuxMeta(meta.st_ino, size=len(data), stamp=meta.st_mtime_ns)
                self.meta[path].st_ctime_ns = meta.st_ctime_ns
        return path

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        path = self._dynamic(self.full(path, dir_fd))
        if (
            path.startswith("/var/lib/yggdrasil/bws-tokens/") and not flags & self.O_DIRECTORY
        ) or path.endswith("/secret-runtime.env"):
            raise AssertionError("credential content read forbidden")
        if flags & self.O_CREAT:
            self.require_write("create", path, parent=True)
            if path in self.meta and flags & self.O_EXCL:
                raise FileExistsError(path)
            self.add(path, mode=mode)
        elif flags & self.O_WRONLY:
            self.require_write("open-write", path)
        if path not in self.meta:
            raise FileNotFoundError(path)
        if flags & self.O_DIRECTORY and not stat.S_ISDIR(self.meta[path].st_mode):
            raise NotADirectoryError(path)
        self.next_fd += 1
        self.fds[self.next_fd] = [path, 0]
        self.opened.append(path)
        return self.next_fd

    def fstat(self, fd):
        if fd == 77:
            return LinuxMeta(789, kind=stat.S_IFSOCK)
        path = self._dynamic(self.fds[fd][0])
        self.meta[path].st_size = len(self.files.get(path, b""))
        return self.meta[path]

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        path = self._dynamic(self.full(path, dir_fd))
        if path == "/proc/707/root/runtime/producer.json":
            return self.meta[self.kernel.scope.binding.heartbeat]
        if path.endswith("/fd/2"):
            pid = path.split("/")[2]
            return LinuxMeta(551 if pid != "707" else 552, kind=stat.S_IFSOCK)
        if path not in self.meta:
            raise FileNotFoundError(path)
        return self.meta[path]

    def readlink(self, path, *, dir_fd=None):
        return self.links[self.full(path, dir_fd)]

    def listxattr(self, descriptor):
        return []

    def set_blocking(self, descriptor, value):
        pass

    def read(self, fd, count):
        if fd in self.pipes:
            return self.pipes[fd].read(count)
        path, position = self.fds[fd]
        self._dynamic(path)
        data = self.files[path][position : position + count]
        self.fds[fd][1] += len(data)
        return data

    def write(self, fd, data):
        if fd in self.pipes:
            return self.pipes[fd].write(data)
        path, position = self.fds[fd]
        self.require_write("write", path)
        raw = self.files[path]
        self.files[path] = raw[:position] + bytes(data) + raw[position + len(data) :]
        self.fds[fd][1] += len(data)
        self.meta[path].st_size = len(self.files[path])
        return len(data)

    def close(self, fd):
        self.closed.append(fd)
        del self.fds[fd]

    def dup(self, fd):
        self.next_fd += 1
        self.fds[self.next_fd] = list(self.fds[fd])
        return self.next_fd

    def fsync(self, fd):
        pass

    def fchmod(self, fd, mode):
        self.require_write("chmod", self.fds[fd][0])
        self.meta[self.fds[fd][0]].st_mode = stat.S_IFREG | mode

    def utime(self, fd, *, ns):
        self.require_write("utime", self.fds[fd][0])
        self.meta[self.fds[fd][0]].st_mtime_ns = ns[1]

    def replace(self, source, destination, *, src_dir_fd, dst_dir_fd):
        a, b = self.full(source, src_dir_fd), self.full(destination, dst_dir_fd)
        self.require_write("replace-source", a, parent=True)
        self.require_write("replace-destination", b, parent=True)
        self.files[b], self.meta[b] = self.files.pop(a), self.meta.pop(a)

    def killpg(self, pid, sig):
        self.kernel.killed.append((pid, sig))

    def getpid(self):
        return 999

    def geteuid(self):
        return 0

    def pidfd_open(self, pid, flags):
        return self.open("/proc/" + str(pid) + "/stat", self.O_RDONLY)

    def mkdir(self, path, mode=0o777, *, dir_fd=None):
        path = self.full(path, dir_fd)
        self.require_write("mkdir", path, parent=True)
        if path in self.meta:
            raise FileExistsError(path)
        self.add(path, mode=mode, directory=True)

    def listdir(self, fd):
        parent = self.fds[fd][0].rstrip("/") + "/"
        return [
            path[len(parent) :]
            for path in self.meta
            if path.startswith(parent) and path != parent and "/" not in path[len(parent) :]
        ]

    def unlink(self, path, *, dir_fd=None):
        path = self.full(path, dir_fd)
        self.require_write("unlink", path, parent=True)
        if self.meta[path].st_nlink > 1:
            self.meta[path].st_nlink -= 1
        self.files.pop(path)
        self.meta.pop(path)

    def link(self, source, destination, *, src_dir_fd, dst_dir_fd, follow_symlinks=False):
        a, b = self.full(source, src_dir_fd), self.full(destination, dst_dir_fd)
        self.require_write("link", b, parent=True)
        if b in self.meta:
            raise FileExistsError(b)
        self.files[b], self.meta[b] = self.files[a], self.meta[a]
        self.meta[a].st_nlink += 1

    def rmdir(self, path, *, dir_fd=None):
        path = self.full(path, dir_fd)
        self.require_write("rmdir", path, parent=True)
        if any(item.startswith(path + "/") for item in self.meta):
            raise OSError("directory not empty")
        self.meta.pop(path)


class NativePipe:
    def __init__(self, process, kind, descriptor):
        self.process, self.kind, self.descriptor, self.closed = process, kind, descriptor, False
        self.offset = 0

    def fileno(self):
        return self.descriptor

    def close(self):
        self.closed = True

    def write(self, data):
        self.process.input.extend(data)
        return len(data)

    def read(self, count):
        if self.kind == "stderr":
            return b""
        if self.process.output is None:
            self.process.output = self.process.kernel.response(
                self.process.argv, bytes(self.process.input)
            )
        data = self.process.output[self.offset : self.offset + count]
        self.offset += len(data)
        return data


class NativeProcess:
    def __init__(self, kernel, argv):
        self.kernel, self.argv, self.input, self.output, self.returncode, self.pid = (
            kernel,
            tuple(argv),
            bytearray(),
            None,
            None,
            999,
        )
        number = 900000 + len(kernel.processes) * 10
        self.stdin, self.stdout, self.stderr = (
            NativePipe(self, key, number + index)
            for index, key in enumerate(("stdin", "stdout", "stderr"))
        )
        for pipe in (self.stdin, self.stdout, self.stderr):
            kernel.os.pipes[pipe.fileno()] = pipe

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.returncode = getattr(self.kernel, "forced_returncodes", {}).get(self.argv, 0)
        self.kernel.reaped.append(self.pid)
        return self.returncode


class NativeSelector:
    def __init__(self):
        self.registered, self.closed = {}, False

    def register(self, stream, events, kind):
        fd = stream if isinstance(stream, int) else stream.fileno()
        self.registered[fd] = SimpleNamespace(fd=fd, fileobj=stream, data=kind)

    def unregister(self, stream):
        self.registered.pop(stream.fileno())

    def get_map(self):
        return self.registered

    def select(self, timeout):
        return [
            (key, 1)
            for key in list(self.registered.values())
            if key.data != "stdout" or key.fileobj.process.stdin.closed
        ]

    def close(self):
        self.closed = True


def manager_show(argv, fields):
    """Actual show projection, including generic a(ss) [unprintable] output."""
    keys = next(
        arg.removeprefix("--property=") for arg in argv if arg.startswith("--property=")
    ).split(",")
    arrays = {"EnvironmentFiles", "ExecStart", "ExecStop", "ExecStopPost"}
    return "".join(
        key + "=" + ("[unprintable]" if key == "LoadCredentialEncrypted" else fields[key]) + "\n"
        for key in keys
        if key in fields and (fields[key] or key not in arrays and "--all" in argv)
    ).encode()


def manager_credential_property(argv, fields):
    assert argv == (
        "/usr/bin/busctl",
        "--json=short",
        "get-property",
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1/unit/yggdrasil_2dhost_2dprobe_40dev_2eservice",
        "org.freedesktop.systemd1.Service",
        "LoadCredentialEncrypted",
    )
    assert fields["LoadState"] == "loaded", "No Service getter exists for absent unit"
    rows = [fields["LoadCredentialEncrypted"].split(":", 1)]
    return json.dumps({"type": "a(ss)", "data": rows}, separators=(",", ":")).encode()


class DockerDiscoveryProducer:
    """External Docker port: apply argv filters and the actual Go projection.

    The fixed template subset follows docker/cli's inspector/templates and
    formatter/container contracts. Inputs have Docker's raw inspect shape;
    no parser-facing dictionary or preselected container is returned.
    """

    def __init__(self):
        self.containers = [
            {
                "Id": identity * 64,
                "Image": "sha256:" + "c" * 64,
                "State": {"Pid": pid, "Running": True},
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.revision": "f" * 40,
                        "com.docker.compose.project": "observed-dev-project",
                        "com.docker.compose.service": service,
                    },
                    "Env": ["PKM_ENVIRONMENT=dev"]
                    + (
                        ["WORKER_HEARTBEAT_PATH=/runtime/producer.json"]
                        if service == "worker"
                        else []
                    ),
                },
                "NetworkSettings": {
                    "Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "47777"}]}
                    if service == "api"
                    else {},
                },
                "Mounts": [{"Source": "/var/lib/actual-backing", "Destination": "/runtime"}]
                if service == "worker"
                else [],
            }
            for identity, service, pid in (("a", "api", 808), ("b", "worker", 707))
        ]
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ("/usr/bin/docker", "ps"):
            assert argv[-2:] == ("--format", "{{.ID}}")
            assert len(argv[2:-2]) % 2 == 0
            filters = []
            for option, value in zip(argv[2:-2:2], argv[3:-2:2], strict=True):
                assert option == "--filter" and value.startswith("label=")
                filters.append(value.removeprefix("label=").split("=", 1))
            return "".join(
                row["Id"][:12] + "\n"
                for row in self.containers
                if row["State"]["Running"]
                and all(row["Config"]["Labels"].get(key) == value for key, value in filters)
            ).encode()
        assert argv[:3] == ("/usr/bin/docker", "inspect", "--format") and len(argv) == 5
        rows = [row for row in self.containers if row["Id"].startswith(argv[-1])]
        assert len(rows) == 1
        row = rows[0]

        def field(path):
            value = row
            for part in path.split("."):
                value = value[part]
            return value

        # Go's range emits nothing for a missing env key and concatenates all
        # matching entries; either can make this caller's JSON invalid.
        output = re.sub(
            r'{{range \.Config.Env}}{{if eq \(index \(split \. "="\) 0\) "([^"]+)"}}'
            r'{{json \(index \(split \. "="\) 1\)}}{{end}}{{end}}',
            lambda match: "".join(
                json.dumps(value.split("=")[1])
                for value in row["Config"]["Env"]
                if value.split("=")[0] == match[1]
            ),
            argv[3],
        )
        output = re.sub(
            r'{{json \(index \.Config.Labels "([^"]+)"\)}}',
            lambda match: json.dumps(row["Config"]["Labels"].get(match[1])),
            output,
        )
        output = re.sub(
            r"{{json \.([A-Za-z.]+)}}", lambda match: json.dumps(field(match[1])), output
        )
        output = output.replace("{{.State.Pid}}", str(row["State"]["Pid"]))
        assert "{{" not in output
        return (output + "\n").encode()


class NativeKernel:
    def __init__(self, h):
        self.h, self.clock, self.processes, self.reaped, self.killed, self.selectors = (
            h,
            h.clock,
            [],
            [],
            [],
            [],
        )
        self.incarnation, self.rows, self.serial, self.next_cycle, self.startup_samples = (
            1,
            [],
            0,
            None,
            0,
        )
        _, manifest, _ = fixture_source()
        binding = replace(
            base_binding(h.clock),
            target="ygg-dev",
            transport="ygg-dev",
            package="/opt/yggdrasil/host-probe",
            sdk="/opt/yggdrasil/bws-deploy-runtime/bin/python3",
            sdk_realpath="/usr/bin/python3.12",
            config="/etc/yggdrasil/host-probe/dev.env",
            state_file="/var/lib/yggdrasil-host-probe-dev/alert-state.json",
            heartbeat="/var/lib/actual-backing/producer.json",
            heartbeat_backing="9:223",
            net_namespace="net:[51917]",
            worker_start=target.sha(("a" * 32 + ":707:700").encode()),
        )
        self.scope = target.FrozenNativeScope(
            binding,
            target.Handle("1" * 32, "ygg-dev", "ygg-dev"),
            "e" * 32,
            "d" * 32,
            "holder",
            "lease",
            target.sha(b"frozen-program"),
            manifest,
            (PUBLIC / "app/ops/host_secret_controller.py").read_bytes(),
            (PUBLIC / target.PROBE).read_bytes(),
            "/root/.local/state/yggdrasil/secret-controller",
            "/var/lib/yggdrasil/bws-tokens/dev/current",
            "/var/lib/yggdrasil/bws-tokens/dev/current",
            "synthetic-project-id",
            "python3",
            0,
            (
                (
                    "shared_dev_host",
                    "/var/lib/preserved-dev-host",
                    target.sha(b"shared DEV bytes remain"),
                    0o600,
                ),
            ),
            (
                ("original5b47", target.sha(b"immutable local original reference")),
                ("successor329", target.sha(b"immutable local successor reference")),
            ),
            (
                (
                    "api",
                    "a" * 64,
                    "sha256:" + "c" * 64,
                    "f" * 40,
                    "808",
                    target.sha(("a" * 32 + ":808:800").encode()),
                ),
                ("worker", "b" * 64, "sha256:" + "c" * 64, "f" * 40, "707", binding.worker_start),
            ),
        )
        self.unit = unit_metadata(binding, self.clock)
        self.unit.update(
            FragmentPath="/etc/systemd/system/yggdrasil-host-probe@.service",
            DropInPaths="",
            LoadCredentialEncrypted="bws-machine-account-token:" + self.scope.credential_source,
            ReadWritePaths=self.scope.controller_directory,
        )
        self.os = MemoryLinuxOS(self)
        self.os.add("/run/systemd/system", mode=0o755, directory=True)
        for relative, data in json.loads(manifest)["files"].items():
            self.os.add(
                binding.package + "/" + relative, (PUBLIC / relative).read_bytes(), mode=0o664
            )
        config = (
            "PROBE_ENVIRONMENT=dev\nPROBE_ALERT_CHANNEL=discord\nPROBE_BASE_URL="
            + binding.api_base
            + "\nPROBE_STATE_FILE="
            + binding.state_file
            + "\nWORKER_HEARTBEAT_PATH="
            + binding.heartbeat
            + "\nWORKER_HEARTBEAT_STALE_SECONDS=601\nPROBE_INTERVAL_SECONDS=61\n"
        ).encode()
        for path, data, mode in (
            (binding.config, config, 0o600),
            ("/etc/machine-id", b"d" * 32 + b"\n", 0o444),
            ("/proc/sys/kernel/random/boot_id", b"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n", 0o444),
            ("/proc/sys/kernel/hostname", b"ygg-dev\n", 0o444),
            (binding.sdk_realpath, b"synthetic existing interpreter", 0o755),
            (self.scope.root + "/request.json", self.scope.request_bytes, 0o600),
            (self.scope.root + "/program.py", b"frozen-program", 0o600),
            (self.scope.controller_directory + "/operation.lock", b"", 0o600),
            (self.scope.controller_directory + "/operations.jsonl", b"", 0o600),
            (
                "/etc/yggdrasil/bws-deploy/dev.json",
                b'{"project_id":"synthetic-project-id","organization_id":"synthetic-organization"}',
                0o600,
            ),
            ("/var/lib/preserved-dev-host", b"shared DEV bytes remain", 0o600),
            (self.scope.credential_source, b"DO_NOT_READ_CREDENTIAL", 0o600),
            ("/run/yggdrasil-host-probe-dev/secret-runtime.env", b"DO_NOT_READ_WEBHOOK", 0o600),
            (
                binding.heartbeat,
                json.dumps({"ts": self.clock.epoch, "pid": 707, "status": "running"}).encode(),
                0o666,
            ),
        ):
            self.os.add(path, data, mode=mode, inode=223 if path == binding.heartbeat else None)
        for path in (
            self.scope.root,
            self.scope.controller_directory,
            str(Path(binding.state_file).parent),
            "/run/yggdrasil-host-probe-dev",
            str(Path(self.scope.credential_source).parent),
        ):
            if path not in self.os.meta:
                self.os.add(path, mode=0o700, directory=True)
            self.os.meta[path].st_mode = stat.S_IFDIR | 0o700
        self.os.links["/proc/self/ns/net"] = binding.net_namespace
        self.os.links["/proc/self/exe"] = binding.sdk_realpath
        self._processes()
        supervisor_unit = "yggdrasil-dev-probe-" + self.scope.handle.operation + ".service"
        self.supervisor = unit_metadata(binding, self.clock)
        self.supervisor.update(
            Id=supervisor_unit,
            MainPID="999",
            InvocationID="b" * 32,
            ControlGroup="/system.slice/" + supervisor_unit,
            WorkingDirectory=self.scope.root,
            Restart="no",
            TimeoutStopUSec="5s",
            Type="exec",
            ExecStart="{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -I "
            + self.scope.root
            + "/program.py --supervised-first-preflight "
            + self.scope.handle.operation
            + " ; ignore_errors=no ; }",
        )
        self.os.add(
            self.scope.root + "/supervisor-start.json",
            json.dumps(
                {
                    "operation": self.scope.handle.operation,
                    "program_sha256": self.scope.program_sha256,
                    "boot_id": binding.boot_id,
                    "unit": supervisor_unit,
                    "pid": "999",
                    "invocation": self.supervisor["InvocationID"],
                    "cgroup": self.supervisor["ControlGroup"],
                    "profile": {
                        key: self.supervisor[key] for key in target.SUPERVISOR_PROFILE_KEYS
                    },
                }
            ).encode(),
        )
        self.os.add(
            "/sys/fs/cgroup" + self.supervisor["ControlGroup"] + "/cgroup.procs",
            b"999\n",
            mode=0o444,
        )
        time_api = SimpleNamespace(
            monotonic=self.clock, time=lambda: self.clock.epoch, sleep=self.sleep
        )
        subprocess_api = SimpleNamespace(
            Popen=self.spawn,
            PIPE="fake-pipe",
            CompletedProcess=lambda args, returncode, stdout, stderr: SimpleNamespace(
                args=args, returncode=returncode, stdout=stdout, stderr=stderr
            ),
            TimeoutExpired=TimeoutError,
        )
        import importlib.util

        self.dependencies = target.LinuxDependencies(
            self.os,
            subprocess_api,
            SimpleNamespace(DefaultSelector=self.selector, EVENT_READ=1, EVENT_WRITE=2),
            SimpleNamespace(SIGKILL=9),
            time_api,
            SocketAPI(),
            SimpleNamespace(flock=lambda *args: None, LOCK_SH=1, LOCK_NB=2),
            SimpleNamespace(getgrgid=lambda _: SimpleNamespace(gr_mem=[])),
            SimpleNamespace(getpwall=lambda: [], getpwnam=lambda _: SimpleNamespace(pw_uid=0)),
            importlib.util,
            SimpleNamespace(executable=sys.executable),
        )
        self.h.probe.ALERT_STATE_FILE = self.h.root / "native-incident.json"
        self.h.probe.log = self.h.notification.log = SimpleNamespace(
            info=lambda msg, *args: self.log("INFO", msg, args),
            warning=lambda msg, *args: self.log("WARNING", msg, args),
            error=lambda msg, *args: self.log("ERROR", msg, args),
            exception=lambda msg, *args: self.log("ERROR", msg, args),
        )
        self.source_cycle()

    def _proc(self, pid, parent, argv, environment, ticks, cgroup, *, stderr=551):
        binding = self.scope.binding
        fields = ["S", str(parent)] + ["0"] * 17 + [str(ticks)] + ["0"] * 5
        base = "/proc/" + pid
        for leaf, data in {
            "stat": (pid + " (python3) " + " ".join(fields)).encode(),
            "status": ("Name:\tpython3\nNSpid:\t" + pid + "\n").encode(),
            "cgroup": ("0::" + cgroup + "\n").encode(),
            "cmdline": b"\0".join(arg.encode() for arg in argv) + b"\0",
            "environ": b"\0".join(
                (key + "=" + value).encode() for key, value in environment.items()
            )
            + (b"\0" if environment else b""),
        }.items():
            self.os.add(base + "/" + leaf, data, mode=0o444)
        self.os.links.update(
            {
                base + "/exe": binding.sdk_realpath,
                base + "/cwd": binding.package,
                base + "/ns/net": binding.net_namespace,
                base + "/fd/2": "socket:[" + str(stderr) + "]",
            }
        )

    def _processes(self):
        binding, group = self.scope.binding, self.unit["ControlGroup"]
        creator, child = (
            self.unit["MainPID"],
            str(int(self.unit["MainPID"]) + 100) if self.unit["MainPID"] != "0" else "0",
        )
        self._proc(
            "707",
            "1",
            ("python3", "-m", "app.workers.outbox_worker"),
            {"PKM_ENVIRONMENT": "dev", "WORKER_HEARTBEAT_PATH": "/runtime/producer.json"},
            700,
            "/system.slice/worker.service",
            stderr=552,
        )
        self._proc(
            "808",
            "1",
            ("python3", "-m", "uvicorn"),
            {},
            800,
            "/system.slice/api.service",
            stderr=552,
        )
        self._proc(
            "999",
            "1",
            (binding.sdk, "-I", self.scope.root + "/program.py"),
            {},
            999,
            "/system.slice/yggdrasil-dev-probe-" + self.scope.handle.operation + ".service",
            stderr=552,
        )
        if creator != "0":
            package = self.unit["WorkingDirectory"]
            marker = (
                {"YGG_DEV_OPERATION": self.scope.handle.operation}
                if "YGG_DEV_OPERATION=" + self.scope.handle.operation in self.unit["Environment"]
                else {}
            )
            self._proc(
                creator,
                "1",
                (binding.sdk, package + "/" + target.LAUNCHER, "--channel", "dev"),
                {"CREDENTIALS_DIRECTORY": "/run/credentials/dev", **marker},
                int(creator),
                group,
            )
            self._proc(
                child,
                creator,
                (binding.sdk, package + "/" + target.PROBE, "--loop"),
                {
                    "HOST_SECRET_RUNTIME_ENV_FILE": "/run/yggdrasil-host-probe-dev/secret-runtime.env",
                    "HOST_SECRET_BOOTSTRAP_CHANNEL": "dev",
                    "HOST_SECRET_BOOTSTRAP_CONSUMER": "heimdal-external-alerts",
                },
                int(child),
                group,
            )
            self.os.links["/proc/" + creator + "/cwd"] = package
            self.os.links["/proc/" + child + "/cwd"] = package
        members = "" if creator == "0" else creator + "\n" + child + "\n"
        self.os.add("/sys/fs/cgroup" + group + "/cgroup.procs", members.encode(), mode=0o444)

    def spawn(self, argv, **kwargs):
        process = NativeProcess(self, argv)
        process.environment = kwargs.get("env", {})
        self.processes.append(process)
        return process

    def selector(self):
        selector = NativeSelector()
        self.selectors.append(selector)
        return selector

    def log(self, level, msg, args):
        self.serial += 1
        self.clock.advance(0.00001)
        self.rows.append(
            {
                "MESSAGE": "2026-10-30 12:00:00,000 [prod-probe] " + level + " " + (msg % args),
                "_BOOT_ID": self.scope.binding.boot_id,
                "_SYSTEMD_UNIT": target.UNIT,
                "_SYSTEMD_INVOCATION_ID": self.unit["InvocationID"],
                "_SYSTEMD_CGROUP": self.unit["ControlGroup"],
                "_PID": self.unit["MainPID"],
                "_TRANSPORT": "stdout",
                "_STREAM_ID": str(self.incarnation + 3) * 32,
                "__CURSOR": "native-cursor-" + str(self.serial),
                "__MONOTONIC_TIMESTAMP": str(int(self.clock.value * 1_000_000)),
            }
        )

    def source_cycle(self):
        binding = self.scope.binding
        configured = self.unit["EnvironmentFiles"].split("(ignore_errors=no)", 1)[0].strip()
        values = target.parse_config(self.os.files[configured])

        def http_get(url, **kwargs):
            if values["PROBE_BASE_URL"] == binding.api_base:
                return 200, {"required_ok": True}
            raise ConnectionRefusedError("fake held non-listening socket")

        def opened(request, **kwargs):
            self.h.deliveries.append(json.loads(request.data)["content"])
            return Response()

        with (
            patch.object(
                self.h.notification.urllib.request,
                "build_opener",
                return_value=SimpleNamespace(open=opened),
            ),
            patch.object(self.h.notification.ssl, "create_default_context", return_value=object()),
        ):
            self.h.probe.run_probe(
                base_url=values["PROBE_BASE_URL"],
                heartbeat_path=str(self.h.root / "arbitrary-producer.json"),
                heartbeat_stale_seconds=601,
                channel=self.h.channel,
                http_get=http_get,
                environment="dev",
            )
        path = self.h.root / "native-incident.json"
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != 0o600:
            path.chmod(0o600)

    def sleep(self, seconds):
        self.clock.advance(seconds)
        if (
            self.next_cycle is not None
            and self.clock.value >= self.next_cycle
            and self.unit["ActiveState"] == "active"
        ):
            self.source_cycle()
            self.next_cycle = self.clock.value + 61

    def response(self, argv, input_bytes):
        if argv == target.systemd("reload_for_temporary_dev"):
            guard_paths = [path for path in self.os.files if "/99-ygg-dev-owner-" in path]
            if not hasattr(self, "original_guard_properties"):
                self.original_guard_properties = (
                    self.unit["Environment"],
                    self.unit["DropInPaths"],
                )
            environment, dropins = self.original_guard_properties
            self.unit["Environment"] = environment + (
                " YGG_DEV_OPERATION=" + self.scope.handle.operation if guard_paths else ""
            )
            self.unit["DropInPaths"] = " ".join([*dropins.split(), *guard_paths])
            return b""
        if argv == target.watchdog_command(self.scope):
            self.guardian_active = True
            self._proc(
                "9888",
                "1",
                (self.scope.binding.sdk, "-I", self.scope.root + "/program.py"),
                {},
                9888,
                "/system.slice/" + target.watchdog_unit(self.scope),
            )
            record = json.loads(self.os.files[self.scope.root + "/watchdog.json"])
            self.os.add(
                self.scope.root + "/watchdog-ready.json",
                json.dumps(
                    {
                        "operation": self.scope.handle.operation,
                        "program_sha256": self.scope.program_sha256,
                        "boot_id": self.scope.binding.boot_id,
                        "helper_pid": record["helper_pid"],
                        "helper_start": record["helper_start"],
                        "guardian_pid": "9888",
                        "guardian_start": target.sha(
                            (self.scope.binding.boot_id + ":9888:9888").encode()
                        ),
                    }
                ).encode(),
            )
            return b""
        if argv == target.supervisor_show(self.scope.handle.operation):
            return manager_show(argv, self.supervisor)
        if argv == target.supervisor_stop(self.scope):
            self.supervisor.update(ActiveState="inactive", MainPID="0", Job="")
            self.os.files["/sys/fs/cgroup" + self.supervisor["ControlGroup"] + "/cgroup.procs"] = (
                b""
            )
            return b""
        if argv == target.watchdog_stop(self.scope):
            self.guardian_active = False
            group = (
                "/sys/fs/cgroup/system.slice/" + target.watchdog_unit(self.scope) + "/cgroup.procs"
            )
            self.os.files.pop(group, None)
            self.os.meta.pop(group, None)
            # A successfully stopped transient unit is already unloaded.
            self.forced_returncodes = {target.watchdog_show(self.scope): 4}
            return b""
        if argv == target.watchdog_show(self.scope):
            active = getattr(self, "guardian_active", False)
            group = "/system.slice/" + target.watchdog_unit(self.scope)
            self.os.add(
                "/sys/fs/cgroup" + group + "/cgroup.procs", b"9888\n" if active else b"", mode=0o444
            )
            fields = {
                "ActiveState": "active" if active else "inactive",
                "SubState": "running" if active else "dead",
                "MainPID": "9888" if active else "0",
                "InvocationID": "8" * 32,
                "ControlGroup": group,
                "ExecMainStartTimestampMonotonic": "1000000000",
                "Job": "0",
                "ExecStart": "{ path="
                + self.scope.binding.sdk
                + " ; argv[]="
                + self.scope.binding.sdk
                + " -I "
                + self.scope.root
                + "/program.py --watch-dev-operation "
                + self.scope.handle.operation
                + " ; ignore_errors=no ; }",
            }
            return manager_show(argv, fields)
        if argv == target.systemd("show"):
            return manager_show(argv, self.unit)
        if argv == target.dev_credential_property():
            return manager_credential_property(argv, self.unit)
        if argv == target.systemd("stop"):
            self.unit.update(
                ActiveState="inactive",
                SubState="dead",
                MainPID="0",
                Job="",
                InactiveEnterTimestampMonotonic=str(int(self.clock.value * 1_000_000)),
            )
            self._processes()
            return b""
        if argv == target.systemd("start"):
            self.incarnation += 1
            self.unit.update(
                ActiveState="active",
                SubState="running",
                MainPID=str(4140 + self.incarnation),
                InvocationID=str(self.incarnation) * 32,
                ExecMainStartTimestampMonotonic=str(int(self.clock.value * 1_000_000)),
            )
            self._processes()
            self.source_cycle()
            self.next_cycle = self.clock.value + 61
            return b""
        if argv[0] == "/usr/bin/journalctl":
            if "--lines=1" in argv:
                return json.dumps(
                    {
                        key: self.rows[-1][key]
                        for key in ("__CURSOR", "_BOOT_ID", "__MONOTONIC_TIMESTAMP")
                    }
                ).encode()
            invocation = next(
                item.split("=", 1)[1] for item in argv if item.startswith("_SYSTEMD_INVOCATION_ID=")
            )
            rows = [row for row in self.rows if row["_SYSTEMD_INVOCATION_ID"] == invocation]
            boundary = next(
                (
                    item.split("native-cursor-", 1)[1]
                    for item in argv
                    if item.startswith("--after-cursor=")
                ),
                None,
            )
            if boundary is not None:
                rows = [row for row in rows if int(row["__CURSOR"].split("-")[-1]) > int(boundary)]
            return b"\n".join(json.dumps(row).encode() for row in rows[-64:])
        if argv[0] == self.scope.binding.sdk and argv[1:3] == ("-I", "-c"):
            self.http_calls = getattr(self, "http_calls", 0) + 1
            return b'{"status":200,"body":{"required_ok":true}}'
        raise AssertionError("unrecognized finite fake command " + str(argv))


class NativeBindingTests(FixedDevAdapterTests):
    # Inherited cases remain part of the original class; suppress duplicate
    # collection here while sharing only the confined fixture lifetime helpers.
    pass


for _method in [name for name in dir(FixedDevAdapterTests) if name.startswith("test_")]:
    setattr(NativeBindingTests, _method, None)


def _native(self):
    kernel = NativeKernel(self.h)
    custody = (PUBLIC / "scripts/probe_upgrade_operation.py").read_text()
    assembly = target.assemble_native(kernel.scope, kernel.dependencies, custody)
    self.addCleanup(assembly.files.close)
    return kernel, assembly


def test_typed_credential_metadata_qualifies_actual_unprintable_producer(self):
    kernel, assembly = _native(self)
    self.assertIn(
        b"LoadCredentialEncrypted=[unprintable]\n",
        manager_show(target.systemd("show"), kernel.unit),
    )
    raw = target.read_dev_unit(assembly.caller.run)
    unit = target.parse_unit(raw)
    target.normal_unit(unit, kernel.scope.binding)
    self.assertEqual(":".join(target.DEV_CREDENTIAL), unit["LoadCredentialEncrypted"])
    self.assertEqual(
        [target.systemd("show"), target.dev_credential_property()] * 2,
        [process.argv for process in kernel.processes],
    )
    self.assertFalse(any(path == kernel.scope.credential_source for path in kernel.os.opened))
    self.assertTrue(all(selector.closed for selector in kernel.selectors))
    self.assertTrue(all(process.returncode == 0 for process in kernel.processes))
    count = len(kernel.processes)
    getter = target.dev_credential_property()
    for argv, effect in (
        (getter, True),
        (getter[:-1] + ("SetCredentialEncrypted",), False),
        (tuple(part.replace("_40dev_", "_40prod_") for part in getter), False),
    ):
        with self.assertRaises(target.Refusal):
            assembly.caller.command.run(
                argv,
                timeout=1,
                limit=8192,
                effect=effect,
                original_handle=kernel.scope.handle.fingerprint,
            )
    self.assertEqual(count, len(kernel.processes))


def test_typed_credential_metadata_refuses_malformed_foreign_drift_and_lost_reads(self):
    expected = list(target.DEV_CREDENTIAL)
    values = {
        "null": None,
        "list": [],
        "missing_type": {"data": [expected]},
        "wrong_type": {"type": "as", "data": [expected]},
        "extra_field": {"type": "a(ss)", "data": [expected], "extra": True},
        "empty": {"type": "a(ss)", "data": []},
        "duplicate_row": {"type": "a(ss)", "data": [expected, expected]},
        "flat": {"type": "a(ss)", "data": expected},
        "mapping_row": {"type": "a(ss)", "data": [{"id": expected[0], "path": expected[1]}]},
        "extra_column": {"type": "a(ss)", "data": [[*expected, "extra"]]},
        "wrong_id": {"type": "a(ss)", "data": [["another-token", expected[1]]]},
        "wrong_channel": {
            "type": "a(ss)",
            "data": [[expected[0], expected[1].replace("/dev/", "/prod/")]],
        },
        "suffix_only": {"type": "a(ss)", "data": [[expected[0], "/foreign/dev/current"]]},
        "relative_path": {"type": "a(ss)", "data": [[expected[0], "dev/current"]]},
        "non_string": {"type": "a(ss)", "data": [[expected[0], True]]},
    }
    cases = list(values) + [
        "invalid_json",
        "duplicate_key",
        "oversized",
        "second_getter_drift",
        "profile_drift",
        "wrong_unit",
        "aliased_unit",
        "printable_mismatch",
        "getter_nonzero",
        "getter_deadline",
    ]
    for index, case in enumerate(cases):
        with self.subTest(case=case):
            if index:
                self.fresh()
            kernel, assembly = _native(self)
            before = dict(kernel.os.files)
            response = kernel.response
            reads = {"show": 0, "typed": 0}

            def metadata(argv, payload):
                if argv == target.systemd("show"):
                    reads["show"] += 1
                    if case == "profile_drift" and reads["show"] == 2:
                        kernel.unit["ProtectSystem"] = "full"
                    if case == "wrong_unit":
                        kernel.unit["Id"] = "yggdrasil-host-probe@prod.service"
                    if case == "aliased_unit":
                        kernel.unit["Names"] += " foreign.service"
                    raw = response(argv, payload)
                    if case == "printable_mismatch":
                        return raw.replace(b"[unprintable]", b"another-token:/foreign/dev/current")
                    return raw
                if argv != target.dev_credential_property():
                    return response(argv, payload)
                reads["typed"] += 1
                if case in values:
                    return json.dumps(values[case]).encode()
                if case == "invalid_json":
                    return b"not-json"
                if case == "duplicate_key":
                    return b'{"type":"a(ss)","type":"a(ss)","data":[]}'
                if case == "oversized":
                    return b" " * 8193
                if case == "second_getter_drift" and reads["typed"] == 2:
                    return json.dumps(values["wrong_channel"]).encode()
                if case == "getter_nonzero":
                    kernel.forced_returncodes = {argv: 1}
                if case == "getter_deadline":
                    kernel.clock.value = assembly.caller.deadline + 1
                return response(argv, payload)

            kernel.response = metadata
            with self.assertRaises((target.Refusal, target.Unknown)):
                target.DevProbeAdapter(
                    kernel.scope.binding, assembly.caller, assembly.files
                ).admit()
            self.assertEqual(before, kernel.os.files)
            self.assertEqual([], self.h.deliveries)
            self.assertFalse(
                any(
                    process.argv in {target.systemd("start"), target.systemd("stop")}
                    for process in kernel.processes
                )
            )
            self.assertFalse(
                any(path == kernel.scope.credential_source for path in kernel.os.opened)
            )
            self.assertTrue(all(selector.closed for selector in kernel.selectors))
            self.assertTrue(
                all(
                    pipe.closed
                    for process in kernel.processes
                    for pipe in (process.stdin, process.stdout, process.stderr)
                )
            )


def test_typed_credential_metadata_preserves_absence_and_owned_restart_cancellation(self):
    kernel, assembly = _native(self)
    absent = dict(kernel.unit)
    absent.update(
        LoadState="not-found",
        ActiveState="inactive",
        SubState="dead",
        MainPID="0",
        UnitFileState="",
        DropInPaths="",
        FragmentPath="",
        Job="",
        NRestarts="0",
    )
    kernel.unit = absent
    unit = target.parse_unit(target.read_dev_unit(assembly.caller.run), allow_absent=True)
    self.assertEqual("not-found", unit["LoadState"])
    self.assertEqual([target.systemd("show")], [process.argv for process in kernel.processes])

    self.fresh()
    kernel, assembly, guard = _armed_native_fault(self)
    incident = (self.root / "native-incident.json").read_bytes()
    kernel.unit.update(
        ActiveState="activating",
        SubState="auto-restart",
        MainPID="0",
        Job="41 /org/freedesktop/systemd1/job/41",
        NRestarts="1",
    )
    kernel._processes()
    response = kernel.response
    changed = []

    def advance_owned_job(argv, payload):
        raw = response(argv, payload)
        if argv == target.dev_credential_property() and not changed:
            changed.append(True)
            kernel.unit.update(
                ActiveState="active",
                SubState="running",
                MainPID="7777",
                Job="",
                InvocationID="7" * 32,
            )
            kernel._processes()
        return raw

    kernel.response = advance_owned_job
    result = target.cleanup_owned_dev_fault(assembly, guard.record)
    self.assertEqual("unknown", result["status"])
    self.assertEqual("0", kernel.unit["MainPID"])
    self.assertEqual(incident, (self.root / "native-incident.json").read_bytes())
    self.assertTrue(changed)


def test_actual_linux_reader_computes_fixed_child_stream_source_worker_health(self):
    kernel, assembly = _native(self)
    runtime = assembly.caller.read_runtime(kernel.scope.binding, health=True)
    runtime.qualify(
        kernel.scope.binding,
        assembly.caller,
        kernel.unit,
        target.sha(kernel.os.files[kernel.scope.binding.config]),
        active=True,
        health=True,
    )
    self.assertEqual("4141", runtime.creator.pid)
    self.assertEqual("4241", runtime.child.pid)
    self.assertEqual("9:223", runtime.heartbeat_backing)
    self.assertEqual(4, len(runtime.source_hashes))
    self.assertTrue(all(process.returncode == 0 for process in kernel.processes))
    self.assertTrue(all(selector.closed for selector in kernel.selectors))
    self.assertFalse(
        any(
            path == kernel.scope.credential_source or path.endswith("secret-runtime.env")
            for path in kernel.os.opened
        )
    )


def test_actual_native_assembly_runs_real_source_finite_pair_without_real_effects(self):
    kernel, assembly = _native(self)
    original = kernel.os.files[kernel.scope.binding.config]
    result = target.run_fixed_dev_worker(assembly, b"not-used-for-existing-active-dev", b"not-used")
    self.assertEqual((1, 1), (result["down"], result["recovery"]))
    self.assertGreaterEqual(result["completed_later_suppressions"], 2)
    self.assertEqual(original, kernel.os.files[kernel.scope.binding.config])
    self.assertEqual(2, len(self.h.deliveries))
    self.assertFalse(result["native_entry_enabled"])
    self.assertEqual(-1, kernel.dependencies.socket.created[0].fileno())
    self.assertEqual([], kernel.killed)
    self.assertTrue(
        all(
            pipe.closed
            for process in kernel.processes
            for pipe in (process.stdin, process.stdout, process.stderr)
        )
    )


def test_realistic_http_reader_is_qualified_but_unknown_descendant_refuses(self):
    kernel, assembly = _native(self)
    binding, group = kernel.scope.binding, kernel.unit["ControlGroup"]
    kernel._proc(
        "4341",
        "4241",
        (
            binding.sdk,
            "-I",
            "-c",
            target.HTTP_CHILD_CODE,
            binding.package + "/ops/host-setup/mac-mini",
        ),
        {},
        4341,
        group,
    )
    kernel.os.files["/sys/fs/cgroup" + group + "/cgroup.procs"] += b"4341\n"
    runtime = assembly.caller.read_runtime(binding)
    runtime.qualify(
        binding,
        assembly.caller,
        kernel.unit,
        target.sha(kernel.os.files[binding.config]),
        active=True,
    )
    self.assertEqual(("4341",), tuple(child.pid for child in runtime.http_children))
    kernel.os.files["/proc/4341/cmdline"] = b"python3\0unqualified.py\0"
    with self.assertRaises(target.Refusal):
        assembly.caller.read_runtime(binding)


def test_type_simple_missing_child_waits_bounded_without_accepting_descendant(self):
    kernel, assembly = _native(self)
    group = kernel.unit["ControlGroup"]
    real_response = kernel.response
    samples = [0]

    def pending_then_ready(argv, payload):
        if argv == target.systemd("show"):
            samples[0] += 1
            kernel.os.files["/sys/fs/cgroup" + group + "/cgroup.procs"] = (
                b"4141\n" if samples[0] < 4 else b"4141\n4241\n"
            )
        return real_response(argv, payload)

    kernel.response = pending_then_ready
    runtime = assembly.caller.read_runtime(kernel.scope.binding)
    self.assertIsNotNone(runtime.child)
    self.assertGreaterEqual(samples[0], 4)
    self.assertGreater(kernel.clock.value, 1000)


def test_controller_append_is_preserved_and_pending_or_truncated_history_refuses(self):
    kernel, assembly = _native(self)
    before = assembly.files.read("ack_history")
    operation = "11111111-1111-4111-8111-111111111111"
    prepared = {
        "operation_id": operation,
        "kind": "check",
        "target": "dev",
        "stage": "prepared",
        "source": None,
    }
    committed = dict(prepared, stage="committed", source="read-complete")
    path = kernel.scope.controller_directory + "/operations.jsonl"
    kernel.os.files[path] = (json.dumps(prepared) + "\n" + json.dumps(committed) + "\n").encode()
    after = assembly.files.read("ack_history")
    self.assertTrue(target.preserves(after, before))
    self.assertFalse(target.preserves(before, after))
    kernel.os.files[path] = (json.dumps(prepared) + "\n").encode()
    with self.assertRaises(target.Unknown):
        assembly.files.read("ack_history")


def test_fixed_supervisor_transport_and_actual_dispatcher_claim_shape(self):
    kernel, assembly = _native(self)
    command = target.supervisor_command(kernel.scope)
    self.assertIn("--property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", command)
    self.assertFalse(any("ReadWritePaths=" in arg and " /var/lib " in arg for arg in command))
    for managed_command in (command, target.watchdog_command(kernel.scope)):
        paths = next(
            arg.removeprefix("--property=ReadWritePaths=")
            for arg in managed_command
            if arg.startswith("--property=ReadWritePaths=")
        ).split()
        # Both producers must work when an absent canonical instance uses its
        # private staged config. Required scope/systemd parents stay mandatory.
        self.assertEqual(
            [kernel.scope.root, "/run/systemd/system", "-/etc/yggdrasil/host-probe"], paths
        )
    self.assertNotIn("-B", command)
    transport = target.strict_dev_transport(kernel.scope)
    self.assertIn("StrictHostKeyChecking=yes", transport)
    self.assertIn("ConnectionAttempts=1", transport)
    issue = json.dumps(
        {"number": 6505, "state": "open", "labels": [{"name": "agent:in-progress"}]}
    ).encode()
    task = json.dumps(
        {
            "ok": True,
            "task": {
                "issue_number": 6505,
                "status": "claimed",
                "claimed_by": "holder",
                "lease_id": "lease",
                "lease_expires_at": "2100-01-01T00:00:00Z",
            },
        }
    ).encode()
    target.assert_local_authority(
        kernel.scope,
        issue=issue,
        task=task,
        git_head=b"a" * 40,
        git_status=b"",
        expected_head="a" * 40,
        epoch_seconds=kernel.clock.epoch,
    )
    with self.assertRaises(target.Refusal):
        target.assert_local_authority(
            kernel.scope,
            issue=issue,
            task=task,
            git_head=b"a" * 40,
            git_status=b" M unreviewed",
            expected_head="a" * 40,
            epoch_seconds=kernel.clock.epoch,
        )


def test_first_accepted_preflight_derives_actual_compose_mapping_not_defaults(self):
    kernel, assembly = _native(self)
    original = kernel.response
    docker = DockerDiscoveryProducer()

    def response(argv, payload):
        if argv[0] == "/usr/bin/docker":
            return docker(argv)
        return original(argv, payload)

    kernel.response = response
    facts = target.discover_fixed_dev_producer(
        kernel.dependencies,
        (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
        deadline=1100,
    )
    self.assertEqual(
        kernel.scope.binding.api_base.replace("synthetic-dev-api.invalid", "127.0.0.1"),
        facts["api_base"],
    )
    self.assertEqual(kernel.scope.binding.heartbeat, facts["heartbeat_host_path"])
    self.assertEqual(kernel.scope.binding.worker_start, facts["worker_start"])
    self.assertEqual("9:223", facts["heartbeat_backing"])
    self.assertEqual("observed-dev-project", facts["producer_route"].split(":", 1)[1])
    self.assertIsNone(facts["actual_vm_id"], "inventory VM100 is only a proposal")
    docker.containers[1]["Config"]["Env"][0] = "PKM_ENVIRONMENT=prod"
    with self.assertRaises(target.Refusal):
        target.discover_fixed_dev_producer(
            kernel.dependencies,
            (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
            deadline=1100,
        )


def test_discovery_uses_actual_docker_projection_and_refuses_unsupported_bindings(self):
    cases = (
        "normal_with_unrelated_containers",
        "revision_label_absent",
        "worker_stopped",
        "worker_foreign_project",
        "two_matching_workers",
        "malformed_worker_list_id",
        "short_inspect_id",
        "heartbeat_setting_absent",
        "heartbeat_setting_duplicated",
        "worker_wrong_channel",
        "different_candidate_image",
        "dual_stack_publication",
        "unpublished_api",
        "ambiguous_heartbeat_mount",
    )
    for index, case in enumerate(cases):
        with self.subTest(case=case):
            if index:
                self.fresh()
            kernel, assembly = _native(self)
            docker = DockerDiscoveryProducer()
            api, worker = docker.containers
            expected = target.Refusal
            if case == "normal_with_unrelated_containers":
                foreign = json.loads(json.dumps(worker))
                foreign["Id"] = "d" * 64
                foreign["Config"]["Labels"]["com.docker.compose.project"] = "another-project"
                stopped = json.loads(json.dumps(worker))
                stopped["Id"], stopped["State"]["Running"] = "e" * 64, False
                docker.containers.extend((foreign, stopped))
                expected = None
            elif case == "revision_label_absent":
                for row in docker.containers:
                    del row["Config"]["Labels"]["org.opencontainers.image.revision"]
                expected = None
            elif case == "worker_stopped":
                worker["State"]["Running"] = False
            elif case == "worker_foreign_project":
                worker["Config"]["Labels"]["com.docker.compose.project"] = "another-project"
            elif case == "two_matching_workers":
                second = json.loads(json.dumps(worker))
                second["Id"] = "d" * 64
                docker.containers.append(second)
            elif case == "malformed_worker_list_id":
                worker["Id"] = "z" * 64
            elif case == "short_inspect_id":
                worker["Id"] = "b" * 12
            elif case == "heartbeat_setting_absent":
                worker["Config"]["Env"] = ["PKM_ENVIRONMENT=dev"]
                expected = json.JSONDecodeError
            elif case == "heartbeat_setting_duplicated":
                worker["Config"]["Env"].append("WORKER_HEARTBEAT_PATH=/runtime/producer.json")
                expected = json.JSONDecodeError
            elif case == "worker_wrong_channel":
                worker["Config"]["Env"][0] = "PKM_ENVIRONMENT=prod"
            elif case == "different_candidate_image":
                worker["Image"] = "sha256:" + "d" * 64
            elif case == "dual_stack_publication":
                api["NetworkSettings"]["Ports"]["8000/tcp"].append(
                    {"HostIp": "::", "HostPort": "47777"}
                )
            elif case == "unpublished_api":
                api["NetworkSettings"]["Ports"]["8000/tcp"] = None
            elif case == "ambiguous_heartbeat_mount":
                worker["Mounts"].append(
                    {"Source": "/var/lib/another-backing", "Destination": "/runtime"}
                )
            response, before = kernel.response, dict(kernel.os.files)

            def ports(argv, payload):
                return docker(argv) if argv[0] == "/usr/bin/docker" else response(argv, payload)

            def discover():
                return target.discover_fixed_dev_producer(
                    kernel.dependencies,
                    (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
                    deadline=1100,
                )

            kernel.response = ports
            if expected is None:
                facts = discover()
                self.assertEqual("http://127.0.0.1:47777", facts["api_base"])
                self.assertEqual(
                    ["a" * 64, "b" * 64], [r[1] for r in facts["candidate_references"]]
                )
                self.assertEqual(
                    ["a" * 12, "b" * 12],
                    [argv[-1] for argv in docker.calls if argv[1] == "inspect"],
                )
            else:
                with self.assertRaises(expected):
                    discover()
            self.assertIn(
                (
                    "/usr/bin/docker",
                    "ps",
                    "--filter",
                    "label=com.docker.compose.service=worker",
                    "--filter",
                    "label=com.docker.compose.project=observed-dev-project",
                    "--format",
                    "{{.ID}}",
                ),
                docker.calls,
            )
            self.assertEqual(before, kernel.os.files)
            self.assertFalse(any(p.argv[0] == "/usr/bin/systemd-run" for p in kernel.processes))
            self.assertFalse(
                any(
                    p.argv in {target.systemd("start"), target.systemd("stop")}
                    for p in kernel.processes
                )
            )


def test_discovery_qualifies_exact_ipv4_and_matching_wildcard_pair_from_raw_inspect(self):
    def row(address, port="47777"):
        return {"HostIp": address, "HostPort": port}

    cases = (
        ("loopback", [row("127.0.0.1")], True),
        ("wildcard", [row("0.0.0.0")], True),
        ("wildcard_pair", [row("0.0.0.0"), row("::")], True),
        ("wildcard_pair_reversed", [row("::"), row("0.0.0.0")], True),
        ("minimum_port", [row("0.0.0.0", "1"), row("::", "1")], True),
        ("maximum_port", [row("0.0.0.0", "65535"), row("::", "65535")], True),
        ("missing", None, False),
        ("empty", [], False),
        ("mapping", row("0.0.0.0"), False),
        ("null_row", [None], False),
        ("string_row", ["0.0.0.0:47777"], False),
        ("missing_address", [{"HostPort": "47777"}], False),
        ("missing_port", [{"HostIp": "0.0.0.0"}], False),
        ("extra_field", [dict(row("0.0.0.0"), Unexpected="value")], False),
        ("object_address", [row({"address": "0.0.0.0"})], False),
        ("integer_port", [row("0.0.0.0", 47777)], False),
        ("boolean_port", [row("0.0.0.0", True)], False),
        ("leading_zero", [row("0.0.0.0", "047777")], False),
        ("unicode_digits", [row("0.0.0.0", "４７７７７")], False),
        ("space_port", [row("0.0.0.0", "47777 ")], False),
        ("plus_port", [row("0.0.0.0", "+47777")], False),
        ("zero_port", [row("0.0.0.0", "0")], False),
        ("overflow_port", [row("0.0.0.0", "65536")], False),
        ("ipv6_only", [row("::")], False),
        ("ipv6_loopback", [row("::1")], False),
        ("loopback_and_ipv6", [row("127.0.0.1"), row("::")], False),
        ("foreign_ipv4", [row("192.0.2.7")], False),
        ("two_ipv4", [row("127.0.0.1"), row("0.0.0.0")], False),
        ("duplicate_ipv4", [row("0.0.0.0"), row("0.0.0.0")], False),
        ("duplicate_ipv6", [row("::"), row("::")], False),
        ("three_rows", [row("0.0.0.0"), row("::"), row("::")], False),
        ("different_ports", [row("0.0.0.0"), row("::", "47778")], False),
    )
    for index, (name, published, accepted) in enumerate(cases):
        with self.subTest(publication=name):
            if index:
                self.fresh()
            kernel = NativeKernel(self.h)
            docker = DockerDiscoveryProducer()
            docker.containers[0]["NetworkSettings"]["Ports"]["8000/tcp"] = published
            response, before = kernel.response, dict(kernel.os.files)
            kernel.response = lambda argv, payload: (
                docker(argv) if argv[0] == "/usr/bin/docker" else response(argv, payload)
            )

            def discover():
                return target.discover_fixed_dev_producer(
                    kernel.dependencies,
                    (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
                    deadline=1100,
                )

            if accepted:
                facts = discover()
                self.assertEqual("http://127.0.0.1:" + published[0]["HostPort"], facts["api_base"])
            else:
                with self.assertRaisesRegex(
                    target.Refusal, "actual_dev_api_publication_ambiguous_or_unsupported"
                ):
                    discover()
            self.assertEqual(2, sum(argv[1] == "inspect" for argv in docker.calls))
            self.assertEqual(before, kernel.os.files)
            self.assertFalse(any(p.argv[0] == "/usr/bin/systemd-run" for p in kernel.processes))
            self.assertFalse(
                any(
                    p.argv in {target.systemd("start"), target.systemd("stop")}
                    for p in kernel.processes
                )
            )
            self.assertFalse(kernel.os.fds)
            self.assertTrue(all(selector.closed for selector in kernel.selectors))


class MappedNativeOS:
    """Privileged syscall boundary mapped only into one real private fixture."""

    def __init__(self, root, scope):
        self.root, self.scope, self.path = (
            root,
            scope,
            SimpleNamespace(realpath=lambda _: scope.binding.sdk_realpath),
        )

    def __getattr__(self, name):
        return getattr(os, name)

    def mapped(self, path):
        if not path.startswith("/"):
            raise AssertionError("relative path requires retained dir_fd")
        return str(self.root / path.lstrip("/"))

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        return os.open(
            self.mapped(path) if path.startswith("/") else path, flags, mode, dir_fd=dir_fd
        )

    def root_meta(self, info):
        fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
        fields.update(st_uid=0, st_gid=0)
        return SimpleNamespace(**fields)

    def fstat(self, fd):
        return self.root_meta(os.fstat(fd))

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        return self.root_meta(
            os.stat(
                self.mapped(path) if isinstance(path, str) and path.startswith("/") else path,
                dir_fd=dir_fd,
                follow_symlinks=follow_symlinks,
            )
        )

    def listxattr(self, descriptor):
        return []

    def readlink(self, path, **kwargs):
        if path == "/proc/self/ns/net":
            return self.scope.binding.net_namespace
        if path == "/proc/self/exe":
            return self.scope.binding.sdk_realpath
        return os.readlink(self.mapped(path) if path.startswith("/") else path, **kwargs)


def test_native_factory_uses_real_confined_atomic_files_and_private_scope_checks(self):
    kernel = NativeKernel(self.h)
    mapped_root = self.root / "mapped-native-root"
    mapped_root.mkdir(mode=0o700)
    api = MappedNativeOS(mapped_root, kernel.scope)
    for path, data in (
        (kernel.scope.root + "/request.json", kernel.scope.request_bytes),
        (kernel.scope.root + "/program.py", b"frozen-program"),
        (kernel.scope.binding.config, kernel.os.files[kernel.scope.binding.config]),
    ):
        physical = Path(api.mapped(path))
        physical.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        physical.write_bytes(data)
        physical.chmod(0o600)
    Path(api.mapped(kernel.scope.root)).chmod(0o700)
    dependencies = replace(kernel.dependencies, os=api)
    assembly = target.assemble_native(
        kernel.scope, dependencies, (PUBLIC / "scripts/probe_upgrade_operation.py").read_text()
    )
    try:
        original = assembly.files.read("config")
        fault = original.data.replace(
            kernel.scope.binding.api_base.encode(), b"http://127.0.0.1:43891"
        )
        changed = assembly.files.atomic_config(original, fault)
        self.assertNotEqual(original.inode, changed.inode)
        restored = assembly.files.atomic_config(changed, original.data, restore=original)
        self.assertEqual(
            (original.data, original.mode, original.uid, original.gid, original.mtime_ns),
            (restored.data, restored.mode, restored.uid, restored.gid, restored.mtime_ns),
        )
        self.assertFalse(
            any(
                path.name.startswith(".owned-dev-config-")
                for path in Path(api.mapped(kernel.scope.binding.config)).parent.iterdir()
            )
        )
    finally:
        assembly.files.close()
    Path(api.mapped(kernel.scope.root)).chmod(0o770)
    with self.assertRaises(target.Refusal):
        target.assemble_native(
            kernel.scope, dependencies, (PUBLIC / "scripts/probe_upgrade_operation.py").read_text()
        )


def test_native_command_custody_and_original_transport_submission_are_nonreplayable(self):
    kernel, assembly = _native(self)
    transport = target.FixedDevTransport(kernel.scope, assembly.caller.command)
    original = kernel.response
    kernel.response = (
        lambda argv, payload: b'{"status":"unbound"}'
        if argv[0] == "/usr/bin/ssh"
        else original(argv, payload)
    )
    checked = []
    result = transport.submit(
        b"frozen-program",
        timeout=20,
        authority_read=lambda: checked.append("actual-normal-authority-port"),
    )
    self.assertEqual(b'{"status":"unbound"}', result)
    self.assertEqual(["actual-normal-authority-port"], checked)
    with self.assertRaises(target.Refusal):
        transport.submit(b"frozen-program", timeout=20, authority_read=lambda: None)
    self.assertTrue(all(process.returncode == 0 for process in kernel.processes))
    self.assertTrue(
        all(
            pipe.closed
            for process in kernel.processes
            for pipe in (process.stdin, process.stdout, process.stderr)
        )
    )
    with self.assertRaises(target.Refusal):
        assembly.caller.command.run(
            ("/usr/bin/systemctl", "stop", "yggdrasil-host-probe@prod.service"),
            timeout=1,
            limit=100,
            effect=True,
            original_handle=kernel.scope.handle.fingerprint,
        )


def test_guard_quiesces_only_owned_fault_and_restores_config_without_state_rewind(self):
    kernel, assembly = _native(self)
    adapter = target.DevProbeAdapter(kernel.scope.binding, assembly.caller, assembly.files)
    adapter.admit()
    guard = target.NativeFaultGuard(assembly, adapter)
    guard.arm()
    url = adapter.reserve_fault()
    guard.fault_intent(url)
    original = target.parse_config(assembly.files.read("config").data)
    adapter.stop_owned()
    adapter.swap_base_url()
    adapter.start_owned()
    incident = (self.root / "native-incident.json").read_bytes()
    fresh = target.assemble_native(
        kernel.scope,
        kernel.dependencies,
        (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
    )
    try:
        result = target.cleanup_owned_dev_fault(fresh, guard.record)
        self.assertEqual("unknown", result["status"])
        self.assertEqual("inactive", kernel.unit["ActiveState"])
        self.assertEqual(original, target.parse_config(fresh.files.read("config").data))
        self.assertEqual(incident, (self.root / "native-incident.json").read_bytes())
        self.assertFalse(result["history_rewound"])
    finally:
        fresh.files.close()


def test_guard_refuses_foreign_incarnation_and_retains_original_fault_handle(self):
    kernel, assembly = _native(self)
    adapter = target.DevProbeAdapter(kernel.scope.binding, assembly.caller, assembly.files)
    adapter.admit()
    guard = target.NativeFaultGuard(assembly, adapter)
    guard.arm()
    url = adapter.reserve_fault()
    guard.fault_intent(url)
    adapter.stop_owned()
    adapter.swap_base_url()
    adapter.start_owned()
    kernel.unit["MainPID"] = "6000"
    kernel.unit["InvocationID"] = "9" * 32
    kernel._processes()
    kernel.os.files["/proc/6000/environ"] = b"CREDENTIALS_DIRECTORY=/run/credentials/dev\0"
    effects = len(
        [process for process in kernel.processes if process.argv == target.systemd("stop")]
    )
    fresh = target.assemble_native(
        kernel.scope,
        kernel.dependencies,
        (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
    )
    try:
        with self.assertRaisesRegex(target.Unknown, "foreign_incarnation"):
            target.cleanup_owned_dev_fault(fresh, guard.record)
        self.assertEqual(
            effects,
            len(
                [process for process in kernel.processes if process.argv == target.systemd("stop")]
            ),
        )
        self.assertEqual("active", kernel.unit["ActiveState"])
        self.assertEqual(kernel.scope.handle.fingerprint, fresh.caller.original_handle)
    finally:
        fresh.files.close()


def test_actual_local_caller_executes_serialized_dataclass_envelope_with_absolute_tools_and_home(
    self,
):
    import contextlib, io
    from datetime import datetime, timezone

    kernel, assembly = _native(self)
    program = fixture_program()
    contract = b"fixed reviewed issue6505"
    packet = {
        "schema": "fixed_dev_probe.carrier.v1",
        "issue": 6505,
        "operation": "1" * 32,
        "namespace": "e" * 32,
        "reviewed_head": "f" * 40,
        "program_sha256": target.sha(program),
        "issue_body_sha256": target.sha(contract),
        "lease_id": "lease-260f32b2",
        "keeper_standing_reference": "synthetic-reviewed-window",
        "window_start_utc": datetime.fromtimestamp(
            kernel.clock.epoch - 1, timezone.utc
        ).isoformat(),
        "window_end_utc": datetime.fromtimestamp(
            kernel.clock.epoch + 1799, timezone.utc
        ).isoformat(),
        "bootstrap_interpreter": "/usr/bin/python3",
        "local_fence_references": list(kernel.scope.local_fence_references),
        "normal_interval_seconds": 61,
        "heartbeat_stale_seconds": 601,
        "gh_executable": "/opt/homebrew/bin/gh",
        "caller_interpreter": sys.executable,
    }
    kernel.os.add(target.LOCAL_DEV_PROGRAM, program, mode=0o644)
    for path in (packet["gh_executable"], packet["caller_interpreter"]):
        kernel.os.add(path, b"qualified existing local tool", mode=0o755)
    original = kernel.response
    executed = []
    authority = {
        "ok": True,
        "task": {
            "task_id": target.LOCAL_DEV_TASK,
            "repo": "RasmusTho/agentic-pkm-mvp",
            "issue_number": 6505,
            "status": "claimed",
            "claimed_by": target.LOCAL_DEV_HOLDER,
            "lease_id": packet["lease_id"],
            "lease_expires_at": "2100-01-01T00:00:00Z",
        },
        "lease": {
            "lease_id": packet["lease_id"],
            "resource": "issue:6505",
            "holder": target.LOCAL_DEV_HOLDER,
            "expires_at": "2100-01-01T00:00:00Z",
            "released_at": None,
        },
    }
    registry = {
        target.LOCAL_DEV_WORKTREE: {
            "status": "active",
            "path": target.LOCAL_DEV_WORKTREE,
            "branch": target.LOCAL_DEV_BRANCH,
            "owner": target.LOCAL_DEV_SESSION,
            "generation": "7" * 32,
            "expires_at": kernel.clock.epoch + 7200,
        }
    }

    def response(argv, payload):
        if argv[:3] == ("/usr/bin/git", "-C", target.LOCAL_DEV_WORKTREE):
            args = argv[3:]
            return {
                ("rev-parse", "HEAD"): b"f" * 40 + b"\n",
                ("status", "--porcelain"): b"",
                ("branch", "--show-current"): target.LOCAL_DEV_BRANCH.encode() + b"\n",
                ("rev-parse", "--show-toplevel"): target.LOCAL_DEV_WORKTREE.encode() + b"\n",
                ("show", "HEAD:scripts/probe_dev_outage_operation.py"): program,
            }[args]
        if argv[0] == packet["gh_executable"]:
            return json.dumps(
                {
                    "number": 6505,
                    "state": "open",
                    "labels": [{"name": "agent:in-progress"}],
                    "body": contract.decode(),
                }
            ).encode()
        if argv[0] == packet["caller_interpreter"]:
            return json.dumps(
                registry if "load_lifecycle_authority" in argv[2] else authority
            ).encode()
        if argv[0] == "/usr/bin/ssh":
            self.assertIn(b"sys.modules[m.__name__]=m", payload)
            # The real serialized DEV program must reject the TEST target.
            # Only the external host's observed hostname is changed.
            kernel.os.files["/proc/sys/kernel/hostname"] = b"ygg-test\n"
            output = execute_serialized_program(payload, kernel.dependencies)
            executed.append(json.loads(output))
            return output
        return original(argv, payload)

    kernel.response = response
    archive, manifest, _ = fixture_source()
    inputs = target.LOCAL_DEV_WORKTREE + "/.codex-tmp/portable-caller"
    for name, content in (
        ("source.tar", archive),
        ("manifest.json", manifest),
        ("custody.py", (PUBLIC / "scripts/probe_upgrade_operation.py").read_bytes()),
    ):
        kernel.os.add(inputs + "/" + name, content)

    def invoke(selected=None):
        kernel.os.add(inputs + "/request.json", json.dumps(selected or packet).encode())
        output = io.StringIO()
        with (
            patch.object(
                target.LinuxDependencies, "standard_library", return_value=kernel.dependencies
            ),
            contextlib.redirect_stdout(output),
        ):
            result = target.main(
                [
                    "--request",
                    inputs + "/request.json",
                    "--archive",
                    inputs + "/source.tar",
                    "--manifest",
                    inputs + "/manifest.json",
                    "--custody-source",
                    inputs + "/custody.py",
                ]
            )
        self.assertEqual(78, result)
        return output.getvalue().encode()

    result = invoke()
    value = json.loads(result)
    self.assertEqual("fixed_dev_probe.outcome.v1", value["schema"])
    self.assertEqual(packet["operation"], value["operation"])
    self.assertEqual(
        ("REFUSED", "bootstrap_guest_not_fixed_dev"), (value["status"], value["reason"])
    )
    self.assertEqual(1, len(executed))
    gh = [process for process in kernel.processes if process.argv[0] == packet["gh_executable"]]
    self.assertEqual(kernel.os.environ["HOME"], gh[0].environment["HOME"])
    ssh = [process for process in kernel.processes if process.argv[0] == "/usr/bin/ssh"]
    self.assertEqual(1, len(ssh))
    self.assertNotIn("GH_TOKEN", ssh[0].environment)
    self.assertFalse(any(process.argv[0] == "/usr/bin/systemd-run" for process in kernel.processes))
    for surface, key, value in (
        (authority["task"], "claimed_by", "former-holder"),
        (authority["task"], "task_id", "github-foreign-issue-6505"),
        (authority["lease"], "resource", "issue:1"),
        (authority["lease"], "released_at", "2026-10-30T00:00:00Z"),
        (authority["lease"], "expires_at", "2000-01-01T00:00:00Z"),
        (registry[target.LOCAL_DEV_WORKTREE], "owner", "former-session"),
        (registry[target.LOCAL_DEV_WORKTREE], "status", "released"),
        (registry[target.LOCAL_DEV_WORKTREE], "generation", ""),
        (registry[target.LOCAL_DEV_WORKTREE], "expires_at", 1),
    ):
        with self.subTest(authority_key=key, value=value):
            previous, surface[key] = surface[key], value
            with self.assertRaises(target.Refusal):
                invoke()
            surface[key] = previous
            self.assertEqual(
                1,
                len([process for process in kernel.processes if process.argv[0] == "/usr/bin/ssh"]),
            )
    for changed, expected in (
        ({"schema": "fixed_test_probe.carrier.v1"}, "carrier_packet_shape"),
        ({"issue": 6493}, "carrier_packet_shape"),
        ({"namespace": "../foreign"}, "carrier_reviewed_identity_unbound"),
        (
            {"caller_interpreter": "/foreign/python3"},
            "actual_local_caller_entry_cwd_or_interpreter_unbound",
        ),
    ):
        with self.subTest(packet=changed):
            with self.assertRaisesRegex(target.Refusal, expected):
                invoke(dict(packet, **changed))
    imported_program = target.__file__
    for foreign in ("cwd", "module", "program"):
        with self.subTest(actual_entry=foreign):
            original_program = kernel.os.files[target.LOCAL_DEV_PROGRAM]
            kernel.os.current_directory = (
                "/foreign" if foreign == "cwd" else target.LOCAL_DEV_WORKTREE
            )
            if foreign == "program":
                kernel.os.files[target.LOCAL_DEV_PROGRAM] += b"# unreviewed change\n"
            before = len(kernel.processes)
            with patch.object(
                target,
                "__file__",
                "/foreign/program.py" if foreign == "module" else imported_program,
            ):
                with self.assertRaises(target.Refusal):
                    invoke()
            self.assertEqual(before, len(kernel.processes))
            kernel.os.files[target.LOCAL_DEV_PROGRAM] = original_program
            kernel.os.current_directory = target.LOCAL_DEV_WORKTREE
    for path, key, value in (
        (target.LOCAL_DEV_PROGRAM, "st_uid", 12345),
        (target.LOCAL_DEV_PROGRAM, "st_mode", stat.S_IFREG | 0o664),
        (packet["caller_interpreter"], "st_mode", stat.S_IFREG | 0o775),
    ):
        with self.subTest(entry_metadata=key, path=path):
            metadata = kernel.os.meta[path]
            previous = getattr(metadata, key)
            setattr(metadata, key, value)
            before = len(kernel.processes)
            with self.assertRaisesRegex(target.Refusal, "actual_local_caller_.*metadata"):
                invoke()
            self.assertEqual(before, len(kernel.processes))
            setattr(metadata, key, previous)
    for change in ("source", "same_bytes_replacement", "interpreter_replacement", "cwd"):
        with self.subTest(after_authority=change):
            script_inode = kernel.os.meta[target.LOCAL_DEV_PROGRAM].st_ino
            tool_inode = kernel.os.meta[packet["caller_interpreter"]].st_ino

            def replace_after_authority(argv, payload):
                result = response(argv, payload)
                if (
                    argv[0] == packet["caller_interpreter"]
                    and "load_lifecycle_authority" in argv[2]
                ):
                    if change == "source":
                        kernel.os.files[target.LOCAL_DEV_PROGRAM] = b"changed after local admission"
                    elif change == "same_bytes_replacement":
                        kernel.os.meta[target.LOCAL_DEV_PROGRAM].st_ino += 1
                    elif change == "interpreter_replacement":
                        kernel.os.meta[packet["caller_interpreter"]].st_ino += 1
                    else:
                        kernel.os.current_directory = "/changed-after-authority"
                return result

            kernel.response = replace_after_authority
            with self.assertRaises(target.Refusal):
                invoke()
            self.assertEqual(1, len([p for p in kernel.processes if p.argv[0] == "/usr/bin/ssh"]))
            kernel.os.files[target.LOCAL_DEV_PROGRAM] = program
            kernel.os.meta[target.LOCAL_DEV_PROGRAM].st_ino = script_inode
            kernel.os.meta[packet["caller_interpreter"]].st_ino = tool_inode
            kernel.os.current_directory = target.LOCAL_DEV_WORKTREE
    kernel.response = response
    close = kernel.os.close

    def lost_entry_close(descriptor):
        path = kernel.os.fds[descriptor][0]
        close(descriptor)
        if path == target.LOCAL_DEV_PROGRAM:
            raise OSError("synthetic caller descriptor close loss")

    before = len(kernel.processes)
    kernel.os.close = lost_entry_close
    with self.assertRaises(OSError):
        invoke()
    self.assertEqual(before, len(kernel.processes))
    kernel.os.close = close
    read, epoch, monotonic = kernel.os.read, kernel.clock.epoch, kernel.clock.value

    def exhaust_entry_budget(descriptor, count):
        value = read(descriptor, count)
        if kernel.os.fds[descriptor][0] == target.LOCAL_DEV_PROGRAM:
            kernel.clock.advance(1800)
        return value

    kernel.os.read = exhaust_entry_budget
    with self.assertRaisesRegex(target.Unknown, "whole_local_caller_entry_budget"):
        invoke()
    self.assertEqual(before, len(kernel.processes))
    kernel.os.read = read
    kernel.clock.epoch, kernel.clock.value = epoch, monotonic
    self.assertEqual(1, len([p for p in kernel.processes if p.argv[0] == "/usr/bin/ssh"]))
    assembly.files.close()
    self.assertFalse(kernel.os.fds)
    sys.modules.pop("fixed_dev_program", None)


def test_core_observations_cannot_satisfy_live_receipt_without_native_custody(self):
    kernel, assembly = _native(self)
    archive, _, _ = fixture_source()
    observations = target.run_fixed_dev_worker(
        assembly, archive, b"not used by owned active instance"
    )
    observations["operation"] = kernel.scope.handle.operation
    observations["request_sha256"] = target.sha(kernel.scope.request_bytes)
    self.assertFalse(observations["live_acceptance"])
    with self.assertRaisesRegex(target.Unknown, "native_completed_evidence_unqualified"):
        target.native_completion_receipt(observations, {"operation": kernel.scope.handle.operation})
    self.assertFalse(observations["live_acceptance"])


def _armed_native_fault(self):
    kernel, assembly = _native(self)
    adapter = target.DevProbeAdapter(kernel.scope.binding, assembly.caller, assembly.files)
    adapter.admit()
    guard = target.NativeFaultGuard(assembly, adapter)
    guard.arm()
    url = adapter.reserve_fault()
    guard.fault_intent(url)
    adapter.stop_owned()
    adapter.swap_base_url()
    adapter.start_owned()
    return kernel, assembly, guard


def test_guard_contains_the_owned_systemd_lifecycle_and_cancels_queued_restarts(self):
    rows = [
        ("activating", "auto-restart", False, "41 /org/freedesktop/systemd1/job/41"),
        ("activating", "start", True, "42 /org/freedesktop/systemd1/job/42"),
        ("deactivating", "stop-sigterm", True, "43 /org/freedesktop/systemd1/job/43"),
        ("reloading", "reload", True, "44 /org/freedesktop/systemd1/job/44"),
        ("failed", "failed", False, ""),
        ("inactive", "dead", False, ""),
    ]
    for index, (state, substate, live, job) in enumerate(rows):
        with self.subTest(state=state, substate=substate):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            saved_incident = (self.root / "native-incident.json").read_bytes()
            kernel.unit.update(ActiveState=state, SubState=substate, Job=job, NRestarts="1")
            if not live:
                kernel.unit["MainPID"] = "0"
                kernel._processes()
            before = sum(process.argv == target.systemd("stop") for process in kernel.processes)
            result = target.cleanup_owned_dev_fault(assembly, guard.record)
            self.assertEqual(
                ("unknown", "failed" if state == "failed" else "inactive", "0", ""),
                (
                    result["status"],
                    kernel.unit["ActiveState"],
                    kernel.unit["MainPID"],
                    kernel.unit["Job"],
                ),
            )
            self.assertEqual(
                before + int(state not in {"inactive", "failed"}),
                sum(process.argv == target.systemd("stop") for process in kernel.processes),
            )
            self.assertEqual(saved_incident, (self.root / "native-incident.json").read_bytes())
            self.assertEqual(
                guard.record["config"]["data"],
                __import__("base64").b64encode(assembly.files.read("config").data).decode(),
            )


def test_actual_watchdog_handles_helper_death_during_automatic_restart(self):
    kernel, assembly, guard = _armed_native_fault(self)
    incident = (self.root / "native-incident.json").read_bytes()
    kernel.unit.update(
        ActiveState="activating",
        SubState="auto-restart",
        MainPID="0",
        NRestarts="1",
        Job="46 /org/freedesktop/systemd1/job/46",
    )
    kernel._processes()
    helper_stat = "/proc/" + guard.record["helper_pid"] + "/stat"
    kernel.os.files.pop(helper_stat, None)
    kernel.os.meta.pop(helper_stat, None)
    result = target.watch_dev_operation(kernel.scope.root, kernel.dependencies)
    self.assertEqual("unknown", result["status"])
    self.assertTrue(result["owned_dev_stopped"])
    self.assertEqual(
        ("inactive", "0", ""),
        (kernel.unit["ActiveState"], kernel.unit["MainPID"], kernel.unit["Job"]),
    )
    self.assertEqual(incident, (self.root / "native-incident.json").read_bytes())
    self.assertIn(kernel.scope.root + "/watchdog-result.json", kernel.os.files)


def test_guard_refuses_foreign_config_or_physical_marker_before_stopping(self):
    for index, drift in enumerate(("config", "marker")):
        with self.subTest(drift=drift):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            if drift == "config":
                kernel.os.files[kernel.scope.binding.config] = b"unowned configuration"
            else:
                marker = guard.parent_path + "/" + guard.marker
                kernel.os.files[marker] = b"[Service]\nEnvironment=YGG_DEV_OPERATION=foreign\n"
            before = sum(process.argv == target.systemd("stop") for process in kernel.processes)
            with self.assertRaisesRegex(target.Unknown, "guard_refuses_unowned"):
                target.cleanup_owned_dev_fault(assembly, guard.record)
            self.assertEqual(
                before, sum(process.argv == target.systemd("stop") for process in kernel.processes)
            )
            self.assertEqual("active", kernel.unit["ActiveState"])


def _remote_boundary(outcome, *, guest="ygg-dev"):
    """Actual bootstrap/CLI; only kernel, clock and systemd/Docker ports fake."""
    import base64
    import signal
    import selectors
    import subprocess
    from datetime import datetime, timezone

    archive, manifest, _ = fixture_source()
    program = Path(target.__file__).read_bytes()
    packet = {
        "schema": "fixed_dev_probe.carrier.v1",
        "issue": 6505,
        "operation": "1" * 32,
        "namespace": "2" * 32,
        "reviewed_head": "3" * 40,
        "program_sha256": target.sha(program),
        "issue_body_sha256": "4" * 64,
        "lease_id": "synthetic",
        "keeper_standing_reference": "synthetic-window",
        "window_start_utc": datetime.fromtimestamp(900, timezone.utc).isoformat(),
        "window_end_utc": datetime.fromtimestamp(1900, timezone.utc).isoformat(),
        "bootstrap_interpreter": "/usr/bin/python3",
        "local_fence_references": [["original5b47", "5" * 64], ["successor329", "6" * 64]],
        "normal_interval_seconds": 60,
        "heartbeat_stale_seconds": 60,
        "gh_executable": "/opt/homebrew/bin/gh",
        "caller_interpreter": "/usr/bin/python3",
    }
    envelope = {
        "packet": packet,
        "program": base64.b64encode(program).decode(),
        "archive": base64.b64encode(archive).decode(),
        "manifest": base64.b64encode(manifest).decode(),
        "custody_source": (PUBLIC / "scripts/probe_upgrade_operation.py").read_text(),
    }
    root = "/var/lib/ygg-dev-probe-" + packet["namespace"]
    unit = "yggdrasil-dev-probe-" + packet["operation"] + ".service"
    k = SimpleNamespace(
        scope=SimpleNamespace(
            binding=SimpleNamespace(state_file="/unused-state", sdk_realpath="/unused-sdk")
        ),
        processes=[],
        reaped=[],
        killed=[],
        calls=[],
        forced_returncodes={},
    )
    k.os = MemoryLinuxOS(k)
    k.os.add("/var/lib", directory=True, mode=0o755)
    k.os.add("/proc/sys/kernel/hostname", (guest + "\n").encode(), mode=0o444)
    k.os.add("/etc/machine-id", b"d" * 32 + b"\n", mode=0o444)
    k.os.add("/proc/sys/kernel/random/boot_id", b"a" * 32 + b"\n", mode=0o444)
    k.os.links["/proc/self/ns/net"] = "net:[51917]"
    started = {
        "operation": packet["operation"],
        "program_sha256": packet["program_sha256"],
        "unit": unit,
        "invocation": "b" * 32,
        "pid": "999",
        "cgroup": "/system.slice/" + unit,
        "boot_id": "a" * 32,
    }
    actual_path = Path

    def namespace_path(value):
        if str(value) == root + "/program.py":
            return SimpleNamespace(resolve=lambda: SimpleNamespace(parent=root))
        return actual_path(value)

    def response(argv, payload):
        k.calls.append(argv)
        if argv[0] == "/usr/bin/systemd-run":
            if outcome == "success_unloaded":
                k.os.add(root + "/supervisor-start.json", json.dumps(started).encode())
                k.os.add(
                    root + "/result.json",
                    json.dumps(
                        {
                            "schema": "fixed_dev_probe.observations.v1",
                            "status": "OBSERVATIONS_COMPLETE",
                            "operation": packet["operation"],
                            "live_acceptance": False,
                        }
                    ).encode(),
                )
            elif outcome == "preflight_refused":
                # Execute the actual final role/CLI and authored refusal path.
                with (
                    patch.object(target, "__file__", root + "/program.py"),
                    patch.object(target, "Path", side_effect=namespace_path),
                    patch.object(target.LinuxDependencies, "standard_library", return_value=deps),
                ):
                    try:
                        target.main(["--supervised-first-preflight", packet["operation"]])
                    except target.Refusal:
                        k.forced_returncodes[argv] = 78
                    else:
                        raise AssertionError(
                            "actual first preflight should refuse missing API producer"
                        )
            return b""
        if argv[0] == "/usr/bin/systemctl":
            if outcome == "success_unloaded":
                raise AssertionError(
                    "successful transient unit was unloaded; no post-exit show is valid"
                )
            fields = {
                "Id": unit,
                "ActiveState": "active",
                "SubState": "running",
                "MainPID": "999",
                "InvocationID": started["invocation"],
                "ControlGroup": started["cgroup"],
                "Job": "",
                "ExecStart": "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -I "
                + root
                + "/program.py --supervised-first-preflight "
                + packet["operation"]
                + " ; ignore_errors=no ; }",
                "WorkingDirectory": root,
                "KillMode": "control-group",
                "Restart": "no",
                "TimeoutStopUSec": "5s",
                "Type": "exec",
                "NotifyAccess": "none",
                "ExecStop": "",
                "ExecStopPost": "",
                "SendSIGKILL": "yes",
                "KillSignal": "15",
                "FinalKillSignal": "9",
                "TimeoutStopFailureMode": "terminate",
            }
            return manager_show(argv, fields)
        if argv[0] == "/usr/bin/docker":
            return b""  # Actual bounded discovery rejects zero API candidates.
        raise AssertionError("unrecognized fake external boundary")

    k.response = response

    def spawn(argv, **kwargs):
        process = NativeProcess(k, argv)
        k.processes.append(process)
        return process

    deps = SimpleNamespace(
        os=k.os,
        time=SimpleNamespace(time=lambda: 1000.0, monotonic=lambda: 1000.0),
        subprocess=SimpleNamespace(
            Popen=spawn,
            PIPE=subprocess.PIPE,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
        selectors=SimpleNamespace(
            DefaultSelector=NativeSelector,
            EVENT_READ=selectors.EVENT_READ,
            EVENT_WRITE=selectors.EVENT_WRITE,
        ),
        signal=signal,
    )
    return k, deps, envelope, root


def test_wrong_guest_is_rejected_before_any_bootstrap_write_or_child(self):
    kernel, dependencies, envelope, root = _remote_boundary("unused", guest="ygg-prod")
    result = target.remote_launch(envelope, dependencies)
    self.assertEqual(
        ("REFUSED", "bootstrap_guest_not_fixed_dev"), (result["status"], result["reason"])
    )
    self.assertNotIn(root, kernel.os.meta)
    self.assertEqual([], kernel.processes)
    self.assertEqual([], kernel.calls)


def test_completed_unloaded_supervisor_uses_retained_original_identity(self):
    kernel, dependencies, envelope, root = _remote_boundary("success_unloaded")
    result = target.remote_launch(envelope, dependencies)
    self.assertEqual("b" * 32, result["supervisor"]["invocation"])
    self.assertEqual(0, result["supervisor"]["manager_exit_code"])
    self.assertTrue(result["supervisor"]["reaped"])
    self.assertTrue(result["supervisor"]["cgroup_empty"])
    self.assertFalse(result["live_acceptance"])
    self.assertFalse(any(argv[0] == "/usr/bin/systemctl" for argv in kernel.calls))
    self.assertTrue(all(process.returncode == 0 for process in kernel.processes))
    self.assertTrue(
        all(
            stream.closed
            for process in kernel.processes
            for stream in (process.stdin, process.stdout, process.stderr)
        )
    )


def test_actual_supervised_preflight_retains_authored_refusal_and_original_handle(self):
    kernel, dependencies, envelope, root = _remote_boundary("preflight_refused")
    result = target.remote_launch(envelope, dependencies)
    self.assertEqual("REFUSED", result["status"])
    self.assertEqual("first_preflight", result["phase"])
    self.assertEqual("normal_dev_api_producer_candidates_unqualified", result["reason"])
    self.assertEqual(
        target.Handle(envelope["packet"]["operation"], "ygg-dev", "ygg-dev").fingerprint,
        result["original_handle_sha256"],
    )
    self.assertIn(root + "/supervisor-start.json", kernel.os.files)
    self.assertIn(root + "/failure.json", kernel.os.files)
    self.assertNotIn(root + "/result.json", kernel.os.files)
    self.assertFalse(result["live_acceptance"])
    self.assertTrue(all(process.returncode is not None for process in kernel.processes))
    self.assertTrue(
        all(
            stream.closed
            for process in kernel.processes
            for stream in (process.stdin, process.stdout, process.stderr)
        )
    )


def test_actual_first_preflight_does_not_require_an_unused_canonical_config_parent(self):
    for config_parent_present, systemd_parent_present in (
        (False, True),
        (True, True),
        (False, False),
    ):
        with self.subTest(
            config_parent_present=config_parent_present,
            systemd_parent_present=systemd_parent_present,
        ):
            kernel, dependencies, envelope, root = _remote_boundary("preflight_refused")
            if systemd_parent_present:
                kernel.os.add("/run/systemd/system", directory=True, mode=0o755)
            if config_parent_present:
                kernel.os.add("/etc/yggdrasil/host-probe", directory=True, mode=0o755)
            response, mounted = kernel.response, []

            def manager_namespace(argv, payload):
                if argv[0] == "/usr/bin/systemd-run":
                    configured = next(
                        arg.removeprefix("--property=ReadWritePaths=")
                        for arg in argv
                        if arg.startswith("--property=ReadWritePaths=")
                    ).split()
                    for entry in configured:
                        path = entry.removeprefix("-")
                        if path not in kernel.os.meta:
                            if entry.startswith("-"):
                                continue
                            # Real systemd refuses a missing mandatory mount
                            # before execve and cannot write a preflight record.
                            kernel.forced_returncodes[argv] = 226
                            return b""
                        mounted.append(path)
                return response(argv, payload)

            kernel.response = manager_namespace
            if systemd_parent_present:
                result = target.remote_launch(envelope, dependencies)
                self.assertEqual(
                    ("REFUSED", "first_preflight"), (result["status"], result["phase"])
                )
                self.assertEqual("normal_dev_api_producer_candidates_unqualified", result["reason"])
                self.assertIn(root + "/supervisor-start.json", kernel.os.files)
                self.assertIn(root + "/failure.json", kernel.os.files)
                self.assertEqual(
                    [root, "/run/systemd/system"]
                    + (["/etc/yggdrasil/host-probe"] if config_parent_present else []),
                    mounted,
                )
            else:
                with self.assertRaisesRegex(
                    target.Unknown, "original_supervisor_start_evidence_missing"
                ):
                    target.remote_launch(envelope, dependencies)
                self.assertNotIn(root + "/supervisor-start.json", kernel.os.files)
                self.assertNotIn(root + "/failure.json", kernel.os.files)
            self.assertEqual(config_parent_present, "/etc/yggdrasil/host-probe" in kernel.os.meta)
            self.assertNotIn(root + "/result.json", kernel.os.files)


def test_cold_four_file_bootstrap_reaches_observed_sdk_without_preseeded_source(self):
    from datetime import datetime, timezone

    class SDKHandoff(BaseException):
        pass

    kernel = NativeKernel(self.h)
    _, _, envelope, _ = _remote_boundary("unused")
    packet, root = envelope["packet"], kernel.scope.root
    packet.update(
        namespace=kernel.scope.namespace,
        window_start_utc=datetime.fromtimestamp(kernel.clock.epoch - 1, timezone.utc).isoformat(),
        window_end_utc=datetime.fromtimestamp(kernel.clock.epoch + 1799, timezone.utc).isoformat(),
    )
    # Remove every fixture-provided operation/source/config artifact. The real
    # launcher must create exactly its four initial leaves before its first CLI.
    for path in list(kernel.os.meta):
        if any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in (
                root,
                kernel.scope.binding.package,
                "/etc/yggdrasil/host-probe",
            )
        ):
            kernel.os.meta.pop(path)
            kernel.os.files.pop(path, None)
    kernel.unit.update(
        LoadState="not-found",
        ActiveState="inactive",
        SubState="dead",
        MainPID="0",
        UnitFileState="",
        FragmentPath="",
        DropInPaths="",
        Job="",
        InvocationID="",
        ControlGroup="",
        WorkingDirectory="",
        EnvironmentFiles="",
        ExecStart="",
        ExecStop="",
        ExecStopPost="",
        Type="",
        Environment="",
    )
    docker = DockerDiscoveryProducer()
    response, actual_path, calls, handoffs = kernel.response, Path, [], []

    def namespace_path(value):
        if str(value) == root + "/program.py":
            return SimpleNamespace(resolve=lambda: SimpleNamespace(parent=root))
        return actual_path(value)

    def execve(executable, argv, environment):
        # The SDK handoff is the first executable after the bootstrap CLI;
        # source extraction belongs to the qualified worker and is not assumed.
        scope, config, custody = target._decode_scope(kernel.os.files[root + "/native-input.json"])
        self.assertEqual(kernel.scope.binding.sdk, executable)
        self.assertEqual(
            [
                executable,
                "-I",
                root + "/program.py",
                "--qualified-dev-worker",
                packet["operation"],
            ],
            argv,
        )
        self.assertEqual({"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}, environment)
        self.assertEqual(root + "/source", scope.binding.package)
        self.assertNotIn(scope.binding.package, kernel.os.meta)
        self.assertEqual(scope.request_bytes, kernel.os.files[root + "/request.json"])
        self.assertEqual(
            packet["program_sha256"], target.sha(kernel.os.files[root + "/program.py"])
        )
        self.assertEqual(scope.binding.sdk_realpath, kernel.scope.binding.sdk_realpath)
        self.assertEqual("http://127.0.0.1:47777", target.parse_config(config)["PROBE_BASE_URL"])
        self.assertEqual(envelope["custody_source"], custody)
        started = json.loads(kernel.os.files[root + "/supervisor-start.json"])
        self.assertEqual("999", started["pid"])
        self.assertEqual(5, target.finite_stop_seconds(started["profile"]))
        self.assertEqual("", started["profile"]["ExecStop"])
        handoffs.append(scope)
        raise SDKHandoff()

    def ports(argv, payload):
        calls.append(argv)
        if argv[0] == "/usr/bin/systemd-run":
            self.assertEqual(
                {
                    root + "/" + name
                    for name in (
                        "program.py",
                        "source.tar",
                        "manifest.json",
                        "carrier-envelope.json",
                    )
                },
                {path for path in kernel.os.files if path.startswith(root + "/")},
            )
            self.assertIn("--property=WorkingDirectory=" + root, argv)
            self.assertTrue(stat.S_ISDIR(kernel.os.meta[root].st_mode))
            self.assertEqual(
                (
                    "/usr/bin/python3",
                    "-I",
                    root + "/program.py",
                    "--supervised-first-preflight",
                    packet["operation"],
                ),
                argv[-5:],
            )
            with (
                patch.object(target, "__file__", root + "/program.py"),
                patch.object(target, "Path", side_effect=namespace_path),
                patch.object(
                    target.LinuxDependencies, "standard_library", return_value=kernel.dependencies
                ),
            ):
                target.main(["--supervised-first-preflight", packet["operation"]])
            raise AssertionError("first preflight must exec the qualified SDK")
        if argv[0] == "/usr/bin/docker":
            return docker(argv)
        return response(argv, payload)

    kernel.response, kernel.os.execve = ports, execve
    with self.assertRaises(SDKHandoff):
        target.remote_launch(envelope, kernel.dependencies)
    self.assertEqual(1, len(handoffs))
    self.assertFalse(
        any(
            path.endswith(("failure.json", "result.json", "watchdog.json"))
            for path in kernel.os.files
            if path.startswith(root + "/")
        )
    )
    self.assertFalse(
        any(argv in {target.systemd("start"), target.systemd("stop")} for argv in calls)
    )
    self.assertTrue(all(not kernel.os.fds and selector.closed for selector in kernel.selectors))
    self.assertTrue(
        all(
            stream.closed
            for process in kernel.processes
            for stream in (process.stdin, process.stdout, process.stderr)
        )
    )
    self.assertFalse(
        any(
            path == kernel.scope.credential_source or path.endswith("secret-runtime.env")
            for path in kernel.os.opened
        )
    )


def test_show_projection_keeps_scalar_and_nonempty_command_failures_closed(self):
    for change in (
        "missing_timeout",
        "duplicate",
        "unknown",
        "exec_stop",
        "exec_stop_post",
        "empty_start",
    ):
        with self.subTest(change=change):
            kernel, dependencies, envelope, root = _remote_boundary("preflight_refused")
            response = kernel.response

            def broken_projection(argv, payload):
                raw = response(argv, payload)
                if argv[0] != "/usr/bin/systemctl":
                    return raw
                if change == "missing_timeout":
                    return (
                        b"\n".join(
                            line
                            for line in raw.splitlines()
                            if not line.startswith(b"TimeoutStopUSec=")
                        )
                        + b"\n"
                    )
                if change == "duplicate":
                    return raw + b"Restart=no\n"
                if change == "unknown":
                    return raw + b"UnknownProperty=0\n"
                if change == "empty_start":
                    return (
                        b"\n".join(
                            line for line in raw.splitlines() if not line.startswith(b"ExecStart=")
                        )
                        + b"\n"
                    )
                key = "ExecStop" if change == "exec_stop" else "ExecStopPost"
                return (
                    raw
                    + (
                        key + "={ path=/bin/sleep ; argv[]=/bin/sleep 999 ; ignore_errors=no ; }\n"
                    ).encode()
                )

            kernel.response = broken_projection
            result = target.remote_launch(envelope, dependencies)
            self.assertEqual(("REFUSED", "first_preflight"), (result["status"], result["phase"]))
            self.assertNotEqual("unqualified_operation_failure", result["reason"])
            self.assertNotIn(root + "/supervisor-start.json", kernel.os.files)
            self.assertNotIn(root + "/native-input.json", kernel.os.files)
            self.assertFalse(any(argv[0] == "/usr/bin/docker" for argv in kernel.calls))


def test_temporary_first_start_is_contained_before_lost_ack_or_admission(self):
    envelope, archive, manifest = self.installation(absent=True)
    envelope.prepare(archive, manifest, self.h.healthy)
    armed = []

    def contain(adapter):
        self.assertEqual("inactive", adapter.unit["ActiveState"])
        self.assertIsNotNone(adapter.current_config)
        self.assertFalse(any(argv == target.systemd("start") for argv in self.h.command.effects))
        armed.append(adapter)

    def lose_after_start():
        self.assertEqual(1, len(armed))
        raise target.Unknown("synthetic_first_start_ack_lost")

    self.h.command.on_start = lose_after_start
    with self.assertRaises(target.Unknown):
        envelope.activate(before_start=contain)
    self.assertEqual("active", self.h.unit["ActiveState"])
    self.assertEqual(1, len(armed))
    self.assertEqual(1, self.h.command.effects.count(target.systemd("start")))
    with self.assertRaises(target.Unknown):
        envelope.activate(before_start=contain)
    self.assertEqual(1, self.h.command.effects.count(target.systemd("start")))


def test_live_archive_pins_remain_independent_of_generated_portable_fixtures(self):
    self.assertEqual(
        "93cfac95951972e471c81749ae3247b12f1b74043aa465ff94615e3f4a019e1e",
        LIVE_PINS["ARCHIVE_SHA256"],
    )
    archive, manifest, _ = fixture_source()
    with patch.multiple(target, **LIVE_PINS):
        with self.assertRaisesRegex(target.Refusal, "source_digest"):
            target.exact_source(archive, manifest, self.h.caller)
    self.assertEqual([], self.h.command.effects)


def test_actual_native_lifecycle_ignores_only_exec_execution_metadata(self):
    kernel, assembly = _native(self)
    response, serial = kernel.response, [0]

    def changing_exec_metadata(argv, payload):
        raw = response(argv, payload)
        if argv in {target.systemd("show"), target.watchdog_show(kernel.scope)}:
            serial[0] += 1
            raw = raw.replace(
                b" ; ignore_errors=no ; }",
                (
                    " ; ignore_errors=no ; start_time=[Fri 2026-10-30 20:00:00 UTC] ; stop_time=[n/a] ; pid="
                    + str(serial[0])
                    + " ; code=exited ; status="
                    + str(serial[0] % 2)
                    + " }"
                ).encode(),
            )
        return raw

    kernel.response = changing_exec_metadata
    result = target.run_fixed_dev_worker(assembly, b"unused-active", b"unused-active")
    self.assertEqual((1, 1), (result["down"], result["recovery"]))
    self.assertTrue(result["independent_guard_disarmed"])
    self.assertGreater(serial[0], 10)
    self.assertIn(".slice/", kernel.unit["ControlGroup"].removeprefix("/system.slice/"))


def test_guard_refuses_configured_exec_marker_inode_source_and_stable_foreign_drift(self):
    for index, change in enumerate(
        ("path", "argv", "command", "flag", "inode", "source", "foreign_marker", "foreign_creator")
    ):
        with self.subTest(change=change):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            before = sum(p.argv == target.systemd("stop") for p in kernel.processes)
            fault = assembly.files.read("config").data
            if change == "path":
                kernel.unit["ExecStart"] = kernel.unit["ExecStart"].replace(
                    "path=", "path=/foreign"
                )
            elif change == "argv":
                kernel.unit["ExecStart"] = kernel.unit["ExecStart"].replace(
                    "--channel dev", "--channel prod"
                )
            elif change == "command":
                kernel.unit["ExecStart"] += " " + kernel.unit["ExecStart"]
            elif change == "flag":
                kernel.unit["ExecStart"] = kernel.unit["ExecStart"].replace(
                    "ignore_errors=no", "ignore_errors=yes"
                )
            elif change == "inode":
                kernel.os.meta[guard.parent_path + "/" + guard.marker].st_ino += 1
            elif change == "source":
                path = kernel.scope.binding.package + "/" + target.LAUNCHER
                kernel.os.add(path, kernel.os.files[path] + b"\n# foreign edit\n", mode=0o664)
            elif change == "foreign_marker":
                kernel.os.files["/proc/" + kernel.unit["MainPID"] + "/environ"] = (
                    b"YGG_DEV_OPERATION=foreign\0"
                )
            else:
                kernel.os.links["/proc/" + kernel.unit["MainPID"] + "/cwd"] = "/foreign"
            with self.assertRaises((target.Refusal, target.Unknown)):
                target.cleanup_owned_dev_fault(assembly, guard.record)
            self.assertEqual(
                before, sum(p.argv == target.systemd("stop") for p in kernel.processes)
            )
            self.assertEqual(fault, assembly.files.read("config").data)


def test_temporary_activation_and_restoration_compare_configured_exec_across_invocations(self):
    for index, absent in enumerate((False, True)):
        with self.subTest(absent=absent):
            if index:
                self.fresh()
            envelope, archive, manifest = self.installation(absent=absent)
            command, serial = self.h.command.run, [0]

            def read_with_execution_status(argv, **kwargs):
                result = command(argv, **kwargs)
                if argv == target.systemd("show"):
                    serial[0] += 1
                    result = replace(
                        result,
                        data=result.data.replace(
                            b" ; ignore_errors=no ; }",
                            (
                                " ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid="
                                + str(serial[0])
                                + " ; code=exited ; status=0 }"
                            ).encode(),
                        ),
                    )
                return result

            self.h.command.run = read_with_execution_status
            envelope.prepare(archive, manifest, self.h.healthy)
            result = self.run_installed_sequence(envelope)
            self.assertTrue(result["original_effective_unit_and_enablement_restored"])
            self.assertEqual([], os.listdir(self.root / "volatile-systemd"))


def test_actual_cleanup_tolerates_exiting_proc_boundaries_without_weakening_admission(self):
    changes = (
        "empty_cmdline",
        "empty_environment",
        "zombie",
        "missing_stat",
        "missing_cgroup",
        "missing_cmdline",
        "missing_environ",
        "missing_exe",
        "missing_cwd",
        "missing_fd",
        "preexec",
    )
    for index, change in enumerate(changes):
        with self.subTest(change=change):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            base = "/proc/" + kernel.unit["MainPID"]
            incident = (self.root / "native-incident.json").read_bytes()
            if change == "empty_cmdline":
                kernel.os.files[base + "/cmdline"] = b""
                with self.assertRaisesRegex(target.Unknown, "native_proc_argv_incomplete"):
                    assembly.io.process(kernel.unit["MainPID"], kernel.scope.binding.boot_id)
            elif change == "empty_environment":
                kernel.os.files[base + "/environ"] = b""
            elif change == "zombie":
                kernel.os.files[base + "/stat"] = kernel.os.files[base + "/stat"].replace(
                    b") S ", b") Z "
                )
            elif change == "preexec":
                kernel.unit.update(
                    ActiveState="activating",
                    SubState="start",
                    Job="41 /org/freedesktop/systemd1/job/41",
                )
                kernel.os.files[base + "/cmdline"] = b"/usr/lib/systemd/systemd\0"
                kernel.os.links[base + "/exe"] = "/usr/lib/systemd/systemd"
            elif change in {"missing_exe", "missing_cwd", "missing_fd"}:
                leaf = {"missing_exe": "exe", "missing_cwd": "cwd", "missing_fd": "fd/2"}[change]
                original = kernel.os.readlink

                def missing_link(path, *, dir_fd=None, original=original, leaf=leaf, base=base):
                    if path == base + "/" + leaf:
                        raise FileNotFoundError(path)
                    return original(path, dir_fd=dir_fd)

                kernel.os.readlink = missing_link
            else:
                leaf = change.removeprefix("missing_")
                kernel.os.files.pop(base + "/" + leaf)
                kernel.os.meta.pop(base + "/" + leaf)
            result = target.cleanup_owned_dev_fault(assembly, guard.record)
            self.assertEqual("unknown", result["status"])
            self.assertTrue(result["healthy_config_restored"])
            self.assertEqual(
                ("inactive", "0", ""),
                (kernel.unit["ActiveState"], kernel.unit["MainPID"], kernel.unit["Job"]),
            )
            self.assertEqual(incident, (self.root / "native-incident.json").read_bytes())


def _actual_watch(kernel):
    path = kernel.scope.root + "/watchdog-ready.json"
    kernel.os.files.pop(path, None)
    kernel.os.meta.pop(path, None)
    kernel.os.getpid = lambda: 9888
    return target.watch_dev_operation(kernel.scope.root, kernel.dependencies)


def test_actual_watchdog_cancels_owned_preexec_and_same_pid_exec_transitions(self):
    cases = (
        "activating_systemd",
        "active_systemd",
        "activating_executor",
        "active_executor",
        "active_other_preexec",
        "mixed_argv_exe",
        "same_pid_image_changes",
    )
    for index, case in enumerate(cases):
        with self.subTest(case=case):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            base = "/proc/" + kernel.unit["MainPID"]
            final_argv = kernel.os.files[base + "/cmdline"]
            final_environment = kernel.os.files[base + "/environ"]
            saved_incident = (self.root / "native-incident.json").read_bytes()
            if case != "same_pid_image_changes":
                executable = {
                    "activating_systemd": "/usr/lib/systemd/systemd",
                    "active_systemd": "/usr/lib/systemd/systemd",
                    "activating_executor": "/usr/lib/systemd/systemd-executor",
                    "active_executor": "/usr/lib/systemd/systemd-executor",
                }.get(case, "/usr/lib/future-pre-exec-helper")
                kernel.os.files[base + "/cmdline"] = executable.encode() + b"\0"
                kernel.os.links[base + "/exe"] = executable
                kernel.os.links[base + "/cwd"] = "/"
            kernel.os.files[base + "/environ"] = b"CREDENTIALS_DIRECTORY=/run/credentials/dev\0"
            activating = case.startswith("activating_")
            kernel.unit.update(
                ActiveState="activating" if activating else "active",
                SubState="start" if activating else "running",
                Job="41 /org/freedesktop/systemd1/job/41" if activating else "",
            )
            if case in {"mixed_argv_exe", "same_pid_image_changes"}:
                readlink, transitions = kernel.os.readlink, []
                trigger = "/exe" if case == "mixed_argv_exe" else "/cwd"

                def exec_during_read(path, *, dir_fd=None):
                    if path == base + trigger and not transitions:
                        transitions.append(case)
                        # execve keeps the PID/start time, but replaces the
                        # image and environment between separate proc reads.
                        kernel.os.files[base + "/cmdline"] = final_argv
                        kernel.os.files[base + "/environ"] = final_environment
                        kernel.os.links[base + "/exe"] = kernel.scope.binding.sdk_realpath
                        kernel.os.links[base + "/cwd"] = kernel.scope.binding.package
                    return readlink(path, dir_fd=dir_fd)

                kernel.os.readlink = exec_during_read
            helper_stat = "/proc/999/stat"
            kernel.os.files.pop(helper_stat)
            kernel.os.meta.pop(helper_stat)
            kernel.supervisor["MainPID"] = "0"
            before = len(kernel.processes)
            result = _actual_watch(kernel)
            effects = [process.argv for process in kernel.processes[before:]]
            self.assertEqual(1, effects.count(target.supervisor_stop(kernel.scope)))
            self.assertEqual(1, effects.count(target.systemd("stop")))
            self.assertNotIn(target.systemd("start"), effects)
            self.assertEqual("unknown", result["status"])
            self.assertTrue(result["healthy_config_restored"])
            self.assertFalse(result["history_rewound"])
            self.assertEqual("inactive", kernel.unit["ActiveState"])
            self.assertEqual(saved_incident, (self.root / "native-incident.json").read_bytes())
            self.assertNotIn(
                "http://127.0.0.1:", kernel.os.files[kernel.scope.binding.config].decode()
            )
            self.assertEqual(
                result, json.loads(kernel.os.files[kernel.scope.root + "/watchdog-result.json"])
            )
            if case in {"mixed_argv_exe", "same_pid_image_changes"}:
                self.assertEqual([case], transitions)


def test_actual_watchdog_preserves_the_coherent_finalized_foreign_launcher_veto(self):
    for index, change in enumerate(("marker", "missing_marker", "uid", "cwd", "cgroup")):
        with self.subTest(change=change):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            base = "/proc/" + kernel.unit["MainPID"]
            fault = kernel.os.files[kernel.scope.binding.config]
            if change == "marker":
                kernel.os.files[base + "/environ"] = b"YGG_DEV_OPERATION=foreign\0"
            elif change == "missing_marker":
                kernel.os.files[base + "/environ"] = b"CREDENTIALS_DIRECTORY=/run/credentials/dev\0"
            elif change == "uid":
                kernel.os.meta[base].st_uid = 1234
            elif change == "cwd":
                kernel.os.links[base + "/cwd"] = "/foreign"
            else:
                kernel.os.files[base + "/cgroup"] = b"0::/system.slice/foreign.service\n"
            before = len(kernel.processes)
            with self.assertRaisesRegex(target.Unknown, "guard_refuses_foreign_"):
                _actual_watch(kernel)
            effects = [process.argv for process in kernel.processes[before:]]
            self.assertEqual(1, effects.count(target.supervisor_stop(kernel.scope)))
            self.assertNotIn(target.systemd("stop"), effects)
            self.assertNotIn(target.systemd("start"), effects)
            self.assertEqual(fault, kernel.os.files[kernel.scope.binding.config])
            self.assertNotIn(kernel.scope.root + "/watchdog-result.json", kernel.os.files)


def test_watchdog_initialization_ack_requires_pidfd_recheck_and_registered_selector(self):
    for index, failure in enumerate(
        (
            "pidfd",
            "selector_create",
            "selector_register",
            "helper_exit",
            "pid_reuse",
            "wait_after_ready",
        )
    ):
        with self.subTest(failure=failure):
            if index:
                self.fresh()
            kernel, assembly = _native(self)
            adapter = target.DevProbeAdapter(kernel.scope.binding, assembly.caller, assembly.files)
            adapter.admit()
            guard = target.NativeFaultGuard(assembly, adapter)
            guard.arm()
            pidfd_open = kernel.os.pidfd_open

            def attach(pid, flags):
                if failure == "pidfd":
                    raise OSError("synthetic pidfd setup failure")
                fd = pidfd_open(pid, flags)
                path = "/proc/" + str(pid) + "/stat"
                if failure == "helper_exit":
                    kernel.os.files.pop(path)
                    kernel.os.meta.pop(path)
                elif failure == "pid_reuse":
                    kernel.os.files[path] = kernel.os.files[path].replace(b" 999 ", b" 1999 ")
                return fd

            kernel.os.pidfd_open = attach
            factory, calls = kernel.selector, [0]

            def selector_factory():
                calls[0] += 1
                if calls[0] != 1 or failure in {"pidfd", "helper_exit", "pid_reuse"}:
                    return factory()
                if failure == "selector_create":
                    raise OSError("synthetic selector setup failure")
                selected = factory()
                register, select = selected.register, selected.select

                def register_helper(stream, events, kind):
                    if kind == "original_helper_exit" and failure == "selector_register":
                        raise OSError("synthetic pidfd registration failure")
                    return register(stream, events, kind)

                def wait(timeout):
                    self.assertIn(kernel.scope.root + "/watchdog-ready.json", kernel.os.files)
                    self.assertTrue(
                        any(
                            key.data == "original_helper_exit"
                            for key in selected.registered.values()
                        )
                    )
                    if failure == "wait_after_ready":
                        raise OSError("synthetic wait failure after readiness")
                    return select(timeout)

                selected.register, selected.select = register_helper, wait
                return selected

            kernel.dependencies = replace(
                kernel.dependencies,
                selectors=SimpleNamespace(
                    DefaultSelector=selector_factory, EVENT_READ=1, EVENT_WRITE=2
                ),
            )
            result = _actual_watch(kernel)
            self.assertEqual("unknown", result["status"])
            self.assertEqual(
                failure == "wait_after_ready",
                kernel.scope.root + "/watchdog-ready.json" in kernel.os.files,
            )
            self.assertFalse(any(p.argv == target.systemd("start") for p in kernel.processes))
            self.assertTrue(all(selector.closed for selector in kernel.selectors))


def test_parent_waits_for_initialized_guard_before_any_first_start(self):
    kernel, assembly = _native(self)
    response = kernel.response

    def without_ack(argv, payload):
        raw = response(argv, payload)
        if argv == target.watchdog_command(kernel.scope):
            path = kernel.scope.root + "/watchdog-ready.json"
            kernel.os.files.pop(path)
            kernel.os.meta.pop(path)
        return raw

    kernel.response = without_ack
    with self.assertRaisesRegex(target.Unknown, "initialization_unconfirmed"):
        target.run_fixed_dev_worker(assembly, b"unused", b"unused")
    self.assertFalse(
        any(p.argv in {target.systemd("start"), target.systemd("stop")} for p in kernel.processes)
    )
    self.assertNotIn("http://127.0.0.1:", kernel.os.files[kernel.scope.binding.config].decode())


def test_watchdog_refuses_a_foreign_supervisor_before_probe_effects(self):
    for index, field in enumerate(("InvocationID", "ExecStart", "KillMode")):
        with self.subTest(field=field):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            before = len(kernel.processes)
            kernel.supervisor[field] = (
                "foreign"
                if field != "ExecStart"
                else kernel.supervisor[field].replace("--supervised-first-preflight", "--foreign")
            )
            with self.assertRaises(target.Unknown):
                _actual_watch(kernel)
            self.assertFalse(
                any(
                    p.argv in {target.supervisor_stop(kernel.scope), target.systemd("stop")}
                    for p in kernel.processes[before:]
                )
            )


def test_watchdog_quiesces_pending_start_children_before_final_probe_cancel_and_rereads_disarm(
    self,
):
    for index, case in enumerate(
        ("helper_gone", "deadline", "disarmed_during_teardown", "nonempty_supervisor")
    ):
        with self.subTest(case=case):
            if index:
                self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            fault = assembly.files.read("config").data
            group = "/sys/fs/cgroup" + kernel.supervisor["ControlGroup"] + "/cgroup.procs"
            kernel.os.files[group] = b"999\n9123\n"
            if case == "helper_gone":
                path = "/proc/999/stat"
                kernel.os.files.pop(path)
                kernel.os.meta.pop(path)
                kernel.supervisor["MainPID"] = "0"
            if case == "deadline":
                kernel.clock.advance(
                    kernel.scope.binding.window_end - target.RESTORATION_RESERVE - kernel.clock()
                )
            response, order = kernel.response, []

            def tracked(argv, payload):
                if argv == target.systemd("stop"):
                    self.assertEqual(b"", kernel.os.files[group])
                    order.append("probe")
                raw = response(argv, payload)
                if argv == target.supervisor_stop(kernel.scope):
                    order.append("helper")
                    if case == "nonempty_supervisor":
                        kernel.os.files[group] = b"9123\n"
                    elif case == "disarmed_during_teardown":
                        guard.record["disarmed"] = True
                        guard.write_record()
                return raw

            kernel.response = tracked
            if case == "nonempty_supervisor":
                with self.assertRaisesRegex(target.Unknown, "supervisor_cgroup_not_empty"):
                    _actual_watch(kernel)
                self.assertEqual(["helper"], order)
                self.assertEqual(fault, assembly.files.read("config").data)
            else:
                result = _actual_watch(kernel)
                self.assertEqual(
                    ["helper"] if case == "disarmed_during_teardown" else ["helper", "probe"], order
                )
                self.assertEqual(
                    "disarmed" if case == "disarmed_during_teardown" else "unknown",
                    result["status"],
                )


def test_stop_is_bounded_before_effects_and_ambiguous_containment_never_restores_or_restarts(self):
    bad = (
        ("TimeoutStopUSec", "infinity"),
        ("TimeoutStopUSec", "1min 30s"),
        ("SendSIGKILL", "no"),
        ("FinalKillSignal", "6"),
        ("TimeoutStopFailureMode", "abort"),
        ("NotifyAccess", "all"),
        ("ExecStopPost", "{ path=/bin/sleep ; argv[]=/bin/sleep 999 ; ignore_errors=no ; }"),
    )
    for index, (key, value) in enumerate(bad):
        with self.subTest(key=key, value=value):
            if index:
                self.fresh()
            kernel, assembly = _native(self)
            kernel.unit[key] = value
            with self.assertRaises(target.Refusal):
                target.run_fixed_dev_worker(assembly, b"unused", b"unused")
            self.assertFalse(
                any(
                    p.argv
                    in {
                        target.systemd("start"),
                        target.systemd("stop"),
                        target.watchdog_command(kernel.scope),
                    }
                    for p in kernel.processes
                )
            )
    for kind in ("lost_ack", "remaining_process", "failed_after_stop", "restart_becomes_live"):
        with self.subTest(kind=kind):
            self.fresh()
            kernel, assembly, guard = _armed_native_fault(self)
            fault = assembly.files.read("config").data
            before = len(kernel.processes)
            response = kernel.response
            if kind == "restart_becomes_live":
                kernel.unit.update(
                    ActiveState="activating",
                    SubState="auto-restart",
                    MainPID="0",
                    Job="41 /org/freedesktop/systemd1/job/41",
                )
                kernel._processes()

            def stopping(argv, payload):
                if argv == target.systemd("stop") and kind == "restart_becomes_live":
                    kernel.unit.update(ActiveState="active", SubState="running", MainPID="7777")
                    kernel._processes()
                raw = response(argv, payload)
                if argv == target.systemd("stop"):
                    if kind == "lost_ack":
                        kernel.forced_returncodes = {argv: 1}
                    elif kind == "remaining_process":
                        kernel.os.files[
                            "/sys/fs/cgroup" + kernel.unit["ControlGroup"] + "/cgroup.procs"
                        ] = b"7777\n"
                    elif kind == "failed_after_stop":
                        kernel.unit.update(ActiveState="failed", SubState="failed")
                return raw

            kernel.response = stopping
            if kind in {"lost_ack", "remaining_process"}:
                with self.assertRaises(target.Unknown):
                    target.cleanup_owned_dev_fault(assembly, guard.record)
                self.assertEqual(fault, kernel.os.files[kernel.scope.binding.config])
            else:
                result = target.cleanup_owned_dev_fault(assembly, guard.record)
                self.assertTrue(result["healthy_config_restored"])
            self.assertFalse(
                any(p.argv == target.systemd("start") for p in kernel.processes[before:])
            )


for _name, _value in list(globals().items()):
    if _name.startswith("test_") and callable(_value):
        setattr(NativeBindingTests, _name, _value)
        del globals()[_name]


def whole_native_call(
    case,
    *,
    lost_transport_ack=False,
    unhealthy_before_install=False,
    temporary_install=False,
    foreign_state_after_guard=False,
    original_state_directory_present=False,
    original_service_inactive=False,
    api_publication=None,
    publication_refused=False,
):
    """Current local entry -> serialized program -> first preflight -> real drill."""
    import contextlib, io
    from datetime import datetime, timezone

    class SDKExited(BaseException):
        pass

    kernel = NativeKernel(case.h)
    kernel.forced_returncodes = {}
    program = fixture_program()
    archive, manifest, _ = fixture_source()
    contract = b"portable fixed DEV #6505 contract"
    root = kernel.scope.root
    kernel.scope = replace(
        kernel.scope,
        binding=replace(kernel.scope.binding, api_base="http://127.0.0.1:47777"),
        program_sha256=target.sha(program),
    )
    config_path = kernel.scope.binding.config
    config = kernel.os.files[config_path].replace(
        b"http://synthetic-dev-api.invalid:47777", b"http://127.0.0.1:47777"
    )
    kernel.os.files[config_path] = config
    kernel.os.add(kernel.unit["FragmentPath"], (PUBLIC / target.TEMPLATE).read_bytes(), mode=0o644)
    temporary = unhealthy_before_install or temporary_install
    state_parent = str(Path(kernel.scope.binding.state_file).parent)
    runtime_parent = "/run/yggdrasil-host-probe-dev"
    original_state_identity = kernel.os.meta[state_parent]
    if temporary:
        if not original_service_inactive:
            kernel.os.files.pop(config_path)
            kernel.os.meta.pop(config_path)
            kernel.unit.update(
                LoadState="not-found",
                UnitFileState="",
                FragmentPath="",
                DropInPaths="",
                WorkingDirectory="",
                EnvironmentFiles="",
                ExecStart="",
                ExecStop="",
                ExecStopPost="",
                Type="",
                Environment="",
            )
        kernel.unit.update(
            ActiveState="inactive",
            SubState="dead",
            MainPID="0",
            Job="",
            InvocationID="",
            ControlGroup="",
        )
        kernel._processes()
        for path in list(kernel.os.meta):
            if path == state_parent and original_state_directory_present:
                continue
            if any(
                path == parent or path.startswith(parent + "/")
                for parent in (state_parent, runtime_parent)
            ):
                kernel.os.meta.pop(path)
                kernel.os.files.pop(path, None)
    original_unit = dict(kernel.unit)
    for path in list(kernel.os.meta):
        if path == root or path.startswith(root + "/"):
            kernel.os.meta.pop(path)
            kernel.os.files.pop(path, None)
    packet = {
        "schema": "fixed_dev_probe.carrier.v1",
        "issue": 6505,
        "operation": kernel.scope.handle.operation,
        "namespace": kernel.scope.namespace,
        "reviewed_head": "f" * 40,
        "program_sha256": target.sha(program),
        "issue_body_sha256": target.sha(contract),
        "lease_id": "portable-dev-lease",
        "keeper_standing_reference": "portable-reviewed-dev-window",
        "window_start_utc": datetime.fromtimestamp(
            kernel.clock.epoch - 1, timezone.utc
        ).isoformat(),
        "window_end_utc": datetime.fromtimestamp(
            kernel.clock.epoch + 1799, timezone.utc
        ).isoformat(),
        "bootstrap_interpreter": "/usr/bin/python3",
        "local_fence_references": list(kernel.scope.local_fence_references),
        "normal_interval_seconds": 61,
        "heartbeat_stale_seconds": 601,
        "gh_executable": "/opt/homebrew/bin/gh",
        "caller_interpreter": sys.executable,
    }
    kernel.os.add(target.LOCAL_DEV_PROGRAM, program, mode=0o644)
    for path in (packet["gh_executable"], packet["caller_interpreter"]):
        kernel.os.add(path, b"existing qualified local executable", mode=0o755)
    docker = DockerDiscoveryProducer()
    if api_publication is not None:
        docker.containers[0]["NetworkSettings"]["Ports"]["8000/tcp"] = api_publication
    original_response, calls, stages = kernel.response, [], []
    original_path = Path

    def namespace_path(value):
        if str(value) == root + "/program.py":
            return SimpleNamespace(resolve=lambda: SimpleNamespace(parent=root))
        return original_path(value)

    def execve(executable, argv, environment):
        module = sys.modules["fixed_dev_program"]
        scope, _, _ = module._decode_scope(kernel.os.files[root + "/native-input.json"])
        case.assertEqual(scope.binding.sdk, executable)
        case.assertEqual(
            [executable, "-I", root + "/program.py", "--qualified-dev-worker", packet["operation"]],
            argv,
        )
        case.assertEqual({"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}, environment)
        kernel.scope = scope
        stages.append("qualified-sdk-exec")
        try:
            case.assertEqual(0, module.main(["--qualified-dev-worker", packet["operation"]]))
        except module.Unknown:
            if not foreign_state_after_guard:
                raise
            stages.append("foreign-state-before-first-start")
            raise SDKExited(78)
        except module.Refusal:
            if not unhealthy_before_install:
                raise
            stages.append("unhealthy-before-installation")
            raise SDKExited(78)
        stages.append("qualified-worker-complete")
        raise SDKExited()

    def response(argv, payload):
        calls.append(argv)
        if argv[:3] == ("/usr/bin/git", "-C", target.LOCAL_DEV_WORKTREE):
            return {
                ("rev-parse", "HEAD"): b"f" * 40 + b"\n",
                ("status", "--porcelain"): b"",
                ("branch", "--show-current"): target.LOCAL_DEV_BRANCH.encode() + b"\n",
                ("rev-parse", "--show-toplevel"): target.LOCAL_DEV_WORKTREE.encode() + b"\n",
                ("show", "HEAD:scripts/probe_dev_outage_operation.py"): program,
            }[argv[3:]]
        if argv[0] == packet["gh_executable"]:
            return json.dumps(
                {
                    "number": 6505,
                    "state": "open",
                    "labels": [{"name": "agent:in-progress"}],
                    "body": contract.decode(),
                }
            ).encode()
        if argv[0] == packet["caller_interpreter"]:
            if "load_lifecycle_authority" in argv[2]:
                return json.dumps(
                    {
                        target.LOCAL_DEV_WORKTREE: {
                            "status": "active",
                            "path": target.LOCAL_DEV_WORKTREE,
                            "branch": target.LOCAL_DEV_BRANCH,
                            "owner": target.LOCAL_DEV_SESSION,
                            "generation": "7" * 32,
                            "expires_at": kernel.clock.epoch + 7200,
                        }
                    }
                ).encode()
            return json.dumps(
                {
                    "ok": True,
                    "task": {
                        "task_id": target.LOCAL_DEV_TASK,
                        "repo": "RasmusTho/agentic-pkm-mvp",
                        "issue_number": 6505,
                        "status": "claimed",
                        "claimed_by": target.LOCAL_DEV_HOLDER,
                        "lease_id": packet["lease_id"],
                        "lease_expires_at": "2100-01-01T00:00:00Z",
                    },
                    "lease": {
                        "lease_id": packet["lease_id"],
                        "resource": "issue:6505",
                        "holder": target.LOCAL_DEV_HOLDER,
                        "expires_at": "2100-01-01T00:00:00Z",
                        "released_at": None,
                    },
                }
            ).encode()
        if argv[0] == "/usr/bin/ssh":
            stages.append("serialized-remote-entry")
            try:
                result = execute_serialized_program(payload, kernel.dependencies)
            except BaseException as error:
                kernel.port_failure = error
                raise
            if lost_transport_ack:
                kernel.forced_returncodes[argv] = 255
            return result
        if argv[0] == "/usr/bin/systemd-run" and "--supervised-first-preflight" in argv:
            properties = dict(
                value.removeprefix("--property=").split("=", 1)
                for value in argv
                if value.startswith("--property=")
            )
            case.assertEqual("strict", properties["ProtectSystem"])
            requested = properties["ReadWritePaths"].split()
            case.assertEqual([root, "/run/systemd/system", "-/etc/yggdrasil/host-probe"], requested)
            writable = tuple(
                value.removeprefix("-")
                for value in requested
                if not value.startswith("-") or value[1:] in kernel.os.meta
            )
            case.assertEqual(
                {
                    root + "/" + name
                    for name in (
                        "program.py",
                        "source.tar",
                        "manifest.json",
                        "carrier-envelope.json",
                    )
                },
                {path for path in kernel.os.files if path.startswith(root + "/")},
            )
            module = sys.modules["fixed_dev_program"]
            stages.append("cold-first-preflight")
            with (
                patch.object(module, "__file__", root + "/program.py"),
                patch.object(module, "Path", side_effect=namespace_path),
                patch.object(kernel.os, "writable_paths", writable),
            ):
                # A leaf allow-list cannot grant creation/removal on /var/lib.
                # The former production mkdir must fail under this actual policy.
                with case.assertRaises(OSError) as denied:
                    kernel.os.require_write("mkdir", state_parent, parent=True)
                case.assertEqual(30, denied.exception.errno)
                try:
                    module.main(["--supervised-first-preflight", packet["operation"]])
                except SDKExited as exit_status:
                    if exit_status.args:
                        kernel.forced_returncodes[argv] = exit_status.args[0]
                except module.Refusal as refusal:
                    if not publication_refused:
                        raise
                    case.assertEqual(
                        "actual_dev_api_publication_ambiguous_or_unsupported", str(refusal)
                    )
                    kernel.forced_returncodes[argv] = 78
                    stages.append("publication-refused-before-sdk")
                else:
                    raise AssertionError("SDK exec must replace the bootstrap")
            kernel.supervisor.update(ActiveState="inactive", SubState="dead", MainPID="0", Job="")
            kernel.os.files[
                "/sys/fs/cgroup" + kernel.supervisor["ControlGroup"] + "/cgroup.procs"
            ] = b""
            return b""
        if argv[0] == "/usr/bin/docker":
            return docker(argv)
        if temporary_install and argv == target.systemd("reload_for_temporary_dev"):
            unit_path = "/run/systemd/system/" + target.UNIT
            temporary_dropins = sorted(
                path for path in kernel.os.files if path.startswith(unit_path + ".d/99-dev-probe-")
            )
            if unit_path not in kernel.os.files and not temporary_dropins:
                kernel.unit = dict(original_unit)
                return b""
            unit_bytes = (
                kernel.os.files[original_unit["FragmentPath"]]
                + b"\n"
                + kernel.os.files[temporary_dropins[0]]
                if original_service_inactive
                else kernel.os.files[unit_path]
            ).decode()
            values = {}
            for line in unit_bytes.splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    values[key] = value
            selected = replace(
                kernel.scope.binding,
                package=values["WorkingDirectory"],
                config=values["EnvironmentFile"],
            )
            projected = unit_metadata(selected, kernel.clock)
            for key in target.VOLATILE:
                projected[key] = kernel.unit[key]
            projected.update(
                LoadState="loaded",
                UnitFileState=original_unit["UnitFileState"]
                if original_service_inactive
                else "disabled",
                Job="",
                FragmentPath=original_unit["FragmentPath"]
                if original_service_inactive
                else unit_path,
                LoadCredentialEncrypted="bws-machine-account-token:"
                + kernel.scope.credential_source,
                ReadWritePaths=kernel.scope.controller_directory,
                DropInPaths="",
                Environment="PYTHONPATH=" + selected.package,
                StateDirectory=values["StateDirectory"],
            )
            markers = [path for path in kernel.os.files if "/99-ygg-dev-owner-" in path]
            projected["DropInPaths"] = " ".join([*temporary_dropins, *markers])
            if markers:
                projected["Environment"] += " YGG_DEV_OPERATION=" + packet["operation"]
            kernel.unit = projected
            return b""
        if foreign_state_after_guard and argv == target.watchdog_command(kernel.scope):
            result = original_response(argv, payload)
            kernel.os.add(
                state_parent
                if foreign_state_after_guard == "canonical"
                else str(Path(kernel.scope.binding.state_file).parent),
                directory=True,
                mode=0o700,
                inode=98765,
            )
            return result
        if temporary_install and argv == target.systemd("start"):
            state = "/var/lib/" + kernel.unit["StateDirectory"]
            case.assertEqual(root + "/probe-state", state)
            case.assertEqual(state + "/alert-state.json", kernel.scope.binding.state_file)
            configured = kernel.unit["EnvironmentFiles"].split("(ignore_errors=no)")[0].strip()
            case.assertEqual(
                kernel.scope.binding.state_file,
                target.parse_config(kernel.os.files[configured])["PROBE_STATE_FILE"],
            )
            case.assertTrue(stat.S_ISDIR(kernel.os.meta[state].st_mode))
            kernel.os.add(runtime_parent, directory=True, mode=0o700)
            kernel.os.add(runtime_parent + "/secret-runtime.env", b"DO_NOT_READ_WEBHOOK")
            kernel.unit["ControlGroup"] = (
                "/system.slice/system-yggdrasil\\x2dhost\\x2dprobe.slice/" + target.UNIT
            )
            return original_response(argv, payload)
        if temporary_install and argv == target.systemd("stop"):
            result = original_response(argv, payload)
            for path in list(kernel.os.meta):
                if path == runtime_parent or path.startswith(runtime_parent + "/"):
                    kernel.os.meta.pop(path)
                    kernel.os.files.pop(path, None)
            return result
        if (
            unhealthy_before_install
            and argv[0] == kernel.scope.binding.sdk
            and argv[1:3] == ("-I", "-c")
        ):
            return b'{"status":200,"body":{"required_ok":false}}'
        return original_response(argv, payload)

    kernel.response, kernel.os.execve = response, execve
    local_inputs = target.LOCAL_DEV_WORKTREE + "/.codex-tmp/portable-dev-entry/"
    for name, content in (
        ("request.json", json.dumps(packet).encode()),
        ("source.tar", archive),
        ("manifest.json", manifest),
        ("custody.py", (PUBLIC / "scripts/probe_upgrade_operation.py").read_bytes()),
    ):
        kernel.os.add(local_inputs + name, content)
    output = io.StringIO()
    try:
        with (
            patch.object(
                target.LinuxDependencies, "standard_library", return_value=kernel.dependencies
            ),
            contextlib.redirect_stdout(output),
        ):
            code = target.main(
                [
                    "--request",
                    local_inputs + "request.json",
                    "--archive",
                    local_inputs + "source.tar",
                    "--manifest",
                    local_inputs + "manifest.json",
                    "--custody-source",
                    local_inputs + "custody.py",
                ]
            )
        case.assertEqual(
            78
            if unhealthy_before_install or foreign_state_after_guard or publication_refused
            else 0,
            code,
        )
        result = json.loads(output.getvalue())
    except target.Unknown:
        if not lost_transport_ack:
            if hasattr(kernel, "port_failure"):
                raise kernel.port_failure
            raise
        result = {"status": "UNKNOWN", "live_acceptance": False}
    finally:
        sys.modules.pop("fixed_dev_program", None)
    if temporary and not original_service_inactive:
        case.assertNotIn(config_path, kernel.os.files)
    else:
        case.assertEqual(config, kernel.os.files[config_path])
    case.assertFalse(kernel.os.fds)
    case.assertTrue(all(selector.closed for selector in kernel.selectors))
    case.assertTrue(
        all(
            stream.closed
            for process in kernel.processes
            for stream in (process.stdin, process.stdout, process.stderr)
        )
    )
    case.assertEqual(1, sum(argv[0] == "/usr/bin/ssh" for argv in calls))
    if publication_refused:
        case.assertEqual(
            ["serialized-remote-entry", "cold-first-preflight", "publication-refused-before-sdk"],
            stages,
        )
        case.assertEqual([], case.h.deliveries)
        case.assertEqual(original_unit, kernel.unit)
        case.assertFalse(
            any(
                path == root + "/source"
                or path.startswith(root + "/source/")
                or path.startswith("/run/systemd/system/")
                or path
                in {root + "/probe-state", root + "/native-input.json", root + "/request.json"}
                for path in kernel.os.meta
            )
        )
        case.assertFalse(
            any(
                argv
                in {
                    target.systemd("start"),
                    target.systemd("stop"),
                    target.systemd("reload_for_temporary_dev"),
                }
                or argv[0] == "/usr/bin/systemd-run"
                and "--watch-dev-operation" in argv
                for argv in calls
            )
        )
        return result, kernel
    completed_stage = (
        "unhealthy-before-installation"
        if unhealthy_before_install
        else "foreign-state-before-first-start"
        if foreign_state_after_guard
        else "qualified-worker-complete"
    )
    case.assertEqual(
        ["serialized-remote-entry", "cold-first-preflight", "qualified-sdk-exec", completed_stage],
        stages,
    )
    case.assertEqual(
        0 if unhealthy_before_install or foreign_state_after_guard else 2, len(case.h.deliveries)
    )
    if unhealthy_before_install:
        case.assertNotIn(root + "/probe-state", kernel.os.meta)
        case.assertFalse(
            any(
                path == root + "/source" or path.startswith(root + "/source/")
                for path in kernel.os.meta
            )
        )
        case.assertFalse(any(path.startswith("/run/systemd/system/") for path in kernel.os.meta))
        case.assertFalse(
            any(
                argv
                in {
                    target.systemd("start"),
                    target.systemd("stop"),
                    target.systemd("reload_for_temporary_dev"),
                }
                for argv in calls
            )
        )
        case.assertEqual("not-found", kernel.unit["LoadState"])
    if temporary_install and not foreign_state_after_guard:
        case.assertEqual(target.unit_profile(original_unit), target.unit_profile(kernel.unit))
        if original_state_directory_present:
            case.assertEqual(original_state_identity, kernel.os.meta[state_parent])
        else:
            case.assertNotIn(state_parent, kernel.os.meta)
        case.assertNotIn(runtime_parent, kernel.os.meta)
        case.assertNotIn(root + "/probe-state", kernel.os.meta)
        case.assertIn(("mkdir", root + "/probe-state", root), kernel.os.mount_writes)
        case.assertIn(("rmdir", root + "/probe-state", root), kernel.os.mount_writes)
        case.assertFalse(
            any(
                path == root + "/source" or path.startswith(root + "/source/")
                for path in kernel.os.meta
            )
        )
        case.assertFalse(any(path.startswith("/run/systemd/system/") for path in kernel.os.meta))
    if foreign_state_after_guard:
        changed_state = (
            state_parent if foreign_state_after_guard == "canonical" else root + "/probe-state"
        )
        case.assertEqual(98765, kernel.os.meta[changed_state].st_ino)
        case.assertFalse(any(argv == target.systemd("start") for argv in calls))
    case.assertIsNone(kernel.os.files.get(kernel.scope.binding.state_file))
    case.assertFalse(
        any(
            path == state_parent or path.startswith(state_parent + "/")
            for _, path, _ in kernel.os.mount_writes
        )
    )
    case.assertFalse(any("--channel" in argv and "test" in argv for argv in calls))
    return result, kernel


def test_actual_dev_cli_qualifies_reversed_wildcard_pair_and_refuses_ambiguous_ports():
    for refused in (False, True):
        case = NativeBindingTests()
        case.setUp()
        try:
            result, _ = whole_native_call(
                case,
                api_publication=[
                    {"HostIp": "::", "HostPort": "47778" if refused else "47777"},
                    {"HostIp": "0.0.0.0", "HostPort": "47777"},
                ],
                publication_refused=refused,
            )
            case.assertEqual("REFUSED" if refused else "PASS", result["status"])
            if refused:
                case.assertEqual("first_preflight", result["phase"])
                case.assertEqual(
                    "actual_dev_api_publication_ambiguous_or_unsupported", result["reason"]
                )
                case.assertFalse(result["live_acceptance"])
            else:
                case.assertTrue(result["config_restored"] and result["same_correlation"])
                case.assertGreaterEqual(result["completed_later_suppressions"], 2)
        finally:
            case.doCleanups()
            case.tearDown()


def test_real_import_from_non_owner_checkout_uses_only_filesystem_port_mapping():
    import importlib.util

    with tempfile.TemporaryDirectory(prefix="portable-dev-source-") as directory:
        copied_path = Path(directory) / "probe_dev_outage_operation.py"
        copied_path.write_bytes(Path(target.__file__).read_bytes())
        spec = importlib.util.spec_from_file_location("portable_copied_dev_program", copied_path)
        copied = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {spec.name: copied}):
            spec.loader.exec_module(copied)
            with patch.object(sys.modules[__name__], "target", copied):
                case = NativeBindingTests()
                case.setUp()
                try:
                    case.assertNotEqual(copied.__file__, copied.LOCAL_DEV_PROGRAM)
                    case.assertEqual(
                        copied.__file__, copied.run_claimed_local_caller.__code__.co_filename
                    )
                    # Actual CLI -> serialized remote entry plus all existing
                    # wrong cwd/module/bytes/interpreter and authority negatives.
                    case.test_actual_local_caller_executes_serialized_dataclass_envelope_with_absolute_tools_and_home()
                finally:
                    case.doCleanups()
                    case.tearDown()


def test_actual_dev_invocation_enforces_bindings_and_custody():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, kernel = whole_native_call(case)
        case.assertEqual("probe_dev_outage_recovery.v1", result["schema"])
        case.assertEqual(
            ("PASS", "dev", "ygg-dev"), (result["status"], result["environment"], result["target"])
        )
        case.assertEqual(
            (1, 1, True), (result["down"], result["recovery"], result["same_correlation"])
        )
        case.assertGreaterEqual(result["completed_later_suppressions"], 2)
        case.assertTrue(result["config_restored"] and result["independent_guard_disarmed"])
        case.assertTrue(result["supervisor"]["reaped"] and result["supervisor"]["cgroup_empty"])
    finally:
        case.doCleanups()
        case.tearDown()


def test_dev_refusal_and_unknown_preserve_owner_and_state():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, kernel = whole_native_call(case, lost_transport_ack=True)
        case.assertEqual({"status": "UNKNOWN", "live_acceptance": False}, result)
        case.assertIn(kernel.scope.root + "/result.json", kernel.os.files)
        case.assertTrue(all(socket.fileno() == -1 for socket in kernel.dependencies.socket.created))
    finally:
        case.doCleanups()
        case.tearDown()


def test_unhealthy_actual_first_preflight_has_zero_probe_installation_writes():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(case, unhealthy_before_install=True)
        case.assertEqual("REFUSED", result["status"])
        case.assertFalse(result["live_acceptance"])
        case.assertEqual("qualified_worker", result["phase"])
        case.assertEqual("independent_readyz_or_required_health_unhealthy", result["reason"])
    finally:
        case.doCleanups()
        case.tearDown()


def test_actual_temporary_dev_installation_restores_original_directory_absence():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(case, temporary_install=True)
        case.assertEqual("PASS", result["status"])
        case.assertEqual("absent", result["original_service"])
        case.assertTrue(result["original_lifecycle_and_artifacts_restored"])
        case.assertEqual(
            {
                "original_state": "absent",
                "state_restored": True,
                "runtime_restored": True,
                "operation_state_removed": True,
            },
            result["temporary_directories"],
        )
    finally:
        case.doCleanups()
        case.tearDown()


def test_actual_temporary_directory_owner_loss_is_unknown_before_first_start():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(case, temporary_install=True, foreign_state_after_guard=True)
        case.assertEqual("UNKNOWN", result["status"])
        case.assertFalse(result["live_acceptance"])
        case.assertEqual("temporary_probe_state_directory_owner_changed", result["reason"])
    finally:
        case.doCleanups()
        case.tearDown()


def test_actual_temporary_dev_installation_preserves_original_empty_directory():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(
            case, temporary_install=True, original_state_directory_present=True
        )
        case.assertEqual("PASS", result["status"])
        case.assertEqual(
            {
                "original_state": "present",
                "state_restored": True,
                "runtime_restored": True,
                "operation_state_removed": True,
            },
            result["temporary_directories"],
        )
    finally:
        case.doCleanups()
        case.tearDown()


def test_actual_temporary_dev_state_is_confined_for_inactive_original_service():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(
            case,
            temporary_install=True,
            original_service_inactive=True,
            original_state_directory_present=True,
        )
        case.assertEqual("PASS", result["status"])
        case.assertEqual("inactive", result["original_service"])
        case.assertTrue(result["temporary_directories"]["operation_state_removed"])
    finally:
        case.doCleanups()
        case.tearDown()


def test_actual_temporary_dev_preserves_foreign_canonical_state_directory():
    case = NativeBindingTests()
    case.setUp()
    try:
        result, _ = whole_native_call(
            case, temporary_install=True, foreign_state_after_guard="canonical"
        )
        case.assertEqual("UNKNOWN", result["status"])
        case.assertFalse(result["live_acceptance"])
        case.assertEqual("canonical_probe_state_directory_changed", result["reason"])
    finally:
        case.doCleanups()
        case.tearDown()


if __name__ == "__main__":
    unittest.main()
