"""Temporary paths reachable by a distinct runtime UID in root-only tests."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

import pytest


def runtime_reachable_test_root(
    fallback: Path, request: pytest.FixtureRequest
) -> Path:
    """Use a traversable /tmp fixture when tests can drop from root to another UID."""

    if os.geteuid() != 0:
        return fallback

    path = Path(tempfile.mkdtemp(prefix="agentic-runtime-test-", dir="/tmp"))
    path.chmod(0o711)
    request.addfinalizer(lambda: shutil.rmtree(path, ignore_errors=True))
    return path
