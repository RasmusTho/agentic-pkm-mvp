from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVISION = ROOT / "app/alembic/versions/f4a05a4b0001_mvr05a4_ingest_projection_binding_keys.py"


def test_membership_key_and_chunk_fk_follow_effective_lineage() -> None:
    source = REVISION.read_text()
    assert "ARRAY['id']" in source
    assert "ARRAY['object_id','set_id']" in source
    assert "FOREIGN KEY (vault_binding_id, chunk_id)" in source
    assert "REFERENCES public.chunks (vault_binding_id, id)" in source
    assert "chunks inbound FK census is not exactly one" in source
    assert "child_ns.nspname <> 'public'" in source


def test_ingest_rekey_reuses_delivered_binding_or_fails_unchanged() -> None:
    source = REVISION.read_text()
    assert "missing delivered binding invariant" in source
    assert "never assigns bindings" in source
    assert "LOCK TABLE public.chunks" in source
    assert "UPDATE public" not in source
    assert "CREATE OR REPLACE VIEW public.view_chunks_missing_embeddings" in source
    assert "e.vault_binding_id=c.vault_binding_id" in source
