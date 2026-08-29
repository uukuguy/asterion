from __future__ import annotations

import asyncio
import hashlib
import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from asterion.client import ClientEvent
from asterion.client.export import (
    ClientArtifactReceipt,
    ClientExportAuthority,
    ClientExportError,
    ClientShareReceipt,
    export_client_session,
    share_client_export,
)
from asterion.client.private import (
    ClientAccess,
    ClientPrivateValueService,
    PrivateValueDescriptor,
)
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal


def _event(event_id: str, sequence: int, event_type: str, payload: Mapping[str, object]) -> ClientEvent:
    return ClientEvent(
        protocol="asterion.agent-client/v1", event_id=event_id, session_id="session-1",
        generation=1, sequence=sequence, emitted_at="2026-08-28T12:00:00Z",
        type=event_type, payload=payload,
    )


def _events() -> tuple[ClientEvent, ...]:
    body = b"SENTINEL_BODY"
    return (
        _event("event-1", 1, "message.available", {
            "content_ref": "message-body-1", "media_type": "text/plain", "message_id": "message-1",
            "role": "assistant", "sha256": hashlib.sha256(body).hexdigest(), "size": len(body),
        }),
        _event("event-2", 2, "session.terminal", {"reason_code": "completed", "status": "completed"}),
    )


class _Store:
    next_id = 0

    def __init__(self) -> None:
        self.contents: list[bytes] = []
        type(self).next_id += 1
        self.artifact_id = f"artifact-{type(self).next_id}"

    def publish(self, *, media_type: str, content: bytes) -> ClientArtifactReceipt:
        self.contents.append(content)
        return ClientArtifactReceipt(
            artifact_id=self.artifact_id, sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type, size=len(content), storage_ref=f"local-export-{self.artifact_id}",
        )


class _Backend:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.body = b"SENTINEL_BODY"

    def describe(self, reference: str) -> PrivateValueDescriptor:
        return PrivateValueDescriptor(reference, "message", "text/plain", len(self.body), hashlib.sha256(self.body).hexdigest())

    def read(self, reference: str, *, max_bytes: int) -> bytes:
        self.reads.append(reference)
        return self.body


def _authority(authority_id: str = "export-authority-1") -> ClientExportAuthority:
    return ClientExportAuthority(
        authority_id=authority_id, client_id="client-1", session_id="session-1",
        authority_revision=1, generation=1, covered_sequence=2, reference_ids=("message-body-1",),
        destination_ref="destination-1", media_type="application/vnd.asterion.client-events+json",
        max_bytes=4096, expires_at_ms=10,
    )


def _reconstructed(authority: ClientExportAuthority) -> ClientExportAuthority:
    return ClientExportAuthority(
        authority_id=authority.authority_id, client_id=authority.client_id,
        session_id=authority.session_id, authority_revision=authority.authority_revision,
        generation=authority.generation, covered_sequence=authority.covered_sequence,
        reference_ids=authority.reference_ids, destination_ref=authority.destination_ref,
        media_type=authority.media_type, max_bytes=authority.max_bytes,
        expires_at_ms=authority.expires_at_ms,
    )


def _private_values(backend: _Backend) -> ClientPrivateValueService:
    return ClientPrivateValueService(
        access=ClientAccess("client-1", "session-1", 1, ("private-export",)), backend=backend,
        clock_ms=lambda: 1, authority_revision_source=lambda: 1,
    )


class _Shares:
    def __init__(self) -> None:
        self.calls = 0

    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority) -> ClientShareReceipt:
        self.calls += 1
        return ClientShareReceipt(
            share_id="share-1", artifact_id=artifact.artifact_id, sha256=artifact.sha256,
            media_type=artifact.media_type, destination_ref=authority.destination_ref, share_ref="share-ref-1",
        )


class TestClientExportShare(unittest.TestCase):
    def test_public_export_never_resolves_private_references(self) -> None:
        store = _Store()
        backend = _Backend()

        receipt = export_client_session(_events(), visibility="public", artifacts=store, private_values=_private_values(backend))

        self.assertEqual(backend.reads, [])
        self.assertEqual(receipt.media_type, "application/vnd.asterion.client-events+json")
        self.assertNotIn("SENTINEL_BODY", repr(receipt))
        self.assertNotIn(b"SENTINEL_BODY", store.contents[0])

    def test_private_export_authority_is_exact_and_one_use(self) -> None:
        store = _Store()
        authority = _authority("private-authority-1")
        backend = _Backend()

        receipt = export_client_session(_events(), visibility="private", artifacts=store, authority=authority, private_values=_private_values(backend))

        self.assertEqual(backend.reads, ["message-body-1"])
        self.assertNotIn("SENTINEL_BODY", repr(receipt))
        with self.assertRaises(ClientExportError):
            export_client_session(_events(), visibility="private", artifacts=store, authority=_reconstructed(authority), private_values=_private_values(backend))

    def test_private_export_rejects_before_a_body_read_when_any_descriptor_or_limit_is_invalid(self) -> None:
        backend = _Backend()
        authority = _authority("limit-authority-1")
        bad = ClientExportAuthority(
            authority_id=authority.authority_id, client_id=authority.client_id,
            session_id=authority.session_id, authority_revision=authority.authority_revision,
            generation=authority.generation, covered_sequence=authority.covered_sequence,
            reference_ids=authority.reference_ids, destination_ref=authority.destination_ref,
            media_type=authority.media_type, max_bytes=1, expires_at_ms=authority.expires_at_ms,
        )

        with self.assertRaises(ClientExportError):
            export_client_session(_events(), visibility="private", artifacts=_Store(), authority=bad, private_values=_private_values(backend))

        self.assertEqual(backend.reads, [])

    def test_share_is_receipted_once_and_no_service_returns_the_local_opaque_reference(self) -> None:
        store = _Store()
        artifact = export_client_session(_events(), visibility="public", artifacts=store, client_id="client-1")
        authority = _authority("share-authority-1")

        local = share_client_export(artifact, authority=authority)
        self.assertEqual(local.share_ref, artifact.storage_ref)
        shares = _Shares()
        with self.assertRaises(ClientExportError):
            share_client_export(artifact, authority=_reconstructed(authority), shares=shares)
        self.assertEqual(shares.calls, 0)

    def test_reconstructed_authority_export_is_consumed_once_across_threads(self) -> None:
        authority = _authority("concurrent-export-authority")
        backend = _Backend()
        store = _Store()

        def invoke() -> object:
            return export_client_session(
                _events(), visibility="private", artifacts=store,
                authority=_reconstructed(authority), private_values=_private_values(backend),
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self._capture(invoke), range(8)))

        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)
        self.assertEqual(backend.reads, ["message-body-1"])
        self.assertEqual(len(store.contents), 1)

    def test_reconstructed_authority_share_is_consumed_once_before_remote_effect(self) -> None:
        artifact = export_client_session(_events(), visibility="public", artifacts=_Store(), client_id="client-1")
        authority = _authority("concurrent-share-authority")
        shares = _Shares()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self._capture(lambda: share_client_export(artifact, authority=_reconstructed(authority), shares=shares)), range(8)))

        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)
        self.assertEqual(shares.calls, 1)

    def test_distinct_authorities_remain_independent_and_failed_share_is_consumed(self) -> None:
        artifact = export_client_session(_events(), visibility="public", artifacts=_Store(), client_id="client-1")
        first = _authority("independent-authority-1")
        second = _authority("independent-authority-2")
        shares = _Shares()

        share_client_export(artifact, authority=first, shares=shares)
        share_client_export(artifact, authority=second, shares=shares)
        self.assertEqual(shares.calls, 2)
        failed = _FailingShares()
        consumed = _authority("failed-share-authority")
        with self.assertRaises(ClientExportError):
            share_client_export(artifact, authority=consumed, shares=failed)
        with self.assertRaises(ClientExportError):
            share_client_export(artifact, authority=_reconstructed(consumed), shares=failed)
        self.assertEqual(failed.calls, 1)
        cancelled = _CancelledShares()
        cancelled_authority = _authority("cancelled-share-authority")
        with self.assertRaises(ClientExportError):
            share_client_export(artifact, authority=cancelled_authority, shares=cancelled)
        with self.assertRaises(ClientExportError):
            share_client_export(artifact, authority=_reconstructed(cancelled_authority), shares=cancelled)
        self.assertEqual(cancelled.calls, 1)

    @staticmethod
    def _capture(operation: object) -> object:
        assert callable(operation)
        try:
            return operation()
        except Exception as error:
            return error

    def test_receipts_are_journaled_without_private_bodies(self) -> None:
        journal = MemoryCanonicalJournal("session-1")
        first = journal.append(0, __import__("asterion.control.journal", fromlist=["JournalRecord"]).JournalRecord.system_bound(system_id="research.system", system_version="1.0.0"))
        journal.append(first.position, __import__("asterion.control.journal", fromlist=["JournalRecord"]).JournalRecord.authority_bound(authority_id="authority-1", authority_revision=1))
        receipt = export_client_session(_events(), visibility="public", artifacts=_Store(), journal=journal, client_id="client-1")

        record = journal.replay(JournalCursor(0))[-1].record
        self.assertEqual(record.kind, "client.export.receipted")
        self.assertEqual(record.payload["artifact_id"], receipt.artifact_id)
        self.assertNotIn("SENTINEL_BODY", repr(record))


class _FailingShares:
    def __init__(self) -> None:
        self.calls = 0

    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority) -> ClientShareReceipt:
        del artifact, authority
        self.calls += 1
        raise RuntimeError("SENTINEL_HOST_ERROR")


class _CancelledShares:
    def __init__(self) -> None:
        self.calls = 0

    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority) -> ClientShareReceipt:
        del artifact, authority
        self.calls += 1
        raise asyncio.CancelledError
