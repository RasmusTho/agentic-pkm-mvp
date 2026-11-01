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
_SYSTEMD_DIRECTORY = '/etc/systemd/system'
_DROPIN_MAX_BYTES = 4096
_DROPIN_MAX_INPUTS = 4
_CONTROL_OWNER_UID = 0
_CONTROL_OWNER_GID = 0
PROC = Path('/proc')
BUS = 'org.freedesktop.systemd1'
MANAGER = '/org/freedesktop/systemd1'
EXEC_TYPE = 'a(sasbttttuii)'
_CONTROL_PROJECTION_MAX_HINTS = 16
_CONTROL_PROJECTION_MAX_COMPONENTS = 32
_CONTROL_PROJECTION_ANCHOR_COMPONENTS = 2
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
       'SYSTEMD_COLORS': '0', 'SYSTEMD_PAGER': ''}


# Values describe public guard families, never native values or exception text.
_OLD_QUALIFICATION_SUBGATES = frozenset({
    'setup', 'retained_runtime', 'unit_properties', 'root_control',
    'launcher', 'service_process', 'cleanup_contract',
})


# Source symbols only. Value cases are existing unit-property predicates;
# launcher/process/cleanup/root semantic refusals retain their own families.
_UNIT_PROPERTY_VALUE_SITES = frozenset(
    ('Unit_Id Unit_LoadState Unit_OnFailure Unit_OnSuccess Unit_TriggeredBy '
     'Service_Type Service_User Service_Group Service_KillMode Service_Restart '
     'Service_RootDirectory Service_RootImage Service_WorkingDirectory Service_BindPaths '
     'Service_BindReadOnlyPaths Service_TemporaryFileSystem Service_ReadOnlyPaths '
     'Service_ReadWritePaths Service_InaccessiblePaths Service_PassEnvironment '
     'Service_ExtensionDirectories Service_MountImages Service_ExtensionImages Service_PAMName '
     'Service_UnsetEnvironment Service_ExecSearchPath Service_PrivateMounts Service_PrivateTmp '
     'Service_PrivateDevices Service_PrivateUsers Service_DynamicUser Service_ProtectHome '
     'Service_ProtectSystem Unit_DropInPaths Unit_JoinsNamespaceOf').split()
)
_UNIT_PROPERTY_READ_SITES = _UNIT_PROPERTY_VALUE_SITES | frozenset(
    ('Manager_GetUnit Manager_GetUnitProcesses Service_ExecCondition Service_ExecStartPre '
     'Service_ExecStartPost Service_ExecStop Service_ExecReload Service_ExecStart '
     'Service_ExecStopPost Service_ExecStopPost_final Service_Environment Service_EnvironmentFiles '
     'Unit_ActiveState Unit_SubState Unit_Job Service_ControlPID Service_MainPID').split()
)
_DROPIN_SELECTOR_CATEGORIES = frozenset({
    'cardinality', 'allowed_parent', 'basename_length', 'basename_grammar',
})
_UNIT_PROPERTY_REFINEMENTS = frozenset(
    (site, kind) for site in _UNIT_PROPERTY_READ_SITES
    for kind in ('backend', 'decode', 'signature', 'shape')
) | frozenset((site, 'value') for site in _UNIT_PROPERTY_VALUE_SITES) | frozenset({
    ('Unit_DropInPaths', 'selection'), ('Unit_DropInPaths', 'unsupported'),
}) | frozenset(('Unit_DropInPaths', kind) for kind in _DROPIN_SELECTOR_CATEGORIES)


class _OldQualificationRefusal(RuntimeError):
    def __init__(
        self, subgate: str | None = None, *,
        root_control: tuple[str, str, str, str] | None = None,
        unit_property: tuple[str, str] | None = None,
        read_kind: str | None = None,
    ) -> None:
        # Receipt consumers separately check the complete closed combination.
        self.root_control = (root_control if type(root_control) is tuple
                             and len(root_control) == 4
                             and all(type(value) is str for value in root_control) else None)
        self.unit_property = (unit_property if type(unit_property) is tuple
                              and len(unit_property) == 2
                              and all(type(value) is str for value in unit_property)
                              and unit_property in _UNIT_PROPERTY_REFINEMENTS else None)
        self.read_kind = (read_kind if type(read_kind) is str
                          and read_kind in {'backend', 'decode', 'signature', 'shape'} else None)
        self.subgate = (subgate if type(subgate) is str
                        and subgate in _OLD_QUALIFICATION_SUBGATES else None)
        super().__init__('bws_lifecycle_unproven')


def _refuse(subgate: str | None = None) -> NoReturn:
    raise _OldQualificationRefusal(subgate) from None


class _LifecycleCloseUncertain(RuntimeError):
    """One original finite lifecycle reader close has an unknown outcome."""


def _close_lifecycle_reader(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        raise _LifecycleCloseUncertain('bws_lifecycle_unproven') from None


def _control_projection_descriptor_bound() -> int:
    """Bound all descriptors retained by one control projection call.

    Each accepted hint can retain its complete 32-component descent and the
    two-directory anchor probes at each of the 33 possible ancestors until the
    call returns. The fixed root walk is retained once per call.
    """
    fixed_root_descriptors = len(Path(CONTROL_DIRECTORY).parts)
    ancestors_per_hint = _CONTROL_PROJECTION_MAX_COMPONENTS + 1
    per_hint = (_CONTROL_PROJECTION_MAX_COMPONENTS
                + _CONTROL_PROJECTION_ANCHOR_COMPONENTS * ancestors_per_hint)
    return max(fixed_root_descriptors + _CONTROL_PROJECTION_MAX_HINTS * per_hint,
               2 * _control_path_descriptor_bound() + 1)


# The PATH-specific namespace is deliberately finite and has no content reader.
_CONTROL_PATH_MAX_ENTRIES = 128
_CONTROL_PATH_MAX_DIRECTORIES = 4 * 33 + 16 * 32


def _control_path_descriptor_bound() -> int:
    # Existing control/effect walks, fixed systemd ancestry, both supported unit
    # directories and all selected files. Revalidation retains a second walk.
    return (_CONTROL_PATH_MAX_DIRECTORIES + len(Path(_SYSTEMD_DIRECTORY).parts)
            + 2 + _DROPIN_MAX_INPUTS)


def _preserved_dropin_path(paths: Any, channel: str) -> tuple[str, ...]:
    if type(paths) is not list:
        _unit_read_refuse('shape')
    if len(paths) > _DROPIN_MAX_INPUTS:
        _dropin_selector_refuse('cardinality')
    allowed = {f'{_SYSTEMD_DIRECTORY}/yggdrasil-bws-deploy@{instance}.service.d'
               for instance in ('', channel)}
    names: set[str] = set()
    for path in paths:
        if type(path) is not str:
            _unit_read_refuse('shape')
        parent, _, name = path.rpartition('/')
        if parent not in allowed:
            _dropin_selector_refuse('allowed_parent')
        if len(name) > 80:
            _dropin_selector_refuse('basename_length')
        if re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\.conf', name) is None:
            _dropin_selector_refuse('basename_grammar')
        if name in names:
            _refuse('unit_properties')
        names.add(name)
    return tuple(paths)


def _dropin_selector_refuse(category: str) -> NoReturn:
    if category not in _DROPIN_SELECTOR_CATEGORIES:
        _refuse('unit_properties')
    raise _OldQualificationRefusal(
        'unit_properties', unit_property=('Unit_DropInPaths', category),
    ) from None


def _preserved_path_assignment(raw: bytes) -> str:
    # One existing regex, not a second syntax classifier.
    match = re.fullmatch(rb'\[Service\]\nEnvironment=(PATH=[A-Za-z0-9_./:+-]+|"PATH=[A-Za-z0-9_./:+-]+")\n', raw)
    if match is None:
        _root_control_refuse('grammar', mode='path_selected', role='selected_content')
    assignment = match[1].strip(b'"').decode('ascii')
    _control_path_slots([assignment], mode='path_selected', role='parsed_slots')
    return assignment


def _control_path_mount(fd: int, *, mode: str = 'path_absent', role: str = 'directory') -> int:
    """Read the Linux mount identity of an already held directory (no pathname IO)."""
    import ctypes
    import struct
    if sys.platform != 'linux':
        _root_control_refuse('mount_platform', mode=mode, role=role)
    site = 'mount_libc_unknown'
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        site = 'mount_buffer_unknown'
        result = ctypes.create_string_buffer(256)  # Linux UAPI struct statx
        site = 'mount_statx_unknown'
        if libc.statx(fd, b'', 0x1000 | 0x100 | 0x800, 0x1000, result) != 0:
            _root_control_refuse('mount_statx', mode=mode, role=role)
        site = 'mount_unpack_unknown'
        mask = struct.unpack_from('=I', result.raw, 0)[0]
        mount = struct.unpack_from('=Q', result.raw, 144)[0]
        if not mask & 0x1000:
            _root_control_refuse('mount_mask', mode=mode, role=role)
        if mount == 0:
            _root_control_refuse('mount_identity', mode=mode, role=role)
        return mount
    except _OldQualificationRefusal:
        raise
    except Exception:
        _root_control_refuse(site, mode=mode, role=role)


def _control_path_slots(environment: list[str], *, mode: str = 'path_environment',
                        role: str = 'loaded_slots') -> tuple[str, ...]:
    def refuse(guard: str) -> NoReturn:
        _root_control_refuse(guard, mode=mode, role=role)

    paths = [value[5:] for value in environment if value.startswith('PATH=')]
    if len(paths) != 1:
        refuse('path_population')
    if any(CONTROL_DIRECTORY in value for value in environment if not value.startswith('PATH=')):
        refuse('non_path_hint')
    components = paths[0].split(':')
    if not 0 < len(components) <= _CONTROL_PROJECTION_MAX_HINTS:
        refuse('hint_bound')
    for path in components:
        if not path.startswith('/'):
            refuse('path_absolute')
        if '\\' in path:
            refuse('path_backslash')
        if '\0' in path:
            refuse('path_nul')
        if any(part in {'', '.', '..'} for part in path.split('/')[1:]):
            refuse('path_canonical')
        if len(path.split('/')) > _CONTROL_PROJECTION_MAX_COMPONENTS + 1:
            refuse('component_bound')
        if CONTROL_DIRECTORY in path and not (
                path == CONTROL_DIRECTORY or path.startswith(CONTROL_DIRECTORY + '/')):
            refuse('misleading_hint')
    slots = tuple(path for path in components if path == CONTROL_DIRECTORY
                  or path.startswith(CONTROL_DIRECTORY + '/'))
    if not slots:
        refuse('slot_absent')
    if len(set(components)) != len(components):
        refuse('duplicate_components')
    return slots


class _ControlPathBinding:
    """Retained control-slot metadata and optional preserved PATH-file proof.

    All forward/restore/staging effects are below disjoint application, launcher
    and backup roots. The control tree receives no writes. Reject all mount
    crossings (including same-device bind mounts), rather than guessing aliases.
    No directory listing outside a selected control slot, or recursion, occurs.
    """

    def __init__(self, control: dict[str, Any], slots: tuple[str, ...],
                 footprint: tuple[dict[str, Any], ...], effect_parents: tuple[str, ...],
                 selected_dropins: tuple[str, ...] = ()) -> None:
        self.control, self.slots, self.footprint = control, slots, footprint
        self.effect_parents = effect_parents
        self.selected_dropins = selected_dropins
        self.path_assignment: str | None = None
        self.close_uncertain = False
        self.fds: dict[str, tuple[int, tuple[int, ...]]] = {}
        self.closed = False
        self.snapshot: tuple[Any, ...] | None = None

    @staticmethod
    def _identity(fd: int, *, mode: str = 'path_absent', role: str = 'directory') -> tuple[int, ...]:
        site = 'directory_fstat_unknown'
        try:
            value = os.fstat(fd)
            if not stat.S_ISDIR(value.st_mode):
                _root_control_refuse('directory_type', mode=mode, role=role)
            if value.st_mode & 0o022:
                _root_control_refuse('directory_mode', mode=mode, role=role)
            if (value.st_uid, value.st_gid) not in {(0, 0), (_CONTROL_OWNER_UID, _CONTROL_OWNER_GID)}:
                _root_control_refuse('directory_owner', mode=mode, role=role)
            site = 'directory_inheritable_unknown'
            if os.get_inheritable(fd):
                _root_control_refuse('directory_inheritable', mode=mode, role=role)
            return (value.st_dev, value.st_ino, value.st_uid, value.st_gid,
                    stat.S_IMODE(value.st_mode), _control_path_mount(fd, mode=mode, role=role))
        except _OldQualificationRefusal:
            raise
        except Exception:
            _root_control_refuse(site, mode=mode, role=role)

    def _input_identity(self, path: str, fd: int, *, mode: str = 'path_absent',
                        role: str = 'retained') -> tuple[int, ...]:
        if path not in self.selected_dropins:
            return self._identity(fd, mode=mode, role=role + '_directory')
        role += '_input'
        site = 'file_fstat_unknown'
        try:
            value = os.fstat(fd)
            if not stat.S_ISREG(value.st_mode):
                _root_control_refuse('file_type', mode=mode, role=role)
            if value.st_nlink != 1:
                _root_control_refuse('file_link', mode=mode, role=role)
            if (value.st_uid, value.st_gid) != (_CONTROL_OWNER_UID, _CONTROL_OWNER_GID):
                _root_control_refuse('file_owner', mode=mode, role=role)
            if value.st_mode & 0o133:
                _root_control_refuse('file_mode', mode=mode, role=role)
            if not 0 < value.st_size:
                _root_control_refuse('file_size_positive', mode=mode, role=role)
            if not value.st_size <= _DROPIN_MAX_BYTES:
                _root_control_refuse('file_size_bound', mode=mode, role=role)
            site = 'file_inheritable_unknown'
            if os.get_inheritable(fd):
                _root_control_refuse('file_inheritable', mode=mode, role=role)
            site = 'file_access_unknown'
            if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
                _root_control_refuse('file_access', mode=mode, role=role)
            return (value.st_dev, value.st_ino, value.st_uid, value.st_gid,
                    stat.S_IMODE(value.st_mode), _control_path_mount(fd, mode=mode, role=role), value.st_nlink,
                    value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        except _OldQualificationRefusal:
            raise
        except Exception:
            _root_control_refuse(site, mode=mode, role=role)

    def _close(self, fds: dict[str, tuple[int, tuple[int, ...]]]) -> bool:
        unknown = False
        for fd, identity in reversed(tuple(fds.values())):
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != identity[:2]:
                    unknown = True
                    continue  # Never close a replacement descriptor.
                os.close(fd)
            except Exception:
                unknown = True
        fds.clear()
        self.close_uncertain |= unknown
        return not self.close_uncertain

    def close(self) -> None:
        self.closed = True
        if not self._close(self.fds):
            _refuse('retained_runtime')

    def revalidate(self) -> tuple[Any, ...]:
        opened: dict[str, tuple[int, tuple[int, ...]]] = {}
        keep = False
        mode = 'path_selected' if self.selected_dropins else 'path_absent'
        site = ('walk', 'unexpected_unknown')

        def refuse(guard: str, role: str) -> NoReturn:
            _root_control_refuse(guard, mode=mode, role=role)
        try:
            if self.close_uncertain:
                _refuse('retained_runtime')
            for path, (fd, identity) in self.fds.items():
                if self._input_identity(path, fd, mode=mode, role='retained') != identity:
                    refuse('retained_version', 'retained')

            def directory(path: str, role: str) -> int:
                nonlocal site
                if path in opened:
                    return opened[path][0]
                parts = path.split('/')[1:]
                if path != '/':
                    if not path.startswith('/'):
                        refuse('directory_absolute', role)
                    if len(parts) > 32:
                        refuse('directory_component_bound', role)
                    if any(p in {'', '.', '..'} for p in parts):
                        refuse('directory_canonical', role)
                parent_path, _, name = path.rpartition('/')
                parent = None if path == '/' else directory(parent_path or '/', 'ancestor')
                if len(opened) >= _control_path_descriptor_bound():
                    refuse('descriptor_bound', role)
                site = (role, 'open_unknown')
                fd = os.open('/' if parent is None else name,
                             os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             **({} if parent is None else {'dir_fd': parent}))
                # Even a failing first metadata read must close the original FD.
                try:
                    identity = self._identity(fd, mode=mode, role=role)
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        self.close_uncertain = True
                        _refuse('retained_runtime')
                    raise
                site = ('walk', 'unexpected_unknown')
                opened[path] = (fd, identity)
                if parent is not None and identity[5] != opened['/'][1][5]:
                    refuse('mount_crossing', role)
                return fd

            if type(self.footprint) is not tuple:
                refuse('tuple_type', 'footprint')
            if len(self.footprint) != 3:
                refuse('population', 'footprint')
            if any(type(root) is not dict for root in self.footprint):
                refuse('member_mapping', 'footprint')
            site = ('walk', 'unexpected_unknown')
            roots = (self.control, *self.footprint)
            for index, root in enumerate(roots):
                path = root['path']
                for other_index, other in enumerate(roots[:index]):
                    if path == other['path']:
                        refuse('equal', 'roots')
                    if path.startswith(other['path'] + '/'):
                        # Public schema positions only, selected after the same
                        # original predicate; never inspect another root pair.
                        refuse('below', (
                            ('roots_application_control',),
                            ('roots_launcher_control', 'roots_launcher_application'),
                            ('roots_backup_control', 'roots_backup_application', 'roots_backup_launcher'),
                        )[index - 1][other_index])
                    if other['path'].startswith(path + '/'):
                        refuse('above', 'roots')
                fd = directory(path, ('control_root', 'application_root', 'launcher_root', 'backup_root')[index])
                site = ('walk', 'unexpected_unknown')
                if opened[path][1][:5] != tuple(root[key] for key in ('device', 'inode', 'uid', 'gid', 'mode')):
                    refuse('recorded_identity', 'roots')
            if type(self.effect_parents) is not tuple:
                refuse('tuple_type', 'effect_parents')
            if not self.effect_parents:
                refuse('empty', 'effect_parents')
            if len(self.effect_parents) > _CONTROL_PATH_MAX_DIRECTORIES:
                refuse('bound', 'effect_parents')
            if any(type(path) is not str for path in self.effect_parents):
                refuse('member_type', 'effect_parents')
            if len(set(self.effect_parents)) != len(self.effect_parents):
                refuse('duplicate', 'effect_parents')
            for path in self.effect_parents:
                if not any(path == root['path'] or path.startswith(root['path'] + '/')
                           for root in self.footprint[:2]):
                    refuse('outside_effect', 'effect_parents')
                # Every admitted target's staging/replacement/restore parent,
                # not just the top-level roots, must have this lookup view.
                directory(path, 'effect_parent')
            # Select and inspect the entire vector before any content read. A
            # later invalid member must never leave an adopted earlier subset.
            selected_files: list[tuple[str, int, tuple[int, ...]]] = []
            total_size = 0
            for path in self.selected_dropins:
                selected_parent, _, name = path.rpartition('/')
                # Full root/target-parent/staging/restoration footprint is already
                # retained above. Same-mount no-follow walks exclude bind aliases;
                # the selected directory must be disjoint from every effect root.
                for root in roots:
                    if selected_parent == root['path']:
                        refuse('equal', 'selected_parent')
                    if selected_parent.startswith(root['path'] + '/'):
                        refuse('below', 'selected_parent')
                    if root['path'].startswith(selected_parent + '/'):
                        refuse('above', 'selected_parent')
                parent_fd = directory(selected_parent, 'selected_parent')
                if any(opened[selected_parent][1][:2] == opened[root['path']][1][:2] for root in roots):
                    refuse('identity_alias', 'selected_parent')
                if len(opened) >= _control_path_descriptor_bound():
                    refuse('descriptor_bound', 'selected_file')
                site = ('selected_file', 'open_unknown')
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                try:
                    identity = self._input_identity(path, fd, mode=mode, role='selected')
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        self.close_uncertain = True
                        _refuse('retained_runtime')
                    raise
                site = ('walk', 'unexpected_unknown')
                opened[path] = (fd, identity)
                if identity[5] != opened['/'][1][5]:
                    refuse('mount_crossing', 'selected_file')
                if any(identity[:2] == prior[2][:2] for prior in selected_files):
                    refuse('identity_alias', 'selected_file')
                selected_files.append((path, fd, identity))
                total_size += identity[7]
            if total_size > _DROPIN_MAX_BYTES:
                refuse('aggregate_size', 'selected_file')
            selected_projection: list[tuple[str, str, str]] = []
            remaining = _DROPIN_MAX_BYTES
            assignment: str | None = None
            for path, fd, identity in selected_files:
                # One shared budget and one sentinel for the entire walk,
                # including growth/short-read/grammar failures.
                site = ('selected_content', 'pread_unknown')
                raw = os.pread(fd, remaining + 1, 0)
                site = ('walk', 'unexpected_unknown')
                remaining -= len(raw)
                if len(raw) != identity[7]:
                    refuse('returned_length', 'selected_content')
                if self._input_identity(path, fd, mode=mode, role='content') != identity:
                    refuse('post_read_version', 'selected_content')
                current_assignment = _preserved_path_assignment(raw)
                if assignment is not None and current_assignment != assignment:
                    refuse('assignment_disagreement', 'selected_content')
                assignment = current_assignment
                selected_projection.append((path, hashlib.sha256(raw).hexdigest(), assignment))
            control_fd = opened[self.control['path']][0]
            for name in ('app', 'scripts'):
                site = ('loader_' + name, 'stat_unknown')
                try:
                    os.stat(name, dir_fd=control_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                site = ('walk', 'unexpected_unknown')
                refuse('present', 'loader_' + name)
            observations: list[tuple[str, Any]] = []
            for slot in self.slots:
                current = self.control['path']
                missing = None
                for name in slot[len(current):].strip('/').split('/') if slot != current else ():
                    parent = directory(current, 'slot_descent')
                    site = ('slot_descent', 'stat_unknown')
                    try:
                        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        missing = (current, name)
                        break
                    if not stat.S_ISDIR(info.st_mode):
                        refuse('not_directory', 'slot_descent')
                    current += '/' + name
                    directory(current, 'slot_descent')
                if missing is not None:
                    observations.append((slot, missing))
                    continue
                fd = directory(current, 'slot_census')
                site = ('slot_census', 'before_fstat_unknown')
                before = os.fstat(fd)
                entries: list[tuple[Any, ...]] = []
                # scandir holds at most one extra FD; iteration is bounded before stat.
                site = ('slot_census', 'scandir_open_unknown')
                with os.scandir(fd) as iterator:
                    try:
                        site = ('slot_census', 'scandir_iteration_unknown')
                        for entry in iterator:
                            if len(entries) >= _CONTROL_PATH_MAX_ENTRIES:
                                refuse('entry_bound', 'slot_census')
                            site = ('slot_census', 'entry_stat_unknown')
                            info = entry.stat(follow_symlinks=False)
                            if (info.st_uid, info.st_gid) != (_CONTROL_OWNER_UID, _CONTROL_OWNER_GID):
                                refuse('entry_owner', 'slot_census')
                            if info.st_mode & 0o022:
                                refuse('entry_mode', 'slot_census')
                            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                                refuse('entry_type', 'slot_census')
                            if stat.S_ISREG(info.st_mode):
                                if info.st_mode & 0o111:
                                    refuse('entry_executable', 'slot_census')
                                if info.st_nlink != 1:
                                    refuse('entry_link', 'slot_census')
                            # Direct subdirectories remain uninspected.
                            entries.append((entry.name, info.st_dev, info.st_ino, info.st_mode,
                                            info.st_uid, info.st_gid, info.st_nlink,
                                            info.st_mtime_ns, info.st_ctime_ns))
                            site = ('slot_census', 'scandir_iteration_unknown')
                    except _OldQualificationRefusal:
                        raise
                    except Exception:
                        refuse(site[1], site[0])
                    finally:
                        site = ('slot_census', 'scandir_exit_unknown')
                site = ('slot_census', 'after_fstat_unknown')
                after = os.fstat(fd)
                if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
                    refuse('directory_time_drift', 'slot_census')
                observations.append((slot, tuple(sorted(entries))))
            for slot, observation in observations:
                if type(observation) is tuple and len(observation) == 2 and type(observation[0]) is str:
                    missing_parent, name = observation
                    site = ('absent_edge', 'stat_unknown')
                    try:
                        os.stat(name, dir_fd=opened[missing_parent][0], follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    refuse('appeared', 'absent_edge')
            # Recheck every held/current ancestor edge including the lookup root.
            for path, (fd, identity) in opened.items():
                parent_path, _, name = path.rpartition('/')
                site = ('current_edge', 'stat_unknown')
                current = os.stat('/' if path == '/' else name, follow_symlinks=False,
                                  **({} if path == '/' else {'dir_fd': opened[parent_path or '/'][0]}))
                if self._input_identity(path, fd, mode=mode, role='current') != identity:
                    refuse('held_version', 'current_edge')
                if (current.st_dev, current.st_ino) != identity[:2]:
                    refuse('edge_identity', 'current_edge')
                site = ('fresh_edge', 'open_unknown')
                current_fd = os.open('/' if path == '/' else name,
                                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                                     | (0 if path in self.selected_dropins else os.O_DIRECTORY),
                                     **({} if path == '/' else {'dir_fd': opened[parent_path or '/'][0]}))
                try:
                    if self._input_identity(path, current_fd, mode=mode, role='fresh') != identity:
                        refuse('version', 'fresh_edge')
                finally:
                    try:
                        os.close(current_fd)
                    except OSError:
                        self.close_uncertain = True
                        _refuse('retained_runtime')
            site = ('walk', 'unexpected_unknown')
            snapshot: tuple[Any, ...] = (tuple((p, identity) for p, (_fd, identity) in sorted(opened.items())),
                        tuple(observations))
            if selected_projection:
                snapshot += (tuple(selected_projection),)
            if self.snapshot is not None and snapshot != self.snapshot:
                refuse('disagreement', 'snapshot')
            if self.snapshot is None:
                self.snapshot = snapshot
                self.fds, keep = opened, True
            self.path_assignment = assignment
            return snapshot
        except _OldQualificationRefusal:
            raise
        except Exception:
            refuse(site[1], site[0])
        finally:
            if not keep and not self._close(opened):
                _refuse('retained_runtime')


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _refuse()
        value[key] = item
    return value


def _unit_read_refuse(kind: str) -> NoReturn:
    raise _OldQualificationRefusal('unit_properties', read_kind=kind) from None


def _run(argv: list[str]) -> bytes:
    # No caller environment, credential, shell, stdin, pager or remote bus.
    if os.geteuid() != 0 or sys.platform != 'linux':
        _unit_read_refuse('backend')
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, env=ENV,
            capture_output=True, check=False, timeout=60)
        if (completed.returncode != 0 or completed.stderr
                or type(completed.stdout) is not bytes or len(completed.stdout) > 131072):
            _unit_read_refuse('backend')
        return completed.stdout
    except Exception:
        # No exception's argv/stdout/stderr/private value becomes a diagnostic.
        # A timeout or unknown action return is never translated into stopped.
        _unit_read_refuse('backend')


def _typed(argv: list[str], signature: str) -> Any:
    # Keep transport provenance from this original read; never re-run a call.
    raw = _run(argv)
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
    except Exception:
        _unit_read_refuse('decode')
    if type(value) is not dict or set(value) != {'type', 'data'}:
        _unit_read_refuse('shape')
    if value['type'] != signature:
        _unit_read_refuse('signature')
    return value['data']


def _runtime_identity(value: os.stat_result) -> tuple[int, ...]:
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or value.st_gid != 0
            or value.st_mode & 0o022 or not value.st_mode & 0o111):
        _refuse('retained_runtime')
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid,
            value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _runtime_version() -> tuple[int, ...]:
    # The accepted V5 preflight separately qualifies this registered alias.
    # Keep its exact target/version stable through this lifecycle; do not pick
    # another interpreter or treat matching argv text as executable identity.
    try:
        return _runtime_identity(os.stat(RUNTIME))
    except Exception:
        _refuse('retained_runtime')


def _root_control_refuse(guard: str, *, mode: str = 'unknown',
                         side: str = 'unknown', role: str) -> NoReturn:
    raise _OldQualificationRefusal(
        'root_control', root_control=(mode, side, role, guard),
    ) from None


def _application_projection(value: Any, *, role: str = 'application',
                            mode: str = 'unknown', side: str = 'unknown') -> dict[str, Any]:
    # Split the original short circuit in its original order. Never re-read a
    # predicate to classify it after failure, or include the offending value.
    def refuse(guard: str) -> NoReturn:
        _root_control_refuse(guard, mode=mode, side=side, role=role)

    if type(value) is not dict:
        refuse('mapping_type')
    if set(value) != {'path', 'device', 'inode', 'uid', 'gid', 'mode'}:
        refuse('fields')
    if type(value['path']) is not str:
        refuse('path_type')
    if not value['path'].startswith('/'):
        refuse('path_absolute')
    if any(part in {'', '.', '..'} for part in value['path'].split('/')[1:]):
        refuse('path_canonical')
    if '\\' in value['path']:
        refuse('path_backslash')
    if '\0' in value['path']:
        refuse('path_nul')
    for key in ('device', 'inode', 'uid', 'gid', 'mode'):
        if type(value[key]) is not int:
            refuse(key + '_type')
    if value['device'] < 0:
        refuse('device_range')
    if value['inode'] <= 0:
        refuse('inode_range')
    if value['uid'] != _CONTROL_OWNER_UID:
        refuse('uid')
    if value['gid'] != _CONTROL_OWNER_GID:
        refuse('gid')
    if value['mode'] not in {0o700, 0o755}:
        refuse('mode')
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
            _refuse('launcher')
        raw = os.pread(fd, before.st_size + 1, 0)
        def version(value: os.stat_result) -> tuple[int, ...]:
            return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
                    value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) != before.st_size or version(os.fstat(fd)) != version(before)
                or version(os.stat(LAUNCHER, follow_symlinks=False)) != version(before)):
            _refuse('launcher')
        return raw
    except Exception:
        _refuse('launcher')
    finally:
        if fd is not None:
            _close_lifecycle_reader(fd)


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
    launcher: bytes, environment: list[str], environment_files: list[list[Any]], *,
    expected_empty_control_root: dict[str, Any] | None = None,
    side: str = 'unknown',
) -> dict[str, Any]:
    """Verify the fixed control root, using public hints only for anchored roots.

    The configured control root is already fixed by this owner contract. A hint
    may select a deeper path under it; without one, verify the fixed root's
    deployment anchor directly. This is support topology, never a loaded-import claim.
    No environment file contents, credentials, journal or private source is read.
    Each candidate is confined to the fixed control subtree; missing paths may
    ascend to their existing anchor, but symlink/foreign/ambiguous roots refuse.
    A transaction-captured empty source root may use the fixed root itself only
    while its identity is unchanged and both loader packages remain absent.
    """
    descriptors = []
    mode = 'unknown'
    site = ('discovery', 'decode_unknown')

    def refuse(guard: str, role: str) -> NoReturn:
        _root_control_refuse(guard, mode=mode, side=side, role=role)

    try:
        decoded = launcher.decode('utf-8')
        site = ('discovery', 'environment_unknown')
        discovery = decoded + '\n' + '\n'.join(environment)
        site = ('discovery', 'environment_files_unknown')
        discovery += '\n' + '\n'.join(row[0] for row in environment_files)
        if expected_empty_control_root is None:
            mode = 'anchored_discovery'
            site = ('discovery', 'candidates_unknown')
            candidates = sorted(set(re.findall(
                re.escape(CONTROL_DIRECTORY) + r'/[A-Za-z0-9._/-]+', discovery,
            )))
        else:
            mode = 'captured_empty'
            # Keep the second original decode and hint short circuit. No new
            # reads, accepted hint format, or continuation after a refusal.
            site = ('discovery', 'empty_decode_unknown')
            if CONTROL_DIRECTORY in launcher.decode('utf-8'):
                refuse('launcher_hint', 'hints')
            site = ('discovery', 'empty_environment_unknown')
            if any(CONTROL_DIRECTORY in value for value in environment):
                refuse('environment_hint', 'hints')
            site = ('discovery', 'empty_environment_files_unknown')
            if any(CONTROL_DIRECTORY in row[0] for row in environment_files):
                refuse('environment_files_hint', 'hints')
            candidates = []
        if not candidates:
            candidates = [CONTROL_DIRECTORY + '/app/ops/postgres_deploy_linux.py']
        if len(candidates) > _CONTROL_PROJECTION_MAX_HINTS:
            refuse('candidate_count', 'hints')

        def directory(
            name: str, parent: int | None = None, *, allow_0750_ancestor: bool = False,
            role: str,
        ) -> int:
            nonlocal site
            site = (role, 'open_unknown')
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         **({} if parent is None else {'dir_fd': parent}))
            descriptors.append(fd)
            site = (role, 'fstat_unknown')
            info = os.fstat(fd)
            allowed_modes = {0o700, 0o750, 0o755} if allow_0750_ancestor else {0o700, 0o755}
            if not stat.S_ISDIR(info.st_mode):
                refuse('directory_type', role)
            if (info.st_uid, info.st_gid) not in {
                (0, 0), (_CONTROL_OWNER_UID, _CONTROL_OWNER_GID),
            }:
                refuse('owner_pair', role)
            if stat.S_IMODE(info.st_mode) not in allowed_modes:
                refuse('directory_mode', role)
            site = (role, 'inheritable_unknown')
            if os.get_inheritable(fd):
                refuse('inheritable', role)
            return fd

        def anchor(parent: int) -> bool:
            nonlocal site
            # Missing/non-directory loader slots still mean false, including
            # FileNotFoundError raised by directory() inside this same try.
            try:
                for name, role in (('app', 'anchor_app'), ('ops', 'anchor_ops')):
                    site = (role, 'stat_unknown')
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        refuse('loader_symlink', role)
                    if not stat.S_ISDIR(info.st_mode):
                        return False
                    parent = directory(name, parent, role=role)
                site = ('anchor_file', 'stat_unknown')
                info = os.stat('postgres_deploy_linux.py', dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISREG(info.st_mode):
                refuse('file_type', 'anchor_file')
            if info.st_uid != _CONTROL_OWNER_UID:
                refuse('uid', 'anchor_file')
            if info.st_gid != _CONTROL_OWNER_GID:
                refuse('gid', 'anchor_file')
            if stat.S_IMODE(info.st_mode) != 0o644:
                refuse('file_mode', 'anchor_file')
            if info.st_nlink != 1:
                refuse('link_count', 'anchor_file')
            return True

        def projection(fd: int, path: str = CONTROL_DIRECTORY, *, role: str) -> dict[str, Any]:
            nonlocal site
            site = (role, 'fstat_unknown')
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                refuse('directory_type', role)
            site = (role, 'construction_unknown')
            return dict(path=path, device=info.st_dev, inode=info.st_ino,
                        uid=info.st_uid, gid=info.st_gid, mode=stat.S_IMODE(info.st_mode))

        root = directory('/', role='fixed_origin')
        site = ('discovery', 'control_parts_unknown')
        control_parts = Path(CONTROL_DIRECTORY).parts[1:]
        for index, name in enumerate(control_parts):
            ancestor = index < len(control_parts) - 1
            root = directory(name, root, allow_0750_ancestor=ancestor,
                             role='fixed_ancestor' if ancestor else 'fixed_root')
        roots = {}
        for candidate in candidates:
            site = ('candidate', 'components_unknown')
            parts = candidate[len(CONTROL_DIRECTORY) + 1:].rstrip('/').split('/')
            if len(parts) > _CONTROL_PROJECTION_MAX_COMPONENTS:
                refuse('component_count', 'candidate')
            if any(name in {'', '.', '..'} for name in parts):
                refuse('components_canonical', 'candidate')
            ancestors = [(CONTROL_DIRECTORY, root)]
            for name in parts:
                path, parent = ancestors[-1]
                try:
                    site = ('candidate', 'stat_unknown')
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        refuse('symlink', 'candidate')
                    if not stat.S_ISDIR(info.st_mode):
                        break
                    child = directory(name, parent, allow_0750_ancestor=True, role='candidate')
                except FileNotFoundError:
                    break
                ancestors.append((path + '/' + name, child))
            for path, fd in reversed(ancestors):
                if anchor(fd):
                    site = ('anchor_root', 'fstat_unknown')
                    info = os.fstat(fd)
                    if stat.S_IMODE(info.st_mode) not in {0o700, 0o755}:
                        refuse('directory_mode', 'anchor_root')
                    roots[path] = projection(fd, path, role='candidate_projection')
                    break
        if expected_empty_control_root is not None:
            expected = _application_projection(
                expected_empty_control_root, role='expected_empty', mode=mode, side=side,
            )
            actual = projection(root, role='fixed_projection')
            if actual != expected:
                refuse('identity', 'empty_root')
            if roots:
                refuse('anchored_root_present', 'empty_root')
            # Any slot entry still refuses, with the same per-slot stat calls.
            for name, role in (('app', 'app_slot'), ('scripts', 'scripts_slot')):
                try:
                    site = (role, 'stat_unknown')
                    os.stat(name, dir_fd=root, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                refuse('present', role)

            current_root = directory('/', role='reopen_origin')
            for index, name in enumerate(control_parts):
                ancestor = index < len(control_parts) - 1
                current_root = directory(
                    name, current_root, allow_0750_ancestor=ancestor,
                    role='reopen_ancestor' if ancestor else 'reopen_root',
                )
            if projection(current_root, role='reopen_projection') != actual:
                refuse('reopen_identity', 'empty_root')
            return actual
        count = len(roots)
        if count != 1:
            refuse('no_anchor' if count == 0 else 'multiple_anchors', 'anchored_roots')
        return next(iter(roots.values()))
    except Exception as failure:
        if type(failure) is _OldQualificationRefusal:
            # Preserve only this supported type, not attrs on a foreign error.
            # The finite consumer validates every tuple again before emission.
            if failure.subgate == 'root_control' and getattr(failure, 'root_control', None) is not None:
                raise
            _refuse('root_control')
        role, guard = site
        refuse(guard, role)
    finally:
        unknown = False
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                unknown = True
        if unknown:
            refuse('close_unknown', 'discovery_close')


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
        _refuse('service_process')
    descriptor = os.open(PROC / str(pid), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        initial = os.fstat(descriptor)
        if initial.st_uid != 0 or not stat.S_ISDIR(initial.st_mode):
            _refuse('service_process')

        def read(name: str, limit: int) -> bytes:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                info = os.fstat(fd)
                if info.st_uid != 0 or not stat.S_ISREG(info.st_mode):
                    _refuse('service_process')
                data = os.read(fd, limit + 1)
                if not 0 < len(data) <= limit:
                    _refuse('service_process')
                return data
            finally:
                _close_lifecycle_reader(fd)

        def identity() -> str:
            raw = read('stat', 16384)
            match = re.fullmatch(rb'([1-9][0-9]*) \((.*)\) ([^\n]+)\n?', raw)
            if match is None or int(match[1]) != pid:
                _refuse('service_process')
            fields = match[3].split()
            if (len(fields) < 20 or fields[0] not in {b'R', b'S', b'D', b'I'}
                    or not fields[19].isdigit()):
                _refuse('service_process')
            uid = [line.split()[1:] for line in read('status', 65536).splitlines() if line.startswith(b'Uid:')]
            if uid != [[b'0', b'0', b'0', b'0']]:
                _refuse('service_process')
            if read('cmdline', 16384) != b'\0'.join(
                    part.encode() for part in (RUNTIME, LAUNCHER, 'serve', channel)) + b'\0':
                _refuse('service_process')
            try:
                cwd = os.stat('cwd', dir_fd=descriptor)
                exe = os.stat('exe', dir_fd=descriptor)
                if (not stat.S_ISDIR(cwd.st_mode)
                        or (cwd.st_dev, cwd.st_ino, cwd.st_uid, cwd.st_gid, stat.S_IMODE(cwd.st_mode))
                        != tuple(application[key] for key in ('device', 'inode', 'uid', 'gid', 'mode'))
                        or os.readlink('cwd', dir_fd=descriptor) != application['path']
                        or (exe.st_dev, exe.st_ino) != runtime_version[:2]
                        or _runtime_version() != runtime_version):
                    _refuse('service_process')
            except Exception:
                # Never include a proc target, runtime path or caller value in
                # the emitted error. Missing/changed links are unknown, not idle.
                _refuse('service_process')
            tasks = os.open('task', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                if os.listdir(tasks) != [str(pid)]:
                    _refuse('service_process')
            finally:
                _close_lifecycle_reader(tasks)
            return fields[19].decode('ascii')

        start = identity()
        named = os.stat(PROC / str(pid), follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (initial.st_dev, initial.st_ino) or identity() != start:
            _refuse('service_process')
        return hashlib.sha256(f'{unit}:{pid}:{start}'.encode()).hexdigest()
    finally:
        _close_lifecycle_reader(descriptor)


class FixedBwsService:
    def __init__(self, *, unit: str, channel: str) -> None:
        if (channel not in {'dev', 'test'} or type(unit) is not str
                or unit != f'yggdrasil-bws-deploy@{channel}.service'):
            _refuse('setup')
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
        self.control_inventory_empty = False
        self.control_path_binding: _ControlPathBinding | None = None
        self.installation_footprint: tuple[dict[str, Any], ...] = ()
        self.installation_effect_parents: tuple[str, ...] = ()
        self.launcher_before: bytes | None = None
        self.launcher_after: bytes | None = None
        self.new_pid: int | None = None
        self.new_token: str | None = None
        self.runtime_fd: int | None = None
        self.runtime_context_started = self.runtime_close_completed = False
        self.lifecycle_close_uncertain = False

    def _held_runtime(self) -> None:
        try:
            if self.lifecycle_close_uncertain:
                _refuse('retained_runtime')
            if self.runtime_version is None:
                _refuse('retained_runtime')
            if self.runtime_fd is None:
                if self.runtime_close_completed and _runtime_version() == self.runtime_version:
                    return
                _refuse('retained_runtime')
            if (os.get_inheritable(self.runtime_fd)
                    or fcntl.fcntl(self.runtime_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
                    or _runtime_identity(os.fstat(self.runtime_fd)) != self.runtime_version
                    or _runtime_version() != self.runtime_version):
                _refuse('retained_runtime')
        except Exception:
            _refuse('retained_runtime')

    def _runtime_contract(self) -> tuple[dict[str, Any], tuple[int, ...]]:
        if self.application is None or self.runtime_version is None:
            _refuse('retained_runtime')
        return self.application, self.runtime_version

    def _launcher_bytes(self) -> bytes:
        if self.lifecycle_close_uncertain:
            _refuse('retained_runtime')
        try:
            return _public_launcher_bytes()
        except _LifecycleCloseUncertain:
            self.lifecycle_close_uncertain = True
            raise

    def _process_token(self, pid: int) -> str:
        if self.lifecycle_close_uncertain:
            _refuse('retained_runtime')
        application, runtime_version = self._runtime_contract()
        try:
            return _pid_token(self.unit, self.channel, pid, application, runtime_version)
        except _LifecycleCloseUncertain:
            self.lifecycle_close_uncertain = True
            raise

    @contextmanager
    def retained_runtime(self) -> Iterator[None]:
        """Own ONE read-only FD to the accepted alias target through body close.

        Following the already registered alias is intentional; no interpreter
        replacement, target-path fallback, executable read or execution occurs.
        The outer admitted window must already be held. This pins identity and
        rechecks metadata; it is NOT exclusion of independent runtime writers.
        """
        if self.phase != 'unqualified' or self.runtime_context_started:
            _refuse('retained_runtime')
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
                _refuse('retained_runtime')
            body_entered = True
            yield
        finally:
            unknown = False
            if self.control_path_binding is not None:
                try:
                    self.control_path_binding.close()
                except Exception:
                    unknown = True
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
                _refuse('retained_runtime')
            self.runtime_close_completed = fd is not None

    def _unit_property_refuse(self, site: str, kind: str) -> NoReturn:
        # Only initial qualification may export the added source-site detail.
        raise _OldQualificationRefusal(
            'unit_properties',
            unit_property=(site, kind) if self.phase == 'qualifying' else None,
        ) from None

    def _unit_read(self, argv: list[str], signature: str, site: str) -> Any:
        try:
            return _typed(argv, signature)
        except Exception as failure:
            if type(failure) is _OldQualificationRefusal:
                kind = getattr(failure, 'read_kind', None)
                if type(kind) is str and kind in {'backend', 'decode', 'signature', 'shape'}:
                    self._unit_property_refuse(site, kind)
            if site == 'Unit_DropInPaths':
                self._unit_property_refuse(site, 'unsupported')
            _refuse('unit_properties')

    def _call(self, method: str, signature: str) -> Any:
        # Only these two read-only Manager methods are constructed here.
        if method not in {'GetUnit', 'GetUnitProcesses'}:
            _refuse('unit_properties')
        site = 'Manager_' + method
        value = self._unit_read(['busctl', '--system', '--no-pager', '--json=short',
            '--auto-start=no', '--allow-interactive-authorization=no', '--timeout=30s',
            'call', BUS, MANAGER, BUS + '.Manager', method, 's', self.unit], signature, site)
        if type(value) is not list or len(value) != 1:
            self._unit_property_refuse(site, 'shape')
        return value[0]

    def _get(self, interface: str, name: str, signature: str) -> Any:
        site = interface + '_' + name
        if name == 'ExecStopPost' and self.phase == 'qualifying' and self.contract is not None:
            site = 'Service_ExecStopPost_final'
        if self.object is None:
            self._unit_property_refuse(site, 'shape')
        return self._unit_read(['busctl', '--system', '--no-pager', '--json=short',
            '--auto-start=no', '--allow-interactive-authorization=no', '--timeout=30s',
            'get-property', BUS, self.object, BUS + '.' + interface, name], signature, site)

    def _exec(self, name: str, action: str | None = None) -> list[Any]:
        rows = self._get('Service', name, EXEC_TYPE)
        if action is None:
            if rows != []:
                _refuse('launcher')
            return []
        if type(rows) is not list or len(rows) != 1:
            _refuse('cleanup_contract' if action == 'cleanup' else 'launcher')
        row = rows[0]
        if (type(row) is not list or len(row) != 10
                or row[:3] != [LAUNCHER, [LAUNCHER, action, self.channel], False]
                or type(row[2]) is not bool
                or any(type(value) is not int or value < 0 for value in row[3:])):
            _refuse('cleanup_contract' if action == 'cleanup' else 'launcher')
        return row

    def _config(self, *, restored: bool = False) -> tuple[Any, ...]:
        self._held_runtime()
        for interface, values in (
            ('Unit', {'Id': self.unit, 'LoadState': 'loaded'}),
            ('Service', {'Type': 'simple', 'User': 'root', 'Group': 'root',
                         'KillMode': 'control-group', 'Restart': 'on-failure'}),
        ):
            for key, expected in values.items():
                if self._get(interface, key, 's') != expected:
                    self._unit_property_refuse(interface + '_' + key, 'value')
        for name in ('OnFailure', 'OnSuccess', 'TriggeredBy'):
            if self._get('Unit', name, 'as') != []:
                self._unit_property_refuse('Unit_' + name, 'value')
        for name in ('ExecCondition', 'ExecStartPre', 'ExecStartPost', 'ExecStop', 'ExecReload'):
            self._exec(name)
        start = self._exec('ExecStart', 'serve')
        cleanup = self._exec('ExecStopPost', 'cleanup')
        environment = self._get('Service', 'Environment', 'as')
        files = self._get('Service', 'EnvironmentFiles', 'a(sb)')
        if (type(environment) is not list or len(environment) > 128
                or any(type(value) is not str or '\0' in value or len(value) > 16384 for value in environment)):
            self._unit_property_refuse('Service_Environment', 'shape')
        if (type(files) is not list or len(files) > 32
                or any(type(row) is not list or len(row) != 2 or type(row[0]) is not str
                       or '\0' in row[0] or len(row[0]) > 4096 or type(row[1]) is not bool for row in files)):
            self._unit_property_refuse('Service_EnvironmentFiles', 'shape')
        launcher = self._launcher_bytes()
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
        if restored:
            if self.phase not in {'stopped_checked', 'new_stopped_checked'}:
                _refuse('root_control')
            allowed = (self.launcher_before,)
        if launcher not in allowed:
            _refuse('launcher')
        # Qualify the proposed public launcher against the SAME current typed
        # unit configuration before backup/stop. Old-only hints must not allow
        # an installation whose final root-first launcher loses this topology.
        if self.launcher_after is None or self.control is None:
            _refuse('launcher')
        expected_empty_control_root = (
            self.control if self.control_inventory_empty else None
        )
        if (self.control_inventory_empty
                and any(value.startswith('PATH=') and CONTROL_DIRECTORY in value for value in environment)
                and not any(not value.startswith('PATH=') and CONTROL_DIRECTORY in value
                            for value in environment)):
            slots = _control_path_slots(environment)
            if files:
                _root_control_refuse('environment_files', mode='path_environment', role='path_hints')
            for side, raw in (('old', launcher), ('proposed', self.launcher_after)):
                if CONTROL_DIRECTORY.encode() in raw:
                    _root_control_refuse('launcher_hint', mode='path_environment', role='path_hints', side=side)
            # Only the fixed unit's ordinary host lookup view is supported.
            for name, signature, namespace_expected in (
                ('RootDirectory', 's', ''), ('RootImage', 's', ''),
                ('WorkingDirectory', 's', ''), ('BindPaths', 'a(ssbt)', []),
                ('BindReadOnlyPaths', 'a(ssbt)', []), ('TemporaryFileSystem', 'a(ss)', []),
                ('ReadOnlyPaths', 'as', []), ('ReadWritePaths', 'as', []),
                ('InaccessiblePaths', 'as', []), ('PassEnvironment', 'as', []),
                ('ExtensionDirectories', 'as', []), ('MountImages', 'a(ssba(ss))', []),
                ('ExtensionImages', 'a(sba(ss))', []), ('PAMName', 's', ''),
                ('UnsetEnvironment', 'as', []), ('ExecSearchPath', 'as', []),
                ('PrivateMounts', 'b', False), ('PrivateTmp', 'b', False),
                ('PrivateDevices', 'b', False), ('PrivateUsers', 'b', False),
                ('DynamicUser', 'b', False), ('ProtectHome', 's', 'no'),
                ('ProtectSystem', 's', 'no'),
            ):
                namespace_value = self._get('Service', name, signature)
                if type(namespace_value) is not type(namespace_expected) or namespace_value != namespace_expected:
                    self._unit_property_refuse('Service_' + name, 'value')
            # The original read must retain its own refusal classification.
            dropin_paths = self._get('Unit', 'DropInPaths', 'as')
            try:
                selected_dropins = _preserved_dropin_path(dropin_paths, self.channel)
            except _OldQualificationRefusal as failure:
                refinement = getattr(failure, 'unit_property', None)
                selector_category = (
                    refinement[1]
                    if type(failure) is _OldQualificationRefusal
                    and type(failure.subgate) is str
                    and failure.subgate == 'unit_properties'
                    and type(refinement) is tuple and len(refinement) == 2
                    and all(type(value) is str for value in refinement)
                    and refinement[0] == 'Unit_DropInPaths'
                    and refinement[1] in _DROPIN_SELECTOR_CATEGORIES else None
                )
                kind = ('unsupported' if type(failure) is not _OldQualificationRefusal else
                        'shape' if failure.read_kind == 'shape' else
                        selector_category if selector_category is not None else 'selection')
                self._unit_property_refuse('Unit_DropInPaths', kind)
            if self._get('Unit', 'JoinsNamespaceOf', 'as') != []:
                self._unit_property_refuse('Unit_JoinsNamespaceOf', 'value')
            loaded_projection: tuple[Any, ...] = ()
            if selected_dropins:
                # Finite effective semantics, not historical unit-byte identity.
                # NeedDaemonReload is only a supplementary pending-change guard.
                loaded = []
                for interface, name, signature, profile_expected in (
                    ('Unit', 'NeedDaemonReload', 'b', False),
                    ('Service', 'StandardOutput', 's', 'null'),
                    ('Service', 'StandardError', 's', 'null'),
                    ('Service', 'UMask', 'u', 0o077),
                    ('Service', 'LoadCredentialEncrypted', 'a(ss)',
                     [['bws-machine-account-token', f'/var/lib/yggdrasil/bws-tokens/{self.channel}/current']]),
                    ('Service', 'LoadCredential', 'a(ss)', []),
                ):
                    value = self._get(interface, name, signature)
                    if type(value) is not type(profile_expected) or value != profile_expected:
                        _refuse('unit_properties')
                    loaded.append(tuple(tuple(row) for row in value) if type(value) is list else value)
                loaded_projection = tuple(loaded)
            mode = 'path_selected' if selected_dropins else 'path_absent'
            try:
                if len(self.installation_footprint) != 3:
                    _root_control_refuse('population', mode=mode, role='config_footprint')
                if self.installation_footprint[0] != self.application:
                    _root_control_refuse('application', mode=mode, role='config_footprint')
                if self.installation_footprint[1]['path'] != str(Path(LAUNCHER).parent):
                    _root_control_refuse('launcher_parent', mode=mode, role='config_footprint')
            except _OldQualificationRefusal:
                raise
            except Exception:
                _root_control_refuse('construction_unknown', mode=mode, role='config_footprint')
            if self.control_path_binding is None:
                try:
                    self.control_path_binding = _ControlPathBinding(
                        self.control, slots, self.installation_footprint, self.installation_effect_parents,
                        selected_dropins,
                    )
                except Exception:
                    _root_control_refuse('construction_unknown', mode=mode, role='binding')
            else:
                if self.control_path_binding.slots != slots:
                    _root_control_refuse('slots_changed', mode=mode, role='binding')
                if self.control_path_binding.selected_dropins != selected_dropins:
                    _root_control_refuse('selection_changed', mode=mode, role='binding')
            projection = self.control_path_binding.revalidate()
            if selected_dropins:
                if self.control_path_binding.path_assignment != next(value for value in environment if value.startswith('PATH=')):
                    _root_control_refuse('loaded_assignment', mode=mode, role='binding')
                projection += (loaded_projection,)
            # Keep exact typed bytes and ordering private, bound into generations.
            return start[:3], cleanup[:3], tuple(environment), tuple(tuple(row) for row in files), projection
        if self.control_path_binding is not None:
            _root_control_refuse('branch_changed', mode='path_environment', role='binding')
        for side, raw in (('old', launcher), ('proposed', self.launcher_after)):
            if _discovered_control_projection(
                raw, environment, files,
                expected_empty_control_root=expected_empty_control_root, side=side,
            ) != self.control:
                _root_control_refuse(
                    'identity', role='comparison', side=side,
                    mode='captured_empty' if self.control_inventory_empty else 'anchored_discovery',
                )
        hints = hashlib.sha256(json.dumps([environment, files], separators=(',', ':')).encode()).hexdigest()
        return start[:3], cleanup[:3], hints

    def _state(self, active: bool) -> int:
        expected = ('active', 'running') if active else ('inactive', 'dead')
        if (self._get('Unit', 'ActiveState', 's'), self._get('Unit', 'SubState', 's')) != expected:
            _refuse('service_process')
        job = self._get('Unit', 'Job', '(uo)')
        if (type(job) is not list or len(job) != 2 or type(job[0]) is not int
                or job[0] != 0 or job[1] != '/'):
            _refuse('service_process')
        control = self._get('Service', 'ControlPID', 'u')
        pid = self._get('Service', 'MainPID', 'u')
        if type(control) is not int or control != 0 or type(pid) is not int:
            _refuse('service_process')
        if (active and not 0 < pid < 2**31) or (not active and pid != 0):
            _refuse('service_process')
        return pid

    def _single_process(self, pid: int) -> None:
        rows = self._call('GetUnitProcesses', 'a(sus)')
        if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not list
                or len(rows[0]) != 3 or type(rows[0][1]) is not int or rows[0][1] != pid):
            _refuse('service_process')
        # Raw cgroup/name data are neither returned nor printed.

    def qualify_old(
        self, expected_service_identity: str | None = None, *, application_root: dict[str, Any],
        control_root: dict[str, Any], launcher_content: dict[str, Any],
        control_inventory_empty: bool = False,
        installation_footprint: tuple[dict[str, Any], ...] = (),
        installation_effect_parents: tuple[str, ...] = (),
    ) -> None:
        if (self.phase != 'unqualified' or (expected_service_identity is not None
                and (type(expected_service_identity) is not str
                     or re.fullmatch('[0-9a-f]{64}', expected_service_identity) is None))
                or type(control_inventory_empty) is not bool):
            _refuse('setup')
        self._held_runtime()
        self.phase = 'qualifying'
        mode = 'captured_empty' if control_inventory_empty else 'anchored_discovery'
        application = _application_projection(application_root, role='application', mode=mode)
        control = _application_projection(control_root, role='control', mode=mode)
        self.application = application
        self.control = control
        self.control_inventory_empty = control_inventory_empty
        self.installation_footprint = installation_footprint
        self.installation_effect_parents = installation_effect_parents
        if control['path'] == application['path']:
            _root_control_refuse('separation', mode=mode, role='roots')
        if not (control['path'] == CONTROL_DIRECTORY
                or control['path'].startswith(CONTROL_DIRECTORY + '/')):
            _root_control_refuse('fixed_subtree', mode=mode, role='roots')
        if control_inventory_empty and control['path'] != CONTROL_DIRECTORY:
            _root_control_refuse('empty_fixed_root', mode=mode, role='roots')
        try:
            if (type(launcher_content) is not dict or set(launcher_content) != {'sha256', 'base64'}
                    or type(launcher_content['base64']) is not str):
                _refuse('launcher')
            proposed_launcher = base64.b64decode(launcher_content['base64'], validate=True)
            if (not 0 < len(proposed_launcher) <= 65536
                    or hashlib.sha256(proposed_launcher).hexdigest() != launcher_content['sha256']):
                _refuse('launcher')
            self.launcher_after = proposed_launcher
        except Exception:
            _refuse('launcher')
        self.launcher_before = self._launcher_bytes()
        self.object = self._call('GetUnit', 'o')
        if (type(self.object) is not str
                or re.fullmatch(r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]+', self.object) is None):
            self._unit_property_refuse('Manager_GetUnit', 'shape')
        self.contract = self._config()
        old_pid = self._state(True)
        runtime_version = self.runtime_version
        if runtime_version is None:
            _refuse('retained_runtime')
        self.old_pid = old_pid
        self._single_process(old_pid)
        old_token = self._process_token(old_pid)
        self.old_token = old_token
        if expected_service_identity is not None and old_token != expected_service_identity:
            _refuse('service_process')
        self.cleanup = self._exec('ExecStopPost', 'cleanup')
        self.phase = 'qualified'

    def revalidate_empty_control_configuration(self) -> None:
        """Recheck the captured first-install control root at the backup boundary."""
        if self.phase != 'qualified':
            _root_control_refuse('phase', role='revalidation')
        if not self.control_inventory_empty:
            _root_control_refuse('empty_required', mode='anchored_discovery', role='revalidation')
        if self.contract is None:
            _root_control_refuse('contract_missing', mode='captured_empty', role='revalidation')
        if self._config() != self.contract:
            _root_control_refuse('configuration', mode='captured_empty', role='revalidation')

    def revalidate_restored_control_configuration(self) -> None:
        """Check authenticated restoration without granting legacy OLD restart."""
        if self.control_path_binding is None or self._config(restored=True) != self.contract:
            _refuse('root_control')

    def stop_old(self) -> None:
        if (self.phase != 'qualified' or self.launcher_after is None
                or self._launcher_bytes() != self.launcher_after):
            _refuse()
        if self._config() != self.contract or self._state(True) != self.old_pid:
            _refuse()
        self._single_process(self.old_pid)
        if self._process_token(self.old_pid) != self.old_token:
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
                or self._launcher_bytes() != launcher_content):
            _refuse()
        self._single_process(self.old_pid)
        if self._process_token(self.old_pid) != self.old_token:
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
        if self._launcher_bytes() != self.launcher_after:
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
        token = self._process_token(pid)
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
        if self._process_token(self.new_pid) != self.new_token:
            _refuse()

    def stop_new(self) -> None:
        """Stop only the exact candidate process already authenticated by this lifecycle."""
        if (self.phase != 'new_kernel_checked' or self.new_pid is None or self.new_token is None
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        if self._process_token(self.new_pid) != self.new_token:
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
                or self._launcher_bytes() != self.launcher_before
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        if self._process_token(self.new_pid) != self.new_token:
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
        token = self._process_token(pid)
        if token == self.old_token:
            _refuse()
        self.new_pid, self.new_token = pid, token
        self.phase = 'new_kernel_checked'
        self.stop_new()

    def start_restored_old(self) -> None:
        """Start the exact old source only after the caller proved same-handle restore."""
        self.require_stopped()
        if self._launcher_bytes() != self.launcher_before:
            _refuse()
        self.phase = 'restore_start_requested'
        _run(['systemctl', '--system', '--no-pager', '--no-ask-password',
              '--job-mode=ignore-dependencies', 'start', self.unit])

    def require_restored_old_kernel(self) -> str:
        if self.phase != 'restore_start_requested' or self._config() != self.contract:
            _refuse()
        if self._launcher_bytes() != self.launcher_before:
            _refuse()
        pid = self._state(True)
        self._single_process(pid)
        token = self._process_token(pid)
        if token == self.old_token:
            _refuse()
        self.new_pid, self.new_token = pid, token
        self.phase = 'old_kernel_restored'
        return token

    def require_same_restored_old_kernel(self) -> None:
        if (self.phase != 'old_kernel_restored' or self.new_pid is None
                or self._launcher_bytes() != self.launcher_before
                or self._config() != self.contract or self._state(True) != self.new_pid):
            _refuse()
        self._single_process(self.new_pid)
        if self._process_token(self.new_pid) != self.new_token:
            _refuse()
