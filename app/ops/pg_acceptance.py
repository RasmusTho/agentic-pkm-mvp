"""The retained PG acceptance selection, shared by Actions and native verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID

PROFILE_VERSION = 'postmerge-pg.v1'
TEST_TIMEOUT = 120
POSTGRES_IMAGE = 'mirror.gcr.io/pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a'
IMAGE_REPOSITORY = 'ghcr.io/rasmustho/pkm-app'
SELECTORS = (
    'tests/index/test_provenance_stamp.py',
    'tests/index/test_identity_migration.py',
    'tests/indexer/test_outbox_roundtrip_pg.py',
    'tests/indexer/test_mixed_identity_detection.py',
    'tests/cli/test_index_doctor_mixed.py',
    'tests/cli/test_index_rebuild_cli.py',
    'tests/cli/test_index_reconcile.py',
    'tests/knowledge_acquisition/test_youtube_api_quota_pg.py',
    'tests/knowledge_acquisition/test_youtube_sync_state_pg.py',
    'tests/heimdal/test_entity_review_operation_journal.py',
    'tests/migrations/test_entity_review_operation_journal_schema_parity.py',
    'tests/migrations/test_file_state_adoption.py',
    'tests/migrations/test_objects_adoption.py',
    'tests/migrations/test_legacy_objects_fk_migration.py',
    'tests/migrations/test_store_schema_parity.py',
    'tests/migrations/test_multi_vault_ingest_projection_keys.py',
    'tests/store/test_membership_store.py',
    'tests/migrations/test_ingest_schema_parity.py',
    'tests/migrations/test_multi_vault_replay_projection_backfill.py',
    'tests/migrations/test_replay_schema_parity.py',
    'tests/migrations/test_mvr05a_residual_binding_keys.py',
    'tests/migrations/test_decisions_fk_set_null.py',
    'tests/integration/test_decisions_rebuild_from_log_only.py',
    'tests/integration/test_multi_vault_projection_isolation.py',
    'tests/episodes/test_episode_projection.py',
    'tests/integration/test_vault_sync_atomicity.py',
    'tests/ingest/test_vault_root_ingest_pg.py',
    'tests/invariants/test_retrieval_spine_invariants.py',
    'tests/jobs/test_decisions_export.py',
    'tests/jobs/test_decisions_projection_rebuild.py',
    'tests/jobs/test_multi_vault_decisions_rebuild_scope.py',
    'tests/jobs/test_calibration_projection_rebuild.py',
    'tests/integration/test_calibration_rebuild_from_log_only.py',
    'tests/stores/test_decisions_fk_semantics.py',
    'tests/stores/test_ensure_tables_assert_only.py',
    'tests/stores/test_multi_vault_store_reset_scope.py',
    'tests/stores/test_pg_truncate_reset.py',
    'tests/stores/test_pg_vector_index.py',
    'tests/stores/test_store_contract_pg.py',
    'tests/stores/test_vector_generation_identity.py',
    'tests/services/test_audit_writer.py',
    'tests/migrations/test_outbox_schema_parity.py',
    'tests/migrations/test_multi_vault_outbox_upgrade.py',
    'tests/services/test_multi_vault_outbox_dual_key_dedup.py',
    'tests/services/test_outbox_bootstrap_assert_only.py',
    'tests/instance/test_file_state_binding_key.py',
    'tests/services/test_vault_sync_binding_scope.py',
    'tests/integration/test_single_vault_compatibility.py',
    'tests/heimdal/test_trigger_ownership_pg.py',
    'tests/migrations/test_heimdal_raw_representation_migration.py',
    'tests/migrations/test_heimdal_raw_liveness_migration.py',
    'tests/builderops/test_owner_fact_producers.py',
    'tests/api/test_devui_owner_facts.py',
    'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_production_admission',
    'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_transaction_recovery',
    'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_concurrent_identical_start_replays_winner',
    'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_concurrent_competing_start_preserves_conflict',
    'tests/builderops/test_control_plane_issue_delivery.py::test_host_candidate_versions_preserve_v1_v2_history',
    'tests/builderops/test_control_plane_issue_delivery.py::test_v3_live_start_refuses_unqualified_continuation',
    'tests/builderops/test_devui_runtime.py::test_managed_source_preserves_v3_candidate_binding',
    'tests/builderops/control_plane/test_postgres_transaction_kernel.py::test_initial_issue_import_preserves_transaction_lease_and_outbox_boundaries',
    'tests/builderops/test_issue_delivery_effect_executor.py',
    'tests/builderops/test_issue_delivery_operation.py',
    'tests/builderops/test_issue_delivery_readback.py',
    'tests/builderops/test_standalone_consumer_conformance.py',
)
MINIMUM_SELECTED = len(SELECTORS)
SELECTION_HASH = hashlib.sha256(json.dumps(
    [PROFILE_VERSION, SELECTORS, 'pg', TEST_TIMEOUT, 'thread', MINIMUM_SELECTED, POSTGRES_IMAGE],
    separators=(',', ':'),
).encode()).hexdigest()


class PgAcceptanceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__('isolated PG acceptance refused')


def identity(sha: str, digest: str, channel: str, operation_id: str) -> dict[str, str]:
    if (re.fullmatch(r'[0-9a-f]{40}', sha) is None
        or re.fullmatch(r'sha256:[0-9a-f]{64}', digest) is None
        or channel not in {'dev', 'test'} or str(UUID(operation_id)) != operation_id):
        raise PgAcceptanceError()
    return {'profile_version': PROFILE_VERSION, 'selection_hash': SELECTION_HASH,
            'source_sha': sha, 'image_digest': digest, 'channel': channel, 'operation_id': operation_id}


def require_pass(result: Any, sha: str, digest: str, channel: str, operation_id: str) -> None:
    expected = identity(sha, digest, channel, operation_id)
    if (not isinstance(result, dict) or set(result) != set(expected) | {
        'result', 'selected', 'passed', 'resource_tree', 'app_image_id', 'report_hash'
    } or any(result.get(key) != value for key, value in expected.items())
        or result['result'] != 'passed' or type(result['selected']) is not int
        or result['selected'] < MINIMUM_SELECTED or result['passed'] != result['selected']
        or type(result['passed']) is not int
        or re.fullmatch(r'[0-9a-f]{40}', str(result['resource_tree'])) is None
        or re.fullmatch(r'sha256:[0-9a-f]{64}', str(result['app_image_id'])) is None
        or re.fullmatch(r'[0-9a-f]{64}', str(result['report_hash'])) is None):
        raise PgAcceptanceError()


def pytest_arguments() -> list[str]:
    return ['-vv', '--durations=20', '-m', 'pg', *SELECTORS, '--tb=short',
            '-p', 'timeout', '--timeout=' + str(TEST_TIMEOUT), '--timeout-method=thread',
            '-o', 'cache_dir=/tmp/pg-acceptance-cache']


class RequiredResults:
    """No empty/missing selector, skip, xfail, collection error or timeout is a pass."""
    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.passed: set[str] = set()
        self.bad = False

    def pytest_collection_finish(self, session: Any) -> None:
        import pytest
        self.nodes = {item.nodeid for item in session.items}
        if (len(self.nodes) < MINIMUM_SELECTED or len(self.nodes) != len(session.items)
            or any(not any(node == selector or node.startswith(selector + '::')
                           or node.startswith(selector + '[') for node in self.nodes)
                   for selector in SELECTORS)
            or session.config.getoption('timeout') != TEST_TIMEOUT
            or session.config.getoption('timeout_method') != 'thread'):
            raise pytest.UsageError('required PG selection or watchdog is missing')

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.skipped or report.failed or hasattr(report, 'wasxfail'):
            self.bad = True
        if report.when == 'call' and report.passed:
            if report.nodeid in self.passed:
                self.bad = True
            self.passed.add(report.nodeid)

    def summary(self, exit_status: int) -> dict[str, Any]:
        if exit_status != 0 or self.bad or not self.nodes or self.nodes != self.passed:
            raise PgAcceptanceError()
        report_hash = hashlib.sha256(json.dumps(sorted(self.passed), separators=(',', ':')).encode()).hexdigest()
        return {'selected': len(self.nodes), 'passed': len(self.passed), 'report_hash': report_hash}


def verify_resources(manifest: dict[str, Any], *, root: Path = Path('/app')) -> None:
    """Check resources and baked Python modules without importing tooling code."""
    if (manifest.get('profile_version') != PROFILE_VERSION
        or manifest.get('selection_hash') != SELECTION_HASH
        or not isinstance(manifest.get('files'), dict) or not manifest['files']):
        raise PgAcceptanceError()
    for name, expected in manifest['files'].items():
        path = root / name
        if (Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink()
            or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise PgAcceptanceError()
    import app
    if Path(app.__file__).resolve() != root / 'app/__init__.py':
        raise PgAcceptanceError()


def run_pytest() -> dict[str, Any]:
    import pytest
    plugin = RequiredResults()
    return plugin.summary(int(pytest.main(pytest_arguments(), plugins=[plugin])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ci', action='store_true')
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.ci:
            if args.manifest is not None:
                raise PgAcceptanceError()
            summary = run_pytest()
        else:
            if args.manifest is None:
                raise PgAcceptanceError()
            manifest = json.loads(args.manifest.read_text())
            expected = identity(manifest['source_sha'], manifest['image_digest'],
                                manifest['channel'], manifest['operation_id'])
            verify_resources(manifest)
            Path('/scratch/vault').mkdir(parents=True, exist_ok=True)
            # Candidate execution has no host network: only its disposable PG
            # server is reachable in the shared network-none namespace.
            import psycopg
            with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as connection:
                connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
            summary = {**expected, **run_pytest(), 'result': 'passed',
                       'resource_tree': manifest['resource_tree'], 'app_image_id': manifest['app_image_id']}
            verify_resources(manifest)
            require_pass(summary, manifest['source_sha'], manifest['image_digest'],
                         manifest['channel'], manifest['operation_id'])
        print('YGGDRASIL_PG_ACCEPTANCE=' + json.dumps(summary, sort_keys=True))
        return 0
    except Exception:
        print('YGGDRASIL_PG_ACCEPTANCE=refused')
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
