# Builder Thread Privacy Boundary Redesign

State: Historical advisory architecture/process audit snapshot (2026-08-28). Its retirement
recommendation was promoted to #5128; current truth lives in `docs/DOCS_INDEX.md` and the BuilderOps
Vault and Operations owner sections, not in this audit. It authorizes no reactivation, replacement,
artifact inspection, migration, or implementation.

Doc role: Reference (audit snapshot)

Authority: Evidence-based review of the Builder Thread producers, transport, serializer, recovery,
tests, and owner contracts at the pinned `main` snapshot below. An owner document wins on any
disagreement until a separately governed promotion changes it.

Owner: Architecture research / Builder System process stewardship

Temporal class: snapshot

Source-of-truth boundary: `origin/main` at
`0ccdb8613766a46fb3830227b2a1b3e45979e2d7`, first resolved at
`2026-08-27T22:09:39Z` and rechecked with `git ls-remote origin refs/heads/main` at
`2026-08-27T22:19:30Z`. Local date was Europe/Stockholm.

## tcd_plan

```yaml
tcd_plan:
  task_summary: "Find the smallest robust replacement for the Builder Thread privacy boundary"
  assumptions:
    - "Builder Thread remains a non-authoritative Builder System exchange"
    - "The production writer remains contained while the contract and mechanism are reassessed"
    - "A free-text or separate notification use case is not assumed without a production producer or live acceptance receipt"
  complexity: high
  risk: high
  verification_difficulty: hard
  human_review_burden: low
  defect_blast_radius: high
  budget_pressure: low
  execution_context: coordinator_only
  issue_local_helper_budget: 0
  context_cost:
    measurement: estimated
    input_tokens: "unknown(no runtime telemetry)"
    agent_starts: 3
    context_pack_bytes: "unknown"
    compactions: 1
  recommended_capability:
    workflow_or_skill: "architecture-research -> docs-authoring"
    model_family: "architecture-grade"
    reasoning_effort: high
    tools: "git, GitHub REST, exact-SHA source reads, bounded pure probes"
    github_context_required: true
  cheapest_acceptable_path: "one coordinator, three evidence-only subsystem censuses, one advisory audit"
  escalation_triggers: "a requirement to persist free prose, private paths, code, patches, or arbitrary external URLs"
  deescalation_triggers: "retirement with no replacement, or a separately governed reference signal with no caller prose"
  review_gate: "fresh exact-main recheck plus independent anchored review of the audit diff"
```

## Research charter

### Product and scale profile

- **Profile:** P1 single operator on trusted personal infrastructure.
- **Users:** one owner; Codex and Claude are authenticated Builder clients, not independent human
  tenants.
- **Independent writers:** one designated host-local serialized writer.
- **Failure cost:** an unsafe immutable artifact may copy private builder material across clients,
  hosts, providers, backups, or projections; a false refusal delays a non-authoritative question.
- **Recovery objective:** fail closed without reconstructing unsafe or unknown records; retained v1
  artifacts remain inert until a separately accepted disposition exists.
- **Threat model:** accidental propagation by authorized clients and malformed/tampered stored data.
  Malicious authorized clients, covert channels, regulated retention, public artifact publication,
  multi-tenancy, and distributed authority are not established requirements.
- **Complexity budget:** retirement adds no writer, parser, or store. If an owning-surface gap later
  justifies a separate signal, its maximum is one writer, one versioned codec, one closed reference
  model, one admission/recovery validator, and row-explicit tests. A general DLP engine, free-text URI
  grammar, filesystem grammar, nested decoder, content quarantine service, or second authority store
  is over budget without new evidence.

`docs/DESIGN_PRINCIPLES.md:124-137` establishes the single-operator default and requires the
simplest mechanism that satisfies current integrity contracts. The one-writer and non-distributed
posture is already explicit in `.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:7-31`.

### Questions

1. Is the strict `shared_non_sensitive` contract reasonable for the actual Builder Thread need?
2. Can the repository retire Builder Thread and use existing owning surfaces; if not, what is the
   minimum separate signal model that can make the strict claim truthful without a bespoke parser?
3. Where must validation live so HTTP admission and restart recovery cannot drift?
4. What proof prevents another aggregate-test false green?
5. Does current evidence justify re-enabling or implementing a replacement now?

### Scope

In scope: current command producers, HTTP transport, immutable command records, recovery, privacy
classification, tests, Builder Thread skills, and the BuilderOps/operations owner sections.

Out of scope: Product/Runtime behavior, Mimer vault semantics, multi-writer filesystems, live-vault
mutation, retained-artifact migration, provider security claims, and the superseded predecessor
repair lines excluded by the review brief.

## Executive conclusion

The strict contract is **reasonable only after narrowing what the artifact is**. It is not a
credible guarantee over arbitrary prose.

The current contract combines four different concerns under one `shared_non_sensitive` classifier:

1. secret and private-host-data prevention;
2. routing code and patches to Git/GitHub rather than duplicating them in a thread;
3. typed provenance and closed schema;
4. bounded resource use and content-free failure.

The last three can be enforced exactly. Secret-free arbitrary prose cannot: a lexical scanner can
only recognize known shapes, so it inevitably admits unknown secrets and rejects harmless builder
language. The current mechanism demonstrates both directions while still leaving production with no
usable writer.

The proportionate default is **retirement without replacement**: keep production disabled and place
the question, answer, review request, or handoff directly on its existing owning GitHub, repository,
or BuilderOps surface. Current evidence shows no executable producer that needs an additional
durable exchange.

If a later producer demonstrates that those surfaces cannot provide bounded recipient notification,
the smallest candidate is a separately named **Builder Reference Signal**, not Builder Thread v2. It
would carry typed intent, endpoint-derived identity, writer-generated identity, closed typed
references, and enumerated dispositions, but no subject, message, reason, arbitrary URL, private host
path, code, or patch prose. This is an index/notification capability: it cannot satisfy the current
Builder Thread contract's question-and-answer semantics without an explicit owner-contract amendment.
Calling it merely a narrower encoding would hide that semantic change.

If free-form discussion is later shown to be essential, it should be a separately named data class
with an honest best-effort DLP and retention contract. It must not reuse an absolute
`shared_non_sensitive` guarantee.

Production should remain fail-closed. The bounded evidence does not justify a replacement
implementation or backlog. A separate reference-signal capability is justified only if an executable
producer, one unmet end-to-end notification use case, and the owning-surface insufficiency are named
through the normal promotion path.

## Evidence boundary

| Evidence | Exact snapshot fact |
| --- | --- |
| Production state | `BuilderThreadWriterHost.from_environment()` raises unconditionally before root initialization or recovery (`app/builderops/builder_threads_serialized.py:453-463`); the HTTP factory and module entrypoint depend on it (`app/builderops/builder_thread_endpoint.py:120-132,229-231`). |
| Producer census | Exact-token searches found no non-test application or script caller of `BuilderThreadClient`, `configured_builder_thread_client`, or `ThreadMutation`; executable uses are confined to the implementation and three Builder Thread test modules. The two skills describe operations but contain no producer (`.codex/skills/builder-thread/SKILL.md:20-31`, `.codex/skills/builder-inbox/SKILL.md:12-24`). |
| Original need | Issue [#4708](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4708) selected one serialized writer for attributed questions and explicitly retained the `shared_non_sensitive` contract after the larger predecessor was rejected. It supplies intent, not present production-use evidence. |
| Current command model | One optional-field `ThreadMutation` represents all four commands (`app/builderops/builder_threads_serialized.py:132-141`); client helpers emit distinct field sets (`:489-560`), but persistence writes all eight fields for every kind (`:885-895`). |
| HTTP shape | `_mutation_from_payload` accepts any object, ignores unknown keys, and uses `.get()` for every known field (`app/builderops/builder_thread_endpoint.py:188-204`). |
| Recovery shape | Root, envelope, and generic command key sets are closed and duplicate stored JSON keys are rejected (`app/builderops/builder_threads_serialized.py:344-366,848-857,898-934`). |
| Privacy mechanism | Free text is scanned with handwritten regex, lexical URI discovery, bounded percent-decoding, `urlsplit`, IP parsing, IDNA conversion, and recursive component classification (`app/builderops/builder_threads_serialized.py:31-59,641-845`). |
| Demonstrated misses | Pure probes on the byte-identical pinned source classified a prefixed `github_pat_...` token and `https://example.test/a\|/tmp/host-only` as `valid`, accepted more than 64 components across generated forms, and classified a valid encoded IPv6 ZoneID as `indeterminate`. |
| Unclassified persisted field | Validation does not reject or classify `subject` on reply, close, or archive (`app/builderops/builder_threads_serialized.py:594-605`), while the common record always persists it (`:885-895`). A direct pinned-source probe persisted `/tmp/private` as the subject of a close command. |
| False-green proof | `test_http_and_recovery_reject_all_persisted_untrusted_fields` covers create fields but only tampered create content during recovery (`tests/builderops/test_builder_thread_privacy_classifier.py:82-120`). `test_structural_privacy_adversarial_matrix` is one create-content loop without recovery rows (`:218-258`). |
| Contract truth | Owner docs correctly retain the strict outcome while rejecting the parser shape and containing production (`docs/builderops/BUILDEROPS_VAULT_STORE.md:262-295`; `docs/OPERATIONS.md:421-448`). |

## Ranked weakness analysis

Rank is based on blast radius multiplied by silence of failure, not estimated likelihood.

| Rank | Finding | Anchored evidence | Disposition |
| --- | --- | --- | --- |
| 1 | The absolute privacy claim is not mechanically satisfiable over arbitrary prose. Known-pattern recognition cannot establish that unknown text is non-secret; the current scanner has both unsafe accepts and safe refusals. | Free text enters through `subject`/`content` (`app/builderops/builder_threads_serialized.py:489-547,620-638`); recognizers are finite regex families (`:31-57`); the pinned probes above exercise misses and false refusal. | **Accepted.** Reject the free-text guarantee/mechanism pairing. |
| 2 | There is no current production producer whose needs justify restoring the mixed-text parser. | Production factory is contained (`app/builderops/builder_threads_serialized.py:453-463`); repo census finds only tests and descriptive skills. | **Accepted.** Keep containment; require one named producer/use case before implementation. |
| 3 | Privacy, artifact-routing, schema, and resource-bounds rules are conflated. | The shared contract lists credentials, private paths, product code, patches, binaries, and untyped provenance in one privacy paragraph (`.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:33-48`). | **Accepted.** Separate invariant ownership in any promoted contract. |
| 4 | The transport/domain schema is broader than the four public commands and silently strips HTTP extras before writing a generic null-filled record. | Command helpers are kind-specific (`app/builderops/builder_threads_serialized.py:489-560`); `ThreadMutation` and HTTP parsing are not (`:132-141`; `app/builderops/builder_thread_endpoint.py:188-204`). | **Accepted.** A replacement needs closed command-specific schemas at the first byte boundary. |
| 5 | Admission/recovery test names overstate their field and matrix coverage. | `tests/builderops/test_builder_thread_privacy_classifier.py:82-120,218-258`; the rejected design's named row tests remain future design (`docs/builderops/BUILDER_THREAD_PRIVACY_CLASSIFIER_RECOVERY.md:328-359`). | **Accepted.** Proof must enumerate every admitted field and every ingress. |
| 6 | Current docs contain two temporal tensions that increase future routing risk. | The shared skill contract describes an operated endpoint in present tense (`.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:7-31`) while owner docs say not to start it (`docs/OPERATIONS.md:421-444`). The rejected recovery doc's header disclaims authority (`docs/builderops/BUILDER_THREAD_PRIVACY_CLASSIFIER_RECOVERY.md:1-5`) while its historical verdict says implementation was permitted (`:361-384`). | **Accepted as docs drift.** Repair only together with an accepted replacement or explicit retirement; do not rewrite owner truth from this audit. |
| 7 | A reference-only signal is not a drop-in Builder Thread encoding. | The current contract creates a thread when no durable representation exists and carries the attributed question and reply itself (`.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:9-20,33-40`). Requiring an existing owning-surface reference changes the capability into notification/indexing. | **Accepted.** Prefer retirement and existing surfaces. Treat any future reference signal as a separate capability requiring an explicit owner-contract amendment. |

## Is the strict repository contract reasonable?

| Current rule | Verdict | Reasonable ownership |
| --- | --- | --- |
| No credentials, bearer material, or private keys in the shared artifact | **Keep strict.** | Privacy/egress invariant. Enforce primarily by admitting no free-text field, not by claiming universal secret recognition. |
| No private host paths | **Keep strict for the artifact.** | Privacy/topology invariant. A conditional signal may admit a typed repository-relative document locator or opaque registered artifact ID; it never admits an absolute/private host path or parses path-looking prose. |
| No product code or patches | **Keep as routing, not privacy.** | Git/GitHub remains the code and patch owner. A public code fragment is not inherently private, but duplicating it into an immutable discussion artifact is still the wrong transport. |
| No untyped provenance or unclassified persisted fields | **Keep strict.** | Closed-schema/authority invariant. Every field has one declared semantic type and producer. |
| Same validation for admission and recovery | **Keep strict.** | Integrity invariant. One versioned codec must be called at both seams. |
| Content-free refusal | **Keep strict.** | Privacy/observability invariant. Return an error code and field class, never offending bytes. |
| Bounded text parser, decoding depth, URI and filesystem grammar | **Remove.** | Mechanism, not outcome. It exists only because arbitrary mixed prose was admitted. |
| Arbitrary free prose labelled provably `shared_non_sensitive` | **Reject.** | The guarantee is stronger than lexical evidence can establish. Use a separate best-effort class if the need is later proven. |

The contract is therefore not “too strict” in its core boundary. It is too broad in what it asks one
privacy classifier to prove. Strictness becomes proportionate either by retiring the extra artifact
or, only after demonstrated need, making a separate signal's accepted data language small enough to
validate exactly.

## Proportionate architecture decision

### Default: retire and use the owning surface

Do not reconstruct question-and-answer semantics in another persistence layer. GitHub Issues and PR
comments already own durable delivery questions and review discussion; repository docs own normative
content; BuilderOps records own builder-operational material. The caller writes to the appropriate
surface and uses that surface's existing attribution, notification, and retention behavior. This
removes the additional privacy boundary, immutable duplicate, recovery parser, and authority
ambiguity.

Retirement is not yet normative because the present shared Builder Thread contract still describes
subject/content exchange. A separately governed owner-contract change would need to retire that
contract and its producer-facing skills while preserving the current fail-closed production posture
and retained-artifact non-migration rule.

### Conditional separate reference-signal architecture

This section is a fallback, not the selected current capability. It applies only if a promoted use
case proves that the owning surface cannot provide the required bounded recipient notification.

#### Persisted signal language

```text
authenticated endpoint
        |
        | derives actor identity; never accepts actor prose
        v
strict JSON decoder -> discriminated signal decoder -> reference validator
        |                         |
        |                         +-- no unknown, duplicate, missing, or null filler fields
        |                         +-- no subject/content/reason/arbitrary URL/private-host-path/code fields
        v
one serialized writer -> immutable builder-reference-signal.v1 envelope
        ^
        |
same strict decoder + command validator during restart recovery
```

The first useful signal command set should be no larger than:

| Command | Caller data after authentication | Writer-derived/persisted behavior |
| --- | --- | --- |
| `notify` | UUID request token; registered recipient; enumerated intent (`review_request`, `clarification_request`, `handoff`); exactly one typed owning-surface reference | Actor from endpoint; signal UUID; request token stored only as a digest; state `pending`; no subject or message text. |
| `acknowledge` | UUID request token; writer-issued signal UUID; enumerated disposition (`seen`, `handled_on_owner_surface`, `declined`) | Actor from endpoint; state `acknowledged`; no response content. |
| `archive` | UUID request token; writer-issued signal UUID | Actor from endpoint; state `archived`; no optional payload. |

The initial typed-reference set should follow demonstrated need, not the broad v1 regex. Current
tests mainly demonstrate GitHub issue references. A promoted signal contract may add closed
structures for a GitHub issue/PR/comment, a repository document locator (`repo_id`, normalized
repository-relative path, optional anchor), or a BuilderOps record only when its producer and access
semantics are named. It should not accept an arbitrary URI string, absolute path, traversal segment,
or platform-specific path spelling. A reference identifies where the content already belongs; it
does not copy that content or confer its authority.

`request_id` should cease to be a persisted caller string. A UUID-shaped idempotency token can be
hashed at ingress; the digest is enough for exact-retry lookup and prevents the raw token from
becoming a covert content field. Actor comes from the authenticated endpoint, recipient comes from
a host registry, and signal identity comes from the writer. Those producer constraints remove most
of the current classifier's input surface.

### Deliberately separate future tier

If a reference signal cannot carry its demonstrated notification use case, define a separate
artifact class before adding prose to any future exchange:

- name it as best-effort screened builder discussion, not provably `shared_non_sensitive`;
- specify which hosts/providers/backups may receive it;
- define retention and deletion;
- state scanner limits and residual disclosure risk;
- do not let it inherit authority from Builder Threads or a reference signal;
- require a new profile/complexity decision before implementation.

That is a different capability, not a signal field addition.

## Minimal invariant kernel

These provisional identifiers extend the semantics of `docs/testing/invariant-tests.md`; this audit
does not add them to the canonical registry. `BTP-*` governs retirement/containment of the existing
capability. `BRS-*` applies only if a separate signal is promoted.

| ID | Category | Invariant | Current posture |
| --- | --- | --- | --- |
| BTP-MUST-01 | MUST | Builder Thread production remains unavailable. Only a separately accepted capability with its own exact production/recovery gates may change that posture. | Exists — keep (`app/builderops/builder_threads_serialized.py:453-463`). |
| BTP-MUST-02 | MUST | Retirement never migrates, projects, parses, or silently reinterprets retained v1 records. | New; current containment preserves artifacts without recovery (`docs/builderops/BUILDEROPS_VAULT_STORE.md:283-289`). |
| BTP-GATE-01 | GATE | An owner-contract amendment explicitly retires the current question/content capability and its producer-facing skills before dormant code is removed or superseded. | Required because the current shared contract remains authoritative (`.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:9-20,33-40`). |
| BTP-DOCTOR-01 | DOCTOR | A read-only, content-free census reports v1 record counts/schema states without parsing, projecting, migrating, or logging their content. | New; defense in depth, needed only if retained artifacts require disposition. |
| BRS-MUST-01 | MUST | Every admitted signal is one closed, discriminated schema; no optional superset or unknown/null filler field crosses HTTP or persistence. | Conditional future invariant. |
| BRS-MUST-02 | MUST | A signal carries references and enums only; no caller prose, arbitrary URI, private host path, code, patch, binary, or raw request token is persistable. A repository document locator is a typed `repo_id` plus normalized repository-relative path and optional anchor. | Conditional future invariant. |
| BRS-MUST-03 | MUST | Endpoint identity supplies actor, writer state supplies signal identity, registered configuration supplies recipient, and each reference kind has one closed structural grammar. | Conditional future invariant. |
| BRS-MUST-04 | MUST | HTTP admission and recovery call the same versioned byte decoder and signal validator before mutation or reconstruction. | Conditional future invariant. |
| BRS-GATE-01 | GATE | A generated signal-kind × field × HTTP/recovery matrix has one independently reported case ID per row and proves no unclassified persisted field. | Conditional future gate. |
| BRS-GATE-02 | GATE | Production remains disabled until a test enters through the real factory/HTTP call site and reconstructs the exact accepted signal after restart. | Conditional future gate. |

The selected retirement kernel is BTP-MUST-01, BTP-MUST-02, and BTP-GATE-01. BTP-DOCTOR-01 is
operational defense in depth and may wait until retained artifacts need a disposition. The BRS
kernel applies only after the separate capability passes the promotion gate.

## Research-question resolutions

### RQ1 — Is the strict contract reasonable?

Yes as a privacy outcome for any shared artifact; no as a promise that arbitrary prose is provably
safe. It does not by itself justify preserving Builder Thread. The repo should first retire the
unused duplicate exchange and use existing owning surfaces. A separate strict reference signal is a
fallback only after demonstrated need.

### RQ2 — What is the minimum input model?

No new input model if existing owning surfaces meet the use case. If bounded recipient notification
is later proven missing: three discriminated signal commands containing enums,
writer/endpoint-derived identities, UUID-shaped retry tokens, and typed references. No generic
`content`, `subject`, `reason`, arbitrary URL, private host path, or extension map.

### RQ3 — Where does validation live?

No new validation layer is needed for retirement. For a promoted signal, validation lives in one
versioned codec operating on bytes before domain-object construction. HTTP and recovery are adapters
into that same codec. State-transition validation remains inside the serialized writer; it does not
duplicate structural parsing.

### RQ4 — What proof avoids another false green?

For retirement, prove that every production entrypoint stays unavailable and no producer bypasses
the owning surfaces. For a promoted signal, generate the test ledger from the schema definitions,
assert every expected case ID is collected, and execute each row independently through both HTTP and
stored-record recovery where applicable. Aggregate loops may supplement the ledger but cannot
satisfy it.

### RQ5 — Should the writer be rebuilt now?

No. The bounded repo census finds no production caller. Containment and eventual explicit retirement
have the lower failure cost. A separate reference signal may advance only through an accepted
BuilderOps `PromotionIntent` that names one executable producer, an unmet owning-surface need, its
typed reference kinds, and the owner contract to change. Only then may `feature-breakdown` or an
implementation Issue be created.

## SBS reconciliation

- **Conforms to the Builder System boundary:** the artifact remains builder-operational context and
  never becomes Product/Runtime truth (`docs/architecture/SBS_OPERATING_MODEL.md:119-184`).
- **Resolves the simpler-path question first:** retirement uses existing owning surfaces and removes
  the extra persistence boundary. A conditional reference signal would be a new notification/index
  capability, not a data-language-only substitution.
- **Extends no Product SBS subsystem:** no Product/Runtime contract, HKA/MEM state, or user memory is
  read or written.
- **Proposes no SBS reshape:** any future contract promotion remains a Builder System / CES change.

## Finding disposition and governed handoff

| Finding family | Disposition | Handoff state |
| --- | --- | --- |
| Continue repairing the handwritten mixed-text classifier | **Rejected.** | No implementation or backlog action. |
| Weaken `shared_non_sensitive` silently while keeping free prose | **Rejected.** | A future prose tier must be explicitly named and governed. |
| Explicitly retire Builder Thread and use existing owning surfaces | **Accepted as the advisory default.** | Requires a separately governed owner-contract amendment; owner docs remain unchanged. |
| Add a separate reference-only notification/index capability | **Deferred fallback.** | Requires accepted promotion evidence that existing owning surfaces cannot satisfy one named producer/use case. |
| Keep production fail-closed until current-SHA production/recovery proof exists | **Accepted and already contained.** | No further mutation required by this audit. |
| Migrate or inspect retained v1 content | **Deferred.** | Only a content-free doctor is proposed; no migration is authorized. |
| Create a specification, parent feature, or implementation Issue | **Deferred.** | Requires an accepted `PromotionIntent` with one executable producer/use case; none was created in this audit. |

No dependency-ordered backlog is emitted because the architecture-research promotion gate has not
been crossed. This is deliberate: a task graph would recreate the same implementation-first bias
that produced the rejected parser.

## Exact evidence commands

```text
git ls-remote origin refs/heads/main
git rev-parse origin/main
git show 0ccdb8613766a46fb3830227b2a1b3e45979e2d7:<path> | nl -ba | sed -n '<range>p'
git grep -n -E 'ThreadMutation|BuilderThreadClient|builder-thread|builder_thread' 0ccdb8613766a46fb3830227b2a1b3e45979e2d7 -- app .codex scripts tests
gh api repos/RasmusTho/agentic-pkm-mvp/issues/4702
gh api repos/RasmusTho/agentic-pkm-mvp/issues/4708
python3 -c '<pure classifier probes against the byte-identical pinned source>'
python3 -c '<temporary-root close-subject persistence probe against the byte-identical pinned source>'
```

The bounded classifier probes returned `valid` for the prefixed token, ambiguous URL/path, and
over-64-generated-component cases; `indeterminate` for the valid IPv6 ZoneID; and persisted
`/tmp/private` in a close command's unclassified subject. Temporary probe data lived only under the
OS temporary directory. No live BuilderOps artifact, Product vault, retained v1 record, or excluded
historical Issue was read or mutated.

## architecture_research_receipt

```yaml
architecture_research_receipt:
  exact_sha: 0ccdb8613766a46fb3830227b2a1b3e45979e2d7
  retrieved_utc: 2026-08-27T22:09:39Z
  rechecked_utc: 2026-08-27T22:19:30Z
  evidence_scope:
    - "exact-main Builder Thread producers and consumers"
    - "HTTP, serializer, persistence, recovery, classifier, and tests"
    - "BuilderOps Vault, Operations, Builder Thread skill, privacy, SBS, and invariant owner surfaces"
    - "read-only GitHub Issues #4702 and #4708"
  explorer_boundaries:
    - "producer and command-field census"
    - "mechanism and test-coverage census"
    - "owner-contract and invariant census"
  synthesis: "Prefer explicit retirement and existing owning surfaces; keep strictness for any future separate reference signal, never arbitrary prose"
  minimal_kernel:
    - BTP-MUST-01
    - BTP-MUST-02
    - BTP-GATE-01
  conditional_signal_kernel:
    - BRS-MUST-01
    - BRS-MUST-02
    - BRS-MUST-03
    - BRS-MUST-04
    - BRS-GATE-01
    - BRS-GATE-02
  proposed_upstream_artifact: "Builder Thread retirement owner-contract amendment; a separate reference signal only after accepted PromotionIntent"
  github_mutation: "read-only issue retrieval only"
  product_code_change: none
  owner_contract_change: none
  feature_breakdown: none
  open_decisions:
    - "Whether one executable producer proves an owning-surface gap that justifies a separate reference signal"
    - "Which typed reference kinds that producer actually needs"
    - "Whether free prose is needed enough to justify a separately governed best-effort data class"
```
