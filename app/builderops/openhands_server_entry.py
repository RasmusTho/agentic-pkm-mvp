"""Fence inputs to an interrupted delivery before OpenHands persists them.

Only a delivery worker uses this entry point. The owner backend is unchanged.
This does not establish that any previous native process has stopped.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import stat
from pathlib import Path
from typing import Any

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
            if method in {"GET", "HEAD", "OPTIONS"} or (method == "POST" and path.endswith("/interrupt")):
                await self.app(scope, receive, send)
                return
            try:
                fd = await self._acquire()
            except (OSError, ValueError, service.ServiceError):
                await send({"type": "http.response.start", "status": 409,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"delivery_continuation_unverified"}'})
                return
            try:
                await self.app(scope, receive, send)
            finally:
                os.close(fd)
            return
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
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
            try:
                held = await self._acquire()
            except (OSError, ValueError, service.ServiceError):
                await send({"type": "websocket.close", "code": 1008})
                return {"type": "websocket.disconnect", "code": 1008}
            return message

        try:
            await self.app(scope, fenced_receive, send)
        finally:
            if held is not None:
                os.close(held)


def main() -> None:
    directory = os.environ["OPENHANDS_FACTORY_DELIVERY_DIR"]
    workspace = os.environ["OPENHANDS_FACTORY_WORKSPACE"]
    from openhands.agent_server.api import api
    from openhands.agent_server.__main__ import main as upstream_main

    api.add_middleware(DeliveryInputFence, directory=directory, workspace=workspace)
    upstream_main()
