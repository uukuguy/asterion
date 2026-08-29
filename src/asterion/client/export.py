"""Canonical client-session export and explicitly authorized sharing."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from asterion.client.private import ClientPrivateValueError, ClientPrivateValueService, PrivateValueDescriptor
from asterion.client.protocol import ClientEvent, validate_client_event_stream
from asterion.control.journal import CanonicalJournal, JournalRecord
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_EVENT_MEDIA_TYPE = "application/vnd.asterion.client-events+json"


class ClientExportError(RuntimeError):
    """Raised without exposing export bodies, destinations, or host errors."""


@dataclass
class _AuthorityUse:
    lock: threading.Lock = field(default_factory=threading.Lock)
    exports: bool = False
    shares: bool = False


@dataclass(frozen=True, repr=False)
class ClientExportAuthority:
    authority_id: str
    client_id: str
    session_id: str
    authority_revision: int
    generation: int
    covered_sequence: int
    reference_ids: tuple[str, ...]
    destination_ref: str
    media_type: str
    max_bytes: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        if (
            any(_OPAQUE_ID.fullmatch(value) is None for value in (self.authority_id, self.client_id, self.session_id, self.destination_ref))
            or not _safe_positive(self.authority_revision)
            or not _safe_positive(self.generation)
            or not _safe_positive(self.covered_sequence)
            or not isinstance(self.reference_ids, tuple)
            or not is_sorted_unique_scalar_strings(list(self.reference_ids))
            or any(_OPAQUE_ID.fullmatch(reference) is None for reference in self.reference_ids)
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
            or not _safe_positive(self.max_bytes)
            or not _safe_positive(self.expires_at_ms)
        ):
            raise ClientExportError("client export authority is invalid")


@dataclass(frozen=True, repr=False)
class ClientArtifactReceipt:
    artifact_id: str
    sha256: str
    media_type: str
    size: int
    storage_ref: str

    def __post_init__(self) -> None:
        if (
            _OPAQUE_ID.fullmatch(self.artifact_id) is None
            or _DIGEST.fullmatch(self.sha256) is None
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
            or not _safe_nonnegative(self.size)
            or _OPAQUE_ID.fullmatch(self.storage_ref) is None
        ):
            raise ClientExportError("client artifact receipt is invalid")


@dataclass(frozen=True, repr=False)
class ClientShareReceipt:
    share_id: str
    artifact_id: str
    sha256: str
    media_type: str
    destination_ref: str
    share_ref: str

    def __post_init__(self) -> None:
        if (
            any(_OPAQUE_ID.fullmatch(value) is None for value in (self.share_id, self.artifact_id, self.destination_ref, self.share_ref))
            or _DIGEST.fullmatch(self.sha256) is None
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
        ):
            raise ClientExportError("client share receipt is invalid")


class ClientArtifactStore(Protocol):
    def publish(self, *, media_type: str, content: bytes) -> ClientArtifactReceipt:
        ...


class ClientShareService(Protocol):
    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority) -> ClientShareReceipt:
        ...


@dataclass(frozen=True)
class _PrivateReference:
    reference: str
    kind: str
    media_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class _ExportBinding:
    client_id: str | None
    session_id: str
    generation: int
    authority_revision: int | None


_AUTHORITY_USE_LOCK = threading.Lock()
_AuthorityIdentity = tuple[
    str, str, str, int, int, int, tuple[str, ...], str, str, int, int
]
_AUTHORITY_USES: dict[_AuthorityIdentity, _AuthorityUse] = {}
_EXPORT_BINDINGS_LOCK = threading.Lock()
_EXPORT_BINDINGS: dict[tuple[str, str, str], _ExportBinding] = {}


def export_client_session(
    events: Sequence[ClientEvent] | object,
    *,
    visibility: str = "public",
    artifacts: ClientArtifactStore,
    authority: ClientExportAuthority | None = None,
    private_values: ClientPrivateValueService | None = None,
    journal: CanonicalJournal | None = None,
    client_id: str | None = None,
) -> ClientArtifactReceipt:
    """Publish one complete, canonical client event export.

    Private material is never resolved for a public export.  The private path
    completely validates the stream, authority, and every descriptor before
    consuming its authority or reading any body.
    """

    try:
        stream = validate_client_event_stream(events)
        _validate_store(artifacts)
        if visibility == "public":
            if authority is not None:
                raise ClientExportError("client export authority is invalid")
            content = _canonical_bytes({"events": [event.to_mapping() for event in stream], "visibility": "public"})
            receipt = _publish(artifacts, content)
            _bind_export(receipt, client_id=client_id, session_id=stream[0].session_id, generation=stream[0].generation, authority_revision=None)
            _journal_export(journal, receipt, visibility="public", client_id=client_id, session_id=stream[0].session_id, generation=stream[0].generation)
            return receipt
        if visibility != "private" or not isinstance(authority, ClientExportAuthority) or not isinstance(private_values, ClientPrivateValueService):
            raise ClientExportError("client export request is invalid")
        _validate_private_authority(stream, authority, private_values, client_id)
        descriptors = _validate_private_descriptors(stream, authority, private_values)
        _consume(authority, "export")
        values = []
        for expected, descriptor in descriptors:
            body = private_values.resolve_bytes(
                expected.reference, purpose="private-export", max_bytes=authority.max_bytes,
                deadline_ms=authority.expires_at_ms, authority_revision=authority.authority_revision,
                expires_at_ms=authority.expires_at_ms,
            )
            if (
                descriptor.kind != expected.kind or descriptor.media_type != expected.media_type
                or descriptor.size != expected.size or descriptor.sha256 != expected.sha256
                or len(body) != expected.size or hashlib.sha256(body).hexdigest() != expected.sha256
            ):
                raise ClientExportError("client private export integrity is invalid")
            values.append({"body_base64": base64.b64encode(body).decode("ascii"), "kind": expected.kind, "media_type": expected.media_type, "reference": expected.reference, "sha256": expected.sha256, "size": expected.size})
        content = _canonical_bytes({"events": [event.to_mapping() for event in stream], "private_values": values, "visibility": "private"})
        if len(content) > authority.max_bytes:
            raise ClientExportError("client export size is invalid")
        receipt = _publish(artifacts, content)
        _bind_export(receipt, client_id=authority.client_id, session_id=authority.session_id, generation=authority.generation, authority_revision=authority.authority_revision)
        _journal_export(journal, receipt, visibility="private", client_id=authority.client_id, session_id=authority.session_id, generation=authority.generation)
        return receipt
    except ClientExportError:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise ClientExportError("client export is cancelled") from None
    except Exception:
        raise ClientExportError("client export is unavailable") from None


def share_client_export(
    artifact: ClientArtifactReceipt,
    *,
    authority: ClientExportAuthority,
    shares: ClientShareService | None = None,
    journal: CanonicalJournal | None = None,
) -> ClientShareReceipt:
    """Share one export through an explicitly injected host-owned service."""

    try:
        if not isinstance(artifact, ClientArtifactReceipt) or not isinstance(authority, ClientExportAuthority):
            raise ClientExportError("client share request is invalid")
        if artifact.media_type != authority.media_type:
            raise ClientExportError("client share authority is invalid")
        _validate_share_binding(artifact, authority)
        _consume(authority, "share")
        if shares is None:
            receipt = ClientShareReceipt(
                share_id=f"local-share:{artifact.artifact_id}", artifact_id=artifact.artifact_id,
                sha256=artifact.sha256, media_type=artifact.media_type,
                destination_ref=authority.destination_ref, share_ref=artifact.storage_ref,
            )
        else:
            if not callable(getattr(shares, "share", None)):
                raise ClientExportError("client share service is invalid")
            receipt = shares.share(artifact, authority=authority)
            if (
                not isinstance(receipt, ClientShareReceipt)
                or receipt.artifact_id != artifact.artifact_id or receipt.sha256 != artifact.sha256
                or receipt.media_type != artifact.media_type or receipt.destination_ref != authority.destination_ref
            ):
                raise ClientExportError("client share receipt is invalid")
        _journal_share(journal, artifact, receipt, authority)
        return receipt
    except ClientExportError:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise ClientExportError("client share is cancelled") from None
    except Exception:
        raise ClientExportError("client share is unavailable") from None


def _validate_private_authority(stream: tuple[ClientEvent, ...], authority: ClientExportAuthority, values: ClientPrivateValueService, client_id: str | None) -> None:
    if (
        authority.media_type != _EVENT_MEDIA_TYPE
        or stream[0].session_id != authority.session_id or stream[0].generation != authority.generation
        or stream[-1].sequence != authority.covered_sequence
        or (client_id is not None and client_id != authority.client_id)
        or values.access.client_id != authority.client_id or values.access.session_id != authority.session_id
        or values.access.authority_revision != authority.authority_revision
    ):
        raise ClientExportError("client export authority is invalid")
    try:
        values.validate_export_access(authority_revision=authority.authority_revision, expires_at_ms=authority.expires_at_ms)
    except ClientPrivateValueError:
        raise ClientExportError("client export authority is invalid") from None


def _validate_private_descriptors(stream: tuple[ClientEvent, ...], authority: ClientExportAuthority, values: ClientPrivateValueService) -> tuple[tuple[_PrivateReference, PrivateValueDescriptor], ...]:
    expected = _private_references(stream)
    if tuple(item.reference for item in expected) != authority.reference_ids:
        raise ClientExportError("client export references are invalid")
    descriptors: list[tuple[_PrivateReference, PrivateValueDescriptor]] = []
    aggregate = 0
    for item in expected:
        try:
            descriptor = values.describe_for_export(item.reference, max_bytes=authority.max_bytes, deadline_ms=authority.expires_at_ms, authority_revision=authority.authority_revision, expires_at_ms=authority.expires_at_ms)
        except ClientPrivateValueError:
            raise ClientExportError("client export descriptor is invalid") from None
        if descriptor.kind != item.kind or descriptor.media_type != item.media_type or descriptor.size != item.size or descriptor.sha256 != item.sha256:
            raise ClientExportError("client export descriptor is invalid")
        aggregate += descriptor.size
        if aggregate > authority.max_bytes:
            raise ClientExportError("client export size is invalid")
        descriptors.append((item, descriptor))
    return tuple(descriptors)


def _private_references(stream: tuple[ClientEvent, ...]) -> tuple[_PrivateReference, ...]:
    found: list[_PrivateReference] = []
    for event in stream:
        payload = event.payload
        if event.type == "message.available":
            found.append(_PrivateReference(cast(str, payload["content_ref"]), "message", cast(str, payload["media_type"]), cast(int, payload["size"]), cast(str, payload["sha256"])))
        elif event.type == "tool.started":
            found.append(_PrivateReference(cast(str, payload["arguments_ref"]), "tool.arguments", "application/json", cast(int, payload["size"]), cast(str, payload["sha256"])))
        elif event.type == "tool.completed":
            found.append(_PrivateReference(cast(str, payload["result_ref"]), "tool.result", cast(str, payload["media_type"]), cast(int, payload["size"]), cast(str, payload["sha256"])))
    if any(not isinstance(item.reference, str) or not isinstance(item.media_type, str) or not isinstance(item.size, int) or not isinstance(item.sha256, str) for item in found):
        raise ClientExportError("client export references are invalid")
    ordered = tuple(sorted(found, key=lambda item: item.reference))
    if len({item.reference for item in ordered}) != len(ordered):
        raise ClientExportError("client export references are invalid")
    return ordered


def _consume(authority: ClientExportAuthority, operation: str) -> None:
    identity = _authority_identity(authority)
    with _AUTHORITY_USE_LOCK:
        use = _AUTHORITY_USES.get(identity)
        if use is None:
            use = _AuthorityUse()
            _AUTHORITY_USES[identity] = use
    with use.lock:
        if operation == "export":
            if use.exports:
                raise ClientExportError("client export authority is consumed")
            use.exports = True
        elif operation == "share":
            if use.shares:
                raise ClientExportError("client share authority is consumed")
            use.shares = True
        else:
            raise ClientExportError("client export authority is invalid")


def _authority_identity(authority: ClientExportAuthority) -> _AuthorityIdentity:
    """Return the complete validated authority witness used for one-use state."""

    return (
        authority.authority_id, authority.client_id, authority.session_id,
        authority.authority_revision, authority.generation,
        authority.covered_sequence, authority.reference_ids,
        authority.destination_ref, authority.media_type, authority.max_bytes,
        authority.expires_at_ms,
    )


def _validate_store(artifacts: object) -> None:
    if not callable(getattr(artifacts, "publish", None)):
        raise ClientExportError("client artifact store is invalid")


def _publish(artifacts: ClientArtifactStore, content: bytes) -> ClientArtifactReceipt:
    receipt = artifacts.publish(media_type=_EVENT_MEDIA_TYPE, content=content)
    if not isinstance(receipt, ClientArtifactReceipt) or receipt.media_type != _EVENT_MEDIA_TYPE or receipt.size != len(content) or receipt.sha256 != hashlib.sha256(content).hexdigest():
        raise ClientExportError("client artifact receipt is invalid")
    return receipt


def _bind_export(
    artifact: ClientArtifactReceipt,
    *,
    client_id: str | None,
    session_id: str,
    generation: int,
    authority_revision: int | None,
) -> None:
    if client_id is not None and _OPAQUE_ID.fullmatch(client_id) is None:
        raise ClientExportError("client export identity is invalid")
    binding = _ExportBinding(client_id, session_id, generation, authority_revision)
    key = (artifact.artifact_id, artifact.sha256, artifact.storage_ref)
    with _EXPORT_BINDINGS_LOCK:
        previous = _EXPORT_BINDINGS.get(key)
        if previous is not None and previous != binding:
            raise ClientExportError("client export receipt conflicts")
        _EXPORT_BINDINGS[key] = binding


def _validate_share_binding(
    artifact: ClientArtifactReceipt, authority: ClientExportAuthority
) -> None:
    key = (artifact.artifact_id, artifact.sha256, artifact.storage_ref)
    with _EXPORT_BINDINGS_LOCK:
        binding = _EXPORT_BINDINGS.get(key)
    if (
        binding is None
        or binding.session_id != authority.session_id
        or binding.generation != authority.generation
        or binding.client_id != authority.client_id
        or (binding.authority_revision is not None and binding.authority_revision != authority.authority_revision)
    ):
        raise ClientExportError("client share authority is invalid")


def _journal_export(journal: CanonicalJournal | None, artifact: ClientArtifactReceipt, *, visibility: str, client_id: str | None, session_id: str, generation: int) -> None:
    if journal is None:
        return
    if not callable(getattr(journal, "append", None)) or not isinstance(client_id, str):
        raise ClientExportError("client export journal is invalid")
    journal.append(journal.position, JournalRecord.client_export_receipted(client_id=client_id, session_id=session_id, generation=generation, artifact=artifact, visibility=visibility))


def _journal_share(journal: CanonicalJournal | None, artifact: ClientArtifactReceipt, receipt: ClientShareReceipt, authority: ClientExportAuthority) -> None:
    if journal is None:
        return
    if not callable(getattr(journal, "append", None)):
        raise ClientExportError("client share journal is invalid")
    journal.append(journal.position, JournalRecord.client_share_receipted(client_id=authority.client_id, session_id=authority.session_id, generation=authority.generation, artifact=artifact, share=receipt))


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple) or isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _safe_positive(value: object) -> bool:
    return type(value) is int and 1 <= value <= _MAX_SAFE_INTEGER


def _safe_nonnegative(value: object) -> bool:
    return type(value) is int and 0 <= value <= _MAX_SAFE_INTEGER
