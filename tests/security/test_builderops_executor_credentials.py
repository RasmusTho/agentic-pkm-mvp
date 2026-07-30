from __future__ import annotations

import json

from app.dispatcher.verification_github import HostCredentialManifestResolver
from app.dispatcher.verification_merge import VerificationMergeExecutor
from tests.dispatcher.test_verification_merge import (
    RepositoryAuthority,
    claimed_run,
)


class CapturingRepository(RepositoryAuthority):
    def __init__(self) -> None:
        super().__init__()
        self.effect_credential = None

    def conditional_merge(self, *args, **kwargs):
        self.effect_credential = kwargs["credential"]
        return super().conditional_merge(*args, **kwargs)


def test_executor_secrets_are_referenced_not_persisted(tmp_path) -> None:
    ledger, run, outbox = claimed_run()
    secret = "github_pat_NEVER_PERSIST_THIS_VALUE"
    repository = CapturingRepository()
    secret_file = tmp_path / "github.secret"
    secret_file.write_text(secret, encoding="utf-8")
    manifest = tmp_path / "executor-credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "repository": "RasmusTho/agentic-pkm-mvp",
                        "credential_id": "github-repo-merge",
                        "rotation_generation": 7,
                        "secret_file": str(secret_file),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    VerificationMergeExecutor(
        ledger,
        outbox,
        repository,
        HostCredentialManifestResolver(manifest),
    ).execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
    )

    durable_api_documents = json.dumps(ledger.client.calls, default=str)
    assert secret not in durable_api_documents
    assert "github-repo-merge" in durable_api_documents
    assert repository.effect_credential == secret
