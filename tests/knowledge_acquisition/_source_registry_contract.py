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
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Callable

import pytest

from app.knowledge_acquisition.source_registry import (
    DuplicateBindingError,
    InboxAlreadySelectedError,
    SourceBinding,
    SourceRegistry,
    SourceRegistryValidationError,
    SourceUnsupportedError,
)

RegistryFactory = Callable[[], SourceRegistry]


def _acct() -> str:
    return str(uuid.uuid4())


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


def assert_v1_inbox_selection_is_atomic(make_registry: RegistryFactory) -> None:
    """Concurrent V1 selections admit one playlist and refuse the other."""
    reg = make_registry()
    acct = _acct()
    first = reg.register(
        collection_kind="inbox_playlist",
        collection_ref=f"PLfixtureV1A{uuid.uuid4().hex}",
        account_binding_id=acct,
        title="V1 Inbox A",
    )
    second = reg.register(
        collection_kind="inbox_playlist",
        collection_ref=f"PLfixtureV1B{uuid.uuid4().hex}",
        account_binding_id=acct,
        title="V1 Inbox B",
    )
    barrier = Barrier(3)

    def _select(binding_id: str) -> SourceBinding | InboxAlreadySelectedError:
        barrier.wait()
        try:
            return reg.select_inbox_if_absent_or_same(acct, binding_id)
        except InboxAlreadySelectedError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_select, first.binding_id),
            pool.submit(_select, second.binding_id),
        ]
        barrier.wait()
        outcomes = [future.result(timeout=10) for future in futures]

    selected = [item for item in outcomes if isinstance(item, SourceBinding)]
    refused = [
        item for item in outcomes if isinstance(item, InboxAlreadySelectedError)
    ]
    assert len(selected) == 1
    assert len(refused) == 1
    enabled = [
        row
        for row in reg.list_for_account(acct)
        if row.collection_kind == "inbox_playlist" and row.enabled
    ]
    assert enabled == selected
    same = reg.select_inbox_if_absent_or_same(acct, selected[0].binding_id)
    assert same == selected[0]

    # The generic administrative operation deliberately retains swap semantics.
    loser_id = second.binding_id if selected[0].binding_id == first.binding_id else first.binding_id
    swapped = reg.set_inbox(acct, loser_id)
    assert swapped.binding_id == loser_id
    assert swapped.enabled is True


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


def assert_account_binding_nullability_by_kind(make_registry: RegistryFactory) -> None:
    """Authenticated collections require an account; RSS/public collections do not."""
    reg = make_registry()
    before_ids = {binding.binding_id for binding in reg.list_all()}

    for kind, collection_ref in (
        ("inbox_playlist", "PLfixtureNOACCOUNTINBOX"),
        ("owned_playlist", "PLfixtureNOACCOUNTOWNED"),
        ("liked_videos", "LLfixtureNOACCOUNTLIKED"),
    ):
        with pytest.raises(SourceRegistryValidationError, match="account_binding_id is required"):
            reg.register(
                collection_kind=kind,
                collection_ref=collection_ref,
                title="Authenticated collection without account",
            )
    assert {binding.binding_id for binding in reg.list_all()} == before_ids

    for kind, collection_ref in (
        ("public_playlist", "PLfixturePUBLICNOACCOUNT"),
        ("subscription_feed", "UCfixtureRSSNOACCOUNT"),
    ):
        binding = reg.register(
            collection_kind=kind,
            collection_ref=collection_ref,
            title="Unauthenticated collection",
        )
        assert binding.account_binding_id is None


def assert_account_binding_uuid_contract(make_registry: RegistryFactory) -> None:
    """Present account bindings are canonical UUIDs; SQL's NULL sentinel is reserved."""
    reg = make_registry()
    before_ids = {binding.binding_id for binding in reg.list_all()}

    for index, invalid in enumerate(("", "not-a-uuid", "__none__")):
        with pytest.raises(SourceRegistryValidationError, match="account_binding_id"):
            reg.register(
                collection_kind="owned_playlist",
                collection_ref=f"PLfixtureINVALIDACCOUNT{index}",
                account_binding_id=invalid,
                title="Invalid account binding",
            )
    assert {binding.binding_id for binding in reg.list_all()} == before_ids

    canonical = str(uuid.uuid4())
    noncanonical = canonical.upper()
    binding = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureNORMALIZEDACCOUNT",
        account_binding_id=noncanonical,
        title="Normalized account binding",
    )
    assert binding.account_binding_id == canonical
    assert reg.list_for_account(noncanonical) == (binding,)


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
    # Omission means "use the default"; an explicit media field must always
    # be the contract's object shape. This shared service-path assertion runs
    # against both memory and Postgres backends.
    for bad_media in (None, ["not-an-object"]):
        with pytest.raises(SourceRegistryValidationError, match="media must be an object"):
            reg.register(
                collection_kind="owned_playlist",
                collection_ref=f"PLfixtureBADMEDIASHAPE{bad_media!r}",
                account_binding_id=acct,
                title="Bad media shape",
                acquisition_policy={"media": bad_media},
            )
    # bool is an int subclass, while NaN/+/-infinity would serialize in the
    # memory backend but fail differently in PostgreSQL jsonb, and negative
    # bounds make free-space protection / retention lifecycle meaningless.
    # Validation must reject each at the shared service boundary.
    for media_key in ("min_free_gb", "retention_days"):
        for bad_number in (True, float("nan"), float("inf"), float("-inf"), -1, -0.5):
            with pytest.raises(SourceRegistryValidationError):
                reg.register(
                    collection_kind="owned_playlist",
                    collection_ref=f"PLfixtureBADNUMBER{media_key}{bad_number!r}",
                    account_binding_id=acct,
                    title="Invalid media number",
                    acquisition_policy={"media": {media_key: bad_number}},
                )
    # Zero-day retention has no lifecycle meaning either (delete-immediately
    # is not a retention policy; "unset" is null).
    with pytest.raises(SourceRegistryValidationError):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureZERORETENTION",
            account_binding_id=acct,
            title="Zero retention",
            acquisition_policy={"media": {"retention_days": 0}},
        )
    # Strings PostgreSQL cannot store (NUL in text columns and jsonb,
    # unpaired surrogates) are refused identically on both backends for every
    # string field, not only provenance (round-B review finding).
    with pytest.raises(SourceRegistryValidationError, match="title"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureNULTITLE",
            account_binding_id=acct,
            title="a\x00b",
        )
    with pytest.raises(SourceRegistryValidationError, match="title"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureSURROGATETITLE",
            account_binding_id=acct,
            title="\ud800",
        )
    with pytest.raises(SourceRegistryValidationError, match="collection_ref"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PL\x00ref",
            account_binding_id=acct,
            title="NUL ref",
        )
    with pytest.raises(SourceRegistryValidationError, match="extractor_ids"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureNULEXTRACTOR",
            account_binding_id=acct,
            title="NUL extractor",
            acquisition_policy={"extractor_ids": ["ex\x00tract"]},
        )
    with pytest.raises(SourceRegistryValidationError, match="max_quality"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureNULQUALITY",
            account_binding_id=acct,
            title="NUL quality",
            acquisition_policy={"media": {"max_quality": "q\x00"}},
        )
    # Unhashable values in enum-checked fields raise the documented
    # validation error, never a raw TypeError (round-B review finding).
    with pytest.raises(SourceRegistryValidationError, match="mode"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureLISTMODE",
            account_binding_id=acct,
            title="List mode",
            acquisition_policy={"mode": ["acquire_transcript"]},
        )
    with pytest.raises(SourceRegistryValidationError, match="origin"):
        reg.register(
            collection_kind="owned_playlist",
            collection_ref="PLfixtureLISTORIGIN",
            account_binding_id=acct,
            title="List origin",
            provenance={"origin": ["user_pick"]},
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

    # Media-policy lower bounds are inclusive: 0 GB free-space floor ("no
    # floor") and 1-day retention are both valid explicit values.
    media_boundary = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureMEDIABOUNDARYOK",
        account_binding_id=acct,
        title="Media boundary",
        acquisition_policy={"media": {"min_free_gb": 0, "retention_days": 1}},
    )
    assert media_boundary.acquisition_policy["media"]["min_free_gb"] == 0
    assert media_boundary.acquisition_policy["media"]["retention_days"] == 1


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


def assert_provenance_is_strict_portable_json(make_registry: RegistryFactory) -> None:
    """Provenance validation is identical before memory/Postgres selection."""
    reg = make_registry()
    acct = _acct()
    before_ids = {binding.binding_id for binding in reg.list_all()}
    invalid_provenance = (
        {"origin": "manual_add", "detail": {"bad": object()}},
        {"origin": "manual_add", "detail": {"bad": float("nan")}},
        {"origin": "manual_add", "detail": {"bad": [float("inf")]}},
        {"origin": "manual_add", "detail": {"bad": ("tuple",)}},
        {"origin": "manual_add", "detail": {1: "non-string key"}},
        {"origin": "manual_add", "unexpected": True},
        {"origin": "manual_add", "at": object()},
        # ``at`` is the provenance timestamp: arbitrary strings and naive
        # (offset-less) timestamps cannot be ordered or audited.
        {"origin": "manual_add", "at": "not-a-timestamp"},
        {"origin": "manual_add", "at": "2026-07-18T10:00:00"},
        {"origin": "manual_add", "at": ""},
        # Strings PostgreSQL jsonb cannot store must be refused before
        # backend selection: NUL and unpaired surrogates.
        {"origin": "manual_add", "detail": {"text": "a\x00b"}},
        {"origin": "manual_add", "detail": {"text": "\ud800"}},
        {"origin": "manual_add", "detail": {"a\x00key": "value"}},
    )
    for index, provenance in enumerate(invalid_provenance):
        with pytest.raises(SourceRegistryValidationError, match="provenance"):
            reg.register(
                collection_kind="owned_playlist",
                collection_ref=f"PLfixtureBADPROVENANCE{index}",
                account_binding_id=acct,
                title="Invalid provenance",
                provenance=provenance,
            )
    assert {binding.binding_id for binding in reg.list_all()} == before_ids

    # Accepted timestamps are canonicalized to one auditable form: UTC with
    # an explicit offset, regardless of the offset the caller supplied.
    canonical = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureCANONICALAT",
        account_binding_id=acct,
        title="Canonical at",
        provenance={"origin": "user_pick", "at": "2026-07-18T10:00:00+02:00"},
    )
    assert canonical.provenance["at"] == "2026-07-18T08:00:00+00:00"
    zulu = reg.register(
        collection_kind="owned_playlist",
        collection_ref="PLfixtureZULUAT",
        account_binding_id=acct,
        title="Zulu at",
        provenance={"origin": "user_pick", "at": "2026-07-18T08:00:00Z"},
    )
    assert zulu.provenance["at"] == "2026-07-18T08:00:00+00:00"


def assert_inbox_poll_outcomes(make_registry: RegistryFactory) -> None:
    """V1 poll state publishes success or degradation without cursor ambiguity."""
    reg = make_registry()
    binding = reg.register(
        collection_kind="inbox_playlist",
        collection_ref=f"PLfixturePOLL{uuid.uuid4().hex}",
        account_binding_id=_acct(),
        title="Poll state contract",
    )
    binding = reg.set_inbox(binding.account_binding_id, binding.binding_id)

    failed = reg.record_poll_failure(
        binding.binding_id,
        reason_code="network_error",
        detail="safe detail",
    )
    assert failed.cursor == {}
    assert failed.last_attempt_at is not None
    assert failed.last_success_at is None
    assert failed.last_error is not None
    assert failed.last_error["reason_code"] == "network_error"

    succeeded = reg.record_poll_success(
        binding.binding_id,
        cursor={"known_playlist_item_ids": ["pli-safe"]},
    )
    assert succeeded.cursor == {"known_playlist_item_ids": ["pli-safe"]}
    assert succeeded.last_attempt_at is not None
    assert succeeded.last_success_at is not None
    assert succeeded.last_error is None

    # Memory and Postgres reads both return fresh JSON objects; caller mutation
    # cannot become an undeclared cursor write.
    succeeded.cursor["known_playlist_item_ids"].append("caller-only")
    stored = reg.get(binding.binding_id)
    assert stored is not None
    assert stored.cursor == {"known_playlist_item_ids": ["pli-safe"]}


ALL_CONTRACT_ASSERTIONS: tuple[Callable[[RegistryFactory], None], ...] = (
    assert_round_trip_and_contract_fields,
    assert_single_enabled_inbox_and_swap,
    assert_v1_inbox_selection_is_atomic,
    assert_duplicate_binding_refused,
    assert_account_binding_nullability_by_kind,
    assert_account_binding_uuid_contract,
    assert_watch_later_and_history_refused,
    assert_title_rename_preserves_binding,
    assert_invalid_interval_and_policy_fail_loud,
    assert_provenance_is_strict_portable_json,
    assert_memory_json_isolation,
    assert_inbox_poll_outcomes,
)
