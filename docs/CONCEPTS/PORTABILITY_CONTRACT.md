State: Concept contract (cross-platform portability; macOS + Windows).

# Portability Contract — macOS + Windows

## Purpose

Portability protects three things:
- **Data durability**: canonical artifacts remain readable and valid across machines and operating systems.
- **Rebuildability**: derived artifacts (indexes, caches, projections) can be discarded and rebuilt without loss of meaning.
- **Predictable behavior**: the same logical inputs produce the same logical outcomes, independent of OS defaults.

This contract applies to all user data and system artifacts that must survive cross-device use, backups, and future upgrades.

## Contract Rules (must hold)

1) **No OS-specific assumptions in canonical artifacts.** Canonical artifacts must not depend on OS-specific path syntax, filesystem semantics, or locale defaults to be interpreted correctly.
2) **Portable identity beats location.** Stable identity and provenance must not be derived solely from filesystem location; location may change across OSes and machines.
3) **Portable paths are OS-neutral.** When a path-like reference is necessary, it must use a canonical “portable path” representation: relative to an agreed root, normalized, and independent of OS-specific prefixes.
4) **Normalization is explicit and consistent.** Any normalization applied to portable paths (segment handling, separators, reserved names/characters) must be consistent across platforms and treated as part of the contract, not an emergent behavior.
5) **Case collisions are portability hazards.** Names that differ only by case (or case-folding) must be treated as ambiguous and unsafe; the system must avoid creating them and must handle existing collisions conservatively.
6) **Unicode must not create “ghost duplicates”.** Visually identical or canonically equivalent strings must not silently diverge across OSes; the system must treat Unicode normalization differences as collision risks and preserve meaning across platforms.
7) **Newlines are not semantics.** Line-ending differences must not change meaning or identity; conversions must not create churn, duplication, or false “changes”.
8) **Encoding is portable by default.** Canonical text must use a portable encoding; unexpected encodings must degrade safely and predictably without corrupting source material.
9) **Determinism over OS defaults.** Derived ordering, grouping, and summaries must not depend on OS-dependent ordering, filesystem traversal order, locale collation, or timestamp resolution.
10) **Correctness must not rely on one OS feature.** Monitoring, sync, and change-detection surfaces must tolerate OS differences; correctness is preserved through idempotence and re-runnable flows, even when OS facilities differ in availability or behavior.
11) **Portability is a stability gate.** Any change that would make artifacts invalid, ambiguous, or lossy on either macOS or Windows is considered a contract violation.

## Tensions / examples (conceptual failure modes)

- Two artifacts differ only by case, and one OS collapses them into a single file identity.
- Unicode normalization causes the “same” name to appear as two distinct names across filesystems.
- Absolute or machine-specific path fragments leak into a canonical artifact, breaking portability and backups.
- Line-ending or encoding conversions create false diffs, duplicate identities, or corrupted excerpts.
- Archive imports include names or characters valid on one OS but not on another, forcing lossy renames or silent drops.

