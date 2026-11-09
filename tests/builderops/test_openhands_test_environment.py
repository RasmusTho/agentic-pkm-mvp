"""The prepared environment only accepts its pinned artifacts and covered tasks."""

import hashlib
import json

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_test_environment as environment


LOCK = ("pytest==9.0.3 --hash=sha256:" + "a" * 64 + "\n").encode()


def test_preflight_accepts_covered_requirements_and_rejects_missing():
    environment.check_requirements(LOCK, {"requirements.txt": "pytest==9.0.3\n"})
    with pytest.raises(delivery.DeliveryError, match="does not cover"):
        environment.check_requirements(LOCK, {"requirements.txt": "pytest==8.0.0\n"})


@pytest.mark.parametrize("line", ["--index-url https://example.invalid", "pytest @ https://example.invalid/x.whl"])
def test_preflight_rejects_remote_requirements(line):
    with pytest.raises(delivery.DeliveryError):
        environment.check_requirements(LOCK, {"requirements.txt": line})


def test_preflight_rejects_lock_directives():
    with pytest.raises(delivery.DeliveryError, match="Invalid"):
        environment.check_requirements(b"--index-url https://example.invalid\n", {})


def test_preflight_rejects_unprepared_extras():
    with pytest.raises(delivery.DeliveryError, match="does not cover"):
        environment.check_requirements(LOCK, {"requirements.txt": "pytest[new-extra]==9.0.3"})


def test_incomplete_preparation_cannot_be_used(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "_platform", lambda: None)
    path = tmp_path / "test-environments" / hashlib.sha256(LOCK).hexdigest()
    path.mkdir(parents=True)
    with pytest.raises(delivery.DeliveryError, match="missing or incomplete"):
        environment.environment(tmp_path, LOCK)
    (path / "receipt.json").write_text(json.dumps({"version": 1, "lock_sha256": "wrong"}))
    with pytest.raises(delivery.DeliveryError, match="missing or incomplete"):
        environment.environment(tmp_path, LOCK)
