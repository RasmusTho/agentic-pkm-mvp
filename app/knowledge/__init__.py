from app.knowledge.contracts import KnowledgePort, NoteLocator, SearchHit, WriteReceipt
from app.knowledge.errors import (
    KnowledgeCapabilityError,
    KnowledgeConfigError,
    KnowledgeDependencyError,
    KnowledgeError,
    KnowledgeWriteConflict,
)
from app.knowledge.health import ObsidianDependencyStatus, obsidian_dependency_status
from app.knowledge.obsidian_cli_scope import has_valid_vault_scope, scoped_cli_args
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.service import resolve_knowledge_port
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings, load_knowledge_settings
from app.knowledge.adapters import FsVaultAdapter, ObsidianCliAdapter
from app.knowledge.vault_identity import resolve_obsidian_vault_name

__all__ = [
    "KnowledgeAdapter",
    "KnowledgeCapabilityError",
    "KnowledgeConfigError",
    "KnowledgeDependencyError",
    "KnowledgeError",
    "KnowledgePort",
    "KnowledgeSettings",
    "KnowledgeWriteConflict",
    "NoteLocator",
    "FsVaultAdapter",
    "ObsidianCliAdapter",
    "ObsidianDependencyStatus",
    "SearchHit",
    "WriteReceipt",
    "build_obsidian_advanced_uri",
    "has_valid_vault_scope",
    "load_knowledge_settings",
    "obsidian_dependency_status",
    "resolve_obsidian_vault_name",
    "resolve_knowledge_port",
    "scoped_cli_args",
]
