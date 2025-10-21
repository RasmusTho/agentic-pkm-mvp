from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from typing import Callable, Mapping, Sequence
from uuid import uuid4

# NOTE: delayed import inside run loop for reflection consumer to avoid cycles.
from app.config.agent import AgentConfigManager
from app.plugins.base import Tool, ToolContext
from app.plugins.loader import load_tools

from .execute import execute_plan
from .interestingness import extract_candidates, score_candidates
from .plan import build_plan
from .reflect import summarize_plan, summarize_results
from .repository import AgentRepository

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        repository: AgentRepository,
        config_manager: AgentConfigManager,
        *,
        plugin_loader: Callable[[Sequence[str]], Mapping[str, Tool]] = load_tools,
    ) -> None:
        self._repository = repository
        self._config_manager = config_manager
        self._plugin_loader = plugin_loader
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._config_manager.start()
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="agent-service-loop")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> None:
        config = self._config_manager.get_config()
        self._consume_reflection_queue()
        run_id = uuid4()
        await asyncio.to_thread(self._repository.record_run_start, run_id, config)
        await asyncio.to_thread(
            self._repository.record_heartbeat,
            config.agent_name,
            run_id,
            "running",
        )

        actions = build_plan(config)
        plan_summary = summarize_plan(actions)
        tools = self._plugin_loader(config.enabled_plugins)
        ctx = ToolContext(run_id=run_id, config=config, repository=self._repository)

        try:
            results = await execute_plan(actions, ctx, tools, self._repository)
            result_summary = summarize_results(results)
            weights = config.interestingness.weights()
            candidates = extract_candidates(results)
            for scored in score_candidates(candidates, weights):
                if scored.score < config.interestingness.score_threshold:
                    continue
                await asyncio.to_thread(self._repository.upsert_interesting_item, run_id, scored)
            await asyncio.to_thread(
                self._repository.record_run_complete,
                run_id,
                "completed",
                plan_summary,
                result_summary,
            )
            await asyncio.to_thread(
                self._repository.record_heartbeat,
                config.agent_name,
                run_id,
                "idle",
            )
        except Exception as exc:  # pragma: no cover - defensive
            await asyncio.to_thread(
                self._repository.record_run_complete,
                run_id,
                "failed",
                plan_summary,
                f"Agent execution failed: {exc}",
            )
            await asyncio.to_thread(
                self._repository.record_heartbeat,
                config.agent_name,
                run_id,
                "error",
            )
            raise

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                await asyncio.sleep(5)
            config = self._config_manager.get_config()
            interval = max(config.scheduler.interval_seconds, 1)
            jitter = random.uniform(0, config.scheduler.jitter_seconds)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval + jitter)
            except asyncio.TimeoutError:
                continue

    def _consume_reflection_queue(self) -> None:
        from app.ingest.reflection_consumer import consume_reflection_queue

        try:
            consume_reflection_queue()
        except Exception as exc:  # pragma: no cover - defensive logging
            # Reflection failures should not stop primary agent loop,
            # but we log explicitly so operators can surface the issue.
            logger.warning("Reflection queue processing failed", exc_info=exc)
