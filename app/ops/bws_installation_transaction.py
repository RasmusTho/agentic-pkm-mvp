"""One owner-bound DEV/TEST BWS source-installation transaction.

The profile function is an internal callback on the existing BWS socket. It is
not a standalone observer: the supervisor accepts it only while the exact
exclusive installation owner is live. Transaction execution remains limited to
the existing BWS launcher, channel lock, public-file handle, and fixed unit.
"""
from __future__ import annotations

import hashlib
import json
import io
import os
import ast
import base64
import copy
import errno
import importlib.util
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, NoReturn, cast
from uuid import UUID

_LEGACY_PROFILE_SCHEMA = "agentic-pkm.bws-loaded-source-profile.v2"
_PROFILE_SCHEMA = "agentic-pkm.bws-loaded-source-profile.v3"
_OLD_DISK_STATE_SCHEMA = "agentic-pkm.bws-old-disk-state.v1"
_SOURCE_LOADING_POLICY = "source-only-no-bytecode-v2"
_SOURCE_PYCACHE_PREFIX = "/dev/null"
_SOURCE_PROVENANCE_POLICY = "bws-source-bytes-v2"
_SOURCE_HASH_ATTRIBUTE = "__yggdrasil_source_sha256__"
_MAX_MODULES = 190
_MAX_MANIFEST_CHANGES = _MAX_MODULES + 2
_MAX_SOURCE_FILES = 4096
_MAX_SOURCE_ENTRIES = 32768
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_PROFILE_BYTES = 900_000
_EXTERNAL_SOURCE_ROOTS = ("llm_contract", "mimer_runtime", "companion_ui", "ops")
_PROFILE_READINESS_TIMEOUT_SECONDS = 30.0
_PROFILE_READINESS_POLL_SECONDS = 0.1
_OWNER_UID = 0
_OWNER_GID = 0
_CONTROL_DIRECTORY = Path("/opt/yggdrasil/bws-control")
_LAUNCHER = Path("/usr/local/libexec/yggdrasil-bws-deploy")
_CONTRACT = Path("config/secrets/host_secret_contract.json")
_CANDIDATE_CLEAN_PATHS = ("app", "scripts", _CONTRACT.as_posix())
_BACKUP_DIRECTORY = Path("/var/lib/yggdrasil/bws-deploy-convergence")
_STARTUP_RELEASE_CALLABLE = "<fixed-bws-startup-release>"
_PREBACKUP_REFUSAL_GATES = frozenset({
    "channel_lock_entry",
    "channel_owner_check",
    "caller_census",
    "current_writer_snapshot",
    "authority_cutover",
    "candidate_verification",
    "old_disk_state",
    "owner_launcher_profile",
    "backup_roots",
    "source_manifest",
    "candidate_profile",
    "old_kernel_qualification",
    "qualified_writer_snapshot",
    "generation_qualification",
})
_LOCAL_SOURCE_REFERENCE = re.compile(
    rb"(?<![A-Za-z0-9_])c?(?:app|scripts|llm_contract|mimer_runtime|companion_ui)"
    rb"(?:(?:\.[A-Za-z_][A-Za-z_0-9]*)|(?:/[A-Za-z_][A-Za-z_0-9]*))*(?![A-Za-z0-9_])",
)
_OPAQUE_CODE_LOADER_TARGETS = {
    "_pickle.load", "_pickle.loads", "_pickle.Unpickler",
    "cloudpickle.load", "cloudpickle.loads", "cloudpickle.CloudPickler",
    "dill.load", "dill.loads", "dill.dill.load", "dill.dill.loads",
    "joblib.load", "jsonpickle.decode",
    "marshal.load", "marshal.loads",
    "numpy.load", "numpy.lib.npyio.load",
    "pandas.read_pickle",
    "pickle.load", "pickle.loads", "pickle.Unpickler",
    "runpy.run_module", "runpy.run_path",
    "shelve.open",
    "torch.load", "torch.jit.load",
    "yaml.full_load", "yaml.load", "yaml.unsafe_load",
}
_OPAQUE_CODE_LOADER_MODULE_ROOTS = {
    "_pickle", "cloudpickle", "dill", "joblib", "jsonpickle", "marshal",
    "multiprocessing.reduction", "pickle", "shelve",
}
_OPAQUE_CODE_LOADER_LEAVES = {
    "compile", "eval", "exec", "exec_module", "load_module",
    "run_module", "run_path", "spec_from_file_location",
    "SourceFileLoader", "SourcelessFileLoader",
}


@dataclass(frozen=True)
class _WriterSnapshot:
    """Bind the current terminal deployment and writer census as old-state evidence."""

    channel: str
    terminal_revision: str
    terminal_image_digest: str
    terminal_operation_id: str
    terminal_stage: str
    installed_fingerprint: str
    execution_fingerprint: str
    running_writers: tuple[str, ...]
    existing_writers: tuple[str, ...]
    census_fingerprint: str
    retained_state_fingerprint: str
    container_root: str
    vault_overlay: str


def _refuse() -> NoReturn:
    raise RuntimeError("bws_installation_transaction_refused") from None


class _PrebackupGateRefusal(RuntimeError):
    """A finite producer gate refusal, without exception or input details."""

    def __init__(self, gate: str) -> None:
        self.gate = gate
        super().__init__("bws_installation_transaction_refused")


def _refuse_prebackup_gate(gate: str) -> NoReturn:
    if type(gate) is not str or gate not in _PREBACKUP_REFUSAL_GATES:
        _refuse()
    raise _PrebackupGateRefusal(gate) from None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _local_source_name(name: str) -> bool:
    roots = ("app", "scripts", "llm_contract", "mimer_runtime", "companion_ui")
    return name in roots or name.startswith(tuple(root + "." for root in roots))


def _source_module_matches_path(module_name: str, relative: str) -> bool:
    path = PurePosixPath(relative)
    if (not path.is_relative_to("app") and not path.is_relative_to("scripts")) or path.suffix != ".py":
        return False
    parts = path.parts[:-1] if path.name == "__init__.py" else (*path.parts[:-1], path.stem)
    return bool(parts) and module_name == ".".join(parts)


def _supported_source_mode(relative: str, mode: int) -> bool:
    """Accept regular tracked Python source modes; installs preserve candidate mode."""
    return relative.endswith(".py") and mode in {0o644, 0o755}




























def _launcher_tree(raw: bytes) -> ast.Module:
    separator = raw.find(b"\n")
    if (separator <= 0 or not raw.startswith(b"#!/opt/yggdrasil/bws-deploy-runtime/bin/python3\n")
            or b"\x00" in raw or b"\r" in raw):
        _refuse()
    try:
        return ast.parse(raw[separator + 1:])
    except Exception:
        _refuse()


def _trusted_source_loader_exec_module(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Recognize only the fixed loader's source-provenance-bound exec call."""
    try:
        expected_source = '''\
def exec_module(self, module):
    code = self.get_code(module.__name__)
    source_sha256 = getattr(self, "loaded_source_sha256", None)
    if (type(source_sha256) is not str or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)):
        raise ImportError("BWS source provenance unavailable")
    exec(code, module.__dict__)
    module.__dict__[_SOURCE_HASH_ATTRIBUTE] = source_sha256
'''
        expected = ast.parse(expected_source).body[0]
        return ast.dump(method, include_attributes=False) == ast.dump(expected, include_attributes=False)
    except Exception:
        _refuse()


def _require_source_only_launcher(raw: bytes, *, require_preimport_reservation: bool = False) -> None:
    """Require source-only loading; candidates also reserve before app imports."""
    tree = _launcher_tree(raw)
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
           for node in ast.walk(tree)):
        _refuse()
    provenance_policies = [node.value.value for node in tree.body
                           if isinstance(node, ast.Assign)
                           and len(node.targets) == 1
                           and isinstance(node.targets[0], ast.Name)
                           and node.targets[0].id == "_SOURCE_PROVENANCE_POLICY"
                           and isinstance(node.value, ast.Constant)
                           and type(node.value.value) is str]
    source_packages = [tuple(cast(ast.Constant, item).value for item in cast(ast.Tuple, node.value).elts)
                       for node in tree.body
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "_SOURCE_PACKAGES"
                       and isinstance(node.value, ast.Tuple)
                       and all(isinstance(item, ast.Constant) and type(item.value) is str
                               for item in node.value.elts)]
    startup_release_attributes = [node.value.value for node in tree.body
                                  if isinstance(node, ast.Assign) and len(node.targets) == 1
                                  and isinstance(node.targets[0], ast.Name)
                                  and node.targets[0].id == "_STARTUP_RELEASE_ATTRIBUTE"
                                  and isinstance(node.value, ast.Constant)
                                  and type(node.value.value) is str]
    source_loaders = [node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_install_source_loader"]
    runs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"]
    if len(runs) != 1 or len(source_loaders) != 1 \
            or provenance_policies != [_SOURCE_PROVENANCE_POLICY]:
        _refuse()
    run = runs[0]
    tries = [node for node in run.body if isinstance(node, ast.Try)]
    if len(tries) != 1:
        _refuse()
    body = tries[0].body
    dispatchers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_dispatch"]

    def assignment(node: ast.stmt, attribute: str, value: object) -> bool:
        return (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute)
                and node.targets[0].attr == attribute
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "sys"
                and isinstance(node.value, ast.Constant) and node.value.value == value)

    prefixes = [index for index, node in enumerate(body)
                if assignment(node, "pycache_prefix", _SOURCE_PYCACHE_PREFIX)]
    disabled = [index for index, node in enumerate(body)
                if assignment(node, "dont_write_bytecode", True)]
    dispatch_calls = [index for index, node in enumerate(body)
                      if isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
                      and isinstance(node.value.func, ast.Name) and node.value.func.id == "_dispatch"]
    loader_tree = source_loaders[0]
    loader_nodes = list(ast.walk(loader_tree))
    loader_names = {node.name for node in loader_nodes if isinstance(node, ast.ClassDef)}
    if require_preimport_reservation:
        source_exec_methods = [node for node in loader_nodes
                               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and node.name == "exec_module"]
        if len(source_exec_methods) != 1 or not _trusted_source_loader_exec_module(source_exec_methods[0]):
            _refuse()
    finder_methods = [node for node in loader_nodes
                      if isinstance(node, ast.FunctionDef) and node.name == "find_spec"]
    finder_uses_source_packages = (len(finder_methods) == 1 and any(
        isinstance(node, ast.Name) and node.id == "_SOURCE_PACKAGES"
        for node in ast.walk(finder_methods[0])))
    provenance_attribute = any(isinstance(node, ast.Constant)
                               and node.value == _SOURCE_HASH_ATTRIBUTE for node in ast.walk(tree))
    compiled_source = any(isinstance(node, ast.Attribute) and node.attr == "source_to_code"
                          for node in loader_nodes)
    finder_registration = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "insert" and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "meta_path"
        and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys"
        for node in loader_nodes
    )
    if (len(prefixes) != 1 or len(disabled) != 1
            or (dispatchers and len(dispatch_calls) != 1)
            or not {"SourceBoundLoader", "SourceBoundFinder"} <= loader_names
            or source_packages != [("app", "scripts")] or not finder_uses_source_packages
            or not provenance_attribute or not compiled_source or not finder_registration
            or (dispatchers and max(prefixes[0], disabled[0]) >= dispatch_calls[0])):
        _refuse()

    if not dispatchers:
        if require_preimport_reservation:
            _refuse()
        app_imports = [index for index, node in enumerate(body)
                       if isinstance(node, ast.ImportFrom) and node.module == "app.ops.postgres_deploy_linux"]
        loaders = [index for index, node in enumerate(body)
                   if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                   and isinstance(node.value.func, ast.Name)
                   and node.value.func.id == "_install_source_loader"
                   and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Name)
                   and node.value.args[0].id == "root" and not node.value.keywords]
        if (len(app_imports) != 1 or len(loaders) != 1
                or max(prefixes[0], disabled[0]) >= loaders[0] or loaders[0] >= app_imports[0]):
            _refuse()
        return
    if len(dispatchers) != 1:
        _refuse()
    dispatch = dispatchers[0]
    dispatch_nodes = list(ast.walk(dispatch))
    preimport_functions = [node for node in tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == "_preimport_reservation"]
    start_consumer_functions = [node for node in tree.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "_consume_start_authorization"]
    required_start_helpers = {
        "_require_live_installation_caller", "_require_exclusive_lock", "_require_active_channel_owner",
    }
    helper_functions = {node.name: node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name in required_start_helpers}
    active_start_path = (len(preimport_functions) == 1 and len(start_consumer_functions) == 1
                         and set(helper_functions) == required_start_helpers
                         and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                                 and node.func.id == "_consume_start_authorization"
                                 for node in ast.walk(preimport_functions[0]))
                         and any(isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
                                 and isinstance(node.value.func, ast.Name)
                                 and node.value.func.id == "_PreimportReservation"
                                 and any(keyword.arg == "authorized_start"
                                         and isinstance(keyword.value, ast.Constant)
                                         and keyword.value.value is True
                                         for keyword in node.value.keywords)
                                 for node in ast.walk(preimport_functions[0]))
                         and all(any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                                     and child.func.id == required
                                     for child in ast.walk(start_consumer_functions[0]))
                                 for required in required_start_helpers))
    preimport_lines = [node.lineno for node in dispatch_nodes
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "_preimport_reservation"]
    loader_lines = [node.lineno for node in dispatch_nodes
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_install_source_loader"]
    app_import_lines = [node.lineno for node in dispatch_nodes
                        if ((isinstance(node, ast.ImportFrom) and node.module is not None
                             and node.module.startswith("app."))
                            or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                and node.func.attr == "import_module" and node.args
                                and isinstance(node.args[0], ast.Constant)
                                and type(node.args[0].value) is str
                                and node.args[0].value.startswith("app.")))]
    main_calls = [child for child in ast.walk(dispatch) if isinstance(child, ast.Call)
                  and isinstance(child.func, ast.Name) and child.func.id == "main"]
    startup_setters = [child for child in ast.walk(dispatch) if isinstance(child, ast.Call)
                       and isinstance(child.func, ast.Name) and child.func.id == "setattr"
                       and len(child.args) == 3 and isinstance(child.args[0], ast.Name)
                       and child.args[0].id == "sys"
                       and isinstance(child.args[1], ast.Name)
                       and child.args[1].id == "_STARTUP_RELEASE_ATTRIBUTE"
                       and isinstance(child.args[2], ast.Attribute)
                       and child.args[2].attr == "release"
                       and isinstance(child.args[2].value, ast.Name)
                       and child.args[2].value.id == "reservation"]
    cleanup_skip_guards = [node for node in dispatch_nodes
                           if isinstance(node, ast.If)
                           and isinstance(node.test, ast.Attribute)
                           and node.test.attr == "skip_cleanup"
                           and isinstance(node.test.value, ast.Name)
                           and node.test.value.id == "reservation"]
    shared_owner_checks = [node for node in dispatch_nodes
                           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == "shared_caller_reservation"]
    ordinary_start_guards = [node for node in dispatch_nodes
                             if isinstance(node, ast.If)
                             and any(isinstance(value, ast.Attribute)
                                     and value.attr == "authorized_start"
                                     and isinstance(value.value, ast.Name)
                                     and value.value.id == "reservation"
                                     for value in ast.walk(node.test))
                             and any(check is child for child in ast.walk(node) for check in shared_owner_checks)]
    startup_guard = [node for node in ast.walk(dispatch) if isinstance(node, ast.If)
                     and any(isinstance(value, ast.Constant) and value.value == "serve"
                             for value in ast.walk(node.test))
                     and any(setter is child for child in ast.walk(node) for setter in startup_setters)]
    release_calls = [child for child in ast.walk(dispatch) if isinstance(child, ast.Call)
                     and isinstance(child.func, ast.Attribute) and child.func.attr == "release"
                     and isinstance(child.func.value, ast.Name)
                     and child.func.value.id == "reservation"]
    cleanup_skip_guard = cleanup_skip_guards[0] if len(cleanup_skip_guards) == 1 else None
    cleanup_skip_return = (cleanup_skip_guard.body[0] if cleanup_skip_guard is not None
                           and len(cleanup_skip_guard.body) == 1 else None)
    if (startup_release_attributes != ["_yggdrasil_bws_startup_reservation_release"]
            or len(preimport_lines) != 1 or len(loader_lines) != 1 or len(app_import_lines) < 1
            or not preimport_lines[0] < loader_lines[0] < min(app_import_lines)
            or not active_start_path or len(shared_owner_checks) != 1 or len(ordinary_start_guards) != 1
            or not min(app_import_lines) < shared_owner_checks[0].lineno
            or shared_owner_checks[0].lineno >= min(
                node.lineno for node in dispatch_nodes
                if isinstance(node, ast.ImportFrom) and node.module == "app.ops.postgres_deploy_linux"
            )
            or cleanup_skip_guard is None or cleanup_skip_guard.orelse
            or not isinstance(cleanup_skip_return, ast.Return)
            or not isinstance(cleanup_skip_return.value, ast.Constant)
            or cleanup_skip_return.value.value != 0
            or not preimport_lines[0] < cleanup_skip_guard.lineno < loader_lines[0]
            or not main_calls or len(startup_setters) != 1 or not startup_guard or not release_calls):
        _refuse()


def _launcher_behavior(raw: bytes) -> str:
    return ast.dump(_launcher_tree(raw), include_attributes=False)


def _require_launcher_imports(raw: bytes) -> None:
    """Keep the fixed launcher on its standard-library-only import boundary."""
    allowed = {"errno", "fcntl", "hashlib", "importlib", "importlib.machinery", "io", "json",
               "os", "pathlib", "re", "stat", "subprocess", "sys", "uuid"}
    try:
        tree = _launcher_tree(raw)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name not in allowed for alias in node.names):
                    _refuse()
            elif isinstance(node, ast.ImportFrom):
                if node.level or node.module not in allowed | {"app.ops.postgres_deploy_linux"}:
                    _refuse()
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "import_module":
                if (not node.args or not isinstance(node.args[0], ast.Constant)
                        or node.args[0].value not in {
                            "app.ops.bws_installation_admission",
                            "app.ops.bws_installation_transaction",
                        }):
                    _refuse()
    except Exception:
        _refuse()










def _module_path_candidates(module_name: str, roots: dict[str, Path]) -> list[tuple[str, str]]:
    if not _local_source_name(module_name):
        return []
    stem = module_name.replace(".", "/")
    candidates: list[tuple[str, str]] = []
    for root_name, root in roots.items():
        for relative in (stem + ".py", stem + "/__init__.py"):
            # Existence selects a possible public source path only. The later
            # no-follow read is authoritative and refuses symlinks or drift.
            if (root / relative).exists():
                candidates.append((root_name, relative))
    return candidates


def _is_cleanup_action(node: ast.AST) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Attribute)
            and isinstance(node.test.left.value, ast.Name)
            and node.test.left.value.id == "args" and node.test.left.attr == "action"
            and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "cleanup")


def _cleanup_action_branch(main: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.If:
    matches = [node for node in ast.walk(main) if _is_cleanup_action(node)]
    if len(matches) != 1:
        _refuse()
    return cast(ast.If, matches[0])


def _is_args_channel(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "channel"
            and isinstance(node.value, ast.Name) and node.value.id == "args")


def _is_dev_test_channel_guard(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.In) and _is_args_channel(test.left)
            and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Set)
            and len(test.comparators[0].elts) == 2
            and all(isinstance(item, ast.Constant) for item in test.comparators[0].elts)
            and [cast(ast.Constant, item).value for item in test.comparators[0].elts] == ["dev", "test"])


def _is_cleanup_skip_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    call = node.test
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "cleanup_must_skip" and not call.keywords and len(call.args) == 1
            and _is_args_channel(call.args[0]))


def _cleanup_fast_return(raw: bytes) -> str:
    """Fingerprint the exact cleanup hook that exits before source cleanup."""
    try:
        tree = ast.parse(raw)
        mains = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "main"]
        if len(mains) != 1:
            _refuse()
        branch = _cleanup_action_branch(mains[0])
        body = branch.body
        if (len(body) < 2 or not isinstance(body[0], ast.ImportFrom)
                or body[0].module != "app.ops.bws_installation_admission"
                or [(item.name, item.asname) for item in body[0].names]
                != [("cleanup_must_skip", None)]):
            _refuse()
        guards = [node for node in ast.walk(branch) if _is_cleanup_skip_guard(node)]
        if len(guards) != 1:
            _refuse()
        guard = cast(ast.If, guards[0])
        if guard.orelse or len(guard.body) != 1:
            _refuse()
        # The accepted placements are the old immediate guard or the current
        # DEV/TEST wrapper which imports the reservation helper first. No
        # executable cleanup statement may precede the guard.
        if body[1] is guard:
            pass
        elif (isinstance(body[1], ast.If) and _is_dev_test_channel_guard(body[1])
              and not body[1].orelse and len(body[1].body) >= 2
              and isinstance(body[1].body[0], ast.ImportFrom)
              and body[1].body[0].module == "app.ops.bws_installation_admission"
              and [(item.name, item.asname) for item in body[1].body[0].names]
              == [("shared_caller_reservation", None)]
              and body[1].body[1] is guard):
            pass
        else:
            _refuse()
        returned = guard.body[0]
        if (not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Constant)
                or returned.value.value != 0):
            _refuse()
        return ast.dump(guard, include_attributes=False)
    except Exception:
        _refuse()


def _cleanup_entrypoint(raw: bytes) -> str:
    try:
        tree = ast.parse(raw)
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name == "main"]
        if len(functions) != 1:
            _refuse()
        main = copy.deepcopy(functions[0])
        branch = _cleanup_action_branch(main)
        # The cleanup branch may gain the shared reservation required to fence
        # its writes. Compare the rest of the real CLI entrypoint byte-for-byte.
        branch.body = [ast.Pass()]
        return ast.dump(main, include_attributes=False)
    except Exception:
        _refuse()


def _require_cleanup_shared_reservation(raw: bytes) -> None:
    """Require candidate ExecStopPost to hold its shared owner lock through cleanup."""
    try:
        tree = ast.parse(raw)
        mains = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "main"]
        if len(mains) != 1:
            _refuse()
        branch = _cleanup_action_branch(mains[0])
        body = branch.body
        if (len(body) < 3 or not isinstance(body[0], ast.ImportFrom)
                or body[0].module != "app.ops.bws_installation_admission"
                or [(item.name, item.asname) for item in body[0].names]
                != [("cleanup_must_skip", None)]
                or not isinstance(body[1], ast.If)
                or not _is_dev_test_channel_guard(body[1])
                or body[1].orelse
                or len(body[1].body) != 3
                or not isinstance(body[1].body[0], ast.ImportFrom)
                or body[1].body[0].module != "app.ops.bws_installation_admission"
                or [(item.name, item.asname) for item in body[1].body[0].names]
                != [("shared_caller_reservation", None)]
                or not _is_cleanup_skip_guard(body[1].body[1])
                or not isinstance(body[1].body[2], ast.Try)):
            _refuse()
        channel_guard = cast(ast.If, body[1])
        guard = cast(ast.If, channel_guard.body[1])
        if guard.orelse or len(guard.body) != 1 or not isinstance(guard.body[0], ast.Return):
            _refuse()
        guarded = body[1].body[2]
        if (len(guarded.body) != 1 or len(guarded.handlers) != 1
                or guarded.orelse or guarded.finalbody
                or not isinstance(guarded.handlers[0].type, ast.Name)
                or guarded.handlers[0].type.id != "Exception"
                or len(guarded.handlers[0].body) != 1
                or not isinstance(guarded.handlers[0].body[0], ast.Return)
                or not isinstance(guarded.handlers[0].body[0].value, ast.Constant)
                or guarded.handlers[0].body[0].value.value != 0):
            _refuse()
        expression = guarded.body[0]
        call = expression.value if isinstance(expression, ast.Expr) else None
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                or call.func.attr != "enter_context"
                or not isinstance(call.func.value, ast.Name) or call.func.value.id != "admissions"
                or len(call.args) != 1 or call.keywords
                or not isinstance(call.args[0], ast.Call)
                or not isinstance(call.args[0].func, ast.Name)
                or call.args[0].func.id != "shared_caller_reservation"
                or len(call.args[0].args) != 1 or call.args[0].keywords
                or not isinstance(call.args[0].args[0], ast.Attribute)
                or not isinstance(call.args[0].args[0].value, ast.Name)
                or call.args[0].args[0].value.id != "args"
                or call.args[0].args[0].attr != "channel"):
            _refuse()
        assignments = [node for node in mains[0].body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "admissions"
                               for target in node.targets)]
        stack_imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                         and node.module == "contextlib"
                         and any(item.name == "ExitStack" and item.asname is None for item in node.names)]
        finalizers = [node for node in mains[0].body if isinstance(node, ast.Try)
                      and any(candidate is branch for candidate in ast.walk(node))]
        if (len(assignments) != 1 or not isinstance(assignments[0].value, ast.Call)
                or not isinstance(assignments[0].value.func, ast.Name)
                or assignments[0].value.func.id != "ExitStack"
                or assignments[0].value.args or assignments[0].value.keywords
                or len(stack_imports) != 1 or len(finalizers) != 1
                or len(finalizers[0].finalbody) != 1
                or not isinstance(finalizers[0].finalbody[0], ast.Expr)
                or not isinstance(finalizers[0].finalbody[0].value, ast.Call)
                or not isinstance(finalizers[0].finalbody[0].value.func, ast.Attribute)
                or not isinstance(finalizers[0].finalbody[0].value.func.value, ast.Name)
                or finalizers[0].finalbody[0].value.func.value.id != "admissions"
                or finalizers[0].finalbody[0].value.func.attr != "close"
                or finalizers[0].finalbody[0].value.args or finalizers[0].finalbody[0].value.keywords):
            _refuse()
    except Exception:
        _refuse()


def _require_startup_reservation_release(raw: bytes) -> None:
    """Keep startup imports fenced through listen, then fence each supervisor call."""
    try:
        tree = ast.parse(raw)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        main = functions.get("main")
        serve = functions.get("serve")
        if (main is None or serve is None
                or not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                           and node.func.id == "serve" for node in ast.walk(main))):
            _refuse()
        release_functions = [node for node in ast.walk(serve)
                             if isinstance(node, ast.FunctionDef)
                             and node.name == "release_startup_reservation"]
        if (len(release_functions) != 1
                or not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                           and node.func.id == "getattr" and len(node.args) >= 2
                           and isinstance(node.args[0], ast.Name) and node.args[0].id == "sys"
                           and isinstance(node.args[1], ast.Constant)
                           and node.args[1].value == "_yggdrasil_bws_startup_reservation_release"
                           for node in ast.walk(release_functions[0]))
                or not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                           and node.func.id == "callback" for node in ast.walk(release_functions[0]))):
            _refuse()
        listener_blocks = [node for node in ast.walk(serve) if isinstance(node, (ast.With, ast.AsyncWith))
                           and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                                   and child.func.id == "Server" for child in ast.walk(node.items[0].context_expr))]
        if len(listener_blocks) != 1:
            _refuse()
        listener_body = listener_blocks[0].body
        release_positions = [index for index, node in enumerate(listener_body)
                             if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                                    and child.func.id == "release_startup_reservation" for child in ast.walk(node))]
        serve_positions = [index for index, node in enumerate(listener_body)
                           if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                                  and child.func.attr == "serve_forever" for child in ast.walk(node))]
        if (len(release_positions) != 1 or len(serve_positions) != 1
                or release_positions[0] >= serve_positions[0]
                or not any(isinstance(node, ast.Try)
                           and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                                   and child.func.id == "release_startup_reservation"
                                   for finalizer in node.finalbody for child in ast.walk(finalizer))
                           for node in ast.walk(serve))):
            _refuse()

        handlers = [node for node in ast.walk(serve) if isinstance(node, ast.ClassDef) and node.name == "Handler"]
        handle_methods = [child for handler in handlers for child in handler.body
                          if isinstance(child, ast.FunctionDef) and child.name == "handle"]
        admission_imports = [node for method in handle_methods for node in ast.walk(method)
                             if isinstance(node, ast.ImportFrom)
                             and node.module == "app.ops.bws_installation_admission"
                             and any(alias.name == "shared_caller_reservation" for alias in node.names)]
        protected_else = [branch for method in handle_methods for conditional in ast.walk(method)
                          if isinstance(conditional, ast.If)
                          and any(isinstance(value, ast.Constant) and value.value == "source-installation-profile"
                                  for value in ast.walk(conditional.test))
                          for branch in conditional.orelse
                          if any(any(import_node is admission for import_node in ast.walk(branch))
                                 for admission in admission_imports)]
        if len(handlers) != 1 or len(handle_methods) != 1 or len(admission_imports) != 1 or not protected_else:
            _refuse()
    except Exception:
        _refuse()


def _module_import_skeleton(raw: bytes) -> str:
    """Fingerprint module-time statements and callable signatures, excluding bodies."""
    try:
        tree = ast.parse(raw)

        def retain_import_behavior(nodes: list[ast.stmt]) -> list[ast.stmt]:
            kept = []
            for original in nodes:
                node = copy.deepcopy(original)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.body = [ast.Pass()]
                elif isinstance(node, ast.ClassDef):
                    node.body = retain_import_behavior(node.body)
                kept.append(node)
            return kept

        return ast.dump(ast.Module(body=retain_import_behavior(tree.body), type_ignores=[]),
                        include_attributes=False)
    except Exception:
        _refuse()


def _cleanup_skip_closure(raw: bytes) -> str:
    """Fingerprint cleanup_must_skip plus its local function/global dependencies."""
    try:
        tree = ast.parse(raw)
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            function_node.name: function_node for function_node in tree.body
            if isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        classes: dict[str, ast.ClassDef] = {
            class_node.name: class_node for class_node in tree.body if isinstance(class_node, ast.ClassDef)
        }
        assignments: dict[str, ast.stmt] = {}
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node
        pending = ["cleanup_must_skip"]
        pending_globals: list[str] = []
        selected_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        selected_classes: dict[str, ast.ClassDef] = {}
        selected_assignments: dict[str, ast.stmt] = {}
        while pending or pending_globals:
            if pending:
                name = pending.pop()
                if name in selected_functions:
                    continue
                function_node = functions.get(name)
                if function_node is None:
                    _refuse()
                selected_functions[name] = function_node
                local_names = {arg.arg for arg in (*function_node.args.posonlyargs, *function_node.args.args,
                                                      *function_node.args.kwonlyargs)}
                if function_node.args.vararg is not None:
                    local_names.add(function_node.args.vararg.arg)
                if function_node.args.kwarg is not None:
                    local_names.add(function_node.args.kwarg.arg)
                for child in ast.walk(function_node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        if child.id in functions:
                            pending.append(child.id)
                        elif child.id in classes:
                            selected_classes[child.id] = classes[child.id]
                        elif child.id not in local_names and child.id in assignments:
                            pending_globals.append(child.id)
                continue
            name = pending_globals.pop()
            if name in selected_assignments:
                continue
            assignment_node = assignments.get(name)
            if assignment_node is None:
                _refuse()
            selected_assignments[name] = assignment_node
            for child in ast.walk(assignment_node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    if child.id in assignments:
                        pending_globals.append(child.id)
                    elif child.id in functions:
                        pending.append(child.id)
        nodes: list[ast.stmt] = [selected_functions[name] for name in sorted(selected_functions)]
        nodes.extend(selected_classes[name] for name in sorted(selected_classes))
        nodes.extend(selected_assignments[name] for name in sorted(selected_assignments))
        return ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False)
    except Exception:
        _refuse()


def _open_absolute_directory(path: Path, opened: list[int]) -> int:
    if (not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:])
            or "\\" in str(path)):
        _refuse()
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(current)
        path_parts = path.parts[1:]
        for index, part in enumerate(path_parts):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            opened.append(child)
            info = os.fstat(child)
            named = os.stat(part, dir_fd=current, follow_symlinks=False)
            is_target = index == len(path_parts) - 1
            allowed_modes = {0o700, 0o755} if is_target else {0o700, 0o750, 0o755}
            if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or not stat.S_ISDIR(info.st_mode)
                    or (info.st_uid != _OWNER_UID if is_target else info.st_uid not in {0, _OWNER_UID})
                    or (info.st_gid != _OWNER_GID if is_target else info.st_mode & 0o022 != 0)
                    or stat.S_IMODE(info.st_mode) not in allowed_modes
                    or os.get_inheritable(child)):
                _refuse()
            current = child
        return current
    except Exception:
        _refuse()


def _read_relative(root_fd: int, relative: str) -> tuple[bytes, int]:
    parts = PurePosixPath(relative).parts
    if (not parts or any(part in {"", ".", ".."} for part in parts)
            or not (relative.startswith("app/") or relative.startswith("scripts/")
                    or relative == _CONTRACT.as_posix())):
        _refuse()
    opened: list[int] = []
    try:
        current = root_fd
        for part in parts[:-1]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            opened.append(current)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != _OWNER_UID or before.st_gid != _OWNER_GID
                or not (_supported_source_mode(relative, mode)
                        or (relative == _CONTRACT.as_posix() and mode in {0o600, 0o644}))
                or before.st_nlink != 1
                or (before.st_size <= 0 and relative == _CONTRACT.as_posix())
                or before.st_size > _MAX_SOURCE_BYTES
                or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                or os.get_inheritable(descriptor)):
            _refuse()
        raw = os.pread(descriptor, before.st_size + 1, 0)
        after = os.fstat(descriptor)
        current_name = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        version = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                                info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (len(raw) != before.st_size or version(after) != version(before)
                or version(current_name) != version(before)):
            _refuse()
        return raw, mode
    except Exception:
        _refuse()
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def _source_modules(
    config: Any, roots: dict[str, Path], *, caller_source_modules: object = None,
) -> list[dict[str, object]]:
    if (getattr(sys, "pycache_prefix", None) != _SOURCE_PYCACHE_PREFIX
            or getattr(sys, "dont_write_bytecode", None) is not True):
        _refuse()
    names: dict[str, tuple[str, str]] = {}
    loaded_source_hashes: dict[str, str] = {}
    ordered_roots = sorted(roots.items(), key=lambda item: len(str(item[1])), reverse=True)
    for name, module in tuple(sys.modules.items()):
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*", name) is None:
            continue
        filename = getattr(module, "__file__", None)
        if type(filename) is not str or not filename.endswith(".py"):
            continue
        path = Path(os.path.abspath(filename))
        for root_name, root in ordered_roots:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if (name == "__main__" and root_name == "application"
                    and relative == "scripts/postgres_deploy_service.py"):
                # The directly executed first-call script is bound separately
                # by the admission caller's checkout/script identity.
                break
            if not _source_module_matches_path(name, relative):
                _refuse()
            cached = getattr(module, "__cached__", None)
            expected_cache = importlib.util.cache_from_source(filename)
            if (type(cached) is not str or cached != expected_cache
                    or not cached.startswith(_SOURCE_PYCACHE_PREFIX + os.sep)):
                _refuse()
            prior = names.get(name)
            selected = (root_name, relative)
            if prior is not None and prior != selected:
                _refuse()
            loaded_sha256 = getattr(module, _SOURCE_HASH_ATTRIBUTE, None)
            if (type(loaded_sha256) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", loaded_sha256) is None
                    or (name in loaded_source_hashes and loaded_source_hashes[name] != loaded_sha256)):
                _refuse()
            names[name] = selected
            loaded_source_hashes[name] = loaded_sha256
            break
    if caller_source_modules is not None:
        if type(caller_source_modules) is not list or len(caller_source_modules) > _MAX_MODULES:
            _refuse()
        for row in caller_source_modules:
            if (type(row) is not dict or set(row) != {"module", "root", "path", "sha256", "mode"}
                    or type(row["module"]) is not str
                    or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*", row["module"]) is None
                    or type(row["root"]) is not str or row["root"] not in roots
                    or type(row["path"]) is not str or not _source_module_matches_path(row["module"], row["path"])
                    or type(row["sha256"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
                    or type(row["mode"]) is not int
                    or not _supported_source_mode(row["path"], row["mode"])
                    or (row["mode"] == 0o755 and row["root"] != "application")):
                _refuse()
            module_name = row["module"]
            selected = (row["root"], row["path"])
            prior = names.get(module_name)
            loaded_sha256 = loaded_source_hashes.get(module_name)
            if (prior != selected or loaded_sha256 != row["sha256"]):
                _refuse()
    if not names or len(names) > _MAX_MODULES:
        _refuse()
    identities: list[dict[str, object]] = []
    descriptors: list[int] = []
    root_descriptors: dict[str, int] = {}
    try:
        for name, path in roots.items():
            root_descriptors[name] = _open_absolute_directory(path, descriptors)
        root_paths = [Path(value) for value in roots.values()]
        if any(left == right or left in right.parents or right in left.parents
               for index, left in enumerate(root_paths) for right in root_paths[index + 1:]):
            _refuse()
        pending = list(names.items())
        visited: dict[str, tuple[str, str]] = {}
        while pending:
            module_name, (root_name, relative) = pending.pop()
            prior = visited.get(module_name)
            selected = (root_name, relative)
            if prior is not None:
                if prior != selected:
                    _refuse()
                continue
            if len(visited) >= _MAX_MODULES:
                _refuse()
            visited[module_name] = selected
            raw, mode = _read_relative(root_descriptors[root_name], relative)
            if loaded_source_hashes.get(module_name) != _sha(raw):
                _refuse()
            identities.append({"module": module_name, "root": root_name,
                               "path": relative, "sha256": _sha(raw), "mode": mode})
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()
    identities.sort(key=lambda row: (str(row["module"]), str(row["root"]), str(row["path"])))
    return identities


def _source_path_is_supported(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (len(parts) >= 2 and parts[0] in {"app", "scripts"}
            and re.fullmatch(r"[A-Za-z0-9_]+\.py", parts[-1]) is not None
            and all(re.fullmatch(r"[A-Za-z0-9_]+", part) is not None for part in parts[:-1]))


def _external_source_path_is_supported(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (len(parts) >= 2 and parts[0] in _EXTERNAL_SOURCE_ROOTS
            and re.fullmatch(r"[A-Za-z0-9_-]+\.py", parts[-1]) is not None
            and all(re.fullmatch(r"[A-Za-z0-9_-]+", part) is not None for part in parts[:-1]))


def _source_file_inventory(roots: dict[str, Path]) -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    """Hash every Python source file reachable through the fixed app/scripts loader roots."""
    rows: list[dict[str, object]] = []
    packages: dict[str, list[str]] = {}
    total_bytes = 0
    total_entries = 0

    def inspect_package(root_fd: int, root_name: str, package: str, package_fd: int) -> None:
        nonlocal total_bytes, total_entries

        def walk(directory_fd: int, prefix: str) -> None:
            nonlocal total_bytes, total_entries
            try:
                names = []
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        total_entries += 1
                        if total_entries > _MAX_SOURCE_ENTRIES:
                            _refuse()
                        names.append(entry.name)
                names.sort()
                for name in names:
                    if (not isinstance(name, str) or name in {"", ".", ".."}
                            or "/" in name or "\\" in name or "\x00" in name):
                        _refuse()
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        _refuse()
                    if stat.S_ISDIR(info.st_mode):
                        if (info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID
                                or info.st_mode & 0o022):
                            _refuse()
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                        | getattr(os, "O_CLOEXEC", 0), dir_fd=directory_fd)
                        try:
                            opened = os.fstat(child)
                            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                            if ((opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                                    or not stat.S_ISDIR(opened.st_mode)):
                                _refuse()
                            walk(child, prefix + name + "/")
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(info.st_mode) and name.endswith(".py"):
                        relative = prefix + name
                        if not _source_path_is_supported(relative):
                            _refuse()
                        raw, mode = _read_relative(root_fd, relative)
                        if not _supported_source_mode(relative, mode):
                            _refuse()
                        total_bytes += len(raw)
                        if total_bytes > _MAX_TOTAL_SOURCE_BYTES:
                            _refuse()
                        rows.append({"root": root_name, "path": relative, "sha256": _sha(raw),
                                     "mode": mode, "size": len(raw)})
                        if len(rows) > _MAX_SOURCE_FILES:
                            _refuse()
                    elif not stat.S_ISREG(info.st_mode):
                        _refuse()
            except OSError:
                _refuse()
            except RuntimeError:
                raise
            except Exception:
                _refuse()

        walk(package_fd, package + "/")

    for root_name, root in sorted(roots.items()):
        opened: list[int] = []
        try:
            root_fd = _open_absolute_directory(root, opened)
            selected_packages: list[str] = []
            for package in ("app", "scripts"):
                try:
                    info = os.stat(package, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if root_name == "application":
                        _refuse()
                    continue
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != _OWNER_UID
                        or info.st_gid != _OWNER_GID or info.st_mode & 0o022):
                    _refuse()
                package_fd = os.open(package, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                     | getattr(os, "O_CLOEXEC", 0), dir_fd=root_fd)
                try:
                    opened_info = os.fstat(package_fd)
                    current = os.stat(package, dir_fd=root_fd, follow_symlinks=False)
                    if ((opened_info.st_dev, opened_info.st_ino) != (current.st_dev, current.st_ino)
                            or not stat.S_ISDIR(opened_info.st_mode)):
                        _refuse()
                    selected_packages.append(package)
                    inspect_package(root_fd, root_name, package, package_fd)
                finally:
                    os.close(package_fd)
            packages[root_name] = selected_packages
        except Exception:
            _refuse()
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    rows.sort(key=lambda row: (str(row["root"]), str(row["path"])))
    if not rows:
        _refuse()
    return rows, packages


def _old_disk_state(config: Any, request: dict[str, str]) -> dict[str, object]:
    """Capture bounded old on-disk state without asserting which bytes it loaded."""
    from app.ops.host_secret_contract import load_host_secret_contract_bytes
    from app.ops.bws_installation_lifecycle import _public_launcher_bytes

    if config.channel not in {"dev", "test"}:
        _refuse()
    roots = {"application": Path(config.root), "control": _CONTROL_DIRECTORY}
    source_files, source_packages = _source_file_inventory(roots)
    opened: list[int] = []
    try:
        application_fd = _open_absolute_directory(roots["application"], opened)
        contract, contract_mode = _read_relative(application_fd, _CONTRACT.as_posix())
        load_host_secret_contract_bytes(contract)
    except Exception:
        _refuse()
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()
    launcher = _public_launcher_bytes()
    value: dict[str, object] = {
        "schema": _OLD_DISK_STATE_SCHEMA,
        "operation_id": request["operation_id"],
        "channel": request["channel"],
        "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"],
        "roots": {name: _root_identity(path) for name, path in roots.items()},
        "source_files": source_files,
        "source_packages": source_packages,
        "contract_sha256": _sha(contract),
        "contract_mode": contract_mode,
        "launcher_sha256": _sha(launcher),
    }
    value["disk_state_sha256"] = _sha(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )
    if len(json.dumps(value, sort_keys=True, separators=(",", ":"))) > _MAX_PROFILE_BYTES:
        _refuse()
    return value


def _git_source_files(root: Path, revision: str) -> dict[str, tuple[bytes, int]]:
    """Read the exact tracked app/scripts Python tree without importing candidate code."""
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        _refuse()
    environment = _git_environment()
    try:
        listing = subprocess.run(
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "ls-tree", "-r", "-t", "-z",
             "--full-tree", revision, "--", "app", "scripts"],
            env=environment, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
        )
        if listing.returncode != 0 or listing.stderr or len(listing.stdout) > 8 * 1024 * 1024:
            _refuse()
        blobs: list[tuple[str, str, int]] = []
        package_roots: set[str] = set()
        for record in listing.stdout.split(b"\0"):
            if not record:
                continue
            header, separator, raw_path = record.partition(b"\t")
            fields = header.split()
            if not separator or len(fields) != 3:
                _refuse()
            mode, kind, object_id = (field.decode("ascii") for field in fields)
            path = raw_path.decode("utf-8")
            if path in {"app", "scripts"}:
                if mode != "040000" or kind != "tree":
                    _refuse()
                package_roots.add(path)
                continue
            if not (path.startswith("app/") or path.startswith("scripts/")):
                _refuse()
            if mode == "120000" or mode == "160000" or kind not in {"blob", "tree"}:
                _refuse()
            if kind == "tree":
                if mode != "040000":
                    _refuse()
                continue
            if mode not in {"100644", "100755"}:
                _refuse()
            if path.endswith(".py"):
                if not _source_path_is_supported(path):
                    _refuse()
                blobs.append((path, object_id, int(mode, 8) & 0o777))
                if len(blobs) > _MAX_SOURCE_FILES:
                    _refuse()
        if package_roots != {"app", "scripts"} or not blobs:
            _refuse()
        unique_ids = list(dict.fromkeys(object_id for _, object_id, _ in blobs))
        batch = subprocess.run(
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "cat-file", "--batch"],
            env=environment, input=("".join(object_id + "\n" for object_id in unique_ids)).encode("ascii"),
            capture_output=True, check=False, timeout=60,
        )
        if batch.returncode != 0 or batch.stderr or len(batch.stdout) > _MAX_TOTAL_SOURCE_BYTES + 1_000_000:
            _refuse()
        source_by_id: dict[str, bytes] = {}
        stream = io.BytesIO(batch.stdout)
        total_bytes = 0
        for expected_id in unique_ids:
            batch_header = stream.readline().rstrip(b"\n").split()
            if (len(batch_header) != 3 or batch_header[0].decode("ascii") != expected_id
                    or batch_header[1] != b"blob"):
                _refuse()
            size = int(batch_header[2])
            if size < 0 or size > _MAX_SOURCE_BYTES:
                _refuse()
            raw = stream.read(size)
            if len(raw) != size or stream.read(1) != b"\n":
                _refuse()
            total_bytes += size
            if total_bytes > _MAX_TOTAL_SOURCE_BYTES:
                _refuse()
            source_by_id[expected_id] = raw
        if stream.read(1):
            _refuse()
        result = {path: (source_by_id[object_id], mode) for path, object_id, mode in blobs}
        if len(result) != len(blobs):
            _refuse()
        return result
    except Exception:
        _refuse()


def _root_identity(path: Path) -> dict[str, int]:
    opened: list[int] = []
    try:
        descriptor = _open_absolute_directory(path, opened)
        info = os.fstat(descriptor)
        if info.st_uid != _OWNER_UID or info.st_gid != _OWNER_GID:
            _refuse()
        return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
                "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode)}
    except Exception:
        _refuse()
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()


def loaded_source_profile(
    config: Any, *, operation_id: str, candidate_sha: str, image_digest: str,
    caller_source_modules: object = None,
) -> dict[str, object]:
    """Return a redacted profile of actually loaded BWS Python source modules."""
    if (getattr(sys, "pycache_prefix", None) != _SOURCE_PYCACHE_PREFIX
            or getattr(sys, "dont_write_bytecode", None) is not True):
        _refuse()
    if (config.channel not in {"dev", "test"} or type(operation_id) is not str
            or str(UUID(operation_id)) != operation_id
            or type(candidate_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
            or type(image_digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None):
        _refuse()
    from app.ops.bws_installation_lifecycle import _public_launcher_bytes
    from app.ops.host_secret_contract import load_host_secret_contract_bytes

    # These fixed modules are used by later transaction phases through local
    # imports. Load their exact source before taking the sys.modules snapshot.
    for module_name in (
        "app.ops.bws_control_installation",
        "app.ops.bws_installation_admission",
        "app.ops.native_source_admission",
        "app.ops.native_journaling_acceptance",
        "app.ops.pg_acceptance",
        "app.ops.postgres_deploy",
        "app.instance.mvr05_cutover",
        "scripts.compose_env",
    ):
        importlib.import_module(module_name)

    roots = {"application": config.root, "control": _CONTROL_DIRECTORY}
    modules = _source_modules(config, roots, caller_source_modules=caller_source_modules)
    source_files, source_packages = _source_file_inventory(roots)
    files_by_key = {(row["root"], row["path"]): row for row in source_files}
    for module in modules:
        file_row = files_by_key.get((module["root"], module["path"]))
        if (file_row is None or file_row["sha256"] != module["sha256"]
                or file_row["mode"] != module["mode"]):
            _refuse()
    application_fds: list[int] = []
    try:
        application_fd = _open_absolute_directory(config.root, application_fds)
        contract_raw, contract_mode = _read_relative(application_fd, _CONTRACT.as_posix())
        load_host_secret_contract_bytes(contract_raw)
    except Exception:
        _refuse()
    finally:
        for descriptor in reversed(application_fds):
            try:
                os.close(descriptor)
            except OSError:
                _refuse()
    launcher = _public_launcher_bytes()
    _require_source_only_launcher(launcher)
    profile: dict[str, object] = {
        "schema": _PROFILE_SCHEMA,
        "source_loading_policy": _SOURCE_LOADING_POLICY,
        "operation_id": operation_id,
        "channel": config.channel,
        "candidate_sha": candidate_sha,
        "image_digest": image_digest,
        "roots": {name: _root_identity(path) for name, path in roots.items()},
        "modules": modules,
        "source_files": source_files,
        "source_packages": source_packages,
        "contract_sha256": _sha(contract_raw),
        "contract_mode": contract_mode,
        "launcher_sha256": _sha(launcher),
    }
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("ascii")
    profile["profile_sha256"] = _sha(canonical)
    if len(json.dumps(profile, sort_keys=True, separators=(",", ":"))) > _MAX_PROFILE_BYTES:
        _refuse()
    return profile


def candidate_manifest(
    profile: dict[str, object], *, revision: str, roots: dict[str, Any],
    backup_root: Any, git_show: Any, git_source_files: Any = None, git_file_mode: Any = None,
) -> tuple[tuple[Any, ...], dict[tuple[str, str], bytes], dict[str, Any]]:
    """Build an exact candidate delta from an old disk snapshot and Git tree."""
    from app.ops.bws_control_installation import Change
    from app.ops.host_secret_contract import load_host_secret_contract_bytes

    required = {
        "schema", "operation_id", "channel", "candidate_sha", "image_digest", "roots",
        "source_files", "source_packages", "contract_sha256", "contract_mode", "launcher_sha256",
        "disk_state_sha256",
    }
    if (type(profile) is not dict or set(profile) != required
            or profile["schema"] != _OLD_DISK_STATE_SCHEMA
            or profile["candidate_sha"] != revision or profile["channel"] not in {"dev", "test"}
            or type(profile["source_files"]) is not list or not profile["source_files"]
            or len(profile["source_files"]) > _MAX_SOURCE_FILES
            or type(profile["source_packages"]) is not dict
            or set(profile["source_packages"]) != {"application", "control"}
            or type(profile["roots"]) is not dict
            or set(profile["roots"]) != {"application", "control"}
            or set(roots) not in ({"application", "control", "launcher"}, {"application", "launcher"})
            or type(profile["contract_mode"]) is not int or profile["contract_mode"] != 0o644
            or type(profile["disk_state_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", profile["disk_state_sha256"]) is None):
        _refuse()
    canonical = {key: value for key, value in profile.items() if key != "disk_state_sha256"}
    if _sha(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("ascii"))             != profile["disk_state_sha256"]:
        _refuse()
    if (type(profile["operation_id"]) is not str or str(UUID(profile["operation_id"])) != profile["operation_id"]
            or type(profile["candidate_sha"]) is not str
            or re.fullmatch(r"[0-9a-f]{40}", profile["candidate_sha"]) is None
            or type(profile["image_digest"]) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", profile["image_digest"]) is None
            or type(profile["contract_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", profile["contract_sha256"]) is None
            or type(profile["launcher_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", profile["launcher_sha256"]) is None):
        _refuse()

    packages = cast(dict[str, object], profile["source_packages"])
    for root_name, package_value in packages.items():
        if (type(package_value) is not list or package_value != sorted(set(package_value))
                or any(type(package) is not str or package not in {"app", "scripts"}
                       for package in package_value)
                or (root_name == "application" and package_value != ["app", "scripts"])):
            _refuse()

    source_rows = cast(list[object], profile["source_files"])
    old_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for value in source_rows:
        if type(value) is not dict or set(value) != {"root", "path", "sha256", "mode", "size"}:
            _refuse()
        row = cast(dict[str, object], value)
        source_root_name, source_path, source_digest, source_mode, source_size = (
            row["root"], row["path"], row["sha256"], row["mode"], row["size"],
        )
        if (type(source_root_name) is not str or source_root_name not in {"application", "control"}
                or source_root_name not in roots or type(source_path) is not str
                or not _source_path_is_supported(source_path)
                or type(source_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", source_digest) is None
                or type(source_mode) is not int or not _supported_source_mode(source_path, source_mode)
                or type(source_size) is not int or not 0 <= source_size <= _MAX_SOURCE_BYTES):
            _refuse()
        key = (cast(str, source_root_name), cast(str, source_path))
        if key in old_by_key:
            _refuse()
        old_by_key[key] = row
    if sum(cast(int, row["size"]) for row in old_by_key.values()) > _MAX_TOTAL_SOURCE_BYTES:
        _refuse()

    current_roots = {name: Path(roots[name].path) for name in ("application", "control") if name in roots}
    current_files, current_packages = _source_file_inventory(current_roots)
    if current_files != profile["source_files"] or current_packages != profile["source_packages"]:
        _refuse()

    if git_source_files is None:
        _refuse()
    candidate_tree = git_source_files(revision)
    if type(candidate_tree) is not dict or not candidate_tree:
        _refuse()
    candidate_file_data: dict[str, tuple[bytes, int]] = {}
    candidate_total = 0
    for path, value in candidate_tree.items():
        if (type(path) is not str or not _source_path_is_supported(path)
                or type(value) is not tuple or len(value) != 2 or type(value[0]) is not bytes
                or len(value[0]) > _MAX_SOURCE_BYTES or type(value[1]) is not int
                or not _supported_source_mode(path, value[1]) or path in candidate_file_data):
            _refuse()
        candidate_total += len(value[0])
        if candidate_total > _MAX_TOTAL_SOURCE_BYTES or len(candidate_tree) > _MAX_SOURCE_FILES:
            _refuse()
        candidate_file_data[path] = cast(tuple[bytes, int], value)

    changes: list[Any] = []
    payloads: dict[tuple[str, str], bytes] = {}
    candidate_source_by_key: dict[tuple[str, str], bytes] = {}
    candidate_files: list[dict[str, object]] = []
    total_delta_bytes = 0
    root_fds: dict[str, tuple[int, list[int]]] = {}
    try:
        for name, root in roots.items():
            opened: list[int] = []
            root_fd = _open_absolute_directory(Path(root.path), opened)
            root_info = os.fstat(root_fd)
            if (root_info.st_dev, root_info.st_ino, root_info.st_uid, root_info.st_gid,
                    stat.S_IMODE(root_info.st_mode)) != (
                    root.device, root.inode, root.uid, root.gid, root.mode):
                _refuse()
            if name in {"application", "control"}:
                expected_identity = profile["roots"].get(name)
                actual_identity = {"device": root_info.st_dev, "inode": root_info.st_ino,
                                   "uid": root_info.st_uid, "gid": root_info.st_gid,
                                   "mode": stat.S_IMODE(root_info.st_mode)}
                if expected_identity != actual_identity:
                    _refuse()
            root_fds[name] = (root_fd, opened)

        package_paths = {package: {path for path in candidate_file_data if path.startswith(package + "/")}
                         for package in ("app", "scripts")}
        for root_name, package_list in packages.items():
            old_paths = {path for selected_root, path in old_by_key if selected_root == root_name}
            candidate_paths = set().union(*(package_paths[package] for package in cast(list[str], package_list)))
            target_paths = candidate_paths if root_name == "application" else old_paths
            if not old_paths <= target_paths or not target_paths:
                _refuse()
            for relative in sorted(target_paths):
                candidate_raw, candidate_mode = candidate_file_data[relative]
                key = (root_name, relative)
                prior = old_by_key.get(key)
                if prior is None:
                    old_raw, old_mode, before_sha256 = b"", None, None
                else:
                    old_raw, old_mode = _read_relative(root_fds[root_name][0], relative)
                    if (_sha(old_raw) != prior["sha256"] or len(old_raw) != prior["size"]
                            or old_mode != prior["mode"]):
                        _refuse()
                    before_sha256 = cast(str, prior["sha256"])
                candidate_source_by_key[key] = candidate_raw
                candidate_files.append({"root": root_name, "path": relative, "sha256": _sha(candidate_raw),
                                        "mode": candidate_mode, "size": len(candidate_raw)})
                if old_raw != candidate_raw or old_mode != candidate_mode:
                    payloads[key] = candidate_raw
                    changes.append(Change(root_name, relative, before_sha256, old_mode,
                                          _sha(candidate_raw), candidate_mode))
                    total_delta_bytes += len(candidate_raw)

        app_fd = root_fds["application"][0]
        old_contract, old_contract_mode = _read_relative(app_fd, _CONTRACT.as_posix())
        if (_sha(old_contract) != profile["contract_sha256"] or old_contract_mode != profile["contract_mode"]):
            _refuse()
        candidate_contract = git_show(revision, _CONTRACT.as_posix())
        if git_file_mode is None:
            _refuse()
        contract_mode = git_file_mode(revision, _CONTRACT.as_posix())
        if type(candidate_contract) is not bytes or not candidate_contract or contract_mode != 0o644:
            _refuse()
        load_host_secret_contract_bytes(candidate_contract)
        contract_key = ("application", _CONTRACT.as_posix())
        payloads[contract_key] = candidate_contract
        changes.append(Change("application", _CONTRACT.as_posix(), _sha(old_contract), old_contract_mode,
                              _sha(candidate_contract), 0o644))

        from app.ops.bws_installation_lifecycle import _public_launcher_bytes
        old_launcher = _public_launcher_bytes()
        if _sha(old_launcher) != profile["launcher_sha256"]:
            _refuse()
        launcher_source = git_show(revision, "scripts/postgres_deploy_service.py")
        launcher_source_mode = git_file_mode(revision, "scripts/postgres_deploy_service.py")
        if (type(launcher_source) is not bytes or not launcher_source.startswith(b"#!")
                or b"\x00" in launcher_source or b"\r" in launcher_source
                or launcher_source_mode != 0o755
                or candidate_file_data.get("scripts/postgres_deploy_service.py")
                != (launcher_source, launcher_source_mode)):
            _refuse()
        _require_source_only_launcher(launcher_source, require_preimport_reservation=True)
        _require_launcher_imports(launcher_source)
        if not candidate_source_by_key.get(("application", "app/ops/postgres_deploy_linux.py")):
            _refuse()
        if not candidate_source_by_key.get(("application", "app/ops/bws_installation_admission.py")):
            _refuse()
        deployment_candidate = candidate_source_by_key[("application", "app/ops/postgres_deploy_linux.py")]
        admission_candidate = candidate_source_by_key[("application", "app/ops/bws_installation_admission.py")]
        _require_cleanup_shared_reservation(deployment_candidate)
        _require_startup_reservation_release(deployment_candidate)
        _cleanup_skip_closure(admission_candidate)

        launcher_key = ("launcher", "yggdrasil-bws-deploy")
        launcher = launcher_source
        if launcher_key in payloads:
            _refuse()
        payloads[launcher_key] = launcher
        changes.append(Change("launcher", launcher_key[1], _sha(old_launcher), 0o755,
                              _sha(launcher), 0o755))
        total_delta_bytes += len(candidate_contract) + len(launcher)
        if total_delta_bytes > _MAX_TOTAL_SOURCE_BYTES or len(changes) > _MAX_MANIFEST_CHANGES:
            _refuse()
        changed_roots = {change.root for change in changes}
        if not changed_roots <= set(roots):
            _refuse()
        candidate_files.sort(key=lambda row: (str(row["root"]), str(row["path"])))
        return tuple(changes), payloads, {
            "backup_root": backup_root,
            "changed_roots": sorted(changed_roots),
            "candidate_files": candidate_files,
            "candidate_modules": [],
            "contract_mode": contract_mode,
            "launcher_key": launcher_key,
            "new_generation_sha256": _sha(json.dumps(
                [[change.root, change.path, change.after_sha256, change.mode] for change in changes],
                separators=(",", ":"),
            ).encode("ascii")),
        }
    except Exception:
        _refuse()
    finally:
        for _name, (_root_fd, opened) in reversed(tuple(root_fds.items())):
            for descriptor in reversed(opened):
                try:
                    os.close(descriptor)
                except OSError:
                    _refuse()

def _validate_request(channel: str, request: object) -> dict[str, str]:
    fields = {"action", "operation_id", "candidate_sha", "image_digest", "bundle_name"}
    if (channel not in {"dev", "test"} or type(request) is not dict or set(request) != fields
            or request.get("action") != "source-installation"):
        _refuse()
    operation_id = request.get("operation_id")
    candidate_sha = request.get("candidate_sha")
    image_digest = request.get("image_digest")
    bundle_name = request.get("bundle_name")
    try:
        if (type(operation_id) is not str or str(UUID(operation_id)) != operation_id
                or type(candidate_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None
                or type(image_digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
                or type(bundle_name) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", bundle_name) is None):
            _refuse()
    except Exception:
        _refuse()
    return {"operation_id": operation_id, "candidate_sha": candidate_sha,
            "image_digest": image_digest, "bundle_name": bundle_name}


def _git_environment() -> dict[str, str]:
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0"}


def _git_show(root: Path, revision: str, relative: str) -> bytes:
    if (re.fullmatch(r"[0-9a-f]{40}", revision) is None or not relative
            or relative.startswith("/") or any(part in {"", ".", ".."} for part in relative.split("/"))):
        _refuse()
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "show", revision + ":" + relative],
            env=_git_environment(), stdin=subprocess.DEVNULL,
            capture_output=True, check=False, timeout=20,
        )
        if (result.returncode != 0 or result.stderr or type(result.stdout) is not bytes
                or not result.stdout or len(result.stdout) > _MAX_SOURCE_BYTES):
            _refuse()
        return result.stdout
    except Exception:
        _refuse()


def _git_mode(root: Path, revision: str, relative: str) -> int:
    """Return one exact regular Git blob mode without materializing its source."""
    if (re.fullmatch(r"[0-9a-f]{40}", revision) is None or not relative
            or relative.startswith("/") or any(part in {"", ".", ".."} for part in relative.split("/"))):
        _refuse()
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "ls-tree", "-z", revision,
             "--", relative], env=_git_environment(), stdin=subprocess.DEVNULL,
            capture_output=True, check=False, timeout=20,
        )
        records = result.stdout.split(b"\0") if result.stdout else []
        if result.returncode != 0 or result.stderr or len(records) != 2 or records[-1] != b"":
            _refuse()
        header, separator, path = records[0].partition(b"\t")
        fields = header.split()
        if (not separator or path.decode("utf-8") != relative or len(fields) != 3
                or fields[1] != b"blob" or fields[0] not in {b"100644", b"100755"}):
            _refuse()
        return int(fields[0], 8) & 0o777
    except Exception:
        _refuse()


def _verify_candidate_checkout(root: Path, revision: str) -> None:
    """Require the caller checkout itself to be the clean exact candidate tree."""
    if not isinstance(root, Path) or not root.is_absolute() or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        _refuse()
    try:
        _root_identity(root)
        commands = (
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "rev-parse", "--show-toplevel"],
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "rev-parse", "HEAD"],
            ["git", "-c", "safe.directory=" + str(root), "-C", str(root), "status", "--porcelain=v1",
             "--untracked-files=all", "--", *_CANDIDATE_CLEAN_PATHS],
        )
        results = [subprocess.run(command, env=_git_environment(), stdin=subprocess.DEVNULL,
                                  capture_output=True, check=False, timeout=20)
                   for command in commands]
        if (any(result.returncode != 0 or result.stderr for result in results)
                or Path(os.fsdecode(results[0].stdout.rstrip(b"\n"))) != root
                or results[1].stdout.rstrip(b"\n").decode("ascii") != revision
                or results[2].stdout):
            _refuse()
        disk_files, disk_packages = _source_file_inventory({"application": root})
        git_files = _git_source_files(root, revision)
        expected = [{"root": "application", "path": path, "sha256": _sha(raw),
                     "mode": mode, "size": len(raw)} for path, (raw, mode) in sorted(git_files.items())]
        if disk_files != expected or disk_packages != {"application": ["app", "scripts"]}:
            _refuse()
    except Exception:
        _refuse()


def _verify_candidate(candidate_root: Path, request: dict[str, str]) -> None:
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    from app.ops.bws_installation_lifecycle import ENV as _LIFECYCLE_ENV
    from app.ops.postgres_deploy_linux import _command

    try:
        if not isinstance(candidate_root, Path) or not candidate_root.is_absolute():
            _refuse()
        completed = subprocess.run(
            ["git", "-c", "safe.directory=" + str(candidate_root), "-C", str(candidate_root),
             "cat-file", "-t", request["candidate_sha"]],
            env=_git_environment(), stdin=subprocess.DEVNULL,
            capture_output=True, check=False, timeout=20,
        )
        if (completed.returncode != 0 or completed.stderr or completed.stdout != b"commit\n"):
            _refuse()
        protocol = ast.parse(_git_show(
            candidate_root, request["candidate_sha"], "app/config/database.py",
        ))
        if not any(isinstance(node, ast.Assign) and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "DATABASE_FILE_CREDENTIAL_PROTOCOL"
                   and isinstance(node.value, ast.Constant) and node.value.value == 1
                   for node in protocol.body):
            _refuse()
        image_ref = IMAGE_REPOSITORY + "@" + request["image_digest"]
        rows = json.loads(_command(
            ["docker", "--host", "unix:///var/run/docker.sock", "image", "inspect", image_ref],
            env=_LIFECYCLE_ENV, timeout=30,
        ))
        if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict
                or rows[0].get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
                != request["candidate_sha"]
                or image_ref not in rows[0].get("RepoDigests", [])):
            _refuse()
    except Exception:
        _refuse()


def _require_writer_snapshot(value: object, request: dict[str, str]) -> _WriterSnapshot:
    """Require a well-formed current-state census, separate from the requested candidate."""
    if (type(value) is not _WriterSnapshot
            or value.channel != request.get("channel")
            or type(value.terminal_revision) is not str
            or re.fullmatch(r"[0-9a-f]{40}", value.terminal_revision) is None
            or type(value.terminal_image_digest) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value.terminal_image_digest) is None):
        _refuse()
    return value


def _current_writer_snapshot(effects: Any, request: dict[str, str]) -> _WriterSnapshot:
    """Capture the existing terminal deployment and writer census as before-state evidence."""
    from app.ops.native_source_admission import require_terminal_deployment

    try:
        if (type(request) is not dict or effects.config.channel != request.get("channel")
                or type(request.get("candidate_sha")) is not str
                or type(request.get("image_digest")) is not str):
            _refuse()
        require_terminal_deployment(effects)
        receipt = effects.config.journal.read()
        if (receipt is None or receipt.terminal_result not in {"committed", "aborted", "failed"}):
            _refuse()
        plan = effects.config.journal.bound_plan(receipt.operation_id)
        receipt.require_profile(plan)
        selected = plan.authority_cutover
        if (type(plan.revision) is not str
                or re.fullmatch(r"[0-9a-f]{40}", plan.revision) is None
                or type(plan.image_digest) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", plan.image_digest) is None):
            _refuse()
        if selected is not None:
            try:
                selected.validate()
            except Exception:
                _refuse_prebackup_gate("authority_cutover")
        snapshot = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=False, current_state=True,
        )
        if not effects.quiescent():
            _refuse()
        return _WriterSnapshot(
            channel=effects.config.channel,
            terminal_revision=plan.revision,
            terminal_image_digest=plan.image_digest,
            terminal_operation_id=receipt.operation_id,
            terminal_stage=receipt.stage,
            installed_fingerprint=snapshot.installed_fingerprint,
            execution_fingerprint=snapshot.execution_fingerprint,
            running_writers=snapshot.running_writers,
            existing_writers=snapshot.existing_writers,
            census_fingerprint=snapshot.census_fingerprint,
            retained_state_fingerprint=snapshot.retained_state_fingerprint,
            container_root=snapshot.container_root,
            vault_overlay=snapshot.vault_overlay,
        )
    except _PrebackupGateRefusal:
        raise
    except Exception:
        _refuse()


def _profile_response(channel: str, request: dict[str, Any]) -> dict[str, object]:
    from app.ops.postgres_deploy_linux import _rpc_via_supervisor

    if channel not in {"dev", "test"}:
        _refuse()

    profile_request: dict[str, Any] = {
        "action": "source-installation-profile",
        "operation_id": request["operation_id"],
        "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"],
    }
    caller_modules = request.get("_caller_source_modules")
    if caller_modules is not None:
        profile_request["caller_source_modules"] = caller_modules
    deadline = time.monotonic() + _PROFILE_READINESS_TIMEOUT_SECONDS
    while True:
        try:
            response = _rpc_via_supervisor(channel, profile_request)
            break
        except OSError as exc:
            # Only retry the read-only profile RPC when the fixed Unix socket
            # is not bound yet. A connected/refused handler response is final.
            if exc.errno not in {errno.ENOENT, errno.ECONNREFUSED}:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(_PROFILE_READINESS_POLL_SECONDS, remaining))
    if (type(response) is not dict or set(response) != {
            "source_installation_profile", "supervisor_idle", "exec_stop_post_no_write"}
            or response["supervisor_idle"] is not True
            or response["exec_stop_post_no_write"] is not True
            or type(response["source_installation_profile"]) is not dict):
        _refuse()
    profile = response["source_installation_profile"]
    if (profile.get("operation_id") != request["operation_id"]
            or profile.get("candidate_sha") != request["candidate_sha"]
            or profile.get("image_digest") != request["image_digest"]
            or profile.get("channel") != channel):
        _refuse()
    return profile


def _bind_source_inventory(profile: dict[str, object], config: Any) -> dict[str, object]:
    """Bind a complete local package inventory while retaining loaded-byte provenance."""
    roots = {"application": config.root, "control": _CONTROL_DIRECTORY}
    expected_v2 = {
        "schema", "source_loading_policy", "operation_id", "channel", "candidate_sha", "image_digest",
        "roots", "modules", "contract_sha256", "contract_mode", "launcher_sha256", "profile_sha256",
    }
    expected_v3 = expected_v2 | {"source_files", "source_packages"}
    if type(profile) is not dict:
        _refuse()
    value = dict(profile)
    if (value.get("schema") == _LEGACY_PROFILE_SCHEMA and set(value) == expected_v2):
        old_canonical = {key: item for key, item in value.items() if key != "profile_sha256"}
        if _sha(json.dumps(old_canonical, sort_keys=True, separators=(",", ":")).encode("ascii")) \
                != value.get("profile_sha256"):
            _refuse()
    elif value.get("schema") == _PROFILE_SCHEMA and set(value) == expected_v3:
        current_canonical = {key: item for key, item in value.items() if key != "profile_sha256"}
        if _sha(json.dumps(current_canonical, sort_keys=True, separators=(",", ":")).encode("ascii")) \
                != value.get("profile_sha256"):
            _refuse()
    else:
        _refuse()

    identities = value.get("roots")
    if type(identities) is not dict or set(identities) != {"application", "control"}:
        _refuse()
    for root_name, root_path in roots.items():
        if identities.get(root_name) != _root_identity(root_path):
            _refuse()
    source_files, source_packages = _source_file_inventory(roots)
    if value["schema"] == _PROFILE_SCHEMA:
        if value["source_files"] != source_files or value["source_packages"] != source_packages:
            _refuse()
    else:
        value["schema"] = _PROFILE_SCHEMA
        value["source_files"] = source_files
        value["source_packages"] = source_packages

    file_by_key = {(row["root"], row["path"]): row for row in source_files}
    modules = value.get("modules")
    if type(modules) is not list or not modules or len(modules) > _MAX_MODULES:
        _refuse()
    seen: set[str] = set()
    for module in modules:
        if type(module) is not dict or set(module) != {"module", "root", "path", "sha256", "mode"}:
            _refuse()
        row = cast(dict[str, object], module)
        source = file_by_key.get((row["root"], row["path"]))
        if (source is None or type(row["module"]) is not str
                or not _source_module_matches_path(cast(str, row["module"]), cast(str, row["path"]))
                or row["module"] in seen or row["sha256"] != source["sha256"]
                or row["mode"] != source["mode"]):
            _refuse()
        seen.add(cast(str, row["module"]))
    canonical = {key: item for key, item in value.items() if key != "profile_sha256"}
    value["profile_sha256"] = _sha(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("ascii"))
    if len(json.dumps(value, sort_keys=True, separators=(",", ":"))) > _MAX_PROFILE_BYTES:
        _refuse()
    return value


def _roots(config: Any, profile: dict[str, object]) -> tuple[dict[str, Any], Any]:
    from app.ops.bws_control_installation import Root

    identities = profile.get("roots")
    if type(identities) is not dict or set(identities) != {"application", "control"}:
        _refuse()
    values = {"application": config.root, "control": _CONTROL_DIRECTORY,
              "launcher": _LAUNCHER.parent}
    roots: dict[str, Any] = {}
    for name, path in values.items():
        if name in identities:
            identity = identities[name]
            if type(identity) is not dict or set(identity) != {"device", "inode", "uid", "gid", "mode"}:
                _refuse()
        else:
            identity = _root_identity(path)
        if any(type(identity[key]) is not int for key in ("device", "inode", "uid", "gid", "mode")):
            _refuse()
        roots[name] = Root(str(path), identity["device"], identity["inode"], identity["uid"],
                           identity["gid"], identity["mode"])
    source_rows = profile["source_files"]
    if type(source_rows) is not list:
        _refuse()
    source_roots = {
        cast(dict[str, object], row)["root"] for row in source_rows if type(row) is dict
    }
    active_roots = {"application", "launcher"} | source_roots
    if not active_roots <= set(roots):
        _refuse()
    roots = {name: root for name, root in roots.items() if name in active_roots}
    backup_identity = _root_identity(_BACKUP_DIRECTORY)
    backup_root = Root(str(_BACKUP_DIRECTORY), backup_identity["device"], backup_identity["inode"],
                       backup_identity["uid"], backup_identity["gid"], backup_identity["mode"])
    return roots, backup_root


def _candidate_profile(
    profile: dict[str, object], payloads: dict[tuple[str, str], bytes], manifest_proof: dict[str, Any],
) -> dict[str, object]:
    candidate_modules = manifest_proof.get("candidate_modules")
    candidate_files = manifest_proof.get("candidate_files")
    if (type(candidate_modules) is not list or type(candidate_files) is not list or not candidate_files):
        _refuse()
    expected: dict[str, object] = {
        "schema": _PROFILE_SCHEMA,
        "source_loading_policy": _SOURCE_LOADING_POLICY,
        "operation_id": profile["operation_id"],
        "channel": profile["channel"],
        "candidate_sha": profile["candidate_sha"],
        "image_digest": profile["image_digest"],
        "roots": profile["roots"],
        "modules": candidate_modules,
        "source_files": candidate_files,
        "source_packages": profile["source_packages"],
    }
    contract = payloads.get(("application", _CONTRACT.as_posix()))
    launcher = payloads.get(("launcher", "yggdrasil-bws-deploy"))
    contract_mode = manifest_proof.get("contract_mode")
    if (type(contract) is not bytes or type(launcher) is not bytes
            or contract_mode != 0o644):
        _refuse()
    expected["contract_sha256"] = _sha(contract)
    expected["contract_mode"] = contract_mode
    expected["launcher_sha256"] = _sha(launcher)
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("ascii")
    expected["profile_sha256"] = _sha(canonical)
    return expected


def _generation_sha(profile: dict[str, object], service_token: str, contract: object) -> str:
    if type(service_token) is not str or re.fullmatch(r"[0-9a-f]{64}", service_token) is None:
        _refuse()
    stable_profile = {key: value for key, value in profile.items()
                      if key not in {"modules", "profile_sha256"}}
    value = {"schema": "agentic-pkm.bws-runtime-generation.v1",
             "operation_id": profile["operation_id"], "channel": profile["channel"],
             "candidate_sha": profile["candidate_sha"], "image_digest": profile["image_digest"],
             "source_state_sha256": _sha(json.dumps(
                 stable_profile, sort_keys=True, separators=(",", ":"),
             ).encode("ascii")), "service_token_sha256": service_token,
             "unit_contract": contract}
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii"))


def _backup_manifest_sha(handle: Any) -> str | None:
    try:
        saved = handle._backup_files.get("manifest.json")
        if saved is None or type(saved.data) is not bytes:
            return None
        return _sha(saved.data)
    except Exception:
        return None


def _root_projection(root: Any) -> dict[str, object]:
    return {"path": root.path, "device": root.device, "inode": root.inode,
            "uid": root.uid, "gid": root.gid, "mode": root.mode}


def _receipt(
    request: dict[str, str], *, status: str, old_generation: str | None,
    new_generation: str | None, backup_manifest: str | None,
    prebackup_gate: str | None = None,
) -> dict[str, object]:
    if status == "refused_before_backup":
        if type(prebackup_gate) is not str or prebackup_gate not in _PREBACKUP_REFUSAL_GATES:
            _refuse()
    elif prebackup_gate is not None:
        _refuse()
    receipt: dict[str, object] = {
        "schema": "agentic-pkm.bws-source-installation-receipt.v1",
        "operation_id": request["operation_id"],
        "channel": request["channel"],
        "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"],
        "old_generation_sha256": old_generation,
        "new_generation_sha256": new_generation,
        "backup_manifest_sha256": backup_manifest,
        "status": status,
    }
    if status == "refused_before_backup":
        receipt["prebackup_gate"] = prebackup_gate
    return receipt


def _retire_channel_owner(effects: Any, owner: dict[str, str]) -> None:
    with effects.failed_reconciliation_lock(expected_owner=owner) as handle:
        effects.retire_reconciled_channel_lock(handle, expected_owner=owner)


def _profile_matches(actual: dict[str, object], expected: dict[str, object]) -> bool:
    if type(actual) is not dict or type(expected) is not dict:
        return False
    if expected.get("modules") != []:
        return actual == expected
    if set(actual) != set(expected):
        return False
    actual_canonical = {key: value for key, value in actual.items() if key != "profile_sha256"}
    if (type(actual.get("profile_sha256")) is not str
            or _sha(json.dumps(actual_canonical, sort_keys=True, separators=(",", ":")).encode("ascii"))
            != actual["profile_sha256"]):
        return False
    stable_actual = {key: value for key, value in actual.items() if key not in {"modules", "profile_sha256"}}
    stable_expected = {key: value for key, value in expected.items() if key not in {"modules", "profile_sha256"}}
    if stable_actual != stable_expected:
        return False
    modules = actual.get("modules")
    files = actual.get("source_files")
    if (type(modules) is not list or not modules or len(modules) > _MAX_MODULES
            or type(files) is not list):
        return False
    by_key = {(row.get("root"), row.get("path")): row for row in files if type(row) is dict}
    seen: set[str] = set()
    for module in modules:
        if type(module) is not dict or set(module) != {"module", "root", "path", "sha256", "mode"}:
            return False
        name, root, path = module["module"], module["root"], module["path"]
        source = by_key.get((root, path))
        if (type(name) is not str or name in seen or type(root) is not str or type(path) is not str
                or type(source) is not dict or source.get("sha256") != module["sha256"]
                or source.get("mode") != module["mode"]
                or not _source_module_matches_path(name, path)):
            return False
        seen.add(name)
    return True


def _require_owner_launcher_profile(admission: Any, profile: dict[str, object]) -> None:
    """Bind the initial remote profile to the launcher that admitted this caller."""
    caller = getattr(admission, "caller_identity", None)
    if (type(caller) is not dict or type(caller.get("launcher_sha256")) is not str
            or profile.get("launcher_sha256") != caller["launcher_sha256"]):
        _refuse()


class _HandleCloseUncertain(RuntimeError):
    """A same-handle close failed, so no terminal transaction receipt is admissible."""


def _restore_from_handle(
    *, admission: Any, service: Any, handle: Any, old_generation: str,
    request: dict[str, str], ports: Any,
) -> tuple[str, str | None]:
    """Compensate once through the prepared handle and keep an unqualified old runtime stopped."""
    if type(old_generation) is not str or re.fullmatch(r"[0-9a-f]{64}", old_generation) is None:
        _refuse()
    if service.phase == "start_requested":
        service.stop_failed_start_if_exact()
    elif service.phase == "new_kernel_checked":
        service.stop_new()
    elif service.phase not in {"stopped_checked", "new_stopped_checked"}:
        _refuse()
    service.require_stopped()
    admission.revoke_service_start()
    if handle.state in {"prepared", "partially_installed", "installed"}:
        ports.compensate(handle)
    if handle.compensation_attempted is not True or handle.compensation_complete is not True:
        try:
            handle.close()
        except Exception as exc:
            raise _HandleCloseUncertain("installation handle close failed") from exc
        return "unknown", None
    # The legacy service supplied no loaded-source profile, so its runtime
    # cannot be qualified for restart even after its disk bytes are restored.
    try:
        handle.close()
    except Exception as exc:
        raise _HandleCloseUncertain("installation handle close failed") from exc
    return "compensated_stopped", None


class _NativePorts:
    """Fixed production bindings for this one DEV/TEST source-installation path."""

    def __init__(self) -> None:
        self._config: Any = None
        self._caller_profile_sent = False
        self._caller_source_modules: list[dict[str, object]] | None = None
        caller_root = getattr(sys, "_yggdrasil_bws_candidate_checkout", None)
        self.caller_root = Path(caller_root) if type(caller_root) is str else None

    def configuration(self, channel: str) -> Any:
        from app.ops.postgres_deploy_linux import LinuxConfig
        self._config = LinuxConfig.load(channel)
        return self._config

    def effects(self, config: Any) -> Any:
        from app.ops.postgres_deploy_linux import LinuxEffects
        self._config = config
        return LinuxEffects(config)

    def admission(self, channel: str, request: dict[str, str]) -> Any:
        from app.ops.bws_installation_admission import installation_admission
        if self.caller_root is None:
            _refuse()
        return installation_admission(
            channel, mode="exclusive", operation_id=request["operation_id"],
            candidate_sha=request["candidate_sha"], image_digest=request["image_digest"],
            bundle_name=request["bundle_name"], caller_checkout=self.caller_root,
        )

    def verify_caller_checkout(self, request: dict[str, str]) -> None:
        if self.caller_root is None:
            _refuse()
        from app.ops.bws_installation_admission import require_verified_candidate_entrypoint
        require_verified_candidate_entrypoint(self.caller_root, request["candidate_sha"])
        _verify_candidate_checkout(self.caller_root, request["candidate_sha"])

    def verify_candidate(self, _config: Any, request: dict[str, str]) -> None:
        self.verify_caller_checkout(request)
        if self.caller_root is None:
            _refuse()
        _verify_candidate(self.caller_root, request)

    def verify_caller_sources(self, request: dict[str, str]) -> None:
        """Bind already imported caller modules to the exact candidate before any backup write."""
        if self.caller_root is None or self._config is None:
            _refuse()
        _verify_candidate_checkout(self.caller_root, request["candidate_sha"])
        self._caller_source_modules = _source_modules(
            self._config, {"application": self.caller_root, "control": _CONTROL_DIRECTORY},
        )

    def preflight(self, effects: Any, request: dict[str, str]) -> _WriterSnapshot:
        return _current_writer_snapshot(effects, request)

    def cleanup_callers(self, channel: str) -> None:
        from app.ops.bws_installation_lifecycle import require_no_cleanup_callers
        require_no_cleanup_callers(channel, caller_pid=os.getpid())

    def old_state(self, config: Any, request: dict[str, str]) -> dict[str, object]:
        return _old_disk_state(config, request)

    def profile(self, channel: str, request: dict[str, Any]) -> dict[str, object]:
        selected = request
        if not self._caller_profile_sent:
            if (self._config is None or self._config.channel != channel or self.caller_root is None
                    or self._caller_source_modules is None):
                _refuse()
            selected = {**request, "_caller_source_modules": self._caller_source_modules}
            self._caller_profile_sent = True
        return _bind_source_inventory(_profile_response(channel, selected), self._config)

    def source_manifest(self, profile: dict[str, object], config: Any, request: dict[str, str],
                        roots: dict[str, Any], backup_root: Any) -> tuple[tuple[Any, ...], dict[tuple[str, str], bytes], dict[str, Any]]:
        if self.caller_root is None:
            _refuse()
        return candidate_manifest(
            profile, revision=request["candidate_sha"], roots=roots, backup_root=backup_root,
            git_show=lambda revision, path: _git_show(self.caller_root, revision, path),
            git_source_files=lambda revision: _git_source_files(self.caller_root, revision),
            git_file_mode=lambda revision, path: _git_mode(self.caller_root, revision, path),
        )

    def roots(self, config: Any, profile: dict[str, object]) -> tuple[dict[str, Any], Any]:
        return _roots(config, profile)

    def service(self, channel: str) -> Any:
        from app.ops.bws_installation_lifecycle import FixedBwsService
        return FixedBwsService(unit=f"yggdrasil-bws-deploy@{channel}.service", channel=channel)

    def prepare(self, roots: dict[str, Any], changes: tuple[Any, ...],
                payloads: dict[tuple[str, str], bytes], backup_root: Any, bundle_name: str) -> Any:
        from app.ops.bws_control_installation import prepare_public_files
        return prepare_public_files(roots=roots, changes=changes, payloads=payloads,
                                    backup_root=backup_root, bundle_name=bundle_name)

    def apply(self, handle: Any) -> Any:
        from app.ops.bws_control_installation import apply_public_files
        return apply_public_files(handle)

    def apply_targets(self, handle: Any, target_keys: tuple[tuple[str, str], ...]) -> Any:
        from app.ops.bws_control_installation import apply_public_files
        return apply_public_files(handle, target_keys=target_keys)

    def compensate(self, handle: Any) -> Any:
        from app.ops.bws_control_installation import compensate_public_files
        return compensate_public_files(handle)

    def retire(self, effects: Any, owner: dict[str, str]) -> None:
        _retire_channel_owner(effects, owner)


def _execute_source_installation(channel: str, raw_request: object, ports: Any) -> dict[str, object]:
    request = _validate_request(channel, raw_request)
    request["channel"] = channel
    verify_checkout = getattr(ports, "verify_caller_checkout", None)
    if callable(verify_checkout):
        verify_checkout(request)
    config = ports.configuration(channel)
    if config.channel != channel:
        _refuse()
    effects = ports.effects(config)
    effects.operation_id = request["operation_id"]
    channel_owner = {
        "kind": "bws-source-installation", "channel": channel,
        "operation_id": request["operation_id"],
        "candidate_sha": request["candidate_sha"], "image_digest": request["image_digest"],
    }
    expected_channel_owner = (json.dumps(channel_owner, sort_keys=True) + "\n").encode()
    receipt: dict[str, object] | None = None
    lock_owned = False
    terminal_safe = False
    terminal_receipt_attempted = False
    terminal_receipt_published = False
    recovery_attempted = False
    handle_close_uncertain = False
    handle = None
    service = None
    phase = "before_backup"
    old_generation: str | None = None
    proposed_generation: str | None = None
    final_generation: str | None = None
    backup_manifest: str | None = None
    prebackup_gate = "channel_lock_entry"

    with ports.admission(channel, request) as admission:
        def publish_terminal_receipt() -> None:
            nonlocal terminal_receipt_attempted, terminal_receipt_published
            if receipt is None:
                _refuse()
            terminal_receipt_attempted = True
            admission.complete(receipt)
            terminal_receipt_published = True

        def recover_failure(*, publish: bool, failure: BaseException | None = None) -> bool:
            nonlocal phase, receipt, terminal_safe, handle, recovery_attempted
            nonlocal handle_close_uncertain
            recovery_attempted = True
            start_revocation_uncertain = False
            try:
                admission.revoke_service_start()
            except Exception:
                # Failure to clear a one-use start permit forbids a terminal
                # receipt, but it must not suppress an exact-generation stop.
                # Quiesce any already authenticated process first, then leave
                # the owner unresolved when permit state remains uncertain.
                start_revocation_uncertain = True
            if phase == "launcher_staged" and service is not None and handle is not None:
                try:
                    if not (handle.compensation_attempted is True
                            and handle.compensation_complete is True):
                        ports.compensate(handle)
                    if handle.compensation_complete is not True:
                        return False
                    service.require_old_kernel(launcher_content=service.launcher_before)
                    try:
                        handle.close()
                    except Exception:
                        handle_close_uncertain = True
                        return False
                    handle = None
                    phase = "qualified"
                except Exception:
                    # A partial launcher stage must be proved restored before
                    # either a terminal refusal or another service effect.
                    return False
            if service is not None:
                # A profile, census, or runtime-close failure can occur after
                # a generation has already been authenticated. Stop that exact
                # generation whenever its lifecycle token still permits it;
                # unknown state must not leave a known process serving.
                if service.phase == "start_requested":
                    try:
                        service.stop_failed_start_if_exact()
                    except Exception:
                        pass
                    phase = "unknown"
                elif service.phase == "new_kernel_checked":
                    try:
                        service.stop_new()
                    except Exception:
                        pass
                    phase = "unknown"
                elif service.phase == "restore_start_requested":
                    try:
                        service.require_restored_old_kernel()
                        service.stop_restored_old()
                    except Exception:
                        pass
                    phase = "unknown"
                elif service.phase == "old_kernel_restored":
                    try:
                        service.stop_restored_old()
                    except Exception:
                        pass
                    phase = "unknown"
                if (service.runtime_context_started and not service.runtime_close_completed
                        and phase in {"qualified", "prepared", "stopped", "new_kernel", "new_stopped",
                                      "compensated_stopped"}):
                    phase = "unknown"
            if handle is not None and not handle_close_uncertain:
                try:
                    handle.close()
                except Exception:
                    handle_close_uncertain = True
            if start_revocation_uncertain or handle_close_uncertain:
                # Preserve the channel owner if either the one-use start grant
                # or same-process backup handle has unknown lifetime.
                return False
            if phase == "before_backup" and receipt is None:
                refusal_gate = (failure.gate if isinstance(failure, _PrebackupGateRefusal)
                                else prebackup_gate)
                receipt = _receipt(request, status="refused_before_backup", old_generation=None,
                                   new_generation=None, backup_manifest=None,
                                   prebackup_gate=refusal_gate)
                terminal_safe = lock_owned
            elif (phase in {"qualified", "prepared"} and receipt is None
                    and (service is None or not service.runtime_context_started
                         or service.runtime_close_completed)):
                receipt = _receipt(request, status="refused_before_stop", old_generation=old_generation,
                                   new_generation=proposed_generation, backup_manifest=backup_manifest)
                terminal_safe = lock_owned
            elif (phase in {"stopped", "new_kernel", "new_stopped", "new_kernel_closed",
                            "restored_old_closed", "unknown", "compensated_stopped"}
                    and receipt is None and old_generation and proposed_generation and backup_manifest):
                if (service is None or service.phase not in {
                        "stopped_checked", "new_stopped_checked", "restored_stopped_checked",
                }):
                    # Never publish a terminal unknown/stopped receipt while a
                    # service may still be live. Leave the persistent operation
                    # marker unresolved so an owner can investigate without
                    # this transaction claiming that quiescence was proved.
                    return False
                try:
                    service.require_stopped()
                except Exception:
                    return False
                if phase != "compensated_stopped":
                    phase = "unknown"
                status = "compensated_stopped" if phase == "compensated_stopped" else "unknown"
                receipt = _receipt(request, status=status, old_generation=old_generation,
                                   new_generation=proposed_generation, backup_manifest=backup_manifest)
            if receipt is None:
                return False
            if publish and not terminal_receipt_published:
                publish_terminal_receipt()
            return True

        prebackup_gate = "channel_lock_entry"
        try:
            with effects.channel_lock(journal=config.journal, owner_marker=channel_owner,
                                      retire_terminal=False):
                lock_owned = True
                try:
                    prebackup_gate = "channel_owner_check"
                    if effects.channel_lock_owner() != expected_channel_owner:
                        _refuse()
                    # The owner marker makes later old ExecStopPost invocations a
                    # no-write fast path. Refuse an invocation that passed that
                    # check just before this owner acquired its lock.
                    prebackup_gate = "caller_census"
                    ports.cleanup_callers(channel)
                    prebackup_gate = "current_writer_snapshot"
                    baseline = _require_writer_snapshot(ports.preflight(effects, request), request)
                    prebackup_gate = "candidate_verification"
                    ports.verify_candidate(config, request)
                    prebackup_gate = "old_disk_state"
                    old_state = ports.old_state(config, request)
                    prebackup_gate = "owner_launcher_profile"
                    _require_owner_launcher_profile(admission, old_state)
                    prebackup_gate = "backup_roots"
                    roots, backup_root = ports.roots(config, old_state)
                    prebackup_gate = "source_manifest"
                    changes, payloads, manifest_proof = ports.source_manifest(
                        old_state, config, request, roots, backup_root,
                    )
                    prebackup_gate = "candidate_profile"
                    candidate_profile = _candidate_profile(old_state, payloads, manifest_proof)
                    roots = {name: root for name, root in roots.items()
                             if name in manifest_proof["changed_roots"]}
                    prebackup_gate = "old_kernel_qualification"
                    service = ports.service(channel)
                    launcher = payloads[("launcher", "yggdrasil-bws-deploy")]
                    launcher_content = {"sha256": _sha(launcher),
                                        "base64": base64.b64encode(launcher).decode("ascii")}
                    app_identity = old_state["roots"]["application"]
                    control_identity = old_state["roots"]["control"]
                    with service.retained_runtime():
                        service.qualify_old(
                            application_root={"path": str(config.root), **app_identity},
                            control_root={"path": str(_CONTROL_DIRECTORY), **control_identity},
                            launcher_content=launcher_content,
                        )
                        prebackup_gate = "qualified_writer_snapshot"
                        current = _require_writer_snapshot(ports.preflight(effects, request), request)
                        if service.phase != "qualified" or current != baseline:
                            _refuse()
                        prebackup_gate = "generation_qualification"
                        old_generation = _generation_sha(old_state, service.old_token, service.contract)
                        proposed_generation = _generation_sha(
                            candidate_profile, manifest_proof["new_generation_sha256"], service.contract,
                        )
                        phase = "qualified"
                        try:
                            verify_caller_sources = getattr(ports, "verify_caller_sources", None)
                            if callable(verify_caller_sources):
                                verify_caller_sources(request)
                            handle = ports.prepare(
                                roots, changes, payloads, backup_root, request["bundle_name"],
                            )
                        except Exception as exc:
                            handle = getattr(exc, "installation", None)
                            backup_manifest = _backup_manifest_sha(handle) if handle is not None else None
                            raise
                        phase = "prepared"
                        backup_manifest = _backup_manifest_sha(handle)
                        if backup_manifest is None:
                            _refuse()
                        launcher_keys = tuple(key for key in payloads if key[0] == "launcher")
                        source_keys = tuple(key for key in payloads if key[0] != "launcher")
                        if launcher_keys != (("launcher", "yggdrasil-bws-deploy"),) or not source_keys:
                            _refuse()
                        phase = "launcher_staged"
                        ports.apply_targets(handle, launcher_keys)
                        service.require_old_kernel(launcher_content=payloads[launcher_keys[0]])
                        ports.cleanup_callers(channel)
                        staged_snapshot = _require_writer_snapshot(ports.preflight(effects, request), request)
                        if staged_snapshot != baseline:
                            _refuse()
                        try:
                            service.stop_old()
                        except Exception:
                            if service.phase == "qualified":
                                raise
                            phase = "unknown"
                            raise
                        phase = "stopped"
                        try:
                            ports.apply_targets(handle, source_keys)
                            if proposed_generation is None:
                                _refuse()
                            admission.authorize_service_start("candidate", proposed_generation)
                            service.start_new()
                            admission.confirm_service_start_consumed("candidate", proposed_generation)
                            try:
                                new_token = service.require_new_kernel()
                            except Exception:
                                service.stop_failed_start_if_exact()
                                raise
                            phase = "new_kernel"
                            observed = ports.profile(channel, request)
                            if not _profile_matches(observed, candidate_profile):
                                service.stop_new()
                                phase = "new_stopped"
                                raise RuntimeError("candidate_generation_mismatch") from None
                            final_generation = _generation_sha(observed, new_token, service.contract)
                            try:
                                handle.close()
                            except Exception as exc:
                                handle_close_uncertain = True
                                raise _HandleCloseUncertain(
                                    "installation handle close failed",
                                ) from exc
                            handle = None
                            observed_after_close = ports.profile(channel, request)
                            if not _profile_matches(observed_after_close, candidate_profile):
                                service.stop_new()
                                phase = "new_stopped"
                                raise RuntimeError("candidate_generation_mismatch") from None
                            phase = "new_kernel_closed"
                        except Exception as exc:
                            if isinstance(exc, _HandleCloseUncertain):
                                handle_close_uncertain = True
                            restored = False
                            if handle is not None and not handle_close_uncertain and service.phase in {
                                    "start_requested", "new_kernel_checked", "stopped_checked", "new_stopped_checked"}:
                                try:
                                    outcome, restored_token = _restore_from_handle(
                                        admission=admission, service=service, handle=handle,
                                        old_generation=old_generation,
                                        request=request, ports=ports,
                                    )
                                    del restored_token
                                    phase = outcome
                                    handle = None
                                    restored = outcome in {"compensated_stopped", "unknown"}
                                except Exception as restore_exc:
                                    if isinstance(restore_exc, _HandleCloseUncertain):
                                        handle_close_uncertain = True
                                    if handle is not None and not handle_close_uncertain:
                                        try:
                                            handle.close()
                                        except Exception:
                                            handle_close_uncertain = True
                                    phase = "unknown"
                            if not restored:
                                raise
                    if phase == "new_kernel_closed":
                        expected_profile = candidate_profile
                        try:
                            final_profile = ports.profile(channel, request)
                        except Exception:
                            try:
                                service.stop_new()
                            except Exception:
                                pass
                            phase = "unknown"
                            raise
                        if not _profile_matches(final_profile, expected_profile):
                            try:
                                service.stop_new()
                            except Exception:
                                pass
                            phase = "unknown"
                            _refuse()
                        # Re-read the complete protected writer/retained-state
                        # census after both the public-file handle and the
                        # qualified runtime context have closed. Any drift
                        # stops the exact generation and preserves the owner.
                        final_snapshot = _require_writer_snapshot(
                            ports.preflight(effects, request), request,
                        )
                        if final_snapshot != baseline:
                            try:
                                service.stop_new()
                            except Exception:
                                pass
                            phase = "unknown"
                            _refuse()
                    if phase == "new_kernel_closed":
                        try:
                            service.require_same_new_kernel()
                        except Exception:
                            service.stop_new()
                            phase = "unknown"
                            raise
                        status = "installed"
                        terminal_safe = True
                        receipt = _receipt(
                            request, status=status, old_generation=old_generation,
                            new_generation=final_generation, backup_manifest=backup_manifest,
                        )
                    elif phase == "compensated_stopped":
                        status = "compensated_stopped"
                        receipt = _receipt(
                            request, status=status, old_generation=old_generation,
                            new_generation=proposed_generation, backup_manifest=backup_manifest,
                        )
                    elif phase == "qualified" or phase == "prepared":
                        status = "refused_before_stop"
                        terminal_safe = True
                        receipt = _receipt(
                            request, status=status, old_generation=old_generation,
                            new_generation=proposed_generation, backup_manifest=backup_manifest,
                        )
                    elif phase == "unknown":
                        status = "unknown"
                        receipt = _receipt(
                            request, status=status, old_generation=old_generation,
                            new_generation=proposed_generation, backup_manifest=backup_manifest,
                        )
                    else:
                        _refuse()
                except Exception as exc:
                    if not recover_failure(publish=True, failure=exc):
                        raise
                if receipt is None:
                    _refuse()
                if not terminal_receipt_published:
                    publish_terminal_receipt()
            if terminal_safe and lock_owned:
                # Publish the operation receipt before releasing the channel owner.
                # Retirement happens afterward while the exclusive installation admission
                # still fences ordinary callers.
                ports.retire(effects, channel_owner)
                lock_owned = False
            return {"source_installation": receipt}
        except Exception as exc:
            if terminal_receipt_published or terminal_receipt_attempted:
                # An attempted durable publication may have reached disk. Preserve the
                # verified runtime and owner evidence; never stop or replay after it.
                raise
            if recovery_attempted:
                raise
            # If channel-lock acquisition failed before yielding, no transaction effect ran.
            # Record only a no-effect refusal under installation admission; preserve any
            # partial lock-path evidence left by a failed context-manager entry.
            if not recover_failure(publish=True, failure=exc):
                raise
            if terminal_safe and lock_owned:
                ports.retire(effects, channel_owner)
                lock_owned = False
            return {"source_installation": receipt}

def run_source_installation(channel: str, request: object) -> dict[str, object]:
    """Execute one fixed DEV/TEST source install through existing BWS ownership."""
    return _execute_source_installation(channel, request, _NativePorts())
