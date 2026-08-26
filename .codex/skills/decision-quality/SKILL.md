---
name: decision-quality
description: Prepare, assess, or improve a decision process in any domain. Use to determine what a decision maker needs to know, decide whether an agent may act autonomously, improve decision support, or review a workflow against the seven dimensions of Decision Quality.
---

# Decision Quality

Help a person or an authorized agent make a high-quality decision at the time of choice. Judge the process and the quality of decision support, not whether hindsight later makes the outcome look fortunate.

This is a general decision method. It applies to product, technical, operational, career, purchasing, personal, and organizational choices. A ticket, label, alert, plan, test failure, conflict, or dashboard state is only an incoming signal; it is not itself a decision, decision record, or authority.

The method has two modes:

- **Decision support:** prepare or repair proportionate support for a real choice by a person or an authorized agent.
- **Design review:** assess whether a UI, workflow, policy, or skill enables the seven dimensions. Do not treat the review itself as a decision or authorization to act.

## Core rule: begin with the decision maker's context

Start from the decision maker's actual context, never from the agent's preferred technical framing. Establish what the person is trying to achieve, what they are responsible for, what they will notice, the relevant time horizon, constraints, and which consequences matter to them. Do this before deciding what information to collect, what model to use, or which alternatives to compare.

Decision Quality protects a decision maker's attention, but it also makes appropriate autonomous action possible. An agent may decide and act when all of these hold:

- the decision is within its established mandate or a safe default is already authorized;
- the decision-relevant evidence is proportionate and sufficiently reliable;
- downside is low, bounded, or reversibly recoverable; and
- the decision does not select a person's values, risk tolerance, rights, budget, relationships, long-term direction, or another explicitly reserved boundary.

Otherwise the agent must seek the smallest missing fact, observation, authority, or decision. A technical choice, disagreement between implementation paths, missing credential, or difficult recovery does not by itself become a human decision.

Do not overload the person with this internal method. Unless they ask for detail, show only the decision they need to make (if any), the recommendation, the meaningful human consequence and trade-off, uncertainty that could change the outcome, and what follows from their answer. Keep evidence, models, ratings, and working notes available behind that short view.

## Evidence discipline

Separate each statement into one of these classes:

- **Established:** verified decision-relevant evidence, with source and freshness where material.
- **Assumption:** plausible but unverified input that could influence the choice.
- **Unknown:** information that is missing or unavailable.
- **Interpretation:** reasoning from established evidence and stated assumptions.

Do not hide uncertainty through confident prose or invent background, authority, objectives, alternatives, or agreement. A label, task, plan, generated view, screen, agent history, or linked record is routing evidence only unless a current authoritative source explicitly makes it binding.

## Universal preflight: classify the situation before escalating

Run this preflight for every material incoming problem, question, alert, proposal, or apparent blocker. Use current authoritative sources where they exist.

1. State the provisional decision-maker context and the apparent problem in ordinary human terms.
2. Check whether a contract, policy, prior decision, acceptance criterion, law, or explicit operator gate already settles the desired outcome. Remove options that violate it.
3. Classify the situation into exactly one current route:
   - **Agent-actionable:** the agent can investigate, interpret, repair, recover, or make an authorized low-risk decision.
   - **Technical or external access:** the outcome is already established, but a system, credential, service, host, supplier, or other external dependency is unavailable. Route it technically; do not manufacture a value choice. If granting access would itself create a new rights, cost, or risk commitment, classify that commitment as a human decision instead.
   - **Acceptance observation:** an already agreed outcome needs a real observation, trial, or confirmation from the appropriate person or environment. Request the precise observation and success signal; do not ask for a new choice.
   - **Genuine decision:** two or more still-authorized paths differ materially in value, human experience, trust, safety, rights, cost, reversibility, or reserved strategy.
4. Record the authoritative source, scope, classification, and next action. A human escalation or `agent:needs-human` equivalent is invalid without this record.

For recovery or exception authority, bind the authority to the actual object and boundary: the system or artifact, intended action, scope, expiry or review trigger, and relevant constraints. Contextually linked records do not substitute for that scope.

If classification is not yet possible, the next action is normally agent investigation, not a broad question to the decision maker.

## Two-or-more-pass context discipline

For every material decision or material problem that may become one, complete at least two passes before presenting a final decision request or committing an irreversible course. Do not fix the process at exactly two: repeat when a later pass materially changes the frame. For low-stakes, familiar, reversible work, the second pass may be brief but may not be skipped.

### Pass one: concrete context and provisional frame

Work in this order:

1. Establish the decision-maker context and classify the situation with the universal preflight.
2. State the provisional frame: who may decide, what exact change is in scope, what is excluded, timing, and existing constraints.
3. Identify the smallest set of real alternatives, including no change, deferral, or a reversible trial when relevant.
4. Identify only the information whose answer could change the frame, alternative ranking, a material risk, or reversibility.
5. Identify the values and trade-offs that distinguish the alternatives.

Do not begin detailed reasoning, model selection, or broad research before these earlier steps are proportionate. A later discovery that changes an earlier step invalidates dependent downstream work and returns the process to the affected step.

### Pass two: scope challenge and reframe

Actively attempt to falsify the first pass rather than merely checking it for consistency:

- Is the frame too narrow, too broad, or centered on a symptom rather than the person's actual outcome?
- Is this really a human decision, or should it be classified as agent action, access, or acceptance observation?
- Does an accepted contract or specific prior decision already settle the outcome?
- What credible alternative framing, stakeholder, consequence, or outside/reference-class view could change the information needed or the preferred action?
- Are the stated alternatives genuinely authorized, or merely technically describable?

If the frame changes, restart from the affected step in pass one. If it holds, proceed to reasoning. Further passes are required whenever new evidence or a changed frame could materially alter the decision.

## The seven dimensions and weakest-link control

Assess every material decision on all seven dimensions at the start of each pass and after each meaningful strengthening action:

1. **Appropriate frame** — the exact choice, decision maker, scope, timing, and higher-order dependencies.
2. **Creative, doable alternatives** — distinct, authorized options, including deferral, status quo, and reversible experiments where relevant.
3. **Relevant, reliable information** — decision-changing evidence that is current, attributable, and clear about uncertainty.
4. **Clear values and trade-offs** — outcomes, constraints, risks, stakeholders, and compromises that actually matter to the decision maker.
5. **Sound reasoning** — a traceable, context-appropriate comparison from evidence and assumptions to conclusion.
6. **Commitment to action** — actual authority, access, tools, time, dependencies, capability, difficulty, and recovery path.
7. **Psychological decision readiness** — enough understanding and agency to choose without jargon, pressure, false urgency, or unnecessary cognitive load.

For each dimension keep an internal rating of `strong`, `adequate`, `weak`, or `unknown`, with evidence, material gap, whether resolving it could change the outcome, and the smallest strengthening action. Do not present this ledger to the decision maker by default.

The process is constrained by its weakest material link. Improve the lowest-quality link whose prerequisites have been met; if that link depends on an earlier stage, strengthen the earlier stage first. Do not compensate for a weak frame, missing value, or uncertain authority by adding more volume elsewhere. Reassess all seven after each meaningful action and follow the newly weakest material link.

## Information gate and research assistance

Before asking a person for missing information:

1. Name the exact missing item and how it could change the frame, recommendation, or risk.
2. Retrieve it from suitable authoritative sources when the agent can do so safely.
3. Use one or more bounded subagents when independent domain research, a credible outside view, or a focused scope challenge is likely to improve the decision enough to justify the cost.
4. Ask the person only when the item is genuinely unavailable to the agent.

Every human request for unavailable information must be one of these:

- a **fact request** for a personal constraint, preference, or private knowledge only that person has;
- an **acceptance request** for a specific observation only the appropriate person or environment can make; or
- a **decision request** for a remaining human value, mandate, rights, cost, risk, or irreversibility choice.

Never disguise a missing fact or observation as “what would you like to do?”

Subagents are research and challenge aids, not decision delegates. Give each the smallest useful scope and require sources, established facts, assumptions, unknowns, and how findings could alter the frame. Keep them read-only by default. They must not contact the decision maker, create escalation state, mutate external systems, or decide the final question. The primary agent verifies and synthesizes their findings.

## Reasoning after the frame is sound

Select a proven decision model only after context, scope, alternatives, information needs, and values are proportionate. Explain internally why the model fits and what it cannot establish. Models clarify trade-offs; they do not set human values or fabricate precision.

Use a model that fits the mechanism of the decision, for example:

- **Total cost of ownership** when lifecycle cost, maintenance, operation, replacement, or disposal matters more than purchase price.
- **Multi-criteria decision analysis** when several criteria must be compared and the decision maker's weights are explicit.
- **Scenarios or expected-value analysis** when uncertainty, likelihood, and consequences are central and estimates are defensible.
- **Outside view or reference class** when a plan-based forecast may be optimistic or unusually framed.
- **Reversible experiment or real-options reasoning** when uncertainty is high but learning can be bought cheaply and safely.
- **Minimax regret** when an irreversible or asymmetric downside dominates.

State material assumptions, sensitivity, and the one uncertainty most likely to reverse the recommendation. Do not use a model merely because it is available or sophisticated.

## Authority and human-decision gate

An agent should take the authorized autonomous action rather than escalate when the universal preflight identifies agent-actionable work and the autonomy conditions in the core rule hold. Report the result compactly afterwards.

Escalate only after the two-or-more-pass discipline, the information gate, and weakest-link work leave a genuine human-owned choice. Before asking, confirm in order:

1. **Necessity:** a real value, user, trust, safety, rights, authority, cost, or strategy choice remains.
2. **Ownership:** the choice is reserved for this person rather than within the agent's mandate.
3. **Readiness:** current evidence, meaningful consequences, uncertainty, a recommendation, and a safe default are available.
4. **Cognitive load:** the request is worth the person's attention and is phrased without domain jargon.

If any answer is no, do not escalate. Take the authorized action, seek the missing information, or route the technical/access/acceptance work instead. Do not use a stale label or prior escalation as evidence that the person must decide now.

## Owner-facing output

Lead with the smallest usable decision view. Unless the person asks for analysis, include only:

- the decision requested, in plain language;
- the recommendation and confidence;
- the material human consequence and trade-off;
- uncertainty that could change the answer; and
- what happens after the response, including the safe default if they defer.

Do not make the person reconstruct repository state, technical mechanisms, or the seven-dimension analysis. Offer deeper evidence, sources, assumptions, alternatives, model detail, and the internal quality ledger on request.

After an action or decision, record the selected path, accountable decision maker or agent, first concrete action, required access or dependencies, success signal, and review trigger. This is a handoff, not permission to create a parallel task store or an unbounded delivery plan.

## Design review

For a workflow, UI, or policy review, identify the intended decision-maker context and evaluate whether it enables the universal preflight, two-or-more-pass challenge, information gate, seven dimensions, proportionate autonomy, and low-cognitive-load output. Rate each of the seven dimensions with evidence and one concrete improvement. Do not score a design as strong merely because it displays a lot of information.

## Context profiles

The core method is general. A context profile may add non-negotiable checks without redefining the seven dimensions.

### Yggdrasil profile

When used for Yggdrasil or Agentic PKM work:

- establish the applicable human or agent authority and authoritative sources before action or recommendation;
- distinguish current delivered state, target state, advisory material, and operational projection;
- treat GitHub labels, linked Issues, screens, plans, generated views, and agent history as routing evidence, not decision, lifecycle, or authorization proof;
- preserve boundaries between observation, proposal, decision, command, and receipt; and
- bind recovery authorization to the actual PR, repository, branch or SHA, action, and boundary; a linked Issue is context only.

## Scale the work

- **Low stakes / reversible:** retain both passes, but make the scope challenge and evidence proportionate.
- **Material or partially irreversible:** require explicit alternatives, trade-offs, evidence, uncertainty, model choice, and execution ownership.
- **High stakes or hard to reverse:** require source verification, explicit authority, scenario/risk analysis, independent challenge where useful, and a defined reconsideration trigger.

## Output standard

Be concise enough to be used. State exactly what cannot yet be decided, the smallest evidence that could change that, and whether the agent can safely act now. Do not expose internal process detail unless it is material to the person's decision or they ask for it.
