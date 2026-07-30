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

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from uuid import uuid4

import yaml

from app.events.models import new_event
from app.events.types import (
    HEIMDAL_REGISTER_ENTITY_MERGED,
    HEIMDAL_REGISTER_ENTITY_MINTED,
    HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED,
    HEIMDAL_REGISTER_ENTITY_SPLIT,
)
from app.knowledge.write_ops import write_note_relative
from app.services.outbox import derive_idempotency_key, write_outbox_event
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    split_from: str | None = None
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
        if self.split_from is not None:
            data["split_from"] = self.split_from
        return data

    @classmethod
    def from_frontmatter(cls, data: Mapping[str, Any]) -> "RegisterEntry":
        return cls(
            entity_id=str(data["entity_id"]),
            kind=str(data.get("kind", KIND_THING)),
            label=str(data.get("label", "")),
            aliases=tuple(data.get("aliases") or ()),
            lifecycle=str(data.get("lifecycle", LIFECYCLE_PROVISIONAL)),
            merged_into=data.get("merged_into"),
            merged_from=tuple(data.get("merged_from") or ()),
            split_from=data.get("split_from"),
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
    ) -> None:
        if not vault_context.active_vault_path:
            raise EntityRegisterError("vault_context.active_vault_path is required")
        self._vault_root = Path(vault_context.active_vault_path).expanduser().resolve()
        self._write_guard = write_guard
        self._register_dir = register_dir
        self._conn = conn

    # -- internal note IO ---------------------------------------------------

    def _note_path(self, entity_id: str) -> Path:
        return self._vault_root / entity_note_path(entity_id, register_dir=self._register_dir)

    def _read_entry(self, entity_id: str) -> RegisterEntry | None:
        path = self._note_path(entity_id)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise EntityRegisterError(f"malformed register note at {path}: missing frontmatter")
        _, _, rest = text.partition("---\n")
        frontmatter_text, _, _ = rest.partition("\n---")
        data = yaml.safe_load(frontmatter_text) or {}
        return RegisterEntry.from_frontmatter(data)

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
        )

    def _all_entries(self) -> list[RegisterEntry]:
        register_root = self._vault_root / self._register_dir
        if not register_root.exists():
            return []
        entries: list[RegisterEntry] = []
        for note_path in sorted(register_root.glob("*.md")):
            text = note_path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            _, _, rest = text.partition("---\n")
            frontmatter_text, _, _ = rest.partition("\n---")
            data = yaml.safe_load(frontmatter_text) or {}
            if "entity_id" in data:
                entries.append(RegisterEntry.from_frontmatter(data))
        return entries

    # -- mutation-event emission ---------------------------------------------

    def _emit(self, topic: str, *, entity_id: str, fingerprint_scope: str, payload: Mapping[str, Any]) -> str:
        key = derive_idempotency_key(topic, entity_id, fingerprint_scope)
        event = new_event(event_type=topic, payload=dict(payload), source=REGISTER_EVENT_SOURCE)
        return write_outbox_event(event, conn=self._conn, idempotency_key=key)

    # -- v0 operations (§3.2) ------------------------------------------------

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

    def merge(self, from_id: str, into_id: str) -> None:
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
        if source.lifecycle == LIFECYCLE_MERGED:
            raise EntityRegisterError(
                f"merge(): {from_id!r} is already merged into {source.merged_into!r}"
            )
        if from_id == into_id:
            raise EntityRegisterError("merge(): from_id and into_id must differ")

        self.ensure_merge_effects(from_id, into_id)

        self._emit(
            HEIMDAL_REGISTER_ENTITY_MERGED,
            entity_id=from_id,
            fingerprint_scope=f"merge:{from_id}:{into_id}:{_now_iso()}",
            payload={"from_id": from_id, "into_id": into_id},
        )

    def merge_effect_state(self, from_id: str, into_id: str) -> str:
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
        source = self._read_entry(from_id)
        target = self._read_entry(into_id)
        if source is None:
            raise EntityRegisterError(f"merge_effect_state(): unknown from_id {from_id!r}")
        if target is None:
            raise EntityRegisterError(f"merge_effect_state(): unknown into_id {into_id!r}")
        if from_id == into_id:
            raise EntityRegisterError("merge_effect_state(): from_id and into_id must differ")

        target_claims_source = from_id in target.merged_from
        if source.lifecycle == LIFECYCLE_MERGED:
            if source.merged_into != into_id:
                raise EntityRegisterError(
                    f"merge_effect_state(): {from_id!r} redirects to "
                    f"{source.merged_into!r}, not {into_id!r}; the original effect cannot "
                    "be proven from current notes and this slice refuses target-evolved "
                    "recovery (EROJ-02)"
                )
            return MERGE_EFFECTS_COMPLETE if target_claims_source else MERGE_EFFECTS_SOURCE_ONLY
        if target_claims_source:
            raise EntityRegisterError(
                f"merge_effect_state(): {into_id!r} claims {from_id!r} in merged_from but "
                f"{from_id!r} carries no redirect; contradictory notes fail closed "
                "(INV-EROJ-6)"
            )
        return MERGE_EFFECTS_NONE

    def ensure_merge_effects(self, from_id: str, into_id: str) -> str:
        """Idempotently apply the two note effects of one exact merge. No event.

        The mechanism half of :meth:`merge`, made resumable for the
        entity-review operation journal (EROJ-01, #4350): whichever of the
        source-redirect and target-complement writes is missing for exactly
        `(from_id -> into_id)` is applied; present effects are left untouched;
        anything unprovable fails closed via :meth:`merge_effect_state`. Never
        emits — the journal path commits its event atomically with the
        operation row, and :meth:`merge` keeps its own emission.

        Returns the pre-application :meth:`merge_effect_state` value.
        """
        state = self.merge_effect_state(from_id, into_id)
        if state == MERGE_EFFECTS_COMPLETE:
            return state

        source = self._read_entry(from_id)
        target = self._read_entry(into_id)
        assert source is not None and target is not None  # proven by merge_effect_state

        if state == MERGE_EFFECTS_NONE:
            merged_source = RegisterEntry(
                entity_id=source.entity_id,
                kind=source.kind,
                label=source.label,
                aliases=source.aliases,
                lifecycle=LIFECYCLE_MERGED,
                merged_into=into_id,
                merged_from=source.merged_from,
                split_from=source.split_from,
                created=source.created,
                updated=_now_iso(),
            )
            self._write_entry(merged_source)

        # Fold the merged entity's aliases (and its own label, as an alias)
        # into the target so future resolve() calls against the old surface
        # form land on the target directly, not only via redirect-follow.
        folded_aliases = tuple(
            dict.fromkeys((*target.aliases, source.label, *source.aliases))
        )
        updated_target = RegisterEntry(
            entity_id=target.entity_id,
            kind=target.kind,
            label=target.label,
            aliases=folded_aliases,
            lifecycle=target.lifecycle,
            merged_into=target.merged_into,
            merged_from=tuple(dict.fromkeys((*target.merged_from, from_id))),
            split_from=target.split_from,
            created=target.created,
            updated=_now_iso(),
        )
        self._write_entry(updated_target)
        return state

    def split(self, entity_id: str, partition_criteria: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
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
        original = self._read_entry(entity_id)
        if original is None:
            raise EntityRegisterError(f"split(): unknown entity_id {entity_id!r}")
        if not partition_criteria:
            raise EntityRegisterError("split(): partition_criteria must be non-empty")

        remaining_aliases = list(original.aliases)
        new_ids: list[str] = []

        # Find any entities that were previously merged into `entity_id`, so
        # a split that re-separates them can re-point their redirect.
        merged_children = [
            e for e in self._all_entries()
            if e.lifecycle == LIFECYCLE_MERGED and e.merged_into == entity_id
        ]

        reclaimed_merged_from: list[str] = []

        for new_label, alias_subset in partition_criteria.items():
            alias_subset = list(alias_subset)
            new_entity_id = _new_canonical_id()
            reversed_children: list[str] = []

            for alias in alias_subset:
                if alias in remaining_aliases:
                    remaining_aliases.remove(alias)

            # Reversibility: any child previously merged into `entity_id`
            # whose own label/aliases fall inside this partition gets
            # re-pointed to the NEW entity instead of the old broad target,
            # restoring its pre-merge identity under `resolve_redirects`.
            for child in merged_children:
                child_names = {child.label, *child.aliases}
                if child_names & set(alias_subset) or child.label == new_label:
                    re_pointed = RegisterEntry(
                        entity_id=child.entity_id,
                        kind=child.kind,
                        label=child.label,
                        aliases=child.aliases,
                        lifecycle=LIFECYCLE_MERGED,
                        merged_into=new_entity_id,
                        split_from=child.split_from,
                        created=child.created,
                        updated=_now_iso(),
                    )
                    self._write_entry(re_pointed)
                    reversed_children.append(child.entity_id)
                    reclaimed_merged_from.append(child.entity_id)

            new_entry = RegisterEntry(
                entity_id=new_entity_id,
                kind=original.kind,
                label=new_label,
                aliases=tuple(dict.fromkeys([new_label, *alias_subset])),
                lifecycle=LIFECYCLE_CANONICAL,
                merged_from=tuple(reversed_children),
                split_from=entity_id,
            )
            self._write_entry(new_entry)
            new_ids.append(new_entity_id)

            self._emit(
                HEIMDAL_REGISTER_ENTITY_SPLIT,
                entity_id=new_entity_id,
                fingerprint_scope=f"split:{entity_id}:{new_label}:{_now_iso()}",
                payload={
                    "split_from": entity_id,
                    "new_entity_id": new_entity_id,
                    "label": new_label,
                    "aliases": alias_subset,
                },
            )

        # `entity_id` itself: keep it canonical, but its alias set shrinks to
        # whatever was not partitioned away (append-only — never deleted), and
        # `merged_from` drops any child ids just reclaimed by a new split
        # entity above (they no longer redirect through `entity_id`).
        remaining_merged_from = tuple(
            m for m in original.merged_from if m not in reclaimed_merged_from
        )
        updated_original = RegisterEntry(
            entity_id=original.entity_id,
            kind=original.kind,
            label=original.label,
            aliases=tuple(remaining_aliases),
            lifecycle=original.lifecycle,
            merged_into=original.merged_into,
            merged_from=remaining_merged_from,
            split_from=original.split_from,
            created=original.created,
            updated=_now_iso(),
        )
        self._write_entry(updated_original)

        return tuple(new_ids)

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
