from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import configure_metrics
from app.settings import settings


def test_metrics_endpoint_available():
    original = settings.metrics_enabled
    try:
        settings.metrics_enabled = True
        app = FastAPI()
        configure_metrics(app)
        with TestClient(app) as client:
            response = client.get("/metrics")
            assert response.status_code == 200
            assert b"http_requests" in response.content
    finally:
        settings.metrics_enabled = original
