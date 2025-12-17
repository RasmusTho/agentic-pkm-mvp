State: Concept contract (configuration is user-facing, validated, versioned, portable; implementation-agnostic).

# Config-as-Product Contract — safe, portable configuration

## Purpose

Configuration is not a hidden developer knob-set; it is a user-facing product surface.

This contract ensures configuration is:
- **Safe by default** (human-first; no surprise automation).
- **Validated and predictable** (bad config degrades safely).
- **Auditable and reversible** (changes leave receipts and can be rolled back).
- **Portable** across machines and operating systems.

This composes with `docs/CONCEPTS/PORTABILITY_CONTRACT.md` and `docs/CONCEPTS/LAYERING_MODEL.md`.

## Precedence (high level)

Configuration is layered. Precedence is:
1) **Repo defaults** (the baseline shipped with the project).
2) **System config** (local/user-provided configuration files for a specific installation).
3) **Environment/session overrides** (explicit overrides for a run or environment).

Higher-precedence layers may override lower ones, but must not violate safety contracts (Domain/Plane/Trust boundaries).

## Validation + safety posture

Validation exists to protect the human experience.

Rules:
- **Degrade gracefully by default.** Invalid or unknown settings must not brick the system; they fall back to safe defaults with a clear warning.
- **Fail closed on boundary risk.** If a configuration would relax boundary guarantees (cross-domain exposure, durable writes without intent, trust laundering), the system must refuse that behavior and fall back to the safest behavior.
- **Unknown is not permission.** Unknown keys are ignored (or quarantined) and must not change behavior.
- **Explicitness over inference for dangerous knobs.** Any setting that increases automation or reduces friction must be explicit, scoped, and auditable.

## Rollback and disable strategy

Configuration must be easy to recover from:
- **Invalid config ⇒ safe fallback.** The system continues in a safe default mode and records that a fallback occurred.
- **Feature disable is always available.** For risky or surprising behavior, the system must support disabling the feature without editing unrelated configuration.
- **No silent partial application.** If only part of a configuration is valid, the system must clearly state what was applied vs ignored.

## Audit requirements (receipts for config)

Config changes and effective configuration must be auditable.

At minimum, record:
- **What changed** (old vs new values) and **where it came from** (defaults vs system config vs environment override).
- **Who/what initiated** the change (human vs automation acting under explicit human intent).
- **When** the change took effect and **what scope** it applies to.
- **Validation outcome** (accepted, rejected, partially applied, fell back to defaults) and why.
- **Boundary impact summary** (whether it affects exposure, suggestions, or durable writes).

## Portability rules

Configuration artifacts must follow the portability constraints:
- Portable, text-based representations where possible.
- Stable semantics across OSes (paths, encoding, case, Unicode normalization).
- No reliance on OS-specific defaults to interpret meaning.

See `docs/CONCEPTS/PORTABILITY_CONTRACT.md` for the portability hazard model.
