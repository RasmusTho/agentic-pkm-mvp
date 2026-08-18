"""Extractors for the Knowledge Acquisition extraction registry (KA-04).

Each module here registers itself with `app.knowledge_acquisition.extraction_registry` on import
and is otherwise independent — the registry (not this package) is the pipeline's one call site.
This slice ships exactly one worked example, `summary` (`summary_extractor.py`); the other worked
examples named in `REFINEMENT_PIPELINE_CONTRACT.md` § Extraction registry (`claims`, `entities`,
`action_items`) are later, separate follow-on issues (explicitly out of scope here).

Importing this package imports every extractor module below, so a pipeline caller only needs
``import app.knowledge_acquisition.extractors`` (or transitively, anything that already imports
it) before resolving extractors by id through
``app.knowledge_acquisition.extraction_registry.run_extractor`` — adding extractor #2 means one
new module plus one import line here, never a change to the registry or the pipeline call site.
"""

from __future__ import annotations

from app.knowledge_acquisition.extractors import claims_extractor as claims_extractor  # noqa: F401
from app.knowledge_acquisition.extractors import summary_extractor as summary_extractor  # noqa: F401
from app.knowledge_acquisition.extractors import synthesis_extractor as synthesis_extractor  # noqa: F401
