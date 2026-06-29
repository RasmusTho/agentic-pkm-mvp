# Parent Feature Issue

State: **Delivered and closed**. Parent validation hub #2003 closed as completed on 2026-06-18 after children #2004-#2007 delivered; follow-up hub #2311 later closed as completed on 2026-06-24 after slices 05A-05D delivered, including the legacy `/app/vault` compatibility-path re-baseline recorded in 05D.

- GitHub: **#2003** - `feature: vault optional at runtime - boot with no vault, open/switch, multi-vault` (`CLOSED` / `COMPLETED`, `Status=Done`).
- Follow-up hub: **#2311** - `refactor: migrate eager resolve_vault_root() consumers to optional/picker (no silent ./vault)` (`CLOSED` / `COMPLETED`, `Status=Done`).
- These issues remain the authoritative backlog/validation surfaces for the capability and its follow-up; local files here mirror the delivered state.

## Child issues (execution order)

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 1 | [RESOLVE_NO_VAULT_STATE](RESOLVE_NO_VAULT_STATE.md) | #2004 | closed/completed |
| 2 | [BOOT_RUNTIME_WITHOUT_VAULT](BOOT_RUNTIME_WITHOUT_VAULT.md) | #2005 | closed/completed |
| 3 | [COMPANION_NO_VAULT_ROUTING](COMPANION_NO_VAULT_ROUTING.md) | #2006 | closed/completed |
| later | [PIN_VAULT_DEFINITION](PIN_VAULT_DEFINITION.md) | #2007 | closed/completed |

## Follow-up child issues for #2311

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 05A | [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES](API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md) | #2383 | closed/completed |
| 05B | [BACKGROUND_OPTIONAL_VAULT_IDLE](BACKGROUND_OPTIONAL_VAULT_IDLE.md) | #2384 | closed/completed |
| 05C | [PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION](PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION.md) | #2385 | closed/completed |
| 05D | [LEGACY_VAULT_MOUNT_REMOVAL](LEGACY_VAULT_MOUNT_REMOVAL.md) | #2386 | closed/completed |

#2311 was the validation hub for the follow-up migration and closed as completed once all
four child slices delivered. Its 05D closure records the legacy `/app/vault` compatibility
path as re-baselined, not that every compatibility-mount reference vanished from owner docs.
The same evidence could be linked to #2003 for traceability, but #2311 did not reopen the
original #2003 closure contract.

## Closure handoff
#2003 closed after the capability acceptance receipt confirmed the original checklist on
merged heads, including the vault-definition doc pin. #2311 closed separately after 05A-05D
delivered and evidence posted there. Neither hub is an active pickup or validation surface now;
reopen only if later verification uncovers a gap.
