from __future__ import annotations

from contextlib import contextmanager

import pytest


@pytest.fixture
def admitted_bws_caller(monkeypatch):
    """Model a caller that already passed host admission for deploy-core tests.

    Admission ownership and the worker's reservation lifetime are exercised
    directly in tests/ops/test_bws_installation_admission.py and
    tests/ops/test_postgres_deploy_bws_installation.py.
    """
    from app.ops import bws_installation_admission

    @contextmanager
    def reservation(channel):
        if channel not in {"dev", "test", "prod"}:
            raise AssertionError("unexpected deployment channel")
        yield

    monkeypatch.setattr(bws_installation_admission, "shared_caller_reservation", reservation)
    return reservation
