#!/usr/bin/env python3
"""One-shot, bounded TypeSafe System One calls for local development agents."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from threading import Thread
from typing import Any, Sequence
import urllib.request

API_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
SECRET_NAME = "typesafe.api-key"
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 16 * 1024
MAX_QUESTIONS = 16
MAX_QUESTION_ID_LENGTH = 128
REQUEST_TIMEOUT_SECONDS = 25
SECRET_TIMEOUT_SECONDS = 15
MAX_SECRET_BYTES = 4096
SECRET_HELPER = Path.home() / ".local" / "bin" / "ygg-secret"


class InvalidRequest(Exception):
    """The stdin payload is not an allowed bounded System One request."""


class CredentialUnavailable(Exception):
    """The local secret helper could not return the configured API key."""


class ProviderFailure(Exception):
    """One provider request failed or ended ambiguously."""


class InvalidResponse(Exception):
    """The provider returned an unrecognized or mismatched answer."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON number: {value}")


def _decode_json(raw: bytes, *, limit: int, error_type: type[Exception]) -> Any:
    if len(raw) > limit:
        raise error_type()
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise error_type() from exc


def _json_object_or_array_or_string(value: Any) -> bool:
    return isinstance(value, (str, dict, list))


def _validate_question(question: Any) -> None:
    if not isinstance(question, dict):
        raise InvalidRequest()
    if set(question) - {"type", "instructions", "criteria"}:
        raise InvalidRequest()

    kind = question.get("type")
    instructions = question.get("instructions")
    if not isinstance(kind, str) or kind not in {"noul", "choice", "score"}:
        raise InvalidRequest()
    if not _json_object_or_array_or_string(instructions):
        raise InvalidRequest()
    if isinstance(instructions, str) and not instructions.strip():
        raise InvalidRequest()

    criteria = question.get("criteria")
    if kind == "noul":
        if "criteria" not in question:
            return
        if not isinstance(criteria, dict) or set(criteria) - {"true", "false"}:
            raise InvalidRequest()
        if not criteria:
            raise InvalidRequest()
        if not all(_json_object_or_array_or_string(value) for value in criteria.values()):
            raise InvalidRequest()
        return

    if kind == "choice":
        if not isinstance(criteria, dict) or not 1 <= len(criteria) <= 64:
            raise InvalidRequest()
        if not all(isinstance(label, str) and label for label in criteria):
            raise InvalidRequest()
        if not all(
            value is None or _json_object_or_array_or_string(value)
            for value in criteria.values()
        ):
            raise InvalidRequest()
        return

    if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
        raise InvalidRequest()
    if (
        not all(isinstance(value, str) and value.strip() for value in criteria)
        or len(set(criteria)) != len(criteria)
    ):
        raise InvalidRequest()


def _encode_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise InvalidRequest() from exc


def build_provider_request(raw: bytes) -> tuple[dict[str, Any], bytes]:
    supplied = _decode_json(raw, limit=MAX_REQUEST_BYTES, error_type=InvalidRequest)
    if not isinstance(supplied, dict) or set(supplied) != {"state", "questions"}:
        raise InvalidRequest()
    state = supplied["state"]
    questions = supplied["questions"]
    if not _json_object_or_array_or_string(state):
        raise InvalidRequest()
    if not isinstance(questions, dict) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise InvalidRequest()
    for question_id, question in questions.items():
        if (
            not isinstance(question_id, str)
            or not question_id
            or len(question_id) > MAX_QUESTION_ID_LENGTH
        ):
            raise InvalidRequest()
        _validate_question(question)

    payload = {"state": state, "model": MODEL, "questions": questions}
    encoded = _encode_json(payload)
    if len(encoded) > MAX_REQUEST_BYTES:
        raise InvalidRequest()
    return payload, encoded


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_distribution(value: Any, expected_keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise InvalidResponse()
    if not all(_finite_number(probability) and 0 <= probability <= 1 for probability in value.values()):
        raise InvalidResponse()
    if abs(sum(value.values()) - 1.0) > 0.01:
        raise InvalidResponse()


def validate_provider_response(raw: bytes, questions: dict[str, Any]) -> dict[str, Any]:
    response = _decode_json(raw, limit=MAX_RESPONSE_BYTES, error_type=InvalidResponse)
    if not isinstance(response, dict) or set(response) != {"model", "answers", "usage"}:
        raise InvalidResponse()

    model = response.get("model")
    answers = response.get("answers")
    usage = response.get("usage")
    if not isinstance(model, str) or not model:
        raise InvalidResponse()
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise InvalidResponse()
    if (
        not isinstance(usage, dict)
        or set(usage) != {"input_tokens", "output_tokens"}
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in usage.values()
        )
    ):
        raise InvalidResponse()

    for question_id, question in questions.items():
        answer = answers[question_id]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise InvalidResponse()

        if kind == "noul":
            if set(answer) != {"type", "noul"} or not _finite_number(answer["noul"]):
                raise InvalidResponse()
            if not 0 <= answer["noul"] <= 1:
                raise InvalidResponse()
        elif kind == "choice":
            options = set(question["criteria"])
            if set(answer) != {"type", "choice", "probabilities", "confidence"}:
                raise InvalidResponse()
            if not isinstance(answer["choice"], str) or answer["choice"] not in options:
                raise InvalidResponse()
            _validate_distribution(answer["probabilities"], options)
            if not _finite_number(answer["confidence"]) or not 0 <= answer["confidence"] <= 1:
                raise InvalidResponse()
        else:
            levels = len(question["criteria"])
            expected_keys = {str(index) for index in range(levels)}
            expected_legend = {
                str(index): label for index, label in enumerate(question["criteria"])
            }
            if set(answer) != {
                "type",
                "score",
                "legend",
                "probabilities",
                "confidence",
            }:
                raise InvalidResponse()
            if (
                not _finite_number(answer["score"])
                or not 0 <= answer["score"] <= levels - 1
                or not isinstance(answer["legend"], dict)
                or set(answer["legend"]) != expected_keys
                or answer["legend"] != expected_legend
            ):
                raise InvalidResponse()
            _validate_distribution(answer["probabilities"], expected_keys)
            if not _finite_number(answer["confidence"]) or not 0 <= answer["confidence"] <= 1:
                raise InvalidResponse()

    # The provider controls `model` in its response. Report our fixed request alias
    # instead so arbitrary provider text cannot be reflected to agent stdout.
    return {"model": MODEL, "answers": answers, "usage": usage}


def _stop_child(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is not None:
            return
        process.terminate()
    except OSError:
        pass

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        pass


def _read_api_key() -> str:
    process: subprocess.Popen[bytes] | None = None
    completed = False
    try:
        process = subprocess.Popen(
            [str(SECRET_HELPER), SECRET_NAME],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                "HOME": str(Path.home()),
                "PATH": os.defpath,
                "LANG": "C",
            },
            close_fds=True,
        )
        if process.stdout is None:
            raise CredentialUnavailable()
        os.set_blocking(process.stdout.fileno(), False)
        deadline = time.monotonic() + SECRET_TIMEOUT_SECONDS
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise CredentialUnavailable()
                chunk = os.read(
                    process.stdout.fileno(),
                    min(4096, MAX_SECRET_BYTES + 1 - len(output)),
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > MAX_SECRET_BYTES:
                    raise CredentialUnavailable()
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0 or not output:
            raise CredentialUnavailable()
        value = output.decode("utf-8")
        if not value or value.strip() != value or any(char in value for char in "\r\n"):
            raise CredentialUnavailable()
        completed = True
        return value
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, CredentialUnavailable):
        raise CredentialUnavailable() from None
    finally:
        if process is not None:
            if not completed:
                _stop_child(process)
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _http_request_once(request_body: bytes, api_key: str) -> bytes:
    request = urllib.request.Request(
        API_ENDPOINT,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler,
        )
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                raise ProviderFailure()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        raise ProviderFailure() from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProviderFailure()
    return raw


_MAX_TRANSPORT_INPUT_BYTES = 4 + MAX_REQUEST_BYTES + MAX_SECRET_BYTES
_TRANSPORT_WORKER_CODE = (
    "import runpy,sys; "
    "f=runpy.run_path(sys.argv[1],run_name='_jev_transport')['_transport_worker']; "
    "sys.exit(f(int(sys.argv[2])))"
)


def _transport_worker(lifeline_fd: int) -> int:
    """Private worker: stop if the caller exits, even without Python cleanup."""
    def stop_on_caller_exit() -> None:
        try:
            os.read(lifeline_fd, 1)
        finally:
            # EOF means the caller's only write handle is gone. Stop blocking
            # native DNS/SSL too; no Python exception needs to reach that code.
            os._exit(1)

    Thread(target=stop_on_caller_exit, name="jev-caller-lifeline", daemon=True).start()
    try:
        wire = sys.stdin.buffer.read(_MAX_TRANSPORT_INPUT_BYTES + 1)
        if len(wire) > _MAX_TRANSPORT_INPUT_BYTES or len(wire) < 5:
            raise ProviderFailure()
        body_size = int.from_bytes(wire[:4], "big")
        if not 1 <= body_size <= MAX_REQUEST_BYTES or len(wire) <= 4 + body_size:
            raise ProviderFailure()
        key_bytes = wire[4 + body_size:]
        if len(key_bytes) > MAX_SECRET_BYTES:
            raise ProviderFailure()
        raw = _http_request_once(wire[4:4 + body_size], key_bytes.decode("utf-8"))
        sys.stdout.buffer.write(raw)
        return 0
    except Exception:
        # No provider errors, input material or credentials leave this worker.
        return 1


def send_once(request_body: bytes, api_key: str) -> bytes:
    """Bound DNS, connection, headers and body with one monotonic deadline.

    A fresh isolated process makes even blocking native DNS/SSL calls stoppable.
    The public CLI stays argument-free; the private bootstrap contains no key.
    """
    process: subprocess.Popen[bytes] | None = None
    lifeline_read: int | None = None
    lifeline_write: int | None = None
    completed = False
    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    try:
        key_bytes = api_key.encode("utf-8")
        if not 1 <= len(request_body) <= MAX_REQUEST_BYTES or not 1 <= len(key_bytes) <= MAX_SECRET_BYTES:
            raise ProviderFailure()
        wire = len(request_body).to_bytes(4, "big") + request_body + key_bytes
        lifeline_read, lifeline_write = os.pipe()
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", _TRANSPORT_WORKER_CODE, str(Path(__file__).resolve()), str(lifeline_read)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"HOME": str(Path.home()), "PATH": os.defpath, "LANG": "C"},
            close_fds=True,
            pass_fds=(lifeline_read,),
        )
        os.close(lifeline_read)
        lifeline_read = None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFailure()
        raw, _ = process.communicate(input=wire, timeout=remaining)
        if process.returncode != 0 or len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderFailure()
        if time.monotonic() > deadline:
            raise ProviderFailure()
        completed = True
        return raw
    except Exception:
        raise ProviderFailure() from None
    finally:
        for fd in (lifeline_read, lifeline_write):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if process is not None:
            if not completed:
                _stop_child(process)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("jev-direct accepts a JSON request on stdin and no command arguments.", file=sys.stderr)
        return 2

    try:
        raw_request = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        payload, encoded_request = build_provider_request(raw_request)
    except (OSError, InvalidRequest):
        print("Invalid or oversized Jev request.", file=sys.stderr)
        return 2

    try:
        api_key = _read_api_key()
    except CredentialUnavailable:
        print("Jev credential unavailable.", file=sys.stderr)
        return 3

    try:
        try:
            raw_response = send_once(encoded_request, api_key)
        finally:
            del api_key
    except ProviderFailure:
        print("Jev request failed; no retry was attempted.", file=sys.stderr)
        return 4

    try:
        result = validate_provider_response(raw_response, payload["questions"])
        output = _encode_json(result) + b"\n"
    except (InvalidResponse, InvalidRequest):
        print("Jev response failed local validation.", file=sys.stderr)
        return 5

    try:
        sys.stdout.buffer.write(output)
    except OSError:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
