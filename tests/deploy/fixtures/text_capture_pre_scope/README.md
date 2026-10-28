# Pre-scope text-capture sources

These frozen public sources come byte-for-byte from commit
`d4004fbb3bab42ac9068d65494a22edf05c5c96e`. The legacy-image refusal tests copy them into their
isolated deployment harness. Keeping the source bytes here makes the tests work in
shallow, offline checkouts while retaining the real pre-scope implementation.

The `.fixture` suffix keeps this historical test data outside Python module discovery.
The corresponding original repository path is the filename without that suffix.

| Original path | SHA-256 |
| --- | --- |
| `app/ops/native_source_bootstrap.py` | `ffc5f58c8ab1ac664423ecff9da2c9213bc0f109bf101309537e8a3c40ed21f1` |
| `app/api/app.py` | `c9e5f1ddb86c1110d6bd69a58fd38c397d1e20279fe61d73572091ceeef5fce7` |
| `scripts/start_api.sh` | `cb1b5655de5f1120f1710844ec76108721e193d8135ffdc9e44973be676f20e9` |

To verify the provenance in a full-history authoring checkout, compare each fixture
with `git show <commit>:<original-path>`. Running the tests does not need Git history.
