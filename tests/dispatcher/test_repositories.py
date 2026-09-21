"""Tests for canonical multi-repository configuration."""

from app.dispatcher.repositories import normalize_repositories


def test_normalize_repositories_deduplicates_case_insensitively() -> None:
    assert normalize_repositories(
        (
            "RasmusTho/bifrost",
            "rasmustho/Bifrost",
            "Example/Repository",
            "example/repository",
        )
    ) == ("RasmusTho/bifrost", "Example/Repository")
