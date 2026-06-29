"""Deterministic-fallback relevance evaluator (CRE-03, pull-only slice).

Reads vault-native inputs only — today's daily note plus notes that carry open
loops (unchecked tasks) or near-term commitments — and produces candidate
moments. This is the deterministic-fallback path the relevance-evaluator
contract permits for the first runtime slice
(``docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md``). It reads no external source
and emits no notification: it only returns :class:`Moment` proposals.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from app.relevance.schema import (
    Moment,
    MomentNeed,
    MomentProvenance,
    MomentTrigger,
    MomentUrgency,
    SurfacedRef,
    UrgencyBand,
)
from app.vault.manager import iter_vault_markdown_files
from app.vault.paths import resolve_vault_system_dir_rel_or_default

EVALUATOR_ID = "relevance-evaluator@deterministic-fallback"
PRODUCED_BY = "relevance-evaluator-contract/v0:deterministic-fallback"

_OPEN_TASK_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+", re.MULTILINE)
_COMMITMENT_HORIZON_DAYS = 2


@dataclass(frozen=True)
class _VaultNote:
    rel_path: str
    uuid: str | None
    frontmatter: dict
    body: str
    open_tasks: int


class DeterministicRelevanceEvaluator:
    """Compute moments from vault-native data, deterministically and pull-only."""

    def __init__(
        self,
        vault_root: Path | str,
        *,
        daily_dir: str = "Daily",
        today: date | None = None,
        now: datetime | None = None,
    ) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.daily_dir = daily_dir
        self._now = now or datetime.now(timezone.utc)
        self.today = today or self._now.date()
        # Degrade gracefully: a vault created by ``initialize_vault`` may carry
        # only ``settings/*.md`` (no layout note / system-settings.yaml), so the
        # strict resolver would raise and the default-on CRE tick would fail to
        # materialize anything. Fall back to the packaged default system folder.
        self._system_dir = resolve_vault_system_dir_rel_or_default(self.vault_root)

    def evaluate(self) -> list[Moment]:
        """Read vault-native inputs and return candidate moments (may be empty)."""

        notes = self._read_vault_notes()
        daily = self._read_daily_note()
        if daily is None and not notes:
            return []

        surfaced: list[SurfacedRef] = []
        inputs: list[str] = []

        if daily is not None:
            surfaced.append(
                SurfacedRef(
                    ref=daily.rel_path,
                    uuid=daily.uuid,
                    why="Today's daily note — resume from your leave-point.",
                )
            )
            inputs.append(daily.rel_path)

        band: UrgencyBand = "routine"
        basis_parts: list[str] = []

        for note in notes:
            due_in = self._commitment_days_until(note.frontmatter)
            if due_in is not None and due_in <= _COMMITMENT_HORIZON_DAYS:
                surfaced.append(
                    SurfacedRef(
                        ref=note.rel_path,
                        uuid=note.uuid,
                        why=f"Commitment due in {due_in} day(s) — backward plan from the deadline.",
                    )
                )
                band = "pressing"
                basis_parts.append(f"commitment within {due_in}d")
                inputs.append(note.rel_path)
            elif note.open_tasks:
                surfaced.append(
                    SurfacedRef(
                        ref=note.rel_path,
                        uuid=note.uuid,
                        why=f"{note.open_tasks} open loop(s) still tugging — incomplete or unparked.",
                    )
                )
                if band == "routine":
                    band = "timely"
                basis_parts.append(f"{note.open_tasks} open loop(s) in {note.rel_path}")
                inputs.append(note.rel_path)

        if not surfaced:
            return []

        need_basis = (
            "commitment-risk"
            if band == "pressing"
            else ("open-loop-pressure" if band == "timely" else "reorientation")
        )
        need_summary = f"Start of day — {self.today.isoformat()}"
        urgency_basis = "; ".join(basis_parts) or "start-of-day reorientation"
        inputs_digest = self._digest(inputs)
        moment = Moment(
            uuid=self._moment_uuid(
                need_basis=need_basis,
                need_summary=need_summary,
                urgency_band=band,
                urgency_basis=urgency_basis,
                surfaced=surfaced,
                inputs_digest=inputs_digest,
            ),
            created=self._iso(self._now),
            trigger=MomentTrigger(
                kind="start-of-day",
                source_ref=daily.rel_path if daily is not None else None,
            ),
            need=MomentNeed(
                basis=need_basis,  # type: ignore[arg-type]
                summary=need_summary,
            ),
            surfaced_refs=surfaced,
            urgency=MomentUrgency(
                band=band,
                basis=urgency_basis,
                evaluator=EVALUATOR_ID,
            ),
            context_snapshot={
                "interruptibility": "unknown (pull-only slice; no reach-out)",
            },
            provenance=MomentProvenance(
                produced_by=PRODUCED_BY,
                inputs_digest=inputs_digest,
            ),
        )
        return [moment]

    # -- vault-native reading (no external source) --------------------------

    def _read_daily_note(self) -> _VaultNote | None:
        rel = f"{self.daily_dir}/{self.today.isoformat()}.md"
        path = self.vault_root / rel
        if not path.is_file():
            return None
        return self._note_from_path(path, rel)

    def _read_vault_notes(self) -> list[_VaultNote]:
        notes: list[_VaultNote] = []
        skip_prefixes = (f"{self._system_dir}/", f"{self.daily_dir}/")
        for path in iter_vault_markdown_files(self.vault_root):
            rel = path.relative_to(self.vault_root).as_posix()
            if rel.startswith(skip_prefixes) or rel == f"{self.daily_dir}":
                continue
            if any(part.startswith(".") for part in path.relative_to(self.vault_root).parts):
                continue
            notes.append(self._note_from_path(path, rel))
        return notes

    def _note_from_path(self, path: Path, rel: str) -> _VaultNote:
        text = path.read_text(encoding="utf-8", errors="ignore")
        frontmatter, body = _split_frontmatter(text)
        return _VaultNote(
            rel_path=rel,
            uuid=_str_or_none(frontmatter.get("uuid")),
            frontmatter=frontmatter,
            body=body,
            open_tasks=len(_OPEN_TASK_RE.findall(body)),
        )

    def _commitment_days_until(self, frontmatter: dict) -> int | None:
        raw = frontmatter.get("due") or frontmatter.get("deadline")
        due = _coerce_date(raw)
        if due is None:
            return None
        return (due - self.today).days

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _digest(inputs: list[str]) -> str:
        joined = "\n".join(inputs).encode("utf-8")
        return f"sha256:{hashlib.sha256(joined).hexdigest()[:16]}"

    @staticmethod
    def _moment_uuid(
        *,
        need_basis: str,
        need_summary: str,
        urgency_band: UrgencyBand,
        urgency_basis: str,
        surfaced: list[SurfacedRef],
        inputs_digest: str,
    ) -> str:
        payload = {
            "inputs_digest": inputs_digest,
            "need_basis": need_basis,
            "need_summary": need_summary,
            "urgency_band": urgency_band,
            "urgency_basis": urgency_basis,
            "surfaced_refs": [
                {"ref": ref.ref, "uuid": ref.uuid, "why": ref.why}
                for ref in surfaced
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"moment-{digest[:32]}"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                data = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                data = {}
            if isinstance(data, dict):
                return data, parts[2].lstrip("\n")
    return {}, text


def _coerce_date(raw: object) -> date | None:
    # ``datetime`` subclasses ``date``; normalize to a pure ``date`` so the
    # caller's ``due - self.today`` does not raise ``datetime - date``.
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["DeterministicRelevanceEvaluator", "EVALUATOR_ID", "PRODUCED_BY"]
