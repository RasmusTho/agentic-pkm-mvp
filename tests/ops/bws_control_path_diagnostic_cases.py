"""Independent synthetic port faults for the retained-PATH source inventory.

These cases change public fixture inputs or external OS metadata/transport only.
No qualification, snapshot, inventory, manifest, transaction or receipt reader is
replaced. Expectations are authored here, independently of production allowlists.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import stat
import struct
from types import SimpleNamespace

from app.ops.bws_installation_lifecycle import _control_path_mount as REAL_MOUNT


# (case, mode, side, role, guard). No native values or observed metadata supply
# any expected token. Defensive producer shapes are covered separately below.
PATH_CASES = [
    ('population', 'path_environment', 'unknown', 'loaded_slots', 'path_population'),
    ('hints', 'path_environment', 'unknown', 'loaded_slots', 'hint_bound'),
    *[(name, 'path_environment', 'unknown', 'loaded_slots', guard) for name, guard in (
        ('absolute', 'path_absolute'), ('backslash', 'path_backslash'),
        ('canonical', 'path_canonical'), ('components', 'component_bound'),
        ('misleading', 'misleading_hint'), ('duplicate', 'duplicate_components'))],
    ('environment-files', 'path_environment', 'unknown', 'path_hints', 'environment_files'),
    ('old-hint', 'path_environment', 'old', 'path_hints', 'launcher_hint'),
    ('proposed-hint', 'path_environment', 'proposed', 'path_hints', 'launcher_hint'),
    ('recorded-root', 'path_selected', 'unknown', 'roots', 'recorded_identity'),
    ('parent-alias', 'path_selected', 'unknown', 'selected_parent', 'identity_alias'),
    ('file-alias', 'path_selected', 'unknown', 'selected_file', 'identity_alias'),
    ('grammar', 'path_selected', 'unknown', 'selected_content', 'grammar'),
    ('assignment', 'path_selected', 'unknown', 'selected_content', 'assignment_disagreement'),
    ('loaded', 'path_selected', 'unknown', 'binding', 'loaded_assignment'),
    ('size-total', 'path_selected', 'unknown', 'selected_file', 'aggregate_size'),
    *[(name, 'path_selected', 'unknown', 'selected_input', guard) for name, guard in (
        ('file-type', 'file_type'), ('file-link', 'file_link'), ('file-owner', 'file_owner'),
        ('file-mode', 'file_mode'), ('file-zero', 'file_size_positive'), ('file-large', 'file_size_bound'),
        ('file-inherit', 'file_inheritable'), ('file-access', 'file_access'),
        ('file-fstat', 'file_fstat_unknown'), ('file-inherit-query', 'file_inheritable_unknown'),
        ('file-access-query', 'file_access_unknown'))],
    *[(name, 'path_selected', 'unknown', 'control_root', guard) for name, guard in (
        ('dir-type', 'directory_type'), ('dir-mode', 'directory_mode'), ('dir-owner', 'directory_owner'),
        ('dir-inherit', 'directory_inheritable'), ('dir-fstat', 'directory_fstat_unknown'),
        ('dir-inherit-query', 'directory_inheritable_unknown'))],
    ('mount-platform', 'path_selected', 'unknown', 'ancestor', 'mount_platform'),
    *[(name, 'path_selected', 'unknown', 'control_root', guard) for name, guard in (
        ('mount-libc', 'mount_libc_unknown'),
        ('mount-buffer', 'mount_buffer_unknown'), ('mount-call', 'mount_statx_unknown'),
        ('mount-result', 'mount_statx'), ('mount-unpack', 'mount_unpack_unknown'),
        ('mount-mask', 'mount_mask'), ('mount-zero', 'mount_identity'))],
    ('dir-open', 'path_selected', 'unknown', 'control_root', 'open_unknown'),
    ('file-open', 'path_selected', 'unknown', 'selected_file', 'open_unknown'),
    ('file-mount', 'path_selected', 'unknown', 'selected_file', 'mount_crossing'),
    ('parent-mount', 'path_selected', 'unknown', 'selected_parent', 'mount_crossing'),
    ('pread', 'path_selected', 'unknown', 'selected_content', 'pread_unknown'),
    ('length', 'path_selected', 'unknown', 'selected_content', 'returned_length'),
    ('read-version', 'path_selected', 'unknown', 'selected_content', 'post_read_version'),
    *[(name, 'path_selected', 'unknown', 'parsed_slots', guard) for name, guard in (
        ('parsed-absolute', 'path_absolute'), ('parsed-canonical', 'path_canonical'),
        ('parsed-duplicate', 'duplicate_components'), ('parsed-absent', 'slot_absent'),
        ('parsed-hints', 'hint_bound'), ('parsed-components', 'component_bound'),
        ('parsed-misleading', 'misleading_hint'))],
    *[(f'loader-{role}-{kind}', 'path_selected', 'unknown', 'loader_' + role,
       'stat_unknown' if kind == 'unknown' else 'present')
      for role in ('app', 'scripts') for kind in ('unknown', 'present')],
    ('descent-stat', 'path_selected', 'unknown', 'slot_descent', 'stat_unknown'),
    ('descent-type', 'path_selected', 'unknown', 'slot_descent', 'not_directory'),
    *[(name, 'path_selected', 'unknown', 'slot_census', guard) for name, guard in (
        ('census-before', 'before_fstat_unknown'), ('census-open', 'scandir_open_unknown'),
        ('census-iteration', 'scandir_iteration_unknown'), ('census-exit', 'scandir_exit_unknown'),
        ('entry-stat', 'entry_stat_unknown'), ('entry-bound', 'entry_bound'),
        ('entry-owner', 'entry_owner'), ('entry-mode', 'entry_mode'), ('entry-type', 'entry_type'),
        ('entry-exec', 'entry_executable'), ('entry-link', 'entry_link'),
        ('census-after', 'after_fstat_unknown'), ('census-drift', 'directory_time_drift'))],
    ('absent-stat', 'path_selected', 'unknown', 'absent_edge', 'stat_unknown'),
    ('absent-appeared', 'path_selected', 'unknown', 'absent_edge', 'appeared'),
    ('edge-stat', 'path_selected', 'unknown', 'current_edge', 'stat_unknown'),
    ('edge-held', 'path_selected', 'unknown', 'current_edge', 'held_version'),
    ('edge-binding', 'path_selected', 'unknown', 'current_edge', 'edge_identity'),
    ('fresh-open', 'path_selected', 'unknown', 'fresh_edge', 'open_unknown'),
    ('fresh-version', 'path_selected', 'unknown', 'fresh_edge', 'version'),
]


PATH_TOPOLOGY_CASES = [
    ('roots-equal', 'path_selected', 'unknown', 'roots', 'equal'),
    ('roots-below', 'path_selected', 'unknown', 'roots', 'below'),
    ('roots-above', 'path_selected', 'unknown', 'roots', 'above'),
    ('parent-equal', 'path_selected', 'unknown', 'selected_parent', 'equal'),
    ('parent-below', 'path_selected', 'unknown', 'selected_parent', 'below'),
    ('parent-above', 'path_selected', 'unknown', 'selected_parent', 'above'),
]


def expected_context(name):
    return next(row[1:] for row in PATH_CASES + PATH_TOPOLOGY_CASES if row[0] == name)


def prepare_path_case(module, patch, state, properties, control, selected, case):
    """Install one external-port fault; return independent ownership/call evidence."""
    uncertain = case.endswith('-close')
    multiple = case == 'grammar-multiple-close'
    name = case.removesuffix('-close').removesuffix('-multiple')
    selected = tuple(Path(p) for p in selected)
    target = selected[-1] if selected else control / 'unselected-placeholder'
    environment = properties['Service', 'Environment']
    assignment = next(value for value in environment if value.startswith('PATH='))
    slot = Path(assignment[5:].split(':')[1])
    evidence = dict(fired=False, trace=[], opened={}, closed=[], reads=[], target=target,
                    original_environment=tuple(environment), open_arguments=[], stat_arguments=[])
    if name in {row[0] for row in PATH_TOPOLOGY_CASES}:
        evidence['fired'] = True
    if name in {'population', 'hints', 'absolute', 'backslash', 'canonical', 'components',
                'misleading', 'duplicate'}:
        extra = dict(absolute='relative', backslash='/bad\\component', canonical='/bad/../component',
                     components='/' + '/'.join(['x'] * 33), misleading=str(control) + '-misleading',
                     duplicate='/usr/bin').get(name)
        if name == 'population':
            environment.append('PATH=/PRIVATE_CANARY')
        elif name == 'hints':
            environment[1] = 'PATH=' + ':'.join([str(slot)] + [f'/h{i}' for i in range(16)])
        else:
            environment[1] += ':' + extra
        evidence['fired'] = True
    elif name == 'environment-files':
        properties['Service', 'EnvironmentFiles'] = [['/PRIVATE_CANARY', False]]
        evidence['fired'] = True
    elif name == 'old-hint':
        launcher = Path(module.LAUNCHER)
        launcher.write_bytes(launcher.read_bytes() + str(control).encode())
        evidence['fired'] = True
    elif name == 'proposed-hint':
        # RPC creates this exact public Git launcher before its commit. Direct
        # callers supply the same supported payload via their fixture argument.
        evidence['fired'] = True
    elif name == 'grammar':
        target.write_bytes(target.read_bytes() + b'ExecStart=/PRIVATE_CANARY\n')
        evidence['fired'] = True
    elif name in {'assignment', 'loaded'}:
        for path in (selected if name == 'loaded' else (target,)):
            path.write_bytes(path.read_bytes().replace(b'/usr/bin', b'/opt/bin'))
        evidence['fired'] = True
    elif name == 'size-total':
        for path in selected:
            path.write_bytes(b'x' * 1025)
        evidence['fired'] = True
    elif name.startswith('parsed-'):
        tail = {'parsed-absolute': ':relative', 'parsed-canonical': ':/bad/../component',
                'parsed-duplicate': ':/usr/bin', 'parsed-absent': '',
                'parsed-hints': ':' + ':'.join(f'/x{i}' for i in range(16)),
                'parsed-components': ':/' + '/'.join(['x'] * 33),
                'parsed-misleading': ':' + str(control) + '-misleading'}[name]
        parsed = 'PATH=/usr/bin' if name == 'parsed-absent' else assignment + tail
        target.write_bytes(('[Service]\nEnvironment=' + parsed + '\n').encode())
        evidence['fired'] = True
    elif name == 'entry-bound':
        evidence['fired'] = True
        for i in range(129):
            (slot / f'entry-{i}').touch(mode=0o644)
    elif name.startswith('entry-'):
        (slot / 'PRIVATE_CANARY').touch(mode=0o644)
    if name.startswith('absent-'):
        properties['Service', 'Environment'][1] = f'PATH=/usr/bin:{control}/absent/deeper:/bin'
        for path in selected:
            path.write_bytes(('[Service]\nEnvironment=' + properties['Service', 'Environment'][1] + '\n').encode())

    original_os, original_fcntl = module.os, module.fcntl
    owned, counts = {}, {}
    def fail():
        evidence['fired'] = True
        raise OSError('PRIVATE_CANARY exception /secret/path errno=777')
    def change(info, **fields):
        evidence['fired'] = True
        return SimpleNamespace(**{**{k: getattr(info, k) for k in dir(info) if k.startswith('st_')}, **fields})
    def called(operation, path):
        key = operation, str(path)
        counts[key] = counts.get(key, 0) + 1
        evidence['trace'].append(key)
        return counts[key]
    def resolved(path, kwargs):
        if 'dir_fd' in kwargs:
            return owned[kwargs['dir_fd']] / str(path)
        return Path(path)
    def open_fd(path, flags, *args, **kwargs):
        full = resolved(path, kwargs)
        occurrence = called('open', full)
        evidence['open_arguments'].append((str(full), flags, tuple(sorted(kwargs))))
        if (name == 'dir-open' and full == control or name == 'file-open' and full == target
                or name == 'fresh-open' and full == Path('/') and occurrence == 2):
            fail()
        fd = original_os.open(path, flags, *args, **kwargs)
        assert fd not in owned
        owned[fd] = full
        evidence['opened'].setdefault(str(full), []).append(fd)
        return fd
    def close_fd(fd):
        path = owned.pop(fd, None)
        called('close', path)
        if path is not None:
            evidence['closed'].append((str(path), fd))
        original_os.close(fd)
        close_target = control if name == 'dir-fstat' else Path('/') if name == 'fresh-version' else target
        if uncertain and (path == close_target or multiple and path in selected):
            evidence.setdefault('failed_closes', []).append((str(path), fd))
            raise OSError('PRIVATE_CANARY uncertain original close')
    def fstat(fd):
        info = original_os.fstat(fd)
        path = owned.get(fd)
        occurrence = called('fstat', path)
        # Metadata changes happen only at the original lifecycle reads, never
        # at the real transaction/manifest/snapshot readers.
        if path == target and occurrence == 1:
            fields = {
                'file-type': dict(st_mode=stat.S_IFDIR | 0o755), 'file-link': dict(st_nlink=2),
                'file-owner': dict(st_uid=777), 'file-mode': dict(st_mode=stat.S_IFREG | 0o644 | 0o100),
                'file-zero': dict(st_size=0), 'file-large': dict(st_size=4097),
            }.get(name)
            if fields:
                return change(info, **fields)
            if name == 'file-fstat':
                fail()
        if path == control and occurrence == 1:
            fields = {
                'dir-type': dict(st_mode=stat.S_IFREG | 0o644), 'dir-mode': dict(st_mode=stat.S_IFDIR | 0o777),
                'dir-owner': dict(st_uid=777),
            }.get(name)
            if fields:
                return change(info, **fields)
            if name == 'dir-fstat':
                fail()
        if path == control and name == 'recorded-root' and occurrence == 1:
            return change(info, st_mode=stat.S_IFDIR | 0o750)
        if path == target.parent and name == 'parent-alias':
            root = original_os.stat(control)
            return change(info, st_ino=root.st_ino, st_dev=root.st_dev)
        if path == target and name == 'file-alias':
            first = original_os.stat(selected[0])
            return change(info, st_ino=first.st_ino, st_dev=first.st_dev)
        if path == target and occurrence == 2 and name == 'read-version':
            return change(info, st_mtime_ns=info.st_mtime_ns + 1)
        if path == slot:
            # initial directory identity, census before, census after
            if name == 'census-before' and occurrence == 2 or name == 'census-after' and occurrence == 3:
                fail()
            if name == 'census-drift' and occurrence == 3:
                return change(info, st_ctime_ns=info.st_ctime_ns + 1)
        if path == Path('/') and name == 'edge-held' and occurrence == 2:
            return change(info, st_ino=info.st_ino + 1)
        if path == Path('/') and name == 'fresh-version' and counts.get(('open', '/')) == 2:
            return change(info, st_mode=stat.S_IFDIR | 0o750)
        return info
    def inheritable(fd):
        path = owned.get(fd)
        called('inheritable', path)
        if path == target and name in {'file-inherit', 'file-inherit-query'}:
            if name.endswith('query'):
                fail()
            evidence['fired'] = True
            return True
        if path == control and name in {'dir-inherit', 'dir-inherit-query'}:
            if name.endswith('query'):
                fail()
            evidence['fired'] = True
            return True
        return original_os.get_inheritable(fd)
    def access(fd, command):
        called('fcntl', owned.get(fd))
        if owned.get(fd) == target and name in {'file-access', 'file-access-query'}:
            if name.endswith('query'):
                fail()
            evidence['fired'] = True
            return module.os.O_WRONLY
        return original_fcntl.fcntl(fd, command)
    def pread(fd, size, offset):
        data = original_os.pread(fd, size, offset)
        path = owned.get(fd)
        called('pread', path)
        evidence['reads'].append((str(path), size, len(data)))
        if path == target and name == 'pread':
            fail()
        if path == target and name == 'length':
            evidence['fired'] = True
            return data[:-1]
        return data
    def stat_entry(path, *args, **kwargs):
        full = resolved(path, kwargs)
        occurrence = called('stat', full)
        evidence['stat_arguments'].append((str(full), tuple(sorted(
            (key, True if key == 'dir_fd' else value) for key, value in kwargs.items()))))
        if full in {control / 'app', control / 'scripts'}:
            role = full.name
            if name == f'loader-{role}-unknown':
                fail()
            if name == f'loader-{role}-present':
                evidence['fired'] = True
                return original_os.stat(control)
        if full == control / 'lookup':
            if name == 'descent-stat' and occurrence == 1:
                fail()
            if name == 'descent-type' and occurrence == 1:
                return change(original_os.stat(control), st_mode=stat.S_IFREG | 0o644)
        if full == control / 'absent' and occurrence == 2:
            if name == 'absent-stat':
                fail()
            if name == 'absent-appeared':
                evidence['fired'] = True
                return original_os.stat(control)
        if full == Path('/'):
            if name == 'edge-stat':
                fail()
            if name == 'edge-binding':
                return change(original_os.stat(path, *args, **kwargs), st_ino=9999999)
        return original_os.stat(path, *args, **kwargs)
    class Census:
        def __init__(self, fd):
            self.iterator = original_os.scandir(fd)
            self.path = owned.get(fd)
        def __enter__(self):
            called('scandir_enter', self.path)
            return self
        def __exit__(self, *_args):
            called('scandir_exit', self.path)
            self.iterator.close()
            if name == 'census-exit':
                fail()
        def __iter__(self):
            return self
        def __next__(self):
            called('scandir_next', self.path)
            if name == 'census-iteration':
                fail()
            entry = next(self.iterator)
            def entry_stat(**kwargs):
                assert kwargs == {'follow_symlinks': False}
                if name == 'entry-stat':
                    fail()
                info = entry.stat(**kwargs)
                fields = {
                    'entry-owner': dict(st_uid=777), 'entry-mode': dict(st_mode=stat.S_IFREG | 0o666),
                    'entry-type': dict(st_mode=stat.S_IFLNK | 0o755),
                    'entry-exec': dict(st_mode=stat.S_IFREG | 0o744), 'entry-link': dict(st_nlink=2),
                }.get(name)
                return change(info, **fields) if fields else info
            return SimpleNamespace(name=entry.name, stat=entry_stat)
    def scandir(fd):
        called('scandir', owned.get(fd))
        if name == 'census-open':
            fail()
        return Census(fd)
    patch.setattr(module, 'os', SimpleNamespace(**{**vars(original_os), 'open': open_fd, 'close': close_fd,
        'fstat': fstat, 'get_inheritable': inheritable, 'pread': pread, 'stat': stat_entry, 'scandir': scandir}))
    patch.setattr(module, 'fcntl', SimpleNamespace(**{**vars(original_fcntl), 'fcntl': access}))
    # Model the Linux statx syscall itself, retaining the real mount reader.
    patch.setattr(module, '_control_path_mount', REAL_MOUNT)
    patch.setattr(module, 'sys', SimpleNamespace(**{**vars(module.sys), 'platform': 'linux'}))
    if name == 'mount-platform':
        evidence['fired'] = True
        patch.setattr(module.sys, 'platform', 'unsupported')
    real_buffer, real_unpack = ctypes.create_string_buffer, struct.unpack_from
    class Libc:
        def statx(self, fd, path, flags, mask, result):
            assert (path, flags, mask) == (b'', 0x1900, 0x1000)
            target_path = owned.get(fd)
            called('statx', target_path)
            if target_path == control and name == 'mount-call':
                fail()
            if target_path == control and name == 'mount-result':
                evidence['fired'] = True
                return -1
            mount = 1
            if name == 'file-mount' and target_path == target or name == 'parent-mount' and target_path == target.parent:
                evidence['fired'] = True
                mount = 2
            if target_path == control and name == 'mount-zero':
                evidence['fired'] = True
                mount = 0
            mask = 0 if target_path == control and name == 'mount-mask' else 0x1000
            if not mask:
                evidence['fired'] = True
            result.raw = struct.pack('=I', mask) + b'\0' * 140 + struct.pack('=Q', mount) + b'\0' * 104
            return 0
    def libc(*_args, **_kwargs):
        if name == 'mount-libc' and control in owned.values():
            fail()
        return Libc()
    def buffer(*args):
        if name == 'mount-buffer' and control in owned.values():
            fail()
        return real_buffer(*args)
    def unpack(*args):
        if name == 'mount-unpack' and control in owned.values():
            fail()
        return real_unpack(*args)
    patch.setattr(ctypes, 'CDLL', libc)
    patch.setattr(ctypes, 'create_string_buffer', buffer)
    patch.setattr(struct, 'unpack_from', unpack)
    evidence['owned'] = owned
    return evidence
