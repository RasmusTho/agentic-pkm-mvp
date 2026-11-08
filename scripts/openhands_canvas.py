#!/usr/bin/env python3
"""Manage one local, official OpenHands Agent Canvas static server."""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class CanvasError(Exception):
    pass


def endpoint_url(value: str) -> str:
    try:
        url = urlsplit(value)
        host = ipaddress.ip_address(url.hostname or "")
        port = url.port
        if (url.scheme != "http" or not host.is_loopback or port is None or port == 0
                or url.username is not None or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError
    except ValueError as exc:
        raise CanvasError("backend must be an http URL with a numeric loopback address and port") from exc
    address = f"[{host}]" if host.version == 6 else str(host)
    return f"http://{address}:{port}"


def private_file(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CanvasError("session key file must be a private owner-readable regular file")
            key = stream.read(4097).strip()
    except (OSError, UnicodeError) as exc:
        raise CanvasError("cannot read private session key file") from exc
    if not key or len(key) > 4096 or "\x00" in key or "\n" in key or "\r" in key:
        raise CanvasError("session key file must contain one nonempty key")
    return key


@contextmanager
def locked_state(path: Path):
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CanvasError("state directory must be private and owned by the current user")
        fd = os.open(path / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            lock_info = os.fstat(lock.fileno())
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid()
                    or lock_info.st_mode & 0o077):
                raise CanvasError("invalid state lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield path / "server.json"
    except OSError as exc:
        raise CanvasError("cannot access private state directory") from exc


def read_state(path: Path) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CanvasError("cannot read server state") from exc
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CanvasError("server state is not private")
            state = json.load(stream)
        if (not isinstance(state, dict) or state.get("version") != 1
                or type(state.get("pid")) is not int or state["pid"] <= 1
                or not all(isinstance(state.get(k), str) and state[k] for k in
                           ("started", "marker", "server", "url", "backend"))
                or not state["marker"].startswith("/__owner_canvas_")
                or len(state["marker"]) != len("/__owner_canvas_") + 32
                or any(c not in "0123456789abcdef" for c in state["marker"][-32:])):
            raise ValueError
        return state
    except (ValueError, TypeError, UnicodeError, OSError) as exc:
        raise CanvasError("invalid server state; refusing to act") from exc


def write_state(path: Path, state: dict) -> None:
    temporary = path.with_name(f".server-{secrets.token_hex(16)}")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def process_info(pid: int) -> tuple[str, str, str] | None:
    # Never print the command: it could belong to an unrelated reused PID.
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "stat=", "-o", "command="],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except OSError as exc:
            raise CanvasError("cannot inspect recorded process") from exc
        raise CanvasError("cannot inspect recorded process")
    parts = result.stdout.strip().split(None, 6)
    if len(parts) != 7:
        raise CanvasError("cannot identify recorded process")
    return " ".join(parts[:5]), parts[5], parts[6]


def process_status(state: dict) -> str:
    info = process_info(state["pid"])
    if info is None or info[1].startswith("Z"):
        return "stopped"
    started, _, command = info
    server_arg = f" {state['server']} --host 127.0.0.1 "
    marker_arg = f" --reject-prefix {state['marker']} "
    if started != state["started"] or server_arg not in command or marker_arg not in command:
        return "mismatch"
    return "running"


def stop_owned(state: dict) -> None:
    pid = state["pid"]
    pidfd = None
    try:
        if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            try:
                pidfd = os.pidfd_open(pid)
            except OSError as exc:
                if exc.errno != errno.ENOSYS:
                    raise
        elif sys.platform not in ("darwin", "linux"):
            raise CanvasError("process signalling is unavailable on this platform; state retained")
        status = process_status(state)
        if status == "stopped":
            raise CanvasError("recorded Canvas process is no longer available; state retained")
        if status != "running":
            raise CanvasError("recorded PID belongs to another process; refusing to stop it")
        if pidfd is not None:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        else:
            # macOS has no pidfd; inspect identity immediately before signalling.
            os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            status = process_status(state)
            if status == "mismatch":
                raise CanvasError("recorded PID changed during stop; state retained")
            if status == "stopped":
                return
            time.sleep(0.1)
        raise CanvasError("Canvas did not stop; state retained")
    except ProcessLookupError:
        raise CanvasError("recorded Canvas process is no longer available; state retained") from None
    except OSError as exc:
        raise CanvasError("could not stop recorded Canvas process") from exc
    finally:
        if pidfd is not None:
            os.close(pidfd)


def wait_ready(process: subprocess.Popen, port: int) -> None:
    # Give a failed bind time to surface before probing the port.
    time.sleep(0.2)
    for _ in range(50):
        if process.poll() is not None:
            raise CanvasError("Canvas server exited before becoming ready")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            if response.status == 200:
                return
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise CanvasError("Canvas server did not become ready")


def ensure_port_free(port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise CanvasError("Canvas loopback port is unavailable") from exc


def start(args, state_path: Path) -> str:
    backend = endpoint_url(args.backend)
    if sys.platform not in ("darwin", "linux") and not (
        hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")
    ):
        raise CanvasError("process signalling is unavailable on this platform")
    if not 1 <= args.port <= 65535:
        raise CanvasError("port must be between 1 and 65535")
    url = f"http://127.0.0.1:{args.port}"
    if backend == url:
        raise CanvasError("Canvas and backend must use different ports")
    package = Path(args.package_dir).resolve()
    server = package / "scripts" / "static-server.mjs"
    build = package / "build"
    if not server.is_file() or not (build / "index.html").is_file():
        raise CanvasError("Canvas package must contain scripts/static-server.mjs and build/index.html")
    current = read_state(state_path)
    if current:
        status = process_status(current)
        if status == "mismatch":
            raise CanvasError("recorded PID belongs to another process; refusing to start")
        if status == "running":
            if (current["url"], current["backend"], current["server"]) != (url, backend, str(server)):
                raise CanvasError("Canvas already running with different configuration")
            fingerprint = current.get("key_fingerprint")
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(c not in "0123456789abcdef" for c in fingerprint)):
                raise CanvasError("cannot verify the running session key; stop and start Canvas")
            key = private_file(Path(args.key_file))
            if not secrets.compare_digest(fingerprint, hashlib.sha256(key.encode("utf-8")).hexdigest()):
                raise CanvasError("session key changed; stop and start Canvas to apply it")
            return url
        state_path.unlink()
    key = private_file(Path(args.key_file))
    node = shutil.which("node")
    if node is None:
        raise CanvasError("node is required to start Canvas")
    ensure_port_free(args.port)
    marker = "/__owner_canvas_" + secrets.token_hex(16)
    command = [node, str(server), "--host", "127.0.0.1", "--port", str(args.port),
               "--dir", str(build), "--reject-prefix", marker]
    for route in ("/api", "/sockets", "/server_info", "/alive", "/health", "/ready", "/docs", "/redoc", "/openapi.json"):
        command.extend(("--route", f"{route}={backend}"))
    env = {"PATH": os.defpath, "SESSION_API_KEY": key, "AGENT_CANVAS_DISABLE_TELEMETRY": "1"}
    try:
        process = subprocess.Popen(command, cwd=package, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise CanvasError("could not start Canvas server") from exc
    try:
        info = process_info(process.pid)
        if info is None or marker not in info[2] or str(server) not in info[2]:
            raise CanvasError("could not identify started Canvas process")
        state = {"version": 1, "pid": process.pid, "started": info[0], "marker": marker,
                 "server": str(server), "url": url, "backend": backend,
                 "key_fingerprint": hashlib.sha256(key.encode("utf-8")).hexdigest()}
        write_state(state_path, state)
        wait_ready(process, args.port)
    except Exception:
        # This is still our unreaped child, so its PID cannot have been reused.
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        state_path.unlink(missing_ok=True)
        raise
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage a local OpenHands Agent Canvas static server.")
    sub = parser.add_subparsers(dest="action", required=True)
    launch = sub.add_parser("start", help="start Canvas against an already-running loopback backend")
    launch.add_argument("--package-dir", required=True, help="installed @openhands/agent-canvas package directory")
    launch.add_argument("--backend", required=True, help="backend URL, e.g. http://127.0.0.1:8000")
    launch.add_argument("--key-file", required=True, help="private session-key file")
    launch.add_argument("--state-dir", required=True, help="private local state directory")
    launch.add_argument("--port", type=int, default=3001, help="Canvas loopback port (default: 3001)")
    launch.add_argument("--open", action="store_true", help="open the Canvas URL in a browser")
    for name in ("status", "stop"):
        command = sub.add_parser(name, help=f"{name} the recorded Canvas server")
        command.add_argument("--state-dir", required=True, help="private local state directory")
    args = parser.parse_args(argv)
    try:
        with locked_state(Path(args.state_dir)) as state_path:
            if args.action == "start":
                url = start(args, state_path)
                print(url)
                if args.open:
                    webbrowser.open(url)
            else:
                state = read_state(state_path)
                status = process_status(state) if state else "stopped"
                if status == "mismatch":
                    raise CanvasError("recorded PID belongs to another process; state retained")
                if args.action == "stop" and state:
                    if status == "stopped":
                        raise CanvasError("recorded Canvas process is no longer running; state retained")
                    stop_owned(state)
                    state_path.unlink()
                    status = "stopped"
                print(f"{status}" + (f" {state['url']}" if state and status == "running" else ""))
        return 0
    except (CanvasError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Canvas: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
