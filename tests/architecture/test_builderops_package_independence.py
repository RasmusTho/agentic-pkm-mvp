from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _clean_builder_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("LLM_PROVIDER", None)
    env["LLM_PROVIDER_ENFORCE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)
    for key in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "VAULT_ROOT",
        "BUILDEROPS_DATABASE_URL",
        "BUILDEROPS_DATABASE_URL_FILE",
        "BUILDEROPS_CREDENTIAL_MANIFEST_FILE",
    ):
        env.pop(key, None)
    return env


def test_builder_boot_does_not_load_product_configuration() -> None:
    code = """
import json
import sys

before = set(sys.modules)
outcomes = {}
for module in (
    "app.builderops.control_plane.service",
    "app.builderops.control_plane.worker",
    "app.builderops.control_plane.migrate",
):
    try:
        __import__(module)
        outcomes[module] = "ok"
    except Exception as exc:
        outcomes[module] = f"{type(exc).__name__}: {exc}"
new_modules = sorted(
    name
    for name in sys.modules
    if name not in before and (name == "app" or name.startswith("app."))
)
print(json.dumps({
    "outcomes": outcomes,
    "llm_loaded": "app.config.llm" in sys.modules,
    "product_modules": [
        name for name in new_modules
        if name in {"app.api", "app.api.app", "app.main", "app.instance", "app.vault"}
        or name.startswith(("app.api.", "app.instance.", "app.vault."))
    ],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_clean_builder_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcomes"] == {
        "app.builderops.control_plane.service": "ok",
        "app.builderops.control_plane.worker": "ok",
        "app.builderops.control_plane.migrate": "ok",
    }
    assert payload["llm_loaded"] is False
    assert payload["product_modules"] == []
