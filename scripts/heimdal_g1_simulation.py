#!/usr/bin/env python3
"""G1 day-like capture simulation runner (#3408, ADR-0060 §4 G1).

Owner decision 2026-08-26: before any wearable is borrowed, simulate a day of
B-full capture against the *existing* downstream path and measure it. This
script is that measurement. It is not a capture path: it replays a synthetic
trace through the shipped governed media admission route
(`POST /api/heimdal/capture/media`, CDLM-01) exactly as a phone-tier uploader
would after receiving audio from a pendant, then reconciles through
`GET /api/heimdal/capture/receipts`.

Procedure (all local-only; tailnet transport; no cloud, no public ingress):

1. ``generate`` -- render a deterministic synthetic day-like trace (default
   8 h of 60 s Opus/16 kHz mono segments, seeded activity schedule) plus a
   ``heimdal.g1-simulation.trace.v1`` manifest. No recording, no speech, no
   personal data: the audio is shaped noise and silence.
2. Bring up the isolated instance with ``scripts/heimdal_g1_sim_host.sh up``
   on the channel host (the channel's pinned image, throwaway DB and vault).
3. ``run`` -- paced replay. Segment *i* becomes ready at sim-time
   ``(i+1) * segment_seconds``; ``--pace`` compresses wall time. Declared
   uplink-outage windows buffer segments and flush the backlog on restore;
   ``--restart-at-index`` restarts the real api mid-run; ``--duplicate-every``
   re-sends acknowledged segments; ``--drop-index`` segments are never sent so
   the reconciliation must report them as gaps.
4. ``run`` again *on the host* over a small calibration trace to measure the
   processing share without the network hop (``--role calibration``).
5. ``report`` -- fold run + calibration + host samples into the redacted
   ``heimdal.g1-simulation.v1`` receipt (JSON + Markdown).
6. Tear down with ``scripts/heimdal_g1_sim_host.sh down``.

Honesty rules: the receipt never claims battery, BLE link, phone-presence,
or wearability evidence; G1 stays unmet by construction. Durable outputs keep
counts, hashes and timings only -- no audio, capture ids, keys or addresses.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import random
import shlex
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlsplit

TRACE_SCHEMA = "heimdal.g1-simulation.trace.v1"
RUN_SCHEMA = "heimdal.g1-simulation.run.v1"
RECEIPT_SCHEMA = "heimdal.g1-simulation.v1"
MEDIA_PATH = "/api/heimdal/capture/media"
RECEIPTS_PATH = "/api/heimdal/capture/receipts"
RECEIPT_QUERY_MAX_IDS = 100
NULL_CAPTURE_ID = "00000000-0000-4000-8000-000000000000"
RECOVERY_QUEUE_WAIT_S = 1.0

ACTIVITY_CLASSES = ("conversation", "solo_speech", "ambient", "quiet", "silence")

# Relative activity weights per hour of a declared day, in ACTIVITY_CLASSES
# order: a meeting-heavy morning, a quieter midday, conversation again in the
# afternoon. Hours past the table reuse its last row.
DAY_PROFILE: Tuple[Tuple[int, int, int, int, int], ...] = (
    (2, 2, 3, 2, 1),
    (5, 1, 2, 1, 1),
    (4, 2, 2, 1, 1),
    (1, 2, 3, 3, 1),
    (2, 1, 4, 2, 1),
    (4, 2, 2, 1, 1),
    (3, 3, 2, 1, 1),
    (1, 1, 3, 3, 2),
)

ENCODER_ARGS = (
    "-ac", "1", "-ar", "16000",
    "-c:a", "libopus", "-b:a", "24k", "-application", "voip",
    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
    "-f", "ogg",
)

# What a phone-tier simulation of the downstream path can never establish.
WEARABLE_UNPROVEN: Tuple[Dict[str, str], ...] = (
    {"question": "battery_life", "why": "no pendant radio or battery is in the loop; a replayed trace draws no device power"},
    {"question": "ble_link_dropout_and_reconnect", "why": "segments enter at the phone-tier uploader; no BLE link, frame loss or reconnect exists in the run"},
    {"question": "phone_presence_and_background_audio", "why": "no iPhone app receives or holds the stream; iOS background/suspension behaviour is unexercised (the BLE receiver is Bifrost B3 scope, G3)"},
    {"question": "wearability_and_real_wearing_sessions", "why": "nothing is worn; comfort, placement, audio pickup quality and real-day usage are unobserved"},
)


# ---------------------------------------------------------------------------
# Trace generation
# ---------------------------------------------------------------------------


def day_schedule(hours: float, segment_seconds: int, seed: int) -> List[str]:
    """Deterministic activity class per segment for a declared day."""

    count = int(round(hours * 3600 / segment_seconds))
    rng = random.Random(seed)
    schedule = []
    for index in range(count):
        hour = min(int(index * segment_seconds // 3600), len(DAY_PROFILE) - 1)
        schedule.append(rng.choices(ACTIVITY_CLASSES, weights=DAY_PROFILE[hour])[0])
    return schedule


def segment_filter(activity: str, segment_seconds: int, segment_seed: int) -> str:
    """The lavfi source graph for one synthetic segment (shaped noise, no speech)."""

    rng = random.Random(segment_seed)
    phase_a, phase_b = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    noise_seed = segment_seed % 2_147_483_647
    duration = f"d={segment_seconds}"
    if activity == "conversation":
        return (
            f"anoisesrc=c=pink:seed={noise_seed}:r=16000:{duration}:a=0.35,"
            f"volume='0.12+0.88*gt(sin(2*PI*3.7*t+{phase_a:.3f})*sin(2*PI*0.23*t+{phase_b:.3f}),0)':eval=frame"
        )
    if activity == "solo_speech":
        return (
            f"anoisesrc=c=pink:seed={noise_seed}:r=16000:{duration}:a=0.3,"
            f"volume='0.05+0.95*gt(sin(2*PI*4.4*t+{phase_a:.3f}),0.2)*gt(sin(2*PI*0.11*t+{phase_b:.3f}),-0.4)':eval=frame"
        )
    if activity == "ambient":
        return f"anoisesrc=c=brown:seed={noise_seed}:r=16000:{duration}:a=0.08"
    if activity == "quiet":
        return f"anoisesrc=c=white:seed={noise_seed}:r=16000:{duration}:a=0.004"
    if activity == "silence":
        return f"anullsrc=r=16000:cl=mono:{duration}"
    raise ValueError(f"unknown activity class {activity!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trace_digest(segments: Sequence[Dict[str, Any]]) -> str:
    """Order-sensitive identity of a trace: index, activity and content hash."""

    digest = hashlib.sha256()
    for segment in segments:
        digest.update(f"{segment['index']}:{segment['activity']}:{segment['sha256']}\n".encode())
    return digest.hexdigest()


def ffmpeg_version(ffmpeg: str) -> str:
    out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True).stdout
    return out.splitlines()[0] if out else "unknown"


def cmd_generate(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"refusing to overwrite non-empty trace dir {out_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    schedule = day_schedule(args.hours, args.segment_seconds, args.seed)
    segments = []
    for index, activity in enumerate(schedule):
        name = f"seg-{index:05d}.ogg"
        target = out_dir / name
        graph = segment_filter(activity, args.segment_seconds, args.seed * 100_000 + index)
        subprocess.run(
            [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", graph,
             *ENCODER_ARGS, str(target)],
            check=True,
        )
        segments.append({
            "index": index,
            "file": name,
            "activity": activity,
            "duration_s": args.segment_seconds,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        })
    manifest = {
        "schema": TRACE_SCHEMA,
        "generator": {
            "script": "scripts/heimdal_g1_simulation.py generate",
            "seed": args.seed,
            "hours": args.hours,
            "segment_seconds": args.segment_seconds,
            "encoder": list(ENCODER_ARGS),
            "ffmpeg": ffmpeg_version(args.ffmpeg),
            "content": "synthetic shaped noise and silence; no recording, speech or personal data",
        },
        "segment_count": len(segments),
        "total_bytes": sum(s["bytes"] for s in segments),
        "total_audio_s": sum(s["duration_s"] for s in segments),
        "activity_counts": {c: schedule.count(c) for c in ACTIVITY_CLASSES},
        "trace_sha256": trace_digest(segments),
        "segments": segments,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("segment_count", "total_bytes", "total_audio_s", "trace_sha256")}))
    return 0


def load_manifest(trace_dir: Path) -> Dict[str, Any]:
    manifest = json.loads((trace_dir / "manifest.json").read_text())
    if manifest.get("schema") != TRACE_SCHEMA:
        raise SystemExit(f"{trace_dir}/manifest.json is not a {TRACE_SCHEMA} manifest")
    if trace_digest(manifest["segments"]) != manifest["trace_sha256"]:
        raise SystemExit("trace manifest digest mismatch")
    return manifest


# ---------------------------------------------------------------------------
# Uplink model and transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outage:
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    @classmethod
    def parse(cls, spec: str) -> "Outage":
        """``START_MIN:DURATION_MIN`` in simulated minutes from day start."""

        start, duration = spec.split(":")
        return cls(float(start) * 60, float(duration) * 60)


def outage_at(outages: Sequence[Outage], sim_s: float) -> Optional[Outage]:
    for outage in outages:
        if outage.start_s <= sim_s < outage.end_s:
            return outage
    return None


@dataclass
class Attempt:
    status: Optional[int]
    error: Optional[str]
    connect_s: float = 0.0
    upload_s: float = 0.0
    server_s: float = 0.0
    total_s: float = 0.0
    body: Dict[str, Any] = field(default_factory=dict)


class Hub:
    """Stdlib HTTP client; one fresh connection per request, like a phone uploader."""

    def __init__(self, base_url: str, timeout: float) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname:
            raise SystemExit("base URL must be http://host:port (tailnet/LAN only)")
        self.host = parts.hostname
        self.port = parts.port or 80
        self.timeout = timeout

    def _do(self, method: str, path: str, body: Optional[bytes], headers: Dict[str, str]) -> Attempt:
        start = time.perf_counter()
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.connect()
            connected = time.perf_counter()
            conn.request(method, path, body=body, headers=headers)
            uploaded = time.perf_counter()
            resp = conn.getresponse()
            first_byte = time.perf_counter()
            raw = resp.read()
            done = time.perf_counter()
        except (OSError, http.client.HTTPException) as exc:
            return Attempt(status=None, error=type(exc).__name__, total_s=time.perf_counter() - start)
        finally:
            conn.close()
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            parsed = {"unparseable": True}
        return Attempt(
            status=resp.status,
            error=None,
            connect_s=connected - start,
            upload_s=uploaded - connected,
            server_s=first_byte - uploaded,
            total_s=done - start,
            body=parsed if isinstance(parsed, dict) else {"value": parsed},
        )

    def post_media(self, media: bytes, sidecar: Dict[str, Any], filename: str) -> Attempt:
        boundary = f"g1sim-{uuid.uuid4().hex}"
        body = b"".join([
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{filename}\"\r\n"
             "Content-Type: audio/ogg\r\n\r\n").encode() + media + b"\r\n",
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"sidecar\"; filename=\"sidecar.json\"\r\n"
             "Content-Type: application/json\r\n\r\n").encode() + json.dumps(sidecar).encode() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        return self._do("POST", MEDIA_PATH, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def query_receipts(self, capture_ids: Sequence[str]) -> Attempt:
        query = urlencode([("capture_id", cid) for cid in capture_ids])
        return self._do("GET", f"{RECEIPTS_PATH}?{query}", None, {})


def retryable(attempt: Attempt) -> bool:
    return attempt.status is None or attempt.status >= 500


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _sample(cmd: Optional[str]) -> Optional[Dict[str, Any]]:
    if not cmd:
        return None
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=False)
    try:
        sample = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"sample command exited {proc.returncode} without JSON"}
    sample["at"] = _iso(datetime.now(timezone.utc))
    return sample


def cmd_run(args: argparse.Namespace) -> int:
    trace_dir = Path(args.trace_dir)
    manifest = load_manifest(trace_dir)
    segments = manifest["segments"][: args.limit] if args.limit else manifest["segments"]
    segment_s = manifest["generator"]["segment_seconds"]
    outages = sorted((Outage.parse(spec) for spec in args.outage), key=lambda o: o.start_s)
    drops = set(args.drop_index)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / f"{args.role}-events.jsonl"
    hub = Hub(args.base_url, args.request_timeout)
    day_start = datetime.fromisoformat(args.day_start.replace("Z", "+00:00"))
    pace = args.pace

    samples: List[Dict[str, Any]] = []
    probes: List[float] = []
    records: List[Dict[str, Any]] = []
    restart: Dict[str, Any] = {}
    first_sample = _sample(args.host_sample_cmd)
    if first_sample:
        samples.append(first_sample)

    started_wall = time.time()
    t0 = time.perf_counter()

    def sim_now() -> float:
        return (time.perf_counter() - t0) * pace if pace > 0 else float("inf")

    def wall_for_sim(sim_s: float) -> float:
        return t0 + sim_s / pace if pace > 0 else t0

    with events_path.open("w") as events:

        def log(event: Dict[str, Any]) -> None:
            events.write(json.dumps(event) + "\n")
            events.flush()

        def deliver(segment: Dict[str, Any], sidecar: Dict[str, Any], media: bytes) -> Tuple[Optional[Attempt], int, float]:
            attempts = 0
            first_failure: Optional[float] = None
            while attempts < args.max_attempts:
                attempts += 1
                attempt = hub.post_media(media, sidecar, segment["file"])
                log({"kind": "attempt", "index": segment["index"], "n": attempts, "status": attempt.status,
                     "error": attempt.error, "connect_s": attempt.connect_s, "upload_s": attempt.upload_s,
                     "server_s": attempt.server_s, "total_s": attempt.total_s,
                     "error_code": (attempt.body.get("detail") or {}).get("error")
                     if isinstance(attempt.body.get("detail"), dict) else None})
                if not retryable(attempt):
                    unavailable = 0.0 if first_failure is None else time.perf_counter() - first_failure
                    return attempt, attempts, unavailable
                if first_failure is None:
                    first_failure = time.perf_counter()
                time.sleep(min(0.5 * 2 ** (attempts - 1), args.max_backoff))
            unavailable = 0.0 if first_failure is None else time.perf_counter() - first_failure
            return None, attempts, unavailable

        pending: List[Dict[str, Any]] = []
        next_index = 0
        while next_index < len(segments) or pending:
            now_sim = sim_now()
            while next_index < len(segments) and (next_index + 1) * segment_s <= now_sim:
                pending.append(segments[next_index])
                next_index += 1
            if not pending:
                time.sleep(max(0.0, wall_for_sim((next_index + 1) * segment_s) - time.perf_counter()))
                continue
            outage = outage_at(outages, now_sim)
            if outage is not None:
                time.sleep(max(0.01, wall_for_sim(outage.end_s) - time.perf_counter()))
                continue

            segment = pending.pop(0)
            index = segment["index"]
            ready_sim = (index + 1) * segment_s
            ready_wall = wall_for_sim(ready_sim)
            blocking = outage_at(outages, ready_sim)
            uplink_wait_sim = (blocking.end_s - ready_sim) if blocking else 0.0
            restored_wall = wall_for_sim(blocking.end_s) if blocking else ready_wall
            record: Dict[str, Any] = {
                "index": index, "activity": segment["activity"], "bytes": segment["bytes"],
                "buffered_by_outage": blocking is not None, "uplink_wait_sim_s": uplink_wait_sim,
                "ready_sim_s": ready_sim,
            }
            if index in drops:
                record.update({"outcome": "dropped_by_design"})
                records.append(record)
                log({"kind": "dropped_by_design", "index": index})
                continue

            if args.restart_at_index is not None and index == args.restart_at_index and not restart:
                restart["requested_at_index"] = index
                restart["requested_wall_offset_s"] = time.perf_counter() - t0
                proc = subprocess.run(shlex.split(args.restart_cmd), capture_output=True, text=True, check=False)
                restart["restart_cmd_exit"] = proc.returncode
                log({"kind": "restart", "index": index, "exit": proc.returncode})

            media = (trace_dir / segment["file"]).read_bytes()
            sidecar = {
                "capture_id": str(uuid.uuid4()),
                "content_sha256": segment["sha256"],
                "kind": "audio",
                "captured_at": _iso(day_start + timedelta(seconds=index * segment_s)),
                "device_id": args.device_id,
                "schema_version": 1,
                "g1_simulation": {"run_id": args.run_id, "role": args.role, "segment_index": index},
            }
            send_start = time.perf_counter()
            attempt, attempts, unavailable_s = deliver(segment, sidecar, media)
            receipt_at = time.perf_counter()
            body = attempt.body if attempt else {}
            record.update({
                "capture_id": sidecar["capture_id"],
                "attempts": attempts,
                "status": attempt.status if attempt else None,
                "outcome": body.get("outcome") or "failed",
                "receipt_id": body.get("receipt_id"),
                "content_sha256_echo_ok": body.get("content_sha256") == segment["sha256"],
                "queue_wait_s": send_start - ready_wall,
                "request_s": attempt.total_s if attempt else None,
                "connect_s": attempt.connect_s if attempt else None,
                "upload_s": attempt.upload_s if attempt else None,
                "server_s": attempt.server_s if attempt else None,
                "e2e_wall_s": receipt_at - ready_wall,
                "e2e_equiv_s": uplink_wait_sim + (receipt_at - max(ready_wall, restored_wall)),
                "unavailable_s": unavailable_s,
                "after_restart": bool(restart) and attempts > 1,
            })
            if restart and attempts > 1 and "client_unavailable_s" not in restart:
                restart["client_unavailable_s"] = unavailable_s
                restart["attempts"] = attempts

            if args.duplicate_every and record["outcome"] == "admitted" and index % args.duplicate_every == 0:
                dup = hub.post_media(media, sidecar, segment["file"])
                record["duplicate"] = {
                    "status": dup.status,
                    "idempotent_replay": bool(dup.body.get("idempotent_replay")),
                    "same_receipt": dup.body.get("receipt_id") == record["receipt_id"],
                }
                log({"kind": "duplicate", "index": index, "status": dup.status,
                     "idempotent_replay": record["duplicate"]["idempotent_replay"]})
            records.append(record)

            if args.probe_every and index % args.probe_every == 0:
                probe = hub.query_receipts([NULL_CAPTURE_ID])
                if probe.status == 200:
                    probes.append(probe.total_s)
            if args.sample_every and index % args.sample_every == 0 and index:
                sample = _sample(args.host_sample_cmd)
                if sample:
                    samples.append(sample)

    finished_wall = time.time()
    reconciliation = reconcile(hub, records)
    last_sample = _sample(args.host_sample_cmd)
    if last_sample:
        samples.append(last_sample)

    run = {
        "schema": RUN_SCHEMA,
        "run_id": args.run_id,
        "role": args.role,
        "host_label": args.host_label,
        "image_ref": args.image_ref,
        "trace_sha256": manifest["trace_sha256"],
        "trace_generator": manifest["generator"],
        "segment_seconds": segment_s,
        "segments_in_run": len(segments),
        "pace": pace,
        "outages": [{"start_s": o.start_s, "duration_s": o.duration_s} for o in outages],
        "drop_index": sorted(drops),
        "duplicate_every": args.duplicate_every,
        "restart": restart,
        "started_at": _iso(datetime.fromtimestamp(started_wall, timezone.utc)),
        "finished_at": _iso(datetime.fromtimestamp(finished_wall, timezone.utc)),
        "wall_s": finished_wall - started_wall,
        "records": records,
        "probes_s": probes,
        "host_samples": samples,
        "reconciliation": reconciliation,
    }
    (out_dir / f"{args.role}-run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(json.dumps(summarize(run)["counts"]))
    return 0


def reconcile(hub: Hub, records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Ask the hub, in bounded batches, which expected originals it holds."""

    expected = [r for r in records if r.get("capture_id")]
    answers: Dict[str, str] = {}
    errors = 0
    for offset in range(0, len(expected), RECEIPT_QUERY_MAX_IDS):
        batch = [r["capture_id"] for r in expected[offset: offset + RECEIPT_QUERY_MAX_IDS]]
        attempt = hub.query_receipts(batch)
        if attempt.status != 200:
            errors += 1
            continue
        for answer in attempt.body.get("receipts", []):
            answers[answer["capture_id"]] = answer.get("outcome", "unknown")
    admitted = sum(1 for r in expected if answers.get(r["capture_id"]) == "admitted")
    return {
        "queried": len(expected),
        "admitted": admitted,
        "not_admitted_indexes": sorted(r["index"] for r in expected if answers.get(r["capture_id"]) != "admitted"),
        "query_errors": errors,
    }


# ---------------------------------------------------------------------------
# Summary and receipt (pure; unit-tested)
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def dist(values: Iterable[Optional[float]]) -> Dict[str, Optional[float]]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"n": 0, "p50": None, "p90": None, "p99": None, "max": None, "mean": None}
    return {
        "n": len(clean),
        "p50": round(percentile(clean, 50), 4),
        "p90": round(percentile(clean, 90), 4),
        "p99": round(percentile(clean, 99), 4),
        "max": round(max(clean), 4),
        "mean": round(statistics.fmean(clean), 4),
    }


def gap_runs(indexes: Sequence[int]) -> List[Tuple[int, int]]:
    """Contiguous runs of missing segment indexes as ``(first, last)`` pairs."""

    runs: List[Tuple[int, int]] = []
    for index in sorted(set(indexes)):
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def summarize(run: Dict[str, Any]) -> Dict[str, Any]:
    records = run["records"]
    segment_s = run["segment_seconds"]
    # Keyed on `attempts`, not `capture_id`: summaries also run over redacted runs.
    sent = [r for r in records if "attempts" in r]
    admitted = [r for r in sent if r.get("outcome") == "admitted"]
    failed = [r for r in sent if r.get("outcome") != "admitted"]
    dropped = [r["index"] for r in records if r.get("outcome") == "dropped_by_design"]
    # Steady state: delivered on first try and sent as soon as ready. A segment that
    # became ready while a backlog or restart was still draining is recovery traffic.
    steady = [
        r for r in admitted
        if not r["buffered_by_outage"] and r["attempts"] == 1 and r["queue_wait_s"] < RECOVERY_QUEUE_WAIT_S
    ]
    recovery = [r for r in admitted if r not in steady and not r["buffered_by_outage"]]
    buffered = [r for r in admitted if r["buffered_by_outage"]]
    retried = [r for r in admitted if r["attempts"] > 1]
    dups = [r["duplicate"] for r in records if r.get("duplicate")]
    recon = run["reconciliation"]
    missing = sorted(set(recon["not_admitted_indexes"]) | set(dropped))

    backlog = []
    for outage in run["outages"]:
        held = [r for r in buffered if outage["start_s"] <= r["ready_sim_s"] < outage["start_s"] + outage["duration_s"]]
        if held:
            backlog.append({
                "outage_sim_s": outage["duration_s"],
                "segments_buffered": len(held),
                "drain_wall_s": round(max(r["e2e_equiv_s"] - r["uplink_wait_sim_s"] for r in held), 3),
                "max_e2e_equiv_s": round(max(r["e2e_equiv_s"] for r in held), 3),
            })

    total_bytes = sum(r["bytes"] for r in admitted)
    upload_time = sum(r["request_s"] or 0 for r in admitted)
    samples = [s for s in run.get("host_samples", []) if "db_bytes" in s]
    host = {}
    if len(samples) >= 2:
        first, last = samples[0], samples[-1]
        audio_h = len(admitted) * segment_s / 3600
        host = {
            "db_growth_bytes": (last.get("db_bytes") or 0) - (first.get("db_bytes") or 0),
            "db_growth_bytes_per_audio_hour": round(((last.get("db_bytes") or 0) - (first.get("db_bytes") or 0)) / audio_h)
            if audio_h else None,
            "disk_used_delta_mb": last["disk"]["used_mb"] - first["disk"]["used_mb"],
            "disk_use_pct_end": last["disk"]["use_pct"],
            "api_mem_samples": [s.get("api_mem") for s in samples],
            "api_restart_count_end": last.get("api_restart_count"),
            "raw_rows_end": last.get("raw_rows"),
            "receipt_rows_end": last.get("receipt_rows"),
        }

    return {
        "counts": {
            "segments": len(records),
            "sent": len(sent),
            "admitted": len(admitted),
            "failed": len(failed),
            "dropped_by_design": len(dropped),
            "reconciled_admitted": recon["admitted"],
            "reconcile_query_errors": recon["query_errors"],
            "retried_segments": len(retried),
            "duplicates_sent": len(dups),
            "duplicates_idempotent": sum(1 for d in dups if d["status"] == 200 and d["idempotent_replay"] and d["same_receipt"]),
            "hash_echo_mismatches": sum(1 for r in admitted if not r["content_sha256_echo_ok"]),
        },
        "latency_s": {
            "steady_e2e": dist(r["e2e_wall_s"] for r in steady),
            "steady_request": dist(r["request_s"] for r in steady),
            "steady_connect": dist(r["connect_s"] for r in steady),
            "steady_upload_write": dist(r["upload_s"] for r in steady),
            "steady_server_ttfb": dist(r["server_s"] for r in steady),
            "recovery_tail_e2e": dist(r["e2e_wall_s"] for r in recovery),
            "all_e2e_equiv": dist(r["e2e_equiv_s"] for r in admitted),
            "rtt_probe": dist(run.get("probes_s", [])),
        },
        "transfer": {
            "admitted_bytes": total_bytes,
            "admitted_mb": round(total_bytes / 1e6, 3),
            "effective_rate_kbit_s": round(total_bytes * 8 / 1000 / upload_time, 1) if upload_time else None,
            "audio_s_admitted": len(admitted) * segment_s,
        },
        "gaps": {
            "missing_runs": [{"first": a, "last": b, "seconds": (b - a + 1) * segment_s} for a, b in gap_runs(missing)],
            "missing_equals_dropped": missing == sorted(dropped),
            "backlog_episodes": backlog,
            "restart": run.get("restart") or {},
        },
        "host": host,
        "wall_s": round(run["wall_s"], 1),
        "pace": run["pace"],
    }


def interpret(main: Dict[str, Any], segment_s: int) -> Dict[str, Any]:
    """Pass/fail for the simulated downstream path only -- never a G1 verdict."""

    counts = main["counts"]
    steady_p99 = main["latency_s"]["steady_e2e"]["p99"]
    checks = {
        "zero_lost_originals": counts["failed"] == 0 and counts["reconciled_admitted"] == counts["admitted"],
        "zero_duplicates": counts["duplicates_idempotent"] == counts["duplicates_sent"] and counts["hash_echo_mismatches"] == 0,
        "gaps_legible": main["gaps"]["missing_equals_dropped"],
        "keeps_up_with_real_time": steady_p99 is not None and steady_p99 < segment_s,
        "backlog_recovers": all(b["drain_wall_s"] < b["outage_sim_s"] for b in main["gaps"]["backlog_episodes"]),
        "no_manual_action_during_run": counts["failed"] == 0,
    }
    return {"checks": checks, "simulated_path": "pass" if all(checks.values()) else "fail"}


def build_receipt(main_run: Dict[str, Any], calibration_run: Optional[Dict[str, Any]],
                  setup: Dict[str, Any]) -> Dict[str, Any]:
    main = summarize(main_run)
    segment_s = main_run["segment_seconds"]
    calibration = summarize(calibration_run) if calibration_run else None
    split = None
    if calibration:
        tailnet = main["latency_s"]["steady_request"]["p50"]
        on_host = calibration["latency_s"]["steady_request"]["p50"]
        if tailnet is not None and on_host is not None:
            split = {
                "request_p50_tailnet_s": tailnet,
                "request_p50_on_host_s": on_host,
                "processing_share_p50_s": on_host,
                "transfer_share_p50_s": round(max(tailnet - on_host, 0.0), 4),
            }
    verdict = interpret(main, segment_s)
    return {
        "schema": RECEIPT_SCHEMA,
        "issue": "RasmusTho/agentic-pkm-mvp#3408",
        "gate": "ADR-0060 §4 G1 (device feasibility)",
        "g1_status": "unmet",
        "run_id": main_run["run_id"],
        "plan": {
            "source_input": {
                "kind": "synthetic deterministic day-like trace (shaped noise and silence)",
                "trace_sha256": main_run["trace_sha256"],
                "generator": main_run["trace_generator"],
            },
            "duration": {"audio_s": main_run["segments_in_run"] * segment_s, "segment_s": segment_s,
                         "pace": main_run["pace"], "wall_s": main["wall_s"]},
            "transport_path": (
                "operator machine (phone-tier uploader stand-in) -> tailnet -> "
                f"{main_run['host_label']} -> POST {MEDIA_PATH} (shipped CDLM-01 admission) -> "
                "consent admission -> AES-GCM raw store -> outbox event -> durable receipt; "
                f"reconciled via GET {RECEIPTS_PATH}"
            ),
            "instance": setup,
            "faults_injected": {
                "uplink_outages_sim_s": [o["duration_s"] for o in main_run["outages"]],
                "api_restart_at_index": (main_run.get("restart") or {}).get("requested_at_index"),
                "dropped_by_design": len(main_run["drop_index"]),
                "duplicate_every": main_run["duplicate_every"],
            },
            "redaction": (
                "no audio, transcript, capture/receipt ids, keys, DSNs or addresses are retained; "
                "counts, hashes and timings only; trace is synthetic"
            ),
            "interpretation": (
                "simulated_path=pass iff zero lost originals, zero duplicates, missing set equals the "
                "by-design drops, steady-state p99 end-to-end < segment duration, every backlog drains "
                "faster than the outage that built it, and no operator action during the run. "
                "This judges the downstream path only; G1 stays unmet."
            ),
        },
        "measurements": main,
        "calibration_on_host": calibration,
        "transfer_vs_processing": split,
        "operational_burden": {
            "manual_actions_during_run": 0 if verdict["checks"]["no_manual_action_during_run"] else None,
            "setup_steps": setup.get("operator_steps"),
            "host": main["host"],
        },
        "verdict": verdict,
        "wearable_questions_unproven": list(WEARABLE_UNPROVEN),
        "loan_materiality": (
            "material, later and narrowly: the simulated path leaves only the four device-specific "
            "questions above open. A short loan of a compatible BLE wearable should measure exactly "
            "those, and is only meaningful once a local BLE receive client exists (Bifrost B3 / G3), "
            "because a vendor app's cloud path would violate the local-only constraint."
        ),
    }


def render_markdown(receipt: Dict[str, Any]) -> str:
    m = receipt["measurements"]
    c = m["counts"]
    lat = m["latency_s"]
    lines = [
        f"## `{receipt['schema']}` — {receipt['run_id']}",
        "",
        f"**G1 status: {receipt['g1_status']}.** Simulated downstream path: **{receipt['verdict']['simulated_path']}**.",
        "This run says nothing about wearable battery, BLE link behaviour, phone presence or wearability.",
        "",
        "### Plan",
        f"- Input: {receipt['plan']['source_input']['kind']}; trace `sha256:{receipt['plan']['source_input']['trace_sha256'][:16]}…`",
        f"- Duration: {receipt['plan']['duration']['audio_s'] / 3600:.1f} h audio in {receipt['plan']['duration']['segment_s']} s segments, pace ×{receipt['plan']['duration']['pace']} ({receipt['plan']['duration']['wall_s'] / 60:.1f} min wall)",
        f"- Path: {receipt['plan']['transport_path']}",
        f"- Faults: {json.dumps(receipt['plan']['faults_injected'])}",
        f"- Redaction: {receipt['plan']['redaction']}",
        "",
        "### Measurements",
        f"- Segments {c['segments']}: admitted {c['admitted']}, failed {c['failed']}, dropped by design {c['dropped_by_design']}, reconciled admitted {c['reconciled_admitted']}",
        f"- Duplicates: {c['duplicates_idempotent']}/{c['duplicates_sent']} idempotent replays; hash-echo mismatches {c['hash_echo_mismatches']}; retried segments {c['retried_segments']}",
        f"- Steady-state end-to-end (segment ready → durable receipt): p50 {lat['steady_e2e']['p50']} s, p90 {lat['steady_e2e']['p90']} s, p99 {lat['steady_e2e']['p99']} s, max {lat['steady_e2e']['max']} s (n={lat['steady_e2e']['n']})",
        f"- Recovery tail (ready while a backlog/restart drained, first-try delivery): p50 {lat['recovery_tail_e2e']['p50']} s, max {lat['recovery_tail_e2e']['max']} s (n={lat['recovery_tail_e2e']['n']})",
        f"- Request split (p50): connect {lat['steady_connect']['p50']} s, upload write {lat['steady_upload_write']['p50']} s, server TTFB {lat['steady_server_ttfb']['p50']} s; RTT probe p50 {lat['rtt_probe']['p50']} s",
        f"- Transfer: {m['transfer']['admitted_mb']} MB admitted, effective {m['transfer']['effective_rate_kbit_s']} kbit/s per request",
    ]
    if receipt.get("transfer_vs_processing"):
        s = receipt["transfer_vs_processing"]
        lines.append(f"- Transfer vs processing (p50): processing ≈ {s['processing_share_p50_s']} s (on-host), tailnet transfer ≈ {s['transfer_share_p50_s']} s")
    lines += [
        f"- Gaps: missing runs {json.dumps(m['gaps']['missing_runs'])}; missing set equals by-design drops: {m['gaps']['missing_equals_dropped']}",
        f"- Backlog episodes: {json.dumps(m['gaps']['backlog_episodes'])}",
        f"- API restart: {json.dumps(m['gaps']['restart'])}",
        f"- Host: {json.dumps(m['host'])}",
        "",
        "### Operational burden",
        f"- Manual actions during run: {receipt['operational_burden']['manual_actions_during_run']}; setup steps: {receipt['operational_burden']['setup_steps']}",
        "",
        "### Verdict checks (simulated path only)",
    ]
    lines += [f"- [{'x' if ok else ' '}] `{name}`" for name, ok in receipt["verdict"]["checks"].items()]
    lines += ["", "### Wearable-specific questions this cannot prove"]
    lines += [f"- `{q['question']}` — {q['why']}" for q in receipt["wearable_questions_unproven"]]
    lines += ["", f"**Loan materiality:** {receipt['loan_materiality']}", ""]
    return "\n".join(lines)


def strip_private(run: Dict[str, Any]) -> Dict[str, Any]:
    """Drop per-segment identifiers before anything leaves the operator machine."""

    redacted = dict(run)
    redacted["records"] = [
        {k: v for k, v in r.items() if k not in {"capture_id", "receipt_id"}} for r in run["records"]
    ]
    return redacted


def cmd_report(args: argparse.Namespace) -> int:
    main_run = json.loads(Path(args.main_run).read_text())
    calibration_run = json.loads(Path(args.calibration_run).read_text()) if args.calibration_run else None
    setup = json.loads(Path(args.setup).read_text()) if args.setup else {}
    receipt = build_receipt(strip_private(main_run), strip_private(calibration_run) if calibration_run else None, setup)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "heimdal.g1-simulation.v1.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (out_dir / "receipt.md").write_text(render_markdown(receipt))
    print(json.dumps({"verdict": receipt["verdict"]["simulated_path"], "g1_status": receipt["g1_status"]}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="render the synthetic day-like trace")
    gen.add_argument("--out-dir", required=True)
    gen.add_argument("--hours", type=float, default=8.0)
    gen.add_argument("--segment-seconds", type=int, default=60)
    gen.add_argument("--seed", type=int, default=3408)
    gen.add_argument("--ffmpeg", default="ffmpeg")
    gen.set_defaults(func=cmd_generate)

    run = sub.add_parser("run", help="paced replay through the governed media route")
    run.add_argument("--trace-dir", required=True)
    run.add_argument("--base-url", required=True, help="http://<tailnet-or-LAN-host>:<port>")
    run.add_argument("--out-dir", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--role", choices=("main", "calibration"), default="main")
    run.add_argument("--host-label", default="ygg-test")
    run.add_argument("--image-ref", default="unknown")
    run.add_argument("--pace", type=float, default=8.0, help="sim seconds per wall second; 0 = unpaced")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--day-start", default="2026-10-27T07:00:00Z")
    run.add_argument("--outage", action="append", default=[], help="START_MIN:DURATION_MIN (sim time)")
    run.add_argument("--drop-index", action="append", type=int, default=[])
    run.add_argument("--duplicate-every", type=int, default=0)
    run.add_argument("--restart-at-index", type=int, default=None)
    run.add_argument("--restart-cmd", default="")
    run.add_argument("--host-sample-cmd", default="")
    run.add_argument("--sample-every", type=int, default=30)
    run.add_argument("--probe-every", type=int, default=10)
    run.add_argument("--device-id", default="g1-sim-phone-tier-uploader")
    run.add_argument("--request-timeout", type=float, default=60.0)
    run.add_argument("--max-attempts", type=int, default=40)
    run.add_argument("--max-backoff", type=float, default=8.0)
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="build the redacted heimdal.g1-simulation.v1 receipt")
    rep.add_argument("--main-run", required=True)
    rep.add_argument("--calibration-run", default=None)
    rep.add_argument("--setup", default=None, help="JSON describing the isolated instance and operator steps")
    rep.add_argument("--out-dir", required=True)
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    if args.command == "run" and args.restart_at_index is not None and not args.restart_cmd:
        parser.error("--restart-at-index requires --restart-cmd")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
