State: Concept contract (human commitment layer for second-brain work).
Doc role: Core SoT
Authority: Canonical semantic contract for human commitment structures; neighboring docs may describe policy or runtime support, but must not collapse these concepts into execution artifacts.

# Commitment Layer Contract

## Purpose

This document defines the human commitment layer of the system.

It exists to make explicit that the system is not only an artifact environment.
It is also a commitment and attention environment in which the human tracks work that requires
clarification, maintenance, progress, handoff, review, or closure over time.

The point of this layer is to describe what the system is for in lived use:
- reducing the burden of carrying open loops in working memory,
- helping the human clarify what requires action,
- helping the human keep track of what is waiting,
- and helping the human return to work with restored orientation.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/HUMAN-FLOWS.md`
- `docs/PROJECT_KERNEL.md`

## Contract boundary

This layer describes human commitment structure.

It does not define:
- the full artifact ontology,
- execution-plan schema,
- event lifecycle,
- or low-level task runner behavior.

Its purpose is to answer:
- what kinds of open loops the human is carrying,
- how those open loops are structured,
- what makes a next step actionable,
- what it means for something to be waiting,
- and how periodic review restores orientation and trust.

## Core rule

Human commitment structures are not the same thing as runtime execution plans.

Therefore:
- a `Project` is not an execution graph,
- a `Commitment` is not only a note or metadata record,
- a `Next Action` is not merely a tool call or action-catalog item,
- a `Waiting` state is not equivalent to generic inactivity,
- and a `Review Cycle` is not the same thing as content approval or `review_state`.

Runtime `Plan` remains an `Execution Artifact`.
It may support commitments, but it does not replace the human commitment model.

This matters because the problem being solved is not "how the runtime sequences steps".
It is "how the human can maintain orientation, responsibility, and progress over time".

## Primary concepts

### `Commitment`

A commitment is something the human experiences as requiring attention, maintenance, progress,
decision, follow-up, or closure.

Problem solved:
- the system must help the human not lose track of what still matters.

A commitment may be:
- active,
- deferred,
- blocked,
- delegated,
- or closed.

A commitment is broader than a task.
It can include:
- obligations,
- outcomes to deliver,
- matters to decide,
- promises to keep,
- and open loops that have not yet been sufficiently clarified.

### `Project`

A project is a commitment that requires multiple steps over time to reach a meaningful outcome.

Problem solved:
- some meaningful outcomes cannot be carried safely as one step or one note; they need durable
  structure over time.

A project is defined by:
- an intended outcome or direction,
- persistence over time,
- and the need for more than one action, decision, or waiting interval.

A project is not defined by:
- folder structure,
- note count,
- tag presence,
- or the existence of a generated runtime plan.

### `Next Action`

A next action is the next concrete step that can advance a commitment or project.

Problem solved:
- the human needs a step that is concrete enough to actually do, not only a vague area of concern.

A next action should be:
- specific enough to perform,
- situated enough that the human can recognize when it is available,
- and bounded enough that it advances the commitment without requiring hidden sub-planning first.

A next action is not the same thing as:
- a vague intention,
- a broad area of work,
- or a system action label detached from human context.

### `Waiting`

`Waiting` is the commitment state in which progress depends on another actor, another event, or a
future condition that is not currently under direct control.

Problem solved:
- the system must keep blocked or deferred matters visible without forcing them to masquerade as
  immediately actionable work.

Waiting is not nothing.
It still belongs to the human's commitment landscape because it requires:
- tracking,
- possible follow-up,
- and eventual review.

Examples:
- awaiting a reply,
- awaiting delivery,
- waiting for a decision,
- waiting for a future date or trigger condition.

### `Review Cycle`

A review cycle is a recurring re-orientation practice through which the human restores trust in the
system's commitment landscape.

Problem solved:
- the system will drift out of usefulness unless the human can periodically re-establish trust in
  what is tracked, what is missing, and what now matters.

Its purpose is to:
- re-surface open loops,
- check what has changed,
- re-clarify ambiguous commitments,
- promote or defer work appropriately,
- and prevent drift between lived responsibility and recorded structure.

Review cycle is therefore:
- a commitment-layer practice,
- a metacognitive operation,
- and a trust-restoring discipline.

It is not identical to:
- content review,
- approval of a single artifact,
- or the `review_state` axis.

## Relation to artifacts

Commitments may be represented by artifacts, but they are not reducible to artifacts.

Examples:
- a project note may support a `Project`,
- a checklist item may express a `Next Action`,
- a waiting note may record a `Waiting` condition,
- a weekly review note may support a `Review Cycle`.

However:
- the note is not the commitment itself,
- and the absence of one canonical note does not mean the commitment does not exist.

This distinction matters because the system must support human responsibility and attention, not
only artifact storage.

## Relation to state axes

The commitment layer and the artifact state axes are different layers.

In particular:
- `review_state` describes artifact review/mutation posture,
- `maturity` describes artifact standing or durability,
- neither of them defines whether a commitment is active, waiting, or complete,
- and commitment tracking must not be forced into `review_state` vocabulary.

## Relation to execution artifacts

Generated plans, subplans, and orchestration structures are execution artifacts.

They may:
- help sequence work,
- propose steps,
- or automate bounded actions.

But they must not be treated as if they were automatically equivalent to:
- the human's project structure,
- the human's actual commitments,
- or the human's authoritative next actions.

Execution artifacts are system process structures.
Commitment structures are part of the human second-brain model.

## Open loops and clarification

An open loop is anything still holding the human's attention without sufficient clarification or
closure.

The commitment layer exists partly to clarify open loops into more stable forms such as:
- commitment,
- project,
- next action,
- waiting,
- scheduled review,
- or intentional closure.

This should be treated as a first-class function of the system, not as optional methodology
decoration.

## Minimal modeling rule

The system does not need to force one prescriptive productivity methodology.

However, any implementation that claims to support second-brain project/commitment work should be
able to represent at least:
- that something is a commitment,
- whether it is a multi-step project,
- what the next actionable step is when one is known,
- when something is waiting on another actor/event,
- and how/when it returns to review.

## Migration direction

The intended direction is:
1. stop letting `Plan` language stand in for all human project/commitment structure,
2. make room in docs and runtime contracts for explicit commitment semantics,
3. keep execution artifacts and commitment structures related but separate,
4. avoid reducing all open loops to notes or all actions to tool invocations,
5. and treat review cycles as a real part of system trust, not only as a UX convention.
