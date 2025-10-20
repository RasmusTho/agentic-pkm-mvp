from __future__ import annotations

from pathlib import Path

from app.config.agent import AgentConfigManager


def test_agent_config_loads_defaults(tmp_path: Path) -> None:
    path = tmp_path / "agent.yaml"
    path.write_text("scheduler:\n  interval_seconds: 120\n", encoding="utf-8")
    manager = AgentConfigManager(path)
    config = manager.get_config()
    assert config.scheduler.interval_seconds == 120
    assert config.enabled_plugins == []
    manager.stop()


def test_agent_config_reload(tmp_path: Path) -> None:
    path = tmp_path / "agent.yaml"
    path.write_text("plugins:\n  enabled:\n    - retriever\n", encoding="utf-8")
    manager = AgentConfigManager(path)
    manager.start()
    path.write_text(
        "plugins:\n  enabled:\n    - retriever\n    - write_note\n",
        encoding="utf-8",
    )
    manager.reload()
    config = manager.get_config()
    assert "write_note" in config.enabled_plugins
    manager.stop()
