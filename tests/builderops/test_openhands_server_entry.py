import asyncio
import importlib.util
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.builderops import openhands_service as service
from app.builderops.openhands_server_entry import DeliveryInputFence, _install_loaded_interrupt


def test_http_blocks_direct_run_and_events_after_interrupt(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active",
                 "conversation_id": "11111111-1111-4111-8111-111111111111"}
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
        base = "/api/conversations/11111111-1111-4111-8111-111111111111"
        await fence({"type": "http", "method": "POST", "path": base + "/run"}, receive, send)
        await fence({"type": "http", "method": "POST", "path": base + "/goal"}, receive, send)
        await fence({"type": "http", "method": "POST", "path": "/api/bash/execute_bash_command"}, receive, send)
        await fence({"type": "http", "method": "GET", "path": "/api/file/archive"}, receive, send)
        for path in ("/api/settings", "/server_info", "/api/conversations/search"):
            await fence({"type": "http", "method": "GET", "path": path}, receive, send)
        await fence({"type": "http", "method": "GET", "path": base + "/events/search"}, receive, send)
        service._write(tmp_path, {**state, "phase": "interrupted"})
        for path in (base + "/run", base + "/events"):
            await fence({"type": "http", "method": "POST", "path": path}, receive, send)
        interrupt_path = "/api/conversations/11111111-1111-4111-8111-111111111111/interrupt"
        await fence({"type": "http", "method": "POST", "path": interrupt_path}, receive, send)
        service._write(tmp_path, {**state, "phase": "interrupting"})
        await fence({"type": "http", "method": "POST", "path": "/api/conversations/22222222-2222-4222-8222-222222222222/interrupt"}, receive, send)
        await fence({"type": "http", "method": "POST", "path": interrupt_path}, receive, send)
        service._write(tmp_path, {**state, "phase": "interrupted"})
        await fence({"type": "http", "method": "POST", "path": "/api/app-backends/name/interrupt"}, receive, send)
        await fence({"type": "http", "method": "GET", "path": base + "/events/search"}, receive, send)
        await fence({"type": "http", "method": "GET", "path": "/api/file/archive"}, receive, send)
        assert handled == [base + "/run", "/api/settings", "/server_info", "/api/conversations/search",
                           base + "/events/search", interrupt_path]
        assert [r["status"] for r in responses if r["type"] == "http.response.start"] == [409] * 10
    asyncio.run(run())


def test_interrupt_only_uses_live_recorded_event_under_lifecycle_lock(tmp_path: Path):
    async def run():
        conversation_id = UUID("11111111-1111-4111-8111-111111111111")
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work",
                 "phase": "interrupting", "conversation_id": str(conversation_id)}
        service._write(tmp_path, state)
        lock = asyncio.Lock()
        calls = []

        class Event:
            stored = "stored"
            is_open_value = True
            def is_open(self):
                return self.is_open_value
            async def interrupt(self):
                assert lock.locked()
                calls.append("interrupt")
            async def get_state(self):
                return "paused"

        class ConversationService:
            _event_services = {}
            @asynccontextmanager
            async def _conversation_lifecycle(self, unused):
                async with lock:
                    yield
            async def _notify_conversation_webhooks(self, info):
                calls.append(info)

        _install_loaded_interrupt(ConversationService, tmp_path, "/work", lambda stored, status: (stored, status))
        instance = ConversationService()
        assert not await instance.interrupt_conversation(conversation_id)
        event = Event()
        instance._event_services[conversation_id] = event
        event.is_open_value = False
        assert not await instance.interrupt_conversation(conversation_id)
        event.is_open_value = True
        assert await instance.interrupt_conversation(conversation_id)
        assert calls == ["interrupt", ("stored", "paused")]
        async with lock:
            pending = asyncio.create_task(instance.interrupt_conversation(conversation_id))
            await asyncio.sleep(0)
            service._write(tmp_path, {**state, "phase": "interrupted"})
        assert not await pending
        assert calls == ["interrupt", ("stored", "paused")]
    asyncio.run(run())


@pytest.mark.skipif(importlib.util.find_spec("openhands") is None, reason="requires pinned agent-server")
def test_pinned_openhands_interrupt_route_never_reloads_an_unloaded_runtime(tmp_path: Path, monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from openhands.agent_server.conversation_router import conversation_router
    from openhands.agent_server.conversation_service import ConversationService
    from openhands.agent_server.dependencies import check_session_api_key

    conversation_id = UUID("11111111-1111-4111-8111-111111111111")
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work",
             "phase": "interrupting", "conversation_id": str(conversation_id)}
    service._write(tmp_path, state)
    calls = []

    class Event:
        stored = "stored"
        open = True
        def is_open(self):
            return self.open
        async def interrupt(self):
            calls.append("interrupt")
        async def get_state(self):
            return "paused"

    cs = ConversationService(conversations_dir=tmp_path / "conversations")
    cs._event_services = {}
    async def notified(info):
        calls.append(info)
    cs._notify_conversation_webhooks = notified
    monkeypatch.setattr(ConversationService, "interrupt_conversation", ConversationService.interrupt_conversation)
    _install_loaded_interrupt(ConversationService, tmp_path, "/work", lambda stored, status: (stored, status))
    api = FastAPI()
    api.state.config = SimpleNamespace(session_api_keys=["synthetic-key"])
    api.state.conversation_service = cs
    api.include_router(conversation_router, prefix="/api", dependencies=[Depends(check_session_api_key)])
    api.add_middleware(DeliveryInputFence, directory=str(tmp_path), workspace="/work")
    path = f"/api/conversations/{conversation_id}/interrupt"
    headers = {"X-Session-API-Key": "synthetic-key"}
    with TestClient(api) as client:
        assert client.post(path).status_code == 401
        assert client.post(path, headers=headers).status_code == 404
        assert not (tmp_path / "conversations").exists()
        event = Event()
        cs._event_services[conversation_id] = event
        event.open = False
        assert client.post(path, headers=headers).status_code == 404
        event.open = True
        assert client.post(path, headers=headers).status_code == 200
        assert calls == ["interrupt", ("stored", "paused")]
        service._write(tmp_path, {**state, "phase": "interrupted"})
        assert client.post(path, headers=headers).status_code == 409
        assert calls == ["interrupt", ("stored", "paused")]


def test_disconnected_http_client_does_not_release_fence_before_handler_finishes(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        started, finish, changed = asyncio.Event(), asyncio.Event(), threading.Event()
        async def app(scope, receive, send):
            started.set()
            await finish.wait()
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(message):
            pass
        def interrupt():
            with service._locked(tmp_path / "input-fence"):
                changed.set()
        client = asyncio.create_task(DeliveryInputFence(app, str(tmp_path), "/work")(
            {"type": "http", "method": "POST", "path": "/api/conversations/11111111-1111-4111-8111-111111111111/events"}, receive, send))
        await started.wait()
        client.cancel()
        try:
            await client
        except asyncio.CancelledError:
            pass
        waiter = asyncio.create_task(asyncio.to_thread(interrupt))
        await asyncio.sleep(0.05)
        assert not changed.is_set()
        finish.set()
        await waiter
        assert changed.is_set()
    asyncio.run(run())


def test_stalled_request_body_does_not_hold_cancellation_fence(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        entered, finish = asyncio.Event(), asyncio.Event()
        handled, sent = [], []
        async def app(scope, receive, send):
            handled.append(True)
        async def receive():
            entered.set()
            await finish.wait()
            return {"type": "http.request", "body": b""}
        async def send(message):
            sent.append(message)
        request = asyncio.create_task(DeliveryInputFence(app, str(tmp_path), "/work")(
            {"type": "http", "method": "POST", "path": "/api/conversations/11111111-1111-4111-8111-111111111111/events"}, receive, send))
        await entered.wait()
        with service._locked(tmp_path / "input-fence", timeout=0.1):
            service._write(tmp_path, {**state, "phase": "interrupted"})
        finish.set()
        await request
        assert not handled and sent[0]["status"] == 409
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
            {"type": "websocket", "path": "/sockets/session/11111111-1111-4111-8111-111111111111"}, receive, send)
        assert seen[-1] == {"type": "websocket.disconnect", "code": 1008}
        assert sent == [{"type": "websocket.close", "code": 1008}]
        assert all(m.get("text") != "replay" for m in seen)
    asyncio.run(run())


def test_unsupported_worker_websockets_do_not_launch_commands(tmp_path: Path):
    async def run():
        handled, sent = [], []
        async def app(scope, receive, send):
            handled.append(True)
        async def receive():
            return {"type": "websocket.connect"}
        async def send(message):
            sent.append(message)
        fence = DeliveryInputFence(app, str(tmp_path), "/work")
        for path in ("/sockets/bash-events", "/app-backends/other"):
            await fence({"type": "websocket", "path": path}, receive, send)
        assert not handled and sent == [{"type": "websocket.close", "code": 1008}] * 2
    asyncio.run(run())


def test_websocket_auth_frame_does_not_block_cancellation_during_replay(tmp_path: Path):
    async def run():
        state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "active"}
        service._write(tmp_path, state)
        replay_started, finish = asyncio.Event(), asyncio.Event()
        incoming = iter([{"type": "websocket.connect"},
                         {"type": "websocket.receive", "text": '{"type":"auth","session_api_key":"test"}'}])
        async def app(scope, receive, send):
            await receive()
            await receive()
            await send({"type": "websocket.send", "text": "initial state"})
            replay_started.set()
            await finish.wait()
        async def receive():
            return next(incoming)
        async def send(message):
            pass
        task = asyncio.create_task(DeliveryInputFence(app, str(tmp_path), "/work")(
            {"type": "websocket", "path": "/sockets/events/11111111-1111-4111-8111-111111111111"}, receive, send))
        await replay_started.wait()
        with service._locked(tmp_path / "input-fence", timeout=0.1):
            service._write(tmp_path, {**state, "phase": "interrupting"})
        finish.set()
        await task
    asyncio.run(run())


def test_interrupted_conversation_does_not_load_unloaded_event_runtime(tmp_path: Path):
    async def run():
        service._write(tmp_path, {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": "/work", "phase": "interrupted"})
        touched, sent = [], []
        async def app(scope, receive, send):
            message = await receive()
            if message.get("type") == "websocket.connect":
                touched.append("loaded")
        async def receive():
            return {"type": "websocket.connect"}
        async def send(message):
            sent.append(message)
        await DeliveryInputFence(app, str(tmp_path), "/work")(
            {"type": "websocket", "path": "/sockets/session/11111111-1111-4111-8111-111111111111"}, receive, send)
        assert not touched and sent == [{"type": "websocket.close", "code": 1008}]
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
            {"type": "http", "method": "POST", "path": "/api/conversations/11111111-1111-4111-8111-111111111111/events"}, receive, send))
        await admitted.wait()
        stopper = asyncio.create_task(asyncio.to_thread(interrupt))
        await asyncio.sleep(0.05)
        assert not changed.is_set()
        finish.set()
        await task
        await stopper
        assert json.loads((tmp_path / "service.json").read_text())["phase"] == "interrupting"
    asyncio.run(run())
