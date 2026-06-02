"""v6.x Knowledge Compilation and Memory Curation runtime foundation (parent #1533).

Slice #1534 ships the pure runtime artifact contracts
(``app.knowledge_compilation.runtime_artifacts``); slice #1535 adds the deterministic
proposal builders (``app.knowledge_compilation.proposal_builders``); slice #1536 adds
read-only reorientation packet assembly (``app.knowledge_compilation.reorientation_packet``).
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
from app.knowledge_compilation.reorientation_packet import (
    PacketAssemblyError,
    assemble_reorientation_packet_from_bundle,
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
    "PacketAssemblyError",
    "ProposalContext",
    "ReorientationPacket",
    "SourceRef",
    "TrustVerb",
    "assemble_reorientation_packet_from_bundle",
    "build_compilation_draft",
    "build_curation_candidate",
]
