import duckdb

from app.settings import settings


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["checks"]["database"]["status"] == "ok"
    assert data["checks"]["duckdb"]["status"] == "ok"
    assert data["checks"]["provenance"]["status"] == "ok"


def test_health_duckdb_failure(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise duckdb.Error("boom")

    monkeypatch.setattr("app.health.duckdb.connect", _boom)

    r = client.get("/health")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["status"] == "degraded"
    assert detail["checks"]["duckdb"]["status"] == "error"
    assert "boom" in detail["checks"]["duckdb"]["detail"]


def test_version_returns_settings(client):
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json() == {"version": settings.app_version}
