"""YSS-01 source registry service-layer contract (#3916).

Named tests map 1:1 to the issue's Acceptance Criteria. The service-layer
integrity rules are asserted here on the memory backend; the identical
behavior on the Postgres backend runs through
``tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract``
(marked ``pg``), which reuses :func:`run_service_layer_contract` from this
module so the two backends cannot drift apart silently.
"""

from __future__ import annotations

import uuid

import pytest

from app.knowledge_acquisition.source_registry import (
    DuplicateBindingError,
    RegistryValidationError,
    SourceRegistry,
    SourceUnsupportedError,
    UnknownBindingError,
    reset_memory_source_registry,
)

pytestmark = pytest.mark.not_pg


_CONTRACT_FIELDS = {
    "binding_id",
    "account_binding_id",
    "collection_kind",
    "collection_ref",
    "title",
    "enabled",
    "discovery_mode",
    "poll_interval_seconds",
    "priority",
    "cursor",
    "last_attempt_at",
    "last_success_at",
    "last_error",
    "acquisition_policy",
    "provenance",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_memory_source_registry()
    yield
    reset_memory_source_registry()


@pytest.fixture()
def registry() -> SourceRegistry:
    return SourceRegistry.for_runtime()


def _ref(prefix: str = "PL") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def test_registry_round_trip_memory_and_contract_fields(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())
    inbox_ref = _ref()
    binding = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=inbox_ref,
        account_binding_id=account,
        title="Inbox",
        provenance_origin="user_pick",
        provenance_detail="setup flow",
    )
    fetched = registry.get(binding.binding_id)
    assert fetched == binding
    assert set(type(fetched).__dataclass_fields__) == _CONTRACT_FIELDS

    assert fetched.collection_kind == "inbox_playlist"
    assert fetched.collection_ref == inbox_ref
    assert fetched.account_binding_id == account
    assert fetched.enabled is True
    assert fetched.discovery_mode == "api_poll"
    assert fetched.priority == "high"
    assert fetched.poll_interval_seconds is None
    assert fetched.cursor == {}
    assert fetched.last_attempt_at is None
    assert fetched.last_success_at is None
    assert fetched.last_error is None
    assert fetched.acquisition_policy["mode"] == "acquire_transcript"
    assert fetched.acquisition_policy["policy_version"] == 1
    assert fetched.provenance["origin"] == "user_pick"
    assert fetched.provenance["detail"] == "setup flow"
    assert fetched.created_at is not None and fetched.updated_at is not None

    # An account-less source (RSS/public) round-trips with its own defaults.
    feed = registry.register(
        collection_kind="subscription_feed",
        collection_ref=_ref("UC"),
        provenance_origin="takeout_import",
    )
    fetched_feed = registry.get(feed.binding_id)
    assert fetched_feed.account_binding_id is None
    assert fetched_feed.discovery_mode == "rss_poll"
    assert fetched_feed.priority == "normal"
    assert fetched_feed.acquisition_policy["mode"] == "discover_only"

    # State mutators round-trip through the same row.
    registry.update_cursor(binding.binding_id, {"frontier": ["item-1"]})
    registry.record_attempt(binding.binding_id)
    registry.record_error(binding.binding_id, reason_code="network_error", detail="timeout")
    row = registry.get(binding.binding_id)
    assert row.cursor == {"frontier": ["item-1"]}
    assert row.last_attempt_at is not None
    assert row.last_error is not None and row.last_error["reason_code"] == "network_error"
    registry.record_success(binding.binding_id)
    row = registry.get(binding.binding_id)
    assert row.last_success_at is not None
    assert row.last_error is None


def test_single_enabled_inbox_enforced_and_swap_atomic(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())
    first = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
    )

    # A second enabled inbox is impossible.
    with pytest.raises(RegistryValidationError, match="set_inbox"):
        registry.register(
            collection_kind="inbox_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
        )

    # A disabled second inbox may exist; the swap enables it atomically.
    second = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
        enabled=False,
    )
    swapped = registry.set_inbox(account, second.binding_id)
    assert swapped.enabled is True
    enabled_inboxes = registry.list(
        account_binding_id=account, collection_kind="inbox_playlist", enabled=True
    )
    assert [row.binding_id for row in enabled_inboxes] == [second.binding_id]
    assert registry.get(first.binding_id).enabled is False

    # Re-enabling the old inbox directly is refused; the swap is the only path.
    with pytest.raises(RegistryValidationError, match="set_inbox"):
        registry.set_enabled(first.binding_id, True)

    # A failed swap changes nothing.
    with pytest.raises(UnknownBindingError):
        registry.set_inbox(account, str(uuid.uuid4()))
    enabled_after = registry.list(
        account_binding_id=account, collection_kind="inbox_playlist", enabled=True
    )
    assert [row.binding_id for row in enabled_after] == [second.binding_id]

    # Swap target must be an inbox playlist of the same account.
    other = registry.register(
        collection_kind="owned_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
    )
    with pytest.raises(RegistryValidationError, match="not an inbox"):
        registry.set_inbox(account, other.binding_id)
    foreign_account = str(uuid.uuid4())
    foreign = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=_ref(),
        account_binding_id=foreign_account,
    )
    with pytest.raises(RegistryValidationError, match="different account"):
        registry.set_inbox(account, foreign.binding_id)

    # Registering an inbox without an account binding is refused.
    with pytest.raises(RegistryValidationError, match="account binding"):
        registry.register(collection_kind="inbox_playlist", collection_ref=_ref())


def test_duplicate_binding_refused(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())
    ref = _ref()
    registry.register(
        collection_kind="owned_playlist", collection_ref=ref, account_binding_id=account
    )
    with pytest.raises(DuplicateBindingError):
        registry.register(
            collection_kind="owned_playlist", collection_ref=ref, account_binding_id=account
        )

    # The triple includes the (nullable) account: no-account duplicates are
    # refused too, while another account may bind the same collection.
    public_ref = _ref()
    registry.register(collection_kind="public_playlist", collection_ref=public_ref)
    with pytest.raises(DuplicateBindingError):
        registry.register(collection_kind="public_playlist", collection_ref=public_ref)
    registry.register(
        collection_kind="owned_playlist",
        collection_ref=ref,
        account_binding_id=str(uuid.uuid4()),
    )


def test_watch_later_and_history_refused_unsupported(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())
    for special in ("WL", "HL"):
        with pytest.raises(SourceUnsupportedError) as excinfo:
            registry.register(
                collection_kind="owned_playlist",
                collection_ref=special,
                account_binding_id=account,
            )
        assert excinfo.value.reason_code == "source_unsupported"
        message = str(excinfo.value)
        assert "Data API" in message
        assert "cookies" in message
    assert registry.list(account_binding_id=account) == []


def test_title_rename_does_not_break_binding(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())
    ref = _ref()
    binding = registry.register(
        collection_kind="owned_playlist",
        collection_ref=ref,
        account_binding_id=account,
        title="Before rename",
    )
    registry.update_cursor(binding.binding_id, {"frontier": ["v-1", "v-2"]})
    registry.set_policy(binding.binding_id, {"mode": "candidate_metadata_only"})

    renamed = registry.rename(binding.binding_id, "After rename")
    assert renamed.binding_id == binding.binding_id
    assert renamed.title == "After rename"
    assert renamed.collection_ref == ref
    assert renamed.cursor == {"frontier": ["v-1", "v-2"]}
    assert renamed.acquisition_policy["mode"] == "candidate_metadata_only"
    assert renamed.acquisition_policy["policy_version"] == 2

    # Identity survives: the triple is still bound, so re-registration is
    # still a duplicate regardless of the display title.
    with pytest.raises(DuplicateBindingError):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=ref,
            account_binding_id=account,
            title="A third title",
        )


def test_invalid_interval_and_policy_fail_loud(registry: SourceRegistry) -> None:
    account = str(uuid.uuid4())

    with pytest.raises(RegistryValidationError, match=r"\[60, 604800\]"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            poll_interval_seconds=30,
        )
    with pytest.raises(RegistryValidationError, match=r"\[60, 604800\]"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            poll_interval_seconds=10_000_000,
        )
    with pytest.raises(RegistryValidationError, match="integer"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            poll_interval_seconds="180",  # type: ignore[arg-type]
        )

    with pytest.raises(RegistryValidationError, match="cookie_mode"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            acquisition_policy={"mode": "cookie_mode"},
        )
    with pytest.raises(RegistryValidationError, match="unknown keys"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            acquisition_policy={"mode": "discover_only", "surprise": True},
        )
    with pytest.raises(RegistryValidationError, match="media"):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            acquisition_policy={"media": {"enabled": "yes"}},
        )
    with pytest.raises(RegistryValidationError, match="unknown collection_kind"):
        registry.register(
            collection_kind="watch_later",
            collection_ref=_ref(),
            account_binding_id=account,
        )

    # Nothing was applied silently.
    assert registry.list(account_binding_id=account) == []

    # Omitted values apply the kind defaults (never a silent bad apply).
    playlist = registry.register(
        collection_kind="owned_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
    )
    assert playlist.acquisition_policy == {
        "mode": "acquire_transcript",
        "extractor_ids": [],
        "captions": True,
        "media": {"enabled": False},
        "policy_version": 1,
    }
    feed = registry.register(collection_kind="subscription_feed", collection_ref=_ref("UC"))
    assert feed.acquisition_policy["mode"] == "discover_only"

    # Post-registration mutators validate just as loudly.
    with pytest.raises(RegistryValidationError):
        registry.update_poll_interval(playlist.binding_id, 5)
    with pytest.raises(RegistryValidationError):
        registry.set_policy(playlist.binding_id, {"mode": "definitely_not_a_mode"})


def run_service_layer_contract(registry: SourceRegistry) -> None:
    """Backend-agnostic service-layer contract, reused by the pg suite.

    Uses per-run unique accounts/refs so it is safe against a persistent
    Postgres database (rows are never deleted; the registry has no delete
    API by design).
    """
    account = str(uuid.uuid4())

    # Round-trip with the contract field set.
    inbox = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
        title="Inbox",
        provenance_origin="user_pick",
    )
    fetched = registry.get(inbox.binding_id)
    assert set(type(fetched).__dataclass_fields__) == _CONTRACT_FIELDS
    assert fetched.binding_id == inbox.binding_id
    assert fetched.enabled is True
    assert fetched.priority == "high"
    assert fetched.acquisition_policy["mode"] == "acquire_transcript"
    assert fetched.cursor == {}

    # Duplicate triple refused.
    with pytest.raises(DuplicateBindingError):
        registry.register(
            collection_kind="inbox_playlist",
            collection_ref=inbox.collection_ref,
            account_binding_id=account,
            enabled=False,
        )

    # Watch Later / Watch History refused as source_unsupported.
    with pytest.raises(SourceUnsupportedError):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref="WL",
            account_binding_id=account,
        )

    # Single enabled inbox + atomic swap.
    with pytest.raises(RegistryValidationError):
        registry.register(
            collection_kind="inbox_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
        )
    second = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=_ref(),
        account_binding_id=account,
        enabled=False,
    )
    registry.set_inbox(account, second.binding_id)
    enabled_rows = registry.list(
        account_binding_id=account, collection_kind="inbox_playlist", enabled=True
    )
    assert [row.binding_id for row in enabled_rows] == [second.binding_id]

    # Rename is display-only; state survives.
    registry.update_cursor(second.binding_id, {"frontier": ["item-1"]})
    renamed = registry.rename(second.binding_id, "Renamed inbox")
    assert renamed.cursor == {"frontier": ["item-1"]}
    assert renamed.enabled is True

    # Validation stays loud on this backend too.
    with pytest.raises(RegistryValidationError):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            poll_interval_seconds=1,
        )
    with pytest.raises(RegistryValidationError):
        registry.register(
            collection_kind="owned_playlist",
            collection_ref=_ref(),
            account_binding_id=account,
            acquisition_policy={"mode": "bogus"},
        )
