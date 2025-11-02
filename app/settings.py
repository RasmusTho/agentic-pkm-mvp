# Shim: re-export settings efter flytt till app/_legacy
try:
    from ._legacy.settings import settings  # type: ignore
except Exception:
    class _Settings:
        DEBUG = False
        DATABASE_URL = None
    settings = _Settings()
__all__ = ["settings"]
