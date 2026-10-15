"""Production managed BSC journey, authority, source-state and provenance proofs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.builderops.devui_control import GOVERNING_PATHS, bind_managed_control_assets
from app.builderops.devui_runtime import RuntimeConfigurationError, create_app, load_configuration
from app.builderops.devui_sources import package_candidate
from tests.builderops.test_devui_runtime import (
    MANAGED_SUBJECT, _package_managed_shell, managed_sources,  # noqa: F401
)

ROOT = Path(__file__).resolve().parents[2]
CONTROL = "/devui/builder-system-control"
API = "/api/devui/builder-system-control"


def prepare_control_sources(source) -> None:
    _package_managed_shell(source.root)
    for path in GOVERNING_PATHS:
        file = source.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes((ROOT / path).read_bytes())
    identity = json.loads((source.root / "manifest.json").read_text())
    package_candidate(source.root, repository=identity["repository"], source_sha=identity["source_sha"],
                      capabilities=identity["capabilities"], matrix=identity["matrix"])


def test_managed_system_lens_navigation_and_context(managed_sources) -> None:  # noqa: F811
    source = managed_sources
    prepare_control_sources(source)
    with source.client() as client:
        overview = client.get("/devui/overview")
        focus = client.get("/devui/focus", params={"subject": MANAGED_SUBJECT})
        assert CONTROL in overview.text and CONTROL in focus.text
        assert "return_subject=${encodeURIComponent(subject)}" in client.get("/devui/assets/focus.js").text
        response = client.get(API, params={"return_subject": MANAGED_SUBJECT})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["control"]["primary_identity"] == "builder_system"
        assert payload["control"]["scope"]["repository_ref"] == "example/fixture"
        assert "subject" not in payload["control"]
        assert parse_qs(urlsplit(payload["navigation"]["focus"]).query) == {"subject": [MANAGED_SUBJECT]}
        assert client.get(payload["navigation"]["focus"]).status_code == 200
        page = client.get(CONTROL, params={"return_subject": MANAGED_SUBJECT})
        assert 'data-primary-identity="builder_system"' in page.text
        assert 'data-testid="focus-return"' in page.text
        assert client.get(API).json()["navigation"]["focus"] is None
        assert 'data-testid="focus-return"' not in client.get(CONTROL).text
        assert client.get("/healthz").json()["complete_dev_system_health"] is False
        assert all(method == "GET" for method, _ in source.http_calls)


def test_source_states_and_inspect_links(managed_sources, monkeypatch) -> None:  # noqa: F811
    source = managed_sources
    prepare_control_sources(source)
    source.environment.update(DEVUI_DIAGNOSTIC_ORIGIN="https://diagnostics.example.test",
                              DEVUI_CKM_OVERVIEW_URL="https://ckm.example.test/overview.html")
    with source.client() as client:
        first = client.get(API).json()
        refs = first["control"]["governing_documents"]
        assert len(refs) == len(GOVERNING_PATHS)
        assert all(d["source_state"]["freshness"] == "fresh" for d in refs)
        assert all(d["source_state"]["coverage"] == "missing" for d in refs)
        assert all(d["lifecycle"]["phase"] == "unknown" for d in refs)
        assert all(d["source_ref"]["version"] == "a" * 40 for d in refs)
        assert first["composition"]["providers"]["capabilities"]["status"] == "refused"
        assert first["control"]["workflow_adapters"] == first["control"]["coverage"] == []
        assert all("payload" not in provider for provider in first["composition"]["providers"].values())
        destinations = {item["label"]: item for item in first["inspect"]}
        assert parse_qs(urlsplit(destinations["BuilderOps control plane"]["href"]).query) == {"repository": ["example/fixture"]}
        assert destinations["Cockpit"]["href"] == "https://diagnostics.example.test/cockpit"
        assert destinations["Cockpit"]["context"] == "unsupported"
        assert destinations["CKM Development Overview"]["destination_state"] == "unread"
        assert destinations["Signboard board"]["href"].endswith("/api/signboard/board")
        assert destinations["Signboard recovery"]["role"] == "operational recovery"
        assert "POST" in " ".join(destinations["Signboard recovery"]["limitations"])
        assert "fixture-secret-never-export" not in json.dumps(first)
        assert "source credential" in " ".join(destinations["BuilderOps control plane"]["limitations"])
        # A changed candidate document withdraws only that document, never the source providers.
        (source.root / GOVERNING_PATHS[0]).write_text("tampered bytes")
        refused = client.get(API).json()
        assert refused["control"]["governing_documents"][0]["source_state"]["availability"] == "refused"
        assert refused["control"]["governing_documents"][1]["source_state"]["freshness"] == "fresh"
        (source.root / GOVERNING_PATHS[1]).unlink()
        missing = client.get(API).json()
        assert missing["control"]["governing_documents"][1]["source_state"]["availability"] == "unavailable"
        assert missing["control"]["governing_documents"][1]["source_state"]["cardinality"] == "not_measured"
    source.environment.pop("DEVUI_DIAGNOSTIC_ORIGIN")
    source.environment.pop("DEVUI_CKM_OVERVIEW_URL")
    with source.client() as client:
        withdrawn = {d["label"]: d for d in client.get(API).json()["inspect"]}
        assert withdrawn["Cockpit"]["href"] is None
        assert withdrawn["CKM Development Overview"]["destination_state"] == "unavailable"
    # The route preserves the composition reader's independently declared stale plane.
    prepare_control_sources(source)
    from app.builderops import devui_runtime
    original = devui_runtime.read_managed_cockpit

    def stale_reader(config):
        result = copy.deepcopy(original(config))
        for plane in result["sources"]:
            if plane["name"] == "docs-frontmatter":
                plane["state"] = "stale"
                plane["detail"] = "Fixture source declares a stale read"
                result["withdrawn_counts"] = [{"source": "docs-frontmatter", "counts": ["capability_lanes.lanes"]}]
                break
        return result

    monkeypatch.setattr(devui_runtime, "read_managed_cockpit", stale_reader)
    with source.client() as client:
        payload = client.get(API).json()
        planes = payload["composition"]["providers"]["work"]["snapshot"]["sources"]
        assert any(p["state"] == "stale" for p in planes)
        assert "stale" in client.get(CONTROL).text


def test_system_lens_admission_and_no_effects(managed_sources) -> None:  # noqa: F811
    source = managed_sources
    prepare_control_sources(source)
    with source.client() as client:
        for path in (CONTROL, API):
            for headers in ({"X-Forwarded-For": "127.0.0.1"}, {"Via": "proxy"}, {"Host": "evil.example"}):
                assert client.get(path, headers=headers).status_code == 403
            for query in ("subject=" + MANAGED_SUBJECT, "return_subject=", "return_subject=github:foreign/repo%23501",
                          "return_subject=github:example/fixture%23501&return_subject=github:example/fixture%23502",
                          "return_subject=%ZZ", "return_subject=capability:fixture", "url=https://evil.example"):
                assert client.get(path + "?" + query).status_code == 400
            assert client.post(path).status_code == 405
            assert client.delete(path).status_code == 405
        assert source.http_calls == [] and not source.gh_calls.exists()
        assert client.get("/cockpit").status_code == 404
        assert client.get("/signboard").status_code == 404
    app = create_app(load_configuration(source.environment))
    with TestClient(app, client=("192.0.2.1", 1), base_url="http://127.0.0.1:8113") as remote:
        assert remote.get(CONTROL).status_code == 403
    for key in ("DEVUI_DIAGNOSTIC_ORIGIN", "DEVUI_CKM_OVERVIEW_URL"):
        for value in ("javascript:alert(1)", "http://198.51.100.1", "https://user:secret@example.test", "https://example.test?token=secret",
                      "https://example.test/#token", "https://example.test/../secret", "https://example.test/%2fsecret"):
            with pytest.raises(RuntimeConfigurationError, match="diagnostic navigation"):
                load_configuration({**source.environment, key: value})
    # Unsafe or changed bytes cannot be laundered by the packaging transformation.
    (source.root / "assets/focus.js").write_text("unreviewed")
    with pytest.raises(ValueError, match="reuse envelope"):
        bind_managed_control_assets(source.root / "assets")


def test_system_lens_reuse_receipt(managed_sources) -> None:  # noqa: F811
    prepare_control_sources(managed_sources)
    receipt = json.loads((ROOT / "docs/DEVUI_BUILDER_SYSTEM_CONTROL/constrained-reuse.json").read_text())
    payload = receipt["provenance_payload"]
    canonical = lambda obj: json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    digest = lambda data: "sha256:" + hashlib.sha256(data).hexdigest()
    assert receipt["payload_sha256"] == digest(canonical(payload))
    review = receipt["independent_review"]
    assert review["verdict"] == "pass" and review["independent_from_author"] is True
    assert review["reviewer_identity"] != payload["authorship"]["author_identity"]
    assert review["reviewed_payload_sha256"] == receipt["payload_sha256"]
    assert receipt["receipt_sha256"] == digest(canonical({k: receipt[k] for k in ("payload_sha256", "independent_review")}))
    assert set(payload["authority_claims"].values()) == {"not_claimed"}
    assert payload["zero_novel_visual_language"]["asserted"] is True
    assert payload["no_egress"]["cross_origin_request_count"] == 0
    for target in payload["target_artifacts"]:
        path = target["target_path"]
        file = managed_sources.root / path.removeprefix("devui-candidate/") if path.startswith("devui-candidate/") else ROOT / path
        assert target["content_sha256"] == digest(file.read_bytes())
    for matrix in (payload["state_matrix"], payload["accessibility_matrix"]):
        assert matrix
        for row in matrix:
            assert row["evidence_sha256"] == digest((ROOT / row["evidence_ref"]).read_bytes())
