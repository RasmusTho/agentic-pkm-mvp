Governing-Issue: #5155
Fixes #5155

Final-Review-Rounds: 0

## Summary

Preserve the documented MVR-01B legacy compatibility posture while the instance registry authority is dormant. Active registry resolution remains governed and fail-closed. Also tolerate an unadopted, mount-blind owner candidate during fresh staged-backup verification without weakening adopted binding checks.

## Verify

- `pytest -q tests/instance/test_scalar_binding_runtime.py tests/workers/test_outbox_worker_no_vault_idle.py tests/workers/test_multi_vault_partial_delivery_gate.py`
- `pytest -q tests/ops/test_instance_state_volume_contract.py::test_staged_backup_verification_succeeds_on_fresh_deployment`
- `ruff check app/instance/scalar_binding_runtime.py tests/instance/test_scalar_binding_runtime.py`

## BuilderOps Routing

- Records/projections/receipts: none
- Reason: bounded repository bug repair; no BuilderOps record is required
