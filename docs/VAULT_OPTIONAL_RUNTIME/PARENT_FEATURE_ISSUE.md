# Parent Feature Issue

State: **Filed and open** as the live validation hub.

- GitHub: **#2003** - `feature: vault optional at runtime - boot with no vault, open/switch, multi-vault` (`agent:blocked` while children are outstanding).
- Follow-up hub: **#2311** - `refactor: migrate eager resolve_vault_root() consumers to optional/picker (no silent ./vault)` (`agent:blocked` while child slices are created and delivered).
- This issue is the authoritative backlog/validation surface. Children post a validation
  receipt to #2003 before the next is picked up.

## Child issues (execution order)

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 1 | [RESOLVE_NO_VAULT_STATE](RESOLVE_NO_VAULT_STATE.md) | #2004 | `agent:ready` |
| 2 | [BOOT_RUNTIME_WITHOUT_VAULT](BOOT_RUNTIME_WITHOUT_VAULT.md) | #2005 | `agent:blocked` (on #2004) |
| 3 | [COMPANION_NO_VAULT_ROUTING](COMPANION_NO_VAULT_ROUTING.md) | #2006 | `agent:blocked` (on #2004; ∥ #2005) |
| later | [PIN_VAULT_DEFINITION](PIN_VAULT_DEFINITION.md) | #2007 | `agent:needs-human` (deferred) |

## Follow-up child issues for #2311

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 05A | [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES](API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md) | TBD | file first; then `agent:ready` |
| 05B | [BACKGROUND_OPTIONAL_VAULT_IDLE](BACKGROUND_OPTIONAL_VAULT_IDLE.md) | TBD | file as blocked/backlog until 05A delivery releases it; includes worker/settings plus direct vault helper fallbacks |
| 05C | [PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION](PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION.md) | TBD | file as blocked/backlog until 05A/05B sequencing is clear |

#2311 remains the validation hub for the follow-up migration and should not be implemented
directly. Each delivered child posts evidence to #2311 before the next slice is picked up.
The same evidence may be linked to #2003 for traceability, but #2311 is a follow-up hub and
does not by itself reopen or block the original #2003 closure contract unless the owner
explicitly keeps #2003 open for this follow-up.

## Closure handoff
The final delivered child (normally #2006 or #2005, whichever lands last) posts the capability
acceptance receipt to #2003 and proposes closure once the README capability-acceptance
checklist is satisfied. #2007 (definition) may remain open as a deferred docs follow-up
without blocking parent closure, at owner discretion.

For the #2311 follow-up, closure is separate: after 05A-05C are delivered and evidence is
posted to #2311, close #2311 through verification-and-closure. Do not use #2311 child
delivery alone as authority to close #2003; use the original #2003 checklist and owner
decision for that parent.
