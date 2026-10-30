from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import uuid
from contextlib import contextmanager, nullcontext

import pytest

from app.ops.bws_control_installation import Change, Root
from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401

from app.ops import (
    bws_installation_lifecycle,
    bws_installation_transaction as transaction,
    host_secret_contract,
)

_DEPLOYMENT_SOURCE = (
    "from contextlib import ExitStack\n"
    "def main(args):\n"
    "    admissions = ExitStack()\n"
    "    try:\n"
    "        if args.action == 'serve':\n"
    "            serve(args)\n"
    "        if args.action == 'cleanup':\n"
    "            from app.ops.bws_installation_admission import cleanup_must_skip\n"
    "            if args.channel in {'dev', 'test'}:\n"
    "                from app.ops.bws_installation_admission import shared_caller_reservation\n"
    "                if cleanup_must_skip(args.channel):\n"
    "                    return 0\n"
    "                try:\n"
    "                    admissions.enter_context(shared_caller_reservation(args.channel))\n"
    "                except Exception:\n"
    "                    return 0\n"
    "            return 1\n"
    "    finally:\n"
    "        admissions.close()\n"
    "def serve(config):\n"
    "    def release_startup_reservation():\n"
    "        callback = getattr(sys, '_yggdrasil_bws_startup_reservation_release', None)\n"
    "        if callback is not None:\n"
    "            callback()\n"
    "    class Handler:\n"
    "        def handle(self, request):\n"
    "            if request.get('action') == 'source-installation-profile':\n"
    "                return 1\n"
    "            else:\n"
    "                from app.ops.bws_installation_admission import shared_caller_reservation\n"
    "                with shared_caller_reservation('dev'):\n"
    "                    return 1\n"
    "    try:\n"
    "        with Server() as server:\n"
    "            release_startup_reservation()\n"
    "            server.serve_forever()\n"
    "    finally:\n"
    "        release_startup_reservation()\n"
)
_OLD_DEPLOYMENT_SOURCE = (
    "from contextlib import ExitStack\n"
    "def main(args):\n"
    "    admissions = ExitStack()\n"
    "    try:\n"
    "        if args.action == 'serve':\n"
    "            serve(args)\n"
    "        if args.action == 'cleanup':\n"
    "            from app.ops.bws_installation_admission import cleanup_must_skip\n"
    "            if cleanup_must_skip(args.channel):\n"
    "                return 0\n"
    "            return 1\n"
    "    finally:\n"
    "        admissions.close()\n"
    "def serve(config):\n"
    "    def release_startup_reservation():\n"
    "        return None\n"
    "    class Handler:\n"
    "        def handle(self, request):\n"
    "            if request.get('action') == 'source-installation-profile':\n"
    "                return 1\n"
    "            else:\n"
    "                from app.ops.bws_installation_admission import shared_caller_reservation\n"
    "                with shared_caller_reservation('dev'):\n"
    "                    return 1\n"
    "    try:\n"
    "        with Server() as server:\n"
    "            release_startup_reservation()\n"
    "            server.serve_forever()\n"
    "    finally:\n"
    "        release_startup_reservation()\n"
)
_ADMISSION_SOURCE = (
    "from contextlib import contextmanager\n"
    "def cleanup_must_skip(channel):\n"
    "    if channel not in {'dev', 'test'}:\n"
    "        return False\n"
    "    return True\n"
    "\n"
    "@contextmanager\n"
    "def shared_caller_reservation(channel):\n"
    "    if channel:\n"
    "        yield\n"
)
_SOURCE_ONLY_LAUNCHER = (
    b"#!/opt/yggdrasil/bws-deploy-runtime/bin/python3\n"
    b"import sys\n"
    b"_SOURCE_PROVENANCE_POLICY = 'bws-source-bytes-v2'\n"
    b"_SOURCE_HASH_ATTRIBUTE = '__yggdrasil_source_sha256__'\n"
    b"_SOURCE_PACKAGES = ('app', 'scripts')\n"
    b"_STARTUP_RELEASE_ATTRIBUTE = '_yggdrasil_bws_startup_reservation_release'\n"
    b"def _install_source_loader(root):\n"
    b"    class SourceBoundLoader:\n"
    b"        def get_code(self):\n"
    b"            return self.source_to_code(b'', '')\n"
    b"        def exec_module(self, module):\n"
    b"            code = self.get_code(module.__name__)\n"
    b"            source_sha256 = getattr(self, \"loaded_source_sha256\", None)\n"
    b"            if (type(source_sha256) is not str or len(source_sha256) != 64\n"
    b"                    or any(character not in \"0123456789abcdef\" for character in source_sha256)):\n"
    b"                raise ImportError(\"BWS source provenance unavailable\")\n"
    b"            exec(code, module.__dict__)\n"
    b"            module.__dict__[_SOURCE_HASH_ATTRIBUTE] = source_sha256\n"
    b"    class SourceBoundFinder:\n"
    b"        def find_spec(self, fullname, path=None, target=None):\n"
    b"            if fullname.partition('.')[0] not in _SOURCE_PACKAGES:\n"
    b"                return None\n"
    b"    sys.meta_path.insert(2, SourceBoundFinder())\n"
    b"def _require_live_installation_caller(caller, channel):\n"
    b"    return None\n"
    b"def _require_exclusive_lock(descriptor, identity):\n"
    b"    return None\n"
    b"def _require_active_channel_owner(parent, channel, owner_raw):\n"
    b"    return None\n"
    b"def _consume_start_authorization(parent, channel, global_fd, identity, owner_raw):\n"
    b"    _require_live_installation_caller({}, channel)\n"
    b"    _require_exclusive_lock(global_fd, identity)\n"
    b"    _require_active_channel_owner(parent, channel, owner_raw)\n"
    b"def _preimport_reservation(channel, action):\n"
    b"    _consume_start_authorization(None, channel, None, None, None)\n"
    b"    return _PreimportReservation(None, authorized_start=True)\n"
    b"def _dispatch(root, channel, arguments):\n"
    b"    reservation = _preimport_reservation(channel, arguments[0])\n"
    b"    if reservation.skip_cleanup:\n"
    b"        return 0\n"
    b"    _install_source_loader(root)\n"
    b"    if arguments[0] in {'cleanup', 'serve'} and channel in {'dev', 'test'}:\n"
    b"        import importlib\n"
    b"        admission = importlib.import_module('app.ops.bws_installation_admission')\n"
    b"        if arguments[0] == 'serve' and not reservation.authorized_start:\n"
    b"            with admission.shared_caller_reservation(channel):\n"
    b"                pass\n"
    b"    from app.ops.postgres_deploy_linux import main\n"
    b"    if arguments[0] == 'serve':\n"
    b"        setattr(sys, _STARTUP_RELEASE_ATTRIBUTE, reservation.release)\n"
    b"    if arguments[0] == 'rpc':\n"
    b"        reservation.release()\n"
    b"    return main(arguments)\n"
    b"def run():\n"
    b"    try:\n"
    b"        sys.pycache_prefix = '/dev/null'\n"
    b"        sys.dont_write_bytecode = True\n"
    b"        return _dispatch(root, sys.argv[2], sys.argv[1:])\n"
    b"    except Exception:\n"
    b"        return 78\n"
)
_LEGACY_SOURCE_ONLY_LAUNCHER = (
    b"#!/opt/yggdrasil/bws-deploy-runtime/bin/python3\n"
    b"import sys\n"
    b"_SOURCE_PROVENANCE_POLICY = 'bws-source-bytes-v2'\n"
    b"_SOURCE_HASH_ATTRIBUTE = '__yggdrasil_source_sha256__'\n"
    b"_SOURCE_PACKAGES = ('app', 'scripts')\n"
    b"def _install_source_loader(root):\n"
    b"    class SourceBoundLoader:\n"
    b"        def get_code(self):\n"
    b"            return self.source_to_code(b'', '')\n"
    b"    class SourceBoundFinder:\n"
    b"        def find_spec(self, fullname, path=None, target=None):\n"
    b"            if fullname.partition('.')[0] not in _SOURCE_PACKAGES:\n"
    b"                return None\n"
    b"    sys.meta_path.insert(2, SourceBoundFinder())\n"
    b"def run():\n"
    b"    try:\n"
    b"        sys.pycache_prefix = '/dev/null'\n"
    b"        sys.dont_write_bytecode = True\n"
    b"        _install_source_loader(root)\n"
    b"        from app.ops.postgres_deploy_linux import main\n"
    b"        return main(sys.argv[1:])\n"
    b"    except Exception:\n"
    b"        return 78\n"
)
_DORMANT_LOCAL_HELPERS = (
    b"class Helper:\n"
    b"    def run(self):\n"
    b"        from app.ops.unprofiled import value\n"
    b"        return value\n"
    b"\n"
    b"def deferred():\n"
    b"    from app.ops.unprofiled import value\n"
    b"    return value\n"
    b"\n"
    b"def dormant_contract_import():\n"
    b"    from llm_contract import value\n"
    b"    return value\n"
    b"\n"
    b"def dormant_runtime_import():\n"
    b"    from mimer_runtime import value\n"
    b"    return value\n"
    b"\n"
    b"def rebound():\n"
    b"    return None\n"
    b"rebound = deferred\n"
    b"\n"
    b"def benign():\n"
    b"    return None\n"
    b"\n"
    b"def rebind_global():\n"
    b"    global benign\n"
    b"    benign = deferred\n"
    b"\n"
    b"def replace_with_importing_wrapper(function):\n"
    b"    def wrapper():\n"
    b"        from app.ops.unprofiled import wrapper_value\n"
    b"        return wrapper_value\n"
    b"    return wrapper\n"
    b"\n"
    b"@replace_with_importing_wrapper\n"
    b"def replaced():\n"
    b"    return None\n"
    b"\n"
    b"class Base:\n"
    b"    def __init__(self):\n"
    b"        from app.ops.unprofiled import base_value\n"
    b"        self.value = base_value\n"
    b"\n"
    b"class InheritedHelper(Base):\n"
    b"    pass\n"
    b"\n"
    b"class HookBase:\n"
    b"    def __init_subclass__(cls, **kwargs):\n"
    b"        from app.ops.unprofiled import subclass_value\n"
    b"        super().__init_subclass__(**kwargs)\n"
    b"\n"
    b"class ContextHelper:\n"
    b"    def __enter__(self):\n"
    b"        from app.ops.unprofiled import enter_value\n"
    b"        return enter_value\n"
    b"    def __exit__(self, *_args):\n"
    b"        from app.ops.unprofiled import exit_value\n"
    b"        return exit_value\n"
    b"\n"
    b"manager = ContextHelper()\n"
    b"\n"
    b"class CallableHelper:\n"
    b"    def __call__(self, _value=None):\n"
    b"        from app.ops.unprofiled import callback_value\n"
    b"        return callback_value\n"
    b"\n"
    b"class DescriptorHelper:\n"
    b"    @property\n"
    b"    def value(self):\n"
    b"        from app.ops.unprofiled import property_value\n"
    b"        return property_value\n"
    b"    def read(self):\n"
    b"        return self.value\n"
    b"\n"
    b"class SetterDescriptorHelper:\n"
    b"    @property\n"
    b"    def value(self):\n"
    b"        from app.ops.unprofiled import setter_property_value\n"
    b"        return setter_property_value\n"
    b"    @value.setter\n"
    b"    def value(self, _value):\n"
    b"        pass\n"
    b"\n"
    b"alias_property = property\n"
    b"\n"
    b"class AliasedPropertyHelper:\n"
    b"    @alias_property\n"
    b"    def value(self):\n"
    b"        from app.ops.unprofiled import aliased_property_value\n"
    b"        return aliased_property_value\n"
    b"\n"
    b"class Descriptor:\n"
    b"    def __get__(self, _instance, _owner):\n"
    b"        from app.ops.unprofiled import descriptor_value\n"
    b"        return descriptor_value\n"
    b"\n"
    b"class Holder:\n"
    b"    value = Descriptor()\n"
    b"\n"
    b"class IterableHelper:\n"
    b"    def __iter__(self):\n"
    b"        from app.ops.unprofiled import iteration_value\n"
    b"        yield iteration_value\n"
    b"\n"
    b"class ItemHelper:\n"
    b"    def __getitem__(self, _index):\n"
    b"        from app.ops.unprofiled import item_value\n"
    b"        return item_value\n"
    b"\n"
    b"class WriteHelper:\n"
    b"    def __setattr__(self, _name, _value):\n"
    b"        from app.ops.unprofiled import setattr_value\n"
    b"        return setattr_value\n"
    b"    def __delattr__(self, _name):\n"
    b"        from app.ops.unprofiled import delattr_value\n"
    b"        return delattr_value\n"
    b"\n"
    b"class HashHelper:\n"
    b"    def __hash__(self):\n"
    b"        from app.ops.unprofiled import hash_value\n"
    b"        return hash_value\n"
    b"\n"
    b"class LengthHelper:\n"
    b"    def __len__(self):\n"
    b"        from app.ops.unprofiled import length_value\n"
    b"        return length_value\n"
    b"\n"
    b"class TruthHelper:\n"
    b"    def __bool__(self):\n"
    b"        from app.ops.unprofiled import truth_value\n"
    b"        return bool(truth_value)\n"
    b"\n"
    b"class TruthError(Exception):\n"
    b"    def __bool__(self):\n"
    b"        from app.ops.unprofiled import error_truth_value\n"
    b"        return bool(error_truth_value)\n"
    b"\n"
    b"class TruthFactory:\n"
    b"    def __new__(cls):\n"
    b"        return TruthHelper()\n"
    b"\n"
    b"class Invoker:\n"
    b"    def __init__(self, fn=None):\n"
    b"        if fn is not None:\n"
    b"            fn(None)\n"
    b"    def run(self, fn):\n"
    b"        return fn(None)\n"
    b"\n"
    b"class QualifiedInvoker:\n"
    b"    @classmethod\n"
    b"    def run(cls, fn):\n"
    b"        return fn(None)\n"
    b"\n"
    b"callback = CallableHelper()\n"
    b"\n"
    b"def make_callback():\n"
    b"    return CallableHelper()\n"
    b"\n"
    b"def safe_callback():\n"
    b"    return None\n"
    b"\n"
    b"def stale_callback(external_callback):\n"
    b"    callback = safe_callback\n"
    b"    callback = external_callback\n"
    b"    return callback()\n"
    b"\n"
    b"def stale_transitive_callback(external_callback):\n"
    b"    source = safe_callback\n"
    b"    callback = source\n"
    b"    callback = external_callback\n"
    b"    return callback()\n"
    b"\n"
    b"def make_truth():\n"
    b"    return TruthHelper()\n"
    b"\n"
    b"def make_factory_truth():\n"
    b"    return TruthFactory()\n"
    b"\n"
    b"import operator\n"
    b"from types import SimpleNamespace\n"
    b"def indirect_truth():\n"
    b"    return operator.truth(TruthHelper())\n"
    b"\n"
    b"def truth_adapter(value):\n"
    b"    return operator.truth(value)\n"
    b"\n"
    b"def forwarded_truth():\n"
    b"    return truth_adapter(TruthHelper())\n"
    b"\n"
    b"def captured_truth_adapter(value):\n"
    b"    def inner():\n"
    b"        return operator.truth(value)\n"
    b"    return inner()\n"
    b"\n"
    b"def nested_default_truth_adapter(value):\n"
    b"    def inner(item=value):\n"
    b"        return operator.truth(item)\n"
    b"    return inner()\n"
    b"\n"
    b"def forwarded_captured_truth():\n"
    b"    return captured_truth_adapter(TruthHelper())\n"
    b"\n"
    b"def forwarded_nested_default_truth():\n"
    b"    return nested_default_truth_adapter(TruthHelper())\n"
    b"\n"
    b"def nested_nested_truth_adapter(value):\n"
    b"    def middle():\n"
    b"        def inner():\n"
    b"            return operator.truth(value)\n"
    b"        return inner()\n"
    b"    return middle()\n"
    b"\n"
    b"def forwarded_nested_nested_truth():\n"
    b"    return nested_nested_truth_adapter(TruthHelper())\n"
    b"\n"
    b"def module_default_truth(item=TruthHelper()):\n"
    b"    return operator.truth(item)\n"
    b"\n"
    b"def indirect_truth_alias():\n"
    b"    value = TruthHelper() if True else None\n"
    b"    return operator.truth(value)\n"
    b"\n"
    b"def truth_in_external_field():\n"
    b"    box = SimpleNamespace()\n"
    b"    box.value = TruthHelper()\n"
    b"    return operator.truth(box.value)\n"
    b"\n"
    b"def truth_in_external_container():\n"
    b"    box = dict()\n"
    b"    box['value'] = TruthHelper()\n"
    b"    return operator.truth(box['value'])\n"
    b"\n"
    b"def truth_caught_local_exception():\n"
    b"    try:\n"
    b"        raise TruthError()\n"
    b"    except TruthError as error:\n"
    b"        return operator.truth(error)\n"
    b"\n"
    b"def truth_caught_local_exception_base():\n"
    b"    try:\n"
    b"        raise TruthError()\n"
    b"    except Exception as error:\n"
    b"        alias = error\n"
    b"        return operator.truth(alias)\n"
    b"\n"
    b"import runpy\n"
    b"def run_hidden():\n"
    b"    return runpy.run_module('app.ops.unprofiled')\n"
    b"\n"
    b"from runpy import run_module as execute\n"
    b"def run_hidden_alias():\n"
    b"    target = 'app.ops.unprofiled'\n"
    b"    return execute(target)\n"
    b"\n"
    b"def run_hidden_alias_external_target():\n"
    b"    return execute('sys')\n"
    b"\n"
    b"import pickle\n"
    b"def load_hidden():\n"
    b"    return pickle.loads(b'capp.ops.unprofiled\\nvalue\\n.')\n"
    b"\n"
    b"def load_hidden_hex():\n"
    b"    return pickle.loads(bytes.fromhex('636170702e6f70732e756e70726f66696c65640a76616c75650a2e'))\n"
    b"\n"
    b"def decode_payload(payload):\n"
    b"    return pickle.loads(payload)\n"
    b"\n"
    b"def load_hidden_forwarded():\n"
    b"    return decode_payload(bytes.fromhex('636170702e6f70732e756e70726f66696c65640a76616c75650a2e'))\n"
    b"\n"
    b"def load_hidden_assigned():\n"
    b"    payload = bytes.fromhex('636170702e6f70732e756e70726f66696c65640a76616c75650a2e')\n"
    b"    return pickle.loads(payload)\n"
    b"\n"
    b"def load_hidden_split_pickle():\n"
    b"    payload = b'c__builtin__\\neval\\n(S\\\"__import__(\\\'app.' + b'ops.unprofiled\\')\\\"\\ntR.'\n"
    b"    return pickle.loads(payload)\n"
    b"\n"
    b"def load_hidden_private_pickle():\n"
    b"    return pickle._loads(b\"cbuiltins\\neval\\n(V__import__('a'+'pp.ops.unprofiled')\\ntR.\")\n"
    b"\n"
    b"from multiprocessing.reduction import ForkingPickler\n"
    b"def load_hidden_forking_pickle(payload):\n"
    b"    return ForkingPickler.loads(payload)\n"
    b"\n"
    b"def apply(callback, values):\n"
    b"    return list(map(callback, values))\n"
    b"\n"
    b"def decorate(function):\n"
    b"    from app.ops.unprofiled import decorator_value\n"
    b"    return function\n"
    b"\n"
    b"class Meta(type):\n"
    b"    def __call__(cls, *args, **kwargs):\n"
    b"        from app.ops.unprofiled import meta_value\n"
    b"        return super().__call__(*args, **kwargs)\n"
    b"\n"
    b"from contextlib import contextmanager\n"
    b"from contextlib import contextmanager as stdlib_contextmanager\n"
    b"\n"
    b"def custom_decorator(_function):\n"
    b"    def wrapped(*_args, **_kwargs):\n"
    b"        return ContextHelper()\n"
    b"    return wrapped\n"
    b"\n"
    b"if True:\n"
    b"    contextmanager = custom_decorator\n"
    b"\n"
    b"@contextmanager\n"
    b"def custom_cm():\n"
    b"    yield None\n"
    b"\n"
    b"@contextmanager\n"
    b"def cm():\n"
    b"    yield None\n"
    b"\n"
    b"@stdlib_contextmanager\n"
    b"def safe_cm():\n"
    b"    yield None\n"
)


def _owned_dir(path: Path) -> Path:
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    path.chmod(0o755)
    return path


def _empty_control_manifest_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    app_root = _owned_dir(tmp_path / "target" / "application")
    control_root = _owned_dir(tmp_path / "target" / "control")
    launcher_root = _owned_dir(tmp_path / "target" / "launcher")
    backup_root = _owned_dir(tmp_path / "target" / "backup")
    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", control_root)
    monkeypatch.setattr(transaction, "_BACKUP_DIRECTORY", backup_root)
    monkeypatch.setattr(transaction, "_LAUNCHER", launcher_root / "yggdrasil-bws-deploy")

    old_sources = {
        "app/__init__.py": b"",
        "app/ops/postgres_deploy_linux.py": b"OLD_DEPLOYMENT = True\n",
        "app/ops/bws_installation_admission.py": b"OLD_ADMISSION = True\n",
        "scripts/__init__.py": b"",
        "scripts/postgres_deploy_service.py": _SOURCE_ONLY_LAUNCHER,
    }
    candidate_sources = {
        **old_sources,
        "app/ops/postgres_deploy_linux.py": b"raise RuntimeError('candidate deployment')\n",
        "app/ops/bws_installation_admission.py": b"raise RuntimeError('candidate admission')\n",
    }
    for relative, raw in old_sources.items():
        target = app_root / relative
        _owned_dir(target.parent)
        target.write_bytes(raw)
        target.chmod(0o755 if relative == "scripts/postgres_deploy_service.py" else 0o644)

    old_contract = (Path(__file__).parent / "fixtures" / "host_secret_contract_legacy.json").read_bytes()
    candidate_contract = (Path(__file__).resolve().parents[2]
                          / "config/secrets/host_secret_contract.json").read_bytes()
    contract_path = app_root / "config/secrets/host_secret_contract.json"
    _owned_dir(contract_path.parent)
    contract_path.write_bytes(old_contract)
    contract_path.chmod(0o644)

    old_launcher = b"legacy launcher bytes\n"
    monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: old_launcher)
    monkeypatch.setattr(transaction, "_require_source_only_launcher", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_require_launcher_imports", lambda *_args: None)
    monkeypatch.setattr(transaction, "_require_cleanup_shared_reservation", lambda *_args: None)
    monkeypatch.setattr(transaction, "_require_startup_reservation_release", lambda *_args: None)
    monkeypatch.setattr(transaction, "_cleanup_skip_closure", lambda *_args: "bounded")

    def open_root(path, opened):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(transaction, "_open_absolute_directory", open_root)
    config = SimpleNamespace(channel="dev", root=app_root)
    request = {"operation_id": str(uuid.uuid4()), "channel": "dev", "candidate_sha": "c" * 40,
               "image_digest": "sha256:" + "b" * 64}
    profile = transaction._old_disk_state(config, request)
    roots, backup = transaction._roots(config, profile)
    revision = request["candidate_sha"]
    candidate_tree = {
        path: (raw, 0o755 if path == "scripts/postgres_deploy_service.py" else 0o644)
        for path, raw in candidate_sources.items()
    }

    def git_show(_revision: str, relative: str) -> bytes:
        if relative == "config/secrets/host_secret_contract.json":
            return candidate_contract
        if relative == "scripts/postgres_deploy_service.py":
            return candidate_sources[relative]
        raise AssertionError(f"unexpected candidate path: {relative}")

    def git_file_mode(_revision: str, relative: str) -> int:
        if relative == "config/secrets/host_secret_contract.json":
            return 0o644
        if relative == "scripts/postgres_deploy_service.py":
            return 0o755
        raise AssertionError(f"unexpected candidate path: {relative}")

    def invoke(selected_roots=roots):
        return transaction.candidate_manifest(
            profile, revision=revision, roots=selected_roots, backup_root=backup,
            git_show=git_show, git_source_files=lambda _revision: candidate_tree,
            git_file_mode=git_file_mode,
        )

    return SimpleNamespace(
        app_root=app_root, control_root=control_root, config=config, profile=profile,
        roots=roots, invoke=invoke,
    )


def _full_source_manifest_case(
    monkeypatch: pytest.MonkeyPatch, secure_tmp_path: Path, *, channel: str,
    generated_count: int = 205, generated_update_count: int = 0,
    control_source: bytes | None = None,
    unchanged_core: tuple[str, ...] = (),
    delta_payload_total_bytes: int | None = None,
    generated_directory: str = "app/ops",
) -> SimpleNamespace:
    """Build a shallow-checkout-safe Git candidate with real guarded core sources."""
    control_module = importlib.import_module("app.ops.bws_control_installation")
    monkeypatch.setattr(control_module, "_source_descriptor_capacity_snapshot",
                        lambda: (0, 1_000_000, 1_000_000))
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    target = _owned_dir(secure_tmp_path / f"target-{channel}")
    app_root = _owned_dir(target / "application")
    control_root = _owned_dir(target / "control")
    launcher_root = _owned_dir(target / "launcher")
    backup_root = _owned_dir(target / "backup")
    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", control_root)
    monkeypatch.setattr(transaction, "_BACKUP_DIRECTORY", backup_root)
    launcher_path = launcher_root / "yggdrasil-bws-deploy"
    monkeypatch.setattr(transaction, "_LAUNCHER", launcher_path)

    repository = Path(__file__).resolve().parents[2]
    core_paths = (
        "app/__init__.py",
        "app/ops/__init__.py",
        "app/ops/postgres_deploy_linux.py",
        "app/ops/bws_installation_admission.py",
        "scripts/__init__.py",
        "scripts/postgres_deploy_service.py",
    )
    candidate_sources = {relative: (repository / relative).read_bytes() for relative in core_paths}
    candidate_contract = (repository / "config/secrets/host_secret_contract.json").read_bytes()
    if delta_payload_total_bytes is None:
        generated_payload_sizes = [None] * generated_count
    else:
        fixed_payload_bytes = sum(len(candidate_sources[path]) for path in (
            "app/ops/postgres_deploy_linux.py", "app/ops/bws_installation_admission.py",
            "scripts/postgres_deploy_service.py",
        )) + len(candidate_contract)
        generated_total_bytes = delta_payload_total_bytes - fixed_payload_bytes
        assert generated_total_bytes >= generated_count
        base_size, extra_bytes = divmod(generated_total_bytes, generated_count)
        generated_payload_sizes = [base_size + (index < extra_bytes)
                                   for index in range(generated_count)]
    generated_paths = [
        f"{generated_directory}/generated_budget_{index:04d}.py"
        for index in range(generated_count)
    ]
    for index in range(generated_count):
        variant = index % 8
        path = generated_paths[index]
        prefix = f"GENERATED_SOURCE = {variant}\n".encode()
        target_size = generated_payload_sizes[index]
        candidate_sources[path] = prefix + b"#" * (
            variant * 7 if target_size is None else target_size - len(prefix)
        )

    checkout = _owned_dir(secure_tmp_path / f"candidate-{channel}")
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, env=git_env)
    for relative, raw in candidate_sources.items():
        path = checkout / relative
        _owned_dir(path.parent)
        path.write_bytes(raw)
        path.chmod(0o755 if relative == "scripts/postgres_deploy_service.py" else 0o644)
    contract_path = checkout / "config/secrets/host_secret_contract.json"
    _owned_dir(contract_path.parent)
    contract_path.write_bytes(candidate_contract)
    contract_path.chmod(0o644)
    subprocess.run(["git", "-C", str(checkout), "add", "app", "scripts", "config"],
                   check=True, env=git_env)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", "generated source candidate"],
                   check=True, env=git_env)
    revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, env=git_env).stdout.strip()

    generated_path_set = set(generated_paths)
    old_sources = {relative: raw for relative, raw in candidate_sources.items()
                   if relative not in generated_path_set}
    for index in range(generated_update_count):
        variant = index % 8
        path = generated_paths[index]
        prefix = f"PREVIOUS_SOURCE = {variant}\n".encode()
        target_size = len(candidate_sources[path])
        old_sources[path] = prefix + b"!" * (variant * 7 if delta_payload_total_bytes is None
                                               else target_size - len(prefix))
    for relative in ("app/ops/postgres_deploy_linux.py", "app/ops/bws_installation_admission.py"):
        if relative not in unchanged_core:
            old_sources[relative] = b"# previous installed source\n" + old_sources[relative]
    for relative in generated_paths:
        _owned_dir((app_root / relative).parent)
    for relative, raw in old_sources.items():
        path = app_root / relative
        _owned_dir(path.parent)
        path.write_bytes(raw)
        path.chmod(0o755 if relative == "scripts/postgres_deploy_service.py" else 0o644)

    old_contract = (Path(__file__).parent / "fixtures" / "host_secret_contract_legacy.json").read_bytes()
    installed_contract = app_root / "config/secrets/host_secret_contract.json"
    _owned_dir(installed_contract.parent)
    installed_contract.write_bytes(old_contract)
    installed_contract.chmod(0o644)
    old_launcher = b"old launcher bytes\n"
    launcher_path.write_bytes(old_launcher)
    launcher_path.chmod(0o755)
    monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: old_launcher)

    if control_source is not None:
        control_file = control_root / "app/ops/postgres_deploy_linux.py"
        _owned_dir(control_file.parent)
        control_file.write_bytes(control_source)
        control_file.chmod(0o644)

    config = SimpleNamespace(channel=channel, root=app_root)
    request = {"operation_id": str(uuid.uuid4()), "channel": channel, "candidate_sha": revision,
               "image_digest": "sha256:" + "b" * 64, "bundle_name": f"source-budget-{channel}"}
    profile = transaction._old_disk_state(config, request)
    roots, backup = transaction._roots(config, profile)
    monkeypatch.setattr(sys, "_yggdrasil_bws_candidate_checkout", str(checkout), raising=False)
    ports = transaction._NativePorts()
    return SimpleNamespace(
        app_root=app_root, backup_root=backup_root, checkout=checkout, config=config,
        request=request, profile=profile, roots=roots, backup=backup, ports=ports,
        candidate_sources=candidate_sources,
    )


def _loaded_module(path: Path) -> SimpleNamespace:
    filename = str(path)
    source = path.read_bytes() if path.exists() else b""
    return SimpleNamespace(
        __file__=filename, __cached__=importlib.util.cache_from_source(filename),
        __yggdrasil_source_sha256__=hashlib.sha256(source).hexdigest(),
    )


def _use_source_only_cache_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "pycache_prefix", "/dev/null")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)


def test_legacy_fixed_launcher_is_accepted_only_as_the_old_generation():
    transaction._require_source_only_launcher(_LEGACY_SOURCE_ONLY_LAUNCHER)
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_source_only_launcher(
            _LEGACY_SOURCE_ONLY_LAUNCHER, require_preimport_reservation=True,
        )
    transaction._require_source_only_launcher(
        _SOURCE_ONLY_LAUNCHER, require_preimport_reservation=True,
    )
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_source_only_launcher(
            _SOURCE_ONLY_LAUNCHER.replace(
                b"exec(code, module.__dict__)", b"exec('unbound source', module.__dict__)",
            ),
            require_preimport_reservation=True,
        )
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_source_only_launcher(
            _SOURCE_ONLY_LAUNCHER.replace(
                b"    if reservation.skip_cleanup:\n        return 0\n", b"",
            ),
            require_preimport_reservation=True,
        )
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_source_only_launcher(
            _SOURCE_ONLY_LAUNCHER.replace(
                b"    _consume_start_authorization(None, channel, None, None, None)\n", b"",
            ),
            require_preimport_reservation=True,
        )
    transaction._require_launcher_imports(_SOURCE_ONLY_LAUNCHER)


def test_native_profile_sends_caller_source_modules_only_on_initial_profile(monkeypatch):
    ports = transaction._NativePorts()
    ports._config = SimpleNamespace(channel="dev", root=Path("/srv/yggdrasil"))
    ports.caller_root = Path("/srv/candidate")
    caller_modules = [{"module": "scripts.compose_env", "root": "application",
                       "path": "scripts/compose_env.py", "sha256": "a" * 64, "mode": 0o644}]
    requests = []
    monkeypatch.setattr(transaction, "_source_modules", lambda _config, _roots: caller_modules)
    monkeypatch.setattr(transaction, "_verify_candidate_checkout", lambda *_args: None)
    monkeypatch.setattr(transaction, "_profile_response",
                        lambda _channel, request: requests.append(dict(request)) or {"profile": "synthetic"})
    monkeypatch.setattr(transaction, "_bind_source_inventory", lambda profile, _config: profile)
    request = {"operation_id": str(uuid.uuid4()), "candidate_sha": "b" * 40,
               "image_digest": "sha256:" + "c" * 64, "bundle_name": "profile-test"}

    ports.verify_caller_sources(request)
    ports.profile("dev", request)
    ports.profile("dev", request)

    assert requests[0]["_caller_source_modules"] == caller_modules
    assert "_caller_source_modules" not in requests[1]


def test_open_absolute_directory_allows_private_0750_ancestors_only(secure_tmp_path, monkeypatch):
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    parent = secure_tmp_path / "private-parent"
    parent.mkdir(mode=0o750)
    parent.chmod(0o750)
    root = parent / "source-root"
    root.mkdir(mode=0o700)
    root.chmod(0o700)

    opened: list[int] = []
    try:
        descriptor = transaction._open_absolute_directory(root.resolve(), opened)
        assert descriptor == opened[-1]
        assert os.fstat(descriptor).st_mode & 0o777 == 0o700
    finally:
        for fd in reversed(opened):
            os.close(fd)

    def assert_refused() -> None:
        descriptors: list[int] = []
        try:
            with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
                transaction._open_absolute_directory(root.resolve(), descriptors)
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    root.chmod(0o750)
    assert_refused()
    root.chmod(0o700)

    parent.chmod(0o770)
    assert_refused()


@pytest.mark.parametrize("binding_kind", ["absent", "candidate", "checkout", "script"])
def test_native_transaction_refuses_stale_direct_caller_binding_before_checkout_or_backup(
        tmp_path, monkeypatch, binding_kind):
    from app.ops import bws_installation_admission as admission

    checkout = tmp_path / "candidate"
    candidate_sha = "a" * 40
    if binding_kind == "absent":
        monkeypatch.delattr(transaction.sys, admission._VERIFIED_CANDIDATE_ENTRYPOINT, raising=False)
    else:
        binding = {"candidate_sha": candidate_sha, "checkout": str(checkout), "script_sha256": "b" * 64}
        if binding_kind == "candidate":
            binding["candidate_sha"] = "c" * 40
        elif binding_kind == "checkout":
            binding["checkout"] = str(tmp_path / "other")
        else:
            binding["script_sha256"] = "not-the-candidate-script"
        monkeypatch.setattr(transaction.sys, admission._VERIFIED_CANDIDATE_ENTRYPOINT, binding, raising=False)

    ports = object.__new__(transaction._NativePorts)
    ports.caller_root = checkout
    monkeypatch.setattr(transaction, "_verify_candidate_checkout",
                        lambda *_args: pytest.fail("stale caller passed entrypoint binding"))
    with pytest.raises(admission.InstallationAdmissionRefused):
        ports.verify_caller_checkout({"candidate_sha": candidate_sha})


def test_profile_readiness_retries_only_missing_fixed_socket(monkeypatch):
    from app.ops import postgres_deploy_linux

    request = {
        "operation_id": str(uuid.uuid4()), "candidate_sha": "b" * 40,
        "image_digest": "sha256:" + "c" * 64,
    }
    expected_profile = {
        "operation_id": request["operation_id"], "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"], "channel": "dev",
    }
    response = {
        "source_installation_profile": expected_profile,
        "supervisor_idle": True, "exec_stop_post_no_write": True,
    }
    calls = 0
    sleeps: list[float] = []

    def delayed_socket(_channel, _request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise FileNotFoundError(2, "synthetic socket not bound")
        return response

    monkeypatch.setattr(postgres_deploy_linux, "_rpc_via_supervisor", delayed_socket)
    monkeypatch.setattr(transaction.time, "sleep", sleeps.append)

    assert transaction._profile_response("dev", request) == expected_profile
    assert calls == 3
    assert sleeps == [transaction._PROFILE_READINESS_POLL_SECONDS] * 2


def test_loaded_profile_is_operation_bound_and_redacted(monkeypatch, tmp_path):
    app_root = _owned_dir(tmp_path / "application")
    control_root = _owned_dir(tmp_path / "control")
    app_module = app_root / "app/ops/loaded.py"
    mvr05_module = app_root / "app/instance/mvr05_cutover.py"
    control_module = control_root / "app/ops/loaded_control.py"
    app_helper = app_root / "app/ops/helper.py"
    caller_script = app_root / "scripts/compose_env.py"
    control_helper = control_root / "app/ops/control_helper.py"
    deployment = app_root / "app/ops/postgres_deploy_linux.py"
    admission = app_root / "app/ops/bws_installation_admission.py"
    bws_control = app_root / "app/ops/bws_control_installation.py"
    native_admission = app_root / "app/ops/native_source_admission.py"
    native_journaling = app_root / "app/ops/native_journaling_acceptance.py"
    contract_path = app_root / "config/secrets/host_secret_contract.json"
    for path in (app_module, mvr05_module, control_module, app_helper, caller_script, control_helper, deployment, admission,
                 bws_control, native_admission, native_journaling, contract_path):
        _owned_dir(path.parent)
    app_module.write_bytes(b"from app.ops.helper import value\n")
    mvr05_module.write_bytes(b"VALUE = 'synthetic-census'\n")
    control_module.write_bytes(b"from app.ops.control_helper import value\n")
    app_helper.write_bytes(b"value = 1\n")
    caller_script.write_bytes(b"def compose_env_value():\n    return 'synthetic'\n")
    control_helper.write_bytes(b"value = 2\n")
    deployment.write_text(_DEPLOYMENT_SOURCE)
    admission.write_text(_ADMISSION_SOURCE)
    bws_control.write_bytes(b"VALUE = 3\n")
    native_admission.write_bytes(b"VALUE = 4\n")
    native_journaling.write_bytes(b"PROFILE = 'synthetic-journaling'\n")
    contract_raw = Path("config/secrets/host_secret_contract.json").read_bytes()
    contract_path.write_bytes(contract_raw)
    for path in (app_module, mvr05_module, control_module, app_helper, caller_script, control_helper, deployment, admission,
                 bws_control, native_admission, native_journaling, contract_path):
        path.chmod(0o644)

    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", control_root)
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    old_launcher = _LEGACY_SOURCE_ONLY_LAUNCHER
    monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: old_launcher)
    _use_source_only_cache_policy(monkeypatch)

    def open_root(path, opened):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(transaction, "_open_absolute_directory", open_root)
    monkeypatch.setitem(sys.modules, "app.ops.loaded", _loaded_module(app_module))
    monkeypatch.setitem(sys.modules, "app.instance.mvr05_cutover", _loaded_module(mvr05_module))
    monkeypatch.setitem(sys.modules, "app.ops.loaded_control", _loaded_module(control_module))
    monkeypatch.setitem(sys.modules, "app.ops.helper", _loaded_module(app_helper))
    monkeypatch.setitem(sys.modules, "scripts.compose_env", _loaded_module(caller_script))
    caller_row = {"module": "scripts.compose_env", "root": "application",
                  "path": "scripts/compose_env.py", "sha256": hashlib.sha256(caller_script.read_bytes()).hexdigest(),
                  "mode": 0o644}
    monkeypatch.setitem(sys.modules, "app.ops.control_helper", _loaded_module(control_helper))
    monkeypatch.setitem(sys.modules, "app.ops.postgres_deploy_linux", _loaded_module(deployment))
    monkeypatch.setitem(sys.modules, "app.ops.bws_installation_admission", _loaded_module(admission))
    monkeypatch.setitem(sys.modules, "app.ops.bws_control_installation",
                        SimpleNamespace(**vars(_loaded_module(bws_control)), Change=Change))
    monkeypatch.setitem(sys.modules, "app.ops.native_source_admission", _loaded_module(native_admission))
    monkeypatch.setitem(sys.modules, "app.ops.native_journaling_acceptance", _loaded_module(native_journaling))
    config = SimpleNamespace(channel="dev", root=app_root)
    operation_id = str(uuid.uuid4())
    loaded_preloads = []
    original_import_module = transaction.importlib.import_module

    def record_import(module_name, *args, **kwargs):
        loaded_preloads.append(module_name)
        return original_import_module(module_name, *args, **kwargs)

    monkeypatch.setattr(transaction.importlib, "import_module", record_import)

    profile = transaction.loaded_source_profile(
        config, operation_id=operation_id, candidate_sha="a" * 40,
        image_digest="sha256:" + "b" * 64, caller_source_modules=[caller_row],
    )
    assert "app.ops.native_journaling_acceptance" in loaded_preloads

    assert profile["operation_id"] == operation_id
    assert profile["candidate_sha"] == "a" * 40
    assert profile["image_digest"] == "sha256:" + "b" * 64
    assert profile["contract_sha256"] == hashlib.sha256(contract_raw).hexdigest()
    assert profile["launcher_sha256"] == hashlib.sha256(old_launcher).hexdigest()
    assert {(row["root"], row["path"]) for row in profile["modules"]} == {
        ("application", "app/ops/loaded.py"),
        ("application", "app/instance/mvr05_cutover.py"),
        ("application", "app/ops/helper.py"),
        ("application", "scripts/compose_env.py"),
        ("control", "app/ops/loaded_control.py"),
        ("control", "app/ops/control_helper.py"),
        ("application", "app/ops/postgres_deploy_linux.py"),
        ("application", "app/ops/bws_installation_admission.py"),
        ("application", "app/ops/bws_control_installation.py"),
        ("application", "app/ops/native_source_admission.py"),
        ("application", "app/ops/native_journaling_acceptance.py"),
    }
    assert str(app_root) not in json.dumps(profile)
    assert str(control_root) not in json.dumps(profile)

    monkeypatch.delitem(sys.modules, "scripts.compose_env")
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._source_modules(
            config, {"application": app_root, "control": control_root},
            caller_source_modules=[caller_row],
        )

    app_helper.write_bytes(b"value = 9\n")
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction.loaded_source_profile(
            config, operation_id=operation_id, candidate_sha="a" * 40,
            image_digest="sha256:" + "b" * 64,
        )


def test_fixed_launcher_loader_binds_executed_source_bytes_and_detects_later_drift(tmp_path):
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"from .probe import VALUE\n")
    probe = package / "probe.py"
    probe.write_bytes(b"VALUE = 7\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_bytes(b"\n")
    (scripts / "__init__.py").chmod(0o755)
    compose_env = scripts / "compose_env.py"
    compose_env.write_bytes(b"VALUE = 'source-bound'\n")
    repository = Path(__file__).resolve().parents[2]
    program = """
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
repository = Path(sys.argv[1])
root = Path(sys.argv[2])
transaction_spec = importlib.util.spec_from_file_location(
    'transaction_for_source_mode_test', repository / 'app/ops/bws_installation_transaction.py')
transaction = importlib.util.module_from_spec(transaction_spec)
sys.modules[transaction_spec.name] = transaction
transaction_spec.loader.exec_module(transaction)
spec = importlib.util.spec_from_file_location('bws_test_launcher', repository / 'scripts/postgres_deploy_service.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
sys.pycache_prefix = '/dev/null'
sys.dont_write_bytecode = True
sys.path.insert(0, str(root))
launcher._install_source_loader(root)
import app
import scripts.compose_env
module = sys.modules['app.probe']
script_module = sys.modules['scripts.compose_env']
loaded = module.__yggdrasil_source_sha256__
assert app.VALUE == 7
assert loaded == hashlib.sha256((root / 'app/probe.py').read_bytes()).hexdigest()
assert script_module.__yggdrasil_source_sha256__ == hashlib.sha256((root / 'scripts/compose_env.py').read_bytes()).hexdigest()
transaction._OWNER_UID = os.getuid()
transaction._OWNER_GID = os.getgid()
def open_root(path, opened):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened.append(descriptor)
    return descriptor
transaction._open_absolute_directory = open_root
modules = transaction._source_modules(object(), {'application': root})
package_row = next(row for row in modules if row['module'] == 'scripts')
assert package_row['path'] == 'scripts/__init__.py' and package_row['mode'] == 0o755
(root / 'app/probe.py').write_bytes(b'VALUE = 8\\n')
assert loaded != hashlib.sha256((root / 'app/probe.py').read_bytes()).hexdigest()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(repository), str(tmp_path)],
        cwd=repository, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_first_install_manifest_accepts_empty_control_source_root(monkeypatch, tmp_path):
    case = _empty_control_manifest_case(monkeypatch, tmp_path)

    assert case.profile["source_packages"] == {"application": ["app", "scripts"], "control": []}
    assert not any(row["root"] == "control" for row in case.profile["source_files"])
    assert set(case.roots) == {"application", "control", "launcher"}

    changes, payloads, proof = case.invoke()

    assert changes
    assert "control" not in proof["changed_roots"]
    assert all(change.root != "control" for change in changes)
    assert all(root_name != "control" for root_name, _path in payloads)


def test_first_install_manifest_refuses_control_source_drift(monkeypatch, tmp_path):
    case = _empty_control_manifest_case(monkeypatch, tmp_path)
    replacement_control_root = _owned_dir(tmp_path / "target" / "replacement-control")
    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", replacement_control_root)
    drifted_roots, _backup = transaction._roots(case.config, case.profile)

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        case.invoke(drifted_roots)

    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", case.control_root)
    new_control_source = case.control_root / "app/ops/new_control_source.py"
    _owned_dir(new_control_source.parent)
    new_control_source.write_text("CONTROL_SOURCE = True\n")

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        case.invoke()


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_full_source_large_delta_reaches_prepare(monkeypatch, secure_tmp_path, channel):
    # Mirror the public 229-change transition with 165 existing-source updates,
    # 60 creates, two guarded core updates, contract and launcher. The real
    # lower prepare retains the resulting target, before-file and backup handles.
    case = _full_source_manifest_case(
        monkeypatch, secure_tmp_path, channel=channel, generated_count=225,
        generated_update_count=165, delta_payload_total_bytes=8_102_989,
    )

    changes, payloads, proof = case.ports.source_manifest(
        case.profile, case.config, case.request, case.roots, case.backup,
    )

    assert len(changes) == 229
    assert any(change.before_sha256 is None for change in changes)
    assert any(change.root == "application"
               and change.path == "config/secrets/host_secret_contract.json" for change in changes)
    assert any(change.root == "launcher" and change.path == "yggdrasil-bws-deploy"
               for change in changes)
    assert sum(len(payload) for payload in payloads.values()) == 8_102_989
    assert case.profile["source_packages"]["control"] == []
    assert all(change.root != "control" for change in changes)
    assert len(proof["candidate_files"]) <= transaction._MAX_SOURCE_FILES
    assert sum(row["size"] for row in proof["candidate_files"]) <= transaction._MAX_TOTAL_SOURCE_BYTES
    generated_rows = [row for row in proof["candidate_files"]
                      if str(row["path"]).startswith("app/ops/generated_budget_")]
    assert len({row["sha256"] for row in generated_rows}) == 16
    assert len({row["size"] for row in generated_rows}) == 2

    changed_roots = {change.root for change in changes}
    prepare_roots = {name: root for name, root in case.roots.items() if name in changed_roots}
    handle = case.ports.prepare(
        prepare_roots, changes, payloads, case.backup, "large-source-delta",
        source_inventory_fd_peak=proof["source_inventory_fd_peak"], runtime_fd_already_open=True,
    )
    try:
        assert handle.state == "prepared"
        assert len(handle._targets) == len(changes)
        assert (case.backup_root / "large-source-delta" / "manifest.json").is_file()
    finally:
        handle.close()

    assert not any(f"app.ops.generated_budget_{index:04d}" in sys.modules
                   for index in range(225))


@pytest.mark.parametrize("budget", ["count", "bytes", "entries", "manifest"])
def test_source_manifest_combined_inventory_budget_refuses_before_backup(
    monkeypatch, secure_tmp_path, budget,
):
    control_source = b"CONTROL_OLD = True\n"
    if budget == "count":
        # The old and Git inventories are each seven files; the prospective
        # application plus retained control copies need an eighth combined slot.
        monkeypatch.setattr(transaction, "_MAX_SOURCE_FILES", 8)
    case = _full_source_manifest_case(
        monkeypatch, secure_tmp_path, channel="dev", generated_count=1,
        control_source=control_source,
        unchanged_core=("app/ops/bws_installation_admission.py",) if budget == "bytes" else (),
    )
    if budget == "entries":
        current_paths = {
            str(row["path"]) for row in case.profile["source_files"]
            if row["root"] == "application"
        }
        assert "app/ops/generated_budget_0000.py" not in current_paths
        current_entries = transaction._source_file_inventory(
            {"application": case.app_root, "control": Path(case.roots["control"].path)},
        )[3]
        monkeypatch.setattr(transaction, "_MAX_SOURCE_ENTRIES", current_entries)
        with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
            case.ports.source_manifest(case.profile, case.config, case.request, case.roots, case.backup)
        assert not list(case.backup_root.iterdir())
        return
    if budget == "manifest":
        control_module = importlib.import_module("app.ops.bws_control_installation")
        payload = b"bounded source\n"
        digest = hashlib.sha256(payload).hexdigest()
        changes = tuple(
            control_module.Change("application", f"app/ops/generated_limit_{index:04d}.py",
                                  None, None, digest, 0o644)
            for index in range(transaction._MAX_SOURCE_MANIFEST_CHANGES + 1)
        )
        payloads = {(change.root, change.path): payload for change in changes}
        with pytest.raises(control_module.InstallationRefused, match="manifest_refused"):
            case.ports.prepare(
                {"application": case.roots["application"]}, changes, payloads,
                case.backup, "over-source-manifest",
            )
        assert not list(case.backup_root.iterdir())
        return
    if budget == "count":
        _changes, _payloads, proof = case.ports.source_manifest(
            case.profile, case.config, case.request, case.roots, case.backup,
        )
        assert len(case.profile["source_files"]) == 7
        assert len(case.candidate_sources) == 7
        assert len(proof["candidate_files"]) == 8
        assert not list(case.backup_root.iterdir())
        monkeypatch.setattr(transaction, "_MAX_SOURCE_FILES", 7)
    if budget == "bytes":
        candidate_inventory_bytes = (
            sum(len(raw) for raw in case.candidate_sources.values())
            + len(case.candidate_sources["app/ops/postgres_deploy_linux.py"])
        )
        old_inventory_bytes = sum(row["size"] for row in case.profile["source_files"])
        candidate_tree_bytes = sum(len(raw) for raw in case.candidate_sources.values())
        assert old_inventory_bytes < candidate_inventory_bytes - 1
        assert candidate_tree_bytes < candidate_inventory_bytes - 1
        monkeypatch.setattr(transaction, "_MAX_TOTAL_SOURCE_BYTES", candidate_inventory_bytes)
        _changes, _payloads, proof = case.ports.source_manifest(
            case.profile, case.config, case.request, case.roots, case.backup,
        )
        assert sum(row["size"] for row in proof["candidate_files"]) == candidate_inventory_bytes
        assert not list(case.backup_root.iterdir())
        monkeypatch.setattr(transaction, "_MAX_TOTAL_SOURCE_BYTES", candidate_inventory_bytes - 1)

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        case.ports.source_manifest(case.profile, case.config, case.request, case.roots, case.backup)

    assert not list(case.backup_root.iterdir())


@pytest.mark.parametrize(
    "capacity", ["unknown", "insufficient", "inventory-insufficient",
                 "control-projection-insufficient"],
)
def test_source_descriptor_capacity_refuses_before_backup(
    monkeypatch, secure_tmp_path, capacity,
):
    case = _full_source_manifest_case(
        monkeypatch, secure_tmp_path, channel="dev", generated_count=225,
        generated_update_count=165,
    )
    control_module = importlib.import_module("app.ops.bws_control_installation")
    changes, payloads, proof = case.ports.source_manifest(
        case.profile, case.config, case.request, case.roots, case.backup,
    )
    prepare_roots = {name: root for name, root in case.roots.items()
                     if name in proof["changed_roots"]}
    inventory_fd_peak = proof["source_inventory_fd_peak"]
    inventory_peak_for_capacity = inventory_fd_peak
    required = control_module._source_descriptor_peak(
        prepare_roots, changes, case.backup, inventory_peak_for_capacity,
    )
    if capacity == "unknown":
        snapshot = lambda: None
        reason = "descriptor_capacity_unknown"
    elif capacity == "inventory-insufficient":
        lifecycle_module = importlib.import_module("app.ops.bws_installation_lifecycle")
        inventory_peak_for_capacity = lifecycle_module._control_projection_descriptor_bound() + 1
        required = control_module._source_descriptor_peak(
            prepare_roots, changes, case.backup, inventory_peak_for_capacity,
        )
        required_without_inventory = control_module._source_descriptor_peak(
            prepare_roots, changes, case.backup,
        )
        assert required > required_without_inventory
        snapshot = lambda: (128, 128 + required_without_inventory, 128 + required_without_inventory)
        reason = "descriptor_capacity_insufficient"
    elif capacity == "control-projection-insufficient":
        lifecycle_module = importlib.import_module("app.ops.bws_installation_lifecycle")
        with monkeypatch.context() as no_projection:
            no_projection.setattr(
                lifecycle_module, "_control_projection_descriptor_bound", lambda: 0,
            )
            required_without_projection = control_module._source_descriptor_peak(
                prepare_roots, changes, case.backup, inventory_fd_peak,
            )
        assert required > required_without_projection
        snapshot = lambda: (128, 128 + required_without_projection, 128 + required_without_projection)
        reason = "descriptor_capacity_insufficient"
    else:
        snapshot = lambda: (128, 128 + required - 1, 128 + required - 1)
        reason = "descriptor_capacity_insufficient"
    monkeypatch.setattr(control_module, "_source_descriptor_capacity_snapshot", snapshot)
    monkeypatch.setattr(control_module, "_source_descriptor_process_eligible", lambda: True)

    with pytest.raises(control_module.InstallationRefused, match=reason):
        case.ports.preflight_source_descriptor_capacity(
            prepare_roots, changes, case.backup, inventory_peak_for_capacity,
        )
    with pytest.raises(control_module.InstallationRefused, match=reason):
        case.ports.prepare(
            prepare_roots, changes, payloads, case.backup, "insufficient-headroom",
            source_inventory_fd_peak=inventory_peak_for_capacity,
        )

    assert not list(case.backup_root.iterdir())


def test_source_descriptor_capacity_covers_control_discovery_peak(secure_tmp_path):
    module = importlib.import_module("app.ops.bws_control_installation")
    lifecycle = importlib.import_module("app.ops.bws_installation_lifecycle")
    backup_path = secure_tmp_path / "descriptor-bound"
    backup_path.mkdir(mode=0o755)
    backup_info = backup_path.stat()
    backup_root = module.Root(
        str(backup_path), backup_info.st_dev, backup_info.st_ino,
        backup_info.st_uid, backup_info.st_gid, stat.S_IMODE(backup_info.st_mode),
    )
    projection_peak = lifecycle._control_projection_descriptor_bound()
    assert projection_peak == 4 + 16 * (32 + 2 * 33) == 1572

    handle_peak = 1 + len(module._path(backup_root.path, absolute=True)) + 2
    assert module._source_descriptor_peak({}, (), backup_root) == handle_peak + 1 + projection_peak
    assert module._source_descriptor_peak(
        {}, (), backup_root, runtime_fd_already_open=True,
    ) == handle_peak + projection_peak


def test_source_inventory_descriptor_peak_covers_actual_open_stack(monkeypatch, secure_tmp_path):
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    application = _owned_dir(secure_tmp_path / "inventory" / "application")
    control = _owned_dir(secure_tmp_path / "inventory" / "control")
    app_root = _owned_dir(application / "app")
    _owned_dir(application / "scripts")
    nested = app_root / "ops"
    nested.mkdir(mode=0o755)
    nested.chmod(0o755)
    for index in range(6):
        nested = nested / f"unchanged_{index}"
        nested.mkdir(mode=0o755)
        nested.chmod(0o755)
    source = nested / "inventory_source.py"
    source.write_bytes(b"SOURCE = True\n")
    source.chmod(0o644)
    empty = app_root / "deep_empty"
    empty.mkdir(mode=0o755)
    empty.chmod(0o755)
    for index in range(9):
        empty = empty / f"empty_{index}"
        empty.mkdir(mode=0o755)
        empty.chmod(0o755)

    original_open, original_close = os.open, os.close
    open_descriptors: set[int] = set()
    observed_peak = 0

    def tracked_open(*args, **kwargs):
        nonlocal observed_peak
        descriptor = original_open(*args, **kwargs)
        open_descriptors.add(descriptor)
        observed_peak = max(observed_peak, len(open_descriptors))
        return descriptor

    def tracked_close(descriptor):
        open_descriptors.discard(descriptor)
        return original_close(descriptor)

    with monkeypatch.context() as descriptor_ports:
        descriptor_ports.setattr(os, "open", tracked_open)
        descriptor_ports.setattr(os, "close", tracked_close)
        rows, packages, measured_peak, entry_count = transaction._source_file_inventory(
            {"application": application, "control": control},
        )

    assert len(rows) == 1
    assert packages == {"application": ["app", "scripts"], "control": []}
    assert observed_peak > 0
    assert measured_peak >= observed_peak
    assert entry_count >= len(rows)
    assert not open_descriptors


def test_created_deep_source_preflights_held_profile_rescan_capacity(
    monkeypatch, secure_tmp_path,
):
    deep_directory = "app/ops/" + "/".join(["d"] * 40)
    case = _full_source_manifest_case(
        monkeypatch, secure_tmp_path, channel="dev", generated_count=1,
        unchanged_core=("app/ops/postgres_deploy_linux.py",
                        "app/ops/bws_installation_admission.py"),
        generated_directory=deep_directory,
    )
    control_module = importlib.import_module("app.ops.bws_control_installation")
    current_roots = {
        "application": case.app_root,
        "control": Path(case.roots["control"].path),
    }
    _old_files, _old_packages, current_fd_peak, _old_entries = (
        transaction._source_file_inventory(current_roots)
    )
    changes, payloads, proof = case.ports.source_manifest(
        case.profile, case.config, case.request, case.roots, case.backup,
    )
    assert len(changes) == 3
    assert any(change.before_sha256 is None for change in changes)
    assert proof["source_inventory_fd_peak"] > current_fd_peak
    prepare_roots = {name: root for name, root in case.roots.items()
                     if name in proof["changed_roots"]}
    required = control_module._source_descriptor_peak(
        prepare_roots, changes, case.backup, proof["source_inventory_fd_peak"],
    )
    monkeypatch.setattr(control_module, "_source_descriptor_capacity_snapshot",
                        lambda: (0, required, required))
    assert not list(case.backup_root.iterdir())
    before_state = {}
    for change in changes:
        path = Path(prepare_roots[change.root].path) / change.path
        before_state[(change.root, change.path)] = (
            None if change.before_sha256 is None else path.read_bytes(),
            None if change.before_sha256 is None else stat.S_IMODE(path.stat().st_mode),
        )

    original_open, original_close = os.open, os.close
    open_descriptors: set[int] = set()
    peak_open_descriptors = 0

    def tracked_open(*args, **kwargs):
        nonlocal peak_open_descriptors
        descriptor = original_open(*args, **kwargs)
        open_descriptors.add(descriptor)
        peak_open_descriptors = max(peak_open_descriptors, len(open_descriptors))
        if len(open_descriptors) > required:
            open_descriptors.remove(descriptor)
            original_close(descriptor)
            raise OSError("synthetic descriptor capacity exceeded")
        return descriptor

    def tracked_close(descriptor):
        open_descriptors.discard(descriptor)
        return original_close(descriptor)

    with monkeypatch.context() as descriptor_ports:
        descriptor_ports.setattr(os, "open", tracked_open)
        descriptor_ports.setattr(os, "close", tracked_close)
        descriptor_ports.setattr(control_module, "_source_descriptor_process_eligible", lambda: True)
        case.ports.preflight_source_descriptor_capacity(
            prepare_roots, changes, case.backup, proof["source_inventory_fd_peak"],
        )
        handle = case.ports.prepare(
            prepare_roots, changes, payloads, case.backup, "deep-rescan-capacity",
            source_inventory_fd_peak=proof["source_inventory_fd_peak"],
            runtime_fd_already_open=True,
        )
        try:
            case.ports.apply(handle)
            rows, packages, measured_fd_peak, entry_count = transaction._source_file_inventory(
                current_roots,
            )
            assert rows == proof["candidate_files"]
            assert packages == {"application": ["app", "scripts"], "control": []}
            assert measured_fd_peak == proof["source_inventory_fd_peak"]
            assert entry_count <= transaction._MAX_SOURCE_ENTRIES
            outcomes = case.ports.compensate(handle)
            assert all(outcome != "refused" for _path, outcome in outcomes)
        finally:
            handle.close()

    assert peak_open_descriptors <= required
    assert not open_descriptors
    assert handle.state == "closed"
    for change in changes:
        path = Path(prepare_roots[change.root].path) / change.path
        before, mode = before_state[(change.root, change.path)]
        if before is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == before
            assert stat.S_IMODE(path.stat().st_mode) == mode
    assert (case.backup_root / "deep-rescan-capacity" / "manifest.json").is_file()


def test_source_manifest_budget_preserves_provenance_and_file_guards(
    monkeypatch, secure_tmp_path,
):
    control_module = importlib.import_module("app.ops.bws_control_installation")
    assert transaction._MAX_MODULES == 190
    assert transaction._MAX_SOURCE_MANIFEST_CHANGES == 2 * transaction._MAX_SOURCE_FILES + 2
    assert transaction._MAX_SOURCE_FILES == control_module._MAX_SOURCE_FILES
    assert transaction._MAX_SOURCE_BYTES == control_module._MAX_SOURCE_FILE_BYTES
    assert transaction._MAX_TOTAL_SOURCE_BYTES == control_module._MAX_TOTAL_SOURCE_BYTES
    assert transaction._MAX_SOURCE_MANIFEST_CHANGES == control_module._MAX_SOURCE_MANIFEST_CHANGES
    case = _full_source_manifest_case(monkeypatch, secure_tmp_path, channel="test")
    changes, payloads, _proof = case.ports.source_manifest(
        case.profile, case.config, case.request, case.roots, case.backup,
    )
    assert len(changes) > 192

    old_source = case.app_root / "app/ops/postgres_deploy_linux.py"
    old_source.write_bytes(old_source.read_bytes() + b"# post-snapshot drift\n")
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        case.ports.source_manifest(case.profile, case.config, case.request, case.roots, case.backup)

    assert payloads
    assert not list(case.backup_root.iterdir())


def test_source_payload_inventory_is_exact_and_independent_json(monkeypatch, tmp_path):
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    app_root = _owned_dir(tmp_path / "target" / "application")
    control_root = _owned_dir(tmp_path / "target" / "control")
    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", control_root)
    launcher_root = _owned_dir(tmp_path / "target" / "launcher")
    backup_root = _owned_dir(tmp_path / "target" / "backup")
    checkout = _owned_dir(tmp_path / "candidate")

    old_sources = {
        "app/__init__.py": b"",
        "app/ops/__init__.py": b"",
        "app/ops/postgres_deploy_linux.py": b"OLD_DEPLOYMENT = True\n",
        "app/ops/bws_installation_admission.py": b"OLD_ADMISSION = True\n",
        "app/ops/unchanged.py": b"UNCHANGED = True\n",
        "scripts/__init__.py": b"",
        "scripts/postgres_deploy_service.py": _SOURCE_ONLY_LAUNCHER,
    }
    candidate_sources = {
        **old_sources,
        "app/ops/postgres_deploy_linux.py": b"raise RuntimeError('candidate module must not execute')\n",
        "app/ops/bws_installation_admission.py": b"raise RuntimeError('candidate module must not execute')\n",
        "app/ops/new_dynamic.py": b"raise RuntimeError('candidate addition must not execute')\n",
    }
    control_old = b"CONTROL_OLD = True\n"
    control_new = b"CONTROL_NEW = True\n"
    for relative, raw in old_sources.items():
        target = app_root / relative
        _owned_dir(target.parent)
        target.write_bytes(raw)
        target.chmod(0o755 if relative == "scripts/postgres_deploy_service.py" else 0o644)
    control_module = control_root / "app/ops/control.py"
    _owned_dir(control_module.parent)
    control_module.write_bytes(control_old)
    contract_path = app_root / "config/secrets/host_secret_contract.json"
    _owned_dir(contract_path.parent)
    old_contract = (Path(__file__).parent / "fixtures" / "host_secret_contract_legacy.json").read_bytes()
    assert hashlib.sha256(old_contract).hexdigest() == (
        "b10ab9cd6674a732cfaa991e4d8c1e90d00a640079e78a5aeea9d32487f3d323"
    )
    candidate_contract = (Path(__file__).resolve().parents[2]
                          / "config/secrets/host_secret_contract.json").read_bytes()
    contract_path.write_bytes(old_contract)
    contract_path.chmod(0o644)

    git_env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
               "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, env=git_env)
    for relative, raw in candidate_sources.items():
        target = checkout / relative
        _owned_dir(target.parent)
        target.write_bytes(raw)
        target.chmod(0o755 if relative == "scripts/postgres_deploy_service.py" else 0o644)
    checkout_contract = checkout / "config/secrets/host_secret_contract.json"
    _owned_dir(checkout_contract.parent)
    checkout_contract.write_bytes(candidate_contract)
    checkout_contract.chmod(0o644)
    candidate_control = checkout / "app/ops/control.py"
    candidate_control.write_bytes(control_new)
    candidate_control.chmod(0o644)
    subprocess.run(["git", "-C", str(checkout), "add", "app", "scripts", "config"], check=True, env=git_env)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", "candidate"], check=True, env=git_env)
    revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, env=git_env).stdout.strip()

    old_launcher = b"legacy launcher bytes\n"
    monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: old_launcher)
    contract_validation: list[bytes] = []
    load_contract = host_secret_contract.load_host_secret_contract_bytes

    def validate_candidate_contract(raw):
        contract_validation.append(raw)
        return load_contract(raw)

    monkeypatch.setattr(host_secret_contract, "load_host_secret_contract_bytes", validate_candidate_contract)
    monkeypatch.setattr(transaction, "_require_source_only_launcher", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_require_launcher_imports", lambda *_args: None)
    monkeypatch.setattr(transaction, "_require_cleanup_shared_reservation", lambda *_args: None)
    monkeypatch.setattr(transaction, "_require_startup_reservation_release", lambda *_args: None)
    monkeypatch.setattr(transaction, "_cleanup_skip_closure", lambda *_args: "bounded")

    def open_root(path, opened):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(transaction, "_open_absolute_directory", open_root)

    request = {"operation_id": str(uuid.uuid4()), "channel": "dev", "candidate_sha": revision,
               "image_digest": "sha256:" + "b" * 64}
    old_state = transaction._old_disk_state(SimpleNamespace(channel="dev", root=app_root), request)
    assert old_state["contract_sha256"] == hashlib.sha256(old_contract).hexdigest()
    assert old_state["contract_mode"] == 0o644
    test_state = transaction._old_disk_state(
        SimpleNamespace(channel="test", root=app_root), {**request, "channel": "test"}
    )
    assert test_state["contract_sha256"] == old_state["contract_sha256"]
    assert test_state["contract_mode"] == old_state["contract_mode"]
    assert contract_validation == []
    roots = {
        "application": Root(str(app_root), **transaction._root_identity(app_root)),
        "control": Root(str(control_root), **transaction._root_identity(control_root)),
        "launcher": Root(str(launcher_root), **transaction._root_identity(launcher_root)),
    }
    backup = Root(str(backup_root), **transaction._root_identity(backup_root))
    changes, payloads, proof = transaction.candidate_manifest(
        old_state, revision=revision, roots=roots, backup_root=backup,
        git_show=lambda selected_revision, relative: transaction._git_show(checkout, selected_revision, relative),
        git_source_files=lambda selected_revision: transaction._git_source_files(checkout, selected_revision),
        git_file_mode=lambda selected_revision, relative: transaction._git_mode(checkout, selected_revision, relative),
    )

    source_payload_keys = {key for key in payloads if key[0] in {"application", "control"}
                           and key[1].endswith(".py")}
    assert source_payload_keys == {
        ("application", "app/ops/postgres_deploy_linux.py"),
        ("application", "app/ops/bws_installation_admission.py"),
        ("application", "app/ops/new_dynamic.py"),
        ("application", "app/ops/control.py"),
        ("control", "app/ops/control.py"),
    }
    assert payloads[("application", "app/ops/new_dynamic.py")] == candidate_sources["app/ops/new_dynamic.py"]
    assert ("application", "app/ops/unchanged.py") not in payloads
    assert payloads[("application", "config/secrets/host_secret_contract.json")] == candidate_contract
    assert payloads[("launcher", "yggdrasil-bws-deploy")] == candidate_sources[
        "scripts/postgres_deploy_service.py"
    ]
    assert any(change.root == "application" and change.path == "app/ops/new_dynamic.py"
               and change.before_sha256 is None for change in changes)
    assert proof["candidate_files"] and proof["contract_mode"] == 0o644
    assert contract_validation == [candidate_contract]
    assert "app.ops.new_dynamic" not in sys.modules

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction.candidate_manifest(
            old_state, revision=revision, roots=roots, backup_root=backup,
            git_show=lambda selected_revision, relative: (
                b"{}" if relative == "config/secrets/host_secret_contract.json"
                else transaction._git_show(checkout, selected_revision, relative)
            ),
            git_source_files=lambda selected_revision: transaction._git_source_files(checkout, selected_revision),
            git_file_mode=lambda selected_revision, relative: transaction._git_mode(checkout, selected_revision, relative),
        )
    assert contract_validation[-1] == b"{}"

    tree = transaction._git_source_files(checkout, revision)
    deleted = dict(tree)
    deleted.pop("app/ops/unchanged.py")
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction.candidate_manifest(
            old_state, revision=revision, roots=roots, backup_root=backup,
            git_show=lambda selected_revision, relative: transaction._git_show(checkout, selected_revision, relative),
            git_source_files=lambda _selected_revision: deleted,
            git_file_mode=lambda selected_revision, relative: transaction._git_mode(checkout, selected_revision, relative),
        )

    unsupported = dict(tree)
    unsupported["app/ops/new_dynamic.py"] = (unsupported["app/ops/new_dynamic.py"][0], 0o600)
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction.candidate_manifest(
            old_state, revision=revision, roots=roots, backup_root=backup,
            git_show=lambda selected_revision, relative: transaction._git_show(checkout, selected_revision, relative),
            git_source_files=lambda _selected_revision: unsupported,
            git_file_mode=lambda selected_revision, relative: transaction._git_mode(checkout, selected_revision, relative),
        )

    (app_root / "app/ops/unchanged.py").write_bytes(b"drifted\n")
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction.candidate_manifest(
            old_state, revision=revision, roots=roots, backup_root=backup,
            git_show=lambda selected_revision, relative: transaction._git_show(checkout, selected_revision, relative),
            git_source_files=lambda selected_revision: transaction._git_source_files(checkout, selected_revision),
            git_file_mode=lambda selected_revision, relative: transaction._git_mode(checkout, selected_revision, relative),
        )

    contract_path.unlink()
    link_target = tmp_path / "legacy-contract-target.json"
    link_target.write_bytes(old_contract)
    contract_path.symlink_to(link_target)
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._old_disk_state(SimpleNamespace(channel="dev", root=app_root), request)
    contract_path.unlink()
    contract_path.write_bytes(old_contract)
    contract_path.chmod(0o644)


def test_candidate_checkout_recheck_rejects_contract_json_worktree_drift(monkeypatch, secure_tmp_path):
    monkeypatch.setattr(transaction, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(transaction, "_OWNER_GID", os.getegid())
    checkout = _owned_dir(secure_tmp_path / "candidate")
    app = _owned_dir(checkout / "app")
    scripts = _owned_dir(checkout / "scripts")
    (app / "__init__.py").write_bytes(b"")
    (scripts / "__init__.py").write_bytes(b"")
    launcher = scripts / "postgres_deploy_service.py"
    launcher.write_bytes(b"#!/usr/bin/env python3\n")
    launcher.chmod(0o755)
    contract = checkout / "config" / "secrets" / "host_secret_contract.json"
    _owned_dir(contract.parent)
    contract.write_bytes((Path(__file__).resolve().parents[2]
                          / "config/secrets/host_secret_contract.json").read_bytes())
    contract.chmod(0o644)

    git_env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
               "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, env=git_env)
    subprocess.run(["git", "-C", str(checkout), "add", "app", "scripts", "config"],
                   check=True, env=git_env)
    subprocess.run(["git", "-C", str(checkout), "commit", "-q", "-m", "candidate"],
                   check=True, env=git_env)
    revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, env=git_env).stdout.strip()

    transaction._verify_candidate_checkout(checkout, revision)
    contract.write_bytes(contract.read_bytes() + b"\n")

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._verify_candidate_checkout(checkout, revision)


def test_actual_cleanup_and_candidate_launcher_guards_match_production_sources():
    deployment = Path(__file__).resolve().parents[2] / "app/ops/postgres_deploy_linux.py"
    admission = deployment.with_name("bws_installation_admission.py")
    launcher = deployment.parents[2] / "scripts/postgres_deploy_service.py"
    transaction._require_cleanup_shared_reservation(deployment.read_bytes())
    transaction._require_startup_reservation_release(deployment.read_bytes())
    transaction._cleanup_skip_closure(admission.read_bytes())
    transaction._require_source_only_launcher(launcher.read_bytes(), require_preimport_reservation=True)


def test_loaded_source_profile_requires_source_only_runtime_and_valid_cache_paths(monkeypatch, tmp_path):
    _use_source_only_cache_policy(monkeypatch)
    module = _loaded_module(Path("/tmp/app/ops/example.py"))
    assert module.__cached__.startswith("/dev/null/")

    root = _owned_dir(tmp_path / "application")
    source = root / "app/ops/example.py"
    _owned_dir(source.parent)
    source.write_text("VALUE = 1\n")
    monkeypatch.setattr(sys, "pycache_prefix", None)
    stale_cache = Path(importlib.util.cache_from_source(str(source)))
    monkeypatch.setattr(sys, "pycache_prefix", "/dev/null")
    monkeypatch.setitem(sys.modules, "app.ops.example", SimpleNamespace(
        __file__=str(source), __cached__=str(stale_cache),
    ))
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._source_modules(SimpleNamespace(), {"application": root})

    monkeypatch.setattr(sys, "pycache_prefix", None)
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._source_modules(SimpleNamespace(channel="dev"), {})










def test_live_preflight_keeps_existing_terminal_identity_separate_from_candidate(monkeypatch):
    from app.ops import native_source_admission

    events: list[str] = []
    request = {
        "channel": "dev",
        "candidate_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
    }
    plan = SimpleNamespace(
        revision="c" * 40,
        image_digest="sha256:" + "d" * 64,
        authority_cutover=SimpleNamespace(validate=lambda: events.append("authority_validate")),
    )
    receipt = SimpleNamespace(
        terminal_result="committed", operation_id=str(uuid.uuid4()), stage="committed",
        require_profile=lambda _plan: events.append("receipt_profile"),
    )
    journal = SimpleNamespace(read=lambda: receipt, bound_plan=lambda _operation_id: plan)
    runtime = SimpleNamespace(
        installed_fingerprint="1" * 64, execution_fingerprint="2" * 64,
        running_writers=("api", "worker", "watcher"),
        existing_writers=("api", "worker", "watcher"),
        census_fingerprint="3" * 64, retained_state_fingerprint="4" * 64,
        container_root="/srv/app", vault_overlay="docker-compose.full-host-vault.yml",
    )
    effects = SimpleNamespace(
        config=SimpleNamespace(channel="dev", journal=journal),
        source_identity_runtime_snapshot=lambda *_args, **_kwargs: events.append("census") or runtime,
        quiescent=lambda: events.append("quiescent") or True,
    )
    monkeypatch.setattr(native_source_admission, "require_terminal_deployment", lambda _effects: None)

    snapshot = transaction._current_writer_snapshot(effects, request)

    assert snapshot.terminal_revision == "c" * 40
    assert snapshot.terminal_image_digest == "sha256:" + "d" * 64
    assert snapshot.terminal_revision != request["candidate_sha"]
    assert snapshot.terminal_image_digest != request["image_digest"]
    assert events == ["receipt_profile", "authority_validate", "census", "quiescent"]


def _transaction_fixture(
    *, channel="dev", config_override=None,
    preflight_error=False, preflight_gate_error: str | None = None,
    descriptor_capacity_error=False,
    terminal_identity_drift: str | None = None, apply_error=False,
    compensation_complete=True, profile_mismatch=False, profile_error=False, retire_error=False,
    channel_lock_error=False, preflight_drift_at: int | None = None,
    profile_drift_at: int | None = None, profile_error_at: int | None = None,
    stop_old_error=False, handle_close_error=False, verify_candidate_error=False, **_legacy_options,
):
    events: list[str] = []
    request = {
        "action": "source-installation",
        "operation_id": str(uuid.uuid4()),
        "candidate_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "bundle_name": "transaction-test",
    }
    terminal_operation_id = str(uuid.uuid4())
    preflight_calls = 0
    profile_calls = 0
    old_state = {
        "schema": transaction._OLD_DISK_STATE_SCHEMA,
        "operation_id": request["operation_id"],
        "channel": channel,
        "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"],
        "roots": {
            "application": {"device": 1, "inode": 2, "uid": 0, "gid": 0, "mode": 0o755},
            "control": {"device": 1, "inode": 3, "uid": 0, "gid": 0, "mode": 0o755},
        },
        "source_files": [],
        "source_packages": {"application": ["app", "scripts"], "control": []},
        "contract_sha256": "3" * 64,
        "contract_mode": 0o644,
        "launcher_sha256": "4" * 64,
        "disk_state_sha256": "5" * 64,
    }
    source_raw = b"candidate deployment bytes"
    script_raw = b"candidate launcher source bytes"
    candidate_files = [
        {"root": "application", "path": "app/ops/postgres_deploy_linux.py",
         "sha256": transaction._sha(source_raw), "mode": 0o644, "size": len(source_raw)},
        {"root": "application", "path": "scripts/postgres_deploy_service.py",
         "sha256": transaction._sha(script_raw), "mode": 0o755, "size": len(script_raw)},
    ]
    candidate_modules = [{"module": "app.ops.postgres_deploy_linux", "root": "application",
                          "path": "app/ops/postgres_deploy_linux.py",
                          "sha256": transaction._sha(source_raw), "mode": 0o644}]
    changes = (
        SimpleNamespace(root="application", path="app/ops/postgres_deploy_linux.py",
                        after_sha256=transaction._sha(source_raw), mode=0o644),
        SimpleNamespace(root="application", path="config/secrets/host_secret_contract.json",
                        after_sha256=transaction._sha(b"new contract"), mode=0o644),
        SimpleNamespace(root="launcher", path="yggdrasil-bws-deploy",
                        after_sha256=transaction._sha(b"new launcher"), mode=0o755),
    )
    payloads = {
        ("application", "app/ops/postgres_deploy_linux.py"): source_raw,
        ("application", "config/secrets/host_secret_contract.json"): b"new contract",
        ("launcher", "yggdrasil-bws-deploy"): b"new launcher",
    }
    proof = {"candidate_files": candidate_files, "candidate_modules": [], "contract_mode": 0o644,
             "new_generation_sha256": "8" * 64,
             "source_inventory_fd_peak": 0,
             "changed_roots": ["application", "launcher"]}
    candidate = transaction._candidate_profile(old_state, payloads, proof)
    actual_candidate = {**candidate, "modules": candidate_modules}
    actual_candidate["profile_sha256"] = transaction._sha(json.dumps(
        {key: value for key, value in actual_candidate.items() if key != "profile_sha256"},
        sort_keys=True, separators=(",", ":"),
    ).encode("ascii"))

    class Admission:
        active = False
        receipt = None
        start_authorization = None
        caller_identity = {"launcher_sha256": "4" * 64}

        def __enter__(self):
            self.active = True
            events.append("admission_enter")
            return self

        def __exit__(self, *_args):
            self.active = False
            events.append("admission_exit")

        def complete(self, receipt):
            assert self.active
            assert self.start_authorization is None
            assert effects.lock_active is True or (
                receipt["status"] == "refused_before_backup" and effects.channel_lock_refused
                and effects.owner_marker is None
            )
            self.receipt = receipt
            events.append("admission_complete")

        def authorize_service_start(self, phase, generation_sha256):
            assert self.active and self.start_authorization is None
            self.start_authorization = (phase, generation_sha256)
            events.append("authorize_start_" + phase)

        def confirm_service_start_consumed(self, phase, generation_sha256):
            assert self.active and self.start_authorization == (phase, generation_sha256)
            self.start_authorization = None
            events.append("consume_start_" + phase)

        def revoke_service_start(self):
            if self.start_authorization is not None:
                self.start_authorization = None
                events.append("revoke_start_authorization")

    admission = Admission()

    class Effects:
        operation_id = None
        lock_active = False
        channel_lock_refused = False
        owner_marker = None

        @contextmanager
        def channel_lock(self, *, journal, owner_marker, retire_terminal):
            assert journal is config.journal and retire_terminal is False
            if channel_lock_error:
                self.channel_lock_refused = True
                events.append("channel_lock_refused")
                raise RuntimeError("synthetic channel lock acquisition refusal")
            self.owner_marker = owner_marker
            self.lock_active = True
            events.append("channel_lock_enter")
            try:
                yield
            finally:
                self.lock_active = False
                events.append("channel_lock_exit")

        def channel_lock_owner(self):
            return (json.dumps(self.owner_marker, sort_keys=True) + "\n").encode()

    effects = Effects()

    class Handle:
        state = "prepared"
        compensation_attempted = False
        compensation_complete = None
        _backup_files = {"manifest.json": SimpleNamespace(data=b"synthetic backup manifest")}

        def close(self):
            events.append("handle_close_failed" if handle_close_error else "handle_close")
            if handle_close_error:
                raise RuntimeError("synthetic handle close failure")
            self.state = "closed"

    handle = Handle()

    class Service:
        phase = "unqualified"
        runtime_context_started = False
        runtime_close_completed = False
        old_token = "5" * 64
        contract = {"unit": "fixed-test-contract"}
        launcher_before = b"legacy launcher bytes"
        launcher_after = b"new launcher"
        old_pid = 123

        @contextmanager
        def retained_runtime(self):
            self.runtime_context_started = True
            events.append("runtime_enter")
            try:
                yield
            finally:
                self.runtime_close_completed = True
                events.append("runtime_close")

        def qualify_old(self, **_kwargs):
            assert admission.active
            self.phase = "qualified"
            events.append("qualified_old")

        def require_old_kernel(self, *, launcher_content):
            assert self.phase == "qualified"
            assert launcher_content in {self.launcher_before, self.launcher_after}
            events.append("require_old_kernel_after_stage" if launcher_content == self.launcher_after
                          else "require_old_kernel_after_compensation")

        def stop_old(self):
            assert admission.active and self.phase == "qualified"
            if stop_old_error:
                events.append("stop_old_refused")
                raise RuntimeError("synthetic stop refusal")
            self.phase = "stopped_checked"
            events.append("stop_old")

        def require_stopped(self):
            assert self.phase in {"stopped_checked", "new_stopped_checked"}
            events.append("require_stopped")

        def start_new(self):
            self.require_stopped()
            self.phase = "start_requested"
            events.append("start_new")

        def require_new_kernel(self):
            self.phase = "new_kernel_checked"
            events.append("new_kernel")
            return "6" * 64

        def require_same_new_kernel(self):
            assert self.phase == "new_kernel_checked"
            events.append("same_new_kernel")

        def stop_new(self):
            assert self.phase == "new_kernel_checked"
            self.phase = "new_stopped_checked"
            events.append("stop_new")

        def stop_failed_start_if_exact(self):
            assert self.phase == "start_requested"
            self.phase = "new_stopped_checked"
            events.append("stop_failed_start")

    service = Service()
    current = {"profile": actual_candidate}

    class Ports:
        def verify_caller_checkout(self, _request):
            events.append("verify_caller_checkout")

        def configuration(self, channel):
            assert channel == config.channel
            return config

        def effects(self, _config):
            return effects

        def admission(self, _channel, _request):
            return admission

        def cleanup_callers(self, channel):
            assert channel == config.channel and admission.active
            events.append("cleanup_caller_census")

        def preflight(self, _effects, _selected_request):
            nonlocal preflight_calls
            preflight_calls += 1
            events.append("preflight")
            if preflight_gate_error is not None:
                transaction._refuse_prebackup_gate(preflight_gate_error)
            if preflight_error:
                raise RuntimeError("synthetic census refusal")
            terminal_revision = "c" * 40
            terminal_image_digest = "sha256:" + "d" * 64
            if terminal_identity_drift is not None and preflight_calls >= 2:
                if terminal_identity_drift == "revision":
                    terminal_revision = "e" * 40
                else:
                    terminal_image_digest = "sha256:" + "f" * 64
            snapshot = transaction._WriterSnapshot(
                channel=channel,
                terminal_revision=terminal_revision,
                terminal_image_digest=terminal_image_digest,
                terminal_operation_id=terminal_operation_id,
                terminal_stage="committed",
                installed_fingerprint="1" * 64,
                execution_fingerprint="2" * 64,
                running_writers=("api", "worker", "watcher"),
                existing_writers=("api", "worker", "watcher"),
                census_fingerprint="3" * 64,
                retained_state_fingerprint=("9" * 64 if preflight_drift_at is not None
                                            and preflight_calls >= preflight_drift_at else "4" * 64),
                container_root="/srv/app",
                vault_overlay="docker-compose.full-host-vault.yml",
            )
            return snapshot

        def verify_candidate(self, _config, _request):
            assert admission.active
            events.append("verify_candidate")
            if verify_candidate_error:
                raise RuntimeError("synthetic private path and secret candidate refusal")

        def old_state(self, _config, _request):
            events.append("old_disk_state")
            return old_state

        def roots(self, _config, _profile):
            return ({"application": "app-root", "control": "control-root",
                     "launcher": "launcher-root"}, "backup-root")

        def source_manifest(self, *_args):
            events.append("source_manifest")
            return changes, payloads, proof

        def preflight_source_descriptor_capacity(self, *_args):
            events.append("descriptor_capacity")
            if descriptor_capacity_error:
                transaction._refuse_prebackup_gate("descriptor_capacity")

        def service(self, _channel):
            return service

        def verify_caller_sources(self, _request):
            events.append("verify_caller_sources")

        def prepare(self, *_args, **_kwargs):
            events.append("prepare")
            return handle

        def apply_targets(self, selected, target_keys):
            assert selected is handle and admission.active
            if target_keys == (("launcher", "yggdrasil-bws-deploy"),):
                events.append("apply_launcher")
                selected.state = "partially_installed"
            else:
                assert ("application", "app/ops/postgres_deploy_linux.py") in target_keys
                events.append("apply_source")
                selected.state = "installed"
                current["profile"] = actual_candidate
                if apply_error:
                    raise RuntimeError("synthetic source apply failure")
            return selected

        def profile(self, _channel, _request):
            nonlocal profile_calls
            profile_calls += 1
            events.append("profile_candidate")
            if profile_calls == 3:
                events.append("profile_after_runtime_close")
            if profile_calls == profile_error_at:
                raise RuntimeError("synthetic profile callback failure")
            if profile_calls == profile_drift_at:
                return {**actual_candidate, "contract_sha256": "f" * 64}
            if profile_mismatch and profile_calls == 1:
                return {**actual_candidate, "contract_sha256": "f" * 64}
            if profile_error:
                raise RuntimeError("profile callback was unexpectedly called")
            return current["profile"]

        def compensate(self, selected):
            assert selected is handle
            events.append("compensate_same_handle")
            selected.compensation_attempted = True
            selected.compensation_complete = compensation_complete
            if compensation_complete:
                selected.state = "compensated"
                current["profile"] = old_state
            return ()

        def retire(self, _effects, _owner):
            assert admission.active and effects.lock_active is False
            events.append("retire_channel_owner")
            if retire_error:
                raise RuntimeError("synthetic channel-owner retirement failure")

    config = config_override or SimpleNamespace(channel=channel, root=Path("/srv/app"), journal=object())
    ports = Ports()
    return request, ports, admission, service, events, old_state, candidate


def _install_synthetic_real_lifecycle_service(monkeypatch, ports, old_state, tmp_path, *, channel="dev"):
    control_root = (tmp_path.resolve() / "empty-control-root").resolve()
    control_root.mkdir(mode=0o755)
    root_info = control_root.stat()
    owner_uid, owner_gid = os.getuid(), os.getgid()
    monkeypatch.setattr(transaction, "_CONTROL_DIRECTORY", control_root)
    monkeypatch.setattr(bws_installation_lifecycle, "CONTROL_DIRECTORY", str(control_root))
    monkeypatch.setattr(bws_installation_lifecycle, "_CONTROL_OWNER_UID", owner_uid)
    monkeypatch.setattr(bws_installation_lifecycle, "_CONTROL_OWNER_GID", owner_gid)
    old_state["roots"]["application"].update(uid=owner_uid, gid=owner_gid)
    old_state["roots"]["control"] = {
        "device": root_info.st_dev, "inode": root_info.st_ino,
        "uid": root_info.st_uid, "gid": root_info.st_gid, "mode": root_info.st_mode & 0o777,
    }

    service = bws_installation_lifecycle.FixedBwsService(
        unit=f"yggdrasil-bws-deploy@{channel}.service", channel=channel,
    )
    service.runtime_version = (1, 2, 3, 4, 5, 6, 7, 8)
    service.retained_runtime = lambda: nullcontext()
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    monkeypatch.setattr(service, "_call", lambda method, _signature: (
        f"/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40{channel}_2eservice"
        if method == "GetUnit" else pytest.fail("unexpected systemd method")
    ))
    monkeypatch.setattr(service, "_state", lambda active: 123 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    monkeypatch.setattr(bws_installation_lifecycle, "_pid_token", lambda *_args: "5" * 64)

    start = [bws_installation_lifecycle.LAUNCHER,
             [bws_installation_lifecycle.LAUNCHER, "serve", channel], False, 1, 2, 3, 4, 5, 1, 0]
    cleanup = [bws_installation_lifecycle.LAUNCHER,
               [bws_installation_lifecycle.LAUNCHER, "cleanup", channel], False, 1, 2, 3, 4, 5, 1, 0]
    properties = {
        ("Unit", "Id"): service.unit,
        ("Unit", "LoadState"): "loaded",
        ("Service", "Type"): "simple",
        ("Service", "User"): "root",
        ("Service", "Group"): "root",
        ("Service", "KillMode"): "control-group",
        ("Service", "Restart"): "on-failure",
        ("Unit", "OnFailure"): [],
        ("Unit", "OnSuccess"): [],
        ("Unit", "TriggeredBy"): [],
        ("Service", "Environment"): [],
        ("Service", "EnvironmentFiles"): [],
    }
    monkeypatch.setattr(service, "_get", lambda interface, name, _signature: properties[(interface, name)])
    monkeypatch.setattr(service, "_exec", lambda name, _action=None: (
        start if name == "ExecStart" else cleanup if name == "ExecStopPost" else []
    ))
    ports.service = lambda _channel: service
    return service, control_root, properties


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_empty_control_root_qualifies_through_lifecycle_gate(secure_tmp_path, monkeypatch, channel):
    request, ports, _admission, _service, events, old_state, _candidate = _transaction_fixture(channel=channel)
    service, _control_root, _properties = _install_synthetic_real_lifecycle_service(
        monkeypatch, ports, old_state, secure_tmp_path, channel=channel,
    )
    revalidation_calls = 0
    original_revalidation = service.revalidate_empty_control_configuration

    def track_revalidation():
        nonlocal revalidation_calls
        revalidation_calls += 1
        original_revalidation()

    service.revalidate_empty_control_configuration = track_revalidation

    def stop_before_synthetic_backup(*_args, **_kwargs):
        events.append("synthetic_stop_before_backup")
        raise RuntimeError("synthetic stop after empty-root revalidation")

    ports.prepare = stop_before_synthetic_backup

    result = transaction._execute_source_installation(channel, request, ports)

    assert result["source_installation"]["status"] == "refused_before_stop"
    assert result["source_installation"].get("prebackup_gate") is None
    assert service.control_inventory_empty is True
    assert service.phase == "qualified"
    assert service.contract is not None
    assert revalidation_calls == 1
    assert "synthetic_stop_before_backup" in events
    assert result["source_installation"]["backup_manifest_sha256"] is None
    assert not {"prepare", "apply_launcher", "stop_old", "apply_source"} & set(events)


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize(
    "drift", [
        "loader_package", "root_identity", "foreign_hint", "root_search_path",
        "root_search_path_trailing_slash", "environment_file_hint",
        "before_backup_loader_package", "before_backup_root_identity",
        "before_backup_foreign_hint", "before_backup_root_search_path",
        "before_backup_root_search_path_trailing_slash",
    ],
)
def test_empty_control_root_refuses_identity_or_inventory_drift_before_backup(
    secure_tmp_path, monkeypatch, channel, drift,
):
    request, ports, _admission, _service, events, old_state, _candidate = _transaction_fixture(channel=channel)
    service, control_root, properties = _install_synthetic_real_lifecycle_service(
        monkeypatch, ports, old_state, secure_tmp_path, channel=channel,
    )
    original = bws_installation_lifecycle._discovered_control_projection
    prebackup_revalidation_calls = 0
    original_revalidation = service.revalidate_empty_control_configuration

    def track_revalidation():
        nonlocal prebackup_revalidation_calls
        prebackup_revalidation_calls += 1
        original_revalidation()

    service.revalidate_empty_control_configuration = track_revalidation
    calls = 0

    def add_drift():
        kind = drift.removeprefix("before_backup_")
        if kind == "loader_package":
            (control_root / "app").mkdir(mode=0o755)
        elif kind == "root_identity":
            moved = control_root.with_name("moved-control-root")
            control_root.rename(moved)
            control_root.mkdir(mode=0o755)
        elif kind == "foreign_hint":
            # A literal suffix used to be truncated as a path separator.
            properties[("Service", "Environment")].append(
                f"PYTHONPATH={control_root}/app;legacy"
            )
            return
        elif kind == "environment_file_hint":
            properties[("Service", "EnvironmentFiles")].append(
                [f"{control_root}/app.env", False]
            )
            return
        else:
            hint = (
                str(control_root) + ("/" if kind == "root_search_path_trailing_slash" else "")
                if kind in {"root_search_path", "root_search_path_trailing_slash"}
                else f"{control_root}/unclassified-loader"
            )
            properties[("Service", "Environment")].append(f"PYTHONPATH={hint}")

    if drift.startswith("before_backup_"):
        original_verify_sources = ports.verify_caller_sources

        def verify_sources_then_drift(selected_request):
            original_verify_sources(selected_request)
            add_drift()

        ports.verify_caller_sources = verify_sources_then_drift
    else:
        def introduce_drift(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                add_drift()
            return original(*args, **kwargs)

        monkeypatch.setattr(bws_installation_lifecycle, "_discovered_control_projection", introduce_drift)

    result = transaction._execute_source_installation(channel, request, ports)

    assert result["source_installation"]["status"] == "refused_before_backup"
    final = drift.startswith('before_backup_')
    kind = drift.removeprefix('before_backup_')
    role, guard = (
        ('app_slot', 'present') if kind == 'loader_package' else
        ('empty_root', 'identity') if kind == 'root_identity' else
        ('hints', 'environment_files_hint') if kind == 'environment_file_hint' else
        ('hints', 'environment_hint')
    )
    assert result['source_installation']['prebackup_gate'] == (
        'old_kernel_' + ('empty_control' if final else 'initial') + '_root_control__'
        + '__'.join(('captured_empty', 'old' if final else 'proposed', role, guard))
    )
    if drift.startswith("before_backup_"):
        assert prebackup_revalidation_calls == 1
        assert service.phase == "qualified"
    else:
        assert calls == 2
        assert prebackup_revalidation_calls == 0
        assert service.phase == "qualifying"
    assert not {"prepare", "apply_launcher", "stop_old", "apply_source"} & set(events)


def _ordinary_terminal_installation_fixture(
    tmp_path, monkeypatch, channel, *, terminal=True, legacy=False, journal_root=None,
):
    """Keep native config, terminal readers and the real Docker census in the transaction."""
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan

    root = tmp_path.resolve() / "checkout"
    (root / "config/deploy").mkdir(parents=True)
    runtime_path = root / "runtime.env"
    vault_root = str(tmp_path.resolve() / "existing-vault")
    container_root = "/app/vault" if legacy else vault_root
    vault_overlay = ("docker-compose.legacy-vault.yml" if legacy else "docker-compose.full-host-vault.yml")
    database = "postgresql+psycopg://app@db:5432/app_" + channel
    pin_path = root / "config/deploy" / (channel + ".env")
    pin_path.write_text("VAULT_HOST_ROOT=" + vault_root + "\n")
    runtime_path.write_text("LLM_PROVIDER=ollama\nDATABASE_URL=" + database + "\n")
    (root / "config/runtime.defaults.env").write_text(
        "EMBED_PROVIDER=ollama\nEMBED_MODEL=installed\nSTORE_BACKEND=pg\n"
    )
    for name in (
        "docker-compose.yaml", f"docker-compose.{channel}.yml", "docker-compose.bws.yml",
        "docker-compose.full-host-vault.yml", "docker-compose.test-vault.yml",
        "docker-compose.legacy-vault.yml",
    ):
        (root / name).write_text("services: {}\n")
    native_config = {
        "root": str(root), "data_directory": str(tmp_path.resolve() / "data"),
        "uid": max(os.geteuid(), 1), "gid": max(os.getegid(), 1),
        "organization_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
        "runtime_env_file": str(runtime_path),
    }
    # Substitute the root-owned host-file boundary, keeping LinuxConfig.load's
    # complete validation and every journal/receipt/request reader real.
    def private_config(path):
        assert path == Path("/etc/yggdrasil/bws-deploy") / (channel + ".json")
        return dict(native_config)

    monkeypatch.setattr(linux, "_private_json", private_config)
    journal = DeployJournal((journal_root or tmp_path).resolve() / "journal", channel)
    monkeypatch.setattr(linux.LinuxConfig, "journal", property(lambda _self: journal))
    config = linux.LinuxConfig.load(channel)
    plan = DeployPlan(channel, "c" * 40, ("db",), ("postgres-db",),
                      image_digest="sha256:" + "d" * 64)
    terminal_id = str(uuid.uuid4())
    journal.bind_request(terminal_id, plan, False, create=True)
    for stage in (("prepared", "preflighted", "materialized", "activating", "committed")
                  if terminal else ("prepared",)):
        journal.write(terminal_id, stage)

    request, ports, admission, service, events, old_state, candidate = _transaction_fixture(
        channel=channel, config_override=config,
    )
    effects = ports.effects(config)
    effects.__dict__.update(linux.LinuxEffects(config).__dict__)
    for method in (
        "source_identity_runtime_snapshot", "environment", "compose", "source_compose_invocation",
        "quiescent", "_running_one_shots",
    ):
        setattr(effects, method, getattr(linux.LinuxEffects, method).__get__(effects))
    rows = []
    for index, name in enumerate(("api", "worker", "watcher"), 1):
        rows.append({
            "Id": f"{index:064x}", "Image": "sha256:" + f"{index:064x}",
            "Config": {
                "Image": "installed:" + plan.revision, "User": f"{config.uid}:{config.gid}",
                "Env": [
                    "DATABASE_URL=" + database, "EMBED_PROVIDER=ollama", "EMBED_MODEL=installed",
                    "LLM_PROVIDER=ollama", "STORE_BACKEND=pg", "PKM_ENVIRONMENT=" + channel,
                    "VAULT_ROOT=" + container_root, "VAULT_ROOT_DEV=" + container_root,
                    "VAULT_ROOT_TEST=" + container_root, "WATCHER_VAULT_PATH=" + container_root,
                ],
                "Labels": {"com.docker.compose.project": "pkm-" + channel,
                           "com.docker.compose.service": name, "com.docker.compose.oneoff": "False"},
            },
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
            "State": {"Status": "running", "Running": True, "Paused": False,
                      "Restarting": False, "Pid": index, "StartedAt": "installed"},
            "Mounts": [{"Type": "bind", "Source": vault_root, "Destination": container_root,
                        "Mode": "", "RW": True, "Propagation": "rprivate"}],
        })
    compose_calls = []

    def command(argv, **kwargs):
        if argv[1:3] == ["ps", "--all"]:
            if "label=com.docker.compose.oneoff=True" in argv:
                return ""
            return "\n".join(row["Id"] for row in rows)
        if argv[1] == "inspect":
            return json.dumps(rows)
        assert argv[1] == "compose"
        compose_calls.append((argv, kwargs["env"]))
        if "ps" in argv:
            return json.dumps([{"Service": row["Config"]["Labels"]["com.docker.compose.service"],
                                "State": row["State"]["Status"]} for row in rows])
        assert argv[-3:] == ["config", "--format", "json"]
        assert kwargs["env"]["VAULT_HOST_ROOT"] == vault_root
        assert str(root / vault_overlay) in argv
        if channel == "test":
            assert str(root / "docker-compose.test-vault.yml") in argv
        environment = dict(entry.split("=", 1) for entry in rows[0]["Config"]["Env"])
        return json.dumps({"services": {name: {
            "labels": {"com.agentic-pkm.mvr05.db-role": "client"}, "environment": environment,
        } for name in ("api", "worker", "watcher")}})

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setenv("INSTANCE_OWNERSHIP_HOST_STATE_DIR", str(tmp_path.resolve() / "ownership"))
    for key in ("DATABASE_URL", "DB_DSN", "POSTGRES_PASSWORD", "PGPASSWORD", "PGPASSFILE",
                "PGSERVICE", "PGSERVICEFILE", "DOCKER_CONTEXT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    preflights = []

    def preflight(selected_effects, selected_request):
        snapshot = transaction._NativePorts.preflight(ports, selected_effects, selected_request)
        preflights.append(snapshot)
        events.append("native_preflight")
        return snapshot

    ports.preflight = preflight
    return SimpleNamespace(
        request=request, ports=ports, admission=admission, service=service, events=events,
        journal=journal, plan=plan, terminal_id=terminal_id, rows=rows, pin=pin_path,
        runtime=runtime_path, native_config=native_config, preflights=preflights,
        compose_calls=compose_calls, old_state=old_state, candidate=candidate,
    )


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("legacy", [False, True], ids=["full-host", "legacy-mount"])
def test_source_installation_accepts_ordinary_terminal_deployment_without_cutover(
    tmp_path, monkeypatch, channel, legacy,
):
    fixture = _ordinary_terminal_installation_fixture(tmp_path, monkeypatch, channel, legacy=legacy)
    assert not any(entry.startswith("VAULT_HOST_ROOT=") for entry in fixture.rows[0]["Config"]["Env"])
    assert fixture.plan.authority_cutover is None and fixture.plan.principal_cutover is False
    assert fixture.journal.operation_request(fixture.terminal_id)[0]["bootstrap"] is False

    result = transaction._execute_source_installation(channel, fixture.request, fixture.ports)

    assert result["source_installation"].get("prebackup_gate") is None
    assert result["source_installation"]["status"] == "installed"
    assert fixture.admission.receipt == result["source_installation"]
    assert len(fixture.preflights) == 4 and len(set(fixture.preflights)) == 1
    snapshot = fixture.preflights[0]
    assert snapshot.terminal_revision == fixture.plan.revision != fixture.request["candidate_sha"]
    assert snapshot.terminal_image_digest == fixture.plan.image_digest != fixture.request["image_digest"]
    assert snapshot.terminal_operation_id == fixture.terminal_id
    assert snapshot.running_writers == snapshot.existing_writers == ("api", "watcher", "worker")
    assert fixture.compose_calls
    assert fixture.events.index("apply_launcher") < fixture.events.index("stop_old")
    assert fixture.events.index("stop_old") < fixture.events.index("apply_source")
    assert fixture.events.index("handle_close") < fixture.events.index("runtime_close")
    assert fixture.events.index("runtime_close") < fixture.events.index("admission_complete")
    assert fixture.events[-2:] == ["retire_channel_owner", "admission_exit"]


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("fault", [
    "missing_plan", "mismatched_plan", "native_owner", "missing_context", "foreign_context",
    "wrong_channel", "wrong_root_selector", "foreign_host_selector", "unknown_writer", "transitioning_writer",
    "drifting_owner", "drifting_context", "drifting_writer",
])
def test_ordinary_terminal_installation_refuses_unproven_or_drifting_owner_state(
    tmp_path, monkeypatch, channel, fault,
):
    fixture = _ordinary_terminal_installation_fixture(tmp_path, monkeypatch, channel)
    native_preflight = fixture.ports.preflight
    calls = 0

    def preflight(effects, request):
        nonlocal calls
        calls += 1
        if calls == (2 if fault.startswith("drifting_") else 1):
            request_path = fixture.journal.directory / (channel + ".request.json")
            if fault == "missing_plan":
                request_path.unlink()
            elif fault == "mismatched_plan":
                raw = json.loads(request_path.read_text())
                raw["operation_id"] = str(uuid.uuid4())
                request_path.write_text(json.dumps(raw))
            elif fault in {"native_owner", "drifting_owner"}:
                fixture.native_config["uid"] += 1
            elif fault == "missing_context":
                fixture.pin.write_text("")
            elif fault == "foreign_context":
                fixture.rows[0]["Mounts"][0]["Source"] += "-foreign"
            elif fault in {"wrong_channel", "wrong_root_selector"}:
                selector = "PKM_ENVIRONMENT" if fault == "wrong_channel" else "VAULT_ROOT"
                fixture.rows[0]["Config"]["Env"] = [
                    entry if not entry.startswith(selector + "=") else selector + "=foreign"
                    for entry in fixture.rows[0]["Config"]["Env"]
                ]
            elif fault == "foreign_host_selector":
                fixture.rows[0]["Config"]["Env"].append("VAULT_HOST_ROOT=/foreign")
            elif fault == "unknown_writer":
                row = json.loads(json.dumps(fixture.rows[0]))
                row["Id"] = "f" * 64
                row["Config"]["Labels"]["com.docker.compose.service"] = "unclassified-writer"
                fixture.rows.append(row)
            elif fault == "transitioning_writer":
                fixture.rows[0]["State"]["Restarting"] = True
            elif fault == "drifting_context":
                fixture.runtime.write_text(fixture.runtime.read_text() + "# changed context\n")
            elif fault == "drifting_writer":
                fixture.rows[0]["State"]["Pid"] += 100
        return native_preflight(effects, request)

    fixture.ports.preflight = preflight
    result = transaction._execute_source_installation(channel, fixture.request, fixture.ports)

    assert result["source_installation"]["status"] == "refused_before_backup"
    assert result["source_installation"]["prebackup_gate"] == (
        "qualified_writer_snapshot" if fault.startswith("drifting_") else "current_writer_snapshot"
    )
    assert calls == (2 if fault.startswith("drifting_") else 1)
    assert not {"prepare", "apply_launcher", "stop_old", "apply_source", "start_new"} & set(fixture.events)


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_ordinary_terminal_state_is_rechecked_after_handle_and_runtime_close(tmp_path, monkeypatch, channel):
    fixture = _ordinary_terminal_installation_fixture(tmp_path, monkeypatch, channel)
    native_preflight = fixture.ports.preflight

    def preflight(effects, request):
        if len(fixture.preflights) == 3:
            assert "handle_close" in fixture.events and "runtime_close" in fixture.events
            fixture.rows[0]["State"]["Pid"] += 100
        return native_preflight(effects, request)

    fixture.ports.preflight = preflight
    result = transaction._execute_source_installation(channel, fixture.request, fixture.ports)

    assert result["source_installation"]["status"] == "unknown"
    assert fixture.events.index("runtime_close") < fixture.events.index("stop_new")
    assert "retire_channel_owner" not in fixture.events
    assert "compensate_same_handle" not in fixture.events


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("fault", ["invalid_cutover", "unresolved_operation", "unknown_operation"])
def test_ordinary_installation_preserves_cutover_and_unknown_operation_refusals(
    tmp_path, monkeypatch, channel, fault,
):
    from app.ops.postgres_deploy import PostgresDeployError

    fixture = _ordinary_terminal_installation_fixture(
        tmp_path, monkeypatch, channel, terminal=fault == "invalid_cutover",
    )
    if fault == "invalid_cutover":
        path = fixture.journal.directory / (channel + ".request.json")
        raw = json.loads(path.read_text())
        raw["plan"]["authority_cutover"] = {
            "binding_id": "existing", "root": "/", "ownership_root": "/srv/owner",
        }
        path.write_text(json.dumps(raw))
    elif fault == "unknown_operation":
        fixture.journal.fence_unknown(fixture.terminal_id, fixture.plan, channel_lock_identity=(1, 2, 3))
    before = {path.name: path.read_bytes() for path in fixture.journal.directory.iterdir()}

    result = transaction._execute_source_installation(channel, fixture.request, fixture.ports)

    assert result["source_installation"]["status"] == "refused_before_backup"
    assert not {"prepare", "stop_old", "apply_source", "start_new"} & set(fixture.events)
    assert {path.name: path.read_bytes() for path in fixture.journal.directory.iterdir()} == before
    if fault == "unknown_operation":
        with pytest.raises(PostgresDeployError):
            fixture.journal.bound_plan(fixture.terminal_id)
        with pytest.raises(PostgresDeployError):
            fixture.journal.bind_request(fixture.terminal_id, fixture.plan, False, create=True)
        assert fixture.journal.unknown_tombstone(fixture.terminal_id)["outcome"] == "unknown"


def test_preflight_refuses_before_backup_or_stop_without_exact_owner_census_and_generations():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(preflight_error=True)

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
    assert receipt["old_generation_sha256"] is None
    assert receipt["new_generation_sha256"] is None
    assert "prepare" not in events and "stop_old" not in events and "apply" not in events
    assert events.index("admission_enter") < events.index("cleanup_caller_census")
    assert events.index("cleanup_caller_census") < events.index("preflight")
    assert events.index("preflight") < events.index("admission_complete")
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert events.index("channel_lock_exit") < events.index("retire_channel_owner")
    assert admission.receipt == receipt


@pytest.mark.parametrize(("options", "expected_gate"), [
    ({"preflight_error": True}, "current_writer_snapshot"),
    ({"channel_lock_error": True}, "channel_lock_entry"),
    ({"preflight_gate_error": "authority_cutover"}, "authority_cutover"),
    ({"descriptor_capacity_error": True}, "descriptor_capacity"),
], ids=["current_writer_snapshot", "channel_lock_entry", "authority_cutover", "descriptor_capacity"])
def test_prebackup_refusal_receipt_reports_finite_gate(options, expected_gate):
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(**options)

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
    assert receipt["prebackup_gate"] == expected_gate
    assert receipt["old_generation_sha256"] is None
    assert receipt["new_generation_sha256"] is None
    assert receipt["backup_manifest_sha256"] is None
    assert "prepare" not in events and "stop_old" not in events and "apply" not in events
    if expected_gate == "descriptor_capacity":
        assert events.index("source_manifest") < events.index("descriptor_capacity")
        assert "qualified_old" not in events
    assert admission.receipt == receipt


@pytest.mark.parametrize("fault", ["missing-port", "missing-peak", "bool-peak", "negative-peak"])
def test_invalid_descriptor_port_or_peak_refuses_before_service(fault):
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture()
    if fault == "missing-port":
        ports.preflight_source_descriptor_capacity = None
    else:
        manifest = ports.source_manifest
        def invalid_manifest(*args):
            changes, payloads, proof = manifest(*args)
            proof = dict(proof)
            if fault == "missing-peak":
                proof.pop("source_inventory_fd_peak")
            else:
                proof["source_inventory_fd_peak"] = True if fault == "bool-peak" else -1
            return changes, payloads, proof
        ports.source_manifest = invalid_manifest
    result = transaction._execute_source_installation("dev", request, ports)["source_installation"]
    assert result["status"] == "refused_before_backup"
    assert result["prebackup_gate"] == "descriptor_capacity_unknown"
    assert result == admission.receipt
    assert not {"prepare", "qualified_old", "stop_old", "apply_source"} & set(events)


@pytest.mark.parametrize("reason", ["descriptor_capacity_unknown", "descriptor_capacity_insufficient",
                                    "descriptor_capacity_ineligible", "descriptor_capacity_admission_refused"])
def test_descriptor_refusal_receipt_keeps_only_finite_reason(reason):
    from app.ops.bws_control_installation import InstallationRefused
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture()
    def refuse(*_args):
        raise InstallationRefused(reason)
    ports.preflight_source_descriptor_capacity = refuse
    result = transaction._execute_source_installation("dev", request, ports)["source_installation"]
    assert result["status"] == "refused_before_backup"
    assert result["prebackup_gate"] == reason
    assert result == admission.receipt
    assert not {"prepare", "qualified_old", "stop_old", "apply_source"} & set(events)


def test_second_native_writer_snapshot_error_reports_qualified_gate(monkeypatch):
    from app.ops import native_source_admission

    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture()
    effects = ports.effects(None)
    config = ports.configuration("dev")
    receipt = SimpleNamespace(
        terminal_result="committed", operation_id=str(uuid.uuid4()), stage="committed",
        require_profile=lambda _plan: None,
    )
    plan = SimpleNamespace(
        revision="c" * 40,
        image_digest="sha256:" + "d" * 64,
        authority_cutover=SimpleNamespace(validate=lambda: None),
    )
    config.journal = SimpleNamespace(read=lambda: receipt, bound_plan=lambda _operation_id: plan)
    effects.config = config

    def fail_runtime_snapshot(*_args, **_kwargs):
        raise RuntimeError("synthetic private writer census detail")

    effects.source_identity_runtime_snapshot = fail_runtime_snapshot
    effects.quiescent = lambda: True
    monkeypatch.setattr(native_source_admission, "require_terminal_deployment", lambda _effects: None)

    original_preflight = ports.preflight
    preflight_calls = 0

    def preflight(selected_effects, selected_request):
        nonlocal preflight_calls
        preflight_calls += 1
        if preflight_calls == 2:
            return transaction._current_writer_snapshot(selected_effects, selected_request)
        return original_preflight(selected_effects, selected_request)

    ports.preflight = preflight

    result = transaction._execute_source_installation("dev", request, ports)

    selected = result["source_installation"]
    assert selected["status"] == "refused_before_backup"
    assert selected["prebackup_gate"] == "qualified_writer_snapshot"
    assert "synthetic private writer census detail" not in json.dumps(selected, sort_keys=True)
    assert selected["old_generation_sha256"] is None
    assert selected["new_generation_sha256"] is None
    assert selected["backup_manifest_sha256"] is None
    assert "prepare" not in events and "stop_old" not in events and "apply" not in events
    assert admission.receipt == selected


def test_prebackup_refusal_receipt_is_redacted_and_fail_closed():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(
        verify_candidate_error=True,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    public_receipt = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "refused_before_backup"
    assert receipt["prebackup_gate"] == "candidate_verification"
    assert "synthetic private path" not in public_receipt and "secret candidate" not in public_receipt
    assert receipt["old_generation_sha256"] is None
    assert receipt["new_generation_sha256"] is None
    assert receipt["backup_manifest_sha256"] is None
    assert "prepare" not in events and "stop_old" not in events and "apply" not in events
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert admission.receipt == receipt


@pytest.mark.parametrize("mismatch", ["revision", "image"])
def test_preflight_refuses_current_terminal_identity_drift_before_backup_or_effects(mismatch):
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(
        terminal_identity_drift=mismatch,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
    assert receipt["prebackup_gate"] == "qualified_writer_snapshot"
    assert "preflight" in events
    assert "verify_candidate" in events
    assert "prepare" not in events and "stop_old" not in events and "apply" not in events
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert events.index("channel_lock_exit") < events.index("retire_channel_owner")
    assert admission.receipt == receipt


def test_legacy_first_call_uses_old_boundary_without_profile_rpc():
    request, ports, _admission, _service, events, _old, _candidate = _transaction_fixture()

    result = transaction._execute_source_installation("dev", request, ports)

    assert result["source_installation"]["status"] == "installed"
    assert events.index("verify_caller_checkout") < events.index("old_disk_state")
    assert "profile_old" not in events
    assert events.index("old_disk_state") < events.index("prepare")
    baseline_preflight = events.index("preflight")
    qualified_preflight = events.index("preflight", baseline_preflight + 1)
    assert qualified_preflight < events.index("verify_caller_sources") < events.index("prepare")
    assert events.index("prepare") < events.index("apply_launcher") < events.index("stop_old")
    assert events.index("stop_old") < events.index("apply_source")


def test_candidate_launcher_is_staged_before_stop_under_same_handle():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture()

    result = transaction._execute_source_installation("dev", request, ports)

    assert result["source_installation"]["status"] == "installed"
    assert events.index("prepare") < events.index("apply_launcher")
    assert events.index("apply_launcher") < events.index("require_old_kernel_after_stage")
    initial_census = events.index("cleanup_caller_census")
    staged_census = events.index("cleanup_caller_census", initial_census + 1)
    assert events.index("require_old_kernel_after_stage") < staged_census
    assert staged_census < events.index("stop_old")
    assert events.index("stop_old") < events.index("apply_source") < events.index("handle_close")
    assert admission.active is False


def test_native_writer_snapshot_requires_terminal_owner_and_selected_authority_cutover(
    monkeypatch,
):
    from app.ops import native_source_admission

    calls: list[str] = []
    request = {
        "channel": "dev",
        "candidate_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
    }
    receipt = SimpleNamespace(
        terminal_result="committed", operation_id="terminal-operation", stage="committed",
        require_profile=lambda _plan: calls.append("profile-bound"),
    )
    def invalid_cutover():
        calls.append("authority-validate")
        raise RuntimeError("synthetic private authority detail")

    plan = SimpleNamespace(
        revision="c" * 40,
        image_digest="sha256:" + "d" * 64,
        authority_cutover=SimpleNamespace(validate=invalid_cutover),
    )
    journal = SimpleNamespace(read=lambda: receipt, bound_plan=lambda _operation_id: plan)
    effects = SimpleNamespace(
        config=SimpleNamespace(channel="dev", journal=journal),
        source_identity_runtime_snapshot=lambda *_args, **_kwargs: calls.append("snapshot"),
        quiescent=lambda: calls.append("quiescent") or True,
    )
    monkeypatch.setattr(native_source_admission, "require_terminal_deployment",
                        lambda _effects: calls.append("terminal-owner"))

    with pytest.raises(transaction._PrebackupGateRefusal) as refusal:
        transaction._current_writer_snapshot(effects, request)

    assert refusal.value.gate == "authority_cutover"
    assert calls == ["terminal-owner", "profile-bound", "authority-validate"]


def test_candidate_preflight_uses_fixed_local_git_and_docker_environment(monkeypatch, tmp_path):
    from app.ops.bws_installation_lifecycle import ENV as lifecycle_env
    from app.ops.pg_acceptance import IMAGE_REPOSITORY

    revision = "a" * 40
    digest = "sha256:" + "b" * 64
    candidate_root = tmp_path / "candidate-checkout"
    candidate_root.mkdir()
    installed_root = tmp_path / "installed-old-checkout"
    installed_root.mkdir()
    git_calls = []
    source_reads = []
    monkeypatch.setattr(
        transaction.subprocess, "run",
        lambda argv, **kwargs: git_calls.append((argv, kwargs)) or SimpleNamespace(
            returncode=0, stderr=b"", stdout=b"commit\n",
        ),
    )
    monkeypatch.setattr(
        transaction, "_git_show",
        lambda root, selected_revision, path: source_reads.append((root, selected_revision, path))
        or (b"DATABASE_FILE_CREDENTIAL_PROTOCOL = 1\n"
            if path == "app/config/database.py" else b""),
    )
    docker_calls = []

    def command(argv, *, env, timeout):
        docker_calls.append((argv, env, timeout))
        return json.dumps([{
            "Config": {"Labels": {"org.opencontainers.image.revision": revision}},
            "RepoDigests": [IMAGE_REPOSITORY + "@" + digest],
        }])

    monkeypatch.setattr("app.ops.postgres_deploy_linux._command", command)
    transaction._verify_candidate(
        candidate_root,
        {"candidate_sha": revision, "image_digest": digest},
    )

    assert git_calls[0][0][4] == str(candidate_root)
    assert git_calls[0][0][4] != str(installed_root)
    assert source_reads == [(candidate_root, revision, "app/config/database.py")]
    assert git_calls[0][1]["env"]["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin"
    assert git_calls[0][1]["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert docker_calls == [(
        ["docker", "--host", "unix:///var/run/docker.sock", "image", "inspect",
         IMAGE_REPOSITORY + "@" + digest],
        lifecycle_env,
        30,
    )]

    port_calls = []
    ports = object.__new__(transaction._NativePorts)
    ports.caller_root = candidate_root
    ports.verify_caller_checkout = lambda selected: port_calls.append(("checkout", selected))
    monkeypatch.setattr(transaction, "_verify_candidate",
                        lambda root, selected: port_calls.append(("candidate", root, selected)))
    ports.verify_candidate(SimpleNamespace(root=installed_root),
                           {"candidate_sha": revision, "image_digest": digest})
    assert port_calls == [
        ("checkout", {"candidate_sha": revision, "image_digest": digest}),
        ("candidate", candidate_root, {"candidate_sha": revision, "image_digest": digest}),
    ]


def test_candidate_preflight_refuses_missing_file_protocol_before_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(
        transaction.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=b"", stdout=b"commit\n"),
    )
    monkeypatch.setattr(transaction, "_git_show", lambda *_args: b"DATABASE_FILE_CREDENTIAL_PROTOCOL = 2\n")
    monkeypatch.setattr("app.ops.postgres_deploy_linux._command", lambda *_args, **_kwargs: pytest.fail("docker queried"))

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._verify_candidate(
            tmp_path,
            {"candidate_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64},
        )


def test_success_rechecks_same_new_generation_after_handle_and_module_close():
    request, ports, admission, _service, events, _old, candidate = _transaction_fixture()

    # The existing terminal deployment is C0/D0; this operation installs C1/D1.
    assert request["candidate_sha"] == "a" * 40
    assert request["image_digest"] == "sha256:" + "b" * 64
    assert request["candidate_sha"] != "c" * 40
    assert request["image_digest"] != "sha256:" + "d" * 64

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "installed"
    assert receipt["operation_id"] == request["operation_id"]
    assert receipt["new_generation_sha256"] is not None
    assert events.index("apply_launcher") < events.index("stop_old") < events.index("apply_source")
    assert events.index("apply_source") < events.index("start_new")
    assert events.index("apply_source") < events.index("handle_close") < events.index("profile_candidate", events.index("handle_close"))
    assert events.index("runtime_close") < events.index("same_new_kernel")
    assert events.index("same_new_kernel") < events.index("admission_complete")
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert events.index("channel_lock_exit") < events.index("retire_channel_owner")
    assert admission.receipt == receipt
    assert candidate["profile_sha256"] not in json.dumps(receipt)


def test_failed_stop_and_handle_close_refusal_retain_owner_without_receipt():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(
        stop_old_error=True, handle_close_error=True,
    )

    with pytest.raises(RuntimeError, match="synthetic stop refusal"):
        transaction._execute_source_installation("dev", request, ports)

    assert "prepare" in events
    assert "stop_old_refused" in events
    assert "handle_close_failed" in events
    assert admission.receipt is None
    assert "admission_complete" not in events
    assert "retire_channel_owner" not in events


@pytest.mark.parametrize("profile_mismatch", [False, True])
def test_handle_close_uncertainty_stops_exact_generation_without_retry(profile_mismatch):
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        profile_mismatch=profile_mismatch, handle_close_error=True,
    )

    with pytest.raises(RuntimeError):
        transaction._execute_source_installation("dev", request, ports)

    assert events.count("handle_close_failed") == 1
    assert service.phase in {"new_stopped_checked", "restored_stopped_checked"}
    assert admission.receipt is None
    assert "retire_channel_owner" not in events


def test_final_writer_census_drift_after_close_stops_candidate_and_retains_owner():
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        preflight_drift_at=4,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "unknown"
    assert service.phase == "new_stopped_checked"
    assert "same_new_kernel" not in events
    final_preflight = max(index for index, event in enumerate(events) if event == "preflight")
    assert events.index("handle_close") < events.index("runtime_close") < final_preflight
    assert events.index("stop_new") < events.index("admission_complete")
    assert "retire_channel_owner" not in events
    assert admission.receipt == receipt


def test_failure_compensates_same_handle_and_leaves_legacy_generation_stopped():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(profile_mismatch=True)

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "compensated_stopped"
    assert receipt["old_generation_sha256"] != receipt["new_generation_sha256"]
    assert events.index("stop_new") < events.index("compensate_same_handle") < events.index("handle_close")
    assert "start_restored_old" not in events
    assert "retire_channel_owner" not in events
    assert "require_old_kernel_after_compensation" not in events
    assert admission.receipt == receipt


def test_failed_compensation_keeps_service_stopped_and_retains_owner():
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        apply_error=True, compensation_complete=False,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "unknown"
    assert service.phase == "stopped_checked"
    assert "start_restored_old" not in events
    assert "retire_channel_owner" not in events
    assert admission.receipt == receipt
    assert admission.active is False


def test_terminal_receipt_is_operation_bound_redacted_and_fail_closed():
    request, ports, admission, _service, _events, _old, _candidate = _transaction_fixture()

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert set(receipt) == {
        "schema", "operation_id", "channel", "candidate_sha", "image_digest",
        "old_generation_sha256", "new_generation_sha256", "backup_manifest_sha256", "status",
    }
    assert receipt["operation_id"] == request["operation_id"]
    assert receipt["channel"] == "dev"
    assert receipt["status"] == "installed"
    assert "/srv/app" not in json.dumps(receipt)
    assert "transaction-test" not in json.dumps(receipt)
    assert admission.receipt == receipt


def test_retirement_failure_after_receipt_keeps_verified_candidate_and_owner_evidence():
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        retire_error=True,
    )

    with pytest.raises(RuntimeError, match="synthetic channel-owner retirement failure"):
        transaction._execute_source_installation("dev", request, ports)

    assert admission.receipt["status"] == "installed"
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert events.index("channel_lock_exit") < events.index("retire_channel_owner")
    assert "stop_new" not in events
    assert service.phase == "new_kernel_checked"


def test_requires_no_write_exec_stop_post_and_retains_one_owner_through_closure():
    assert transaction._cleanup_fast_return(_DEPLOYMENT_SOURCE.encode())
    transaction._require_cleanup_shared_reservation(_DEPLOYMENT_SOURCE.encode())
    assert transaction._cleanup_skip_closure(_ADMISSION_SOURCE.encode())
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_cleanup_shared_reservation(
            _DEPLOYMENT_SOURCE.replace("            try:", "            if True:\n                pass\n            try:").encode()
        )
    changed = _ADMISSION_SOURCE.replace("    return True", "    return False").encode()

    assert transaction._cleanup_skip_closure(changed) != transaction._cleanup_skip_closure(
        _ADMISSION_SOURCE.encode()
    )

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._cleanup_fast_return(
            _DEPLOYMENT_SOURCE.replace("            return 0", "            pass").encode()
        )

    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture()
    result = transaction._execute_source_installation("dev", request, ports)

    assert result["source_installation"]["status"] == "installed"
    assert events.index("admission_enter") < events.index("stop_old")
    assert events.index("stop_old") < events.index("handle_close") < events.index("runtime_close")
    assert events.index("runtime_close") < events.index("profile_after_runtime_close")
    assert events.index("profile_after_runtime_close") < events.index("same_new_kernel")
    assert events.index("same_new_kernel") < events.index("admission_complete")
    assert events.index("admission_complete") < events.index("channel_lock_exit")
    assert events.index("channel_lock_exit") < events.index("retire_channel_owner")
    assert events.index("retire_channel_owner") < events.index("admission_exit")
    assert admission.active is False


def test_final_profile_rechecks_python_and_json_closure_after_runtime_close():
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        profile_drift_at=3,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    assert result["source_installation"]["status"] == "unknown"
    assert admission.receipt["status"] == "unknown"
    assert service.phase == "new_stopped_checked"
    assert events.index("runtime_close") < events.index("profile_after_runtime_close")
    assert events.index("profile_after_runtime_close") < events.index("stop_new")
    assert "same_new_kernel" not in events
    assert "retire_channel_owner" not in events


def test_profile_error_after_handle_close_stops_candidate_and_retains_owner():
    request, ports, admission, service, events, _old, _candidate = _transaction_fixture(
        profile_error_at=2,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    assert result["source_installation"]["status"] == "unknown"
    assert service.phase == "new_stopped_checked"
    assert events.index("handle_close") < events.index("profile_candidate", events.index("handle_close"))
    assert events.index("stop_new") < events.index("admission_complete")
    assert "compensate" not in events
    assert "retire_channel_owner" not in events
    assert admission.receipt["status"] == "unknown"


def test_source_installation_recovery_refuses_unknown_or_foreign_owner_without_effects(
    tmp_path, monkeypatch,
):
    """Recovery never turns an unfinished or foreign marker into a transaction."""
    from app.ops import bws_installation_admission as admission
    from app.ops import postgres_deploy_linux as linux

    runtime = tmp_path / "runtime"
    receipts = tmp_path / "receipts"
    runtime.mkdir(mode=0o700)
    receipts.mkdir(mode=0o700)
    monkeypatch.setattr(admission, "_RUNTIME_DIRECTORY", runtime)
    monkeypatch.setattr(admission, "_RECEIPT_DIRECTORY", receipts)
    monkeypatch.setattr(admission, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(admission, "_OWNER_GID", os.getegid())
    caller = {
        "pid": os.getpid(), "uid": os.geteuid(), "gid": os.getegid(), "start_time": 42,
        "argv_sha256": "1" * 64, "executable_sha256": "2" * 64, "launcher_sha256": "3" * 64,
    }
    monkeypatch.setattr(admission, "_fixed_caller_identity", lambda _channel: dict(caller))
    monkeypatch.setattr(admission, "_proc_identity", lambda pid: {
        "pid": pid, "start_time": caller["start_time"],
        "argv_sha256": caller["argv_sha256"], "executable_sha256": caller["executable_sha256"],
    })
    monkeypatch.setattr(
        admission, "_open_directory",
        lambda path: (os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW), path.stat()),
    )
    operation_id = "019ff695-00a6-7072-a082-57cbf2b3ee22"
    install_request = {
        "channel": "dev", "mode": "exclusive", "operation_id": operation_id,
        "candidate_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64,
        "bundle_name": "synthetic-recovery",
    }
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**install_request):
            pass
    marker = runtime / "dev.source-installation.lock"
    marker_before = marker.read_bytes()

    monkeypatch.setattr(
        linux.LinuxConfig, "load", staticmethod(
            lambda _channel: pytest.fail("recovery must not construct effects for unproven evidence"),
        ),
    )
    recovery = {
        key: install_request[key]
        for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }
    recovery["action"] = "source-installation-reconcile"
    result = transaction.reconcile_source_installation("dev", recovery)
    assert result == {
        "source_installation": {"status": "unresolved", "reason": "receipt_invalid"},
    }
    assert marker.read_bytes() == marker_before
    assert not list(receipts.iterdir())

    foreign = {**recovery, "candidate_sha": "f" * 40}
    result = transaction.reconcile_source_installation("dev", foreign)
    assert result == {
        "source_installation": {"status": "unresolved", "reason": "owner_mismatch"},
    }
    assert marker.read_bytes() == marker_before
    assert not list(receipts.iterdir())


def test_source_installation_recovery_rejects_missing_transaction_parent_as_unproven(tmp_path):
    from app.ops import postgres_deploy_linux as linux

    effects = linux.LinuxEffects.__new__(linux.LinuxEffects)
    effects.config = SimpleNamespace(root=tmp_path / "missing-root", channel="dev")
    with pytest.raises(linux.PostgresDeployError):
        effects.channel_lock_owner()

    deploy = tmp_path / "existing-root" / "config" / "deploy"
    deploy.mkdir(parents=True)
    effects.config = SimpleNamespace(root=tmp_path / "existing-root", channel="dev")
    assert effects.channel_lock_owner() is None


def test_cleanup_guards_validate_the_actual_deployment_entrypoint():
    deployment_path = Path(__file__).resolve().parents[2] / "app/ops/postgres_deploy_linux.py"
    source = deployment_path.read_bytes()
    admission_path = deployment_path.with_name("bws_installation_admission.py")
    admission_source = admission_path.read_bytes()
    launcher_source = (deployment_path.parents[2] / "scripts/postgres_deploy_service.py").read_bytes()

    assert transaction._cleanup_fast_return(source)
    assert transaction._cleanup_entrypoint(source)
    assert transaction._module_import_skeleton(source)
    transaction._require_cleanup_shared_reservation(source)
    transaction._require_source_only_launcher(launcher_source)
    transaction._require_source_only_launcher(launcher_source, require_preimport_reservation=True)
    cleanup_closure = transaction._cleanup_skip_closure(admission_source)
    altered_lock_opener = admission_source.replace(
        b"    if create:\n        flags |= os.O_CREAT\n",
        b"    if create:\n        flags |= os.O_TRUNC\n",
        1,
    )
    assert altered_lock_opener != admission_source
    assert transaction._cleanup_skip_closure(altered_lock_opener) != cleanup_closure

    weakened = source.replace(
        b"                    admissions.enter_context(shared_caller_reservation(args.channel))",
        b"                    shared_caller_reservation(args.channel)",
        1,
    )
    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._require_cleanup_shared_reservation(weakened)


def test_channel_lock_acquisition_refusal_is_no_effect_and_has_no_channel_owner_claim():
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(
        channel_lock_error=True,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
    assert "channel_lock_refused" in events
    assert "channel_lock_enter" not in events and "channel_lock_exit" not in events
    assert "verify_candidate" not in events and "prepare" not in events
    assert "stop_old" not in events and "apply" not in events
    assert "retire_channel_owner" not in events
    assert events.index("channel_lock_refused") < events.index("admission_complete")
    assert events.index("admission_complete") < events.index("admission_exit")
    assert admission.receipt == receipt


# Real lifecycle and typed bus decoding; only filesystem/transport ports are synthetic.
def _old_qualification_case(monkeypatch, secure_tmp_path, channel="dev"):
    request, ports, admission, _service, events, old_state, _candidate = _transaction_fixture(channel=channel)
    service, control, properties = _install_synthetic_real_lifecycle_service(
        monkeypatch, ports, old_state, secure_tmp_path, channel=channel,
    )
    cls = bws_installation_lifecycle.FixedBwsService
    for name in ("_call", "_get", "_exec", "_state", "_single_process"):
        monkeypatch.setattr(service, name, getattr(cls, name).__get__(service))
    for name in ("ExecCondition", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecReload"):
        properties[("Service", name)] = []
    for name, action in (("ExecStart", "serve"), ("ExecStopPost", "cleanup")):
        properties[("Service", name)] = [[
            bws_installation_lifecycle.LAUNCHER,
            [bws_installation_lifecycle.LAUNCHER, action, channel], False,
            1, 2, 3, 4, 5, 1, 0,
        ]]
    properties.update({
        ("Unit", "ActiveState"): "active", ("Unit", "SubState"): "running",
        ("Unit", "Job"): [0, "/"], ("Service", "ControlPID"): 0,
        ("Service", "MainPID"): 123,
    })
    faults = {"transport": False, "processes": [["private-cgroup", 123, "private-command"]]}

    def run(argv):
        if faults["transport"]:
            # The real _typed decoder must reject this value without echoing it.
            return json.dumps({"type": "PRIVATE_CANARY", "data": "PRIVATE_CANARY"}).encode()
        if argv[7] == "call":
            method = argv[11]
            signature = "o" if method == "GetUnit" else "a(sus)"
            data = ["/org/freedesktop/systemd1/unit/synthetic"] if method == "GetUnit" else [faults["processes"]]
        else:
            interface, name = argv[-2].rsplit(".", 1)[-1], argv[-1]
            value = properties[(interface, name)]
            signature = (bws_installation_lifecycle.EXEC_TYPE if name.startswith("Exec") else
                         "a(sb)" if name == "EnvironmentFiles" else
                         "as" if name in {"OnFailure", "OnSuccess", "TriggeredBy", "Environment"} else
                         "(uo)" if name == "Job" else
                         "u" if name in {"ControlPID", "MainPID"} else "s")
            data = value
        return json.dumps({"type": signature, "data": data}).encode()

    monkeypatch.setattr(bws_installation_lifecycle, "_run", run)
    return request, ports, admission, service, events, control, properties, faults


def _assert_old_refusal(result, events, expected):
    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
    if expected.endswith(('_root_control', '_initial_unit_properties')):
        assert (receipt['prebackup_gate'] == expected
                or receipt['prebackup_gate'].startswith(expected + '__'))
    else:
        assert receipt["prebackup_gate"] == expected
    assert all(receipt[key] is None for key in (
        "old_generation_sha256", "new_generation_sha256", "backup_manifest_sha256",
    ))
    assert not {"prepare", "apply_launcher", "stop_old", "apply_source", "start_new"} & set(events)
    assert "PRIVATE_CANARY" not in json.dumps(result)


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("fault,subgate", [
    ("setup", "setup"), ("runtime", "retained_runtime"),
    ("transport", "unit_properties"), ("typed_value", "unit_properties"),
    ("root", "root_control"), ("launcher", "launcher"),
    ("state", "service_process"), ("processes", "service_process"),
    ("cleanup", "cleanup_contract"),
])
def test_source_old_kernel_refusals_preserve_finite_stage_classification(
    monkeypatch, secure_tmp_path, channel, fault, subgate, capsys,
):
    request, ports, admission, service, events, control, properties, faults = _old_qualification_case(
        monkeypatch, secure_tmp_path, channel,
    )
    if fault == "setup":
        # The actual native service factory reaches the strict constructor guard.
        ports.service = lambda _channel: transaction._NativePorts.service(ports, "PRIVATE_CANARY")
    elif fault == "runtime":
        # Real retained_runtime entry, before qualify_old, with a failed runtime stat.
        monkeypatch.setattr(service, "retained_runtime", type(service).retained_runtime.__get__(service))
        monkeypatch.setattr(bws_installation_lifecycle, "RUNTIME", str(control / "PRIVATE_CANARY"))
    elif fault == "transport":
        faults["transport"] = True
    elif fault == "typed_value":
        properties[("Service", "User")] = "PRIVATE_CANARY"
    elif fault == "root":
        (control / "app").mkdir()
    elif fault == "launcher":
        launcher_reads = iter((b"old launcher", b"PRIVATE_CANARY"))
        monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: next(launcher_reads))
    elif fault == "state":
        properties[("Service", "ControlPID")] = "PRIVATE_CANARY"
    elif fault == "processes":
        faults["processes"] = [["PRIVATE_CANARY", "PRIVATE_CANARY", "PRIVATE_CANARY"]]
    elif fault == "cleanup":
        properties[("Service", "ExecStopPost")][0][1] = ["PRIVATE_CANARY"]
    result = transaction._execute_source_installation(channel, request, ports)
    _assert_old_refusal(result, events, f"old_kernel_initial_{subgate}")
    assert admission.receipt == result["source_installation"]
    assert "PRIVATE_CANARY" not in repr(capsys.readouterr())


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("drift", [
    "inventory", "identity", "configuration", "runtime", "unit", "launcher", "cleanup",
])
def test_empty_control_revalidation_reports_finite_old_kernel_refusal(
    monkeypatch, secure_tmp_path, channel, drift,
):
    request, ports, _admission, service, events, control, properties, _faults = _old_qualification_case(
        monkeypatch, secure_tmp_path, channel,
    )

    def drift_after_qualification(_request):
        assert service.phase == "qualified"
        events.append("verify_caller_sources")
        if drift == "inventory":
            (control / "scripts").mkdir()
        elif drift == "identity":
            control.rename(control.with_name("old-root"))
            control.mkdir(mode=0o755)
        elif drift == "configuration":
            properties[("Service", "Environment")] = ["PRIVATE_CANARY=value"]
        elif drift == "runtime":
            monkeypatch.setattr(service, "_held_runtime", type(service)._held_runtime.__get__(service))
        elif drift == "unit":
            properties[("Service", "Type")] = "PRIVATE_CANARY"
        elif drift == "launcher":
            monkeypatch.setattr(bws_installation_lifecycle, "_public_launcher_bytes", lambda: b"PRIVATE_CANARY")
        else:
            properties[("Service", "ExecStopPost")][0][1] = ["PRIVATE_CANARY"]

    ports.verify_caller_sources = drift_after_qualification
    result = transaction._execute_source_installation(channel, request, ports)
    subgate = {"runtime": "retained_runtime", "unit": "unit_properties",
               "launcher": "launcher", "cleanup": "cleanup_contract"}.get(drift, "root_control")
    _assert_old_refusal(result, events, f"old_kernel_empty_control_{subgate}")
    assert "verify_caller_sources" in events
    assert service.phase == "qualified"


@pytest.mark.parametrize("bad", [None, "PRIVATE_CANARY", [], {}, 7])
@pytest.mark.parametrize("exception_kind", ["typed", "ordinary", "foreign"])
def test_old_kernel_unclassified_failures_preserve_legacy_refusal(bad, exception_kind):
    request, ports, _admission, service, events, *_ = _transaction_fixture()

    def refuse(**_kwargs):
        if exception_kind == "typed":
            raise bws_installation_lifecycle._OldQualificationRefusal(bad)
        if exception_kind == "foreign":
            exc = RuntimeError("PRIVATE_CANARY")
            exc.subgate = "root_control"
            raise exc
        raise RuntimeError("PRIVATE_CANARY")

    service.qualify_old = refuse
    result = transaction._execute_source_installation("dev", request, ports)
    _assert_old_refusal(result, events, "old_kernel_qualification")
    assert events.index("runtime_enter") < events.index("runtime_close")


@pytest.mark.parametrize("fault", ["runtime", "unit", "root", "cleanup", "process"])
def test_old_kernel_classification_keeps_prebackup_effect_order_and_protected_guards(
    monkeypatch, secure_tmp_path, fault,
):
    request, ports, _admission, service, events, control, properties, faults = _old_qualification_case(
        monkeypatch, secure_tmp_path,
    )
    # Track the actual ordered guard calls, without replacing their predicates.
    for name in ("_held_runtime", "_config", "_state", "_single_process", "_exec"):
        original = getattr(service, name)

        def tracked(*args, _name=name, _original=original, **kwargs):
            events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(service, name, tracked)
    expected = {
        "runtime": "retained_runtime", "unit": "unit_properties", "root": "root_control",
        "cleanup": "cleanup_contract", "process": "service_process",
    }[fault]
    if fault == "runtime":
        monkeypatch.setattr(service, "_held_runtime", type(service)._held_runtime.__get__(service))
    elif fault == "unit":
        properties[("Service", "Type")] = "PRIVATE_CANARY"
    elif fault == "root":
        (control / "scripts").mkdir()
    elif fault == "cleanup":
        properties[("Service", "ExecStopPost")][0][2] = True
    else:
        faults["processes"] = []
    result = transaction._execute_source_installation("dev", request, ports)
    _assert_old_refusal(result, events, f"old_kernel_initial_{expected}")
    assert events.index("source_manifest") < events.index("descriptor_capacity")
    if fault != "runtime":
        assert events.index("_held_runtime") < events.index("_config")
    if fault == "process":
        assert events.index("_config") < events.index("_state") < events.index("_single_process")


def test_root_control_leaf_matrix_reaches_canonical_receipt(monkeypatch, secure_tmp_path):
    from tests.ops.test_bws_installation_lifecycle import RootControlOS
    # The end-to-end Source RPC matrix is the producer proof. These cheap
    # transaction cases isolate side comparison and final configuration order.
    for channel in ('dev', 'test'):
        for side, discovery in (('old', 1), ('proposed', 2)):
            case_root = secure_tmp_path / (channel + side)
            case_root.mkdir(mode=0o750)
            request, ports, admission, service, events, control, _properties, _ = _old_qualification_case(
                monkeypatch, case_root, channel,
            )
            old = ports.old_state(None, None)
            old['source_packages']['control'] = ['app']
            kernel = RootControlOS(control, anchored=True)
            kernel.arm(dict(operation='fstat', path=str(control), occurrence=2,
                            change={'st_ino': 987654321}), discovery=discovery)
            monkeypatch.setattr(bws_installation_lifecycle, 'os', kernel.port())
            result = transaction._execute_source_installation(channel, request, ports)
            _assert_old_refusal(result, events, 'old_kernel_initial_root_control__' + '__'.join((
                'anchored_discovery', side, 'comparison', 'identity',
            )))
            assert admission.receipt == result['source_installation']
            assert kernel.fired and not kernel.fds

    # Captured-empty discovery itself guarantees equality with its captured
    # dictionary. No supported writer mutates that dictionary while _config
    # runs. Exercise the remaining defensive comparison by corrupting only
    # in-process test state after the real discovery returns its validated
    # projection and before its caller compares it; never fake a producer.
    case_root = secure_tmp_path / 'defensive-empty-comparison'
    case_root.mkdir(mode=0o750)
    request, ports, _admission, service, events, control, _properties, _ = _old_qualification_case(
        monkeypatch, case_root,
    )
    kernel = RootControlOS(control)
    original_close = kernel.close
    def corrupt_after_discovery(fd):
        original_close(fd)
        if not kernel.fds and kernel.discovery == 1:
            service.control = {**service.control, 'inode': 987654321}
    kernel.close = corrupt_after_discovery
    monkeypatch.setattr(bws_installation_lifecycle, 'os', kernel.port())
    result = transaction._execute_source_installation('dev', request, ports)
    _assert_old_refusal(result, events,
                        'old_kernel_initial_root_control__captured_empty__old__comparison__identity')


def test_root_control_leaf_refusals_preserve_order_effects_and_lifetime(monkeypatch, secure_tmp_path):
    from tests.ops.test_bws_installation_lifecycle import RootControlOS
    for close_failures in (0, 3):
        case_root = secure_tmp_path / str(close_failures)
        case_root.mkdir(mode=0o750)
        request, ports, admission, _service, events, control, _properties, _ = _old_qualification_case(
            monkeypatch, case_root,
        )
        kernel = RootControlOS(control)
        kernel.arm(dict(operation='fstat', path=str(control), occurrence=0,
                        change={'st_mode': 0o100644}))
        kernel.close_failures = close_failures
        monkeypatch.setattr(bws_installation_lifecycle, 'os', kernel.port())
        result = transaction._execute_source_installation('dev', request, ports)
        expected = ('discovery_close', 'close_unknown') if close_failures else ('fixed_root', 'directory_type')
        _assert_old_refusal(result, events, 'old_kernel_initial_root_control__' + '__'.join((
            'captured_empty', 'old', *expected,
        )))
        assert kernel.closed == list(reversed(kernel.opened)) and not kernel.fds
        assert admission.receipt == result['source_installation']
        assert events.index('source_manifest') < events.index('descriptor_capacity')
    # The unchanged uncertain-handle and retained-runtime protocols remain
    # acceptance evidence, rather than forcing a finite diagnostic on them.
    test_failed_stop_and_handle_close_refusal_retain_owner_without_receipt()
    test_handle_close_uncertainty_stops_exact_generation_without_retry(False)


@pytest.mark.parametrize('kind', ['foreign', 'subclass', 'missing', 'bad_tuple', 'bad_atom', 'bad_context', 'missing_subgate', 'legacy'])
def test_root_control_leaf_unknowns_preserve_legacy_privacy_and_binding(kind):
    request, ports, _admission, service, events, *_ = _transaction_fixture()
    cls = bws_installation_lifecycle._OldQualificationRefusal
    def refuse(**_kwargs):
        if kind == 'foreign':
            exc = RuntimeError('PRIVATE_CANARY')
            exc.subgate = 'root_control'
            exc.root_control = ('captured_empty', 'old', 'hints', 'launcher_hint')
        elif kind == 'subclass':
            class Foreign(cls):
                pass
            exc = Foreign('root_control')
        else:
            exc = cls('root_control')
            if kind == 'missing_subgate':
                exc.root_control = ('captured_empty', 'old', 'hints', 'launcher_hint')
                del exc.subgate
            elif kind == 'missing':
                del exc.root_control
            elif kind == 'bad_tuple':
                exc.root_control = ['captured_empty', 'old', 'hints', 'launcher_hint']
            elif kind == 'bad_atom':
                exc.root_control = ('captured_empty', 'old', 'hints', 'PRIVATE_CANARY')
            elif kind == 'bad_context':
                exc.root_control = ('unknown', 'old', 'hints', 'launcher_hint')
        raise exc
    service.qualify_old = refuse
    result = transaction._execute_source_installation('dev', request, ports)
    _assert_old_refusal(result, events, 'old_kernel_qualification' if kind in {'foreign', 'subclass', 'missing_subgate'}
                        else 'old_kernel_initial_root_control')
    assert events.index('runtime_enter') < events.index('runtime_close')
    # Binding itself remains real in the source RPC matrix and existing precise
    # checkout/Git-launcher/OCI/full-profile negatives; no new request field exists.
    assert set(request) == {'action', 'operation_id', 'candidate_sha', 'image_digest', 'bundle_name'}


def test_root_control_defensive_projection_rows_have_real_producer_invariants(monkeypatch, secure_tmp_path):
    import copy
    monkeypatch.setattr(bws_installation_lifecycle, '_CONTROL_OWNER_UID', os.geteuid())
    monkeypatch.setattr(bws_installation_lifecycle, '_CONTROL_OWNER_GID', os.getegid())
    # Actual no-follow root producer, not a hand-authored profile as sole proof.
    paths = {name: secure_tmp_path / name for name in ('application', 'control', 'backup', 'launcher')}
    for path in paths.values():
        path.mkdir(mode=0o755)
        path.chmod(0o755)
    monkeypatch.setattr(transaction, '_OWNER_UID', os.geteuid())
    monkeypatch.setattr(transaction, '_OWNER_GID', os.getegid())
    monkeypatch.setattr(transaction, '_CONTROL_DIRECTORY', paths['control'])
    monkeypatch.setattr(transaction, '_BACKUP_DIRECTORY', paths['backup'])
    monkeypatch.setattr(transaction, '_LAUNCHER', paths['launcher'] / 'yggdrasil-bws-deploy')
    identities = {name: transaction._root_identity(paths[name]) for name in ('application', 'control')}
    for identity in identities.values():
        assert set(identity) == {'device', 'inode', 'uid', 'gid', 'mode'}
        assert all(type(v) is int for v in identity.values())
        assert identity['device'] >= 0 and identity['inode'] > 0
        assert identity['uid'] == os.geteuid() and identity['gid'] == os.getegid()
        assert identity['mode'] == 0o755
    config = SimpleNamespace(root=paths['application'])
    profile = dict(roots=identities, source_files=[])
    roots, _backup = transaction._roots(config, profile)
    for name in ('application', 'control'):
        value = transaction._root_projection(roots[name])
        assert bws_installation_lifecycle._application_projection(value) == value
        assert type(value) is dict and type(value['path']) is str
        assert value['path'] == str(paths[name].resolve())
    # The actual roots boundary rejects malformed/foreign projection records
    # before lifecycle, and preserves the independently produced healthy root.
    for invalid in (None, {}, {**identities['application'], 'private': 'PRIVATE_CANARY'}, *[
        {**identities['application'], key: True} for key in ('device', 'inode', 'uid', 'gid', 'mode')
    ]):
        malformed = copy.deepcopy(profile)
        malformed['roots']['application'] = invalid
        with pytest.raises(RuntimeError, match='bws_installation_transaction_refused'):
            transaction._roots(config, malformed)
        assert transaction._root_identity(paths['control']) == identities['control']
    for mode in (0o750, 0o777):
        paths['application'].chmod(mode)
        with pytest.raises(RuntimeError, match='bws_installation_transaction_refused'):
            transaction._root_identity(paths['application'])
    paths['application'].chmod(0o755)
    for path in (Path('relative'), paths['application'] / '..', Path('/PRIVATE_CANARY\\bad'),
                 Path('/PRIVATE_CANARY\0bad')):
        with pytest.raises(RuntimeError, match='bws_installation_transaction_refused'):
            transaction._root_identity(path)
    for field in ('_OWNER_UID', '_OWNER_GID'):
        with monkeypatch.context() as patch:
            patch.setattr(transaction, field, 999999)
            with pytest.raises(RuntimeError, match='bws_installation_transaction_refused'):
                transaction._root_identity(paths['application'])
    assert transaction._CONTROL_DIRECTORY == paths['control']
    # The typed caller constructs control.path from the fixed source constant;
    # outside-subtree and empty-deeper-path defensive states have no input flag.
    assert set(transaction._validate_request('dev', {
        'action': 'source-installation', 'operation_id': str(uuid.uuid4()),
        'candidate_sha': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64, 'bundle_name': 'fixed',
    })) == {'operation_id', 'candidate_sha', 'image_digest', 'bundle_name'}


@pytest.mark.parametrize('mode', ['manifest', 'effect-alias', 'process-cwd'])
def test_control_path_slots_bind_complete_effect_footprint(monkeypatch, secure_tmp_path, mode):
    import base64
    if mode in {'effect-alias', 'process-cwd'}:
        from tests.deploy.test_bws_source_rpc_assembly import exercise_control_path_transaction
        assert exercise_control_path_transaction(secure_tmp_path, 'dev', mode)['status'] == 'refused_before_backup'
        return
    from tests.ops.test_bws_installation_lifecycle import configure_control_path_service
    case = _empty_control_manifest_case(monkeypatch, secure_tmp_path)
    unrelated = case.control_root / 'unrelated'
    unrelated.write_bytes(b'untouched synthetic data')
    unrelated.chmod(0o644)
    changes, payloads, proof = case.invoke()
    assert {c.root for c in changes} == {'application', 'launcher'}
    footprint = proof['control_path_footprint']
    assert tuple(r['path'] for r in footprint) == (
        case.roots['application'].path, case.roots['launcher'].path, proof['backup_root'].path,
    )
    runtime = secure_tmp_path / 'runtime'
    runtime.write_bytes(b'synthetic runtime')
    runtime.chmod(0o755)
    launcher = Path(case.roots['launcher'].path) / 'yggdrasil-bws-deploy'
    launcher.write_bytes(b'legacy launcher bytes\n')
    launcher.chmod(0o755)
    state = {'events': []}
    configure_control_path_service(bws_installation_lifecycle, monkeypatch, state, case.control_root,
        case.app_root, runtime, launcher, 'dev', ['PATH=/usr/bin:' + str(case.control_root)])
    raw = payloads['launcher', 'yggdrasil-bws-deploy']
    for selected in (footprint, (footprint[0], footprint[1], dict(footprint[2], path=str(case.control_root)))):
        service = bws_installation_lifecycle.FixedBwsService(unit='yggdrasil-bws-deploy@dev.service', channel='dev')
        with service.retained_runtime():
            arguments = dict(application_root=dict(path=str(case.app_root), **case.profile['roots']['application']),
                control_root=dict(path=str(case.control_root), **case.profile['roots']['control']),
                control_inventory_empty=True, installation_footprint=selected,
                installation_effect_parents=proof['control_path_effect_parents'],
                launcher_content=dict(sha256=transaction._sha(raw), base64=base64.b64encode(raw).decode()))
            if selected == footprint:
                service.qualify_old(**arguments)
                service.revalidate_empty_control_configuration()
            else:
                with pytest.raises(RuntimeError):
                    service.qualify_old(**arguments)
    assert not state['events']
    assert unrelated.read_bytes() == b'untouched synthetic data'
    assert not list(Path(proof['backup_root'].path).iterdir())


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('fault', ['partial', 'close', 'transient-initial', 'transient-prebackup',
                                   'proc-close', 'launcher-close'])
def test_control_path_slots_restore_original_generation(secure_tmp_path, channel, fault):
    from tests.deploy.test_bws_source_rpc_assembly import exercise_control_path_transaction
    result = exercise_control_path_transaction(secure_tmp_path, channel, fault)
    assert result['status'] == ('compensated_stopped' if fault == 'partial' else 'unknown')


def test_control_path_projection_privacy_and_legacy_refusals(monkeypatch, secure_tmp_path):
    from tests.ops.test_bws_installation_lifecycle import control_path_fixture
    fixture = control_path_fixture(monkeypatch, secure_tmp_path)
    fixture.properties['Service', 'Environment'].append('PYTHONPATH=' + str(fixture.slot) + '/PRIVATE_CANARY')
    with fixture.service.retained_runtime():
        with pytest.raises(bws_installation_lifecycle._OldQualificationRefusal) as caught:
            fixture.service.qualify_old(**fixture.arguments)
    assert str(caught.value) == 'bws_lifecycle_unproven'
    assert caught.value.subgate == 'root_control'
    assert caught.value.root_control == ('captured_empty', 'old', 'hints', 'environment_hint')
    assert 'PRIVATE_CANARY' not in repr((str(caught.value), caught.value.root_control))
    assert not fixture.state['events']


@pytest.mark.parametrize('scenario', ['positive', 'environment-order', 'short-circuit', 'retained', 'path-close', 'transient'])
def test_initial_unit_property_refinement_preserves_order_and_close_uncertainty(
    monkeypatch, secure_tmp_path, scenario,
):
    from tests.ops.test_bws_installation_lifecycle import (
        control_path_fixture, install_unit_property_transport, _UNIT_INITIAL_TRACE,
    )
    if scenario in {'retained', 'path-close'}:
        from tests.deploy.test_bws_source_rpc_assembly import exercise_unit_property_close
        assert exercise_unit_property_close(secure_tmp_path,
            'runtime-close' if scenario == 'retained' else 'close')['status'] == 'unknown'
        return
    if scenario == 'transient':
        from tests.deploy.test_bws_source_rpc_assembly import exercise_control_path_transaction
        result = exercise_control_path_transaction(secure_tmp_path, 'dev',
            'close' if scenario == 'retained' else 'transient-initial')
        assert result['status'] == 'unknown'
        return
    fixture = control_path_fixture(monkeypatch, secure_tmp_path)
    fault = None if scenario == 'positive' else dict(
        site='Service_Environment' if scenario == 'environment-order' else 'Service_Type', kind='value')
    install_unit_property_transport(bws_installation_lifecycle, monkeypatch, fixture.state,
                                    fixture.properties, fault)
    with fixture.service.retained_runtime():
        if fault:
            with pytest.raises(bws_installation_lifecycle._OldQualificationRefusal) as caught:
                fixture.service.qualify_old(**fixture.arguments)
            assert caught.value.unit_property == (fault['site'], 'shape' if scenario == 'environment-order' else 'value')
        else:
            fixture.service.qualify_old(**fixture.arguments)
            assert fixture.service.contract[2] == tuple(fixture.environment)
            assert fixture.properties['Service', 'Environment'] == fixture.environment
            assert fixture.service.phase == 'qualified'
    trace = fixture.state['unit_trace']
    assert trace == (_UNIT_INITIAL_TRACE if scenario == 'positive' else
                     _UNIT_INITIAL_TRACE[:20] if scenario == 'environment-order' else _UNIT_INITIAL_TRACE[:4])
    assert fixture.service.runtime_close_completed and not fixture.state['events']


@pytest.mark.parametrize('kind', ['supported', 'absent', 'foreign', 'subclass', 'unknown-site',
                                'unknown-kind', 'list', 'member-type', 'extra', 'missing', 'final'])
def test_initial_unit_property_refinement_preserves_privacy_and_legacy_fallback(kind):
    request, ports, _admission, service, events, *_ = _transaction_fixture()
    cls = bws_installation_lifecycle._OldQualificationRefusal
    class Foreign(cls):
        pass
    def refuse(**_kwargs):
        refinement = ('Service_Type', 'value')
        failure = (RuntimeError('PRIVATE_CANARY') if kind == 'foreign' else
                   Foreign('unit_properties') if kind == 'subclass' else cls('unit_properties'))
        failure.subgate = 'unit_properties'
        failure.unit_property = {
            'absent': None, 'unknown-site': ('PRIVATE_CANARY', 'value'),
            'unknown-kind': ('Service_Type', 'PRIVATE_CANARY'), 'list': ['Service_Type', 'value'],
            'member-type': ('Service_Type', []), 'extra': ('Service_Type', 'value', 'PRIVATE_CANARY'),
        }.get(kind, refinement)
        if kind == 'missing':
            del failure.unit_property
        raise failure
    if kind == 'final':
        # A supported-looking metadata tuple cannot move final-stage semantics.
        service.control_inventory_empty = True
        service.revalidate_empty_control_configuration = refuse
    else:
        service.qualify_old = refuse
    result = transaction._execute_source_installation('dev', request, ports)
    gate = ('old_kernel_qualification' if kind in {'foreign', 'subclass'} else
            'old_kernel_empty_control_unit_properties' if kind == 'final' else
            'old_kernel_initial_unit_properties__Service_Type__value' if kind == 'supported' else
            'old_kernel_initial_unit_properties')
    _assert_old_refusal(result, events, gate)
    assert events.count('runtime_close') == 1


@pytest.mark.parametrize('mode', ['manifest', 'selection', 'content', 'ancestor', 'lookup', 'mount',
                                  'effect-mount', 'application-overlap', 'backup-overlap',
                                  'prebackup', 'prestop', 'after-start', 'closing'])
def test_preserved_dropin_profile_binds_effects_and_revalidation(monkeypatch, secure_tmp_path, mode):
    import base64
    from tests.ops.test_bws_installation_lifecycle import configure_control_path_service, configure_preserved_dropin
    if mode in {'prebackup', 'prestop', 'after-start', 'closing'}:
        from tests.deploy.test_bws_source_rpc_assembly import exercise_control_path_transaction
        result = exercise_control_path_transaction(secure_tmp_path, 'dev', 'preserved-' + mode)
        assert result['status'] == ('refused_before_backup' if mode == 'prebackup' else 'unknown')
        return
    case = _empty_control_manifest_case(monkeypatch, secure_tmp_path)
    changes, payloads, proof = case.invoke()
    assert {c.root for c in changes} == {'application', 'launcher'}
    runtime = secure_tmp_path / 'runtime'
    runtime.write_bytes(b'synthetic runtime')
    runtime.chmod(0o755)
    launcher = Path(case.roots['launcher'].path) / 'yggdrasil-bws-deploy'
    launcher.write_bytes(b'legacy launcher bytes\n')
    launcher.chmod(0o755)
    state = {'events': []}
    module = bws_installation_lifecycle
    properties = configure_control_path_service(module, monkeypatch, state, case.control_root,
        case.app_root, runtime, launcher, 'dev', ['PATH=/usr/bin:' + str(case.control_root)])
    directory = (case.app_root if mode == 'application-overlap' else Path(proof['backup_root'].path)
                 if mode == 'backup-overlap' else secure_tmp_path.resolve())
    selected = configure_preserved_dropin(module, monkeypatch, directory, properties, 'dev')
    raw = payloads['launcher', 'yggdrasil-bws-deploy']
    service = module.FixedBwsService(unit='yggdrasil-bws-deploy@dev.service', channel='dev')
    arguments = dict(application_root=dict(path=str(case.app_root), **case.profile['roots']['application']),
        control_root=dict(path=str(case.control_root), **case.profile['roots']['control']),
        control_inventory_empty=True, installation_footprint=proof['control_path_footprint'],
        installation_effect_parents=proof['control_path_effect_parents'],
        launcher_content=dict(sha256=transaction._sha(raw), base64=base64.b64encode(raw).decode()))
    with service.retained_runtime():
        if mode.endswith('overlap'):
            with pytest.raises(RuntimeError):
                service.qualify_old(**arguments)
        else:
            service.qualify_old(**arguments)
            contract = service.contract
            held = service.control_path_binding.fds
            assert str(selected) in held
            assert all(path in held for path in proof['control_path_effect_parents'])
            assert all(root['path'] in held for root in proof['control_path_footprint'])
            if mode == 'manifest':
                assert service._config() == contract
                assert transaction._generation_sha(case.profile, 'a' * 64, contract) != transaction._generation_sha(
                    case.profile, 'a' * 64, contract[:-1])
            else:
                if mode == 'selection':
                    properties['Unit', 'DropInPaths'] = []
                elif mode == 'content':
                    selected.write_bytes(selected.read_bytes().replace(b'/usr/bin', b'/opt/bin'))
                elif mode == 'ancestor':
                    selected.parent.chmod(0o777)
                elif mode == 'lookup':
                    data = selected.read_bytes()
                    selected.rename(selected.with_name('retained.conf'))
                    selected.write_bytes(data)
                elif mode in {'mount', 'effect-mount'}:
                    target = selected if mode == 'mount' else case.app_root / 'app/ops'
                    identity = target.stat()
                    original = module._control_path_mount
                    def mount(fd):
                        info = module.os.fstat(fd)
                        return original(fd) + int((info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino))
                    monkeypatch.setattr(module, '_control_path_mount', mount)
                with pytest.raises(RuntimeError):
                    service.revalidate_empty_control_configuration()
    assert not state['events']
    assert not service.control_path_binding.fds


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('mode', ['partial', 'restored-drift'])
def test_preserved_dropin_profile_preserves_compensation_boundaries(secure_tmp_path, channel, mode):
    from tests.deploy.test_bws_source_rpc_assembly import exercise_control_path_transaction
    result = exercise_control_path_transaction(secure_tmp_path, channel, 'preserved-' + mode)
    assert result['status'] == ('compensated_stopped' if mode == 'partial' else 'unknown')
