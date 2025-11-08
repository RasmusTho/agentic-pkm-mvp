from .api import ingest_object  # minimal always available

try:
    from .lifecycle import normalize_payload, handle_post_ingest  # legacy/full
except Exception:
    try:
        from .api import normalize_payload, handle_post_ingest  # fallback
    except Exception:
        pass

__all__ = [n for n in ("ingest_object", "normalize_payload", "handle_post_ingest") if n in globals()]
