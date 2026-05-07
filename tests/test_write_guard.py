import pytest

from app.write_guard import WriteGuard, WritesBlockedError


@pytest.mark.parametrize("state", ["safe_mode", "unhealthy"])
def test_assert_writes_allowed_blocks_known_blocked_states(state: str) -> None:
    guard = WriteGuard(lambda: {"state": state, "reason": "maintenance"})
    with pytest.raises(WritesBlockedError) as exc:
        guard.assert_writes_allowed("promotion frontmatter")
    assert exc.value.state == state
    assert exc.value.reason == "maintenance"
    assert exc.value.action == "promotion frontmatter"
    assert "promotion frontmatter" in str(exc.value)
    assert state in str(exc.value)
    assert "maintenance" in str(exc.value)


@pytest.mark.parametrize("state", ["running", "degraded"])
def test_assert_writes_allowed_allows_current_non_blocked_policy(state: str) -> None:
    guard = WriteGuard(lambda: {"state": state, "reason": "ok"})
    guard.assert_writes_allowed("panel runtimes")

