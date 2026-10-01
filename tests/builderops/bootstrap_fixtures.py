"""Explicit isolated authority fixtures; production has no acceptance bypass."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.builderops.control_plane import bootstrap

REPOSITORIES = ("rasmustho/agentic-pkm-mvp", "rasmustho/bifrost", "example/second-repo", "example/fixture", "otherorg/other-repo")
SOURCE_SHA = "a" * 40


def authority_files(directory: Path):
    candidate = json.dumps({"receipt_version": 1, "repository": "RasmusTho/agentic-pkm-mvp",
                           "workflow": ".github/workflows/app-image-build.yml", "event_name": "push",
                           "source_ref": "refs/heads/main", "durability_posture": "rebuildable",
                           "platform": "linux/amd64", "source_sha": SOURCE_SHA,
                           "control_plane_image_digest": "sha256:" + "b" * 64,
                           "postgres_image_digest": "sha256:" + "c" * 64}).encode()
    receipt = directory / "candidate.json"
    receipt.write_bytes(candidate)
    pin = directory / "current.env"
    pin.write_text(f"BUILDEROPS_SOURCE_SHA={SOURCE_SHA}\n"
                   f"BUILDEROPS_IMAGE_DIGEST=sha256:{'b' * 64}\n"
                   f"BUILDEROPS_POSTGRES_IMAGE_DIGEST=sha256:{'c' * 64}\n"
                   f"BUILDEROPS_CANDIDATE_RECEIPT_SHA={hashlib.sha256(candidate).hexdigest()}\n")
    return {"pin_file": pin, "candidate_receipt": receipt, "repositories": REPOSITORIES}


def github_get(args):
    assert args[0] == "api" and args[-2:] == ["--method", "GET"]
    if args[1] == "user":
        return {"id": 123}
    assert args[1].endswith("/commits/" + SOURCE_SHA)
    return {"sha": SOURCE_SHA}


def github_pages(owner, name, endpoint, **kwargs):
    assert kwargs["extra_fields"] == ("state=all", "sort=created", "direction=asc")
    if endpoint == "issues":
        return [{"number": 5712, "state": "open", "labels": [{"name": "agent:ready"}],
                 "body": "Canonical fixture contract", "updated_at": "2026-09-28T00:00:00Z"}]
    assert endpoint == "pulls"
    return []


@contextmanager
def authenticated_github_fixture():
    with (patch.object(bootstrap, "_authenticate_candidate") as attestation,
          patch.object(bootstrap, "_run_gh", side_effect=github_get),
          patch.object(bootstrap, "_paged_rest", side_effect=github_pages)):
        yield attestation


def accept_fixture_authority(store):
    with TemporaryDirectory(prefix="rsc07-fixture-") as directory, authenticated_github_fixture():
        result = bootstrap.bootstrap_from_authority(store, **authority_files(Path(directory)))
        assert result["status"] == "converged", result


def admit_fixture_connections(store):
    """Pin intentional fixture SQL to the accepted epoch (never auto-refresh)."""
    epoch = store.readiness()["authority_epoch"]
    original = store._connect
    def connect():
        conn = original()
        conn.execute("SELECT set_config('builderops.authority_epoch', %s, true)", (str(epoch),))
        return conn
    store._connect = connect
