State: Shared skill contract. Canonical GitHub Project GraphQL operations.

# Project Status Operations

Single source for the GraphQL blocks that read and mutate Project state. Skills reference these
operations by name instead of carrying inline copies. Project: `Agent Delivery Control Plane`.
This is optional legacy projection repair: use it only when a governing workflow explicitly places
Project repair in scope, never as a readiness, pickup, review, merge, or closure gate.

Resolve stable identifiers once per run and reuse cached values instead of repeating lookups.
Batch field mutations into one bounded pass near workflow completion where possible.

## Resolve item, status field, and option IDs

For an Issue (swap `issue(number:N)` for `pullRequest(number:N)` for PR cards):

```bash
gh api graphql -f query='query {
  repository(owner:"OWNER", name:"REPO") {
    issue(number: N) {
      projectItems(first: 5) {
        nodes {
          id
          project {
            id
            title
            field(name: "Status") {
              ... on ProjectV2SingleSelectField { id options { id name } }
            }
          }
        }
      }
    }
  }
}'
```

An empty `projectItems` list means the item is not in the Project yet — add it first (below).

## Set Project Status

The single canonical mutation; pass the option ID for the target status (`Backlog`, `Ready`,
`In Progress`, `Review`, `Done` — see `LIFECYCLE_TRUTH_MATRIX.md`):

Before setting an Issue item to `Ready`, first run strict executable-contract validation on the
exact Issue body that will be paired with `agent:ready`:

```bash
python3 scripts/validate_issue_readiness.py --body-file <body-file> --label agent:ready
```

Do not use `--observe-only` for a `Ready` mutation. If the command does not exit 0, do not set
Project Status to `Ready`; keep or move the Issue to the appropriate non-executable state already
allowed by the lifecycle truth matrix. This strict readiness check does not replace existing Source
Anchors validation when that validation is part of the Issue path.

```bash
gh api graphql -f projectId="$PROJECT_ID" -f itemId="$ITEM_ID" \
  -f fieldId="$STATUS_FIELD_ID" -f optionId="$TARGET_OPTION_ID" \
  -f query='mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$optionId:String!) { updateProjectV2ItemFieldValue(input:{projectId:$projectId itemId:$itemId fieldId:$fieldId value:{singleSelectOptionId:$optionId}}) { projectV2Item { id } } }'
```

## Add an item to the Project

```bash
gh api graphql -f projectId="$PROJECT_ID" -f contentId="$ISSUE_OR_PR_NODE_ID" \
  -f query='mutation($projectId:ID!,$contentId:ID!) { addProjectV2ItemById(input:{projectId:$projectId contentId:$contentId}) { item { id } } }'
```

## Verify after mutation

```bash
gh issue view <N> --json labels,projectItems   # or: gh pr view <N> --json projectItems
```

Execute mutations explicitly and verify they succeeded — do not describe them as recommendations.
