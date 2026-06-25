from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest


def _marker_expr(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:]
    return ""


def _normalize_debug_env() -> None:
    raw = os.environ.get("DEBUG")
    if raw is None:
        return
    if raw.strip().lower() in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return
    # Test collection imports settings early; keep invalid local shell values
    # from breaking pytest bootstrap.
    os.environ["DEBUG"] = "false"


# Keep the repo's default unit-test run deterministic even if the developer has
# DATABASE_URL/DB_DSN exported in their shell.
#
# This is intentionally evaluated before importing app modules.
_mark_expr = _marker_expr(sys.argv).strip().lower()
_normalize_debug_env()
if "not pg" in _mark_expr:
    os.environ["STORE_BACKEND"] = "memory"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("DB_DSN", None)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class StoredObject:
    kind: str | None
    source_ref: str | None
    payload: dict[str, Any]
    embedding: list[float]
    model: str


class StubVectorIndex:
    def __init__(self) -> None:
        self.store: dict[UUID, StoredObject] = {}

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
        identity: Any | None = None,
    ) -> None:
        self.store[object_id] = StoredObject(
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=list(embedding),
            model=model,
        )

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        if not self.store:
            return []
        query_vec = list(embedding)
        results: list[Any] = []
        for object_id, stored in self.store.items():
            if filters and not all(stored.payload.get(k) == v for k, v in filters.items()):
                continue
            score = sum(a * b for a, b in zip(query_vec, stored.embedding, strict=False))
            from app.search.vector_index import VectorResult  # noqa: PLC0415

            results.append(VectorResult(object_id=object_id, score=score, payload=stored.payload))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:k]


@pytest.fixture
def stub_index(monkeypatch: pytest.MonkeyPatch) -> StubVectorIndex:
    import app.search as search_module  # noqa: PLC0415
    import app.search.service as search_service_module  # noqa: PLC0415
    from app.search import get_vector_index as original_get_vector_index  # noqa: PLC0415

    index = StubVectorIndex()

    def _get_index() -> StubVectorIndex:
        return index

    monkeypatch.setattr(search_module, "get_vector_index", _get_index)
    monkeypatch.setattr(search_service_module, "get_vector_index", _get_index)
    if hasattr(original_get_vector_index, "cache_clear"):
        original_get_vector_index.cache_clear()
    return index


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure a clean LLM environment for each test."""

    from app.config import llm as llm_config

    keys = [
        "LLM_PROVIDER",
        "LLM_MODEL",
        "EMBED_MODEL",
        "LLM_FORCE_PROVIDER",
        "LLM_FORCE_MODEL",
        "LLM_PROVIDER_ENFORCE",
        "OLLAMA_HOST",
        "OLLAMA_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    yield monkeypatch


@pytest.fixture(autouse=True)
def force_memory_store_for_non_pg(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Keep non-pg tests independent of DATABASE_URL/DB_DSN."""

    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    yield monkeypatch


@pytest.fixture(autouse=True)
def default_pg_dsn_for_pg_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Provide the standard local Postgres DSN for pg-marked tests when unset."""

    if (
        request.node.get_closest_marker("pg") is not None
        and os.getenv("DATABASE_URL") is None
        and os.getenv("DB_DSN") is None
    ):
        monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    yield monkeypatch


@pytest.fixture(autouse=True)
def default_vault_layout_env(monkeypatch: pytest.MonkeyPatch):
    """Provide explicit test defaults for vault layout env.

    Runtime code must not assume folder names; tests set explicit defaults to
    keep behavior deterministic and avoid implicit fallbacks.

    This fixture never overrides a value that is already set.
    """

    if os.getenv("VAULT_SYSTEM_DIR_REL") is None:
        monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "⚙️ System")
    if os.getenv("VAULT_INBOX_DIR_REL") is None:
        monkeypatch.setenv("VAULT_INBOX_DIR_REL", "📥 Inbox")
    if os.getenv("VAULT_DESK_DIR_REL") is None:
        monkeypatch.setenv("VAULT_DESK_DIR_REL", "🛠️ Workbench")

    yield monkeypatch


def pytest_addoption(parser) -> None:
    """Provide minimal timeout flags when pytest-timeout is unavailable."""

    group = parser.getgroup("timeout", "timeout control")
    try:
        group.addoption(
            "--timeout",
            action="store",
            type=float,
            dest="timeout",
            default=None,
            help="No-op stub for pytest-timeout's --timeout option.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--timeout-method",
            action="store",
            dest="timeout_method",
            default="signal",
            help="No-op stub for pytest-timeout's --timeout-method option.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--faulthandler-timeout",
            action="store",
            type=float,
            dest="faulthandler_timeout",
            default=None,
            help="No-op stub for pytest-faulthandler's --faulthandler-timeout option.",
        )
    except ValueError:
        pass


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "pg: marks tests requiring Postgres")

    # Fail loud if a non-zero --timeout was requested but the real pytest-timeout
    # plugin is not active. Otherwise the no-op stub above silently absorbs the
    # flag and the suite runs with NO per-test timeout — exactly the failure mode
    # behind the intermittent 22-min CI hangs (#2259): a hung test then has no
    # safety net at all. A missing/incompatible pytest-timeout must break the
    # build, not quietly disarm the watchdog.
    requested = getattr(config.option, "timeout", None)
    plugins = config.pluginmanager
    has_real_timeout = plugins.hasplugin("timeout") or plugins.hasplugin(
        "pytest_timeout"
    )
    if requested and not has_real_timeout:
        raise pytest.UsageError(
            f"--timeout={requested} was requested but the pytest-timeout plugin "
            "is not active; the per-test hang watchdog is disarmed. Install "
            "pytest-timeout (see dev-requirements.txt) or remove the --timeout "
            "flag. Refusing to run unguarded — see #2259."
        )
