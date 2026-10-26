"""Fixed BWS-only systemd boundary for the ONE #3347 installation invocation.

No CLI, observer mode, retry, daemon-reload, controller change or default run.
The owner must enter the actual admitted operational window and prove the whole
old cleanup path BEFORE calling stop_old. This file does not supply that window,
private predecessor binding, protected-state proof, or application/JSON closure.

Read properties use existing systemd's typed busctl JSON, never a journal/log or
formatted human-status parser. Unsupported/missing busctl refuses BEFORE stop;
no package/runtime installation or fallback is provided. The only effect verbs
are one stop and one later start of the already authenticated BWS unit. The
administrative ignore-dependencies mode bounds the queued job to that unit;
OnFailure/OnSuccess and activation triggers must be absent. This is not a general
service-management API and is not permission to invoke it on a native host.
"""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Any, Iterator, NoReturn

LAUNCHER = '/usr/local/libexec/yggdrasil-bws-deploy'
RUNTIME = '/opt/yggdrasil/bws-deploy-runtime/bin/python3'
CONTROL_DIRECTORY = '/opt/yggdrasil/bws-control'
_CONTROL_OWNER_UID = 0
_CONTROL_OWNER_GID = 0
PROC = Path('/proc')
BUS = 'org.freedesktop.systemd1'
MANAGER = '/org/freedesktop/systemd1'
EXEC_TYPE = 'a(sasbttttuii)'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
       'SYSTEMD_COLORS': '0', 'SYSTEMD_PAGER': ''}


def _refuse() -> NoReturn:
    raise RuntimeError('bws_lifecycle_unproven') from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _refuse()
        value[key] = item
    return value


def _run(argv: list[str]) -> bytes:
    # No caller environment, credential, shell, stdin, pager or remote bus.
    if os.geteuid() != 0 or sys.platform != 'linux':
        _refuse()
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, env=ENV,
            capture_output=True, check=False, timeout=60)
        if (completed.returncode != 0 or completed.stderr
                or type(completed.stdout) is not bytes or len(completed.stdout) > 131072):
            _refuse()
        return completed.stdout
    except Exception:
        # No exception's argv/stdout/stderr/private value becomes a diagnostic.
        # A timeout or unknown action return is never translated into stopped.
        _refuse()


def _typed(argv: list[str], signature: str) -> Any:
    try:
        value = json.loads(_run(argv), object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != {'type', 'data'} or value['type'] != signature:
            _refuse()
        return value['data']
    except Exception:
        _refuse()


def _runtime_identity(value: os.stat_result) -> tuple[int, ...]:
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or value.st_gid != 0
            or value.st_mode & 0o022 or not value.st_mode & 0o111):
        _refuse()
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid,
            value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _runtime_version() -> tuple[int, ...]:
    # The accepted V5 preflight separately qualifies this registered alias.
    # Keep its exact target/version stable through this lifecycle; do not pick
    # another interpreter or treat matching argv text as executable identity.
    try:
        return _runtime_identity(os.stat(RUNTIME))
    except Exception:
        _refuse()


def _application_projection(value: Any) -> dict[str, Any]:
    if (type(value) is not dict
            or set(value) != {'path', 'device', 'inode', 'uid', 'gid', 'mode'}
            or type(value['path']) is not str or not value['path'].startswith('/')
            or any(part in {'', '.', '..'} for part in value['path'].split('/')[1:])
            or '\\' in value['path'] or '\0' in value['path']
            or any(type(value[key]) is not int for key in ('device', 'inode', 'uid', 'gid', 'mode'))
            or value['device'] < 0 or value['inode'] <= 0
            or value['uid'] != _CONTROL_OWNER_UID or value['gid'] != _CONTROL_OWNER_GID
            or value['mode'] not in {0o700, 0o755}):
        _refuse()
    return dict(value)


def _public_launcher_bytes() -> bytes:
    """Read the fixed public launcher under the body's retained-before context."""
    fd = None
    try:
        fd = os.open(LAUNCHER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != 0o755 or before.st_nlink != 1
                or not 0 < before.st_size <= 65536 or os.get_inheritable(fd)):
            _refuse()
        raw = os.pread(fd, before.st_size + 1, 0)
        def version(value: os.stat_result) -> tuple[int, ...]:
            return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                    value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) != before.st_size or version(os.fstat(fd)) != version(before)
                or version(os.stat(LAUNCHER, follow_symlinks=False)) != version(before)):
            _refuse()
        return raw
    except Exception:
        _refuse()
    finally:
        if fd is not None:
            os.close(fd)


def require_no_cleanup_callers(channel: str, *, caller_pid: int | None = None) -> None:
    """Refuse old cleanup and request processes across the caller replacement window."""
    if channel not in {'dev', 'test'}:
        _refuse()
    proc_fd: int | None = None
    try:
        proc_fd = os.open(PROC, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        entries = os.listdir(proc_fd)
        pids = [entry for entry in entries if entry.isascii() and entry.isdigit()]
        if len(pids) > 8192:
            _refuse()
        for pid in pids:
            descriptor: int | None = None
            command_fd: int | None = None
            try:
                try:
                    descriptor = os.open(
                        pid, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=proc_fd,
                    )
                except FileNotFoundError:
                    continue
                before = os.fstat(descriptor)
                if not stat.S_ISDIR(before.st_mode):
                    _refuse()
                command_fd = os.open(
                    'cmdline', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=descriptor,
                )
                command = os.read(command_fd, 65537)
                if len(command) > 65536:
                    _refuse()
                named = os.stat(pid, dir_fd=proc_fd, follow_symlinks=False)
                repeated = os.pread(command_fd, 65537, 0)
                if ((named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                        or repeated != command):
                    _refuse()
                arguments = command.rstrip(b'\0').split(b'\0') if command else []
                entrypoints = [index for index, item in enumerate(arguments)
                               if item == LAUNCHER.encode()
                               or item.endswith(b'/scripts/postgres_deploy_service.py')]
                for index in entrypoints:
                    if index + 2 >= len(arguments):
                        continue
                    action, selected_channel = arguments[index + 1:index + 3]
                    if (selected_channel == channel.encode() and action != b'serve'
                            and pid != str(caller_pid)):
                        _refuse()
            except FileNotFoundError:
                # A caller that exited during this read can no longer mutate.
                continue
            except Exception:
                _refuse()
            finally:
                for fd in (command_fd, descriptor):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            _refuse()
    except Exception:
        _refuse()
    finally:
        if proc_fd is not None:
            try:
                os.close(proc_fd)
            except OSError:
                _refuse()


def _discovered_control_projection(
    launcher: bytes, environment: list[str], environment_files: list[list[Any]],
) -> dict[str, Any]:
    """Verify the fixed control root, using a public hint when one is present.

    The configured control root is already fixed by this owner contract. A hint
    may select a deeper path under it; without one, verify the fixed root's
    deployment anchor directly. This is support topology, never a loaded-import claim.
    No environment file contents, credentials, journal or private source is read.
    Each candidate is confined to the fixed control subtree; missing paths may
    ascend to their existing anchor, but symlink/foreign/ambiguous roots refuse.
    """
    descriptors = []
    try:
        discovery = launcher.decode('utf-8') + '\n' + '\n'.join(environment)
        discovery += '\n' + '\n'.join(row[0] for row in environment_files)
        candidates = sorted(set(re.findall(re.escape(CONTROL_DIRECTORY) + r'/[A-Za-z0-9._/-]+', discovery)))
        if not candidates:
            candidates = [CONTROL_DIRECTORY + '/app/ops/postgres_deploy_linux.py']
        if len(candidates) > 16:
            _refuse()

        def directory(
            name: str, parent: int | None = None, *, allow_0750_ancestor: bool = False,
        ) -> int:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         **({} if parent is None else {'dir_fd': parent}))
            descriptors.append(fd)
            info = os.fstat(fd)
            allowed_modes = {0o700, 0o750, 0o755} if allow_0750_ancestor else {0o700, 0o755}
            if (not stat.S_ISDIR(info.st_mode)
                    or (info.st_uid, info.st_gid) not in {
                        (0, 0), (_CONTROL_OWNER_UID, _CONTROL_OWNER_GID),
                    }
                    or stat.S_IMODE(info.st_mode) not in allowed_modes or os.get_inheritable(fd)):
                _refuse()
            return fd

        def anchor(parent: int) -> bool:
            # ENOTDIR also covers a symlink on some hosts: stat first, no-follow,
            # and reject it explicitly instead of mistaking it for an absent dir.
            try:
                for name in ('app', 'ops'):
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        _refuse()
                    if not stat.S_ISDIR(info.st_mode):
                        return False
                    parent = directory(name, parent)
                info = os.stat('postgres_deploy_linux.py', dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid != _CONTROL_OWNER_UID or info.st_gid != _CONTROL_OWNER_GID
                    or stat.S_IMODE(info.st_mode) != 0o644 or info.st_nlink != 1):
                _refuse()
            return True

        root = directory('/')
        control_parts = Path(CONTROL_DIRECTORY).parts[1:]
        for index, name in enumerate(control_parts):
            root = directory(name, root, allow_0750_ancestor=index < len(control_parts) - 1)
        roots = {}
        for candidate in candidates:
            parts = candidate[len(CONTROL_DIRECTORY) + 1:].rstrip('/').split('/')
            if len(parts) > 32 or any(name in {'', '.', '..'} for name in parts):
                _refuse()
            ancestors = [(CONTROL_DIRECTORY, root)]
            for name in parts:
                path, parent = ancestors[-1]
                try:
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        _refuse()
                    if not stat.S_ISDIR(info.st_mode):
                        break
                    child = directory(name, parent, allow_0750_ancestor=True)
                except FileNotFoundError:
                    break
                ancestors.append((path + '/' + name, child))
            for path, fd in reversed(ancestors):
                if anchor(fd):
                    info = os.fstat(fd)
                    if stat.S_IMODE(info.st_mode) not in {0o700, 0o755}:
                        _refuse()
                    roots[path] = dict(path=path, device=info.st_dev, inode=info.st_ino,
                                      uid=info.st_uid, gid=info.st_gid, mode=stat.S_IMODE(info.st_mode))
                    break
        if len(roots) != 1:
            _refuse()
        return next(iter(roots.values()))
    except Exception:
        _refuse()
    finally:
        unknown = False
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                unknown = True
        if unknown:
            _refuse()


def _pid_token(
    unit: str, channel: str, pid: int, application: dict[str, Any],
    runtime_version: tuple[int, ...],
) -> str:
    """Same unit/PID/kernel-start token as the accepted finite V5 projection.

    This additionally requires only the main task in this process. It is NOT a
    full machine census, and never claims that task count freezes admission.
    The cwd must be the configured application FD projection held by the BODY,
    not merely any root-first launcher argv. Kernel exe follows the accepted
    registered runtime alias, whose target/version must remain unchanged.
    """
    if type(pid) is not int or not 0 < pid < 2**31:
        _refuse()
    descriptor = os.open(PROC / str(pid), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        initial = os.fstat(descriptor)
        if initial.st_uid != 0 or not stat.S_ISDIR(initial.st_mode):
            _refuse()

        def read(name: str, limit: int) -> bytes:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                info = os.fstat(fd)
                if info.st_uid != 0 or not stat.S_ISREG(info.st_mode):
                    _refuse()
                data = os.read(fd, limit + 1)
                if not 0 < len(data) <= limit:
                    _refuse()
                return data
            finally:
                os.close(fd)

        def identity() -> str:
            raw = read('stat', 16384)
            match = re.fullmatch(rb'([1-9][0-9]*) \((.*)\) ([^\n]+)\n?', raw)
            if match is None or int(match[1]) != pid:
                _refuse()
            fields = match[3].split()
            if (len(fields) < 20 or fields[0] not in {b'R', b'S', b'D', b'I'}
                    or not fields[19].isdigit()):
                _refuse()
            uid = [line.split()[1:] for line in read('status', 65536).splitlines() if line.startswith(b'Uid:')]
            if uid != [[b'0', b'0', b'0', b'0']]:
                _refuse()
            if read('cmdline', 16384) != b'\0'.join(
                    part.encode() for part in (RUNTIME, LAUNCHER, 'serve', channel)) + b'\0':
                _refuse()
            try:
                cwd = os.stat('cwd', dir_fd=descriptor)
                exe = os.stat('exe', dir_fd=descriptor)
                if (not stat.S_ISDIR(cwd.st_mode)
                        or (cwd.st_dev, cwd.st_ino, cwd.st_uid, cwd.st_gid, stat.S_IMODE(cwd.st_mode))
                        != tuple(application[key] for key in ('device', 'inode', 'uid', 'gid', 'mode'))
                        or os.readlink('cwd', dir_fd=descriptor) != application['path']
                        or (exe.st_dev, exe.st_ino) != runtime_version[:2]
                        or _runtime_version() != runtime_version):
                    _refuse()
            except Exception:
                # Never include a proc target, runtime path or caller value in
                # the emitted error. Missing/changed links are unknown, not idle.
                _refuse()
            tasks = os.open('task', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                if os.listdir(tasks) != [str(pid)]:
                    _refuse()
            finally:
                os.close(tasks)
            return fields[19].decode('ascii')

        start = identity()
        named = os.stat(PROC / str(pid), follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (initial.st_dev, initial.st_ino) or identity() != start:
            _refuse()
        return hashlib.sha256(f'{unit}:{pid}:{start}'.encode()).hexdigest()
    finally:
        os.close(descriptor)


class FixedBwsService:
    def __init__(self, *, unit: str, channel: str) -> None:
        if (channel not in {'dev', 'test'} or type(unit) is not str
                or unit != f'yggdrasil-bws-deploy@{channel}.service'):
            _refuse()
        self.unit, self.channel = unit, channel
        self.object: str | None = None
        self.phase = 'unqualified'
        self.old_pid: int | None = None
        self.old_token: str | None = None
        self.contract: tuple[Any, ...] | None = None
        self.cleanup: list[Any] | None = None
        self.stop_started: int | None = None
        self.application: dict[str, Any] | None = None
        self.runtime_version: tuple[int, ...] | None = None
        self.control: dict[str, Any] | None = None
        self.launcher_before: bytes | None = None
        self.launcher_after: bytes | None = None
        self.new_pid: int | None = None
        self.new_token: str | None = None
        self.runtime_fd: int | None = None
        self.runtime_context_started = self.runtime_close_completed = False

    def _held_runtime(self) -> None:
        try:
            if self.runtime_version is None:
                _refuse()
            if self.runtime_fd is None:
                if self.runtime_close_completed and _runtime_version() == self.runtime_version:
                    return
                _refuse()
            if (os.get_inheritable(self.runtime_fd)
                    or fcntl.fcntl(self.runtime_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
                    or _runtime_identity(os.fstat(self.runtime_fd)) != self.runtime_version
                    or _runtime_version() != self.runtime_version):
                _refuse()
        except Exception:
            _refuse()

    def _runtime_contract(self) -> tuple[dict[str, Any], tuple[int, ...]]:
        if self.application is None or self.runtime_version is None:
            _refuse()
        return self.application, self.runtime_version

    @contextmanager
    def retained_runtime(self) -> Iterator[None]:
        """Own ONE read-only FD to the accepted alias target through body close.

        Following the already registered alias is intentional; no interpreter
        replacement, target-path fallback, executable read or execution occurs.
        The outer admitted window must already be held. This pins identity and
        rechecks metadata; it is NOT exclusion of independent runtime writers.
        """
        if self.phase != 'unqualified' or self.runtime_context_started:
            _refuse()
        self.runtime_context_started = True
        fd: int | None = None
        version: tuple[int, ...] | None = None
        owned_identity: tuple[int, int] | None = None
        body_entered = False
        try:
            try:
                version = _runtime_version()
                fd = os.open(RUNTIME, os.O_RDONLY | os.O_NONBLOCK)
                info = os.fstat(fd)
                owned_identity = (info.st_dev, info.st_ino)
                self.runtime_fd, self.runtime_version = fd, version
                self._held_runtime()
            except Exception:
                _refuse()
            body_entered = True
            yield
        finally:
            unknown = False
            if fd is not None:
                # Retain the original local FD/identity, not a reconstructed
                # handle or a newly opened alias. Before yield this context
                # alone owns the just-opened FD, even if its first fstat fails.
                # After yield, never close an unexpectedly reused foreign inode.
                # Do all version/alias rechecks BEFORE deciding close ownership:
                # those reads may observe reuse, so an earlier identity snapshot
                # must not remain authority for closing the replacement FD.
                try:
                    self._held_runtime()
                except Exception:
                    unknown = True
                try:
                    info = os.fstat(fd)
                    still_owned = not body_entered or (info.st_dev, info.st_ino) == owned_identity
                except Exception:
                    still_owned = not body_entered
                # This final comparison is not an atomic compare-and-close OS
                # primitive: the assembled caller must still exclude independent
                # in-process FD mutation. Never retry an uncertain close.
                if still_owned:
                    try:
                        os.close(fd)
                    except OSError:
                        unknown = True
                else:
                    unknown = True
                self.runtime_fd = None
            if unknown:
                # Never retry close: the FD may already have been released.
                _refuse()
            self.runtime_close_completed = fd is not None

    def _call(self, method: str, signature: str) -> Any:
        # Only these two read-only Manager methods are constructed here.
        if method not in {'GetUnit', 'GetUnitProcesses'}:
            _refuse()
        value = _typed(['busctl', '--system', '--no-pager', '--json=short',
            '--auto-start=no', '--allow-interactive-authorization=no', '--timeout=30s',
            'call', BUS, MANAGER, BUS + '.Manager', method, 's', self.unit], signature)
        if type(value) is not list or len(value) != 1:
            _refuse()
        return value[0]

    def _get(self, interface: str, name: str, signature: str) -> Any:
        if self.object is None:
            _refuse()
        return _typed(['busctl', '--system', '--no-pager', '--json=short',
            '--auto-start=no', '--allow-interactive-authorization=no', '--timeout=30s',
            'get-property', BUS, self.object, BUS + '.' + interface, name], signature)

    def _exec(self, name: str, action: str | None = None) -> list[Any]:
        rows = self._get('Service', name, EXEC_TYPE)
        if action is None:
            if rows != []:
                _refuse()
            return []
        if type(rows) is not list or len(rows) != 1:
            _refuse()
        row = rows[0]
        if (type(row) is not list or len(row) != 10
                or row[:3] != [LAUNCHER, [LAUNCHER, action, self.channel], False]
                or type(row[2]) is not bool
                or any(type(value) is not int or value < 0 for value in row[3:])):
            _refuse()
        return row

    def _config(self) -> tuple[Any, ...]:
        self._held_runtime()
        for interface, values in (
            ('Unit', {'Id': self.unit, 'LoadState': 'loaded'}),
            ('Service', {'Type': 'simple', 'User': 'root', 'Group': 'root',
                         'KillMode': 'control-group', 'Restart': 'on-failure'}),
        ):
            for key, expected in values.items():
                if self._get(interface, key, 's') != expected:
                    _refuse()
        for name in ('OnFailure', 'OnSuccess', 'TriggeredBy'):
            if self._get('Unit', name, 'as') != []:
                _refuse()
        for name in ('ExecCondition', 'ExecStartPre', 'ExecStartPost', 'ExecStop', 'ExecReload'):
            self._exec(name)
        start = self._exec('ExecStart', 'serve')
        cleanup = self._exec('ExecStopPost', 'cleanup')
        environment = self._get('Service', 'Environment', 'as')
        files = self._get('Service', 'EnvironmentFiles', 'a(sb)')
        if (type(environment) is not list or len(environment) > 128
                or any(type(value) is not str or '\0' in value or len(value) > 16384 for value in environment)
                or type(files) is not list or len(files) > 32
                or any(type(row) is not list or len(row) != 2 or type(row[0]) is not str
                       or '\0' in row[0] or len(row[0]) > 4096 or type(row[1]) is not bool for row in files)):
            _refuse()
        launcher = _public_launcher_bytes()
        allowed = (
            (self.launcher_before,) if self.phase in {
                'qualifying', 'restore_start_requested', 'old_kernel_restored', 'restored_stop_requested',
            } else
            (self.launcher_before, self.launcher_after) if self.phase == 'qualified' else
            (self.launcher_after,) if self.phase in {
                'stop_requested', 'stopped_checked', 'start_requested', 'new_kernel_checked',
                'new_stop_requested', 'new_stopped_checked',
            } else
            (self.launcher_before, self.launcher_after)
        )
        if launcher not in allowed:
            _refuse()
        # Qualify the proposed public launcher against the SAME current typed
        # unit configuration before backup/stop. Old-only hints must not allow
        # an installation whose final root-first launcher loses this topology.
        if self.launcher_after is None or self.control is None:
            _refuse()
        for raw in (launcher, self.launcher_after):
            if _discovered_control_projection(raw, environment, files) != self.control:
                _refuse()
        hints = hashlib.sha256(json.dumps([environment, files], separators=(',', ':')).encode()).hexdigest()
        return start[:3], cleanup[:3], hints

    def _state(self, active: bool) -> int:
        expected = ('active', 'running') if active else ('inactive', 'dead')
        if (self._get('Unit', 'ActiveState', 's'), self._get('Unit', 'SubState', 's')) != expected:
            _refuse()
        job = self._get('Unit', 'Job', '(uo)')
        if (type(job) is not list or len(job) != 2 or type(job[0]) is not int
                or job[0] != 0 or job[1] != '/'):
            _refuse()
        control = self._get('Service', 'ControlPID', 'u')
        pid = self._get('Service', 'MainPID', 'u')
        if type(control) is not int or control != 0 or type(pid) is not int:
            _refuse()
        if (active and not 0 < pid < 2**31) or (not active and pid != 0):
            _refuse()
        return pid

    def _single_process(self, pid: int) -> None:
        rows = self._call('GetUnitProcesses', 'a(sus)')
        if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not list
                or len(rows[0]) != 3 or type(rows[0][1]) is not int or rows[0][1] != pid):
            _refuse()
        # Raw cgroup/name data are neither returned nor printed.

    def qualify_old(
        self, expected_service_identity: str | None = None, *, application_root: dict[str, Any],
        control_root: dict[str, Any], launcher_content: dict[str, Any],
    ) -> None:
        if (self.phase != 'unqualified' or (expected_service_identity is not None
                and (type(expected_service_identity) is not str
                     or re.fullmatch('[0-9a-f]{64}', expected_service_identity) is None))):
            _refuse()
        self._held_runtime()
        self.phase = 'qualifying'
        application = _application_projection(application_root)
        control = _application_projection(control_root)
        self.application = application
        self.control = control
        if (control['path'] == application['path']
                or not (control['path'] == CONTROL_DIRECTORY
                        or control['path'].startswith(CONTROL_DIRECTORY + '/'))):
            _refuse()
        try:
            if (type(launcher_content) is not dict or set(launcher_content) != {'sha256', 'base64'}
                    or type(launcher_content['base64']) is not str):
                _refuse()
            proposed_launcher = base64.b64decode(launcher_content['base64'], validate=True)
            if (not 0 < len(proposed_launcher) <= 65536
                    or hashlib.sha256(proposed_launcher).hexdigest() != launcher_content['sha256']):
                _refuse()
            self.launcher_after = proposed_launcher
        except Exception:
            _refuse()
        self.launcher_before = _public_launcher_bytes()
        self.object = self._call('GetUnit', 'o')
        if (type(self.object) is not str
                or re.fullmatch(r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]+', self.object) is None):
            _refuse()
        self.contract = self._config()
        old_pid = self._state(True)
        runtime_version = self.runtime_version
        if runtime_version is None:
            _refuse()
        self.old_pid = old_pid
        self._single_process(old_pid)
        old_token = _pid_token(self.unit, self.channel, old_pid, application, runtime_version)
        self.old_token = old_token
        if expected_service_identity is not None and old_token != expected_service_identity:
            _refuse()
        self.cleanup = self._exec('ExecStopPost', 'cleanup')
        self.phase = 'qualified'

    def stop_old(self) -> None:
        if (self.phase != 'qualified' or self.launcher_after is None
                or _public_launcher_bytes() != self.launcher_after):
            _refuse()
        if self._config() != self.contract or self._state(True) != self.old_pid:
            _refuse()
        self._single_process(self.old_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.old_pid,
                      application, runtime_version) != self.old_token:
            _refuse()
        # Recorded BEFORE the action; an uncertain return can never be retried.
        self.stop_started = time.monotonic_ns() // 1000
        self.phase = 'stop_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'stop', self.unit])
        self._stopped()
        self.phase = 'stopped_checked'

    def require_old_kernel(self, *, launcher_content: bytes) -> None:
        """Recheck the exact old process and selected launcher bytes before stop."""
        if (type(launcher_content) is not bytes
                or launcher_content not in {self.launcher_before, self.launcher_after}):
            _refuse()
        if (self.phase != 'qualified' or self.old_pid is None or self.old_token is None
                or self._config() != self.contract or self._state(True) != self.old_pid
                or _public_launcher_bytes() != launcher_content):
            _refuse()
        self._single_process(self.old_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.old_pid, application, runtime_version) != self.old_token:
            _refuse()

    def _stopped(self) -> None:
        if self._config() != self.contract or self._state(False) != 0:
            _refuse()
        if self._get('Service', 'Result', 's') != 'success':
            _refuse()
        row = self._exec('ExecStopPost', 'cleanup')
        cleanup = self.cleanup
        stop_started = self.stop_started
        if cleanup is None or stop_started is None:
            _refuse()
        # D-Bus tuple: path, argv, ignore, start-real, start-mono, end-real,
        # end-mono, pid, wait-code, status. Require THIS invocation's cleanup,
        # not a stale successful prior stop or an ignored/signalled command.
        if (not stop_started <= row[4] <= row[6] <= time.monotonic_ns() // 1000
                or row[4] <= cleanup[4] or row[3] <= 0 or row[5] < row[3]
                or row[7] <= 0 or row[8:] != [1, 0]):
            _refuse()
        if self._call('GetUnitProcesses', 'a(sus)') != []:
            _refuse()
        try:
            os.stat(PROC / str(self.old_pid), follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            # Even reuse of this PID is outside this exact stopped proof.
            _refuse()

    def require_stopped(self) -> None:
        if self.phase not in {'stopped_checked', 'new_stopped_checked', 'restored_stopped_checked'}:
            _refuse()
        self._stopped()

    def start_new(self) -> None:
        self.require_stopped()
        if _public_launcher_bytes() != self.launcher_after:
            _refuse()
        self.phase = 'start_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'start', self.unit])
        # Type=simple success is deliberately NOT accepted as kernel/closure proof.

    def require_new_kernel(self) -> str:
        if self.phase != 'start_requested' or self._config() != self.contract:
            _refuse()
        pid = self._state(True)
        self._single_process(pid)
        application, runtime_version = self._runtime_contract()
        token = _pid_token(self.unit, self.channel, pid, application, runtime_version)
        if token == self.old_token:
            _refuse()
        self.new_pid, self.new_token = pid, token
        self.phase = 'new_kernel_checked'
        return token

    def require_same_new_kernel(self) -> None:
        # Closing the file handle/module cannot silently turn an intervening
        # restart or changed unit/launcher/runtime topology into success. This
        # rechecks the SAME generation inside the still-held outer reservation;
        # it never adopts another PID or starts/retries a unit.
        if (self.phase != 'new_kernel_checked' or self.new_pid is None
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.new_pid,
                      application, runtime_version) != self.new_token:
            _refuse()

    def stop_new(self) -> None:
        """Stop only the exact candidate process already authenticated by this lifecycle."""
        if (self.phase != 'new_kernel_checked' or self.new_pid is None or self.new_token is None
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.new_pid,
                      application, runtime_version) != self.new_token:
            _refuse()
        self.stop_started = time.monotonic_ns() // 1000
        self.phase = 'new_stop_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'stop', self.unit])
        self._stopped()
        self.phase = 'new_stopped_checked'

    def stop_restored_old(self) -> None:
        """Stop only the exact restored-old process after a final close-boundary failure."""
        if (self.phase != 'old_kernel_restored' or self.new_pid is None or self.new_token is None
                or _public_launcher_bytes() != self.launcher_before
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.new_pid,
                      application, runtime_version) != self.new_token:
            _refuse()
        self.stop_started = time.monotonic_ns() // 1000
        self.phase = 'restored_stop_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'stop', self.unit])
        self._stopped()
        self.phase = 'restored_stopped_checked'

    def stop_failed_start_if_exact(self) -> None:
        """Quiesce a failed start only after proving it is this unit's new process."""
        if self.phase != 'start_requested' or self._config() != self.contract:
            _refuse()
        pid = self._state(True)
        self._single_process(pid)
        application, runtime_version = self._runtime_contract()
        token = _pid_token(self.unit, self.channel, pid, application, runtime_version)
        if token == self.old_token:
            _refuse()
        self.new_pid, self.new_token = pid, token
        self.phase = 'new_kernel_checked'
        self.stop_new()

    def start_restored_old(self) -> None:
        """Start the exact old source only after the caller proved same-handle restore."""
        self.require_stopped()
        if _public_launcher_bytes() != self.launcher_before:
            _refuse()
        self.phase = 'restore_start_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'start', self.unit])

    def require_restored_old_kernel(self) -> str:
        if self.phase != 'restore_start_requested' or self._config() != self.contract:
            _refuse()
        if _public_launcher_bytes() != self.launcher_before:
            _refuse()
        pid = self._state(True)
        self._single_process(pid)
        application, runtime_version = self._runtime_contract()
        token = _pid_token(self.unit, self.channel, pid, application, runtime_version)
        if token == self.old_token:
            _refuse()
        self.new_pid, self.new_token = pid, token
        self.phase = 'old_kernel_restored'
        return token

    def require_same_restored_old_kernel(self) -> None:
        if (self.phase != 'old_kernel_restored' or self.new_pid is None
                or _public_launcher_bytes() != self.launcher_before
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        application, runtime_version = self._runtime_contract()
        if _pid_token(self.unit, self.channel, self.new_pid,
                      application, runtime_version) != self.new_token:
            _refuse()
