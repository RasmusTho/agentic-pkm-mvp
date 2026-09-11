"""Standalone, read-only Builder DevUI listener; never boot Product.

The managed Linux container uses host networking and a fixed loopback bind.
Only the retained VM102 receipt transport is admitted in this slice. Other
provider transports remain refused until independently admitted by their owners.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
import os
from pathlib import Path
import re
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.builderops.devui_composition import compose_owner_snapshot
from app.builderops.devui_overview import compose_overview_view
from app.builderops.devui_overview_inputs import derive_overview_inputs
from app.builderops.devui_receipts import read_vm102_receipt_provider


class RuntimeConfigurationError(ValueError):
    """Explicit runtime preconditions are missing; do not bind a listener."""


@dataclass(frozen=True)
class RuntimeConfiguration:
    source_sha: str
    image_digest: str
    config_fingerprint: str
    receipt_dir: Path


def load_configuration(environment: Mapping[str, str]) -> RuntimeConfiguration:
    """Read only explicitly addressed Builder configuration; no dotenv/settings."""
    values = [
        environment.get(key, "")
        for key in (
            "DEVUI_SOURCE_SHA",
            "DEVUI_IMAGE_DIGEST",
            "DEVUI_CONFIG_FINGERPRINT",
        )
    ]
    for value, pattern in zip(
        values, (r"[a-f0-9]{40}", r"sha256:[a-f0-9]{64}", r"sha256:[a-f0-9]{64}")
    ):
        if re.fullmatch(pattern, value) is None or set(value.removeprefix("sha256:")) == {"0"}:
            raise RuntimeConfigurationError(
                "immutable Builder runtime identity is missing or invalid"
            )
    if values[0] != environment.get("VCS_REF"):
        raise RuntimeConfigurationError("runtime source does not match the image-baked source")
    if any(
        environment.get(key)
        for key in (
            "PKM_ENVIRONMENT",
            "DATABASE_URL",
            "DB_DSN",
            "VAULT_ROOT",
            "API_KEY",
        )
    ):
        raise RuntimeConfigurationError("Product runtime configuration is forbidden")
    raw = environment.get("DEVUI_VM102_RECEIPT_DIR", "")
    path = Path(raw)
    try:
        if not raw or not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise RuntimeConfigurationError("Builder receipt source must be an existing directory")
        # Check actual read access, without creating a receipt or directory.
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError as exc:
        raise RuntimeConfigurationError("Builder receipt source is unavailable") from exc
    return RuntimeConfiguration(values[0], values[1], values[2], receipt_dir=path)


def _unavailable_provider() -> Any:
    raise RuntimeError("provider transport is not admitted in this runtime")


def _local_request(request: Request) -> bool:
    forwarded = {
        "forwarded",
        "via",
        "x-real-ip",
        "cf-connecting-ip",
        "true-client-ip",
        "x-client-ip",
        "x-envoy-external-address",
        "x-original-forwarded-for",
    }
    if any(name.startswith("x-forwarded-") or name in forwarded for name in request.headers):
        return False
    if request.headers.get("host") not in {"127.0.0.1:8113", "localhost:8113"}:
        return False
    try:
        return request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def create_app(configuration: RuntimeConfiguration) -> FastAPI:
    """Create only the narrow Builder listener, without Product routers/lifespan."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)

    def receipt_provider() -> dict[str, Any]:
        provider = read_vm102_receipt_provider(configuration.receipt_dir)
        if provider["status"] == "available":
            identities = [
                row["candidate_identity"] for row in provider["payload"]["receipts"].values()
            ]
            if any(
                candidate.get("source_sha") != configuration.source_sha
                or candidate.get("devui_image_digest") != configuration.image_digest
                or candidate.get("devui_config_fingerprint") != configuration.config_fingerprint
                for candidate in identities
            ):
                return {
                    "provider": provider["provider"],
                    "authority": provider["authority"],
                    "status": "refused",
                    "captured_at": None,
                    "snapshot": None,
                    "completeness": None,
                    "refusal": {
                        "code": "runtime_identity_mismatch",
                        "message": "VM102 evidence does not match this listener",
                        "details": {},
                    },
                }
        return provider

    @app.middleware("http")
    async def admit(request: Request, call_next: Any) -> Any:
        if not _local_request(request):
            return JSONResponse(
                {"detail": "DevUI requires direct local admission"}, status_code=403
            )
        if request.url.query:
            return JSONResponse(
                {"detail": "DevUI listener does not accept query parameters"}, status_code=400
            )
        return await call_next(request)

    @app.get("/api/devui/overview")
    def overview() -> dict[str, Any]:
        snapshot = compose_owner_snapshot(
            cockpit_reader=_unavailable_provider,
            ckm_reader=_unavailable_provider,
            receipt_reader=receipt_provider,
        )
        inputs = derive_overview_inputs(
            work_provider=snapshot["providers"]["work"],
            receipt_provider=snapshot["providers"]["vm102_evidence"],
        )
        return compose_overview_view(composition=snapshot, candidates=inputs)

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "source_sha": configuration.source_sha,
            "image_digest": configuration.image_digest,
            "config_fingerprint": configuration.config_fingerprint,
            "component_id": "devui_projection",
        }

    @app.get("/healthz")
    def liveness() -> dict[str, Any]:
        return {"listener_alive": True, "complete_dev_system_health": False}

    return app


def production_app() -> FastAPI:
    return create_app(load_configuration(os.environ))


def main() -> int:
    try:
        app = production_app()
    except RuntimeConfigurationError:
        print(
            "DevUI startup refused: explicit Builder runtime prerequisites are invalid",
            file=sys.stderr,
        )
        return 2
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8113, proxy_headers=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
