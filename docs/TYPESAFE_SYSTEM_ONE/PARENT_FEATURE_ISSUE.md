State: Active capability validation hub, Issue #5764.

# Parent Capability Issue

[Issue #5764](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5764) is the authoritative end-to-end acceptance and validation surface for the TypeSafe System One capability. This specification defines stable intent; child Issues are the bounded implementation contracts.

The parent remains open until both the Product and Builder slices and their separately governed dev acceptance evidence are complete. Repository tests use fakes. Live TypeSafe use requires owner-confirmed rotation, a provider-key binding installed only on the MARR Mac dev server, separate Product/Builder caller credentials and profiles, explicit one-call authorization with synthetic input, and redacted receipts. The runtime key is not granted to either caller, Linux, BWS readers, or coding-agent runtime consumers.
