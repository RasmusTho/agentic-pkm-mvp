"""v6.x Knowledge Compilation and Memory Curation runtime foundation (parent #1533).

Slice #1534 ships the pure runtime artifact contracts
(``app.knowledge_compilation.runtime_artifacts``); slice #1535 adds the deterministic
proposal builders (``app.knowledge_compilation.proposal_builders``).
"""

from app.knowledge_compilation.proposal_builders import (
    ProposalContext,
    build_compilation_draft,
    build_curation_candidate,
)
from app.knowledge_compilation.runtime_artifacts import (
    AGENT_MEMORY_CLASS,
    BRIDGE_ARTIFACT_CLASSES,
    COMPILATION_DRAFT_CLASS,
    CURATION_CANDIDATE_CLASS,
    REORIENTATION_PACKET_CLASS,
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    CurationCandidate,
    GeneratedArtifact,
    ReorientationPacket,
    SourceRef,
    TrustVerb,
)

__all__ = [
    "AGENT_MEMORY_CLASS",
    "BRIDGE_ARTIFACT_CLASSES",
    "COMPILATION_DRAFT_CLASS",
    "CURATION_CANDIDATE_CLASS",
    "REORIENTATION_PACKET_CLASS",
    "AdmissionState",
    "CompilationDraft",
    "ContextAuthorityLimits",
    "CurationCandidate",
    "GeneratedArtifact",
    "ProposalContext",
    "ReorientationPacket",
    "SourceRef",
    "TrustVerb",
    "build_compilation_draft",
    "build_curation_candidate",
]
