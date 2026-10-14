"""Private, source-backed reconciliation of evidence-free legacy note mirrors."""
from __future__ import annotations

import contextlib
import io
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import UUID

from app.config.paths import resolve_vault_root
from app.knowledge.adapters import FsVaultAdapter
from app.knowledge.contracts import NoteLocator
from app.knowledge.profile_authority_store import assert_profile_note_ingestible
from app.rebuildability.product_total_loss import capture_source_frontmatter, canonical_product_source_text


def assert_admission_layers(*layers: dict) -> None:
    """Negative markers cannot be hidden behind a permissive persisted alias."""
    for layer in layers:
        authority = layer.get("authority")
        if (
            ("candidate_only" in layer and layer["candidate_only"] is not False)
            or layer.get("artifact_class") in ("youtube_source_note", "youtube_source_note_proposal")
            or ("authority" in layer and not isinstance(authority, dict))
            or (isinstance(authority, dict) and (
                ("source_authoritative" in authority and type(authority["source_authoritative"]) is not bool)
                or ("requires_review" in authority and type(authority["requires_review"]) is not bool)
                or authority.get("source_authoritative") is False
                or authority.get("requires_review") is True
            ))
            or ("trust" in layer and layer["trust"] not in ("unreviewed", "trusted", "reviewed", "human", "own"))
            or ("review_state" in layer and layer["review_state"] not in ("provisional", "reviewed", "protected", "archived"))
        ):
            raise ValueError("source admission refused")


@contextlib.contextmanager
def private_source_output() -> Iterator[None]:
    """Keep the complete private one-shot, including library logs, content-free."""
    previous_logging_disable = logging.root.manager.disable
    try:
        # This entrypoint belongs to a private synchronous CLI process, not a
        # request handler. Existing log handlers can retain the old stderr, so
        # redirecting streams alone cannot protect settings/quarantine paths.
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        logging.disable(previous_logging_disable)


def reconcile_legacy_sources(binding: Any, index: Any, client_factory: Callable[..., Any]) -> int:
    with private_source_output():
        return _reconcile_legacy_sources(binding, index, client_factory)


def _reconcile_legacy_sources(binding: Any, index: Any, client_factory: Callable[..., Any]) -> int:
    """Re-prove canonical policy; never infer authority from a legacy payload.

    The caller owns guarded native deployment/quiescence. All source streams
    remain private, and the CLI translates exceptions into a finite refusal.
    """
    from app.ingest import vault_alpha as producer
    from app.index.artifact_metadata import build_indexed_unit_payload, canonicalize_indexable_text
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.vault.manager import iter_vault_markdown_files
    from app.vault.paths import get_vault_system_dir_rel
    from app.write_guard import DEFAULT_WRITE_GUARD, SOURCE_BACKED_REBUILD_ACTION

    DEFAULT_WRITE_GUARD.assert_writes_allowed(SOURCE_BACKED_REBUILD_ACTION)
    present = index.present_object_ids()
    candidates = [row for row in binding.store.list_objects(limit=None)
                  if str(row["object_id"]) not in present
                  and isinstance(row.get("payload"), dict)
                  and canonicalize_indexable_text(row["payload"])
                  and "frontmatter" not in row["payload"]]
    if not candidates:
        return 0
    root = resolve_vault_root().resolve(strict=True)
    adapter = FsVaultAdapter(root)
    count = 0
    for row in candidates:
        payload = row["payload"]
        if row.get("kind") != "note" or not isinstance(row.get("source_ref"), str):
            raise ValueError("legacy source refused")
        source = Path(row["source_ref"])
        relative = source.relative_to(root) if source.is_absolute() else source
        locator = NoteLocator(vault="active", path=relative.as_posix())
        snapshot = adapter.read_recovery_snapshot(locator)
        raw, _identity = snapshot
        frontmatter = capture_source_frontmatter(raw)
        if frontmatter is None:
            raise ValueError("legacy source malformed")
        parsed, body, error = parse_bounded_frontmatter(raw)
        if error is not None or "\x00" in raw:
            raise ValueError("legacy source malformed")
        assert_admission_layers(frontmatter, payload)
        assert_admission_layers({"review_state": producer._canonical_review_state(parsed)})
        if "origin" in payload and payload["origin"] != "vault":
            raise ValueError("legacy origin refused")
        if "core6" in payload:
            if not isinstance(payload["core6"], dict):
                raise ValueError("legacy admission malformed")
            assert_admission_layers(payload["core6"])
        if producer._is_unindexed_system_path(relative, system_root=Path(get_vault_system_dir_rel(root))):
            raise ValueError("staged source refused")
        # Only an exact current meaning/identity match proves this old row is a
        # rebuildable projection of this source rather than accepted history.
        if canonicalize_indexable_text(payload) != canonical_product_source_text(raw):
            raise ValueError("legacy source drift")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            note = producer.resolve_vault_note_identity(root / relative, vault_root=root, frontmatter=parsed, body=body)
        if note.frontmatter_invalid or not note.frontmatter_uuid:
            raise ValueError("legacy source identity unknown")
        vault_uuid = note.note_uuid
        if parsed.get("uuid") and parsed.get("id") and str(parsed["uuid"]) != str(parsed["id"]):
            raise ValueError("ambiguous source identity")
        if "vault_uuid" in payload and str(payload["vault_uuid"]) != vault_uuid:
            raise ValueError("legacy source identity drift")
        if "replay" in payload and payload["replay"] != producer.product_replay_for_vault_note(
            root / relative, vault_root=root, source_text=raw,
        ):
            raise ValueError("legacy source provenance drift")
        assert_profile_note_ingestible(root, relative.as_posix(), vault_uuid, source_text=raw)

        def eligibility() -> bool:
            # Alpha, layout-aware root ingest and watcher ingestion share this
            # inventory. A missing/invalid layout is ambiguity, not exclusion.
            inventory = producer.select_source_backed_rebuild_candidates(root)
            selected = root / relative in inventory
            # The separate dev-only fs_watcher/vault-sync producer has a
            # broader inventory (VAULT_DIR/**/*.md except .obsidian). Native
            # deployment does not attest whether that optional producer is
            # enabled. If its configured/default scope overlaps this vault,
            # alpha exclusion alone cannot authorize retirement. Fail closed
            # rather than enabling that producer or using alpha to bypass it.
            legacy_root = Path(os.environ.get("VAULT_DIR", "vault")).expanduser().resolve()
            if (not selected and (root / relative).is_relative_to(legacy_root)
                    and not any(part.startswith(".obsidian") for part in (root / relative).parts)):
                raise ValueError("ambiguous producer inventory")
            claims = 0
            for path in iter_vault_markdown_files(root):
                text, _ = adapter.read_recovery_snapshot(NoteLocator(vault="active", path=path.relative_to(root).as_posix()))
                fm = capture_source_frontmatter(text)
                if fm is None:
                    raise ValueError("ambiguous source inventory")
                identities = set()
                for value in (fm.get("uuid"), fm.get("id")):
                    try:
                        identities.add(str(UUID(str(value))))
                    except (ValueError, TypeError):
                        continue
                if vault_uuid in identities:
                    claims += 1
            if claims != 1:
                raise ValueError("ambiguous source identity")
            return selected

        selected = eligibility()

        def revalidate() -> None:
            DEFAULT_WRITE_GUARD.assert_writes_allowed(SOURCE_BACKED_REBUILD_ACTION)
            if resolve_vault_root().resolve(strict=True) != root or adapter.read_recovery_snapshot(locator) != snapshot:
                raise ValueError("source changed")
            assert_profile_note_ingestible(root, relative.as_posix(), vault_uuid, source_text=raw)
            if eligibility() != selected:
                raise ValueError("source policy changed")

        replacement = None
        vector = None
        if selected:
            prepared: list[dict] = []
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                producer._ingest_single(root / relative, vault_root=root, trace_id="legacy-reconciliation",
                                       raw_text=raw, write_companion_record=False,
                                       reconcile_existing_projection=True, projection_sink=prepared.append)
            replacement = prepared[0]
            # The locked database seam re-proves the source UUID's canonical ID.
            replacement["artifact_id"] = replacement["stable_id"] = str(row["object_id"])
            assert_admission_layers(replacement["frontmatter"], replacement)
            client = client_factory(profile="default")
            text = canonicalize_indexable_text(replacement)
            embedding = client.embed_text(text)
            vector = dict(kind="note", source_ref=row["source_ref"],
                          payload=build_indexed_unit_payload(object_id=row["object_id"], kind="note",
                              source_ref=row["source_ref"], payload=replacement, text=text,
                              embedding_identity=client.identity),
                          embedding=embedding, model=client.identity.model, identity=client.identity)
        revalidate()
        binding.store.reconcile_legacy_source(row, vault_uuid=str(UUID(vault_uuid)), revalidate=revalidate,
                                              replacement=replacement, vector=vector)
        count += 1
    return count
