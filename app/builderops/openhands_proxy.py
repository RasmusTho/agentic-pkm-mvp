"""Supervise a Codex app-server without granting ACP's automatic approvals.

This is only the model/permission boundary, not a delivery orchestrator.  The
host must supply a trusted workspace and enforce the profile's OS sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO

from app.builderops.openhands_policy import (
    PolicyRefusal,
    prepare_request,
    verify_effective_config,
    verify_thread_response,
)

_AUTH_ID = "builder-factory:auth"
_CONFIG_ID = "builder-factory:config"


class GuardedProxy:
    """Filter JSON-RPC messages while keeping rejected requests recoverable."""

    def __init__(
        self, child: subprocess.Popen[bytes], workspace: Path, output: BinaryIO,
        *, allowed_read_roots: tuple[str, ...], resume_thread_id: str | None = None,
        workspace_writable: bool = True, delivery_state_dir: Path | None = None,
    ):
        if child.stdin is None or child.stdout is None:
            raise ValueError("child must have piped stdin and stdout")
        self.child = child
        self.workspace = workspace.resolve()
        self.output = output
        self.allowed_read_roots = allowed_read_roots
        self.resume_thread_id = resume_thread_id
        self.workspace_writable = workspace_writable
        self.delivery_state_dir = delivery_state_dir
        self._write_lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._condition = threading.Condition()
        self._pending: dict[Any, str] = {}
        self._threads: set[str] = set()
        self._account: dict[str, Any] | None = None
        self._config: dict[str, Any] | None = None
        self._preflight: str | None = None
        self._preflight_started = False
        self._stopped = False

    @staticmethod
    def _encode(value: dict[str, Any]) -> bytes:
        return (json.dumps(value, separators=(",", ":")) + "\n").encode()

    def _to_child(self, value: dict[str, Any]) -> None:
        assert self.child.stdin is not None
        with self._write_lock:
            self.child.stdin.write(self._encode(value))
            self.child.stdin.flush()

    def _to_client(self, value: dict[str, Any]) -> None:
        with self._output_lock:
            self.output.write(self._encode(value))
            self.output.flush()

    def _refuse(self, request_id: Any, reason: str) -> None:
        if request_id is not None:
            self._to_client({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": reason}})

    def _start_preflight(self) -> None:
        with self._condition:
            if self._preflight_started:
                return
            self._preflight_started = True
        self._to_child({"jsonrpc": "2.0", "id": _AUTH_ID, "method": "account/read", "params": {"refreshToken": False}})
        self._to_child({
            "jsonrpc": "2.0",
            "id": _CONFIG_ID,
            "method": "config/read",
            "params": {"cwd": str(self.workspace), "includeLayers": False},
        })

    def _wait_preflight(self) -> None:
        with self._condition:
            self._condition.wait_for(lambda: self._preflight is not None or self._stopped, timeout=30)
            if self._preflight != "ok" or self._stopped:
                raise PolicyRefusal(self._preflight or "preflight_unavailable")

    def receive_client(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id in {_AUTH_ID, _CONFIG_ID}:
            self._refuse(request_id, "reserved_request_id")
            return
        try:
            method = message.get("method")
            if method in {"thread/start", "thread/resume", "turn/start"}:
                self._wait_preflight()
            with self._condition:
                prepared = prepare_request(message, workspace=self.workspace, threads=self._threads,
                                           resume_thread_id=self.resume_thread_id)
                if request_id is not None:
                    self._pending[request_id] = str(method)
            if method in {"turn/start", "turn/steer"} and self.delivery_state_dir is not None:
                # Serialize forwarding with cancellation's persisted intent.
                # The status file is outside the worker's writable workspace.
                from app.builderops import openhands_service as service

                try:
                    with service._locked(self.delivery_state_dir / "execution-fence"):
                        state = service._read(self.delivery_state_dir)
                        if (not state or state.get("kind") != "openhands_delivery_run.v1"
                                or state.get("worktree") != str(self.workspace)
                                or state.get("phase") not in {"creating_conversation", "active"}):
                            raise PolicyRefusal("delivery_continuation_unverified")
                        self._to_child(prepared)
                except (service.ServiceError, OSError, ValueError) as exc:
                    raise PolicyRefusal("delivery_continuation_unverified") from exc
            else:
                self._to_child(prepared)
            if method == "initialized":
                self._start_preflight()
        except PolicyRefusal as exc:
            with self._condition:
                self._pending.pop(request_id, None)
            self._refuse(request_id, str(exc))

    def _preflight_result(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        with self._condition:
            if "error" in message:
                self._preflight = "preflight_request_failed"
            else:
                result = message.get("result") or {}
                if request_id == _AUTH_ID:
                    self._account = result.get("account") or {}
                else:
                    self._config = result.get("config") or {}
                if self._account is not None and self._config is not None:
                    try:
                        verify_effective_config(
                            self._config, self._account, allowed_read_roots=self.allowed_read_roots,
                            workspace_writable=self.workspace_writable,
                        )
                        self._preflight = "ok"
                        print("factory preflight: verified ChatGPT auth and fixed configuration", file=sys.stderr, flush=True)
                    except PolicyRefusal as exc:
                        self._preflight = str(exc)
            self._condition.notify_all()

    def receive_server(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id in {_AUTH_ID, _CONFIG_ID}:
            self._preflight_result(message)
            return
        method = message.get("method")
        if method and request_id is not None:
            # The ACP client otherwise approves requests automatically.  No
            # server-initiated request is an authority to expand permissions.
            self._to_child({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": "permission_not_granted"}})
            return
        if method == "model/rerouted":
            with self._condition:
                self._preflight = "model_rerouted"
                self._condition.notify_all()
        with self._condition:
            pending_method = self._pending.pop(request_id, None)
            if pending_method in {"thread/start", "thread/resume"} and "result" in message:
                try:
                    thread_id = verify_thread_response(message["result"], workspace=self.workspace)
                    if (pending_method == "thread/resume" and self.resume_thread_id
                            and thread_id != self.resume_thread_id):
                        raise PolicyRefusal("resumed_thread_mismatch")
                    self._threads.add(thread_id)
                    print("factory thread: verified gpt-6.1-terra / openai / builder_factory", file=sys.stderr, flush=True)
                except PolicyRefusal as exc:
                    message = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": str(exc)}}
        self._to_client(message)
        if pending_method == "initialize" and "result" in message:
            self._start_preflight()

    def run(self, source: BinaryIO) -> int:
        def client_loop() -> None:
            try:
                pending = bytearray()
                while chunk := os.read(source.fileno(), 65536):
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, remainder = pending.partition(b"\n")
                        pending = bytearray(remainder)
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            return
                        self.receive_client(value)
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                with self._condition:
                    self._stopped = True
                    self._condition.notify_all()
                if self.child.stdin is not None:
                    self.child.stdin.close()

        threading.Thread(target=client_loop, daemon=True).start()
        assert self.child.stdout is not None
        try:
            for raw in self.child.stdout:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    break
                self.receive_server(value)
        finally:
            with self._condition:
                self._stopped = True
                self._condition.notify_all()
        return self.child.wait()


def main() -> int:
    if os.environ.get("OPENHANDS_FACTORY_CONTROL_ONLY") == "1":
        print("Owner control cannot launch a worker; authorize an Issue in Builder control", file=sys.stderr)
        return 2
    if sys.argv[1:] != ["app-server"]:
        print("factory guard requires app-server", file=sys.stderr)
        return 2
    workspace = Path(os.environ["OPENHANDS_FACTORY_WORKSPACE"]).resolve(strict=True)
    binary = Path(os.environ["OPENHANDS_CODEX_BINARY"]).resolve(strict=True)
    # The factory launcher supplies and verifies this argv as part of admission;
    # this module intentionally does not accept shell command text.
    args = json.loads(os.environ["OPENHANDS_CODEX_CONFIG_ARGS"])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("invalid fixed Codex configuration arguments")
    read_roots = json.loads(os.environ["OPENHANDS_FACTORY_READ_ROOTS"])
    if not isinstance(read_roots, list) or not all(isinstance(root, str) for root in read_roots):
        raise ValueError("invalid fixed read roots")
    child = subprocess.Popen([str(binary), "app-server", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    return GuardedProxy(
        child, workspace, sys.stdout.buffer, allowed_read_roots=tuple(read_roots),
        resume_thread_id=os.environ.get("OPENHANDS_FACTORY_RESUME_THREAD") or None,
        workspace_writable=os.environ.get("OPENHANDS_FACTORY_READ_ONLY") != "1",
        delivery_state_dir=(Path(os.environ["OPENHANDS_FACTORY_DELIVERY_DIR"])
                            if os.environ.get("OPENHANDS_FACTORY_DELIVERY_DIR") else None),
    ).run(sys.stdin.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
