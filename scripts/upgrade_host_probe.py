#!/usr/bin/env python3
"""Run the one-off, reviewed production probe source upgrade.

The target, source revisions, package closure, and remote interpreter are
fixed.  The only live input is the already-observed Issue lease, which binds
the operation to the normal claim path.  This command is not a deployment
framework and cannot select another service or filesystem path.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import time
from io import BytesIO
from typing import Any

from probe_upgrade_operation import (
    BODY_SHA256,
    RENDERING_INSTALLATION_BODY_SHA256,
    RENDERING_INSTALLATION_ISSUE,
    RENDERING_MANIFEST_SHA256,
    RENDERING_SCRIPT_SHA256,
    RENDERING_SOURCE_MERGE,
    OperationFailure,
    _bounded_process,
    _manifest_digest,
    _rendering_authority,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = REPOSITORY_ROOT / "scripts/probe_script_swap_core.py"
OPERATION_PATH = REPOSITORY_ROOT / "scripts/probe_upgrade_operation.py"
LOCAL_RECORD_ROOT = REPOSITORY_ROOT / ".codex-tmp/probe-upgrade-6457"
PACKAGE_PATHS = (
    "app/__init__.py",
    "app/ops",
    "config/secrets/host_secret_contract.json",
    "config/systemd/yggdrasil-host-probe@.service",
    "ops/host-setup/linux/host_probe_launcher.py",
    "ops/host-setup/mac-mini/notification_channels.py",
    "ops/host-setup/mac-mini/prod_probe.py",
)
OLD_SOURCE = "777726d3139fc82cd69097dcd3bccc4d1c6c167a"
SOURCE_MERGE = "0d064c012296589e92987c1f374fa18b05104f7b"
OLD_ARCHIVE_SHA256 = "4703dc31210b536d9f09cae2b6b3d355225f03d1e850b5995b5d88d9da2c4cdd"
OLD_SCRIPT_SHA256 = "bde4a4d8b57baaba998b1ac8a5158551f0b0ee52b9a89bb2ecec7bef1ab1750b"
NEW_SCRIPT_SHA256 = "0172b37565a067c26acd37afed8d650be7a56117ad1962860446fd18353058ac"
EXPECTED_INSTALLED_MANIFEST_SHA256 = (
    "3ae600b78abefb751ef8fd73e7639b75a41b09f30d44fd4d06b1bb77101ae861"
)
TARGET_HOST = "ygg-prod"
REMOTE_INTERPRETER = "/opt/yggdrasil/bws-deploy-runtime/bin/python3"
TASK_ID = "github-RasmusTho--agentic-pkm-mvp-issue-6457"
ISSUE = 6457
PARENT_ISSUE = 4076
HOLDER = "codex-4076-upgrade-6457-sol"
SESSION = "01a187d4-0219-7811-b100-16322d5ad554"
EXPECTED_BRANCH = "codex/issue-6457-probe-upgrade-sol"


class CarrierRefusal(Exception):
    pass


class CarrierUnknown(Exception):
    pass


@dataclass(frozen=True)
class Archive:
    manifest: dict[str, dict[str, Any]]
    files: dict[str, bytes]
    archive_sha256: str


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode or result.stderr:
        raise CarrierRefusal("repository readback unavailable")
    return result.stdout.strip()


def _git_bytes(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode or result.stderr:
        raise CarrierRefusal("repository byte readback unavailable")
    return result.stdout


def _archive(revision: str) -> Archive:
    result = subprocess.run(
        ["git", "archive", "--format=tar", revision, "--", *PACKAGE_PATHS],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode or result.stderr:
        raise CarrierRefusal("source archive unavailable")
    archive_sha256 = hashlib.sha256(result.stdout).hexdigest()
    manifest: dict[str, dict[str, Any]] = {}
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            if member.name in manifest or member.mode != 0o664:
                raise CarrierRefusal("source archive metadata mismatch")
            source = bundle.extractfile(member)
            if source is None:
                raise CarrierRefusal("source archive content unavailable")
            data = source.read()
            files[member.name] = data
            manifest[member.name] = {
                "mode": member.mode,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    if len(manifest) != 60:
        raise CarrierRefusal("source closure is not exactly 60 files")
    return Archive(manifest, files, archive_sha256)


def _source_pair() -> tuple[Archive, Archive, str]:
    old = _archive(OLD_SOURCE)
    if old.archive_sha256 != OLD_ARCHIVE_SHA256:
        raise CarrierRefusal("old archive digest mismatch")
    head = _git("rev-parse", "HEAD")
    if not _git("merge-base", "--is-ancestor", SOURCE_MERGE, head) == "":
        # ``git merge-base --is-ancestor`` has no stdout on success; failure
        # is surfaced by _git as a non-zero result.
        raise CarrierRefusal("reviewed source merge is not an ancestor")
    script = _git_bytes("show", f"{SOURCE_MERGE}:ops/host-setup/mac-mini/prod_probe.py")
    if hashlib.sha256(script).hexdigest() != NEW_SCRIPT_SHA256:
        raise CarrierRefusal("new script digest mismatch")
    if (
        hashlib.sha256(old.files["ops/host-setup/mac-mini/prod_probe.py"]).hexdigest()
        != OLD_SCRIPT_SHA256
    ):
        raise CarrierRefusal("old script digest mismatch")
    new_manifest = dict(old.manifest)
    new_files = dict(old.files)
    new_files["ops/host-setup/mac-mini/prod_probe.py"] = script
    new_manifest["ops/host-setup/mac-mini/prod_probe.py"] = {
        "mode": 0o664,
        "size": len(script),
        "sha256": NEW_SCRIPT_SHA256,
    }
    manifest_rows = [
        {"mode": value["mode"], "path": path, "sha256": value["sha256"], "size": value["size"]}
        for path, value in new_manifest.items()
    ]
    manifest_sha = hashlib.sha256(
        json.dumps(manifest_rows, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest_sha != EXPECTED_INSTALLED_MANIFEST_SHA256:
        raise CarrierRefusal("installed manifest binding mismatch")
    new = Archive(new_manifest, new_files, "")
    return old, new, head


def _rendering_source_pair() -> tuple[Archive, Archive, str]:
    """Retain the original 59 files and replace only the verified 0172 script."""
    _, before, head = _source_pair()
    _git("merge-base", "--is-ancestor", RENDERING_SOURCE_MERGE, head)
    script = _git_bytes("show", f"{RENDERING_SOURCE_MERGE}:ops/host-setup/mac-mini/prod_probe.py")
    if len(script) != 28_710 or hashlib.sha256(script).hexdigest() != RENDERING_SCRIPT_SHA256:
        raise CarrierRefusal("verified rendering script binding mismatch")
    manifest = dict(before.manifest)
    files = dict(before.files)
    files["ops/host-setup/mac-mini/prod_probe.py"] = script
    manifest["ops/host-setup/mac-mini/prod_probe.py"] = {
        "mode": 0o664,
        "size": len(script),
        "sha256": RENDERING_SCRIPT_SHA256,
    }
    if _manifest_digest(manifest) != RENDERING_MANIFEST_SHA256:
        raise CarrierRefusal("verified rendering manifest binding mismatch")
    return before, Archive(manifest, files, ""), head


def _lease_readback(lease_id: str, *, rendering_successor: bool = False) -> dict[str, Any]:
    issue_number, holder, session, branch, body_sha = (
        ISSUE,
        HOLDER,
        SESSION,
        EXPECTED_BRANCH,
        BODY_SHA256,
    )
    if rendering_successor:
        issue_number, body_sha = RENDERING_INSTALLATION_ISSUE, RENDERING_INSTALLATION_BODY_SHA256
        session = os.environ.get("CODEX_THREAD_ID", "")
        holder = session  # This fixed live pickup uses --agent "$CODEX_THREAD_ID".
        if not session or Path.cwd().resolve() != REPOSITORY_ROOT:
            raise CarrierRefusal(
                "rendering installation requires its actual owner runtime worktree"
            )
        if _git("rev-parse", "--show-toplevel") != str(REPOSITORY_ROOT):
            raise CarrierRefusal("rendering installation Git worktree differs from its runtime")
        branch = _git("branch", "--show-current")
        if _git("status", "--porcelain"):
            raise CarrierRefusal("rendering installation requires a clean source checkout")
    task_id = f"github-RasmusTho--agentic-pkm-mvp-issue-{issue_number}"
    if not lease_id.startswith("lease-"):
        raise CarrierRefusal("lease id is malformed")
    if _git("branch", "--show-current") != branch:
        raise CarrierRefusal("actual worktree branch differs from its sole-owner receipt")
    result = _bounded_process(
        [sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
        timeout=15,
        limit=262_144,
        environment=dict(os.environ),
    )
    if result.returncode or result.stderr:
        raise CarrierRefusal("dispatcher lease readback unavailable")
    try:
        payload = json.loads(result.stdout)
        task, lease = payload["task"], payload["lease"]
        expiry = datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
        valid = (
            payload["ok"] is True
            and task["task_id"] == task_id
            and task["repo"] == "RasmusTho/agentic-pkm-mvp"
            and task["issue_number"] == issue_number
            and task["status"] == "claimed"
            and task["claimed_by"] == lease["holder"] == holder
            and task["lease_id"] == lease["lease_id"] == lease_id
            and lease["resource"] == f"issue:{issue_number}"
            and lease["released_at"] is None
            and expiry > datetime.now(timezone.utc)
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        raise CarrierRefusal("dispatcher lease readback malformed") from None
    if not valid:
        raise CarrierRefusal("dispatcher lease is not owned by this operation")
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from scripts.agent_worktree import (
        WorktreeLifecycleError,
        load_lifecycle_authority,
        load_lifecycle_records,
    )

    records = load_lifecycle_records(REPOSITORY_ROOT)
    record = records.get(str(REPOSITORY_ROOT))
    if rendering_successor:
        try:
            record = load_lifecycle_authority(REPOSITORY_ROOT, candidate_branch=branch).get(
                str(REPOSITORY_ROOT)
            )
        except (WorktreeLifecycleError, OSError, RuntimeError, subprocess.SubprocessError):
            raise CarrierRefusal(
                "rendering installation worktree authority is unqualified"
            ) from None
    if (
        not record
        or record.get("owner") != session
        or record.get("branch") != branch
        or record.get("status") != "active"
        or record.get("expires_at", 0) <= time.time()
        or (rendering_successor and record.get("path") != str(REPOSITORY_ROOT))
    ):
        raise CarrierRefusal("sole registered worktree is not owned by the successor")
    if (
        rendering_successor
        and sum(
            item.get("owner") == session
            and item.get("status") == "active"
            and item.get("expires_at", 0) > time.time()
            for item in records.values()
        )
        != 1
    ):
        raise CarrierRefusal("rendering installation has more than one active owner worktree")
    github = _bounded_process(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--json",
            "body,state,labels",
        ],
        timeout=15,
        limit=65_536,
        environment=dict(os.environ),
    )
    try:
        issue = json.loads(github.stdout)
        valid = (
            not github.returncode
            and not github.stderr
            and issue["state"] == "OPEN"
            and {x["name"] for x in issue["labels"]}
            == {"type:task", "prio:high", "agent:in-progress"}
            and hashlib.sha256(issue["body"].encode()).hexdigest() == body_sha
        )
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        raise CarrierRefusal("governing Issue body or sole active claim changed")
    result = {
        **task,
        "lease_expires_at": lease["expires_at"],
        "registration_generation": record["generation"],
    }
    if rendering_successor:
        head = _git("rev-parse", "HEAD")
        for path in (CORE_PATH, OPERATION_PATH, Path(__file__).resolve()):
            committed = _git_bytes("show", f"{head}:{path.relative_to(REPOSITORY_ROOT)}")
            if path.read_bytes() != committed:
                raise CarrierRefusal(
                    "rendering operation programs differ from the claimed source head"
                )
        result["installation_authority"] = _rendering_authority(
            {
                "issue": issue_number,
                "body_sha256": body_sha,
                "holder": holder,
                "session": session,
                "branch": branch,
                "worktree": str(REPOSITORY_ROOT),
                "source_head": head,
                "registration_generation": record["generation"],
                "scope": "install-0172-to-17c2-on-ygg-prod-under-4076",
            }
        )
    return result


def _worker_source() -> bytes:
    return (
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0,str(Path(__file__).resolve().parent))\n"
        "import probe_upgrade_operation\n"
        "raise SystemExit(probe_upgrade_operation.worker_main(sys.argv[1]))\n"
    ).encode()


def _programs() -> dict[str, bytes]:
    return {
        "probe_script_swap_core.py": CORE_PATH.read_bytes(),
        "probe_upgrade_operation.py": OPERATION_PATH.read_bytes(),
        "worker.py": _worker_source(),
    }


def _request(
    operation: str,
    lease_id: str,
    old: Archive,
    new: Archive,
    *,
    lease_expires_at: str,
    installation_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    programs = _programs()
    request = {
        "packet": {
            "issue": ISSUE,
            "parent_issue": PARENT_ISSUE,
            "source_merge": SOURCE_MERGE,
            "claim_holder": HOLDER,
            "lease_id": lease_id,
            "operation": operation,
        },
        "before_manifest": old.manifest,
        "after_manifest": new.manifest,
        "old_base64": base64.b64encode(old.files["ops/host-setup/mac-mini/prod_probe.py"]).decode(),
        "new_base64": base64.b64encode(new.files["ops/host-setup/mac-mini/prod_probe.py"]).decode(),
        "program_sha256": {
            name: hashlib.sha256(data).hexdigest() for name, data in programs.items()
        },
        "contract_body_sha256": BODY_SHA256,
        "lease_expires_at": lease_expires_at,
    }
    if installation_authority is not None:
        authority = _rendering_authority(installation_authority)
        request["packet"].update(
            issue=authority["issue"],
            source_merge=RENDERING_SOURCE_MERGE,
            claim_holder=authority["holder"],
            installation_authority=authority,
        )
        request["contract_body_sha256"] = authority["body_sha256"]
    return request


def _remote_payload(
    action: str, request: dict[str, Any], handle: dict[str, Any] | None = None
) -> bytes:
    programs = _programs()
    if {name: hashlib.sha256(data).hexdigest() for name, data in programs.items()} != request[
        "program_sha256"
    ]:
        raise CarrierRefusal("original frozen operation programs changed")
    encoded = {name: base64.b64encode(data).decode() for name, data in programs.items()}
    return (
        "import base64,json,sys,types\n"
        f"_sources=json.loads({json.dumps(encoded)!r})\n"
        "_core=types.ModuleType('probe_script_swap_core'); exec(base64.b64decode(_sources['probe_script_swap_core.py']),_core.__dict__); sys.modules['probe_script_swap_core']=_core\n"
        "_op=types.ModuleType('probe_upgrade_operation'); exec(base64.b64decode(_sources['probe_upgrade_operation.py']),_op.__dict__)\n"
        f"_request=json.loads({json.dumps(request,sort_keys=True,separators=(',',':'))!r})\n"
        f"_handle=json.loads({json.dumps(handle)!r})\n"
        "try:\n"
        f"    _result=_op.remote_entry({action!r},_request,programs={{n:base64.b64decode(b) for n,b in _sources.items()}},expected_handle=_handle)\n"
        "except BaseException as _error:\n"
        "    _result={'schema':'probe_installation.v1','operation':_request['packet']['operation'],'status':'unknown' if not isinstance(_error,_op.OperationFailure) or _error.unknown else 'refused','failure':_error.reason if isinstance(_error,_op.OperationFailure) else 'remote_operation_unhandled','test_acceptance':False}\n"
        "sys.stdout.write(json.dumps(_result,sort_keys=True,separators=(',',':')))\n"
    ).encode()


def _ssh(payload: bytes) -> dict[str, Any]:
    command = [
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "PermitLocalCommand=no",
        "--",
        TARGET_HOST,
        "sudo",
        "-n",
        REMOTE_INTERPRETER,
        "-I",
        "-B",
        "-",
    ]
    environment = {
        key: os.environ[key] for key in ("HOME", "PATH", "SSH_AUTH_SOCK") if key in os.environ
    }
    try:
        result = _bounded_process(
            command, input_bytes=payload, timeout=30, limit=1_048_576, environment=environment
        )
    except (OSError, OperationFailure):
        raise CarrierUnknown("strict target transport unavailable or unknown") from None
    if result.returncode or result.stderr:
        raise CarrierUnknown("strict target operation returned no qualified receipt")
    try:
        receipt = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise CarrierUnknown("target receipt malformed") from None
    if not isinstance(receipt, dict) or receipt.get("schema") != "probe_installation.v1":
        raise CarrierUnknown("target receipt schema mismatch")
    return receipt


def _record_path(operation: str) -> Path:
    import re

    if not re.fullmatch(r"[0-9a-f]{32}", operation):
        raise CarrierRefusal("original operation id must be 32 lowercase hex characters")
    return LOCAL_RECORD_ROOT / (operation + ".json")


def _read_record(operation: str) -> dict[str, Any]:
    path = _record_path(operation)
    descriptor = None
    try:
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise CarrierRefusal("local original-handle directory ownership changed")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > 1_048_576
        ):
            raise CarrierRefusal("local original-handle ownership changed")
        raw = bytearray()
        while len(raw) <= 1_048_576:
            block = os.read(descriptor, min(65_536, 1_048_577 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(descriptor)
        slot = path.lstat()

        def signature(item):
            return (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mode,
                item.st_uid,
                item.st_nlink,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )

        if (
            len(raw) != before.st_size
            or signature(before) != signature(after)
            or signature(before) != signature(slot)
        ):
            raise CarrierRefusal("local original-handle record changed")
        value = json.loads(raw)
        if value["request"]["packet"]["operation"] != operation:
            raise CarrierRefusal("local original handle mismatches operation")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise CarrierRefusal("local original-handle record unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _save_record(operation: str, value: dict[str, Any], *, create: bool = False) -> None:
    path = _record_path(operation)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_meta = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_meta.st_mode)
        or parent_meta.st_uid != os.geteuid()
        or stat.S_IMODE(parent_meta.st_mode) != 0o700
    ):
        raise CarrierRefusal("local original-handle directory ownership changed")
    if not create and _read_record(operation)["request"] != value["request"]:
        raise CarrierRefusal("original local request changed")
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if create:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        temporary = None
    else:
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(descriptor)
    try:
        view = memoryview(raw)
        while view:
            size = os.write(descriptor, view)
            if size <= 0:
                raise CarrierRefusal("local original-handle write incomplete")
            view = view[size:]
        os.fsync(descriptor)
        if temporary is not None:
            slot = temporary.lstat()
            if (slot.st_dev, slot.st_ino) != (created.st_dev, created.st_ino):
                raise CarrierRefusal("local operation stage became foreign")
            os.replace(temporary, path)
    finally:
        os.close(descriptor)
        if temporary is not None:
            try:
                slot = temporary.lstat()
                if (slot.st_dev, slot.st_ino) == (created.st_dev, created.st_ino):
                    temporary.unlink()
            except FileNotFoundError:
                pass
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def run(
    lease_id: str, operation: str, action: str = "apply", *, rendering_successor: bool = False
) -> dict[str, Any]:
    record: dict[str, Any]

    def claim_readback(rendering: bool) -> dict[str, Any]:
        return (
            _lease_readback(lease_id, rendering_successor=True)
            if rendering
            else _lease_readback(lease_id)
        )

    if action == "apply":
        task = claim_readback(rendering_successor)
        old, new, head = _rendering_source_pair() if rendering_successor else _source_pair()
        if rendering_successor and task["installation_authority"]["source_head"] != head:
            raise CarrierRefusal("rendering installation source head changed")
        if _record_path(operation).exists():
            raise CarrierRefusal("original operation already exists; follow or reconcile it")
        record = {
            "request": _request(
                operation,
                lease_id,
                old,
                new,
                lease_expires_at=task["lease_expires_at"],
                installation_authority=task.get("installation_authority"),
            ),
            "source_head": head,
            "old_archive_sha256": old.archive_sha256,
            "handle": None,
            "authorization_sent": False,
        }
        _save_record(operation, record, create=True)
        remote_action = "prepare"
    else:
        record = _read_record(operation)
        actual_rendering = "installation_authority" in record["request"]["packet"]
        if rendering_successor and not actual_rendering:
            raise CarrierRefusal("rendering follow requires its original successor request")
        rendering_successor = actual_rendering
        try:
            task = claim_readback(rendering_successor)
        except Exception:
            if action == "reconcile":
                return {
                    "schema": "probe_installation.v1",
                    "operation": operation,
                    "status": "unknown",
                    "handle": record["handle"],
                    "failure": "current_claim_unqualified_for_reconciliation",
                    "next_action": "follow this original handle read-only; restore the normal Issue claim before recovery effects",
                }
            # Reading the original operation cannot borrow mutation authority.
            # It remains available when a claim must first be repaired.
            task = {"lease_expires_at": None, "current_claim_verified": False}
        remote_action = "reconcile" if action == "reconcile" else "status"
    request = record["request"]
    try:
        receipt = _ssh(_remote_payload(remote_action, request, record["handle"]))
        if receipt.get("operation") != operation:
            raise CarrierUnknown("target receipt belongs to another operation")
        if receipt.get("handle"):
            if record["handle"] is not None and record["handle"] != receipt["handle"]:
                raise CarrierUnknown("target original handle changed")
            record["handle"] = receipt["handle"]
            _save_record(operation, record)
        if action == "apply" and receipt.get("status") == "pending" and record["handle"]:
            if rendering_successor:
                current = claim_readback(True)
                if current["installation_authority"] != request["packet"]["installation_authority"]:
                    raise CarrierRefusal("rendering installation claim identity changed")
            # Persist send intent first. A lost authorization response is followed,
            # never replayed as another apply or start.
            record["authorization_sent"] = True
            _save_record(operation, record)
            receipt = _ssh(_remote_payload("authorize", request, record["handle"]))
        deadline = time.monotonic() + 440.0
        while receipt.get("status") == "pending" and time.monotonic() < deadline:
            time.sleep(2.0)
            receipt = _ssh(_remote_payload("status", request, record["handle"]))
            if receipt.get("operation") != operation:
                raise CarrierUnknown("follow returned another operation")
        if receipt.get("status") == "pending":
            receipt.update(status="unknown", failure="original_operation_follow_bound")
    except (CarrierUnknown, CarrierRefusal, OSError, OperationFailure) as error:
        return {
            "schema": "probe_installation.v1",
            "operation": operation,
            "status": "unknown",
            "failure": str(error),
            "handle": record["handle"],
            "original_request_sha256": hashlib.sha256(
                json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "next_action": "follow the same operation id; reconcile only after its owned supervisor is reaped",
            "test_acceptance": False,
        }
    receipt["carrier"] = {
        "target_role": "production_probe_host",
        "source_head": record["source_head"],
        "old_archive_sha256": record["old_archive_sha256"],
        "strict_transport": True,
        "lease_expires_at": task["lease_expires_at"],
        "current_claim_verified": task.get("current_claim_verified", True),
        "original_operation": operation,
    }
    try:
        _save_record(operation, {**record, "last_receipt": receipt})
    except (CarrierRefusal, OSError):
        # The exact remote terminal receipt is already authoritative. Preserve
        # it even if a local copy cannot be persisted.
        receipt["local_receipt_persistence"] = "failed; original remote result retained"
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--rendering-successor", action="store_true")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--follow", action="store_true")
    modes.add_argument("--reconcile", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run(
            args.lease_id,
            args.operation,
            "apply" if args.apply else "reconcile" if args.reconcile else "follow",
            rendering_successor=args.rendering_successor,
        )
    except (CarrierUnknown, OperationFailure, CarrierRefusal, OSError) as error:
        prior_request = args.follow or args.reconcile
        handle = None
        record_path = None
        try:
            record_path = _record_path(args.operation)
            exists = record_path.exists()
            prior_request = prior_request or exists
            if exists:
                handle = _read_record(args.operation).get("handle")
        except (CarrierRefusal, OSError):
            # An existing unreadable handle is not proof that its effect failed.
            prior_request = prior_request or record_path is not None
        receipt = {
            "schema": "probe_installation.v1",
            "operation": args.operation,
            "status": "unknown"
            if prior_request or isinstance(error, (CarrierUnknown, OperationFailure))
            else "refused",
            "failure": str(error),
            "handle": handle,
        }
    print(json.dumps(receipt, sort_keys=True))
    return (
        0
        if receipt.get("status") == "committed"
        else 78
        if receipt.get("status") == "refused"
        else 79
    )


if __name__ == "__main__":
    raise SystemExit(main())
