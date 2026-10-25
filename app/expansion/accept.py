"""Governed acceptance/promotion of staged Create drafts (EXP-4, #2997).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2.4,
§5 (EXP-4). Parent: #2980 (Capability Hardening / Cognitive Expansion). This is
the *only* path from a staged Create draft (produced by
``app.expansion.create.run_create_pass``, EXP-3) to a canonical vault note. It
implements the acceptance half of ``create_never_autowrites_canonical``: a
staged draft becomes canonical vault content ONLY through a human acceptance
receipt, never on the machine's own initiative.

Authority model (the point of this slice — do not relax without an owner-ratified
ADR; ``docs/testing/invariant-tests.md`` names these invariants):

- **The human checkbox is the sole trigger.** The staged draft carries one
  unchecked in-draft acceptance checkbox (EXP-3 writes ``- [ ] Accept ...``).
  A human checking it (``- [x]``) is the acceptance decision — substrate-neutral,
  exactly like the Panel confirmation checkbox. :func:`accept_draft` refuses to
  materialize a draft whose checkbox is still unchecked
  (:class:`DraftNotAcceptedError`); there is no code path, and no configuration
  flag, that materializes an unchecked draft. This is
  ``create_never_autowrites_canonical`` (acceptance side).

- **Acceptance is a governed AuthorityTransition** (``authority-transition.schema.json``):
  the checked checkbox mints a :class:`DecisionToken` (the pre-mutation
  ``decision_token_ref``) and the completed materialization emits an
  ``expansion.create.accepted`` :class:`AcceptanceReceipt` (the post-mutation
  ``authority_receipt_id``). Both ride on the transition record. This is
  ``authority_transition_requires_decision_token_and_receipt``.

- **Execution cannot authorize itself** (``execution_cannot_authorize_itself``):
  the decision token is derived *only* from the human's checked checkbox
  (:func:`_mint_decision_token`), never minted by the materialization path on
  its own. A caller cannot pass a fabricated token; the token is computed here
  from the observed checkbox state, so an unchecked draft can produce no token
  and therefore no transition and therefore no canonical write.

- **WriteGuard gates the canonical materialization** with a named action
  (:data:`ACCEPT_MATERIALIZE_WRITE_ACTION`), asserted before the canonical file
  is written — the same fail-closed gate every other durable write in the repo
  consults.

- **Provenance survives acceptance permanently** (``synthesis_carries_source_provenance``,
  ``test_accepted_note_keeps_provenance``): the materialized note keeps its
  ``sources:`` list and ``derived_by: synthesis``, and gains ``accepted_by: human``,
  ``authority_state: accepted``, and the acceptance receipt id. Citations are
  re-validated at acceptance time against the live source set; a citation that no
  longer resolves blocks the acceptance LOUDLY
  (:class:`UnresolvableCitationError`) rather than silently shipping an
  unsourced/untraceable note.

- **Trust is not silently upgraded.** Acceptance advances ``authority_state``
  from ``proposal`` to ``accepted`` and stamps ``accepted_by: human`` — it does
  *not* set a real-world-evidence role and does *not* strip
  ``derived_by: synthesis``. The accepted note is knowledge the human owns, not
  evidence the machine may cite as settled, until a review state is separately
  human-advanced (spec §2.3, owner decision E4 defaulting conservative).

- **Idempotent.** Re-processing an already-accepted draft (one whose frontmatter
  already reads ``authority_state: accepted`` / carries ``accepted_by``) does not
  double-materialize: :func:`accept_draft` returns an ``already_accepted`` result
  without writing a second canonical note or a second receipt.

- **Modify-existing-note variant stays ``ask-you``.** Materializing an accepted
  draft as a **new** note is additive and Git-reversible — the human's accept is
  the explicit act, so no further gate is owed. Any variant that *modifies an
  existing canonical note* (destination resolves to an already-existing file) is
  a body edit and stays ``ask-you`` per the ratified #1881 table
  (``docs/CAPABILITY_CONTRACT_MODEL.md``): :func:`accept_draft` refuses to
  overwrite an existing canonical note (:class:`ModifyExistingRequiresAskError`)
  — this slice never materializes that variant at a lighter tier.

- **Decline is a visible lifecycle outcome, not deletion.** :func:`decline_draft`
  records the draft id in the shared declined-proposal ledger
  (``app.proposals.declined_ledger``, EXP-2), archives/removes the staged draft,
  produces NO canonical note, and keeps its decline receipt.

- **Edited-then-accepted text is authoritative.** The materialized note reflects
  the draft's *current on-disk body* at acceptance time — human edits made to the
  draft before checking the box are what get materialized, not the original
  generated draft.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.expansion.create import (
    UnresolvableCitationError,
    standing_question_acceptance_option_id,
)
from app.knowledge.write_ops import _atomic_rename_noreplace_at
from app.services.outbox import append_jsonl_outbox_event, iter_jsonl_outbox_records
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# --- named, WriteGuard-gated action (dotted <module>.<verb> convention) ------
ACCEPT_MATERIALIZE_WRITE_ACTION = "expansion.create.accept_materialize"

CREATE_ACCEPTED_EVENT = "expansion.create.accepted"
CREATE_DECLINED_EVENT = "expansion.create.declined"
ACCEPT_EVENT_SOURCE = "app.expansion.accept"

# Acceptance advances authority_state along the spec's frontmatter vocabulary
# (`proposal` -> `accepted`), matching what EXP-3 actually writes into the draft
# (`app.expansion.create._draft_frontmatter` stamps `authority_state: proposal`).
PROPOSAL_AUTHORITY_STATE = "proposal"
ACCEPTED_AUTHORITY_STATE = "accepted"

# Accepted synthesis stays machine-derived (never silently upgraded to evidence).
SYNTHESIS_DERIVED_BY = "synthesis"

# The AuthorityTransition operation class + initiating source (the checked
# checkbox is the human's approval).
ACCEPT_OPERATION_TYPE = "accept"
ACCEPT_INITIATING_SOURCE = "human_approval"


class AcceptError(RuntimeError):
    """Base for acceptance-path refusals."""


class DraftNotFoundError(AcceptError):
    """The staged draft path does not exist / is unreadable."""


class DraftNotAcceptedError(AcceptError):
    """The staged draft's in-draft acceptance checkbox is still unchecked.

    The machine never materializes a canonical note without the human's
    checkbox — this is the acceptance-side half of
    ``create_never_autowrites_canonical``.
    """


class DraftContentChangedError(AcceptError):
    """The loaded staged draft does not match the bytes a caller approved."""


class ModifyExistingRequiresAskError(AcceptError):
    """The resolved destination is an existing canonical note.

    Materializing over an existing note is a body edit and stays ``ask-you``
    per the ratified #1881 table (``docs/CAPABILITY_CONTRACT_MODEL.md``). This
    slice applies the ratified table; it never quietly materializes that variant
    at a lighter tier. The checkbox for that variant *is* the ask, handled by a
    separate governed edit flow — not by this new-note materialization path.
    """


class AcceptanceReconciliationError(AcceptError):
    """A durable transition exists but its receipt-bound state is unresolved."""

    def __init__(
        self,
        message: str,
        *,
        receipt_id: str | None = None,
        recovery_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.receipt_id = receipt_id
        self.recovery_paths = recovery_paths


class MalformedDraftError(AcceptError):
    """The staged draft is missing the provenance frontmatter EXP-3 writes
    (``derived_by: synthesis`` / ``sources:``); refusing to materialize an
    artifact whose provenance cannot be preserved."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _strip_html_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Remove Markdown-hidden HTML comments while carrying multiline state."""
    visible: list[str] = []
    offset = 0
    while offset < len(line):
        if in_comment:
            close = line.find("-->", offset)
            if close < 0:
                return "".join(visible), True
            offset = close + len("-->")
            in_comment = False
            continue

        start = line.find("<!--", offset)
        if start < 0:
            visible.append(line[offset:])
            break
        visible.append(line[offset:start])
        offset = start + len("<!--")
        in_comment = True

    return "".join(visible), in_comment


def _commonmark_indent_columns(line: str) -> int:
    """Count leading indentation using CommonMark's four-column tab stops."""
    columns = 0
    for character in line:
        if character == " ":
            columns += 1
        elif character == "\t":
            columns = ((columns // 4) + 1) * 4
        else:
            break
    return columns


def _is_commonmark_indented_code(line: str) -> bool:
    return _commonmark_indent_columns(line) >= 4


_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_HTML_RAW_BLOCK_TAGS = frozenset({"pre", "script", "style"})
_HTML_BLOCK_START = re.compile(
    r"^ {0,3}(?:</?[A-Za-z][A-Za-z0-9:-]*(?:[\t />]|$)|<![A-Za-z\[]|<\?)"
)
_HTML_RAW_BLOCK_START = re.compile(r"^ {0,3}<(pre|script|style)(?:[\t />]|$)", re.IGNORECASE)


class _AcceptanceHtmlScope(HTMLParser):
    """Track raw HTML containers so checkbox-looking content cannot authorize acceptance."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.open_tags: list[str] = []
        self.closed_tags: list[str] = []

    @property
    def has_open_markup(self) -> bool:
        return bool(self.open_tags or self.rawdata)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized not in _HTML_VOID_TAGS:
            self.open_tags.append(normalized)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in _HTML_RAW_BLOCK_TAGS:
            # CommonMark starts a type-1 raw HTML block from `<pre ` even
            # when HTMLParser sees an XHTML-style self-closing tag. Keep that
            # block literal until the matching end tag is encountered.
            self.open_tags.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        for index in range(len(self.open_tags) - 1, -1, -1):
            if self.open_tags[index] == normalized:
                del self.open_tags[index:]
                self.closed_tags.append(normalized)
                break


def _is_checked(text: str, draft_id: str) -> bool:
    """Accept only the generated checkbox for this draft inside an AI panel.

    Draft text may contain ordinary checked tasks. They are human content, not
    acceptance authority. The generated control binds its short draft identity
    into the exact label, and duplicate/malformed copies fail closed.
    """
    expected_label = f"Accept this draft into the vault (draft {draft_id[:12]})"
    question_option_suffix = (
        f" <!--ai:option_id={standing_question_acceptance_option_id(draft_id)}--> "
        "<!--ai:proposed=exp4-->"
    )
    # A visible checked copy must not stand in for the generated unchecked
    # control when that original is hidden in a comment, code block, or HTML.
    # The draft-bound label is unique, so any duplicate occurrence is an
    # ambiguous authority signal and fails closed.
    unique_label = text.count(expected_label) == 1
    in_ai_panel = False
    in_html_comment = False
    html_scope = _AcceptanceHtmlScope()
    html_block_until_blank = False
    html_raw_block_tag: str | None = None
    fence: tuple[str, int] | None = None
    matches: list[bool] = []
    # CommonMark recognizes LF, CR, and CRLF as line endings; str.splitlines()
    # also splits Unicode separators such as U+2028 and could turn literal
    # text into a flush-left generated control.
    for original_line in re.split(r"\r\n|\r|\n", text):
        if fence is not None:
            fence_marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", original_line)
            if fence_marker:
                delimiter, suffix = fence_marker.groups()
                if delimiter[0] == fence[0] and len(delimiter) >= fence[1] and not suffix.strip():
                    fence = None
            continue

        if not in_html_comment and _is_commonmark_indented_code(original_line):
            # Indented Markdown code is literal content, so HTML-like text in
            # it cannot open a comment that hides the later generated control.
            continue

        comment_was_active = in_html_comment
        line, in_html_comment = _strip_html_comments(original_line, in_html_comment)
        if _is_commonmark_indented_code(line):
            # Markdown's indented-code form is literal example text. The
            # generated action is flush-left, so indentation never carries
            # acceptance authority.
            continue
        if html_raw_block_tag is not None:
            html_scope.closed_tags.clear()
            html_scope.feed(line + "\n")
            if html_raw_block_tag in html_scope.closed_tags:
                # CommonMark type-1 HTML blocks end on the line containing
                # the matching raw-element close, even when no blank line
                # follows. Let Markdown fences and controls parse next line.
                html_raw_block_tag = None
            continue
        if html_block_until_blank:
            html_scope.feed(line + "\n")
            if not line.strip() and not in_html_comment and not html_scope.has_open_markup:
                # CommonMark type-6/7 HTML blocks end at a blank line. Keep
                # raw/unclosed markup fail-closed even across that boundary.
                html_block_until_blank = False
            continue
        html_was_open = html_scope.has_open_markup
        if _HTML_BLOCK_START.match(line):
            raw_block_match = _HTML_RAW_BLOCK_START.match(line)
            if raw_block_match:
                html_raw_block_tag = raw_block_match.group(1).lower()
            else:
                # Markdown keeps type-3 through type-7 block HTML literal
                # through a blank line, even when tags open and close on the
                # same source line. This also conservatively covers custom
                # elements and declarations.
                html_block_until_blank = True
            html_scope.closed_tags.clear()
            html_scope.feed(line + "\n")
            if html_raw_block_tag and html_raw_block_tag in html_scope.closed_tags:
                html_raw_block_tag = None
            continue
        html_scope.closed_tags.clear()
        html_scope.feed(line + "\n")
        if html_was_open or html_scope.has_open_markup:
            # HTML blocks are literal markup content. A checkbox-looking line
            # inside one is never the generated interactive control.
            continue
        # Do not normalize non-ASCII whitespace into the generated control.
        marker = original_line
        has_comment_delimiter = "<!--" in original_line or "-->" in original_line
        generated_question_control = marker in {
            f"- [ ] {expected_label}{question_option_suffix}",
            f"- [x] {expected_label}{question_option_suffix}",
            f"- [X] {expected_label}{question_option_suffix}",
        }
        exact_visible_line = (
            not comment_was_active
            and not in_html_comment
            and (not has_comment_delimiter or generated_question_control)
        )
        fence_marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_marker:
            delimiter, _suffix = fence_marker.groups()
            fence = (delimiter[0], len(delimiter))
            continue
        if _commonmark_indent_columns(line):
            # Generated controls and panel delimiters are flush-left. A
            # nested-list checkbox is rendered as a different control and
            # cannot stand in for the dedicated generated action.
            continue
        if not exact_visible_line:
            continue
        if marker == "%% AI:Start %%":
            if in_ai_panel:
                return False
            in_ai_panel = True
            continue
        if marker == "%% AI:End %%":
            if not in_ai_panel:
                return False
            in_ai_panel = False
            continue
        if not in_ai_panel:
            continue
        if marker in {
            f"- [ ] {expected_label}",
            f"- [ ] {expected_label}{question_option_suffix}",
        }:
            matches.append(False)
        elif marker in {
            f"- [x] {expected_label}",
            f"- [X] {expected_label}",
            f"- [x] {expected_label}{question_option_suffix}",
            f"- [X] {expected_label}{question_option_suffix}",
        }:
            matches.append(True)
    return (
        fence is None
        and not in_html_comment
        and not html_block_until_blank
        and not html_scope.has_open_markup
        and not in_ai_panel
        and unique_label
        and len(matches) == 1
        and matches[0]
    )


@dataclass(frozen=True)
class DecisionToken:
    """The pre-mutation governed-write DecisionToken.

    Minted ONLY from the human's checked acceptance checkbox
    (:func:`_mint_decision_token`) — never by the materialization path on its
    own initiative (``execution_cannot_authorize_itself``). ``token_ref`` is a
    content hash over the draft id + the checkbox-checked evidence, so the token
    is inseparable from the human act that produced it.
    """

    token_ref: str
    draft_id: str
    decided_by: str  # "human" — the checkbox is the human's decision
    decided_at: str


@dataclass(frozen=True)
class AcceptanceReceipt:
    """The post-mutation AuthorityReceipt for an accepted draft.

    Links draft -> final note -> sources (spec §2.4). Carried on the
    AuthorityTransition as ``authority_receipt_id``.
    """

    receipt_id: str
    draft_id: str
    final_note_path: str
    sources: tuple[str, ...]
    decision_token_ref: str
    accepted_at: str


@dataclass(frozen=True)
class AcceptResult:
    """Outcome of one acceptance attempt (observability + call-site assertions)."""

    status: str  # "accepted" | "already_accepted"
    draft_id: str
    final_note_path: str | None
    receipt_id: str | None
    decision_token_ref: str | None
    transition_id: str | None
    materialized_content_sha256: str | None = None


@dataclass(frozen=True)
class DeclineResult:
    """Outcome of one decline (spec §2.4 decline path)."""

    status: str  # "declined"
    draft_id: str
    receipt_id: str
    ledger_recorded: bool


@dataclass(frozen=True)
class _LoadedDraft:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    raw_text: str
    checked: bool
    raw_content: bytes
    raw_content_sha256: str
    file_identity: tuple[int, int, int, int]


_EXP4_RETIREMENT_MARKER = ".exp4-retire-"
_EXP4_RETIRED_MARKER = ".exp4-retired-"


def _draft_stat_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    )


def _draft_read_stability(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (*_draft_stat_identity(info), info.st_ctime_ns)


def _open_draft_parent(draft_path: Path) -> tuple[int, str, Path]:
    parent = draft_path.parent.resolve(strict=True)
    directory_fd = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
        os.close(directory_fd)
        raise OSError("staged draft parent is not a stable directory")
    return directory_fd, draft_path.name, parent / draft_path.name


def _read_named_draft(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise OSError("staged draft must be one stable regular file")

        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            _draft_read_stability(opened) != _draft_read_stability(after)
            or not stat.S_ISREG(named_after.st_mode)
            or named_after.st_nlink != 1
            or (after.st_dev, after.st_ino)
            != (named_after.st_dev, named_after.st_ino)
            or after.st_size != len(raw)
        ):
            raise OSError("staged draft changed while it was read")
        return raw, after
    finally:
        os.close(descriptor)


def _load_draft(
    draft_path: Path,
    *,
    expected_content_sha256: str | None = None,
) -> _LoadedDraft:
    from scripts.yaml_roundtrip import load_frontmatter

    directory_fd: int | None = None
    try:
        directory_fd, name, canonical_path = _open_draft_parent(draft_path)
        raw_bytes, before = _read_named_draft(directory_fd, name)
    except FileNotFoundError as exc:
        raise DraftNotFoundError(f"staged draft {draft_path} is not readable: {exc}") from exc
    except (OSError, RuntimeError) as exc:
        raise DraftContentChangedError(
            f"staged draft {draft_path} is not a stable regular file: {exc}"
        ) from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    raw_content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if (
        expected_content_sha256 is not None
        and raw_content_sha256 != expected_content_sha256
    ):
        raise DraftContentChangedError(
            f"staged draft {draft_path} changed after its human approval control was loaded"
        )
    raw_text = raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    frontmatter, body = load_frontmatter(raw_text)
    frontmatter = frontmatter or {}
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    return _LoadedDraft(
        path=canonical_path,
        frontmatter=frontmatter,
        body=body,
        raw_text=raw_text,
        # Frontmatter is metadata, not rendered acceptance content. Only the
        # parsed Markdown body can carry the governed checkbox.
        checked=_is_checked(body, draft_id),
        raw_content=raw_bytes,
        raw_content_sha256=raw_content_sha256,
        file_identity=_draft_stat_identity(before),
    )


def _draft_id_of(loaded: _LoadedDraft) -> str:
    return str(loaded.frontmatter.get("uuid") or loaded.path.stem)


def _receipt_retirement_names(draft_name: str, receipt_id: str) -> tuple[str, str]:
    receipt_tag = hashlib.sha256(receipt_id.encode("utf-8")).hexdigest()
    return (
        f".{draft_name}{_EXP4_RETIREMENT_MARKER}{receipt_tag}.pending",
        f".{draft_name}{_EXP4_RETIRED_MARKER}{receipt_tag}.recovery",
    )


def _named_entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _retirement_conflict(
    message: str,
    *,
    receipt_id: str,
    parent: Path,
    names: tuple[str, ...],
) -> AcceptanceReconciliationError:
    paths = tuple(str(parent / name) for name in names if name)
    return AcceptanceReconciliationError(
        message,
        receipt_id=receipt_id,
        recovery_paths=paths,
    )


def _loaded_file_matches(loaded: _LoadedDraft, raw: bytes, info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and _draft_stat_identity(info) == loaded.file_identity
        and raw == loaded.raw_content
    )


def _restore_retirement_if_absent(
    directory_fd: int,
    *,
    source_name: str,
    original_name: str,
) -> bool:
    if _named_entry_exists(directory_fd, original_name):
        return False
    try:
        _atomic_rename_noreplace_at(
            directory_fd,
            source_name,
            directory_fd,
            original_name,
        )
    except FileExistsError:
        return False
    os.fsync(directory_fd)
    return True


def _retire_loaded_draft_if_unchanged(
    loaded: _LoadedDraft,
    *,
    receipt_id: str,
) -> str:
    """Receipt-bind an unchanged staged snapshot into an inert retained archive.

    The rename to a pending name happens before verification, so a concurrent
    replacement cannot slip between a path check and deletion.  A mismatch is
    restored only when the original name is free; otherwise both versions are
    kept and named in the reconciliation error.
    """

    try:
        directory_fd, original_name, canonical_path = _open_draft_parent(loaded.path)
    except (OSError, RuntimeError) as exc:
        raise _retirement_conflict(
            "the staged draft directory cannot be opened for receipt-bound retirement",
            receipt_id=receipt_id,
            parent=loaded.path.parent,
            names=(loaded.path.name,),
        ) from exc
    pending_name, retired_name = _receipt_retirement_names(original_name, receipt_id)
    parent = canonical_path.parent
    try:
        pending_exists = _named_entry_exists(directory_fd, pending_name)
        retired_exists = _named_entry_exists(directory_fd, retired_name)
        original_exists = _named_entry_exists(directory_fd, original_name)

        if pending_exists and retired_exists:
            raise _retirement_conflict(
                "both pending and retired draft evidence exist for this receipt",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name, retired_name),
            )
        if retired_exists:
            if original_exists:
                raise _retirement_conflict(
                    "a new staged file occupies the path of an already-retired draft",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name, retired_name),
                )
            try:
                archived, info = _read_named_draft(directory_fd, retired_name)
            except OSError as exc:
                raise _retirement_conflict(
                    "the receipt-bound retired draft cannot be inspected safely",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(retired_name,),
                ) from exc
            if not _loaded_file_matches(loaded, archived, info):
                raise _retirement_conflict(
                    "the receipt-bound retired draft differs from the loaded snapshot",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(retired_name,),
                )
            if _named_entry_exists(directory_fd, original_name):
                raise _retirement_conflict(
                    "a new staged file appeared while the retired archive was being checked",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name, retired_name),
                )
            return str(parent / retired_name)

        if pending_exists:
            if original_exists:
                raise _retirement_conflict(
                    "a new staged file appeared while receipt-bound retirement is pending",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name, pending_name),
                )
        else:
            if not original_exists:
                raise _retirement_conflict(
                    "the staged draft disappeared before receipt-bound retirement",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name,),
                )
            try:
                _atomic_rename_noreplace_at(
                    directory_fd,
                    original_name,
                    directory_fd,
                    pending_name,
                )
            except FileExistsError as exc:
                raise _retirement_conflict(
                    "the receipt-bound pending draft path already exists",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name, pending_name),
                ) from exc
            os.fsync(directory_fd)

        try:
            pending, info = _read_named_draft(directory_fd, pending_name)
        except OSError as exc:
            _restore_retirement_if_absent(
                directory_fd,
                source_name=pending_name,
                original_name=original_name,
            )
            raise _retirement_conflict(
                "the pending staged draft cannot be inspected safely",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name),
            ) from exc
        if not _loaded_file_matches(loaded, pending, info):
            _restore_retirement_if_absent(
                directory_fd,
                source_name=pending_name,
                original_name=original_name,
            )
            raise _retirement_conflict(
                "the staged draft changed during conditional retirement; its current bytes were preserved",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name),
            )
        if _named_entry_exists(directory_fd, original_name):
            raise _retirement_conflict(
                "a new staged file appeared before the accepted snapshot could be archived",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name),
            )
        try:
            _atomic_rename_noreplace_at(
                directory_fd,
                pending_name,
                directory_fd,
                retired_name,
            )
        except FileExistsError as exc:
            raise _retirement_conflict(
                "the receipt-bound retired archive path already exists",
                receipt_id=receipt_id,
                parent=parent,
                names=(pending_name, retired_name),
            ) from exc
        os.fsync(directory_fd)

        try:
            archived, archived_info = _read_named_draft(directory_fd, retired_name)
        except OSError as exc:
            _restore_retirement_if_absent(
                directory_fd,
                source_name=retired_name,
                original_name=original_name,
            )
            raise _retirement_conflict(
                "the retired draft archive cannot be inspected safely",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, retired_name),
            ) from exc
        if not _loaded_file_matches(loaded, archived, archived_info):
            _restore_retirement_if_absent(
                directory_fd,
                source_name=retired_name,
                original_name=original_name,
            )
            raise _retirement_conflict(
                "the staged draft changed during final retirement; its current bytes were preserved",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, retired_name),
            )
        if _named_entry_exists(directory_fd, original_name):
            raise _retirement_conflict(
                "a new staged file appeared while the final archive was being checked",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, retired_name),
            )
        return str(parent / retired_name)
    except AcceptanceReconciliationError:
        raise
    except Exception as exc:
        raise _retirement_conflict(
            "receipt-bound staged draft retirement did not complete safely",
            receipt_id=receipt_id,
            parent=parent,
            names=(original_name, pending_name, retired_name),
        ) from exc
    finally:
        os.close(directory_fd)


def reconcile_missing_draft_retirement(
    draft_path: Path,
    *,
    receipt_id: str,
    expected_content_sha256: str | None,
) -> str | None:
    """Finish or verify receipt-bound retirement after the staged name vanished.

    ``None`` is returned only for a legacy receipt that predates draft hashes
    and has no retirement marker. New receipts require matching pending or
    retired evidence before Question acknowledgement can proceed.
    """

    try:
        directory_fd, original_name, canonical_path = _open_draft_parent(draft_path)
    except (OSError, RuntimeError) as exc:
        raise _retirement_conflict(
            "the staged draft directory cannot be opened for receipt reconciliation",
            receipt_id=receipt_id,
            parent=draft_path.parent,
            names=(draft_path.name,),
        ) from exc
    pending_name, retired_name = _receipt_retirement_names(original_name, receipt_id)
    parent = canonical_path.parent
    try:
        if _named_entry_exists(directory_fd, original_name):
            raise _retirement_conflict(
                "a staged file now occupies the path whose receipt is being reconciled",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name, retired_name),
            )
        pending_exists = _named_entry_exists(directory_fd, pending_name)
        retired_exists = _named_entry_exists(directory_fd, retired_name)
        if pending_exists and retired_exists:
            raise _retirement_conflict(
                "both pending and retired draft evidence exist for this receipt",
                receipt_id=receipt_id,
                parent=parent,
                names=(pending_name, retired_name),
            )
        if not pending_exists and not retired_exists:
            if expected_content_sha256 is None:
                return None
            raise _retirement_conflict(
                "the staged draft is missing without receipt-bound retirement evidence",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name,),
            )
        if expected_content_sha256 is None:
            raise _retirement_conflict(
                "retired draft evidence cannot be verified against this legacy receipt",
                receipt_id=receipt_id,
                parent=parent,
                names=(pending_name, retired_name),
            )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_content_sha256):
            raise _retirement_conflict(
                "receipt-bound staged-draft digest has an invalid format",
                receipt_id=receipt_id,
                parent=parent,
                names=(pending_name, retired_name),
            )

        current_name = pending_name if pending_exists else retired_name
        try:
            raw, info = _read_named_draft(directory_fd, current_name)
        except OSError as exc:
            raise _retirement_conflict(
                "receipt-bound draft evidence cannot be inspected safely",
                receipt_id=receipt_id,
                parent=parent,
                names=(current_name,),
            ) from exc
        if hashlib.sha256(raw).hexdigest() != expected_content_sha256:
            if pending_exists:
                _restore_retirement_if_absent(
                    directory_fd,
                    source_name=pending_name,
                    original_name=original_name,
                )
            raise _retirement_conflict(
                "receipt-bound draft evidence differs from the bytes accepted by EXP-4",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, current_name),
            )
        if retired_exists:
            if _named_entry_exists(directory_fd, original_name):
                raise _retirement_conflict(
                    "a staged file appeared while its receipt-bound archive was being checked",
                    receipt_id=receipt_id,
                    parent=parent,
                    names=(original_name, retired_name),
                )
            return str(parent / retired_name)

        if _named_entry_exists(directory_fd, original_name):
            raise _retirement_conflict(
                "a staged file appeared before pending draft evidence could be archived",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, pending_name),
            )

        try:
            _atomic_rename_noreplace_at(
                directory_fd,
                pending_name,
                directory_fd,
                retired_name,
            )
        except FileExistsError as exc:
            raise _retirement_conflict(
                "the receipt-bound retired archive path appeared during reconciliation",
                receipt_id=receipt_id,
                parent=parent,
                names=(pending_name, retired_name),
            ) from exc
        os.fsync(directory_fd)
        archived, archived_info = _read_named_draft(directory_fd, retired_name)
        if (
            hashlib.sha256(archived).hexdigest() != expected_content_sha256
            or not stat.S_ISREG(archived_info.st_mode)
            or archived_info.st_nlink != 1
        ):
            raise _retirement_conflict(
                "the receipt-bound archive changed during reconciliation",
                receipt_id=receipt_id,
                parent=parent,
                names=(retired_name,),
            )
        if _named_entry_exists(directory_fd, original_name):
            raise _retirement_conflict(
                "a staged file appeared while its reconciled archive was being checked",
                receipt_id=receipt_id,
                parent=parent,
                names=(original_name, retired_name),
            )
        return str(parent / retired_name)
    except AcceptanceReconciliationError:
        raise
    except Exception as exc:
        raise _retirement_conflict(
            "receipt-bound staged draft retirement could not be reconciled safely",
            receipt_id=receipt_id,
            parent=parent,
            names=(original_name, pending_name, retired_name),
        ) from exc
    finally:
        os.close(directory_fd)


def _sources_of(loaded: _LoadedDraft) -> tuple[str, ...]:
    raw = loaded.frontmatter.get("sources")
    if not isinstance(raw, list):
        return ()
    return tuple(str(s) for s in raw if str(s).strip())


def _mint_decision_token(loaded: _LoadedDraft, *, now: datetime) -> DecisionToken:
    """Mint the governed-write DecisionToken from the human's checked checkbox.

    This is the ``execution_cannot_authorize_itself`` seam: the token exists
    only because ``loaded.checked`` is True (a human checked the box). The
    materialization path never calls this for an unchecked draft, and the token
    is a hash over the checkbox evidence, so it cannot be forged by execution.
    """
    if not loaded.checked:  # defensive: callers gate on this first
        raise DraftNotAcceptedError(
            f"draft {_draft_id_of(loaded)!r} has no checked acceptance checkbox; "
            "the machine never mints acceptance authority for an unchecked draft"
        )
    draft_id = _draft_id_of(loaded)
    digest = hashlib.sha256(
        f"human-accept::{draft_id}::checkbox-checked".encode("utf-8")
    ).hexdigest()
    return DecisionToken(
        token_ref=f"dtok-{digest[:24]}",
        draft_id=draft_id,
        decided_by="human",
        decided_at=_iso(now),
    )


def _re_validate_citations(loaded: _LoadedDraft, *, live_source_ids: set[str] | None) -> None:
    """Re-validate provenance at acceptance time (spec §2.4 / §6:
    ``synthesis_carries_source_provenance``).

    The draft must still carry its ``sources:`` list and ``derived_by: synthesis``.
    When the caller supplies the set of source ids that still resolve
    (``live_source_ids``), a cited source that no longer resolves blocks the
    acceptance LOUDLY — provenance survival is enforced at acceptance, not just
    at draft creation. When ``live_source_ids`` is None the caller has asserted
    the source set is unchanged since draft creation (already citation-validated
    by EXP-3), so only the structural provenance is re-checked.
    """
    if str(loaded.frontmatter.get("derived_by") or "").strip() != SYNTHESIS_DERIVED_BY:
        raise MalformedDraftError(
            f"draft {_draft_id_of(loaded)!r} is missing 'derived_by: {SYNTHESIS_DERIVED_BY}'; "
            "refusing to materialize an artifact whose synthesis provenance is absent"
        )
    sources = _sources_of(loaded)
    if not sources:
        raise MalformedDraftError(
            f"draft {_draft_id_of(loaded)!r} carries no 'sources:'; a synthesis note without "
            "resolvable sources is unaccountable machine text — blocking acceptance"
        )
    if live_source_ids is None:
        return
    for source_id in sources:
        if source_id not in live_source_ids:
            raise UnresolvableCitationError(
                f"cited source {source_id!r} for draft {_draft_id_of(loaded)!r} no longer resolves "
                "at acceptance time; blocking materialization (provenance must survive acceptance)"
            )


def _already_accepted(loaded: _LoadedDraft) -> bool:
    state = str(loaded.frontmatter.get("authority_state") or "").strip()
    return state == ACCEPTED_AUTHORITY_STATE or bool(loaded.frontmatter.get("accepted_by"))


def _slugify(title: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in title.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or uuid4().hex[:12]


def _resolve_destination(
    *,
    vault_root: Path,
    loaded: _LoadedDraft,
    destination: str | None,
) -> Path:
    """Resolve the human-chosen canonical destination (default correctable by
    the human, spec §2.4). Falls back to a title/id-derived filename at the
    vault root. Always contained within the vault."""
    if destination:
        rel = Path(destination)
    else:
        title = str(loaded.frontmatter.get("title") or "").strip()
        stem = _slugify(title) if title else _draft_id_of(loaded)
        rel = Path(f"{stem}.md")
    if rel.is_absolute():
        candidate = rel.resolve()
    else:
        candidate = (vault_root / rel).resolve()
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    # Compare path ancestry, not string prefixes (e.g. `/vault-backup` is not
    # inside `/vault`). Resolve above so existing symlinks cannot escape either.
    if not candidate.is_relative_to(vault_root):
        raise AcceptError(
            f"destination {destination!r} resolves outside the vault root; refusing"
        )
    return candidate


def _build_accepted_frontmatter(
    loaded: _LoadedDraft,
    *,
    receipt_id: str,
    decision_token_ref: str,
    accepted_at: datetime,
) -> dict[str, Any]:
    """Provenance-preserving frontmatter for the accepted canonical note.

    Keeps ``sources`` + ``derived_by: synthesis`` (never stripped, never
    upgraded); advances ``authority_state`` proposal -> accepted; stamps
    ``accepted_by: human`` + the acceptance receipt id. Drops staging-only keys
    (``kind: draft``, ``expires``, ``create_kind``) that no longer apply to a
    canonical note, but never the provenance ones.
    """
    fm = dict(loaded.frontmatter)
    fm["derived_by"] = SYNTHESIS_DERIVED_BY  # permanent, not staging-only
    fm["authority_state"] = ACCEPTED_AUTHORITY_STATE
    fm["accepted_by"] = "human"
    fm["accepted_at"] = _iso(accepted_at)
    fm["acceptance_receipt_id"] = receipt_id
    fm["decision_token_ref"] = decision_token_ref
    # `sources` is preserved verbatim from the draft (do not touch it).
    fm.setdefault("sources", list(_sources_of(loaded)))
    # Staging-only keys that must not leak onto a canonical note.
    for staging_key in ("kind", "expires", "create_kind"):
        fm.pop(staging_key, None)
    return fm


def _strip_acceptance_checkbox(body: str) -> str:
    """Remove the EXP-3 acceptance checkbox block from the materialized body.

    The checkbox is a review-surface affordance on the *staged* draft; the
    accepted canonical note must not carry a live acceptance checkbox. The
    human's edits to the rest of the body are preserved verbatim.
    """
    lines = body.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == "%% AI:Start %%":
            skipping = True
            continue
        if stripped == "%% AI:End %%":
            skipping = False
            continue
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _emit_receipt(
    event: str,
    payload: dict[str, Any],
    *,
    outbox_path: Path,
    trace_id: str | None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> str:
    event_id = event_id or uuid4().hex
    record = {
        "event": event,
        "event_id": event_id,
        "trace_id": trace_id or uuid4().hex,
        "source": ACCEPT_EVENT_SOURCE,
        "timestamp": timestamp or _iso(_now()),
        "payload": payload,
    }
    append_jsonl_outbox_event(outbox_path, record, default_source=ACCEPT_EVENT_SOURCE)
    return event_id


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("canonical note write made no progress")
        offset += written


def _fsync_directory(path: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if directory_flag is None:
        return
    descriptor = os.open(path, os.O_RDONLY | directory_flag)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _install_new_canonical_note(destination_path: Path, data: bytes) -> bool:
    """Atomically publish a fully written note without replacing a destination."""

    temporary_path = destination_path.parent / f".{destination_path.name}.{uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    temporary_created = False
    try:
        descriptor = os.open(temporary_path, flags, 0o666)
        temporary_created = True
        try:
            _write_all(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

        try:
            os.link(temporary_path, destination_path, follow_symlinks=False)
        except FileExistsError:
            return False
        _fsync_directory(destination_path.parent)
        return True
    finally:
        if temporary_created:
            temporary_path.unlink(missing_ok=True)


def _cleanup_linked_acceptance_temps(destination_path: Path) -> None:
    """Retire only a leftover staging name that is the canonical note's inode."""

    target = destination_path.stat(follow_symlinks=False)
    if not stat.S_ISREG(target.st_mode):
        raise AcceptanceReconciliationError("the accepted destination is not a regular file")
    removed = False
    for candidate in destination_path.parent.glob(f".{destination_path.name}.*.tmp"):
        try:
            info = candidate.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if (
            stat.S_ISREG(info.st_mode)
            and (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino)
        ):
            candidate.unlink()
            removed = True
    if removed:
        _fsync_directory(destination_path.parent)


def _recover_materialized_question_acceptance(
    loaded: _LoadedDraft,
    *,
    destination_path: Path,
    vault_root: Path,
    outbox_path: Path,
    write_guard: WriteGuard,
) -> AcceptResult | None:
    """Recover only an exact SQ answer materialized by an earlier attempt.

    EXP-4 writes the canonical note, then its outbox receipt, then removes the
    staged draft. A process exit between those operations leaves enough evidence
    to retry safely while the draft still exists. The accepted note must match
    every draft field and the checkbox-stripped body; an unrelated destination
    remains the existing ask-you case.
    """

    if (
        loaded.frontmatter.get("create_kind") != "create.answer_note"
        or not isinstance(loaded.frontmatter.get("question_id"), str)
        or not loaded.frontmatter.get("question_id")
    ):
        return None

    from scripts.yaml_roundtrip import load_frontmatter

    try:
        accepted_bytes = destination_path.read_bytes()
        accepted_text = accepted_bytes.decode("utf-8")
        accepted_frontmatter, accepted_body = load_frontmatter(accepted_text)
    except (OSError, UnicodeError, ValueError) as exc:
        raise AcceptanceReconciliationError(
            "the existing answer destination cannot be inspected safely"
        ) from exc
    accepted_frontmatter = accepted_frontmatter or {}
    receipt_id = accepted_frontmatter.get("acceptance_receipt_id")
    token_ref = accepted_frontmatter.get("decision_token_ref")
    accepted_at_value = accepted_frontmatter.get("accepted_at")

    def reject_ambiguous_same_draft() -> None:
        if (
            accepted_frontmatter.get("uuid") == _draft_id_of(loaded)
            or destination_path.stem == _draft_id_of(loaded)
        ):
            raise AcceptanceReconciliationError(
                "the existing answer appears to belong to this draft but has incomplete acceptance metadata"
            )

    if not isinstance(receipt_id, str) or not receipt_id.strip():
        reject_ambiguous_same_draft()
        return None
    if not isinstance(token_ref, str) or not token_ref.strip():
        reject_ambiguous_same_draft()
        return None
    if isinstance(accepted_at_value, datetime):
        accepted_at = accepted_at_value
    elif isinstance(accepted_at_value, str):
        try:
            accepted_at = datetime.fromisoformat(accepted_at_value.replace("Z", "+00:00"))
        except ValueError:
            reject_ambiguous_same_draft()
            return None
    else:
        reject_ambiguous_same_draft()
        return None
    if accepted_at.tzinfo is None:
        reject_ambiguous_same_draft()
        return None

    expected_frontmatter = _build_accepted_frontmatter(
        loaded,
        receipt_id=receipt_id,
        decision_token_ref=token_ref,
        accepted_at=accepted_at,
    )
    comparable_frontmatter = dict(accepted_frontmatter)
    comparable_frontmatter["accepted_at"] = _iso(accepted_at)
    if (
        comparable_frontmatter != expected_frontmatter
        or accepted_body != _strip_acceptance_checkbox(loaded.body)
    ):
        if (
            accepted_frontmatter.get("uuid") == _draft_id_of(loaded)
            or destination_path.stem == _draft_id_of(loaded)
        ):
            raise AcceptanceReconciliationError(
                "the existing answer appears to belong to this draft but is not an exact materialization"
            )
        return None

    _cleanup_linked_acceptance_temps(destination_path)

    try:
        final_rel = destination_path.resolve().relative_to(vault_root).as_posix()
    except (OSError, RuntimeError, ValueError) as exc:
        raise AcceptanceReconciliationError(
            "the existing answer destination is outside the selected vault"
        ) from exc
    payload = {
        "draft_id": _draft_id_of(loaded),
        "final_note_path": final_rel,
        "draft_content_sha256": loaded.raw_content_sha256,
        "sources": list(_sources_of(loaded)),
        "decision_token_ref": token_ref,
        "authority_receipt_id": receipt_id,
        "accepted_by": "human",
        "authority_state": ACCEPTED_AUTHORITY_STATE,
        "materialized_content_sha256": hashlib.sha256(accepted_bytes).hexdigest(),
    }

    try:
        matching = [
            record
            for record in iter_jsonl_outbox_records(outbox_path)
            if record.get("event") == CREATE_ACCEPTED_EVENT
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("draft_id") == payload["draft_id"]
        ]
        if matching:
            if (
                len(matching) != 1
                or matching[0].get("payload") != payload
                or matching[0].get("source") != ACCEPT_EVENT_SOURCE
                or matching[0].get("trace_id") != payload["draft_id"]
            ):
                raise AcceptanceReconciliationError(
                    "the accepted answer has a conflicting or duplicate receipt"
                )
            event_id = matching[0].get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise AcceptanceReconciliationError(
                    "the accepted answer receipt has no event identity"
                )
        else:
            write_guard.assert_writes_allowed(ACCEPT_MATERIALIZE_WRITE_ACTION)
            event_id = hashlib.sha256(
                f"{CREATE_ACCEPTED_EVENT}\x1f{payload['draft_id']}\x1f{receipt_id}".encode("utf-8")
            ).hexdigest()
            _emit_receipt(
                CREATE_ACCEPTED_EVENT,
                payload,
                outbox_path=outbox_path,
                trace_id=str(payload["draft_id"]),
                event_id=event_id,
                timestamp=_iso(accepted_at),
            )
    except AcceptanceReconciliationError:
        raise
    except Exception as exc:
        raise AcceptanceReconciliationError(
            "the accepted answer receipt could not be reconciled safely"
        ) from exc

    _retire_loaded_draft_if_unchanged(loaded, receipt_id=receipt_id)
    return AcceptResult(
        status="accepted",
        draft_id=_draft_id_of(loaded),
        final_note_path=final_rel,
        receipt_id=receipt_id,
        decision_token_ref=token_ref,
        transition_id=None,
        materialized_content_sha256=hashlib.sha256(accepted_bytes).hexdigest(),
    )


def _build_authority_transition(
    *,
    target_object_id: str,
    target_scope_id: str,
    token: DecisionToken,
    receipt_id: str,
    provenance_event_ids: list[str],
    now: datetime,
) -> dict[str, Any]:
    """Assemble the governed AuthorityTransition record for this acceptance.

    Carries BOTH the pre-mutation ``decision_token_ref`` and the post-mutation
    ``authority_receipt_id`` (``authority_transition_requires_decision_token_and_receipt``),
    mirroring ``schemas/authority-transition.schema.json``. This is the
    architecture state object; WriteGuard is the runtime mechanism that gated
    the write it records.
    """
    return {
        "transition_id": f"atx-{uuid4().hex}",
        "actor_id": token.decided_by,
        "initiating_source": ACCEPT_INITIATING_SOURCE,
        "target_object_id": target_object_id,
        "target_scope_id": target_scope_id,
        "prior_authority_state": PROPOSAL_AUTHORITY_STATE,
        "requested_authority_state": ACCEPTED_AUTHORITY_STATE,
        "approved_authority_state": ACCEPTED_AUTHORITY_STATE,
        "operation_type": ACCEPT_OPERATION_TYPE,
        "approval_required": True,
        "approval_state": "approved",
        "approved_by": token.decided_by,
        "approved_at": _iso(now),
        "decision_token_ref": token.token_ref,
        "authority_receipt_id": receipt_id,
        "provenance_event_ids": list(provenance_event_ids) or [receipt_id],
        "affected_derived_representation_ids": [],
        "created_at": _iso(now),
    }


def accept_draft(
    draft_path: Path,
    *,
    vault_root: Path,
    outbox_path: Path,
    destination: str | None = None,
    live_source_ids: set[str] | None = None,
    expected_draft_content_sha256: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> AcceptResult:
    """Materialize a *checked* staged draft into a canonical vault note.

    The ONLY path from a staged Create draft to canonical content. Refuses:
    an unchecked draft (:class:`DraftNotAcceptedError`); a destination that is an
    existing canonical note (:class:`ModifyExistingRequiresAskError` — that
    variant stays ``ask-you``); a draft whose provenance is missing or whose
    cited sources no longer resolve (:class:`MalformedDraftError` /
    :class:`UnresolvableCitationError`). Idempotent: an already-accepted draft
    returns ``already_accepted`` without a second write or receipt.

    ``live_source_ids`` — when given, the set of source object ids that still
    resolve; a cited source outside it blocks acceptance loudly. When None, the
    caller asserts the draft's source set is unchanged since EXP-3 validated it.

    ``expected_draft_content_sha256`` — when given by a source-bound human review
    flow, pins the exact UTF-8 bytes loaded for EXP-4 to the bytes that flow
    preflighted. A concurrent edit before this load refuses materialization; an
    edit after this load cannot change the immutable content EXP-4 materializes.
    """
    now = now or _now()
    vault_root = Path(vault_root).expanduser().resolve()
    draft_path = Path(draft_path)
    if not draft_path.is_absolute():
        draft_path = (vault_root / draft_path).resolve()

    loaded = _load_draft(
        draft_path,
        expected_content_sha256=expected_draft_content_sha256,
    )
    draft_id = _draft_id_of(loaded)

    # Idempotency: an already-accepted draft never double-materializes.
    if _already_accepted(loaded):
        return AcceptResult(
            status="already_accepted",
            draft_id=draft_id,
            final_note_path=None,
            receipt_id=str(loaded.frontmatter.get("acceptance_receipt_id") or "") or None,
            decision_token_ref=str(loaded.frontmatter.get("decision_token_ref") or "") or None,
            transition_id=None,
        )

    # create_never_autowrites_canonical (acceptance side): unchecked => refuse.
    if not loaded.checked:
        raise DraftNotAcceptedError(
            f"draft {draft_id!r} acceptance checkbox is unchecked; the machine never writes "
            "canonical on its own — a human must check the in-draft acceptance box first"
        )

    # synthesis_carries_source_provenance: re-validate at acceptance time.
    _re_validate_citations(loaded, live_source_ids=live_source_ids)

    destination_path = _resolve_destination(
        vault_root=vault_root, loaded=loaded, destination=destination
    )
    # modify-existing-note variant stays ask-you: never overwrite an existing note.
    if destination_path.exists():
        recovered = _recover_materialized_question_acceptance(
            loaded,
            destination_path=destination_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            write_guard=write_guard,
        )
        if recovered is not None:
            return recovered
        raise ModifyExistingRequiresAskError(
            f"destination {destination_path.relative_to(vault_root)} already exists; materializing over "
            "an existing canonical note is a body edit held at 'ask-you' — not this new-note path"
        )

    # execution_cannot_authorize_itself: the token is minted from the human's
    # checked checkbox, before any canonical write is attempted.
    token = _mint_decision_token(loaded, now=now)

    # WriteGuard gates the canonical materialization with a named action.
    write_guard.assert_writes_allowed(ACCEPT_MATERIALIZE_WRITE_ACTION)

    receipt_id = uuid4().hex

    # Edited-then-accepted: materialize the draft's CURRENT on-disk body (human
    # edits preserved), minus the staging-only acceptance checkbox block.
    from scripts.yaml_roundtrip import dump_frontmatter

    accepted_frontmatter = _build_accepted_frontmatter(
        loaded,
        receipt_id=receipt_id,
        decision_token_ref=token.token_ref,
        accepted_at=now,
    )
    materialized_body = _strip_acceptance_checkbox(loaded.body)
    note_text = dump_frontmatter(accepted_frontmatter, materialized_body)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    materialized_bytes = note_text.encode("utf-8")
    if not _install_new_canonical_note(destination_path, materialized_bytes):
        recovered = _recover_materialized_question_acceptance(
            loaded,
            destination_path=destination_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            write_guard=write_guard,
        )
        if recovered is not None:
            return recovered
        raise ModifyExistingRequiresAskError(
            f"destination {destination_path.relative_to(vault_root)} already exists; materializing over "
            "an existing canonical note is a body edit held at 'ask-you' — not this new-note path"
        )
    materialized_content_sha256 = hashlib.sha256(materialized_bytes).hexdigest()

    final_rel = str(destination_path.relative_to(vault_root))
    sources = _sources_of(loaded)

    # Post-mutation AuthorityReceipt (authority_receipt_id) — linking
    # draft -> final note -> sources, carrying the decision token ref.
    emitted_receipt_id = _emit_receipt(
        CREATE_ACCEPTED_EVENT,
        {
            "draft_id": draft_id,
            "final_note_path": final_rel,
            "draft_content_sha256": loaded.raw_content_sha256,
            "sources": list(sources),
            "decision_token_ref": token.token_ref,
            "authority_receipt_id": receipt_id,
            "accepted_by": "human",
            "authority_state": ACCEPTED_AUTHORITY_STATE,
            **(
                {"materialized_content_sha256": materialized_content_sha256}
                if loaded.frontmatter.get("create_kind") == "create.answer_note"
                and loaded.frontmatter.get("question_id")
                else {}
            ),
        },
        outbox_path=outbox_path,
        trace_id=draft_id,
    )

    transition = _build_authority_transition(
        target_object_id=draft_id,
        target_scope_id="vault",
        token=token,
        receipt_id=receipt_id,
        provenance_event_ids=[emitted_receipt_id],
        now=now,
    )

    # The staged draft has served its purpose; remove it so it is not re-swept
    # or re-accepted. The canonical note + receipt carry the durable record.
    _retire_loaded_draft_if_unchanged(loaded, receipt_id=receipt_id)

    return AcceptResult(
        status="accepted",
        draft_id=draft_id,
        final_note_path=final_rel,
        receipt_id=receipt_id,
        decision_token_ref=token.token_ref,
        transition_id=transition["transition_id"],
        materialized_content_sha256=materialized_content_sha256,
    )


def decline_draft(
    draft_path: Path,
    *,
    vault_root: Path,
    outbox_path: Path,
    reason: str | None = None,
    declined_ledger: Any = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> DeclineResult:
    """Decline a staged draft: record it in the declined-proposal ledger (EXP-2),
    remove/archive the staged draft, produce NO canonical note, keep the receipt.

    Decline is a visible lifecycle outcome, not silent deletion (spec §2.4).
    """
    now = now or _now()
    vault_root = Path(vault_root).expanduser().resolve()
    draft_path = Path(draft_path)
    if not draft_path.is_absolute():
        draft_path = (vault_root / draft_path).resolve()

    loaded = _load_draft(draft_path)
    draft_id = _draft_id_of(loaded)
    try:
        draft_rel = loaded.path.relative_to(vault_root).as_posix()
    except ValueError as exc:
        raise MalformedDraftError(
            "staged draft must be inside the selected vault before it can be declined"
        ) from exc

    if declined_ledger is None:
        from app.proposals.declined_ledger import default_declined_ledger

        declined_ledger = default_declined_ledger()

    ledger_recorded = False
    record_decline = getattr(declined_ledger, "record_decline", None)
    if callable(record_decline):
        record_decline(
            draft_id,
            finding_class="create.draft",
            reason=reason,
            declined_at=_iso(now),
            write_guard=write_guard,
        )
        ledger_recorded = True

    receipt_id = _emit_receipt(
        CREATE_DECLINED_EVENT,
        {
            "draft_id": draft_id,
            "draft_path": draft_rel,
            "draft_content_sha256": loaded.raw_content_sha256,
            "reason": reason,
            "sources": list(_sources_of(loaded)),
        },
        outbox_path=outbox_path,
        trace_id=draft_id,
    )

    # Remove the staged draft (no canonical note produced). The decline receipt
    # + ledger entry are the durable record.
    _retire_loaded_draft_if_unchanged(loaded, receipt_id=receipt_id)

    return DeclineResult(
        status="declined",
        draft_id=draft_id,
        receipt_id=receipt_id,
        ledger_recorded=ledger_recorded,
    )


__all__ = [
    "ACCEPT_EVENT_SOURCE",
    "ACCEPT_INITIATING_SOURCE",
    "ACCEPT_MATERIALIZE_WRITE_ACTION",
    "ACCEPT_OPERATION_TYPE",
    "ACCEPTED_AUTHORITY_STATE",
    "AcceptanceReconciliationError",
    "CREATE_ACCEPTED_EVENT",
    "CREATE_DECLINED_EVENT",
    "PROPOSAL_AUTHORITY_STATE",
    "SYNTHESIS_DERIVED_BY",
    "AcceptError",
    "AcceptResult",
    "AcceptanceReceipt",
    "DeclineResult",
    "DecisionToken",
    "DraftNotAcceptedError",
    "DraftNotFoundError",
    "MalformedDraftError",
    "ModifyExistingRequiresAskError",
    "UnresolvableCitationError",
    "accept_draft",
    "decline_draft",
]
