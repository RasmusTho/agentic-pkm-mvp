from app.retrieval.context_cache import context_cache_identity
from tests.retrieval.test_active_context_cache_isolation import _snapshot


def test_two_sessions_use_distinct_vaults_without_cross_talk() -> None:
    left = _snapshot(context_id="session-a")
    right = _snapshot(context_id="session-b")
    assert left.binding_ids == right.binding_ids
    assert context_cache_identity(left, settings_bundle_digest="same").key != context_cache_identity(right, settings_bundle_digest="same").key


def test_authority_change_cannot_cross_read_effect_window() -> None:
    before = _snapshot(authorization_epoch="epoch-a")
    after = _snapshot(authorization_epoch="epoch-b")
    assert context_cache_identity(before, settings_bundle_digest="same").key != context_cache_identity(after, settings_bundle_digest="same").key
