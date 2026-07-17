"""Shared service-layer contract assertions for `SourceRegistry` (YSS-01, #3916).

Run identically against the memory backend
(`tests/knowledge_acquisition/test_source_registry.py`) and the Postgres
backend (`tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract`),
per the issue's AC8: "the pg backend passes the same service-layer suite."
Factoring the assertions once here is what makes "same suite" true by
construction rather than by two hand-synced copies drifting apart.

Not a test module itself (no `test_` prefix -- mirrors the
`tests/properties/_machinery.py` shared-helper convention): pytest does not
collect anything here as a test.
"""

from __future__ import annotations

import uuid
from typing import Callable

import pytest

from app.knowledge_acquisition.source_registry import (
    DuplicateBindingError,
    SourceRegistry,
    SourceRegistryValidationError,
    SourceUnsupportedError,
)

RegistryFactory = Callable[[], SourceRegistry]


def _acct() -> str:
    return f"acct-{uuid.uuid4()}"


def assert_round_trip_and_contract_fields(make_registry: RegistryFactory) -> None:
    """AC1: registry rows persist and round-trip with the contract's field set."""
    reg = make_registry()
    acct = _acct()

    binding = reg.register(
        collection_kind="inbox_playlist",
        collection_ref="PLfixture000inbox",
        account_binding_id=acct,
        title="Mimer Inbox",
    )
    fetched = reg.get(binding.binding_id)
    assert fetched is not None

    for obj in (binding, fetched):
        assert isinstance(obj.binding_id, str) and obj.binding_id
        assert obj.account_binding_id == acct
        assert obj.collection_kind == "inbox_playlist"
        assert obj.collection_ref == "PLfixture000inbox"
        assert obj.title == "Mimer Inbox"
        # inbox_playlist rows always start disabled -- only set_inbox activates one.
        assert obj.enabled is False
        assert obj.discovery_mode == "api_poll"
        assert obj.poll_interval_seconds == 180
        assert obj.priority == "high"
        assert obj.cursor == {}
        assert obj.last_attempt_at is None
        assert obj.last_success_at is None
        assert obj.last_error is None
        assert obj.acquisition_policy["mode"] == "acquire_transcript"
        assert obj.acquisition_policy["captions"] is True
        assert obj.acquisition_policy["extractor_ids"] == []
        assert isinstance(obj.acquisition_policy["media"], dict)
        assert obj.acquisition_policy["media"]["enabled"] is False
        assert obj.provenance["origin"] == "manual_add"
        assert obj.provenance["at"]
        assert obj.created_at
        assert obj.updated_at

    assert fetched.binding_id == binding.binding_id
    assert fetched.created_at == binding.created_at

    # A non-inbox, non-playlist-shaped kind gets the conservative discover_only
    # default and starts enabled (no single-enabled-source constraint applies).
    feed = reg.register(
        collection_kind="subscription_feed",
        collection_ref="UCfixture000channel",
        title="Some Channel",
    )
    assert feed.account_binding_id is None
    assert feed.enabled is True
    assert feed.discovery_mode == "rss_poll"
    assert feed.priority == "normal"
    assert feed.poll_interval_seconds == 21600
    assert feed.acquisition_policy["mode"] == "discover_only"


def assert_single_enabled_inbox_and_swap(make_registry: RegistryFactory) -> None:
    """AC2: exactly one enabled inbox per account binding; swap is atomic."""
    reg = make_registry()
    acct = _acct()

    first = reg.register(
        collection_kind="inbox_playlist",
        collection_ref="PLfixtureAAAinbox",
        account_binding_id=acct,
        title="Inbox A",
    )
    second = reg.register(
        collection_kind="inbox_playlist",
        collection_ref="PLfixtureBBBinbox",
        account_binding_id=acct,
        title="Inbox B",
    )
    assert first.enabled is False
    assert second.enabled is False

    activated_first = reg.set_inbox(acct, first.binding_id)
    assert activated_first.enabled is True
    assert reg.get(second.binding_id).enabled is False  # type: ignore[union-attr]

    swapped = reg.set_inbox(acct, second.binding_id)
    assert swapped.enabled is True
    assert reg.get(first.binding_id).enabled is False  # type: ignore[union-attr]

    enabled_inboxes = [
        b for b in reg.list_for_account(acct) if b.collection_kind == "inbox_playlist" and b.enabled
    ]
    assert len(enabled_inboxes) == 1
    assert enabled_inboxes[0].binding_id == second.binding_id

    # Re-activating the already-active inbox is a safe no-op swap, not a second row.
    idempotent = reg.set_inbox(acct, second.binding_id)
    assert idempotent.enabled is True
    still_only_one = [
        b for b in reg.list_for_account(acct) if b.collection_kind == "inbox_playlist" and b.enabled
    ]
    assert len(still_only_one) == 1

    # set_inbox refuses a binding that isn't an inbox_playlist, and a mismatched account.
    owned = reg.register(
        collection_kind="owned_playlist", collection_ref="PLfixtureOWNEDCCC", account_binding_id=acct, title="Owned"
    )
    with pytest.raises(ValueError):
        reg.set_inbox(acct, owned.binding_id)
    other_acct = _acct()
    with pytest.raises(ValueError):
        reg.set_inbox(other_acct, second.binding_id)


def assert_duplicate_binding_refused(make_registry: RegistryFactory) -> None:
    """AC3: duplicate (collection_kind, collection_ref, account_binding_id) is refused."""
    reg = make_registry()
    acct = _acct()

    reg.register(
        collection_kind="owned_playlist", collection_ref="PLfixtureDUPLICATE", account_binding_id=acct, title="First"
    )
    with pytest.raises(DuplicateBindingError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureDUPLICATE",
            account_binding_id=acct,
            title="Second attempt",
        )

    # Same ref, different account -> allowed (the triple includes account_binding_id).
    other_acct = _acct()
    allowed = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureDUPLICATE",
        account_binding_id=other_acct,
        title="Different account",
    )
    assert allowed.account_binding_id == other_acct

    # Same ref, different kind, same account -> allowed (the triple includes kind).
    different_kind = reg.register(
        collection_kind="public_playlist",
        collection_ref="PLfixtureDUPLICATE",
        account_binding_id=acct,
        title="Different kind",
    )
    assert different_kind.collection_kind == "public_playlist"


def assert_watch_later_and_history_refused(make_registry: RegistryFactory) -> None:
    """AC4: Watch Later / Watch History refused as source_unsupported with legible copy."""
    reg = make_registry()
    acct = _acct()

    for ref, needle in (("WL", "Watch Later"), ("HL", "Watch History")):
        with pytest.raises(SourceUnsupportedError) as excinfo:
            reg.register(
                collection_kind="owned_playlist", collection_ref=ref, account_binding_id=acct, title="Should fail"
            )
        assert excinfo.value.reason_code == "source_unsupported"
        assert needle in str(excinfo.value)
        assert "api" in str(excinfo.value).lower()

    # The refusal fires regardless of the requested collection_kind.
    with pytest.raises(SourceUnsupportedError):
        reg.register(
            collection_kind="inbox_playlist", collection_ref="WL", account_binding_id=acct, title="Should also fail"
        )

    # No row was left behind by any refused attempt.
    assert reg.list_for_account(acct) == ()


def assert_title_rename_preserves_binding(make_registry: RegistryFactory) -> None:
    """AC5: renaming title changes no identity, cursor, or policy; binding survives."""
    reg = make_registry()
    acct = _acct()
    custom_policy = {"mode": "candidate_metadata_only", "captions": False}

    binding = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureRENAMEME",
        account_binding_id=acct,
        title="Original Title",
        acquisition_policy=custom_policy,
    )
    renamed = reg.rename(binding.binding_id, "Brand New Title")

    assert renamed.title == "Brand New Title"
    assert renamed.binding_id == binding.binding_id
    assert renamed.collection_kind == binding.collection_kind
    assert renamed.collection_ref == binding.collection_ref
    assert renamed.account_binding_id == binding.account_binding_id
    assert renamed.enabled == binding.enabled
    assert renamed.discovery_mode == binding.discovery_mode
    assert renamed.poll_interval_seconds == binding.poll_interval_seconds
    assert renamed.priority == binding.priority
    assert renamed.cursor == binding.cursor
    assert renamed.acquisition_policy == binding.acquisition_policy
    assert renamed.provenance == binding.provenance
    assert renamed.created_at == binding.created_at

    fetched = reg.get(binding.binding_id)
    assert fetched is not None
    assert fetched.title == "Brand New Title"

    with pytest.raises(SourceRegistryValidationError):
        reg.rename(binding.binding_id, "")


def assert_invalid_interval_and_policy_fail_loud(make_registry: RegistryFactory) -> None:
    """AC6: poll-interval/policy validation reject bad values loudly; defaults still apply."""
    reg = make_registry()
    acct = _acct()

    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureBADINTLOW",
            account_binding_id=acct,
            title="Bad interval low",
            poll_interval_seconds=-5,
        )
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureBADINTHIGH",
            account_binding_id=acct,
            title="Bad interval high",
            poll_interval_seconds=999_999_999,
        )
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureBADMODE",
            account_binding_id=acct,
            title="Bad mode",
            acquisition_policy={"mode": "not_a_real_mode"},
        )
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureBADKEY",
            account_binding_id=acct,
            title="Unknown policy key",
            acquisition_policy={"totally_bogus_key": True},
        )
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureBADMEDIA",
            account_binding_id=acct,
            title="Bad media shape",
            acquisition_policy={"media": {"enabled": "not-a-bool"}},
        )
    # bool is an int subclass, while NaN/+/-infinity would serialize in the
    # memory backend but fail differently in PostgreSQL jsonb. Validation must
    # reject each at the shared service boundary.
    for media_key in ("min_free_gb", "retention_days"):
        for bad_number in (True, float("nan"), float("inf"), float("-inf")):
            with pytest.raises(SourceRegistryValidationError):
                reg.register(
                    collection_kind="owned_playlist",
                    collection_ref=f"PLfixtureBADNUMBER{media_key}{bad_number!r}",
                    account_binding_id=acct,
                    title="Invalid media number",
                    acquisition_policy={"media": {media_key: bad_number}},
                )
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="not_a_real_kind",
            collection_ref="PLfixtureBADKIND",
            account_binding_id=acct,
            title="Bad kind",
        )

    # None of the rejected calls left a row behind.
    assert reg.list_for_account(acct) == ()

    # Omitted fields still resolve to the contract defaults for this kind.
    ok = reg.register(
        collection_kind="owned_playlist", collection_ref="PLfixtureGOODDEFAULT", account_binding_id=acct, title="Fine"
    )
    assert ok.poll_interval_seconds == 3600
    assert ok.acquisition_policy["mode"] == "acquire_transcript"
    assert ok.acquisition_policy["media"]["enabled"] is False

    # A valid boundary value (exactly the lower bound) is accepted, not rejected.
    boundary = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureBOUNDARYOK",
        account_binding_id=acct,
        title="Boundary",
        poll_interval_seconds=60,
    )
    assert boundary.poll_interval_seconds == 60


def assert_memory_json_isolation(make_registry: RegistryFactory) -> None:
    """Returned nested JSON cannot mutate the memory store out of band.

    The same assertion runs on Postgres, where jsonb deserialization already
    yields fresh values, and documents the identical-backend contract.
    """
    reg = make_registry()
    acct = _acct()
    binding = reg.register(
        collection_kind="inbox_playlist",
        collection_ref="PLfixtureISOLATION",
        account_binding_id=acct,
        title="Isolation",
        acquisition_policy={"extractor_ids": ["summary"], "media": {"min_free_gb": 4}},
        provenance={"origin": "manual_add", "detail": {"reason": "test"}},
    )

    # Insert return: mutating it must not alter what was stored.
    binding.cursor["page"] = {"token": "caller"}
    binding.acquisition_policy["extractor_ids"].append("caller")
    binding.provenance["detail"]["reason"] = "caller"
    stored = reg.get(binding.binding_id)
    assert stored is not None
    assert stored.cursor == {}
    assert stored.acquisition_policy["extractor_ids"] == ["summary"]
    assert stored.provenance["detail"]["reason"] == "test"

    # Get and list returns carry the same isolation.
    stored.cursor["page"] = {"token": "get"}
    listed = reg.list_for_account(acct)[0]
    listed.acquisition_policy["extractor_ids"].append("list")
    listed.provenance["detail"]["reason"] = "list"
    assert reg.get(binding.binding_id).cursor == {}  # type: ignore[union-attr]
    assert reg.get(binding.binding_id).acquisition_policy["extractor_ids"] == ["summary"]  # type: ignore[union-attr]
    assert reg.get(binding.binding_id).provenance["detail"]["reason"] == "test"  # type: ignore[union-attr]

    # Update returns must be isolated too.
    renamed = reg.rename(binding.binding_id, "Renamed")
    renamed.cursor["page"] = {"token": "rename"}
    renamed.acquisition_policy["extractor_ids"].append("rename")
    renamed.provenance["detail"]["reason"] = "rename"
    final = reg.get(binding.binding_id)
    assert final is not None
    assert final.title == "Renamed"
    assert final.cursor == {}
    assert final.acquisition_policy["extractor_ids"] == ["summary"]
    assert final.provenance["detail"]["reason"] == "test"


ALL_CONTRACT_ASSERTIONS: tuple[Callable[[RegistryFactory], None], ...] = (
    assert_round_trip_and_contract_fields,
    assert_single_enabled_inbox_and_swap,
    assert_duplicate_binding_refused,
    assert_watch_later_and_history_refused,
    assert_title_rename_preserves_binding,
    assert_invalid_interval_and_policy_fail_loud,
    assert_memory_json_isolation,
)
