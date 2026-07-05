"""Shared, cross-cutting proposal-emitting substrate (Cognitive Expansion).

Currently home to the declined-proposal ledger (EXP-2, #2995). Per the
repo's cross-cutting-decomposition principle, a mechanism that must hold an
invariant across N call sites (every proposal-emitting pass: Connect, G2
curation, later E8 contradiction) gets its own package rather than living
inside any single consumer.
"""
from __future__ import annotations
