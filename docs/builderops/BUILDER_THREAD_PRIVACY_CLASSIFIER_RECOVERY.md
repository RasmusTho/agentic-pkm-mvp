State: Rejected target-state candidate retained as recovery evidence. Although
the implementation from Issue #5118 merged in PR #5122, a fresh exact-head
review found new P1 privacy-boundary and false-green acceptance failures. The
production host is therefore fail-closed under #5124. This document is not the
current implementation contract and does not authorize further point repair.

# Builder Thread Structural Privacy Classifier Recovery

## Purpose and authority

The serialized Builder Thread writer accepts only `shared_non_sensitive`
material. The existing Builder Thread contract remains the authority for that
boundary; this document defines a candidate replacement for the exhausted
`builder-thread-privacy-admission/path-uri-classification` mechanism. It is
Builder System design material, not Product/Runtime truth and not a new
BuilderOps authority surface.

The candidate classifier applies to every caller-controlled value that is
eligible to reach a persisted command envelope, as detailed below. Existing
identity, request-id, and provenance grammar validation remains in place, but
it is not evidence that a credential-like value cannot fit those grammars.
Thread-state values are writer-derived and are not caller input.

### Post-#5122 contract disposition

The strict outcome remains reasonable: secrets, credentials, private host paths,
product code, patches, untyped provenance, and unclassified persisted fields
must never enter immutable shared BuilderOps artifacts. Admission and recovery
must enforce the same closed schema, bounded work, and content-free refusal.

The rejected mechanism prescription is not itself an invariant. In particular,
future work is not required to extend a handwritten parser over arbitrary mixed
prose, URI grammar, filesystem syntax, and every nested encoding merely to retain
the strict privacy outcome. A replacement should first reduce the input problem:
use closed command-specific schemas, keep ordinary prose deliberately narrow,
place resources in typed fields parsed by maintained standards libraries, and
generate row-explicit admission and recovery tests. The exact replacement is a
separate governed decision and implementation slice; none of those options are
claimed as shipped here.

### Persisted record and root-identity inventory

`_persist()` writes the command envelope, and writer-root initialization writes
the root identity. The implementation must retain this entire table as one
review surface; adding a persisted field requires an explicit classification or
proof rule and matching write/recovery cases.

| Persisted field | Record and provenance | Required pre-persistence / recovery rule |
| --- | --- | --- |
| `command.request_id` | command envelope; caller HTTP payload | Existing grammar, then structural classifier; token-shaped values are terminal. |
| `command.kind` | command envelope; caller HTTP payload | Safe by closed `_validate_command` enum (`create`, `reply`, `close`, `archive`); no free text reaches persistence. Test all four through HTTP and recovery. |
| `command.actor` | command envelope; caller HTTP payload | Existing identity grammar and endpoint binding, then structural classifier. |
| `command.thread_id` | command envelope; absent for create, caller HTTP payload otherwise | Existing identifier grammar, then writer resolution under the writer lock. It may persist only after `read_thread` resolves an already-created writer-derived UUID; an unknown or token-shaped candidate must fail before `_persist`. Recovery repeats that resolution in sequence before recording. |
| `command.recipient` | command envelope; caller HTTP payload for create/reply | Existing identity grammar, then structural classifier. |
| `command.subject` | command envelope; caller HTTP payload for create | Structural classifier. |
| `command.content` | command envelope; caller HTTP payload for create/reply and close reason | Structural classifier. |
| `command.source_refs` | command envelope; caller HTTP payload for create/reply | Existing provenance grammar, then structural classifier on each member. |
| `request_digest` | command envelope; writer-derived SHA-256 of canonical command record | Safe by fixed 64-lowercase-hex digest verification against the reconstructed command; it is never caller-supplied text. |
| `sequence` | command envelope; writer-derived accepted-count successor | Safe by positive integer type/range and contiguous recovery-order proof. |
| `schema` | command envelope and root identity; writer literal | Safe only when exactly `builder-thread-command.v1` in an envelope and `builder-thread-writer.v1` in root identity. |
| `vault_id` | command envelope and root identity; writer-host configuration | Existing identifier grammar **and** structural classifier before root creation. Recovery requires equality with that already admitted host value; credential-like or private-path forms are terminal. |

The classifier therefore covers every raw/caller or configured string that may
persist: `request_id`, `actor`, `recipient`, `subject`, `content`, each
`source_ref`, and `vault_id`. `kind`, `thread_id`, digest, sequence, and schema
have the explicitly bounded proof rules above. No persisted field is implicitly
safe.

The record schemas are closed. A root identity has exactly `{schema, vault_id}`;
an envelope has exactly `{command, request_digest, sequence, schema, vault_id}`;
and `command` has exactly `{actor, content, kind, recipient, request_id,
source_refs, subject, thread_id}`. Duplicate JSON keys and every unknown or
missing key are recovery-terminal before any command reconstruction. The
implementation must use a JSON object-pairs hook (or equivalent) that detects
duplicates rather than relying on last-key-wins decoding.

### Recovery ledger

The predecessor mechanism is exhausted and remains bound to its original
ledger. The source record is [#4728 comment
5261290728](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4728#issuecomment-5261290728),
with the preserved evidence and non-merge receipt on #4813.

| Finding class | Required design response |
| --- | --- |
| POSIX, tilde, Windows drive/rooted, and UNC path bypasses | Parse path candidates structurally after bounded decoding; a standalone absolute host path is terminal regardless of its POSIX root. |
| A path-looking legal HTTP(S) resource URL was rejected | Exempt only the parsed path component of a syntactically valid HTTP(S) URI; never infer a private path from authority text. |
| Encoded standalone, query, and fragment bypasses | Decode each untrusted component through a bounded, fail-closed loop before path classification. |
| `file:`/network-filesystem URI bypasses and macOS private-path gaps | Treat local-capable filesystem schemes as terminal refusal candidates and include the complete private-root taxonomy. |
| Whitespace/terminal Windows and named-user tilde forms | Tokenize path boundaries rather than requiring a trailing separator in a regex. |
| Malformed IPv6 ZoneID and existing malformed IDNA A-labels | A malformed HTTP(S) authority is `indeterminate`, never a safe URL exemption. |
| Content-bearing refusal and recovery asymmetry | Return a stable content-free refusal; admission and recovery use the same classifier before persistence or reconstruction. |

## Classifier contract

### Outcomes

`classify_shared_text(value)` has exactly these terminal outcomes:

| Outcome | Meaning | Writer action |
| --- | --- | --- |
| `valid` | Every candidate component is bounded, parsed, and free of prohibited material. | Continue normal command validation. |
| `terminal_private` | A credential-like form, code/patch form, or concrete private-host path is present. | Refuse with the existing content-free `shared_non_sensitive` error. |
| `indeterminate` | A bounded parser cannot establish a safe interpretation: malformed protected syntax, excessive decoding/fan-out, or an invalid authority that would otherwise receive an HTTP(S) exemption. | Refuse with the same content-free error. |

There is no permissive fallback. In particular, malformed input is not treated
as ordinary prose merely because URI parsing failed.

### Recognition grammar and state model

The classifier is a deterministic left-to-right scanner over at most 500 input
characters. It emits at most 64 components. A component is one of:

```text
text           = characters outside a candidate URI or path token
uri-candidate  = scheme ":" (hier-part [ "?" query ] [ "#" fragment ] | opaque)
scheme         = ALPHA *(ALPHA / DIGIT / "+" / "-" / ".")
hier-part      = "//" authority path-abempty
authority      = host [ ":" port ]
host           = ipv6-literal / ipv4-address / idna-dns-name
ipv6-literal   = "[" ipv6-address [ "%25" zone-id ] "]"
path-abempty   = *( "/" segment )
segment        = *uri-char
query          = *uri-char
fragment       = *uri-char
opaque         = 1*uri-char
uri-char       = unreserved / pct-encoded / sub-delim / ":" / "@" / "/" / "?" / "[" / "]"
path-token     = posix-path / tilde-path / windows-drive / windows-rooted / unc-path
```

`unreserved`, `pct-encoded`, and `sub-delim` use RFC 3986 productions. A URI
candidate begins only at `boundary`. The scanner consumes URI characters until
whitespace, `<`, `>`, a double quote, a backtick, or `}`. It preserves every
legal RFC sub-delimiter, including `!`, `,`, `;`, `(`, and `)`. It tracks one
IPv6 bracket literal: its matching `]` is part of the authority; an unmatched
bracket, malformed percent escape, or delimiter-inconsistent form is
`indeterminate`. The terminating character is returned to the outer scanner.
Thus both `https://example.test/home/start)/root/.ssh/id_rsa` and
`https://example.test/a;/root/start` remain legal resource URLs; the classifier
does not infer a local host path from a validated HTTP(S) resource path.

For an HTTP(S) candidate, the parser splits the consumed bytes at the first
`?` and `#`; it validates authority before giving only `path-abempty` the
resource-path exemption. `port` is either empty/absent or decimal `0..65535`.
`ipv4-address` and `ipv6-address` are accepted only through a standard-library
address parser. `idna-dns-name` is converted under IDNA2008 to ASCII, each
label is 1..63 ASCII letters/digits/hyphens without leading/trailing hyphen,
and the total name is at most 253 characters. `zone-id` is one or more RFC 3986
unreserved or percent-encoded characters. Any conversion, address, delimiter,
or range failure is `indeterminate`; it never falls back to URL exemption.

#### Deterministic path-token productions

The scanner applies the productions below to decoded, non-exempt components.
`boundary` is start-of-component or a preceding character that is neither an
ASCII letter/digit nor `_`, `%`, `+`, `-`, or `.`. `terminator` is
end-of-component, whitespace, a quote, or a closing delimiter `)`, `]`, `}`,
`,`, `;`, `!`, or `?`. A token may contain internal `/`, `\\`, `.`, `-`, `_`,
and non-whitespace Unicode text; it ends at the first terminator. URI scanning
runs before path scanning, except the Windows-drive/URI prefix collision below.

```text
segment         = 1*(non-whitespace AND non-terminator)
posix-path      = boundary "/" [segment] terminator
tilde-path      = boundary "~" [user] [ ("/" / "\\") segment ] terminator
user            = 1*(ALPHA / DIGIT / "_" / "-" / ".")
windows-drive   = boundary ALPHA ":" ("\\" / "/") [segment] terminator
windows-rooted  = boundary "\\" segment terminator
unc-path        = boundary "\\\\" segment terminator
```

`posix-path` is terminal whenever it is standalone; no root allowlist exists.
`tilde-path` includes terminal named-user forms such as `~operator` even with
no trailing separator. `windows-rooted` requires exactly one leading backslash;
`unc-path` has two and is recognized before `windows-rooted`. A complete
`windows-drive` is recognized before a one-letter opaque URI candidate. A
matched path is `terminal_private`; a syntactically incomplete candidate that
could become one of these forms after another parse or decode is
`indeterminate`. The parsed path of a valid HTTP(S) URI remains the sole
resource-path exemption.

Recognition is followed by validation, not replaced by it:

1. Scan all text and candidate delimiters without removing characters. At a
   prefix collision, recognize a complete Windows drive/rooted or UNC token
   before considering a one-letter `scheme:` URI candidate; `C:\\Users` must
   never evade path classification by being reinterpreted as opaque URI data.
2. For each candidate URI, validate its scheme and components. Only a valid
   HTTP(S) hierarchical URI with a valid authority can mark its **path** as a
   public-resource-path component.
3. Decode every component one percent-decoding pass at a time, at most twice.
   The parsed valid HTTP(S) path is exempt only from local-host-path scanning;
   its raw and decoded forms still undergo credential and code/patch
   recognition. Text, query, fragment, opaque data, source reference, and
   filesystem-URI components undergo all recognizers. If a third pass would
   change any component, return `indeterminate`. Invalid percent escapes return
   `indeterminate`.
4. Re-tokenize a decoded component before path classification. A decoded nested
   URI gets the same scheme/authority/component rules as its parent; its parsed
   valid HTTP(S) path may receive the narrow resource-path exemption, while its
   query, fragment, opaque data, and invalid authority stay untrusted. Every
   generated component counts toward the 64-component cap; crossing that cap is
   `indeterminate`.
5. Scan each resulting component for credential-like and code/patch forms, then
   parse candidate host paths except in a valid HTTP(S) parsed path. The scanner
   keeps token boundaries, so a path remains detectable before punctuation,
   whitespace, or end-of-input.
6. Return `terminal_private` for a prohibited form, `indeterminate` for an
   unprovable interpretation, and `valid` only after every component passes.

The only exemption is narrow: a valid HTTP(S) URI's parsed path is a
public-resource-path and is not itself classified as a local filesystem path.
That exemption never applies to its authority, userinfo, query, fragment, or
opaque data. It does not suppress credential-like or code/patch detection.

#### Credential and code/patch recognizers

Path parsing does not weaken the existing `shared_non_sensitive` classes. The
candidate uses these deterministic, case-insensitive recognizers on every
non-exempt decoded component and every classified identifier:

| Class | Terminal recognizer family |
| --- | --- |
| Credential-like | ASCII-casefolded substring `password`, `secret`, `credential`, `token`, `apikey`, `api-key`, `api_key`, or `bearer`; at **every line start and decoded URI path-segment start**, optional horizontal whitespace then `authorization:` followed by optional horizontal whitespace then `basic` or `bearer`, or `aws_access_key_id`/`aws_secret_access_key` followed by optional horizontal whitespace and `=`; optional horizontal whitespace then `-----begin ` + ASCII letters/spaces + `private key-----`; `AKIA` + exactly 16 uppercase ASCII letters/digits bounded by non-alphanumeric; `github_pat_` + at least 20 ASCII letters/digits/underscores; or `sk-` optionally followed by `proj-` then at least 20 ASCII letters/digits/underscores/hyphens |
| Code/patch | at **every line start and decoded URI path-segment start**, optional horizontal whitespace then `diff --git `, `--- a/`, `+++ b/`, `@@ `, triple backtick, or `git diff` followed by whitespace/end; or the same boundary followed by optional horizontal whitespace and one case-sensitive concrete syntax form: `async` + whitespace + `def` + whitespace + ASCII identifier + `(`; `def`/`function` + whitespace + identifier + `(`; `class` + whitespace + identifier then `(` or `:`; `const`/`let`/`var` + whitespace + identifier + optional whitespace + `=`; `from` + module token + whitespace + `import`; `import` + module token then end, comma, or whitespace + `as`; `package`/`func` + whitespace + identifier; `print` + optional whitespace + `(`; `return`/`yield` + optional whitespace + one of decimal digit, quote, `(`, `[`, `{`; `throw` + optional whitespace + `new` + whitespace + identifier or `(`; `await` + optional whitespace + identifier + `(` or `Promise.`; `lambda` + parameter + `:`; `if` + non-newline expression + `:`; `console.log(`/`console.error(`/`console.warn(`; or an ASCII JavaScript identifier (`[A-Za-z_$][A-Za-z0-9_$]*`) followed by optional horizontal whitespace, `=`, optional horizontal whitespace, then either parenthesized non-newline parameters or one identifier, optional horizontal whitespace, and `=>` |

Each recognizer runs on both raw and bounded-decoded forms, including a valid
HTTP(S) parsed path, and returns only its terminal class, never the matching
substring. New recognizer families require a matrix row and cannot silently
extend the HTTP(S) exemption.

### URI authorities and schemes

An HTTP(S) authority is valid only when it has no userinfo and exactly one of:

- a DNS authority whose labels are valid ASCII/IDNA A-labels;
- a syntactically valid IPv4 address; or
- a bracketed syntactically valid IPv6 address, with a ZoneID only where the
  URI form permits and percent-encodes it.

Syntactic validity does not make an authority a policy decision about network
reachability. Therefore a legal hostname, IPv4 address, or IPv6 literal is not
mistaken for a private host path. Invalid, ambiguous, or malformed authorities
do not receive the public-resource-path exemption and produce `indeterminate`.

`file`, `smb`, `nfs`, `ssh`, and `sftp` are local-capable filesystem schemes.
Their hierarchical and opaque forms are decoded and classified as filesystem
data; a concrete private path is `terminal_private`, while malformed or
ambiguous filesystem forms are `indeterminate`. An unrecognised scheme grants
no exemption: its data remains untrusted text and follows the same bounded
decode-and-scan path.

### Private-host path taxonomy

The implementation candidate must recognize, after bounded decoding, all of:

- every standalone absolute POSIX path as a terminal host-path form, including
  roots such as `/Users`, `/home`, `/private`, `/root`, `/etc`, `/var`, `/opt`,
  `/tmp`, `/usr`, `/Volumes`, `/mnt`, and macOS `/Library/Keychains`; only the
  parsed path of a valid HTTP(S) URI has the narrow resource-path exemption;
- tilde forms for the current or named user, including slash and backslash
  separators, with or without a terminal separator;
- Windows drive-rooted and rooted paths, including whitespace/terminal forms;
- UNC paths; and
- the same forms embedded as URI query, fragment, opaque data, or source-ref
  data.

The taxonomy names policy roots; it does not log matching content or expose the
matched token in an error.

## Writer, persistence, and recovery ordering

The only production mutation writer remains `SerializedThreadWriter.mutate`.
Its endpoint clients are consumers of the command API, not writers of the
external artifact tree. The recovery consumer is
`SerializedThreadWriter._restore_external_state`; read/inbox consumers only
receive already reconstructed projections.

The proposed ordering is invariant-preserving:

1. The HTTP host authenticates the endpoint, reconstructs the mutation payload,
   and endpoint identity binding and command-shape validation run.
2. The structural classifier validates every inventory field that is classified,
   including identifiers that passed their existing grammar. `kind` and
   `thread_id` use their inventory proof rules before persistence.
3. Only a `valid` command reaches `_persist`; `terminal_private` and
   `indeterminate` leave `accepted_mutation_count` and the final envelope set
   unchanged.
4. `_persist` keeps the existing temporary-write then atomic-publication order.
5. Recovery validates envelope identity, schema, digest, and sequence, then
   calls the same command validation and structural classifier **before**
   rebuilding in-memory thread state or recording an accepted mutation.
6. A rejected recovery envelope fails closed without logging its content and
   without partially rebuilding state after that envelope.

No client filesystem fallback, alternate writer, migration, or live-vault
rewrite belongs to this design.

### States, transitions, locks, and restart behavior

| State | Entry / allowed transition | Durable and observable result |
| --- | --- | --- |
| `candidate` | HTTP payload is reconstructed; only command-shape and identity checks have run. | No final envelope and no accepted mutation. |
| `valid` | Classifier and inventory proof rules pass; create/reply/close/archive state transition is legal. | The writer may create provisional in-memory state while holding its `RLock`. |
| `terminal_private` / `indeterminate` | Any classified field or bounded parser refuses. | Content-free HTTP refusal; no provisional state, final envelope, or accepted mutation. |
| `persisted` | `_persist` atomically links the complete final envelope, then `_record` advances in-memory receipt/count. | One sequence-ordered final envelope; an exact identical request returns the recorded replay result. |
| `compensated` | `_persist` fails after a provisional create/append. | Restore the captured thread/capture-index snapshots, latch typed writer-unavailable, and leave no accepted mutation. This state is not a retry success. |
| `recovery-terminal` | Constructor sees malformed, unsafe, unknown-thread, duplicate, or out-of-order final envelope. | Fail closed before exposing the writer or partial reconstructed state. |

`SerializedThreadWriter.mutate` owns one host-local `RLock` across validation,
exact-retry lookup, provisional state, persistence, compensation, and record.
`_append` calls the re-entrant `read_thread` while that same lock is held; no
queued request can observe a provisional mutation. Construction invokes
`_restore_external_state` before the writer is exposed by its host, so recovery
has no live consumer race. The design adds no cross-process lock or external
claim authority.

Exact retries are compared against the canonical command digest while the lock
is held. A changed command under a used request ID is terminal; an identical
one returns the prior result without another envelope. If publication fails,
the current process stays typed-unavailable until restart. Restart reads only
final `*.json` envelopes in strict sequence and re-runs command, inventory, and
classifier validation; a valid published final either reconstructs once or the
writer fails closed. Same-directory temporary artifacts are not final envelopes
and do not replay; a failed temporary cleanup after an already linked final is
not a second accepted mutation.

## Executable adversarial matrix

The future implementation must turn every admission row into the production
HTTP path: `BuilderThreadClient -> HttpWriterEndpoint ->
BuilderThreadEndpointHost.app().mutate -> _mutation_from_payload ->
BoundWriterEndpoint -> SerializedThreadWriter`. It must exercise recovery via
`SerializedThreadWriter._restore_external_state`. Until then, this is the
executable test design, not evidence that the behavior ships.

| ID | Representative class (non-secret form) | Production HTTP admission | Final-envelope recovery | Focused proof |
| --- | --- | --- | --- | --- |
| P1-01 | Any standalone absolute POSIX path, named/current-user tilde, macOS private root | `terminal_private`; no final envelope | Same persisted fixture -> content-free recovery refusal before reconstruction | `test_private_path_forms_never_persist`, including `/tmp`, `/usr`, `/Volumes`, and `/mnt` |
| P1-02 | Windows drive/rooted/terminal-whitespace and UNC | `terminal_private`; no final envelope | Same persisted fixture -> content-free recovery refusal | `test_windows_and_unc_forms_never_persist` |
| P1-03 | Percent-encoded standalone local path, including double encoding | `terminal_private`; a third effective decode is `indeterminate` | Each persisted fixture -> content-free recovery refusal | `test_bounded_decode_rejects_private_and_excessive_forms` |
| P1-04 | Encoded local path in HTTP(S) query or fragment, including a nested URL | `terminal_private`; no final envelope | Same persisted fixture -> content-free recovery refusal | `test_http_query_fragment_are_untrusted_data` |
| P1-05 | `file:` or network-filesystem URI naming a private path | `terminal_private`, or malformed -> `indeterminate` | Same persisted fixture -> content-free recovery refusal | `test_filesystem_uri_forms_do_not_persist` |
| P1-06 | Invalid IPv6 ZoneID, malformed bracket form, or malformed IDNA A-label | `indeterminate`; no final envelope | Same persisted fixture -> content-free recovery refusal | `test_malformed_authority_has_no_url_exemption` |
| P1-07 | Credential-like assignment, bearer form, private-key marker, token-shaped identifier, or raw/percent-encoded credential (including indented path-segment `authorization:`/AWS form) in a valid HTTP(S) resource path | `terminal_private`; no final envelope | Every persisted-field fixture -> content-free recovery refusal | `test_credential_forms_never_persist` |
| P1-08 | Valid ordinary HTTP(S) DNS, IPv4, IPv6, host+port, `https://home/start`, or nested encoded HTTPS URL with `/home` or `/users` path | `valid`; exactly one final envelope | Same final envelope reconstructs once | `test_valid_http_resource_paths_persist_once` |
| P1-09 | HTTP(S) URL with userinfo | `terminal_private`; no final envelope | Same persisted fixture -> content-free recovery refusal | `test_userinfo_is_not_a_public_url` |
| P1-10 | Content-free refusal | Every terminal/indeterminate row returns the generic error only | Every rejected recovery row exposes no input content | `test_refusals_do_not_echo_input` |
| P1-11 | Interrupted temporary artifact, malformed/unsafe/unknown-thread/out-of-order final envelope | N/A: these are writer-state fixtures, not admissible HTTP mutations | Temporary ignored; final forms fail closed before partial reconstruction | `test_recovery_validates_before_rebuild` |
| P1-12 | More than 64 generated scan components or a decoded component that still changes on a third pass | `indeterminate`; no final envelope | Same persisted fixture -> content-free recovery refusal | `test_component_and_decode_bounds_fail_closed` |
| P1-13 | `kind` enumeration and reply/close/archive `thread_id` | Every kind exercised; unknown/token-shaped thread ID refuses before `_persist` | Each valid writer-derived UUID rebuilds in order; unknown/token-shaped ID fails closed | `test_command_envelope_inventory_http_and_recovery` |
| P1-14 | Publication failure, exact replay, restart, and interrupted temporary artifact | Valid HTTP mutation either persists once, becomes `compensated`, or returns the prior replay; no partial acceptance | Restart rebuilds a valid final once, ignores temporary artifacts, and fails closed on malformed final state | `test_persistence_compensation_and_restart_lineage` |
| P1-15 | Concurrent HTTP mutation/read, provisional create/append, and stale thread observation | A reader or queued mutation cannot observe provisional state while the writer `RLock` is held; an illegal/unknown stale transition has no final envelope | N/A: race is within one writer process; a restart begins only after the process is no longer exposed | `test_rlock_hides_provisional_state_and_rejects_stale_transition` |
| P1-16 | Legal `create -> reply -> close -> archive`, illegal state transitions, and final-link-before-record/acknowledgement loss | Legal transitions persist exactly once; illegal transitions refuse without final envelope; an acknowledgement-loss retry observes one result | Restart from a final linked before local record reconstructs once, then exact retry replays rather than duplicating | `test_transition_and_acknowledgement_crash_lineage` |
| P1-17 | Configured `vault_id`, writer-derived digest/sequence/schema, root identity, and exact key sets | `initialize_external_writer_root` / `BuilderThreadWriterHost.from_environment` rejects unsafe vault ID before HTTP host exists; all derived fields use only their fixed proof domain | Safe root/envelope key sets validate; unknown/duplicate/missing/mismatched key or derived value fails closed before reconstruction | `test_persisted_outer_fields_and_root_identity` |
| P1-18 | Raw/percent-encoded indented code or patch marker at any line or valid HTTP(S) path-segment start, including `async def`, numeric/string `return`/`yield`, `throw new`, and `await Promise` forms; capitalized ordinary prose without the case-sensitive syntax tail and URL with RFC `!`, `,`, `;`, and unmatched/balanced parentheses | Code/patch -> `terminal_private`; prose/ordinary URL -> `valid` once | Code/patch fixture refuses; prose/ordinary URL reconstructs once | `test_code_marker_and_rfc_url_delimiter_matrix` |

The matrix has no row for a live external vault: that would be a separately
governed runtime/operations proof after implementation exists.

## Mechanism identity verdict

**Verdict: `materially_different`, independently clean on 2026-08-27.**

The candidate differs from the exhausted key because its protected decision is
not a collection of path/URI regex exceptions. It introduces a bounded lexical
and parsed-component state model, explicit valid/terminal/indeterminate
outcomes, a scheme/authority policy, shared admission/recovery ordering, and a
single end-to-end matrix. It preserves—rather than resets—the predecessor's
findings and repair accounting.

Fresh Sol/ultra review checked that:

1. checks every ledger row and matrix row against the actual writer and
   recovery entrypoints;
2. confirms that no prior P0/P1 class is merely renamed or hidden behind the
   new grammar; and
3. records a clean `materially_different` result rather than
   `same_exhausted_key`/blocking.

The clean result permits exactly one separately bounded implementation route:
#5118. That Issue preserves the exhausted predecessor ledger and names its own
production, recovery, and current-SHA review gates. It does not authorize a
repair attempt on #4813, CI, merge, or closure from this design artifact.

## Traceability

- Issue contract: #4846.
- Exhausted predecessor and ledger: #4728, #4813, and #4728 comment 5261290728.
- Existing boundary: `.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md :: Capture, Privacy, And Read Bounds`.
- Writer and recovery entrypoints: `app/builderops/builder_threads_serialized.py :: _validate_command / _validate_text / _restore_external_state / _persist`.
- Store boundary: `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Builder Thread artifact exchange`.
- Repair identity policy: `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate`.
