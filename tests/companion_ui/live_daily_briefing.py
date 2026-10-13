"""Opt-in Daily Briefing acceptance on one frozen native synthetic TEST binding.

Run inside the existing #5675 native/channel lock boundary. This module never
deploys, resets a database, changes runtime configuration or starts a service.
The supplied fixture must already have been prepared through canonical writers.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import urlopen
from uuid import UUID, uuid4
import wave
import xml.etree.ElementTree as ET

from tests.companion_ui.live_core_flow import (
    Blocked,
    CoreFlow,
    _PROBE,
    _origin,
)
from tests.companion_ui.live_smoke_contract import assert_gateway_identity

SCENARIOS = (
    "preflight",
    "generation_and_provenance",
    "daily_trigger_idempotence",
    "one_read_only_card",
    "mixed_audio_playback",
    "partial_source",
    "text_only_degradation",
    "fixture_restored",
)
EFFECT_LIMITS = {"first_contact": 2, "navigation": 4, "tts_plan": 1, "tts_synthesis": 1,
                 "degrade_source": 1, "restore_source": 1}
NATIVE_CONTEXT = Path("/scratch/native-web-context.json")
NATIVE_OUTPUT = Path("/scratch/native-web-reports/daily-briefing")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _navigation_url(value: str) -> str:
    """Canonicalize only the empty root path, as the browser does."""
    parsed = urlparse(value)
    return parsed._replace(path=parsed.path or "/").geturl()


def _relative(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not PurePosixPath(value).is_absolute()
            and all(x not in {"", ".", ".."} for x in value.split("/")))


def _private_json(path: Path, *, max_bytes: int = 65536) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or info.st_nlink != 1):
            raise ValueError("manifest_requires_private_regular_file")
        raw = os.read(fd, max_bytes + 1)
    finally:
        os.close(fd)
    if len(raw) > max_bytes:
        raise ValueError("manifest_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("manifest_fields_invalid")
    return value


def validate_legacy_manifest(path: Path) -> dict[str, Any]:
    """Read-only regression for old admission inputs; never a live entrypoint."""
    d = _private_json(path)
    fields = {"channel", "ui_url", "api_url", "expected_sha", "expected_digest", "run_id",
              "output_dir", "vault_id", "vault_path", "resource_version", "fixture_marker",
              "fixture_marker_sha256", "source_files", "moment_path", "moment_full_text",
              "calendar", "date", "effects", "native_boundary_ref"}
    optional = {"navigation_ms", "request_ms", "playback_ms"}
    if not fields <= d.keys() or d.keys() - fields - optional:
        raise ValueError("manifest_fields_invalid")
    if d["channel"] not in {"dev", "test"}:
        raise ValueError("only_dev_and_test_are_supported")
    for key in fields - {"source_files", "calendar", "effects"}:
        if not isinstance(d[key], str) or not d[key] or "\x00" in d[key] or len(d[key]) > 16384:
            raise ValueError("manifest_string_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", d["expected_sha"]) or not re.fullmatch(r"sha256:[0-9a-f]{64}", d["expected_digest"]):
        raise ValueError("candidate_identity_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", d["run_id"]):
        raise ValueError("run_id_invalid")
    from datetime import date
    if date.fromisoformat(d["date"]).isoformat() != d["date"]:
        raise ValueError("fixture_date_invalid")
    ports = {"test": (8112, 18002), "dev": (8111, 18001)}[d["channel"]]
    for key, port in zip(("ui_url", "api_url"), ports):
        p = urlparse(d[key])
        if (p.scheme != "http" or p.hostname != "127.0.0.1" or p.port != port
                or p.username or p.password or p.query or p.fragment or p.path not in {"", "/"}):
            raise ValueError("native_channel_origin_invalid")
    root, output = Path(d["vault_path"]), Path(d["output_dir"])
    for path_value in (root, output):
        if (not path_value.is_absolute() or path_value.resolve() != path_value
                or any(p.is_symlink() for p in (path_value, *path_value.parents))):
            raise ValueError("fixture_or_evidence_path_invalid")
    if output.is_relative_to(root):
        raise ValueError("evidence_must_be_outside_fixture")
    for key in ("moment_path", "fixture_marker"):
        if not _relative(d[key]):
            raise ValueError("fixture_path_invalid")
    sources = d["source_files"]
    if (not isinstance(sources, dict) or not 1 <= len(sources) <= 128
            or any(not _relative(k) or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for k, v in sources.items())
            or d["moment_path"] not in sources or d["fixture_marker"] in sources
            or _hash(d["moment_full_text"].encode()) != sources[d["moment_path"]]):
        raise ValueError("source_inventory_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", d["fixture_marker_sha256"]):
        raise ValueError("fixture_marker_digest_invalid")
    calendar = d["calendar"]
    if (not isinstance(calendar, dict) or set(calendar) != {"calendar_id", "base_url", "calendar_path", "uid", "etag"}
            or any(not isinstance(v, str) or not v or len(v) > 1024 for v in calendar.values())):
        raise ValueError("synthetic_calendar_invalid")
    p = urlparse(calendar["base_url"])
    if (p.scheme != "http" or not p.hostname or p.username or p.password or p.query or p.fragment
            or p.path not in {"", "/"} or not calendar["calendar_path"].startswith("/synthetic/")):
        raise ValueError("synthetic_calendar_origin_invalid")
    if d["effects"] != EFFECT_LIMITS or any(type(x) is not int for x in d["effects"].values()):
        raise ValueError("effect_budget_invalid")
    for key, default in (("navigation_ms", 30000), ("request_ms", 35000), ("playback_ms", 15000)):
        d.setdefault(key, default)
        if type(d[key]) is not int or not 100 <= d[key] <= 60000:
            raise ValueError("test_budget_invalid")
    return d


def _native_seam() -> Any:
    try:
        from app.ops import native_web_runtime
        from app.ops.native_web_acceptance import EFFECT_LIMITS as limits, SCENARIOS as inventory
    except ImportError as exc:
        raise Blocked("reviewed_native_web_seam_not_available") from exc
    if (Path(native_web_runtime.__file__).resolve() != Path("/app/app/ops/native_web_runtime.py")
            or limits.get("daily-briefing") != EFFECT_LIMITS or inventory.get("daily-briefing") != SCENARIOS):
        raise Blocked("reviewed_native_web_seam_identity_mismatch")
    return native_web_runtime


def _hash_json(value: Any) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def load_manifest(path: Path) -> dict[str, Any]:
    """Only the fixed native producer manifest can admit an actual run."""
    m = _private_json(path)
    if (set(m) != {"schema", "pilot", "native_context", "output_dir", "report_binding"}
            or m.get("schema") != "native-web-pilot-manifest.v1" or m.get("pilot") != "daily-briefing"
            or m.get("native_context") != str(NATIVE_CONTEXT) or m.get("output_dir") != str(NATIVE_OUTPUT)):
        raise ValueError("reviewed_native_manifest_required")
    ctx = _private_json(NATIVE_CONTEXT, max_bytes=1024 * 1024)
    if ctx.get("schema") != "native-web-context.v1":
        raise ValueError("reviewed_native_context_required")
    binding = m["report_binding"]
    if (not isinstance(binding, dict)
            or set(binding) != {"source_sha", "image_digest", "channel", "harness_hashes", "configuration_hashes",
                                "run_id", "resource_version", "native_boundary_ref", "fixture_metadata_sha256", "local_instance_id"}
            or binding != {k: v for k, v in ctx.get("report_binding", {}).items() if k != "manifest_sha256"}
            or binding.get("channel") not in {"dev", "test"}
            or not re.fullmatch(r"[a-f0-9]{40}", str(binding.get("source_sha")))
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(binding.get("image_digest")))
            or binding.get("native_boundary_ref") != _hash_json({"native_identity": ctx["native_identity"], "start": ctx["start"]})
            or ctx.get("api_url") != "http://127.0.0.1:8000" or ctx.get("ui_url") != "http://127.0.0.1:8090"
            or ctx.get("caldav_url") != "http://127.0.0.1:8870"
            or ctx.get("reports", {}).get("daily-briefing") != str(NATIVE_OUTPUT / "report.json")):
        raise ValueError("native_manifest_context_binding_mismatch")
    identity = ctx["native_identity"]
    api_identity = ctx["start"]["api"]
    if (set(identity) != {"source_sha", "image_digest", "channel", "operation_id", "resource_generation", "resource_tree", "app_image_id"}
            or str(UUID(str(binding.get("run_id")))) != binding["run_id"]
            or re.fullmatch(r"[a-f0-9]{40}", str(binding.get("resource_version"))) is None
            or re.fullmatch(r"sha256:[a-f0-9]{64}", str(identity.get("app_image_id"))) is None
            or type(api_identity.get("api_pid")) is not int or api_identity["api_pid"] <= 0
            or api_identity.get("api_module") != "/app/app/main.py"
            or type(ctx["start"].get("ui_pid")) is not int or ctx["start"]["ui_pid"] <= 0
            or ctx["start"]["ui_pid"] == api_identity["api_pid"]
            or api_identity.get("fixture") != ctx["fixture"]
            or binding.get("configuration_hashes") != {"runtime": ctx["start"].get("configuration_hash"),
                                                       "vault": ctx["fixture"].get("settings_hash")}
            or any(identity.get(k) != binding.get(b) or api_identity.get(k) != binding.get(b)
            for k, b in (("source_sha", "source_sha"), ("image_digest", "image_digest"),
                         ("resource_generation", "run_id"), ("resource_tree", "resource_version")))
            or identity.get("channel") != binding["channel"]
            or binding.get("fixture_metadata_sha256") != _hash_json(ctx["fixture"])
            or binding.get("local_instance_id") != ctx["fixture"].get("local_clone_id")):
        raise ValueError("native_source_fixture_binding_mismatch")
    daily = ctx.get("daily_start_sources")
    fixture = ctx.get("fixture")
    if not isinstance(daily, dict) or not isinstance(fixture, dict):
        raise Blocked("actual_daily_start_source_versions_missing")
    from app.briefing.trigger import _local_now
    d = dict(daily) | {"channel": binding["channel"], "api_url": ctx["api_url"], "ui_url": ctx["ui_url"],
                      "expected_sha": binding["source_sha"], "expected_digest": binding["image_digest"],
                      "run_id": binding["run_id"], "resource_version": binding["resource_version"],
                      "native_boundary_ref": binding["native_boundary_ref"], "report_binding": binding,
                      "native_context": ctx, "output_dir": m["output_dir"],
                      "vault_path": os.environ.get("VAULT_ROOT", ""), "vault_id": fixture["logical_vault_id"],
                      "date": _local_now(None).date().isoformat(), "effects": dict(EFFECT_LIMITS),
                      "navigation_ms": 30000, "request_ms": 35000, "playback_ms": 15000,
                      "calendar": {"uid": ctx["calendar"]["calendar_uid"], "etag": ctx["calendar"]["calendar_etag"]}}
    if not Path(d["vault_path"]).is_absolute() or Path(d["vault_path"]).resolve() != Path(d["vault_path"]):
        raise Blocked("actual_native_vault_binding_missing")
    if not isinstance(d.get("source_files"), dict) or not 1 <= len(d["source_files"]) <= 128:
        raise ValueError("actual_daily_source_inventory_invalid")
    if any(not _relative(k) or re.fullmatch(r"[a-f0-9]{64}", str(v)) is None for k, v in d["source_files"].items()):
        raise ValueError("actual_daily_source_inventory_invalid")
    if (not _relative(d.get("fixture_marker")) or not _relative(d.get("moment_path"))
            or d["moment_path"] not in d["source_files"] or d["fixture_marker"] in d["source_files"]
            or _hash(d["moment_full_text"].encode()) != d["source_files"][d["moment_path"]]):
        raise ValueError("actual_daily_fault_source_invalid")
    d.update(input_manifest_path=str(path.resolve()), input_manifest_sha256=_hash_json(m),
             context_authority_sha256=_hash_json(ctx),
             harness_hashes=_harness_hashes())
    if binding.get("harness_hashes", {}).get("live_core_flow.py") != d["harness_hashes"]["live_core_flow.py"]:
        raise Blocked("native_admitted_core_harness_mismatch")
    return d


def _harness_hashes() -> dict[str, str]:
    return {p.name: _hash(p.read_bytes()) for p in (
        Path(__file__), Path(__file__).with_name("live_core_flow.py"),
        Path(__file__).with_name("test_companion_ui_live_daily_briefing.py"),
    )}


def _check_frozen_input(d: dict[str, Any]) -> None:
    if d.get("harness_hashes") != _harness_hashes():
        raise Blocked("frozen_runner_changed_during_invocation")
    if (_hash_json(_private_json(Path(d["input_manifest_path"]))) != d["input_manifest_sha256"]
            or _hash_json(_private_json(NATIVE_CONTEXT, max_bytes=1024 * 1024)) != d["context_authority_sha256"]):
        raise Blocked("native_input_identity_changed")


def _read_json_url(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=5) as response:
            if response.geturl() != url:
                raise Blocked("native_observer_redirect_forbidden")
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise Blocked("native_observer_response_unbounded")
        value = json.loads(raw)
    except Blocked:
        raise
    except Exception as exc:
        raise Blocked("native_observer_unavailable") from exc
    if not isinstance(value, dict):
        raise Blocked("native_observer_response_invalid")
    return value


def _local_fixture_read(d: dict[str, Any]) -> dict[str, Any]:
    # Reuse the already-proved passive restoration checks without a manager or
    # unrelated capture/ASK qualification. The namespace is local to this read.
    code = _PASSIVE_BINDING.replace("p=json.load(sys.stdin)", "p=admitted_values")
    exec(code, {"admitted_values": d})
    root = Path(d["vault_path"])
    marker = root / d["fixture_marker"]
    if marker.is_symlink() or _hash(marker.read_bytes()) != d["fixture_marker_sha256"]:
        raise Blocked("immutable_synthetic_marker_changed")
    if json.loads(marker.read_bytes()) != {"schema": "daily-briefing-synthetic-fixture.v1", "synthetic": True,
            "run_id": d["run_id"], "resource_version": d["resource_version"], "vault_id": d["vault_id"], "vault_path": str(root)}:
        raise Blocked("synthetic_marker_identity_mismatch")
    from datetime import date
    from app.briefing.compose import briefing_note_path, load_briefing
    from app.briefing.trigger import _local_now
    from app.tts.config import load_tts_config
    from app.tts.status import tts_runtime_status
    from app.vault.manager import VaultContext
    if _local_now(None).date().isoformat() != d["date"]:
        raise Blocked("fixture_day_changed")
    context = VaultContext(status="selected", active_vault_id=d["vault_id"], active_vault_path=str(root))
    target = briefing_note_path(vault_context=context, for_date=date.fromisoformat(d["date"]))
    actual = {}
    count = 0
    for path in root.rglob("*"):
        count += 1
        if count > 512 or path.is_symlink():
            raise Blocked("synthetic_fixture_unbounded_or_symlink")
        if path.is_file() and path != marker and path != target:
            raw = path.read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                raise Blocked("synthetic_fixture_file_unbounded")
            actual[path.relative_to(root).as_posix()] = _hash(raw)
    if actual != d["source_files"]:
        raise Blocked("synthetic_source_inventory_changed")
    note = load_briefing(vault_context=context, for_date=date.fromisoformat(d["date"]))
    status = tts_runtime_status(load_tts_config())
    config = {k: status["config"][k] for k in ("enabled", "local_only", "allow_browser_fallback", "allow_cloud_fallback")}
    if not config["local_only"] or config["allow_browser_fallback"] or config["allow_cloud_fallback"]:
        raise Blocked("nonlocal_tts_route_forbidden")
    return {"date": d["date"], "source_sha256": _hash_json(actual), "briefing_path": target.relative_to(root).as_posix(),
            "briefing_exists": target.is_file(), "briefing_sha256": _hash(target.read_bytes()) if target.is_file() else None,
            "degraded_sections": list(note.degraded_sections) if note else [], "tts_config": config,
            "tts_routes": {k: {x: v[x] for x in ("provider", "voice_id", "available")} for k, v in status["providers"].items()}}


# Reuse #5942/#5957's passive restore admission, stopping before the unrelated
# capture producer and PG-vector probe. This prefix creates no manager/provider.
def passive_binding_prefix(source: str) -> str:
    marker = "from app.vault.paths import get_vault_capture_note_rel\n"
    if source.count(marker) != 1:
        raise Blocked("passive_binding_prefix_drift")
    return source.split(marker, 1)[0]


_PASSIVE_BINDING = passive_binding_prefix(_PROBE)
_NATIVE_READ = _PASSIVE_BINDING + r"""
import socket,ipaddress
from datetime import date
from app.briefing.config import BRIEFING_TIMEZONE,BRIEFING_ENABLED
from app.briefing.trigger import _local_now
from app.briefing.compose import briefing_note_path,load_briefing
from app.vault.manager import VaultContext
assert BRIEFING_ENABLED,'briefing_disabled'
assert _local_now(None).date().isoformat()==p['date'],'fixture_day_changed'
marker=root/p['fixture_marker']
assert marker.is_file() and not marker.is_symlink(),'synthetic_fixture_marker_missing'
raw=marker.read_bytes();assert hashlib.sha256(raw).hexdigest()==p['fixture_marker_sha256'],'synthetic_fixture_marker_mismatch'
admission=json.loads(raw)
assert admission=={'schema':'daily-briefing-synthetic-fixture.v1','synthetic':True,'run_id':p['run_id'],'resource_version':p['resource_version'],'vault_id':p['vault_id'],'vault_path':p['vault_path']},'synthetic_fixture_not_admitted'
ctx=VaultContext(status='selected',active_vault_id=p['vault_id'],active_vault_path=str(root))
target=briefing_note_path(vault_context=ctx,for_date=date.fromisoformat(p['date']))
assert not target.is_symlink() and target.resolve().is_relative_to(root),'briefing_target_invalid'
actual={}
for path in root.rglob('*'):
 assert not path.is_symlink(),'synthetic_fixture_symlink'
 if path.is_file() and path!=marker and path!=target:
  raw=path.read_bytes();assert len(raw)<=2*1024*1024,'synthetic_fixture_file_unbounded'
  actual[path.relative_to(root).as_posix()]=hashlib.sha256(raw).hexdigest()
assert actual==p['source_files'],'synthetic_fixture_inventory_changed'
from app.episodes.stream_registry import load_registry,STATUS_LIVE
from app.episodes.calendar_stream import resolve_calendar_bindings
stream=load_registry().get('calendar')
assert stream is not None and stream.status==STATUS_LIVE,'synthetic_calendar_stream_not_live'
bindings=resolve_calendar_bindings()
assert len(bindings)==1,'synthetic_calendar_binding_not_exclusive'
b=bindings[0];cal=p['calendar']
assert b.calendar_id==cal['calendar_id'] and b.base_url==cal['base_url'] and b.calendar_path==cal['calendar_path'],'synthetic_calendar_binding_mismatch'
assert b.username=='synthetic' and b.app_password=='synthetic','synthetic_calendar_credentials_mismatch'
from urllib.parse import urlparse
host=urlparse(b.base_url).hostname
addresses={x[4][0] for x in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)}
nets=[ipaddress.ip_network(x) for x in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','::1/128')]
assert addresses and all(any(ipaddress.ip_address(a) in n for n in nets) for a in addresses),'synthetic_calendar_must_not_egress'
from app.tts.config import load_tts_config
from app.tts.status import tts_runtime_status
status=tts_runtime_status(load_tts_config())
assert status['config']['local_only'] and not status['config']['allow_cloud_fallback'] and not status['config']['allow_browser_fallback'],'tts_nonlocal_route_forbidden'
sources={k:actual[k] for k in actual}
result={'binding_verified':True,'fixture_verified':True,'source_sha256':hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest(),'date':p['date'],'briefing_path':target.relative_to(root).as_posix(),'briefing_exists':target.is_file(),'briefing_sha256':hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,'tts_config':{k:status['config'][k] for k in ('enabled','local_only','allow_browser_fallback','allow_cloud_fallback')},'tts_routes':{k:{x:v[x] for x in ('provider','voice_id','available')} for k,v in status['providers'].items()}}
"""

_NATIVE_ACTION = r"""
assert p['action']=='read','legacy_native_effect_path_forbidden'
if target.is_file():
 note=load_briefing(vault_context=ctx,for_date=date.fromisoformat(p['date']))
 result['degraded_sections']=list(note.degraded_sections)
print(json.dumps(result))
"""


def native_probe(d: dict[str, Any], action: str = "read") -> dict[str, Any]:
    """Use the reviewed same-process native observer; never run a Docker command."""
    _native_seam()
    if action != "read":
        raise Blocked("legacy_native_effect_path_forbidden")
    context = d.get("native_context")
    if not isinstance(context, dict):
        raise Blocked("reviewed_native_context_required")
    observed = _read_json_url(d["api_url"] + "/__native_web_identity")
    if observed.get("identity") != context["start"]["api"]:
        raise Blocked("actual_native_identity_drift")
    _check_frozen_input(d)
    expected_sources = d["source_files"]
    if observed.get("daily_source_versions") != expected_sources:
        raise Blocked("actual_native_source_versions_changed")
    state = _local_fixture_read(d)
    selected = {tuple(x) for x in observed["identity"].get("selected_tts", [])}
    for language in ("sv-SE", "en-US"):
        route = state["tts_routes"].get(language) or {}
        if (route.get("provider"), language, route.get("voice_id")) not in selected:
            raise Blocked("native_selected_tts_configuration_mismatch")
    return state | {"binding_verified": True, "fixture_verified": True, "gateway_upstream_verified": True,
                    "running_sha": d["expected_sha"], "image_digest": d["expected_digest"],
                    "configuration_hashes": d["report_binding"]["configuration_hashes"],
                    "source_transition": observed.get("daily_source_transition"),
                    "native_effects": observed.get("effects", {}).get("daily-briefing"),
                    "source_acknowledgements": observed.get("daily_source_acknowledgements", {}),
                    "native_identity": observed["identity"],
                    "daily_briefing_state": observed.get("daily_briefing_state", {})}


def validate_admission(d: dict[str, Any], result: dict[str, Any], *, fresh: bool = False) -> None:
    if (any(result.get(k) is not True for k in ("binding_verified", "fixture_verified", "gateway_upstream_verified"))
            or result.get("running_sha") != d["expected_sha"] or result.get("image_digest") != d["expected_digest"]
            or result.get("date") != d["date"]):
        raise Blocked("candidate_or_synthetic_fixture_not_verified")
    if fresh and result.get("briefing_exists") is not False:
        raise Blocked("fresh_daily_generation_fixture_required")


def validate_projection(d: dict[str, Any], payload: dict[str, Any]) -> None:
    if (payload.get("date") != d["date"] or payload.get("state") != "full" or payload.get("read_only") is not True
            or payload.get("degraded_sections")):
        raise AssertionError("full_today_projection_required")
    sections = {x["name"]: x for x in payload.get("sections", [])}
    if set(sections) != {"commitments", "moments", "decision_receipts", "calendar_episodes"}:
        raise AssertionError("required_source_sections_missing")
    for name, section in sections.items():
        if section.get("status") != "available" or not section.get("items"):
            raise AssertionError("required_source_missing:" + name)
        for item in section["items"]:
            refs = [item[k] for k in ("artifact_path", "target_ref", "receipt_path") if item.get(k)]
            refs.extend(x["ref"] for x in item.get("surfaced_refs", []) if x.get("ref"))
            refs = [ref.removeprefix("vault://") for ref in refs]
            if name == "calendar_episodes":
                if item.get("source") == "calendar":
                    if item.get("provenance_ref") != "calendar:" + d["calendar"]["uid"] + ":" + d["calendar"]["etag"]:
                        raise AssertionError("calendar_provenance_mismatch")
                elif item.get("source") == "episode":
                    refs.append("episodes/" + str(item.get("provenance_ref")) + ".md")
                else:
                    raise AssertionError("calendar_source_kind_unknown")
            elif not refs:
                raise AssertionError("item_provenance_missing")
            if any(ref not in d["source_files"] for ref in refs):
                raise AssertionError("item_provenance_not_in_admitted_sources")
    if {x.get("source") for x in sections["calendar_episodes"]["items"]} != {"calendar", "episode"}:
        raise AssertionError("calendar_and_episode_required")


def validate_audio(plan: dict[str, Any], synthesis: dict[str, Any], routes: dict[str, Any], raw: bytes,
                   *, source_text: str) -> dict[str, Any]:
    from app.tts.normalization import normalize_tts_text
    if plan.get("normalized_text") != normalize_tts_text(source_text):
        raise AssertionError("audio_plan_did_not_use_served_briefing_text")
    if (plan.get("enabled") is not True or plan.get("local_only") is not True
            or plan.get("allow_cloud_fallback") is not False or plan.get("allow_browser_fallback") is not False
            or plan.get("mixed_language") is not True or plan.get("cached") is not False):
        raise AssertionError("actual_uncached_local_mixed_plan_required")
    segments = plan.get("segments") or []
    if not any(str(x.get("language", "")).startswith("sv") for x in segments) or not any(str(x.get("language", "")).startswith("en") for x in segments):
        raise AssertionError("mixed_sv_en_segments_required")
    for segment in segments:
        route = routes.get(segment.get("language")) or {}
        if (segment.get("provider") not in {"piper", "kokoro"} or segment.get("provider_available") is not True
                or any(segment.get(k) != route.get(k) for k in ("provider", "voice_id"))
                or route.get("available") is not True):
            raise AssertionError("selected_segment_route_not_proven")
    if (synthesis.get("ok") is not True or synthesis.get("state") != "generated" or synthesis.get("cached") is not False
            or synthesis.get("cache_key") != plan.get("cache_key") or synthesis.get("audio_url") != plan.get("audio_url")
            or not re.fullmatch(r"/api/companion/tts/audio/[a-f0-9]{64}\.wav", str(synthesis.get("audio_url")))):
        raise AssertionError("actual_synthesis_lineage_required")
    try:
        with wave.open(io.BytesIO(raw)) as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            pcm = audio.readframes(frames)
            if frames <= 0 or rate <= 0 or audio.getcomptype() != "NONE" or not pcm or not any(pcm):
                raise AssertionError("empty_or_silent_audio")
    except (EOFError, wave.Error) as exc:
        raise AssertionError("audio_not_decodable_wav") from exc
    return {"audio_sha256": _hash(raw), "source_text_sha256": _hash(source_text.encode()), "frames": frames, "sample_rate": rate,
            "cache_key": synthesis["cache_key"], "segments": [{k: x[k] for k in ("language", "provider", "voice_id")} for x in segments]}


def acceptance_passed(report: dict[str, Any]) -> bool:
    rows = report.get("scenarios", [])
    diagnostics = report.get("diagnostics") or {}
    if not isinstance(diagnostics, dict):
        return False
    audio = diagnostics.get("audio") or {}
    provenance = diagnostics.get("working_provenance") or {}
    if not isinstance(audio, dict) or not isinstance(provenance, dict):
        return False
    return (report.get("channel") == "test" and report.get("execution_kind") == "actual_native_browser"
            and isinstance(rows, list) and len(rows) == len(SCENARIOS)
            and all(isinstance(x, dict) for x in rows) and [x.get("id") for x in rows] == list(SCENARIOS)
            and all(x.get("status") == "passed" for x in rows)
            and all(x.get("kind") == ("browser_local_failure" if x["id"] == "text_only_degradation" else "actual") for x in rows)
            and report.get("fixture_restored") is True and bool(report.get("native_boundary_ref"))
            and audio.get("playback_observed") is True
            and all(re.fullmatch(r"[a-f0-9]{64}", str(audio.get(key)))
                    for key in ("audio_sha256", "source_text_sha256", "cache_key"))
            and type(audio.get("frames")) is int and audio["frames"] > 0
            and type(audio.get("sample_rate")) is int and audio["sample_rate"] > 0
            and provenance.get("readable") is True and _relative(provenance.get("target"))
            and bool(provenance.get("source_uuid"))
            and re.fullmatch(r"[a-f0-9]{64}", str(provenance.get("source_sha256"))) is not None
            and report.get("end_identity_verified") is True
            and report.get("end_identity_error") is None
            and report.get("trace_status") == "recorded" and report.get("junit_status") == "recorded"
            and report.get("effects_consumed") == EFFECT_LIMITS)


def invocation_evidence_recorded(report: dict[str, Any]) -> bool:
    """A retained refusal/failure is code evidence and remains feature failure."""
    rows = report.get("scenarios")
    effects = report.get("effects_consumed")
    return (report.get("schema") == "daily_briefing_live_acceptance.v1"
            and report.get("execution_kind") in {"actual_native_browser", "actual_invocation_refused"}
            and isinstance(rows, list) and len(rows) == len(SCENARIOS)
            and [x.get("id") for x in rows] == list(SCENARIOS)
            and all(x.get("status") in {"passed", "failed", "blocked"} for x in rows)
            and isinstance(effects, dict) and set(effects) == set(EFFECT_LIMITS)
            and all(type(v) is int and 0 <= v <= EFFECT_LIMITS[k] for k, v in effects.items())
            and report.get("passed") is acceptance_passed(report)
            and report.get("trace") == "trace.zip" and report.get("junit") == "junit.xml")


def _unexecuted_rows(reason: str) -> list[dict[str, Any]]:
    return [{"id": name, "kind": "browser_local_failure" if name == "text_only_degradation" else "actual",
             "status": "blocked", "reason": reason, "observation": "not_executed"} for name in SCENARIOS]


class DailyBriefingFlow(CoreFlow):
    def __init__(self, d: dict[str, Any], browser: Any,
                 probe: Callable[[dict[str, Any], str], dict[str, Any]] = native_probe,
                 *, output_created: Callable[[Path], None] | None = None) -> None:
        self.d, self.browser, self.probe = d, browser, probe
        self.execution_kind = ("actual_native_browser" if probe is native_probe
                               and type(browser).__module__.startswith("playwright.") else "deterministic_fixture")
        self.effects = {k: 0 for k in EFFECT_LIMITS}
        self.admitted = self.generated = self.degraded = self.restored = False
        self.playback_armed = False
        self.tts_payloads: dict[str, dict[str, Any]] = {}
        self.diagnostics: dict[str, Any] = {}
        self.baseline: dict[str, Any] = {}
        self.projection: dict[str, Any] = {}
        self.end_identity_verified = False
        self.end_identity_error: str | None = None
        self.trace_status = self.junit_status = "not_started"
        self.harness_hashes = _harness_hashes()
        self.report_version: tuple[int, int, str] | None = None
        self.output_identity: tuple[int, int] | None = None
        self.provenance_href: str | None = None
        self.provenance_path: str | None = None
        self.navigation_target: str | None = None

        def created(output: Path) -> None:
            info = output.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise Blocked("invocation_output_not_directory")
            self.output_identity = (info.st_dev, info.st_ino)
            if output_created is not None:
                output_created(output)

        # The delivered CoreFlow remains the exclusive creator. Preserve the
        # original Daily context's blocked-service-worker posture at that call.
        context_creator = SimpleNamespace(new_context=lambda **kwargs: browser.new_context(service_workers="block", **kwargs))
        super().__init__(d, context_creator, probe, output_created=created)
        self.browser = browser
        self.results = _unexecuted_rows("invocation_not_completed")
        self.context.add_init_script("""(() => { const Original = window.Audio;
          window.Audio = function(src) { const a = new Original(src); window.__briefingAudio = a;
            a.addEventListener('playing', () => window.__briefingPlaying = true); return a; };
          window.Audio.prototype = Original.prototype;
        })();""")
        self._snapshot()

    def _guard_request(self, route: Any) -> None:
        self._guard(route)

    def _owned_directory(self) -> int:
        if self.output.is_symlink() or any(p.is_symlink() for p in self.output.parents):
            raise Blocked("invocation_output_identity_changed")
        directory = os.open(self.output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        current = self.output.lstat()
        if ((info.st_dev, info.st_ino) != self.output_identity
                or (current.st_dev, current.st_ino) != self.output_identity):
            os.close(directory)
            raise Blocked("invocation_output_identity_changed")
        return directory

    def _snapshot(self) -> dict[str, Any]:
        report = {"schema": "daily_briefing_live_acceptance.v1", "channel": self.d["channel"],
                  "execution_kind": self.execution_kind, "expected_sha": self.d["expected_sha"],
                  "expected_digest": self.d["expected_digest"], "run_id": self.d["run_id"],
                  "resource_version": self.d["resource_version"], "native_boundary_ref": self.d["native_boundary_ref"],
                  "output_dir": str(self.output), "scenarios": self.results, "effects_consumed": self.effects,
                  "diagnostics": self.diagnostics, "fixture_restored": self.restored,
                  "trace": "trace.zip", "junit": "junit.xml", "trace_status": self.trace_status,
                  "junit_status": self.junit_status, "harness_hashes": dict(self.harness_hashes),
                  "input_manifest_sha256": self.d.get("input_manifest_sha256"),
                  "end_identity_verified": self.end_identity_verified, "end_identity_error": self.end_identity_error}
        report["passed"] = acceptance_passed(report)
        directory = self._owned_directory()
        try:
            if self.report_version is None:
                if "report.json" in os.listdir(directory):
                    raise Blocked("prior_report_must_be_preserved")
            else:
                fd = os.open("report.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    raw = os.read(fd, 2 * 1024 * 1024 + 1)
                    if (info.st_dev, info.st_ino, _hash(raw)) != self.report_version:
                        raise Blocked("partial_report_identity_changed")
                finally:
                    os.close(fd)
            fd = os.open("report.json.next", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            raw = json.dumps(report, indent=2).encode()
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
                info = os.fstat(handle.fileno())
            current = self.output.lstat()
            if (current.st_dev, current.st_ino) != self.output_identity:
                raise Blocked("invocation_output_identity_changed")
            if self.report_version is None:
                os.link("report.json.next", "report.json", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                os.unlink("report.json.next", dir_fd=directory)
            else:
                # Recheck after writing the candidate, before replacing only
                # the last version produced by this invocation.
                incumbent = os.open("report.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    prior = os.fstat(incumbent)
                    if (prior.st_dev, prior.st_ino, _hash(os.read(incumbent, 2 * 1024 * 1024 + 1))) != self.report_version:
                        raise Blocked("partial_report_identity_changed")
                finally:
                    os.close(incumbent)
                os.replace("report.json.next", "report.json", src_dir_fd=directory, dst_dir_fd=directory)
            self.report_version = (info.st_dev, info.st_ino, _hash(raw))
            os.fsync(directory)
        finally:
            os.close(directory)
        return report

    def _consume(self, effect: str) -> None:
        if not self.admitted or self.effects[effect] >= self.d["effects"][effect]:
            raise Blocked("effect_not_admitted:" + effect)
        self.effects[effect] += 1
        self._snapshot()  # Reserve before forwarding: uncertain effects are not replayed.
        if self.probe is native_probe:
            try:
                _native_seam().before_effect("daily-briefing", effect)
            except Exception as exc:
                raise Blocked("native_before_effect_refused:" + effect) from exc

    def _guard(self, route: Any) -> None:
        r = route.request
        if _origin(r.url) != _origin(self.d["ui_url"]):
            route.abort("blockedbyclient")
            return
        if r.method in {"GET", "HEAD", "OPTIONS"}:
            if r.method == "GET" and urlparse(r.url).path in {"/", "/workspace"}:
                if r.url != self.navigation_target:
                    route.abort("blockedbyclient")
                    return
                self.navigation_target = None
            route.continue_()
            return
        action = {"/api/companion/tts/plan": "tts_plan", "/api/companion/tts/synthesize": "tts_synthesis"}.get(urlparse(r.url).path)
        if r.method != "POST" or not action or not self.playback_armed:
            route.abort("blockedbyclient")
            return
        payload = r.post_data_json
        if (not isinstance(payload, dict) or type(payload.get("rate")) not in {int, float}
                or payload != self.tts_payloads.get(action)):
            route.abort("blockedbyclient")
            return
        try:
            self._consume(action)
        except Blocked:
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _native(self, action: str = "read") -> dict[str, Any]:
        d = self.d
        if self.degraded:
            d = d | {"source_files": d["source_files"] | {d["moment_path"]: _hash(b"---\ninvalid: [\n---\nSynthetic unavailable source.\n")}}
        result = self.probe(d, action)
        validate_admission(d, result)
        return result

    def _json(self, path: str, *, method: str = "GET") -> dict[str, Any]:
        self._native()
        if method == "POST":
            self._consume("first_contact")
        response = self.page.request.fetch(urljoin(self.d["api_url"], path), method=method,
                                           timeout=self.d["request_ms"], max_redirects=0)
        if not response.ok or _origin(response.url) != _origin(self.d["api_url"]):
            raise Blocked("backend_route_unavailable:" + str(response.status))
        return response.json()

    def _navigate(self, destination: str | None = None) -> None:
        state = self._native()
        if state.get("briefing_exists") is not True:
            raise Blocked("first_contact_would_generate_unbudgeted_briefing")
        target = _navigation_url(destination or self.d["ui_url"])
        admitted = {_navigation_url(self.d["ui_url"])}
        if self.provenance_href is not None:
            admitted.add(_navigation_url(self.provenance_href))
        if (target not in admitted
                or _origin(target) != _origin(self.d["ui_url"]) or urlparse(target).path not in {"/", "/workspace"}):
            raise Blocked("navigation_target_outside_fixed_gateway")
        self._consume("navigation")
        self.navigation_target = target
        try:
            response = self.page.goto(target, wait_until="domcontentloaded")
        finally:
            self.navigation_target = None
        if response is None or not response.ok or self.page.url != target:
            raise AssertionError("gateway_navigation_failed")
        assert_gateway_identity(actual_channel=self.page.locator('meta[name="pkm-runtime-channel"]').get_attribute("content") or "",
                                actual_git_sha=self.page.locator('meta[name="pkm-runtime-git-sha"]').get_attribute("content") or "",
                                expected_channel=self.d["channel"], expected_git_sha=self.d["expected_sha"])

    def preflight(self) -> None:
        self.baseline = self.probe(self.d, "read")
        validate_admission(self.d, self.baseline, fresh=True)
        version = self._json("/version")
        if version.get("git_sha") != self.d["expected_sha"]:
            raise Blocked("running_version_mismatch")
        self.admitted = True
        self.diagnostics["admission"] = self.baseline

    def generation_and_provenance(self) -> None:
        if not self.admitted:
            raise Blocked("preflight_not_passed")
        payload = self._json("/api/companion/briefing/first-contact", method="POST")
        if payload.get("triggered") is not True or payload.get("reason") != "first_contact":
            raise AssertionError("actual_first_contact_generation_required")
        self.generated = True
        self.projection = payload["briefing"]
        validate_projection(self.d, self.projection)
        observed = self._native()
        if observed.get("briefing_exists") is not True or observed.get("degraded_sections") != []:
            raise AssertionError("dated_canonical_artifact_not_observed")
        self.diagnostics["generation"] = observed

    def daily_trigger_idempotence(self) -> None:
        if not self.generated:
            raise Blocked("generation_not_observed")
        before = self._native()
        replay = self._json("/api/companion/briefing/first-contact", method="POST")
        scheduled = self._scheduled_replay()
        if (replay.get("triggered") is not False or replay.get("reason") != "already_generated_today"
                or scheduled.get("triggered") is not False or scheduled.get("reason") != "already_generated_today"
                or before["briefing_sha256"] != scheduled["briefing_sha256"]):
            raise AssertionError("daily_trigger_replay_changed_artifact")
        self.diagnostics["idempotence"] = scheduled
        self._navigate()
        if self._native()["briefing_sha256"] != before["briefing_sha256"]:
            raise AssertionError("gateway_first_contact_changed_existing_artifact")
        self._select_served_provenance()

    def _select_served_provenance(self) -> None:
        refs = [item.get("target_ref") for section in self.projection["sections"]
                for item in section["items"] if item.get("target_ref")]
        for ref in refs:
            path = str(ref).removeprefix("vault://")
            if path.endswith(".md") and path in self.d["source_files"]:
                break
        else:
            raise Blocked("admitted_note_provenance_link_required")
        card = self.page.get_by_test_id("day-start-card")
        card.locator("summary").click()
        link = card.get_by_role("link", name=str(ref), exact=True).first
        if not link.is_visible():
            raise AssertionError("actual_note_provenance_link_not_visible")
        target = urljoin(self.d["ui_url"], link.get_attribute("href") or "")
        parsed = urlparse(target)
        if (_origin(target) != _origin(self.d["ui_url"]) or parsed.path not in {"/", "/workspace"}
                or parsed.fragment or parse_qs(parsed.query, keep_blank_values=True) != {"note_path": [path]}):
            raise AssertionError("actual_provenance_link_target_mismatch")
        self.provenance_href, self.provenance_path = target, path

    def _scheduled_replay(self) -> dict[str, Any]:
        observed = self._native()
        if observed.get("briefing_exists") is not True:
            raise Blocked("scheduled_replay_requires_existing_dated_artifact")
        replay = _native_seam().scheduled_replay()
        if (replay.get("target") != observed["briefing_path"] or replay.get("date") != self.d["date"]
                or replay.get("durable_writes") != 0 or replay.get("briefing_sha256") != observed["briefing_sha256"]):
            raise Blocked("scheduled_replay_actual_producer_mismatch")
        return replay

    def one_read_only_card(self) -> None:
        if not self.generated:
            raise Blocked("generation_not_observed")
        if self.provenance_href is not None:
            self._navigate(self.provenance_href)
            self._prove_opened_source()
        else:
            self._navigate()
        card = self.page.get_by_test_id("day-start-card")
        if (card.count() != 1 or card.get_attribute("data-read-only") != "true"
                or card.get_attribute("data-briefing-state") != "full"):
            raise AssertionError("single_honest_read_only_card_required")
        visible_date = card.locator("time")
        if (visible_date.count() != 1 or not visible_date.is_visible()
                or visible_date.inner_text().strip() != self.d["date"]):
            raise AssertionError("card_date_does_not_match_admitted_day")
        card.locator("summary").click()
        if card.locator("input, textarea, [contenteditable=true]").count():
            raise AssertionError("briefing_has_mutable_or_typing_surface")
        for section in self.projection["sections"]:
            for item in section["items"]:
                for key in ("artifact_path", "target_ref", "receipt_path", "provenance_ref"):
                    if item.get(key) and str(item[key]) not in card.inner_text():
                        raise AssertionError("card_dropped_item_provenance")

    def _prove_opened_source(self) -> None:
        path = self.provenance_path
        if not _relative(path) or not str(path).endswith(".md") or path not in self.d["source_files"]:
            raise Blocked("admitted_note_provenance_link_required")
        from app.rebuildability.product_total_loss import parse_bounded_frontmatter
        from companion_ui.renderer.vault_markdown_renderer import render_vault_markdown, _RawHtmlStripper
        source = Path(self.d["vault_path"]) / path
        if source.is_symlink() or source.resolve() != source:
            raise Blocked("provenance_source_identity_changed")
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, 2 * 1024 * 1024 + 1)
        finally:
            os.close(descriptor)
        if len(raw) > 2 * 1024 * 1024 or _hash(raw) != self.d["source_files"][path]:
            raise Blocked("provenance_source_identity_changed")
        frontmatter, _body, error = parse_bounded_frontmatter(raw.decode())
        if error is not None:
            raise Blocked("provenance_source_unreadable")
        workspace = self._json("/api/companion/workspace?note_path=" + quote(path, safe=""))
        artifact = workspace.get("artifact") or {}
        api_body = artifact.get("body")
        if (artifact.get("note_path") != path or not frontmatter.get("uuid")
                or artifact.get("artifact_id") != frontmatter["uuid"] or not isinstance(api_body, str)
                or _hash(api_body.encode()) != self.d["source_files"][path]):
            raise AssertionError("actual_provenance_workspace_identity_mismatch")
        # Use the same renderer as the served reading view. Raw frontmatter and
        # Markdown remain bound above; neither is required to appear as prose.
        rendered = render_vault_markdown(api_body, note_path=path,
                                        content_hash=str(artifact.get("content_hash") or ""))
        text = _RawHtmlStripper()
        text.feed(rendered.html)
        text.close()
        expected_text = text.text()
        reading = self.page.get_by_test_id("workspace-note-rendered")
        marker = self.page.get_by_test_id("workspace-note-source-editor")
        if (reading.count() != 1 or not reading.is_visible() or marker.count() != 1
                or marker.get_attribute("data-note-path") != path or not artifact.get("content_hash")
                or marker.get_attribute("data-content-hash") != artifact["content_hash"]
                or not expected_text.strip() or reading.text_content() != expected_text
                # innerText inserts layout whitespace between block elements.
                # DOM text must still match exactly, and all rendered characters
                # must remain visible; a nonempty/partial reading cannot pass.
                or re.sub(r"\s+", "", reading.inner_text()) != re.sub(r"\s+", "", expected_text)):
            raise AssertionError("actual_provenance_source_not_readable")
        self.diagnostics["working_provenance"] = {"target": path, "source_sha256": _hash(raw),
                                                 "source_uuid": artifact["artifact_id"], "readable": True}

    def mixed_audio_playback(self) -> None:
        if not self.generated:
            raise Blocked("generation_not_observed")
        routes = self.baseline["tts_routes"]
        if (self.baseline["tts_config"].get("enabled") is not True
                or any(routes.get(x, {}).get("available") is not True for x in ("sv-SE", "en-US"))):
            raise Blocked("selected_actual_sv_en_tts_unavailable")
        # No response mocking in the happy path. Audio instrumentation observes
        # the original browser Audio object and native playback events.
        from app.tts.normalization import normalize_tts_text
        source = json.loads(self.page.locator(".briefing-audio-surface").get_attribute("data-briefing-text") or '""')
        self.tts_payloads = {"tts_plan": {"text": source, "rate": 1.0},
                             "tts_synthesis": {"text": normalize_tts_text(source), "rate": 1.0}}
        self.playback_armed = True
        try:
            with self.page.expect_response("**/api/companion/tts/plan", timeout=self.d["request_ms"]) as planned:
                with self.page.expect_response("**/api/companion/tts/synthesize", timeout=self.d["request_ms"]) as synthesized:
                    self.page.get_by_test_id("briefing-listen").click()
            plan_response, synth_response = planned.value, synthesized.value
            if not plan_response.ok or not synth_response.ok:
                raise Blocked("selected_tts_route_failed")
            plan, synthesis = plan_response.json(), synth_response.json()
            source_text = json.loads(self.page.locator(".briefing-audio-surface").get_attribute("data-briefing-text") or '""')
            if (plan_response.request.post_data_json.get("text") != source_text
                    or synth_response.request.post_data_json.get("text") != plan.get("normalized_text")):
                raise AssertionError("tts_request_lineage_does_not_match_card")
            url = synthesis.get("audio_url")
            if not isinstance(url, str) or not re.fullmatch(r"/api/companion/tts/audio/[a-f0-9]{64}\.wav", url):
                raise AssertionError("audio_url_not_same_origin_cache_route")
            response = self.page.request.get(urljoin(self.d["ui_url"], url), max_redirects=0)
            if not response.ok or _origin(response.url) != _origin(self.d["ui_url"]):
                raise AssertionError("audio_route_unavailable")
            self.diagnostics["audio"] = validate_audio(plan, synthesis, routes, response.body(), source_text=source_text)
            self.page.wait_for_function("window.__briefingPlaying === true && window.__briefingAudio && window.__briefingAudio.currentTime > 0 && !window.__briefingAudio.error", timeout=self.d["playback_ms"])
            self.diagnostics["audio"]["playback_observed"] = True
        finally:
            self.playback_armed = False

    def partial_source(self) -> None:
        if not self.generated:
            raise Blocked("generation_not_observed")
        transition = self._native().get("source_transition")
        expected = {"moment_path": self.d["moment_path"], "briefing_path": self.baseline["briefing_path"],
                    "source_writes_per_effect": 1, "regenerations_per_effect": 1,
                    "effects": ["degrade_source", "restore_source"]}
        if transition != expected:
            raise Blocked("native_source_transition_regeneration_not_admitted")
        self._consume("degrade_source")
        # Record uncertainty before the producer call; always attempt the exact
        # restoration later, even when regeneration or readback fails.
        self.degraded = True
        response = self.page.request.post(self.d["api_url"] + "/__native_web_fixture/degrade-source", timeout=self.d["request_ms"], max_redirects=0)
        if not response.ok:
            raise Blocked("native_source_degradation_refused")
        result = response.json()
        self.diagnostics["partial_source"] = result
        self._require_regeneration_ack(result, "degrade_source")
        payload = self._json("/api/companion/briefing/today")
        if payload.get("state") != "degraded" or payload.get("degraded_sections") != ["moments"]:
            raise AssertionError("actual_source_failure_not_named")
        for section in payload["sections"]:
            if section["name"] != "moments" and (section.get("status") != "available" or not section.get("items")):
                raise AssertionError("bad_source_suppressed_healthy_section")
        self._navigate()
        if self.page.get_by_test_id("day-start-card").get_attribute("data-briefing-state") != "degraded":
            raise AssertionError("card_did_not_surface_actual_partial_failure")

    def fixture_restored(self) -> None:
        if not self.generated:
            raise Blocked("generation_not_observed")
        if self.degraded:
            try:
                self._native()
            except Blocked:
                # A failed native call may have refused before its source write.
                # Inspect only the other declared state; never repeat a mutation.
                validate_admission(self.d, self.probe(self.d, "read"))
                self.degraded = False
            if self.degraded:
                self._consume("restore_source")
                response = self.page.request.post(self.d["api_url"] + "/__native_web_fixture/restore-source", timeout=self.d["request_ms"], max_redirects=0)
                if not response.ok:
                    raise Blocked("native_source_restoration_refused")
                result = response.json()
                self.diagnostics["restoration"] = result
                self.degraded = False
                if result.get("post_sha256") != self.d["source_files"][self.d["moment_path"]]:
                    raise AssertionError("synthetic_source_restore_mismatch")
                self._require_regeneration_ack(result, "restore_source")
        validate_projection(self.d, self._json("/api/companion/briefing/today"))
        self.restored = True

    def _require_regeneration_ack(self, result: dict[str, Any], effect: str) -> None:
        receipt = result.get("receipt") or {}
        if (result.get("target") != self.d["moment_path"] or receipt.get("outcome") != "written"
                or receipt.get("locator", {}).get("path") != self.d["moment_path"]):
            raise AssertionError("native_source_write_receipt_mismatch")
        regeneration = result.get("regeneration") or {}
        write = regeneration.get("receipt") or {}
        if (write.get("operation") != "write_note" or write.get("outcome") != "written"
                or write.get("locator", {}).get("path") != self.baseline.get("briefing_path")
                or receipt.get("operation") != "write_note"
                or any(type(result.get(key)) is not int or result[key] != 1
                       for key in ("source_writes", "regenerations"))
                or regeneration.get("target") != self.baseline.get("briefing_path")
                or regeneration.get("degraded_sections") != (["moments"] if effect == "degrade_source" else [])
                or any(re.fullmatch(r"[a-f0-9]{64}", str(record.get(key))) is None
                       for record in (result, regeneration) for key in ("pre_sha256", "post_sha256"))):
            raise Blocked("native_source_transition_regeneration_not_admitted:" + effect)
        generated = self.diagnostics["generation"]["briefing_sha256"]
        if effect == "degrade_source":
            valid = (result["pre_sha256"] == self.d["source_files"][self.d["moment_path"]]
                     and result["post_sha256"] == _hash(b"---\ninvalid: [\n---\nSynthetic unavailable source.\n")
                     and regeneration["pre_sha256"] == generated and regeneration["post_sha256"] != generated)
        else:
            prior = self.diagnostics.get("partial_source") or {}
            valid = (result["pre_sha256"] == prior.get("post_sha256")
                     and result["post_sha256"] == self.d["source_files"][self.d["moment_path"]]
                     and regeneration["pre_sha256"] == prior.get("regeneration", {}).get("post_sha256")
                     and regeneration["post_sha256"] == generated)
        if not valid:
            raise Blocked("native_source_transition_lineage_mismatch:" + effect)
        observed = self._native()
        actual = observed.get("source_acknowledgements", {}).get(effect)
        if (actual != result or observed.get("briefing_sha256") != regeneration["post_sha256"]
                or observed.get("degraded_sections") != regeneration["degraded_sections"]):
            raise Blocked("native_source_acknowledgement_mismatch:" + effect)

    def text_only_degradation(self) -> None:
        # Restore before browser-only injection. The synthetic 503 is explicitly
        # separate from backend/provider evidence and forwards no TTS mutation.
        self.fixture_restored()
        self._navigate()
        self.page.route("**/api/companion/tts/plan", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":{"reason":"Local audio is unavailable. Read the briefing below."}}'))
        button = self.page.get_by_test_id("briefing-listen")
        if not button.is_enabled():
            # Existing actual route absence is honest text-only, but cannot
            # establish the injected enabled-to-disabled interaction.
            raise Blocked("text_only_injection_requires_initial_listen_affordance")
        button.click()
        self.page.wait_for_function("document.querySelector('[data-testid=briefing-listen]').disabled")
        self.page.get_by_test_id("day-start-card").locator("summary").click()
        if not self.page.get_by_test_id("briefing-text").is_visible():
            raise AssertionError("text_unavailable_after_audio_failure")
        status = self.page.get_by_test_id("briefing-listen-status").inner_text()
        if not status.strip():
            raise AssertionError("tts_degrade_reason_not_visible")
        self.diagnostics["text_only"] = {"kind": "browser_local_failure", "forwarded_tts_actions": 0, "status": status}

    def _verify_end(self) -> None:
        if not self.admitted:
            raise Blocked("end_identity_requires_initial_admission")
        if _harness_hashes() != self.harness_hashes:
            raise Blocked("frozen_runner_changed_during_invocation")
        if self.probe is native_probe:
            _check_frozen_input(self.d)
        observed = self._native()
        validate_admission(self.d, observed)
        for key in ("native_identity", "configuration_hashes", "source_sha256", "tts_config", "tts_routes"):
            if key not in self.baseline or observed.get(key) != self.baseline[key]:
                raise Blocked("end_identity_changed:" + key)
        if observed.get("native_effects") != self.effects:
            raise Blocked("end_effect_inventory_mismatch")
        generation = self.diagnostics.get("generation") or {}
        if (not self.restored or observed.get("briefing_sha256") != generation.get("briefing_sha256")
                or observed.get("degraded_sections") != []):
            raise Blocked("end_fixture_restoration_unverified")
        directory = self._owned_directory()
        os.close(directory)
        self.diagnostics["end_identity"] = observed
        self.end_identity_verified = True

    def _write_junit(self) -> None:
        suite = ET.Element("testsuite", name="daily-briefing-actual-required", tests=str(len(SCENARIOS)))
        for row in self.results:
            case = ET.SubElement(suite, "testcase", name=row["id"], classname="actual-test-daily-briefing")
            if row["status"] != "passed":
                ET.SubElement(case, "failure", type=row["status"]).text = row.get("reason") or "required_scenario_not_passed"
            elif row["id"] == "preflight" and not self.end_identity_verified:
                ET.SubElement(case, "failure", type="end_identity").text = self.end_identity_error or "required_end_identity_missing"
        directory = self._owned_directory()
        try:
            descriptor = os.open("junit.xml", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(descriptor, "wb") as stream:
                ET.ElementTree(suite).write(stream, encoding="utf-8", xml_declaration=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
            self.junit_status = "recorded"
        finally:
            os.close(directory)

    def run(self) -> dict[str, Any]:
        try:
            for index, name in enumerate(SCENARIOS):
                started = time.monotonic()
                row: dict[str, Any] = {"id": name, "kind": "browser_local_failure" if name == "text_only_degradation" else "actual"}
                try:
                    getattr(self, name)()
                    row.update(status="passed", reason=None)
                except Blocked as exc:
                    row.update(status="blocked", reason=str(exc))
                except AssertionError as exc:
                    row.update(status="failed", reason=str(exc)[:200])
                except Exception as exc:
                    row.update(status="failed", reason=type(exc).__name__)
                row["seconds"] = round(time.monotonic() - started, 3)
                self.results[index] = row
                self._snapshot()
                if row["status"] != "passed":
                    try:
                        raw = self.page.screenshot()
                        if len(raw) > 10 * 1024 * 1024:
                            raise Blocked("failure_screenshot_unbounded")
                        directory = self._owned_directory()
                        try:
                            descriptor = os.open(name + ".png", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                                 0o600, dir_fd=directory)
                            with os.fdopen(descriptor, "wb") as stream:
                                stream.write(raw)
                                stream.flush()
                                os.fsync(stream.fileno())
                        finally:
                            os.close(directory)
                    except Exception:
                        pass
        finally:
            try:
                self._verify_end()
            except Exception as exc:
                self.end_identity_verified = False
                self.end_identity_error = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
            self._snapshot()
            directory = self._owned_directory()
            try:
                if "trace.zip" in os.listdir(directory):
                    raise Blocked("prior_trace_must_be_preserved")
                trace = self.output / "trace.zip"
                self.context.tracing.stop(path=str(trace))
                os.chmod(trace, 0o600)
                self.trace_status = "recorded"
            except Exception as exc:
                self.trace_status = "unavailable"
                self.end_identity_verified = False
                self.end_identity_error = "trace_retention_failed:" + type(exc).__name__
            finally:
                os.close(directory)
                self.context.close()
            self._write_junit()
        return self._snapshot()


def execute_manifest(path: Path | None) -> dict[str, Any]:
    """Actual invocation, including an unqualified pre-effect startup refusal."""
    d: dict[str, Any] = {"output_dir": str(Path.cwd() / ".codex-tmp" / ("daily-briefing-refusal-" + str(uuid4()))),
                         "channel": "test", "effects": dict(EFFECT_LIMITS)}
    owned_output: tuple[int, int] | None = None

    def output_created(output: Path) -> None:
        nonlocal owned_output
        info = output.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise Blocked("invocation_output_not_directory")
        owned_output = (info.st_dev, info.st_ino)

    try:
        if path is None:
            raise Blocked("qualified_native_manifest_unavailable")
        raw = _private_json(path)
        d["input_manifest_sha256"] = _hash_json(raw)
        binding = raw.get("report_binding") or {}
        # Expectations are explicitly unqualified. Do not choose the native
        # output path until the actual image-owned seam has been admitted.
        if isinstance(binding, dict):
            for key, field in (("expected_sha", "source_sha"), ("expected_digest", "image_digest"),
                               ("run_id", "run_id"), ("resource_version", "resource_version"),
                               ("native_boundary_ref", "native_boundary_ref")):
                d[key] = binding.get(field)
        _native_seam()
        if (set(raw) != {"schema", "pilot", "native_context", "output_dir", "report_binding"}
                or raw.get("schema") != "native-web-pilot-manifest.v1" or raw.get("pilot") != "daily-briefing"
                or raw.get("native_context") != str(NATIVE_CONTEXT) or raw.get("output_dir") != str(NATIVE_OUTPUT)):
            raise ValueError("reviewed_native_manifest_required")
        d["output_dir"] = raw["output_dir"]
        d = load_manifest(path)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                return DailyBriefingFlow(d, browser, output_created=output_created).run()
            finally:
                browser.close()
    except Exception as exc:
        reason = "runner_startup_failed:" + (str(exc) if isinstance(exc, Blocked) else type(exc).__name__)
        return _refused_invocation(d, reason, owned_output, output_created)


def _refused_invocation(d: dict[str, Any], reason: str, owned_output: tuple[int, int] | None,
                        output_created: Callable[[Path], None]) -> dict[str, Any]:
    """Write only to this invocation's exclusive, still-empty directory."""
    output = Path(d["output_dir"])
    if (not output.is_absolute() or output.resolve() != output
            or any(p.is_symlink() for p in (output, *output.parents))):
        raise ValueError("private_refusal_output_invalid")
    if output.exists():
        info = output.lstat()
        if (not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != owned_output
                or any(output.iterdir())):
            raise Blocked("prior_partial_or_foreign_output_must_be_preserved")
    elif owned_output is not None:
        raise Blocked("invocation_output_removed_must_be_preserved")
    else:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        output_created(output)
        info = output.lstat()
        owned_output = (info.st_dev, info.st_ino)
    report = {"schema": "daily_briefing_live_acceptance.v1", "execution_kind": "actual_invocation_refused",
              "output_dir": str(output),
              "channel": d.get("channel"), "expected_sha": d.get("expected_sha"),
              "expected_digest": d.get("expected_digest"), "run_id": d.get("run_id"),
              "resource_version": d.get("resource_version"), "native_boundary_ref": d.get("native_boundary_ref"),
              "qualification": "not_established", "identity_metadata_origin": "unqualified_invocation_input",
              "runner_sha256": _hash(Path(__file__).read_bytes()), "passed": False, "fixture_restored": False,
              "harness_hashes": _harness_hashes(), "input_manifest_sha256": d.get("input_manifest_sha256"),
              "observed_native_identity": None, "end_identity_verified": False, "end_identity_error": reason,
              "identity_gaps": [key for key in ("expected_sha", "expected_digest", "run_id", "resource_version",
                                                "native_boundary_ref") if not d.get(key)],
              "effects_consumed": dict.fromkeys(EFFECT_LIMITS, 0), "diagnostics": {"refusal": reason},
              "scenarios": _unexecuted_rows(reason),
              "trace": "trace.zip", "trace_status": "not_started", "junit": "junit.xml",
              "junit_status": "not_started", "junit_producer": "original_daily_runner"}
    directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if (info.st_dev, info.st_ino) != owned_output or os.listdir(directory):
            raise Blocked("prior_partial_or_foreign_output_must_be_preserved")
        descriptor = os.open("report.json", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "w+") as handle:
            # Retain truthful startup outcomes even if the later JUnit writer
            # fails. Keep the original descriptor so a replacement namespace
            # can never redirect the final status update into foreign bytes.
            json.dump(report, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            report_info = os.fstat(handle.fileno())
            suite = ET.Element("testsuite", name="daily-briefing-startup-refusal", tests=str(len(SCENARIOS)))
            for row in report["scenarios"]:
                case = ET.SubElement(suite, "testcase", name=row["id"], classname="actual-test-daily-briefing")
                ET.SubElement(case, "failure", type="blocked").text = reason
            descriptor = os.open("junit.xml", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(descriptor, "wb") as stream:
                ET.ElementTree(suite).write(stream, encoding="utf-8", xml_declaration=True)
                stream.flush()
                os.fsync(stream.fileno())
            named = os.stat("report.json", dir_fd=directory, follow_symlinks=False)
            current = output.lstat()
            if ((named.st_dev, named.st_ino) != (report_info.st_dev, report_info.st_ino)
                    or (current.st_dev, current.st_ino) != owned_output):
                raise Blocked("startup_report_identity_changed")
            report["junit_status"] = "recorded"
            handle.seek(0)
            json.dump(report, handle, indent=2)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)
    return report


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
