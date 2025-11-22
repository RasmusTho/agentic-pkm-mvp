from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict

import yaml

from .policy import pick_target as _pick_target
from app.events.types import (
    PROMOTE_DONE,
    PROMOTE_ERROR,
    PROMOTE_ORPHAN_OVERRIDE,
    PROMOTE_SKIP_DECODE,
    PROMOTE_SKIP_MISSING,
    PROMOTE_SKIP_ORPHAN,
    PROMOTE_SKIP_RELATIONS,
    PROMOTE_SKIP_MOVE,
)
from app.observability.tracing import current_trace_id, span
from app.promotion.gates import OrphanPromotionError, ensure_object_has_relations, prepare_relations_for_promotion
from app.settings.models import PromotionSettings, SettingsBundle
from app.settings.runtime import subscribe_settings
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

ROOT = Path().resolve()
VAULT = ROOT / "vault"
EVENTS = VAULT / "_system" / "events"
QUEUE = EVENTS / "promote.queue.jsonl"
LOG   = EVENTS / "promote.log.jsonl"
SETTINGS = ROOT / "vault" / "_system" / "settings" / "system-settings.yaml"
_PROMOTION_SETTINGS = PromotionSettings()
_NOTE_MOVES_ENABLED = False


def _apply_promotion_settings(bundle: SettingsBundle) -> None:
    global _PROMOTION_SETTINGS
    candidate = bundle.agents.get("promotion") if bundle else None
    if isinstance(candidate, PromotionSettings):
        _PROMOTION_SETTINGS = candidate
    else:
        _PROMOTION_SETTINGS = PromotionSettings()


def _apply_global_settings(bundle: SettingsBundle) -> None:
    global _NOTE_MOVES_ENABLED
    try:
        _NOTE_MOVES_ENABLED = bool(bundle.global_.note_moves_enable)
    except Exception:
        _NOTE_MOVES_ENABLED = False


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def enqueue(path: Path, uuid: str, desired_state: str = "promoted") -> None:
    _append_jsonl(QUEUE, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trace_id": current_trace_id() or hashlib.sha1(f"{uuid}{path}".encode()).hexdigest()[:12],
        "uuid": uuid,
        "path": str(path),
        "desired_state": desired_state,
        "retries": 0
    })


def _load_settings() -> Dict[str, Any]:
    if not SETTINGS.exists():
        return {}
    return yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}


def _safe_move(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        stem, suff = dst.stem, dst.suffix
        i = 1
        while (dst_dir / f"{stem}-{i}{suff}").exists():
            i += 1
        dst = dst_dir / f"{stem}-{i}{suff}"
    shutil.move(str(src), str(dst))
    return dst


def _move_policy_dict(promo: PromotionSettings, legacy: Dict[str, Any]) -> Dict[str, Any]:
    policy = legacy.get("move_policy")
    if isinstance(policy, dict) and policy:
        return policy
    return promo.move_policy.model_dump()


subscribe_settings(_apply_promotion_settings)
subscribe_settings(_apply_global_settings)


def run_once() -> int:
    if not QUEUE.exists():
        return 0
    legacy = (_load_settings().get("promotion") or {})
    promo_cfg = _PROMOTION_SETTINGS
    cooldown = int(legacy.get("cooldown_seconds", promo_cfg.cooldown_seconds))
    idle_req = int(legacy.get("require_idle_seconds", promo_cfg.require_idle_seconds))
    max_retries = int(legacy.get("max_retries", promo_cfg.max_retries))
    move_policy = _move_policy_dict(promo_cfg, legacy)
    note_moves_allowed = _NOTE_MOVES_ENABLED

    lines = QUEUE.read_text(encoding="utf-8").splitlines()
    QUEUE.unlink(missing_ok=True)
    processed = 0

    for ln in lines:
        ev: Dict[str, Any] | None = None
        try:
            with span("worker.process_event"):
                ev = json.loads(ln)
                p = Path(ev["path"])
                if not p.exists():
                    _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "level": "warn", "event": PROMOTE_SKIP_MISSING, "path": str(p),
                                        "uuid": ev.get("uuid"), "trace_id": current_trace_id()})
                    continue

                st = p.stat()
                age = time.time() - st.st_mtime
                if age < cooldown or age < idle_req:
                    _append_jsonl(QUEUE, ev)
                    continue

                uuid = ev.get("uuid")
                with span("worker.read_frontmatter"):
                    frontmatter, body = load_frontmatter(p.read_text(encoding="utf-8"))
                meta = dict(frontmatter)

                if uuid:
                    try:
                        prepare_relations_for_promotion(uuid, metadata=meta, body=body)
                    except OrphanPromotionError as rel_err:
                        _append_jsonl(
                            LOG,
                            {
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "warn",
                                "event": PROMOTE_SKIP_RELATIONS,
                                "uuid": uuid,
                                "path": str(p),
                                "reason": str(rel_err),
                                "trace_id": current_trace_id(),
                            },
                        )
                        continue

                    allow_override = os.getenv("PROMOTION_ALLOW_ORPHANS", "").strip()
                    override_reason = (os.getenv("PROMOTION_ORPHAN_OVERRIDE_REASON") or "").strip()
                    try:
                        ensure_object_has_relations(uuid)
                    except OrphanPromotionError as oom:
                        if allow_override and override_reason:
                            ensure_object_has_relations(
                                uuid,
                                allow_orphans=True,
                                override_reason=override_reason,
                            )
                            _append_jsonl(
                                LOG,
                                {
                                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "level": "info",
                                    "event": PROMOTE_ORPHAN_OVERRIDE,
                                    "uuid": uuid,
                                    "path": str(p),
                                    "reason": override_reason,
                                    "trace_id": current_trace_id(),
                                },
                            )
                        else:
                            _append_jsonl(
                                LOG,
                                {
                                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "level": "warn",
                                    "event": PROMOTE_SKIP_ORPHAN,
                                    "uuid": uuid,
                                    "path": str(p),
                                    "reason": str(oom),
                                    "trace_id": current_trace_id(),
                                },
                            )
                            continue
                meta["review_state"] = ev.get("desired_state", "promoted")

                with span("worker.update_frontmatter"):
                    cleaned_lines = [ln for ln in body.splitlines() if "Promote" not in ln]
                    cleaned_body = "\n".join(cleaned_lines).rstrip("\n")
                    updated = dump_frontmatter(meta, cleaned_body)
                    p.write_text(updated, encoding="utf-8")

                new_p = p
                move_enabled = move_policy.get("enabled", False)
                target_dir: Path | None = None
                if move_enabled:
                    target_rel = _pick_target(meta, move_policy)
                    target_dir = VAULT / target_rel
                if move_enabled and note_moves_allowed:
                    with span("worker.move_file"):
                        new_p = _safe_move(p, target_dir) if target_dir else p
                elif move_enabled and not note_moves_allowed:
                    _append_jsonl(
                        LOG,
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "info",
                            "event": PROMOTE_SKIP_MOVE,
                            "uuid": uuid,
                            "path": str(p),
                            "target": str(target_dir) if target_dir else None,
                            "reason": "note_moves_enable=false",
                            "trace_id": current_trace_id(),
                        },
                    )

                with span("worker.log_done"):
                    _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "level": "info", "event": PROMOTE_DONE,
                                        "uuid": ev.get("uuid"), "from": str(p), "to": str(new_p),
                                        "trace_id": current_trace_id()})
                processed += 1

        except json.JSONDecodeError as e:
            _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "error", "event": PROMOTE_SKIP_DECODE,
                                "raw": ln, "err": repr(e), "trace_id": current_trace_id()})
            continue
        except Exception as e:
            payload = ev if isinstance(ev, dict) else {"raw": ln}
            payload["retries"] = int(payload.get("retries", 0)) + 1
            if payload["retries"] <= max_retries:
                _append_jsonl(QUEUE, payload)
            _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "error", "event": PROMOTE_ERROR,
                                "path": payload.get("path"), "uuid": payload.get("uuid"),
                                "err": repr(e), "retries": payload["retries"],
                                "trace_id": current_trace_id()})
    return processed
