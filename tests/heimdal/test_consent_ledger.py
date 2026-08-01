"""Heimdal consent ledger v0 + capture-time check (HEIM-3), Epic #3019 slice A5 (#3042).

Covers the issue's three behavioral Acceptance Criteria:

- ``test_capture_refused_without_grant`` -- no active grant means raw is
  NOT admitted and the refusal is surfaced loudly; there is no signal->raw
  path that bypasses the ledger.
- ``test_self_record_stamps_every_event`` -- with the standing
  ``self_record`` grant active, every admitted raw record and published
  event carries a ``consent.grant_ref`` stamping that grant.
- ``test_b_shaped_fields_present_dormant`` -- the B-shaped fields
  (``vad_gate``, ``third_party``, ``retention``, ``erasure``) are present
  but v1-inert on every grant record.

``admit_raw_evidence`` is the real production call site (the one
signal->raw admission function this slice builds -- the future capture
adapter, out of scope here, is required to call it rather than reimplement
grant resolution), so ``test_capture_refused_without_grant`` exercises that
function directly, not a lower-level helper.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.heimdal import consent_ledger
from app.heimdal.consent_ledger import (
    MEDIA_CAPTURE_BASIS,
    MEDIA_CAPTURE_GRANT_REF,
    MEDIA_CAPTURE_MODALITIES,
    MEDIA_CAPTURE_SCOPE,
    SELF_RECORD_BASIS,
    SELF_RECORD_GRANT_REF,
    SELF_RECORD_SCOPE,
    AdmittedEvidence,
    ConsentGrant,
    ConsentRefusedError,
    admit_raw_evidence,
    grant_consent,
    list_active_grants,
    reset_memory_consent_ledger,
    resolve_active_grant,
    revoke_consent,
    stamp_consent_block,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _reset_consent_ledger():
    reset_memory_consent_ledger()
    yield
    reset_memory_consent_ledger()


_UNGRANTED_SCOPE = "device+adapter:no-such-scope"


# --- AC1: capture refused without an active grant ------------------------------


def test_capture_refused_without_grant() -> None:
    """No active grant for a scope -> admit_raw_evidence refuses loudly.

    Drives the real production call site (`admit_raw_evidence`, the one
    sanctioned signal->raw admission function this slice builds) directly,
    not a lower-level helper -- proving there is no bypass path: the only
    way to get raw admitted is through this function, and it raises rather
    than returning a falsy/None sentinel a caller could silently ignore.
    """
    with pytest.raises(ConsentRefusedError) as excinfo:
        admit_raw_evidence(scope=_UNGRANTED_SCOPE)

    message = str(excinfo.value)
    assert "HEIM-3" in message
    assert _UNGRANTED_SCOPE in message
    # No silent drop: the refusal names the structural OFF-default directly.
    assert "no grant, no capture" in message.lower() or "no active consent grant" in message.lower()


def test_capture_refused_after_revocation() -> None:
    """A revoked grant no longer admits capture -- revocation lapses immediately (§6.4)."""
    scope = "device+adapter:session-scope"
    grant_consent(grant_ref="grant-session-1", basis="session_optin", scope=scope, granted_by="operator")
    # Active before revocation.
    admitted = admit_raw_evidence(scope=scope)
    assert admitted.grant.grant_ref == "grant-session-1"

    revoke_consent(grant_ref="grant-session-1", revoked_by="operator")

    with pytest.raises(ConsentRefusedError):
        admit_raw_evidence(scope=scope)


def test_capture_refused_after_expiry() -> None:
    """An expired grant does not admit capture (negative/completeness coverage)."""
    scope = "device+adapter:expiring-scope"
    past = datetime.now(timezone.utc) - timedelta(days=1)
    grant_consent(
        grant_ref="grant-expired-1",
        basis="session_optin",
        scope=scope,
        granted_by="operator",
        expiry=past,
    )
    with pytest.raises(ConsentRefusedError):
        admit_raw_evidence(scope=scope)


def test_no_bypass_path_exists_on_the_module() -> None:
    """Structural proof there is no second admission entrypoint to bypass the ledger.

    Mirrors the observation_log precedent's structural assertion: the
    module's public surface exposes exactly one admission function, so a
    caller cannot reach for an alternate "just write raw" path.
    """
    public_names = set(consent_ledger.__all__)
    admission_like = {
        name
        for name in public_names
        if "admit" in name.lower() or ("raw" in name.lower() and "consent" not in name.lower())
    }
    assert admission_like == {"admit_raw_evidence", "AdmittedEvidence"}


# --- AC2: self_record stamps every admitted record + published event ----------


def test_standing_self_record_grant_is_active_by_default() -> None:
    """The standing `self_record` grant is seeded and active without any setup call."""
    grant = resolve_active_grant(scope=SELF_RECORD_SCOPE)
    assert grant is not None
    assert grant.grant_ref == SELF_RECORD_GRANT_REF
    assert grant.basis == SELF_RECORD_BASIS


def test_self_record_stamps_every_event() -> None:
    """With self_record active, admission stamps a consent.grant_ref every time.

    Simulates the multiple admitted "raw record" + "published event" call
    sites a capture adapter would make for one memo (one admission at
    capture time, then the consent block is stamped onto both the raw
    record and the eventual published event) and asserts the same
    grant_ref is present on every one.
    """
    admitted_records = [admit_raw_evidence(scope=SELF_RECORD_SCOPE) for _ in range(3)]
    assert len(admitted_records) == 3
    for admitted in admitted_records:
        assert isinstance(admitted, AdmittedEvidence)
        assert admitted.consent.grant_ref == SELF_RECORD_GRANT_REF
        assert admitted.consent.basis == SELF_RECORD_BASIS

    # The same admission's consent block is what gets stamped onto both the
    # raw record and the published event -- one admission, one grant_ref,
    # reused verbatim on every downstream artifact for that observation.
    admitted = admitted_records[0]
    raw_record = {"kind": "raw", "consent": admitted.consent.as_dict()}
    published_event = {"kind": "published", "payload": {"consent": admitted.consent.as_dict()}}
    assert raw_record["consent"]["grant_ref"] == SELF_RECORD_GRANT_REF
    assert published_event["payload"]["consent"]["grant_ref"] == SELF_RECORD_GRANT_REF


def test_stamp_consent_block_matches_fable_companion_field_family() -> None:
    """`consent` block shape matches FABLE_COMPANION §1.1 exactly."""
    grant = resolve_active_grant(scope=SELF_RECORD_SCOPE)
    assert grant is not None
    block = stamp_consent_block(grant, third_party="none")
    d = block.as_dict()
    assert set(d.keys()) == {"basis", "granted_by", "granted_at", "third_party", "grant_ref"}
    assert d["grant_ref"] == SELF_RECORD_GRANT_REF
    assert d["basis"] == SELF_RECORD_BASIS
    assert d["third_party"] == "none"


def test_stamp_consent_block_carries_third_party_detected() -> None:
    """The third-party guard (§6.3, out of scope here) overrides third_party on the block."""
    grant = resolve_active_grant(scope=SELF_RECORD_SCOPE)
    assert grant is not None
    block = stamp_consent_block(grant, third_party="detected")
    assert block.as_dict()["third_party"] == "detected"


# --- AC3: B-shaped fields present-but-dormant ----------------------------------


def test_b_shaped_fields_present_dormant() -> None:
    """vad_gate/third_party/retention/erasure exist on every grant, v1-inert.

    Checked against both the seeded standing grant and a freshly-created
    grant, so the shape is guaranteed by the ledger's write path, not just
    an accident of the migration seed.
    """
    seeded = resolve_active_grant(scope=SELF_RECORD_SCOPE)
    assert seeded is not None
    _assert_b_shaped_dormant(seeded)

    fresh = grant_consent(
        grant_ref="grant-fresh-1",
        basis="session_optin",
        scope="device+adapter:fresh-scope",
        granted_by="operator",
    )
    _assert_b_shaped_dormant(fresh)


def _assert_b_shaped_dormant(grant: ConsentGrant) -> None:
    # Present: the fields exist and are structured dicts, not missing/None.
    assert isinstance(grant.vad_gate, dict)
    assert isinstance(grant.third_party, dict)
    assert isinstance(grant.retention, dict)
    assert isinstance(grant.erasure, dict)

    # Dormant: v1-inert defaults -- nothing here is live in posture A.
    assert grant.vad_gate.get("enabled") is False
    assert grant.third_party.get("policy") == "degrade"
    assert grant.retention.get("hard_retention_days") is None
    assert grant.erasure.get("supported") is False


def test_b_shaped_fields_overridable_for_future_posture_b() -> None:
    """A caller (future posture-B grant) can override the B-shaped defaults without a schema change."""
    grant = grant_consent(
        grant_ref="grant-place-1",
        basis="place_optin",
        scope="place:office",
        granted_by="operator",
        vad_gate={"enabled": True, "threshold_db": -35},
        third_party={"policy": "mark_only"},
        retention={"hard_retention_days": 30},
        erasure={"supported": True},
    )
    assert grant.vad_gate == {"enabled": True, "threshold_db": -35}
    assert grant.third_party == {"policy": "mark_only"}
    assert grant.retention == {"hard_retention_days": 30}
    assert grant.erasure == {"supported": True}


# --- Append-only discipline (HEIM-1) -------------------------------------------


def test_revocation_is_a_new_row_not_a_rewrite() -> None:
    """Revoking a grant appends a new row; the original grant row is untouched."""
    grant_consent(grant_ref="grant-revocable-1", basis="session_optin", scope="device+adapter:rev-scope", granted_by="operator")
    before = list_active_grants(scope="device+adapter:rev-scope")
    assert len(before) == 1
    original_sequence = before[0].sequence

    revocation = revoke_consent(grant_ref="grant-revocable-1", revoked_by="operator")
    assert revocation.is_revocation
    assert revocation.revokes_grant_ref == "grant-revocable-1"
    assert revocation.sequence > original_sequence

    # The grant is no longer active, but the original row was never edited
    # or deleted -- it is simply superseded by the later revocation row.
    assert list_active_grants(scope="device+adapter:rev-scope") == []


def test_no_mutation_surface_on_ledger_module() -> None:
    """Structural HEIM-1 proof: no update/delete method anywhere in the public API."""
    assert not hasattr(consent_ledger, "update_grant")
    assert not hasattr(consent_ledger, "delete_grant")
    assert not hasattr(consent_ledger, "update")
    assert not hasattr(consent_ledger, "delete")

    public_names = set(consent_ledger.__all__)
    mutating_names = {name for name in public_names if "update" in name or "delete" in name}
    assert mutating_names == set(), f"unexpected mutation surface exported: {mutating_names}"


def test_no_mutation_method_on_resolved_backend() -> None:
    backend = consent_ledger._backend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "delete")


@pytest.mark.pg
def test_append_only_enforced_pg() -> None:
    """Real Postgres trigger rejects UPDATE/DELETE against heimdal_consent_grant (HEIM-1)."""
    pytest.importorskip("psycopg")

    grant = grant_consent(
        grant_ref="grant-pg-append-only-check",
        basis="session_optin",
        scope="device+adapter:pg-check-scope",
        granted_by="operator",
    )

    conn = consent_ledger._pg_connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"UPDATE {consent_ledger._TABLE} SET basis = 'tampered' WHERE id = %s",
                (grant.id,),
            )
        assert "append-only" in str(excinfo.value).lower() or "HEIM-1" in str(excinfo.value)

        with pytest.raises(Exception) as excinfo_del:
            cur.execute(f"DELETE FROM {consent_ledger._TABLE} WHERE id = %s", (grant.id,))
        assert "append-only" in str(excinfo_del.value).lower() or "HEIM-1" in str(excinfo_del.value)
    finally:
        conn.close()


# --- Validation / negative coverage --------------------------------------------


def test_grant_consent_rejects_empty_grant_ref() -> None:
    with pytest.raises(ValueError):
        grant_consent(grant_ref="", basis="session_optin", scope="s", granted_by="operator")


def test_grant_consent_rejects_revocation_basis() -> None:
    with pytest.raises(ValueError):
        grant_consent(grant_ref="x", basis="revocation", scope="s", granted_by="operator")


def test_revoke_consent_rejects_empty_grant_ref() -> None:
    with pytest.raises(ValueError):
        revoke_consent(grant_ref="", revoked_by="operator")


def test_resolve_active_grant_returns_none_for_unknown_scope() -> None:
    assert resolve_active_grant(scope=_UNGRANTED_SCOPE) is None


def test_list_active_grants_excludes_revocation_rows_themselves() -> None:
    grant_consent(grant_ref="grant-list-1", basis="session_optin", scope="device+adapter:list-scope", granted_by="operator")
    revoke_consent(grant_ref="grant-list-1", revoked_by="operator")
    # Revocation rows are never returned by list_active_grants as if they
    # were themselves grants (basis == "revocation" is not a valid active grant).
    all_active = list_active_grants()
    assert all(g.basis != "revocation" for g in all_active)


# --- #4492: the governed media ingress lane's own standing grant ---------------


def test_media_capture_grant_is_seeded_and_names_every_admitted_kind() -> None:
    """The media lane's standing grant is active by default and its descriptive
    `capture_profile.modalities` names exactly the kinds the lane admits.

    The set equality against `media_ingress.MEDIA_KINDS` is the load-bearing
    half: `KD-4E7228960927` existed because the stamped grant named `speech`
    while the lane admitted four kinds, so a fifth admitted kind added without
    extending this grant would recreate the same provenance gap silently.
    """
    from app.heimdal.media_ingress import MEDIA_KINDS

    grant = resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE)
    assert grant is not None, "the media-capture grant must be seeded, not set up per test"
    assert grant.grant_ref == MEDIA_CAPTURE_GRANT_REF
    assert grant.basis == MEDIA_CAPTURE_BASIS
    assert grant.scope == MEDIA_CAPTURE_SCOPE

    modalities = grant.capture_profile["modalities"]
    assert set(modalities) == set(MEDIA_KINDS), (
        "the seeded grant's modalities must name exactly the admitted media kinds; "
        f"grant={sorted(modalities)} lane={sorted(MEDIA_KINDS)}"
    )
    assert set(modalities) == set(MEDIA_CAPTURE_MODALITIES)
    # The owner ruling of 2026-07-30 (#4172): one grant covering all four kinds.
    assert set(modalities) == {"audio", "image", "video", "document"}
    # Audio and video can carry third-party speech, so the §6.3 degradation
    # posture is inherited rather than dropped.
    assert grant.capture_profile["degradation_rules"] == ["third_party_speech"]


def test_media_capture_and_self_record_are_separate_grants() -> None:
    """Two standing grants, two scopes, revoked independently.

    Before #4492 one grant covered both lanes, so revoking voice memos also
    disabled media ingress. `list_active_grants` sees both, and a revocation of
    either leaves the other resolvable.
    """
    assert MEDIA_CAPTURE_SCOPE != SELF_RECORD_SCOPE
    assert MEDIA_CAPTURE_GRANT_REF != SELF_RECORD_GRANT_REF
    seeded = {g.grant_ref for g in list_active_grants()}
    assert {SELF_RECORD_GRANT_REF, MEDIA_CAPTURE_GRANT_REF} <= seeded

    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="operator")
    assert resolve_active_grant(scope=SELF_RECORD_SCOPE) is None
    still_active = resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE)
    assert still_active is not None and still_active.grant_ref == MEDIA_CAPTURE_GRANT_REF

    reset_memory_consent_ledger()

    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="operator")
    assert resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE) is None
    voice_memo = resolve_active_grant(scope=SELF_RECORD_SCOPE)
    assert voice_memo is not None and voice_memo.grant_ref == SELF_RECORD_GRANT_REF


def test_reset_reseeds_every_standing_grant() -> None:
    """`reset_memory_consent_ledger` restores a *valid freshly-migrated* ledger.

    The property the reset hook exists for, now that there is more than one
    standing grant: a reset ledger with only some of them would make the
    un-reseeded lane spuriously refuse every capture.
    """
    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="operator")
    revoke_consent(grant_ref=MEDIA_CAPTURE_GRANT_REF, revoked_by="operator")
    assert resolve_active_grant(scope=SELF_RECORD_SCOPE) is None
    assert resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE) is None

    reset_memory_consent_ledger()

    assert {g.grant_ref for g in list_active_grants()} == {
        SELF_RECORD_GRANT_REF,
        MEDIA_CAPTURE_GRANT_REF,
    }
    for scope in (SELF_RECORD_SCOPE, MEDIA_CAPTURE_SCOPE):
        assert resolve_active_grant(scope=scope) is not None


def test_media_capture_grant_carries_the_b_shaped_dormant_shape() -> None:
    """The new standing grant is B-shaped-but-dormant like every other grant
    (ADR-0049 §3), so Posture B stays a grant change rather than a redesign."""
    grant = resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE)
    assert grant is not None
    _assert_b_shaped_dormant(grant)
