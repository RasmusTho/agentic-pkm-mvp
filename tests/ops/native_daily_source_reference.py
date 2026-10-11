"""Pinned original finite Daily producer reference for native-only CI proof.

Only prepare_sources is retained, unchanged; no browser/feature/report substitute.
Original source file SHA256: 6729b41176a618ce006b47c4051a431c278273c653d9eb3c64dc754732978051
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from typing import Any

class Blocked(RuntimeError):
    pass

def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def _relative(value: str) -> bool:
    return isinstance(value, str) and bool(value) and not Path(value).is_absolute() and '..' not in Path(value).parts

def prepare_sources(*, vault_context: Any, for_date: Any, run_id: str, marker_path: str) -> dict[str, Any]:
    """Finite fixture preparation, called only inside #5675's admitted boundary.

    The native owner first creates/selects an isolated initialized test vault and
    its exact synthetic marker. All source writes below use existing writers and
    their real default guard; this helper never enables a route or changes env.
    """
    from datetime import datetime, time, timedelta, timezone
    from uuid import NAMESPACE_URL, uuid5
    from app.domain.commitments import CommitmentRecord
    from app.episodes.notes import render_episode_note
    from app.knowledge.write_ops import write_note_relative
    from app.receipts.decision_receipt_log import append_decision_receipt
    from app.relevance.materialization import materialize_moment
    from app.relevance.schema import Moment, MomentNeed, MomentProvenance, MomentTrigger, MomentUrgency, SurfacedRef
    from app.services.commitment_persistence import persist_commitment
    from app.vault.paths import get_vault_system_dir_rel

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) or not _relative(marker_path):
        raise ValueError("synthetic_fixture_input_invalid")
    root = Path(vault_context.active_vault_path).resolve(strict=True)
    marker = root / marker_path
    admission = json.loads(marker.read_text())
    if (marker.is_symlink() or admission.get("schema") != "daily-briefing-synthetic-fixture.v1"
            or admission.get("synthetic") is not True or admission.get("run_id") != run_id
            or admission.get("vault_id") != vault_context.active_vault_id or admission.get("vault_path") != str(root)):
        raise ValueError("synthetic_fixture_not_admitted")
    token = str(uuid5(NAMESPACE_URL, "daily-briefing-test:" + run_id))
    system = get_vault_system_dir_rel(root)
    reference = "Synthetic/" + run_id + ".md"
    paths = [reference, f"{system}/commitments/c-{token}.md", f"{system}/moments/{token}.md",
             f"episodes/ep-{token}.md", f"{system}/receipts/moments-{run_id}.jsonl"]
    receipt_day = for_date - timedelta(days=1)
    paths.append(f"{system}/receipts/decisions/decisions-{receipt_day.strftime('%Y%m')}.jsonl")
    if any((root / x).exists() for x in paths):
        raise ValueError("synthetic_source_target_exists")
    text = "I dag ska jag läsa den här anteckningen. We will review the synthetic decision today. Synthetic run " + run_id + "."
    write_note_relative(reference, f"---\nuuid: {token}\nsynthetic: true\n---\n{text}\n", vault_root=root)
    persist_commitment(CommitmentRecord(commitment_id="c-" + token, commitment_kind="next_action",
                                       state="next", target_ref=reference, summary=text), vault_context=vault_context)
    moment = Moment(uuid=token, created=datetime.combine(for_date, time(6), timezone.utc).isoformat(),
                    trigger=MomentTrigger(kind="test"), need=MomentNeed(basis="reorientation", summary=text),
                    surfaced_refs=[SurfacedRef(ref=reference, why="Explicit synthetic acceptance source")],
                    urgency=MomentUrgency(band="timely", basis="synthetic", evaluator="test"),
                    provenance=MomentProvenance(produced_by="synthetic-acceptance", inputs_digest=_hash(text.encode())))
    result = materialize_moment(moment, vault_context=vault_context, outbox_path=root / paths[4])
    if result.status != "materialized":
        raise Blocked("synthetic_moment_not_materialized")
    append_decision_receipt(object_id=token, vault_uuid=token, key="synthetic-review", value={"synthetic": True},
                            trace_id="synthetic-" + run_id, vault_root=root,
                            created_at=datetime.combine(receipt_day, time(12), timezone.utc))
    fields = {"episode_id": "ep-" + token, "scope": "synthetic", "title": "Synthetic planning episode",
              "time": {"start": for_date.isoformat() + "T08:30:00Z", "end": for_date.isoformat() + "T10:30:00Z", "closed": False},
              "space": [], "protagonists": [], "goal": [], "causation": [], "parent_episode": None,
              "segmentation": "proposed", "derived_from": ["calendar:synthetic-" + run_id + ":synthetic-etag"]}
    write_note_relative(paths[3], render_episode_note(fields), vault_root=root)
    inventory = {p.relative_to(root).as_posix(): _hash(p.read_bytes()) for p in root.rglob("*") if p.is_file() and p != marker}
    day_stamp = for_date.strftime("%Y%m%d")
    return {"source_files": inventory, "moment_path": paths[2], "moment_full_text": (root / paths[2]).read_text(),
            "fixture_marker": marker_path, "fixture_marker_sha256": _hash(marker.read_bytes()),
            "calendar_uid": "synthetic-" + run_id, "calendar_etag": "synthetic-etag",
            "calendar_ics": f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:synthetic-{run_id}\nSUMMARY:Synthetic planning session\nDTSTART:{day_stamp}T090000Z\nDTEND:{day_stamp}T100000Z\nEND:VEVENT\nEND:VCALENDAR\n"}
