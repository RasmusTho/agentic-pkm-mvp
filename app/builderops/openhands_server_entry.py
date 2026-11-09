"""Fence inputs to an interrupted delivery before OpenHands persists them.

Only a delivery worker uses this entry point. The owner backend is unchanged.
This does not establish that any previous native process has stopped.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from app.builderops import openhands_service as service


class DeliveryInputFence:
    def __init__(self, app: Any, directory: str, workspace: str):
        self.app = app
        self.directory = Path(directory)
        self.workspace = workspace

    async def _acquire(self) -> int:
        directory = self.directory / "input-fence"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise service.ServiceError("Invalid input fence directory")
        fd = os.open(directory / "service.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise service.ServiceError("Input fence is busy")
                    await asyncio.sleep(0.05)
            state = service._read(self.directory)
            if (not state or state.get("kind") != "openhands_delivery_run.v1"
                    or state.get("worktree") != self.workspace
                    or state.get("phase") not in {"creating_conversation", "active"}):
                raise service.ServiceError("Delivery continuation is not verified")
            return fd
        except BaseException:
            os.close(fd)
            raise

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            if method == "GET" and path == "/api/_builder_identity":
                query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore"))
                nonce = query.get("nonce", [])
                key = os.environ.get("OH_SESSION_API_KEYS_0", "")
                if len(nonce) == 1 and re.fullmatch(r"[0-9a-f]{64}", nonce[0]) and key:
                    digest = hmac.new(key.encode(), nonce[0].encode(), hashlib.sha256).hexdigest()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")]})
                    await send({"type": "http.response.body", "body": digest.encode()})
                    return
                await self._refuse_http(send)
                return
            if method == "OPTIONS":
                await self.app(scope, receive, send)
                return
            if method in {"GET", "HEAD"}:
                # OpenHands has GET endpoints which execute Git or write
                # archives. Keep the Canvas connection and the delivery's
                # conversation readbacks available on a worker backend.
                conversation = r"/api/conversations/[0-9a-fA-F-]{32,36}"
                if (path in {"/api/conversations", "/api/conversations/search", "/api/settings", "/server_info"}
                        or re.fullmatch(
                        conversation + r"(?:/events(?:/[A-Za-z0-9_-]{1,128})?)?", path)):
                    await self.app(scope, receive, send)
                    return
                await self._refuse_http(send)
                return
            if method == "POST" and re.fullmatch(r"/api/conversations/[0-9a-fA-F-]{32,36}/interrupt", path):
                try:
                    state = service._read(self.directory)
                    if (state and state.get("kind") == "openhands_delivery_run.v1"
                            and state.get("worktree") == self.workspace
                            and state.get("phase") in {"interrupting", "interrupted"}):
                        await self.app(scope, receive, send)
                        return
                except (OSError, ValueError, service.ServiceError):
                    pass
                await self._refuse_http(send)
                return
            # The delivery path uses only conversation creation and message
            # admission. Other write endpoints can start background work or
            # run a long shell command outside this cancellation boundary.
            if not (method == "POST" and (path == "/api/conversations" or
                    re.fullmatch(r"/api/conversations/[0-9a-fA-F-]{32,36}/(?:events|run)", path))):
                await self._refuse_http(send)
                return
            # Do not hold the cancellation fence while a client slowly uploads a body.
            messages: list[dict[str, Any]] = []
            size = 0
            try:
                while True:
                    message = await asyncio.wait_for(receive(), timeout=5)
                    if message.get("type") != "http.request":
                        return
                    size += len(message.get("body", b""))
                    if size > 4 * 1024 * 1024:
                        raise ValueError("Request body is too large")
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
            except (asyncio.TimeoutError, ValueError):
                await self._refuse_http(send)
                return
            try:
                fd = await self._acquire()
            except (OSError, ValueError, service.ServiceError):
                await self._refuse_http(send)
                return
            async def buffered_receive() -> dict[str, Any]:
                if messages:
                    return messages.pop(0)
                return await receive()
            task = asyncio.create_task(self.app(scope, buffered_receive, send))
            try:
                await asyncio.shield(task)
            finally:
                # A disconnected client must not release the fence while an
                # upstream executor thread is still processing its message.
                # If upstream itself is cancelled, keep the fence until this
                # service exits: the executor's outcome is then unknown.
                def release(done: asyncio.Task[Any]) -> None:
                    if not done.cancelled():
                        os.close(fd)
                if task.done():
                    release(task)
                else:
                    task.add_done_callback(release)
            return
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return
        if not re.fullmatch(r"/sockets/(?:session|events)/[0-9a-fA-F-]{32,36}", scope.get("path", "")):
            # The bash socket and app-backend bridges can launch work without
            # a conversation run; they are not part of the delivery route.
            await send({"type": "websocket.close", "code": 1008})
            return
        held: int | None = None

        async def fenced_receive() -> dict[str, Any]:
            nonlocal held
            if held is not None:
                os.close(held)
                held = None
            message = await receive()
            if message.get("type") != "websocket.receive":
                return message
            # Agent-server consumes these as authentication control frames,
            # including a redundant frame after header-based authentication.
            # They are not conversation input and can precede a slow replay.
            try:
                value = json.loads(message.get("text") or message.get("bytes") or "")
                if (isinstance(value, dict) and value.get("type") == "auth"
                        and set(value) <= {"type", "session_api_key"}):
                    return message
            except (TypeError, ValueError, UnicodeError):
                pass
            try:
                held = await self._acquire()
            except (OSError, ValueError, service.ServiceError):
                await send({"type": "websocket.close", "code": 1008})
                return {"type": "websocket.disconnect", "code": 1008}
            return message

        async def serve_socket() -> None:
            nonlocal held
            try:
                await self.app(scope, fenced_receive, send)
            except asyncio.CancelledError:
                # The upstream executor may still have the last message.
                held = None  # Retain the open descriptor until service exit.
                raise
            finally:
                if held is not None:
                    os.close(held)

        task = asyncio.create_task(serve_socket())
        await asyncio.shield(task)

    @staticmethod
    async def _refuse_http(send: Any) -> None:
        await send({"type": "http.response.start", "status": 409,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"detail":"delivery_continuation_unverified"}'})


def main() -> None:
    directory = os.environ["OPENHANDS_FACTORY_DELIVERY_DIR"]
    workspace = os.environ["OPENHANDS_FACTORY_WORKSPACE"]
    from openhands.agent_server.api import api
    from openhands.agent_server.__main__ import main as upstream_main

    api.add_middleware(DeliveryInputFence, directory=directory, workspace=workspace)
    upstream_main()
