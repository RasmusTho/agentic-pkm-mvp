State: Legacy (archived).
## Summary
- 

## Acceptance Criteria
- [ ] Objective A (cross-encoder rerank provider)
- [ ] Objective B (RelationIndex gate + override audit)
- [ ] Objective C (diarization hook + chunk integration)
- [ ] Objective D (golden-set evaluation + CI summary)

## Flags Used
- `RERANK_ENABLE=`
- `RERANK_PROVIDER=`
- `DIARIZE_ENABLE=`
- Others:

## CI Metrics
- QAS-003 p95: 
- QAS-010 p95: 
- Golden P@10 / nDCG@10: 
- Relation coverage %:
- Diarization chunk p95 / speaker avg:

## CI Checklist
- [ ] Pasted the six CI summary lines plus the `CI SUMMARY GATES` line in this PR description.
- [ ] Confirmed no TODO/FIXME remain in any touched docs.
- [ ] Listed all flags used (if any) and documented whether positive/zero deltas are expected.

## Risks & Rollback
-

## Docs Updated
- [ ] docs/ARCHITECTURE.md
- [ ] docs/ROADMAP.md
- [ ] docs/STATUS.md
- [ ] CHANGELOG.md
