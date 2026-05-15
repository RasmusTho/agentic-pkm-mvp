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
from app.config.paths import resolve_system_settings_path, resolve_vault_root
from app.events.types import (
    PROMOTE_DONE,
    PROMOTE_ERROR,
    PROMOTE_ORPHAN_OVERRIDE,
    PROMOTE_SKIP_DECODE,
    PROMOTE_SKIP_MISSING,
    PROMOTE_SKIP_ORPHAN,
    PROMOTE_SKIP_MOVE,
)
from app.observability.tracing import current_trace_id, span
from app.promotion.gates import OrphanPromotionError, ensure_object_has_relations, prepare_relations_for_promotion
from app.knowledge.write_ops import write_note_from_absolute
from app.settings.models import PromotionSettings, SettingsBundle
from app.settings.runtime import subscribe_settings
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

ROOT = Path().resolve()
VAULT = resolve_vault_root()
EVENTS = VAULT / "_system" / "events"
QUEUE = EVENTS / "promote.queue.jsonl"
LOG = EVENTS / "promote.log.jsonl"
SETTINGS = resolve_system_settings_path()
_PROMOTION_SETTINGS = PromotionSettings()
_NOTE_MOVES_ENABLED = True


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
        _NOTE_MOVES_ENABLED = True


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def enqueue(path: Path, uuid: str, desired_state: str = "promoted") -> None:
    _append_jsonl(
        QUEUE,
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trace_id": current_trace_id() or hashlib.sha256(f"{uuid}{path}".encode()).hexdigest()[:12],
            "uuid": uuid,
            "path": str(path),
            "desired_state": desired_state,
            "retries": 0,
        },
    )


def _load_settings() -> Dict[str, Any]:
    if not SETTINGS or not Path(SETTINGS).exists():
        return {}
    return yaml.safe_load(Path(SETTINGS).read_text(encoding="utf-8")) or {}


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


def _resolve_target_dir(target: Path, note_path: Path) -> Path:
    if target.is_absolute():
        return target
    try:
        base = Path(VAULT)
    except Exception:
        base = note_path.parent
    if base is None:
        base = note_path.parent
    return (base / target).resolve()


def _move_policy_dict(promo: PromotionSettings, legacy: Dict[str, Any]) -> Dict[str, Any]:
    policy = legacy.get("move_policy")
    if isinstance(policy, dict) and policy:
        return policy
    return promo.move_policy.model_dump()


def _select_target(meta: Dict[str, Any], move_policy: Dict[str, Any], legacy_config: Dict[str, Any], note_moves_allowed: bool):
    if not note_moves_allowed:
        return None, "note moves disabled"
    policy = move_policy or {}
    if policy.get("enabled") is False:
        return None, "move policy disabled"
    try:
        target_path = _pick_target(meta, policy)
    except Exception as exc:
        return None, str(exc)
    return target_path, None


def _write_note_via_port(path: Path, content: str) -> None:
    resolved = path.resolve()
    root_candidates = [Path(VAULT).resolve(), Path(resolved.anchor) if resolved.anchor else Path("/")]
    for root in root_candidates:
        try:
            write_note_from_absolute(resolved, content, vault_root=root)
            return
        except ValueError:
            continue
    raise ValueError(f"Unable to resolve note locator for {resolved}")


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
                    _append_jsonl(
                        LOG,
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "warn",
                            "event": PROMOTE_SKIP_MISSING,
                            "path": str(p),
                            "uuid": ev.get("uuid"),
                            "trace_id": current_trace_id(),
                        },
                    )
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
                meta["review_state"] = "promoted"
                body_lines = [ln for ln in (body.splitlines()) if "Promote" not in ln.strip()]
                body = "\n".join(body_lines).lstrip("\n")
                updated_text = dump_frontmatter(meta, body)
                _write_note_via_port(p, updated_text)

                if uuid:
                    try:
                        prepare_relations_for_promotion(uuid, metadata=meta, body=body)
                        allow_override = os.getenv("PROMOTION_ALLOW_ORPHANS", "").strip()
                        override_reason = os.getenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "").strip() or None
                        if allow_override:
                            ensure_object_has_relations(uuid, allow_orphans=True, override_reason=override_reason)
                            _append_jsonl(
                                LOG,
                                {
                                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "level": "info",
                                    "event": PROMOTE_ORPHAN_OVERRIDE,
                                    "uuid": uuid,
                                    "path": str(p),
                                    "trace_id": current_trace_id(),
                                    "reason": override_reason or "allow_orphans",
                                },
                            )
                        else:
                            ensure_object_has_relations(uuid)
                    except OrphanPromotionError as rel_err:
                        _append_jsonl(
                            LOG,
                            {
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "warn",
                                "event": PROMOTE_SKIP_ORPHAN,
                                "uuid": uuid,
                                "path": str(p),
                                "reason": str(rel_err),
                                "trace_id": current_trace_id(),
                            },
                        )
                        continue

                target, reason = _select_target(meta, move_policy, legacy, note_moves_allowed)
                if target is None:
                    _append_jsonl(
                        LOG,
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "warn",
                            "event": PROMOTE_SKIP_MOVE,
                            "uuid": uuid,
                            "path": str(p),
                            "trace_id": current_trace_id(),
                            "reason": reason or "no target",
                        },
                    )
                    processed += 1
                    continue

                dst_dir = _resolve_target_dir(Path(target), p)
                try:
                    new_path = _safe_move(p, dst_dir)
                    _append_jsonl(
                        LOG,
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "info",
                            "event": PROMOTE_DONE,
                            "uuid": uuid,
                            "src": str(p),
                            "dst": str(new_path),
                            "trace_id": current_trace_id(),
                        },
                    )
                except Exception as exc:
                    _append_jsonl(
                        LOG,
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "error",
                            "event": PROMOTE_ERROR,
                            "uuid": uuid,
                            "src": str(p),
                            "dst": str(dst_dir),
                            "trace_id": current_trace_id(),
                            "reason": str(exc),
                        },
                    )
                    continue

                processed += 1
        except Exception:
            _append_jsonl(
                LOG,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "error",
                    "event": PROMOTE_ERROR,
                    "payload": ev,
                    "trace_id": current_trace_id(),
                },
            )
            continue

    return processed


__all__ = ["enqueue", "run_once", "_PROMOTION_SETTINGS", "_NOTE_MOVES_ENABLED"]
