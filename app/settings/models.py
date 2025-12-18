from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GlobalSettings(BaseModel):
    enable: bool = Field(default=True, description="Enable this component for runtime pipelines.")
    dry_run: bool = Field(default=False, description="Skip persistence and side-effects when true.")
    note_moves_enable: bool = Field(
        default=False,
        description="Allow agents to move or rename notes as part of ingestion and promotion.",
    )
    timeout_ms: int = Field(
        default=8000,
        description="Per-operation timeout in milliseconds.",
        json_schema_extra={"allowed": ["100-60000"]},
    )
    log_level: str = Field(
        default="INFO",
        description="Log level for agents (DEBUG|INFO|WARNING|ERROR).",
        json_schema_extra={"allowed": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    )
    profile: str = Field(default="default", description="Active configuration profile name.")
    secrets: Dict[str, str] = Field(default_factory=dict, description="Secret references resolved at compile time.")


class ProviderRef(BaseModel):
    kind: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    device: Optional[str] = None


class Providers(BaseModel):
    llm: Dict[str, ProviderRef] = Field(default_factory=dict, description="Named chat/LLM providers.")
    embedding: Dict[str, ProviderRef] = Field(default_factory=dict, description="Embedding model providers.")
    reranker: Dict[str, ProviderRef] = Field(default_factory=dict, description="Cross-encoder/rerank providers.")


class RetryPolicy(BaseModel):
    max_tries: int = Field(default=2, description="Retry attempts before surfacing errors.")


class AgentBase(BaseModel):
    enable: bool = Field(default=True, description="Enable this agent.")
    dry_run: bool = Field(default=False, description="Disable writes for this agent.")
    timeout_ms: int = Field(
        default=8000,
        description="Agent-specific timeout in milliseconds.",
        json_schema_extra={"allowed": ["100-120000"]},
    )
    labels: List[str] = Field(default_factory=list, description="Tag this agent with capability labels.")


class ClassifierSettings(AgentBase):
    min_confidence: float = Field(default=0.5, description="Minimum confidence for positive classifications.")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    model: Optional[str] = Field(default=None, description="Preferred LLM model for classifier prompts.")
    embedding: Optional[str] = Field(default=None, description="Embedding provider override.")
    reranker: Optional[str] = Field(default=None, description="Reranker provider override.")
    rules: Dict[str, Any] = Field(default_factory=dict, description="Additional policy flags for classifier runs.")


class MovePolicy(BaseModel):
    enabled: bool = Field(default=False, description="Enable promotion move window enforcement.")
    window: str = Field(default="02:00-03:00", description="HH:MM-HH:MM window where moves are allowed.")
    batch_size: int = Field(default=100, description="Files moved per batch.")
    default_target: str = Field(default="2_Cards/Concepts", description="Fallback folder for promoted files.")
    targets: List[Dict[str, Any]] = Field(default_factory=list, description="Conditional move targets.")


class PromotionSettings(AgentBase):
    cooldown_seconds: int = Field(default=90, description="Minimum seconds since last edit before promotion.")
    require_idle_seconds: int = Field(default=30, description="Minimum idle seconds to avoid churn.")
    max_retries: int = Field(default=3, description="Queue retries before giving up on a promotion item.")
    move_policy: MovePolicy = Field(default_factory=MovePolicy)


class ReviewerRules(BaseModel):
    required_labels: List[str] = Field(default_factory=list, description="Objects must have these labels before review.")
    min_score: float = Field(default=0.75, description="Minimum acceptable reviewer score.")


class ReviewerSettings(AgentBase):
    threshold: float = Field(default=0.75, description="Score threshold to auto-approve.")
    escalation_channel: str = Field(default="audit", description="Audit or notification channel for escalations.")
    rules: ReviewerRules = Field(default_factory=ReviewerRules)


class QaLLMSettings(BaseModel):
    provider: str = Field(
        default="mock",
        description="qa.agent LLM provider (mock|ollama|http).",
        json_schema_extra={"allowed": ["mock", "ollama", "http"]},
    )
    model: str = Field(default="llama3.1:8b-instruct", description="Model identifier for QA prompts.")
    host: str = Field(default="http://127.0.0.1:11434", description="Base URL for local providers.")
    timeout_s: float = Field(default=120.0, description="HTTP timeout in seconds.")
    max_tokens: int = Field(default=512, description="Maximum tokens per response.")



class EmbeddingProfile(BaseModel):
    provider: str = Field(default="mock", description="Embedding provider identifier (mock|ollama|http).")
    model: str = Field(default="nomic-embed-text:latest", description="Embedding model identifier.")
    dim: int = Field(default=1536, description="Embedding dimension for this profile.")
    normalize: bool = Field(default=True, description="Apply L2 normalization when true.")


class EmbeddingProfiles(BaseModel):
    default_profile: str = Field(default="default", description="Profile name to use when unspecified.")
    profiles: Dict[str, EmbeddingProfile] = Field(
        default_factory=dict,
        description="Named embedding profiles keyed by profile name.",
    )


class QaSettings(AgentBase):
    search_k: int = Field(default=8, description="Documents retrieved before filtering.")
    context_docs: int = Field(default=5, description="Documents kept in the final answer context.")
    llm: QaLLMSettings = Field(default_factory=QaLLMSettings)


DEFAULT_ASK_SYSTEM_PROMPT = (
    "You are Rasmus Thornberg's personal PKM assistant, operating over a mixed corpus of his own notes and external documents.\n"
    "Your job is to answer questions using ONLY the provided sources.\n"
    "When choosing what to base your answer on:\n"
    '- Prefer content with origin: "vault" (Rasmus\' own notes) over external sources.\n'
    '- Prefer items in the "hot" zone over "warm", and both over "cold"/unspecified.\n'
    "- When multiple sources agree, synthesize them.\n"
    "- When sources disagree, say that they disagree and summarize the main positions.\n"
    "- If the answer is not clearly supported by the sources, explicitly say you are unsure.\n"
    "Keep answers concise but not cryptic. Use clear, direct language and avoid filler."
)


class AskSettings(AgentBase):
    system_prompt: str = Field(
        default=DEFAULT_ASK_SYSTEM_PROMPT,
        description="System prompt for the ASK agent.",
    )
    max_context_docs: int = Field(default=10, description="Maximum number of docs passed to the ASK LLM context.")
    max_context_chars: int = Field(default=16000, description="Character budget for ASK context payload.")
    answer_style: Literal["lean", "detailed"] = Field(default="lean")
    prefer_vault: bool = Field(default=True, description="Prefer vault-origin sources.")
    prefer_hot_zone: bool = Field(default=True, description="Prefer hot zone sources.")


class YggdrasilPaths(BaseModel):
    yggdrasil_root: Path
    mimer_root: Path
    hugin_root: Optional[Path] = None
    munin_root: Optional[Path] = None
    ratatosk_root: Optional[Path] = None
    brokkr_root: Optional[Path] = None
    tyr_root: Optional[Path] = None
    heimdall_root: Optional[Path] = None


class InstanceSettings(BaseModel):
    id: str = Field(
        default="home",
        description="Logical instance id (e.g. 'home', 'work', 'laptop').",
    )
    role: Literal["master", "satellite"] = Field(
        default="master",
        description="Instance role; 'master' is canonical, 'satellite' runs a partial view.",
    )


class SettingsBundle(BaseModel):
    global_: GlobalSettings = Field(default_factory=GlobalSettings)
    providers: Providers = Field(default_factory=Providers)
    embedding_profiles: EmbeddingProfiles = Field(default_factory=EmbeddingProfiles)
    agents: Dict[str, Any] = Field(default_factory=dict)
    yggdrasil_paths: Optional[YggdrasilPaths] = None
    instance: InstanceSettings = Field(default_factory=InstanceSettings)

