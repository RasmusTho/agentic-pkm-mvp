"""Server-owned Product profile, dev gate and MARR-only credential boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_contract import SystemOneJudgmentRequest

from app.model_access.product_judgment_contract import (
    PRODUCT_JUDGMENT_PROFILE,
    JudgmentSelection,
    ProductJudgmentResult,
    validate_product_request,
)
from app.model_access.typesafe_adapter import (
    TYPESAFE_SDK_VERSION,
    TypeSafeAdapter,
    TypeSafeAdapterError,
    strict_json_object,
)
from app.ops.bws_secret_reader import BwsSecretReader
from app.ops.host_secret_bootstrap import (
    create_marr_typesafe_bws_reader,
    resolve_host_secret_values,
    validate_secret_value,
)
from app.ops.host_secret_controller import HostSecretController


PRODUCT_TYPESAFE_PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "config/model_access/product_typesafe_profile.json"
)
_PINNED_MODEL = re.compile(r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")


class _PinnedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    provider: Literal["typesafe"]
    model: str = Field(pattern=r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")


class _ProductProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1]
    owner: Literal["product"]
    selected_profile: Literal["product.canvas_intent.v1"]
    profiles: dict[str, _PinnedModel]
    supported_models: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def _supported_pinned_profile(self) -> "_ProductProfile":
        if set(self.profiles) != {PRODUCT_JUDGMENT_PROFILE}:
            raise ValueError("unknown profile")
        if (
            len(set(self.supported_models)) != len(self.supported_models)
            or any(_PINNED_MODEL.fullmatch(model) is None for model in self.supported_models)
            or self.profiles[self.selected_profile].model not in self.supported_models
        ):
            raise ValueError("unsupported pinned model")
        return self


def resolve_product_typesafe_profile(
    path: Path = PRODUCT_TYPESAFE_PROFILE_PATH,
) -> JudgmentSelection:
    raw = path.read_bytes()
    if len(raw) > 8192:
        raise ValueError("profile invalid")
    policy = _ProductProfile.model_validate(json.loads(raw, object_pairs_hook=strict_json_object))
    return JudgmentSelection(
        model=policy.profiles[policy.selected_profile].model, sdk_version=TYPESAFE_SDK_VERSION
    )


class ProductTypeSafeExecutor:
    """Every request is terminal. A one-call acceptance server has no restart/replay promise."""

    def __init__(
        self,
        *,
        mode: str = "disabled",
        runtime_channel: str = "dev",
        profile_path: Path = PRODUCT_TYPESAFE_PROFILE_PATH,
        adapter: TypeSafeAdapter | None = None,
        keychain_lookup: Callable[[str, str], str] | None = None,
        bws_reader: BwsSecretReader | None = None,
        secret_controller: HostSecretController | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._mode = mode
        self._runtime_channel = runtime_channel
        self._profile_path = profile_path
        self._adapter = adapter or TypeSafeAdapter()
        # This Keychain seam supplies the MARR BWS reader token only. The
        # TypeSafe provider key comes from the isolated BWS project.
        self._keychain_lookup = keychain_lookup
        self._bws_reader = bws_reader
        self._secret_controller = secret_controller
        self._environment = os.environ if environment is None else dict(environment)
        self._acceptance_used = False
        self._lock = Lock()

    @classmethod
    def from_host_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "ProductTypeSafeExecutor":
        env = os.environ if environment is None else environment
        # Existing bootstrap attests the dedicated process identity. Mode changes
        # are operator-owned; no checked-in configuration enables runtime calls.
        valid_server = (
            env.get("HOST_SECRET_BOOTSTRAP_CONSUMER") == "marr-server-dev"
            and env.get("HOST_SECRET_BOOTSTRAP_CHANNEL") == "dev"
        )
        return cls(
            mode=env.get("MODEL_ACCESS_PRODUCT_TYPESAFE_MODE", "disabled")
            if valid_server
            else "disabled",
            runtime_channel=env.get("HOST_SECRET_BOOTSTRAP_CHANNEL", ""),
            environment=env,
        )

    def execute(self, request: SystemOneJudgmentRequest) -> ProductJudgmentResult:
        unavailable = ProductJudgmentResult(outcome="unavailable_before_send")
        selection = None
        try:
            request = validate_product_request(request)
            if self._runtime_channel != "dev" or self._mode not in {
                "acceptance_once",
                "accepted_dev",
            }:
                return unavailable
            selection = resolve_product_typesafe_profile(self._profile_path)
            with self._lock:
                if self._mode == "acceptance_once":
                    if self._acceptance_used:
                        return unavailable
                    # Consume before credential lookup/dispatch. Failure never
                    # rearms this server; restart requires fresh operator authority.
                    self._acceptance_used = True
            bws_reader = self._bws_reader
            if bws_reader is None:
                if self._keychain_lookup is None:
                    bws_reader = create_marr_typesafe_bws_reader(
                        environment=self._environment
                    )
                else:
                    bws_reader = create_marr_typesafe_bws_reader(
                        environment=self._environment,
                        keychain_lookup=self._keychain_lookup,
                    )
            secrets = resolve_host_secret_values(
                channel="dev",
                consumer="marr-server-dev",
                provider="bws",
                bws_reader=bws_reader,
                controller=self._secret_controller,
            )
            api_key = secrets.get("typesafe.api-key", "")
            if not validate_secret_value("api-key", api_key):
                return unavailable
        except Exception:
            return unavailable
        try:
            judgment, usage = self._adapter.judge(request, model=selection.model, api_key=api_key)
        except TypeSafeAdapterError as exc:
            return ProductJudgmentResult(outcome=exc.outcome, selection=selection)
        except Exception:
            return ProductJudgmentResult(
                outcome="outcome_unknown_after_dispatch", selection=selection
            )
        try:
            return ProductJudgmentResult(
                outcome="success", selection=selection, judgment=judgment, usage=usage
            )
        except Exception:
            return ProductJudgmentResult(outcome="response_invalid", selection=selection)
