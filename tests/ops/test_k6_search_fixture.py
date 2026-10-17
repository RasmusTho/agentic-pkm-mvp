"""Exercise the real nightly producer, HTTP probe, and k6 script boundary."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Thread
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/integration-nightly.yaml"
FIXTURE = {
    "query": "smoke",
    "expected_uuid": "11111111-1111-1111-1111-111111111111",
    "expected_title": "K6 synthetic smoke note",
    "vault_binding_id": "k6-search-synthetic",
}
EXPECTED = {"uuid": FIXTURE["expected_uuid"], "title": FIXTURE["expected_title"]}
RESPONSES = (
    (200, json.dumps({"results": [EXPECTED]}), True),
    (500, json.dumps({"results": [EXPECTED]}), False),
    (204, "", False),
    (200, json.dumps({"results": []}), False),
    (200, json.dumps({"results": [{**EXPECTED, "title": "wrong fixture"}]}), False),
    (200, json.dumps({"results": [{**EXPECTED, "uuid": str(uuid4())}]}), False),
    (200, "malformed JSON", False),
    (200, json.dumps({"results": {"uuid": FIXTURE["expected_uuid"]}}), False),
    (200, json.dumps({"results": [None]}), False),
    (200, json.dumps({"results": [EXPECTED, {"uuid": "bad", "title": "bad"}]}), False),
    (200, json.dumps({"results": [EXPECTED, EXPECTED]}), False),
)


def _run(arguments: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=ROOT, env=env, text=True, capture_output=True, timeout=90)


def _assert_success(result: subprocess.CompletedProcess[str], step: str) -> None:
    assert result.returncode == 0, f"{step} failed (exit {result.returncode}): {result.stderr[-4000:]}"


def test_k6_checks_reject_unsuccessful_or_missing_fixture_results(tmp_path: Path) -> None:
    """Execute the warm-up CLI and actual load script with the same bad responses."""
    manifest = tmp_path / "fixture.json"
    manifest.write_text(json.dumps(FIXTURE), encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        status = 200
        body = ""

        def do_GET(self) -> None:
            assert self.path == "/search?q=smoke"
            self.send_response(type(self).status)
            self.end_headers()
            self.wfile.write(type(self).body.encode())

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for status, body, valid in RESPONSES:
            Handler.status, Handler.body = status, body
            result = _run([
                sys.executable, "-m", "scripts.k6_search_fixture", "probe",
                "--base-url", f"http://127.0.0.1:{server.server_port}",
                "--manifest", str(manifest),
            ])
            assert (result.returncode == 0) is valid, (status, body, result.stderr)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    node = shutil.which("node")
    assert node, "Node is required to exercise the actual k6 JavaScript checks"
    runner = r"""
import fs from 'node:fs';
import vm from 'node:vm';
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
let current, checks, requestedUrl;
const context = vm.createContext({
  __ENV: { BASE_URL: process.argv[3], K6_FIXTURE_MANIFEST: process.argv[2] },
  open: (path) => fs.readFileSync(path, 'utf8')
});
const mod = new vm.SourceTextModule(fs.readFileSync(process.argv[1], 'utf8'), { context });
await mod.link((name) => {
  if (name === 'k6/http') return new vm.SyntheticModule(['default'], function () {
    this.setExport('default', { get: (url) => {
      requestedUrl = url;
      return { status: current[0], json: () => JSON.parse(current[1]) };
    }});
  }, { context });
  if (name === 'k6') return new vm.SyntheticModule(['check', 'sleep'], function () {
    this.setExport('check', (res, predicates) => {
      checks = Object.values(predicates).map((predicate) => predicate(res));
      return checks.every(Boolean);
    });
    this.setExport('sleep', () => {});
  }, { context });
  throw new Error(`Unexpected import ${name}`);
});
await mod.evaluate();
const results = cases.map((item) => {
  current = item;
  let warmup = true;
  try { mod.namespace.setup(); } catch (_) { warmup = false; }
  mod.namespace.default();
  return { warmup, load: checks.every(Boolean), url: requestedUrl };
});
process.stdout.write(JSON.stringify({ options: mod.namespace.options, results }));
"""
    command = [node, "--no-warnings", "--experimental-vm-modules", "--input-type=module", "-e", runner,
               str(ROOT / "scripts/k6_search.js"), str(manifest)]
    result = subprocess.run(
        [*command, "http://localhost:8000"],
        input=json.dumps(RESPONSES), text=True, capture_output=True, timeout=15,
    )
    _assert_success(result, "actual k6 script response checks")
    report = json.loads(result.stdout)
    assert report["options"] == {
        "vus": 5,
        "duration": "10s",
        "thresholds": {
            "http_req_duration": ["p(95)<250"],
            "http_req_failed": ["rate==0"],
            "checks": ["rate==1"],
        },
    }
    for actual, (_, _, valid) in zip(report["results"], RESPONSES, strict=True):
        assert actual == {"warmup": valid, "load": valid, "url": "http://localhost:8000/search?q=smoke"}
    missing_target = subprocess.run(
        [*command, ""], input=json.dumps(RESPONSES), text=True, capture_output=True, timeout=15,
    )
    assert missing_target.returncode != 0
    assert "BASE_URL is required" in missing_target.stderr


@contextmanager
def _fresh_database():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy.engine import URL

    from app.db.dsn import resolve_dsn

    admin = resolve_dsn()
    name = f"k6_search_{uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        fields = conninfo_to_dict(admin)
        fields.pop("dbname", None)
        url = URL.create(
            "postgresql+psycopg", username=fields.pop("user", None), password=fields.pop("password", None),
            host=fields.pop("host", None), port=int(fields.pop("port", "5432")), database=name,
            query=fields,
        )
        yield url.render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://", 1)
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.pg
def test_k6_fixture_produces_a_real_bound_search_result(tmp_path: Path) -> None:
    import psycopg

    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["k6-search"]
    steps = {step.get("name"): step for step in job["steps"] if "name" in step}
    with _fresh_database() as dsn:
        env = dict(os.environ)
        for key in ("DB_DSN", "STORE_SCHEMA_AUTOCREATE", "VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST",
                    "WATCHER_VAULT_PATH", "INSTANCE_VAULT_REGISTRY_PATH", "INSTANCE_OWNERSHIP_ROOT"):
            env.pop(key, None)
        env.update(DATABASE_URL=dsn, STORE_BACKEND="pg", EMBED_PROFILE="deterministic",
                   LLM_PROVIDER="mock", PYTHONPATH=str(ROOT),
                   K6_FIXTURE_MANIFEST=str(tmp_path / "fixture.json"))
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        # The old job's first runtime command really refuses a fresh database.
        old_bootstrap = _run([sys.executable, "-c", "from app.services.outbox import bootstrap; bootstrap()"], env=env)
        assert old_bootstrap.returncode != 0
        assert "OutboxSchemaMissingError" in old_bootstrap.stderr
        assert "Missing table outbox" in old_bootstrap.stderr.replace("'", "")
        for name in ("Prepare pgvector extension", "Apply migrations", "Bootstrap database", "Seed search fixture"):
            _assert_success(_run(["bash", "-e", "-c", steps[name]["run"]], env=env), name)
        manifest = json.loads(Path(env["K6_FIXTURE_MANIFEST"]).read_text(encoding="utf-8"))
        with psycopg.connect(dsn) as connection:
            rows = connection.execute(
                "SELECT o.vault_binding_id, o.object_id::text, v.model, v.provider "
                "FROM store_objects o JOIN store_vector_index v USING (vault_binding_id, object_id)"
            ).fetchall()
            assert rows == [(manifest["vault_binding_id"], manifest["expected_uuid"],
                             "deterministic-hash", "deterministic")]
            assert manifest["vault_binding_id"].startswith("k6-search-")
        with psycopg.connect(dsn) as connection, pytest.raises(psycopg.Error):
            connection.execute(
                "INSERT INTO objects(uuid,title,review_state,content,path) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (uuid) DO UPDATE SET title=excluded.title",
                (FIXTURE["expected_uuid"], "Smoke note", "inbox", "smoke", "Notes/smoke.md"),
            )

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env["BASE_URL"] = f"http://127.0.0.1:{port}"
        with (tmp_path / "api.log").open("w", encoding="utf-8") as log:
            api = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.api.app:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for name in ("Wait for API readiness", "Warm up search endpoint"):
                    _assert_success(_run(["bash", "-e", "-c", steps[name]["run"]], env=env), name)
            finally:
                api.terminate()
                api.wait(timeout=15)
        # An incomplete schema cannot seed or publish a successful manifest.
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("DROP TABLE store_vector_index")
        refused = _run(["bash", "-e", "-c", steps["Seed search fixture"]["run"]], env=env)
        assert refused.returncode != 0
        assert "StoreSchemaMissingError" in refused.stderr
        assert "store_vector_index" in refused.stderr


@pytest.mark.parametrize("dsn", [
    "postgresql://localhost/app", "postgresql://localhost/app_test",
    "postgresql://example.org/k6_search", "postgresql://localhost:15432/k6_search",
    "postgresql://localhost/k6_search?hostaddr=192.0.2.1",
])
def test_k6_producer_refuses_unadmitted_database(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.k6_search_fixture import _disposable_dsn

    monkeypatch.setenv("DATABASE_URL", dsn)
    with pytest.raises(RuntimeError, match="explicit localhost disposable"):
        _disposable_dsn()
