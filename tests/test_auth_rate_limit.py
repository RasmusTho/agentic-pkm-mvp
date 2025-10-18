import uuid

from app.auth import configure_rate_limit_storage, limiter
from app.settings import settings


def _reset_auth_state():
    settings.api_key = None
    settings.rate_limit_enabled = False
    configure_rate_limit_storage()
    limiter.reset()


def test_api_key_required_when_set(client):
    original = settings.api_key
    try:
        settings.api_key = "secret-key"
        response = client.get("/items")
        assert response.status_code == 401

        ok = client.get("/items", headers={"X-API-Key": "secret-key"})
        assert ok.status_code == 200
    finally:
        settings.api_key = original
        configure_rate_limit_storage()


def test_rate_limit_triggers_429(client):
    original_enabled = settings.rate_limit_enabled
    original_limit = settings.rate_limit_default
    try:
        settings.rate_limit_enabled = True
        settings.rate_limit_default = "2/minute"
        configure_rate_limit_storage()
        limiter.reset()

        for idx in range(2):
            name = f"rl-{uuid.uuid4()}-{idx}"
            r = client.post("/items", params={"name": name})
            assert r.status_code == 200

        overflow = client.post("/items", params={"name": f"rl-{uuid.uuid4()}-overflow"})
        assert overflow.status_code == 429
        assert overflow.json()["detail"].lower().startswith("rate limit")
    finally:
        settings.rate_limit_enabled = original_enabled
        settings.rate_limit_default = original_limit
        configure_rate_limit_storage()
        limiter.reset()
