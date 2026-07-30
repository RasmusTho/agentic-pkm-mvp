"""Live meeting transcript + default analysis projections (CDLM-06, issue #4386).

Specified by
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md`
and bound by INV-CDLM-5 (projections, never canonical truth), INV-CDLM-8 (no
person attribution anywhere), and INV-CDLM-9 (gaps legible) from that
directory's `README.md`.

What this module owns:

- **Per-segment ASR derivation** through the one shared engine seam
  (`app.media.transcribe.run_asr` — the one-Whisper rule, ADR-0049 §3; reached
  via the module attribute so tests stub the real seam, never a stand-in).
  Each segment derives **exactly once per content hash**: the derivation row is
  durable and keyed by `content_sha256`, so idempotent replays and hub
  restarts re-derive nothing (INV-CDLM-3). An ASR failure is recorded as a
  per-segment `failed` derivation — fail-loud, surfaced as needs-attention in
  the projection, isolated from every other segment.
- **Transcript projection**, assembled from the CDLM-02 ledger plus the
  derivation rows: ordered by `session_seq`, per-segment text/timing, explicit
  gap markers for missing sequences (never elided). Third-party speech follows
  ADR-0060's withheld default; there is **no speaker naming of any kind** —
  rows carry device/source provenance only.
- **Analysis projection** under the generic default template
  (`generic-default@1`): summary, themes, provisional decisions, open
  questions, action candidates — emitted as `derived_projection` blocks with
  `{revision, derived_from, template_id, engine}` provenance. Derivation is
  deterministic in its inputs, so re-derivation over an identical admitted set
  is convergent; the result is cached by input-set identity, and an identical
  set never mints a new revision. A late admission changes the input set and
  therefore derives a new revision; prior revisions stay addressable up to a
  config-capped retention bound.
- **Template precedence seam** (`resolve_template`): explicit user selection >
  explicitly permitted metadata mapping (no permission flag ships in this
  slice, so the branch exists and resolves only when a caller passes one) >
  generic default. `generic-default@1` is the only shipped template.

Storage follows the CDLM-02 ledger pattern exactly (`app.heimdal.meeting_ledger`):
migration-owned Postgres tables (`a7c2e9f4b1d3` → this slice's `b8d3f0a5c2e4`)
with fail-loud preflight, and a file-backed SQLite lane for dev/test so the
restart criterion is proven against real durable storage. Projection state is
derived and rebuildable (Machine Mirror class) — it is never semantic
authority, which is why every block carries its revision and derivation
provenance instead of pretending stability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.heimdal import meeting_blocks, meeting_ledger
from app.heimdal._backend import resolve_heimdal_backend
from app.media import transcribe as transcribe_module

logger = logging.getLogger(__name__)

_ANALYSIS_WRITER = meeting_blocks.WriterIdentity(
    kind=meeting_blocks.WRITER_DERIVED,
    engine=str("heimdal-meeting-analysis"),
    role="analysis",
)
_ASR_WRITER = meeting_blocks.WriterIdentity(
    kind=meeting_blocks.WRITER_DERIVED,
    engine="app.media.transcribe.run_asr",
    role="asr",
)

_DERIVATION_TABLE = "heimdal_meeting_asr_derivation"
_REVISION_TABLE = "heimdal_meeting_analysis_revision"

_MIGRATION_HINT = (
    "heimdal meeting-projection schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/b8d3f0a5c2e4_heim_meeting_projection_v0.py."
)

_PROJECTION_PATH_ENV = "HEIMDAL_MEETING_PROJECTION_PATH"

# The only shipped template (rich templates are later, gated work).
GENERIC_DEFAULT_TEMPLATE = "generic-default@1"
SHIPPED_TEMPLATES: tuple[str, ...] = (GENERIC_DEFAULT_TEMPLATE,)

# Deterministic analysis engine identity, stamped into block provenance so a
# rendered block can always answer "what derived you, from what, under which
# template". Bump the version whenever the derivation functions change shape.
ANALYSIS_ENGINE = {"engine": "heimdal-meeting-analysis", "version": "v1"}

# Prior analysis revisions stay addressable until finalization, bounded so the
# projection state cannot grow without limit on a long meeting.
DEFAULT_REVISION_RETENTION = 20
_REVISION_RETENTION_ENV = "HEIMDAL_MEETING_REVISION_RETENTION"

# Runs of missing sequences longer than this collapse into one explicit
# `gap_run` marker in the transcript (from/to/count), bounding the poll
# payload for undercounted or sparse sessions.
_GAP_RUN_COLLAPSE_THRESHOLD = 25

DERIVATION_OK = "ok"
DERIVATION_FAILED = "failed"


class MeetingProjectionSchemaMissingError(RuntimeError):
    """Postgres backend selected but the projection tables are absent (fail loud)."""


class MeetingProjectionPersistenceError(RuntimeError):
    """A projection write or read-back could not be completed durably."""


@dataclass(frozen=True)
class AsrDerivation:
    """One durable per-content-hash ASR derivation outcome."""

    content_sha256: str
    status: str
    text: str
    segments: List[Dict[str, Any]]
    language: str
    error: str
    engine: Dict[str, Any]
    derived_at: datetime


@dataclass(frozen=True)
class AnalysisRevision:
    """One durable analysis revision over a specific admitted input set."""

    session_id: str
    revision: int
    input_set_sha256: str
    derived_from: List[Dict[str, Any]]
    template_id: str
    blocks: List[Dict[str, Any]]
    engine: Dict[str, Any]
    derived_at: datetime


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


def revision_retention() -> int:
    raw = (os.environ.get(_REVISION_RETENTION_ENV) or "").strip()
    if not raw:
        return DEFAULT_REVISION_RETENTION
    try:
        value = int(raw)
    except ValueError as exc:
        raise MeetingProjectionPersistenceError(
            f"{_REVISION_RETENTION_ENV}={raw!r} is not a valid revision retention bound."
        ) from exc
    if value < 1:
        raise MeetingProjectionPersistenceError(
            f"{_REVISION_RETENTION_ENV}={raw!r} must keep at least the newest revision."
        )
    return value


# ---------------------------------------------------------------------------
# Template precedence seam
# ---------------------------------------------------------------------------


def resolve_template(
    template_selection: Optional[Dict[str, Any]],
    *,
    permitted_metadata_template: Optional[str] = None,
    metadata_mapping_permitted: bool = False,
) -> Dict[str, str]:
    """Resolve the session's analysis template with the fixed precedence.

    Explicit user selection > explicitly permitted metadata mapping > generic
    default. The metadata branch resolves only when the caller passes an
    explicit permission flag — no such permission flag ships in this slice, so
    production calls always fall through it, but the seam is real and tested
    rather than re-derived later.

    A user selection naming an unshipped template resolves to the generic
    default with the fallback recorded, so the projection never renders under
    a template identity that does not exist.
    """
    selection = template_selection or {}
    user_choice = selection.get("template_id")
    if isinstance(user_choice, str) and user_choice.strip():
        wanted = user_choice.strip()
        if wanted in SHIPPED_TEMPLATES:
            return {"template_id": wanted, "source": "user_selection"}
        return {
            "template_id": GENERIC_DEFAULT_TEMPLATE,
            "source": "default",
            "fallback_reason": f"unshipped template {wanted!r}",
        }
    if metadata_mapping_permitted and isinstance(permitted_metadata_template, str):
        wanted = permitted_metadata_template.strip()
        if wanted in SHIPPED_TEMPLATES:
            return {"template_id": wanted, "source": "permitted_metadata"}
    return {"template_id": GENERIC_DEFAULT_TEMPLATE, "source": "default"}


# ---------------------------------------------------------------------------
# Deterministic generic-default analysis derivation
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']{4,}")
_STOPWORDS = frozenset(
    "this that with from have will would could should about there their which "
    "were what when then them they been being into over under more some just "
    "like also very much your ours mine".split()
)
_DECISION_MARKERS = ("decide", "decision", "agreed", "we will go with", "settled on")
_ACTION_MARKERS = ("will ", "need to", "needs to", "todo", "to do", "action", "follow up")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _derive_analysis_blocks(transcript_text: str) -> List[Dict[str, Any]]:
    """Derive the five generic-default block payloads, deterministically.

    Pure function of the transcript text: same admitted set → same transcript
    text → block-level equality, which is what makes re-derivation convergent
    (the AC's block-level equality is a consequence, not a cache artifact).
    No LLM is involved in this slice, so determinism is structural.
    """
    sentences = _sentences(transcript_text)
    summary = " ".join(sentences[:3])

    counts: Dict[str, int] = {}
    for word in _WORD.findall(transcript_text.lower()):
        if word not in _STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    themes = [
        word
        for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        if counts[word] > 1
    ]

    decisions = [
        s for s in sentences if any(marker in s.lower() for marker in _DECISION_MARKERS)
    ]
    questions = [s for s in sentences if s.endswith("?")]
    actions = [
        s
        for s in sentences
        if any(marker in s.lower() for marker in _ACTION_MARKERS) and s not in decisions
    ]

    return [
        {"block_type": "summary", "content": summary},
        {"block_type": "themes", "content": themes},
        {"block_type": "provisional_decisions", "content": decisions},
        {"block_type": "open_questions", "content": questions},
        {"block_type": "action_candidates", "content": actions},
    ]


def _input_set_identity(derived_from: List[Dict[str, Any]]) -> str:
    canonical = "\n".join(
        f"{item['seq']}:{item['content_sha256']}"
        for item in sorted(derived_from, key=lambda item: item["seq"])
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQLite backend (dev/test lane — file-backed so restart is honestly testable)
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_DERIVATION_TABLE} (
    content_sha256 TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    segments TEXT NOT NULL DEFAULT '[]',
    language TEXT NOT NULL DEFAULT 'unknown',
    error TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT '{{}}',
    derived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {_REVISION_TABLE} (
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    input_set_sha256 TEXT NOT NULL,
    derived_from TEXT NOT NULL,
    template_id TEXT NOT NULL,
    blocks TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT '{{}}',
    derived_at TEXT NOT NULL,
    PRIMARY KEY (session_id, revision)
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_analysis_revision_set_idx
    ON {_REVISION_TABLE} (session_id, input_set_sha256);
"""

_process_tmp_lock = threading.Lock()
_process_tmp_path: Optional[str] = None


def _sqlite_path() -> str:
    env_path = (os.environ.get(_PROJECTION_PATH_ENV) or "").strip()
    if env_path:
        return env_path
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is None:
            fd, path = tempfile.mkstemp(
                prefix="heimdal-meeting-projection-", suffix=".sqlite3"
            )
            os.close(fd)
            _process_tmp_path = path
        return _process_tmp_path


def reset_process_meeting_projection() -> None:
    """Test-only reset for the *default* (env-unset) per-process projection file."""
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is not None:
            try:
                Path(_process_tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            _process_tmp_path = None


class _SqliteProjectionStore:
    """File-backed projection store; the file is the state (restart honesty)."""

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

    def get_derivation(self, content_sha256: str) -> Optional[AsrDerivation]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT content_sha256, status, text, segments, language, error, engine, "
                f"derived_at FROM {_DERIVATION_TABLE} WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
        return self._derivation_from_row(row) if row else None

    def insert_derivation(self, derivation: AsrDerivation) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_DERIVATION_TABLE} "
                "(content_sha256, status, text, segments, language, error, engine, derived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    derivation.content_sha256,
                    derivation.status,
                    derivation.text,
                    json.dumps(derivation.segments),
                    derivation.language,
                    derivation.error,
                    json.dumps(derivation.engine),
                    _iso(derivation.derived_at),
                ),
            )
            return cur.rowcount == 1

    def replace_failed_derivation(self, derivation: AsrDerivation) -> bool:
        """Atomically replace a `failed` row with a fresh derivation outcome.

        One transaction: the failed row is deleted (only a failed row — an
        `ok` derivation is never deleted; derive once per content hash) and
        the new row inserted, so no crash window can erase the durable failure
        record without leaving its replacement. If a concurrent racer already
        installed an `ok` row, the delete matches nothing and the insert is a
        no-op — the stored row wins.
        """
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM {_DERIVATION_TABLE} WHERE content_sha256 = ? AND status = ?",
                (derivation.content_sha256, DERIVATION_FAILED),
            )
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_DERIVATION_TABLE} "
                "(content_sha256, status, text, segments, language, error, engine, derived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    derivation.content_sha256,
                    derivation.status,
                    derivation.text,
                    json.dumps(derivation.segments),
                    derivation.language,
                    derivation.error,
                    json.dumps(derivation.engine),
                    _iso(derivation.derived_at),
                ),
            )
            return cur.rowcount == 1

    def derivations_for(self, hashes: List[str]) -> Dict[str, AsrDerivation]:
        if not hashes:
            return {}
        # Chunked: a legal session can hold up to MAX_SESSION_SEQ segments,
        # which would exceed SQLite's default variable limit in one IN clause.
        found: Dict[str, AsrDerivation] = {}
        with self._connect() as conn:
            for start in range(0, len(hashes), 500):
                chunk = hashes[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT content_sha256, status, text, segments, language, error, engine, "
                    f"derived_at FROM {_DERIVATION_TABLE} "
                    f"WHERE content_sha256 IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    derivation = self._derivation_from_row(row)
                    found[derivation.content_sha256] = derivation
        return found

    @staticmethod
    def _derivation_from_row(row: tuple) -> AsrDerivation:
        return AsrDerivation(
            content_sha256=row[0],
            status=row[1],
            text=row[2] or "",
            segments=json.loads(row[3] or "[]"),
            language=row[4] or "unknown",
            error=row[5] or "",
            engine=json.loads(row[6] or "{}"),
            derived_at=_parse_ts(row[7]),
        )

    def latest_revision(self, session_id: str) -> Optional[AnalysisRevision]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, revision, input_set_sha256, derived_from, template_id, "
                f"blocks, engine, derived_at FROM {_REVISION_TABLE} "
                "WHERE session_id = ? ORDER BY revision DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._revision_from_row(row) if row else None

    def revision_by_input_set(
        self, session_id: str, input_set_sha256: str
    ) -> Optional[AnalysisRevision]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, revision, input_set_sha256, derived_from, template_id, "
                f"blocks, engine, derived_at FROM {_REVISION_TABLE} "
                "WHERE session_id = ? AND input_set_sha256 = ? "
                "ORDER BY revision DESC LIMIT 1",
                (session_id, input_set_sha256),
            ).fetchone()
        return self._revision_from_row(row) if row else None

    def insert_revision(self, revision: AnalysisRevision) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_REVISION_TABLE} "
                "(session_id, revision, input_set_sha256, derived_from, template_id, blocks, "
                "engine, derived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision.session_id,
                    revision.revision,
                    revision.input_set_sha256,
                    json.dumps(revision.derived_from),
                    revision.template_id,
                    json.dumps(revision.blocks),
                    json.dumps(revision.engine),
                    _iso(revision.derived_at),
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                keep = revision_retention()
                conn.execute(
                    f"DELETE FROM {_REVISION_TABLE} WHERE session_id = ? AND revision <= ?",
                    (revision.session_id, revision.revision - keep),
                )
            return inserted

    def revisions_for_session(self, session_id: str) -> List[AnalysisRevision]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, revision, input_set_sha256, derived_from, template_id, "
                f"blocks, engine, derived_at FROM {_REVISION_TABLE} "
                "WHERE session_id = ? ORDER BY revision ASC",
                (session_id,),
            ).fetchall()
        return [self._revision_from_row(row) for row in rows]

    @staticmethod
    def _revision_from_row(row: tuple) -> AnalysisRevision:
        return AnalysisRevision(
            session_id=row[0],
            revision=int(row[1]),
            input_set_sha256=row[2],
            derived_from=json.loads(row[3] or "[]"),
            template_id=row[4],
            blocks=json.loads(row[5] or "[]"),
            engine=json.loads(row[6] or "{}"),
            derived_at=_parse_ts(row[7]),
        )


# ---------------------------------------------------------------------------
# Postgres backend (PDM; migration-owned, fail-loud preflight)
# ---------------------------------------------------------------------------


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


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    for table in (_DERIVATION_TABLE, _REVISION_TABLE):
        cur.execute("SELECT to_regclass(%s)", (table,))
        row = cur.fetchone()
        if not (row and row[0]):
            raise MeetingProjectionSchemaMissingError(
                f"Missing table '{table}'. {_MIGRATION_HINT}"
            )


_PG_AUTOCREATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_DERIVATION_TABLE} (
    content_sha256 TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    segments JSONB NOT NULL DEFAULT '[]'::jsonb,
    language TEXT NOT NULL DEFAULT 'unknown',
    error TEXT NOT NULL DEFAULT '',
    engine JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    derived_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {_REVISION_TABLE} (
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    input_set_sha256 TEXT NOT NULL,
    derived_from JSONB NOT NULL,
    template_id TEXT NOT NULL,
    blocks JSONB NOT NULL,
    engine JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    derived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, revision)
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_analysis_revision_set_idx
    ON {_REVISION_TABLE} (session_id, input_set_sha256);
"""


class _PgProjectionStore:
    """Postgres-backed projection store mirroring the SQLite semantics."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            if _schema_autocreate_enabled():
                conn.cursor().execute(_PG_AUTOCREATE_DDL)
            else:
                _assert_pg_schema(conn)
        finally:
            conn.close()

    def get_derivation(self, content_sha256: str) -> Optional[AsrDerivation]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT content_sha256, status, text, segments, language, error, engine, "
                f"derived_at FROM {_DERIVATION_TABLE} WHERE content_sha256 = %s",
                (content_sha256,),
            )
            row = cur.fetchone()
            return self._derivation_from_row(row) if row else None
        finally:
            conn.close()

    def insert_derivation(self, derivation: AsrDerivation) -> bool:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_DERIVATION_TABLE} "
                "(content_sha256, status, text, segments, language, error, engine, derived_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s) "
                "ON CONFLICT (content_sha256) DO NOTHING",
                (
                    derivation.content_sha256,
                    derivation.status,
                    derivation.text,
                    json.dumps(derivation.segments),
                    derivation.language,
                    derivation.error,
                    json.dumps(derivation.engine),
                    derivation.derived_at,
                ),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    def replace_failed_derivation(self, derivation: AsrDerivation) -> bool:
        import psycopg

        from app.db.dsn import resolve_dsn

        url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
        if not url:
            raise RuntimeError("DATABASE_URL or DB_DSN not set")
        # One explicit transaction (autocommit off) so the failed-row delete
        # and its replacement commit together — no crash window can erase the
        # durable failure record without leaving its replacement.
        conn = psycopg.connect(resolve_dsn(url))
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    f"DELETE FROM {_DERIVATION_TABLE} WHERE content_sha256 = %s AND status = %s",
                    (derivation.content_sha256, DERIVATION_FAILED),
                )
                cur.execute(
                    f"INSERT INTO {_DERIVATION_TABLE} "
                    "(content_sha256, status, text, segments, language, error, engine, derived_at) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s) "
                    "ON CONFLICT (content_sha256) DO NOTHING",
                    (
                        derivation.content_sha256,
                        derivation.status,
                        derivation.text,
                        json.dumps(derivation.segments),
                        derivation.language,
                        derivation.error,
                        json.dumps(derivation.engine),
                        derivation.derived_at,
                    ),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def derivations_for(self, hashes: List[str]) -> Dict[str, AsrDerivation]:
        if not hashes:
            return {}
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT content_sha256, status, text, segments, language, error, engine, "
                f"derived_at FROM {_DERIVATION_TABLE} WHERE content_sha256 = ANY(%s)",
                (hashes,),
            )
            found: Dict[str, AsrDerivation] = {}
            for row in cur.fetchall():
                derivation = self._derivation_from_row(row)
                found[derivation.content_sha256] = derivation
            return found
        finally:
            conn.close()

    @staticmethod
    def _derivation_from_row(row: tuple) -> AsrDerivation:
        def _as_obj(value: Any, default: Any) -> Any:
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value) if value else default

        return AsrDerivation(
            content_sha256=row[0],
            status=row[1],
            text=row[2] or "",
            segments=_as_obj(row[3], []),
            language=row[4] or "unknown",
            error=row[5] or "",
            engine=_as_obj(row[6], {}),
            derived_at=_parse_ts(row[7]),
        )

    def latest_revision(self, session_id: str) -> Optional[AnalysisRevision]:
        return self._one_revision(
            "WHERE session_id = %s ORDER BY revision DESC LIMIT 1", (session_id,)
        )

    def revision_by_input_set(
        self, session_id: str, input_set_sha256: str
    ) -> Optional[AnalysisRevision]:
        return self._one_revision(
            "WHERE session_id = %s AND input_set_sha256 = %s ORDER BY revision DESC LIMIT 1",
            (session_id, input_set_sha256),
        )

    def _one_revision(self, clause: str, params: tuple) -> Optional[AnalysisRevision]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, revision, input_set_sha256, derived_from, template_id, "
                f"blocks, engine, derived_at FROM {_REVISION_TABLE} {clause}",
                params,
            )
            row = cur.fetchone()
            return self._revision_from_row(row) if row else None
        finally:
            conn.close()

    def insert_revision(self, revision: AnalysisRevision) -> bool:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_REVISION_TABLE} "
                "(session_id, revision, input_set_sha256, derived_from, template_id, blocks, "
                "engine, derived_at) VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s) "
                "ON CONFLICT (session_id, revision) DO NOTHING",
                (
                    revision.session_id,
                    revision.revision,
                    revision.input_set_sha256,
                    json.dumps(revision.derived_from),
                    revision.template_id,
                    json.dumps(revision.blocks),
                    json.dumps(revision.engine),
                    revision.derived_at,
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                keep = revision_retention()
                cur.execute(
                    f"DELETE FROM {_REVISION_TABLE} WHERE session_id = %s AND revision <= %s",
                    (revision.session_id, revision.revision - keep),
                )
            return inserted
        finally:
            conn.close()

    def revisions_for_session(self, session_id: str) -> List[AnalysisRevision]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, revision, input_set_sha256, derived_from, template_id, "
                f"blocks, engine, derived_at FROM {_REVISION_TABLE} "
                "WHERE session_id = %s ORDER BY revision ASC",
                (session_id,),
            )
            return [self._revision_from_row(row) for row in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _revision_from_row(row: tuple) -> AnalysisRevision:
        def _as_obj(value: Any, default: Any) -> Any:
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value) if value else default

        return AnalysisRevision(
            session_id=row[0],
            revision=int(row[1]),
            input_set_sha256=row[2],
            derived_from=_as_obj(row[3], []),
            template_id=row[4],
            blocks=_as_obj(row[5], []),
            engine=_as_obj(row[6], {}),
            derived_at=_parse_ts(row[7]),
        )


def _backend() -> "_SqliteProjectionStore | _PgProjectionStore":
    if resolve_heimdal_backend() == "pg":
        return _PgProjectionStore()
    return _SqliteProjectionStore(_sqlite_path())


# ---------------------------------------------------------------------------
# Derivation trigger (called from the production admission path)
# ---------------------------------------------------------------------------


def derive_segment(
    *,
    session_id: str,
    session_seq: int,
    content_sha256: str,
    media_bytes: bytes,
    kind: str,
) -> Optional[AsrDerivation]:
    """Derive one admitted segment's ASR result, exactly once per content hash.

    Called from the admission path after the CDLM-02 ledger row is recorded, on
    both the fresh and the idempotent-replay branch — a replay whose earlier
    attempt crashed before derivation completes it here, while an
    already-derived hash short-circuits on the durable derivation row (which is
    also what makes a hub restart re-derive nothing).

    A `failed` row is retried on the next replay of the same content: the
    failure stays durable and legible in the projection until a retry
    succeeds, and only failed rows are ever replaced. ASR runs through the one
    shared engine seam (`app.media.transcribe.run_asr`, reached as a module
    attribute so the enforcement test stubs the real seam). Non-audio kinds
    attach as items, not analysis inputs, and derive nothing here.

    After a successful (or failed) derivation the session's analysis is
    re-derived; the projection read reports the result. This function never
    raises into the admission path: the admission was already acknowledged, and
    a derivation problem is per-segment needs-attention state, not an
    admission failure.
    """
    try:
        return _derive_segment_inner(
            session_id=session_id,
            session_seq=session_seq,
            content_sha256=content_sha256,
            media_bytes=media_bytes,
            kind=kind,
        )
    except Exception as exc:
        # Nothing in derivation — including a store or schema failure — may
        # fail the admission that already acknowledged the capture. An
        # unrecordable derivation is retried on the client's next resend, and
        # the projection read surfaces the store problem loudly on its own
        # surface.
        logger.error(
            "meeting projection derivation trigger failed session_id=%s seq=%s sha=%s: %s",
            session_id,
            session_seq,
            content_sha256,
            exc,
        )
        return None


def _derive_segment_inner(
    *,
    session_id: str,
    session_seq: int,
    content_sha256: str,
    media_bytes: bytes,
    kind: str,
) -> Optional[AsrDerivation]:
    if kind != "audio":
        return None
    store = _backend()
    existing = store.get_derivation(content_sha256)
    if existing is not None and existing.status == DERIVATION_OK:
        # The replay heals everything a crashed first attempt may have left
        # unfinished (KD-F9588AFBC165): the transcript block registration is
        # an idempotent guard create, and the analysis re-derivation is
        # idempotent by input-set identity — an already-complete state mints
        # nothing on either path.
        _register_transcript_block(session_id, session_seq, content_sha256, existing)
        _rederive_analysis(session_id)
        return existing
    retry_of_failed = existing is not None and existing.status == DERIVATION_FAILED

    try:
        with tempfile.NamedTemporaryFile(
            prefix="heimdal-meeting-seg-", suffix=".m4a", delete=True
        ) as handle:
            handle.write(media_bytes)
            handle.flush()
            result = transcribe_module.run_asr(Path(handle.name))
        derivation = AsrDerivation(
            content_sha256=content_sha256,
            status=DERIVATION_OK,
            text=str(result.get("text") or ""),
            segments=list(result.get("segments") or []),
            language=str(result.get("language") or "unknown"),
            error="",
            engine={"seam": "app.media.transcribe.run_asr", **ANALYSIS_ENGINE},
            derived_at=_utcnow(),
        )
    except Exception as exc:
        logger.error(
            "meeting projection ASR failed session_id=%s seq=%s sha=%s: %s",
            session_id,
            session_seq,
            content_sha256,
            exc,
        )
        derivation = AsrDerivation(
            content_sha256=content_sha256,
            status=DERIVATION_FAILED,
            text="",
            segments=[],
            language="unknown",
            error=f"{type(exc).__name__}: {exc}",
            engine={"seam": "app.media.transcribe.run_asr", **ANALYSIS_ENGINE},
            derived_at=_utcnow(),
        )

    if retry_of_failed:
        # ASR ran first, so the durable failure record exists right up to the
        # atomic delete+insert that replaces it — no crash window renders the
        # failure illegible as a bare "pending" row.
        created = store.replace_failed_derivation(derivation)
    else:
        created = store.insert_derivation(derivation)
    if not created:
        stored = store.get_derivation(content_sha256)
        if stored is not None:
            derivation = stored

    if derivation.status == DERIVATION_OK:
        _register_transcript_block(session_id, session_seq, content_sha256, derivation)

    try:
        _rederive_analysis(session_id)
    except Exception as exc:
        # Analysis is rebuildable from durable state; a failed re-derivation
        # must not fail the admission and is re-attempted on the next segment
        # or read.
        logger.error(
            "meeting projection analysis re-derivation failed session_id=%s: %s",
            session_id,
            exc,
        )
    return derivation


def _register_transcript_block(
    session_id: str, session_seq: int, content_sha256: str, derivation: AsrDerivation
) -> None:
    """Register the transcript block through the shared ownership guard
    (CDLM-07): the ASR derivation is the only writer of transcript_segment
    blocks, and even it goes through the guard seam. Idempotent (guard create
    replays), and called on both the fresh and the replay derivation path so
    duplicate-content segments and crash windows still register."""
    meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=_ASR_WRITER,
        action=meeting_blocks.ACTION_CREATE,
        block_id=f"{session_id}:transcript:{session_seq}",
        block_type=meeting_blocks.TYPE_TRANSCRIPT_SEGMENT,
        content=derivation.text,
        position=session_seq,
        provenance_extra={"content_sha256": content_sha256},
    )


def _admitted_input_set(session_id: str) -> tuple[List[Dict[str, Any]], Dict[str, AsrDerivation]]:
    report = meeting_ledger.build_gap_report(session_id)
    segments = report["segments"]
    hashes = [seg["content_sha256"] for seg in segments]
    derivations = _backend().derivations_for(hashes)
    derived_from = [
        {"seq": seg["seq"], "content_sha256": seg["content_sha256"]}
        for seg in segments
        if derivations.get(seg["content_sha256"]) is not None
        and derivations[seg["content_sha256"]].status == DERIVATION_OK
    ]
    return derived_from, derivations


def _rederive_analysis(session_id: str) -> Optional[AnalysisRevision]:
    """Re-derive the analysis projection over the current admitted set.

    Cached by input-set identity: an identical admitted set returns the
    existing revision and mints nothing (idempotent replays create no new
    revision); a changed set — a new or late segment — derives the next
    revision. Convergence is structural: `_derive_analysis_blocks` is a pure
    function of the ordered transcript text.
    """
    store = _backend()
    derived_from, derivations = _admitted_input_set(session_id)
    if not derived_from:
        return store.latest_revision(session_id)

    input_set = _input_set_identity(derived_from)
    existing = store.revision_by_input_set(session_id, input_set)
    if existing is not None:
        return existing

    session = meeting_ledger.get_meeting_session(session_id)
    template = resolve_template(session.template_selection if session else None)

    transcript_text = " ".join(
        derivations[item["content_sha256"]].text
        for item in sorted(derived_from, key=lambda item: item["seq"])
        if derivations[item["content_sha256"]].text
    ).strip()
    payloads = _derive_analysis_blocks(transcript_text)

    # Bounded retry: losing the (session, revision) insert race must not drop
    # this input set — the loser re-reads the latest revision and re-attempts
    # with the next number until its set is persisted (or a racer persisted
    # the identical set). Without this, two concurrent admissions could leave
    # the analysis permanently excluding an admitted segment.
    for _ in range(8):
        existing = store.revision_by_input_set(session_id, input_set)
        if existing is not None:
            return existing
        latest = store.latest_revision(session_id)
        next_revision = (latest.revision + 1) if latest else 1
        blocks = [
            {
                "block_id": f"{session_id}:{payload['block_type']}:{next_revision}",
                "ownership": "derived_projection",
                "revision": next_revision,
                "derived_from": derived_from,
                "template_id": template["template_id"],
                "engine": dict(ANALYSIS_ENGINE),
                **payload,
            }
            for payload in payloads
        ]
        revision = AnalysisRevision(
            session_id=session_id,
            revision=next_revision,
            input_set_sha256=input_set,
            derived_from=derived_from,
            template_id=template["template_id"],
            blocks=blocks,
            engine=dict(ANALYSIS_ENGINE),
            derived_at=_utcnow(),
        )
        if store.insert_revision(revision):
            _register_analysis_blocks(session_id, revision)
            return revision
    raise MeetingProjectionPersistenceError(
        f"analysis revision for session {session_id!r} could not be persisted after retries"
    )


# ---------------------------------------------------------------------------
# Projection read (side-effect-free)
# ---------------------------------------------------------------------------


def _register_analysis_blocks(session_id: str, revision: AnalysisRevision) -> None:
    """Mirror the analysis revision into the block registry via the guard.

    One stable block per analysis block type (`{session}:analysis:{type}`),
    revised in place under the analysis writer's own provenance — the guard is
    what makes it impossible for this path to land on a user_note target
    (INV-CDLM-6): a wrong id refuses instead of overwriting.
    """
    for index, block in enumerate(revision.blocks):
        block_id = f"{session_id}:analysis:{block['block_type']}"
        content = json.dumps(block["content"], sort_keys=True)
        extra = {"template_id": revision.template_id, "analysis_revision": revision.revision}
        existing = meeting_blocks.get_block(block_id)
        if existing is None:
            outcome = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=_ANALYSIS_WRITER,
                action=meeting_blocks.ACTION_CREATE,
                block_id=block_id,
                block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
                content=content,
                position=1_000_000 + index,
                provenance_extra=extra,
            )
        elif existing.content != content:
            outcome = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=_ANALYSIS_WRITER,
                action=meeting_blocks.ACTION_REVISE,
                block_id=block_id,
                content=content,
                provenance_extra=extra,
            )
        else:
            continue
        if not outcome.allowed:
            logger.warning(
                "analysis block registration refused session=%s block=%s: %s",
                session_id,
                block_id,
                outcome.reason,
            )


def build_projection(session_id: str) -> Dict[str, Any]:
    """Assemble the projection read: transcript, analysis, revisions, gaps.

    Side-effect-free: reads the CDLM-02 ledger and the durable projection
    state, derives nothing, writes nothing. Raises
    :class:`meeting_ledger.MeetingSessionNotFoundError` for an unknown session.
    """
    report = meeting_ledger.build_gap_report(session_id)
    store = _backend()
    hashes = [seg["content_sha256"] for seg in report["segments"]]
    derivations = store.derivations_for(hashes)

    by_seq = {seg["seq"]: seg for seg in report["segments"]}
    # The transcript covers every ledgered sequence AND every declared slot:
    # clamping to the declared count would silently elide an admitted segment
    # whose seq lands at or beyond an undercounted close (INV-CDLM-9 — the
    # ledger and analysis would carry a row the transcript never shows).
    received_bound = (max(report["received"]) + 1) if report["received"] else 0
    if report["closed"] and report["final_seq_count"] is not None:
        max_bound = max(report["final_seq_count"], received_bound)
    else:
        max_bound = received_bound

    transcript: List[Dict[str, Any]] = []
    needs_attention: List[Dict[str, Any]] = list(report["needs_attention"])

    def _flush_gap_run(run_start: int, run_end: int) -> None:
        """Render a run of missing sequences: individual markers for short
        runs, one explicit bounded run marker for long ones — still legible
        (INV-CDLM-9: from/to/count name every missing seq), never a multi-MB
        payload when a declared count vastly exceeds what arrived."""
        count = run_end - run_start + 1
        if count <= _GAP_RUN_COLLAPSE_THRESHOLD:
            for missing_seq in range(run_start, run_end + 1):
                transcript.append(
                    {"seq": missing_seq, "kind": "gap", "reason": "segment_missing"}
                )
        else:
            transcript.append(
                {
                    "seq": run_start,
                    "kind": "gap_run",
                    "reason": "segments_missing",
                    "from": run_start,
                    "to": run_end,
                    "count": count,
                }
            )

    pending_gap_start: Optional[int] = None
    for seq in range(max_bound):
        seg = by_seq.get(seq)
        if seg is None:
            if pending_gap_start is None:
                pending_gap_start = seq
            continue
        if pending_gap_start is not None:
            _flush_gap_run(pending_gap_start, seq - 1)
            pending_gap_start = None
        derivation = derivations.get(seg["content_sha256"])
        if derivation is None:
            transcript.append(
                {
                    "seq": seq,
                    "kind": "pending",
                    "content_sha256": seg["content_sha256"],
                    "receipt_id": seg["receipt_id"],
                }
            )
            continue
        if derivation.status == DERIVATION_FAILED:
            transcript.append(
                {
                    "seq": seq,
                    "kind": "needs_attention",
                    "content_sha256": seg["content_sha256"],
                    "receipt_id": seg["receipt_id"],
                    "error": derivation.error,
                }
            )
            needs_attention.append(
                {
                    "seq": seq,
                    "reason": "asr_failed",
                    "error": derivation.error,
                }
            )
            continue
        transcript.append(
            {
                "seq": seq,
                "kind": "segment",
                "content_sha256": seg["content_sha256"],
                "receipt_id": seg["receipt_id"],
                "text": derivation.text,
                "timing": derivation.segments,
                "language": derivation.language,
                "late": seg["late"],
            }
        )

    if pending_gap_start is not None:
        _flush_gap_run(pending_gap_start, max_bound - 1)

    latest = store.latest_revision(session_id)
    revisions = store.revisions_for_session(session_id)
    session = meeting_ledger.get_meeting_session(session_id)
    template = resolve_template(session.template_selection if session else None)

    needs_attention.extend(meeting_blocks.refusals_for_session(session_id))
    page_blocks = [
        {
            "block_id": blk.block_id,
            "owner": blk.owner,
            "type": blk.block_type,
            "position": blk.position,
            "revision": blk.revision,
            "retired": blk.retired,
            "content": blk.content,
            "provenance": blk.provenance,
        }
        for blk in meeting_blocks.blocks_for_session(session_id)
    ]

    return {
        "session_id": session_id,
        "closed": report["closed"],
        "complete": report["complete"],
        "final_seq_count": report["final_seq_count"],
        "missing": report["missing"],
        "template": template,
        "transcript": transcript,
        "analysis": {
            "revision": latest.revision if latest else None,
            "template_id": latest.template_id if latest else template["template_id"],
            "derived_from": latest.derived_from if latest else [],
            "engine": latest.engine if latest else dict(ANALYSIS_ENGINE),
            "blocks": latest.blocks if latest else [],
        },
        # The history entries are deliberately slim (count + set identity, not
        # the full derived_from list): the latest revision above carries the
        # complete provenance, and repeating every retained revision's input
        # list would make the poll payload O(retention x segments).
        "revisions": [
            {
                "revision": rev.revision,
                "derived_from_count": len(rev.derived_from),
                "input_set_sha256": rev.input_set_sha256,
                "template_id": rev.template_id,
                "derived_at": _iso(rev.derived_at),
            }
            for rev in revisions
        ],
        "needs_attention": needs_attention,
        "page_blocks": page_blocks,
    }


__all__ = [
    "ANALYSIS_ENGINE",
    "DEFAULT_REVISION_RETENTION",
    "DERIVATION_FAILED",
    "DERIVATION_OK",
    "GENERIC_DEFAULT_TEMPLATE",
    "SHIPPED_TEMPLATES",
    "AnalysisRevision",
    "AsrDerivation",
    "MeetingProjectionPersistenceError",
    "MeetingProjectionSchemaMissingError",
    "build_projection",
    "derive_segment",
    "reset_process_meeting_projection",
    "resolve_template",
    "revision_retention",
]
