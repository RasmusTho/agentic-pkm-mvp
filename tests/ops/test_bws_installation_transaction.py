from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid
from contextlib import contextmanager

import pytest

from app.ops.bws_control_installation import Change, Root
from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401

from app.ops import bws_installation_lifecycle, bws_installation_transaction as transaction

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
    old_contract = b'{"contract":"old"}\n'
    candidate_contract = b'{"contract":"candidate"}\n'
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
    monkeypatch.setattr("app.ops.host_secret_contract.load_host_secret_contract_bytes",
                        lambda raw: contract_validation.append(raw))
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
    assert contract_validation == [old_contract, candidate_contract]
    assert "app.ops.new_dynamic" not in sys.modules

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
    *, preflight_error=False, terminal_identity_drift: str | None = None, apply_error=False,
    compensation_complete=True, profile_mismatch=False, profile_error=False, retire_error=False,
    channel_lock_error=False, preflight_drift_at: int | None = None,
    profile_drift_at: int | None = None, profile_error_at: int | None = None,
    stop_old_error=False, handle_close_error=False, **_legacy_options,
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
        "channel": "dev",
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
            assert channel == "dev"
            return config

        def effects(self, _config):
            return effects

        def admission(self, _channel, _request):
            return admission

        def cleanup_callers(self, channel):
            assert channel == "dev" and admission.active
            events.append("cleanup_caller_census")

        def preflight(self, _effects, _selected_request):
            nonlocal preflight_calls
            preflight_calls += 1
            events.append("preflight")
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
                channel="dev",
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

        def old_state(self, _config, _request):
            events.append("old_disk_state")
            return old_state

        def roots(self, _config, _profile):
            return ({"application": "app-root", "control": "control-root",
                     "launcher": "launcher-root"}, "backup-root")

        def source_manifest(self, *_args):
            events.append("source_manifest")
            return changes, payloads, proof

        def service(self, _channel):
            return service

        def verify_caller_sources(self, _request):
            events.append("verify_caller_sources")

        def prepare(self, *_args):
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

    config = SimpleNamespace(channel="dev", root=Path("/srv/app"), journal=object())
    ports = Ports()
    return request, ports, admission, service, events, old_state, candidate


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


@pytest.mark.parametrize("mismatch", ["revision", "image"])
def test_preflight_refuses_current_terminal_identity_drift_before_backup_or_effects(mismatch):
    request, ports, admission, _service, events, _old, _candidate = _transaction_fixture(
        terminal_identity_drift=mismatch,
    )

    result = transaction._execute_source_installation("dev", request, ports)

    receipt = result["source_installation"]
    assert receipt["status"] == "refused_before_backup"
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


def test_native_writer_snapshot_requires_terminal_owner_and_selected_authority_cutover(monkeypatch):
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
    plan = SimpleNamespace(authority_cutover=None)
    journal = SimpleNamespace(read=lambda: receipt, bound_plan=lambda _operation_id: plan)
    effects = SimpleNamespace(
        config=SimpleNamespace(channel="dev", journal=journal),
        source_identity_runtime_snapshot=lambda *_args, **_kwargs: calls.append("snapshot"),
        quiescent=lambda: calls.append("quiescent") or True,
    )
    monkeypatch.setattr(native_source_admission, "require_terminal_deployment",
                        lambda _effects: calls.append("terminal-owner"))

    with pytest.raises(RuntimeError, match="bws_installation_transaction_refused"):
        transaction._current_writer_snapshot(effects, request)

    assert calls == ["terminal-owner", "profile-bound"]


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
