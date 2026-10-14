"""Bounded read-time wiring for the separate Builder System Control lens.

The candidate owns document bytes; existing sources own their observations.
Diagnostic destinations are optional explicit addresses, never discovered or probed.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from app.builderops.devui_builder_system_control import compose_builder_system_control_view
from app.builderops.devui_sources import SourceConfiguration

GOVERNING_PATHS = (
    "docs/DEVUI.md",
    "docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md",
    "docs/architecture/SBS_OPERATING_MODEL.md",
    "docs/development/DEV_WORKFLOW.md",
    "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md",
)
_SUBJECT = re.compile(r"github:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#[1-9][0-9]*\Z", re.ASCII)


class ControlInputError(ValueError):
    """An explicit scope or destination cannot support navigation."""


def validate_control_destination(value: str | None, *, origin_only: bool) -> str | None:
    """Validate a navigation address only; never connect or forward credentials."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query or parsed.fragment
            or any(c.isspace() or ord(c) < 32 for c in value)
            or "\\" in value
            or "%" in value
            or (origin_only and parsed.path not in {"", "/"})
            or ".." in parsed.path.split("/")
            or (parsed.port is not None and parsed.port < 1)
        ):
            raise ValueError()
        if parsed.scheme == "http" and not (
            parsed.hostname == "localhost" or ip_address(parsed.hostname).is_loopback
        ):
            raise ValueError()
    except ValueError as exc:
        raise ControlInputError("diagnostic navigation address is invalid") from exc
    return value.rstrip("/") if origin_only else value


def validate_return_subject(subject: str | None, repository: str | None) -> str | None:
    if subject is None:
        return None
    match = _SUBJECT.fullmatch(subject)
    if match is None or repository is None or match[1].lower() != repository.lower():
        raise ControlInputError("prior Focus must be one Issue in the addressed repository")
    return subject


def _reference(config: SourceConfiguration, path: str) -> dict[str, str]:
    return {
        "source_type": "repository_document",
        "source_id": path,
        "version": config.candidate_sha,
        "locator": f"https://github.com/{config.repository}/blob/{config.candidate_sha}/{path}",
    }


def _document(config: SourceConfiguration, path: str, stamp: str) -> tuple[dict[str, Any], dict[str, str]]:
    ref = _reference(config, path)
    availability, freshness = "unavailable", "unknown"
    headers: dict[str, str] = {}
    reason = "Candidate document is missing; governance completeness is not declared."
    try:
        root = config.candidate_root
        file = root / path
        if root.is_symlink() or (root / "manifest.json").is_symlink():
            raise ValueError()
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["repository"] != config.repository or manifest["source_sha"] != config.candidate_sha:
            raise ValueError()
        if any(parent.is_symlink() for parent in (file, *file.parents) if parent == root or root in parent.parents):
            raise ValueError()
        content = file.read_bytes()
        if len(content) > 1024 * 1024:
            raise ValueError()
        digest = hashlib.sha256(content).hexdigest()
        if manifest["files"].get(path) != digest:
            raise ValueError()
        ref["content_hash"] = digest
        # Only literal document-header declarations; no inferred lifecycle, policy or owner.
        current_header: str | None = None
        for line in content.decode("utf-8").splitlines()[:40]:
            if line.startswith("#"):
                break
            key, separator, text = line.partition(": ")
            if separator and re.fullmatch(r"[A-Za-z][A-Za-z -]+", key):
                current_header = key if key in {"Doc role", "Authority", "Owner", "State", "Last reviewed"} else None
                if current_header:
                    headers[current_header] = text
            elif current_header and line.strip():
                headers[current_header] += "\n" + line
            else:
                current_header = None
        availability, freshness = "available", "fresh"
        reason = "Exact candidate bytes were read; typed lifecycle and governance completeness remain undeclared."
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        availability = "refused"
        reason = "Candidate document identity or content was refused; no document claims are admitted."
    declaration = {
        "source_ref": ref,
        "role": headers.get("Doc role", path),
        "authority_class": "reference" if path in {"docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md", "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"} else "normative",
        "authority_scope": headers.get("Authority", "Authority scope is not declared"),
        "owner_ref": ref if headers.get("Owner") else None,
        "source_state": {
            "availability": availability, "freshness": freshness, "coverage": "missing",
            "cardinality": "not_measured", "linkage": "linked" if headers.get("Owner") else "unlinked",
            "captured_at": stamp, "freshness_rule": "exact candidate bytes verified at this read; no live-policy freshness claim",
            "read_scope": path, "read_watermark": config.candidate_sha, "limitations": [reason],
        },
        "limitations": [reason],
    }
    return declaration, headers


def _inspect(label: str, role: str, href: str | None, limitation: str, *, context: str = "unsupported") -> dict[str, Any]:
    return {"label": label, "role": role, "href": href, "destination_state": "unread" if href else "unavailable",
            "context": context, "limitations": [limitation]}


def read_system_control(
    config: SourceConfiguration, composition: Mapping[str, Any], *,
    return_subject: str | None = None, diagnostic_origin: str | None = None,
    ckm_overview_url: str | None = None,
) -> dict[str, Any]:
    """Compose only the addressed candidate and existing read envelope, without effects."""
    if config.repository is None:
        raise ControlInputError("Builder System Control requires an explicit repository binding")
    prior = validate_return_subject(return_subject, config.repository)
    origin = validate_control_destination(diagnostic_origin, origin_only=True)
    ckm_url = validate_control_destination(ckm_overview_url, origin_only=False)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    read_documents = [_document(config, path, stamp) for path in GOVERNING_PATHS]
    control = compose_builder_system_control_view(
        repository_ref=config.repository,
        governance_baseline_ref=_reference(config, "docs/architecture/SBS_OPERATING_MODEL.md"),
        composed_at=stamp, governing_document_declarations=[d for d, _ in read_documents],
        workflow_adapter_declarations=[], capability_binding_declarations=[], coverage_declarations=[],
        route_deviation_declarations=[], governed_route_declarations=[],
        limitations=["This finite document read declares no complete governance, adapter or capability inventory.",
                     "Coverage, exceptions and intended-to-observed route correlations are unread, not healthy or measured empty.",
                     "Repository delivery does not establish live source qualification, VM102 deployment, pilot or owner acceptance."],
    )
    api = config.api_environment.get("BUILDEROPS_API_URL")
    # The source configuration already admits this address. Recheck before exposing an outlink.
    api = validate_control_destination(api, origin_only=True)
    inspect = [
        _inspect("BuilderOps control plane", "authenticated source", f"{api}/v1/tasks?{urlencode({'repository': config.repository})}" if api else None,
                 "Destination requires its own authentication. DevUI never forwards its source credential or proves browser reachability.", context="repository"),
        _inspect("Cockpit", "diagnostic projection", f"{origin}/cockpit" if origin else None,
                 "The legacy Cockpit does not consume selected-subject or repository URL context. DevUI context stays in this tab."),
        _inspect("Signboard board", "read-only diagnostic", f"{origin}/api/signboard/board" if origin else None,
                 "This GET reads the source board. It has no selected-context URL contract."),
        _inspect("Signboard recovery", "operational recovery", f"{origin}/signboard" if origin else None,
                 "Opening Signboard triggers a refresh POST and its controls permit writes under its own authority. This is operational recovery."),
        _inspect("CKM Development Overview", "generated diagnostic projection", ckm_url,
                 "CKM has no built-in HTTP route and its managed reader is unavailable. An explicitly hosted generated view remains unread and non-authoritative."),
        _inspect("Legacy BuilderOps records", "diagnostic source", f"{origin}/api/builderops/records" if origin else None,
                 "Legacy Product-hosted records are a distinct source, not the standalone control plane; selected context is unsupported."),
        _inspect("Legacy status", "Product diagnostic", f"{origin}/api/status" if origin else None,
                 "This is the earlier Product status diagnostic, not complete Builder System health."),
        _inspect("DevUI candidate identity", "local diagnostic", "/version", "Image metadata is diagnostic identity, not independent deployment attestation.", context="candidate"),
        _inspect("DevUI listener health", "local diagnostic", "/healthz", "Listener liveness does not establish complete Dev System health.", context="candidate"),
    ]
    providers = composition.get("providers", {})
    return {
        "control": control,
        "document_headers": {path: headers for path, (_, headers) in zip(GOVERNING_PATHS, read_documents)},
        "composition": {key: value for key, value in composition.items() if key != "providers"} | {
            "providers": {name: {key: value for key, value in provider.items() if key != "payload"}
                          for name, provider in providers.items()},
        },
        "inspect": inspect,
        "navigation": {"overview": "/devui/overview", "prior_focus_subject": prior,
                       "focus": f"/devui/focus?subject={quote(prior, safe='')}" if prior else None},
    }


def bind_managed_control_assets(root: Any) -> None:
    """Apply only the reviewed content/interaction binding to image-baked assets.

    Companion source assets remain unchanged. Repeated packaging is idempotent;
    unknown input bytes fail rather than receiving an unreviewed transformation.
    """
    from app.builderops.devui_assets import ASSET_SHA256, CandidateAssetError

    originals = {
        "overview.html": "6e0b20cf2aca808d1330bc6033994e9f9acb7b17c9cf46d3f61479995fa7b2b5",
        "focus.html": "464e2f2ee5ba59268177261ac6f8f9464cb024caac567d8054e13c058a3a753e",
        "focus.js": "47454f62ab51cde497741504669903f235eee3e131380ea7692f0bcc78d25f0b",
    }
    link = '<a class="btn btn-out" data-testid="builder-system-control-entry" href="/devui/builder-system-control"><span class="k">system</span>Builder System Control</a>'
    for name, original_hash in originals.items():
        path = root / name
        if path.is_symlink():
            raise CandidateAssetError("managed navigation source is invalid")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest == ASSET_SHA256[name]:
            continue
        if digest != original_hash:
            raise CandidateAssetError("managed navigation source is outside the reviewed reuse envelope")
        text = content.decode()
        if name.endswith(".html"):
            text = text.replace('    </section>\n    <noscript>', f'      {link}\n    </section>\n    <noscript>', 1)
        else:
            text = text.replace('  subjectNode.dataset.subject = subject;', '''  const systemEntry = document.querySelector('[data-testid="builder-system-control-entry"]');
  systemEntry.href = `/devui/builder-system-control?return_subject=${encodeURIComponent(subject)}`;
  subjectNode.dataset.subject = subject;''')
        if hashlib.sha256(text.encode()).hexdigest() != ASSET_SHA256[name]:
            raise CandidateAssetError("managed navigation transformation is outside the reviewed reuse envelope")
        path.write_text(text)
    from pathlib import Path

    template = Path(__file__).with_name("devui_control.html").read_bytes()
    path = root / "control.html"
    if path.is_symlink() or hashlib.sha256(template).hexdigest() != ASSET_SHA256["control.html"]:
        raise CandidateAssetError("system lens template is outside the reviewed reuse envelope")
    path.write_bytes(template)


def render_system_control(payload: Mapping[str, Any], template: bytes) -> str:
    """Render escaped server declarations using the exact reviewed native grammar."""
    from html import escape
    from string import Template

    def scalar(value: Any) -> str:
        return escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True))

    def rows(values: Mapping[str, Any]) -> str:
        return '<div class="owner-summary">' + ''.join(
            f'<p class="owner-fact"><b>{scalar(key)}</b><span>{scalar(value)}</span></p>'
            for key, value in values.items()
        ) + '</div>'

    def button(label: str, href: str | None, *, testid: str = "", external: bool = True) -> str:
        if not href:
            return ''
        attributes = ' target="_blank" rel="noopener noreferrer"' if external else ''
        if testid:
            attributes += f' data-testid="{scalar(testid)}"'
        return f'<a class="btn btn-out"{attributes} href="{scalar(href)}"><span class="k">inspect</span>{scalar(label)}</a>'

    def entry(summary: Mapping[str, Any], details: Any, href: str | None = None) -> str:
        return '<div class="focus-entry">' + rows(summary) + (
            '<details class="technical-disclosure"><summary>Inspect source and technical details</summary>'
            '<ul class="rungs"><li><b>source details</b><code>' + scalar(details) + '</code></li></ul></details>'
        ) + button('Inspect source', href) + '</div>'

    control = payload['control']
    governance = ''.join(
        entry({
            'Source': document['role'], 'Availability': document['source_state']['availability'],
            'Freshness': document['source_state']['freshness'], 'Governance completeness': document['source_state']['coverage'],
            'Owner': payload['document_headers'][document['source_ref']['source_id']].get('Owner', 'not declared'),
        }, document, document['source_ref']['locator'])
        for document in control['governing_documents']
    )
    providers = payload['composition']['providers']
    assurance = ''.join(entry({
        'Source': provider['provider'], 'Read': provider['status'],
        'Authority': provider['authority'].get('status', 'Source declaration under Inspect') if isinstance(provider['authority'], Mapping) else provider['authority'],
        'Captured': provider.get('captured_at'),
    }, provider) for provider in providers.values())
    for provider in providers.values():
        snapshot = provider.get('snapshot')
        if isinstance(snapshot, Mapping):
            for source in snapshot.get('sources', []):
                assurance += entry({'Source': source['name'], 'Source state': source['state'],
                                    'Limitation': source['detail']}, source)
    inspect = ''.join(entry({
        'Destination': item['label'], 'Role': item['role'], 'Destination state': item['destination_state'],
        'Context': item['context'], 'Limitation': ' '.join(item['limitations']),
    }, item) + button('Inspect ' + item['label'], item['href']) for item in payload['inspect'])
    repository = control['scope']['repository_ref']
    sha = control['scope']['governance_baseline_ref']['version']
    source_base = f'https://github.com/{repository}/blob/{sha}/'
    return Template(template.decode()).substitute(
        composed_at=scalar(control['composed_at']), repository=scalar(repository),
        focus_return=button('Return to prior Focus', payload['navigation']['focus'], testid='focus-return', external=False),
        governance=governance,
        workflows=entry({'State': 'unread', 'Limitation': 'No adapter inventory is supplied. Existing versioned skills retain workflow authority.'},
                        control['workflow_adapters'], source_base + '.codex/skills/README.md'),
        capabilities=entry({'State': 'unread', 'Limitation': 'No tool inventory is supplied. Provider projections and APIs retain their existing contracts.'},
                           control['capability_bindings'], source_base + 'docs/development/BUILDER_SYSTEM_PROCESS_MAP.md'),
        assurance=assurance + entry({'State': 'unread', 'Limitation': 'No complete coverage or exception declaration is supplied.'}, control['coverage']),
        routes=entry({'State': 'unlinked', 'Limitation': 'No intended-to-observed route correlation is supplied. Existing delivery workflows retain authority.'},
                     control['deviations'], source_base + 'docs/development/DEV_WORKFLOW.md'),
        inspect=inspect,
        limitations=rows({'Scope': ' '.join(control['limitations']), 'Navigation': 'Prior Focus is return navigation only; it contributes no subject claims to Builder System Control.'}),
    )
