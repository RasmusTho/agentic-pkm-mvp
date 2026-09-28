"""Shared fixtures for the provider-free Model Inquiry role intent surface.

Every helper here works through the production surfaces: the committed intent
example, the declared provider census, and the host secret contract's runtime
env-file delivery. Nothing fabricates a provider, model, endpoint, or
environment-variable name on the caller side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from app.builderops.model_access_resolver import BuilderModelAccessResolver

from app.builderops.model_inquiry_adapters import INQUIRY_INTENT_CONFIG_ENV
from app.ops.host_secret_bootstrap import HOST_SECRET_RUNTIME_ENV_FILE


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_INTENT_PATH = (
    REPO_ROOT / "config" / "builderops" / "model_inquiry_role_intent.example.json"
)
COMMITTED_INTENT_CONFIG: dict[str, Any] = json.loads(
    COMMITTED_INTENT_PATH.read_text(encoding="utf-8")
)
CENSUS_PATH = REPO_ROOT / "docs" / "settings" / "models" / "providers.yaml"
CONTRACT_PATH = REPO_ROOT / "config" / "secrets" / "host_secret_contract.json"

# Declared api-key grammar: trimmed, printable, 20-512 characters.
DECLARED_TEST_CREDENTIALS = {
    "ANTHROPIC_API_KEY": "declared-anthropic-credential-0001",
    "OPENAI_API_KEY": "declared-openai-credential-0001",
}


def intent_config(**overrides: Any) -> dict[str, Any]:
    """Return the committed intent example, optionally with top-level overrides."""
    payload = json.loads(json.dumps(COMMITTED_INTENT_CONFIG))
    payload.update(overrides)
    return payload


def intent_env(**overrides: Any) -> dict[str, str]:
    """Return an environment carrying only the value-free intent configuration."""
    return {INQUIRY_INTENT_CONFIG_ENV: json.dumps(intent_config(**overrides))}


def runtime_secret_file(
    directory: Path,
    values: dict[str, str] | None = None,
) -> Path:
    """Materialize the mode-0600 runtime surface the host secret bootstrap writes."""
    selected = DECLARED_TEST_CREDENTIALS if values is None else values
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "host-secret-runtime.env"
    path.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(selected.items())),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def resolver_for_targets(
    directory: Path,
    targets: dict[str, tuple[str, str]],
) -> "BuilderModelAccessResolver":
    """Build a resolver whose declared sources map both roles to *targets*."""
    from app.builderops.model_access_resolver import BuilderModelAccessResolver

    return BuilderModelAccessResolver.from_declared_sources(
        census_path=census_with_role_targets(directory, targets),
        contract_path=CONTRACT_PATH,
    )


def provisioned_env(directory: Path, **overrides: Any) -> dict[str, str]:
    """Return intent configuration plus a declared, resolvable credential surface."""
    return {
        **intent_env(**overrides),
        HOST_SECRET_RUNTIME_ENV_FILE: str(runtime_secret_file(directory)),
    }


def census_with_role_targets(
    directory: Path,
    targets: dict[str, tuple[str, str]],
) -> Path:
    """Write a census whose configured Sol capability points at one test target.

    Used to prove that a colliding or non-provider policy mapping is refused by
    the resolver before any model call, without touching the shipped census.
    """
    directory.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    provider_id, model = next(iter(targets.values()))
    for profiles in payload["runtime_channels"]["builder_execution"].values():
        profiles["sol"].update(
            {
                "provider": provider_id,
                "model": model,
                "selectable_models": [model],
                "model_reasoning_efforts": {model: "high"},
                "selection_intent_models": {
                    "strong_reasoning": model,
                    "verification": model,
                },
                "requires": [],
            }
        )
    path = directory / "providers.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path
