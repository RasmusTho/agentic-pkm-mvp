# Data Governance & Provenance — SoT v4.2

## Core Principles
- **Human-first:** Data serves cognition, not storage.
- **Traceable:** Every write carries a trace_id.
- **Reversible:** Nothing is mutated without audit trail.
- **Trust-aware:** Provenance and confidence guide promotion.
- **Transparent:** Every object has provenance, maturity, and trust metadata.

## Provenance Fields
| Field | Description |
|--------|-------------|
| origin | Original file path or source reference |
| trust | Confidence score from agents (0–1) |
| maturity | State from seed → note → evergreen |
| evidence_level | Factual confidence from evidence |
| source_ref | External reference (URL, repo, etc.) |
| review_state | Pending, approved, rejected |

## Promotion Logic
Reviewer blocks promotion when:
- trust < 0.7  
- missing_citations = true  
- maturity rule not satisfied

## Retention
Retention rules (from retention.yaml):
- Transient: purge after 30–90 days
- Golden: never auto-deleted
- Archival: compressed, read-only

## Separation of Trust
| Source | Trust Range | Review Required |
|---------|--------------|----------------|
| Authored (human) | 0.8–1.0 | No |
| Imported (known source) | 0.6–0.9 | Yes |
| AI-generated | 0.4–0.7 | Yes |
| Unknown | 0–0.5 | Discard |
