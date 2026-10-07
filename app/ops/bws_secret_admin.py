"""Authenticated, in-process BWS administration; no CLI, token env or SDK cache.

The SDK provides no request-terminality endpoint. Every mutation exception therefore
remains indeterminate; item-note readback is never used to authorize recovery.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import os
import sys
from typing import Any, Protocol
from uuid import UUID

from app.ops.bws_secret_reader import _sdk_client
from app.ops.host_secret_bootstrap import _security_framework_keychain_lookup
from app.ops.host_secret_contract import (
    BWS_IDENTITIES, CHANNEL_PROJECTS,
)


class SecretAdminError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("secret administration refused; inspect value-free operation status")


class PrecommitRejection(SecretAdminError):
    """Adapter proof of rejection before any effect; never inferred from SDK errors."""


@dataclass(frozen=True, repr=False)
class SecretCopy:
    item_id: str
    value: str = field(repr=False)
    note: str = field(repr=False)


class SecretAdminProvider(Protocol):
    def read(self, project: str, identity: str) -> SecretCopy | None: ...
    def put(self, project: str, identity: str, previous: SecretCopy | None,
            value: str, note: str) -> SecretCopy: ...
    def delete(self, project: str, identity: str, current: SecretCopy) -> None: ...


@dataclass(frozen=True)
class BwsAdminConfig:
    organization_id: str
    non_prod_project_id: str
    prod_project_id: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BwsAdminConfig:
        try:
            cfg = cls(environment['BWS_ORGANIZATION_ID'],
                      environment['BWS_NON_PROD_PROJECT_ID'], environment['BWS_PROD_PROJECT_ID'])
            cfg.validate()
            return cfg
        except Exception:
            raise SecretAdminError() from None

    def validate(self) -> None:
        ids = [self.organization_id, self.non_prod_project_id, self.prod_project_id]
        if len(set(ids)) != len(ids) or any(str(UUID(item)) != item for item in ids):
            raise SecretAdminError()

    def projects(self) -> dict[str, str]:
        self.validate()
        projects = {
            'non-prod': self.non_prod_project_id,
            'prod': self.prod_project_id,
        }
        return projects


def _admin_token() -> str:
    if sys.platform != 'darwin':
        raise SecretAdminError()
    # Exact bytes through Security.framework: no subprocess/token environment.
    return _security_framework_keychain_lookup('yggdrasil.bws-admin', 'admin.token')


class BwsSecretAdmin:
    def __init__(self, config: BwsAdminConfig, *,
                 client_factory: Callable[[], Any] = _sdk_client,
                 token_reader: Callable[[], str] = _admin_token) -> None:
        self.config = config
        self._factory = client_factory
        self._token_reader = token_reader
        self._client: Any = None

    def _session(self) -> Any:
        if self._client is not None:
            return self._client
        self.config.validate()
        token = self._token_reader()
        if not token or any(c.isspace() or not c.isprintable() for c in token):
            raise SecretAdminError()
        client = self._factory()
        result = client.auth().login_access_token(token, None)
        del token
        if not result.success or result.data is None or not result.data.authenticated:
            raise SecretAdminError()
        response = client.projects().list(self.config.organization_id)
        if not response.success or len(response.data.data) != len(self.config.projects()):
            raise SecretAdminError()
        projects = {item.name: str(item.id) for item in response.data.data
                    if str(item.organization_id) == self.config.organization_id}
        if projects != self.config.projects():
            raise SecretAdminError()
        self._client = client
        return client

    def _scope(self, project: str, identity: str) -> str:
        prefix, _, logical = identity.partition('/')
        scope = BWS_IDENTITIES.get(logical)
        configured_projects = self.config.projects()
        if scope == 'shared':
            allowed = prefix == 'shared' and project in {'non-prod', 'prod'}
        elif scope == 'channel':
            allowed = CHANNEL_PROJECTS.get(prefix) == project
        else:
            allowed = False
        allowed = allowed and project in configured_projects
        if not allowed:
            raise SecretAdminError()
        try:
            return configured_projects[project]
        except KeyError:
            raise SecretAdminError() from None

    def _copy(self, response: Any, project_id: str, identity: str,
              expected_id: str | None = None) -> SecretCopy:
        if not response.success or response.data is None:
            raise SecretAdminError()
        item = response.data
        item_id = str(item.id)
        if (str(UUID(item_id)) != item_id or item.key != identity
            or str(item.organization_id) != self.config.organization_id
            or str(item.project_id) != project_id
            or (expected_id is not None and item_id != expected_id)
            or not isinstance(item.value, str) or not isinstance(item.note, str)):
            raise SecretAdminError()
        return SecretCopy(item_id, item.value, item.note)

    def read(self, project: str, identity: str) -> SecretCopy | None:
        try:
            project_id = self._scope(project, identity)
            client = self._session()
            response = client.secrets().list(self.config.organization_id)
            if not response.success:
                raise SecretAdminError()
            matches = [item for item in response.data.data if item.key == identity
                       and project_id in [str(p) for p in item.project_ids]]
            if not matches:
                return None
            if len(matches) != 1:
                raise SecretAdminError()
            item = matches[0]
            if (str(item.organization_id) != self.config.organization_id
                or [str(p) for p in item.project_ids] != [project_id]):
                raise SecretAdminError()
            return self._copy(client.secrets().get(str(item.id)), project_id, identity, str(item.id))
        except Exception:
            raise SecretAdminError() from None

    def put(self, project: str, identity: str, previous: SecretCopy | None,
            value: str, note: str) -> SecretCopy:
        try:
            project_id = self._scope(project, identity)
            client = self._session()
            if previous is None:
                response = client.secrets().create(UUID(self.config.organization_id), identity,
                    value, note, [UUID(project_id)])
            else:
                response = client.secrets().update(self.config.organization_id, previous.item_id,
                    identity, value, note, [UUID(project_id)])
            copy = self._copy(response, project_id, identity,
                              previous.item_id if previous else None)
            if copy.value != value or copy.note != note:
                raise SecretAdminError()
            return copy
        except Exception:
            # Even a rejection-looking string or missing marker is not terminal proof.
            raise SecretAdminError() from None

    def delete(self, project: str, identity: str, current: SecretCopy) -> None:
        try:
            self._scope(project, identity)
            response = self._session().secrets().delete([current.item_id])
            if not response.success or len(response.data.data) != 1:
                raise SecretAdminError()
            item = response.data.data[0]
            if str(item.id) != current.item_id or item.error is not None:
                raise SecretAdminError()
        except Exception:
            raise SecretAdminError() from None


def configured_admin() -> BwsSecretAdmin:
    return BwsSecretAdmin(BwsAdminConfig.from_environment(os.environ))
