import pytest
pytest.skip(
    "legacy pre-v4.4 capture_ingest contract; CLI is now ObjectStore-backed "
    "and emits Outbox events atomically. This e2e test will be replaced by a "
    "new ingestion→outbox→indexer flow test.",
    allow_module_level=True,
)
