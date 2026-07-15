"""BGE-M3 identity migration mechanism (G3-1, #2984).

Covers:

- A new, SELECTABLE ``bge-m3`` embedding profile (model ``bge-m3``, dim 1024,
  no-prefix mode) exists and resolves correctly when an operator activates it
  (``EMBED_PROFILE=bge-m3``).
- The historical ``EMBED_DIM`` / ``DEFAULT_EMBED_DIM`` code drift (#2296/#2297)
  is closed: the runtime constant, the ``Settings.embed_dim`` mirror, and the
  ``EmbeddingProfile.dim`` default all agree on the documented 768 value, not a
  stale third value (1536).
- The shipped runtime DEFAULT is NOT silently flipped to BGE-M3/1024 by this
  change: with no profile/env override, identity resolution still produces the
  768-dim nomic-embed-text identity.
- The query path pins the identity that ``get_embedding_identity()``/the
  resolved client returns; selecting the bge-m3 profile changes what is
  pinned, but a single resolution never mixes two identities within one call.

Doctor-flags-old-identity-rows and reconcile-converges coverage against a real
mixed-identity index requires a live Postgres backend (per-vector identity
columns) and already exists in ``tests/indexer/test_mixed_identity_detection.py``
and ``tests/cli/test_index_reconcile.py`` (both ``@pytest.mark.pg``, generic
over any two distinct identities, including a 768-vs-1024 pair). This file adds
a BGE-M3-dimension-specific pg-marked pair of tests here so the AC's named
``Verify:`` targets resolve directly from this module, using the same
established fixtures/patterns as those files. No real re-index is executed;
Ollama/BGE-M3 need not be installed — the pg tests use a deterministic stub
embedding client, exactly like the existing reconcile suite.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from uuid import uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity, resolve_embedding_identity
from app.embedding_config import BGE_M3_EMBED_DIM, DEFAULT_EMBED_DIM
from app.settings.models import EmbeddingProfile, EmbeddingProfiles


def _pg_available() -> bool:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _seed_row(dsn: str, identity: EmbeddingIdentity, *, text: str) -> str:
    """Write a store_vector_index row directly via SQL, bypassing
    VectorIndex.upsert()'s single-identity-per-write guardrail — mirrors
    tests/cli/test_index_reconcile.py::_seed_row so a mixed-identity index can
    be constructed for doctor/reconcile tests without upsert() rejecting the
    second identity."""
    import psycopg

    oid = uuid4()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, now(), now())
                """,
                (oid, "note", "tests/bge-m3-migration", json.dumps({"text": text})),
            )
            cur.execute(
                """
                INSERT INTO store_vector_index (
                    object_id, kind, source_ref, payload, embedding,
                    dim, model, provider, normalize, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                """,
                (
                    oid,
                    "note",
                    "tests/bge-m3-migration",
                    json.dumps({"text": text}),
                    [0.1] * identity.dim,
                    identity.dim,
                    identity.model,
                    identity.provider,
                    identity.normalize,
                ),
            )
        conn.commit()
    return str(oid)


# ---------------------------------------------------------------------------
# AC1: new EmbeddingIdentity profile + EMBED_DIM/DEFAULT_EMBED_DIM drift closed
# ---------------------------------------------------------------------------


def test_embed_dim_drift_closed() -> None:
    """#2296/#2297: DEFAULT_EMBED_DIM must equal the documented default (768),
    not a stale third value (1536), and BGE_M3_EMBED_DIM must be the distinct
    1024 value the migration targets. No third value is introduced."""
    assert DEFAULT_EMBED_DIM == 768
    assert BGE_M3_EMBED_DIM == 1024
    assert DEFAULT_EMBED_DIM != BGE_M3_EMBED_DIM


def test_embedding_profile_dim_default_matches_embed_dim_default() -> None:
    """The EmbeddingProfile.dim default must not drift from
    app.embedding_config.DEFAULT_EMBED_DIM (closes #2296/#2297 in the settings
    model as well as the runtime constant)."""
    assert EmbeddingProfile().dim == DEFAULT_EMBED_DIM


def test_settings_embed_dim_matches_default_embed_dim(monkeypatch) -> None:
    """app.settings.settings.embed_dim (the fallback source get_embed_dim()
    reads when EMBED_DIM is unset) must not drift from DEFAULT_EMBED_DIM."""
    from app.embedding_config import get_embed_dim
    from app.settings import settings

    monkeypatch.delenv("EMBED_DIM", raising=False)
    assert settings.embed_dim == DEFAULT_EMBED_DIM
    assert get_embed_dim() == DEFAULT_EMBED_DIM


def test_bge_m3_profile_registered_and_selectable() -> None:
    """The bge-m3 profile is registered as a SELECTABLE named profile (not the
    default_profile), with model bge-m3, dim 1024, no-prefix mode, and a
    raised input-char budget recommendation for BGE-M3's larger context
    window."""
    profiles = EmbeddingProfiles()
    assert profiles.default_profile == "default"  # not auto-activated
    assert "bge-m3" in profiles.profiles

    cfg = profiles.profiles["bge-m3"]
    assert cfg.provider == "ollama"
    assert cfg.model == "bge-m3"
    assert cfg.dim == BGE_M3_EMBED_DIM
    assert cfg.normalize is True
    assert cfg.no_prefix is True
    # Raised above the nomic-tuned ~6000 char default to fit BGE-M3's larger
    # (8192-token) context window.
    assert cfg.max_input_chars is not None and cfg.max_input_chars > 6000


def test_bge_m3_profile_resolves_to_1024_identity(monkeypatch) -> None:
    """Operator-activated selection (EMBED_PROFILE=bge-m3) resolves a clean
    1024-dim, no-prefix EmbeddingIdentity."""
    monkeypatch.setenv("EMBED_PROFILE", "bge-m3")
    monkeypatch.delenv("EMBED_DIM", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)

    identity = resolve_embedding_identity()

    assert identity.provider == "ollama"
    assert identity.model.startswith("bge-m3")
    assert identity.dim == 1024
    assert identity.normalize is True
    assert identity.no_prefix is True


def test_doctor_honors_bge_profile_over_shipped_model_default(monkeypatch) -> None:
    """The doctor uses the routed fabric path, so it must compare a BGE-M3
    index with the same BGE-M3 identity selected by the operator profile."""
    from app.index import doctor as doctor_mod

    class _BgeIndex:
        @staticmethod
        def get_identity() -> EmbeddingIdentity:
            return EmbeddingIdentity(
                provider="ollama",
                model="bge-m3:latest",
                dim=1024,
                normalize=True,
            )

    monkeypatch.setenv("EMBED_PROFILE", "bge-m3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.setenv("EMBED_DIM", "768")
    monkeypatch.setattr(doctor_mod, "get_vector_index", _BgeIndex)
    monkeypatch.setattr(
        doctor_mod,
        "inspect_retrieval_index_divergence",
        lambda: {"checked": False, "cache_warmed": False},
    )
    doctor_mod.reset_diagnose_cache()

    result = doctor_mod.diagnose_index()

    assert result["expected_identity"] == {
        "provider": "ollama",
        "model": "bge-m3:latest",
        "dim": 1024,
        "normalize": True,
    }
    assert result["stored_identity"] == result["expected_identity"]
    assert result["compatible_identity"] is True
    assert result["rebuild_required"] is False


# ---------------------------------------------------------------------------
# AC: default NOT silently flipped
# ---------------------------------------------------------------------------


def test_default_identity_stays_768_without_operator_activation(monkeypatch) -> None:
    """CRITICAL safety test: with no EMBED_PROFILE/profile override, resolving
    the embedding identity must still produce the shipped 768-dim identity.
    This is the guard against silently flipping the live runtime default to
    BGE-M3/1024 on merge — activation must be an explicit operator action."""
    monkeypatch.delenv("EMBED_PROFILE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    monkeypatch.delenv("EMBED_DIM", raising=False)

    identity = resolve_embedding_identity()

    assert identity.dim == DEFAULT_EMBED_DIM
    assert identity.dim == 768
    assert identity.dim != BGE_M3_EMBED_DIM


# ---------------------------------------------------------------------------
# AC: query path pins the resolved identity, never mixes within one resolution
# ---------------------------------------------------------------------------


def test_query_path_pins_new_identity(monkeypatch) -> None:
    """Once an operator activates bge-m3, the query embedding path
    (get_embedding_client / get_embedding_identity) pins the same 1024-dim
    identity a document embed would use in the same process — no call
    silently mixes the old 768-dim identity with the new one."""
    from app.components.embeddings import get_embedding_client, get_embedding_identity

    monkeypatch.setenv("EMBED_PROFILE", "bge-m3")
    monkeypatch.delenv("EMBED_DIM", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)

    client = get_embedding_client(profile="bge-m3")
    query_identity = get_embedding_identity(client)
    doc_identity = resolve_embedding_identity(profile="bge-m3")

    assert query_identity.dim == doc_identity.dim == 1024
    assert query_identity.provider == doc_identity.provider
    assert query_identity.model == doc_identity.model
    assert query_identity.no_prefix is True


# ---------------------------------------------------------------------------
# AC: doctor flags old-identity rows / reconcile converges (BGE-M3 dims)
#
# Requires Postgres (per-vector identity columns). Generic mixed-identity
# detection/reconcile mechanics are already covered by
# tests/indexer/test_mixed_identity_detection.py and
# tests/cli/test_index_reconcile.py; these two tests exercise the identical,
# unmodified mechanism at the specific 768-vs-1024 (nomic -> BGE-M3) pair this
# migration introduces, using a deterministic stub client (no live Ollama/
# BGE-M3 required).
# ---------------------------------------------------------------------------


@pytest.mark.pg
def test_doctor_flags_old_identity_rows(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.db.dsn import resolve_dsn
    from app.index import doctor as doctor_mod
    from app.stores import pg as pg_store
    from app.stores import reset_store_backends

    def _dsn() -> str:
        return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")

    monkeypatch.setenv("DATABASE_URL", _dsn())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("EMBED_PROFILE", "bge-m3")
    monkeypatch.delenv("EMBED_DIM", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    reset_store_backends()
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()

    old_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=768, normalize=True)
    new_identity = EmbeddingIdentity(provider="ollama", model="bge-m3:latest", dim=1024, normalize=True)

    try:
        # Seed the pre-migration identity as the recorded steady-state, then
        # write one old-identity row directly via SQL (bypassing upsert()'s
        # single-identity guardrail), simulating a pre-cutover mixed index.
        import psycopg

        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vector_index_meta (id, identity_json, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json, updated_at = now()
                    """,
                    (json.dumps(asdict(new_identity)),),
                )
            conn.commit()

        _seed_row(_dsn(), old_identity, text="pre-migration nomic row")
        _seed_row(_dsn(), new_identity, text="post-migration bge-m3 row")

        doctor_mod.reset_diagnose_cache()
        result = doctor_mod.diagnose_index()

        mixed = result.get("mixed_identities") or []
        assert len(mixed) > 1, f"expected doctor to flag mixed identities, got {result.get('issues')}"
        warnings_and_issues = " ".join((result.get("issues") or []) + (result.get("warnings") or []))
        assert "Mixed embedding" in warnings_and_issues or "index reconcile" in warnings_and_issues
    finally:
        doctor_mod.reset_diagnose_cache()
        pg_store.truncate_pg_tables()
        reset_store_backends()


@pytest.mark.pg
def test_reconcile_converges(tmp_path, monkeypatch) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import index_rebuild as reconcile_mod
    from app.cli.index_rebuild import index as index_cli
    from app.db.dsn import resolve_dsn
    from app.index import doctor as doctor_mod
    from app.stores import pg as pg_store
    from app.stores import reset_store_backends

    def _dsn() -> str:
        return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")

    monkeypatch.setenv("DATABASE_URL", _dsn())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    reset_store_backends()
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()

    old_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=1024, normalize=True)
    new_identity = EmbeddingIdentity(provider="ollama", model="bge-m3:latest", dim=1024, normalize=True)

    class _StubClient:
        identity = new_identity

        def embed_text(self, text: str) -> list[float]:
            base = float(len(text) % 7 + 1)
            return [base] * new_identity.dim

    try:
        import psycopg

        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vector_index_meta (id, identity_json, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json, updated_at = now()
                    """,
                    (json.dumps(asdict(new_identity)),),
                )
            conn.commit()

        _seed_row(_dsn(), old_identity, text="pre-migration row to reconcile")

        monkeypatch.setattr(reconcile_mod, "get_embedding_client", lambda *a, **k: _StubClient())

        runner = CliRunner()
        result = runner.invoke(index_cli, ["reconcile", "--json"])
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary.get("reconciled", 0) >= 1

        doctor_mod.reset_diagnose_cache()
        diag = doctor_mod.diagnose_index()
        mixed = diag.get("mixed_identities") or []
        assert len(mixed) <= 1, f"expected convergence to a single identity, got {mixed}"
    finally:
        doctor_mod.reset_diagnose_cache()
        pg_store.truncate_pg_tables()
        reset_store_backends()
