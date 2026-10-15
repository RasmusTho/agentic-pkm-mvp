"""Private, source-backed reconciliation of evidence-free legacy note mirrors."""
from __future__ import annotations

import contextlib
import io
import logging
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import UUID

from app.config.paths import resolve_vault_root
from app.ingest.producer_policy import FilesystemProducerPolicy, RegistryProducerPolicy
from app.knowledge.write_ops import read_recovery_snapshot_relative
from app.knowledge.profile_authority_store import assert_profile_note_ingestible
from app.rebuildability.product_total_loss import capture_source_frontmatter, canonical_product_source_text


LEGACY_RECONCILIATION_REASONS = frozenset({
    "legacy_producer_policy_refused", "legacy_source_refused", "legacy_admission_refused",
    "legacy_identity_refused", "legacy_race_refused", "legacy_write_failed",
    "embedding_generation_failed",
})


class LegacySourceRefusal(ValueError):
    """Only an allowlisted content-free class may cross the private boundary."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in LEGACY_RECONCILIATION_REASONS else "legacy_source_refused"
        super().__init__(self.reason)


def _producer_policy() -> FilesystemProducerPolicy:
    from app.ingest.producer_policy import filesystem_producer_policy
    try:
        return filesystem_producer_policy()
    except Exception:
        raise LegacySourceRefusal("legacy_producer_policy_refused") from None


def _registry_policy(root: Path) -> RegistryProducerPolicy:
    from app.ingest.producer_policy import registry_producer_policy
    try:
        return registry_producer_policy(root)
    except Exception:
        raise LegacySourceRefusal("legacy_producer_policy_refused") from None


def _source_uuid(value: object) -> str | None:
    """Use the producer's supported scalar/list/wikilink identity grammar."""
    from app.ingest.vault_alpha import _normalize_uuid, _sanitize_uuid

    normalized, invalid = _sanitize_uuid(_normalize_uuid(value))
    return normalized if normalized and not invalid else None


def assert_unique_projection_source(
    rows: list[dict], *, expected_id: str, root: Path, source_identity: str, vault_uuid: str,
) -> None:
    """Compare discovery locators canonically, never as raw stored spellings."""
    def normalized(value: str) -> str:
        # Conservative on case-sensitive hosts; ambiguous portable spellings
        # must not authorize retirement of either projection.
        return unicodedata.normalize("NFC", value).casefold()

    def source_key(value: str) -> str:
        path = Path(value.strip().replace("\\", "/")).expanduser()
        return normalized(str((path if path.is_absolute() else root / path).resolve()))

    target = source_key(source_identity)
    for row in rows:
        if str(row["object_id"]) == expected_id:
            continue
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        replay = payload.get("replay")
        replay = replay if isinstance(replay, dict) else {}
        locators = (row.get("source_ref"), replay.get("source_identity"))
        if any(source_key(value) == target
               for value in locators if isinstance(value, str)):
            raise LegacySourceRefusal("legacy_identity_refused")
        frontmatter = payload.get("frontmatter")
        frontmatter = frontmatter if isinstance(frontmatter, dict) else {}
        core = payload.get("core6")
        core = core if isinstance(core, dict) else {}
        claims = (payload.get("vault_uuid"), payload.get("artifact_id"), payload.get("stable_id"),
                  frontmatter.get("uuid"), frontmatter.get("id"), core.get("id"))
        for value in claims:
            if _source_uuid(value) in (vault_uuid, expected_id):
                raise LegacySourceRefusal("legacy_identity_refused")


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
            raise LegacySourceRefusal("legacy_admission_refused")


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
    policy = _producer_policy()
    registry_policy = _registry_policy(root)
    count = 0
    for row in candidates:
        payload = row["payload"]
        if row.get("kind") != "note" or not isinstance(row.get("source_ref"), str):
            raise LegacySourceRefusal("legacy_source_refused")
        source = Path(row["source_ref"])
        relative = source.relative_to(root) if source.is_absolute() else source
        snapshot = read_recovery_snapshot_relative(relative.as_posix(), vault_root=root)
        raw, _identity = snapshot
        frontmatter = capture_source_frontmatter(raw)
        if frontmatter is None:
            raise LegacySourceRefusal("legacy_source_refused")
        parsed, body, error = parse_bounded_frontmatter(raw)
        if error is not None or "\x00" in raw:
            raise LegacySourceRefusal("legacy_source_refused")
        assert_admission_layers(frontmatter, payload)
        assert_admission_layers({"review_state": producer._canonical_review_state(parsed)})
        if "origin" in payload and payload["origin"] != "vault":
            raise LegacySourceRefusal("legacy_admission_refused")
        if "core6" in payload:
            if not isinstance(payload["core6"], dict):
                raise LegacySourceRefusal("legacy_admission_refused")
            assert_admission_layers(payload["core6"])
        if producer._is_unindexed_system_path(relative, system_root=Path(get_vault_system_dir_rel(root))):
            raise LegacySourceRefusal("legacy_admission_refused")
        # Only an exact current meaning/identity match proves this old row is a
        # rebuildable projection of this source rather than accepted history.
        if canonicalize_indexable_text(payload) != canonical_product_source_text(raw):
            raise LegacySourceRefusal("legacy_race_refused")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            note = producer.resolve_vault_note_identity(root / relative, vault_root=root, frontmatter=parsed, body=body)
        if note.frontmatter_invalid or not note.frontmatter_uuid:
            raise LegacySourceRefusal("legacy_identity_refused")
        vault_uuid = note.note_uuid
        if any(parsed.get(key) and _source_uuid(parsed[key]) != vault_uuid for key in ("uuid", "id")):
            raise LegacySourceRefusal("legacy_identity_refused")
        if "vault_uuid" in payload and _source_uuid(payload["vault_uuid"]) != vault_uuid:
            raise LegacySourceRefusal("legacy_identity_refused")
        if "replay" in payload and payload["replay"] != producer.product_replay_for_vault_note(
            root / relative, vault_root=root, source_text=raw,
        ):
            raise LegacySourceRefusal("legacy_source_refused")
        def admission() -> None:
            try:
                assert_profile_note_ingestible(root, relative.as_posix(), vault_uuid, source_text=raw)
            except Exception:
                raise LegacySourceRefusal("legacy_admission_refused") from None

        admission()

        def eligibility() -> bool:
            # Alpha/targeted-alpha and native registry are distinct producers.
            # Every enabled producer must exclude a source before retirement.
            inventory = producer.select_source_backed_rebuild_candidates(root)
            selected = root / relative in inventory
            if _producer_policy() != policy:
                raise LegacySourceRefusal("legacy_producer_policy_refused")
            if _registry_policy(root) != registry_policy:
                raise LegacySourceRefusal("legacy_producer_policy_refused")
            if policy.includes(root / relative) and policy.root != root:
                # A producer bound to another source root cannot borrow this
                # active binding's relative replay/identity authority.
                raise LegacySourceRefusal("legacy_producer_policy_refused")
            try:
                filesystem_uuid = str(UUID(str(parsed.get("uuid") or "").strip()))
            except (ValueError, TypeError, AttributeError):
                filesystem_uuid = None
            if policy.includes(root / relative) and filesystem_uuid != vault_uuid:
                # The real FS adapter preserves only a literal uuid scalar;
                # id-only/encoded forms would acquire another identity when
                # it resumes. Recovery must refuse rather than heal a source.
                raise LegacySourceRefusal("legacy_identity_refused")
            if registry_policy.includes(root / relative):
                from app.services.note_uuid import inbox_uuid_heal_applies, is_read_only_derived_artifact
                try:
                    inbox_heal = inbox_uuid_heal_applies(root / relative, root)
                except Exception:
                    raise LegacySourceRefusal("legacy_producer_policy_refused") from None
                if (inbox_heal
                        and not str(parsed.get("uuid") or "").strip()
                        and not is_read_only_derived_artifact(parsed)):
                    # Ordinary registry workers heal inbox UUIDs before using
                    # their parsed id fallback. That new identity must not be
                    # introduced on resume after this recovery transition.
                    raise LegacySourceRefusal("legacy_identity_refused")
            claims = 0
            identity_sources = set(iter_vault_markdown_files(root)) | set(registry_policy.sources)
            if policy.root == root:
                identity_sources.update(policy.sources)
            for path in identity_sources:
                text, _ = read_recovery_snapshot_relative(path.relative_to(root).as_posix(), vault_root=root)
                fm = capture_source_frontmatter(text)
                if fm is None:
                    raise LegacySourceRefusal("legacy_identity_refused")
                identities = {_source_uuid(fm.get(key)) for key in ("uuid", "id")}
                if vault_uuid in identities:
                    claims += 1
            if claims != 1:
                raise LegacySourceRefusal("legacy_identity_refused")
            return selected or registry_policy.includes(root / relative) or policy.includes(root / relative)

        selected = eligibility()
        alpha_selected = root / relative in producer.select_source_backed_rebuild_candidates(root)

        def revalidate() -> None:
            DEFAULT_WRITE_GUARD.assert_writes_allowed(SOURCE_BACKED_REBUILD_ACTION)
            if resolve_vault_root().resolve(strict=True) != root or read_recovery_snapshot_relative(relative.as_posix(), vault_root=root) != snapshot:
                raise LegacySourceRefusal("legacy_race_refused")
            admission()
            if eligibility() != selected:
                raise LegacySourceRefusal("legacy_producer_policy_refused")
            if (root / relative in producer.select_source_backed_rebuild_candidates(root)) != alpha_selected:
                raise LegacySourceRefusal("legacy_producer_policy_refused")

        replacement = None
        vector = None
        if selected:
            prepared: list[dict] = []
            if registry_policy.includes(root / relative):
                from app.services.indexer import prepare_ingest_projection, watched_note_ingest_object
                event = watched_note_ingest_object(root / relative, parsed, body, note_uuid=vault_uuid,
                                                  source_text=raw, observation={})
                projection, _text, metadata = prepare_ingest_projection(event,
                    incoming_uuid=str(row["object_id"]), vault_root=root, source_snapshot=raw)
                projection.update(metadata)
                prepared.append(projection)
            elif alpha_selected:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    producer._ingest_single(root / relative, vault_root=root, trace_id="legacy-reconciliation",
                                           raw_text=raw, write_companion_record=False,
                                           reconcile_existing_projection=True, projection_sink=prepared.append)
            else:
                from app.services.vault_sync import prepare_note_projection
                prepared.append(prepare_note_projection(root / relative, parsed, body, vault_root=root))
            replacement = prepared[0]
            # The locked database seam re-proves the source UUID's canonical ID.
            replacement["artifact_id"] = replacement["stable_id"] = str(row["object_id"])
            assert_admission_layers(replacement["frontmatter"], replacement)
            text = canonicalize_indexable_text(replacement)
            try:
                client = client_factory(profile="default")
                embedding = client.embed_text(text)
            except Exception:
                raise LegacySourceRefusal("embedding_generation_failed") from None
            vector = dict(kind="note", source_ref=row["source_ref"],
                          payload=build_indexed_unit_payload(object_id=row["object_id"], kind="note",
                              source_ref=row["source_ref"], payload=replacement, text=text,
                              embedding_identity=client.identity),
                          embedding=embedding, model=client.identity.model, identity=client.identity)
        revalidate()
        try:
            binding.store.reconcile_legacy_source(row, vault_uuid=str(UUID(vault_uuid)), revalidate=revalidate,
                check_sources=lambda rows: assert_unique_projection_source(rows, expected_id=str(row["object_id"]),
                    root=root, source_identity=relative.as_posix(), vault_uuid=vault_uuid),
                                                  replacement=replacement, vector=vector)
        except LegacySourceRefusal:
            raise
        except Exception:
            raise LegacySourceRefusal("legacy_write_failed") from None
        count += 1
    return count
