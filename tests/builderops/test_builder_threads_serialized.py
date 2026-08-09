from __future__ import annotations

import pytest

from app.builderops.builder_threads_serialized import (
    BuilderThreadClient,
    InProcessWriterEndpoint,
    SerializedThreadWriter,
    ThreadMutation,
    WriterAcknowledgementLost,
    WriterUnavailableError,
)


class _AcknowledgementDroppingEndpoint:
    """Simulates one lost response after the designated writer accepted it."""

    def __init__(self, delegate: InProcessWriterEndpoint) -> None:
        self._delegate = delegate
        self._drop_next_ack = True

    def mutate(self, command: object) -> object:
        result = self._delegate.mutate(command)
        if self._drop_next_ack:
            self._drop_next_ack = False
            raise WriterAcknowledgementLost("acknowledgement lost")
        return result

    def read_thread(self, thread_id: str) -> object:
        return self._delegate.read_thread(thread_id)

    def inbox(self, recipient: str, *, limit: int) -> object:
        return self._delegate.inbox(recipient, limit=limit)


class _UnavailableEndpoint:
    def mutate(self, command: object) -> object:
        raise WriterUnavailableError("serialized writer unavailable")

    def read_thread(self, thread_id: str) -> object:
        raise WriterUnavailableError("serialized writer unavailable")

    def inbox(self, recipient: str, *, limit: int) -> object:
        raise WriterUnavailableError("serialized writer unavailable")


def _writer() -> SerializedThreadWriter:
    return SerializedThreadWriter(vault_id="builderops-mac-mini")


def test_serialized_writer_round_trip() -> None:
    writer = _writer()
    codex = BuilderThreadClient(InProcessWriterEndpoint(writer), client_id="codex:desktop")
    claude = BuilderThreadClient(InProcessWriterEndpoint(writer), client_id="claude:mac")

    created = codex.create(
        request_id="create-4708",
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Confirm serialized writer boundary",
        content="Please confirm the writer endpoint contract.",
        source_refs=("github:4708",),
    )
    assert created.thread.privacy_class == "shared_non_sensitive"
    assert created.thread.vault_id == "builderops-mac-mini"
    assert created.thread.reply_expected is True
    assert created.thread.entries[0].actor == "codex:desktop"
    assert created.thread.entries[0].recipient == "claude:mac"
    assert created.thread.entries[0].source_refs == ("github:4708",)

    assert claude.read(created.thread.thread_id) == created.thread
    replied = claude.reply(
        request_id="reply-4708",
        thread_id=created.thread.thread_id,
        actor="claude:mac",
        recipient="codex:desktop",
        content="Confirmed.",
        source_refs=("github:4708",),
    )
    closed = codex.close(
        request_id="close-4708",
        thread_id=created.thread.thread_id,
        actor="codex:desktop",
        reason="Question answered.",
    )
    archived = codex.archive(
        request_id="archive-4708",
        thread_id=created.thread.thread_id,
        actor="codex:desktop",
    )

    assert replied.thread.entries[-1].kind == "reply"
    assert closed.thread.state == "closed"
    assert archived.thread.state == "archived"


def test_clients_cannot_bypass_serialized_writer() -> None:
    writer = _writer()
    endpoint = InProcessWriterEndpoint(writer)
    client = BuilderThreadClient(endpoint, client_id="codex:desktop")

    assert not hasattr(client, "artifact_root")
    assert not hasattr(client, "write_thread")
    assert not hasattr(client, "mutate")

    client.create(
        request_id="writer-only-4708",
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Writer only",
        content="Mutations must reach the designated writer.",
        source_refs=("github:4708",),
    )
    assert endpoint.mutation_count == 1
    assert writer.accepted_mutation_count == 1


def test_create_refuses_an_existing_durable_capture() -> None:
    client = BuilderThreadClient(InProcessWriterEndpoint(_writer()), client_id="codex:desktop")
    create = dict(
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Already represented",
        content="One durable question is enough.",
        source_refs=("github:4708",),
    )
    client.create(request_id="first-capture-4708", **create)

    with pytest.raises(ValueError, match="capture already has a durable"):
        client.create(request_id="duplicate-capture-4708", **create)


def test_capture_requires_named_recipient_and_shared_non_sensitive_provenance() -> None:
    client = BuilderThreadClient(InProcessWriterEndpoint(_writer()), client_id="codex:desktop")

    with pytest.raises(ValueError, match="named identity"):
        client.create(
            request_id="privacy-recipient-4708",
            actor="codex:desktop",
            recipient="unaddressed",
            subject="Missing recipient",
            content="This must not become a monologic note.",
            source_refs=("github:4708",),
        )
    with pytest.raises(ValueError, match="shared_non_sensitive"):
        client.create(
            request_id="privacy-content-4708",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Sensitive content",
            content="Bearer token must not be captured.",
            source_refs=("github:4708",),
        )
    with pytest.raises(ValueError, match="typed bounded provenance"):
        client.create(
            request_id="privacy-provenance-4708",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Untyped source",
            content="Source references must retain their type.",
            source_refs=("4708",),
        )
    with pytest.raises(ValueError, match="shared_non_sensitive"):
        client.create(
            request_id="privacy-code-4708",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Code must not be captured",
            content="def deploy():\n    return deploy_unreviewed_change()",
            source_refs=("github:4708",),
        )
    with pytest.raises(ValueError, match="shared_non_sensitive"):
        client.create(
            request_id="privacy-patch-4708",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Patch must not be captured",
            content="diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-old\n+new",
            source_refs=("github:4708",),
        )


def test_close_requires_the_named_recipient_reply_and_keeps_unanswered_thread_discoverable() -> None:
    client = BuilderThreadClient(InProcessWriterEndpoint(_writer()), client_id="codex:desktop")
    created = client.create(
        request_id="unanswered-create-4708",
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Awaiting answer",
        content="Please reply before this thread can close.",
        source_refs=("github:4708",),
    )

    with pytest.raises(ValueError, match="requires a reply from the named recipient"):
        client.close(
            request_id="unanswered-close-4708",
            thread_id=created.thread.thread_id,
            actor="codex:desktop",
            reason="Attempted premature closure.",
        )

    assert client.inbox("claude:mac", limit=10).threads[0].thread_id == created.thread.thread_id


def test_writer_rejects_unknown_mutation_kind_without_state_change() -> None:
    writer = _writer()

    with pytest.raises(ValueError, match="unsupported thread mutation"):
        writer.mutate(
            ThreadMutation(
                request_id="unknown-kind-4708",
                kind="unknown",  # type: ignore[arg-type]
                actor="codex:desktop",
            )
        )

    assert writer.accepted_mutation_count == 0


def test_serialized_request_id_retry_converges() -> None:
    writer = _writer()
    endpoint = InProcessWriterEndpoint(writer)
    client = BuilderThreadClient(
        _AcknowledgementDroppingEndpoint(endpoint), client_id="codex:desktop"
    )
    create = dict(
        request_id="retry-4708",
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Retry safely",
        content="The reply may be retried after acknowledgement loss.",
        source_refs=("github:4708",),
    )

    with pytest.raises(WriterAcknowledgementLost, match="acknowledgement lost"):
        client.create(**create)

    retrying_client = BuilderThreadClient(endpoint, client_id="codex:desktop")
    retried = retrying_client.create(**create)
    assert retried.replayed is True
    assert writer.accepted_mutation_count == 1

    with pytest.raises(ValueError, match="request id reuse conflicts"):
        retrying_client.create(**{**create, "content": "Changed request under same ID."})


def test_two_client_round_trip_and_writer_unavailable_state() -> None:
    writer = _writer()
    mac = BuilderThreadClient(InProcessWriterEndpoint(writer), client_id="codex:mac")
    mac_mini = BuilderThreadClient(InProcessWriterEndpoint(writer), client_id="claude:mac-mini")
    created = mac.create(
        request_id="mac-create-4708",
        actor="codex:mac",
        recipient="claude:mac-mini",
        subject="Mac to Mac mini",
        content="A single writer owns the mutation boundary.",
        source_refs=("github:4708",),
    )

    assert mac_mini.read(created.thread.thread_id).thread_id == created.thread.thread_id
    assert mac_mini.inbox("claude:mac-mini", limit=10).threads[0].thread_id == created.thread.thread_id

    unavailable = BuilderThreadClient(_UnavailableEndpoint(), client_id="codex:mac")
    with pytest.raises(WriterUnavailableError, match="serialized writer unavailable"):
        unavailable.inbox("claude:mac-mini", limit=10)
