"""Guard the committed enablement path of the cockpit live GitHub plane (#4484).

The `github-live` source is opt-in: `app/api/routes/cockpit.py :: _github_repo`
returns `None` unless `COCKPIT_GITHUB_REPO` is set, and `fetch_github_live`
refuses before the transport is reached. Until #4484 no committed configuration
set that key for any channel, so the plane's own stated acceptance form
(`docs/BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md :: Concretely` — a `fresh`
source at `localhost:18001/api/cockpit/registry`) was not executable anywhere.

This file asserts the committed side of that path:

1. the dev channel (the 18001 acceptance form) binds the repo slug on the
   `api` service, which is the service that serves the cockpit route;
2. the token key the plane needs is documented on the `api` consumer's
   already-declared host-secret env layer, which is how a value reaches that
   container without a new secret mechanism or compose surface; and
3. the other channels stay unset, so the opt-in posture (and #4481's
   opted-out-vs-broken distinction) still holds where nobody asked for it.
"""

from __future__ import annotations

from pathlib import Path

from app.release_channels.channel_isolation_preflight import _load_compose

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_COMPOSE = _REPO_ROOT / "docker-compose.yaml"
_DEV_COMPOSE = _REPO_ROOT / "docker-compose.dev.yml"
_OPTED_OUT_COMPOSE = (
    _REPO_ROOT / "docker-compose.test.yml",
    _REPO_ROOT / "docker-compose.prod.yml",
)

_REPO_SLUG = "RasmusTho/agentic-pkm-mvp"
_TOKEN_KEY = "GITHUB_TOKEN"
_HOST_SECRET_HANDLE = "HOST_SECRET_RUNTIME_ENV_FILE_API"


def _services(path: Path) -> dict:
    # `_load_compose` tolerates compose's `!override` / `!reset` merge tags,
    # which plain `yaml.safe_load` rejects in the channel overlays.
    return _load_compose(path)["services"]


def test_api_service_receives_cockpit_repo_and_token_key() -> None:
    dev_api = _services(_DEV_COMPOSE)["api"]
    assert dev_api["environment"]["COCKPIT_GITHUB_REPO"] == _REPO_SLUG, (
        "the dev channel's api service must bind COCKPIT_GITHUB_REPO — it is "
        "the channel whose port (18001) is the live plane's stated acceptance "
        "form (docs/BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md :: Concretely)"
    )

    # The token rides the api consumer's already-declared host-secret layer;
    # this issue adds no new secret plumbing, so the committed artifact is the
    # documented key name on that layer, next to the key it already delivers.
    base_api = _services(_BASE_COMPOSE)["api"]
    host_secret_layers = [
        entry
        for entry in base_api["env_file"]
        if isinstance(entry, dict) and _HOST_SECRET_HANDLE in str(entry.get("path", ""))
    ]
    assert len(host_secret_layers) == 1, (
        f"the api service must keep exactly one {_HOST_SECRET_HANDLE} env_file "
        "layer (#4422); #4484 reuses it rather than adding a surface"
    )

    base_text = _BASE_COMPOSE.read_text(encoding="utf-8")
    layer_comment = base_text[: base_text.index(f"${{{_HOST_SECRET_HANDLE}")]
    layer_comment = layer_comment[layer_comment.rindex("# Governed host-secret") :]
    assert "HEIMDAL_RAW_STORE_KEY" in layer_comment, (
        "guard assumption: the layer's existing key is documented in its own "
        "comment block, which is where the new key must be documented too"
    )
    assert _TOKEN_KEY in layer_comment, (
        f"the api host-secret layer must document {_TOKEN_KEY} as the key the "
        "cockpit live GitHub plane's gh transport reads (#4484), alongside the "
        "key that layer already delivers"
    )


def test_other_channels_stay_opted_out_of_the_live_plane() -> None:
    """The plane stays opt-in: only the enabled channel binds the slug.

    With `COCKPIT_GITHUB_REPO` unset a channel's behavior is byte-identical to
    the pre-#4484 refusal, and the source renders *not enabled* rather than
    broken (EXT-8, #4481).
    """
    for path in _OPTED_OUT_COMPOSE:
        api = _services(path).get("api", {})
        assert "COCKPIT_GITHUB_REPO" not in (api.get("environment") or {}), (
            f"{path.name} must not bind COCKPIT_GITHUB_REPO: turning a channel "
            "onto the live plane is an operational act owned by the promotion "
            "lane, not a side effect of making enablement possible (#4484)"
        )
