from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from app.agent.repository import PostgresAgentRepository
from app.agent.service import AgentService
from app.config.agent import AgentConfigManager
from app.settings import settings

logger = logging.getLogger("agent.service.runner")


async def _serve() -> None:
    repository = PostgresAgentRepository(settings.db_dsn)
    config_manager = AgentConfigManager(Path(settings.agent_config_path))
    service = AgentService(repository, config_manager)
    await service.start()

    stop_event = asyncio.Event()

    def _shutdown_handler() -> None:
        logger.info("Received shutdown signal for agent service.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _shutdown_handler)
    loop.add_signal_handler(signal.SIGINT, _shutdown_handler)

    logger.info("Agent service started. Waiting for stop signal.")
    await stop_event.wait()

    logger.info("Stopping agent service...")
    await service.stop()
    config_manager.stop()
    repository.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
