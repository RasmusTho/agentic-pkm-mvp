from fastapi.testclient import TestClient

from app.api.app import app
from app.orientation.runtime import build_orientation_frame


def test_orientation_returns_frame_without_query() -> None:
    client = TestClient(app)
    resp = client.get('/api/orientation')
    assert resp.status_code == 200
    body = resp.json()
    assert body.get('frame')


def test_orientation_explanation_shape() -> None:
    client = TestClient(app)
    resp = client.get('/api/orientation')
    assert resp.status_code == 200
    explanation = (resp.json().get('explanation') or {})
    assert 'leave_point' in explanation
    assert 'open_items' in explanation
    assert 'notable_change' in explanation


def test_orientation_is_read_only() -> None:
    client = TestClient(app)
    resp = client.get('/api/orientation')
    assert resp.status_code == 200
    body = resp.json()
    assert body.get('read_only') is True
    assert body.get('mutation_intents') == []


def test_orientation_does_not_evaluate_write_guard(monkeypatch) -> None:
    def _fail() -> None:
        raise AssertionError("write guard should not be evaluated for orientation frame")

    monkeypatch.setattr("app.observability.status_service.DEFAULT_CONTRACT.evaluate", _fail)
    frame = build_orientation_frame()
    assert frame.read_only is True
