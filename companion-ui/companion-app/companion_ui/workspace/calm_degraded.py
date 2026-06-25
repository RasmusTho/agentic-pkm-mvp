"""Calm degraded grammar + runtime-enum/identifier humanisation map (CUIDR-01).

Single source of the Companion UI's degraded/unavailable/error *copy*. Every
user-facing surface that needs to say "this is unavailable / partial / failed"
reads from one grammar template here, and every runtime enum or internal
identifier passes through one humanising map before it reaches HTML.

Hard constraint (presentation only): this module does NOT classify state. It
never decides *whether* a surface is degraded, stale, blocked, or unavailable —
that classification is server-authoritative and arrives in the runtime payload.
This module only maps the runtime-declared *display token* to human copy, and
fails closed (raw token suppressed) when a token is unknown. The classified
value still travels in ``data-*`` attributes on the rendered element so the
runtime declaration remains observable; only the visible copy is humanised.

The grammar template:

    "<what> unavailable — <why>. <nothing-clause>. <what to do>."

where ``<nothing-clause>`` is one of "Nothing was lost", "Nothing was decided",
or "Nothing was mutated" depending on the surface's write posture.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Nothing-clause vocabulary (the calm degraded voice — a deliberate commitment).
# ---------------------------------------------------------------------------
NOTHING_LOST: Final[str] = "Nothing was lost"
NOTHING_DECIDED: Final[str] = "Nothing was decided"
NOTHING_MUTATED: Final[str] = "Nothing was mutated"

_NOTHING_CLAUSES: Final[frozenset[str]] = frozenset(
    {NOTHING_LOST, NOTHING_DECIDED, NOTHING_MUTATED}
)

# Fail-closed fallback used when a runtime degraded-reason token is unknown.
# The raw token is never surfaced; the calm voice is preserved.
FAIL_CLOSED_DEGRADED: Final[str] = (
    "… unavailable — details withheld. Nothing was lost."
)

# ---------------------------------------------------------------------------
# Runtime-enum / internal-identifier → human-copy map.
#
# Covers the confirmed leak tokens from the deep review (REVIEW_RESPONSE.txt
# §03/§04 C3, D3). The value is the *display* string; the classified value
# itself still arrives from the runtime payload and is preserved in data-*.
# ---------------------------------------------------------------------------
_ENUM_MAP: Final[dict[str, str]] = {
    "resurfacing_source_unavailable": "Orientation source unavailable",
    "orientation_unavailable": "Orientation unavailable",
    "orientation_source_unavailable": "Orientation source unavailable",
    "lifecycle.move": "Move note",
    # Orientation provenance / signal tokens that leaked raw into the re-entry
    # and orientation footers (REVIEW_RESPONSE.txt C3). These are runtime
    # provenance enums, never user-facing copy: map them to a human label so the
    # footer reads as a sentence, not a machine token. The classified value
    # still travels in the footer's data-* attributes.
    "operational_trace_pointer": "from where you left off",
    "artifact_activation": "from your last activity",
}

# Internal identifiers that must never appear as user-facing copy. They are
# correlation IDs, not labels — suppress them in copy and let the calling site
# fall back to the artefact/proposal description. The raw value is still allowed
# in data-* attributes (server-authoritative correlation), which this map does
# not touch.
_SUPPRESS_ID_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^prop-[\w.-]+$"),
    re.compile(r"^proposal-[\w.-]+$"),
    re.compile(r"^art-[\w.-]+$"),
    re.compile(r"^artifact-[\w.-]+$"),
    re.compile(r"^note-[\w.-]+$"),
)

# Runtime classified-token namespaces. A token in one of these namespaces is a
# machine enum, never user-facing copy: if it is not explicitly mapped it must
# FAIL CLOSED (suppressed) rather than pass through raw. The review names
# ``lifecycle.*`` as a confirmed leak family (lifecycle.move / future
# lifecycle.* actions); the calling site falls back to the proposal's
# ``description``. Legitimate human/evidence values (e.g. ``bounded.panel_action``)
# live outside these namespaces and pass through.
_CLASSIFIED_TOKEN_NAMESPACES: Final[tuple[str, ...]] = ("lifecycle.",)

# Runtime classified-token *shapes* (not namespaces) that are machine signal
# encodings, never user-facing copy: e.g. ``signal=0`` resurface strength
# encodings. An unmapped token matching one of these FAILS CLOSED (suppressed),
# exactly like a classified-namespace token. The raw value still travels in the
# surface's data-* attributes.
_CLASSIFIED_TOKEN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^signal=[\w.-]*$"),
)

# Machine ``name=value`` signal-encoding shape used by the orientation/resurface
# producer. The runtime emits every resurface signal as ``f"{signal.name}={signal.value}"``
# (app/api/routes/companion.py::_orientation_resurface_candidates) — e.g.
# ``worker_queue_pending=2``, ``recent_change=orientation``, ``signal=0``. NONE of
# these are user-authored copy; they are correlation encodings. The chip render
# path must fail closed on the WHOLE family, not just the fixture's ``signal=…``.
#
# The shape that identifies a machine encoding (and distinguishes it from human
# copy such as "Resume the runtime API contract" or "from where you left off"):
# a leading bare *identifier* token (``[a-z][\w.]*`` — snake/dotted, no spaces)
# immediately followed by ``=`` and a value, with no surrounding prose. Human
# labels never carry that ``identifier=value`` head, so this does not redact
# legitimate copy that merely happens to contain an ``=`` mid-sentence.
_SIGNAL_LABEL_ENCODING_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][\w.]*=.*$"
)

# Embedded-identifier pattern for prose redaction. Matches an internal id
# (``prop-*`` / ``proposal-*`` / ``art-*`` / ``artifact-*`` / ``note-*``) where
# it appears *inside* free text (e.g. a runtime ``trigger_summary`` such as
# "Trigger for prop-move-1 …"). Whole-string ids are handled by
# :func:`humanise_token`; this catches the in-prose case the review flagged.
#
# CRITICAL — distinguish a real opaque ID from ordinary hyphenated prose.
# ``humanise_prose`` runs on EVERY ``trigger_summary`` / provenance label, so an
# over-broad matcher (any ``note-…`` / ``proposal-…`` hyphenated word) silently
# rewrites legitimate copy: "note-taking follow-up", "proposal-worthy evidence",
# "artifact-level context" would all collapse to "this item …". That corrupts
# user-visible Evidence text.
#
# Real producer IDs in this codebase always carry an *opaque* segment — a purely
# numeric run (``prop-move-1``, ``prop-cross-1``, ``art-123``, ``art-2075``) or a
# long hex/uuid-like token — somewhere in the hyphen chain. Ordinary prose words
# ("taking", "worthy", "level", "stub", "cross") never are. So the matcher only
# fires when the token contains at least one numeric / hex-opaque segment, and
# only then consumes the WHOLE hyphen chain (so multi-segment ids like
# ``art-1187-empty`` / ``prop-move-1`` redact whole, leaving no ``-1`` residue).
#
# Shape (IGNORECASE):
#   <prefix>(-<word>)* -<opaque> (-<word|opaque>)*
# where <opaque> = a digit run (``1``, ``2075``) or a >=8-char hex/uuid token.
_EMBEDDED_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:prop|proposal|art|artifact|note)"  # producer prefix
    r"(?:-[A-Za-z]+)*"  # optional leading word segments (move, cross, …)
    r"-(?:\d+|[0-9a-f]{8,})"  # >=1 opaque segment: numeric run or hex/uuid token
    r"(?:-[\w.]+)*",  # any trailing segments (art-1187-empty, …)
    re.IGNORECASE,
)


def _is_suppressed_identifier(token: str) -> bool:
    return any(pattern.match(token) for pattern in _SUPPRESS_ID_PATTERNS)


def _is_classified_pattern_token(token: str) -> bool:
    return any(pattern.match(token) for pattern in _CLASSIFIED_TOKEN_PATTERNS)


def _is_classified_namespace_token(token: str) -> bool:
    return any(token.startswith(ns) for ns in _CLASSIFIED_TOKEN_NAMESPACES)


def calm_degraded(
    what: str,
    why: str,
    nothing_clause: str = NOTHING_LOST,
    what_to_do: str = "",
) -> str:
    """Render the one calm degraded-copy grammar.

    Produces ``"<what> unavailable — <why>. <nothing-clause>. <what to do>."``.

    This is the *sole* code path that emits unavailable/error copy on any
    user-facing surface. No surface may inline its own unavailable-state string
    literal.

    ``nothing_clause`` defaults to "Nothing was lost"; pass NOTHING_DECIDED or
    NOTHING_MUTATED for surfaces with a different write posture. An unrecognised
    nothing-clause falls back to "Nothing was lost" so the voice stays calm.
    ``what_to_do`` is optional (e.g. "Refresh to retry."); when omitted the
    sentence ends after the nothing-clause.
    """
    what = (what or "Something").strip()
    why = (why or "details withheld").strip()
    clause = nothing_clause if nothing_clause in _NOTHING_CLAUSES else NOTHING_LOST
    # Normalise an accidental trailing period on the why-clause.
    why = why.rstrip(".")
    sentence = f"{what} unavailable — {why}. {clause}."
    action = (what_to_do or "").strip()
    if action:
        action = action.rstrip(".")
        sentence = f"{sentence} {action}."
    return sentence


def humanise_token(token: object) -> str:
    """Map a single runtime enum / identifier to human-facing copy.

    - A known enum returns its mapped human copy.
    - A ``prop-*`` / ``art-*`` / ``note-*``-style internal identifier returns the
      empty string (suppressed — the caller uses the artefact/proposal
      ``description`` instead). The raw id is never returned.
    - An *unmapped* token in a known classified-enum namespace (``lifecycle.*``)
      FAILS CLOSED to the empty string — a new runtime enum is never shown raw.
    - Any other value (a legitimate, already-human action class such as
      ``bounded.panel_action``, or free-text) passes through unchanged.

    This is the general humanisation map used before a classified *label* token
    reaches a user surface. Arbitrary free-text passes through; known machine
    namespaces and internal identifiers fail closed to suppression.
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return ""
    if text in _ENUM_MAP:
        return _ENUM_MAP[text]
    if _is_suppressed_identifier(text):
        return ""
    if _is_classified_namespace_token(text):
        # Unmapped machine enum in a classified namespace — fail closed.
        return ""
    if _is_classified_pattern_token(text):
        # Unmapped machine signal encoding (e.g. signal=0) — fail closed.
        return ""
    return text


def humanise_signal_label(token: object) -> str:
    """Fail-closed humanisation for an orientation/resurface *signal chip* label.

    The resurface/orientation chips render the runtime's resurface signal labels,
    which the producer emits as machine ``name=value`` encodings (e.g.
    ``worker_queue_pending=2``, ``recent_change=orientation``, ``signal=0``). Those
    are correlation encodings, never user-authored copy, so an *unmapped*
    ``name=value`` token must FAIL CLOSED (suppressed) rather than render raw —
    otherwise the live (non-gallery) runtime leaks ``worker_queue_pending=2`` into
    visible chip text, defeating the no-raw-enum constraint for REAL data.

    Resolution:

    - an explicitly mapped enum returns its human copy (via :func:`humanise_token`);
    - any whole-string machine ``identifier=value`` encoding is suppressed (empty);
    - any other value (legitimate human label) passes through unchanged via
      :func:`humanise_token`, preserving its identifier/namespace fail-closed rules.

    The raw signal label still travels server-authoritatively in the chip's
    ``data-signal-token`` attribute. This is deliberately scoped to the signal
    chip render path; it does NOT change :func:`humanise_token`, whose pass-through
    contract other callers (evidence/proposal ``action_class`` labels) rely on.
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return ""
    if text in _ENUM_MAP:
        return _ENUM_MAP[text]
    if _SIGNAL_LABEL_ENCODING_RE.match(text):
        # Unmapped machine name=value signal encoding — fail closed, never raw.
        return ""
    return humanise_token(text)


def humanise_provenance_token(token: object, *, fallback: str) -> str:
    """Fail-closed humanisation for an orientation *provenance* enum.

    Unlike :func:`humanise_token` (which passes arbitrary human/free-text values
    through unchanged), the provenance footer renders runtime-classified enums
    only — ``authority_role`` and a ``source_ref`` kind/label. Those are machine
    tokens, never user-authored copy, so an *unmapped* one must FAIL CLOSED to the
    supplied calm ``fallback`` ("Derived" / "details withheld") rather than leak
    the raw enum (Constraint: an unmapped token renders the safe fallback, never
    the raw token).

    Resolution:

    - an explicitly mapped enum returns its human copy;
    - an empty / missing token returns ``fallback``;
    - any other token — including an allowed-but-unmapped provenance enum such as
      ``derived_runtime_projection`` or a raw ``source_ref`` kind used as a label
      — returns ``fallback`` (fail closed). The raw classified value still travels
      server-authoritatively in the footer's ``data-*`` attributes.

    This is deliberately scoped to the provenance render path; it does NOT change
    :func:`humanise_token`, whose pass-through contract other callers (evidence
    ``action_class``, resurface ``signal_labels``) still rely on.
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return fallback
    mapped = _ENUM_MAP.get(text)
    if mapped is not None:
        return mapped
    # Unmapped provenance enum — fail closed to the calm fallback, never raw.
    return fallback


def humanise_prose(text: object) -> str:
    """Redact embedded internal identifiers from free-text runtime copy.

    Some runtime free-text fields (notably a proposal ``trigger_summary`` such
    as "Trigger for prop-move-1 …") embed an internal correlation id *inside*
    otherwise-human prose. :func:`humanise_token` only suppresses a whole-string
    id; this scrubs the id where it appears mid-sentence so it never reaches
    visible copy, while leaving the rest of the human sentence intact. The raw
    id is still preserved in the surface's ``data-*`` attributes (this only
    touches the visible copy string).

    Only an *opaque correlation id* (a ``prop-*`` / ``art-*`` / ``note-*`` token
    carrying a numeric or hex/uuid-like segment, e.g. ``prop-move-1`` /
    ``art-123``) is replaced with "this item". Ordinary hyphenated prose that
    merely starts with one of those words — "note-taking", "proposal-worthy",
    "artifact-level" — is NOT an id and passes through verbatim.
    """
    raw = "" if text is None else str(text)
    if not raw:
        return ""
    return _EMBEDDED_ID_RE.sub("this item", raw)


def humanise_degraded_reason(token: object) -> str:
    """Map a runtime degraded-reason token to human copy, failing closed.

    Known reason enums map to their human copy. An unknown / unmapped token does
    NOT leak: it collapses to :data:`FAIL_CLOSED_DEGRADED`
    ("… unavailable — details withheld. Nothing was lost.").
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return FAIL_CLOSED_DEGRADED
    mapped = _ENUM_MAP.get(text)
    if mapped is not None:
        return mapped
    # Suppressed identifiers and unknown tokens both fail closed.
    return FAIL_CLOSED_DEGRADED


def is_mapped_token(token: object) -> bool:
    """True when ``token`` has an explicit entry in the enum map."""
    text = "" if token is None else str(token).strip()
    return text in _ENUM_MAP


# ---------------------------------------------------------------------------
# Agent-lane labeling (CUIDR-08 / C2).
#
# The two agent lanes differ on the single most trust-critical dimension in the
# system — whether applying an action is *recorded* (produces a durable
# receipt). That distinction is stated here in plain words so no surface infers
# it from colour or button count. The lane itself is server-authoritative and
# arrives in the runtime payload; this module only maps the declared lane token
# to its label, exactly as the enum map does for degraded reasons.
# ---------------------------------------------------------------------------

#: The body-edit lane (S2): an in-memory edit to the active note body. Not
#: recorded — no durable receipt is produced.
LANE_BODY_EDIT: Final[str] = "body_edit"
#: The governed lane (S3): a governed proposal whose Apply writes to the vault
#: and produces a durable receipt.
LANE_GOVERNED: Final[str] = "governed"

#: Mandatory label line for a body-edit-lane card. The recorded/not-recorded
#: distinction is the headline text on the card.
LANE_LABEL_BODY_EDIT: Final[str] = "Apply · not recorded (no receipt)"
#: Mandatory label line for a governed-lane card whose Apply writes the vault
#: and produces a receipt directly (the Panel proposal / rail card).
LANE_LABEL_GOVERNED: Final[str] = "Apply → vault change → receipt"
#: Label for a governance-bearing *suggestion card* whose action only queues /
#: routes the intent to Panel for a later governed decision — it does NOT apply
#: a vault change or produce a receipt on this surface. Labeling it with the
#: governed-apply line would overstate the recording guarantee (a Queue is not
#: an Apply); this names the queue-then-record reality instead.
LANE_LABEL_GOVERNANCE_QUEUE: Final[str] = (
    "Queue → governed review · not recorded yet"
)

#: Fixed Defer consequence line. Prevents "Defer" from being a mystery action.
#: This is a presentation string (not server-supplied) per the spec.
DEFER_CONSEQUENCE: Final[str] = (
    "Deferred proposals return the next time this note is active."
)


def lane_label(lane: object = None, *, governed: object = None) -> str:
    """Map a server-declared agent lane to its recorded/not-recorded label.

    The lane is sourced from the runtime payload's ``lane`` token (preferred) or
    its boolean ``governed`` field; this function never infers the lane from
    colour, button count, or proposal content. Resolution order:

    - an explicit ``lane`` token (``"governed"`` / ``"body_edit"``) wins;
    - otherwise the boolean ``governed`` flag selects the governed/body-edit
      label;
    - with neither declared, the governed label is returned, because the
      surfaces that call this without a lane (the Panel rail / palette) *are* the
      governed lane by construction — this is not a client-side classification,
      it is the default label for an already-governed surface.
    """
    token = "" if lane is None else str(lane).strip().lower()
    if token in {LANE_GOVERNED, "governed", "vault", "vault_change"}:
        return LANE_LABEL_GOVERNED
    if token in {LANE_BODY_EDIT, "body-edit", "body", "suggestion"}:
        return LANE_LABEL_BODY_EDIT
    if governed is not None:
        return LANE_LABEL_GOVERNED if bool(governed) else LANE_LABEL_BODY_EDIT
    return LANE_LABEL_GOVERNED


# ---------------------------------------------------------------------------
# Blocked-proposal reason + recourse (CUIDR-08 / A3).
#
# A WriteGuard-held proposal presents calm (held, not red) but must state, in
# plain language, *why* the hold fired and *what would unblock it*. The reason
# humanises the runtime ``block_reason.gate`` enum (or renders the supplied
# ``message`` as-is); the recourse uses the runtime ``recourse`` field when
# present, otherwise a per-gate canonical fallback. Neither collapses to a mute
# "unavailable" dead end.
# ---------------------------------------------------------------------------

#: Calm fallback when the runtime declares a block but supplies no detail.
BLOCKED_REASON_FALLBACK: Final[str] = (
    "Proposal held — details unavailable. Nothing was mutated."
)
BLOCKED_RECOURSE_FALLBACK: Final[str] = (
    "No action is needed now; the hold clears on its own or via an operator."
)

# Per-gate human reason + canonical recourse fallback. The gate value is
# server-declared; an unmapped gate falls back to the calm grammar so a new
# runtime gate enum never leaks raw.
_BLOCK_GATE_COPY: Final[dict[str, tuple[str, str]]] = {
    "writeguard": (
        "Writes are temporarily held while the system is in safe mode.",
        "Writes resume automatically once safe mode clears. "
        "No action is needed now.",
    ),
    "safe-mode": (
        "Writes are temporarily held while the system is in safe mode.",
        "Writes resume automatically once safe mode clears. "
        "No action is needed now.",
    ),
    "stale-source": (
        "The note changed since this proposal was prepared, so it is held.",
        "Reopen the note to prepare a fresh proposal against the current text.",
    ),
    "identity-mismatch": (
        "This proposal targets a different version of the note than the one "
        "open now, so it is held.",
        "Reopen the intended note; the proposal re-prepares against it.",
    ),
    "same-turn": (
        "This proposal cannot be confirmed in the same interaction it was "
        "raised.",
        "Confirm it on the next interaction; nothing was mutated.",
    ),
    "already-confirmed": (
        "This proposal was already confirmed, so it cannot be applied again.",
        "No action is needed — the recorded receipt already reflects the "
        "change.",
    ),
}


def blocked_reason(block_reason: object) -> str:
    """Plain-language reason a proposal is held, humanised from the payload.

    ``block_reason`` is the runtime's server-declared block object. The reason
    is sourced, in order: the per-gate human copy for a known ``gate`` enum; an
    explicit ``message`` field rendered as-is; otherwise the calm fallback
    (:data:`BLOCKED_REASON_FALLBACK`). An unknown gate never leaks raw — it
    falls back to the supplied message or the calm grammar.
    """
    block = block_reason if isinstance(block_reason, dict) else {}
    gate = str(block.get("gate") or "").strip().lower()
    mapped = _BLOCK_GATE_COPY.get(gate)
    if mapped is not None:
        return mapped[0]
    message = str(block.get("message") or "").strip()
    if message:
        return message
    return BLOCKED_REASON_FALLBACK


def blocked_recourse(block_reason: object) -> str:
    """Plain-language next step / recourse for a held proposal.

    Sourced, in order: an explicit ``recourse`` field from the runtime payload;
    the per-gate canonical recourse for a known ``gate`` enum; otherwise the calm
    fallback (:data:`BLOCKED_RECOURSE_FALLBACK`).
    """
    block = block_reason if isinstance(block_reason, dict) else {}
    recourse = str(block.get("recourse") or "").strip()
    if recourse:
        return recourse
    gate = str(block.get("gate") or "").strip().lower()
    mapped = _BLOCK_GATE_COPY.get(gate)
    if mapped is not None:
        return mapped[1]
    return BLOCKED_RECOURSE_FALLBACK


# ---------------------------------------------------------------------------
# recents_anchor display-label humanisation (#2525).
#
# `recents_anchor.display_label` is "derived from the note's first H1 heading,
# or its filename stem when no heading is present" (WORKSPACE_ORIENTATION_
# CONTRACT.md §recents_anchor). When the runtime had to fall back to the
# filename stem, the cold_start door surfaced a raw machine-ish token such as
# `uat-prod-action-parse-20260515T175952Z` as "your most recent note". The
# server is authoritative for *which* note; this is a pure presentation
# transform of the label it declared — no vault I/O, no re-classification.
# ---------------------------------------------------------------------------

# A trailing capture/run timestamp segment a filename stem commonly carries,
# e.g. `...-20260515T175952Z`, `..._20260515`, `...-20260515T175952`. Stripped
# from the humanised label (the timestamp is noise, not a title).
_RECENTS_TRAILING_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"[\s_-]*\d{8}(?:[tT]\d{6}[zZ]?)?$"
)

# Filename-stem signals. A single token can be a legitimate H1 title (`iPhone`,
# `macOS`), so only transform labels that carry stem separators or timestamp
# noise.
_RECENTS_STEM_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(r"[-_]")


def humanise_recents_label(label: object) -> str:
    """Humanise a ``recents_anchor.display_label`` that is a bare filename stem.

    - When the runtime-declared label is already a human title (an H1 heading),
      return it unchanged, including single-token H1s such as ``iPhone``.
    - When it is a filename stem (no whitespace, separator-joined tokens, often
      with a trailing capture timestamp such as ``-20260515T175952Z``), strip a
      trailing timestamp, replace ``-``/``_`` separators with spaces, collapse
      whitespace, and title-case the result so the door never surfaces a raw
      stem as "your most recent note".
    - An empty / whitespace-only value returns the empty string (the caller
      omits the sub-affordance entirely when it has no honest label).

    Pure presentation transform of a server-declared label — never a re-read of
    the vault and never a new identity claim.
    """
    text = "" if label is None else str(label).strip()
    if not text:
        return ""
    # Already a human H1 title with whitespace — leave it untouched.
    if re.search(r"\s", text):
        return text
    # A single token can also be a human H1 title. Only transform labels that
    # actually look stem-generated: separator-joined or timestamp-suffixed.
    if not _RECENTS_STEM_SEPARATOR_RE.search(
        text
    ) and not _RECENTS_TRAILING_TIMESTAMP_RE.search(text):
        return text
    # Filename-stem shape: drop a trailing timestamp segment, then split on the
    # stem separators and title-case the remaining words.
    stem = _RECENTS_TRAILING_TIMESTAMP_RE.sub("", text)
    words = [w for w in re.split(r"[\s_-]+", stem) if w]
    if not words:
        # The stem was nothing but a timestamp — fall back to the original
        # (timestamp-stripped) text rather than emitting an empty label.
        return stem or text
    return " ".join(word[:1].upper() + word[1:] for word in words)
