State: Development reference. Parent-issue closure guidance.
Doc role: Closure reference
Authority: Parent issues are validation hubs during delivery, not permanent containers or direct pickup issues.
Owner: Builder-agent governance
Temporal class: operational

# Parent Issue Closure

Parent issues exist to validate a capability while child slices are delivered.
Child slices should form an execution chain. Each delivered child posts a validation receipt to the parent issue so the parent reflects live evidence, not just backlog shape.
They are not meant to remain open forever.

## Close the Parent When

Close the parent issue when all of the following are true:

1. All child or slice issues are closed or terminal.
2. Repo-verifiable parent acceptance criteria are satisfied.
3. The closure receipt links the child issues, PRs, validation receipts, and the parent-closure handoff or explicit parent-closure issue.
4. Future adoption, retro notes, or observation work has moved to the right BuilderOps surface:
   `LearningSignal` for operational learning, `PromotionIntent` for boundary-crossing proposals,
   `BuilderOpsReceipt` for discard/supersession, or a follow-up GitHub Issue when it is executable work.

## Boundary Rules

- Parent issues are validation hubs during delivery.
- Parent issues are validation hubs during delivery, not direct pickup issues.
- Parent closure is not part of the default PR hot path unless this PR is the final child slice.
- Future adoption over N deliveries must not block closure of delivered, repo-verifiable scope.
- If the delivered scope is complete and the remaining work is only observation or follow-up learning, close the parent and move that remaining work out of the parent issue.
- The final child must include a parent-closure handoff or create/link an explicit parent-closure issue.

## Closure Receipt

The closure receipt should name:

- the parent issue
- the child issues that delivered it
- the PRs that closed those child issues
- the validation receipts posted by each delivered child
- the evidence proving repo-verifiable acceptance
- the parent-closure handoff or explicit parent-closure issue when the final child delivered the closure
- any follow-up issue or BuilderOps record that will hold future adoption or retro work

Minimal receipt shape:

```text
PARENT CLOSURE RECEIPT: parent #<n> closed after child issues #<a>, #<b>. Evidence: <links>. Validation receipts: <links>. Parent-closure handoff: <link to issue or receipt>. Follow-up: #<m>, BuilderOps LearningSignal/PromotionIntent, or discard receipt.
```
