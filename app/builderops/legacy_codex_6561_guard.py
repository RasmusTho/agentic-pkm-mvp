"""Bounded, read-only reconciliation of #6561 Codex observations.

``check`` reads scoped sources and an authenticated operator comment, without creating a
fence or granting transfer/publication authority. Callers must prevent new
starts and apply all existing recovery gates. The #6637 preboot-only timing
rule cannot validate this postboot inventory; integration must not falsify it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Iterator

from app.builderops import legacy_owner_recovery
from scripts import agent_worktree, codex_session_relations

CHILD = "01a19b1d-7671-7f43-a053-77db65ac7dfb"
PR = 6562
GENERATION = "c98ea60e6e0d4592b08d1ce05e5517b3"
OWNER = "issue6561-normal-transport-20261102"
HOLDER = "codex-issue6561-normal-transport"
LEASE = "lease-a0019077"
BOOT = datetime(2026, 11, 14, 21, 48, 30, tzinfo=timezone.utc)
INVENTORY_START = datetime(2026, 11, 15, 7, 55, tzinfo=timezone.utc)
PARENT_COMPLETED = datetime(2026, 11, 15, 8, 16, tzinfo=timezone.utc)
PARENT_COVERED = datetime(2026, 11, 15, 10, 15, 58, tzinfo=timezone.utc)
PUBLICATION_COMMANDS = frozenset({
    "exec-5866e18d-5e33-4b13-93ea-b853148159c3",
    "exec-ebb0369f-aee6-4936-946e-aff4045ce844",
    "exec-f1807f6f-4da9-49a9-aa28-d6fa230f4e94",
    "exec-bffb5005-ee7f-4d46-b4ba-dfae71574981",
    "exec-d79126fc-968a-47e6-aaed-89a64b7ae500",
})
COMMENTS = frozenset({6572276588, 6574147023})
PUBLICATION_HASHES = {
    "exec-5866e18d-5e33-4b13-93ea-b853148159c3": "3c92bdafed682498f151208bdb43a24b0ac3a17bf9fed6562d21047d1825219e",
    "exec-ebb0369f-aee6-4936-946e-aff4045ce844": "17d9f87427ae45580d8564bafe9cf29d3c2b186810254724052f443b3c33f823",
    "exec-f1807f6f-4da9-49a9-aa28-d6fa230f4e94": "8d854bd34cf67c3be176275fa07a0460e8cbc6ac203ae7a4ffaa5810f8c8c7a2",
    "exec-bffb5005-ee7f-4d46-b4ba-dfae71574981": "ef2006b05889892cf2a59f8222ce234b3c94e54ecd9048c954363901f582e92f",
    "exec-d79126fc-968a-47e6-aaed-89a64b7ae500": "c5fa5704759e9d1507e7fa6a8d1db67de20decdba85478967e84385307b35bc3",
}


class GuardRefused(ValueError):
    """A specifically identified source or its outcome is unknown."""


def _aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


# Narrow native readback. A successful result is only a scoped observation, not
# a lock or permission to mutate; callers must recheck at every effect boundary.
PARENT = "01a18113-fbc7-79e1-813f-bb54a5f7d59c"
TURN = "01a1de33-fb6d-7881-9cda-5c260846b6d2"
PARENT_TURN = "01a1de33-affb-7732-a4d5-c4a7938c9a17"
WORKTREE = str(Path.home() / ".codex/worktrees/issue-6561-normal-host-transport-20261102/agentic-pkm-mvp")
BRANCH = "codex/issue-6561-normal-host-transport-20261102"
HEAD = "bc72cf1ad68d5daaef3b7f145030abdd249df23f"
BODY = "ed5320a06a190916e2a7864ddca3b340701789ac2ade8711fb0506d1ce8ced49"
CHILD_JOURNAL = Path.home() / ".codex/sessions/2026/11/02/rollout-2026-11-02T08-16-01-01a19b1d-7671-7f43-a053-77db65ac7dfb.jsonl"
PARENT_JOURNAL = Path.home() / ".codex/sessions/2026/10/28/rollout-2026-10-28T06-55-32-01a18113-fbc7-79e1-813f-bb54a5f7d59c.jsonl"
STATE_DB = Path.home() / ".codex/state_5.sqlite"
INVENTORY_COMMANDS = {
    "exec-2870c60a-f8a0-4218-9cce-34ca930f6835": (20851, "e3737e98b09d8b75b4e0d421964983c2c3ccbba677626985b1ac71550d8f2194"),
    "exec-5cb42423-f955-4826-8a6c-bbd4de1652d2": (42059, "53e578ebaa372436b2d5ab821138aa39ae2c5f34f5e7cf3166ae6f432b5968f6"),
    "exec-1cbf68bb-9a21-4058-b874-80b6d779ea30": (29664, "029e916bf1655626603df01179a539705849f2923e6cdb0fedae84611f77ad3d"),
    "exec-f8137fd4-b717-4d99-ab28-7a064d8e453d": (95088, "e17f582e6952170f6b0e1ee87379ad426dff7a35acdafd127bbdedfdf5524ef3"),
    "exec-5460e1ee-a398-4a91-9dd1-bbc1a409f6c2": (85984, "3f20f3c00bd4318786f9beebec0d83887e7eb670e544af60e02a74bd8c78bc0f"),
    "exec-7fad215e-c536-4979-afc2-8831e896948b": (69238, "d99e53846ce8917d4e933afe67034843521594d9fce996a6793b571775393350"),
    "exec-4d0c789b-088a-47c0-8f87-8a374b983ce2": (99988, "f0847573dc52674d32d7952e280745a8deb3fd8dc65594ddfe7421920cdd9bb4"),
    "exec-58b6ce9a-3a20-451c-b984-2e810f15b35d": (37745, "bbd9fe0606121875208511bbae7b0c51291f9c467f4347ee83276fe8791e9076"),
}
INVENTORY_MCP = {
    "exec-f061ddad-a308-44a0-8fef-0518005f1bd8": "github.fetch_issue",
    "exec-6ff3270e-644c-4c41-867a-0cc7373ba256": "github.fetch_issue_comments",
    "exec-722cb119-eee1-455b-985c-a6b9f6e1f34e": "github.get_pr_info",
    "exec-1a3841e0-2687-4a85-8e62-3d627bfd6cf2": "github.get_commit_combined_status",
    "exec-27a0f673-b33a-44ca-a5cc-246b74f6f3e7": "github.list_pull_request_reviews",
    "exec-99f190be-087f-4cd7-a226-be613c48deb2": "github.fetch_issue",
    "exec-f0dd3123-4521-4bd4-ac33-5c8df2c13b66": "github.fetch_issue_comments",
}
INVENTORY_CALLS = {
    "call_019fa24585f7437e8bb973a1627c8d51": ("exec", "cbcaca95c431df0f8231b7f1594f8287e9251ce9b94a9d8164193776f370f12e"),
    "call_1ff05e65c1644fe7926a3f49fc7e4e78": ("exec", "68282a9a540c6e55f42f0370332ad9dc311c4be0501bf2799f05546e41869c63"),
    "call_03193d1cfac944b6b4b03a48276a342e": ("exec", "a710b85a216c242e518d2d60765881d401ad42b039f5017ddc92b3228fc83328"),
    "call_91e2f31fc0c94e74883dd9e9847a569b": ("list_agents", "c89a148be40e6752261e3038609a4b68de22fa3bfdaf32f884edffb8480b9bbe"),
    "call_417b1e012ee04b68bb30fa5b42b12ee5": ("exec", "008e928bee1ff079fa468a3ce23810b9b3596fcbb65e71419c4f4146c9371e38"),
    "call_1a59b98df3fe4312ab1f52ed035cfc93": ("exec", "5ad030cf0a9b8a75f4701924e19665514098634b99e0358f463178186afce81a"),
    "call_1a38472f44e246e4a1545c3b22e73147": ("exec", "756de73cddf95505ae3bf7a875067c595631b271dd31a62c302592e213601382"),
    "call_b1b3be0202224c258e3b68926d3ef479": ("send_message", "9293f0acf52abc01e50531e084f7cfa560c0df1611220ced59de7953e6e99a0b"),
}
MCP_ARGUMENT_HASHES = {
    "exec-f061ddad-a308-44a0-8fef-0518005f1bd8": "5448de0865f75029a099baf7ced9e41afdedf055d57d2fe7e4750115f8cb5c1c",
    "exec-6ff3270e-644c-4c41-867a-0cc7373ba256": "ae7ca294b99230e53b4e7ea9f662d51f7075997cefa7548f2ebfef636e4a558d",
    "exec-722cb119-eee1-455b-985c-a6b9f6e1f34e": "63bf9239aeef3ff3e31470a75b11f413da3e30464f10ad72902af4448c0e223c",
    "exec-1a3841e0-2687-4a85-8e62-3d627bfd6cf2": "f580e7e8d44c9a476b82d550f0281a1dadbb937fb2677c419ffce00186d98c18",
    "exec-27a0f673-b33a-44ca-a5cc-246b74f6f3e7": "d8898a89e67e4a1209527db40f9dcb0d580ba36387a887f3b29a45e77e7c902b",
    "exec-99f190be-087f-4cd7-a226-be613c48deb2": "a271bcd1502916a811c7cdc59aadb014d13f22c6d618d5e81b577287faf24fbd",
    "exec-f0dd3123-4521-4bd4-ac33-5c8df2c13b66": "ce315d1c636fc203c81c0caaa58fedc465e5b2ca5d26714cb0e66b1e35724348",
}
PARENT_CALLS = {
    "call_aabfaf6a32494b98ad6080273c817546": ("followup_task", "2026-11-15T07:55:11.030Z", "dfc94b0e1f921c19b6517bb44091b44f13cc2803d89982c9896caf0d088bbd00"),
    "call_b99169878cc546678633732eade9cc29": ("send_message", "2026-11-15T07:57:48.042Z", "c376f1e5fe38447e3ac3244791cbcdb4e22e49828993927e9ed530e215cb7ce8"),
    "call_aeea2d2433df49609ffb32edd61ad553": ("send_message", "2026-11-15T08:02:23.042Z", "2bfbf113200d7fc6e1e14cfe1daabea1db2b54961946438ec93efc39351bccef"),
    "call_502e1f09fb21461c9f017a9a61a4281c": ("interrupt_agent", "2026-11-15T08:03:36.531Z", "89a58a63926d758792eec0002db7e32848687ed2ccfe681a7e29ccd65d136b0e"),
}

# The separately observed later inventory did not transfer ownership. These
# identities bind only that exact child/parent chronology and its known effects.
LATER_TURN = "01a1e11d-1f3e-7f12-8d72-644bf6d7c3e6"
LATER_PARENT_TURN = "01a1e11c-e0ac-7020-aa2c-3c948275e0dd"
# This binds the preserved parent snapshot, including other target-related
# calls. It does not establish their downstream effects or a stopped delegation.
# A caller-supplied digest cannot validate an extended, unexamined prefix.
LATER_PARENT_PREFIX_BYTES = 113_921_951
LATER_PARENT_PREFIX_SHA256 = "e8187cd4b957dc98eec12002ea4f30023880d966478444fb758767b9ea1bd8bb"
LATER_COMMANDS = {
    "exec-5b76527d-fe36-452b-9468-f4f51c857dc8": (75210, "73d7f91678d09e28c0569f254c0a163826f631701d0ea81c009783f6556fda55"),
    "exec-8cba6500-040a-4b07-b953-6a14149646ae": (5308, "d63c7a21cf0bd2d69ef12a3e27c57746d323400d7f64702c5b21c5cbf05b6d96"),
    "exec-62dd00fb-b475-4c3a-aaf9-27a2167b6136": (98766, "91816b0f81b2cc58cca0ab64be7fa26d1805eccb59364b0baf9beabd8013b02e"),
    "exec-37332db3-9ecd-4b07-9dde-7bb8c00308a6": (34415, "1dc49cc8e6b6a61c1266a55e7b68a7d71ccce9f6026aae3a105c8a888b740d91"),
    "exec-4f7cdf6f-edae-47ba-8542-f33c137073c1": (99896, "bdce7df2862a20899c93b2661c2edf01f85d5d2a13c7761939d5f04e5e2c4536"),
    "exec-20f75295-9588-4b2c-b74d-03f0951f67ef": (38424, "0e6dba0d1742eb0b51793f7484dfa46853256b6f73903e11ea22601ddf7c739a"),
}
LATER_CALLS = {
    "call_43f18ca9a462410d88ad2f727f44fbce": ("send_message", "e172060ac0cf2c30dad170ecb8a085ceeea5680e8d478caf44a737c4327ca815", "12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126"),
    "call_8bd0eebdd3cd4cfe8b5d8c52037e2a31": ("exec", "c3262bd56f69c069aa7327a214877e5c56cd385ccfa64202a813bebf8ac86425", "7a359824c10b7f65850043208e4dc0f85d2caecd3a7c6782d47acaf1d8d6cebb"),
    "call_6580877fde24499ba3e926fdae777bfe": ("exec", "9dd225e9432d356fbcca569353ae7c40e60ce74ac698542314dbd40a1a8d1eb8", "10287010058a9d8b063d37ade6514fcdd3ec51f4aa3488a3a92aa14efdb2fac5"),
    "call_0026f4a866de432d8d6928199ecb29ee": ("send_message", "1244a5187e40eaad910c6a1575042284becd088262d5364dac891890aa3fe48a", "12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126"),
    "call_1a44d2585f0f476390abf3ee58f8cf15": ("exec", "8bb816a16e957bb0b877051e2c913cfe1f4c3c483d2e80c626f178006ad9af57", "91b826ee0b697b8d7ccd344bbf37a5df14ddf87540eed928375337f609ee834a"),
    "call_383be8bf8a2b471f94a127ee1719981d": ("exec", "8fc8c7c2606a803444c0c5d4ec54b7770ce31c21b9f9575ffd6d907b86cf3d65", "84bff8c7f02252ac0ccd17bbe1020bc3d5499fa4aecd9da4cf9a07ef8c4cb8e5"),
}
LATER_MCP = {
    "exec-a55c1e2b-7866-4017-996d-6c519f27fe47": ("github.fetch_commit_workflow_runs", "f580e7e8d44c9a476b82d550f0281a1dadbb937fb2677c419ffce00186d98c18"),
    "exec-ce0a0129-5fb8-47c3-928f-c4e4879e03a3": ("github.fetch_issue_comments", "5b01857b9ecb67616362726b444aac8d5e3f009c010f5b7e04f445cc936e58a4"),
    "exec-c6e6d78e-474f-4f2b-bd18-3be8fac0f4c1": ("github.fetch_issue", "5448de0865f75029a099baf7ced9e41afdedf055d57d2fe7e4750115f8cb5c1c"),
    "exec-cf132233-2882-491a-a200-3603b130760e": ("github.get_pr_info", "63bf9239aeef3ff3e31470a75b11f413da3e30464f10ad72902af4448c0e223c"),
}
LATER_EXEC_ITEMS = {
    "call_8bd0eebdd3cd4cfe8b5d8c52037e2a31": (
        "exec-5b76527d-fe36-452b-9468-f4f51c857dc8", "exec-a55c1e2b-7866-4017-996d-6c519f27fe47",
        "exec-8cba6500-040a-4b07-b953-6a14149646ae"),
    "call_6580877fde24499ba3e926fdae777bfe": (
        "exec-62dd00fb-b475-4c3a-aaf9-27a2167b6136", "exec-ce0a0129-5fb8-47c3-928f-c4e4879e03a3"),
    "call_1a44d2585f0f476390abf3ee58f8cf15": (
        "exec-37332db3-9ecd-4b07-9dde-7bb8c00308a6", "exec-4f7cdf6f-edae-47ba-8542-f33c137073c1",
        "exec-c6e6d78e-474f-4f2b-bd18-3be8fac0f4c1", "exec-cf132233-2882-491a-a200-3603b130760e"),
    "call_383be8bf8a2b471f94a127ee1719981d": ("exec-20f75295-9588-4b2c-b74d-03f0951f67ef",),
}
LATER_PARENT_CALLS = {
    "call_ec19063d697e4834b48f94798d0143d7": ("followup_task", "2026-11-15T21:29:04.528Z", "fb3338488c8ed0cd4ba7e45dddcaa6bbceb3708b21364892920be2641daeb6e2"),
    "call_0898c98eb3214d43932225d115ee75d9": ("send_message", "2026-11-15T21:30:28.662Z", "9eded963151b495e701341881b58f17ffc9a1fc08367ee56292026bc4ebaaf56"),
    "call_6a0e3b32fcfb47ff9d22ccda7e56f2d4": ("send_message", "2026-11-15T21:33:44.834Z", "a69517d43af878334fb49a1a2f4b83c18bb915e0e74fcf581994a3c681e44819"),
    "call_61cfe322c42a4b5ca331bfc420127d0c": ("send_message", "2026-11-15T21:35:22.677Z", "9c0c40cf675e8fc49cbc22f7c11b31db2aa9a8d5e52219fadeee9c852533a9a2"),
    "call_24383eceb3b24154b372c41be9d8fbae": ("send_message", "2026-11-15T21:37:38.204Z", "04ef9b64d3ae637740f0d34f663eb26f4885fc58b0e3c2ab337a83988a13b751"),
}
LATER_LOCAL_FILES = {
    ".codex-tmp/issue-6561/handoff-process-readback-20261115.json": "80147de49443dc55309fe76d00056777435498feab613b933f6eb80966593130",
    ".codex-tmp/issue-6561/handoff-process-current-20261115.json": "8193254e36fbb1d1dbe8558f7e3826671ef6ce3f3a6d09fb55ef46edf616c7e0",
    ".codex-tmp/issue-6561/lifecycle-handoff-preparation-20261115.json": "f2f3089c5561608ce57e22c2e328b27e72eb4da17d7e231ee05053aa4a46959a",
}


def _read_source(path: Path, limit: int) -> tuple[bytes, str]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_mode & 0o022 or before.st_size > limit):
                raise GuardRefused("UNKNOWN: unqualified journal source")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            after = os.fstat(fd)
            named = os.lstat(path)
            if (len(data) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
                raise GuardRefused("UNKNOWN: journal changed during read")
        finally:
            os.close(fd)
    except OSError as exc:
        raise GuardRefused("UNKNOWN: journal source unavailable") from exc
    return data, hashlib.sha256(data).hexdigest()


def _events(data: bytes) -> Iterator[dict[str, Any]]:
    try:
        for line in io.BytesIO(data):
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                raise ValueError("journal shape")
            yield row
    except (ValueError, UnicodeError) as exc:
        raise GuardRefused("UNKNOWN: malformed journal") from exc


def _strict_json(data: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError("invalid JSON number")

    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)


def _parent_checkpoint(data: bytes, *, length: int, digest: str, observed: datetime) -> bytes:
    """Verify the attested prefix and allow only contiguous token-accounting records.

    The checkpoint is an offset at a complete JSONL boundary, not permission to
    ignore subsequent journal records. Every suffix event is inspected. Unknown
    activity, partial records, ordinal gaps and pre-checkpoint drift fail closed.
    """
    if type(length) is not int or length <= 0 or length > len(data) or data[length - 1:length] != b"\n":
        raise GuardRefused("UNKNOWN: parent checkpoint boundary is invalid")
    prefix, suffix = data[:length], data[length:]
    if hashlib.sha256(prefix).hexdigest() != digest:
        raise GuardRefused("UNKNOWN: parent checkpoint changed since operator observation")
    if suffix and not suffix.endswith(b"\n"):
        raise GuardRefused("UNKNOWN: parent journal tail is incomplete")
    # The fixed prefix is also checked semantically by _journal_check below.
    last_line = prefix.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    try:
        last = _strict_json(last_line)
        ordinal = last["ordinal"]
        timestamp = datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
        if (type(ordinal) is not int or ordinal < 0 or not _aware(timestamp)
                or not PARENT_COVERED <= timestamp <= observed):
            raise ValueError("parent checkpoint time or ordinal")
        for line in io.BytesIO(suffix):
            row = _strict_json(line)
            if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                raise ValueError("invalid parent tail shape")
            ordinal += 1
            payload = row["payload"]
            token_count = (row.get("type") == "event_msg" and payload.get("type") == "token_count"
                           and set(payload) == {"type", "info", "rate_limits"})
            usage_fields = {"thread_id", "turn_id", "session_id", "root_turn_id", "response_id",
                            "usage", "turn_token_usage", "thread_token_usage"}
            token_usage = (row.get("type") == "token_usage_record" and set(payload) == usage_fields
                           and payload.get("thread_id") == PARENT and payload.get("session_id") == PARENT
                           and all(isinstance(payload.get(k), str) and payload[k]
                                   for k in ("turn_id", "root_turn_id", "response_id"))
                           and all(isinstance(payload.get(k), dict)
                                   for k in ("usage", "turn_token_usage", "thread_token_usage")))
            if (set(row) != {"ordinal", "timestamp", "type", "payload"}
                    or type(row["ordinal"]) is not int or row["ordinal"] != ordinal
                    or not (token_count or token_usage) or not isinstance(row["timestamp"], str)):
                raise ValueError("unrecognized parent tail")
            tail_time = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if not _aware(tail_time) or tail_time < timestamp or tail_time > datetime.now(timezone.utc):
                raise ValueError("invalid parent tail timing")
            timestamp = tail_time
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if isinstance(exc, GuardRefused):
            raise
        raise GuardRefused("UNKNOWN: parent checkpoint or later activity is unverified") from exc
    return prefix


def _journal_timestamp(row: dict[str, Any]) -> datetime:
    """Read one timestamp without rounding away the interruption boundary."""
    try:
        raw = row.get("timestamp")
        if not isinstance(raw, str):
            raise ValueError("missing journal timestamp")
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not _aware(value):
            raise ValueError("naive journal timestamp")
        return value
    except (TypeError, ValueError, OverflowError) as exc:
        raise GuardRefused("UNKNOWN: journal timing is unavailable") from exc


def _later_child_check(rows: list[dict[str, Any]], *, abort_index: int) -> tuple[datetime, datetime]:
    """Validate only the identified subsequent inventory, including its outputs."""
    starts = [i for i, row in enumerate(rows) if row.get("type") == "event_msg"
              and row["payload"].get("type") == "task_started" and row["payload"].get("turn_id") == LATER_TURN]
    contexts = [i for i, row in enumerate(rows) if row.get("type") == "turn_context"
                and row["payload"].get("turn_id") == LATER_TURN]
    ends = [i for i, row in enumerate(rows) if row.get("type") == "event_msg"
            and row["payload"].get("type") == "task_complete" and row["payload"].get("turn_id") == LATER_TURN]
    if (len(starts) != 1 or len(contexts) != 1 or len(ends) != 1
            or not abort_index < starts[0] < contexts[0] < ends[0]):
        raise GuardRefused("UNKNOWN: later child turn boundary changed")
    start, end = starts[0], ends[0]
    times = [_journal_timestamp(row) for row in rows[start:end + 1]]
    if (times[0] != datetime.fromisoformat("2026-11-15T21:29:04.582+00:00")
            or times[-1] != datetime.fromisoformat("2026-11-15T21:38:55.138+00:00")
            or _journal_timestamp(rows[abort_index]) > times[0]
            or any(left > right for left, right in zip(times, times[1:]))):
        raise GuardRefused("UNKNOWN: later child chronology changed")
    calls: dict[str, tuple[str, str]] = {}
    outputs: dict[str, tuple[str, str]] = {}
    commands: dict[str, dict[str, Any]] = {}
    mcps: dict[str, dict[str, Any]] = {}
    interactions: set[str] = set()
    call_positions: dict[str, int] = {}
    output_positions: dict[str, int] = {}
    item_positions: dict[str, int] = {}
    for offset, row in enumerate(rows[start:end + 1], start=start):
        p = row["payload"]
        if (row.get("type") not in {"event_msg", "turn_context", "inter_agent_communication_metadata",
                                    "response_item", "token_usage_record"}
                or (row.get("type") == "event_msg" and p.get("type") not in
                    {"task_started", "task_complete", "item_completed", "token_count"})
                or (row.get("type") == "response_item" and p.get("type") not in
                    {"agent_message", "custom_tool_call", "custom_tool_call_output", "function_call",
                     "function_call_output", "message", "reasoning"})):
            raise GuardRefused("UNKNOWN: later child journal record is unrecognized")
        if ((p.get("type") in {"task_started", "task_complete", "turn_aborted"} and offset not in {start, end})
                or (row.get("type") == "turn_context" and p.get("turn_id") != LATER_TURN)):
            raise GuardRefused("UNKNOWN: unexpected child turn boundary")
        if row.get("type") == "response_item" and p.get("type") in {"function_call", "custom_tool_call"}:
            identity, name = p.get("call_id"), p.get("name")
            if not isinstance(identity, str) or identity in calls:
                raise GuardRefused("UNKNOWN: later child call is ambiguous")
            arg = p.get("input") if p["type"] == "custom_tool_call" else p.get("arguments")
            calls[identity] = (str(name), hashlib.sha256(
                json.dumps(arg, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
            call_positions[identity] = offset
        if row.get("type") == "response_item" and p.get("type") in {"function_call_output", "custom_tool_call_output"}:
            identity = p.get("call_id")
            if not isinstance(identity, str) or identity in outputs:
                raise GuardRefused("UNKNOWN: later child output is ambiguous")
            outputs[identity] = (str(p["type"]), hashlib.sha256(
                json.dumps(p.get("output"), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest())
            output_positions[identity] = offset
        item = p.get("item")
        if p.get("type") == "item_completed" and not isinstance(item, dict):
            raise GuardRefused("UNKNOWN: later child item is unavailable")
        if not isinstance(item, dict):
            continue
        if (p.get("type") != "item_completed" or p.get("thread_id") != CHILD
                or p.get("turn_id") != LATER_TURN):
            raise GuardRefused("UNKNOWN: later child item identity changed")
        identity, kind = item.get("id"), item.get("type")
        if kind not in {"Reasoning", "AgentMessage", "CommandExecution", "McpToolCall", "SubAgentActivity"}:
            raise GuardRefused("UNKNOWN: later child item is unrecognized")
        if kind in {"CommandExecution", "McpToolCall"}:
            target = commands if kind == "CommandExecution" else mcps
            if not isinstance(identity, str) or identity in target:
                raise GuardRefused("UNKNOWN: later child item is ambiguous")
            target[identity] = item
            item_positions[identity] = offset
        elif kind == "SubAgentActivity":
            if (not isinstance(identity, str) or identity in interactions or item.get("kind") != "interacted"
                    or item.get("agent_thread_id") != PARENT):
                raise GuardRefused("UNKNOWN: later child interaction changed")
            interactions.add(identity)
            item_positions[identity] = offset
    if (calls != {identity: (value[0], value[1]) for identity, value in LATER_CALLS.items()}
            or list(calls) != list(LATER_CALLS)
            or outputs != {identity: ("custom_tool_call_output" if value[0] == "exec" else "function_call_output",
                                      value[2]) for identity, value in LATER_CALLS.items()}
            or interactions != {identity for identity, value in LATER_CALLS.items() if value[0] == "send_message"}
            or set(commands) != set(LATER_COMMANDS) or set(mcps) != set(LATER_MCP)):
        raise GuardRefused("UNKNOWN: later child inventory is incomplete or changed")
    ordered_calls = list(calls)
    if (any(call_positions[identity] >= output_positions[identity] for identity in calls)
            or any(output_positions[left] >= call_positions[right] for left, right in zip(ordered_calls, ordered_calls[1:]))
            or any(not any(name == "exec" and call_positions[call] < position < output_positions[call]
                           for call, (name, _) in calls.items())
                   for identity, position in item_positions.items() if identity in commands or identity in mcps)
            or any(not call_positions[identity] < item_positions[identity] < output_positions[identity]
                   for identity in interactions)):
        raise GuardRefused("UNKNOWN: later child call and completion order changed")
    for call, expected_items in LATER_EXEC_ITEMS.items():
        observed_items = tuple(identity for identity, position in sorted(item_positions.items(), key=lambda entry: entry[1])
                               if identity in commands or identity in mcps
                               if call_positions[call] < position < output_positions[call])
        if observed_items != expected_items:
            raise GuardRefused("UNKNOWN: later exec item sequence changed")
    for identity, item in commands.items():
        pid, digest = LATER_COMMANDS[identity]
        command = json.dumps(item.get("command"), ensure_ascii=False, separators=(",", ":")).encode()
        if (str(item.get("process_id")) != str(pid) or item.get("status") != "completed"
                or type(item.get("exit_code")) is not int or item["exit_code"] != 0
                or hashlib.sha256(command).hexdigest() != digest):
            raise GuardRefused("UNKNOWN: later child command changed or is nonterminal")
    for identity, item in mcps.items():
        tool, digest = LATER_MCP[identity]
        args = json.dumps(item.get("arguments"), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        result = item.get("result")
        if (item.get("server") != "codex_apps" or item.get("tool") != tool or item.get("status") != "completed"
                or item.get("readOnlyHint") is not True or not isinstance(result, dict)
                or result.get("isError") is not False or hashlib.sha256(args).hexdigest() != digest):
            raise GuardRefused("UNKNOWN: later child GitHub read changed or is nonterminal")
    for row in rows[end + 1:]:
        p = row["payload"]
        if (p.get("turn_id") in {TURN, LATER_TURN} or (isinstance(p.get("item"), dict) and p.get("thread_id") == CHILD)
                or p.get("type") in {"task_started", "task_complete", "turn_aborted"}
                or (row.get("type") == "response_item"
                and p.get("type") in {"function_call", "custom_tool_call"})):
            raise GuardRefused("UNKNOWN: child activity follows the later inventory")
    return times[0], times[-1]


def _journal_check(child: bytes, parent: bytes) -> datetime:
    rows = list(_events(child))
    meta = [r["payload"] for r in rows if r.get("type") == "session_meta"]
    turns = [r["payload"].get("turn_id") for r in rows if r.get("type") == "turn_context"]
    if (len(meta) != 1 or meta[0].get("id") != CHILD or turns.count(TURN) != 1
            or turns[turns.index(TURN):] not in ([TURN], [TURN, LATER_TURN])):
        raise GuardRefused("UNKNOWN: child identity or subsequent turn")
    has_later = turns[-1] == LATER_TURN
    context = next(r for r in rows if r.get("type") == "turn_context" and r["payload"].get("turn_id") == TURN)
    if not str(context.get("timestamp", "")).startswith("2026-11-15T07:55:"):
        raise GuardRefused("UNKNOWN: postboot turn timing")
    inventory: dict[str, dict[str, Any]] = {}
    mcps: dict[str, dict[str, Any]] = {}
    publications: dict[str, dict[str, Any]] = {}
    abort = []
    active_turn = False
    calls_seen: dict[str, tuple[str, str]] = {}
    for row in rows:
        payload = row["payload"]
        if row.get("type") == "turn_context":
            active_turn = payload.get("turn_id") == TURN
        if active_turn and row.get("type") == "response_item":
            kind, name = payload.get("type"), payload.get("name")
            if kind in {"function_call", "custom_tool_call"}:
                identity = payload.get("call_id")
                if not isinstance(identity, str) or identity in calls_seen:
                    raise GuardRefused("UNKNOWN: duplicate inventory call")
                arg = payload.get("input") if kind == "custom_tool_call" else payload.get("arguments")
                digest = hashlib.sha256(json.dumps(arg, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                calls_seen[identity] = (str(name), digest)
        if payload.get("type") == "turn_aborted" and payload.get("turn_id") == TURN:
            abort.append(row)
        item = payload.get("item")
        if not isinstance(item, dict):
            continue
        identity = item.get("id")
        if identity in PUBLICATION_COMMANDS:
            if (payload.get("type") != "item_completed" or payload.get("thread_id") != CHILD
                    or payload.get("turn_id") != "01a19b1d-76b9-71c2-8d4c-edc8a0c5e0ce"):
                raise GuardRefused("UNKNOWN: publication event identity mismatch")
            if identity in publications:
                raise GuardRefused("UNKNOWN: duplicate publication item")
            publications[identity] = item
        if payload.get("turn_id") != TURN:
            continue
        if payload.get("type") != "item_completed" or payload.get("thread_id") != CHILD:
            raise GuardRefused("UNKNOWN: inventory event identity mismatch")
        if item.get("type") not in {"Reasoning", "AgentMessage", "CommandExecution", "McpToolCall", "SubAgentActivity"}:
            raise GuardRefused("UNKNOWN: unrecognized inventory activity")
        if item.get("type") == "CommandExecution":
            if identity in inventory:
                raise GuardRefused("UNKNOWN: duplicate inventory item")
            inventory[identity] = item
        elif item.get("type") == "McpToolCall":
            if identity in mcps:
                raise GuardRefused("UNKNOWN: duplicate inventory tool")
            mcps[identity] = item
        elif item.get("type") == "SubAgentActivity" and (item.get("kind") != "interacted" or item.get("agent_thread_id") != PARENT):
            raise GuardRefused("UNKNOWN: inventory delegation")
    if (len(abort) != 1 or not str(abort[0].get("timestamp", "")).startswith("2026-11-15T08:03:36.")
            or set(inventory) != set(INVENTORY_COMMANDS) or set(mcps) != set(INVENTORY_MCP)
            or set(publications) != PUBLICATION_COMMANDS or calls_seen != INVENTORY_CALLS):
        raise GuardRefused("UNKNOWN: incomplete or changed journal items")
    start_index, abort_index = rows.index(context), rows.index(abort[0])
    if abort_index <= start_index:
        raise GuardRefused("UNKNOWN: journal turn ordering changed")
    times = [_journal_timestamp(row) for row in rows[start_index:abort_index + 1]]
    if any(left > right for left, right in zip(times, times[1:])):
        raise GuardRefused("UNKNOWN: journal activity timing changed")
    later_start_index = next((i for i, row in enumerate(rows) if row.get("type") == "event_msg"
                              and row["payload"].get("type") == "task_started"
                              and row["payload"].get("turn_id") == LATER_TURN), len(rows))
    for row in rows[abort_index + 1:later_start_index]:
        payload = row["payload"]
        if (payload.get("turn_id") in {TURN, LATER_TURN}
                or (isinstance(payload.get("item"), dict) and payload.get("thread_id") == CHILD)
                or payload.get("type") in {"task_started", "task_complete", "turn_aborted"}
                or (row.get("type") == "response_item"
                and payload.get("type") in {"function_call", "custom_tool_call"})):
            raise GuardRefused("UNKNOWN: journal activity follows the interrupted turn")
    aborted_at = times[-1]
    later_child = _later_child_check(rows, abort_index=abort_index) if has_later else None
    if not has_later and later_start_index != len(rows):
        raise GuardRefused("UNKNOWN: unpaired later child start")
    for identity, item in inventory.items():
        pid, command_hash = INVENTORY_COMMANDS[identity]
        command = json.dumps(item.get("command"), ensure_ascii=False, separators=(",", ":")).encode()
        if (str(item.get("process_id")) != str(pid) or item.get("status") != "completed"
                or type(item.get("exit_code")) is not int or item["exit_code"] != 0
                or hashlib.sha256(command).hexdigest() != command_hash):
            raise GuardRefused("UNKNOWN: inventory command changed or nonterminal")
    if any(item.get("server") != "codex_apps" or item.get("tool") != INVENTORY_MCP[identity]
           or item.get("status") != "completed"
           or hashlib.sha256(json.dumps(item.get("arguments"), sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest() != MCP_ARGUMENT_HASHES[identity]
           for identity, item in mcps.items()):
        raise GuardRefused("UNKNOWN: inventory MCP changed or nonterminal")
    if any(item.get("type") != "CommandExecution" or item.get("status") != "completed"
           or type(item.get("exit_code")) is not int or item["exit_code"] != 0
           or hashlib.sha256(json.dumps(item.get("command"), ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest() != PUBLICATION_HASHES[identity]
           for identity, item in publications.items()):
        raise GuardRefused("UNKNOWN: publication command nonterminal")
    try:
        patch_output = publications["exec-d79126fc-968a-47e6-aaed-89a64b7ae500"].get("aggregated_output")
        if not isinstance(patch_output, str):
            raise ValueError("missing final patch readback")
        patch, _ = json.JSONDecoder().raw_decode(patch_output.lstrip())
        if (not isinstance(patch, dict) or patch.get("pr") != PR or patch.get("head") != HEAD
                or patch.get("body_sha256") != BODY or patch.get("state") != "open"):
            raise ValueError("final patch readback changed")
    except (KeyError, ValueError, TypeError) as exc:
        raise GuardRefused("UNKNOWN: final PATCH body readback is unavailable") from exc
    calls: dict[str, tuple[str, str, str]] = {}
    completed = []
    later_parent_started = []
    later_parent_completed = []
    parent_meta = []
    for row in _events(parent):
        if row.get("type") == "session_meta":
            parent_meta.append(row["payload"])
        p = row["payload"]
        if p.get("type") == "task_complete" and p.get("turn_id") == PARENT_TURN:
            completed.append(row)
        if p.get("type") == "task_started" and p.get("turn_id") == LATER_PARENT_TURN:
            later_parent_started.append(row)
        if p.get("type") == "task_complete" and p.get("turn_id") == LATER_PARENT_TURN:
            later_parent_completed.append(row)
        if row.get("type") == "response_item" and p.get("type") == "function_call":
            args = str(p.get("arguments", ""))
            if row.get("timestamp", "") >= "2026-11-15T07:55" and (CHILD in args or "issue6561_normal_transport" in args):
                if p.get("name") in {"followup_task", "send_message", "interrupt_agent", "spawn_agent"}:
                    identity = p.get("call_id")
                    if identity in calls:
                        raise GuardRefused("UNKNOWN: duplicate parent call")
                    arg_hash = hashlib.sha256(json.dumps(p.get("arguments"), ensure_ascii=False,
                                                          separators=(",", ":")).encode()).hexdigest()
                    calls[identity] = (str(p.get("name")), str(row.get("timestamp")), arg_hash)
    expected_parent_calls = PARENT_CALLS | LATER_PARENT_CALLS if has_later else PARENT_CALLS
    if (len(parent_meta) != 1 or parent_meta[0].get("id") != PARENT
            or calls != expected_parent_calls or list(calls) != list(expected_parent_calls) or len(completed) != 1
            or not str(completed[0].get("timestamp", "")).startswith("2026-11-15T08:16:")):
        raise GuardRefused("UNKNOWN: parent activity or completion changed")
    interrupt_times = [_journal_timestamp({"timestamp": at}) for name, at, _ in calls.values()
                       if name == "interrupt_agent"]
    if (len(interrupt_times) != 1 or not interrupt_times[0] <= aborted_at
            <= _journal_timestamp(completed[0])):
        raise GuardRefused("UNKNOWN: interruption and completion ordering changed")
    if has_later:
        if later_child is None or len(later_parent_started) != 1 or len(later_parent_completed) != 1:
            raise GuardRefused("UNKNOWN: later parent boundary changed")
        _parent_checkpoint(parent, length=LATER_PARENT_PREFIX_BYTES, digest=LATER_PARENT_PREFIX_SHA256,
                           observed=datetime.now(timezone.utc))
        parent_start = _journal_timestamp(later_parent_started[0])
        parent_end = _journal_timestamp(later_parent_completed[0])
        followup = [_journal_timestamp({"timestamp": at}) for name, at, _ in LATER_PARENT_CALLS.values()
                    if name == "followup_task"]
        parent_times = [_journal_timestamp({"timestamp": at}) for _, at, _ in LATER_PARENT_CALLS.values()]
        if (len(followup) != 1 or not parent_start <= followup[0] <= later_child[0] <= later_child[1] <= parent_end
                or any(not parent_start <= value <= parent_end for value in parent_times)
                or parent_end != datetime.fromisoformat("2026-11-15T21:39:26.072+00:00")):
            raise GuardRefused("UNKNOWN: later child and parent ordering changed")
        return parent_end
    if later_parent_started or later_parent_completed:
        raise GuardRefused("UNKNOWN: unpaired later parent activity")
    return aborted_at


def _check_operator_relations(evidence: dict[str, Any], *, observed: datetime,
                              last_activity: datetime) -> dict[str, Any]:
    """Bind an operator's stopped-window observation to a fresh target snapshot."""
    relation = evidence.get("relations")
    keys = {"source", "source_tables", "read_method", "parent", "child", "child_rollout", "parent_rollout",
            "child_thread_source", "parent_edge_count", "child_thread_count", "parent_thread_count",
            "registered_children", "observation_complete", "observed_at",
            "coordination_started_at", "coordination"}
    if (not isinstance(relation, dict) or set(relation) != keys
            or relation.get("source") != str(STATE_DB)
            or relation.get("source_tables") != ["threads", "thread_spawn_edges"]
            or relation.get("read_method") != "sqlite_readonly_consistent_transaction"
            or relation.get("child_thread_source") != "subagent"
            or any(type(relation.get(k)) is not int or relation[k] != 1
                   for k in ("parent_edge_count", "child_thread_count", "parent_thread_count"))
            or relation.get("parent") != PARENT or relation.get("child") != CHILD
            or relation.get("child_rollout") != str(CHILD_JOURNAL)
            or relation.get("parent_rollout") != str(PARENT_JOURNAL)
            or relation.get("registered_children") != [] or relation.get("observation_complete") is not True
            or relation.get("coordination") != "no_new_manual_starts_until_transition_complete"):
        raise GuardRefused("UNKNOWN: operator relation observation is missing or ambiguous")
    try:
        started = datetime.fromisoformat(relation["coordination_started_at"].replace("Z", "+00:00"))
        relation_time = datetime.fromisoformat(relation["observed_at"].replace("Z", "+00:00"))
        if (not _aware(started) or not _aware(relation_time)
                or not last_activity <= started <= relation_time <= observed):
            raise ValueError("relation observation outside stopped window")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise GuardRefused("UNKNOWN: operator relation timing invalid") from exc
    expected = {k: relation[k] for k in ("source", "parent", "child", "child_rollout", "parent_rollout",
                                         "child_thread_source", "registered_children")}
    _check_fresh_relations(expected)
    return expected


def _check_fresh_relations(expected: dict[str, Any]) -> None:
    try:
        actual = codex_session_relations.read_6561()
    except codex_session_relations.RelationsUnavailable as exc:
        raise GuardRefused("UNKNOWN: Codex relation source unavailable") from exc
    if actual != expected:
        raise GuardRefused("UNKNOWN: Codex target relations changed since operator observation")


def _run_readback(*args: str, allow_no_crontab: bool = False) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardRefused("UNKNOWN: scoped host readback unavailable") from exc
    if result.returncode:
        if allow_no_crontab and result.returncode == 1 and "no crontab for" in result.stderr.lower():
            return ""
        raise GuardRefused("UNKNOWN: scoped host readback failed")
    if len(result.stdout) > 4_000_000:
        raise GuardRefused("UNKNOWN: scoped host readback too large")
    return result.stdout


def _boot() -> int:
    raw = _run_readback("/usr/sbin/sysctl", "-n", "kern.boottime")
    match = re.search(r"\bsec\s*=\s*(\d+)", raw)
    if match is None:
        raise GuardRefused("UNKNOWN: host boot unavailable")
    return int(match.group(1))


def _check_host() -> None:
    """Inspect identified PIDs and named targets, not every possible writer."""
    if _boot() != int(BOOT.timestamp()):
        raise GuardRefused("UNKNOWN: boot changed from reconciled postboot inventory")
    processes = _run_readback("/bin/ps", "-axo", "pid=,ppid=,command=")
    if not processes.strip():
        raise GuardRefused("UNKNOWN: empty process readback")
    launchctl = _run_readback("/bin/launchctl", "print", f"gui/{os.getuid()}")
    crontab = _run_readback("/usr/bin/crontab", "-l", allow_no_crontab=True)
    targets = (WORKTREE, CHILD, "issue-6561-normal-host-transport", "issue6561_normal_transport")
    pids = {pid for pid, _ in (*INVENTORY_COMMANDS.values(), *LATER_COMMANDS.values())}
    own = {os.getpid(), os.getppid()}
    for line in processes.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            raise GuardRefused("UNKNOWN: malformed scoped process observation")
        pid, ppid = int(parts[0]), int(parts[1])
        if pid in pids or ppid in pids:
            raise GuardRefused("UNKNOWN: identified process or descendant is active or ambiguous")
        if pid in own:
            continue
        if any(target in parts[2] for target in targets):
            raise GuardRefused("UNKNOWN: identified process or descendant is active or ambiguous")
        if re.search(r"(?i)\bcodex\b", parts[2]):
            cwd = _run_readback("/usr/sbin/lsof", "-a", "-p", parts[0], "-d", "cwd", "-Fn")
            cwd_lines = [line[1:] for line in cwd.splitlines() if line.startswith("n")]
            if len(cwd_lines) != 1:
                raise GuardRefused("UNKNOWN: Codex process cwd unavailable")
            if cwd_lines[0] == WORKTREE or cwd_lines[0].startswith(WORKTREE + "/"):
                raise GuardRefused("UNKNOWN: Codex process owns target cwd")
    if any(target in value for target in targets for value in (launchctl, crontab)):
        raise GuardRefused("UNKNOWN: identified automatic restart target")
    if _boot() != int(BOOT.timestamp()):
        raise GuardRefused("UNKNOWN: host boot changed during readback")


def _check_later_local_files(worktree: Path) -> None:
    """Compare the three preserved local outputs to the observed snapshot.

    These point-in-time hashes do not attest a historical writer signature.
    """
    for name, expected in LATER_LOCAL_FILES.items():
        _, actual = _read_source(worktree / name, 1_000_000)
        if actual != expected:
            raise GuardRefused("UNKNOWN: later local inventory output changed")


def _read_publication(cwd: Path, expected: dict[str, Any]) -> None:
    try:
        current = legacy_owner_recovery.read_live_publication(cwd=cwd, pr=PR, branch=BRANCH)
        comparable = {k: v for k, v in expected.items() if k not in {"state", "sources"}}
        if (current.get("head") != HEAD or current.get("body_sha256") != BODY
                or {k: v for k, v in current.items() if k != "state"} != comparable):
            raise GuardRefused("UNKNOWN: #6562 publication changed since reconciliation")
        for identity in COMMENTS:
            raw = legacy_owner_recovery._github_read(
                [f"repos/RasmusTho/agentic-pkm-mvp/issues/comments/{identity}"], cwd=cwd)
            comment = json.loads(raw)
            if (not isinstance(comment, dict) or comment.get("id") != identity
                    or not isinstance(comment.get("user"), dict) or comment["user"].get("login") != "RasmusTho"
                    or comment.get("issue_url") not in {
                        "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6561",
                        "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6562"}):
                raise GuardRefused("UNKNOWN: historical GitHub comment is missing or mismatched")
    except (legacy_owner_recovery.RecoveryEvidenceError, ValueError, TypeError) as exc:
        if isinstance(exc, GuardRefused):
            raise
        raise GuardRefused("UNKNOWN: GitHub publication readback unavailable") from exc


def _check(*, cwd: Path, issue: int, pr: int, worktree: Path, session: str, comment_id: int,
           initial_publication: bool) -> dict[str, Any]:
    """Check live bounded sources against a fresh, authenticated operator comment.

    No source here is a predecessor signature, a lock, a transfer, a publication
    permit, or proof about arbitrary unregistered processes and effects. Existing
    custody, mandate, claimant and delivery gates remain mandatory. Call again
    before each effect, under the caller's existing coordination boundary.
    """
    if (issue != 6561 or pr != PR or str(worktree) != WORKTREE
            or not isinstance(session, str) or not session or type(comment_id) is not int or comment_id < 1):
        raise GuardRefused("UNKNOWN: target or successor mismatch")
    try:
        comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
        receipt, created_at, digest = agent_worktree._transfer_comment(
            comment, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1")
    except agent_worktree.WorktreeLifecycleError as exc:
        raise GuardRefused("UNKNOWN: operator comment authentication failed") from exc
    writer, candidate = receipt.get("writer"), receipt.get("candidate")
    registration, predecessor = receipt.get("registration"), receipt.get("predecessor")
    successor, publication, mandate = receipt.get("successor"), receipt.get("publication"), receipt.get("mandate")
    if (not isinstance(writer, dict) or not isinstance(candidate, dict) or not isinstance(registration, dict)
            or not isinstance(predecessor, dict) or not isinstance(successor, dict)
            or not isinstance(publication, dict) or not isinstance(mandate, dict)):
        raise GuardRefused("UNKNOWN: operator receipt lacks custody bindings")
    evidence = writer.get("codex_custody")
    if (receipt.get("mode") != "operator" or receipt.get("account") != "RasmusTho" or receipt.get("issue") != issue
            or mandate.get("repo") != "RasmusTho/agentic-pkm-mvp" or mandate.get("issue") != issue
            or mandate.get("effects") != ["reconcile", "claim", "register", "acknowledge"]
            or not isinstance(mandate.get("reference"), str) or not mandate["reference"].strip()
            or successor.get("session") != session or candidate.get("path") != WORKTREE
            or candidate.get("branch") != BRANCH or candidate.get("generation") != GENERATION
            or registration.get("owner") != OWNER
            or registration.get("path") != WORKTREE or registration.get("branch") != BRANCH
            or registration.get("generation") != candidate.get("generation")
            or predecessor.get("holder") != HOLDER
            or predecessor.get("lease_id") != LEASE
            or writer.get("state") != "stopped" or writer.get("delegations") != "stopped"
            or writer.get("restart") != "reconciled" or publication.get("state") != "reconciled"
            or not isinstance(evidence, dict)):
        raise GuardRefused("UNKNOWN: operator receipt identity or custody mismatch")
    fields = {"child_sha256", "parent_sha256", "parent_prefix_bytes", "observed_at", "no_new_manual_starts", "historical_push_output",
              "earlier_body", "historical_ppids", "unrecorded_effects", "boot", "relations"}
    if (set(evidence) not in (fields, fields | {"later_git_status_index_effect"})
            or ("later_git_status_index_effect" in evidence and evidence["later_git_status_index_effect"] != "unknown")
            or evidence.get("no_new_manual_starts") is not True
            or any(evidence.get(k) != "unknown" for k in
                   ("historical_push_output", "earlier_body", "historical_ppids", "unrecorded_effects"))
            or any(not isinstance(evidence.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", evidence[k])
                   for k in ("child_sha256", "parent_sha256"))):
        raise GuardRefused("UNKNOWN: incomplete operator source binding")
    try:
        observed = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
        boot = datetime.fromisoformat(evidence["boot"].replace("Z", "+00:00"))
        last_activity = datetime.fromisoformat(writer["last_activity"].replace("Z", "+00:00"))
        if (not _aware(observed) or not _aware(boot) or not _aware(last_activity) or boot != BOOT
                or writer.get("boot") != evidence["boot"]
                or not datetime(2026, 11, 15, 8, 3, 36, tzinfo=timezone.utc) <= last_activity <= observed
                or not PARENT_COVERED <= observed <= datetime.fromtimestamp(created_at, timezone.utc)
                or created_at > datetime.now(timezone.utc).timestamp()):
            raise ValueError("invalid observation timing")
    except (KeyError, ValueError, TypeError, OverflowError, AttributeError) as exc:
        raise GuardRefused("UNKNOWN: operator source timing invalid") from exc
    child, child_digest = _read_source(CHILD_JOURNAL, 20_000_000)
    parent, _ = _read_source(PARENT_JOURNAL, 160_000_000)
    if child_digest != evidence["child_sha256"]:
        raise GuardRefused("UNKNOWN: child journal changed since operator observation")
    parent_prefix = _parent_checkpoint(parent, length=evidence["parent_prefix_bytes"],
                                       digest=evidence["parent_sha256"], observed=observed)
    verified_activity = _journal_check(child, parent_prefix)
    later_observed = verified_activity == datetime.fromisoformat("2026-11-15T21:39:26.072+00:00")
    if last_activity < verified_activity:
        raise GuardRefused("UNKNOWN: stopped window precedes the recorded activity")
    if later_observed:
        if evidence.get("later_git_status_index_effect") != "unknown":
            raise GuardRefused("UNKNOWN: later git status index effect is not recorded")
        _check_later_local_files(worktree)
    expected_relations = _check_operator_relations(evidence, observed=observed, last_activity=last_activity)
    _check_host()
    if initial_publication:
        _read_publication(cwd, publication)
    if _read_source(CHILD_JOURNAL, 20_000_000)[1] != child_digest:
        raise GuardRefused("UNKNOWN: child journal changed during observation")
    if later_observed:
        _check_later_local_files(worktree)
    _check_fresh_relations(expected_relations)
    latest_parent, _ = _read_source(PARENT_JOURNAL, 160_000_000)
    _parent_checkpoint(latest_parent, length=evidence["parent_prefix_bytes"],
                       digest=evidence["parent_sha256"], observed=observed)
    try:
        latest = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
        _, _, latest_digest = agent_worktree._transfer_comment(
            latest, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1")
    except agent_worktree.WorktreeLifecycleError as exc:
        raise GuardRefused("UNKNOWN: operator comment recheck failed") from exc
    if latest != comment or latest_digest != digest:
        raise GuardRefused("UNKNOWN: operator comment changed during observation")
    return {"scope": ("identified #6561 journal, freshly read registered relations, host targets and initial #6562 publication"
                      if initial_publication else "identified #6561 journal, freshly read registered relations and host targets only"),
            "child_sha256": child_digest, "parent_sha256": evidence["parent_sha256"],
            "parent_prefix_bytes": evidence["parent_prefix_bytes"], "operator_digest": digest,
            "historical_push_output": "UNKNOWN", "earlier_body": "UNKNOWN", "historical_ppids": "UNKNOWN",
            "later_git_status_index_effect": "UNKNOWN",
            "unrecorded_effects": "UNKNOWN", "unregistered_delegations": "UNKNOWN",
            "arbitrary_or_future_processes": "UNKNOWN"}


def check(*, cwd: Path, issue: int, pr: int, worktree: Path, session: str, comment_id: int) -> dict[str, Any]:
    """Reconcile the original publication and bounded sources before pickup effects."""
    return _check(cwd=cwd, issue=issue, pr=pr, worktree=worktree, session=session,
                  comment_id=comment_id, initial_publication=True)


def check_runtime(*, cwd: Path, issue: int, pr: int, worktree: Path, session: str, comment_id: int) -> dict[str, Any]:
    """Re-read bounded sources only; callers must independently verify current PR and pinned authority."""
    return _check(cwd=cwd, issue=issue, pr=pr, worktree=worktree, session=session,
                  comment_id=comment_id, initial_publication=False)
