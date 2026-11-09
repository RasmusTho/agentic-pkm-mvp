import asyncio
import json
import threading
from pathlib import Path

from app.builderops import openhands_service as service
from app.builderops.openhands_server_entry import DeliveryInputFence


def test_http_blocks_direct_run_and_events_after_interrupt(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        handled = []
        responses = []

        async def app(scope, receive, send):
            handled.append(scope["path"])

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            responses.append(message)

        fence = DeliveryInputFence(app, str(tmp_path), "/work")
        await fence({"type": "http", "method": "POST", "path": "/api/conversations/id/run"}, receive, send)
        service._write(tmp_path, {**state, "phase": "interrupted"})
        for path in ("/api/conversations/id/run", "/api/conversations/id/events"):
            await fence({"type": "http", "method": "POST", "path": path}, receive, send)
        await fence({"type": "http", "method": "POST", "path": "/api/conversations/id/interrupt"}, receive, send)
        assert handled == ["/api/conversations/id/run", "/api/conversations/id/interrupt"]
        assert [r["status"] for r in responses if r["type"] == "http.response.start"] == [409, 409]
    asyncio.run(run())


def test_already_connected_websocket_cannot_send_after_interrupt(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        incoming = iter([{"type": "websocket.connect"}, {"type": "websocket.receive", "text": "first"},
                         {"type": "websocket.receive", "text": "replay"}])
        seen, sent = [], []

        # Use events to control delivery of the second frame deterministically.
        allow_second = asyncio.Event()
        async def receive():
            item = next(incoming)
            if item.get("text") == "replay":
                await allow_second.wait()
            return item
        async def send(message):
            sent.append(message)
        async def app_with_interrupt(scope, fenced_receive, send):
            seen.append(await fenced_receive())
            seen.append(await fenced_receive())
            next_frame = asyncio.create_task(fenced_receive())
            await asyncio.sleep(0)
            with service._locked(tmp_path / "input-fence"):
                service._write(tmp_path, {**state, "phase": "interrupted"})
            allow_second.set()
            seen.append(await next_frame)
        await DeliveryInputFence(app_with_interrupt, str(tmp_path), "/work")(
            {"type": "websocket", "path": "/api/session/id"}, receive, send)
        assert seen[-1] == {"type": "websocket.disconnect", "code": 1008}
        assert sent == [{"type": "websocket.close", "code": 1008}]
        assert all(m.get("text") != "replay" for m in seen)
    asyncio.run(run())


def test_cancellation_waits_for_an_admitted_input(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        admitted, finish = asyncio.Event(), asyncio.Event()
        changed = threading.Event()

        async def app(scope, receive, send):
            admitted.set()
            await finish.wait()
        async def receive():
            return {"type": "http.request"}
        async def send(message):
            pass
        def interrupt():
            with service._locked(tmp_path / "input-fence"):
                service._write(tmp_path, {**state, "phase": "interrupting"})
                changed.set()
        task = asyncio.create_task(DeliveryInputFence(app, str(tmp_path), "/work")(
            {"type": "http", "method": "POST", "path": "/api/conversations/id/events"}, receive, send))
        await admitted.wait()
        stopper = asyncio.create_task(asyncio.to_thread(interrupt))
        await asyncio.sleep(0.05)
        assert not changed.is_set()
        finish.set()
        await task
        await stopper
        assert json.loads((tmp_path / "service.json").read_text())["phase"] == "interrupting"
    asyncio.run(run())
