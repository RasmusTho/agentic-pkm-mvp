# Authority boundaries — Runtime Proof / Health Dashboard

## This design is

- **Visual guidance** for the surface(s) named in this package's README.
- **An interaction contract** limited to the fields, intents, and data attributes enumerated
  in `implementation-contracts.md` and in `prototype.html` §07.
- **A target-state proposal** until a normalized spec lands in owner-docs.

## This design is not

- **Architecture authority.** Authority lives in:
  - `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md (invariant)`
  - `runtime-proof receipt contract (when normalized)`
- **Runtime truth.** Runtime truth lives in shipped code, tests, status docs, and validation
  receipts.
- **A schema.** This contract references fields the runtime exposes; it does not declare them.
- **A claim about current runtime behavior** unless explicitly cited from owner-docs.

## Invariants this design honors

- **Gated execution.** No interaction surface in this design mutates durable state outside
  the existing governed path: policy, validation, event pipeline, deterministic writer.
- **Authority separation.** Chat is a canvas surface; Panel is the command surface;
  Automation is its own lane. This design does not collapse them.
- **Provenance visibility.** Where this design shows agent-contributed content, it shows
  source, trust state, and authority flags.
- **Bundle integrity.** Where this design shows context selection, it shows what was excluded
  when exclusion affects interpretation.
- **Memory candidacy.** Where this design touches agent memory, it never treats candidate
  memory as semantic authority.

## What this design may suggest to owner-docs

See `prototype.html` §10 ("Handoff notes for Claude Code / Codex") of this package for the
specific proposed normalized-spec path and follow-on issues. Owner-doc owners decide whether
to accept any of those suggestions.

## What this design must not suggest

- Any loosening of the gated-execution invariant.
- Any new authority surface that bypasses the existing pipeline.
- Any new write path that bypasses policy / validation.
- Any silent promotion of agent memory into semantic knowledge.
- Any redefinition of authority flag semantics.
