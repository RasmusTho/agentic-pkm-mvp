from __future__ import annotations

# Keep the top-level package import side-effect free.  Standalone BuilderOps
# entrypoints import ``app.builderops`` from the same source tree as Product;
# importing the namespace must not resolve Product's LLM policy, vault, or
# service graph.  Product boot owns its own explicit policy preflight in
# ``app.api.app``.
