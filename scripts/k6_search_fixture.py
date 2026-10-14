"""Finite, disposable canonical-search producer and response probe for k6."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4


_DATABASE_NAME = re.compile(r"k6_search(?:_[0-9a-f]{12})?")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_TITLE = "K6 synthetic smoke note"


def _disposable_dsn() -> str:
    from psycopg.conninfo import conninfo_to_dict

    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    fields = conninfo_to_dict(dsn)
    if (
        fields.get("host") not in {"localhost", "127.0.0.1", "::1"}
        or fields.get("hostaddr", "127.0.0.1") not in {"127.0.0.1", "::1"}
        or fields.get("service")
        or fields.get("port") == "15432"
        or not _DATABASE_NAME.fullmatch(fields.get("dbname", ""))
    ):
        raise RuntimeError("k6 producer requires an explicit localhost disposable k6_search database")
    if os.getenv("STORE_SCHEMA_AUTOCREATE"):
        raise RuntimeError("k6 producer requires migration-owned schema without schema autocreation")
    return dsn


def prepare_extension() -> None:
    import psycopg

    with psycopg.connect(_disposable_dsn(), autocommit=True) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")


def seed(manifest_path: Path) -> dict[str, str]:
    _disposable_dsn()
    if os.getenv("EMBED_PROFILE") != "deterministic" or os.getenv("STORE_BACKEND") != "pg":
        raise RuntimeError("k6 fixture requires STORE_BACKEND=pg and EMBED_PROFILE=deterministic")

    from app.components.embeddings import get_embedding_client
    from app.services.outbox import bootstrap
    from app.stores.pg import PgObjectStore, PgVectorIndex

    bootstrap()
    object_id = uuid4()
    binding_id = f"k6-search-{uuid4().hex}"
    source_ref = f"k6://synthetic/{binding_id}/smoke.md"
    text = "smoke content for the finite k6 canonical search fixture"
    payload = {
        "artifact_id": str(object_id),
        "stable_id": str(object_id),
        "title": _TITLE,
        "text": text,
        "path": "synthetic/smoke.md",
        "source_ref": source_ref,
        "language": "en",
        "origin": "synthetic-ci",
        "source_role": "primary",
        "trust": "trusted",
        "review_state": "inbox",
    }
    client = get_embedding_client()
    payload["embedding_identity"] = {
        "provider": client.identity.provider,
        "model": client.identity.model,
        "dim": client.identity.dim,
        "normalize": client.identity.normalize,
    }
    vector = client.embed_text(text)
    PgObjectStore(vault_binding_id=binding_id).put(
        object_id, kind="note", source_ref=source_ref, payload=payload
    )
    PgVectorIndex(vault_binding_id=binding_id).upsert(
        object_id,
        kind="note",
        source_ref=source_ref,
        payload=payload,
        embedding=vector,
        model=client.identity.model,
        identity=client.identity,
    )
    manifest = {
        "query": "smoke",
        "expected_uuid": str(object_id),
        "expected_title": _TITLE,
        "vault_binding_id": binding_id,
    }
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def response_matches(status: int, body: str, fixture: dict[str, str]) -> bool:
    if status != 200:
        return False
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return False
    results = payload["results"]
    if not results or len(results) > 10:
        return False
    for result in results:
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("uuid"), str)
            or not _UUID.fullmatch(result["uuid"])
            or not isinstance(result.get("title"), str)
        ):
            return False
    return sum(
        result["uuid"] == fixture["expected_uuid"] and result["title"] == fixture["expected_title"]
        for result in results
    ) == 1


def probe(base_url: str, manifest_path: Path, *, wait_seconds: float = 0) -> None:
    base = urlsplit(base_url)
    if base.scheme != "http" or base.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("k6 probe requires an explicit localhost HTTP API")
    fixture = json.loads(manifest_path.read_text(encoding="utf-8"))
    UUID(fixture["expected_uuid"])
    if not fixture["expected_title"] or fixture["query"] != "smoke":
        raise RuntimeError("invalid k6 fixture manifest")
    request = Request(
        f"{base_url.rstrip('/')}/search?{urlencode({'q': fixture['query']})}",
        headers={"x-trace-id": "warmup-k6"},
    )
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with urlopen(request, timeout=5) as response:
                if response_matches(response.status, response.read().decode("utf-8"), fixture):
                    return
        except (HTTPError, URLError, TimeoutError, UnicodeError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("k6 search probe did not return the expected seeded canonical result")
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("prepare-extension")
    for action in ("seed", "probe"):
        command = actions.add_parser(action)
        command.add_argument("--manifest", type=Path, required=True)
        if action == "probe":
            command.add_argument("--base-url", required=True)
            command.add_argument("--wait-seconds", type=float, default=0)
    args = parser.parse_args()
    if args.action == "prepare-extension":
        prepare_extension()
    elif args.action == "seed":
        seed(args.manifest)
    else:
        probe(args.base_url, args.manifest, wait_seconds=args.wait_seconds)


if __name__ == "__main__":
    main()
