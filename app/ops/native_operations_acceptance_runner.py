"""Fixed live DEV/TEST fact producer; no deploy, repair, or source initializer.

Only the native committed operation id and channel are inputs. Git, Docker,
the existing native journal and installed external distribution produce facts.
The external effect ports are replaceable for deterministic orchestration tests.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any
from uuid import UUID, uuid5

from app.ops.operations_acceptance import (
    PROFILE, SELECTION_HASH, OperationsAcceptanceRefusal, digest, file_hash, inventory, require_identity,
)

SDK_PYTHON = Path("/opt/yggdrasil/bws-deploy-runtime/bin/python")
BAKED = ("app", "mimer_runtime", "llm_contract", "companion-ui/companion-app", "schemas", "config", "configs", "vault", "docs/settings", "alembic.ini")
PRODUCERS = ("Dockerfile", "docker-compose.yaml", "app/ops/native_operations_acceptance_runner.py",
             "app/ops/operations_acceptance.py", "app/ops/native_channel_probe.py",
             "tests/operations/live_operations_acceptance.py", "tests/operations/operations_acceptance_recovery.py",
             "tests/companion_ui/live_operations_acceptance.py")
PACKAGE_PROBE = r'''
import hashlib,importlib.metadata as m,json,pathlib,platform,sys,sysconfig
import mimer_mcp_sidecar
from mimer_mcp_sidecar.semantic import MimerMcpServer
d=m.distribution('mimer-mcp-sidecar'); sdk=m.distribution('mcp')
def files(distribution,prefix):
 out={}
 for f in distribution.files or []:
  if str(f).startswith(prefix) and '__pycache__' not in str(f) and str(f).endswith('.py'):
   p=pathlib.Path(distribution.locate_file(f))
   if p.is_symlink() or not p.is_file(): raise ValueError('installed package resource unavailable')
   out[str(f)]=hashlib.sha256(p.read_bytes()).hexdigest()
 if not out: raise ValueError('installed package resources missing')
 return out
package_root=pathlib.Path(mimer_mcp_sidecar.__file__).parent
package_files={}
for p in package_root.rglob('*.py'):
 if p.is_symlink() or not p.is_file(): raise ValueError('sidecar resource unavailable')
 package_files['mimer_mcp_sidecar/'+str(p.relative_to(package_root))]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps({'distribution':d.metadata['Name'],'version':d.version,'files':package_files,
 'v1_contract':[tool.as_dict() for tool in MimerMcpServer.for_loopback().list_tools()],
 'sdk_version':sdk.version,'sdk_files':files(sdk,'mcp/'),
 'metadata_sha256':hashlib.sha256(d.read_text('METADATA').encode()).hexdigest(),
 'runtime':{'executable':sys.executable,'prefix':sys.prefix,'python':platform.python_version(),
 'platform':sys.platform,'machine':platform.machine(),'abi':sysconfig.get_config_var('SOABI')}}))
'''
BROWSER_PROBE = r'''
import hashlib,importlib.metadata as m,json,os,pathlib,re,subprocess,sys
# Ask the installed Playwright CLI for the same payload the native bootstrap
# provisions. Dry-run neither downloads nor installs, and starts no browser.
metadata=subprocess.run([sys.executable,'-I','-m','playwright','install','--dry-run','--only-shell','chromium'],
 capture_output=True,text=True,check=True,timeout=20).stdout
if len(metadata)>2*1024**2: raise ValueError('native browser metadata unavailable')
locations=[pathlib.Path(value.strip()) for value in re.findall(r'(?m)^[ \t]*Install location:[ \t]+([^\n]+)$',metadata)]
shells=[path for path in locations if re.fullmatch(r'chromium_headless_shell-[0-9]+',path.name)]
if len(shells)!=1: raise ValueError('native browser payload ambiguous')
root=shells[0]
if root.parent!=pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']) or root.is_symlink() or not root.is_dir():
 raise ValueError('native browser payload unavailable')
executables=[]
for count,path in enumerate(root.rglob('*')):
 if count>=10000: raise ValueError('native browser resource budget exceeded')
 if path.name in {'headless_shell','chrome-headless-shell'} and (path.is_file() or path.is_symlink()):
  executables.append(path)
if len(executables)!=1: raise ValueError('native browser executable ambiguous')
executable=executables[0]
if any(path.is_symlink() for path in (executable,*executable.parents) if path==root or root in path.parents):
 raise ValueError('native browser unavailable')
if not executable.is_file() or executable.stat().st_size>1024**3: raise ValueError('native browser unavailable')
with executable.open('rb') as stream: measured=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({'playwright':m.version('playwright'),'executable':str(executable),'executable_sha256':measured}))
'''


def command(argv: list[str], *, payload: dict[str, Any] | None = None, cwd: Path | None = None) -> str:
    try:
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
            "PLAYWRIGHT_BROWSERS_PATH": "/opt/yggdrasil/bws-deploy-runtime/browsers"}
        result = subprocess.run(argv, input=json.dumps(payload) if payload is not None else None,
            cwd=cwd, env=environment, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError()
        return result.stdout
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise OperationsAcceptanceRefusal("native_owner_port_unavailable") from None


class NativeChannel:
    """The native source owner, with one finite fixed operation context."""
    def __init__(self, channel: str, operation_id: str) -> None:
        inventory(channel)
        if str(UUID(operation_id)) != operation_id:
            raise OperationsAcceptanceRefusal("native_operation_identity_invalid")
        self.channel, self.operation_id = channel, operation_id
        self.identity: dict[str, Any] | None = None
        self.repository: Path | None = None
        self.restart_binding: dict[str, Any] | None = None

    def _native(self, expected_operation_id: str | None = None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        # This path reads original receipt/request facts. It obtains no BWS
        # reader, channel lock, native lease, controller or deploy authority.
        from app.ops.postgres_deploy_linux import LinuxConfig
        config = LinuxConfig.load(self.channel, require_runtime_env=False)
        receipt, plan = self._native_record(config, expected_operation_id or self.operation_id)
        return config.root, receipt, plan

    def _native_record(self, config: Any, expected: str, *, historical: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        """Use the existing native current/historical contract readers only."""
        from app.ops.postgres_deploy import DeployPlan
        from app.ops.pg_acceptance import require_pass
        receipt = config.journal.operation_receipt(expected) if historical else config.journal.read()
        request = config.journal.operation_request(expected) if historical else config.journal.current_request()
        if (receipt is None or receipt.operation_id != expected
            or receipt.terminal_result != "committed" or receipt.activation_scope != "full"
            or request is None or request[0].get("operation_id") != expected or request[0].get("bootstrap") is not False
            or receipt.pg_acceptance is None):
            raise OperationsAcceptanceRefusal("current_committed_full_native_operation_required")
        plan = request[1]
        if not isinstance(plan, DeployPlan):
            raise OperationsAcceptanceRefusal("native_request_binding_mismatch")
        require_pass(receipt.pg_acceptance, plan.revision, plan.image_digest or "", self.channel, expected)
        if plan.channel != self.channel or plan.activation_scope != "full":
            raise OperationsAcceptanceRefusal("native_request_binding_mismatch")
        return asdict(receipt), plan.payload()

    def _running(self, revision: str, image_digest: str) -> dict[str, Any]:
        observed = {}
        for service in ("api", "companion-ui"):
            identifiers = command(["docker", "ps", "-q", "--no-trunc", "--filter",
                "label=com.docker.compose.project=pkm-" + self.channel, "--filter",
                "label=com.docker.compose.service=" + service]).split()
            if len(identifiers) != 1 or re.fullmatch(r"[0-9a-f]{64}", identifiers[0]) is None:
                raise OperationsAcceptanceRefusal("running_channel_service_unavailable")
            rows = json.loads(command(["docker", "inspect", identifiers[0]]))
            if len(rows) != 1:
                raise OperationsAcceptanceRefusal("running_channel_identity_ambiguous")
            row = rows[0]
            labels = row["Config"].get("Labels", {})
            images = json.loads(command(["docker", "image", "inspect", row["Image"]]))
            if (not row["State"]["Running"] or labels.get("org.opencontainers.image.revision") != revision
                or labels.get("com.docker.compose.project") != "pkm-" + self.channel
                or labels.get("com.docker.compose.service") != service
                or len(images) != 1 or not any(ref.endswith("@" + image_digest) for ref in images[0].get("RepoDigests", []))):
                raise OperationsAcceptanceRefusal("running_channel_candidate_mismatch")
            for mount in row.get("Mounts", []):
                destination = PurePosixPath(mount.get("Destination", "/"))
                if any(PurePosixPath("/app/" + name).is_relative_to(destination) or destination.is_relative_to(PurePosixPath("/app/" + name))
                       for name in BAKED):
                    raise OperationsAcceptanceRefusal("running_candidate_code_overlay")
            environment = dict(entry.split("=", 1) for entry in row["Config"].get("Env", []) if "=" in entry)
            if (row["Config"].get("Entrypoint") is not None
                or environment.get("PKM_ENVIRONMENT") != self.channel
                or environment.get("PKM_ACTIVATION_SCOPE", "full") != "full"
                or environment.get("VCS_REF") != revision):
                raise OperationsAcceptanceRefusal("actual_channel_configuration_mismatch")
            observed[service] = row
        # Bind actual upstream/start command/published ports using the passive
        # canonical gateway reader; it does not navigate or initialize state.
        from app.ops.native_channel_probe import validate_native_gateway
        api_port, ui_port = ((18001, 8111) if self.channel == "dev" else (18002, 8112))
        values = {"channel": self.channel, "expected_sha": revision,
                  "api_url": f"http://127.0.0.1:{api_port}", "ui_url": f"http://127.0.0.1:{ui_port}"}
        resolved = json.loads(command(["docker", "exec", observed["companion-ui"]["Id"], "python", "-c",
            "import json,socket;print(json.dumps(sorted({x[4][0] for x in socket.getaddrinfo('api',8000,type=socket.SOCK_STREAM)})))"]))
        validate_native_gateway(values, observed["api"], observed["companion-ui"], resolved)
        return observed

    def _git(self, root: Path, *args: str) -> str:
        return command(["git", "--no-replace-objects", "-C", str(root), *args])

    def _qualified_running(self, root: Path, revision: str, image_digest: str,
                           receipt: dict[str, Any]) -> dict[str, Any]:
        """Same actual startup qualification for fresh and retained processes."""
        running = self._running(revision, image_digest)
        import yaml
        compose = yaml.safe_load(self._git(root, "show", revision + ":docker-compose.yaml"))
        expected_command = [item.replace("$$", "$") for item in compose["services"]["api"]["command"]]
        if (running["api"]["Config"].get("Cmd") != expected_command
            or running["api"]["Config"].get("WorkingDir") != "/app"
            or running["companion-ui"]["Config"].get("WorkingDir") != "/app/companion-ui/companion-app"
            or running["api"]["Image"] != receipt["pg_acceptance"]["app_image_id"]):
            raise OperationsAcceptanceRefusal("actual_native_program_or_image_mismatch")
        return running

    def _package(self, root: Path, revision: str) -> dict[str, Any]:
        package = json.loads(command([str(SDK_PYTHON), "-I", "-c", PACKAGE_PROBE]))
        files = {}
        records = self._git(root, "ls-tree", "-r", revision, "--", "mimer-mcp-sidecar/mimer_mcp_sidecar")
        for record in records.splitlines():
            header, name = record.split("\t")
            mode, kind, oid = header.split()
            if mode not in {"100644", "100755"} or kind != "blob":
                raise OperationsAcceptanceRefusal("sidecar_source_resource_unqualified")
            # Ask Git for the exact byte hash through a bounded fixed Python
            # port; text newline conversion cannot qualify installed bytes.
            content = subprocess.run(["git", "--no-replace-objects", "-C", str(root), "cat-file", "blob", oid],
                capture_output=True, check=True, timeout=20).stdout
            import hashlib
            files[name.removeprefix("mimer-mcp-sidecar/")] = hashlib.sha256(content).hexdigest()
        if package.get("distribution") != "mimer-mcp-sidecar" or package.get("files") != files:
            raise OperationsAcceptanceRefusal("installed_sidecar_differs_from_candidate")
        version = re.fullmatch(r"1\.([0-9]+)\.[0-9]+", str(package.get("sdk_version")))
        if version is None or int(version[1]) < 29:
            raise OperationsAcceptanceRefusal("official_sdk_version_outside_distribution_contract")
        package["browser"] = json.loads(command([str(SDK_PYTHON), "-I", "-c", BROWSER_PROBE]))
        package["source_sha"] = revision
        return package

    def _resources(self, root: Path, revision: str) -> tuple[dict[str, str], dict[str, str]]:
        resources = {}
        records = self._git(root, "ls-tree", "-r", revision, "--", *BAKED, *PRODUCERS)
        producers = {}
        import hashlib
        for record in records.splitlines():
            header, name = record.split("\t")
            mode, kind, oid = header.split()
            if mode not in {"100644", "100755"} or kind != "blob":
                raise OperationsAcceptanceRefusal("candidate_resource_unqualified")
            content = subprocess.run(["git", "--no-replace-objects", "-C", str(root), "cat-file", "blob", oid],
                capture_output=True, check=True, timeout=20).stdout
            measured = hashlib.sha256(content).hexdigest()
            if name in PRODUCERS:
                if file_hash(root / name) != measured:
                    raise OperationsAcceptanceRefusal("executed_producer_differs_from_candidate")
                producers[name] = measured
            if any(name == path or name.startswith(path + "/") for path in BAKED):
                resources[name] = measured
        if set(producers) != set(PRODUCERS):
            raise OperationsAcceptanceRefusal("committed_operations_producer_missing")
        return resources, producers

    def admit(self) -> dict[str, Any]:
        from app.ops.postgres_deploy_linux import LinuxConfig
        config = LinuxConfig.load(self.channel, require_runtime_env=False)
        current = config.journal.read()
        if current is not None and current.operation_id != self.operation_id:
            return self._retained_admission(config)
        root, receipt, plan = self._native()
        revision, image_digest = plan["revision"], plan["image_digest"]
        running = self._qualified_running(root, revision, image_digest, receipt)
        package = self._package(root, revision)
        resources, producers = self._resources(root, revision)
        identity = {"profile": PROFILE, "selection_hash": SELECTION_HASH, "channel": self.channel,
            "operation_id": self.operation_id, "source_sha": revision, "image_digest": image_digest,
            "restart_operation_id": str(uuid5(UUID(self.operation_id), PROFILE + ":backend-wsp-restart")),
            "resource_tree": self._git(root, "rev-parse", revision + "^{tree}").strip(),
            "resource_hashes": resources, "producer_hashes": producers, "sidecar": package, "activation_scope": "full",
            "execution_kind": running["api"]["Config"].get("Labels", {}).get("io.yggdrasil.acceptance-kind", "deployed"),
            "native_receipt_sha256": digest(receipt),
            "api_container_id": running["api"]["Id"], "ui_container_id": running["companion-ui"]["Id"],
            "api_image_id": running["api"]["Image"], "ui_image_id": running["companion-ui"]["Image"]}
        require_identity(identity)
        # The fixed baked producer rechecks current program, native principal,
        # instance/binding, canonical sources and restore state before writing
        # a narrowing record outside the vault. No caller manifest is accepted.
        context = json.loads(command(["docker", "exec", "-i", identity["api_container_id"],
            "python", "-m", "app.api.native_operations_acceptance", "prepare"], payload=identity))
        if context["identity"] != identity:
            raise OperationsAcceptanceRefusal("original_native_producer_binding_mismatch")
        self.identity = identity
        self.repository = root
        return context

    def _retained_admission(self, config: Any) -> dict[str, Any]:
        """Recover only the exact existing original and committed successor.

        No prepare command, new context, selection or effect is permitted on
        this path. The protected native history and actual replacement process
        qualify a read of the original retained context, never a new approval.
        """
        successor = str(uuid5(UUID(self.operation_id), PROFILE + ":backend-wsp-restart"))
        root, current, plan = self._native(successor)
        original, original_plan = self._native_record(config, self.operation_id, historical=True)
        if (plan["revision"] != original_plan["revision"] or plan["image_digest"] != original_plan["image_digest"]
            or "api" not in plan["services"]):
            raise OperationsAcceptanceRefusal("separate_native_restart_receipt_unqualified")
        running = self._qualified_running(root, plan["revision"], plan["image_digest"], current)
        probe = json.loads(command(["docker", "exec", running["api"]["Id"],
            "python", "-m", "app.api.native_operations_acceptance", "probe"]))
        binding = probe["binding"]
        identity = binding["identity"]
        require_identity(identity, channel=self.channel)
        resources, producers = self._resources(root, plan["revision"])
        if (not binding.get("selection") or not binding.get("slots")
            or identity["operation_id"] != self.operation_id or identity.get("restart_operation_id") != successor
            or identity["source_sha"] != original_plan["revision"] or identity["image_digest"] != original_plan["image_digest"]
            or identity["native_receipt_sha256"] != digest(original)
            or identity["resource_tree"] != self._git(root, "rev-parse", plan["revision"] + "^{tree}").strip()
            or identity["resource_hashes"] != resources or identity["producer_hashes"] != producers
            or identity["sidecar"] != self._package(root, plan["revision"])
            or identity["api_image_id"] != running["api"]["Image"] or identity["ui_image_id"] != running["companion-ui"]["Image"]
            or identity["execution_kind"] != running["api"]["Config"].get("Labels", {}).get("io.yggdrasil.acceptance-kind", "deployed")):
            raise OperationsAcceptanceRefusal("foreign_or_changed_retained_native_context")
        self.identity, self.repository = identity, root
        if self.observe_restart().get("status") != "observed":
            raise OperationsAcceptanceRefusal("separate_native_restart_receipt_unqualified")
        if self.observe()["binding"] != binding:
            raise OperationsAcceptanceRefusal("original_native_producer_binding_mismatch")
        return binding

    def observe(self) -> dict[str, Any]:
        if self.identity is None:
            raise OperationsAcceptanceRefusal("native_admission_required")
        if self.restart_binding is None:
            from app.ops.postgres_deploy_linux import LinuxConfig
            current = LinuxConfig.load(self.channel, require_runtime_env=False).journal.read()
            if current is not None and current.operation_id == self.identity["restart_operation_id"]:
                if self.observe_restart().get("status") != "observed":
                    raise OperationsAcceptanceRefusal("separate_native_restart_receipt_unqualified")
        expected = self.restart_binding["operation_id"] if self.restart_binding else self.operation_id
        root, receipt, plan = self._native(expected)
        receipt_hash = self.restart_binding["native_receipt_sha256"] if self.restart_binding else self.identity["native_receipt_sha256"]
        if (plan["revision"] != self.identity["source_sha"] or plan["image_digest"] != self.identity["image_digest"]
            or digest(receipt) != receipt_hash
            or any(file_hash(root / name) != expected for name, expected in self.identity["producer_hashes"].items())
            or self._package(root, plan["revision"]) != self.identity["sidecar"]):
            raise OperationsAcceptanceRefusal("current_native_candidate_changed")
        running = self._qualified_running(root, plan["revision"], plan["image_digest"], receipt)
        process_binding = self.restart_binding or self.identity
        if any(running[service]["Id"] != process_binding[key] for service, key in
               (("api", "api_container_id"), ("companion-ui", "ui_container_id"))):
            raise OperationsAcceptanceRefusal("channel_process_replaced")
        return json.loads(command(["docker", "exec", process_binding["api_container_id"],
            "python", "-m", "app.api.native_operations_acceptance", "probe"]))

    def observe_restart(self) -> dict[str, Any]:
        """Observe only the separately owned fixed native successor; never run it.

        Namespace identity is no grant. PASS needs the existing native owner's
        original committed request/receipt and an actual replacement process.
        No foreign current operation is joined, retried, stopped or repaired.
        """
        if self.identity is None:
            raise OperationsAcceptanceRefusal("native_admission_required")
        expected = self.identity["restart_operation_id"]
        from app.ops.postgres_deploy_linux import LinuxConfig
        config = LinuxConfig.load(self.channel, require_runtime_env=False)
        current = config.journal.read()
        if current is None or current.operation_id != expected or current.terminal_result != "committed":
            return {"status": "blocked", "separate_native_authority": False,
                "expected_operation_id": expected, "reason": "separately_authorized_native_backend_wsp_restart_required"}
        root, receipt, plan = self._native(expected)
        original, original_plan = self._native_record(config, self.operation_id, historical=True)
        if (digest(original) != self.identity["native_receipt_sha256"]
            or original_plan["revision"] != self.identity["source_sha"] or original_plan["image_digest"] != self.identity["image_digest"]
            or plan["revision"] != self.identity["source_sha"] or plan["image_digest"] != self.identity["image_digest"]
            or "api" not in plan["services"] or self._package(root, plan["revision"]) != self.identity["sidecar"]):
            raise OperationsAcceptanceRefusal("separate_native_restart_receipt_unqualified")
        running = self._qualified_running(root, plan["revision"], plan["image_digest"], receipt)
        if (running["api"]["Image"] != receipt["pg_acceptance"]["app_image_id"]
            or running["api"]["Image"] != self.identity["api_image_id"]
            or running["companion-ui"]["Image"] != self.identity["ui_image_id"]
            or running["api"]["Id"] == self.identity["api_container_id"]):
            raise OperationsAcceptanceRefusal("actual_backend_replacement_not_observed")
        self.restart_binding = {"operation_id": expected, "native_receipt_sha256": digest(receipt),
            "api_container_id": running["api"]["Id"], "ui_container_id": running["companion-ui"]["Id"]}
        return {"status": "observed", "separate_native_authority": True,
                "original_native_receipt": receipt, "restart_binding": self.restart_binding,
                "source_sha": plan["revision"], "image_digest": plan["image_digest"], "source_replays": 0}
