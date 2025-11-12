import pytest

pytest.skip(
    "legacy pre-v4.4 capture_ingest contract; CLI is now ObjectStore-backed and "
    "emits Outbox events atomically. This test is kept for historical reference.",
    allow_module_level=True,
)
