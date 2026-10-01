from __future__ import annotations

import uuid
from pathlib import Path

from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import dump_frontmatter

# Namespace of the deterministic, path-derived recovery identity shared with
# ``app.ingest.vault_alpha`` for notes that carry no persisted ``uuid``.
VAULT_NOTE_UUID_NAMESPACE = uuid.UUID("b6b2d8b3-8f2a-4a75-9c65-4c4a0d36b3b8")


def _new_note_uuid() -> str:
    """Allocate a fresh note-identity UUID.

    This is the single, single-purpose allocation seam for a *note's* identity
    (#3622). Infrastructure UUIDs generated elsewhere on the write path — e.g.
    the knowledge adapter's ``.rewrite-swap`` staging name and the
    ``concurrent-save-*`` conflict-artifact writer identity — are a separate
    concern and are deliberately not routed through here, so a test that counts
    note-identity allocations by patching this seam is not confounded by them.
    """
    return str(uuid.uuid4())


def is_read_only_derived_artifact(frontmatter: dict[str, object]) -> bool:
    """Return whether a note declares itself a byte-owned derived artifact.

    Agent-maintained, read-only, derived artifacts (for example the Daily Briefing) are
    owned end to end by their composer, and their readers verify the exact
    rendered bytes. A uuid heal would reserialize such a note under a second
    writer and make it unreadable (#5656), so identity healing never rewrites
    them; ``ensure_note_uuid`` returns a stable, unpersisted identity instead.
    """

    return (
        frontmatter.get("agent_maintained") is True
        and frontmatter.get("read_only") is True
        and frontmatter.get("authority_role") == "derived"
    )


def ensure_note_uuid(
    path: Path,
    *,
    vault_root: Path | str,
    preferred_uuid: str | None = None,
    write_action: str = "ensure uuid",
) -> str:
    resolved = Path(path).resolve()
    root = Path(vault_root).expanduser().resolve()
    resolved.relative_to(root)
    text, expected_version = read_note_text_with_version(resolved)
    frontmatter, body, _ = parse_bounded_frontmatter(text)
    existing = str(frontmatter.get("uuid") or "").strip()
    if existing:
        return existing
    candidate = str(preferred_uuid or "").strip()
    if is_read_only_derived_artifact(frontmatter):
        # No rewrite. The caller's resolved identity, else the same path-derived
        # recovery identity vault-alpha ingest uses, keeps every re-ingest of
        # the note on one stable object.
        return candidate or str(
            uuid.uuid5(VAULT_NOTE_UUID_NAMESPACE, resolved.relative_to(root).as_posix())
        )
    if not candidate:
        candidate = _new_note_uuid()
    frontmatter["uuid"] = candidate
    DEFAULT_WRITE_GUARD.assert_writes_allowed(write_action)
    write_note_from_absolute(
        resolved,
        dump_frontmatter(frontmatter, body),
        vault_root=root,
        action=write_action,
        expected_version=expected_version,
    )
    return candidate


__all__ = ["VAULT_NOTE_UUID_NAMESPACE", "ensure_note_uuid", "is_read_only_derived_artifact"]
