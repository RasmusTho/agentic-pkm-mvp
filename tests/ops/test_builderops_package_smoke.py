from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _clean_builder_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("LLM_PROVIDER", None)
    env["LLM_PROVIDER_ENFORCE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    for key in (
        "BUILDEROPS_DATABASE_URL",
        "BUILDEROPS_DATABASE_URL_FILE",
        "BUILDEROPS_CREDENTIAL_MANIFEST_FILE",
        "DATABASE_URL",
        "VAULT_ROOT",
    ):
        env.pop(key, None)
    return env


def test_minimal_builder_package_boots_without_product_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile.builderops").read_text(encoding="utf-8")
    manifest = (ROOT / "requirements-builderops.txt").read_text(encoding="utf-8")
    assert "COPY requirements-builderops.txt ./" in dockerfile
    assert "requirements.txt" not in dockerfile
    assert "pip install --no-cache-dir -r requirements-builderops.txt" in dockerfile
    assert "fastapi==" in manifest
    assert "psycopg[binary]==" in manifest
    assert "pydantic==" in manifest
    assert "uvicorn==" in manifest
    assert "faster-whisper" not in manifest
    assert "langgraph" not in manifest

    code = """
import json
import sys

from app.builderops.control_plane import migrate, service, worker

results = {}
for name, callback in (
    ("api", service.production_app),
    ("worker", worker.main),
    ("migrate", migrate.main),
):
    try:
        callback()
    except Exception as exc:
        results[name] = f"{type(exc).__name__}: {exc}"
    else:
        results[name] = "unexpected-success"
print(json.dumps({
    "results": results,
    "llm_loaded": "app.config.llm" in sys.modules,
    "product_loaded": any(
        name == "app.main" or name.startswith(("app.api.", "app.instance.", "app.vault."))
        for name in sys.modules
    ),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=_clean_builder_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "BUILDEROPS_CREDENTIAL_MANIFEST_FILE is required" in payload["results"]["api"]
    assert payload["results"]["worker"].endswith(
        "BUILDEROPS_DATABASE_URL is required for production BuilderOps"
    )
    assert payload["results"]["migrate"].endswith(
        "BUILDEROPS_DATABASE_URL is required for production BuilderOps"
    )
    assert payload["llm_loaded"] is False
    assert payload["product_loaded"] is False
