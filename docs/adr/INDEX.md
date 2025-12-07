State: SoT v4.10 Reality-MVP (index; mixed legacy/partially applied ADRs).
# ADR Index

| ADR | Title | State | Notes |
| --- | --- | --- | --- |
| [0004](./0004-outbox-latency.md) | Control outbox-to-index latency <= 2s | Partially outdated | Outbox envelope exists; no latency worker/CI gate in Reality-MVP. |
| [0005](./0005-per-loop.md) | Standardize PER-loop agent base | Partially applied | Base loop exists; ASK/panel agents use bespoke graphs; not enforced repo-wide. |
| [Agent memory v1](./ADR-00X-agent-memory-v1.md) | Postgres JSONB agent memory | Legacy (archived) | Superseded by Reality-MVP (ObjectStore + in-memory decisions only). |
| [Agent memory v4.2](./ADR-00X-agent-memory-v42.md) | Scoped PG memory with edges | Legacy (archived) | Not implemented in v4.10; see DATA_MODEL/ObjectStore. |
| [0001](./0001-externa-komponenter.md) | External components | Legacy (archived) | Superseded by SYSTEM_DESIGN_v4.10/LLM/COMPONENTS. |
| [00xx](../adrs/ADR-00xx-promotion-agent.md) | Promotion Agent – event-driven | Partially outdated | Promotion/projector stubs only; filesystem/frontmatter moves are future work. |
