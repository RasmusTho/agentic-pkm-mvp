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
    credentials_directory: Path | None
    token_file: Path | None
    token_source: str = "credential-file"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BwsReaderConfig:
        try:
            project = environment["BWS_READER_PROJECT"]
            if project not in {"non-prod", "prod"}:
                raise BwsLookupError()
            return cls(
                project,
                environment["BWS_PROJECT_ID"],
                environment["BWS_ORGANIZATION_ID"],
                Path(environment["CREDENTIALS_DIRECTORY"]),
                Path(environment["BWS_ACCESS_TOKEN_FILE"]),
            )
        except Exception:
            raise BwsLookupError() from None

    @classmethod
    def from_marr_server_environment(
        cls, environment: Mapping[str, str]
    ) -> BwsReaderConfig:
        """Build the MARR configuration; its non-prod reader token is fetched from Keychain."""
        try:
            if (
                environment["BWS_READER_PROJECT"] != "non-prod"
                or any(
                    name in environment
                    for name in (
                        "BWS_ACCESS_TOKEN",
                        "BWS_ACCESS_TOKEN_FILE",
                        "CREDENTIALS_DIRECTORY",
                    )
                )
            ):
                raise BwsLookupError()
            return cls(
                "non-prod",
                environment["BWS_PROJECT_ID"],
                environment["BWS_ORGANIZATION_ID"],
                None,
                None,
                "keychain",
            )
        except Exception:
            raise BwsLookupError() from None

    def validate(self, project: str) -> None:
        try:
            valid_ids = (
                str(UUID(self.project_id)) == self.project_id
                and str(UUID(self.organization_id)) == self.organization_id
            )
        except (ValueError, TypeError, AttributeError):
            valid_ids = False
        valid_marr = (
            project == self.project == "non-prod"
            and self.token_source == "keychain"
            and self.credentials_directory is None
            and self.token_file is None
        )
        valid_channel = (
            project in {"non-prod", "prod"}
            and self.project == project
            and self.token_source == "credential-file"
            and self.credentials_directory is not None
            and self.credentials_directory.is_absolute()
            and self.token_file
            == self.credentials_directory / "bws-machine-account-token"
        )
        if not valid_ids or not (valid_marr or valid_channel):
            raise BwsLookupError()


def _sdk_client() -> Any:
    # The SDK decrypts in-process. No state_file: tokens and decrypted values are
    # never written by the SDK or put into a subprocess environment/argument.
    return importlib.import_module("bitwarden_sdk").BitwardenClient()


def _read_token(config: BwsReaderConfig) -> str:
    if config.credentials_directory is None:
        raise BwsLookupError()
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
        self,
        config: BwsReaderConfig,
        *,
        client_factory: Callable[[], Any] = _sdk_client,
        keychain_token_lookup: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._keychain_token_lookup = keychain_token_lookup

    @staticmethod
    def _validate_token(token: str) -> str:
        try:
            encoded = token.encode("utf-8", errors="strict")
        except (AttributeError, UnicodeError):
            raise BwsLookupError() from None
        if (
            not encoded
            or len(encoded) > 4096
            or any(char.isspace() or not char.isprintable() for char in token)
        ):
            raise BwsLookupError()
        return token

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

            scope = BWS_IDENTITIES.get(logical_id)
            valid_channel_identity = (
                scope == "channel" and CHANNEL_PROJECTS.get(prefix) == project
            )
            valid_shared_identity = scope == "shared" and prefix == "shared"
            if (
                not separator
                or not (valid_channel_identity or valid_shared_identity)
            ):
                raise BwsLookupError()
            if self.config.token_source == "keychain":
                if self._keychain_token_lookup is None:
                    raise BwsLookupError()
                token = self._validate_token(self._keychain_token_lookup())
            else:
                token = _read_token(self.config)
            # Authenticate only after the project and exact identity were checked.
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
