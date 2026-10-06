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
from app.model_access.typesafe_acceptance_marker import (
    BUILDER_ACCEPTANCE_CONSUMER,
    acceptance_state_directory_from_environment,
    consume_acceptance_once,
)
from app.ops.bws_secret_reader import BwsSecretReader
from app.ops.host_secret_bootstrap import (
    create_marr_typesafe_bws_reader,
    resolve_host_secret_values,
    validate_secret_value,
)
from app.ops.host_secret_controller import HostSecretController


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
        bws_reader: BwsSecretReader | None = None,
        secret_controller: HostSecretController | None = None,
        acceptance_state_directory: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._mode = mode
        self._runtime_channel = runtime_channel
        self._profile_path = profile_path
        self._adapter = adapter or TypeSafeAdapter(max_request_bytes=CKM_JUDGMENT_REQUEST_BYTES)
        # This Keychain seam supplies the MARR BWS reader token only. The
        # TypeSafe provider key comes from the isolated BWS project.
        self._keychain_lookup = keychain_lookup
        self._bws_reader = bws_reader
        self._secret_controller = secret_controller
        self._environment = os.environ if environment is None else dict(environment)
        self._acceptance_state_directory = (
            acceptance_state_directory
            if acceptance_state_directory is not None
            else acceptance_state_directory_from_environment(self._environment)
        )
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
            environment=env,
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
                    if not consume_acceptance_once(
                        BUILDER_ACCEPTANCE_CONSUMER, self._acceptance_state_directory
                    ):
                        return unavailable
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
            return BuilderJudgmentResult(outcome=exc.outcome, selection=selection)
        except Exception:
            return BuilderJudgmentResult(outcome="outcome_unknown_after_dispatch", selection=selection)
        try:
            return BuilderJudgmentResult(
                outcome="success", selection=selection, judgment=judgment, usage=usage,
            )
        except Exception:
            return BuilderJudgmentResult(outcome="response_invalid", selection=selection)
