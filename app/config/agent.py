from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, Field
from watchfiles import watch

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class SchedulerConfig(BaseModel):
    interval_seconds: int = Field(default=300, ge=30)
    jitter_seconds: int = Field(default=15, ge=0)
    max_concurrent_runs: int = Field(default=1, ge=1)


class PlanConfig(BaseModel):
    seed_queries: list[str] = Field(default_factory=list)
    max_actions: int = Field(default=3, ge=1)


class InterestingnessConfig(BaseModel):
    novelty_weight: float = Field(default=0.25, ge=0.0)
    anomaly_weight: float = Field(default=0.25, ge=0.0)
    uncertainty_weight: float = Field(default=0.25, ge=0.0)
    value_weight: float = Field(default=0.25, ge=0.0)
    score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    def weights(self) -> dict[str, float]:
        total = (
            self.novelty_weight
            + self.anomaly_weight
            + self.uncertainty_weight
            + self.value_weight
        )
        if total <= 0:
            return {
                "novelty": 0.25,
                "anomaly": 0.25,
                "uncertainty": 0.25,
                "value": 0.25,
            }
        return {
            "novelty": self.novelty_weight / total,
            "anomaly": self.anomaly_weight / total,
            "uncertainty": self.uncertainty_weight / total,
            "value": self.value_weight / total,
        }


class AgentConfig(BaseModel):
    agent_name: str = Field(default="background-agent")
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    plan: PlanConfig = Field(default_factory=PlanConfig)
    plugins: dict[str, list[str]] = Field(default_factory=lambda: {"enabled": []})
    interestingness: InterestingnessConfig = Field(default_factory=InterestingnessConfig)

    @property
    def enabled_plugins(self) -> list[str]:
        return [name for name in self.plugins.get("enabled", []) if isinstance(name, str)]


class AgentConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or CONFIG_DIR / "agent.yaml").resolve()
        self._lock = threading.RLock()
        self._config = self._load()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._subscribers: list[Callable[[AgentConfig], None]] = []

    def _load(self) -> AgentConfig:
        if not self._path.exists():
            return AgentConfig()
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        return AgentConfig.model_validate(data)

    def get_config(self) -> AgentConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def set_config(self, config: AgentConfig) -> None:
        with self._lock:
            self._config = config
        for callback in list(self._subscribers):
            callback(config.model_copy(deep=True))

    def subscribe(self, callback: Callable[[AgentConfig], None]) -> None:
        self._subscribers.append(callback)

    def reload(self) -> AgentConfig:
        config = self._load()
        self.set_config(config)
        return config

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="agent-config-watch",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=1)
        self._thread = None

    def _watch_loop(self) -> None:
        directory = self._path.parent
        try:
            for changes in watch(directory, stop_event=self._stop_event):
                if self._stop_event.is_set():
                    break
                if any(Path(changed).resolve() == self._path for _, changed in changes):
                    self.reload()
        except FileNotFoundError:
            return
