---
kind: system_doc
title: Vault Structure – Human-First Orientation (Mimer)
trust: asserted
review_state: reviewed
---

# Vault Structure (Mimer)

This document defines the **intended meaning and usage** of the root folders in the vault (Mimer).
The vault is the **human-facing knowledge surface** of the Yggdrasil system.

The purpose of this structure is to:
- enable fast manual navigation, even without knowing exact names
- enable fast, low-friction capture (“where should this go?”)
- reflect human cognitive orientation, not system internals
- remain stable even as metadata, policies, and agents evolve

Folders express **orientation and context**, not state, type, or truth.

---

## Design Principles

- Folder placement must be understandable without reading system documentation
- Folders must not encode workflow state (active, reviewed, archived, etc.)
- Metadata (Core-6, state axes, policies) defines behavior — folders define orientation
- It must always be acceptable to place something quickly, imperfectly, and refine later

If unsure where something belongs, **Inbox is always correct**.

---

## Root Folders

### 📥 Inbox

**Purpose:**  
Immediate capture with zero decision cost.

**Contains:**  
- raw notes
- quick thoughts
- links
- dumped ideas
- newly imported material

**Mental rule:**  
> “I have something. I don’t want to think. Put it here.”

Nothing is required to stay here forever, but nothing is forbidden from entering.

---

### 🛠️ Workbench

**Purpose:**  
Active work and experimentation.

**Contains:**  
- work-in-progress notes
- drafts
- sketches
- analyses under construction
- experimental material

**Mental rule:**  
> “I am actively working on this.”

Workbench may be messy. That is intentional.

---

### 🔍 Focus

**Purpose:**  
Cognitive attention and current importance.

**Contains:**  
- active questions
- decisions in progress
- investigations
- topics occupying mental bandwidth right now

**Mental rule:**  
> “This is in my head right now.”

Focus is about **attention**, not volume or task tracking.

---

### 📁 Projects

**Purpose:**  
Time-bounded efforts with a goal or outcome.

**Contains:**  
- projects with a defined start and expected end
- contextual material related to “getting something done”
- project-specific notes, decisions, and references

**Mental rule:**  
> “This is something that should become finished.”

Projects are containers of context, not task engines.

---

### 🧩 Areas

**Purpose:**  
Long-lived domains of responsibility or interest.

**Contains:**  
- hobbies
- role-playing campaigns and worldbuilding
- long-term interests
- personal domains without a defined end

**Examples:**  
- Roleplaying
- Home automation
- Philosophy
- Health
- Creative writing

**Mental rule:**  
> “This is a part of my life, not a project.”

Areas persist over time and may spawn multiple projects.

---

### 💡 Knowledge

**Purpose:**  
Understanding, thinking, and synthesis.

**Contains:**  
- concepts
- mental models
- explanations
- evergreen notes
- synthesized understanding

**Mental rule:**  
> “I keep this to understand the world better.”

Knowledge is not time-bound and not owned by any single project or area.

---

### 🗂️ Reference

**Purpose:**  
Lookup and support material.

**Contains:**  
- instructions
- checklists
- manuals
- policies
- factual material meant to be consulted, not worked on

**Mental rule:**  
> “I want to be able to look this up.”

Reference material should be stable and low-change.

---

### 🗄️ Archive

**Purpose:**  
Completed or parked material.

**Contains:**  
- finished projects
- closed focus topics
- historical material
- things no longer relevant to current work or attention

**Mental rule:**  
> “This is done or not relevant right now.”

Archive removes cognitive noise without deleting knowledge.

---

### ⚙️ System

**Purpose:**  
System configuration and governance.

**Contains:**  
- system documentation
- policies
- settings
- templates
- automation notes
- architectural descriptions

**Mental rule:**  
> “This is about how the system works.”

System content is not part of domain knowledge.

---

## Important Notes

- Folder placement does **not** define truth, review status, or priority
- Notes may move between folders over time without changing identity
- Agents may suggest moves, but folder placement remains a human choice
- If metadata is missing or incomplete, the folder structure must still work

This structure reflects current intent and may evolve.
Any changes should preserve the core principle: **human-first orientation**.
