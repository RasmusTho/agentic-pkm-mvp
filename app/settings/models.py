from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GlobalSettings(BaseModel):
    enable: bool = True
    dry_run: bool = False
    timeout_ms: int = 8000
    log_level: str = "INFO"
    profile: str = "default"
    secrets: Dict[str, str] = Field(default_factory=dict)


class ProviderRef(BaseModel):
    kind: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    device: Optional[str] = None


class Providers(BaseModel):
    llm: Dict[str, ProviderRef] = Field(default_factory=dict)
    embedding: Dict[str, ProviderRef] = Field(default_factory=dict)
    reranker: Dict[str, ProviderRef] = Field(default_factory=dict)


class RetryPolicy(BaseModel):
    max_tries: int = 2


class AgentBase(BaseModel):
    enable: bool = True
    dry_run: bool = False
    timeout_ms: int = 8000
    labels: List[str] = Field(default_factory=list)


class ClassifierSettings(AgentBase):
    min_confidence: float = 0.5
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    model: Optional[str] = None
    embedding: Optional[str] = None
    reranker: Optional[str] = None
    rules: Dict[str, Any] = Field(default_factory=dict)


class MovePolicy(BaseModel):
    enabled: bool = False
    window: str = "02:00-03:00"
    batch_size: int = 100


class PromotionSettings(AgentBase):
    move_policy: MovePolicy = Field(default_factory=MovePolicy)


class SettingsBundle(BaseModel):
    global_: GlobalSettings = Field(default_factory=GlobalSettings)
    providers: Providers = Field(default_factory=Providers)
    agents: Dict[str, Any] = Field(default_factory=dict)
