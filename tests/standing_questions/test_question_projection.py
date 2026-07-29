from __future__ import annotations

import re
import uuid
from pathlib import Path

import psycopg
import pytest

from app.standing_questions.projection import (
    QuestionsDirectoryMissingError,
    _postgres_timestamptz_value,
    iter_question_notes,
    rebuild_standing_questions_projection,
)
from app.standing_questions.question_store import QuestionStore, parse_rfc3339_datetime
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


def _store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))


def test_missing_questions_directory_raises_instead_of_wiping(tmp_path: Path) -> None:
    """Review finding #2: a missing questions/ dir must fail loud, never TRUNCATE the
    existing projection down to zero rows as if it were legitimately empty."""
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(QuestionsDirectoryMissingError):
        rebuild_standing_questions_projection(vault)
    with pytest.raises(QuestionsDirectoryMissingError):
        iter_question_notes(vault)


def test_present_but_empty_questions_directory_is_not_missing(tmp_path: Path) -> None:
    """The dir-missing guard must not fire for a genuinely empty (but present) dir."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    assert iter_question_notes(vault) == []


def test_iter_question_notes_isolates_malformed_note(tmp_path: Path) -> None:
    """Review finding #1: one malformed Question note must not abort parsing of the
    rest -- it is skipped, and every valid note still comes back."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Valid question", scope="work", registered_via="explicit")

    bad_path = vault / "questions" / "sq-0badbad0-0000-0000-0000-000000000000.md"
    bad_path.write_text(
        "---\nquestion_id: sq-0badbad0-0000-0000-0000-000000000000\n---\n\nincomplete\n",
        encoding="utf-8",
    )

    notes = iter_question_notes(vault)
    assert [source for source, _ in notes] == [f"questions/{note['question_id']}.md"]


def test_iter_question_notes_ignores_non_question_markdown(tmp_path: Path) -> None:
    """Review finding #4: reusing iter_vault_markdown_files must not pick up unrelated
    markdown dropped directly into questions/."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Valid question", scope="work", registered_via="explicit")
    (vault / "questions" / "README.md").write_text("not a question note", encoding="utf-8")

    notes = iter_question_notes(vault)
    assert [source for source, _ in notes] == [f"questions/{note['question_id']}.md"]


#: Marks a source string the write/parse seam refuses, so the projection never sees it.
SEAM_REJECTS = "<rejected-by-the-write-seam>"

#: The literal grammar PostgreSQL 16 actually stores in a ``TIMESTAMPTZ``: no ``:60``
#: second (the server folds or rejects it) and at most microsecond resolution (an
#: over-long fraction is an outright error). The adapter must never emit outside this.
POSTGRES_TIMESTAMPTZ_LITERAL = re.compile(
    r"\d{4,6}-\d{2}-\d{2} \d{2}:\d{2}:[0-5]\d(\.\d{1,6})?\+00( BC)?"
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (None, None),
        ("2026-07-11T10:00:00Z", "2026-07-11 10:00:00+00"),
        ("1937-01-01T12:00:27.87+00:20", "1937-01-01 11:40:27.87+00"),
        ("2026-07-11T10:00:00+23:59", "2026-07-10 10:01:00+00"),
        ("2026-07-11T10:00:00-23:59", "2026-07-12 09:59:00+00"),
        ("0000-02-29T00:00:00Z", "0001-02-29 00:00:00+00 BC"),
        ("0000-01-01T00:00:00+23:59", "0002-12-31 00:01:00+00 BC"),
        ("9999-12-31T23:59:59-23:59", "10000-01-01 23:58:59+00"),
        # Leap seconds fold onto the following minute -- PostgreSQL has no ":60"
        # representation. The stored instant is one second later than the canonical
        # vault string; the adapter does the fold itself instead of relying on the
        # server, which accepts ":60" only with a zero fraction (see below).
        ("2016-12-31T23:59:60Z", "2017-01-01 00:00:00+00"),
        ("1990-12-31T15:59:60-08:00", "1991-01-01 00:00:00+00"),
        ("2017-01-01T00:59:60+01:00", "2017-01-01 00:00:00+00"),
        ("1972-06-30T23:59:60Z", "1972-07-01 00:00:00+00"),
        # A *fractional* announced leap second is accepted by the seam and is a hard
        # PostgreSQL error as a ":60" literal ("date/time field value out of range"),
        # which would abort every rebuild until the vault note was hand-edited.
        ("2016-12-31T23:59:60.123Z", "2017-01-01 00:00:00.123+00"),
        ("2016-12-31T23:59:60.0Z", "2017-01-01 00:00:00.0+00"),
        ("2012-06-30T23:59:60.999999Z", "2012-07-01 00:00:00.999999+00"),
        # RFC 3339 time-secfrac is unbounded; TIMESTAMPTZ resolves to microseconds and
        # rejects an over-long literal outright (MAXDATELEN 128). Digits past the
        # microsecond are truncated -- never rounded, so no carry reaches the seconds.
        ("2026-07-11T10:00:00.1234567890Z", "2026-07-11 10:00:00.123456+00"),
        ("2026-07-11T10:00:00.9999999Z", "2026-07-11 10:00:00.999999+00"),
        ("2026-07-11T10:00:00." + "1" * 129 + "Z", "2026-07-11 10:00:00.111111+00"),
        ("2016-12-31T23:59:60." + "9" * 200 + "Z", "2017-01-01 00:00:00.999999+00"),
        # Unannounced ":60" values never reach the projection: the seam rejects them,
        # so the adapter must fail loud rather than invent a PostgreSQL instant.
        ("1973-06-30T23:59:60Z", SEAM_REJECTS),
        ("1999-06-30T23:59:60Z", SEAM_REJECTS),
        ("2026-06-30T23:59:60Z", SEAM_REJECTS),
        ("2000-01-01T00:59:60+01:00", SEAM_REJECTS),
    ],
)
def test_postgres_timestamp_adapter_maps_rfc3339_to_a_storable_literal(
    source: str | None,
    expected: str | None,
) -> None:
    """Pin the literal the adapter *emits*, not the instant PostgreSQL then stores.

    For a leap second the two differ by one second, and the emitted literal is what
    decides whether a rebuild succeeds at all. The stored value is pinned separately
    against a real server by
    :func:`test_projection_adapts_rfc3339_edges_for_postgres`.
    """
    if expected == SEAM_REJECTS:
        assert parse_rfc3339_datetime(source) is None
        with pytest.raises(ValueError, match="invalid RFC 3339 timestamp"):
            _postgres_timestamptz_value(source)
        return
    if source is not None:
        # Every value the seam still accepts must project without a late failure.
        assert parse_rfc3339_datetime(source) is not None
    assert _postgres_timestamptz_value(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "2016-12-31T23:59:60Z",
        "2016-12-31T23:59:60.123Z",
        "2016-12-31T23:59:60." + "9" * 200 + "Z",
        "1972-06-30T23:59:60Z",
        "1990-12-31T15:59:60-08:00",
        "2026-07-11T10:00:00." + "1" * 129 + "Z",
        "2026-07-11T10:00:00.1234567890Z",
        "0000-02-29T00:00:00Z",
        "9999-12-31T23:59:59-23:59",
    ],
)
def test_postgres_literal_stays_inside_the_server_grammar(source: str) -> None:
    """No value the seam accepts may reach PostgreSQL as a literal it rejects.

    A rejected literal is not a skipped note: the INSERT runs inside the single
    TRUNCATE+replay transaction with no per-note guard, so it aborts the whole rebuild
    and keeps aborting until a human edits the vault. The two escapes that reached
    PostgreSQL were a ``:60`` second and an unbounded ``time-secfrac``.
    """
    literal = _postgres_timestamptz_value(source)
    assert literal is not None
    assert POSTGRES_TIMESTAMPTZ_LITERAL.fullmatch(literal), literal


def test_postgres_timestamp_adapter_fails_loud_for_unvalidated_input() -> None:
    with pytest.raises(ValueError, match="invalid RFC 3339 timestamp"):
        _postgres_timestamptz_value("not-a-timestamp")


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_questions_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f"ALTER DATABASE \"{name}\" SET lc_messages = 'C'")
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")
    yield dsn
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


@pytest.mark.pg
def test_projection_rebuilds_from_vault(scratch_db: str, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text="Will it rebuild?", scope="work", registered_via="explicit")

    first = rebuild_standing_questions_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        baseline = conn.execute(
            "SELECT question_id, scope, text, status, evidence FROM standing_questions ORDER BY question_id"
        ).fetchall()
        conn.execute("TRUNCATE TABLE standing_questions")
    second = rebuild_standing_questions_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rebuilt = conn.execute(
            "SELECT question_id, scope, text, status, evidence FROM standing_questions ORDER BY question_id"
        ).fetchall()
    assert first.inserted == second.inserted == 1
    assert baseline == rebuilt
    assert rebuilt[0][0] == note["question_id"]


@pytest.mark.pg
def test_rebuild_reports_and_survives_a_malformed_note(scratch_db: str, tmp_path: Path) -> None:
    """Review finding #1, end-to-end: a malformed note next to valid ones must not
    abort the transaction -- the valid note is still projected, the malformed one is
    reported in ``skipped_invalid``."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text="Survives a bad sibling?", scope="work", registered_via="explicit")
    bad_path = vault / "questions" / "sq-0badbad0-0000-0000-0000-000000000000.md"
    bad_path.write_text(
        "---\nquestion_id: sq-0badbad0-0000-0000-0000-000000000000\n---\n\nincomplete\n",
        encoding="utf-8",
    )

    summary = rebuild_standing_questions_projection(vault)

    assert summary.inserted == 1
    assert len(summary.skipped_invalid) == 1
    assert summary.skipped_invalid[0]["note_path"] == "questions/sq-0badbad0-0000-0000-0000-000000000000.md"
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = conn.execute("SELECT question_id FROM standing_questions").fetchall()
    assert [r[0] for r in rows] == [note["question_id"]]


@pytest.mark.pg
def test_projection_adapts_rfc3339_edges_for_postgres(
    scratch_db: str,
    tmp_path: Path,
) -> None:
    """Schema-valid vault timestamps must never become late projection failures.

    Every case here is a value the write seam accepts and durably stores in the vault.
    If the adapter hands PostgreSQL a literal the server refuses, the failure is not a
    skipped note -- the INSERT is inside the single TRUNCATE+replay transaction, so the
    whole rebuild aborts and keeps aborting until a human edits the note.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    created_at_cases = {
        "year-zero": ("0000-02-29T00:00:00Z", "0001-02-29 00:00:00.000000 BC"),
        "positive-extreme": (
            "2026-07-11T10:00:00+23:59",
            "2026-07-10 10:01:00.000000 AD",
        ),
        "negative-extreme": (
            "2026-07-11T10:00:00-23:59",
            "2026-07-12 09:59:00.000000 AD",
        ),
        # Asserted contract, not an incidental value: PostgreSQL has no ":60"
        # representation, so an announced leap second is stored one second later than
        # the canonical vault string -- on all 27 announced dates.
        "leap-second": (
            "2016-12-31T23:59:60Z",
            "2017-01-01 00:00:00.000000 AD",
        ),
        # A *fractional* announced leap second: `2016-12-31 23:59:60.123+00` is a hard
        # PostgreSQL error ("date/time field value out of range"), so the fold has to
        # happen in the adapter rather than being left to the server.
        "fractional-leap-second": (
            "2016-12-31T23:59:60.123Z",
            "2017-01-01 00:00:00.123000 AD",
        ),
        "fractional-leap-second-june": (
            "2012-06-30T23:59:60.999999Z",
            "2012-07-01 00:00:00.999999 AD",
        ),
        # RFC 3339 time-secfrac is unbounded and the vault keeps every digit; a literal
        # past MAXDATELEN (128) is rejected outright, so the adapter truncates to the
        # microsecond PostgreSQL actually stores.
        "over-long-fraction": (
            "2026-07-11T10:00:00." + "1" * 129 + "Z",
            "2026-07-11 10:00:00.111111 AD",
        ),
        "sub-microsecond-fraction": (
            "2026-07-11T10:00:00.1234567890Z",
            "2026-07-11 10:00:00.123456 AD",
        ),
        "ordinary": ("2026-07-11T10:00:00Z", "2026-07-11 10:00:00.000000 AD"),
    }
    expected_created_at: dict[str, str] = {}
    for label, (source, expected) in created_at_cases.items():
        note, _receipt = store.create_question(
            text=label,
            scope="work",
            registered_via="explicit",
            created_at=source,
        )
        expected_created_at[note["question_id"]] = expected
        assert store.read_question(note["question_id"])["created_at"] == source

    system_note, _receipt = store.create_question(
        text="system timestamp fields",
        scope="work",
        registered_via="explicit",
        created_at="2026-07-11T10:00:00Z",
    )
    evidence_timestamp = "2026-07-11T10:00:00+23:59"
    system_note, _receipt = store.update_system_fields(
        system_note["question_id"],
        {
            "evidence": [
                {
                    "artifact_ref": "note:abc",
                    "source_stream": "vault.activity",
                    "matched_at": evidence_timestamp,
                    "confidence_class": "high",
                    "provenance_ref": "receipt:abc",
                    "quoted_span": "evidence",
                }
            ],
            "last_matched_at": "0000-02-29T00:00:00Z",
            "last_refreshed_at": "2026-07-11T10:00:00-23:59",
        },
    )

    summary = rebuild_standing_questions_projection(vault)

    assert summary.inserted == len(created_at_cases) + 1
    expected_created_at[system_note["question_id"]] = "2026-07-11 10:00:00.000000 AD"
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        created_rows = conn.execute(
            """
            SELECT
                question_id,
                to_char(
                    created_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD HH24:MI:SS.US BC'
                )
            FROM standing_questions
            """
        ).fetchall()
        system_row = conn.execute(
            """
            SELECT
                to_char(
                    last_matched_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD HH24:MI:SS.US BC'
                ),
                to_char(
                    last_refreshed_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD HH24:MI:SS.US BC'
                ),
                evidence
            FROM standing_questions
            WHERE question_id = %s
            """,
            (system_note["question_id"],),
        ).fetchone()

    assert dict(created_rows) == expected_created_at
    assert system_row is not None
    assert system_row[0] == "0001-02-29 00:00:00.000000 BC"
    assert system_row[1] == "2026-07-12 09:59:00.000000 AD"
    assert system_row[2][0]["matched_at"] == evidence_timestamp
    persisted_system_note = store.read_question(system_note["question_id"])
    assert persisted_system_note["last_matched_at"] == "0000-02-29T00:00:00Z"
    assert persisted_system_note["last_refreshed_at"] == "2026-07-11T10:00:00-23:59"
    assert persisted_system_note["evidence"][0]["matched_at"] == evidence_timestamp


@pytest.mark.pg
def test_standing_questions_projection_migration_applies(scratch_db: str) -> None:
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('public.standing_questions')").fetchone()
    assert row[0] == "standing_questions"
