from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[2] / "app/api/request_active_context.py").read_text()


def test_scoped_write_is_sealed_until_mvr05c() -> None:
    assert "capability_not_ready" in SOURCE
    assert "mvr05c_scoped_write" in SOURCE


def test_migrated_client_write_precondition_prevents_cross_client_compatibility_redirect() -> None:
    assert "X-Active-Context-Session" in SOURCE


def test_migrated_write_route_rejects_stripped_precondition_without_legacy_downgrade() -> None:
    assert "X-Active-Context-Override" in SOURCE
