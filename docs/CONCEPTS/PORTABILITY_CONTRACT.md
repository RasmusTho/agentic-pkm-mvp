State: Concept contract (cross-platform portability; macOS + Windows).

# Portability Contract — macOS + Windows

## Purpose

Portability protects three things:
- **Data durability**: canonical artifacts remain readable and valid across machines and operating systems.
- **Human comprehensibility**: central human-facing artifacts remain understandable even if the current runtime or stack changes.
- **Rebuildability**: derived artifacts (indexes, caches, projections) can be discarded and rebuilt without loss of meaning.
- **Predictable behavior**: the same logical inputs produce the same logical outcomes, independent of OS defaults.

This contract applies to all user data and system artifacts that must survive cross-device use, backups, and future upgrades.
Not every supporting structure must be equally system-independent, but central human artifacts must remain the most portable and intelligible surfaces.

## What counts as a central human artifact

A central human artifact is a human-facing artifact that is intended to carry durable meaning for the
user in directly understandable form.

It is defined by function, not by implementation detail.

An artifact counts as central when it is expected to:
- remain readable and meaningful to the human without reconstructing hidden runtime state,
- carry meaning the human may rely on over time,
- and continue to make sense even if supporting metadata or system modules change.

Typical examples:
- vault notes used as primary thinking/writing surfaces,
- durable project or commitment notes the human relies on directly,
- reflective artifacts the human revisits as records of understanding or review,
- and other human-authored or human-facing artifacts intended to remain directly usable over time.

Things that are usually **not** central human artifacts:
- mirrors,
- indexes,
- embeddings,
- projections,
- machine-side connection graphs,
- caches,
- and other support structures whose purpose is to aid the system rather than to remain a primary
  meaning surface for the human.

Some artifacts may be important without being central in this specific sense.
The contract claim here is narrower:
- central human artifacts must remain directly intelligible,
- supporting structures may evolve more freely as long as they remain derivative or rebuildable.

## Contract Rules (must hold)

1) **Central human artifacts remain directly comprehensible.** Canonical human-facing artifacts must not require the current system's runtime, hidden metadata, or derived structures in order to make basic sense to the user.
2) **Derived support structures may be less portable, but never authoritative.** Metadata, indexes, projections, and machine-side connection structures may be more system-specific as long as they remain non-authoritative or rebuildable and do not become the only place where core meaning lives.
3) **No OS-specific assumptions in canonical artifacts.** Canonical artifacts must not depend on OS-specific path syntax, filesystem semantics, or locale defaults to be interpreted correctly.
4) **Portable identity beats location.** Stable identity and provenance must not be derived solely from filesystem location; location may change across OSes and machines.
5) **Portable paths are OS-neutral.** When a path-like reference is necessary, it must use a canonical “portable path” representation: relative to an agreed root, normalized, and independent of OS-specific prefixes.
6) **Normalization is explicit and consistent.** Any normalization applied to portable paths (segment handling, separators, reserved names/characters) must be consistent across platforms and treated as part of the contract, not an emergent behavior.
7) **Case collisions are portability hazards.** Names that differ only by case (or case-folding) must be treated as ambiguous and unsafe; the system must avoid creating them and must handle existing collisions conservatively.
8) **Unicode must not create “ghost duplicates”.** Visually identical or canonically equivalent strings must not silently diverge across OSes; the system must treat Unicode normalization differences as collision risks and preserve meaning across platforms.
9) **Newlines are not semantics.** Line-ending differences must not change meaning or identity; conversions must not create churn, duplication, or false “changes”.
10) **Encoding is portable by default.** Canonical text must use a portable encoding; unexpected encodings must degrade safely and predictably without corrupting source material.
11) **Determinism over OS defaults.** Derived ordering, grouping, and summaries must not depend on OS-dependent ordering, filesystem traversal order, locale collation, or timestamp resolution.
12) **Correctness must not rely on one OS feature.** Monitoring, sync, and change-detection surfaces must tolerate OS differences; correctness is preserved through idempotence and re-runnable flows, even when OS facilities differ in availability or behavior.
13) **Portability is a stability gate.** Any change that would make artifacts invalid, ambiguous, lossy, or no longer meaningfully understandable on either macOS or Windows is considered a contract violation.

## Tensions / examples (conceptual failure modes)

- Two artifacts differ only by case, and one OS collapses them into a single file identity.
- Unicode normalization causes the “same” name to appear as two distinct names across filesystems.
- Absolute or machine-specific path fragments leak into a canonical artifact, breaking portability and backups.
- Line-ending or encoding conversions create false diffs, duplicate identities, or corrupted excerpts.
- Archive imports include names or characters valid on one OS but not on another, forcing lossy renames or silent drops.
