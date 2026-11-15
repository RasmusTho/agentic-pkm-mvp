#!/usr/bin/env python3
"""Manage one local, official OpenHands Agent Canvas static server."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
import secrets
import select
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


def verify_backend_key(backend: str, key: str) -> None:
    endpoint = urlsplit(endpoint_url(backend))

    def check(headers: dict[str, str]) -> int:
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=5)
        try:
            connection.request("GET", "/api/conversations/search", headers=headers)
            return connection.getresponse().status
        except (OSError, http.client.HTTPException, ValueError, UnicodeError):
            raise CanvasError("could not verify session authentication with backend") from None
        finally:
            try:
                connection.close()
            except OSError:
                pass

    if check({"X-Session-API-Key": key}) != 200:
        raise CanvasError("backend rejected session key or verification request")
    # A 200 with the key is insufficient if the backend does not enforce auth.
    if check({}) not in (401, 403):
        raise CanvasError("backend session authentication could not be confirmed")


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
                or state.get("phase") not in (None, "starting")
                or not all(isinstance(state.get(k), str) and state[k] for k in
                           ("marker", "server", "url", "backend"))
                or not state["marker"].startswith("/__owner_canvas_")
                or len(state["marker"]) != len("/__owner_canvas_") + 32
                or any(c not in "0123456789abcdef" for c in state["marker"][-32:])):
            raise ValueError
        if state.get("phase") != "starting":
            if type(state.get("pid")) is not int or state["pid"] <= 1:
                raise ValueError
            if state.get("supervised") is True:
                if state.get("control") != "control-" + state["marker"][-32:]:
                    raise ValueError
            elif not isinstance(state.get("started"), str) or not state["started"]:
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


def _fifo_open(path: Path, flags: int) -> int:
    fd = os.open(path, flags | os.O_NONBLOCK | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise CanvasError("invalid private supervisor channel")
    return fd


def supervisor_request(state_path: Path, state: dict, action: str) -> str:
    if state.get("supervised") is not True:
        raise CanvasError("legacy Canvas is not supervised; owner reconciliation required")
    reply = state_path.parent / ("reply-" + secrets.token_hex(16))
    reply_fd = None
    created = False
    try:
        os.mkfifo(reply, 0o600)
        created = True
        reply_fd = _fifo_open(reply, os.O_RDWR)
        control_fd = _fifo_open(state_path.parent / state["control"], os.O_WRONLY)
        try:
            message = f"{action} {state['pid']} {state['marker']} {reply.name}\n".encode()
            os.write(control_fd, message)
        finally:
            os.close(control_fd)
        if not select.select([reply_fd], [], [], 7)[0]:
            raise CanvasError("supervisor did not respond; state retained")
        response = os.read(reply_fd, 1024).decode("ascii").strip()
        if response not in ("running", "stopped"):
            raise CanvasError("supervisor refused request; state retained")
        return response
    except (OSError, UnicodeError) as exc:
        raise CanvasError("supervisor unavailable; state retained") from exc
    finally:
        if reply_fd is not None:
            os.close(reply_fd)
        if created:
            reply.unlink(missing_ok=True)


def supervise(control: Path, marker: str, command: list[str]) -> int:
    # Only this process can reap or signal its own Canvas child.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    child = None
    control_fd = None
    try:
        control_fd = _fifo_open(control, os.O_RDWR)
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env=os.environ.copy())
        print(json.dumps({"pid": child.pid}), flush=True)
        sys.stdout.close()
        pending = b""
        while True:
            if not select.select([control_fd], [], [], 1)[0]:
                continue
            pending += os.read(control_fd, 4096)
            if len(pending) > 4096:
                pending = b""
                continue
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                parts = line.decode("ascii", errors="replace").split()
                if len(parts) != 4:
                    continue
                action, pid, requested_marker, reply_name = parts
                if (not reply_name.startswith("reply-") or len(reply_name) != 38
                        or any(c not in "0123456789abcdef" for c in reply_name[6:])):
                    continue
                if pid != str(child.pid) or requested_marker != marker or action not in ("status", "stop"):
                    result = "refused"
                else:
                    result = "running" if child.poll() is None else "stopped"
                if action == "stop" and result == "running":
                    # A live child cannot have its PID reused before this parent reaps it.
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                        result = "stopped"
                    except subprocess.TimeoutExpired:
                        result = "running"
                try:
                    fd = _fifo_open(control.parent / reply_name, os.O_WRONLY)
                    try:
                        os.write(fd, (result + "\n").encode("ascii"))
                    finally:
                        os.close(fd)
                except (CanvasError, OSError):
                    pass
                if action == "stop" and result == "stopped":
                    return 0
    except (OSError, CanvasError):
        if child is None:
            try:
                print('{"error":"supervisor could not start Canvas"}', flush=True)
            except (OSError, ValueError):
                pass
        return 1
    finally:
        if control_fd is not None:
            os.close(control_fd)


def wait_ready(process: subprocess.Popen, port: int, marker: str) -> None:
    # Give a failed bind time to surface before probing the port.
    time.sleep(0.2)
    marker_body = b"Service Unavailable (no backend configured for this route)"
    for _ in range(50):
        if process.poll() is not None:
            raise CanvasError("Canvas server exited before becoming ready")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            if response.status == 200:
                connection.close()
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                connection.request("GET", marker)
                response = connection.getresponse()
                if (response.status == 503 and response.read(len(marker_body) + 1) == marker_body
                        and process.poll() is None):
                    return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise CanvasError("Canvas server did not become ready")


def ensure_port_free(port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            probe.listen(1)
    except OSError as exc:
        raise CanvasError("Canvas loopback port is unavailable") from exc


def start(args, state_path: Path) -> str:
    backend = endpoint_url(args.backend)
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
        if current.get("phase") == "starting":
            raise CanvasError("startup outcome unknown; owner reconciliation required before start")
        status = supervisor_request(state_path, current, "status")
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
            verify_backend_key(backend, key)
            return url
        if supervisor_request(state_path, current, "stop") != "stopped":
            raise CanvasError("Canvas did not stop; state retained")
        (state_path.parent / current["control"]).unlink(missing_ok=True)
        state_path.unlink()
    key = private_file(Path(args.key_file))
    verify_backend_key(backend, key)
    node = shutil.which("node")
    if node is None:
        raise CanvasError("node is required to start Canvas")
    ensure_port_free(args.port)
    marker = "/__owner_canvas_" + secrets.token_hex(16)
    control = state_path.parent / ("control-" + marker[-32:])
    command = [node, str(server), "--host", "127.0.0.1", "--port", str(args.port),
               "--dir", str(build), "--reject-prefix", marker, "--auth-required"]
    for route in ("/api", "/sockets", "/server_info", "/alive", "/health", "/ready", "/docs", "/redoc", "/openapi.json"):
        command.extend(("--route", f"{route}={backend}"))
    env = {"PATH": os.defpath, "SESSION_API_KEY": key, "AGENT_CANVAS_DISABLE_TELEMETRY": "1"}
    intent = {"version": 1, "phase": "starting", "marker": marker,
              "server": str(server), "url": url, "backend": backend, "control": control.name,
              "key_fingerprint": hashlib.sha256(key.encode("utf-8")).hexdigest()}
    write_state(state_path, intent)
    control_created = False
    try:
        os.mkfifo(control, 0o600)
        control_created = True
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_supervise",
                                    str(control), marker, *command], cwd=package, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        if control_created:
            control.unlink(missing_ok=True)
        state_path.unlink()
        raise CanvasError("could not start Canvas supervisor") from exc
    state = None
    try:
        assert process.stdout is not None
        if not select.select([process.stdout], [], [], 10)[0]:
            raise CanvasError("supervisor startup unknown; owner reconciliation required")
        try:
            response = json.loads(process.stdout.readline(1024))
        except (ValueError, UnicodeError) as exc:
            raise CanvasError("supervisor startup unknown; owner reconciliation required") from exc
        if not isinstance(response, dict):
            raise CanvasError("supervisor startup unknown; owner reconciliation required")
        if "error" in response:
            control.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            raise CanvasError("supervisor could not start Canvas")
        pid = response.get("pid")
        if type(pid) is not int or pid <= 1:
            raise CanvasError("supervisor startup unknown; owner reconciliation required")
        state = {"version": 1, "pid": pid, "supervised": True, "control": control.name, "marker": marker,
                 "server": str(server), "url": url, "backend": backend,
                 "key_fingerprint": hashlib.sha256(key.encode("utf-8")).hexdigest()}
        write_state(state_path, state)
        wait_ready(process, args.port, marker)
        if supervisor_request(state_path, state, "status") != "running":
            raise CanvasError("Canvas server exited before becoming ready")
    except Exception:
        if state is not None:
            try:
                if supervisor_request(state_path, state, "stop") == "stopped":
                    control.unlink(missing_ok=True)
                    state_path.unlink(missing_ok=True)
            except CanvasError:
                pass  # Preserve state when the child cannot be reconciled.
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage a local OpenHands Agent Canvas static server.")
    sub = parser.add_subparsers(dest="action", required=True)
    launch = sub.add_parser("start", help="start Canvas against an already-running loopback backend")
    launch.add_argument("--package-dir", required=True, help="installed @openhands/agent-canvas package directory")
    launch.add_argument("--backend", required=True, help="backend URL, e.g. http://127.0.0.1:8000")
    launch.add_argument("--key-file", required=True, help="private session-key file; enter the same key in Canvas")
    launch.add_argument("--state-dir", required=True, help="private local state directory")
    launch.add_argument("--port", type=int, default=3001, help="Canvas loopback port (default: 3001)")
    launch.add_argument("--open", action="store_true", help="open the Canvas URL in a browser")
    for name in ("status", "stop"):
        command = sub.add_parser(name, help=f"{name} the recorded Canvas server")
        command.add_argument("--state-dir", required=True, help="private local state directory")
    args = parser.parse_args(argv)
    try:
        with locked_state(Path(os.path.abspath(args.state_dir))) as state_path:
            if args.action == "start":
                url = start(args, state_path)
                print(url)
                if args.open:
                    webbrowser.open(url)
            else:
                state = read_state(state_path)
                if state and state.get("phase") == "starting":
                    raise CanvasError("startup outcome unknown; owner reconciliation required")
                status = supervisor_request(state_path, state, "status") if state else "stopped"
                if args.action == "stop" and state:
                    if supervisor_request(state_path, state, "stop") != "stopped":
                        raise CanvasError("Canvas did not stop; state retained")
                    (state_path.parent / state["control"]).unlink(missing_ok=True)
                    state_path.unlink()
                    status = "stopped"
                print(f"{status}" + (f" {state['url']}" if state and status == "running" else ""))
        return 0
    except (CanvasError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Canvas: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) >= 6 and sys.argv[1] == "_supervise":
        raise SystemExit(supervise(Path(sys.argv[2]), sys.argv[3], sys.argv[4:]))
    raise SystemExit(main())
