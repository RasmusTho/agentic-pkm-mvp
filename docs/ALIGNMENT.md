State: Legacy / historical; superseded by SoT v4.10.
# Alignment Guide (legacy)

This document reflects historical “Second-Brain” requirements and runtime surfaces that predate the Reality-MVP stack. It is retained for reference only and is not an active source of truth.

Key divergences from Reality-MVP:
- Describes legacy endpoints (`/items`, `/context`, legacy ingest/search) and an agent supervisor loop that are no longer primary surfaces.
- Proposes frontmatter/system_intent fields, reflection analytics, and categorization pipelines that are not implemented in v4.10.
- Refers to chunking/categorization/promotion flows tied to legacy Postgres schemas (`objects`, `embeddings`, `chunks`, `sets`) rather than the current Store abstraction.

Use current docs instead:
- Runtime design and flows: `docs/ARCHITECTURE.md`, `docs/SYSTEM_DESIGN_v4.10.md`, `docs/HUMAN-FLOWS.md`, `docs/INGEST.md`, `docs/RETRIEVAL.md`, `docs/DATA_MODEL.md`.
- Frontmatter rules: `docs/FRONTMATTER.md`.
- Promotion/projector: `docs/PROJECTOR.md`, `docs/STATUS.md`.

If any future work from this legacy guide is revived, document it under “Planned” sections in the SoT docs and gate behind flags/tests.
