"""Read-only pinned-image cutover readiness preflight.

The guard reports whether a channel has the inputs needed for the
pinned-image cutover without mutating Docker, files, git refs, or database
state. Live-host execution belongs to the operator cutover window; tests
exercise this module with fixtures and injected command runners.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.release_channels.reversibility import FORWARD_ONLY, classify_migration
from app.release_channels.reversibility import MigrationMarkerError

CHANNELS = frozenset({"dev", "test", "prod"})
CHANNEL_COMPOSE_OVERLAYS = {
    "dev": "docker-compose.dev.yml",
    "test": "docker-compose.test.yml",
    "prod": "docker-compose.prod.yml",
}
CHANNEL_PROJECTS = {
    "dev": "pkm-dev",
    "test": "pkm-test",
    "prod": "pkm-prod",
}
RECREATE_SERVICES = (
    "api",
    "worker",
    "watcher",
    "heimdal-capture-watch",
    "companion-ui",
)
REQUIRED_CONTAINER_ENV_KEYS = (
    "HEIMDAL_RAW_READ_ALLOWLIST",
    "EMBED_PROFILE",
    "COMPANION_TRUSTED_PROXY_HOSTS",
)
DEFAULT_IMAGE_REPOSITORY = "ghcr.io/rasmustho/pkm-app"
DEFAULT_PROMOTION_REF = "origin/main"

CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        return f"{status}  {self.name}: {self.detail}"


@dataclass(frozen=True)
class MigrationInfo:
    revision: str
    down_revisions: tuple[str, ...]
    filename: str
    path: Path


@dataclass(frozen=True)
class CutoverReadinessResult:
    channel: str
    target_sha: str
    checks: tuple[ReadinessCheck, ...]
    pending_migrations: tuple[str, ...] = ()
    pending_forward_only_migrations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def summary(self) -> str:
        heading = (
            f"cutover-readiness: {'PASS' if self.ok else 'FAIL'} "
            f"channel={self.channel} target={self.target_sha}"
        )
        return "\n".join([heading, *(check.line() for check in self.checks)])


@dataclass(frozen=True)
class _GitPinResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class _ImageResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class _ComposeModel:
    services: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _MigrationDelta:
    pending: tuple[MigrationInfo, ...] = ()
    forward_only: tuple[MigrationInfo, ...] = ()
    head_revision: str | None = None


def _default_runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def _make_compose_loader() -> type[yaml.SafeLoader]:
    class _ComposeLoader(yaml.SafeLoader):
        pass

    def _passthrough(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _ComposeLoader.add_constructor("!override", _passthrough)
    _ComposeLoader.add_constructor("!reset", _passthrough)
    return _ComposeLoader


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_make_compose_loader()) or {}


def _load_compose_model(root: Path, overlay_name: str) -> _ComposeModel:
    services: dict[str, dict[str, Any]] = {}
    for path in (root / "docker-compose.yaml", root / overlay_name):
        for name, service in (_load_yaml(path).get("services") or {}).items():
            existing = dict(services.get(name, {}))
            services[name] = _merge_service(existing, service or {})
    return _ComposeModel(services=services)


def _merge_service(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key == "environment":
            env = _normalize_environment(merged.get("environment"))
            env.update(_normalize_environment(value))
            merged[key] = env
        elif key == "env_file":
            existing = _as_list(merged.get("env_file"))
            merged[key] = [*existing, *_as_list(value)]
        else:
            merged[key] = value
    return merged


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _normalize_environment(value: Any) -> dict[str, Any]:
    """Normalize Compose mapping/list environment forms into a key mapping."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, list):
        env: dict[str, Any] = {}
        for item in value:
            key, sep, item_value = str(item).partition("=")
            key = key.strip()
            if not key:
                continue
            env[key] = item_value if sep else None
        return env
    return {}


def _parse_env_file_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return keys
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


_VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _interpolate_path(expr: str, environ: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default") or ""
        return environ.get(name, default)

    return _VAR_PATTERN.sub(replace, expr)


def _env_file_path(root: Path, entry: Any, environ: Mapping[str, str]) -> Path | None:
    if isinstance(entry, str):
        raw = entry
    elif isinstance(entry, Mapping):
        raw = str(entry.get("path") or "")
    else:
        return None
    if not raw:
        return None
    interpolated = _interpolate_path(raw, environ)
    path = Path(interpolated)
    return path if path.is_absolute() else root / path


def _environment_keys(value: Any) -> set[str]:
    return set(_normalize_environment(value))


def _declared_channel_env_keys(
    root: Path,
    model: _ComposeModel,
    channel: str,
    environ: Mapping[str, str],
) -> set[str]:
    keys: set[str] = set()
    for service_name in RECREATE_SERVICES:
        service = model.services.get(service_name) or {}
        keys.update(_environment_keys(service.get("environment")))
        for entry in _as_list(service.get("env_file")):
            path = _env_file_path(root, entry, environ)
            if path is not None:
                keys.update(_parse_env_file_keys(path))
    keys.update(_parse_env_file_keys(root / "config" / "deploy" / f"{channel}.env"))
    return keys


def _check_env_completeness(
    root: Path,
    model: _ComposeModel,
    channel: str,
    environ: Mapping[str, str],
) -> ReadinessCheck:
    declared = _declared_channel_env_keys(root, model, channel, environ)
    missing = [key for key in REQUIRED_CONTAINER_ENV_KEYS if key not in declared]
    if missing:
        return ReadinessCheck(
            "env-completeness",
            False,
            "missing required env key(s): " + ", ".join(missing),
        )
    return ReadinessCheck(
        "env-completeness",
        True,
        "required containerized-model env keys are declared",
    )


def _check_recreate_set(model: _ComposeModel) -> ReadinessCheck:
    missing = [service for service in RECREATE_SERVICES if service not in model.services]
    if missing:
        return ReadinessCheck(
            "recreate-set",
            False,
            "missing recreate service(s): " + ", ".join(missing),
        )
    return ReadinessCheck(
        "recreate-set",
        True,
        "api/worker/watcher/heimdal-capture-watch/companion-ui all declared",
    )


def _parse_deploy_pin(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key, sep, value = stripped.partition("=")
            if key == "APP_IMAGE_TAG" and sep:
                return value.strip()
    return None


def _normalize_sha_tag(value: str) -> str:
    """Return the SHA-like tag portion of a deploy pin or image reference."""
    tag = value.strip().lower()
    if ":" in tag:
        tag = tag.rsplit(":", 1)[1]
    return tag


def _sha_tags_match(pinned_tag: str, target_sha: str) -> bool:
    pinned = _normalize_sha_tag(pinned_tag)
    target = _normalize_sha_tag(target_sha)
    if not (
        re.fullmatch(r"[0-9a-f]{7,40}", pinned)
        and re.fullmatch(r"[0-9a-f]{7,40}", target)
    ):
        return False
    if pinned == target:
        return True
    longer, shorter = (pinned, target) if len(pinned) > len(target) else (target, pinned)
    return len(shorter) >= 7 and longer.startswith(shorter)


def _check_pin_sanity(
    root: Path,
    channel: str,
    target_sha: str,
    promotion_ref: str,
    runner: CommandRunner,
) -> ReadinessCheck:
    pin_path = root / "config" / "deploy" / f"{channel}.env"
    try:
        pinned_tag = _parse_deploy_pin(pin_path)
    except OSError as exc:
        return ReadinessCheck("pin-sanity", False, f"{pin_path} cannot be read: {exc}")
    if not pinned_tag:
        return ReadinessCheck("pin-sanity", False, f"{pin_path} is missing APP_IMAGE_TAG")
    normalized_pin = _normalize_sha_tag(pinned_tag)
    normalized_target = _normalize_sha_tag(target_sha)
    if not re.fullmatch(r"[0-9a-f]{7,40}", normalized_pin):
        return ReadinessCheck("pin-sanity", False, "APP_IMAGE_TAG is not a git SHA-shaped tag")
    if not _sha_tags_match(normalized_pin, normalized_target):
        return ReadinessCheck(
            "pin-sanity",
            False,
            f"deploy pin mismatch: APP_IMAGE_TAG={normalized_pin} target-sha={normalized_target}",
        )

    git_result = _git_target_reachable(root, target_sha, promotion_ref, runner)
    if not git_result.ok:
        return ReadinessCheck("pin-sanity", False, git_result.detail)
    return ReadinessCheck(
        "pin-sanity",
        True,
        f"deploy pin parses; target commit is reachable from {promotion_ref}",
    )


def _git_target_reachable(
    root: Path,
    target_sha: str,
    promotion_ref: str,
    runner: CommandRunner,
) -> _GitPinResult:
    exists = runner(["git", "cat-file", "-e", f"{target_sha}^{{commit}}"], root)
    if exists.returncode != 0:
        return _GitPinResult(False, f"target SHA is not a git commit: {target_sha}")
    reachable = runner(["git", "merge-base", "--is-ancestor", target_sha, promotion_ref], root)
    if reachable.returncode != 0:
        return _GitPinResult(
            False,
            f"target SHA {target_sha} is not reachable from promotion ref {promotion_ref}",
        )
    return _GitPinResult(True, "target reachable")


def _check_image_availability(
    root: Path,
    image_repository: str,
    target_sha: str,
    runner: CommandRunner,
) -> ReadinessCheck:
    tag = f"{image_repository}:{target_sha}"
    image_result = _image_available(root, tag, runner)
    return ReadinessCheck("image-availability", image_result.ok, image_result.detail)


def _image_available(root: Path, tag: str, runner: CommandRunner) -> _ImageResult:
    local = runner(["docker", "image", "inspect", tag], root)
    if local.returncode == 0:
        return _ImageResult(True, f"{tag} exists locally")
    remote = runner(["docker", "manifest", "inspect", tag], root)
    if remote.returncode == 0:
        return _ImageResult(True, f"{tag} has a readable registry manifest")
    return _ImageResult(False, f"{tag} is not available locally or via registry manifest")


_REVISION_ASSIGN_RE = re.compile(
    r"^(?P<name>revision|down_revision)\s*(?::[^=]+)?=\s*(?P<value>.+)$",
    re.MULTILINE,
)


def _literal_assignment(text: str, name: str) -> object | None:
    for match in _REVISION_ASSIGN_RE.finditer(text):
        if match.group("name") != name:
            continue
        value_text = match.group("value").strip()
        try:
            value = ast.literal_eval(value_text)
        except (SyntaxError, ValueError):
            return None
        return value
    return None


def _revision_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _load_migrations(migrations_dir: Path) -> dict[str, MigrationInfo]:
    migrations: dict[str, MigrationInfo] = {}
    for path in sorted(migrations_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = _literal_assignment(text, "revision")
        if not revision:
            continue
        migrations[revision] = MigrationInfo(
            revision=revision,
            down_revisions=_revision_tuple(_literal_assignment(text, "down_revision")),
            filename=path.name,
            path=path,
        )
    return migrations


def _head_revision(migrations: Mapping[str, MigrationInfo]) -> str | None:
    down_revisions = {
        down_revision
        for info in migrations.values()
        for down_revision in info.down_revisions
    }
    heads = sorted(set(migrations) - down_revisions)
    return heads[-1] if heads else None


def _path_from_revision_to_head(
    migrations: Mapping[str, MigrationInfo],
    *,
    current: str | None,
    db_revision: str | None,
    seen: frozenset[str] = frozenset(),
) -> list[MigrationInfo] | None:
    if current is None:
        return [] if db_revision is None else None
    if current == db_revision:
        return []
    if current in seen:
        return None
    info = migrations.get(current)
    if info is None:
        return None

    next_seen = seen | {current}
    for parent in info.down_revisions or (None,):
        parent_path = _path_from_revision_to_head(
            migrations,
            current=parent,
            db_revision=db_revision,
            seen=next_seen,
        )
        if parent_path is not None:
            return [*parent_path, info]
    return None


def _pending_migration_delta(migrations_dir: Path, db_revision: str | None) -> _MigrationDelta:
    migrations = _load_migrations(migrations_dir)
    head = _head_revision(migrations)
    if head is None:
        return _MigrationDelta(head_revision=None)

    pending = _path_from_revision_to_head(
        migrations,
        current=head,
        db_revision=db_revision,
    )
    if pending is None:
        pending = []

    forward_only = [
        info for info in pending if classify_migration(info.path).classification == FORWARD_ONLY
    ]
    return _MigrationDelta(
        pending=tuple(pending),
        forward_only=tuple(forward_only),
        head_revision=head,
    )


def _resolve_db_revision(root: Path, runner: CommandRunner) -> str | None:
    env_revision = os.environ.get("CUTOVER_DB_REVISION")
    if env_revision:
        return env_revision
    completed = runner(["alembic", "-c", "alembic.ini", "current"], root)
    if completed.returncode != 0:
        return None
    for token in completed.stdout.replace("(", " ").replace(")", " ").split():
        if re.fullmatch(r"[0-9A-Za-z_]+", token):
            return token
    return None


def _check_migration_state(
    root: Path,
    db_revision: str | None,
    ack_forward_only: bool,
) -> tuple[ReadinessCheck, _MigrationDelta]:
    if db_revision is None:
        return (
            ReadinessCheck(
                "migration-state",
                False,
                "DB revision unavailable; pass --db-revision or CUTOVER_DB_REVISION",
            ),
            _MigrationDelta(),
        )

    try:
        delta = _pending_migration_delta(root / "app" / "alembic" / "versions", db_revision)
    except MigrationMarkerError as exc:
        return ReadinessCheck("migration-state", False, str(exc)), _MigrationDelta()
    if not delta.pending:
        return (
            ReadinessCheck(
                "migration-state",
                True,
                f"DB revision {db_revision} is at alembic head {delta.head_revision}",
            ),
            delta,
        )

    pending_names = ", ".join(info.filename for info in delta.pending)
    forward_only_names = ", ".join(info.filename for info in delta.forward_only)
    if delta.forward_only and not ack_forward_only:
        return (
            ReadinessCheck(
                "migration-state",
                False,
                "pending forward-only migration(s) require operator ack: "
                + forward_only_names,
            ),
            delta,
        )
    detail = f"pending migration(s): {pending_names}"
    if delta.forward_only:
        detail += f"; forward-only acked: {forward_only_names}"
    return ReadinessCheck("migration-state", True, detail), delta


def check_cutover_readiness(
    channel: str,
    target_sha: str,
    *,
    root: Path | str = Path("."),
    db_revision: str | None = None,
    ack_forward_only: bool = False,
    image_repository: str = DEFAULT_IMAGE_REPOSITORY,
    promotion_ref: str = DEFAULT_PROMOTION_REF,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner = _default_runner,
    check_image: bool = True,
) -> CutoverReadinessResult:
    if channel not in CHANNELS:
        raise ValueError(f"unsupported channel {channel!r}; expected one of {sorted(CHANNELS)}")
    root_path = Path(root)
    env = os.environ if environ is None else environ
    model = _load_compose_model(root_path, CHANNEL_COMPOSE_OVERLAYS[channel])

    checks: list[ReadinessCheck] = []
    checks.append(_check_pin_sanity(root_path, channel, target_sha, promotion_ref, runner))
    if check_image:
        checks.append(_check_image_availability(root_path, image_repository, target_sha, runner))
    checks.append(_check_env_completeness(root_path, model, channel, env))
    checks.append(_check_recreate_set(model))
    migration_check, migration_delta = _check_migration_state(
        root_path,
        db_revision if db_revision is not None else _resolve_db_revision(root_path, runner),
        ack_forward_only,
    )
    checks.append(migration_check)

    return CutoverReadinessResult(
        channel=channel,
        target_sha=target_sha,
        checks=tuple(checks),
        pending_migrations=tuple(info.filename for info in migration_delta.pending),
        pending_forward_only_migrations=tuple(
            info.filename for info in migration_delta.forward_only
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.cutover_readiness",
        description="Read-only pinned-image cutover readiness preflight.",
    )
    parser.add_argument("channel", choices=sorted(CHANNELS))
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--db-revision")
    parser.add_argument("--ack-forward-only", action="store_true")
    parser.add_argument("--image-repository", default=DEFAULT_IMAGE_REPOSITORY)
    parser.add_argument("--promotion-ref", default=DEFAULT_PROMOTION_REF)
    parser.add_argument(
        "--skip-image-check",
        action="store_true",
        help="Skip Docker image/manifest inspection for offline fixture runs.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = check_cutover_readiness(
        args.channel,
        args.target_sha,
        db_revision=args.db_revision,
        ack_forward_only=args.ack_forward_only,
        image_repository=args.image_repository,
        promotion_ref=args.promotion_ref,
        check_image=not args.skip_image_check,
    )
    stream = sys.stdout if result.ok else sys.stderr
    print(result.summary(), file=stream)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
