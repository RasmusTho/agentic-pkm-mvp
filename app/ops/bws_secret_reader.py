"""Read-only, memory-only BWS SDK boundary. No CLI, state cache or token env."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import stat
from typing import Any
from uuid import UUID


class BwsLookupError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("BWS secret lookup failed")


class BwsItemAbsent(BwsLookupError):
    """Only a successful identifier listing with no selected item proves absence."""


@dataclass(frozen=True)
class BwsReaderConfig:
    project: str
    project_id: str
    organization_id: str
    credentials_directory: Path
    token_file: Path

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BwsReaderConfig:
        try:
            return cls(
                environment["BWS_READER_PROJECT"],
                environment["BWS_PROJECT_ID"],
                environment["BWS_ORGANIZATION_ID"],
                Path(environment["CREDENTIALS_DIRECTORY"]),
                Path(environment["BWS_ACCESS_TOKEN_FILE"]),
            )
        except Exception:
            raise BwsLookupError() from None

    def validate(self, project: str) -> None:
        if (
            project not in {"non-prod", "prod"}
            or self.project != project
            or str(UUID(self.project_id)) != self.project_id
            or str(UUID(self.organization_id)) != self.organization_id
            or not self.credentials_directory.is_absolute()
            or self.token_file != self.credentials_directory / "bws-machine-account-token"
        ):
            raise BwsLookupError()


def _sdk_client() -> Any:
    # The SDK decrypts in-process. No state_file: tokens and decrypted values are
    # never written by the SDK or put into a subprocess environment/argument.
    return importlib.import_module("bitwarden_sdk").BitwardenClient()


def _read_token(config: BwsReaderConfig) -> str:
    descriptor = directory_fd = None
    try:
        directory_fd = os.open(
            config.credentials_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        directory_info = os.fstat(directory_fd)
        if (
            directory_info.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(directory_info.st_mode) & 0o022
        ):
            raise BwsLookupError()
        descriptor = os.open(
            "bws-machine-account-token",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(info.st_mode) & 0o077
            or not stat.S_IMODE(info.st_mode) & 0o400
            or info.st_nlink != 1
            or not 1 <= info.st_size <= 4096
        ):
            raise BwsLookupError()
        raw = os.read(descriptor, 4097)
        token = raw.decode("utf-8", errors="strict")
        if (
            not token
            or len(raw) > 4096
            or any(char.isspace() or not char.isprintable() for char in token)
        ):
            raise BwsLookupError()
        return token
    except Exception:
        raise BwsLookupError() from None
    finally:
        for opened in (descriptor, directory_fd):
            if opened is not None:
                os.close(opened)


class BwsSecretReader:
    def __init__(
        self, config: BwsReaderConfig, *, client_factory: Callable[[], Any] = _sdk_client
    ) -> None:
        self.config = config
        self._client_factory = client_factory

    def lookup(self, project: str, identity: str) -> str:
        """Validate scope before authentication and recheck selected response membership.

        Caller supplies a contract-authorized identity under host controller admission.
        The SDK identifier list has no values; only the selected UUID is fetched.
        """
        try:
            self.config.validate(project)
            # Even a direct caller cannot name an identity from a different channel/project.
            prefix, separator, logical_id = identity.partition("/")
            from app.ops.host_secret_contract import BWS_IDENTITIES, CHANNEL_PROJECTS

            if (
                not separator
                or logical_id not in BWS_IDENTITIES
                or (BWS_IDENTITIES[logical_id] == "shared" and prefix != "shared")
                or (
                    BWS_IDENTITIES[logical_id] == "channel"
                    and CHANNEL_PROJECTS.get(prefix) != project
                )
            ):
                raise BwsLookupError()
            token = _read_token(self.config)  # before constructing/accessing any provider
            client = self._client_factory()
            login = client.auth().login_access_token(token, None)
            del token
            if not login.success or login.data is None or not login.data.authenticated:
                raise BwsLookupError()
            projects = client.projects().list(self.config.organization_id)
            if (
                not projects.success
                or len(projects.data.data) != 1
                or str(projects.data.data[0].id) != self.config.project_id
                or projects.data.data[0].name != project
                or str(projects.data.data[0].organization_id) != self.config.organization_id
            ):
                raise BwsLookupError()
            identifiers = client.secrets().list(self.config.organization_id)
            if not identifiers.success:
                raise BwsLookupError()
            selected = [item for item in identifiers.data.data if item.key == identity]
            if not selected:
                raise BwsItemAbsent()
            if (
                len(selected) != 1
                or str(selected[0].organization_id) != self.config.organization_id
                or [str(item) for item in selected[0].project_ids] != [self.config.project_id]
            ):
                raise BwsLookupError()
            response = client.secrets().get(str(selected[0].id))
            if (
                not response.success
                or response.data.key != identity
                or str(response.data.id) != str(selected[0].id)
                or str(response.data.organization_id) != self.config.organization_id
                or str(response.data.project_id) != self.config.project_id
                or not isinstance(response.data.value, str)
            ):
                raise BwsLookupError()
            return response.data.value
        except BwsItemAbsent:
            raise
        except Exception:
            # Never retain an SDK exception as __cause__ or display its payload.
            raise BwsLookupError() from None
