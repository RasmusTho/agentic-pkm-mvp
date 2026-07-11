"""Heimdal `_heimdal/**` settings-note substrate + schema (Epic #3019 slice A14, #3034).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
§2 ("Markdown-first control surface") and specified by
`docs/HEIMDAL/FABLE_COMPANION.md` §9-k. The owner's locked decision:

    Heimdal's entire control state is a small folder of writable notes in
    the vault (`_heimdal/**`). Every capability -- watching, never-listing,
    interest weights, per-source filters, entity merges, consent grants,
    device config -- is a note edit the agent reads as intent. Any UI is a
    lens with better ergonomics, never the sole home of a capability.

This module lands that substrate and its schema -- **not** a UI, and **not**
the runtime wiring that would make capture/consent/interest behavior actually
read these notes (both are out of scope per the governing Issue). What it
does provide is the one thing every future capability needs before it can be
markdown-first: a schema that (a) can be parsed back losslessly, (b) declares
per-note **authority** (what this note is canonical for), and (c) declares,
per section, which fields are **human-editable** (an operator's literal edit
is read as intent and honored) vs **agent-authored** (Heimdal writes these;
a human edit is preserved as an override, never silently clobbered on the
next agent write -- "persistence is not read-only" applies to both
directions, not just the human-edit direction).

Note inventory (governing Issue's file list), each a `SettingsNoteSpec`:

- `watchlist.md`   -- what Heimdal actively watches (sources, folders, feeds).
                       Epic #3019 slice A18 (#3043) adds in-flow "watch this"
                       durable body-line appends (chat or item transport) via
                       `app.heimdal.interest_steering.append_watch`, alongside
                       this note's existing structured `watched` frontmatter
                       field.
- `never.md`       -- explicit never-list / exclusions (highest-priority veto).
                       A18 adds in-flow "never this" durable body-line
                       appends via `app.heimdal.interest_steering.append_never`,
                       the `never.md` counterpart to `append_watch` above.
- `interests.md`   -- interest weights that steer relevance, not authority.
                       Epic #3019 slice A18 (#3043) extends this note's
                       agent-authored columns with `confidence`/`evidence`/
                       `decay`; the human-editable `weights` column is
                       untouched by that slice.
- `steering.log.md` -- post-hoc steering trail (A18, #3043): "less of this" /
                       "mute" / "wrong" append immutable lines to this
                       note's body. The one note in this registry whose
                       `authority` is `AUTHORITY_APPEND_ONLY_LOG` rather than
                       `AUTHORITY_CONTROL_STATE` -- see
                       `app.heimdal.interest_steering` for the append path
                       and the body-preserving frontmatter-patch mechanism
                       this note kind requires (`write_settings_note`'s
                       generic `render_note` would otherwise discard prior
                       appended lines on every bookkeeping update).
- `sources/*.md`   -- per-source filter/config (one note per configured source).
- `consent.md`     -- the append-only-*ledger*-referencing consent surface
                       (FABLE_COMPANION §6.1); the ledger itself stays
                       append-only (HEIM-1) -- this note is the durable,
                       human-editable *grant/revoke* control surface a human
                       or agent edits to declare intent, which a (future,
                       out-of-scope) runtime translates into ledger events.
- `settings.md`    -- general Heimdal control knobs not covered above.
- `attention/YYYY-MM-DD.md` -- daily durable slice of the attention view
                       (ADR-0049 §2 bend: counts/reasons/overrides are
                       durable; the moment-to-moment skip firehose is not
                       recorded here, UI-only per the ADR).
- `entities/*.md`  -- referenced substrate only (Mimer-owned register per A1,
                       `app/heimdal/entity_register.py`); this module does not
                       define or write entity notes, it only reserves the
                       schema slot the register already owns.
- `entities/review.md` -- Heimdal-side queue of register items awaiting
                       human confirmation (distinct from the register itself:
                       this is Heimdal's editable review queue, not Mimer's
                       canonical entity notes).
- `devices/*.md`   -- one note per capture device: durable identity, config,
                       consent binding, capture-gap log, last-known snapshot
                       (ADR-0049 §2 bend: live battery/signal/buffer telemetry
                       is UI-only, not recorded here).

Every note is a governed vault write through the same seam every other vault
write in this repo uses (`app.knowledge.write_ops.write_note_relative` +
`app.write_guard.DEFAULT_WRITE_GUARD`, mirroring `entity_register.py`) -- no
hand-rolled YAML (`scripts.yaml_roundtrip.load_frontmatter`/`dump_frontmatter`
does the parsing, exactly as `app.services.companion_note` does).

Append-only vs writable (Constraints, binding): these notes are **writable
control state**, not the append-only observation log (HEIM-1 governs the
log, `app/heimdal/observation_log.py`, not these notes). They are canonical
control state but grant **no promotion authority** (HEIM-8 unaffected) --
nothing here promotes an observation to knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SETTINGS_NOTE_WRITE_ACTION = "heimdal.settings_notes.write"
ARTIFACT_CLASS = "heimdal_settings_note"
DEFAULT_SETTINGS_DIR = "_heimdal"

# Field-authority markers (per-section split; "persistence is not read-only").
FIELD_HUMAN_EDITABLE = "human_editable"
FIELD_AGENT_AUTHORED = "agent_authored"
_VALID_FIELD_AUTHORITIES = frozenset({FIELD_HUMAN_EDITABLE, FIELD_AGENT_AUTHORED})

# Note-level authority classes (what a note is canonical for).
AUTHORITY_CONTROL_STATE = "control_state"  # canonical control state; no promotion authority (HEIM-8)
AUTHORITY_REFERENCED_SUBSTRATE = "referenced_substrate"  # e.g. entities/*.md: owned elsewhere (Mimer/A1)
AUTHORITY_DURABLE_SLICE = "durable_slice"  # e.g. attention/*.md: durable slice of a partly UI-only surface
AUTHORITY_APPEND_ONLY_LOG = "append_only_log"  # e.g. steering.log.md: immutable trail, no in-place rewrite
_VALID_AUTHORITIES = frozenset(
    {
        AUTHORITY_CONTROL_STATE,
        AUTHORITY_REFERENCED_SUBSTRATE,
        AUTHORITY_DURABLE_SLICE,
        AUTHORITY_APPEND_ONLY_LOG,
    }
)


class SettingsNoteError(RuntimeError):
    """Raised for `_heimdal/**` settings-note contract violations."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Schema: one FieldSpec per frontmatter field, grouped into sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One frontmatter field's declared authority.

    `field_authority` is exactly `FIELD_HUMAN_EDITABLE` or
    `FIELD_AGENT_AUTHORED` -- never conflated, never left implicit
    (dishonest labelling is a named `break` per the governing Issue's SBS
    Impact "Boundary risk").
    """

    name: str
    field_authority: str
    description: str = ""

    def __post_init__(self) -> None:
        if self.field_authority not in _VALID_FIELD_AUTHORITIES:
            raise SettingsNoteError(
                f"FieldSpec {self.name!r}: field_authority must be one of "
                f"{sorted(_VALID_FIELD_AUTHORITIES)}, got {self.field_authority!r}"
            )


@dataclass(frozen=True)
class SectionSpec:
    """A named group of fields (a frontmatter sub-block or the note's flat
    top-level field set for simple notes). Every section MUST declare an
    explicit editable-vs-agent-authored split for its own fields -- a
    section with zero fields is invalid (nothing to split)."""

    name: str
    fields: tuple[FieldSpec, ...]

    def __post_init__(self) -> None:
        if not self.fields:
            raise SettingsNoteError(f"SectionSpec {self.name!r}: must declare at least one field")

    def human_editable_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.field_authority == FIELD_HUMAN_EDITABLE)

    def agent_authored_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.field_authority == FIELD_AGENT_AUTHORED)


@dataclass(frozen=True)
class SettingsNoteSpec:
    """The declared schema + authority for one `_heimdal/**` note kind.

    `authority` names what this note is canonical for (`AUTHORITY_*`).
    `sections` is non-empty and every section must itself declare a
    non-empty editable-vs-agent-authored split -- this is what
    `test_schema_and_authority_split` checks structurally, and what
    `render_note`/`parse_note` enforce for every concrete note instance.
    """

    kind: str
    rel_path: str  # vault-relative path, may be a template for glob kinds (sources/*.md etc.)
    authority: str
    sections: tuple[SectionSpec, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if self.authority not in _VALID_AUTHORITIES:
            raise SettingsNoteError(
                f"SettingsNoteSpec {self.kind!r}: authority must be one of "
                f"{sorted(_VALID_AUTHORITIES)}, got {self.authority!r}"
            )
        if not self.sections:
            raise SettingsNoteError(f"SettingsNoteSpec {self.kind!r}: must declare at least one section")

    def all_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for section in self.sections for f in section.fields)

    def field_authority_map(self) -> dict[str, str]:
        return {f.name: f.field_authority for f in self.all_fields()}


# ---------------------------------------------------------------------------
# The canonical `_heimdal/**` schema registry
# ---------------------------------------------------------------------------

WATCHLIST = SettingsNoteSpec(
    kind="watchlist",
    rel_path="watchlist.md",
    authority=AUTHORITY_CONTROL_STATE,
    description="What Heimdal actively watches (sources, folders, feeds).",
    sections=(
        SectionSpec(
            "watch",
            (
                FieldSpec("watched", FIELD_HUMAN_EDITABLE, "sources/folders/feeds under active watch"),
                FieldSpec("last_synced", FIELD_AGENT_AUTHORED, "last time Heimdal reconciled against this list"),
            ),
        ),
    ),
)

NEVER_LIST = SettingsNoteSpec(
    kind="never",
    rel_path="never.md",
    authority=AUTHORITY_CONTROL_STATE,
    description="Explicit never-list / exclusions -- highest-priority veto over watchlist/interests.",
    sections=(
        SectionSpec(
            "exclusions",
            (
                FieldSpec("never", FIELD_HUMAN_EDITABLE, "sources/entities/terms Heimdal must never ingest"),
                FieldSpec("last_enforced", FIELD_AGENT_AUTHORED, "last time the veto was checked/applied"),
            ),
        ),
    ),
)

INTERESTS = SettingsNoteSpec(
    kind="interests",
    rel_path="interests.md",
    authority=AUTHORITY_CONTROL_STATE,
    description=(
        "Interest weights that steer relevance (not authority -- never/consent "
        "still veto). Epic #3019 slice A18 (#3043): `weights` is human-editable "
        "and a hand-edit is explicit intent that outranks inference -- the "
        "`confidence`/`evidence`/`decay` columns are agent-authored derived "
        "bookkeeping and must never overwrite a human weight edit "
        "(`apply_agent_update` enforces this generically for every note kind)."
    ),
    sections=(
        SectionSpec(
            "weights",
            (
                FieldSpec("weights", FIELD_HUMAN_EDITABLE, "named interest -> weight map, human-tunable"),
                FieldSpec("observed_signal", FIELD_AGENT_AUTHORED, "agent-observed engagement signal, informational only"),
                FieldSpec("confidence", FIELD_AGENT_AUTHORED, "agent-derived confidence per named interest, informational only"),
                FieldSpec("evidence", FIELD_AGENT_AUTHORED, "agent-collected evidence refs per named interest, informational only"),
                FieldSpec("decay", FIELD_AGENT_AUTHORED, "agent-computed decay/staleness signal per named interest, informational only"),
            ),
        ),
    ),
)

STEERING_LOG = SettingsNoteSpec(
    kind="steering_log",
    rel_path="steering.log.md",
    authority=AUTHORITY_APPEND_ONLY_LOG,
    description=(
        "Post-hoc steering trail (Epic #3019 slice A18, #3043): 'less of "
        "this' / 'mute' / 'wrong' signals append immutable lines to this "
        "note's body -- never rewritten, never reordered, no update/delete "
        "path (mirrors HEIM-1's append-only discipline, applied to a vault "
        "note instead of the DB-backed observation log). The frontmatter "
        "carries only agent-authored bookkeeping about the log itself; the "
        "steering entries are body lines, appended via "
        "`app.heimdal.interest_steering.append_steering_log_line` through "
        "the governed `append_note_relative` seam, never through "
        "`write_settings_note` (which replaces a note's full content and "
        "would violate append-only)."
    ),
    sections=(
        SectionSpec(
            "log",
            (
                FieldSpec("entry_count", FIELD_AGENT_AUTHORED, "agent-maintained count of appended steering lines"),
                FieldSpec("last_appended", FIELD_AGENT_AUTHORED, "timestamp of the most recent appended steering line"),
            ),
        ),
    ),
)

SOURCE_CONFIG = SettingsNoteSpec(
    kind="source",
    rel_path="sources/{source_id}.md",
    authority=AUTHORITY_CONTROL_STATE,
    description="Per-source filter/config, one note per configured source.",
    sections=(
        SectionSpec(
            "config",
            (
                FieldSpec("source_id", FIELD_HUMAN_EDITABLE, "stable identifier for this source"),
                FieldSpec("filters", FIELD_HUMAN_EDITABLE, "per-source include/exclude filters"),
                FieldSpec("last_fetched", FIELD_AGENT_AUTHORED, "last successful fetch timestamp"),
                FieldSpec("last_error", FIELD_AGENT_AUTHORED, "last fetch error, if any"),
            ),
        ),
    ),
)

CONSENT = SettingsNoteSpec(
    kind="consent",
    rel_path="consent.md",
    authority=AUTHORITY_CONTROL_STATE,
    description=(
        "Read-mostly readout mirroring the append-only consent LEDGER "
        "(HEIM-1, FABLE_COMPANION §6.1, ratified by ADR-0049 §2/§3). The "
        "ledger (`app.heimdal.consent_ledger`) is the sole mechanism and "
        "source of record; this note is the legible lens over it -- "
        "`grants` and `last_ledger_sync` are agent-authored (rebuilt from "
        "the ledger by `app.heimdal.consent_surface.write_consent_readout` "
        "every time), never a channel for a human edit to mutate consent "
        "independently of the ledger (Epic #3019 slice A19, #3044). The "
        "`withhold_span_review` and `retention_erasure` sections are "
        "B-shaped: present so Posture B inherits a working surface, inert "
        "in v1."
    ),
    sections=(
        SectionSpec(
            "grants",
            (
                FieldSpec("grants", FIELD_AGENT_AUTHORED, "active ledger grants, mirrored verbatim (read-mostly)"),
                FieldSpec("last_ledger_sync", FIELD_AGENT_AUTHORED, "last time this note was rebuilt from the ledger"),
            ),
        ),
        SectionSpec(
            "withhold_span_review",
            (
                FieldSpec(
                    "withhold_span_review",
                    FIELD_AGENT_AUTHORED,
                    "B-shaped, present-but-dormant in v1: third-party withhold-span review queue/state",
                ),
            ),
        ),
        SectionSpec(
            "retention_erasure",
            (
                FieldSpec(
                    "retention_erasure",
                    FIELD_AGENT_AUTHORED,
                    "B-shaped, present-but-dormant in v1: retention/erasure control state",
                ),
            ),
        ),
    ),
)

SETTINGS = SettingsNoteSpec(
    kind="settings",
    rel_path="settings.md",
    authority=AUTHORITY_CONTROL_STATE,
    description="General Heimdal control knobs not covered by a more specific note.",
    sections=(
        SectionSpec(
            "general",
            (
                FieldSpec("options", FIELD_HUMAN_EDITABLE, "operator-set control knobs"),
                FieldSpec("schema_version", FIELD_AGENT_AUTHORED, "settings schema version this note conforms to"),
            ),
        ),
        SectionSpec(
            "retention",
            (
                FieldSpec(
                    "retention_window_days",
                    FIELD_HUMAN_EDITABLE,
                    "D-RETENTION hard-retention bound in days (Charter FIXED #7): the "
                    "operator-set window past which the hard-retention ops job "
                    "(app.heimdal.retention) hard-deletes raw records, regardless of "
                    "decay signals. Read markdown-first, not from hidden config.",
                ),
                FieldSpec(
                    "screen_frame_retention_minutes",
                    FIELD_HUMAN_EDITABLE,
                    "SCREEN-01 bounded raw-frame reprocessing buffer in minutes. This is a "
                    "separate, deliberately short bound from retention_window_days and is "
                    "read markdown-first; screen capture refuses to assume a default.",
                ),
                FieldSpec(
                    "last_enforced_at",
                    FIELD_AGENT_AUTHORED,
                    "last time the hard-retention ops job ran (informational only; the "
                    "durable audit trail is the deletion-receipt table, not this field)",
                ),
            ),
        ),
    ),
)

ATTENTION_DAY = SettingsNoteSpec(
    kind="attention_day",
    rel_path="attention/{date}.md",
    authority=AUTHORITY_DURABLE_SLICE,
    description=(
        "Daily durable slice of the attention view (ADR-0049 §2 bend): "
        "counts/reasons/every override are durable here; the moment-to-"
        "moment item-level skip firehose is UI-only, not recorded here."
    ),
    sections=(
        SectionSpec(
            "summary",
            (
                FieldSpec("overrides", FIELD_HUMAN_EDITABLE, "human overrides of agent attention decisions that day"),
                FieldSpec("counts", FIELD_AGENT_AUTHORED, "agent-recorded per-reason counts for that day"),
                FieldSpec("reasons", FIELD_AGENT_AUTHORED, "agent-recorded distinct skip/attend reasons that day"),
            ),
        ),
    ),
)

ENTITY_REVIEW = SettingsNoteSpec(
    kind="entity_review",
    rel_path="entities/review.md",
    authority=AUTHORITY_CONTROL_STATE,
    description=(
        "Heimdal-side queue of register items awaiting human confirmation. "
        "Distinct from the Mimer-owned canonical register (`entities/*.md`, "
        "`app/heimdal/entity_register.py`, A1) -- this note never mutates "
        "register identity itself, only tracks what still needs review."
    ),
    sections=(
        SectionSpec(
            "queue",
            (
                FieldSpec("decisions", FIELD_HUMAN_EDITABLE, "human confirm/reject/merge decisions on queued items"),
                FieldSpec("pending", FIELD_AGENT_AUTHORED, "agent-queued entity_ids awaiting human review"),
            ),
        ),
    ),
)

DEVICE_CONFIG = SettingsNoteSpec(
    kind="device",
    rel_path="devices/{device_id}.md",
    authority=AUTHORITY_DURABLE_SLICE,
    description=(
        "One note per capture device: durable identity, config, consent "
        "binding, capture-gap log, last-known snapshot. Live telemetry "
        "(battery/signal/buffer) is the ADR-0049 §2 UI-only bend, not "
        "recorded here."
    ),
    sections=(
        SectionSpec(
            "identity",
            (
                FieldSpec("device_id", FIELD_HUMAN_EDITABLE, "stable device identifier"),
                FieldSpec("label", FIELD_HUMAN_EDITABLE, "human-readable device label"),
                FieldSpec("consent_grant_ref", FIELD_HUMAN_EDITABLE, "bound consent grant for this device"),
            ),
        ),
        SectionSpec(
            "history",
            (
                FieldSpec("capture_gap_log", FIELD_AGENT_AUTHORED, "agent-recorded capture gaps for this device"),
                FieldSpec("last_known_snapshot", FIELD_AGENT_AUTHORED, "last durable device-state snapshot"),
            ),
        ),
    ),
)

# Registry: kind -> spec, for lookup/iteration by tests and future callers.
SETTINGS_NOTE_SPECS: Mapping[str, SettingsNoteSpec] = {
    spec.kind: spec
    for spec in (
        WATCHLIST,
        NEVER_LIST,
        INTERESTS,
        STEERING_LOG,
        SOURCE_CONFIG,
        CONSENT,
        SETTINGS,
        ATTENTION_DAY,
        ENTITY_REVIEW,
        DEVICE_CONFIG,
    )
}


# ---------------------------------------------------------------------------
# Note instance: parsed frontmatter for one concrete `_heimdal/**` note
# ---------------------------------------------------------------------------


@dataclass
class SettingsNote:
    """One concrete `_heimdal/**` note: a spec plus its current field values.

    `values` holds exactly the fields declared by `spec` (human-editable and
    agent-authored together) -- callers read/write the whole note through
    this shape rather than raw frontmatter dicts, so the human/agent split
    is always visible next to the data itself.
    """

    spec: SettingsNoteSpec
    values: dict[str, Any] = field(default_factory=dict)
    updated: str = field(default_factory=_now_iso)

    def to_frontmatter(self) -> dict[str, Any]:
        known = self.spec.field_authority_map()
        fm: dict[str, Any] = {
            "artifact_class": ARTIFACT_CLASS,
            "heimdal_note_kind": self.spec.kind,
            "authority": self.spec.authority,
            "updated": self.updated,
        }
        for name in known:
            if name in self.values:
                fm[name] = self.values[name]
        return fm

    @classmethod
    def from_frontmatter(cls, spec: SettingsNoteSpec, data: Mapping[str, Any]) -> "SettingsNote":
        known = spec.field_authority_map()
        values = {name: data[name] for name in known if name in data}
        return cls(
            spec=spec,
            values=values,
            updated=str(data.get("updated", _now_iso())),
        )


def render_note(note: SettingsNote) -> str:
    """Render one settings note: YAML frontmatter (the parsed source of
    truth) + a short human-readable body that documents the authority split
    inline, so opening the file in Obsidian is self-explanatory without
    reading this module's docstring."""
    fm = note.to_frontmatter()
    spec = note.spec
    lines: list[str] = [f"# {spec.kind}", "", spec.description.strip(), ""]
    lines.append(f"**Authority:** `{spec.authority}`")
    lines.append("")
    for section in spec.sections:
        human = section.human_editable_fields()
        agent = section.agent_authored_fields()
        lines.append(f"## {section.name}")
        lines.append("")
        if human:
            lines.append(f"- Human-editable fields (edit these; honored as intent): {', '.join(human)}")
        if agent:
            lines.append(f"- Agent-authored fields (written by Heimdal; not for manual edits): {', '.join(agent)}")
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return dump_frontmatter(fm, body)


def parse_note(spec: SettingsNoteSpec, text: str) -> SettingsNote:
    """Parse a `_heimdal/**` note's frontmatter back into a `SettingsNote`.

    Uses the shared `scripts.yaml_roundtrip.load_frontmatter` parser (never
    hand-rolled YAML), mirroring `app.services.companion_note`.
    """
    fm, _ = load_frontmatter(text)
    return SettingsNote.from_frontmatter(spec, fm)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def note_rel_path(spec: SettingsNoteSpec, *, settings_dir: str = DEFAULT_SETTINGS_DIR, **template_args: str) -> str:
    """Deterministic vault-relative path for one note of `spec`'s kind.

    Glob-shaped kinds (`sources/*.md`, `devices/*.md`, `attention/*.md`)
    require the matching template argument (`source_id` / `device_id` /
    `date`); fixed-path kinds take none.
    """
    rel = spec.rel_path.format(**template_args) if template_args else spec.rel_path
    if "{" in rel:
        raise SettingsNoteError(
            f"note_rel_path: spec {spec.kind!r} rel_path {spec.rel_path!r} requires template "
            f"argument(s); got {template_args!r}"
        )
    return (PurePosixPath(settings_dir) / rel).as_posix()


# ---------------------------------------------------------------------------
# Read / write -- the real production entry point
# ---------------------------------------------------------------------------


def read_settings_note(
    vault_root: Path,
    spec: SettingsNoteSpec,
    *,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    **template_args: str,
) -> SettingsNote | None:
    """Read one `_heimdal/**` note. Returns `None` if the note does not exist yet.

    This is the read half of the writable-source-of-record contract: any
    field a human hand-edited comes back exactly as written (no silent
    normalization / overwrite-on-read), so a caller that reads-then-writes
    (the common "reconcile agent-authored fields, preserve human ones"
    pattern) never clobbers a human edit it did not itself request.
    """
    rel_path = note_rel_path(spec, settings_dir=settings_dir, **template_args)
    path = vault_root / rel_path
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return parse_note(spec, text)


def write_settings_note(
    vault_root: Path,
    note: SettingsNote,
    *,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    action: str = SETTINGS_NOTE_WRITE_ACTION,
    **template_args: str,
) -> None:
    """Write one `_heimdal/**` note through the governed vault-write seam.

    Uses `app.knowledge.write_ops.write_note_relative` (the same production
    write port `app.services.companion_note` and
    `app.heimdal.entity_register` use), which itself asserts
    `write_guard.assert_writes_allowed(action)` before touching the
    filesystem -- so a health-blocked runtime cannot silently corrupt the
    control surface either.
    """
    rel_path = note_rel_path(note.spec, settings_dir=settings_dir, **template_args)
    content = render_note(note)
    write_note_relative(
        rel_path,
        content,
        vault_root=vault_root,
        action=action,
        write_guard=write_guard,
    )


def apply_agent_update(
    vault_root: Path,
    spec: SettingsNoteSpec,
    agent_values: Mapping[str, Any],
    *,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    **template_args: str,
) -> SettingsNote:
    """The honored-intent read/merge/write cycle an agent uses to update its
    own agent-authored fields **without disturbing human-editable ones**.

    This is the concrete mechanism behind "a human edit to an editable field
    is read as intent and honored, not overwritten as read-only"
    (`test_notes_are_writable_source_of_record`): the agent reads the
    current note first, keeps every human-editable field exactly as found
    on disk, and only overwrites the agent-authored fields named in
    `agent_values`. Passing a human-editable field name in `agent_values`
    raises -- an agent has no channel to silently overwrite what a human
    just typed; the only way is a distinct, explicitly-human-facing edit.
    """
    field_authority = spec.field_authority_map()
    for name in agent_values:
        if field_authority.get(name) != FIELD_AGENT_AUTHORED:
            raise SettingsNoteError(
                f"apply_agent_update: {name!r} is not an agent-authored field of "
                f"{spec.kind!r} (field_authority={field_authority.get(name)!r}); "
                "agents may not silently overwrite human-editable fields"
            )

    existing = read_settings_note(vault_root, spec, settings_dir=settings_dir, **template_args)
    merged_values: dict[str, Any] = dict(existing.values) if existing is not None else {}
    merged_values.update(agent_values)

    note = SettingsNote(spec=spec, values=merged_values)
    write_settings_note(
        vault_root,
        note,
        settings_dir=settings_dir,
        write_guard=write_guard,
        **template_args,
    )
    return note


__all__ = [
    "ARTIFACT_CLASS",
    "ATTENTION_DAY",
    "AUTHORITY_APPEND_ONLY_LOG",
    "AUTHORITY_CONTROL_STATE",
    "AUTHORITY_DURABLE_SLICE",
    "AUTHORITY_REFERENCED_SUBSTRATE",
    "CONSENT",
    "DEFAULT_SETTINGS_DIR",
    "DEVICE_CONFIG",
    "ENTITY_REVIEW",
    "FIELD_AGENT_AUTHORED",
    "FIELD_HUMAN_EDITABLE",
    "FieldSpec",
    "INTERESTS",
    "NEVER_LIST",
    "SETTINGS",
    "SETTINGS_NOTE_SPECS",
    "SETTINGS_NOTE_WRITE_ACTION",
    "SOURCE_CONFIG",
    "STEERING_LOG",
    "SectionSpec",
    "SettingsNote",
    "SettingsNoteError",
    "SettingsNoteSpec",
    "WATCHLIST",
    "apply_agent_update",
    "note_rel_path",
    "parse_note",
    "read_settings_note",
    "render_note",
    "write_settings_note",
]
