"""Knowledge Acquisition Platform — Phase 2 vertical slice (KA-01).

This package holds the `youtube_url` source plugin's `fetch` operation and the
immutable `raw` record persistence it produces, per
`docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` and
`docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md`.

Scope is deliberately narrow (KA-01 only): the plugin fetch operation plus raw-record
persistence and dedup trace. No pipeline stages, no vault writes, no discovery.
"""

from __future__ import annotations
