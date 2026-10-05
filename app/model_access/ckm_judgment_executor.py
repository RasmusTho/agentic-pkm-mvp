"""MARR's separately owned, dormant Builder profile and provider credential boundary."""

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

from app.model_access.ckm_judgment_contract import (
    BUILDER_JUDGMENT_PROFILE,
    CKM_JUDGMENT_REQUEST_BYTES,
    BuilderJudgmentResult,
    BuilderJudgmentSelection,
    validate_ckm_request,
)
from app.model_access.typesafe_adapter import (
    TYPESAFE_SDK_VERSION, TypeSafeAdapter, TypeSafeAdapterError, strict_json_object,
)
from app.ops.host_secret_bootstrap import resolve_host_secret_values, validate_secret_value


BUILDER_TYPESAFE_PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "config/model_access/builder_typesafe_profile.json"
)


class _PinnedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    provider: Literal["typesafe"]
    model: str = Field(pattern=r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")


class _BuilderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1]
    owner: Literal["builder"]
    selected_profile: Literal["builder.ckm_association.v1"]
    profiles: dict[str, _PinnedModel]
    supported_models: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def _supported_profile(self) -> "_BuilderProfile":
        if (
            set(self.profiles) != {BUILDER_JUDGMENT_PROFILE}
            or len(set(self.supported_models)) != len(self.supported_models)
            or any(re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", item) is None
                   for item in self.supported_models)
            or self.profiles[self.selected_profile].model not in self.supported_models
        ):
            raise ValueError("unsupported Builder model profile")
        return self


def resolve_builder_typesafe_profile(
    path: Path = BUILDER_TYPESAFE_PROFILE_PATH,
) -> BuilderJudgmentSelection:
    raw = path.read_bytes()
    if len(raw) > 8192:
        raise ValueError("profile invalid")
    profile = _BuilderProfile.model_validate(json.loads(raw, object_pairs_hook=strict_json_object))
    return BuilderJudgmentSelection(
        model=profile.profiles[profile.selected_profile].model, sdk_version=TYPESAFE_SDK_VERSION,
    )


class BuilderTypeSafeExecutor:
    """One Builder allowance per server; Product admission never consumes or grants it."""

    def __init__(
        self, *, mode: str = "disabled", runtime_channel: str = "dev",
        profile_path: Path = BUILDER_TYPESAFE_PROFILE_PATH,
        adapter: TypeSafeAdapter | None = None,
        keychain_lookup: Callable[[str, str], str] | None = None,
    ) -> None:
        self._mode = mode
        self._runtime_channel = runtime_channel
        self._profile_path = profile_path
        self._adapter = adapter or TypeSafeAdapter(max_request_bytes=CKM_JUDGMENT_REQUEST_BYTES)
        self._keychain_lookup = keychain_lookup
        self._acceptance_used = False
        self._lock = Lock()

    @classmethod
    def from_host_environment(
        cls, environment: Mapping[str, str] | None = None,
    ) -> "BuilderTypeSafeExecutor":
        env = os.environ if environment is None else environment
        valid_server = (
            env.get("HOST_SECRET_BOOTSTRAP_CONSUMER") == "marr-server-dev"
            and env.get("HOST_SECRET_BOOTSTRAP_CHANNEL") == "dev"
        )
        return cls(
            mode=env.get("MODEL_ACCESS_BUILDER_TYPESAFE_MODE", "disabled")
            if valid_server else "disabled",
            runtime_channel=env.get("HOST_SECRET_BOOTSTRAP_CHANNEL", ""),
        )

    def execute(self, request: SystemOneJudgmentRequest) -> BuilderJudgmentResult:
        unavailable = BuilderJudgmentResult(outcome="unavailable_before_send")
        try:
            request = validate_ckm_request(request)
            if self._runtime_channel != "dev" or self._mode not in {"acceptance_once", "accepted_dev"}:
                return unavailable
            selection = resolve_builder_typesafe_profile(self._profile_path)
            with self._lock:
                if self._mode == "acceptance_once":
                    if self._acceptance_used:
                        return unavailable
                    self._acceptance_used = True
            if self._keychain_lookup is None:
                secrets = resolve_host_secret_values(
                    channel="dev", consumer="marr-server-dev", provider="keychain",
                )
            else:
                secrets = resolve_host_secret_values(
                    channel="dev", consumer="marr-server-dev", provider="keychain",
                    keychain_lookup=self._keychain_lookup,
                )
            api_key = secrets.get("typesafe.api-key", "")
            if not validate_secret_value("api-key", api_key):
                return unavailable
        except Exception:
            return unavailable
        try:
            judgment, usage = self._adapter.judge(request, model=selection.model, api_key=api_key)
        except TypeSafeAdapterError as exc:
            return BuilderJudgmentResult(outcome=exc.outcome, selection=selection)
        except Exception:
            return BuilderJudgmentResult(outcome="outcome_unknown_after_dispatch", selection=selection)
        try:
            return BuilderJudgmentResult(
                outcome="success", selection=selection, judgment=judgment, usage=usage,
            )
        except Exception:
            return BuilderJudgmentResult(outcome="response_invalid", selection=selection)
