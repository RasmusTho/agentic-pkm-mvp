"""Explicit typed facts and measured evidence for the manual v2 shadow probe.

There is intentionally no live reader, launcher, lifecycle or mutation adapter here.
The operator retains observations; this module validates and compares their evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, ValidationError, validators

from app.builderops import epic_rehydration_probe as v1

UNKNOWN = v1.UNKNOWN
Error = v1.EpicRehydrationProbeError
EVENT_KINDS = (
    "agent_start", "handoff", "admission_retry", "implementation_repair",
    "review_repair", "ci_repair",
)
EVENT_DEFINITIONS = {
    "agent_start": "Successful admission of a fresh probe agent; rejected admissions are not starts.",
    "handoff": "One transfer of the frozen packet to the probe or original response to the coordinator.",
    "admission_retry": "A new admission attempt after an explicitly rejected native invocation; not a code repair.",
    "implementation_repair": "A code/test correction after a failed implementation check within this probe scope.",
    "review_repair": "A code/test correction responding to an independent review within this probe scope.",
    "ci_repair": "A code/test correction responding to CI failure within this probe scope.",
}
USAGE_UNITS = {"input_tokens": "tokens", "output_tokens": "tokens", "model_cost_usd": "USD", "human_minutes": "minutes"}
PROVENANCE: dict[str, Any] = {
    "type": "array", "minItems": 1,
    "items": {
        "type": "object", "additionalProperties": False, "required": ["kind", "ref"],
        "properties": {"kind": {"enum": ["github", "repository", "dispatcher", "checkpoint", "agent", "independent_audit"]}, "ref": {"type": "string", "minLength": 1}},
    },
}
STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING}
SHA = {"type": "string", "pattern": "^[0-9a-f]{40}$", "minLength": 40, "maxLength": 40}


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def maybe(shape: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [{"const": UNKNOWN}, shape]}


CI_SCOPE = "all_returned_pr_rollup_entries_including_historical_duplicates_not_a_current_required_ci_verdict"
CI = obj({"status": {"enum": ["green", "pending", "red", UNKNOWN]}, "scope": {"const": CI_SCOPE}})
EXTERNAL = obj({
    "issue": maybe(STRING), "pr": maybe(STRING), "pr_head_sha": maybe(SHA),
    "merge_sha": maybe(SHA), "repository_head": maybe(SHA), "ci": CI,
    "dispatcher": maybe(obj({"coordination_mode": STRING, "db_exists": {"type": "boolean"}})),
})
FIELD_SHAPES = {
    "slice_status": maybe(STRING),
    "checkpoint_decision_delta": maybe(STRINGS),
    "checkpoint_gate_invariants": maybe(obj({key: {"const": "unchanged_required"} for key in ("ci", "independent_review", "merge", "closure")})),
    "open_review_findings": maybe(STRINGS),
    "external_state": maybe(EXTERNAL),
    "checkpoint_recommendations": maybe(obj({
        "recommendations": obj({"coordinator_lifecycle": {"enum": ["keep", "checkpoint_rotate"]}, "slice_execution": {"enum": ["inline", "thin_worker"]}, "model_tier": {"enum": ["luna", "terra", "sol"]}}),
        "reasons": STRINGS,
    })),
    "live_slice_next_action": maybe(obj({"action": STRING, "reason": STRING})),
    "missing_claims": maybe(STRINGS),
    "fabricated_claims": maybe(STRINGS),
}
COMPARED = tuple(FIELD_SHAPES)[:6]
LIVE_FIELD_KINDS = {"slice_status": ("github",), "open_review_findings": ("github",), "external_state": ("github", "repository", "dispatcher"), "live_slice_next_action": ("github",)}


def _provenance_contract(kinds: tuple[str, ...], *, require_each: bool = False) -> dict[str, Any]:
    schema = deepcopy(PROVENANCE)
    schema["items"]["properties"]["kind"] = {"enum": list(kinds)}
    if require_each:
        schema["allOf"] = [{"contains": {"properties": {"kind": {"const": kind}}}} for kind in kinds]
    return schema


def _field_contract(name: str, shape: dict[str, Any]) -> dict[str, Any]:
    kinds = LIVE_FIELD_KINDS.get(name, ("checkpoint",) if name.startswith("checkpoint_") else ("agent",))
    return obj({"value": shape, "provenance": _provenance_contract(kinds, require_each=True), "notes": STRINGS})


AGENT = obj({"admitted_model": STRING, "admitted_reasoning_effort": STRING,
             "engine_identity": STRING, "engine_identity_source": STRING,
             "start_status": {"const": "succeeded"}, "start_observed_at": STRING})
TARGET = obj({"repository": STRING, "issue_number": {"type": "integer", "minimum": 1}, "pr_number": {"type": "integer", "minimum": 1}, "verified_pr_head_sha": SHA, "merge_sha": SHA})
BINDING = obj({"ref": STRING, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "minLength": 64, "maxLength": 64}, "bytes_length": {"type": "integer", "minimum": 1}})
LIVE_READS = {"type": "array", "items": obj({"kind": {"enum": ["github", "repository", "dispatcher"]}, "evidence": BINDING})}
LIVE_READ_CONTRACT = obj({
    "schema_name": {"const": "epic_rehydration_live_read"}, "schema_version": {"type": "integer", "const": 2},
    "probe_id": STRING, "kind": {"enum": ["github", "repository", "dispatcher"]},
    "target": obj({key: TARGET["properties"][key] for key in ("repository", "issue_number", "pr_number")}),
    "observed_at": STRING, "availability": {"enum": ["observed", "unavailable"]},
    "payload": {"anyOf": [{"type": "object"}, {"const": UNKNOWN}]}, "unavailable_reason": {"type": "string"},
})
THREADS = obj({"repository": STRING, "pr_number": {"type": "integer", "minimum": 1}, "nodes": {"type": "array", "items": obj({"isResolved": {"type": "boolean"}, "url": STRING})}, "complete": {"type": "boolean"}})
LIVE_PAYLOADS = {
    "github": obj({"issue": {"type": "object", "required": ["number", "url", "state"]}, "pr": {"type": "object", "required": ["number", "url", "state"]}, "review_threads": THREADS}),
    "repository": obj({"head_sha": SHA, "remote": {"const": "origin"}, "ref": {"const": "refs/heads/main"}}),
    "dispatcher": {"type": "object", "required": ["ok", "db_exists", "coordination_mode", "configured_repositories"], "properties": {"ok": {"const": True}, "db_exists": {"type": "boolean"}, "coordination_mode": STRING, "configured_repositories": STRINGS}},
}
LIVE_READ_CONTRACT["allOf"] = [
    {"if": {"properties": {"availability": {"const": "unavailable"}}}, "then": {"properties": {"payload": {"const": UNKNOWN}, "unavailable_reason": STRING}}, "else": {"properties": {"payload": {"type": "object"}, "unavailable_reason": {"const": ""}}}},
    *[{"if": {"properties": {"kind": {"const": kind}, "availability": {"const": "observed"}}}, "then": {"properties": {"payload": shape}}} for kind, shape in LIVE_PAYLOADS.items()],
]
CHECKPOINT_POINTERS = {
    "checkpoint_decision_delta": "/source/receipt/checkpoint/decision_log_delta",
    "checkpoint_gate_invariants": "/source/receipt/gate_invariants",
    "checkpoint_recommendations": "/source/receipt/recommendations",
}
RESPONSE_CONTRACT = obj({
    "schema_name": {"const": v1.OBSERVATION_SCHEMA_NAME}, "schema_version": {"type": "integer", "const": 2},
    "probe_id": STRING, "observed_at": STRING, "target": TARGET, "agent": AGENT, "context_pack": BINDING,
    "fields": obj({name: _field_contract(name, shape) for name, shape in FIELD_SHAPES.items()}),
    "live_reads": LIVE_READS, "limitations": STRINGS,
})
RESPONSE_CONTRACT["properties"]["live_reads"]["description"] = "Exactly one github, repository and dispatcher local live-read evidence binding, observed at/after this agent's successful admission and at/before this response. Local paths resolve from repository CWD; URI/fragment refs and final symlinks are refused. Evidence must satisfy the carried live_read_contract and exclude packet/source/custody canonical paths and device/inode identities. This binds trusted recorder attestation, not authenticated fetch truth."
RESPONSE_CONTRACT["properties"]["context_pack"]["description"] = "Exact raw packet binding used by this observer. File-aware comparison, telemetry, receipt and audit consumers require this same ref, SHA256 and byte length, not another serialization of equivalent JSON."
RESPONSE_CONTRACT["live_read_contract"] = LIVE_READ_CONTRACT
RESPONSE_CONTRACT["checkpoint_pointers"] = CHECKPOINT_POINTERS
FIELD_MEANINGS = {
    "slice_status": "Independently observed live slice lifecycle; closed_merged means Issue CLOSED and PR MERGED. Never copy status from the checkpoint without a live read.",
    "checkpoint_decision_delta": "Exact ordered decision_log_delta strings from this packet's accepted source checkpoint, not a paraphrase or a live decision.",
    "checkpoint_gate_invariants": "Exact gate_invariants object declared by this packet's source checkpoint; not proof that a live gate passed.",
    "open_review_findings": "Independently read unresolved review-thread URLs; [] requires a complete live thread read, unavailable evidence is unknown.",
    "external_state": "Independent live projections: lower-case number:state Issue/PR strings, exact SHAs, named-scope CI rollup classification, dispatcher mode/DB availability. Never inherit missing dimensions from source.",
    "checkpoint_recommendations": "Exact source recommendations and ordered recommendation_reasons, not the live slice's next action. Provenance uses the exact /source/receipt/recommendations pointer for this paired projection.",
    "live_slice_next_action": "Independently grounded action/reason for this live slice; intentionally not comparable to checkpoint evaluator recommendations.",
    "missing_claims": "Ordered comparable field names whose observation is unknown or has an unknown dimension; not JSON keys omitted from this strict response.",
    "fabricated_claims": "Unknown unless an independent auditor establishes field names with separately retained facts; mismatch and self-report alone are not fabrication proof.",
}
for _name, _meaning in FIELD_MEANINGS.items():
    RESPONSE_CONTRACT["properties"]["fields"]["properties"][_name]["description"] = _meaning
_Validator = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, instance: type(instance) is int))


def _validate(value: Any, schema: dict[str, Any], field: str) -> None:
    v1._assert_json_values(value, field)
    try:
        _Validator(schema).validate(value)
    except ValidationError as exc:
        raise Error(f"{field} violates v2 contract at {list(exc.absolute_path)}: {exc.message}") from exc


def _exact(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    result = v1._strict_object(value, field)
    v1._exact_fields(result, keys, field)
    return result


def _envelope(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    result = _exact(value, keys | {"schema_name", "schema_version", "probe_id"}, name)
    if result["schema_name"] != name or type(result["schema_version"]) is not int or result["schema_version"] != 2:
        raise Error(f"unsupported {name} version")
    v1._required_string(result["probe_id"], f"{name}.probe_id")
    return result


def _bound_ref(ref: str, value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    path = Path(v1._required_string(ref, "evidence.ref"))
    if path.is_symlink() or not path.is_file():
        raise Error(f"evidence must be a retained regular file: {ref}")
    raw = path.read_bytes()
    parsed = v1.parse_strict_json(raw, field=ref)
    if value is not None and not v1._json_exact_equal(parsed, value):
        raise Error(f"evidence does not bind normalized object: {ref}")
    return {"ref": ref, "sha256": v1.sha256_bytes(raw), "bytes_length": len(raw)}


def _read_bound(binding: Any) -> dict[str, Any]:
    record = _exact(binding, {"ref", "sha256", "bytes_length"}, "evidence binding")
    actual = _bound_ref(record["ref"])
    if not v1._json_exact_equal(record, actual):
        raise Error("retained evidence digest/length mismatch")
    return v1._read_json_file(Path(record["ref"]))


def _observation_packet(pack: Mapping[str, Any], observation: Mapping[str, Any], ref: str | None = None) -> dict[str, Any]:
    binding = observation["context_pack"]
    if not v1._json_exact_equal(_read_bound(binding), pack):
        raise Error("observation packet binding is not context-pack bound")
    if ref is not None and not v1._json_exact_equal(binding, _bound_ref(ref, pack)):
        raise Error("packet ref/digest/length differs from the observer's exact raw packet")
    return binding


def _local_evidence_path(ref: Any) -> Path:
    """Classify before treating a string as a filesystem path; no opaque fallback."""
    text = v1._required_string(ref, "local live evidence ref")
    parsed = urlsplit(text)
    if text != ref or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "#" in text:
        raise Error("live evidence refs must be local file paths without URI/query/fragment syntax")
    path = Path(text)
    if path.is_symlink() or not path.is_file():
        raise Error("live evidence requires a readable regular non-symlink file")
    return path.resolve(strict=True)


def _independent_read(binding: Any, *, kind: str, pack: Mapping[str, Any], packet_binding: Mapping[str, Any], observed_at: str, earliest_at: str | None = None) -> dict[str, Any]:
    record = _exact(binding, {"ref", "sha256", "bytes_length"}, "live evidence binding")
    candidate = _local_evidence_path(record["ref"])
    excluded = (*closure_paths(pack), Path(packet_binding["ref"]))
    candidate_stat = candidate.stat()
    for path in excluded:
        if candidate == path.resolve() or (path.is_file() and (candidate_stat.st_dev, candidate_stat.st_ino) == (path.stat().st_dev, path.stat().st_ino)):
            raise Error("packet/source/custody identity is not independent live evidence")
    read = _read_bound(record)
    _validate(read, LIVE_READ_CONTRACT, "live read evidence")
    target = {key: pack["target"][key] for key in ("repository", "issue_number", "pr_number")}
    if read["kind"] != kind or read["probe_id"] != pack["probe_id"] or not v1._json_exact_equal(read["target"], target):
        raise Error("live read domain/target/probe identity mismatch")
    lower_bound = max(_timestamp(pack["source"]["observed_at"]), _timestamp(earliest_at or pack["source"]["observed_at"]))
    if not lower_bound <= _timestamp(read["observed_at"]) <= _timestamp(observed_at):
        raise Error("live read observation time is outside its admitted observation interval")
    if read["availability"] == "unavailable":
        if read["payload"] != UNKNOWN:
            raise Error("unavailable live read must have unknown payload")
        v1._required_string(read["unavailable_reason"], "live read unavailable reason")
        return read
    if read["unavailable_reason"] != "" or type(read["payload"]) is not dict:
        raise Error("observed live read must retain its payload")
    payload = read["payload"]
    if kind == "github":
        _exact(payload, {"issue", "pr", "review_threads"}, "github live payload")
        issue, pr = payload["issue"], payload["pr"]
        for value, number, url_segment in ((issue, target["issue_number"], "issues"), (pr, target["pr_number"], "pull")):
            if type(value) is not dict or type(value.get("number")) is not int or value["number"] != number or value.get("url") != f"https://github.com/{target['repository']}/{url_segment}/{number}":
                raise Error("live GitHub payload has foreign target identity")
            v1._required_string(value.get("state"), "live GitHub state")
        if pr.get("headRefOid") is not None:
            _validate(pr["headRefOid"], SHA, "live PR head")
        merge = pr.get("mergeCommit")
        if merge is not None and (type(merge) is not dict or "oid" not in merge):
            raise Error("live PR merge identity is malformed")
        if merge is not None:
            _validate(merge["oid"], SHA, "live PR merge")
        threads = _exact(payload["review_threads"], {"repository", "pr_number", "nodes", "complete"}, "live review threads")
        if threads["repository"] != target["repository"] or type(threads["pr_number"]) is not int or threads["pr_number"] != target["pr_number"] or type(threads["complete"]) is not bool or type(threads["nodes"]) is not list:
            raise Error("live review thread identity/completeness is malformed")
        for node in threads["nodes"]:
            _validate(node, obj({"isResolved": {"type": "boolean"}, "url": STRING}), "live review thread")
            if not node["url"].startswith(f"https://github.com/{target['repository']}/pull/{target['pr_number']}#discussion_"):
                raise Error("live review thread URL is foreign to the target PR")
    elif kind == "repository":
        _validate(payload, obj({"head_sha": SHA, "remote": {"const": "origin"}, "ref": {"const": "refs/heads/main"}}), "live repository payload")
    elif kind == "dispatcher":
        if payload.get("ok") is not True or type(payload.get("db_exists")) is not bool:
            raise Error("live dispatcher payload is not an observed status")
        v1._required_string(payload.get("coordination_mode"), "live dispatcher mode")
        configured = payload.get("configured_repositories")
        if type(configured) is not list or target["repository"] not in configured:
            raise Error("live dispatcher payload is foreign to the target repository")
    return read


def _admit_provenance(name: str, provenance: Any, live_reads: Any, *, pack: Mapping[str, Any], packet_binding: Mapping[str, Any], observed_at: str, earliest_at: str | None = None) -> dict[str, Any]:
    """One field-aware admission boundary for observations and independent audit facts."""
    _validate(provenance, _field_contract(name, FIELD_SHAPES[name])["properties"]["provenance"], f"{name} provenance")
    _validate(live_reads, LIVE_READS, "live read bindings")
    if name in CHECKPOINT_POINTERS:
        expected = f"packet:{pack['probe_id']}#{CHECKPOINT_POINTERS[name]}"
        if any(item["ref"] != expected for item in provenance):
            raise Error("checkpoint provenance must use the exact field-specific packet pointer")
        if live_reads:
            raise Error("checkpoint audit facts do not borrow live-read authority")
        return {}
    if name not in LIVE_FIELD_KINDS:
        if any(item["ref"] != f"agent:{pack['probe_id']}" for item in provenance):
            raise Error("agent reporting provenance must identify this probe")
        return {}
    required = set(LIVE_FIELD_KINDS[name])
    reads = {}
    for item in live_reads:
        kind = item["kind"]
        if kind in reads:
            raise Error("duplicate live read kind")
        reads[kind] = _independent_read(item["evidence"], kind=kind, pack=pack, packet_binding=packet_binding, observed_at=observed_at, earliest_at=earliest_at)
    if not required.issubset(reads):
        raise Error("live field lacks all required independently retained read domains")
    refs = {(item["kind"], item["evidence"]["ref"]) for item in live_reads}
    if any((item["kind"], item["ref"]) not in refs for item in provenance):
        raise Error("live field provenance is not bound to its retained independent reads")
    return {kind: reads[kind] for kind in required}


def _live_facts(reads: Mapping[str, Any]) -> dict[str, Any]:
    github = reads.get("github", {})
    payload = github.get("payload", UNKNOWN)
    status: Any = UNKNOWN
    findings: Any = UNKNOWN
    external: dict[str, Any] = {key: UNKNOWN for key in EXTERNAL["properties"]}
    external["ci"] = {"status": UNKNOWN, "scope": CI_SCOPE}
    if type(payload) is dict:
        issue, pr, threads = payload["issue"], payload["pr"], payload["review_threads"]
        status = "closed_merged" if issue["state"].lower() == "closed" and pr["state"].lower() == "merged" else f"{issue['state'].lower()}_{pr['state'].lower()}"
        findings = sorted(node["url"] for node in threads["nodes"] if not node["isResolved"]) if threads["complete"] else UNKNOWN
        external.update(issue=f"{issue['number']}:{issue['state'].lower()}", pr=f"{pr['number']}:{pr['state'].lower()}", pr_head_sha=pr.get("headRefOid", UNKNOWN), merge_sha=(pr.get("mergeCommit") or {}).get("oid", UNKNOWN), ci=_ci_summary(pr))
    repository = reads.get("repository", {}).get("payload", UNKNOWN)
    dispatcher = reads.get("dispatcher", {}).get("payload", UNKNOWN)
    if type(repository) is dict:
        external["repository_head"] = repository["head_sha"]
    if type(dispatcher) is dict:
        external["dispatcher"] = {"coordination_mode": dispatcher["coordination_mode"], "db_exists": dispatcher["db_exists"]}
    _validate(external, EXTERNAL, "independent live external facts")
    return {"slice_status": status, "open_review_findings": findings, "external_state": external}


def _timestamp(value: Any) -> datetime:
    text = v1._required_string(value, "UTC timestamp")
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Error("timestamp must be ISO8601 UTC") from exc
    offset = result.utcoffset()
    if result.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise Error("timestamp must name UTC")
    return result


def _custody(pack: Mapping[str, Any]) -> dict[str, Any]:
    source = Path(pack["source"]["source_ref"])
    marker = pack["source"]["external_state_marker"]
    refs = {
        "issue": str(source.with_name(f"live-issue-{pack['target']['issue_number']}.json")),
        "pr": str(source.with_name(f"live-pr-{pack['target']['pr_number']}.json")),
        "dispatcher": marker.get("dispatcher_status_ref"),
        "repository": marker.get("repository_status_ref"),
    }
    return {key: _bound_ref(ref) for key, ref in refs.items()}


def _ci_summary(pr: Mapping[str, Any]) -> dict[str, str]:
    checks = pr.get("statusCheckRollup")
    if checks is not None and type(checks) is not list:
        raise Error("malformed check rollup")
    if not checks:
        return {"status": UNKNOWN, "scope": CI_SCOPE}
    states = [item.get("conclusion") or item.get("state") or item.get("status") for item in checks if type(item) is dict]
    if len(states) != len(checks):
        raise Error("malformed source check rollup")
    if any(state in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"} for state in states):
        status = "red"
    else:
        status = "green" if all(state in {"SUCCESS", "SKIPPED", "NEUTRAL"} for state in states) else "pending"
    return {"status": status, "scope": CI_SCOPE}


def _source_external(pack: Mapping[str, Any]) -> dict[str, Any]:
    custody = pack["source_custody"]
    issue, pr, dispatcher, repository = (_read_bound(custody[key]) for key in ("issue", "pr", "dispatcher", "repository"))
    # Raw source captures may retain diagnostic metadata, but their repository
    # identity must satisfy the same origin/main contract as independent reads.
    _validate({key: repository.get(key) for key in LIVE_PAYLOADS["repository"]["properties"]}, LIVE_PAYLOADS["repository"], "source repository custody")
    target = pack["target"]
    for value, key in ((issue, "issue_number"), (pr, "pr_number")):
        if type(value.get("number")) is not int or value["number"] != target[key]:
            raise Error("v2 source custody requires exact integer Issue/PR identity")
    if issue.get("url") != f"https://github.com/{target['repository']}/issues/{target['issue_number']}" or pr.get("url") != f"https://github.com/{target['repository']}/pull/{target['pr_number']}":
        raise Error("v2 source custody URLs must identify the exact target")
    issue_state = v1._required_string(issue.get("state"), "custody issue.state").lower()
    pr_state = v1._required_string(pr.get("state"), "custody pr.state").lower()
    result = {
        "issue": f"{issue['number']}:{issue_state}", "pr": f"{pr['number']}:{pr_state}",
        "pr_head_sha": pr["headRefOid"], "merge_sha": pr["mergeCommit"]["oid"],
        "repository_head": repository.get("head_sha"), "ci": _ci_summary(pr),
        "dispatcher": {"coordination_mode": dispatcher.get("coordination_mode"), "db_exists": dispatcher.get("db_exists")},
    }
    _validate(result, EXTERNAL, "source external projection")
    marker = pack["source"]["external_state_marker"]
    if not v1._json_exact_equal(marker.get("probe_external_state"), result):
        raise Error("v2 source marker is not bound to retained external custody")
    return result


def build_context_pack(source_bytes: bytes | str, **kwargs: Any) -> dict[str, Any]:
    if "schema_version" in kwargs:
        version = kwargs.pop("schema_version")
        if type(version) is not int or version != 2:
            raise Error("v2 builder requires explicit version 2")
    pack = v1.build_context_pack(source_bytes, **kwargs)
    pack.update(schema_version=2, response_contract=deepcopy(RESPONSE_CONTRACT))
    pack["source_custody"] = _custody(pack)
    return normalize_context_pack(pack)


def normalize_context_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    pack = _exact(value, {"schema_name", "schema_version", "probe_id", "source", "target", "read_instructions", "live_truth_precedence", "forbidden_effects", "effects", "response_contract", "source_custody"}, "v2 context pack")
    if type(pack["schema_version"]) is not int or pack["schema_version"] != 2:
        raise Error("unsupported v2 context pack version")
    base = {key: val for key, val in pack.items() if key not in {"response_contract", "source_custody"}}
    base["schema_version"] = 1
    v1.normalize_context_pack(base)
    _timestamp(pack["source"]["observed_at"])
    if not v1._json_exact_equal(pack["response_contract"], RESPONSE_CONTRACT):
        raise Error("v2 response field contract is not supported")
    if not v1._json_exact_equal(pack["source_custody"], _custody(pack)):
        raise Error("v2 source custody is not source-bound")
    _source_external(pack)
    for name, value in _expected_fields(pack).items():
        _validate(value, FIELD_SHAPES[name], f"source.{name}")
    return pack


def normalize_rehydrated_observation(value: Mapping[str, Any], *, context_pack: Mapping[str, Any] | None = None, context_pack_ref: str | None = None) -> dict[str, Any]:
    observation = v1._strict_object(value, "v2 observation")
    _validate(observation, RESPONSE_CONTRACT, "observation")
    if context_pack is None:
        raise Error("v2 observation admission requires context_pack")
    pack = normalize_context_pack(context_pack)
    _observation_packet(pack, observation, context_pack_ref)
    _timestamp(observation["observed_at"])
    _timestamp(observation["agent"]["start_observed_at"])
    if _timestamp(observation["observed_at"]) < _timestamp(observation["agent"]["start_observed_at"]):
        raise Error("observation predates agent start")
    if observation["probe_id"] != pack["probe_id"] or not v1._json_exact_equal(observation["target"], {key: pack["target"][key] for key in TARGET["properties"]}):
        raise Error("v2 observation identity is not context-pack bound")
    if len(observation["live_reads"]) != 3 or {item["kind"] for item in observation["live_reads"]} != {"github", "repository", "dispatcher"}:
        raise Error("observation requires exactly three distinct live read domains")
    for name, field in observation["fields"].items():
        _admit_provenance(name, field["provenance"], observation["live_reads"] if name in LIVE_FIELD_KINDS else [], pack=pack, packet_binding=observation["context_pack"], observed_at=observation["observed_at"], earliest_at=observation["agent"]["start_observed_at"])
    return observation


def _unknown(value: Any) -> bool:
    return value == UNKNOWN or (type(value) is dict and any(_unknown(item) for item in value.values()))


def _status(observed: Any, expected: Any) -> str:
    if observed == UNKNOWN or expected == UNKNOWN:
        return "unknown"
    if type(observed) is dict and type(expected) is dict:
        statuses = [_status(observed[key], expected[key]) for key in expected]
        return "mismatch" if "mismatch" in statuses else "unknown" if "unknown" in statuses else "match"
    return "match" if v1._json_exact_equal(observed, expected) else "mismatch"


def _fabrication_audit(ref: str, pack: Mapping[str, Any], obs: Mapping[str, Any], *, observation_binding: Mapping[str, Any] | None = None) -> list[str]:
    audit = _envelope(_read_bound(_bound_ref(ref)), "epic_rehydration_fabrication_audit", {"context_pack", "observation", "auditor", "independence", "findings"})
    if audit["probe_id"] != pack["probe_id"] or audit["independence"] != "separate_agent_or_human":
        raise Error("fabrication audit must attest independent review of this probe")
    v1._required_string(audit["auditor"], "independent auditor")
    if not v1._json_exact_equal(_read_bound(audit["context_pack"]), pack) or not v1._json_exact_equal(_read_bound(audit["observation"]), obs):
        raise Error("independent fabrication audit is not packet/response-bound")
    if observation_binding is not None and not v1._json_exact_equal(audit["observation"], observation_binding):
        raise Error("audit response ref/digest/length differs from the joined raw response")
    _observation_packet(pack, obs, audit["context_pack"]["ref"])
    if type(audit["findings"]) is not list:
        raise Error("audit findings must be a list")
    names = []
    for value in audit["findings"]:
        finding = _exact(value, {"field", "claimed_value", "established_value", "evidence", "verdict"}, "fabrication finding")
        name = finding["field"]
        if name not in COMPARED or name in names or finding["verdict"] != "fabricated":
            raise Error("unsupported or duplicate independently audited field")
        _validate(finding["established_value"], FIELD_SHAPES[name], "independent fact")
        if _unknown(finding["claimed_value"]) or _unknown(finding["established_value"]) or not v1._json_exact_equal(finding["claimed_value"], obs["fields"][name]["value"]) or v1._json_exact_equal(finding["claimed_value"], finding["established_value"]):
            raise Error("fabrication audit lacks a distinct established fact for the actual claim")
        evidence = _envelope(_read_bound(finding["evidence"]), "epic_rehydration_independent_fact", {"field", "value", "provenance", "observed_at", "live_reads"})
        _timestamp(evidence["observed_at"])
        if evidence["probe_id"] != pack["probe_id"] or evidence["field"] != name or not v1._json_exact_equal(evidence["value"], finding["established_value"]):
            raise Error("audited fact is not independent-evidence bound")
        # Separate audit reads are source-to-fact bound, not this probe agent's reads.
        reads = _admit_provenance(name, evidence["provenance"], evidence["live_reads"], pack=pack, packet_binding=audit["context_pack"], observed_at=evidence["observed_at"], earliest_at=pack["source"]["observed_at"])
        established = _expected_fields(pack)[name] if name in CHECKPOINT_POINTERS else _live_facts(reads)[name]
        if not v1._json_exact_equal(evidence["value"], established):
            raise Error("audit established fact contradicts its own retained evidence")
        names.append(name)
    return names


def _expected_fields(pack: Mapping[str, Any]) -> dict[str, Any]:
    source = pack["source"]["receipt"]
    return {
        "slice_status": source["checkpoint"]["slice_status"],
        "checkpoint_decision_delta": source["checkpoint"]["decision_log_delta"],
        "checkpoint_gate_invariants": source["gate_invariants"],
        "open_review_findings": source["checkpoint"]["open_review_findings"],
        "external_state": _source_external(pack),
        "checkpoint_recommendations": {"recommendations": source["recommendations"], "reasons": source["recommendation_reasons"]},
    }


def compare_rehydrated_observation(context_pack: Mapping[str, Any], observation: Mapping[str, Any], *, fabrication_audit_ref: str | None = None, context_pack_ref: str | None = None, observation_ref: str | None = None) -> dict[str, Any]:
    pack = normalize_context_pack(context_pack)
    obs = normalize_rehydrated_observation(observation, context_pack=pack, context_pack_ref=context_pack_ref)
    expected = _expected_fields(pack)
    live = _live_facts(_admit_provenance("external_state", obs["fields"]["external_state"]["provenance"], obs["live_reads"], pack=pack, packet_binding=obs["context_pack"], observed_at=obs["observed_at"], earliest_at=obs["agent"]["start_observed_at"]))
    results = {}
    for name in COMPARED:
        field = obs["fields"][name]
        observed = field["value"]
        status = _status(observed, expected[name])
        results[name] = {"status": status, "expected": expected[name], "observed": observed, "provenance": field["provenance"], "notes": field["notes"]}
        if name in live:
            support = _status(observed, live[name])
            results[name]["independent_live_value"] = live[name]
            results[name]["evidence_support"] = support
            if support == "mismatch" or (support == "unknown" and status == "match"):
                results[name]["status"] = support
        if name == "external_state" and type(observed) is dict:
            results[name]["dimensions"] = {key: {"status": _status(observed[key], expected[name][key]), "expected": expected[name][key], "observed": observed[key]} for key in EXTERNAL["properties"]}
    missing = [name for name in COMPARED if _unknown(obs["fields"][name]["value"])]
    response_binding = None if observation_ref is None else _bound_ref(observation_ref, obs)
    audited_fabrications: Any = UNKNOWN if fabrication_audit_ref is None else _fabrication_audit(fabrication_audit_ref, pack, obs, observation_binding=response_binding)
    for name, expectation, forced_status in (
        ("live_slice_next_action", UNKNOWN, "not_comparable"),
        ("missing_claims", missing, None),
        ("fabricated_claims", audited_fabrications, "unknown" if audited_fabrications == UNKNOWN else None),
    ):
        field = obs["fields"][name]
        results[name] = {"status": forced_status or v1._comparison_status(field["value"], expectation), "expected": expectation, "observed": field["value"], "provenance": field["provenance"], "notes": field["notes"]}
    return {
        "schema_name": v1.COMPARISON_SCHEMA_NAME, "schema_version": 2, "probe_id": pack["probe_id"],
        "target": pack["target"], "context_pack": deepcopy(pack), "observation": deepcopy(obs),
        "fabrication_audit": UNKNOWN if fabrication_audit_ref is None else _bound_ref(fabrication_audit_ref),
        "field_results": results,
        "external_refresh": {"status": _status(live["external_state"], expected["external_state"]), "refresh_required": _status(live["external_state"], expected["external_state"]) != "match"},
        "limitations": obs["limitations"] + ["Drift is not fabrication. Fabrication requires a retained independent auditor attestation with separately retained facts; absent audit remains unknown. This validator binds custody, not auditor identity or source truth. Live next action has no checkpoint-recommendation equivalent."],
        "effects": {key: [] for key in v1._EFFECT_CATEGORIES},
    }


def normalize_comparison(value: Mapping[str, Any], *, context_pack: Mapping[str, Any] | None = None, observation: Mapping[str, Any] | None = None, observation_ref: str | None = None) -> dict[str, Any]:
    comparison = _envelope(value, v1.COMPARISON_SCHEMA_NAME, {"target", "context_pack", "observation", "fabrication_audit", "field_results", "external_refresh", "limitations", "effects"})
    pack = normalize_context_pack(comparison["context_pack"])
    obs = normalize_rehydrated_observation(comparison["observation"], context_pack=pack)
    if context_pack is not None and not v1._json_exact_equal(pack, normalize_context_pack(context_pack)):
        raise Error("comparison context pack is foreign")
    if observation is not None and not v1._json_exact_equal(obs, normalize_rehydrated_observation(observation, context_pack=pack)):
        raise Error("comparison observation is foreign")
    audit_ref = None
    if comparison["fabrication_audit"] != UNKNOWN:
        _read_bound(comparison["fabrication_audit"])
        audit_ref = comparison["fabrication_audit"]["ref"]
    if not v1._json_exact_equal(comparison, compare_rehydrated_observation(pack, obs, fabrication_audit_ref=audit_ref, observation_ref=observation_ref)):
        raise Error("comparison is not semantically bound to packet and observation")
    return comparison


def _measurement(value: Any, unit: str, scope: str, source: Any, *, availability: str = "measured", reason: str = "") -> dict[str, Any]:
    return {"availability": availability, "value": value, "unit": unit, "scope": scope, "source": source, "reason": reason}


def _execution_log(value: Mapping[str, Any], pack: Mapping[str, Any], obs: Mapping[str, Any]) -> dict[str, Any]:
    log = _envelope(value, "epic_rehydration_execution_log", {"clock", "started_at", "ended_at", "invocation", "events", "events_complete", "recorder", "usage"})
    if log["probe_id"] != pack["probe_id"]:
        raise Error("execution log probe identity mismatch")
    if log["events_complete"] is not True:
        raise Error("execution event counts require recorder-attested complete scope coverage")
    v1._required_string(log["recorder"], "execution recorder")
    clock = _exact(log["clock"], {"name", "unit", "scope"}, "execution clock")
    for key in ("name", "scope"):
        v1._required_string(clock[key], f"clock.{key}")
    if clock["unit"] != "seconds":
        raise Error("execution wall clock unit must be seconds")
    start, end = _timestamp(log["started_at"]), _timestamp(log["ended_at"])
    if end < start or not start <= _timestamp(obs["observed_at"]) <= end:
        raise Error("execution interval contradicts response observation time")
    _validate(log["invocation"], AGENT, "execution invocation")
    if not v1._json_exact_equal(log["invocation"], obs["agent"]):
        raise Error("execution invocation is not observation-bound")
    events = log["events"]
    if type(events) is not list:
        raise Error("execution events must be a list")
    previous = start
    event_ids: set[str] = set()
    for event in events:
        event = _exact(event, {"id", "kind", "at", "evidence"}, "execution event")
        event_id = v1._required_string(event["id"], "event.id")
        if event_id in event_ids:
            raise Error("duplicate execution event id")
        event_ids.add(event_id)
        if event["kind"] not in EVENT_KINDS:
            raise Error("unsupported execution event kind")
        at = _timestamp(event["at"])
        if not previous <= at <= end:
            raise Error("execution events are out of order or interval")
        previous = at
        v1._required_string(event["evidence"], "event.evidence")
    starts = [event for event in events if event["kind"] == "agent_start"]
    if len(starts) != 1 or _timestamp(starts[0]["at"]) != _timestamp(obs["agent"]["start_observed_at"]):
        raise Error("one observation-bound successful agent_start is required")
    start_index = events.index(starts[0])
    if any(event["kind"] == "admission_retry" for event in events[start_index + 1:]):
        raise Error("admission retry cannot follow the successful probe admission")
    usage = _exact(log["usage"], set(USAGE_UNITS), "execution usage")
    for key, unit in USAGE_UNITS.items():
        item = _exact(usage[key], {"availability", "value", "unit", "scope", "source", "reason"}, f"usage.{key}")
        if item["unit"] != unit or item["scope"] != clock["scope"]:
            raise Error("usage unit/scope mismatch")
        if item["availability"] == "unknown":
            if item["value"] != UNKNOWN or type(item["source"]) is not str:
                raise Error("unknown usage must retain unavailable source and unknown value")
            v1._required_string(item["source"], "unavailable usage source")
            v1._required_string(item["reason"], "unavailable usage reason")
        elif item["availability"] in {"measured", "attested"}:
            authority = _envelope(_read_bound(item["source"]), "epic_rehydration_usage_authority", {"authority", "metric", "value", "unit", "scope", "observed_at", "source"})
            authority_kind = "human_attestation" if key == "human_minutes" else "carrier_usage_receipt"
            if authority["authority"] != authority_kind or authority["probe_id"] != pack["probe_id"] or authority["metric"] != key or authority["unit"] != unit or authority["scope"] != clock["scope"] or not v1._json_exact_equal(authority["value"], item["value"]):
                raise Error("known usage is not authoritative-receipt bound")
            _timestamp(authority["observed_at"])
            v1._required_string(authority["source"], "usage authority source")
            v1._required_string(item["reason"], "known usage evidence explanation")
            v1._unknown_or_finite_non_negative(item["value"], key)
            if item["value"] == UNKNOWN or (key.endswith("tokens") and type(item["value"]) is not int):
                raise Error("known usage must have a measured value in the declared unit")
        else:
            raise Error("unsupported usage availability")
    return log


def build_telemetry(context_pack: Mapping[str, Any], observation: Mapping[str, Any], *, pack_ref: str, observation_ref: str, execution_ref: str) -> dict[str, Any]:
    pack = normalize_context_pack(context_pack)
    obs = normalize_rehydrated_observation(observation, context_pack=pack, context_pack_ref=pack_ref)
    bindings = {"context_pack": _bound_ref(pack_ref, pack), "observation": _bound_ref(observation_ref, obs), "execution": _bound_ref(execution_ref)}
    log = _execution_log(_read_bound(bindings["execution"]), pack, obs)
    scope = log["clock"]["scope"]
    measurements = {
        "packet_bytes": _measurement(bindings["context_pack"]["bytes_length"], "bytes", "exact retained UTF-8 context packet", bindings["context_pack"]),
        "response_bytes": _measurement(bindings["observation"]["bytes_length"], "bytes", "exact original retained UTF-8 response", bindings["observation"]),
        "elapsed_wall_time": _measurement((_timestamp(log["ended_at"]) - _timestamp(log["started_at"])).total_seconds(), "seconds", scope, bindings["execution"]),
    }
    for kind in EVENT_KINDS:
        measurements[kind] = _measurement(sum(event["kind"] == kind for event in log["events"]), "events", scope, bindings["execution"])
    measurements.update(log["usage"])
    return {"schema_name": "epic_rehydration_telemetry", "schema_version": 2, "probe_id": pack["probe_id"], "evidence": bindings, "clock": log["clock"], "started_at": log["started_at"], "ended_at": log["ended_at"], "event_definitions": EVENT_DEFINITIONS, "measurements": measurements, "effects": {key: [] for key in v1._EFFECT_CATEGORIES}}


def normalize_telemetry(value: Mapping[str, Any]) -> dict[str, Any]:
    telemetry = _envelope(value, "epic_rehydration_telemetry", {"evidence", "clock", "started_at", "ended_at", "event_definitions", "measurements", "effects"})
    evidence = _exact(telemetry["evidence"], {"context_pack", "observation", "execution"}, "telemetry evidence")
    expected = build_telemetry(_read_bound(evidence["context_pack"]), _read_bound(evidence["observation"]), pack_ref=evidence["context_pack"]["ref"], observation_ref=evidence["observation"]["ref"], execution_ref=evidence["execution"]["ref"])
    if not v1._json_exact_equal(telemetry, expected):
        raise Error("telemetry contradicts retained byte, clock or event evidence")
    return telemetry


def build_probe_receipt(context_pack: Mapping[str, Any], observation: Mapping[str, Any], comparison: Mapping[str, Any], *, evidence_refs: Mapping[str, str], telemetry: Mapping[str, Any], source_observed_at: str | None = None) -> dict[str, Any]:
    refs = v1._normalize_evidence_refs(evidence_refs)
    pack = normalize_context_pack(context_pack)
    obs = normalize_rehydrated_observation(observation, context_pack=pack)
    comp = normalize_comparison(comparison, context_pack=pack, observation=obs, observation_ref=refs["agent_response"])
    measured = normalize_telemetry(telemetry)
    if source_observed_at is not None and source_observed_at != pack["source"]["observed_at"]:
        raise Error("source observed_at is not packet-bound")
    v1._validate_source_ref_binding(refs["source_checkpoint"], pack["source"]["bytes_sha256"], pack["source"]["bytes_length"], pack["source"]["receipt"])
    if refs["source_checkpoint"] != pack["source"]["source_ref"]:
        raise Error("source ref differs from packet custody")
    bindings = {"context_pack": _bound_ref(refs["context_pack"], pack), "observation": _bound_ref(refs["agent_response"], obs), "comparison": _bound_ref(refs["comparison_receipt"], comp)}
    _observation_packet(pack, obs, refs["context_pack"])
    if measured["probe_id"] != pack["probe_id"] or measured["evidence"]["context_pack"] != bindings["context_pack"] or measured["evidence"]["observation"] != bindings["observation"]:
        raise Error("telemetry is not bound to receipt chain")
    return {"schema_name": v1.PROBE_RECEIPT_SCHEMA_NAME, "schema_version": 2, "probe_id": pack["probe_id"], "mode": "one_manual_read_only", "source_checkpoint": deepcopy(pack["source"]), **bindings, "target": pack["target"], "agent": obs["agent"], "telemetry": measured, "evidence": refs, "effects": {key: [] for key in v1._EFFECT_CATEGORIES}, "limitations": comp["limitations"]}


def normalize_probe_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    receipt = _envelope(value, v1.PROBE_RECEIPT_SCHEMA_NAME, {"mode", "source_checkpoint", "context_pack", "observation", "comparison", "target", "agent", "telemetry", "evidence", "effects", "limitations"})
    pack = _read_bound(receipt["context_pack"])
    obs = _read_bound(receipt["observation"])
    comp = _read_bound(receipt["comparison"])
    expected = build_probe_receipt(pack, obs, comp, evidence_refs=receipt["evidence"], telemetry=receipt["telemetry"])
    if not v1._json_exact_equal(receipt, expected):
        raise Error("standalone v2 receipt is not bound to the complete normalized chain")
    return receipt


def closure_paths(pack: Mapping[str, Any], telemetry: Mapping[str, Any] | None = None) -> tuple[Path, ...]:
    paths = list(v1._context_pack_closure_paths(pack))
    paths.extend(Path(item["ref"]) for item in pack["source_custody"].values())
    if telemetry is not None:
        paths.extend(Path(item["ref"]) for item in telemetry["evidence"].values())
        log = _read_bound(telemetry["evidence"]["execution"])
        paths.extend(Path(item["source"]["ref"]) for item in log["usage"].values() if type(item["source"]) is dict)
    return tuple(paths)
