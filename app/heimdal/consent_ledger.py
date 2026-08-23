"""Heimdal consent ledger v0 + capture-time check (HEIM-3) -- Epic #3019 slice A5 (#3042).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
§3 (Posture A / discrete, `self_record` standing consent, structural
OFF-default; the surface is designed to inherit Posture B without a
redesign) and specified by `docs/HEIMDAL/FABLE_COMPANION.md` §6.1/§6.2/§8
(HEIM-3, `heim_consent_gated_capture`).

Contract:

- **Append-only ledger (HEIM-1).** Grants are appended; a revocation is a
  NEW row, never an edit of the grant it lapses (`revokes_grant_ref` names
  the lapsed grant). Same discipline as `app.heimdal.observation_log`: this
  module exposes no update/delete function, and the Postgres backend
  additionally installs a trigger rejecting UPDATE/DELETE at the database
  level (migration `c4f7a1b2d9e3`), independent of which code path issues
  the statement.
- **Standing `self_record` grant (v1 posture A).** Seeded by the owning
  migration (`c4f7a1b2d9e3`) as one standing ledger entry -- "the act of
  deliberately recording is the grant" (FABLE_COMPANION §6.1 basis 1) -- so
  v1 capture is consented without per-memo ceremony, while still flowing
  through the same ledger + capture-time check every later posture uses.
- **Standing media-capture grant (#4492).** One standing grant per capture
  lane, not one shared grant: the governed media ingress lane
  (`app.heimdal.media_ingress`) admits audio, image, video, and document, so
  it carries its own scope and a `capture_profile` naming all four rather
  than borrowing the voice-memo grant whose profile names `speech` only.
  Seeded by migration `a9f3c2d7b6e1`. Per the owner ruling of 2026-07-30
  (#4172), one grant covers all four admitted kinds. The two grants revoke
  independently -- revoking voice memos no longer disables media ingress.
  `capture_profile` stays **descriptive**: no admission path compares a
  modality against it, so this is provenance accuracy, not a new gate.
- **Capture-time check (HEIM-3), the one enforcement point.**
  :func:`admit_raw_evidence` is the *only* sanctioned signal->raw admission
  call. It resolves an active grant for a scope BEFORE returning an
  admission decision; no active grant raises :class:`ConsentRefusedError`
  loudly (never a silent drop). A future capture adapter (§11#5, out of
  scope for this slice) MUST call this function rather than reimplement
  grant resolution -- that is what keeps this the only signal->raw path,
  so no capture route can bypass the ledger.
- **`consent.grant_ref` stamping.** :func:`stamp_consent_block` builds the
  `consent` block (`basis`, `granted_by`, `granted_at`, `third_party`,
  `grant_ref`) that every raw record and every published event must carry
  (FABLE_COMPANION §1.1 field table; HEIM-3 "every event carries `consent`
  with a resolvable `grant_ref`").
- **B-shaped fields present-but-dormant.** The grant record carries
  `vad_gate`, `third_party` (`third_party_policy` + structured
  `third_party` block), `retention`, and `erasure` fields now, populated
  with v1-inert defaults (`vad_gate.enabled = False`,
  `third_party.policy = "degrade"`, no retention/erasure runtime), so
  enabling Posture B later is a grant + adapter change, not a schema
  redesign (ADR-0049 §3).
- **Grant/revocation events are observations.** Granting or revoking is
  itself evented onto the existing Heimdal observation log
  (`heimdal.consent.granted` / `heimdal.consent.revoked`,
  FABLE_COMPANION §6.1) via `app.heimdal.publish.publish_observation` --
  this module references those topic *values* but does not define the
  constants; sibling slice A4 owns `app/events/types.py` topic constants.
- **Revocation propagates to raw erasure (HAR-05).** Once the append-only
  revocation row is durable, :func:`revoke_consent` invokes the same fenced,
  receipted all-copy deletion primitive as hard retention for every raw
  generation stamped with that ``grant_ref``. Pending response leases and
  cold cleanup fail loud and remain retryable; the call does not report
  completion while a cold object or manifest remains. The durable revocation
  row is also replay authority for the scheduled retention entrypoint, so a
  process loss between append and immediate propagation needs no second
  operator revocation.

Backend selection mirrors `app.heimdal.observation_log` (dual-backend,
fail-loud resolution via `app.heimdal._backend.resolve_heimdal_backend`):
``STORE_BACKEND=memory`` (or no Postgres DSN configured) uses an in-process
append-only list seeded with the same standing grants the migrations seed for
Postgres; a resolvable Postgres DSN uses the real `heimdal_consent_grant`
table.

Still out of scope after HAR-05: the capture
adapter itself, ASR, third-party voice detection, place/session grant
runtime (contract-stub only), and published-event suppression propagation
(§11#14, contract-stub).
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional
from uuid import uuid4

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_consent_grant"

_MIGRATION_HINT = (
    "heimdal_consent_grant schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/c4f7a1b2d9e3_heim_consent_ledger_v0.py."
)

# Standing v1 self_record grant identity (mirrors the migration seed exactly
# -- FABLE_COMPANION §6.1 basis 1). Kept as a named constant so the memory
# backend and tests can refer to it without re-deriving a magic string.
SELF_RECORD_GRANT_REF = "grant-self-record-v1"
SELF_RECORD_BASIS = "self_record"
SELF_RECORD_SCOPE = "device+adapter:v1-voice-memo"

# Standing grant for the governed media ingress lane (#4492, owner ruling
# 2026-07-30 on #4172). The lane admits four kinds, so it gets its own scope
# and a `capture_profile` that actually names them, instead of borrowing the
# voice-memo grant whose profile names `speech` only -- the consent block
# stamped onto a photo/video/document must reference a grant that covers it.
# Same per-lane shape as `screen_capture.SCREEN_CAPTURE_SCOPE`.
MEDIA_CAPTURE_GRANT_REF = "grant-media-capture-v1"
# Same *basis* as the voice-memo grant: the reason consent exists is unchanged
# ("the act of deliberately recording is the grant", FABLE_COMPANION §6.1
# basis 1 -- an operator transferring their own device capture IS self-record).
# Only the scope and the modality profile differ, so nothing downstream that
# reads `consent.basis` changes meaning.
MEDIA_CAPTURE_BASIS = "self_record"
MEDIA_CAPTURE_SCOPE = "device+adapter:v1-media-ingress"
# Every kind the governed media ingress lane admits. Held here rather than
# imported from `app.heimdal.media_ingress` (which imports this module), and
# pinned to `media_ingress.MEDIA_KINDS` by
# `tests/heimdal/test_consent_ledger.py::test_media_capture_grant_is_seeded_and_names_every_admitted_kind`
# so a fifth admitted kind cannot ship without extending this grant.
MEDIA_CAPTURE_MODALITIES = ("audio", "image", "video", "document")

# Consent event topics (values only -- app.events.types constants are owned
# by sibling slice A4; referencing the string here does not redefine it).
CONSENT_GRANTED_TOPIC = "heimdal.consent.granted"
CONSENT_REVOKED_TOPIC = "heimdal.consent.revoked"

_THIRD_PARTY_POLICY_DEFAULT = "degrade"


class ConsentLedgerSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the ledger table/columns are absent."""


class AppendOnlyViolationError(RuntimeError):
    """Raised when a caller attempts to mutate an existing grant row.

    Never raised by this module's own code paths (there is no update/delete
    API) -- it is raised when the Postgres backend surfaces the DB trigger's
    rejection of an UPDATE/DELETE statement issued outside this module.
    """


class ConsentRefusedError(RuntimeError):
    """Raised by :func:`admit_raw_evidence` when no active grant covers the scope.

    This is the HEIM-3 refusal: loud, never a silent drop. Raising (rather
    than returning a falsy sentinel) makes "ingestion refused" impossible to
    accidentally ignore at the one signal->raw call site.
    """


@dataclass(frozen=True)
class ConsentGrant:
    """One durable, immutable row in the Heimdal consent ledger.

    ``basis`` is ``"self_record"`` | ``"session_optin"`` | ``"place_optin"``
    for a grant, or the sentinel ``"revocation"`` for a revocation row
    (``revokes_grant_ref`` names the grant it lapses). B-shaped fields
    (``vad_gate``, ``third_party``, ``retention``, ``erasure``) are always
    present, populated with v1-inert defaults on a grant row.
    """

    id: str
    grant_ref: str
    basis: str
    scope: str
    granted_by: str
    granted_at: datetime
    expiry: Optional[datetime]
    capture_profile: Dict[str, Any]
    third_party_policy: str
    vad_gate: Dict[str, Any]
    third_party: Dict[str, Any]
    retention: Dict[str, Any]
    erasure: Dict[str, Any]
    revokes_grant_ref: Optional[str]
    payload: Dict[str, Any]
    created_at: datetime
    sequence: int

    @property
    def is_revocation(self) -> bool:
        return self.basis == "revocation"


def _default_b_shaped_fields() -> Dict[str, Dict[str, Any]]:
    """The B-shaped fields, present-but-dormant (ADR-0049 §3).

    v1-inert defaults: VAD gating disabled, third-party policy defaults to
    degrade-by-default (§6.3), no retention/erasure runtime configured.
    Posture B enables these by writing a new grant with non-default values
    -- never by altering this shape.
    """
    return {
        "vad_gate": {"enabled": False},
        "third_party": {"policy": _THIRD_PARTY_POLICY_DEFAULT},
        "retention": {"hard_retention_days": None},
        "erasure": {"supported": False},
    }


def _standing_seed_row(
    *,
    grant_ref: str,
    basis: str,
    scope: str,
    capture_profile: Dict[str, Any],
    note: str,
    sequence: int,
) -> ConsentGrant:
    """Build one standing grant row, mirroring its owning migration's seed exactly.

    Shared by every standing grant so the memory backend and the
    ``STORE_SCHEMA_AUTOCREATE`` Postgres bootstrap cannot drift apart in the
    B-shaped defaults, the ``granted_by``, or the expiry posture.
    """
    b_shaped = _default_b_shaped_fields()
    now = datetime.now(timezone.utc)
    return ConsentGrant(
        id=str(uuid4()),
        grant_ref=grant_ref,
        basis=basis,
        scope=scope,
        granted_by="operator",
        granted_at=now,
        expiry=None,
        capture_profile=dict(capture_profile),
        third_party_policy=_THIRD_PARTY_POLICY_DEFAULT,
        vad_gate=b_shaped["vad_gate"],
        third_party=b_shaped["third_party"],
        retention=b_shaped["retention"],
        erasure=b_shaped["erasure"],
        revokes_grant_ref=None,
        payload={"note": note},
        created_at=now,
        sequence=sequence,
    )


def _self_record_seed_row(sequence: int) -> ConsentGrant:
    return _standing_seed_row(
        grant_ref=SELF_RECORD_GRANT_REF,
        basis=SELF_RECORD_BASIS,
        scope=SELF_RECORD_SCOPE,
        capture_profile={"modalities": ["speech"], "degradation_rules": ["third_party_speech"]},
        note="standing self_record grant (memory backend seed, mirrors migration c4f7a1b2d9e3)",
        sequence=sequence,
    )


def _media_capture_seed_row(sequence: int) -> ConsentGrant:
    """The governed media ingress lane's standing grant (#4492).

    ``degradation_rules`` keeps ``third_party_speech``: audio and video are
    admitted kinds and can carry third-party speech, so the same §6.3
    degradation posture applies here as on the voice-memo grant.
    """
    return _standing_seed_row(
        grant_ref=MEDIA_CAPTURE_GRANT_REF,
        basis=MEDIA_CAPTURE_BASIS,
        scope=MEDIA_CAPTURE_SCOPE,
        capture_profile={
            "modalities": list(MEDIA_CAPTURE_MODALITIES),
            "degradation_rules": ["third_party_speech"],
        },
        note=(
            "standing media-capture grant (memory backend seed, mirrors migration "
            "a9f3c2d7b6e1)"
        ),
        sequence=sequence,
    )


# Every standing grant the ledger seeds, in append order. Both in-process
# producers (`_MemoryConsentLedger._seed` and the STORE_SCHEMA_AUTOCREATE
# branch of `_bootstrap_pg`) iterate this one tuple, so adding a standing grant
# cannot half-apply across them -- the invariant->producers rule
# (`AGENTS.md :: Required rules`) in structural form. The Postgres production
# producer is the owning migration; `tests/migrations/
# test_heimdal_media_capture_grant_seed_parity.py` pins the two together.
_STANDING_SEED_ROW_BUILDERS = (
    (SELF_RECORD_GRANT_REF, _self_record_seed_row),
    (MEDIA_CAPTURE_GRANT_REF, _media_capture_seed_row),
)


class _MemoryConsentLedger:
    """In-process append-only ledger. Test/dev backend; volatile by design.

    Seeded with every standing grant at construction (`self_record` for the
    voice-memo lane, media-capture for the governed media ingress lane),
    mirroring the Postgres migrations' seed rows, so `STORE_BACKEND=memory`
    behaves like a freshly-migrated database rather than an empty one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[ConsentGrant] = []
        self._seed()

    def _seed(self) -> None:
        with self._lock:
            for grant_ref, build_row in _STANDING_SEED_ROW_BUILDERS:
                if any(r.grant_ref == grant_ref and not r.is_revocation for r in self._rows):
                    continue
                self._rows.append(build_row(len(self._rows)))

    def append(self, grant: ConsentGrant) -> ConsentGrant:
        with self._lock:
            row = ConsentGrant(
                id=grant.id,
                grant_ref=grant.grant_ref,
                basis=grant.basis,
                scope=grant.scope,
                granted_by=grant.granted_by,
                granted_at=grant.granted_at,
                expiry=grant.expiry,
                capture_profile=grant.capture_profile,
                third_party_policy=grant.third_party_policy,
                vad_gate=grant.vad_gate,
                third_party=grant.third_party,
                retention=grant.retention,
                erasure=grant.erasure,
                revokes_grant_ref=grant.revokes_grant_ref,
                payload=grant.payload,
                created_at=datetime.now(timezone.utc),
                sequence=len(self._rows),
            )
            self._rows.append(row)
            return row

    def all_rows(self) -> List[ConsentGrant]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_LEDGER = _MemoryConsentLedger()
_GRANT_FENCE_GUARD = threading.Lock()
_MEMORY_GRANT_FENCES: Dict[str, threading.RLock] = {}
_raw_admission_stage_hook = lambda _stage: None


def reset_memory_consent_ledger() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers.

    Re-seeds **every** standing grant after clearing, so a reset ledger is
    still a *valid* freshly-migrated ledger, not an empty one that would make
    every capture attempt (including the standing-grant tests) spuriously
    refuse. A standing grant added to `_STANDING_SEED_ROW_BUILDERS` inherits
    this automatically; one seeded outside it would silently lose the property.
    """
    _MEMORY_LEDGER.clear()
    _MEMORY_LEDGER._seed()


def _pg_connect() -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


@contextmanager
def consent_grant_fence(grant_ref: str) -> Iterator[None]:
    """Serialize final raw admission and revocation for one consent grant.

    PostgreSQL uses a session advisory lock so the fence spans the ledger and
    raw-store transactions opened by the caller. Memory uses a per-grant
    re-entrant lock with the same grant -> raw-generation lock order.
    """

    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ValueError("grant_ref must be a non-empty string")
    if resolve_heimdal_backend() == "memory":
        with _GRANT_FENCE_GUARD:
            fence = _MEMORY_GRANT_FENCES.setdefault(grant_ref, threading.RLock())
        with fence:
            yield
        return

    lock_key = f"heimdal:consent-grant:{grant_ref}"
    conn = _pg_connect()
    try:
        conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (lock_key,))
        yield
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_key,))
        finally:
            conn.close()


def _schema_autocreate_enabled() -> bool:
    """Explicit test-fixture opt-in, mirroring KERNEL-04/KERNEL-05 precedent.

    Production/runtime Postgres never auto-creates this table; only test
    environments set STORE_SCHEMA_AUTOCREATE=1 (tests/conftest.py).
    """
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    oid = row[0] if row else None
    if not oid:
        raise ConsentLedgerSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")
    from app.heimdal.trigger_ownership import (
        CONSENT_GRANT_TRIGGER,
        assert_migration_owned_reject_mutation_trigger,
    )

    assert_migration_owned_reject_mutation_trigger(
        conn,
        CONSENT_GRANT_TRIGGER,
        error_type=ConsentLedgerSchemaMissingError,
        migration_hint=_MIGRATION_HINT,
    )


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    table_groups = (
        (
            _TABLE,
            (
                "CREATE EXTENSION IF NOT EXISTS pgcrypto",
                f"""
                CREATE TABLE {_TABLE} (
                    id uuid PRIMARY KEY,
                    grant_ref text NOT NULL,
                    basis text NOT NULL,
                    scope text NOT NULL,
                    granted_by text NOT NULL,
                    granted_at timestamptz NOT NULL,
                    expiry timestamptz,
                    capture_profile jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    third_party_policy text NOT NULL DEFAULT 'degrade',
                    vad_gate jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    third_party jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    retention jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    erasure jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    revokes_grant_ref text,
                    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    sequence bigserial NOT NULL
                )
                """,
                f"CREATE INDEX heimdal_consent_grant_seq_idx ON {_TABLE} (sequence)",
                f"CREATE INDEX heimdal_consent_grant_grant_ref_idx ON {_TABLE} (grant_ref)",
                f"CREATE INDEX heimdal_consent_grant_scope_idx ON {_TABLE} (scope)",
                """
                CREATE OR REPLACE FUNCTION heimdal_consent_grant_reject_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'heimdal_consent_grant is append-only (HEIM-1): % is not permitted', TG_OP;
                END;
                $$ LANGUAGE plpgsql
                """,
                f"""
                CREATE TRIGGER heimdal_consent_grant_no_update
                BEFORE UPDATE OR DELETE ON {_TABLE}
                FOR EACH ROW EXECUTE FUNCTION heimdal_consent_grant_reject_mutation()
                """,
            ),
        ),
    )
    for table_name, statements in table_groups:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        row = cur.fetchone()
        table_present = bool(row and row[0])
        if table_present:
            continue
        for statement in statements:
            cur.execute(statement)
    _assert_pg_schema(conn)
    # Seed every standing grant (idempotent), from the same builder tuple the
    # memory backend uses -- a standing grant cannot land in one in-process
    # producer and not the other.
    for grant_ref, build_row in _STANDING_SEED_ROW_BUILDERS:
        cur.execute(
            f"SELECT 1 FROM {_TABLE} WHERE grant_ref = %s AND basis != 'revocation'",
            (grant_ref,),
        )
        if cur.fetchone() is not None:
            continue
        seed = build_row(0)
        cur.execute(
            f"""
            INSERT INTO {_TABLE} (
                id, grant_ref, basis, scope, granted_by, granted_at, expiry,
                capture_profile, third_party_policy, vad_gate, third_party,
                retention, erasure, revokes_grant_ref, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb)
            """,
            (
                seed.id,
                seed.grant_ref,
                seed.basis,
                seed.scope,
                seed.granted_by,
                seed.granted_at,
                seed.expiry,
                json.dumps(seed.capture_profile),
                seed.third_party_policy,
                json.dumps(seed.vad_gate),
                json.dumps(seed.third_party),
                json.dumps(seed.retention),
                json.dumps(seed.erasure),
                seed.revokes_grant_ref,
                json.dumps(seed.payload),
            ),
        )


def _row_from_db(row: tuple) -> ConsentGrant:
    (
        row_id, grant_ref, basis, scope, granted_by, granted_at, expiry,
        capture_profile, third_party_policy, vad_gate, third_party,
        retention, erasure, revokes_grant_ref, payload, created_at, sequence,
    ) = row

    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    return ConsentGrant(
        id=str(row_id),
        grant_ref=str(grant_ref),
        basis=str(basis),
        scope=str(scope),
        granted_by=str(granted_by),
        granted_at=granted_at,
        expiry=expiry,
        capture_profile=_as_dict(capture_profile),
        third_party_policy=str(third_party_policy),
        vad_gate=_as_dict(vad_gate),
        third_party=_as_dict(third_party),
        retention=_as_dict(retention),
        erasure=_as_dict(erasure),
        revokes_grant_ref=str(revokes_grant_ref) if revokes_grant_ref is not None else None,
        payload=_as_dict(payload),
        created_at=created_at,
        sequence=int(sequence),
    )


_SELECT_COLUMNS = (
    "id, grant_ref, basis, scope, granted_by, granted_at, expiry, "
    "capture_profile, third_party_policy, vad_gate, third_party, "
    "retention, erasure, revokes_grant_ref, payload, created_at, sequence"
)


class _PgConsentLedger:
    """Postgres-backed append-only ledger; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def append(self, grant: ConsentGrant) -> ConsentGrant:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (
                    id, grant_ref, basis, scope, granted_by, granted_at, expiry,
                    capture_profile, third_party_policy, vad_gate, third_party,
                    retention, erasure, revokes_grant_ref, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    grant.id,
                    grant.grant_ref,
                    grant.basis,
                    grant.scope,
                    grant.granted_by,
                    grant.granted_at,
                    grant.expiry,
                    json.dumps(grant.capture_profile),
                    grant.third_party_policy,
                    json.dumps(grant.vad_gate),
                    json.dumps(grant.third_party),
                    json.dumps(grant.retention),
                    json.dumps(grant.erasure),
                    grant.revokes_grant_ref,
                    json.dumps(grant.payload),
                ),
            )
            row = cur.fetchone()
            return _row_from_db(row)
        finally:
            conn.close()

    def all_rows(self) -> List[ConsentGrant]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} ORDER BY sequence ASC")
            return [_row_from_db(row) for row in cur.fetchall()]
        finally:
            conn.close()


def _backend() -> "_MemoryConsentLedger | _PgConsentLedger":
    if resolve_heimdal_backend() == "pg":
        return _PgConsentLedger()
    return _MEMORY_LEDGER


# ---------------------------------------------------------------------------
# Public ledger API
# ---------------------------------------------------------------------------


def grant_consent(
    *,
    grant_ref: str,
    basis: str,
    scope: str,
    granted_by: str,
    expiry: Optional[datetime] = None,
    capture_profile: Optional[Mapping[str, Any]] = None,
    third_party_policy: str = _THIRD_PARTY_POLICY_DEFAULT,
    vad_gate: Optional[Mapping[str, Any]] = None,
    third_party: Optional[Mapping[str, Any]] = None,
    retention: Optional[Mapping[str, Any]] = None,
    erasure: Optional[Mapping[str, Any]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> ConsentGrant:
    """Append a new consent grant to the ledger.

    Grants are appended, never edited (HEIM-1). B-shaped fields
    (``vad_gate``/``third_party``/``retention``/``erasure``) default to the
    v1-inert shape from :func:`_default_b_shaped_fields` when omitted, so
    every grant -- including future place/session grants -- carries the
    full posture-B-ready shape without callers having to know its defaults.
    """
    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ValueError(f"grant_consent requires a non-empty grant_ref, got {grant_ref!r}")
    if basis == "revocation":
        raise ValueError("grant_consent cannot create a revocation row; use revoke_consent")
    b_shaped = _default_b_shaped_fields()
    grant = ConsentGrant(
        id=str(uuid4()),
        grant_ref=grant_ref,
        basis=basis,
        scope=scope,
        granted_by=granted_by,
        granted_at=datetime.now(timezone.utc),
        expiry=expiry,
        capture_profile=dict(capture_profile or {}),
        third_party_policy=third_party_policy,
        vad_gate=dict(vad_gate) if vad_gate is not None else b_shaped["vad_gate"],
        third_party=dict(third_party) if third_party is not None else b_shaped["third_party"],
        retention=dict(retention) if retention is not None else b_shaped["retention"],
        erasure=dict(erasure) if erasure is not None else b_shaped["erasure"],
        revokes_grant_ref=None,
        payload=dict(payload or {}),
        created_at=datetime.now(timezone.utc),
        sequence=-1,
    )
    return _backend().append(grant)


def assert_consent_grant_active(
    grant_ref: str, *, at: Optional[datetime] = None
) -> ConsentGrant:
    """Fail loud unless the exact stamped grant remains active.

    Production raw producers call this while holding
    :func:`consent_grant_fence`, immediately before their durable insert.
    """

    reference = at or datetime.now(timezone.utc)
    rows = _backend().all_rows()
    revoked = _revoked_grant_refs(rows)
    for row in reversed(rows):
        if row.is_revocation or row.grant_ref != grant_ref:
            continue
        if row.grant_ref in revoked or (row.expiry is not None and row.expiry <= reference):
            break
        return row
    raise ConsentRefusedError(
        f"Capture refused (HEIM-3): consent grant {grant_ref!r} is no longer active. "
        "No raw evidence was admitted."
    )


@contextmanager
def consent_raw_admission(grant_ref: str) -> Iterator[None]:
    """Fence and revalidate the exact grant around one raw-store insert."""

    with consent_grant_fence(grant_ref):
        assert_consent_grant_active(grant_ref)
        _raw_admission_stage_hook("after_final_consent_validation")
        yield


def revoke_consent(*, grant_ref: str, revoked_by: str, payload: Optional[Mapping[str, Any]] = None) -> ConsentGrant:
    """Append a revocation row that lapses ``grant_ref`` (HEIM-1: new event, never a rewrite).

    FABLE_COMPANION §6.4: future capture lapses immediately (the ledger is
    checked at capture time -- :func:`resolve_active_grant` stops returning
    the revoked grant the instant this row is visible). HAR-05 then propagates
    the durable revocation through the shared governed raw-erasure primitive;
    a cold cleanup failure raises and remains retryable. Published-event
    suppression remains a separate future concern.
    """
    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ValueError(f"revoke_consent requires a non-empty grant_ref, got {grant_ref!r}")
    b_shaped = _default_b_shaped_fields()
    revocation = ConsentGrant(
        id=str(uuid4()),
        grant_ref=f"{grant_ref}:revoked:{uuid4().hex[:8]}",
        basis="revocation",
        scope="",
        granted_by=revoked_by,
        granted_at=datetime.now(timezone.utc),
        expiry=None,
        capture_profile={},
        third_party_policy=_THIRD_PARTY_POLICY_DEFAULT,
        vad_gate=b_shaped["vad_gate"],
        third_party=b_shaped["third_party"],
        retention=b_shaped["retention"],
        erasure=b_shaped["erasure"],
        revokes_grant_ref=grant_ref,
        payload=dict(payload or {}),
        created_at=datetime.now(timezone.utc),
        sequence=-1,
    )
    with consent_grant_fence(grant_ref):
        persisted = _backend().append(revocation)
        # Local import keeps the consent ledger's read/admission path independent
        # of raw-store initialization while making the production revocation call
        # the authority that starts all-copy erasure.
        from app.heimdal.retention import enforce_consent_revocation

        enforce_consent_revocation(grant_ref=grant_ref, revoked_at=persisted.created_at)
        return persisted


def _revoked_grant_refs(rows: List[ConsentGrant]) -> set:
    return {r.revokes_grant_ref for r in rows if r.is_revocation and r.revokes_grant_ref}


def list_revoked_grant_refs() -> List[str]:
    """Return durable revocation work identities in first-observed order."""

    refs: List[str] = []
    seen: set[str] = set()
    for row in _backend().all_rows():
        grant_ref = row.revokes_grant_ref
        if not row.is_revocation or not grant_ref or grant_ref in seen:
            continue
        seen.add(grant_ref)
        refs.append(grant_ref)
    return refs


def reconcile_revoked_consent_erasure() -> int:
    """Replay durable revocation rows through all-copy erasure.

    The append-only revocation row is the durable work item. The scheduled
    retention entrypoint calls this on every run, so a process loss after the
    row commits but before immediate propagation converges without another
    operator revocation.
    """

    from app.heimdal.retention import enforce_consent_revocation

    reconciled = 0
    for grant_ref in list_revoked_grant_refs():
        with consent_grant_fence(grant_ref):
            enforce_consent_revocation(grant_ref=grant_ref)
        reconciled += 1
    return reconciled


def list_active_grants(*, scope: Optional[str] = None, at: Optional[datetime] = None) -> List[ConsentGrant]:
    """Return every currently-active (non-revoked, non-expired) grant.

    A grant is active iff: it is not a revocation row, no later revocation
    row names its ``grant_ref``, and (if ``expiry`` is set) ``at`` is before
    that expiry. ``scope`` filters to grants whose ``scope`` matches
    exactly (place/session scope hierarchy is a v2 concern, out of scope
    here per FABLE_COMPANION §6.1 basis 2/3 being contract-stub).
    """
    at = at or datetime.now(timezone.utc)
    rows = _backend().all_rows()
    revoked = _revoked_grant_refs(rows)
    active = []
    for row in rows:
        if row.is_revocation:
            continue
        if row.grant_ref in revoked:
            continue
        if row.expiry is not None and row.expiry <= at:
            continue
        if scope is not None and row.scope != scope:
            continue
        active.append(row)
    return active


def resolve_active_grant(*, scope: str, at: Optional[datetime] = None) -> Optional[ConsentGrant]:
    """Resolve the single active grant for ``scope``, or ``None`` if none is active.

    This is the read the capture-time check (HEIM-3) is built on: it is a
    pure query over the ledger and never mutates it. When more than one
    grant is active for the same scope (should not normally happen for v1's
    one-standing-grant-per-adapter model), the most recently granted one
    wins -- last-appended-wins, consistent with append-only "later rows are
    the current truth" semantics elsewhere in the ledger.
    """
    candidates = list_active_grants(scope=scope, at=at)
    if not candidates:
        return None
    return max(candidates, key=lambda g: g.sequence)


# ---------------------------------------------------------------------------
# Capture-time check (HEIM-3) -- the one signal->raw enforcement point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsentBlock:
    """The `consent` block every raw record and published event must carry.

    Mirrors FABLE_COMPANION §1.1's `consent: { basis, granted_by,
    granted_at, third_party, grant_ref }` field family exactly.
    """

    basis: str
    granted_by: str
    granted_at: str
    third_party: str
    grant_ref: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "basis": self.basis,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "third_party": self.third_party,
            "grant_ref": self.grant_ref,
        }


def stamp_consent_block(grant: ConsentGrant, *, third_party: str = "none") -> ConsentBlock:
    """Build the `consent` block stamping ``grant`` onto a raw record or published event.

    ``third_party`` defaults to ``"none"`` (v1 single-party declaration);
    the third-party detection guard (§6.3, out of scope for this slice)
    overrides it to ``"detected"``/``"marked"`` per observation.
    """
    return ConsentBlock(
        basis=grant.basis,
        granted_by=grant.granted_by,
        granted_at=grant.granted_at.isoformat(),
        third_party=third_party,
        grant_ref=grant.grant_ref,
    )


@dataclass(frozen=True)
class AdmittedEvidence:
    """The admission receipt returned by :func:`admit_raw_evidence`.

    Carries the resolved grant's :class:`ConsentBlock` so the caller can
    stamp it directly onto the raw record and, later, the published event
    -- the same `consent.grant_ref` value flows through both, per HEIM-3.
    """

    grant: ConsentGrant
    consent: ConsentBlock


def admit_raw_evidence(*, scope: str, third_party: str = "none", at: Optional[datetime] = None) -> AdmittedEvidence:
    """The HEIM-3 capture-time check: the only sanctioned signal->raw admission call.

    Resolves an active grant for ``scope`` BEFORE the caller may admit raw
    evidence. No active grant -> raises :class:`ConsentRefusedError` loudly
    (never a silent drop, never a falsy return a caller could ignore).

    A future capture adapter (§11#5, out of scope for this slice) is
    required to call this function as its one signal->raw gate rather than
    reimplement grant resolution inline -- that is what keeps this the only
    code path from signal to raw store, so no capture route can bypass the
    ledger (FABLE_COMPANION §6.2).
    """
    grant = resolve_active_grant(scope=scope, at=at)
    if grant is None:
        raise ConsentRefusedError(
            f"Capture refused (HEIM-3): no active consent grant for scope {scope!r}. "
            "Raw evidence was not admitted. Structural OFF-default: no grant, no capture."
        )
    consent = stamp_consent_block(grant, third_party=third_party)
    return AdmittedEvidence(grant=grant, consent=consent)


__all__ = [
    "AdmittedEvidence",
    "AppendOnlyViolationError",
    "CONSENT_GRANTED_TOPIC",
    "CONSENT_REVOKED_TOPIC",
    "ConsentBlock",
    "ConsentGrant",
    "ConsentLedgerSchemaMissingError",
    "ConsentRefusedError",
    "assert_consent_grant_active",
    "consent_grant_fence",
    "consent_raw_admission",
    "MEDIA_CAPTURE_BASIS",
    "MEDIA_CAPTURE_GRANT_REF",
    "MEDIA_CAPTURE_MODALITIES",
    "MEDIA_CAPTURE_SCOPE",
    "SELF_RECORD_BASIS",
    "SELF_RECORD_GRANT_REF",
    "SELF_RECORD_SCOPE",
    "admit_raw_evidence",
    "grant_consent",
    "list_active_grants",
    "list_revoked_grant_refs",
    "reconcile_revoked_consent_erasure",
    "reset_memory_consent_ledger",
    "resolve_active_grant",
    "revoke_consent",
    "stamp_consent_block",
]
