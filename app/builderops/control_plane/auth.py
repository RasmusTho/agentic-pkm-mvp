"""Scoped bearer authentication for the independent BuilderOps service."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CredentialConfigurationError(RuntimeError):
    """Raised when the host-owned credential configuration is unusable."""


@dataclass(frozen=True)
class Credential:
    credential_id: str
    principal: str
    secret_ref: str
    fingerprint: str
    scopes: frozenset[str]
    rotation_generation: int


class CredentialRegistry:
    """Resolve revocable credentials from host secret files on every request.

    The manifest contains metadata and secret-file references only. Raw bearer
    material is read transiently and is never returned by this object.
    """

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self._lock = threading.Lock()
        self._failures = 0

    @staticmethod
    def _fingerprint(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def _entries(self) -> list[tuple[Credential, str]]:
        try:
            document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialConfigurationError("BuilderOps credential manifest is unavailable") from exc
        raw_entries = document.get("credentials") if isinstance(document, dict) else None
        if not isinstance(raw_entries, list) or not raw_entries:
            raise CredentialConfigurationError("BuilderOps credential manifest has no credentials")
        entries: list[tuple[Credential, str]] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                raise CredentialConfigurationError("invalid BuilderOps credential metadata")
            try:
                credential_id = str(raw["id"]).strip()
                principal = str(raw["principal"]).strip()
                secret_ref = str(raw["secret_ref"]).strip()
                scopes_raw = raw["scopes"]
                generation = int(raw["rotation_generation"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CredentialConfigurationError("invalid BuilderOps credential metadata") from exc
            if not credential_id or not principal or not secret_ref or generation < 1:
                raise CredentialConfigurationError("invalid BuilderOps credential metadata")
            if not isinstance(scopes_raw, list) or not scopes_raw:
                raise CredentialConfigurationError("BuilderOps credential scopes are required")
            scopes = frozenset(str(scope).strip() for scope in scopes_raw)
            if "" in scopes:
                raise CredentialConfigurationError("BuilderOps credential scopes must be non-empty")
            if bool(raw.get("revoked", False)):
                continue
            verifier = str(raw.get("verifier_sha256", "")).strip().lower()
            secret_file_raw = str(raw.get("secret_file", "")).strip()
            if verifier and secret_file_raw:
                raise CredentialConfigurationError(
                    "credential metadata must use either a verifier or a secret file"
                )
            if verifier:
                if len(verifier) != 64 or any(char not in "0123456789abcdef" for char in verifier):
                    raise CredentialConfigurationError("invalid BuilderOps credential verifier")
            elif secret_file_raw:
                try:
                    secret = Path(secret_file_raw).read_text(encoding="utf-8").strip()
                except OSError as exc:
                    raise CredentialConfigurationError(
                        "BuilderOps credential secret is unavailable"
                    ) from exc
                if not secret:
                    raise CredentialConfigurationError("BuilderOps credential secret is empty")
                verifier = self._fingerprint(secret)
            else:
                raise CredentialConfigurationError("BuilderOps credential verifier is required")
            entries.append(
                (
                    Credential(
                        credential_id=credential_id,
                        principal=principal,
                        secret_ref=secret_ref,
                        fingerprint=verifier,
                        scopes=scopes,
                        rotation_generation=generation,
                    ),
                    verifier,
                )
            )
        return entries

    def authenticate(self, bearer: str | None) -> Credential | None:
        if bearer is None or not bearer:
            self.record_failure()
            return None
        match: Credential | None = None
        supplied = self._fingerprint(bearer)
        for credential, expected_verifier in self._entries():
            if hmac.compare_digest(supplied, expected_verifier):
                match = credential
        if match is None:
            self.record_failure()
        return match

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1

    def is_registered_secret(self, value: str) -> bool:
        """Check a candidate without retaining or returning raw credential material."""
        fingerprint = self._fingerprint(value)
        return any(
            hmac.compare_digest(fingerprint, verifier)
            for _credential, verifier in self._entries()
        )

    def status(self) -> dict[str, Any]:
        entries = [credential for credential, _secret in self._entries()]
        with self._lock:
            failures = self._failures
        return {
            "configured": True,
            "credential_count": len(entries),
            "failures_total": failures,
            "credentials": [
                {
                    "id": entry.credential_id,
                    "principal": entry.principal,
                    "secret_ref": entry.secret_ref,
                    "fingerprint": entry.fingerprint,
                    "scopes": sorted(entry.scopes),
                    "rotation_generation": entry.rotation_generation,
                }
                for entry in entries
            ],
        }


class CredentialRateLimiter:
    """Small per-principal fixed-window limiter for the independent service."""

    def __init__(self, requests_per_minute: int = 120) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.requests_per_minute = requests_per_minute
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}
        self._rejections = 0

    def allow(self, principal: str) -> bool:
        window = int(time.monotonic() // 60)
        with self._lock:
            prior_window, count = self._windows.get(principal, (window, 0))
            if prior_window != window:
                count = 0
            if count >= self.requests_per_minute:
                self._rejections += 1
                self._windows[principal] = (window, count)
                return False
            self._windows[principal] = (window, count + 1)
            return True

    def status(self) -> dict[str, int | bool]:
        with self._lock:
            rejections = self._rejections
        return {
            "enabled": True,
            "requests_per_minute": self.requests_per_minute,
            "rejections_total": rejections,
        }


__all__ = [
    "Credential",
    "CredentialConfigurationError",
    "CredentialRateLimiter",
    "CredentialRegistry",
]
