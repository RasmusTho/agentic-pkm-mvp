"""One executable owner for the fixed start-model-inquiry skill mechanics.

No provider, credential provisioning, source mutation or generic command port
belongs here. Process calls below are the finite, host-owned workflow boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any

from app.builderops.devui_model_inquiry_command import (
    OPERATION_VERBS,
    OPERATION_VERSION,
    WORKFLOW_REF,
    validate_approval_identity,
)

SSH = "/usr/bin/ssh"
DESTINATION = "Tailscale_macmini"
LOCK = "/tmp/yggdrasil-model-inquiry.lock"
STAGE = "/tmp/model-inquiry-question.md"
LAUNCHER = '"$HOME/.local/bin/yggdrasil-model-inquiry"'
CONTRACT_PATH = Path(__file__).resolve().parents[2] / WORKFLOW_REF
_CONTROL_TIMEOUT = 60
_LAUNCH_TIMEOUT = 1800
_MAX_RESPONSE = 262144
_TERMINAL_FIELDS = ("inquiry_id", "final_state", "terminal_receipt_id", "human_readable_report")


class WorkflowUnavailable(ValueError):
    """The fixed workflow is unavailable; never select another executor."""


class StagingFailure(WorkflowUnavailable):
    def __init__(self, *, owned: bool) -> None:
        super().__init__("workflow staging unavailable")
        self.owned = owned


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def decode_object(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate response field")
            value[key] = item
        return value

    if len(raw) > _MAX_RESPONSE:
        raise ValueError("bounded response required")
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    if not isinstance(value, dict):
        raise ValueError("one JSON object required")
    return value


def workflow_binding() -> dict[str, str]:
    if CONTRACT_PATH.is_symlink() or not CONTRACT_PATH.is_file():
        raise WorkflowUnavailable("packaged workflow contract is unavailable")
    return {
        "version": "start-model-inquiry.v1",
        "content_hash": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
    }


class SanctionedModelInquiryWorkflow:
    """Concrete production facade; test doubles replace only the process boundary."""

    @staticmethod
    def _process(
        argv: list[str], *, stdin: bytes | None = None, timeout: int = _CONTROL_TIMEOUT
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(argv, input=stdin, capture_output=True, check=False, timeout=timeout)

    def _route(self) -> bool:
        """Return proven-local only from all three independent local bindings."""
        expanded = self._process([SSH, "-G", DESTINATION])
        if expanded.returncode:
            raise WorkflowUnavailable("fixed SSH destination is unavailable")
        settings: dict[str, str] = {}
        for line in expanded.stdout.decode("utf-8", errors="replace").splitlines():
            pair = line.split(None, 1)
            if len(pair) == 2:
                settings.setdefault(pair[0].lower(), pair[1])
        try:
            account = self._process(["/usr/bin/id", "-un"])
            user = account.stdout.decode().strip()
            if account.returncode or not user or settings.get("user") != user:
                return False
            home = self._process(
                ["/usr/bin/dscl", ".", "-read", f"/Users/{user}", "NFSHomeDirectory"]
            )
            if (
                home.returncode
                or home.stdout.decode().strip() != f"NFSHomeDirectory: {Path.home()}"
            ):
                return False
            hostname = settings.get("hostname", "")
            if not hostname or hostname.lower() == DESTINATION.lower():
                return False
            alias = settings.get("hostkeyalias", "")
            host = alias if alias and alias.lower() != "none" else hostname
            port = settings.get("port", "22")
            if host.startswith("-") or not port.isdecimal() or not 1 <= int(port) <= 65535:
                return False
            lookup = host if int(port) == 22 else f"[{host}]:{port}"
            keys: set[tuple[str, ...]] = set()
            for name in ("known_hosts", "known_hosts2"):
                pinned = self._process(
                    ["/usr/bin/ssh-keygen", "-F", lookup, "-f", str(Path.home() / ".ssh" / name)]
                )
                if pinned.returncode == 0:
                    keys.update(
                        tuple(parts[1:3])
                        for line in pinned.stdout.decode().splitlines()
                        if not line.startswith("#") and len(parts := line.split()) >= 3
                    )
            for name in ("ed25519", "ecdsa", "rsa"):
                path = Path(f"/etc/ssh/ssh_host_{name}_key.pub")
                if path.is_file() and not path.is_symlink():
                    parts = path.read_text().split()
                    if tuple(parts[:2]) in keys:
                        return True
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
            return False
        return False

    def _remote(
        self, command: str, *, stdin: bytes | None = None, timeout: int = _CONTROL_TIMEOUT
    ) -> subprocess.CompletedProcess[bytes]:
        return self._process(
            [
                SSH,
                "-oBatchMode=yes",
                "-oStrictHostKeyChecking=yes",
                "-oConnectTimeout=10",
                DESTINATION,
                command,
            ],
            stdin=stdin,
            timeout=timeout,
        )

    def _invoke(
        self,
        local: bool,
        args: list[str],
        *,
        envelope: dict[str, Any] | None = None,
        timeout: int = _CONTROL_TIMEOUT,
    ) -> subprocess.CompletedProcess[bytes]:
        # All arguments are selected below, never taken from a request.
        data = canonical_bytes(envelope) if envelope is not None else None
        if local:
            return self._process(
                [str(Path.home() / ".local/bin/yggdrasil-model-inquiry"), *args],
                stdin=data,
                timeout=timeout,
            )
        return self._remote(LAUNCHER + " " + " ".join(args), stdin=data, timeout=timeout)

    def _control(
        self, local: bool, verb: str, envelope: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if verb not in OPERATION_VERBS or verb == "--approved-operation-stdin":
            raise WorkflowUnavailable("unsupported workflow control verb")
        result = self._invoke(local, [verb], envelope=envelope)
        if result.returncode:
            raise WorkflowUnavailable("destination control refused or unavailable")
        return decode_object(result.stdout)

    def _capabilities(self, local: bool) -> dict[str, Any]:
        value = self._control(local, "--operation-capabilities")
        if (
            set(value) != {"schema", "version", "verbs", "bindings", "stop_support"}
            or value["schema"] != "builderops.model-inquiry-operation-capabilities.v1"
            or value["version"] != OPERATION_VERSION
            or value["verbs"] != OPERATION_VERBS
            or value["stop_support"] != "unsupported"
        ):
            raise WorkflowUnavailable("operation protocol is unsupported")
        bindings = value["bindings"]
        if (
            not isinstance(bindings, dict)
            or set(bindings) != {"workflow", "destination", "policy", "configuration", "capability"}
            or bindings["workflow"] != workflow_binding()
            or bindings["destination"] != {"identity": DESTINATION, "revision": OPERATION_VERSION}
        ):
            raise WorkflowUnavailable("operation workflow binding is unavailable")
        return bindings

    def current_bindings(self) -> dict[str, Any]:
        try:
            return self._capabilities(self._route())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise WorkflowUnavailable("sanctioned workflow unavailable") from exc

    @staticmethod
    def _envelope(
        approval: dict[str, Any], readback: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "approval": approval,
            "reservation_receipt_hash": readback.get("reservation_receipt_hash")
            if readback
            else None,
            "launch_attempt_receipt_hash": readback.get("launch_attempt_receipt_hash")
            if readback
            else None,
        }

    @staticmethod
    def _bound_readback(value: Any, approval: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("state"), str):
            raise WorkflowUnavailable("exact destination readback is unavailable")
        proposal = approval["proposal"]
        expected = {
            "approval_id": approval["approval_id"],
            "approval_manifest_hash": approval["approval_manifest_hash"],
            "repository": proposal["repository"],
            "subject_ref": proposal["subject_ref"],
            "operation_type": "start_model_inquiry",
            "operation_key": proposal["operation_key"],
            "destination": proposal["destination"],
            "admission_receipt_ref": approval["approval_receipt_ref"],
            "inquiry_id": approval["inquiry_id"],
            "stop_support": "unsupported",
            "stop_status": "unsupported",
        }
        if (
            any(value.get(key) != item for key, item in expected.items())
            or value.get("state") not in {"reserved", "ambiguous", "terminal"}
            or not value.get("reservation_receipt_hash")
            or not value.get("observed_at")
            or type(value.get("source_epoch")) is not int
        ):
            raise WorkflowUnavailable("exact destination readback is unavailable")
        return value

    def readback(self, approval: dict[str, Any]) -> dict[str, Any]:
        validate_approval_identity(approval)
        try:
            local = self._route()
            self._capabilities(local)
            return self._bound_readback(
                self._control(local, "--operation-readback-stdin", self._envelope(approval)),
                approval,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return {
                "state": "unavailable",
                "reason": "authenticated_readback_unavailable",
                "inquiry_id": approval["inquiry_id"],
                "operation_key": approval["proposal"]["operation_key"],
                "stop_support": "unsupported",
                "stop_status": "unsupported",
            }

    def _lock(self, local: bool) -> None:
        if local:
            os.mkdir(LOCK, 0o700)
        elif self._remote(f"/bin/mkdir -m 700 {LOCK}").returncode:
            raise WorkflowUnavailable("workflow lock unavailable")

    def _stage(self, local: bool, question: bytes) -> None:
        if local:
            fd = os.open(STAGE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(question)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise StagingFailure(owned=True) from exc
        else:
            try:
                result = self._remote(
                    f"umask 077; set -C; test ! -e {STAGE} && test ! -L {STAGE} || exit 17; /bin/cat > {STAGE}",
                    stdin=question,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise StagingFailure(owned=False) from exc
            if result.returncode == 17:
                raise WorkflowUnavailable("workflow staged path already exists")
            if result.returncode:
                # Partial writes and lost acknowledgements cannot prove remote
                # creation/ownership. Keep both paths for reconciliation.
                raise StagingFailure(owned=False)

    def _cleanup(self, local: bool, *, stage_owned: bool) -> bool:
        """Only the fixed owned stage and empty lock, never a general path helper."""
        try:
            if local:
                path = Path(STAGE)
                if stage_owned and (path.exists() or path.is_symlink()):
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                        return False
                    path.unlink()
                lock = Path(LOCK)
                if lock.is_symlink() or lock.stat().st_uid != os.getuid():
                    return False
                lock.rmdir()
                return True
            # Fail before deletion on symlink/ownership mismatch; never remove a
            # nonempty lock or release it after a failed staged-file deletion.
            stage_check = (
                f"test ! -L {STAGE} && {{ test ! -e {STAGE} || {{ test -f {STAGE} && test -O {STAGE} && /bin/rm {STAGE}; }}; }} && "
                if stage_owned
                else ""
            )
            command = f"test ! -L {LOCK} && test -O {LOCK} && {stage_check}/bin/rmdir {LOCK}"
            return self._remote(command).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _launch(
        self,
        local: bool,
        question: str,
        approval: dict[str, Any] | None,
        readback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        locked, staged, attempted, terminal = False, False, False, False
        staging_unknown = False
        temporary: Path | None = None
        identity: tuple[int, int] | None = None
        result: dict[str, Any] = {"state": "unavailable", "reason": "workflow_preflight_failed"}
        try:
            self._lock(local)
            locked = True
            fd, name = tempfile.mkstemp(prefix="model-inquiry-question-", suffix=".md")
            temporary = Path(name)
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            with os.fdopen(fd, "wb") as stream:
                stream.write(question.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            self._stage(local, temporary.read_bytes())
            staged = True
            args = ["--question-file", STAGE]
            envelope = None
            if approval is not None:
                # The RPC may persist an attempt and lose its response. Mark the
                # protected ambiguity boundary before issuing that RPC.
                attempted = True
                assert readback is not None
                attempt = self._control(
                    local, "--operation-attempt-stdin", self._envelope(approval, readback)
                )
                readback = self._bound_readback(attempt["readback"], approval)
                if attempt.get("created") is not True:
                    raise WorkflowUnavailable("operation attempt already exists")
                envelope = self._envelope(approval, readback)
                args.append("--approved-operation-stdin")
            attempted = True
            captured = self._invoke(local, args, envelope=envelope, timeout=_LAUNCH_TIMEOUT)
            value = decode_object(captured.stdout)
            launcher_valid = captured.returncode == 0 and all(
                isinstance(value.get(key), str) and value[key].strip() for key in _TERMINAL_FIELDS
            )
            if not launcher_valid:
                raise WorkflowUnavailable("launcher outcome ambiguous")
            if approval is not None:
                result = self._bound_readback(
                    self._control(
                        local, "--operation-readback-stdin", self._envelope(approval, readback)
                    ),
                    approval,
                )
                if not (
                    value.get("inquiry_id") == approval["inquiry_id"]
                    and result["state"] == "terminal"
                    and result.get("terminal_receipt")
                    == {key: value[key] for key in _TERMINAL_FIELDS}
                ):
                    raise WorkflowUnavailable("terminal readback does not match launcher")
            else:
                result = {"state": "terminal", "terminal_receipt": value}
            # Cleanup eligibility is committed only after every required terminal
            # check succeeds. Even an unexpected exception before here preserves
            # the fixed stage and lock without depending on an exception list.
            terminal = True
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            terminal = False
            if isinstance(exc, StagingFailure):
                staged = exc.owned
                staging_unknown = not exc.owned
            result = {
                "state": "ambiguous" if attempted else "unavailable",
                "reason": "launcher_outcome_ambiguous"
                if attempted
                else "workflow_preflight_failed",
            }
            if approval is not None:
                result.update(
                    inquiry_id=approval["inquiry_id"],
                    operation_key=approval["proposal"]["operation_key"],
                    stop_support="unsupported",
                    stop_status="unsupported",
                )
        finally:
            if temporary is not None:
                try:
                    info = temporary.lstat()
                    if (
                        identity == (info.st_dev, info.st_ino)
                        and info.st_uid == os.getuid()
                        and stat.S_ISREG(info.st_mode)
                    ):
                        temporary.unlink()
                    else:
                        result["caller_cleanup"] = "refused"
                except OSError:
                    result["caller_cleanup"] = "failed"
            if locked and not staging_unknown and (not attempted or terminal):
                result["workflow_cleanup"] = (
                    "complete" if self._cleanup(local, stage_owned=staged) else "failed"
                )
            elif locked:
                result["workflow_cleanup"] = "preserved_for_reconciliation"
        return result

    def start(self, approval: dict[str, Any]) -> dict[str, Any]:
        validate_approval_identity(approval)
        try:
            local = self._route()
            bindings = self._capabilities(local)
            if any(approval["material"][name] != value for name, value in bindings.items()):
                raise WorkflowUnavailable("preview workflow changed")
            reservation = self._control(
                local, "--operation-reserve-stdin", self._envelope(approval)
            )
            readback = self._bound_readback(reservation["readback"], approval)
            if reservation.get("created") is not True:
                return readback
            return self._launch(
                local, approval["proposal"]["exact_inputs"][0]["text"], approval, readback
            )
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            # Reservation may have committed: no automatic continuation or key.
            return {
                "state": "workflow_unavailable",
                "reason": "capability_or_reservation_unavailable",
                "inquiry_id": approval["inquiry_id"],
                "operation_key": approval["proposal"]["operation_key"],
                "stop_support": "unsupported",
                "stop_status": "unsupported",
            }

    def manual(self, question_file: Path) -> dict[str, Any]:
        """Use current manual authorization, with no operation approval authority."""
        try:
            descriptor = os.open(question_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise WorkflowUnavailable("exact regular question file required")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    raw = stream.read(16385)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise WorkflowUnavailable("exact question file unavailable") from exc
        if not raw or len(raw) > 16384 or not raw.decode("utf-8").strip():
            raise WorkflowUnavailable("bounded UTF-8 question required")
        return self._launch(self._route(), raw.decode("utf-8"), None, None)
