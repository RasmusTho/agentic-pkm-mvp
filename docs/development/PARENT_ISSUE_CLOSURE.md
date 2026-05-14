State: Development reference. Parent-issue closure guidance.
Doc role: Closure reference
Authority: Parent issues are validation hubs during delivery, not permanent containers.
Owner: Builder-agent governance
Temporal class: operational

# Parent Issue Closure

Parent issues exist to validate a capability while child slices are delivered.
They are not meant to remain open forever.

## Close the Parent When

Close the parent issue when all of the following are true:

1. All child or slice issues are closed or terminal.
2. Repo-verifiable parent acceptance criteria are satisfied.
3. The closure receipt links the child issues, PRs, and evidence.
4. Future adoption, retro notes, or observation work has moved to a follow-up issue or learning-log item.

## Boundary Rules

- Parent issues are validation hubs during delivery.
- Parent closure is not part of the default PR hot path unless this PR is the final child slice.
- Future adoption over N deliveries must not block closure of delivered, repo-verifiable scope.
- If the delivered scope is complete and the remaining work is only observation or follow-up learning, close the parent and move that remaining work out of the parent issue.

## Closure Receipt

The closure receipt should name:

- the parent issue
- the child issues that delivered it
- the PRs that closed those child issues
- the evidence proving repo-verifiable acceptance
- any follow-up issue that will hold future adoption or retro work

Minimal receipt shape:

```text
PARENT CLOSURE RECEIPT: parent #<n> closed after child issues #<a>, #<b>. Evidence: <links>. Follow-up: #<m> or learning-log item.
```
