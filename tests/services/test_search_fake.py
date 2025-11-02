import pytest
pytest.skip(
    "legacy pre-v4.4 search/index bootstrap. Indexing is now driven by Outbox "
    "events (`ingest.object.created`) and VectorIndex, not manual bootstrap(). "
    "Will be replaced by Indexer agent contract tests.",
    allow_module_level=True,
)
