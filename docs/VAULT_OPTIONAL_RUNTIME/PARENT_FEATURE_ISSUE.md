# Parent Feature Issue

State: **Filed and open** as the live validation hub.

- GitHub: **#2003** — `feature: vault optional at runtime — boot with no vault, open/switch, multi-vault` (`agent:blocked` while children are outstanding).
- This issue is the authoritative backlog/validation surface. Children post a validation
  receipt to #2003 before the next is picked up.

## Child issues (execution order)

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 1 | [RESOLVE_NO_VAULT_STATE](RESOLVE_NO_VAULT_STATE.md) | #2004 | `agent:ready` |
| 2 | [BOOT_RUNTIME_WITHOUT_VAULT](BOOT_RUNTIME_WITHOUT_VAULT.md) | #2005 | `agent:blocked` (on #2004) |
| 3 | [COMPANION_NO_VAULT_ROUTING](COMPANION_NO_VAULT_ROUTING.md) | #2006 | `agent:blocked` (on #2004; ∥ #2005) |
| later | [PIN_VAULT_DEFINITION](PIN_VAULT_DEFINITION.md) | #2007 | `agent:needs-human` (deferred) |

## Closure handoff
The final delivered child (normally #2006 or #2005, whichever lands last) posts the capability
acceptance receipt to #2003 and proposes closure once the README capability-acceptance
checklist is satisfied. #2007 (definition) may remain open as a deferred docs follow-up
without blocking parent closure, at owner discretion.
