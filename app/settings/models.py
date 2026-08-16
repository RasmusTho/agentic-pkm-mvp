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


class LLMRoutingSettings(BaseModel):
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Compiled LLM request timeout; legacy LLM_TIMEOUT overrides when set.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Compiled LLM sampling temperature; legacy LLM_TEMPERATURE overrides when set.",
    )
    class RouteTarget(BaseModel):
        model_id: str | None = Field(
            default=None,
            description="Model registry id for this route. Provider/model are derived from it when present.",
        )
        provider: str | None = Field(
            default=None,
            description="Provider id for this route (mock|ollama|openai|deepseek).",
        )
        model: str | None = Field(
            default=None,
            description="Model override for this route.",
        )
        profile: str | None = Field(
            default=None,
            description="Optional embedding profile override when routing embed tasks.",
        )

    class FallbackPolicy(BaseModel):
        mode: Literal["never", "local", "allowed", "skip"] = Field(
            default="never",
            description="Fallback policy when the preferred route cannot be used.",
        )
        model_id: str | None = Field(
            default=None,
            description="Fallback model registry id when fallback is allowed.",
        )
        provider: str | None = Field(
            default=None,
            description="Fallback provider override when fallback is allowed.",
        )
        model: str | None = Field(
            default=None,
            description="Fallback model override when fallback is allowed.",
        )
        profile: str | None = Field(
            default=None,
            description="Fallback embedding profile override when fallback is allowed.",
        )

    class TaskPolicy(BaseModel):
        primary: "LLMRoutingSettings.RouteTarget" = Field(
            default_factory=lambda: LLMRoutingSettings.RouteTarget(),
            description="Preferred route for this task class.",
        )
        fallback: "LLMRoutingSettings.FallbackPolicy" = Field(
            default_factory=lambda: LLMRoutingSettings.FallbackPolicy(),
            description="Fallback behavior for this task class.",
        )
        require_compatible_identity: bool = Field(
            default=False,
            description="Require fallback to preserve embedding identity compatibility.",
        )

    default_provider: str | None = Field(
        default=None,
        description="Default LLM provider override for router (vault-configurable).",
    )
    default_chat_model: str | None = Field(
        default=None,
        description="Default chat model override for routed LLM tasks.",
    )
    default_embed_model: str | None = Field(
        default=None,
        description="Default embedding model override for routed tasks.",
    )
    task_overrides: Dict[str, Dict[str, str]] = Field(
        default_factory=dict,
        description="Per task_kind provider/model overrides (future use).",
    )
    default_chat: "LLMRoutingSettings.TaskPolicy" = Field(
        default_factory=lambda: LLMRoutingSettings.TaskPolicy(),
        description="Default task policy for chat/completion work.",
    )
    default_reasoning: "LLMRoutingSettings.TaskPolicy" = Field(
        default_factory=lambda: LLMRoutingSettings.TaskPolicy(),
        description="Default task policy for reasoning-heavy work.",
    )
    default_embedding: "LLMRoutingSettings.TaskPolicy" = Field(
        default_factory=lambda: LLMRoutingSettings.TaskPolicy(require_compatible_identity=True),
        description="Default task policy for embeddings and retrieval/index identity.",
    )
    default_eval: "LLMRoutingSettings.TaskPolicy" = Field(
        default_factory=lambda: LLMRoutingSettings.TaskPolicy(
            fallback=LLMRoutingSettings.FallbackPolicy(mode="skip")
        ),
        description="Default task policy for eval tooling.",
    )
    tasks: Dict[str, "LLMRoutingSettings.TaskPolicy"] = Field(
        default_factory=dict,
        description="Per task_kind routing policies.",
    )


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
    host: str = Field(default="", description="Base URL for local providers.")
    timeout_s: float = Field(default=120.0, description="HTTP timeout in seconds.")
    max_tokens: int = Field(default=512, description="Maximum tokens per response.")



class EmbeddingProfile(BaseModel):
    provider: str = Field(default="mock", description="Embedding provider identifier (mock|ollama|http).")
    model: str = Field(default="nomic-embed-text:latest", description="Embedding model identifier.")
    # Matches app/embedding_config.py::DEFAULT_EMBED_DIM (768) — closes the
    # EMBED_DIM/DEFAULT_EMBED_DIM drift (#2296/#2297) rather than layering a
    # third stale value alongside it. See docs/EMBEDDINGS.md :: EMBED_DIM.
    dim: int = Field(default=768, description="Embedding dimension for this profile.")
    normalize: bool = Field(default=True, description="Apply L2 normalization when true.")
    primary_provider: str | None = Field(
        default=None,
        description=(
            "Preferred embedding provider for this profile. "
            "Takes precedence over the 'provider' field when set. "
            "Operator can also set EMBED_PRIMARY_PROVIDER env var (env wins over profile)."
        ),
    )
    fallback_provider: str | None = Field(
        default=None,
        description=(
            "Fallback embedding provider for this profile, used by EMBEDREL-05 "
            "fallback orchestration when the primary fails after retries. "
            "Ignored at runtime until EMBEDREL-05 is wired. "
            "Operator can also set EMBED_FALLBACK_PROVIDER env var (env wins over profile)."
        ),
    )
    no_prefix: bool = Field(
        default=True,
        description=(
            "True when the model family requires no query/passage prefix formatting "
            "(docs/EMBEDDINGS.md :: Model-specific formatting). Both nomic-embed-text "
            "and BGE-M3 are no-prefix models; recorded per-profile so this is not "
            "re-litigated per call site if an E5-family (prefix-requiring) profile is "
            "added later."
        ),
    )
    max_input_chars: int | None = Field(
        default=None,
        description=(
            "Recommended EMBED_MAX_INPUT_CHARS value for this profile (see "
            "app/llm/embeddings.py::_embedding_max_input_chars). This is "
            "descriptive/advisory, not auto-applied: the actual chunking budget "
            "is still read from the EMBED_MAX_INPUT_CHARS env var at call time. "
            "Operators activating a profile whose max_input_chars differs from "
            "the built-in default (6000, tuned for nomic-embed-text's ~2k-token "
            "window) must also set EMBED_MAX_INPUT_CHARS explicitly — see the "
            "cutover runbook (docs/ops/BGE_M3_CUTOVER_RUNBOOK.md)."
        ),
    )


class EmbeddingProfiles(BaseModel):
    default_profile: str = Field(default="default", description="Profile name to use when unspecified.")
    profiles: Dict[str, EmbeddingProfile] = Field(
        default_factory=lambda: {
            "bge-m3": EmbeddingProfile(
                provider="ollama",
                model="bge-m3",
                dim=1024,
                normalize=True,
                no_prefix=True,
                # ~8192-token window (vs. nomic-embed-text's ~2k) allows a larger
                # in-budget chunk before the mean-pooling fallback kicks in,
                # producing better long-note vectors. See docs/EMBEDDINGS.md ::
                # Oversized input handling.
                max_input_chars=24000,
            ),
        },
        description=(
            "Named embedding profiles keyed by profile name. Registering the "
            "'bge-m3' profile here makes it SELECTABLE (EMBED_PROFILE=bge-m3 or "
            "default_profile: bge-m3 in runtime/settings/embeddings.yaml); it is "
            "not the shipped default and activating it is an explicit operator "
            "action gated on pulling bge-m3 into Ollama and running a full "
            "re-index (docs/ops/BGE_M3_CUTOVER_RUNBOOK.md, ADR-0052, #2984)."
        ),
    )


class LinearFusionWeights(BaseModel):
    """Weights for the ratified linear-fusion strategy (ADR-0024, encoded as config by ADR-0059 D3).

    Defaults (0.5/0.4/0.1) are today's trust encoding: exact lexical match (BM25) weighted above
    fuzzy semantic match (embeddings), with a small overlap bonus. Changing these values is a
    ranking-behavior change; the shipped default reproduces
    `app/retrieval/hybrid.py::_rank_eligible` exactly.
    """

    bm25: float = Field(default=0.5, ge=0.0, description="Weight on the normalized BM25 (lexical) score.")
    embedding: float = Field(default=0.4, ge=0.0, description="Weight on the normalized embedding (semantic) similarity score.")
    overlap: float = Field(default=0.1, ge=0.0, description="Weight on the query/doc token-overlap bonus.")


class RRFSignalWeights(BaseModel):
    """Per-signal multipliers on ``1/(k + rank)`` for the weighted RRF fusion strategy.

    Implemented behind ``fusion="rrf"`` (ADR-0059 D3 step 5, issue #3407); still ships dark — the
    default ``fusion`` stays ``"linear"`` until an eval-gated owner call flips it. ``lexical >=
    dense`` by default so the trust hierarchy that the linear weights encode today survives the
    strategy swap — weighted RRF, not vanilla RRF. The token-overlap signal (the linear formula's
    third, smallest term) is intentionally not exposed here as a user-tunable weight — it is not
    part of the trust-hierarchy knob this model guards; see
    ``app/retrieval/hybrid.py::_RRF_OVERLAP_WEIGHT`` for its fixed multiplier.
    """

    lexical: float = Field(default=1.0, ge=0.0, description="Multiplier on the lexical (BM25) reciprocal-rank signal.")
    dense: float = Field(default=0.8, ge=0.0, description="Multiplier on the dense (embedding) reciprocal-rank signal.")


class RetrievalTuning(BaseModel):
    """Typed, settings-backed, env-overridable retrieval tuning surface (ADR-0059 D3, #3404).

    Resolved once per process via ``app.retrieval.tuning.get_retrieval_tuning()`` — never a
    per-query ``os.getenv`` read. With no override set anywhere, every field below reproduces
    today's ranking exactly (byte-identical parity is a hard constraint of #3404). ``fusion="rrf"``
    and ``rerank="conditional"`` are implemented (ADR-0059 D3 step 5, issue #3407) but ship dark:
    selecting either is a valid, resolvable config choice, never the shipped default. A default
    flip is a separate owner call gated on eval evidence, recorded against ADR-0059.
    """

    fusion: Literal["linear", "rrf"] = Field(
        default="linear",
        description=(
            "Fusion strategy. 'linear' (default) matches today's ranking exactly. 'rrf' is "
            "implemented (ADR-0059 D3 step 5 / #3407, weighted RRF) but ships dark: selecting it "
            "is a deliberate operator/eval action, never the shipped default."
        ),
    )
    linear_weights: LinearFusionWeights = Field(default_factory=LinearFusionWeights)
    rrf_k: int = Field(
        default=60,
        ge=1,
        description="RRF k constant (30-40 favors top-1 precision per the ADR-0059 audit citations); used only when fusion='rrf'.",
    )
    rrf_signal_weights: RRFSignalWeights = Field(default_factory=RRFSignalWeights)
    retrieve_depth: int = Field(
        default=500,
        ge=1,
        description=(
            "Per-signal candidate depth. Dormant by construction today: the in-memory cache is "
            "full-corpus, so every document is already scored regardless of this value. Recorded "
            "now (ADR-0059 D3) so the config shape does not churn later if/when an ANN backend or a "
            "non-full-corpus cache makes it meaningful; documented as dormant, not silently ignored."
        ),
    )
    rerank: Literal["off", "always", "conditional"] = Field(
        default="off",
        description=(
            "Rerank gate. 'off' (default) matches today's behavior. 'always' reranks every result "
            "through the existing optional rerank hook. 'conditional' is implemented (ADR-0059 D3 "
            "step 5 / #3407): a deterministic score-margin gate, not a keyword classifier — it "
            "reranks only when the top BM25 result does not already dominate. Ships dark; the "
            "default stays 'off'."
        ),
    )
    rerank_top_k: int = Field(
        default=100,
        ge=1,
        description="Maximum results handed to the reranker when rerank is active.",
    )
    rerank_score_margin: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Score-margin threshold for the conditional rerank gate: rerank is skipped when the "
            "top-1 vs top-2 normalized-BM25 gap over the admitted candidate set is >= this value. "
            "Used only when rerank='conditional'."
        ),
    )


class QaSettings(AgentBase):
    search_k: int = Field(default=8, description="Documents retrieved before filtering.")
    context_docs: int = Field(default=5, description="Documents kept in the final answer context.")
    llm: QaLLMSettings = Field(default_factory=QaLLMSettings)


DEFAULT_ASK_SYSTEM_PROMPT = (
    "You are a personal PKM assistant, operating over a mixed corpus of vault notes and external documents.\n"
    "Your job is to answer questions using ONLY the provided sources.\n"
    "When choosing what to base your answer on:\n"
    '- Prefer content with origin: "vault" (personal notes) over external sources.\n'
    '- Prefer items in the "hot" zone over "warm", and both over "cold"/unspecified.\n'
    "- When multiple sources agree, synthesize them.\n"
    "- When sources disagree, say that they disagree and summarize the main positions.\n"
    "- When a source directly contains the answer (a definition, list, or stated fact), give it in full and enumerate the items; do not abstain when the content is present.\n"
    "- If the answer is not clearly supported by the sources, explicitly say you are unsure.\n"
    "Keep answers concise but not cryptic. Use clear, direct language and avoid filler."
)


def build_ask_system_prompt(owner_name: Optional[str] = None) -> str:
    if not owner_name:
        return DEFAULT_ASK_SYSTEM_PROMPT
    return (
        f"You are {owner_name}'s personal PKM assistant, operating over a mixed corpus of vault notes and external documents.\n"
        "Your job is to answer questions using ONLY the provided sources.\n"
        "When choosing what to base your answer on:\n"
        f'- Prefer content with origin: "vault" ({owner_name}\'s own notes) over external sources.\n'
        '- Prefer items in the "hot" zone over "warm", and both over "cold"/unspecified.\n'
        "- When multiple sources agree, synthesize them.\n"
        "- When sources disagree, say that they disagree and summarize the main positions.\n"
        "- When a source directly contains the answer (a definition, list, or stated fact), give it in full and enumerate the items; do not abstain when the content is present.\n"
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


class VaultSettings(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description=(
            "Human-facing vault name shown in the Companion UI and used as the "
            "vault's runtime identity. When unset, the runtime infers it from the "
            "VAULT_ROOT path basename. Authoritative and hot-reloadable: changing "
            "it does not require a restart."
        ),
    )
    owner_name: Optional[str] = Field(
        default=None,
        description=(
            "Display name of the vault owner. When set, personalises the ASK agent system "
            "prompt so the assistant addresses the user by name. Leave unset for a generic prompt."
        ),
    )
    purpose: Optional[str] = Field(
        default=None,
        description=(
            "Reserved for multi-vault routing (e.g. 'personal', 'work', 'research'). "
            "Not yet wired to vault selection; present so a single-vault config can "
            "evolve into plural vaults without a schema break."
        ),
    )


class InstanceSettings(BaseModel):
    id: str = Field(
        default="home",
        description="Logical instance id (e.g. 'home', 'work', 'laptop').",
    )
    role: Literal["master", "satellite"] = Field(
        default="master",
        description="Instance role; 'master' is canonical, 'satellite' runs a partial view.",
    )
    environment: Literal["dev", "prod", "test"] = Field(
        default="prod",
        description="Runtime environment; 'prod' is production-safe default, 'dev' enables development features.",
    )
    vault: VaultSettings = Field(
        default_factory=VaultSettings,
        description="Active vault identity. Hot-reloadable; the seam for future multi-vault support.",
    )


class SettingsBundle(BaseModel):
    global_: GlobalSettings = Field(default_factory=GlobalSettings)
    providers: Providers = Field(default_factory=Providers)
    llm_routing: LLMRoutingSettings = Field(default_factory=LLMRoutingSettings)
    embedding_profiles: EmbeddingProfiles = Field(default_factory=EmbeddingProfiles)
    retrieval_tuning: RetrievalTuning = Field(default_factory=RetrievalTuning)
    agents: Dict[str, Any] = Field(default_factory=dict)
    yggdrasil_paths: Optional[YggdrasilPaths] = None
    instance: InstanceSettings = Field(default_factory=InstanceSettings)
