"""Meeting finalization: consolidate a closed session into vault artifacts
(CDLM-08, issue #4388).

Specified by `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/CONSOLIDATE_MEETING_ON_END.md`
and bound by INV-CDLM-5 (derived material never self-promotes), INV-CDLM-6
(user notes never merged into machine output; finalization is a derived
writer under the CDLM-07 guard), and INV-CDLM-9 (a reader can never mistake a
gapped transcript for a complete one).

What happens at finalize time:

1. The session's ledger completeness state is snapshotted into a stable
   identity (`state_sha256` over the admitted `(seq, hash)` set, the missing
   list, and the declared count). Finalization is idempotent per
   `(session_id, state_sha256)`: an unchanged ledger replays the existing
   durable receipt and creates nothing.
2. Three artifacts materialize **create-once** into the Sources zone through
   the governed write seam (`app.knowledge.write_ops.write_note_relative`,
   WriteGuard-gated at the port): the consolidated transcript, the final
   derived analysis (draft-zone standing, full provenance frontmatter —
   promotion to canonical knowledge stays a human act via the trust path),
   and the user-notes artifact (verbatim bytes, human provenance, never
   merged into derived output). Paths carry the state identity prefix, so a
   post-close reconciliation *creates new versions* under the Sources-zone
   re-derivation rule and never rewrites an existing note.
3. Finalization registers its own receipt block through the CDLM-07 guard as
   a derived writer (`heimdal-meeting-finalization` / role `finalization`) —
   its block writes pass the same seam every writer passes, and the guard is
   what makes it structurally unable to touch user-note content beyond
   reading it verbatim out of the registry.
4. The completeness receipt `{session_id, complete|needs_attention,
   missing_seqs, artifact refs, finalized_at}` is durable, and its outbox
   event (`heimdal.meeting.finalized`) commits **before** the receipt row
   that is the finalized acknowledgement — the CDLM-01 ack-ordering family.
5. A late admission after close re-derives and re-finalizes: the new receipt
   carries lineage to the superseded state (old artifacts remain on disk,
   named in the new receipt's `supersedes`).

The vault root is resolved from ``HEIMDAL_MEETING_VAULT_ROOT``; when it is
not configured, finalization reports a named ``skipped`` outcome instead of
guessing a vault — the close itself remains ledger truth, and the skip is
honest and loud.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import yaml

from app.events.schema import make_outbox_event
from app.events.types import HEIMDAL_MEETING_FINALIZED
from app.heimdal import meeting_blocks, meeting_ledger, meeting_projection
from app.heimdal._backend import resolve_heimdal_backend
from app.knowledge.write_ops import create_candidate_note_once
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services import outbox as outbox_service

logger = logging.getLogger(__name__)

_RECEIPT_TABLE = "heimdal_meeting_finalization_receipt"
_MIGRATION_HINT = (
    "heimdal meeting-finalization schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/d0f5b2c7e4a6_heim_meeting_finalization_v0.py."
)

_FINALIZATION_PATH_ENV = "HEIMDAL_MEETING_FINALIZATION_PATH"
_VAULT_ROOT_ENV = "HEIMDAL_MEETING_VAULT_ROOT"
_EVENT_SOURCE = "heimdal.meeting.finalization"
FINALIZATION_WRITE_ACTION = "heimdal.meeting_finalization.write"

# Path-safe charset for the session's directory component. Session ids are
# client-minted opaque strings (CDLM-02); one that is not path-safe is mapped
# to a deterministic digest slug instead of ever reaching path construction —
# no dot-segment or separator a client mints can move an artifact outside the
# Meetings zone.
_SAFE_SESSION_COMPONENT = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _session_path_component(session_id: str) -> str:
    if _SAFE_SESSION_COMPONENT.fullmatch(session_id) and session_id not in {".", ".."} and ".." not in session_id:
        return session_id
    return "sess-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]

# Settings-resolved default per MIMER_CLIENT_CONTRACT §5 — writers must not
# hardcode displayed names beyond the default relative root convention.
MEETINGS_DIR_DEFAULT = "Sources/Meetings"
_MEETINGS_DIR_ENV = "HEIMDAL_MEETINGS_DIR_REL"

FINALIZATION_WRITER = meeting_blocks.WriterIdentity(
    kind=meeting_blocks.WRITER_DERIVED,
    engine="heimdal-meeting-finalization",
    role="finalization",
)


class MeetingFinalizationSchemaMissingError(RuntimeError):
    """Postgres backend selected but the receipt table is absent (fail loud)."""


class MeetingFinalizationError(RuntimeError):
    """Finalization could not complete; nothing was acknowledged as finalized."""


@dataclass(frozen=True)
class FinalizationReceipt:
    """One durable finalization receipt — the finalized acknowledgement."""

    session_id: str
    state_sha256: str
    complete: bool
    missing_seqs: List[int]
    artifact_refs: Dict[str, str]
    supersedes: Optional[str]
    finalized_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def meetings_dir_rel() -> str:
    return (os.environ.get(_MEETINGS_DIR_ENV) or "").strip() or MEETINGS_DIR_DEFAULT


def resolve_vault_root() -> Optional[Path]:
    """Resolve the finalization vault root, or None when unconfigured.

    Unconfigured is a named, honest skip — never a guessed path.
    """
    raw = (os.environ.get(_VAULT_ROOT_ENV) or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise MeetingFinalizationError(
            f"{_VAULT_ROOT_ENV}={raw!r} is not an existing directory; refusing to "
            "materialize meeting artifacts into a guessed vault."
        )
    return root


# ---------------------------------------------------------------------------
# Receipt store (sqlite dev/test lane + migration-owned pg)
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_RECEIPT_TABLE} (
    session_id TEXT NOT NULL,
    state_sha256 TEXT NOT NULL,
    complete INTEGER NOT NULL,
    missing_seqs TEXT NOT NULL DEFAULT '[]',
    artifact_refs TEXT NOT NULL DEFAULT '{{}}',
    supersedes TEXT,
    finalized_at TEXT NOT NULL,
    PRIMARY KEY (session_id, state_sha256)
);
"""

_process_tmp_lock = threading.Lock()
_process_tmp_path: Optional[str] = None


def _sqlite_path() -> str:
    env_path = (os.environ.get(_FINALIZATION_PATH_ENV) or "").strip()
    if env_path:
        return env_path
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is None:
            fd, path = tempfile.mkstemp(
                prefix="heimdal-meeting-finalization-", suffix=".sqlite3"
            )
            os.close(fd)
            _process_tmp_path = path
        return _process_tmp_path


class _SqliteReceiptStore:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._connect() as conn:
            conn.executescript(_SQLITE_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, session_id: str, state_sha256: str) -> Optional[FinalizationReceipt]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, state_sha256, complete, missing_seqs, artifact_refs, "
                f"supersedes, finalized_at FROM {_RECEIPT_TABLE} "
                "WHERE session_id = ? AND state_sha256 = ?",
                (session_id, state_sha256),
            ).fetchone()
        return self._from_row(row) if row else None

    def latest(self, session_id: str) -> Optional[FinalizationReceipt]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, state_sha256, complete, missing_seqs, artifact_refs, "
                f"supersedes, finalized_at FROM {_RECEIPT_TABLE} "
                "WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def insert(self, receipt: FinalizationReceipt) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_RECEIPT_TABLE} "
                "(session_id, state_sha256, complete, missing_seqs, artifact_refs, "
                "supersedes, finalized_at) VALUES (?,?,?,?,?,?,?)",
                (
                    receipt.session_id,
                    receipt.state_sha256,
                    1 if receipt.complete else 0,
                    json.dumps(receipt.missing_seqs),
                    json.dumps(receipt.artifact_refs),
                    receipt.supersedes,
                    _iso(receipt.finalized_at),
                ),
            )
            return cur.rowcount == 1

    @staticmethod
    def _from_row(row: tuple) -> FinalizationReceipt:
        return FinalizationReceipt(
            session_id=row[0],
            state_sha256=row[1],
            complete=bool(row[2]),
            missing_seqs=json.loads(row[3] or "[]"),
            artifact_refs=json.loads(row[4] or "{}"),
            supersedes=row[5],
            finalized_at=_parse_ts(row[6]),
        )


def _pg_connect() -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


_PG_AUTOCREATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_RECEIPT_TABLE} (
    session_id TEXT NOT NULL,
    state_sha256 TEXT NOT NULL,
    complete BOOLEAN NOT NULL,
    missing_seqs JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_refs JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    supersedes TEXT,
    finalized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, state_sha256)
);
"""


class _PgReceiptStore:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            if _schema_autocreate_enabled():
                conn.cursor().execute(_PG_AUTOCREATE_DDL)
            else:
                cur = conn.cursor()
                cur.execute("SELECT to_regclass(%s)", (_RECEIPT_TABLE,))
                row = cur.fetchone()
                if not (row and row[0]):
                    raise MeetingFinalizationSchemaMissingError(
                        f"Missing table '{_RECEIPT_TABLE}'. {_MIGRATION_HINT}"
                    )
        finally:
            conn.close()

    def get(self, session_id: str, state_sha256: str) -> Optional[FinalizationReceipt]:
        return self._one(
            "WHERE session_id = %s AND state_sha256 = %s", (session_id, state_sha256)
        )

    def latest(self, session_id: str) -> Optional[FinalizationReceipt]:
        return self._one(
            "WHERE session_id = %s ORDER BY finalized_at DESC, state_sha256 DESC LIMIT 1",
            (session_id,),
        )

    def _one(self, clause: str, params: tuple) -> Optional[FinalizationReceipt]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, state_sha256, complete, missing_seqs, artifact_refs, "
                f"supersedes, finalized_at FROM {_RECEIPT_TABLE} {clause}",
                params,
            )
            row = cur.fetchone()
            return self._from_row(row) if row else None
        finally:
            conn.close()

    def insert(self, receipt: FinalizationReceipt) -> bool:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_RECEIPT_TABLE} "
                "(session_id, state_sha256, complete, missing_seqs, artifact_refs, "
                "supersedes, finalized_at) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s) "
                "ON CONFLICT (session_id, state_sha256) DO NOTHING",
                (
                    receipt.session_id,
                    receipt.state_sha256,
                    receipt.complete,
                    json.dumps(receipt.missing_seqs),
                    json.dumps(receipt.artifact_refs),
                    receipt.supersedes,
                    receipt.finalized_at,
                ),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    @staticmethod
    def _from_row(row: tuple) -> FinalizationReceipt:
        def _as_obj(value: Any, default: Any) -> Any:
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value) if value else default

        return FinalizationReceipt(
            session_id=row[0],
            state_sha256=row[1],
            complete=bool(row[2]),
            missing_seqs=_as_obj(row[3], []),
            artifact_refs=_as_obj(row[4], {}),
            supersedes=row[5],
            finalized_at=_parse_ts(row[6]),
        )


def _backend() -> "_SqliteReceiptStore | _PgReceiptStore":
    if resolve_heimdal_backend() == "pg":
        return _PgReceiptStore()
    return _SqliteReceiptStore(_sqlite_path())


# ---------------------------------------------------------------------------
# State identity + artifact rendering
# ---------------------------------------------------------------------------


def _state_identity(report: Dict[str, Any], projection: Dict[str, Any]) -> str:
    """Identity of the state a finalization's artifact bytes derive from.

    The ledger set alone is not enough: a failed ASR derivation later healed
    by a resend changes the rendered transcript and analysis without changing
    the ledger, and finalization must supersede rather than replay stale
    "derivation failed" artifacts forever. So the identity covers the ledger
    completeness state AND each segment's derivation outcome.
    """
    derivations = []
    for row in projection["transcript"]:
        kind = row.get("kind")
        if kind == "segment":
            derivations.append(
                (row["seq"], "ok", hashlib.sha256(row["text"].encode("utf-8")).hexdigest())
            )
        elif kind in ("needs_attention", "pending"):
            derivations.append((row["seq"], kind, ""))
    canonical = json.dumps(
        {
            "segments": sorted(
                (seg["seq"], seg["content_sha256"]) for seg in report["segments"]
            ),
            "missing": report["missing"],
            "final_seq_count": report["final_seq_count"],
            "derivations": derivations,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _frontmatter(data: Dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=True, allow_unicode=True) + "---\n"


def _completeness_fields(
    report: Dict[str, Any], state_sha256: str, supersedes: Optional[str]
) -> Dict[str, Any]:
    return {
        "session_id": report["session_id"],
        "completeness": "complete" if report["complete"] else "needs_attention",
        "missing_seqs": report["missing"],
        "finalization_state": state_sha256,
        "supersedes": supersedes,
    }


def _render_transcript(
    projection: Dict[str, Any], state_sha256: str, supersedes: Optional[str]
) -> str:
    front = {
        "artifact_class": "meeting_transcript",
        "zone": "sources",
        "note_class": "create-once",
        **_completeness_fields(projection, state_sha256, supersedes),
        "provenance": {
            "kind": "derived",
            "engine": "app.media.transcribe.run_asr",
            "materialized_by": "heimdal-meeting-finalization",
            "written_at": _iso(_utcnow()),
        },
    }
    lines: List[str] = [f"# Meeting transcript — {projection['session_id']}", ""]
    if not projection["complete"]:
        lines.append(
            f"> **Needs attention:** missing sequence numbers {projection['missing']} — "
            "this transcript has gaps and must not be read as complete."
        )
        lines.append("")
    for row in projection["transcript"]:
        if row["kind"] == "segment":
            lines.append(f"**[{row['seq']}]** {row['text']}")
        elif row["kind"] == "gap":
            lines.append(f"**[{row['seq']}]** _[missing segment]_")
        elif row["kind"] == "gap_run":
            lines.append(
                f"**[{row['from']}–{row['to']}]** _[{row['count']} missing segments]_"
            )
        elif row["kind"] == "needs_attention":
            lines.append(f"**[{row['seq']}]** _[derivation failed: {row['error']}]_")
        else:
            lines.append(f"**[{row['seq']}]** _[not yet derived]_")
        lines.append("")
    return _frontmatter(front) + "\n".join(lines).rstrip() + "\n"


def _render_analysis(
    projection: Dict[str, Any], state_sha256: str, supersedes: Optional[str]
) -> str:
    analysis = projection["analysis"]
    front = {
        "artifact_class": "meeting_analysis",
        "zone": "sources",
        "note_class": "create-once",
        "standing": "draft",
        "promotion": "human-only (trust path); this note never self-promotes",
        **_completeness_fields(projection, state_sha256, supersedes),
        "template_id": analysis["template_id"],
        "analysis_revision": analysis["revision"],
        "derived_from": analysis["derived_from"],
        "provenance": {
            "kind": "derived",
            **analysis["engine"],
            "materialized_by": "heimdal-meeting-finalization",
            "written_at": _iso(_utcnow()),
        },
    }
    lines: List[str] = [f"# Meeting analysis — {projection['session_id']}", ""]
    if not projection["complete"]:
        lines.append(
            f"> **Needs attention:** derived over an incomplete segment set; missing "
            f"{projection['missing']}."
        )
        lines.append("")
    for block in analysis["blocks"]:
        title = block["block_type"].replace("_", " ").title()
        lines.append(f"## {title}")
        content = block["content"]
        if isinstance(content, list):
            lines.extend(f"- {item}" for item in content) if content else lines.append("_none_")
        else:
            lines.append(str(content) if content else "_none_")
        lines.append("")
    return _frontmatter(front) + "\n".join(lines).rstrip() + "\n"


def _render_user_notes(
    projection: Dict[str, Any],
    notes: List[meeting_blocks.MeetingBlock],
    state_sha256: str,
    supersedes: Optional[str],
) -> str:
    front = {
        "artifact_class": "meeting_user_notes",
        "zone": "sources",
        "note_class": "create-once",
        **_completeness_fields(projection, state_sha256, supersedes),
        "provenance": {
            "kind": "human",
            "authored_by": "user (structural editor identity per block history)",
            "materialized_by": "heimdal-meeting-finalization",
            "written_at": _iso(_utcnow()),
        },
        "note_blocks": [
            {
                "block_id": note.block_id,
                "revision": note.revision,
                "editor_identity": (note.provenance or {}).get("editor_identity", ""),
            }
            for note in notes
        ],
    }
    lines: List[str] = [f"# Meeting notes (human-authored) — {projection['session_id']}", ""]
    for note in notes:
        # Verbatim bytes, fenced by nothing that could alter them: the content
        # is emitted exactly as stored, one block after another in position
        # order, never interleaved with derived text.
        lines.append(f"<!-- user_note {note.block_id} revision {note.revision} -->")
        lines.append(note.content)
        lines.append("")
    # No rstrip: the last note's trailing whitespace and blank lines are part
    # of its verbatim bytes. Each block is bounded by its marker comment and a
    # single separating newline, never altered.
    return _frontmatter(front) + "\n".join(lines)


# ---------------------------------------------------------------------------
# Event emission (ack-ordering family)
# ---------------------------------------------------------------------------


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _emit_finalized_event(payload: Dict[str, Any], *, trace_id: str) -> bool:
    evt = make_outbox_event(
        event=HEIMDAL_MEETING_FINALIZED,
        source=_EVENT_SOURCE,
        payload=payload,
        trace_id=trace_id,
    )
    emitted = False
    try:
        emitted = outbox_service.append_jsonl_outbox_event(
            _resolve_outbox_path(), evt, default_source=_EVENT_SOURCE
        )
    except Exception as exc:
        logger.warning("meeting finalized event jsonl write failed: %s", exc)
    # Ask the outbox policy whether a self-owned write will actually connect,
    # instead of re-deriving that from STORE_BACKEND/DATABASE_URL here (#4214
    # D1). The local predicate was narrower than the connection's own resolver,
    # and since the memory-mode skip branch landed a skipped write returns
    # normally — which would make the `emitted = True` below report a finalized
    # acknowledgement for an event no sink took.
    if not outbox_service.self_owned_write_would_skip():
        outbox_evt = outbox_service.coerce_outbox_event(evt, default_source=_EVENT_SOURCE)
        if outbox_evt is not None:
            try:
                outbox_service.write_outbox_event(
                    outbox_evt,
                    idempotency_key=outbox_service.derive_idempotency_key(
                        outbox_evt.event,
                        str(payload.get("session_id", "")),
                        str(payload.get("finalization_state", "")),
                    ),
                )
                emitted = True
            except Exception as exc:
                logger.warning("meeting finalized event db outbox write failed: %s", exc)
    return emitted


# ---------------------------------------------------------------------------
# The finalization
# ---------------------------------------------------------------------------


def finalize_session(session_id: str, *, trace_id: str = "") -> Dict[str, Any]:
    """Finalize one closed session; idempotent per ledger completeness state.

    Returns a status dict: ``{"status": "finalized"|"replayed"|"skipped",
    "receipt": {...}}``. Raises :class:`MeetingFinalizationError` when the
    session is unknown or not closed, when the vault root is misconfigured,
    or when the event commit fails (nothing acknowledged as finalized).
    """
    session = meeting_ledger.get_meeting_session(session_id)
    if session is None:
        raise MeetingFinalizationError(f"session {session_id!r} is not in the ledger")
    if not session.closed:
        raise MeetingFinalizationError(
            f"session {session_id!r} is not closed; finalization runs on close"
        )

    vault_root = resolve_vault_root()
    if vault_root is None:
        logger.warning(
            "meeting finalization skipped session=%s: %s is not configured",
            session_id,
            _VAULT_ROOT_ENV,
        )
        return {
            "status": "skipped",
            "reason": "vault_root_unconfigured",
            "session_id": session_id,
        }

    projection = meeting_projection.build_projection(session_id)
    report = meeting_ledger.build_gap_report(session_id)
    state_sha256 = _state_identity(report, projection)

    store = _backend()
    existing = store.get(session_id, state_sha256)
    if existing is not None:
        return {"status": "replayed", "receipt": _receipt_dict(existing)}

    previous = store.latest(session_id)
    supersedes = previous.state_sha256 if previous else None

    short = state_sha256[:8]
    base = f"{meetings_dir_rel()}/{_session_path_component(session_id)}"
    artifact_refs = {
        "transcript": f"{base}/transcript-{short}.md",
        "analysis": f"{base}/analysis-{short}.md",
        "user_notes": f"{base}/user-notes-{short}.md",
    }

    notes = [
        block
        for block in meeting_blocks.blocks_for_session(session_id)
        if block.block_type == meeting_blocks.TYPE_USER_NOTE and not block.retired
    ]

    contents = {
        "transcript": _render_transcript(projection, state_sha256, supersedes),
        "analysis": _render_analysis(projection, state_sha256, supersedes),
        "user_notes": _render_user_notes(projection, notes, state_sha256, supersedes),
    }

    # Create-once, atomically: `create_candidate_note_once` opens the target
    # with O_EXCL, so an already-existing artifact at the deterministic path
    # for this exact state is preserved untouched (this finalization's durable
    # replay result) even under concurrent triggers — never rewritten, never
    # raced. Its path validation also rejects any dot-segment outright,
    # defense in depth under the sanitized session component above.
    for name, rel_path in artifact_refs.items():
        result = create_candidate_note_once(
            rel_path,
            contents[name],
            vault_root=vault_root,
            action=FINALIZATION_WRITE_ACTION,
        )
        if result not in ("written", "already_exists"):
            raise MeetingFinalizationError(
                f"artifact {name} could not be materialized at {rel_path!r}: {result!r}"
            )

    # Finalization's own block write goes through the CDLM-07 guard as the
    # derived finalization writer — the same seam that structurally refuses it
    # any user_note mutation.
    guard_outcome = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=FINALIZATION_WRITER,
        action=meeting_blocks.ACTION_CREATE,
        block_id=f"{session_id}:finalization:{short}",
        block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
        content=json.dumps(
            {"state": state_sha256, "artifact_refs": artifact_refs}, sort_keys=True
        ),
        position=2_000_000,
        provenance_extra={"finalization_state": state_sha256},
    )
    if not guard_outcome.allowed:
        raise MeetingFinalizationError(
            f"finalization block registration refused: {guard_outcome.reason}"
        )

    receipt = FinalizationReceipt(
        session_id=session_id,
        state_sha256=state_sha256,
        complete=bool(report["complete"]),
        missing_seqs=list(report["missing"]),
        artifact_refs=artifact_refs,
        supersedes=supersedes,
        finalized_at=_utcnow(),
    )

    # Ack ordering: the outbox event commits BEFORE the receipt row that is
    # the finalized acknowledgement. A failed event commit acknowledges
    # nothing; artifacts already on disk are this state's create-once replay
    # target for the retry.
    if not _emit_finalized_event(
        {
            "session_id": session_id,
            "finalization_state": state_sha256,
            "complete": receipt.complete,
            "missing_seqs": receipt.missing_seqs,
            "artifact_refs": artifact_refs,
            "supersedes": supersedes,
        },
        trace_id=trace_id,
    ):
        raise MeetingFinalizationError(
            "the finalized event could not be committed; the session is NOT "
            "acknowledged as finalized. Re-trigger — finalization is idempotent."
        )

    if not store.insert(receipt):
        stored = store.get(session_id, state_sha256)
        if stored is not None:
            return {"status": "replayed", "receipt": _receipt_dict(stored)}
        raise MeetingFinalizationError(
            "the finalization receipt could not be persisted; nothing acknowledged."
        )
    return {"status": "finalized", "receipt": _receipt_dict(receipt)}


def maybe_refinalize(session_id: str, *, trace_id: str = "") -> None:
    """Post-close reconciliation trigger: re-finalize after a late admission.

    Exception-isolated — called from the admission path, which must never fail
    on finalization problems; the close-flow trigger uses
    :func:`finalize_session` directly and reports loudly.
    """
    try:
        session = meeting_ledger.get_meeting_session(session_id)
        if session is None or not session.closed:
            return
        if _backend().latest(session_id) is None:
            # Never finalized (e.g. vault unconfigured at close time) — the
            # close-flow owns first finalization; reconciliation only
            # supersedes an existing one.
            return
        finalize_session(session_id, trace_id=trace_id)
    except Exception as exc:
        logger.error(
            "meeting re-finalization failed session=%s: %s", session_id, exc
        )


def latest_receipt(session_id: str) -> Optional[Dict[str, Any]]:
    receipt = _backend().latest(session_id)
    return _receipt_dict(receipt) if receipt else None


def _receipt_dict(receipt: FinalizationReceipt) -> Dict[str, Any]:
    return {
        "session_id": receipt.session_id,
        "finalization_state": receipt.state_sha256,
        "completeness": "complete" if receipt.complete else "needs_attention",
        "missing_seqs": receipt.missing_seqs,
        "artifact_refs": receipt.artifact_refs,
        "supersedes": receipt.supersedes,
        "finalized_at": _iso(receipt.finalized_at),
    }


__all__ = [
    "FINALIZATION_WRITER",
    "MEETINGS_DIR_DEFAULT",
    "FinalizationReceipt",
    "MeetingFinalizationError",
    "MeetingFinalizationSchemaMissingError",
    "finalize_session",
    "latest_receipt",
    "maybe_refinalize",
    "meetings_dir_rel",
    "resolve_vault_root",
]
