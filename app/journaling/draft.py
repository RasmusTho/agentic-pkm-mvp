"""Stage provenance-separated conversational journal proposals (JRNL-03).

The only durable effect in this module is an atomic write beneath the vault's
system ``drafts/journal`` directory.  It never writes or edits the canonical
daily journal path.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

from app.activation.gate import ActivationPosture
from app.activation.journal_draft import (
    JOURNAL_DRAFT_CAPABILITY_ID,
    evaluate_journal_draft_activation,
)
from app.journaling.day_context import (
    DayContextBundle,
    DayContextItem,
    assemble_day_context,
)
from app.knowledge_compilation.proposal_builders import (
    ProposalContext,
    build_compilation_draft,
)
from app.knowledge_compilation.runtime_artifacts import (
    CompilationDraft,
    ContextAuthorityLimits,
    SourceRef,
)
from app.reasoning.multi import run_multi_note_reasoning
from app.reasoning.schema import ReasoningOutput
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


JOURNAL_DRAFT_WRITE_ACTION = "journal.draft.write"
JOURNAL_DRAFTS_SUBDIR = Path("drafts") / "journal"
CANONICAL_JOURNAL_SUBDIR = Path("1_Calendar") / "Daily"
DEFAULT_STALENESS_DAYS = 14


class UnresolvableJournalCitationError(ValueError):
    """A transcript or day-context provenance reference did not resolve."""


class JournalDraftBlockedError(RuntimeError):
    """JRNL-03's own activation record refused the proposal run."""


class ReasoningFunction(Protocol):
    def __call__(
        self, object_ids: Sequence[str], *, trace_id: str | None = None
    ) -> ReasoningOutput: ...


@dataclass(frozen=True)
class _ResolvedSession:
    session_id: str
    relative_path: str
    owner_turns: tuple[str, ...]

    @property
    def source_id(self) -> str:
        return f"session:{self.session_id}"


@dataclass(frozen=True)
class JournalDraftResult:
    path: str
    is_addendum: bool
    compilation_draft: CompilationDraft
    activation_receipt_id: str


def draft_journal_entry(
    *,
    vault_context: VaultContext,
    for_date: date,
    session_id: str,
    day_context: DayContextBundle | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    activation_posture: ActivationPosture | None = None,
    reasoning_fn: ReasoningFunction = run_multi_note_reasoning,
    now: datetime | None = None,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
) -> JournalDraftResult:
    """Build and atomically stage one proposal for ``for_date``.

    Before acceptance, every same-day call rewrites the same candidate path
    while retaining every contributing session.  Once a canonical daily note
    exists, the target switches to a distinct addendum candidate; the
    canonical note is only observed and is never opened for writing here.
    """

    vault_root = _vault_root(vault_context)
    if not session_id.strip():
        raise ValueError("draft_journal_entry requires a non-empty session_id")
    if staleness_days <= 0:
        raise ValueError("staleness_days must be positive")

    bundle = day_context or assemble_day_context(
        vault_context=vault_context, for_date=for_date
    )
    if bundle.for_date != for_date:
        raise ValueError("day_context date does not match the requested journal date")

    accepted_path = vault_root / CANONICAL_JOURNAL_SUBDIR / f"{for_date.isoformat()}.md"
    is_addendum = accepted_path.exists()
    draft_path = _draft_path(vault_root, for_date, is_addendum=is_addendum)
    existing_frontmatter = _load_existing_draft_frontmatter(draft_path)

    previous_session_ids = _session_ids(existing_frontmatter.get("sources"))
    all_session_ids = _deduplicate((*previous_session_ids, session_id.strip()))
    sessions = tuple(
        _resolve_session(vault_root, prior_session_id)
        for prior_session_id in all_session_ids
    )
    context_items = tuple(_iter_context_items(bundle))

    _validate_session_citations(vault_root, sessions)
    _validate_context_citations(vault_root, context_items)
    source_ids = tuple(session.source_id for session in sessions) + tuple(
        item.provenance_ref for item in context_items
    )
    activation = evaluate_journal_draft_activation(
        source_ids, posture=activation_posture, now=now
    )
    if not activation.activatable:
        reasons = ", ".join(activation.blocked_reasons) or "unknown"
        raise JournalDraftBlockedError(f"journal draft activation blocked: {reasons}")

    body = _build_body(
        for_date=for_date,
        sessions=sessions,
        context_items=context_items,
        is_addendum=is_addendum,
    )
    source_refs = tuple(
        SourceRef(
            artifact_id=session.source_id,
            note_path=session.relative_path,
            role="conversation",
            review_state="reviewed",
        )
        for session in sessions
    ) + tuple(
        SourceRef(
            artifact_id=item.provenance_ref,
            note_path=_reference_path(item.provenance_ref),
            role="system_context",
            review_state="reviewed",
        )
        for item in context_items
    )
    compilation = build_compilation_draft(
        ProposalContext(
            source_refs=source_refs,
            authority_limits=ContextAuthorityLimits(
                may_inform=True, may_propose=True
            ),
            content=body,
            generated_by=JOURNAL_DRAFT_CAPABILITY_ID,
            trace_ref=activation.receipt.receipt_id,
        ),
        title=(
            f"Journal addendum candidate {for_date.isoformat()}"
            if is_addendum
            else f"Journal draft {for_date.isoformat()}"
        ),
    )
    existing_uuid = str(existing_frontmatter.get("uuid") or "").strip()
    if existing_uuid:
        compilation = compilation.model_copy(update={"artifact_id": existing_uuid})

    cognition = _run_cognition(reasoning_fn, source_ids, activation.receipt.receipt_id)
    checked_at = now or datetime.now(timezone.utc)
    created = str(existing_frontmatter.get("created") or _iso(checked_at))
    frontmatter: dict[str, object] = {
        "uuid": compilation.artifact_id,
        "kind": "journal-draft",
        "journal_candidate_type": "addendum" if is_addendum else "primary",
        "for_date": for_date.isoformat(),
        "derived_by": "conversation",
        "authority_state": "proposal",
        "proposed_by": {
            "capability": JOURNAL_DRAFT_CAPABILITY_ID,
            "cognition": cognition,
        },
        "sources": list(source_ids),
        "activation_receipt_id": activation.receipt.receipt_id,
        "created": created,
        "updated": _iso(checked_at),
        "expires": _iso(checked_at + timedelta(days=staleness_days)),
    }
    note_text = dump_frontmatter(frontmatter, compilation.body or "") + _review_actions(
        is_addendum=is_addendum
    )

    # Re-resolve immediately before the guarded mutation so a source removed
    # during cognition cannot be laundered into the staged proposal.
    _validate_session_citations(vault_root, sessions)
    _validate_context_citations(vault_root, context_items)

    # Production mutation seam: the guard is immediately before the first
    # possible filesystem mutation (directory creation).  The same-directory
    # staged file plus os.replace makes both create and redraft atomic.
    write_guard.assert_writes_allowed(JOURNAL_DRAFT_WRITE_ACTION)
    _atomic_write(draft_path, note_text)

    return JournalDraftResult(
        path=draft_path.relative_to(vault_root).as_posix(),
        is_addendum=is_addendum,
        compilation_draft=compilation,
        activation_receipt_id=activation.receipt.receipt_id,
    )


def _vault_root(context: VaultContext) -> Path:
    if context.status != "selected" or not context.active_vault_path:
        raise ValueError("draft_journal_entry requires a selected active vault")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("draft_journal_entry requires an existing active vault")
    return root


def _draft_path(vault_root: Path, for_date: date, *, is_addendum: bool) -> Path:
    system_dir = Path(get_vault_system_dir_rel(vault_root))
    suffix = "-addendum" if is_addendum else ""
    path = (
        vault_root
        / system_dir
        / JOURNAL_DRAFTS_SUBDIR
        / f"{for_date.isoformat()}{suffix}.md"
    ).resolve()
    try:
        path.relative_to(vault_root)
    except ValueError as exc:
        raise ValueError("journal draft staging path escapes the active vault") from exc
    return path


def _load_existing_draft_frontmatter(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
    if (
        frontmatter.get("kind") != "journal-draft"
        or frontmatter.get("authority_state") != "proposal"
        or frontmatter.get("derived_by") != "conversation"
    ):
        raise ValueError(f"existing journal draft at {path} has an incompatible contract")
    return frontmatter


def _session_ids(raw_sources: object) -> tuple[str, ...]:
    if not isinstance(raw_sources, list):
        return ()
    return tuple(
        source.removeprefix("session:")
        for source in raw_sources
        if isinstance(source, str) and source.startswith("session:")
    )


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _resolve_session(vault_root: Path, session_id: str) -> _ResolvedSession:
    matches: list[tuple[Path, str]] = []
    for path in sorted((vault_root / ".chats").glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
        if str(frontmatter.get("session_id") or "").strip() == session_id:
            matches.append((path, body))
    if len(matches) != 1:
        raise UnresolvableJournalCitationError(
            f"session:{session_id} resolved to {len(matches)} transcript files"
        )
    path, body = matches[0]
    owner_turns = tuple(
        match.group(1).strip()
        for match in re.finditer(
            r"^\*\*Owner:\*\*\s*(.+?)(?=\n\n|\Z)", body, flags=re.MULTILINE | re.DOTALL
        )
        if match.group(1).strip()
    )
    return _ResolvedSession(
        session_id=session_id,
        relative_path=path.relative_to(vault_root).as_posix(),
        owner_turns=owner_turns,
    )


def _iter_context_items(bundle: DayContextBundle) -> Iterable[DayContextItem]:
    for source_name in sorted(bundle.sections):
        yield from bundle.sections[source_name].items


def _validate_session_citations(
    vault_root: Path, sessions: tuple[_ResolvedSession, ...]
) -> None:
    if not sessions:
        raise UnresolvableJournalCitationError(
            "a journal draft requires at least one resolvable conversation session"
        )
    for session in sessions:
        path = (vault_root / session.relative_path).resolve()
        try:
            path.relative_to(vault_root)
        except ValueError as exc:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} escapes the active vault"
            ) from exc
        if not path.is_file():
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} transcript no longer resolves"
            )
        frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        if str(frontmatter.get("session_id") or "").strip() != session.session_id:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} transcript identity changed"
            )


def _validate_context_citations(
    vault_root: Path, items: tuple[DayContextItem, ...]
) -> None:
    for item in items:
        reference = item.provenance_ref.strip()
        relative_path = _reference_path(reference)
        path = (vault_root / relative_path).resolve()
        try:
            path.relative_to(vault_root)
        except ValueError as exc:
            raise UnresolvableJournalCitationError(
                f"citation escapes the active vault: {reference}"
            ) from exc
        if not path.is_file():
            raise UnresolvableJournalCitationError(
                f"citation does not resolve: {reference}"
            )
        if "#" in reference:
            _validate_jsonl_fragment(path, reference.split("#", 1)[1], reference)


def _reference_path(reference: str) -> str:
    relative = reference.split("#", 1)[0]
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise UnresolvableJournalCitationError(
            f"citation must be vault-relative: {reference}"
        )
    return path.as_posix()


def _validate_jsonl_fragment(path: Path, fragment: str, reference: str) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        candidate = (
            f"{record.get('object_id')}:{record.get('key')}:{record.get('created_at')}"
        )
        if candidate == fragment:
            return
    raise UnresolvableJournalCitationError(
        f"citation fragment does not resolve: {reference}"
    )


def _build_body(
    *,
    for_date: date,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    is_addendum: bool,
) -> str:
    title = "Addendum candidate" if is_addendum else "Journal draft"
    lines = [f"# {title} — {for_date.isoformat()}", "", "## My reflection", ""]
    conversation_footnotes: list[str] = []
    conversation_index = 0
    for session in sessions:
        turns = session.owner_turns or (
            "I opened a reflection conversation and stopped before adding my own words.",
        )
        for turn in turns:
            conversation_index += 1
            lines.append(f"I reflected: {turn} [^conversation-{conversation_index}]")
            lines.append("")
            conversation_footnotes.append(
                f"[^conversation-{conversation_index}]: {session.source_id} "
                f"(`{session.relative_path}`); owner's conversation words."
            )

    lines.extend(["## Day context folded into the draft", ""])
    context_footnotes: list[str] = []
    if not context_items:
        lines.extend(["No additional day-context facts were available.", ""])
    for index, item in enumerate(context_items, start=1):
        lines.append(
            "I also had this context available: "
            f"{_describe_context_item(item)}. [^context-{index}]"
        )
        lines.append("")
        context_footnotes.append(
            f"[^context-{index}]: {item.provenance_ref}; system-derived day context, "
            "not an owner utterance."
        )

    lines.extend(["## Provenance", ""])
    lines.extend(conversation_footnotes)
    lines.extend(context_footnotes)
    return "\n".join(lines).rstrip() + "\n"


def _describe_context_item(item: DayContextItem) -> str:
    for key in (
        "summary",
        "key",
        "content_identity",
        "target_ref",
        "commitment_id",
        "object_id",
    ):
        value = item.content.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return item.provenance_ref


def _run_cognition(
    reasoning_fn: ReasoningFunction, source_ids: tuple[str, ...], trace_id: str
) -> dict[str, object]:
    try:
        output = reasoning_fn(source_ids, trace_id=trace_id)
        claims = getattr(output, "claims", ())
        inferences = getattr(output, "inferences", ())
        return {
            "engine": "run_multi_note_reasoning",
            "claims": len(claims),
            "inferences": len(inferences),
            "degraded": False,
        }
    except Exception:
        return {
            "engine": "run_multi_note_reasoning",
            "claims": 0,
            "inferences": 0,
            "degraded": True,
        }


def _review_actions(*, is_addendum: bool) -> str:
    accept_label = (
        "Accept and append this addendum to today's journal"
        if is_addendum
        else "Accept this draft as today's journal entry"
    )
    return (
        "\n%% AI:Start %%\n"
        "## AI-åtgärder\n\n"
        f"- [ ] {accept_label}\n"
        "- [ ] Dismiss this journal candidate\n"
        "%% AI:End %%\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "JOURNAL_DRAFT_WRITE_ACTION",
    "JournalDraftBlockedError",
    "JournalDraftResult",
    "UnresolvableJournalCitationError",
    "draft_journal_entry",
]
