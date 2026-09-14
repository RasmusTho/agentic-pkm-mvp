"""Standalone, read-only Builder DevUI listener; never boot Product.

The managed Linux container uses host networking and a fixed loopback bind.
The finite managed source transports retain their existing owners and fail
independently. This listener never starts Product or an action boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.builderops.devui_assets import (
    CSP,
    INVENTORY_SHA256,
    ROUTES,
    CandidateAssetError,
    validate_packaged_assets,
)
from app.builderops.devui_composition import compose_owner_snapshot
from app.builderops.devui_focus import FocusContractError, compose_focus_view
from app.builderops.devui_focus_inputs import FocusInputError
from app.builderops.devui_overview import compose_overview_view
from app.builderops.devui_overview_inputs import derive_overview_inputs, bind_visual_focus_targets
from app.builderops.devui_receipts import read_first_read_observation_provider, read_vm102_receipt_provider
from app.builderops.devui_owner_facts import owner_fact_trust, read_owner_fact_transport
from app.builderops.devui_sources import (
    SourceConfiguration,
    SourceConfigurationError,
    load_source_configuration,
    read_managed_cockpit,
    read_managed_focus,
    read_managed_issue,
)

CANDIDATE_ROOT = Path(__file__).resolve().parents[2] / "devui-candidate"


class RuntimeConfigurationError(ValueError):
    """Explicit runtime preconditions are missing; do not bind a listener."""


@dataclass(frozen=True)
class RuntimeConfiguration:
    source_sha: str
    image_digest: str
    config_fingerprint: str
    receipt_dir: Path
    sources: SourceConfiguration


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
    try:
        sources = load_source_configuration(
            environment, candidate_root=CANDIDATE_ROOT, source_sha=values[0]
        )
    except SourceConfigurationError as exc:
        raise RuntimeConfigurationError("managed source configuration is invalid") from exc
    return RuntimeConfiguration(values[0], values[1], values[2], receipt_dir=path, sources=sources)


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

    def first_read_provider(request: Request) -> dict[str, Any]:
        def identity() -> dict[str, Any]:
            from app.builderops.devui_assets import ASSET_SHA256
            from app.builderops.devui_sources import _candidate_docs

            config = configuration.sources
            manifest_path = config.candidate_root / "manifest.json"
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw)
            validate_packaged_assets(config.candidate_root, source_sha=configuration.source_sha, repository=config.repository)
            _candidate_docs(config)
            if raw != manifest_path.read_bytes():
                raise ValueError("candidate manifest changed")
            # The retained full candidate includes activation-owned PostgreSQL
            # pins. This listener checks only the identity it actually serves.
            observation = json.loads((configuration.receipt_dir / "first-read/observation.json").read_bytes())
            candidate = dict(observation["candidate_identity"])
            candidate.update(source_sha=configuration.source_sha, devui_image_digest=configuration.image_digest,
                             control_plane_image_digest=configuration.image_digest,
                             devui_config_fingerprint=configuration.config_fingerprint)
            return {"candidate_identity": candidate, "origin": str(request.base_url).rstrip("/"),
                    "repository": config.repository, "assets": ASSET_SHA256,
                    "documents": {name: digest for name, digest in manifest["files"].items() if not name.startswith("assets/")},
                    "source": {"repository": config.repository, "authority_epoch": config.authority_epoch,
                               "grants": ["receipts:read", "status:read"]}}

        def source_read(binding: Mapping[str, Any]) -> Mapping[str, Any]:
            from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig

            config = configuration.sources
            if not config.repository or not config.authority_epoch:
                raise ValueError("source is not configured")
            with BuilderOpsControlPlaneClient(ClientConfig.from_env(config.api_environment), max_retries=0) as client:
                if client.status().get("authority_epoch") != config.authority_epoch:
                    raise ValueError("source epoch changed")
                task = client.get_task(repository=config.repository, task_id=binding["task_id"])
                issue = read_managed_issue(config, config.repository, str(binding["number"]))
                epoch = client.status().get("authority_epoch")
                return {"issue": issue, "task": task, "authority_epoch": epoch}

        return read_first_read_observation_provider(configuration.receipt_dir, listener_identity=identity, source_reader=source_read)

    def receipt_provider() -> dict[str, Any]:
        provider = read_vm102_receipt_provider(
            configuration.receipt_dir, require_typed_runtime=True
        )
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
        response: Response
        if not _local_request(request):
            response = JSONResponse(
                {"detail": "DevUI requires direct local admission"}, status_code=403
            )
        elif request.url.path not in {
            *ROUTES,
            "/api/devui/overview",
            "/api/devui/focus",
            "/version",
            "/healthz",
        }:
            response = JSONResponse({"detail": "Unknown DevUI route"}, status_code=404)
        elif request.method != "GET":
            response = JSONResponse({"detail": "DevUI admits GET only"}, status_code=405)
        else:
            try:
                query = request.scope["query_string"].decode("ascii")
                if request.url.path in {"/devui/focus", "/api/devui/focus"}:
                    if re.search(r"%(?![0-9a-fA-F]{2})", query):
                        raise ValueError()
                    pairs = parse_qsl(
                        query, keep_blank_values=True, strict_parsing=True, errors="strict"
                    )
                    if (
                        len(pairs) != 1
                        or pairs[0][0] != "subject"
                        or re.fullmatch(
                            r"(?:github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*|[a-z][a-z0-9_.:-]{2,127})",
                            pairs[0][1],
                        )
                        is None
                    ):
                        raise ValueError()
                    request.state.subject = pairs[0][1]
                elif query:
                    raise ValueError()
            except (ValueError, UnicodeError):
                response = JSONResponse(
                    {"detail": "One typed Focus subject is required; other routes accept no query"},
                    status_code=400,
                )
            else:
                try:
                    if request.url.path not in {"/version", "/healthz"}:
                        request.state.assets = validate_packaged_assets(
                            configuration.sources.candidate_root,
                            source_sha=configuration.source_sha,
                            repository=configuration.sources.repository,
                        )
                        # Completed evidence follows the managed read. Diagnostic
                        # liveness/version never depend on observation transports.
                        from starlette.concurrency import run_in_threadpool
                        request.state.first_read = await run_in_threadpool(first_read_provider, request)
                    response = await call_next(request)
                    if request.url.path not in {"/version", "/healthz"}:
                        response.headers["X-DevUI-First-Read-Observation"] = request.state.first_read["status"]
                except CandidateAssetError:
                    response = JSONResponse(
                        {"detail": "Managed DevUI candidate assets or metadata are unavailable"},
                        status_code=503,
                    )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": CSP,
                "X-PKM-Runtime-Git-SHA": configuration.source_sha,
                "X-DevUI-Image-Digest": configuration.image_digest,
                "X-DevUI-Config-Fingerprint": configuration.config_fingerprint,
                "X-DevUI-Asset-Inventory": INVENTORY_SHA256,
            }
        )
        return response

    def asset(request: Request) -> Response:
        media_type, filename = ROUTES[request.url.path]
        return Response(request.state.assets[filename], media_type=media_type)

    for path in ROUTES:
        app.add_api_route(path, asset, methods=["GET"], response_class=Response)

    @app.get("/api/devui/focus")
    def focus(request: Request) -> Any:
        try:
            return compose_focus_view(
                **read_managed_focus(configuration.sources, request.state.subject)
            )
        except (FocusInputError, FocusContractError):
            return JSONResponse(
                {"detail": "DevUI Focus subject is unavailable or unsupported"}, status_code=404
            )

    @app.get("/api/devui/overview")
    def overview(request: Request) -> dict[str, Any]:
        snapshot = compose_owner_snapshot(
            cockpit_reader=lambda: read_managed_cockpit(configuration.sources),
            ckm_reader=_unavailable_provider,
            receipt_reader=receipt_provider,
        )
        owner_facts = read_owner_fact_transport(repository=configuration.sources.repository,
            environment=configuration.sources.api_environment, authority_epoch=configuration.sources.authority_epoch)
        snapshot["providers"]["owner_facts"] = owner_fact_trust(owner_facts, snapshot["captured_at"])
        snapshot["providers"]["first_read_observation"] = request.state.first_read
        inputs = derive_overview_inputs(
            work_provider=snapshot["providers"]["work"],
            receipt_provider=snapshot["providers"]["vm102_evidence"],
            owner_fact_provider=owner_facts,
        )
        return compose_overview_view(
            composition=snapshot, candidates=bind_visual_focus_targets(inputs)
        )

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "source_sha": configuration.source_sha,
            "image_digest": configuration.image_digest,
            "config_fingerprint": configuration.config_fingerprint,
            "component_id": "devui_projection",
            "asset_inventory_sha256": INVENTORY_SHA256,
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
