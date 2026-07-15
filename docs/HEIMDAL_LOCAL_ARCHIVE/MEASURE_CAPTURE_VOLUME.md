---
name: Measure Capture Volume
task_id: HAR-01
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Fixed constraints
parent_capability: Heimdal Local Archive
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Authored task specification (future-state; child issue not yet filed)

# Measure Capture Volume

## Purpose

Measure enough non-content data to size local hot/cold tiers from actual use before provisioning or
rotating external storage.

## What this task does

1. Add a rebuildable aggregate over raw-record metadata: count, encrypted-byte total, age buckets,
   archive-eligible bytes, and projection timestamp.
2. Emit a redacted capacity receipt/health surface with no audio name, transcript, raw path, content
   hash, or decrypted size-by-record.
3. Derive an operator-visible forecast using the current retention bound and seven-day hot threshold;
   report unknown/insufficient observation honestly rather than guessing capacity.

## Acceptance criteria

- [ ] The capacity report uses aggregate metadata only and omits raw paths, content, hashes, and
      individual recording sizes.
      Verify: `tests/heimdal/test_archive_capacity.py::test_capacity_receipt_contains_aggregates_only`
- [ ] The report separates hot-tier and archive-eligible totals using configured retention and the
      seven-day threshold.
      Verify: `tests/heimdal/test_archive_capacity.py::test_capacity_forecast_uses_hot_and_retention_windows`
- [ ] A missing retention setting fails loud rather than inventing a forecast.
      Verify: `tests/heimdal/test_archive_capacity.py::test_capacity_forecast_requires_retention_setting`

## Out of scope

Mounting storage, moving audio, changing retention, or collecting recording content.

## How to verify

`pytest -q tests/heimdal/test_archive_capacity.py`
