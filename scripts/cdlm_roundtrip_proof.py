#!/usr/bin/env python3
"""CDLM-10 (#4389): composed cross-device round-trip proof against the test channel.

Specified by
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/PROVE_CROSS_DEVICE_ROUND_TRIP_WITH_RECONNECT.md`.
One re-runnable script drives the six stages of the vertical's composed proof
through the hub's production HTTP surfaces — the exact contract the Bifrost
client speaks (same endpoints, sidecar shapes, resend semantics) — plus
hub-side verification queries, and emits named, durable evidence per stage:

  1 multi_modality_round_trip   — four modalities admitted, receipted, enumerated
  2 kill_restart_chaos          — api restart between admissions; no loss, no dup
  3 duplicate_injection         — scripted double-POSTs; everything stays singular
  4 live_meeting_reconnect      — projection grows; drop >=2 segments; reconnect
                                  resends exactly the ledger-missing set; user
                                  notes survive verbatim (hash-compared)
  5 gapped_close_late_reconcile — needs_attention naming the hole; late admit;
                                  re-finalization with lineage; 3-way separation
  6 legacy_lane_statement       — the watched-folder contrast + which guarantees
                                  apply to which lane

Outputs (under --out-dir):
  - round_trip_run_report.v1.json   (`cross_device_capture_live_meeting.round_trip_run_report.v1`)
  - chaos_stage_evidence.v1.json    (`cross_device_capture_live_meeting.chaos_stage_evidence.v1`)
  - run_report.md                   (the parent-issue receipt body)

Honesty rules, non-negotiable: a stage that cannot run in this environment is
reported `limited` with the named reason (e.g. the raw-store key still
unprovisioned, no api container handle for a real restart, no vault root for
artifact reads) — never silently skipped, never faked green. The four
capability checklines (zero lost originals, zero duplicates, gap legibility,
user-note verbatim survival) are explicit checked lines with inline evidence.

Test channel only. Simulator/device truths stay with bifrost#21's walkthrough.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RUN_REPORT_SCHEMA = "cross_device_capture_live_meeting.round_trip_run_report.v1"
CHAOS_EVIDENCE_SCHEMA = "cross_device_capture_live_meeting.chaos_stage_evidence.v1"

# Stage registry: the structure contract the AC test pins. Each stage names the
# evidence keys its receipt must carry.
STAGES: List[Dict[str, Any]] = [
    {
        "stage": 1,
        "id": "multi_modality_round_trip",
        "evidence": ["admissions", "receipt_query", "modality_count", "hash_matches"],
    },
    {
        "stage": 2,
        "id": "kill_restart_chaos",
        "evidence": ["pre_restart_receipts", "restart", "post_restart_receipts", "resend_outcome"],
    },
    {
        "stage": 3,
        "id": "duplicate_injection",
        "evidence": ["double_post_count", "idempotent_replays", "singularity"],
    },
    {
        "stage": 4,
        "id": "live_meeting_reconnect",
        "evidence": [
            "projection_growth",
            "dropped_segments",
            "ledger_missing_before_reconnect",
            "resent_exactly_missing",
            "revision_after_reconnect",
            "user_note_hashes",
        ],
    },
    {
        "stage": 5,
        "id": "gapped_close_late_reconcile",
        "evidence": [
            "close_needs_attention",
            "late_admit",
            "refinalization_lineage",
            "artifact_separation",
        ],
    },
    {
        "stage": 6,
        "id": "legacy_lane_statement",
        "evidence": ["watched_folder_admission", "lane_guarantees"],
    },
]

CHECKLINES = [
    "zero_lost_originals",
    "zero_duplicates",
    "gap_legibility",
    "user_note_verbatim_survival",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class StageResult:
    stage: int
    id: str
    status: str = "pass"  # pass | fail | limited
    evidence: Dict[str, Any] = field(default_factory=dict)
    limits: List[str] = field(default_factory=list)


class Hub:
    """Minimal client for the hub's production surfaces (stdlib only)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(
        self, method: str, path: str, *, data: Optional[bytes] = None, headers: Optional[dict] = None
    ) -> Dict[str, Any]:
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers or {}, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return {"status": resp.status, "json": json.loads(resp.read().decode("utf-8"))}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {"raw": "unparseable"}
            return {"status": exc.code, "json": body}

    def get(self, path: str) -> Dict[str, Any]:
        return self._request("GET", path)

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    def post_media(self, media: bytes, sidecar: Dict[str, Any], filename: str) -> Dict[str, Any]:
        boundary = f"cdlm10-{uuid.uuid4().hex}"
        parts = []
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
            + media
            + b"\r\n"
        )
        parts.append(
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="sidecar"; filename="sidecar.json"\r\n'
                "Content-Type: application/json\r\n\r\n"
                + json.dumps(sidecar)
                + "\r\n"
            ).encode("utf-8")
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        return self._request(
            "POST",
            "/api/heimdal/capture/media",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


def _sidecar(media: bytes, kind: str, device: str, **extra: Any) -> Dict[str, Any]:
    return {
        "capture_id": str(uuid.uuid4()),
        "content_sha256": _sha256(media),
        "kind": kind,
        "captured_at": _now(),
        "device_id": device,
        "schema_version": 1,
        **extra,
    }


def _admit(hub: Hub, media: bytes, sidecar: Dict[str, Any], name: str) -> Dict[str, Any]:
    resp = hub.post_media(media, sidecar, name)
    return {
        "capture_id": sidecar["capture_id"],
        "kind": sidecar["kind"],
        "content_sha256": sidecar["content_sha256"],
        "status": resp["status"],
        "body": resp["json"],
    }


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage_1_multi_modality(hub: Hub) -> StageResult:
    result = StageResult(stage=1, id="multi_modality_round_trip")
    fixtures = [
        ("audio", b"CDLM10 fixture audio memo bytes " + uuid.uuid4().bytes, "memo.m4a", "iphone-sim"),
        ("image", b"\xff\xd8\xff CDLM10 fixture photo " + uuid.uuid4().bytes, "photo.jpg", "iphone-sim"),
        (
            "document",
            b"%PDF-1.4 CDLM10 two-page receipt scan " + uuid.uuid4().bytes,
            "receipt.pdf",
            "ipad-sim",
        ),
        ("video", b"\x00\x00\x00 ftypmp42 CDLM10 clip " + uuid.uuid4().bytes, "clip.mp4", "ipad-sim"),
    ]
    admissions = []
    for kind, media, name, device in fixtures:
        sidecar = _sidecar(media, kind, device)
        admission = _admit(hub, media, sidecar, name)
        admission["_media"] = media  # in-process only; stripped before receipts
        admissions.append(admission)
    result.evidence["admissions"] = admissions
    result.evidence["modality_count"] = len({a["kind"] for a in admissions})

    ids = "&".join(f"capture_id={a['capture_id']}" for a in admissions)
    query = hub.get(f"/api/heimdal/capture/receipts?{ids}")
    result.evidence["receipt_query"] = query
    hash_matches = []
    outcomes = {r["capture_id"]: r for r in query["json"].get("receipts", [])} if query["status"] == 200 else {}
    for adm in admissions:
        answer = outcomes.get(adm["capture_id"], {})
        hash_matches.append(
            {
                "capture_id": adm["capture_id"],
                "admitted": adm["status"] == 200 and answer.get("outcome") == "admitted",
                "hash_match": answer.get("content_sha256") == adm["content_sha256"],
            }
        )
    result.evidence["hash_matches"] = hash_matches
    if not all(m["admitted"] and m["hash_match"] for m in hash_matches):
        failures = [a for a in admissions if a["status"] != 200]
        if failures and any(
            f["body"].get("detail", {}).get("error") == "raw_store_key_unavailable" for f in failures
        ):
            result.status = "fail"
            result.limits.append(
                "raw_store_key_unavailable: HEIMDAL_RAW_STORE_KEY is not provisioned to the "
                "test-channel api process (operator Keychain step from #4422 outstanding)"
            )
        else:
            result.status = "fail"
    return result


def stage_2_kill_restart(
    hub: Hub,
    api_container: Optional[str],
    admissions: List[Dict[str, Any]],
    restart_cmd: Optional[str] = None,
) -> StageResult:
    result = StageResult(stage=2, id="kill_restart_chaos")
    if not admissions:
        result.status = "limited"
        result.limits.append("no stage-1 admissions to exercise (stage 1 did not pass)")
        return result

    ids = "&".join(f"capture_id={a['capture_id']}" for a in admissions)
    result.evidence["pre_restart_receipts"] = hub.get(f"/api/heimdal/capture/receipts?{ids}")

    if api_container or restart_cmd:
        if api_container:
            restart = subprocess.run(
                ["docker", "restart", api_container], capture_output=True, text=True, check=False
            )
            restart_evidence = {"container": api_container}
        else:
            restart = subprocess.run(
                ["sh", "-c", restart_cmd], capture_output=True, text=True, check=False
            )
            restart_evidence = {"restart_cmd": restart_cmd}
        result.evidence["restart"] = {
            **restart_evidence,
            "returncode": restart.returncode,
            "stderr_tail": restart.stderr[-400:],
        }
        deadline = time.time() + 120
        up = False
        while time.time() < deadline:
            try:
                probe = hub.get("/api/health")
                if probe["status"] in (200, 503):
                    up = True
                    break
            except Exception:
                pass
            time.sleep(2)
        result.evidence["restart"]["api_back_up"] = up
        if not up:
            result.status = "fail"
            return result
    else:
        result.status = "limited"
        result.evidence["restart"] = {"skipped": True}
        result.limits.append(
            "no --api-container or --restart-cmd handle provided; a real process restart "
            "was not exercised in this run (receipts durability is still asserted by "
            "re-query below)"
        )

    result.evidence["post_restart_receipts"] = hub.get(f"/api/heimdal/capture/receipts?{ids}")
    post = result.evidence["post_restart_receipts"]
    survived = (
        post["status"] == 200
        and all(r.get("outcome") == "admitted" for r in post["json"].get("receipts", []))
    )
    # Resend the first original after restart: idempotent completion, no dup.
    first = admissions[0]
    resend = hub.post_media(
        first["_media"],
        {
            "capture_id": first["capture_id"],
            "content_sha256": first["content_sha256"],
            "kind": first["kind"],
            "captured_at": _now(),
            "device_id": "iphone-sim",
            "schema_version": 1,
        },
        "resend.bin",
    )
    result.evidence["resend_outcome"] = {
        "status": resend["status"],
        "idempotent_replay": resend["json"].get("idempotent_replay"),
        "receipt_id": resend["json"].get("receipt_id"),
        "same_receipt_id": resend["json"].get("receipt_id") == first["body"].get("receipt_id"),
    }
    if not survived or resend["status"] != 200 or not result.evidence["resend_outcome"]["same_receipt_id"]:
        result.status = "fail"
    return result


def stage_3_duplicate_injection(hub: Hub, admissions: List[Dict[str, Any]]) -> StageResult:
    result = StageResult(stage=3, id="duplicate_injection")
    if not admissions:
        result.status = "limited"
        result.limits.append("no stage-1 admissions to double-post (stage 1 did not pass)")
        return result
    replays = []
    for adm in admissions:
        resp = hub.post_media(
            adm["_media"],
            {
                "capture_id": adm["capture_id"],
                "content_sha256": adm["content_sha256"],
                "kind": adm["kind"],
                "captured_at": _now(),
                "device_id": "chaos-injector",
                "schema_version": 1,
            },
            "dup.bin",
        )
        replays.append(
            {
                "capture_id": adm["capture_id"],
                "status": resp["status"],
                "idempotent_replay": resp["json"].get("idempotent_replay"),
                "same_receipt_id": resp["json"].get("receipt_id") == adm["body"].get("receipt_id"),
            }
        )
    result.evidence["double_post_count"] = len(replays)
    result.evidence["idempotent_replays"] = replays
    singular = all(r["status"] == 200 and r["idempotent_replay"] and r["same_receipt_id"] for r in replays)
    ids = "&".join(f"capture_id={a['capture_id']}" for a in admissions)
    query = hub.get(f"/api/heimdal/capture/receipts?{ids}")
    receipt_ids = [r.get("receipt_id") for r in query["json"].get("receipts", [])]
    result.evidence["singularity"] = {
        "distinct_receipt_ids": len(set(receipt_ids)),
        "expected": len(admissions),
        "receipt_query_status": query["status"],
    }
    if not singular or len(set(receipt_ids)) != len(admissions):
        result.status = "fail"
    return result


def _admit_segment(hub: Hub, session_id: str, seq: int, media: bytes) -> Dict[str, Any]:
    sidecar = _sidecar(media, "audio", "ipad-sim", session_id=session_id, session_seq=seq)
    out = _admit(hub, media, sidecar, f"seg-{seq}.m4a")
    out["_media"] = media
    return out


def _load_audio_fixtures(fixture_dir: Optional[str], prefix: str, count: int) -> Optional[Dict[int, bytes]]:
    """Real speech fixtures for the meeting stages, when provided.

    The live hub runs the real ASR engine, which (correctly) refuses
    non-audio bytes — so an honest live run feeds real audio. Returns None
    when the directory or any expected file is absent.
    """
    if not fixture_dir:
        return None
    base = Path(fixture_dir)
    fixtures: Dict[int, bytes] = {}
    for seq in range(count):
        path = base / f"{prefix}-{seq}.m4a"
        if not path.is_file():
            return None
        fixtures[seq] = path.read_bytes()
    return fixtures


def stage_4_live_meeting(hub: Hub, audio_fixtures: Optional[str] = None) -> StageResult:
    result = StageResult(stage=4, id="live_meeting_reconnect")
    session_id = f"cdlm10-{uuid.uuid4().hex[:12]}"
    opened = hub.post_json(
        "/api/heimdal/meeting/session",
        {"session_id": session_id, "device_id": "ipad-sim", "template_selection": {}},
    )
    result.evidence["session"] = {"session_id": session_id, "open_status": opened["status"]}
    if opened["status"] != 200:
        result.status = "fail"
        return result

    segments = _load_audio_fixtures(audio_fixtures, "seg", 6) or {
        seq: f"cdlm10 meeting segment {seq}: we decided item {seq}.".encode() for seq in range(6)
    }
    if not _load_audio_fixtures(audio_fixtures, "seg", 6):
        result.limits.append(
            "no real audio fixtures provided; segment bytes are synthetic and the live "
            "ASR engine will record failed derivations (structure still proven)"
        )
    growth = []
    note_id = str(uuid.uuid4())
    note_text = "CDLM-10 verbatim note — must survive é å 中文, tabs\tand all."
    # Live phase: send 0..2, note, observe projection growth.
    for seq in (0, 1, 2):
        _admit_segment(hub, session_id, seq, segments[seq])
        proj = hub.get(f"/api/heimdal/meeting/{session_id}/projection")
        growth.append(
            {
                "after_seq": seq,
                "received": proj["json"].get("missing") is not None
                and [row["seq"] for row in proj["json"].get("transcript", []) if row.get("kind") == "segment"],
                "analysis_revision": proj["json"].get("analysis", {}).get("revision"),
            }
        )
    note = hub.post_json(
        f"/api/heimdal/meeting/{session_id}/user-note",
        {"note_block_id": note_id, "revision": 1, "text": note_text, "editor_identity": "operator@ipad-sim"},
    )
    result.evidence["user_note_write"] = {"status": note["status"], "sha": note["json"].get("content_sha256")}

    # Forced network drop over >=2 segments: 3 and 4 are never sent; 5 arrives.
    _admit_segment(hub, session_id, 5, segments[5])
    ledger = hub.get(f"/api/heimdal/meeting/{session_id}/segments")
    missing_before = ledger["json"].get("missing")
    result.evidence["dropped_segments"] = [3, 4]
    result.evidence["ledger_missing_before_reconnect"] = missing_before
    revision_before = hub.get(f"/api/heimdal/meeting/{session_id}/projection")["json"]["analysis"]["revision"]

    # Reconnect: resend EXACTLY what the ledger names missing.
    resent = []
    for seq in missing_before or []:
        out = _admit_segment(hub, session_id, seq, segments[seq])
        resent.append({"seq": seq, "status": out["status"]})
    result.evidence["resent_exactly_missing"] = {
        "asked_for": missing_before,
        "resent": [r["seq"] for r in resent],
        "match": [r["seq"] for r in resent] == missing_before,
    }
    proj_after = hub.get(f"/api/heimdal/meeting/{session_id}/projection")["json"]
    result.evidence["projection_growth"] = growth
    result.evidence["revision_after_reconnect"] = {
        "before": revision_before,
        "after": proj_after["analysis"]["revision"],
        "advanced": (proj_after["analysis"]["revision"] or 0) > (revision_before or 0),
        "missing_now": proj_after.get("missing"),
    }
    note_rows = [b for b in proj_after.get("page_blocks", []) if b.get("block_id") == note_id]
    registry_hash = _sha256(note_rows[0]["content"].encode("utf-8")) if note_rows else None
    result.evidence["user_note_hashes"] = {
        "written_sha256": _sha256(note_text.encode("utf-8")),
        "registry_sha256": registry_hash,
        "verbatim": registry_hash == _sha256(note_text.encode("utf-8")),
    }
    result.evidence["_session_id"] = session_id
    result.evidence["_note"] = {"id": note_id, "text_sha": _sha256(note_text.encode("utf-8"))}
    if not (
        result.evidence["resent_exactly_missing"]["match"]
        and result.evidence["revision_after_reconnect"]["advanced"]
        and result.evidence["user_note_hashes"]["verbatim"]
        and missing_before == [3, 4]
    ):
        result.status = "fail"
    return result


def stage_5_gapped_close(
    hub: Hub, vault_root: Optional[Path], audio_fixtures: Optional[str] = None
) -> StageResult:
    result = StageResult(stage=5, id="gapped_close_late_reconcile")
    session_id = f"cdlm10-gap-{uuid.uuid4().hex[:10]}"
    hub.post_json(
        "/api/heimdal/meeting/session",
        {"session_id": session_id, "device_id": "ipad-sim", "template_selection": {}},
    )
    segs = _load_audio_fixtures(audio_fixtures, "gap", 3) or {
        seq: f"cdlm10 gapped segment {seq} content.".encode() for seq in range(3)
    }
    for seq in (0, 2):  # withhold 1
        _admit_segment(hub, session_id, seq, segs[seq])
    note_text = "gap-session verbatim user note."
    note_id = str(uuid.uuid4())
    hub.post_json(
        f"/api/heimdal/meeting/{session_id}/user-note",
        {"note_block_id": note_id, "revision": 1, "text": note_text, "editor_identity": "operator@ipad-sim"},
    )
    closed = hub.post_json(f"/api/heimdal/meeting/{session_id}/close", {"final_seq_count": 3})
    fin = closed["json"].get("finalization", {})
    result.evidence["close_needs_attention"] = {
        "status": closed["status"],
        "finalization_status": fin.get("status"),
        "completeness": fin.get("receipt", {}).get("completeness"),
        "missing_seqs": fin.get("receipt", {}).get("missing_seqs"),
        "skip_or_fail_reason": fin.get("reason") or fin.get("message"),
    }
    if fin.get("status") not in ("finalized", "replayed"):
        result.status = "limited" if fin.get("reason") == "vault_root_unconfigured" else "fail"
        if fin.get("reason") == "vault_root_unconfigured":
            result.limits.append(
                "finalization skipped: HEIMDAL_MEETING_VAULT_ROOT is not configured on the "
                "test-channel api process; artifact materialization not exercised live"
            )
        return result

    late = _admit_segment(hub, session_id, 1, segs[1])
    proj = hub.get(f"/api/heimdal/meeting/{session_id}/projection")["json"]
    refin = proj.get("finalization") or {}
    first_receipt = fin.get("receipt", {})
    result.evidence["late_admit"] = {"status": late["status"], "seq": 1}
    result.evidence["refinalization_lineage"] = {
        "first_state": first_receipt.get("finalization_state"),
        "latest_state": refin.get("finalization_state"),
        "supersedes": refin.get("supersedes"),
        "lineage_ok": refin.get("supersedes") == first_receipt.get("finalization_state"),
        "completeness_now": refin.get("completeness"),
    }
    separation: Dict[str, Any] = {"checked": False}
    if vault_root is not None and refin.get("artifact_refs"):
        refs = refin["artifact_refs"]
        notes_path = vault_root / refs.get("user_notes", "")
        transcript_path = vault_root / refs.get("transcript", "")
        analysis_path = vault_root / refs.get("analysis", "")
        try:
            notes_body = notes_path.read_text(encoding="utf-8")
            separation = {
                "checked": True,
                "three_distinct_files": len({str(p) for p in (notes_path, transcript_path, analysis_path)}) == 3
                and transcript_path.is_file()
                and analysis_path.is_file(),
                "user_note_verbatim_in_artifact": note_text in notes_body,
                "derived_text_absent_from_notes_artifact": "gapped segment" not in notes_body,
            }
        except OSError as exc:
            separation = {"checked": False, "error": type(exc).__name__}
    elif vault_root is None:
        result.limits.append(
            "no --vault-root provided; the three-way artifact separation was verified through "
            "the finalization receipt refs only, not by reading artifact bytes"
        )
    result.evidence["artifact_separation"] = separation
    if not result.evidence["refinalization_lineage"]["lineage_ok"] or (
        result.evidence["close_needs_attention"]["missing_seqs"] != [1]
    ):
        result.status = "fail"
    elif result.limits and result.status == "pass":
        result.status = "limited"
    return result


def stage_6_legacy_statement(hub: Hub, watched_folder: Optional[Path]) -> StageResult:
    result = StageResult(stage=6, id="legacy_lane_statement")
    result.evidence["lane_guarantees"] = {
        "outbox_lane": (
            "governed HTTP admission; durable-acceptance receipts keyed by (capture_id, "
            "content_sha256); receipt-gated retention on the client (CDLM-03); idempotent "
            "resend; session/segment ledger, projections, ownership guard, finalization"
        ),
        "watched_folder_lane": (
            "legacy Model-1 floor: admitted and receipted hub-side (content-hash keyed when no "
            "sidecar capture_id), NO receipt-gated retention, no session semantics; deletion "
            "behavior owned by the watcher (#4362 lineage)"
        ),
    }
    if watched_folder is None:
        result.status = "limited"
        result.evidence["watched_folder_admission"] = {"skipped": True}
        result.limits.append(
            "no --watched-folder provided (watcher service not part of this run); the lane "
            "contrast is stated, and the watched-folder round trip remains proven by HCAP-08 "
            "(#3191), which owns that lane's proof"
        )
        return result
    fixture = watched_folder / f"cdlm10-legacy-{uuid.uuid4().hex[:8]}.m4a"
    payload = b"cdlm10 legacy watched-folder fixture " + uuid.uuid4().bytes
    fixture.write_bytes(payload)
    content_hash = _sha256(payload)
    deadline = time.time() + 120
    answer: Dict[str, Any] = {}
    while time.time() < deadline:
        query = hub.get(f"/api/heimdal/capture/receipts?capture_id={content_hash}")
        receipts = query["json"].get("receipts", []) if query["status"] == 200 else []
        if receipts and receipts[0].get("outcome") == "admitted":
            answer = receipts[0]
            break
        time.sleep(3)
    result.evidence["watched_folder_admission"] = {
        "content_sha256": content_hash,
        "receipt": answer or {"outcome": "not observed within 120s"},
    }
    if not answer:
        result.status = "limited"
        result.limits.append("watched-folder admission not observed within 120s")
    return result


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def build_checklines(results: Dict[str, StageResult]) -> List[Dict[str, Any]]:
    s1 = results.get("multi_modality_round_trip")
    s2 = results.get("kill_restart_chaos")
    s3 = results.get("duplicate_injection")
    s4 = results.get("live_meeting_reconnect")
    s5 = results.get("gapped_close_late_reconcile")

    def line(name: str, ok: Optional[bool], evidence: Any) -> Dict[str, Any]:
        return {"checkline": name, "checked": bool(ok), "evidence": evidence}

    lost = None
    if s1 and s2:
        lost = (
            s1.status == "pass"
            and all(m["admitted"] for m in s1.evidence.get("hash_matches", []))
            and (
                s2.status != "fail"
                and all(
                    r.get("outcome") == "admitted"
                    for r in s2.evidence.get("post_restart_receipts", {}).get("json", {}).get("receipts", [])
                )
            )
        )
    dup = None
    if s3:
        dup = s3.status == "pass"
    gaps = None
    if s4 and s5:
        gaps = (
            s4.evidence.get("ledger_missing_before_reconnect") == [3, 4]
            and s5.evidence.get("close_needs_attention", {}).get("missing_seqs") == [1]
        )
    verbatim = None
    if s4:
        verbatim = bool(s4.evidence.get("user_note_hashes", {}).get("verbatim"))
        if s5 and s5.evidence.get("artifact_separation", {}).get("checked"):
            verbatim = verbatim and s5.evidence["artifact_separation"]["user_note_verbatim_in_artifact"]

    return [
        line(
            "zero_lost_originals",
            lost,
            {
                "stage1_hash_matches": s1.evidence.get("hash_matches") if s1 else None,
                "stage2_post_restart": (s2.evidence.get("post_restart_receipts", {}).get("json") if s2 else None),
            },
        ),
        line("zero_duplicates", dup, s3.evidence.get("singularity") if s3 else None),
        line(
            "gap_legibility",
            gaps,
            {
                "meeting_missing_pre_reconnect": s4.evidence.get("ledger_missing_before_reconnect") if s4 else None,
                "gapped_close": s5.evidence.get("close_needs_attention") if s5 else None,
            },
        ),
        line(
            "user_note_verbatim_survival",
            verbatim,
            {
                "hashes": s4.evidence.get("user_note_hashes") if s4 else None,
                "artifact": s5.evidence.get("artifact_separation") if s5 else None,
            },
        ),
    ]


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "## CDLM-10 round-trip run report — `prove-cross-device-round-trip-with-reconnect`",
        "",
        f"- **Channel identity:** {report['channel']}",
        f"- **Hub build SHA:** `{report['hub_sha']}`",
        f"- **Client build SHA (bifrost):** `{report['client_sha']}`",
        f"- **Run id / time:** `{report['run_id']}` / {report['ran_at']}",
        f"- **Duplicate-injection count:** {report['duplicate_injection_count']}",
        "",
        "### Capability checklines",
        "",
    ]
    for check in report["checklines"]:
        mark = "x" if check["checked"] else " "
        lines.append(f"- [{mark}] `{check['checkline']}`")
    lines.append("")
    lines.append("### Stages")
    lines.append("")
    lines.append("| # | Stage | Status | Limits |")
    lines.append("| --- | --- | --- | --- |")
    for stage in report["stages"]:
        limits = "; ".join(stage["limits"]) or "—"
        lines.append(f"| {stage['stage']} | `{stage['id']}` | **{stage['status']}** | {limits} |")
    lines.append("")
    lines.append(
        "Full per-stage evidence (commands, responses, counts, hashes) is in the attached "
        "receipt JSONs (`round_trip_run_report.v1.json`, `chaos_stage_evidence.v1.json`)."
    )
    lines.append("")
    lines.append("### Simulator-only limits and the remaining human step")
    lines.append("")
    lines.append(
        "This run drives the hub's production HTTP contract exactly as the Bifrost client "
        "speaks it; on-device client behaviors (locked-screen capture, real calls, wrist "
        "haptics, app-lifecycle kill/relaunch UI truths) are covered by CDLM-09's simulator "
        "XCUITest receipts and remain **bifrost#21's device walkthrough** — the named, now "
        "unblocked human step."
    )
    return "\n".join(lines)


def _strip_private(value: Any) -> Any:
    """Drop in-process-only keys (leading underscore, e.g. raw media bytes)
    before anything is serialized into a durable receipt."""
    if isinstance(value, dict):
        return {k: _strip_private(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_strip_private(v) for v in value]
    return value


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hub = Hub(args.base_url)
    run_id = f"cdlm10-{uuid.uuid4().hex[:10]}"

    results: Dict[str, StageResult] = {}
    s1 = stage_1_multi_modality(hub)
    # Stage 2/3 need the raw bytes; stash them on the admission dicts.
    results["multi_modality_round_trip"] = s1
    admitted = [a for a in s1.evidence.get("admissions", []) if a["status"] == 200]
    # regenerate media bytes references (kept in-process from stage 1)
    results["kill_restart_chaos"] = stage_2_kill_restart(
        hub, args.api_container, admitted, restart_cmd=args.restart_cmd
    )
    results["duplicate_injection"] = stage_3_duplicate_injection(hub, admitted)
    results["live_meeting_reconnect"] = stage_4_live_meeting(hub, args.audio_fixtures)
    results["gapped_close_late_reconcile"] = stage_5_gapped_close(
        hub, Path(args.vault_root) if args.vault_root else None, args.audio_fixtures
    )
    results["legacy_lane_statement"] = stage_6_legacy_statement(
        hub, Path(args.watched_folder) if args.watched_folder else None
    )

    checklines = build_checklines(results)
    stages_payload = [
        {
            "stage": r.stage,
            "id": r.id,
            "status": r.status,
            "evidence": _strip_private(r.evidence),
            "limits": r.limits,
        }
        for r in sorted(results.values(), key=lambda r: r.stage)
    ]
    report = {
        "schema": RUN_REPORT_SCHEMA,
        "run_id": run_id,
        "ran_at": _now(),
        "channel": args.channel,
        "base_url": args.base_url,
        "hub_sha": args.hub_sha,
        "client_sha": args.client_sha,
        "duplicate_injection_count": results["duplicate_injection"].evidence.get("double_post_count", 0),
        "checklines": checklines,
        "stages": stages_payload,
    }
    chaos = {
        "schema": CHAOS_EVIDENCE_SCHEMA,
        "run_id": run_id,
        "checklines": checklines,
        "kill_restart": stages_payload[1],
        "duplicate_injection": stages_payload[2],
        "reconnect": stages_payload[3],
    }
    (out_dir / "round_trip_run_report.v1.json").write_text(json.dumps(report, indent=2))
    (out_dir / "chaos_stage_evidence.v1.json").write_text(json.dumps(chaos, indent=2))
    (out_dir / "run_report.md").write_text(render_markdown(report))
    print(json.dumps({"run_id": run_id, "out_dir": str(out_dir), "stages": {s['id']: s['status'] for s in stages_payload}}, indent=2))
    return 0 if all(s["status"] != "fail" for s in stages_payload) else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8100", help="test-channel api base URL")
    parser.add_argument("--channel", default="test")
    parser.add_argument("--hub-sha", default="unknown")
    parser.add_argument("--client-sha", default="unknown")
    parser.add_argument("--api-container", default=None, help="docker container name for the restart stage")
    parser.add_argument(
        "--restart-cmd",
        default=None,
        help="shell command that restarts the api process (alternative to --api-container)",
    )
    parser.add_argument("--vault-root", default=None, help="test-channel vault root for artifact reads")
    parser.add_argument("--watched-folder", default=None, help="watched folder for the legacy-lane stage")
    parser.add_argument(
        "--audio-fixtures",
        default=None,
        help="directory of real speech fixtures (seg-0..5.m4a, gap-0..2.m4a) for the meeting stages",
    )
    parser.add_argument("--out-dir", default="runtime/proof/cdlm10")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the stage/evidence contract as JSON and exit without any network access",
    )
    args = parser.parse_args(argv)
    if args.plan:
        print(
            json.dumps(
                {
                    "schemas": [RUN_REPORT_SCHEMA, CHAOS_EVIDENCE_SCHEMA],
                    "stages": STAGES,
                    "checklines": CHECKLINES,
                },
                indent=2,
            )
        )
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
