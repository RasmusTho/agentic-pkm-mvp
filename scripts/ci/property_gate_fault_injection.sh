#!/usr/bin/env bash
# property_gate_fault_injection.sh — prove the P-2 mirror-census gate is NOT vacuous.
#
# #2909: the P-2 event-completeness property's static census gate
# (tests/properties/test_event_completeness.py::test_mirror_census_is_closed)
# is only meaningful if a NEW unregistered `emit_outbox=False` call site makes
# it fail. This script injects one such site into a throwaway, harness-only
# module under `app/`, proves the gate REJECTS it (fails red), then removes
# the injected file and proves the gate is green again -- the same
# fault-injection posture `scripts/ci/harness_gate_fault_injection.sh`
# established for the release-channel harness (issue #1997 F1).
#
# Exit 0 = baseline green, injected fault correctly rejected, cleanup restores
#          green. Exit 1 = the gate is vacuous (accepted the fault) or the
#          harness itself is broken.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python}"

FAULT_MODULE="app/_p2_fault_injection_scratch.py"
GATE_TEST="tests/properties/test_event_completeness.py::test_mirror_census_is_closed"

cleanup() {
  rm -f "$FAULT_MODULE"
}
trap cleanup EXIT

fail=0

echo "== baseline: census gate MUST be green on the unmodified tree =="
if ! "${PYTHON}" -m pytest -q -c /dev/null --import-mode=importlib "$GATE_TEST"; then
  echo "BASELINE FAILED: the census gate is red on an unmodified tree -- either" >&2
  echo "REGISTERED_MIRRORS has drifted from real app/ call sites, or the" >&2
  echo "harness itself is broken. Every 'rejection' below would be meaningless." >&2
  fail=1
fi
if [ "$fail" -eq 0 ]; then
  echo "ok: baseline census gate is green"
fi

echo ""
echo "== fault injection: an unregistered emit_outbox=False call site =="
cat > "$FAULT_MODULE" <<'PYEOF'
"""Throwaway module injected ONLY by scripts/ci/property_gate_fault_injection.sh
to prove the P-2 mirror-census gate (test_mirror_census_is_closed) is not
vacuous. Never imported by production code. Removed by the script's cleanup
trap; if you see this file committed, delete it -- it is not real production
code (#2909 harness-selfverify fixture).
"""

from app.objects import ObjectStore


def _unregistered_mirror_write(obj) -> None:
    store = ObjectStore()
    # Deliberately unregistered -- this is the injected violation.
    store.save_object(obj, emit_outbox=False)
PYEOF

set +e
"${PYTHON}" -m pytest -q -c /dev/null --import-mode=importlib "$GATE_TEST" >/tmp/p2_fault_injection_out.log 2>&1
rc=$?
set -e

if [ "$rc" -eq 0 ]; then
  echo "FAULT-INJECTION FAILED: the census gate ACCEPTED an unregistered" >&2
  echo "emit_outbox=False call site -- the gate is vacuous. Output:" >&2
  cat /tmp/p2_fault_injection_out.log >&2
  fail=1
elif ! grep -q "Unregistered emit_outbox=False call site" /tmp/p2_fault_injection_out.log; then
  echo "FAULT-INJECTION FAILED: the gate did not reject for the expected" >&2
  echo "reason (rc=${rc} but no 'Unregistered emit_outbox=False call site'" >&2
  echo "message) -- it may have crashed instead of rejecting. Output:" >&2
  cat /tmp/p2_fault_injection_out.log >&2
  fail=1
else
  echo "ok: gate rejected the injected unregistered mirror site (rc=${rc})"
fi
rm -f /tmp/p2_fault_injection_out.log

echo ""
echo "== cleanup verification: removing the fault restores green =="
rm -f "$FAULT_MODULE"
if ! "${PYTHON}" -m pytest -q -c /dev/null --import-mode=importlib "$GATE_TEST"; then
  echo "CLEANUP FAILED: the census gate is still red after removing the" >&2
  echo "injected fault -- the gate or the injection script itself is broken." >&2
  fail=1
else
  echo "ok: census gate is green again after cleanup"
fi

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "GATE IS VACUOUS OR BROKEN: the P-2 mirror-census gate did not behave" >&2
  echo "as a real gate under fault injection." >&2
  exit 1
fi

echo ""
echo "PASS: the P-2 mirror-census gate rejected the injected fault -- the gate is real."
