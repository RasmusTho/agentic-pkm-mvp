"""Local OpenHands agent-server lifecycle; this is not a factory admission boundary.

Run ``python -m app.builderops.openhands_service --help`` for owner commands.
Running means the recorded process exists, not that its HTTP service is ready.

The settings JSON contains only non-secret values with these required keys:
``guard_executable``, ``codex_binary``, ``codex_config_args`` (string array),
``sandbox_read_roots`` (directory array), ``conversations_path``,
``bash_events_dir``, and ``conversation_worktree_root``. Paths must be absolute;
executables and read roots must already exist. Storage paths may be new.
The caller is responsible for supplying approved, secret-free Codex arguments.
For a recovery launch, ``resume_thread_id`` may name the previously recorded
Codex thread UUID for this workspace. The proxy verifies the resumed thread
before permitting its next turn.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


class ServiceError(RuntimeError):
    """A lifecycle operation could not safely proceed."""


@contextlib.contextmanager
def _locked(directory: Path) -> Iterator[None]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ServiceError("State directory must be private and owned by the current user")
    with (directory / "service.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read(directory: Path) -> dict[str, Any] | None:
    path = directory / "service.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ServiceError(f"Cannot read lifecycle state: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ServiceError("Invalid lifecycle state; preserve it for inspection")
    return data


def _write(directory: Path, data: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".service-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / "service.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _identity(pid: int) -> tuple[str, str] | None:
    """Return process start time and command, excluding dead/zombie processes."""
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "stat=", "-o", "lstart=", "-o", "command="],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 1 and not result.stdout.strip():
        return None
    if result.returncode != 0:
        raise ServiceError("Cannot inspect recorded process")
    fields = result.stdout.strip().split(maxsplit=6)
    if len(fields) != 7:
        raise ServiceError("Cannot establish process identity")
    if fields[0].startswith("Z"):
        return None
    return " ".join(fields[1:6]), fields[6]


def _status(data: dict[str, Any] | None) -> str:
    if data is None or data.get("state") == "stopped":
        return "stopped"
    pid, marker, started = data.get("pid"), data.get("marker"), data.get("started")
    if (
        type(pid) is not int or pid <= 1 or not isinstance(marker, str) or not marker
        or not isinstance(started, str) or not started
    ):
        return "stale"
    identity = _identity(pid)
    if identity is None or identity[0] != started or marker not in identity[1]:
        return "stale"
    return "running"


def status(directory: Path) -> dict[str, Any]:
    with _locked(directory):
        data = _read(directory)
        return {"status": _status(data), "state": data}


_SETTINGS = {
    "guard_executable", "codex_binary", "codex_config_args", "sandbox_read_roots",
    "conversations_path", "bash_events_dir", "conversation_worktree_root",
}


def _settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ServiceError("Cannot read settings JSON") from exc
    if not isinstance(data, dict) or not _SETTINGS <= set(data) or set(data) - _SETTINGS - {"resume_thread_id"}:
        raise ServiceError("Settings must contain the documented non-secret fields")
    if "resume_thread_id" in data:
        try:
            thread_id = data["resume_thread_id"]
            if not isinstance(thread_id, str) or str(uuid.UUID(thread_id)) != thread_id:
                raise ValueError("invalid thread id")
        except ValueError as exc:
            raise ServiceError("resume_thread_id must be a canonical UUID") from exc
    for key in _SETTINGS - {"codex_config_args", "sandbox_read_roots"}:
        value = data[key]
        if (
            not isinstance(value, str) or not value or "\0" in value
            or not Path(value).is_absolute()
        ):
            raise ServiceError(f"Settings field {key} must be an absolute path")
    for key in ("guard_executable", "codex_binary"):
        candidate = Path(data[key])
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise ServiceError(f"Settings field {key} must be an executable file")
    args = data["codex_config_args"]
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\0" in arg for arg in args):
        raise ServiceError("codex_config_args must be a string array")
    roots = data["sandbox_read_roots"]
    if not isinstance(roots, list) or any(
        not isinstance(root, str) or not root or "\0" in root
        or not Path(root).is_absolute() or not Path(root).is_dir()
        for root in roots
    ):
        raise ServiceError("sandbox_read_roots must be an array of existing absolute directories")
    return data


def _session_key(directory: Path) -> str:
    """Create once, or reuse only an owner-private, regular key file."""
    path = directory / "session-api-key"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    try:
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
        )
        with os.fdopen(fd, "r") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ServiceError("Session key file must be private and owned by the current user")
            value = stream.read(128).strip()
    except OSError as exc:
        raise ServiceError("Cannot safely read session key file") from exc
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if len(value) != 43 or any(c not in alphabet for c in value):
        raise ServiceError("Invalid session key file; preserve it for inspection")
    return value


def start(
    directory: Path, python: Path, workspace: Path, port: int, settings_file: Path,
    *, control_only: bool = False,
) -> dict[str, Any]:
    python = python.absolute()
    workspace = workspace.resolve(strict=True)
    directory = directory.resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ServiceError("Python must be an executable file")
    if not workspace.is_dir() or not 1 <= port <= 65535:
        raise ServiceError("Workspace must be a directory and port must be 1–65535")
    settings = _settings(settings_file)
    with _locked(directory):
        old_status = _status(_read(directory))
        if old_status != "stopped":
            raise ServiceError(f"Cannot start: lifecycle state is {old_status}; inspect it first")
        session_key = _session_key(directory)
        marker = "openhands_service_" + secrets.token_hex(16)
        data: dict[str, Any] = {
            "version": 1, "state": "starting", "marker": marker,
            "python": str(python), "workspace": str(workspace), "port": port,
            "settings_file": str(settings_file.absolute()), "control_only": control_only,
        }
        # A crash during launch remains ambiguous and blocks automatic replay.
        _write(directory, data)
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
                        "DISPATCHER_STATE_DIR", "DISPATCHER_DB_PATH", "DISPATCHER_EVENTS_PATH")
            if key in os.environ
        }
        env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "CODEX_PATH": settings["guard_executable"],
            "OPENHANDS_FACTORY_PYTHON": str(python),
            # The execution boundary comes from the installed factory, not
            # from an issue worktree whose contents the worker can change.
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "OPENHANDS_FACTORY_WORKSPACE": str(workspace),
            "OPENHANDS_CODEX_BINARY": settings["codex_binary"],
            "OPENHANDS_CODEX_CONFIG_ARGS": json.dumps(settings["codex_config_args"]),
            "OPENHANDS_FACTORY_READ_ROOTS": json.dumps(settings["sandbox_read_roots"]),
            "OH_WORKSPACE_PATH": str(workspace),
            "OH_PERSISTENCE_DIR": str(directory / "openhands"),
            "OH_CONVERSATIONS_PATH": settings["conversations_path"],
            "OH_BASH_EVENTS_DIR": settings["bash_events_dir"],
            "OH_CONVERSATION_WORKTREE_ROOT": settings["conversation_worktree_root"],
            "OH_SESSION_API_KEYS_0": session_key,
            "OH_TELEMETRY_CONSENT": "denied",
        })
        if control_only:
            env["OPENHANDS_FACTORY_CONTROL_ONLY"] = "1"
        if settings.get("resume_thread_id"):
            env["OPENHANDS_FACTORY_RESUME_THREAD"] = settings["resume_thread_id"]
        command = [
            str(python), "-c",
            f"from openhands.agent_server.__main__ import main; main() # {marker}",
            "--host", "127.0.0.1", "--port", str(port),
        ]
        try:
            log_fd = os.open(
                directory / "service.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            with os.fdopen(log_fd, "ab") as log:
                process = subprocess.Popen(
                    command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
        except OSError as exc:
            data["state"] = "stopped"
            _write(directory, data)
            raise ServiceError(f"Could not launch agent-server: {exc}") from exc
        data["pid"] = process.pid
        _write(directory, data)
        identity = _identity(process.pid)
        if identity is None or marker not in identity[1]:
            raise ServiceError(
                "Server exited or process identity is unavailable; inspect stale state and log"
            )
        data.update(state="running", started=identity[0])
        _write(directory, data)
        return {"status": "running", "state": data}


def stop(directory: Path, timeout: float = 5.0) -> dict[str, Any]:
    with _locked(directory):
        data = _read(directory)
        current = _status(data)
        if current == "stopped":
            return {"status": current, "state": data}
        if current != "running" or data is None:
            raise ServiceError("Cannot stop: lifecycle state is stale; no signal sent")
        pid = data["pid"]
        # The random command marker and start time guard against PID reuse. On Linux,
        # a pidfd also binds the eventual signal to the checked process instance.
        pidfd = None
        try:
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                pidfd = os.pidfd_open(pid)
            if _status(data) != "running":
                raise ServiceError("Process identity changed; no signal sent")
            if pidfd is not None:
                getattr(signal, "pidfd_send_signal")(pidfd, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            raise ServiceError(f"Could not signal recorded service: {exc}") from exc
        finally:
            if pidfd is not None:
                os.close(pidfd)
        deadline = time.monotonic() + timeout
        while _status(data) == "running":
            if time.monotonic() >= deadline:
                raise ServiceError("Service did not stop before timeout; state preserved")
            time.sleep(0.1)
        data["state"] = "stopped"
        _write(directory, data)
        return {"status": "stopped", "state": data}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir", type=Path, required=True, help="Private directory for state and logs"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("start", help="Launch one loopback agent-server")
    launch.add_argument(
        "--python", type=Path, required=True, help="Python with OpenHands installed"
    )
    launch.add_argument("--workspace", type=Path, required=True)
    launch.add_argument("--port", type=int, required=True)
    launch.add_argument(
        "--settings", type=Path, required=True, help="Non-secret launcher settings JSON"
    )
    commands.add_parser("status", help="Inspect recorded process (not readiness)")
    commands.add_parser("stop", help="Stop only the recorded process")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.state_dir, args.python, args.workspace, args.port, args.settings)
        elif args.command == "stop":
            result = stop(args.state_dir)
        else:
            result = status(args.state_dir)
    except (ServiceError, OSError, ValueError) as exc:
        print(f"openhands-service: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
