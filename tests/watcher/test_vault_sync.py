import pytest
pytest.skip(
    "legacy vault_sync bootstrap flow. Vault capture is now handled by "
    "capture_ingest writing both Obsidian file and ObjectStore+Outbox in one "
    "transaction. Will be replaced by Promotion Agent lifecycle tests.",
    allow_module_level=True,
)
