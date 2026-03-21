State: Concept contract (system-agent ontology, delegation, authority, and accountability).
Doc role: Core SoT
Authority: Canonical semantic contract for `System Agent`, `Agent Role`, `Delegation`, `Authority Boundary`, and `Receipt`; runtime architecture docs may describe implementations, but must not redefine these concepts.

# Agent Ontology Contract

## Purpose

This document defines the canonical ontology for bounded system agency in the second-brain domain.

It exists to keep four things explicit:
- what a `System Agent` is,
- how that differs from a role, tool, or deterministic component,
- how authority is delegated and bounded,
- and how accountable action is recorded through receipts.

The goal is to describe what kind of help the system is meant to provide:
- assistive help that reduces cognitive and practical load,
- without displacing human judgment,
- without hiding authority,
- and without turning opaque automation into assumed truth.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/AGENTS.md`
- `docs/HUMAN-FLOWS.md`

## Contract boundary

This contract defines ontology and accountability semantics.

It does not define:
- the runtime matrix of current agents,
- one required implementation framework,
- internal graph structure,
- or event schema details,
- or development-time coding agents / repo assistants that work on this repository.

Its purpose is to answer:
- what kind of actor a system agent is,
- which runtime entities count as agents versus components,
- how delegated authority is bounded,
- and what must exist for actions to remain attributable.

## Core rule

System agency in this system is delegated, bounded, and accountable.

Therefore:
- a system agent never owns final meaning or final authority,
- automation is never authority-free,
- role, agent, tool, and component must not be silently collapsed,
- and every meaningful agent action must remain reconstructable through receipts and provenance.

This is not primarily a software-architecture preference.
It follows from the human problem being solved:
- the system should help the human think, decide, and act,
- but it must do so without confusing who meant what, who authorized what, and what actually
  happened.

Development-time contributors and coding agents are outside this ontology.
They are governed by dev-layer workflow and repo policy docs, not by the runtime system-agent
contract.

## Primary concepts

### `System Agent`

A system agent is a bounded assisting actor that can observe, retrieve, propose, transform, plan,
or execute within explicit limits.

Problem solved:
- some forms of cognitive and practical support require an active helper, not only passive storage
  or retrieval.

A system agent:
- acts on delegation, policy, or explicit intent,
- operates within a defined authority boundary,
- does not become the primary bearer of meaning,
- and must remain attributable and auditable.

Not every runtime unit is a system agent.
A deterministic pipeline stage, storage adapter, or utility component may support agency without
being an ontological actor in its own right.

### `Agent Role`

An agent role is the functional posture an agent takes within a bounded context.

Problem solved:
- the system needs to distinguish kinds of help, so that retrieval, review, planning, and other
  assisting functions are not treated as one undifferentiated agency blob.

Examples:
- retrieving,
- reviewing,
- planning,
- classifying,
- promoting,
- or reconciling.

An agent role is not identical to a concrete runtime implementation.
The same system agent may carry more than one role across contexts, and multiple runtime units may
instantiate similar roles.

### `Delegation`

Delegation is the bounded authorization by which a human permits a system agent to act within a
defined scope.

Problem solved:
- the system must help without forcing the human to either micromanage every action or surrender
  control entirely.

Delegation defines:
- what kinds of actions are allowed,
- under what conditions,
- on which artifacts or surfaces,
- with what review or confirmation requirements,
- and how that authority can be narrowed, revoked, or overridden.

Delegation may be expressed through:
- explicit human instruction,
- confirmed panel action,
- standing policy,
- or narrowly defined automatic behavior that still remains attributable.

Delegation does not erase responsibility boundaries.
It is the mechanism that makes automation legible and governable.

### `Authority Boundary`

An authority boundary defines what an agent may and may not do without further human involvement.

Problem solved:
- assistance becomes unsafe and epistemically confusing if the human cannot tell where system power
  stops.

This includes limits on:
- domains,
- planes,
- trust posture,
- write scope,
- transition types,
- and reversibility expectations.

Authority boundary is therefore not a minor implementation detail.
It is part of the domain contract that protects human authorship, provenance, and control.

### `Receipt`

A receipt is a human-legible accountability record of what happened, by whom or by what, under what
authority, on what basis, and with what result.

Problem solved:
- helpful automation is not enough; the human must be able to inspect and understand system action
  afterward.

A receipt must make it possible to reconstruct:
- the action,
- the acting agent or acting component context,
- the delegation or intent that authorized it,
- the sources or rationale involved,
- the affected artifacts or surfaces,
- and the outcome, including failure where relevant.

Receipts are not optional diagnostics.
They are part of how agent action remains acceptable in a human-first system.

## Distinctions that must remain explicit

### Agent vs role

- `System Agent` answers: what kind of actor is this?
- `Agent Role` answers: what functional posture is it taking here?

These must not be treated as interchangeable.

### Agent vs component

- a system agent is an ontological actor with bounded assisting agency,
- a component is an architectural/runtime unit that may or may not embody such agency.

Some runtime entries called "agents" are better understood as deterministic components or migration
era naming continuity.

### Agent vs tool

- a tool is a capability or operation surface used by an agent or by orchestration,
- it is not automatically an actor.

### Event vs receipt

- an event is a runtime coordination record,
- a receipt is a human-legible accountability record.

The event stream may support receipt construction, but it is not the full receipt model by itself.

## Human-first accountability rule

Meaningful agent action must always preserve a clear line back to the human authority structure.

At minimum this means:
- the human remains the final authority for durable meaning and consequential change,
- explicit intent or policy basis must be discoverable,
- actions must remain attributable,
- and silent authority escalation is forbidden.

This applies even when the system runs automatically under standing policy.
Automatic execution still depends on delegation and still requires accountability.

## Relation to trust semantics

Trust semantics and agent ontology are adjacent but not identical.

- trust semantics govern whether the system should ASSERT, SUGGEST, or APPLY,
- agent ontology governs who is acting, under what delegation, and how that action remains bounded
  and accountable.

An agent may be technically able to act and still not be authorized to APPLY.

## Relation to execution artifacts

Generated execution plans, intents, and outbox events are system artifacts that support agent
coordination.

They are not themselves the acting authority.

Authority comes from:
- human intent,
- policy-backed delegation,
- and bounded runtime execution under those conditions.

## Minimal accountability rule

Any implementation that claims to support agentic action in this system should be able to answer:
- which agent or runtime actor acted,
- which role it was acting in,
- what authority basis allowed the action,
- what boundary conditions applied,
- what was changed or proposed,
- and where the human can inspect the resulting receipt.

## Migration direction

The intended direction is:
1. keep `docs/AGENTS.md` as the runtime coordination map rather than the full ontology of agency,
2. make `System Agent`, `Agent Role`, `Delegation`, `Authority Boundary`, and `Receipt` explicit in
   concept contracts,
3. avoid calling every pipeline or helper an agent when no real assisting agency is implied,
4. keep event streams and receipts related but distinct,
5. and require automation narratives to name the authority basis rather than implying that runtime
   execution is self-justifying.
