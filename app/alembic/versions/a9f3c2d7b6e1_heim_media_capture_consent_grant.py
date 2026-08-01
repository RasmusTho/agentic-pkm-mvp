"""HEIM (#4492): standing media-capture consent grant for the governed media ingress lane.

Resolves Known Defect `KD-4E7228960927` (`KD-4384-MODALITY`) on #4172, under
the owner ruling of 2026-07-30 recorded on that Issue: **one grant covering all
four admitted kinds -- audio, image, video, document.**

`POST /api/heimdal/capture/media` (`app/heimdal/media_ingress.py`, CDLM-01
#4384) admitted every kind under the standing `self_record` grant seeded by
`c4f7a1b2d9e3`, whose scope is `device+adapter:v1-voice-memo` and whose
`capture_profile` names `speech` only. The consent block stamped onto a photo,
video, or document raw record therefore referenced a grant whose descriptive
profile did not cover it. This seeds the lane its own standing grant, following
the per-lane precedent of `screen_capture.SCREEN_CAPTURE_SCOPE`.

This is **provenance accuracy, not an enforcement change**: nothing on the
admission path compares a modality against `capture_profile`
(`admit_raw_evidence` resolves an active grant for the scope and
`stamp_consent_block` copies `basis`/`granted_by`/`granted_at`/`third_party`/
`grant_ref`). The field is stored, seeded, and surfaced read-only by
`app/heimdal/consent_surface.py`. This migration adds no gate.

Data-only: no DDL. The `heimdal_consent_grant` table, its indexes, and its
HEIM-1 append-only trigger are all owned by `c4f7a1b2d9e3` and untouched here.
The seed mirrors that migration's `self_record` seed exactly -- same idempotent
`INSERT ... WHERE NOT EXISTS` shape, same v1-inert B-shaped defaults -- and is
mirrored in-process by `app/heimdal/consent_ledger.py`
(`_media_capture_seed_row`, seeded from `_MemoryConsentLedger._seed` and from
the `STORE_SCHEMA_AUTOCREATE` branch of `_bootstrap_pg`). The producers are
pinned together by
`tests/migrations/test_heimdal_media_capture_grant_seed_parity.py`.

Forward-only: `heimdal_consent_grant` is append-only (HEIM-1) and carries a
database trigger rejecting UPDATE and DELETE, so a downgrade could not remove
this row even if it wanted to. Revoking the grant is an appended revocation
row, never a deletion.

**Operator note for an existing deployment whose voice-memo grant was
revoked.** Before this change both lanes resolved `SELF_RECORD_SCOPE`, so
revoking `grant-self-record-v1` also stopped media ingress. This seed uses a
*different* `grant_ref` that has never existed on that database, so the
`WHERE NOT EXISTS` guard cannot match that revocation and the upgrade inserts
an **active** media-capture grant: media ingress resumes admitting without a
separate operator action. That is the intended consequence of separating the
grants under the 2026-07-30 ruling, and `/api/status` shows the lane going
live. `_heimdal/consent.md` will NOT show it: nothing in the shipped runtime
calls `consent_surface.write_consent_readout`, so that note stays stale until
something rebuilds it. An operator who revoked voice memos to stop *all*
capture must also revoke `grant-media-capture-v1` after upgrading -- which is
programmatic today, as no route or CLI grants or revokes.

Revision ID: a9f3c2d7b6e1
Revises: e7a2b9c4d1f8
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# Alembic identifiers
revision: str = "a9f3c2d7b6e1"
down_revision: Union[str, None] = "e7a2b9c4d1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Machine-readable classification for the promotion migration gate
# (docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md;
# app/release_channels/reversibility.py). Downgrade raises by design.
reversibility: str = "forward-only"

# Mirrors app/heimdal/consent_ledger.py exactly (MEDIA_CAPTURE_GRANT_REF /
# MEDIA_CAPTURE_BASIS / MEDIA_CAPTURE_SCOPE / MEDIA_CAPTURE_MODALITIES).
_MEDIA_CAPTURE_GRANT_REF = "grant-media-capture-v1"
_MEDIA_CAPTURE_BASIS = "self_record"
_MEDIA_CAPTURE_SCOPE = "device+adapter:v1-media-ingress"
_MEDIA_CAPTURE_CAPTURE_PROFILE = (
    '{"modalities": ["audio", "image", "video", "document"], '
    '"degradation_rules": ["third_party_speech"]}'
)


def upgrade() -> None:
    # Idempotent: a rerun (bootstrap re-apply) must not duplicate the standing
    # grant. Same guard shape as c4f7a1b2d9e3's self_record seed.
    op.execute(
        f"""
        INSERT INTO heimdal_consent_grant (
            id, grant_ref, basis, scope, granted_by, granted_at,
            expiry, capture_profile, third_party_policy,
            vad_gate, third_party, retention, erasure, revokes_grant_ref, payload
        )
        SELECT
            gen_random_uuid(),
            '{_MEDIA_CAPTURE_GRANT_REF}',
            '{_MEDIA_CAPTURE_BASIS}',
            '{_MEDIA_CAPTURE_SCOPE}',
            'operator',
            now(),
            NULL,
            '{_MEDIA_CAPTURE_CAPTURE_PROFILE}'::jsonb,
            'degrade',
            '{{"enabled": false}}'::jsonb,
            '{{"policy": "degrade"}}'::jsonb,
            '{{"hard_retention_days": null}}'::jsonb,
            '{{"supported": false}}'::jsonb,
            NULL,
            '{{"note": "standing media-capture grant seeded by migration a9f3c2d7b6e1, owner ruling 2026-07-30 on #4172 (#4492)"}}'::jsonb
        WHERE NOT EXISTS (
            SELECT 1 FROM heimdal_consent_grant
            WHERE grant_ref = '{_MEDIA_CAPTURE_GRANT_REF}'
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "HEIM media-capture consent grant is forward-only; heimdal_consent_grant "
        "is append-only (HEIM-1) and its trigger rejects DELETE. Revoke the grant "
        "with an appended revocation row instead of removing the seed."
    )
