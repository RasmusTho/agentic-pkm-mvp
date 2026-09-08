"""Entity register v0 (Mimer-side, markdown-built) — Epic #3019 slice A1 (#3038).

Implements `docs/HEIMDAL/FABLE_COMPANION.md` §3.2 (the minimal register
contract) and §11#1 (Entity register v0, build-now before the first
published Heimdal event), ratified by `docs/adr/ADR-0049-...md` §1 and the
2026-07-05 owner ruling ("Decision run" item 1 in FABLE_COMPANION.md §9):
the register is **Mimer-owned** and **markdown-built** — file-per-entity
`.md` notes are the canonical store; any graph database is a derived,
rebuildable index (explicitly out of scope here).

Design decisions (binding for this slice):

- **Canonical store = one `.md` note per entity**, written through the same
  governed `write_note_relative` / `WriteGuard` seam every other vault write
  uses (`app.knowledge_acquisition.candidate_writeback` is the precedent
  this module follows). No graph DB, no relational table holds canonical
  identity — `test_mutations_are_evented_markdown_canonical` asserts this
  directly by reading the note file back off disk.
- **Mutation events on the existing outbox.** Every mutating op (mint /
  merge / split / redirect-fold) emits exactly one event via
  `app.services.outbox.write_outbox_event` + `derive_idempotency_key`,
  mirroring `app.knowledge_acquisition.stage_events` — lineage/audit, not a
  dispatched command (no worker branch, no schema registration).
- **Append-only truth (HEIM-1).** `merge()` and `split()` never delete or
  edit a prior identity in place: a merge marks the source entity
  `lifecycle: merged` with a `merged_into` redirect (and leaves its note on
  disk), and marks the target entity's `merged_from` with the source id
  appended (Epic #3019 slice A17, #3037: the target-side complement of the
  redirect); a split creates NEW entities and marks the merged entity
  redirects as reversed (`split_of` / superseded), removing the reversed id
  from the old target's `merged_from`, so `test_split_reverses_merge` can
  assert the pre-merge identities are restored under `resolve_redirects`.
- **Three-state resolution (HEIM-6 / HEIM-11).** `resolve()` returns exactly
  one of `ResolvedRef`, `AmbiguousCandidates`, or `UnresolvedProvisional` —
  never a bare string. This is enforced by construction: the return type is
  a closed union, not an optional plus a name field.
- **No direct DB imports across the Heimdal↔Mimer boundary.** This module
  only reads/writes vault notes (via the governed knowledge port) and the
  Mimer-internal outbox; it does not import anything under a hypothetical
  `app/heimdal_capture` or similar Heimdal-internal package. Heimdal's own
  pipeline calls `mint_provisional` / `resolve` / etc. as its integration
  point with Mimer, per ADR-0049 §1 ("Heimdal emits entity mentions only").

Out of scope (per the governing Issue): any graph/relationship index over
the register (derived, rebuildable-from-notes — not built here); Heimdal-side
resolution; attribution/mention extraction; consent, capture, ASR.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar, cast
from uuid import uuid4

import yaml

from app.events.models import new_event
from app.events.types import (
    HEIMDAL_REGISTER_ENTITY_MERGED,
    HEIMDAL_REGISTER_ENTITY_MINTED,
    HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED,
)
from app.heimdal.entity_review_operation_journal import (
    EntityRegisterSplitJournal, SplitJournalPort, SplitRecord, split_checkpoint_keys,
)
from app.knowledge.write_ops import read_note_text_with_version, write_note_relative
from app.services.outbox import derive_idempotency_key, write_outbox_event
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTER_WRITE_ACTION = "heimdal.entity_register.write"
ARTIFACT_CLASS = "heimdal_entity_register_entry"
DEFAULT_REGISTER_DIR = "_heimdal/register"

REGISTER_EVENT_SOURCE = "heimdal.entity_register"

# Register entry kinds (FABLE_COMPANION.md §3.2 field table).
KIND_PERSON = "person"
KIND_ORGANIZATION = "organization"
KIND_PROJECT = "project"
KIND_PLACE = "place"
KIND_AGENT = "agent"
KIND_THING = "thing"

# Lifecycle states (§3.2: "provisional -> canonical -> merged").
LIFECYCLE_PROVISIONAL = "provisional"
LIFECYCLE_CANONICAL = "canonical"
LIFECYCLE_MERGED = "merged"

# Note-effect states for one exact merge `(from_id -> into_id)` — the
# resumable-application vocabulary of `merge_effect_state` /
# `ensure_merge_effects` (EROJ-01, #4350).
MERGE_EFFECTS_NONE = "none"
MERGE_EFFECTS_SOURCE_ONLY = "source_only"
MERGE_EFFECTS_COMPLETE = "complete"


class EntityRegisterError(RuntimeError):
    """Raised for register contract violations (unknown id, bad merge, etc.)."""



_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_DEPTH = threading.local()
_F = TypeVar("_F", bound=Callable[..., Any])


def _locked(method: _F) -> _F:
    @wraps(method)
    def invoke(self: EntityRegister, *args: Any, **kwargs: Any) -> Any:
        with self.locked():
            return method(self, *args, **kwargs)
    return cast(_F, invoke)


def _complement_id(vault: str, from_id: str, into_id: str, operation_id: str | None) -> str:
    key = json.dumps([vault, from_id, into_id, operation_id], separators=(",", ":"))
    return ("cmp:operation:" if operation_id else "cmp:legacy:") + hashlib.sha256(key.encode()).hexdigest()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _direct_split_operation_id(
    entity_id: str, partition_criteria: Mapping[str, Sequence[str]]
) -> str:
    """Derive a retry-stable public split identity from its exact partition."""
    canonical_partition = {
        str(label): sorted(str(alias) for alias in aliases)
        for label, aliases in partition_criteria.items()
    }
    digest = hashlib.sha256(
        json.dumps(canonical_partition, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"direct-split:{entity_id}:{digest}"


def _new_canonical_id() -> str:
    return f"ent:{uuid4().hex}"


def _new_provisional_id() -> str:
    return f"ent:prov:{uuid4().hex}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "entity"


# ---------------------------------------------------------------------------
# Three-state resolution (§3.3, HEIM-6, HEIM-11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedRef:
    """`resolved`: exactly one canonical/provisional entity_id + confidence."""

    entity_id: str
    confidence: float


@dataclass(frozen=True)
class AmbiguousCandidates:
    """`ambiguous`: ranked candidates, no winner asserted."""

    candidates: tuple[ResolvedRef, ...]


@dataclass(frozen=True)
class UnresolvedProvisional:
    """`unresolved`: a freshly minted (or matched) provisional entity_id."""

    entity_id: str
    surface_form: str


ResolutionResult = ResolvedRef | AmbiguousCandidates | UnresolvedProvisional


# ---------------------------------------------------------------------------
# Register entry (§3.2 field table; Concept-compatible extension)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterEntry:
    """One entity register note's parsed frontmatter (`Concept`-compatible)."""

    entity_id: str
    kind: str
    label: str
    aliases: tuple[str, ...] = ()
    lifecycle: str = LIFECYCLE_PROVISIONAL
    merged_into: str | None = None
    merged_from: tuple[str, ...] = ()
    complement_id: str | None = None
    complements: tuple[Mapping[str, str], ...] = ()
    split_from: str | None = None
    lineage: tuple[Mapping[str, str], ...] = ()
    created: str = field(default_factory=_now_iso)
    updated: str = field(default_factory=_now_iso)

    def to_frontmatter(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "artifact_class": ARTIFACT_CLASS,
            "entity_id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "aliases": list(self.aliases),
            "lifecycle": self.lifecycle,
            "created": self.created,
            "updated": self.updated,
        }
        if self.merged_into is not None:
            data["merged_into"] = self.merged_into
        if self.merged_from:
            data["merged_from"] = list(self.merged_from)
        if self.complement_id is not None:
            data["complement_id"] = self.complement_id
        if self.complements:
            data["complements"] = [dict(c) for c in self.complements]
        if self.split_from is not None:
            data["split_from"] = self.split_from
        if self.lineage:
            data["lineage"] = [dict(link) for link in self.lineage]
        return data

    @classmethod
    def from_frontmatter(cls, data: Mapping[str, Any]) -> "RegisterEntry":
        complements = data.get("complements", [])
        if not isinstance(complements, (list, tuple)) or any(
            not isinstance(c, dict) or not all(isinstance(c.get(k), str) and c[k]
                for k in ("complement_id", "from_id", "into_id"))
            or ("operation_id" in c and (not isinstance(c["operation_id"], str) or not c["operation_id"]))
            for c in complements
        ):
            raise EntityRegisterError("malformed structured complement identity")
        cid = data.get("complement_id")
        if cid is not None and (not isinstance(cid, str) or not cid):
            raise EntityRegisterError("malformed source complement identity")
        for key in ("merged_from", "aliases"):
            value = data.get(key, [])
            if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v for v in value):
                raise EntityRegisterError(f"malformed register {key}")
        return cls(
            entity_id=str(data["entity_id"]),
            kind=str(data.get("kind", KIND_THING)),
            label=str(data.get("label", "")),
            aliases=tuple(data.get("aliases") or ()),
            lifecycle=str(data.get("lifecycle", LIFECYCLE_PROVISIONAL)),
            merged_into=data.get("merged_into"),
            merged_from=tuple(data.get("merged_from") or ()),
            complement_id=cid,
            complements=tuple(dict(c) for c in complements),
            split_from=data.get("split_from"),
            lineage=tuple(
                dict(link) for link in (data.get("lineage") or ()) if isinstance(link, Mapping)
            ),
            created=str(data.get("created", _now_iso())),
            updated=str(data.get("updated", _now_iso())),
        )


def render_entity_note(entry: RegisterEntry) -> str:
    """Render one entity note: YAML frontmatter (canonical fields) + a short
    human-readable body. The frontmatter block is the parsed source of truth
    (`from_frontmatter` round-trips it); the body is a human convenience.
    """
    frontmatter = entry.to_frontmatter()
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    aliases_line = ", ".join(entry.aliases) if entry.aliases else "_none recorded_"
    status_line = {
        LIFECYCLE_PROVISIONAL: "Provisional — unresolved recurring mention, not yet confirmed.",
        LIFECYCLE_CANONICAL: "Canonical register entry.",
        LIFECYCLE_MERGED: f"Merged into `{entry.merged_into}`. Follow the redirect for the current identity.",
    }.get(entry.lifecycle, entry.lifecycle)
    body = f"""
## {entry.label or entry.entity_id}

**Kind:** {entry.kind}
**Status:** {status_line}
**Aliases:** {aliases_line}

<!-- This note is the canonical register entry for this entity (Heimdal
entity register v0, ADR-0049 §1). Mutations (mint/merge/split/redirect) are
audit-evented; edits to this file outside the register API are not
reflected in the mutation log. -->
"""
    return f"---\n{yaml_block}\n---\n{body}"


def entity_note_path(entity_id: str, *, register_dir: str = DEFAULT_REGISTER_DIR) -> str:
    """Deterministic vault-relative path for an entity's canonical note.

    Derived from `entity_id` (never a random/incidental slug source) so a
    given entity always resolves to the same file across processes.
    """
    safe_dir = PurePosixPath(register_dir)
    slug = _slug(entity_id.replace(":", "-"))
    return (safe_dir / f"{slug}.md").as_posix()


# ---------------------------------------------------------------------------
# The register: a directory of entity notes + the v0 operations
# ---------------------------------------------------------------------------


class EntityRegister:
    """Entity register v0 over a directory of canonical `.md` notes.

    One instance is bound to one vault (`vault_context`) and one governed
    write path (`write_guard`). All mutating operations are synchronous,
    in-process, and each emits exactly one outbox mutation event immediately
    after the note write succeeds — mirroring
    `app.knowledge_acquisition.stage_events`'s "emit after effect, both
    idempotent" posture: a crash between note-write and event-emit is
    self-healing on retry because both the write (`write_note_relative`
    targeting a deterministic path) and the event (deterministic
    idempotency key) are themselves idempotent.
    """

    def __init__(
        self,
        *,
        vault_context: VaultContext,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
        register_dir: str = DEFAULT_REGISTER_DIR,
        conn: Any = None,
        split_journal: SplitJournalPort | None = None,
    ) -> None:
        if not vault_context.active_vault_path:
            raise EntityRegisterError("vault_context.active_vault_path is required")
        self._vault_root = Path(vault_context.active_vault_path).expanduser().resolve()
        # Canonical vault identity for operational records bound to this
        # register (EROJ-01, #4350): the vault-selection SoT id when the
        # context carries one, else the resolved root path. A mount/symlink
        # respelling of the same selected vault must NOT re-derive
        # entity-review operation ids — that silently duplicates merge events
        # instead of resuming (review F7 on #4350).
        active_vault_id = vault_context.active_vault_id
        if active_vault_id == "":
            raise EntityRegisterError(
                "vault_context.active_vault_id must not be empty; "
                "entity-review operation identity cannot fall back silently"
            )
        self._vault_identity = active_vault_id or str(self._vault_root)
        self._active_vault_id = active_vault_id
        self._write_guard = write_guard
        self._register_dir = register_dir
        self._note_versions: dict[str, str] = {}
        self._conn = conn
        self._split_journal = split_journal or EntityRegisterSplitJournal()

    @property
    def vault_identity(self) -> str:
        """Stable identity of the vault this register is bound to."""
        return self._vault_identity

    @property
    def vault_root(self) -> Path:
        """Resolved vault root bound to this register."""
        return self._vault_root

    @property
    def operation_vault_identity(self) -> str:
        """Return the selection-owned identity permitted for EROJ operations.

        Generic register mutations can still run in an explicitly supplied
        path-only context, but an entity-review journal row cannot: a path
        fallback and a selection id for the same vault would otherwise mint
        different operation namespaces.  The context id must agree with the
        root-local, vault-selection authority in ``settings/vault.md``;
        callers cannot establish operation identity by choosing an id shape.
        """
        if self._active_vault_id is None:
            raise EntityRegisterError(
                "entity-review operation identity requires a vault-scoped "
                "vault_context.active_vault_id; refusing path fallback"
            )
        try:
            vault_doc = MarkdownSettingsStore().read(self._vault_root / "settings" / "vault.md")
        except (OSError, MarkdownSettingsError) as exc:
            raise EntityRegisterError(
                "entity-review operation identity requires a vault-scoped "
                "settings/vault.md selection authority"
            ) from exc
        if vault_doc.frontmatter.get("schema") != "design-handoff.vault.v1":
            raise EntityRegisterError(
                "entity-review operation identity requires canonical "
                "settings/vault.md schema design-handoff.vault.v1"
            )
        persisted_vault_id = vault_doc.frontmatter.get("vaultId")
        if not isinstance(persisted_vault_id, str) or not persisted_vault_id:
            raise EntityRegisterError(
                "entity-review operation identity requires a non-empty vaultId "
                "in settings/vault.md"
            )
        if persisted_vault_id != self._active_vault_id:
            raise EntityRegisterError(
                "entity-review operation identity requires active_vault_id to "
                "match settings/vault.md vaultId; refusing synthetic identity "
                f"{self._active_vault_id!r}"
            )
        return self._active_vault_id

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Single-host register serialization, nested across confirm/merge/split.

        The scope is the canonical register directory. The host lock is outside
        the knowledge surface; all note effects still use the governed port.
        """
        key = str((self._vault_root / self._register_dir).resolve())
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(key, threading.RLock())
        with lock:
            depths = getattr(_LOCK_DEPTH, "depths", {})
            _LOCK_DEPTH.depths = depths
            if depths.get(key, 0):
                depths[key] += 1
                try:
                    yield
                finally:
                    depths[key] -= 1
                return
            path = Path(tempfile.gettempdir()) / ("entity-register-" + hashlib.sha256(key.encode()).hexdigest() + ".lock")
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                depths[key] = 1
                yield
            finally:
                depths.pop(key, None)
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    @staticmethod
    def _validate_legacy_split_copy(
        link: Mapping[str, str], entries: Mapping[str, RegisterEntry],
    ) -> None:
        """Authenticate the exact three-note shape written by the EROJ-02 producer."""
        required = {"predecessor_id", "successor_id", "operation_id", "mutation_kind", "reclaimed_from_id"}
        if set(link) != required or link.get("mutation_kind") != "split" or any(not link[k] for k in required):
            raise EntityRegisterError("legacy split has malformed producer lineage")
        predecessor, successor, reclaimed = (entries.get(link[k]) for k in
                                             ("predecessor_id", "successor_id", "reclaimed_from_id"))
        if predecessor is None or successor is None or reclaimed is None or successor.split_from != predecessor.entity_id:
            raise EntityRegisterError("legacy split lacks its producer-owned successor")
        for entry in (predecessor, successor, reclaimed):
            copies = [item for item in entry.lineage if item.get("mutation_kind") == "split"
                      and item.get("predecessor_id") == predecessor.entity_id
                      and item.get("reclaimed_from_id") == reclaimed.entity_id]
            if copies != [link]:
                raise EntityRegisterError("legacy split lacks one unambiguous copied producer link")

    @staticmethod
    def _validate_split_checkpoint(link: Mapping[str, str], record: SplitRecord | None) -> None:
        cid = link.get("complement_id")
        if (not cid or record is None or not record.completed
            or record.plan["entity_id"] != link.get("predecessor_id")
            or "complement:" + cid not in record.checkpoints
            or not any(e["after"]["entity_id"] == link.get("successor_id")
                       and any(c["complement_id"] == cid and c["from_id"] == link.get("reclaimed_from_id")
                               for c in e["after"].get("complements", []))
                       for e in record.plan["effects"])):
            raise EntityRegisterError("target evolution split complement checkpoint mismatch")

    def _legacy_relation_origin(
        self, source: RegisterEntry, entries: Mapping[str, RegisterEntry],
    ) -> tuple[str, str | None]:
        merges = [link for link in source.lineage if link.get("mutation_kind") == "merge"
                  and link.get("predecessor_id") == source.entity_id]
        splits = [link for link in source.lineage if link.get("mutation_kind") == "split"
                  and link.get("reclaimed_from_id") == source.entity_id]
        if len(merges) > 1 or (splits and not merges):
            raise EntityRegisterError("ambiguous legacy original merge lineage")
        original_id = merges[0].get("successor_id") if merges else source.merged_into
        operation_id = merges[0].get("operation_id") if merges else None
        if original_id not in entries or (merges and not operation_id):
            raise EntityRegisterError("legacy relation lacks its original merge identity")
        assert original_id is not None
        current = original_id
        seen: set[str] = set()
        while current != source.merged_into:
            if current in seen:
                raise EntityRegisterError("legacy split lineage cycle")
            seen.add(current)
            hops = [link for link in splits if link.get("predecessor_id") == current]
            if len(hops) != 1:
                raise EntityRegisterError("legacy split lacks an unambiguous original-to-current path")
            record = self._split_journal.load_split(self.vault_identity, hops[0]["operation_id"])
            if "complement_id" in hops[0]:
                if source.complement_id != hops[0]["complement_id"]:
                    raise EntityRegisterError("legacy split chain has mismatched complement identity")
                self._validate_split_checkpoint(hops[0], record)
            else:
                self._validate_legacy_split_copy(hops[0], entries)
                if record is not None:
                    raise EntityRegisterError("journaled split cannot use legacy compatibility proof")
            current = hops[0]["successor_id"]
        if splits and not {source.label, *source.aliases}.issubset(entries[current].aliases):
            raise EntityRegisterError("legacy split lacks complete successor aliases")
        return original_id, operation_id

    def _validated_entries(
        self, entries: Sequence[RegisterEntry] | None = None, *,
        allow_source_only: tuple[str, str] | None = None,
        legacy: bool = False,
    ) -> dict[str, RegisterEntry]:
        """Validate the entire register before any effect; optionally plan legacy conversion."""
        all_entries = list(entries) if entries is not None else self._all_entries()
        by_id = {e.entity_id: e for e in all_entries}
        original_by_id = dict(by_id)
        if len(by_id) != len(all_entries):
            raise EntityRegisterError("duplicate entity notes in active register")
        memberships: dict[str, list[str]] = {}
        relations: dict[str, tuple[str, Mapping[str, str]]] = {}
        for target in all_entries:
            if len(set(target.merged_from)) != len(target.merged_from):
                raise EntityRegisterError("duplicate legacy complement membership")
            if target.complements and tuple(c["from_id"] for c in target.complements) != target.merged_from:
                raise EntityRegisterError("structured complement contradicts merged_from projection")
            for source_id in target.merged_from:
                memberships.setdefault(source_id, []).append(target.entity_id)
            for relation in target.complements:
                cid = relation["complement_id"]
                if cid in relations:
                    raise EntityRegisterError("duplicate global complement identity")
                if relation["into_id"] not in by_id:
                    raise EntityRegisterError("complement has missing original target")
                relations[cid] = (target.entity_id, relation)
        source_ids: set[str] = set()
        for source in all_entries:
            targets = memberships.get(source.entity_id, [])
            if source.lifecycle != LIFECYCLE_MERGED:
                if targets or source.complement_id is not None or source.merged_into is not None:
                    raise EntityRegisterError("complement source lacks a consistent redirect")
                continue
            target_id = source.merged_into
            if target_id not in by_id or target_id == source.entity_id:
                raise EntityRegisterError("complement redirect has missing opposite side or cycle")
            # Every redirect cycle is rejected before any compatibility write.
            seen = {source.entity_id}
            current: str | None = target_id
            while current:
                if current in seen:
                    raise EntityRegisterError("complement redirect cycle")
                seen.add(current)
                entry = by_id.get(current)
                if entry is None:
                    raise EntityRegisterError("complement redirect has missing opposite side")
                current = entry.merged_into if entry.lifecycle == LIFECYCLE_MERGED else None
            if not targets and allow_source_only == (source.entity_id, target_id):
                # A claimed merge retry alone may complete its missing target.
                if source.complement_id and source.complement_id in relations:
                    raise EntityRegisterError("source-only complement exists at another target")
                continue
            if targets != [target_id]:
                raise EntityRegisterError("complement has missing opposite side or multiple targets")
            target = original_by_id[target_id]
            matches = [c for c in target.complements if c["from_id"] == source.entity_id]
            legacy_origin = None
            if not matches and legacy and not target.complements:
                legacy_origin = self._legacy_relation_origin(source, original_by_id)
                original_id, original_operation = legacy_origin
                cid = _complement_id(self.vault_identity, source.entity_id, original_id, None)
                if source.complement_id not in (None, cid):
                    raise EntityRegisterError("missing structured complement for current identity")
                relation = {"complement_id": cid, "from_id": source.entity_id, "into_id": original_id}
                if original_operation:
                    relation["operation_id"] = original_operation
                matches = [relation]
            if len(matches) != 1:
                raise EntityRegisterError("missing or duplicate structured complement")
            relation = matches[0]
            cid = relation["complement_id"]
            if legacy and cid.startswith("cmp:legacy:"):
                # A durable target side is still an interrupted compatibility
                # state, not proof of the original merge or historical splits.
                original_id, original_operation = legacy_origin or self._legacy_relation_origin(source, original_by_id)
                if relation["into_id"] != original_id:
                    raise EntityRegisterError("legacy complement contradicts its original target")
                if original_operation:
                    if relation.get("operation_id", original_operation) != original_operation:
                        raise EntityRegisterError("legacy complement contradicts its original operation")
                    relation = {**relation, "operation_id": original_operation}
            expected_id = _complement_id(self.vault_identity, source.entity_id, relation["into_id"],
                relation.get("operation_id") if cid.startswith("cmp:operation:") else None)
            if cid != expected_id:
                raise EntityRegisterError("complement identity contradicts its original relation")
            expected_legacy = _complement_id(self.vault_identity, source.entity_id, relation["into_id"], None)
            if source.complement_id != cid and not (legacy and source.complement_id is None and cid == expected_legacy):
                raise EntityRegisterError("source/target complement identity mismatch")
            if cid in source_ids:
                raise EntityRegisterError("duplicate source complement identity")
            source_ids.add(cid)
            by_id[source.entity_id] = replace(by_id[source.entity_id], complement_id=cid)
            if not target.complements:
                # Collect all legacy pairs against the original snapshot before writing.
                existing = by_id[target_id]
                by_id[target_id] = replace(existing, complements=(*existing.complements, relation))
            else:
                existing = by_id[target_id]
                by_id[target_id] = replace(existing, complements=tuple(
                    relation if item["from_id"] == source.entity_id else item for item in existing.complements))
        if set(memberships) - set(by_id):
            raise EntityRegisterError("complement has missing source note")
        if set(relations) - source_ids:
            raise EntityRegisterError("complement has no matching source identity")
        # Preserve the compatibility projection's original order.
        for key, entry in list(by_id.items()):
            if entry.complements:
                records = {c["from_id"]: c for c in entry.complements}
                by_id[key] = replace(entry, complements=tuple(records[k] for k in entry.merged_from))
        return by_id

    @_locked
    def backfill_complements(self) -> None:
        planned = self._validated_entries(legacy=True)
        for entry in self._all_entries():
            updated = planned[entry.entity_id]
            if updated != entry:
                self._write_entry(updated)

    # -- internal note IO ---------------------------------------------------

    def _note_path(self, entity_id: str) -> Path:
        return self._vault_root / entity_note_path(entity_id, register_dir=self._register_dir)

    def _read_entry(self, entity_id: str) -> RegisterEntry | None:
        path = self._note_path(entity_id)
        if not path.exists():
            return None
        text, version = read_note_text_with_version(path)
        self._note_versions[entity_id] = version
        if not text.startswith("---"):
            raise EntityRegisterError(f"malformed register note at {path}: missing frontmatter")
        _, _, rest = text.partition("---\n")
        frontmatter_text, _, _ = rest.partition("\n---")
        data = yaml.safe_load(frontmatter_text) or {}
        entry = RegisterEntry.from_frontmatter(data)
        if entry.entity_id != entity_id:
            raise EntityRegisterError("register note identity disagrees with its path")
        return entry

    def _write_entry(self, entry: RegisterEntry) -> None:
        self._write_guard.assert_writes_allowed(REGISTER_WRITE_ACTION)
        rel_path = entity_note_path(entry.entity_id, register_dir=self._register_dir)
        content = render_entity_note(entry)
        write_note_relative(
            rel_path,
            content,
            vault_root=self._vault_root,
            action=REGISTER_WRITE_ACTION,
            write_guard=self._write_guard,
            expected_version=self._note_versions.get(entry.entity_id),
        )
        self._note_versions[entry.entity_id] = hashlib.sha256(content.encode()).hexdigest()

    def _all_entries(self) -> list[RegisterEntry]:
        register_root = self._vault_root / self._register_dir
        if not register_root.exists():
            return []
        entries: list[RegisterEntry] = []
        for note_path in sorted(register_root.glob("*.md")):
            text, version = read_note_text_with_version(note_path)
            if not text.startswith("---"):
                raise EntityRegisterError("malformed register note; global complement preflight refused")
            _, _, rest = text.partition("---\n")
            frontmatter_text, _, _ = rest.partition("\n---")
            data = yaml.safe_load(frontmatter_text) or {}
            if not isinstance(data, dict) or "entity_id" not in data:
                raise EntityRegisterError("malformed register note identity")
            entry = RegisterEntry.from_frontmatter(data)
            if self._note_path(entry.entity_id) != note_path:
                raise EntityRegisterError("duplicate or misplaced register note identity")
            self._note_versions[entry.entity_id] = version
            entries.append(entry)
        return entries

    # -- mutation-event emission ---------------------------------------------

    def _emit(self, topic: str, *, entity_id: str, fingerprint_scope: str, payload: Mapping[str, Any]) -> str:
        key = derive_idempotency_key(topic, entity_id, fingerprint_scope)
        event = new_event(event_type=topic, payload=dict(payload), source=REGISTER_EVENT_SOURCE)
        return write_outbox_event(event, conn=self._conn, idempotency_key=key)

    # -- v0 operations (§3.2) ------------------------------------------------

    @_locked
    def mint_provisional(
        self, surface_form: str, *, kind_hint: str = KIND_THING
    ) -> UnresolvedProvisional:
        """`mint_provisional(surface_form, kind_hint) -> ent:prov:<uuid>`.

        Unknowns become durable provisional entities immediately, so
        recurrence is linkable from the first sighting. Emits
        `heimdal.register.entity.minted`.
        """
        entity_id = _new_provisional_id()
        entry = RegisterEntry(
            entity_id=entity_id,
            kind=kind_hint,
            label=surface_form,
            aliases=(surface_form,),
            lifecycle=LIFECYCLE_PROVISIONAL,
        )
        self._write_entry(entry)
        self._emit(
            HEIMDAL_REGISTER_ENTITY_MINTED,
            entity_id=entity_id,
            fingerprint_scope=f"mint:{surface_form}:{kind_hint}",
            payload={
                "entity_id": entity_id,
                "surface_form": surface_form,
                "kind_hint": kind_hint,
                "lifecycle": LIFECYCLE_PROVISIONAL,
            },
        )
        return UnresolvedProvisional(entity_id=entity_id, surface_form=surface_form)

    @_locked
    def mint_canonical(
        self, label: str, *, kind: str = KIND_THING, aliases: Sequence[str] = ()
    ) -> str:
        """Mint a canonical (non-provisional) entity directly.

        Not part of the four contract-named v0 operations, but required
        plumbing so `resolve()` has canonical entities to find and so
        `merge()`/`split()` have real canonical targets to exercise — the
        contract's `resolve`/`mint_provisional`/`merge`/`resolve_redirects`
        presuppose canonical entities exist via some admission path.
        """
        entity_id = _new_canonical_id()
        entry = RegisterEntry(
            entity_id=entity_id,
            kind=kind,
            label=label,
            aliases=tuple(aliases),
            lifecycle=LIFECYCLE_CANONICAL,
        )
        self._write_entry(entry)
        self._emit(
            HEIMDAL_REGISTER_ENTITY_MINTED,
            entity_id=entity_id,
            fingerprint_scope=f"mint_canonical:{label}:{kind}",
            payload={
                "entity_id": entity_id,
                "label": label,
                "kind": kind,
                "aliases": list(aliases),
                "lifecycle": LIFECYCLE_CANONICAL,
            },
        )
        return entity_id

    def resolve(
        self,
        surface_form: str,
        *,
        kind_hint: str = KIND_THING,
        context: Mapping[str, Any] | None = None,
    ) -> ResolutionResult:
        """`resolve(surface_form, kind_hint, context) -> resolved | ambiguous | unresolved`.

        v0 resolver: exact label/alias match against non-merged entries.
        Zero matches -> `UnresolvedProvisional` (mints a new provisional
        entity, per §3.3: "even the unknown is an id"). One match ->
        `ResolvedRef`. Multiple matches -> `AmbiguousCandidates`, no winner
        asserted (never guessed into a canonical identity, HEIM-6).
        """
        del context  # v0: context is accepted for contract shape, unused by the exact matcher.
        needle = surface_form.strip().lower()
        matches: list[RegisterEntry] = []
        for entry in self._all_entries():
            if entry.lifecycle == LIFECYCLE_MERGED:
                continue  # resolve() never returns a redirected identity directly
            names = {entry.label.strip().lower(), *(a.strip().lower() for a in entry.aliases)}
            if needle in names:
                matches.append(entry)

        if not matches:
            minted = self.mint_provisional(surface_form, kind_hint=kind_hint)
            return minted
        if len(matches) == 1:
            confidence = 1.0 if matches[0].lifecycle == LIFECYCLE_CANONICAL else 0.5
            return ResolvedRef(entity_id=matches[0].entity_id, confidence=confidence)
        ranked = tuple(
            ResolvedRef(
                entity_id=m.entity_id,
                confidence=1.0 if m.lifecycle == LIFECYCLE_CANONICAL else 0.5,
            )
            for m in matches
        )
        return AmbiguousCandidates(candidates=ranked)

    @_locked
    def merge(self, from_id: str, into_id: str, *, operation_id: str | None = None) -> None:
        """`merge(from_id, into_id)` — governed, human-confirmed convergence.

        Marks `from_id`'s entry `lifecycle: merged` with `merged_into =
        into_id` (append-only: the source note is never deleted, only
        redirected — HEIM-1), and marks `into_id`'s entry with `from_id`
        appended to `merged_from` — the target-side complement of the
        source's redirect (Epic #3019 slice A17, #3037: "a confirmed merge
        writes `merged_from:` plus a redirect"). Both sides of the merge are
        reversible via `split()` (red-team F5): a split re-points the
        source's `merged_into` and removes it from the target's
        `merged_from`, so neither field ever asserts a stale relationship.
        Callers are the human-confirmation call site; this method performs
        the mutation once confirmation has already happened (matching §9-g
        "human-confirmed by default": the confirmation gate lives at the
        caller, this is the mechanism). Emits `heimdal.register.entity.merged`.

        The entity-review applicator does NOT call this method: it applies the
        same note effects through :meth:`ensure_merge_effects` (resumable, no
        emission) and commits its `heimdal.register.entity.merged` event in the
        entity-review operation journal's atomic transaction instead (EROJ-01,
        #4350) so the event cannot exist without its committed operation row.
        """
        source = self._read_entry(from_id)
        target = self._read_entry(into_id)
        if source is None:
            raise EntityRegisterError(f"merge(): unknown from_id {from_id!r}")
        if target is None:
            raise EntityRegisterError(f"merge(): unknown into_id {into_id!r}")
        if from_id == into_id:
            raise EntityRegisterError("merge(): from_id and into_id must differ")

        # Public direct merges do not have an entity-review journal operation,
        # but they still need a durable, retry-stable lineage identity so a
        # later governed target evolution can be proven.  Review callers pass
        # their immutable journal operation id unchanged.
        effective_operation_id = operation_id or f"direct-merge:{from_id}:{into_id}"
        self.ensure_merge_effects(from_id, into_id, operation_id=effective_operation_id)

        self._emit(
            HEIMDAL_REGISTER_ENTITY_MERGED,
            entity_id=from_id,
            fingerprint_scope=f"merge:{self.vault_identity}:{effective_operation_id}",
            payload={"from_id": from_id, "into_id": into_id},
        )

    @_locked
    def merge_effect_state(self, from_id: str, into_id: str) -> str:
        self._validated_entries(allow_source_only=(from_id, into_id))
        return self._merge_effect_state(from_id, into_id)

    def _merge_effect_state(self, from_id: str, into_id: str, *, entries: Mapping[str, RegisterEntry] | None = None) -> str:
        """Read-only classification of the note effects for one exact merge.

        EROJ-01 (#4350) resume support: after a crash mid-merge, the retry must
        prove from current notes exactly which side of `(from_id -> into_id)`
        was written. Returns one of :data:`MERGE_EFFECTS_NONE` (no effect yet),
        :data:`MERGE_EFFECTS_SOURCE_ONLY` (redirect written, target complement
        absent), or :data:`MERGE_EFFECTS_COMPLETE` (both sides present).

        Fails closed (INV-EROJ-6) instead of guessing: unknown ids, a
        self-merge, a source redirect pointing at a *different* target (the
        original effect can no longer be proven from current notes — a
        pre-existing merge, or post-effect target evolution whose lineage
        proof is EROJ-02, out of scope here), or contradictory notes (an
        unmerged source that the target already claims in `merged_from`) all
        raise `EntityRegisterError`.
        """
        read_entry: Callable[[str], RegisterEntry | None] = (lambda key: entries.get(key)) if entries is not None else self._read_entry
        source = read_entry(from_id)
        target = read_entry(into_id)
        if source is None:
            raise EntityRegisterError(f"merge_effect_state(): unknown from_id {from_id!r}")
        if target is None:
            raise EntityRegisterError(f"merge_effect_state(): unknown into_id {into_id!r}")
        if from_id == into_id:
            raise EntityRegisterError("merge_effect_state(): from_id and into_id must differ")
        target_claims_source = from_id in target.merged_from
        # A source-reclaiming split is a durable, source-bound recovery proof.
        # It must be considered before the old target's current redirect: the
        # original target may later merge elsewhere after the source was
        # reclaimed, and that unrelated residual evolution cannot invalidate
        # the original operation's recovery path.
        if source.lifecycle == LIFECYCLE_MERGED and source.merged_into != into_id:
            if source.merged_into is None:
                raise EntityRegisterError(
                    "merge_effect_state(): merged source lacks a redirect target"
                )
            original_links = [
                link for link in source.lineage
                if link.get("predecessor_id") == from_id
                and link.get("successor_id") == into_id
                and link.get("mutation_kind") == "merge"
                and isinstance(link.get("operation_id"), str)
                and link.get("operation_id")
            ]
            if len(original_links) == 1:
                # The immediate split successor must retain the complete
                # reclaimed-source complement. Any later evolution, including
                # consecutive source-reclaim splits, is accepted only through
                # the resolver, which proves each explicit hop (and rejects
                # cycles or ambiguity) before this classification may resume
                # the original operation.
                resolved_target = self._resolve_target_evolution(
                    from_id,
                    into_id,
                    operation_id=str(original_links[0]["operation_id"]), entries=entries,
                )
                # The source redirect may still point at the immediate
                # reclaimed successor while that successor has since merged
                # onward. Cross-check the resolver's proven terminal target
                # against the complete current redirect chain without calling
                # resolve_redirects(), whose public read emits a derived event.
                redirect_target = source.merged_into
                redirect_seen = {from_id}
                while redirect_target:
                    if redirect_target in redirect_seen:
                        raise EntityRegisterError(
                            "merge_effect_state(): target evolution redirect cycle; "
                            "queue entry stays pending"
                        )
                    redirect_seen.add(redirect_target)
                    redirect_entry = read_entry(redirect_target)
                    if redirect_entry is None:
                        raise EntityRegisterError(
                            "merge_effect_state(): target evolution redirect has a "
                            "missing successor"
                        )
                    if (
                        redirect_entry.lifecycle != LIFECYCLE_MERGED
                        or not redirect_entry.merged_into
                    ):
                        break
                    redirect_target = redirect_entry.merged_into
                if resolved_target == redirect_target:
                    return MERGE_EFFECTS_COMPLETE
            raise EntityRegisterError(
                f"merge_effect_state(): {from_id!r} redirects to "
                f"{source.merged_into!r}, not {into_id!r}; the original effect cannot "
                "be proven from current notes and this slice refuses target-evolved "
                "recovery (EROJ-02)"
            )
        if target.lifecycle == LIFECYCLE_MERGED:
            # Target-evolution refusal (INV-EROJ-7, partial-failure matrix row
            # 5): the human-decided target has itself been merged away, so this
            # slice can neither begin a merge into it nor prove that resuming
            # one recovers the original decision rather than rewriting it.
            # EROJ-02's lineage proof owns that recovery; until then the
            # decision history stays unchanged and the queue entry pending.
            original_links = [
                link for link in source.lineage
                if link.get("predecessor_id") == from_id
                and link.get("successor_id") == into_id
                and link.get("mutation_kind") == "merge"
                and isinstance(link.get("operation_id"), str)
                and link.get("operation_id")
            ]
            if len(original_links) != 1:
                raise EntityRegisterError(
                    f"merge_effect_state(): into_id {into_id!r} is merged into "
                    f"{target.merged_into!r}; the target has evolved but lacks operation-bound proof"
                )
            if source.lifecycle != LIFECYCLE_MERGED or source.merged_into != into_id:
                raise EntityRegisterError(
                    "merge_effect_state(): target evolution lacks the original source redirect"
                )
            if not target_claims_source:
                raise EntityRegisterError(
                    "merge_effect_state(): target evolution lacks the original target complement"
                )
            self._resolve_target_evolution(
                from_id, into_id, operation_id=str(original_links[0]["operation_id"]), entries=entries
            )
            return MERGE_EFFECTS_COMPLETE

        if source.lifecycle == LIFECYCLE_MERGED:
            return MERGE_EFFECTS_COMPLETE if target_claims_source else MERGE_EFFECTS_SOURCE_ONLY
        if target_claims_source:
            raise EntityRegisterError(
                f"merge_effect_state(): {into_id!r} claims {from_id!r} in merged_from but "
                f"{from_id!r} carries no redirect; contradictory notes fail closed "
                "(INV-EROJ-6)"
            )
        return MERGE_EFFECTS_NONE

    @_locked
    def preflight_merge_effects_for_operation(
        self, from_id: str, into_id: str, *, operation_id: str
    ) -> str:
        """Prove a *new* journal operation can own the observed merge effects.

        This is deliberately read-only.  A fresh claim must not be persisted
        merely because generic effect classification says a pre-existing
        merge is complete: any existing effects need exactly one matching
        operation-bound original-merge link.  Legacy effects without a bound
        operation may only be backfilled by an already-claimed retry.
        """
        state = self.merge_effect_state(from_id, into_id)
        source = self._read_entry(from_id)
        assert source is not None  # proven by merge_effect_state
        original_links = [
            link for link in source.lineage
            if link.get("predecessor_id") == from_id
            and link.get("successor_id") == into_id
            and link.get("mutation_kind") == "merge"
        ]
        if state != MERGE_EFFECTS_NONE and (
            len(original_links) != 1
            or original_links[0].get("operation_id") != operation_id
        ):
            raise EntityRegisterError(
                "preflight_merge_effects_for_operation(): existing merge effects are not "
                "bound to this prospective operation"
            )
        return state

    @_locked
    def ensure_merge_effects(
        self, from_id: str, into_id: str, *, operation_id: str | None = None,
        require_complete: bool = False,
    ) -> str:
        """Idempotently apply the two note effects of one exact merge. No event.

        The mechanism half of :meth:`merge`, made resumable for the
        entity-review operation journal (EROJ-01, #4350): whichever of the
        source-redirect and target-complement writes is missing for exactly
        `(from_id -> into_id)` is applied; present effects are left untouched;
        anything unprovable fails closed via :meth:`merge_effect_state`. Never
        emits — the journal path commits its event atomically with the
        operation row, and :meth:`merge` keeps its own emission.

        Returns the pre-application :meth:`merge_effect_state` value. A committed
        journal retry may require complete effects, allowing only compatibility
        metadata backfill rather than replaying a missing merge.
        """
        effective_id = operation_id or f"direct-merge:{from_id}:{into_id}"
        source = self._read_entry(from_id)
        target = self._read_entry(into_id)
        if source is None or target is None or from_id == into_id:
            raise EntityRegisterError("merge(): unknown or identical relation endpoints")
        # Validate all unrelated relations before even binding old lineage.
        planned = self._validated_entries(legacy=True, allow_source_only=(from_id, into_id))
        if source.lifecycle == LIFECYCLE_MERGED:
            links = [l for l in source.lineage if l.get("mutation_kind") == "merge"
                     and l.get("predecessor_id") == from_id and l.get("successor_id") == into_id]
            if links and (len(links) != 1 or links[0].get("operation_id") != effective_id):
                raise EntityRegisterError("ensure_merge_effects(): original redirect has conflicting operation lineage")
        if source.lifecycle == LIFECYCLE_MERGED and source.merged_into == into_id:
            old = planned[from_id]
            original_links = [l for l in old.lineage if l.get("mutation_kind") == "merge"
                              and l.get("predecessor_id") == from_id and l.get("successor_id") == into_id]
            if not original_links:
                planned[from_id] = replace(old, lineage=(*old.lineage, {
                    "predecessor_id": from_id, "successor_id": into_id,
                    "operation_id": effective_id, "mutation_kind": "merge"}))
        # An authenticated retry can supply an operation that old notes did not
        # record. Preserve the deterministic legacy identity while binding that
        # operation on the current owner of the original complement.
        current_source = planned[from_id]
        if current_source.lifecycle == LIFECYCLE_MERGED:
            assert current_source.merged_into is not None  # globally validated above
            current_target = planned[current_source.merged_into]
            bound = []
            for relation in current_target.complements:
                if relation["from_id"] == from_id and relation["into_id"] == into_id:
                    if relation.get("operation_id", effective_id) != effective_id:
                        raise EntityRegisterError("merge complement operation mismatch")
                    relation = {**relation, "operation_id": effective_id}
                bound.append(relation)
            planned[current_target.entity_id] = replace(current_target, complements=tuple(bound))
        state = self._merge_effect_state(from_id, into_id, entries=planned)
        if require_complete and state != MERGE_EFFECTS_COMPLETE:
            raise EntityRegisterError("committed merge lacks complete note effects")
        if state == MERGE_EFFECTS_COMPLETE:
            self._validated_entries(list(planned.values()))
            for old in self._all_entries():
                if planned[old.entity_id] != old:
                    self._write_entry(planned[old.entity_id])
            return state
        source = planned[from_id]
        target = planned[into_id]
        cid = source.complement_id or _complement_id(self.vault_identity, from_id, into_id, effective_id)
        if source.complement_id and state == MERGE_EFFECTS_SOURCE_ONLY and source.complement_id != _complement_id(self.vault_identity, from_id, into_id, effective_id):
            raise EntityRegisterError("source-only merge complement does not match operation")
        link = {"predecessor_id": from_id, "successor_id": into_id,
                "operation_id": effective_id, "mutation_kind": "merge"}
        matching = [l for l in source.lineage if l.get("mutation_kind") == "merge"
                    and l.get("predecessor_id") == from_id and l.get("successor_id") == into_id]
        merged_source = replace(source, lifecycle=LIFECYCLE_MERGED, merged_into=into_id,
                                complement_id=cid, lineage=source.lineage if matching else (*source.lineage, link))
        relation = {"complement_id": cid, "from_id": from_id, "into_id": into_id, "operation_id": effective_id}
        existing = [c for c in target.complements if c["from_id"] == from_id]
        if existing and (existing[0]["complement_id"] != cid or existing[0].get("operation_id", effective_id) != effective_id):
            raise EntityRegisterError("merge complement operation mismatch")
        updated_target = replace(target,
            aliases=tuple(dict.fromkeys((*target.aliases, source.label, *source.aliases))),
            merged_from=tuple(dict.fromkeys((*target.merged_from, from_id))),
            complements=target.complements if existing else (*target.complements, relation))
        final = dict(planned)
        final[from_id] = merged_source
        final[into_id] = updated_target
        self._validated_entries(list(final.values()))
        # Complete validation precedes all compatibility and merge writes.
        for entry in self._all_entries():
            if entry.entity_id not in (from_id, into_id) and planned[entry.entity_id] != entry:
                self._write_entry(planned[entry.entity_id])
        if self._read_entry(from_id) != merged_source:
            self._write_entry(merged_source)
        if self._read_entry(into_id) != updated_target:
            self._write_entry(updated_target)
        return state

    @_locked
    def resolve_target_evolution(
        self, from_id: str, into_id: str, *, operation_id: str
    ) -> str:
        """Prove a current target from operation-bound note lineage only.

        The journal's original pair is immutable.  Redirects merely cross-check
        producer-written lineage; they never supply historical evidence.
        """
        self._validated_entries()
        return self._resolve_target_evolution(from_id, into_id, operation_id=operation_id)

    def _resolve_target_evolution(self, from_id: str, into_id: str, *, operation_id: str,
                                  entries: Mapping[str, RegisterEntry] | None = None) -> str:
        read_entry: Callable[[str], RegisterEntry | None] = (lambda key: entries.get(key)) if entries is not None else self._read_entry
        source = read_entry(from_id)
        original = read_entry(into_id)
        if source is None or original is None:
            raise EntityRegisterError("target evolution has an unknown original entity")
        initial = [
            link for link in source.lineage
            if link.get("predecessor_id") == from_id
            and link.get("successor_id") == into_id
            and link.get("operation_id") == operation_id
            and link.get("mutation_kind") == "merge"
        ]
        if len(initial) != 1:
            raise EntityRegisterError("target evolution lacks the journal-bound original merge proof")
        all_entries = (
            dict(entries)
            if entries is not None
            else {entry.entity_id: entry for entry in self._all_entries()}
        )
        original_source = all_entries[from_id]
        original_complements = [
            relation
            for entry in all_entries.values()
            for relation in entry.complements
            if relation["complement_id"] == original_source.complement_id
            and relation["from_id"] == from_id
            and relation["into_id"] == into_id
        ]
        if (
            original_source.complement_id is None
            or len(original_complements) != 1
            or original_complements[0].get("operation_id") != operation_id
        ):
            raise EntityRegisterError(
                "target evolution lacks an operation-bound original complement proof"
            )
        current = into_id
        seen: set[str] = set()

        def validate_split_link(
            split_link: Mapping[str, str], visited: frozenset[tuple[str, str, str]] = frozenset()
        ) -> None:
            """Validate one split hop, including a consecutive source-reclaim hop."""
            reclaimed_from_id = split_link.get("reclaimed_from_id")
            predecessor_id = split_link.get("predecessor_id")
            successor_id = split_link.get("successor_id")
            if not (
                isinstance(reclaimed_from_id, str)
                and isinstance(predecessor_id, str)
                and isinstance(successor_id, str)
            ):
                raise EntityRegisterError(
                    "target evolution split lacks a complete reclaimed-source proof"
                )
            cid = split_link.get("complement_id")
            split_operation = split_link.get("operation_id")
            record = self._split_journal.load_split(self.vault_identity, str(split_operation))
            if cid is None:
                legacy_entries = dict(entries) if entries is not None else {e.entity_id: e for e in self._all_entries()}
                reclaimed = legacy_entries.get(reclaimed_from_id)
                if record is not None or reclaimed is None or not (reclaimed.complement_id or "").startswith("cmp:legacy:"):
                    raise EntityRegisterError("target evolution split complement checkpoint mismatch")
                self._validate_legacy_split_copy(split_link, legacy_entries)
                original_id, _ = self._legacy_relation_origin(reclaimed, legacy_entries)
                if reclaimed.complement_id != _complement_id(self.vault_identity, reclaimed_from_id, original_id, None):
                    raise EntityRegisterError("legacy split contradicts immutable complement identity")
            else:
                self._validate_split_checkpoint(split_link, record)
            hop_key = (predecessor_id, successor_id, reclaimed_from_id)
            if hop_key in visited:
                raise EntityRegisterError(
                    "target evolution lineage cycle; queue entry stays pending"
                )
            predecessor_entry = read_entry(predecessor_id)
            successor_entry = read_entry(successor_id)
            reclaimed_entry = read_entry(reclaimed_from_id)
            if predecessor_entry is None or successor_entry is None or reclaimed_entry is None:
                raise EntityRegisterError(
                    "target evolution split lacks a complete successor complement"
                )
            if cid is not None and reclaimed_entry.complement_id != cid:
                raise EntityRegisterError("target evolution split complement identity mismatch")
            if reclaimed_from_id in predecessor_entry.merged_from:
                raise EntityRegisterError(
                    "target evolution split has a contradictory partial complement"
                )
            if (
                reclaimed_from_id in successor_entry.merged_from
                and {reclaimed_entry.label, *reclaimed_entry.aliases}.issubset(
                    successor_entry.aliases
                )
            ):
                return

            # A consecutive source-reclaim split legitimately consumes the
            # prior successor's complement while preserving the proof in its
            # own lineage. Follow exactly one unambiguous next source-reclaim
            # link and validate that hop's successor complement; ambiguity or
            # a cycle remains fail-closed.
            continuation = [
                link for link in successor_entry.lineage
                if link.get("predecessor_id") == successor_id
                and link.get("mutation_kind") == "split"
                and link.get("reclaimed_from_id") == reclaimed_from_id
                and isinstance(link.get("successor_id"), str)
                and link.get("successor_id")
            ]
            if len(continuation) != 1:
                raise EntityRegisterError(
                    "target evolution split lacks the complete successor complement"
                )
            validate_split_link(continuation[0], visited | {hop_key})

        while True:
            if current in seen:
                raise EntityRegisterError("target evolution lineage cycle; queue entry stays pending")
            seen.add(current)
            entry = read_entry(current)
            if entry is None:
                raise EntityRegisterError("target evolution lineage has a missing successor")
            # A split can explicitly re-point an intermediate merged child.
            # That current redirect supersedes the child's older merge hop,
            # but only when the source-reclaim link names this exact child.
            re_pointed_splits = [
                link for link in entry.lineage
                if link.get("mutation_kind") == "split"
                and link.get("reclaimed_from_id") == current
                and entry.lifecycle == LIFECYCLE_MERGED
                and entry.merged_into == link.get("successor_id")
            ]
            source_reclaimed_splits = [
                link for link in (*source.lineage, *entry.lineage)
                if link.get("predecessor_id") == current
                and link.get("mutation_kind") == "split"
                and link.get("reclaimed_from_id") == from_id
                and isinstance(link.get("operation_id"), str)
                and link.get("operation_id")
            ]
            using_source_reclaimed_split = bool(source_reclaimed_splits)
            candidates = source_reclaimed_splits or re_pointed_splits or [
                link for link in (*source.lineage, *entry.lineage)
                if link.get("predecessor_id") == current
                and link.get("mutation_kind") in {"merge", "split"}
                and isinstance(link.get("operation_id"), str)
                and link.get("operation_id")
                and (
                    link.get("mutation_kind") != "split"
                    or link.get("reclaimed_from_id") in {*seen, from_id}
                )
            ]
            if not candidates:
                if entry.lifecycle == LIFECYCLE_MERGED:
                    raise EntityRegisterError("target evolution redirect lacks governed lineage")
                return current
            successors = {str(link["successor_id"]) for link in candidates if link.get("successor_id")}
            if len(successors) != 1:
                raise EntityRegisterError("target evolution lineage is fork-ambiguous")
            successor = successors.pop()
            # A cycle is already decisive and must not depend on whether its
            # synthetic/corrupt hop happens to retain a target complement.
            # Check it before validating the ordinary merge-hop effects so
            # diagnostics remain deterministic and the queue stays pending.
            if successor in seen:
                raise EntityRegisterError("target evolution lineage cycle; queue entry stays pending")
            split_candidates = [
                link for link in candidates if link.get("mutation_kind") == "split"
            ]
            for split_link in split_candidates:
                validate_split_link(split_link)
            if (
                entry.lifecycle == LIFECYCLE_MERGED
                and entry.merged_into != successor
                and not using_source_reclaimed_split
            ):
                raise EntityRegisterError("target evolution lineage contradicts the redirect")
            if any(link.get("mutation_kind") == "merge" for link in candidates):
                successor_entry = read_entry(successor)
                if successor_entry is None:
                    raise EntityRegisterError("target evolution lineage has a missing successor")
                folded_source_aliases = {entry.label, *entry.aliases}
                if (
                    current not in successor_entry.merged_from
                    or not folded_source_aliases.issubset(successor_entry.aliases)
                ):
                    raise EntityRegisterError(
                        "target evolution merge hop lacks the complete successor complement"
                    )
            current = successor

    @_locked
    def split(
        self, entity_id: str, partition_criteria: Mapping[str, Sequence[str]], *, operation_id: str | None = None
    ) -> tuple[str, ...]:
        """`split(entity_id, partition_criteria)` — reversible un-merge (F5 gate).

        `partition_criteria` maps a NEW canonical entity's label to the
        subset of aliases from `entity_id`'s current alias set that belong
        under it (the caller decides the partition; this mechanism performs
        it). Two supported shapes, both append-only:

        1. **Reversing a merge**: `entity_id` is a *target* that absorbed one
           or more merged sources. Splitting recreates a fresh canonical
           entity per partition key, redistributes the folded aliases, and
           — the reversibility contract `test_split_reverses_merge` checks —
           re-points any entity that had been merged into `entity_id` (and
           whose own label/aliases match a partition) so `resolve_redirects`
           on the ORIGINAL merged-away id now lands on the correct new
           entity instead of the (now over-broad) old target.
        2. **Splitting a single conflated entity** with no prior merge: same
           partitioning mechanism, no redirect re-pointing needed.

        The pre-split entity is never deleted: it is marked `lifecycle:
        merged` pointing at a synthetic reconciliation note is NOT created;
        instead it is simply superseded by the new entities it was split
        into, recorded via each new entity's `split_from`. `entity_id` itself
        stays `canonical` (it remains a legitimate identity for whatever
        aliases were NOT re-partitioned away) unless every alias was moved
        out, in which case it stays as an empty-alias canonical entry (still
        resolvable by its own label) — never silently removed, per HEIM-1.

        Emits one `heimdal.register.entity.split` event per resulting new
        entity. Returns the tuple of new entity_ids in partition-key order.
        """
        if not partition_criteria:
            raise EntityRegisterError("split(): partition_criteria must be non-empty")
        partition: list[list[Any]] = [[label, list(aliases)] for label, aliases in partition_criteria.items()]
        if any(not isinstance(label, str) or not label or isinstance(aliases, str)
               or any(not isinstance(alias, str) or not alias for alias in aliases)
               for label, aliases in partition_criteria.items()):
            raise EntityRegisterError("split(): malformed partition")
        direct_key = _direct_split_operation_id(entity_id, partition_criteria)
        effective_id = operation_id or direct_key
        generation = 0
        record = self._split_journal.load_split(self.vault_identity, effective_id)
        if operation_id is None:
            # The stable request key has contiguous generations. A partial
            # generation always wins over changes its own note writes caused.
            while record is not None:
                stored_generation = record.plan.get("direct_generation", 0)
                if (record.plan["entity_id"] != entity_id or record.plan["partition"] != partition
                    or record.plan.get("direct_request_key", direct_key if generation == 0 else None) != direct_key
                    or type(stored_generation) is not int or stored_generation != generation):
                    raise EntityRegisterError("split(): direct generation plan mismatch")
                if not record.completed:
                    break
                next_id = f"{direct_key}:generation:{generation + 1}"
                following = self._split_journal.load_split(self.vault_identity, next_id)
                if following is None:
                    normalized = self._validated_entries(legacy=True)
                    original = normalized.get(entity_id)
                    if original is None:
                        raise EntityRegisterError("split(): completed original is missing")
                    prior_original = RegisterEntry.from_frontmatter(record.plan["effects"][0]["after"])
                    requested_aliases = {a for _, aliases in partition for a in aliases}
                    new_aliases = (set(original.aliases) - set(prior_original.aliases)) & requested_aliases
                    new_children = [child for child in normalized.values()
                                    if child.merged_into == entity_id
                                    and child.complement_id not in record.plan["complement_ids"]
                                    and any({child.label, *child.aliases} & set(aliases) or child.label == label
                                            for label, aliases in partition)]
                    if not new_aliases and not new_children:
                        break
                    # A later matching input is new work; unrelated downstream
                    # evolution alone remains a replay of the latest generation.
                    self._validate_completed_split_notes(record, normalized)
                generation += 1
                effective_id = next_id
                record = following
        if record is None:
            original = self._read_entry(entity_id)
            if original is None:
                raise EntityRegisterError(f"split(): unknown entity_id {entity_id!r}")
            if original.lifecycle == LIFECYCLE_MERGED:
                raise EntityRegisterError("split(): target must be a current canonical/provisional entity")
            # Validate every legacy relation first, then persist only unambiguous backfill.
            normalized = self._validated_entries(legacy=True)
            original = normalized[entity_id]
            children = [e for e in normalized.values() if e.merged_into == entity_id]
            assignments: dict[str, int] = {}
            for child in children:
                matches = [i for i, (label, aliases) in enumerate(partition)
                           if {child.label, *child.aliases} & set(aliases) or child.label == label]
                if len(matches) > 1:
                    raise EntityRegisterError("split(): ambiguous source in multiple partitions")
                if matches:
                    i = matches[0]
                    if not {child.label, *child.aliases} <= {partition[i][0], *partition[i][1]}:
                        raise EntityRegisterError("split(): partition lacks complete source aliases")
                    assignments[child.entity_id] = i
            new_ids = [_new_canonical_id() for _ in partition]
            if len(set(new_ids)) != len(new_ids) or any(self._read_entry(i) for i in new_ids):
                raise EntityRegisterError("split(): successor identity collision")
            links: list[Mapping[str, str]] = []
            source_effects: list[dict[str, Any]] = []
            for child in children:
                if child.entity_id not in assignments:
                    continue
                successor = new_ids[assignments[child.entity_id]]
                assert child.complement_id is not None
                link = {"predecessor_id": entity_id, "successor_id": successor,
                        "operation_id": effective_id, "mutation_kind": "split",
                        "reclaimed_from_id": child.entity_id, "complement_id": child.complement_id}
                links.append(link)
                updated = replace(child, merged_into=successor, lineage=(*child.lineage, link))
                source_effects.append({"key": "source:" + child.complement_id,
                                       "before": child.to_frontmatter(), "after": updated.to_frontmatter()})
            moved = {a for _, aliases in partition for a in aliases}
            retained = tuple(c for c in original.complements if c["from_id"] not in assignments)
            updated_original = replace(original, aliases=tuple(a for a in original.aliases if a not in moved),
                merged_from=tuple(c["from_id"] for c in retained), complements=retained,
                lineage=(*original.lineage, *links))
            # Remove old ownership before adding the successor: no intermediate duplicate.
            effects: list[dict[str, Any]] = [{"key": "original", "before": original.to_frontmatter(),
                                            "after": updated_original.to_frontmatter()}]
            events: list[dict[str, Any]] = []
            for i, (label, aliases) in enumerate(partition):
                complements = tuple(c for c in original.complements if assignments.get(c["from_id"]) == i)
                successor_entry = RegisterEntry(entity_id=new_ids[i], kind=original.kind, label=label,
                    aliases=tuple(dict.fromkeys([label, *aliases])), lifecycle=LIFECYCLE_CANONICAL,
                    merged_from=tuple(c["from_id"] for c in complements), complements=complements,
                    split_from=entity_id, lineage=tuple(l for l in links if l["successor_id"] == new_ids[i]))
                effects.append({"key": "successor:" + new_ids[i], "before": None, "after": successor_entry.to_frontmatter()})
                events.append({"split_from": entity_id, "new_entity_id": new_ids[i], "label": label,
                               "aliases": aliases, "operation_id": effective_id,
                               "complement_ids": [c["complement_id"] for c in complements]})
            effects.extend(source_effects)
            plan = {"version": 1, "vault_identity": self.vault_identity, "operation_id": effective_id,
                    "entity_id": entity_id, "partition": partition, "successor_ids": new_ids,
                    "effects": effects, "events": events,
                    "complement_ids": [l["complement_id"] for l in links]}
            if operation_id is None:
                plan.update(direct_request_key=direct_key, direct_generation=generation)
            final = dict(normalized)
            for effect in effects:
                entry = RegisterEntry.from_frontmatter(effect["after"])
                final[entry.entity_id] = entry
            self._validated_entries(list(final.values()))
            self.backfill_complements()
            record = self._split_journal.prepare_split(SplitRecord(self.vault_identity, effective_id, plan))
        if (record.plan["entity_id"] != entity_id or record.plan["partition"] != partition
            or record.vault_identity != self.vault_identity or record.operation_id != effective_id):
            raise EntityRegisterError("split(): operation plan does not match requested partition")
        keys = split_checkpoint_keys(record.plan)
        if record.checkpoints != keys[:len(record.checkpoints)]:
            raise EntityRegisterError("split(): checkpoint mismatch")
        if record.completed:
            if record.checkpoints != keys:
                raise EntityRegisterError("split(): incomplete terminal checkpoints")
            self._validate_completed_split_notes(record, self._validated_entries())
            return tuple(record.plan["successor_ids"])
        # Authenticate every affected note before the first retry write. Only the
        # next unchecked effect may have landed without its checkpoint.
        current_entries = {e.entity_id: e for e in self._all_entries()}
        before_entries = dict(current_entries)
        for index, effect in enumerate(record.plan["effects"]):
            after = RegisterEntry.from_frontmatter(effect["after"])
            before = RegisterEntry.from_frontmatter(effect["before"]) if effect["before"] is not None else None
            current = current_entries.get(after.entity_id)
            if (current not in (before, after)
                or (index < len(record.checkpoints) and current != after)
                or (index > len(record.checkpoints) and current != before)):
                raise EntityRegisterError("split(): note/checkpoint mismatch; repair required")
            if before is None:
                before_entries.pop(after.entity_id, None)
            else:
                before_entries[after.entity_id] = before
        self._validated_entries(list(before_entries.values()))
        for effect in record.plan["effects"]:
            if effect["key"] in record.checkpoints:
                continue
            after = RegisterEntry.from_frontmatter(effect["after"])
            if self._read_entry(after.entity_id) != after:
                self._write_entry(after)
            if self._read_entry(after.entity_id) != after:
                raise EntityRegisterError("split(): note effect not visible")
            record = self._split_journal.checkpoint_split(record, effect["key"])
        self._validated_entries()
        for cid in record.plan["complement_ids"]:
            record = self._split_journal.checkpoint_split(record, "complement:" + cid)
        self._split_journal.finish_split(record)
        return tuple(record.plan["successor_ids"])

    @staticmethod
    def _validate_completed_split_notes(record: SplitRecord, entries: Mapping[str, RegisterEntry]) -> None:
        if record.checkpoints != split_checkpoint_keys(record.plan):
            raise EntityRegisterError("split(): incomplete terminal checkpoints")
        for effect in record.plan["effects"]:
            expected = RegisterEntry.from_frontmatter(effect["after"])
            observed = entries.get(expected.entity_id)
            if (observed is None or observed.split_from != expected.split_from
                or any(link not in observed.lineage for link in expected.lineage)):
                raise EntityRegisterError("split(): completed note or lineage evidence is missing")

    def resolve_redirects(self, entity_id: str) -> str:
        """`resolve_redirects(entity_id) -> entity_id` — follow merge chains.

        Every consumer of historical events uses this to translate a
        (possibly stale) entity_id into its current living identity. A
        non-merged entity resolves to itself. Cycle-safe: bounded by the
        number of register entries.
        """
        current = entity_id
        seen: set[str] = set()
        max_hops = max(len(self._all_entries()), 1) + 1
        for _ in range(max_hops):
            if current in seen:
                raise EntityRegisterError(f"resolve_redirects(): redirect cycle at {current!r}")
            seen.add(current)
            entry = self._read_entry(current)
            if entry is None:
                raise EntityRegisterError(f"resolve_redirects(): unknown entity_id {current!r}")
            if entry.lifecycle != LIFECYCLE_MERGED or not entry.merged_into:
                self._emit(
                    HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED,
                    entity_id=entity_id,
                    fingerprint_scope=f"redirect:{entity_id}:{current}",
                    payload={"queried_entity_id": entity_id, "resolved_entity_id": current},
                )
                return current
            current = entry.merged_into
        raise EntityRegisterError(f"resolve_redirects(): exceeded max hops resolving {entity_id!r}")

    # -- convenience read accessor -------------------------------------------

    def get_entry(self, entity_id: str) -> RegisterEntry | None:
        """Read-only accessor used by tests/consumers to inspect a note's
        parsed frontmatter without reaching into the filesystem directly."""
        return self._read_entry(entity_id)


__all__ = [
    "EntityRegister",
    "EntityRegisterError",
    "RegisterEntry",
    "ResolvedRef",
    "AmbiguousCandidates",
    "UnresolvedProvisional",
    "ResolutionResult",
    "REGISTER_WRITE_ACTION",
    "ARTIFACT_CLASS",
    "DEFAULT_REGISTER_DIR",
    "KIND_PERSON",
    "KIND_ORGANIZATION",
    "KIND_PROJECT",
    "KIND_PLACE",
    "KIND_AGENT",
    "KIND_THING",
    "LIFECYCLE_PROVISIONAL",
    "LIFECYCLE_CANONICAL",
    "LIFECYCLE_MERGED",
    "MERGE_EFFECTS_NONE",
    "MERGE_EFFECTS_SOURCE_ONLY",
    "MERGE_EFFECTS_COMPLETE",
    "entity_note_path",
    "render_entity_note",
]
