"""Fixed opt-in qualified TEST journey for Conversational Journaling.

The runner owns no channel, deployment, or fixture lifecycle.  It consumes one
operation-owned disposable vault after the native qualification owner has
bound the channel, source/image identity, fixture, actor, and finite effects.
It then exercises the shipped journaling seams without substituting a harness
implementation for Product behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Literal

from app.chat.reflection_conversation import ReflectionConversationService
from app.journaling.day_context import assemble_day_context
from app.journaling.draft import draft_journal_entry
from app.journaling.review import (
    JournalReviewState,
    process_journal_reviews_tick,
)
from app.vault.manager import VaultContext
from scripts.yaml_roundtrip import load_frontmatter


RECEIPT_SCHEMA = "conversational_journaling_execution.v1"
SYNTHETIC_ACTOR_ID = "synthetic-journaling-acceptance-v1"
REQUIRED_EFFECT_BUDGET = {
    "conversation_sessions": 2,
    "candidate_writes": 2,
    "actor_checkbox_writes": 1,
    "canonical_accepts": 1,
}
REQUIRED_SCENARIOS = (
    "preflight",
    "day_context",
    "conversation",
    "transcript",
    "primary_candidate",
    "synthetic_acceptance",
    "canonical_materialization",
    "second_conversation",
    "addendum_candidate",
    "never_overwrite",
)
_FIXED_OWNER_TURNS = (
    "I finished a difficult task and learned where the handoff was unclear.",
    "The most useful part was making the next step explicit.",
)
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")


class QualificationRefused(RuntimeError):
    """The operation could not prove prerequisites before Product effects."""


@dataclass(frozen=True)
class QualifiedManifest:
    channel: Literal["dev", "test"]
    expected_sha: str
    observed_sha: str
    expected_image_digest: str
    observed_image_digest: str
    run_id: str
    fixture_id: str
    actor_id: str
    for_date: date
    vault_root: Path
    anchor_note: str
    outbox_path: Path
    output_dir: Path
    effect_budget: dict[str, int]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    outcome: Literal["passed", "failed", "blocked", "not_run"]
    detail: str


@dataclass(frozen=True)
class AcceptanceReport:
    schema: str
    run_id: str
    channel: str
    actor_id: str
    expected_sha: str
    observed_sha: str
    expected_image_digest: str
    observed_image_digest: str
    fixture_id: str
    for_date: str
    feature_acceptance: Literal["PASS", "FAIL", "BLOCKED"]
    scenarios: tuple[ScenarioResult, ...]
    effects: dict[str, int]
    artifacts: dict[str, str]
    limitation: str | None

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["scenarios"] = [asdict(item) for item in self.scenarios]
        return payload


def load_manifest(path: Path, *, today: date | None = None) -> QualifiedManifest:
    """Load a private, fixed-shape manifest and prove pre-effect admission."""

    payload = _load_private_json(path, description="manifest")
    required = {
        "channel",
        "expected_sha",
        "observed_sha",
        "expected_image_digest",
        "observed_image_digest",
        "run_id",
        "fixture_id",
        "actor_id",
        "for_date",
        "vault_root",
        "anchor_note",
        "outbox_path",
        "output_dir",
        "effect_budget",
    }
    if set(payload) != required:
        raise QualificationRefused("manifest_fields_invalid")
    if payload["channel"] not in {"dev", "test"}:
        raise QualificationRefused("only_dev_and_test_are_supported")
    if not _SHA_RE.fullmatch(_text(payload, "expected_sha")):
        raise QualificationRefused("expected_sha_invalid")
    if not _SHA_RE.fullmatch(_text(payload, "observed_sha")):
        raise QualificationRefused("observed_sha_invalid")
    if payload["expected_sha"] != payload["observed_sha"]:
        raise QualificationRefused("source_identity_mismatch")
    for key in ("expected_image_digest", "observed_image_digest"):
        if not _DIGEST_RE.fullmatch(_text(payload, key)):
            raise QualificationRefused(f"{key}_invalid")
    if payload["expected_image_digest"] != payload["observed_image_digest"]:
        raise QualificationRefused("image_identity_mismatch")
    if not _RUN_ID_RE.fullmatch(_text(payload, "run_id")):
        raise QualificationRefused("run_id_invalid")
    fixture_id = _text(payload, "fixture_id")
    if not _RUN_ID_RE.fullmatch(fixture_id):
        raise QualificationRefused("fixture_id_invalid")
    if payload["actor_id"] != SYNTHETIC_ACTOR_ID:
        raise QualificationRefused("synthetic_actor_identity_invalid")
    try:
        for_date = date.fromisoformat(_text(payload, "for_date"))
    except ValueError as exc:
        raise QualificationRefused("for_date_invalid") from exc
    if for_date != (today or date.today()):
        raise QualificationRefused("fixture_date_must_be_current")

    vault_root = _absolute_existing_directory(payload["vault_root"], "vault_root")
    output_dir = _absolute_existing_directory(payload["output_dir"], "output_dir")
    if output_dir == vault_root or output_dir.is_relative_to(vault_root):
        raise QualificationRefused("evidence_must_be_outside_vault")
    outbox_path = _absolute_path(payload["outbox_path"], "outbox_path")
    if outbox_path == vault_root or outbox_path.is_relative_to(vault_root):
        raise QualificationRefused("receipt_outbox_must_be_outside_vault")
    if outbox_path.exists() or outbox_path.parent != output_dir:
        raise QualificationRefused("receipt_outbox_not_fresh_or_owned")
    anchor_note = _relative_markdown(payload["anchor_note"])
    anchor = vault_root / anchor_note
    _require_regular_file(anchor, description="anchor_note")

    effect_budget = payload["effect_budget"]
    if effect_budget != REQUIRED_EFFECT_BUDGET:
        raise QualificationRefused("effect_budget_invalid")

    marker = _load_private_json(
        vault_root / ".journal-acceptance-fixture.json",
        description="fixture_marker",
    )
    expected_marker = {
        "run_id": payload["run_id"],
        "fixture_id": fixture_id,
        "actor_id": SYNTHETIC_ACTOR_ID,
        "channel": payload["channel"],
        "for_date": for_date.isoformat(),
    }
    if marker != expected_marker:
        raise QualificationRefused("fixture_marker_mismatch")

    return QualifiedManifest(
        channel=payload["channel"],
        expected_sha=payload["expected_sha"],
        observed_sha=payload["observed_sha"],
        expected_image_digest=payload["expected_image_digest"],
        observed_image_digest=payload["observed_image_digest"],
        run_id=payload["run_id"],
        fixture_id=fixture_id,
        actor_id=SYNTHETIC_ACTOR_ID,
        for_date=for_date,
        vault_root=vault_root,
        anchor_note=anchor_note,
        outbox_path=outbox_path,
        output_dir=output_dir,
        effect_budget=dict(effect_budget),
    )


def run_qualified_journey(manifest: QualifiedManifest) -> AcceptanceReport:
    """Exercise the fixed Product journey and return redaction-safe evidence."""

    scenarios: list[ScenarioResult] = [
        ScenarioResult("preflight", "passed", "qualified identities admitted")
    ]
    effects = {key: 0 for key in REQUIRED_EFFECT_BUDGET}
    artifacts: dict[str, str] = {}
    try:
        context = VaultContext(
            status="selected",
            active_vault_path=str(manifest.vault_root),
            settings_path=str(manifest.vault_root / "settings"),
        )
        bundle = assemble_day_context(
            vault_context=context,
            for_date=manifest.for_date,
        )
        missing = [
            name
            for name, section in bundle.sections.items()
            if section.status != "available" or not section.items
        ]
        if missing:
            raise QualificationRefused(
                "synthetic_day_context_incomplete:" + ",".join(sorted(missing))
            )
        scenarios.append(
            ScenarioResult("day_context", "passed", "all three source families present")
        )

        first_session_id, first_transcript = _run_conversation(
            manifest=manifest,
            bundle=bundle,
            anchor=manifest.vault_root / manifest.anchor_note,
        )
        effects["conversation_sessions"] += 1
        scenarios.append(
            ScenarioResult("conversation", "passed", "fixed synthetic owner turns completed")
        )
        artifacts["primary_transcript_sha256"] = _sha256_file(first_transcript)
        scenarios.append(
            ScenarioResult("transcript", "passed", "durable transcript retained")
        )

        primary = draft_journal_entry(
            vault_context=context,
            for_date=manifest.for_date,
            session_id=first_session_id,
            day_context=bundle,
        )
        effects["candidate_writes"] += 1
        if primary.is_addendum:
            raise AssertionError("first qualified draft unexpectedly routed as addendum")
        primary_path = manifest.vault_root / primary.path
        primary_frontmatter, primary_body = load_frontmatter(
            primary_path.read_text(encoding="utf-8")
        )
        _assert_primary_candidate(
            primary_frontmatter,
            primary_body,
            first_session_id=first_session_id,
        )
        artifacts["primary_candidate_sha256"] = _sha256_file(primary_path)
        scenarios.append(
            ScenarioResult("primary_candidate", "passed", "proposal and provenance verified")
        )

        _check_primary_accept(primary_path)
        effects["actor_checkbox_writes"] += 1
        scenarios.append(
            ScenarioResult(
                "synthetic_acceptance",
                "passed",
                "fixed synthetic actor checked the existing acceptance intent",
            )
        )
        tick = process_journal_reviews_tick(
            vault_context=context,
            outbox_path=manifest.outbox_path,
            only_date=manifest.for_date,
        )
        if tick.errors or len(tick.results) != 1:
            raise AssertionError("journal review tick did not produce one clean result")
        accepted = tick.results[0]
        if (
            accepted.state is not JournalReviewState.FULLY_MATERIALIZED
            or accepted.action != "accept"
            or not accepted.receipt_id
            or not accepted.canonical_path
        ):
            raise AssertionError("journal review did not materialize the primary candidate")
        effects["canonical_accepts"] += 1
        canonical = manifest.vault_root / accepted.canonical_path
        canonical_before = canonical.read_bytes()
        canonical_frontmatter, _canonical_body = load_frontmatter(
            canonical_before.decode("utf-8")
        )
        if (
            canonical_frontmatter.get("authority_state") != "accepted"
            or canonical_frontmatter.get("acceptance_receipt_id") != accepted.receipt_id
        ):
            raise AssertionError("accepted note is not bound to the review receipt")
        artifacts["canonical_before_sha256"] = hashlib.sha256(
            canonical_before
        ).hexdigest()
        artifacts["acceptance_receipt_id"] = accepted.receipt_id
        scenarios.append(
            ScenarioResult(
                "canonical_materialization",
                "passed",
                "accepted test note and receipt identity verified",
            )
        )

        second_session_id, second_transcript = _run_conversation(
            manifest=manifest,
            bundle=bundle,
            anchor=manifest.vault_root / manifest.anchor_note,
        )
        effects["conversation_sessions"] += 1
        artifacts["second_transcript_sha256"] = _sha256_file(second_transcript)
        scenarios.append(
            ScenarioResult(
                "second_conversation", "passed", "second durable session completed"
            )
        )
        addendum = draft_journal_entry(
            vault_context=context,
            for_date=manifest.for_date,
            session_id=second_session_id,
            day_context=bundle,
        )
        effects["candidate_writes"] += 1
        if not addendum.is_addendum:
            raise AssertionError("second qualified draft did not route as addendum")
        addendum_path = manifest.vault_root / addendum.path
        addendum_frontmatter, addendum_body = load_frontmatter(
            addendum_path.read_text(encoding="utf-8")
        )
        if (
            addendum_frontmatter.get("journal_candidate_type") != "addendum"
            or addendum_frontmatter.get("authority_state") != "proposal"
            or f"session:{second_session_id}" not in addendum_frontmatter.get("sources", [])
            or "Accept and append this addendum" not in addendum_body
        ):
            raise AssertionError("second session addendum contract is incomplete")
        artifacts["addendum_candidate_sha256"] = _sha256_file(addendum_path)
        scenarios.append(
            ScenarioResult(
                "addendum_candidate", "passed", "distinct proposal addendum verified"
            )
        )
        canonical_after = canonical.read_bytes()
        artifacts["canonical_after_sha256"] = hashlib.sha256(
            canonical_after
        ).hexdigest()
        if canonical_after != canonical_before:
            raise AssertionError("accepted primary bytes changed during the second session")
        scenarios.append(
            ScenarioResult(
                "never_overwrite", "passed", "accepted primary bytes remain identical"
            )
        )
        _assert_effects_within_budget(effects, manifest.effect_budget)
    except QualificationRefused as exc:
        _append_terminal_results(scenarios, outcome="blocked", detail=str(exc))
        return _report(
            manifest,
            scenarios,
            effects,
            artifacts,
            feature_acceptance="BLOCKED",
            limitation=str(exc),
        )
    except Exception as exc:
        _append_terminal_results(
            scenarios,
            outcome="failed",
            detail=f"{type(exc).__name__}:{exc}",
        )
        return _report(
            manifest,
            scenarios,
            effects,
            artifacts,
            feature_acceptance="FAIL",
            limitation=f"{type(exc).__name__}:{exc}",
        )

    return _report(
        manifest,
        scenarios,
        effects,
        artifacts,
        feature_acceptance="PASS",
        limitation=None,
    )


def write_receipt(report: AcceptanceReport, *, output_dir: Path) -> Path:
    """Atomically retain one private attributable receipt outside the vault."""

    target = report_path(report, output_dir=output_dir)
    if target.exists():
        raise QualificationRefused("execution_receipt_already_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(report.as_payload(), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def report_path(report: AcceptanceReport, *, output_dir: Path) -> Path:
    if not output_dir.is_absolute() or not output_dir.is_dir():
        raise QualificationRefused("report_output_directory_missing")
    return output_dir / f"{report.run_id}.json"


def _run_conversation(
    *, manifest: QualifiedManifest, bundle: Any, anchor: Path
) -> tuple[str, Path]:
    service = ReflectionConversationService(vault_root=manifest.vault_root)
    conversation = service.start(note_path=anchor, day_context=bundle)
    for owner_turn in _FIXED_OWNER_TURNS:
        service.submit_owner_turn(conversation, owner_turn)
    service.submit_owner_turn(conversation, "/stop")
    if not conversation.closed or conversation.owner_turn_count != len(_FIXED_OWNER_TURNS):
        raise AssertionError("fixed reflection did not close after the synthetic owner stop")
    transcript = conversation.session.log_path
    _require_regular_file(transcript, description="transcript")
    text = transcript.read_text(encoding="utf-8")
    if "**Agent:**" not in text or "**Owner:**" not in text:
        raise AssertionError("reflection transcript lacks distinct agent/owner turns")
    return conversation.session.session_id, transcript


def _assert_primary_candidate(
    frontmatter: dict[str, object], body: str, *, first_session_id: str
) -> None:
    sources = frontmatter.get("sources")
    if (
        frontmatter.get("journal_candidate_type") != "primary"
        or frontmatter.get("derived_by") != "conversation"
        or frontmatter.get("authority_state") != "proposal"
        or not isinstance(sources, list)
        or f"session:{first_session_id}" not in sources
        or "[^conversation-" not in body
        or "[^context-" not in body
    ):
        raise AssertionError("primary candidate proposal/provenance contract is incomplete")


def _check_primary_accept(path: Path) -> None:
    _require_regular_file(path, description="primary_candidate")
    raw = path.read_bytes()
    unchecked = b"- [ ] Accept this draft as today's journal entry"
    checked = b"- [x] Accept this draft as today's journal entry"
    if raw.count(unchecked) != 1 or checked in raw:
        raise QualificationRefused("primary_acceptance_affordance_not_exactly_unchecked")
    replacement = raw.replace(unchecked, checked, 1)
    before = path.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.synthetic-actor.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), stat.S_IMODE(before.st_mode))
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        current = path.stat()
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            raise QualificationRefused("primary_candidate_changed_before_actor_write")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_terminal_results(
    scenarios: list[ScenarioResult],
    *,
    outcome: Literal["failed", "blocked"],
    detail: str,
) -> None:
    present = {item.name for item in scenarios}
    first_missing = True
    for name in REQUIRED_SCENARIOS:
        if name in present:
            continue
        scenarios.append(
            ScenarioResult(
                name,
                outcome if first_missing else "not_run",
                detail if first_missing else "not run after earlier terminal outcome",
            )
        )
        first_missing = False


def _report(
    manifest: QualifiedManifest,
    scenarios: list[ScenarioResult],
    effects: dict[str, int],
    artifacts: dict[str, str],
    *,
    feature_acceptance: Literal["PASS", "FAIL", "BLOCKED"],
    limitation: str | None,
) -> AcceptanceReport:
    by_name = {item.name: item for item in scenarios}
    ordered = tuple(by_name[name] for name in REQUIRED_SCENARIOS)
    if feature_acceptance == "PASS" and any(
        item.outcome != "passed" for item in ordered
    ):
        raise AssertionError("incomplete scenario inventory cannot report PASS")
    return AcceptanceReport(
        schema=RECEIPT_SCHEMA,
        run_id=manifest.run_id,
        channel=manifest.channel,
        actor_id=manifest.actor_id,
        expected_sha=manifest.expected_sha,
        observed_sha=manifest.observed_sha,
        expected_image_digest=manifest.expected_image_digest,
        observed_image_digest=manifest.observed_image_digest,
        fixture_id=manifest.fixture_id,
        for_date=manifest.for_date.isoformat(),
        feature_acceptance=feature_acceptance,
        scenarios=ordered,
        effects=dict(effects),
        artifacts=dict(artifacts),
        limitation=limitation,
    )


def _assert_effects_within_budget(
    effects: dict[str, int], budget: dict[str, int]
) -> None:
    if effects != budget:
        raise AssertionError(f"effect accounting mismatch: {effects!r}")


def _load_private_json(path: Path, *, description: str) -> dict[str, Any]:
    _require_regular_file(path, description=description, private=True)
    raw = path.read_bytes()
    if len(raw) > 32768:
        raise QualificationRefused(f"{description}_too_large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationRefused(f"{description}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise QualificationRefused(f"{description}_not_object")
    return payload


def _require_regular_file(
    path: Path, *, description: str, private: bool = False
) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise QualificationRefused(f"{description}_missing") from exc
    if path.is_symlink() or not stat.S_ISREG(observed.st_mode):
        raise QualificationRefused(f"{description}_not_regular")
    if private and (
        stat.S_IMODE(observed.st_mode) != 0o600 or observed.st_uid != os.geteuid()
    ):
        raise QualificationRefused(f"{description}_not_private")


def _absolute_existing_directory(value: object, description: str) -> Path:
    path = _absolute_path(value, description)
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        raise QualificationRefused(f"{description}_invalid")
    if any(parent.is_symlink() for parent in path.parents):
        raise QualificationRefused(f"{description}_symlink_parent")
    return path


def _absolute_path(value: object, description: str) -> Path:
    if not isinstance(value, str) or not value:
        raise QualificationRefused(f"{description}_invalid")
    path = Path(value)
    if not path.is_absolute() or "\x00" in value:
        raise QualificationRefused(f"{description}_invalid")
    return path


def _relative_markdown(value: object) -> str:
    if not isinstance(value, str) or not value.endswith(".md") or "\x00" in value:
        raise QualificationRefused("anchor_note_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise QualificationRefused("anchor_note_invalid")
    return value


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value != value.strip():
        raise QualificationRefused(f"{key}_invalid")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "AcceptanceReport",
    "QualificationRefused",
    "QualifiedManifest",
    "RECEIPT_SCHEMA",
    "REQUIRED_EFFECT_BUDGET",
    "REQUIRED_SCENARIOS",
    "SYNTHETIC_ACTOR_ID",
    "load_manifest",
    "report_path",
    "run_qualified_journey",
    "write_receipt",
]
